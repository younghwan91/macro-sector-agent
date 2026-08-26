"""DuckDB 스토어 읽기 계층.

**이 모듈의 존재 이유는 조용한 절단을 구조적으로 막는 것이다** (`CLAUDE.md` §2).
그래서 모든 조회 함수는 기대 범위를 인자로 받고, 못 미치면 `ShortRead` 를 던진다.
빈 DataFrame 을 반환하고 호출자가 알아서 처리하기를 기대하지 않는다.

## 실측 스키마 — `docs/08-data-contract.md` §2 와 다른 지점

M1 에서 `~/data/us_micro.duckdb` 를 실측한 결과, 문서가 기술한 Sharadar 원본 테이블 구조와
적재된 스토어의 구조가 여러 곳에서 다르다. 코드는 **실측에 맞춘다.**

- 별도의 `daily` 테이블은 **없다.** `DAILY` 의 `marketcap`·`ev` 는 `prices` 테이블에
  `mcap`·`ev` 컬럼으로 병합돼 있다.
- **단위는 적재 시점에 이미 달러로 환산돼 있다.** 실측: 원본 `daily.csv` 의
  `AAPL,2026-08-12` `marketcap=4411090.9`(백만 달러), 스토어 `prices.mcap=4.4110909e12`(달러).
  즉 배수 10⁶ 가 이미 적용됐다 — **여기서 다시 곱하면 그때 10⁶배 왜곡이 생긴다.**
  이 사실을 코드 한 곳(=`MCAP_UNIT`)에만 두고 다른 곳에서는 환산하지 않는다.
- `prices.close` 는 **분할·배당 조정 종가**(원본 `closeadj`)이고, `closeunadj` 가 원가다.
  실측: NVDA 2024-06-06 `close=120.793` / `closeunadj=1209.98` (2024-06-10 10:1 분할).
- `DAILY` 의 `pe`·`pb`·`ps`·`evebitda`·`evebit` 은 **적재되지 않았다.** 필요하면 벌크에서
  다시 받거나 `fundamentals` 로 계산해야 한다.
- `tickers.is_delisted` — 문서는 `isdelisted` 로 적었다. 실제 컬럼명은 `is_delisted`.
- `tickers` 에 `sicsector`·`firstpricedate`·`lastpricedate` 는 **없다.**
- `fundamentals.dimension` 은 `ARQ` 한 종류뿐이다 — **`ART` 는 적재돼 있지 않다.**
  문서 §2 가 예고한 "`assetsavg`·`equityavg` 는 ARQ 에서 전부 null" 은 실측에서
  그대로 확인됐다 (`invcapavg` 포함 셋 다 655,000행 전부 null → 직접 계산해야 한다).
- `prices.short_interest` 는 **컬럼만 있고 100% null** 이다. 있는 줄 알고 쓰면
  L4 토크 축이 조용히 빈다.
- `estimates` 테이블은 0행이다 — 컨센서스는 이 스토어에 없다.
- ETF 가격(`SFP`)은 스토어에 **없다.** `prices` 에 있는 ETF 는 `SPY` 하나뿐이다.
  나머지는 벌크 원본 `funds.csv.zip` 에서 읽는다 → `etf_prices()`.
"""

from __future__ import annotations

import hashlib
import logging
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from msa.config import paths
from msa.errors import MsaError

log = logging.getLogger(__name__)

# 적재기가 원본 DAILY(백만 달러)에 이미 곱해 둔 배수. 스토어 값은 **달러**다.
# 여기 상수는 "다시 곱하지 마라" 는 사실을 코드로 붙잡아 두기 위한 것이며,
# 조회 결과에 적용되지 않는다. 적용하는 순간 10^6 배 왜곡이 생긴다.
MCAP_UNIT_ALREADY_APPLIED = 1_000_000

#: 스토어에 실제로 존재하는 테이블 (M1 실측).
KNOWN_TABLES = (
    "actions",
    "estimates",
    "fundamentals",
    "insiders",
    "institutions",
    "prices",
    "sp500",
    "tickers",
)

#: 실측 결과 0행인 테이블. `table_stats()` 가 이것을 "비었음" 이 아니라 "미적재" 로 보고한다.
EMPTY_TABLES = ("estimates",)

#: `Store.prices()` 가 기본으로 돌려주는 12개 컬럼 (순서 포함).
PRICE_COLUMNS: tuple[str, ...] = (
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "closeunadj",
    "volume",
    "dividends",
    "mcap",
    "ev",
    "short_interest",
)


class StoreError(MsaError, RuntimeError):
    """스토어 계층의 모든 예외의 최상위."""


class ShortRead(StoreError):
    """요청한 것보다 적게 받았다 — 조용한 절단 (`CLAUDE.md` §2)."""


class SchemaDrift(StoreError):
    """스토어 스키마가 코드가 기대한 것과 다르다."""


@dataclass(frozen=True)
class TableStat:
    name: str
    rows: int
    tickers: int | None
    start: date | None
    end: date | None
    loaded: bool
    #: 실측 결과 벤더가 0행을 주는 테이블(`EMPTY_TABLES`). 0행이 **적재 실패가 아니라**
    #: 원래 그렇다는 뜻이다. 이 구분이 없으면 `msa data status` 를 볼 때마다 고장으로 읽힌다.
    known_empty: bool = False

    @property
    def status(self) -> str:
        """`msa data status` 가 찍는 한 마디 — 적재됨 · 미적재(원래 빈 테이블) · 비었음."""
        if self.loaded:
            return "적재됨"
        return "미적재(벤더가 0행)" if self.known_empty else "비었음"


def _expand(path: Path) -> Path:
    return path.expanduser().resolve()


class Store:
    """읽기 전용 DuckDB 접근자.

    쓰기 경로는 제공하지 않는다. `duckdb.connect(read_only=True)` 로 열기 때문에
    실수로 DDL 을 날려도 드라이버가 거부한다.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.path = _expand(Path(db_path) if db_path is not None else paths().duckdb)
        if not self.path.exists():
            raise StoreError(
                f"DuckDB 스토어가 없다: {self.path}\n"
                "MSA_DUCKDB 환경변수로 경로를 지정하거나 "
                "`docs/08-data-contract.md` §6 부트스트랩 절차를 먼저 밟아라."
            )
        self._con = duckdb.connect(str(self.path), read_only=True)
        self._columns: dict[str, list[str]] = {}
        self._verify_schema()

    # ------------------------------------------------------------------ 내부

    def _verify_schema(self) -> None:
        rows = self._con.execute("select table_name from information_schema.tables").fetchall()
        present = {r[0] for r in rows}
        missing = [t for t in KNOWN_TABLES if t not in present]
        if missing:
            raise SchemaDrift(
                f"스토어에 기대한 테이블이 없다: {missing}. 있는 것: {sorted(present)}"
            )

    def _df(self, sql: str, params: Sequence[Any] | None = None) -> pd.DataFrame:
        return self._con.execute(sql, list(params or [])).fetch_df()

    def scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        """단일 값 조회 (`select max(date) …`·`select count(*) …`). 행이 없으면 None."""
        row = self._con.execute(sql, list(params or [])).fetchone()
        return None if row is None else row[0]

    def columns(self, table: str) -> list[str]:
        """테이블 컬럼 목록 (ordinal 순). 읽기 전용 연결이라 한 번 읽으면 캐시한다."""
        if table not in KNOWN_TABLES:
            raise SchemaDrift(f"모르는 테이블: {table}")
        if table not in self._columns:
            rows = self._con.execute(
                "select column_name from information_schema.columns "
                "where table_name = ? order by ordinal_position",
                [table],
            ).fetchall()
            self._columns[table] = [r[0] for r in rows]
        return list(self._columns[table])

    # ------------------------------------------------------------------ 일반 질의 표면
    #
    # 계층 모듈이 `store._con` 에 직접 손대지 않게 하기 위한 것이다. SQL 텍스트는 호출자가
    # 갖고, 프레임 등록·해제·`_guard` 는 여기서 한다.

    @contextmanager
    def temp_tables(self, **frames: pd.DataFrame) -> Iterator[None]:
        """`frames` 를 이름대로 DuckDB 뷰로 등록하고 블록이 끝나면 해제한다."""
        names = list(frames)
        for name, df in frames.items():
            self._con.register(name, df)
        try:
            yield
        finally:
            for name in names:
                self._con.unregister(name)

    def query(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
        *,
        min_rows: int = 0,
        frames: dict[str, pd.DataFrame] | None = None,
        what: str | None = None,
    ) -> pd.DataFrame:
        """임의 SQL → DataFrame. `frames` 는 질의 동안만 등록되는 뷰. `min_rows` 미만이면 던진다."""
        with self.temp_tables(**(frames or {})):
            df = self._df(sql, params)
        _guard(df, what or f"query({' '.join(sql.split())[:60]}…)", min_rows=min_rows)
        return df

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        """결과가 없는 문장 (임시 테이블 생성·삭제). 읽기 전용 연결이라 DDL 은 임시 객체뿐이다."""
        self._con.execute(sql, list(params or []))

    def configure(self, *, threads: int | None = None, memory_limit: str | None = None) -> None:
        """세션 설정 (`set threads`·`set memory_limit`) — 큰 집계 전에 호출한다."""
        if threads is not None:
            self._con.execute(f"set threads = {int(threads)}")
        if memory_limit is not None:
            self._con.execute(f"set memory_limit = '{memory_limit}'")

    def store_end(self) -> date | None:
        """`prices` 의 최종일 — 스캔·피처의 기본 기준일. 행이 없으면 None."""
        v = self.scalar("select max(date) from prices")
        return None if v is None else _as_date(v)

    def latest_mcap(
        self, tickers: Iterable[str] | None = None, asof: date | str | None = None
    ) -> pd.Series:
        """종목별 **가장 최근 non-null 시총** (달러). index ticker(오름차순), name `mcap`.

        `arg_max(mcap, date)` 해시 집계 — `row_number() over (order by date desc) = 1` 과 같다.
        `asof` 를 주면 `date ≤ asof` 안에서 고른다.
        """
        clauses = ["mcap is not null"]
        params: list[Any] = []
        if tickers is not None:
            frag, vals = _in_clause("ticker", [t.upper() for t in tickers])
            clauses.append(frag)
            params.extend(vals)
        _date_clauses(clauses, params, None, asof, "date")
        df = self._df(
            "select ticker, arg_max(mcap, date) as mcap from prices "
            f"where {' and '.join(clauses)} group by ticker order by ticker",
            params,
        )
        return pd.Series(
            df["mcap"].to_numpy(), index=pd.Index(df["ticker"], name="ticker"), name="mcap"
        )

    def close_series(
        self, ticker: str, start: date | str | None = None, end: date | str | None = None
    ) -> pd.Series:
        """한 종목의 조정 종가 — `DatetimeIndex`(오름차순), name = ticker. 없으면 빈 시리즈.

        `ETF_IN_STORE` 종목이 스토어에 없으면 **벌크 `funds.csv.zip` 으로 넘어간다.**
        ETF 가 `prices` 에 있느냐는 스토어를 어떻게 빌드했느냐에 달린 우연이고(주식 `SEP` 과
        펀드 `SFP` 는 다른 파일이다), 2026-08-25 재빌드에서 실제로 SPY 가 0행이 되어
        L1 패널과 L4 달력이 동시에 멈췄다. 벌크에도 없으면 빈 시리즈다 — 호출자가 판단한다.
        """
        where, params = _ticker_date_where([ticker], start, end)
        df = self._df(f"select date, close from prices {where} order by date", params)
        if df.empty and ticker.upper() in ETF_IN_STORE:
            df = _etf_close_from_bulk(ticker, start, end)
        return pd.Series(
            df["close"].to_numpy(dtype=float),
            index=pd.DatetimeIndex(pd.to_datetime(df["date"]), name="date"),
            name=ticker.upper(),
        )

    def tickers_with_prices(
        self, tickers: Iterable[str], start: date | str | None = None, end: date | str | None = None
    ) -> set[str]:
        """요청 종목 중 구간 안에 가격 행이 **하나라도** 있는 것 (`select distinct ticker`)."""
        ts = list(tickers)
        if not ts:
            return set()
        where, params = _ticker_date_where(ts, start, end)
        df = self._df(f"select distinct ticker from prices {where}", params)
        return set(df["ticker"].astype(str))

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ 조회

    def prices(
        self,
        tickers: Iterable[str] | None = None,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        min_rows: int,
        expect_tickers: int | None = None,
        columns: Sequence[str] | None = None,
        absent_expected: bool = False,
    ) -> pd.DataFrame:
        """일별 가격·시총. **폐지 종목을 포함한다** (생존 편향 방지, `docs/01` §5).

        반환 컬럼(기본 = `PRICE_COLUMNS` 12개): `ticker, date, open, high, low, close, closeunadj,
        volume, dividends, mcap, ev, short_interest`. `columns` 를 주면 그 열만 읽는다
        (순서는 준 대로; `PRICE_COLUMNS` 밖이면 `SchemaDrift`).

        - `close` 는 **조정 종가**, `closeunadj` 가 미조정 원가다.
        - `mcap`·`ev` 는 **달러**다. 적재 시점에 백만→달러 환산이 이미 끝났다
          (`MCAP_UNIT_ALREADY_APPLIED`). 다시 곱하지 마라.
        - PIT: 가격은 개정되지 않으므로 PIT 구분이 필요 없다.

        Args:
            min_rows: 이 행수 미만이면 `ShortRead`. 호출자는 반드시 기대치를 밝힌다 —
                기본값을 주면 "0행이 나왔는데 아무도 몰랐다" 가 다시 가능해진다.
            expect_tickers: 요청 티커 중 최소 몇 개가 결과에 있어야 하는지.
                `None` 이면 검사하지 않는다.
        """
        cols = PRICE_COLUMNS if columns is None else tuple(columns)
        unknown = [c for c in cols if c not in PRICE_COLUMNS]
        if unknown:
            raise SchemaDrift(f"prices 에 없는 컬럼: {unknown}. 있는 것: {list(PRICE_COLUMNS)}")
        where, params = _ticker_date_where(tickers, start, end)
        df = self._df(
            f"select {', '.join(cols)} from prices {where} order by ticker, date",
            params,
        )
        _guard(
            df,
            "prices",
            min_rows=min_rows,
            expect_tickers=expect_tickers,
            requested=tickers,
            absent_expected=absent_expected,
        )
        return df

    def tickers_meta(
        self,
        categories: Sequence[str] | None = None,
        *,
        min_rows: int,
        include_delisted: bool = True,
    ) -> pd.DataFrame:
        """티커 메타 전체.

        `categories` 의 **기본값은 `None` = 필터 없음**이다. 보통주만 보고 싶으면
        호출자가 명시한다 (`msa.data.universe.common_stock`). 여기서 조용히 걸러 두면
        "왜 우선주가 안 보이지" 를 6개월 뒤에 디버깅하게 된다.

        `include_delisted=True` 가 기본인 것도 같은 이유다 — 폐지 종목을 빼면
        자기이력 백분위가 낙관 방향으로 왜곡된다 (`docs/01` §5).

        컬럼: `ticker, name, category, sector, industry, siccode, location, is_delisted`.
        문서 §2 는 `isdelisted` 로 적었지만 실제 컬럼명은 `is_delisted` 다.
        `sicsector`·`firstpricedate`·`lastpricedate` 는 스토어에 없다.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if categories is not None:
            cats = list(categories)
            if not cats:
                raise ValueError("categories=[] 는 전부 거르라는 뜻이 된다. 필터 없음은 None 이다.")
            frag, vals = _in_clause("category", cats)
            clauses.append(frag)
            params.extend(vals)
        if not include_delisted:
            clauses.append("coalesce(is_delisted, 'N') <> 'Y'")
        where = f"where {' and '.join(clauses)}" if clauses else ""
        df = self._df(
            "select ticker, name, category, sector, industry, siccode, location, is_delisted "
            f"from tickers {where} order by ticker",
            params,
        )
        _guard(df, "tickers", min_rows=min_rows)
        return df

    def fundamentals(
        self,
        tickers: Iterable[str] | None = None,
        fields: Sequence[str] | None = None,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        min_rows: int,
        date_column: str = "datekey",
        absent_expected: bool = False,
    ) -> pd.DataFrame:
        """분기 재무 (`SF1`).

        PIT: `datekey` 가 **공시일**, `calendardate` 가 회계기간이다. 자기이력 백분위와
        자본 사이클 시계열은 `datekey` 로 잘라야 한다 (`CLAUDE.md` PIT 규약 — 필요 쪽).
        오늘의 스냅샷(부채비율·런웨이)만 `calendardate` 기준이 허용된다.
        그래서 `date_column` 을 인자로 받되 기본값은 PIT 쪽인 `datekey` 다.

        실측: `dimension` 은 `ARQ` 한 종류뿐이다(`ART` 없음). 문서 §2 의 경고대로
        `assetsavg`·`equityavg`·`invcapavg` 는 655,000행 **전부 null** 이라 직접 계산해야 한다.
        `roic`·`grossmargin`·`evebitda`·`pb`·`ps` 도 스토어에 없다 (파생 계산 대상).
        """
        if date_column not in ("datekey", "calendardate"):
            raise ValueError(f"date_column 은 datekey 또는 calendardate 여야 한다: {date_column!r}")
        available = set(self.columns("fundamentals"))
        base = ["ticker", "calendardate", "datekey", "dimension"]
        if fields is None:
            select = "*"
        else:
            unknown = [f for f in fields if f not in available]
            if unknown:
                raise SchemaDrift(
                    f"fundamentals 에 없는 필드: {unknown}. "
                    f"있는 것: {sorted(available - set(base))}"
                )
            select = ", ".join(base + [f for f in fields if f not in base])
        where, params = _ticker_date_where(tickers, start, end, date_col=date_column)
        df = self._df(
            f"select {select} from fundamentals {where} order by ticker, {date_column}", params
        )
        _guard(
            df,
            "fundamentals",
            min_rows=min_rows,
            requested=tickers,
            absent_expected=absent_expected,
        )
        return df

    def actions(
        self,
        kinds: Sequence[str] | None = None,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        min_rows: int,
    ) -> pd.DataFrame:
        """기업 액션. 자본 사이클 E 블록의 `exit_count`/`entry_count` 재료다.

        실측 `action` 값 19종 — 진입: `listed`, 이탈: `delisted`·`bankruptcyliquidation`·
        `acquisitionby`·`mergerto`·`regulatorydelisting`·`voluntarydelisting`.
        `EXIT_ACTIONS`·`ENTRY_ACTIONS` 상수를 쓰면 오타로 조용히 0건이 되는 일이 없다.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if kinds is not None:
            ks = list(kinds)
            if not ks:
                raise ValueError("kinds=[] 는 전부 거르라는 뜻이 된다. 필터 없음은 None 이다.")
            frag, vals = _in_clause("action", ks)
            clauses.append(frag)
            params.extend(vals)
        _date_clauses(clauses, params, start, end, "date")
        where = f"where {' and '.join(clauses)}" if clauses else ""
        df = self._df(
            f"select ticker, date, action, value, name, contraticker from actions {where} "
            "order by date, ticker",
            params,
        )
        _guard(df, "actions", min_rows=min_rows)
        if kinds is not None:
            got = set(df["action"].unique())
            absent = [k for k in kinds if k not in got]
            if absent:
                log.warning("actions: 요청한 종류 중 결과가 0건인 것 %s", absent)
        return df

    def table_stats(self) -> list[TableStat]:
        """`msa data status` 의 재료. 각 테이블의 행수·기간·종목수."""
        out: list[TableStat] = []
        for name in KNOWN_TABLES:
            cols = set(self.columns(name))
            rows = int(self.scalar(f'select count(*) from "{name}"'))
            date_col = next((c for c in ("date", "datekey", "calendardate") if c in cols), None)
            start = end = None
            if date_col and rows:
                start, end = self._con.execute(
                    f'select min({date_col}), max({date_col}) from "{name}"'
                ).fetchone()  # type: ignore[misc]
            n_tickers = None
            if "ticker" in cols and rows:
                n_tickers = int(self.scalar(f'select count(distinct ticker) from "{name}"'))
            out.append(
                TableStat(
                    name=name,
                    rows=rows,
                    tickers=n_tickers,
                    start=start,
                    end=end,
                    loaded=rows > 0,
                    known_empty=name in EMPTY_TABLES,
                )
            )
        return out

    def null_rates(self, table: str, columns: Sequence[str]) -> dict[str, float]:
        """결측률. `msa data status` 가 쓴다."""
        available = set(self.columns(table))
        unknown = [c for c in columns if c not in available]
        if unknown:
            raise SchemaDrift(f"{table} 에 없는 컬럼: {unknown}")
        rows = int(self.scalar(f'select count(*) from "{table}"'))
        if rows == 0:
            return dict.fromkeys(columns, 1.0)
        expr = ", ".join(f'count("{c}")' for c in columns)
        counts = self._con.execute(f'select {expr} from "{table}"').fetchone()
        assert counts is not None
        return {c: 1.0 - (n / rows) for c, n in zip(columns, counts, strict=True)}


#: `actions.action` 중 유니버스 이탈로 세는 값 (자본 사이클 E 블록).
EXIT_ACTIONS = (
    "delisted",
    "bankruptcyliquidation",
    "acquisitionby",
    "mergerto",
    "regulatorydelisting",
    "voluntarydelisting",
)
#: 유니버스 진입.
ENTRY_ACTIONS = ("listed",)


# ---------------------------------------------------------------- ETF (SFP)

#: 스토어에 적재된 유일한 ETF. 나머지는 벌크 `funds.csv.zip` 에만 있다.
ETF_IN_STORE = ("SPY",)

#: `etf_prices()` 반환 프레임의 컬럼 (순서 포함).
ETF_COLUMNS: tuple[str, ...] = ("ticker", "date", "close", "closeadj", "volume")

#: 벌크 CSV 에서 읽는 열의 pyarrow 타입 — 전부 문자열로 받아 pandas 에서 예전과 같은 규칙으로
#: 변환한다 (`pd.to_datetime(...).dt.date` · `pd.to_numeric(errors="coerce")`).
_ETF_READ_TYPES = {c: pa.string() for c in ETF_COLUMNS}


def _etf_close_from_bulk(
    ticker: str, start: date | str | None, end: date | str | None
) -> pd.DataFrame:
    """벌크에서 한 ETF 의 `date,close` — 조정 종가(`closeadj`)를 쓴다. 실패하면 빈 프레임."""
    try:
        raw = etf_prices([ticker], min_rows=1)
    except Exception as e:  # 벌크가 없거나 읽히지 않는다 — 조용히 실패하지 않는다
        log.warning("%s: 스토어에 없고 벌크도 읽지 못했다 — %s", ticker, e)
        return pd.DataFrame(columns=["date", "close"])
    if raw.empty:
        log.warning("%s: 스토어에도 벌크에도 없다", ticker)
        return pd.DataFrame(columns=["date", "close"])
    # 한 실행에서 티커당 한 번만, INFO 로 말한다. 이것은 **문서화된 정상 경로**다
    # (`docs/18` §6) — Airflow DAG 의 `TABLE_KINDS` 에 `funds` 가 없어 ETF 가 `prices` 에
    # 들어오지 않고, 벌크가 그것을 정확히 메운다. 경고로 두면 테마마다 되풀이돼 같은 사실이
    # 9줄이 되고 그 사이의 진짜 이상이 묻힌다. 폴백이 **실패하면** 위에서 경고가 난다.
    if ticker not in _BULK_FALLBACK_SAID:
        _BULK_FALLBACK_SAID.add(ticker)
        log.info("%s 를 스토어가 아니라 벌크 funds.csv.zip 에서 읽었다 (docs/18 §6)", ticker)
    out = raw.loc[:, ["date", "closeadj"]].rename(columns={"closeadj": "close"})
    d = pd.to_datetime(out["date"])
    if start is not None:
        out = out[d >= pd.Timestamp(start)]
        d = pd.to_datetime(out["date"])
    if end is not None:
        out = out[d <= pd.Timestamp(end)]
    return out.dropna().sort_values("date").reset_index(drop=True)


def empty_etf_frame() -> pd.DataFrame:
    """`etf_prices()` 와 같은 컬럼의 빈 프레임 — 벌크를 못 읽었을 때 하류가 같은 모양을 본다."""
    return pd.DataFrame(columns=list(ETF_COLUMNS))


def etf_prices(
    tickers: Sequence[str],
    *,
    min_rows: int,
    raw_dir: Path | None = None,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """ETF 일별 가격 — 벌크 원본 `funds.csv.zip` 을 직접 읽는다.

    **`SFP` 는 DuckDB 스토어에 적재돼 있지 않다.** 실측: `prices` 안의 ETF 는 `SPY`
    하나뿐이고 GDX·SIL·REMX·LIT·URA·COPX·XME·XOP·TAN·ITA·JETS·SOXX·XBI·KRE·XHB·PAVE·
    NLR·GLD·CPER 은 전부 없다. `docs/08` §6.2 가 "`SPY` 외 ETF 가 있는지" 로 물었던
    항목의 답은 **없다** 이며, 그래서 이 함수가 벌크를 직접 읽는다.

    zip 안 CSV 를 pyarrow 로 한 번 스트리밍하며 요청한 티커를 배치 단위로 걸러 낸다.
    티커를 하나씩 부르면 그만큼 통과 횟수가 늘어나므로 **한 번에 모아서 부른다.**

    결과는 `state/cache/etf_<지문>.parquet` 에 사이드 캐시한다 — 지문 = 요청 티커 집합 +
    zip 의 크기·수정시각이라 **벌크가 갱신되면 자동으로 비껴간다.** 캐시 적중이면 zip 을 열지
    않는다. `cache_dir=None` 이면 `paths().cache`.

    반환: `ETF_COLUMNS` — `date` 는 `datetime.date`, 나머지 숫자는 float, `ticker, date` 오름차순.
    """
    want = {t.upper() for t in tickers}
    if not want:
        raise ValueError("tickers 가 비었다.")
    base = _expand(raw_dir or paths().sharadar_raw)
    zip_path = next(
        (p for p in (base / "raw" / "funds.csv.zip", base / "funds.csv.zip") if p.exists()), None
    )
    if zip_path is None:
        raise StoreError(
            f"ETF 벌크 원본을 찾을 수 없다: {base}/funds.csv.zip. "
            "MSA_SHARADAR_RAW 로 경로를 지정해라."
        )
    cdir = cache_dir if cache_dir is not None else paths().cache
    cache = cdir / f"etf_{_etf_cache_key(want, zip_path)}.parquet"
    if cache.exists():
        log.info("etf_prices: 캐시 사용 %s", cache.name)
        df = pd.read_parquet(cache)
    else:
        df = _scan_funds_zip(zip_path, want)
        try:
            cdir.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache)
        except OSError as e:  # 캐시 실패는 결과를 막지 않는다 — 다음에 다시 훑을 뿐이다
            log.warning("etf_prices: 캐시 저장 실패 %s: %s", cache, e)
    _guard(df, f"etf_prices({zip_path.name})", min_rows=min_rows, requested=sorted(want))
    return df


def _etf_cache_key(want: set[str], zip_path: Path) -> str:
    st = zip_path.stat()
    h = hashlib.sha256()
    h.update(",".join(sorted(want)).encode())
    h.update(f"|{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


def _scan_funds_zip(zip_path: Path, want: set[str]) -> pd.DataFrame:
    """zip 안 CSV 를 pyarrow 로 배치 스트리밍하며 `want` 티커만 남긴다. 한 번 통과."""
    with zipfile.ZipFile(zip_path) as zf:
        name = next((n for n in zf.namelist() if n.endswith(".csv")), None)
        if name is None:
            raise StoreError(f"{zip_path} 안에 csv 가 없다: {zf.namelist()}")
        with zf.open(name) as raw:
            header = raw.readline().decode("utf-8").rstrip("\r\n").split(",")
        missing = [c for c in ETF_COLUMNS if c not in header]
        if missing:
            raise SchemaDrift(f"funds.csv 헤더에 없는 컬럼 {missing}. 헤더: {header}")
        value_set = pa.array(sorted(want), type=pa.string())
        batches: list[pa.RecordBatch] = []
        with zf.open(name) as raw:
            reader = pacsv.open_csv(
                raw,
                read_options=pacsv.ReadOptions(block_size=8 << 20),
                convert_options=pacsv.ConvertOptions(
                    include_columns=list(ETF_COLUMNS), column_types=_ETF_READ_TYPES
                ),
            )
            for batch in reader:
                mask = pc.is_in(batch.column("ticker"), value_set=value_set)
                if pc.any(mask).as_py():
                    batches.append(batch.filter(mask))
    if batches:
        table = pa.Table.from_batches(batches).select(list(ETF_COLUMNS))
        df: pd.DataFrame = table.to_pandas()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for c in ("close", "closeadj", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.sort_values(["ticker", "date"], ignore_index=True)
    else:
        df = empty_etf_frame()
    return df


def etf_prices_or_empty(
    tickers: Sequence[str], *, raw_dir: Path | None = None, cache_dir: Path | None = None
) -> pd.DataFrame:
    """`etf_prices(min_rows=0)` 이되 벌크를 못 읽으면(`StoreError`) **경고를 남기고** 빈 프레임.

    스캔·백테스트처럼 ETF 없이도 진행하는 경로용이다 — 조용히 비우지 않고 경고는 반드시 남긴다.
    """
    try:
        return etf_prices(tickers, min_rows=0, raw_dir=raw_dir, cache_dir=cache_dir)
    except StoreError as e:
        log.warning("ETF 벌크를 읽지 못했다: %s", e)
        return empty_etf_frame()


def etf_series(df: pd.DataFrame, symbol: str) -> pd.Series | None:
    """`etf_prices` 프레임에서 한 심볼의 `closeadj` 시계열 (`DatetimeIndex`, 결측 제거, 오름차순).
    프레임에 없으면 None."""
    sub = df.loc[df["ticker"] == symbol.upper()]
    if sub.empty:
        return None
    s = pd.Series(sub["closeadj"].to_numpy(), index=pd.to_datetime(sub["date"])).dropna()
    return s.sort_index()


# ---------------------------------------------------------------- 공용 헬퍼


def _date_clauses(
    clauses: list[str],
    params: list[Any],
    start: date | str | None,
    end: date | str | None,
    col: str,
) -> None:
    if start is not None:
        clauses.append(f"{col} >= ?")
        params.append(str(start))
    if end is not None:
        clauses.append(f"{col} <= ?")
        params.append(str(end))


def _as_date(v: Any) -> date:
    """DuckDB 가 돌려주는 `date`/`datetime`/`Timestamp` → `datetime.date`."""
    if isinstance(v, date) and not hasattr(v, "hour"):
        return v
    return pd.Timestamp(v).date()


def _in_clause(col: str, values: Sequence[Any]) -> tuple[str, list[Any]]:
    """`col in (?,?,…)` 조각과 바인딩 값. 빈 목록은 호출자가 먼저 거른다."""
    return f"{col} in ({','.join('?' * len(values))})", list(values)


def _ticker_date_where(
    tickers: Iterable[str] | None,
    start: date | str | None,
    end: date | str | None,
    *,
    date_col: str = "date",
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if tickers is not None:
        ts = [t.upper() for t in tickers]
        if not ts:
            raise ValueError("tickers=[] 는 전부 거르라는 뜻이 된다. 필터 없음은 None 이다.")
        frag, vals = _in_clause("ticker", ts)
        clauses.append(frag)
        params.extend(vals)
    _date_clauses(clauses, params, start, end, date_col)
    return (f"where {' and '.join(clauses)}" if clauses else ""), params


#: 경고 한 줄에 찍는 티커 수. 나머지는 개수로 적고 DEBUG 에 전문을 남긴다 — 로그 한 줄이
#: 수백 개로 불어나면 아무도 읽지 않는다.
_ABSENT_LOG_LIMIT = 20

#: 벌크 폴백을 이미 알린 티커 (프로세스 수명). 사실을 감추는 것이 아니라 **되풀이를** 막는다.
_BULK_FALLBACK_SAID: set[str] = set()


def _guard(
    df: pd.DataFrame,
    what: str,
    *,
    min_rows: int,
    expect_tickers: int | None = None,
    requested: Iterable[str] | None = None,
    absent_expected: bool = False,
) -> None:
    """기대에 못 미치면 던진다. 빈 결과를 조용히 흘려보내지 않는다."""
    if len(df) < min_rows:
        raise ShortRead(
            f"{what}: {len(df):,}행 — 최소 {min_rows:,}행을 기대했다. "
            "조용한 절단일 수 있다 (`CLAUDE.md` §2). 필터 조건과 스토어 적재 상태를 확인해라."
        )
    if requested is not None:
        req = {t.upper() for t in requested}
        got = set(df["ticker"].unique()) if "ticker" in df.columns and len(df) else set()
        absent = sorted(req - got)
        if absent:
            # **잘랐으면 잘랐다고 적는다** (`CLAUDE.md` §2). 예전에는 20개만 찍고 말이 없어
            # 154개가 빠졌는데 20개가 전부인 것처럼 읽혔다.
            shown = absent[:_ABSENT_LOG_LIMIT]
            more = len(absent) - len(shown)
            # `absent_expected` 는 **호출자가 결측을 세어 스스로 보고할 때**만 준다.
            # 테마 구성원 명단은 폐지 종목과 부상장 클래스를 일부러 포함하므로(생존 편향
            # 방지, `docs/01` §5) 여기서 매번 경고하면 진짜 이상이 그 사이에 묻힌다.
            # **감추는 것이 아니다** — 호출자가 `구성원/상장/재무없음` 을 INFO 로 적는다.
            log.log(
                logging.DEBUG if absent_expected else logging.WARNING,
                "%s: 요청한 %d 종목 중 %d 종목이 결과에 없다: %s%s",
                what,
                len(req),
                len(absent),
                shown,
                f" 외 {more}개 (DEBUG 로 전문)" if more else "",
            )
            if more and not absent_expected:
                log.debug("%s: 결과에 없는 종목 전문: %s", what, absent)
    if expect_tickers is not None:
        n = df["ticker"].nunique() if "ticker" in df.columns else 0
        if n < expect_tickers:
            raise ShortRead(f"{what}: 종목 {n}개 — 최소 {expect_tickers}개를 기대했다.")
