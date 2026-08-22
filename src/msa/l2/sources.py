"""드라이버 원시 시계열 로더 — provider 별로 한 가지 모양(`RawSeries`)으로 돌려준다.

| provider | 어디서 | 없으면 |
|---|---|---|
| `fred` | `state/physical/fred/<SYMBOL>.csv` (L1 과 같은 캐시). 키 있으면 받아 캐시 | `missing` |
| `derived` | FRED 시리즈 여러 개 (`usd_liquidity`) — 결합은 `drivers.py` | 구성 시리즈별로 보고 |
| `etf` | 벌크 `funds.csv.zip` (`msa.data.store.etf_prices`, 1회 통과 ≈ 12초) | `missing` |
| `manual` | `state/physical/manual/<id>.csv` (`date,value[,available]`) — 사람이 갱신 | `missing` |
| `sharadar_derived` | DuckDB 스토어 SF1 ARQ `capex` (`hyperscaler_capex`) | `missing` |
| `agent` | `state/physical/manual/policy_events.csv` (`date,theme,effect[,…]`) | `missing` |

**없는 것은 없다고 돌려준다** — `status="missing"` 과 이유. 조용히 빈 시리즈를 돌려주지 않는다
(`CLAUDE.md` §2). 모든 외부 접근은 여기서만 일어나며, `drivers.py` 이하는 순수 함수다 —
테스트는 `RawSeries` 를 직접 만들어 넣는다.

## 수동 CSV 규약

`date,value` 가 필수. `available`(발표일) 열이 있으면 그것을 쓰고, 없으면 `drivers.PUB_LAG` 의
수동 시리즈 기본 지연(월간 +1개월)을 적용한다. 값의 단위는 드라이버 `measure` 가 기대하는 대로
(`china_credit_impulse` 는 GDP 대비 비율, `china_property` 는 면적 수준 — YoY 는 코드가 계산).

`policy_events.csv` 는 시계열이 아니라 이벤트 목록이다: `effect ∈ {+1, -1}` 은 **해당 테마에**
유리/불리, `confirmed ∈ {Y, N}` 은 확정 여부(`N` 은 세지 않는다).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from msa.config import MissingApiKey, paths, rel
from msa.data.pit import add_ttm, pit_quarterly
from msa.l1.physical import fetch_fred_to_cache, fred_cache_path, read_fred_cache
from msa.status import SeriesStatus

log = logging.getLogger(__name__)

HYPERSCALERS: tuple[str, ...] = ("MSFT", "GOOGL", "AMZN", "META", "ORCL")
POLICY_EVENTS_FILE = "policy_events"

#: TTM 유효 범위 — 4분기가 **연속**이어야 한다 (직전 3분기가 250~300일 전). 분기가 하나 빠진 채
#: 4행이 붙으면 TTM 이 아니다. `add_ttm` 의 상한(300)에 하한(250)을 더한 것이다.
CAPEX_TTM_SPAN_DAYS: tuple[int, int] = (250, 300)


@dataclass(frozen=True)
class RawSeries:
    """원래 주기의 시계열 + (있으면) 관측별 이용 가능 시점.

    `available` 이 `None` 이면 `drivers.py` 가 선언된 발표 지연표로 계산한다.
    """

    symbol: str
    source: str  # 예: fred:DFII10 · etf:GLD · manual:china_property · sharadar:capex_ttm
    status: str  # ok | missing
    values: pd.Series | None = None
    available: pd.Series | None = None
    note: str = ""
    units: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == SeriesStatus.OK and self.values is not None and len(self.values) > 0


def _missing(symbol: str, source: str, note: str) -> RawSeries:
    return RawSeries(symbol, source, SeriesStatus.MISSING, note=note)


# TODO(rf-b): → `msa.l1.physical.read_date_value_csv(path, extra=("available",))` 로 교체
# (L1 이 `extra` 열을 받게 되면 아래 본문은 그 호출 한 줄이 된다).
def read_manual_csv(path: Path) -> tuple[pd.Series, pd.Series | None]:
    """`date,value[,available]` → (값, 이용가능일 또는 None)."""
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    if "date" not in cols or "value" not in cols:
        raise ValueError(
            f"{path}: 컬럼은 date,value[,available] 여야 한다. 있는 것: {list(df.columns)}"
        )
    idx = pd.to_datetime(df[cols["date"]])
    s = pd.Series(pd.to_numeric(df[cols["value"]], errors="coerce").to_numpy(), index=idx)
    avail: pd.Series | None = None
    if "available" in cols:
        avail = pd.Series(pd.to_datetime(df[cols["available"]]).to_numpy(), index=idx)
        avail = avail[s.notna()]
    s = s.dropna().sort_index()
    if s.empty:
        raise ValueError(f"{path}: 값이 전부 결측이다")
    if avail is not None:
        avail = avail.reindex(s.index)
    return s, avail


def capex_ttm_asof(
    fund: pd.DataFrame, grid: pd.DatetimeIndex, *, max_stale_days: int = 200
) -> pd.DataFrame:
    """SF1 ARQ `capex` → 티커별 TTM(|capex| 4분기 합)을 월말 격자에 **datekey as-of** 로 놓는다.

    PIT: 같은 `calendardate` 에 행이 여럿이면(정정 공시) **가장 이른 `datekey`** 행을 쓴다 —
    그 시점에 보였던 값이다 (`msa.data.pit.pit_quarterly`). 4분기가 연속(직전 3분기가 250~300일
    전)이 아니면 TTM 은 NaN. `max_stale_days` 를 넘게 새 공시가 없으면 NaN — 죽은 시리즈를 앞으로
    끌지 않는다. 유효한 TTM 행이 하나도 없는 티커는 결과 열에 **없다** (호출자가 이름으로 센다).
    """
    need = {"ticker", "calendardate", "datekey", "capex"}
    if not need <= set(fund.columns):
        raise ValueError(
            f"fund 프레임 컬럼 부족: 필요 {sorted(need)}, 있는 것 {list(fund.columns)}"
        )
    lo, hi = CAPEX_TTM_SPAN_DAYS
    q = pit_quarterly(fund, asof=None)  # 최초 보고분 규칙 — datekey 상한은 격자 as-of 가 맡는다
    q["capex_abs"] = q["capex"].abs()
    q = add_ttm(q, ["capex_abs"], span_days=hi)
    span = (q["calendardate"] - q.groupby("ticker", sort=False)["calendardate"].shift(3)).dt.days
    rows = (
        q.assign(ttm=q["capex_abs_ttm"].where(span >= lo), ticker=q["ticker"].astype(str))
        .dropna(subset=["ttm"])
        # 같은 날 두 분기가 공시되면 나중 분기의 TTM — 그 날 이후 보이는 값이다
        .sort_values(["ticker", "datekey", "calendardate"])
        .drop_duplicates(["ticker", "datekey"], keep="last")
        .sort_values("datekey", kind="stable")[["ticker", "datekey", "ttm"]]
    )
    if rows.empty:
        return pd.DataFrame(index=grid)
    tickers = sorted(rows["ticker"].unique())
    left = pd.DataFrame(
        {"t": grid.repeat(len(tickers)), "ticker": list(tickers) * len(grid)}
    ).sort_values(["t", "ticker"])
    m = pd.merge_asof(
        left, rows, left_on="t", right_on="datekey", by="ticker", direction="backward"
    )
    stale = (m["t"] - m["datekey"]).dt.days > max_stale_days
    m["ttm"] = m["ttm"].where(~stale)
    return (
        m.pivot(index="t", columns="ticker", values="ttm")
        .reindex(grid)
        .rename_axis(index=None, columns=None)
    )


class SeriesStore:
    """외부 접근을 한곳에 모은 로더. 실패는 `RawSeries(status="missing")` 로 돌려준다."""

    def __init__(
        self, *, allow_fetch: bool = True, allow_etf: bool = True, allow_store: bool = True
    ) -> None:
        self.allow_fetch = allow_fetch
        self.allow_etf = allow_etf
        self.allow_store = allow_store
        self.manual_dir = paths().manual_dir
        self._etf: dict[str, pd.DataFrame] | None = None  # ticker → (date, closeadj) 행
        self._etf_error: str | None = None
        self._etf_requested: set[str] = set()

    # ------------------------------------------------------------ FRED

    def fred(self, symbol: str) -> RawSeries:
        src = f"fred:{symbol}"
        cache = fred_cache_path(symbol)
        s = read_fred_cache(symbol)
        note = f"cache {cache.name}"
        if s is None:
            if not self.allow_fetch:
                return _missing(symbol, src, f"캐시 없음 {cache} (--no-fetch)")
            try:
                s = fetch_fred_to_cache(symbol)
                note = "fetched+cached"
            except MissingApiKey:
                return _missing(symbol, src, f"FRED_API_KEY 없음 · 캐시 없음 {rel(cache)}")
            except Exception as e:  # FredError · 네트워크
                return _missing(symbol, src, f"{type(e).__name__}: {e}")
        units: str | None = None
        meta_p = cache.with_suffix(".meta.json")
        if meta_p.exists():
            try:
                units = json.loads(meta_p.read_text()).get("units")
            except (OSError, ValueError):
                units = None
        return RawSeries(symbol, src, SeriesStatus.OK, values=s, note=note, units=units)

    # ------------------------------------------------------------ ETF

    def prefetch_etf(self, symbols: Iterable[str]) -> None:
        """벌크 zip 을 **한 번만** 훑고 티커별로 갈라 둔다. `etf()` 전에 심볼을 모아 부른다."""
        want = sorted({s.upper() for s in symbols})
        if not want:
            return
        self._etf_requested = set(want)
        if not self.allow_etf:
            self._etf_error = "ETF 벌크 읽기 비활성 (--no-etf)"
            return
        try:
            from msa.data.store import etf_prices

            df = etf_prices(want, min_rows=0)
        except Exception as e:  # StoreError · 파일 없음 — 이유를 드라이버 메모에 남긴다
            self._etf_error = f"{type(e).__name__}: {e}"
            log.warning("ETF 벌크를 읽지 못했다: %s", e)
            return
        df = df.assign(date=pd.to_datetime(df["date"]))[["ticker", "date", "closeadj"]]
        self._etf = {str(tk): g for tk, g in df.groupby("ticker", sort=False)}

    def etf(self, symbol: str) -> RawSeries:
        sym = symbol.upper()
        src = f"etf:{sym}"
        if sym not in self._etf_requested:
            self.prefetch_etf(self._etf_requested | {sym})
        if self._etf is None:
            return _missing(sym, src, self._etf_error or "벌크 미조회")
        sub = self._etf.get(sym)
        if sub is None:
            return _missing(sym, src, "벌크 funds.csv.zip 에 없음")
        s = pd.Series(sub["closeadj"].to_numpy(), index=pd.DatetimeIndex(sub["date"])).dropna()
        s = s.sort_index()
        return RawSeries(
            sym, src, SeriesStatus.OK, values=s, note=f"{len(s)}행 closeadj", units="USD"
        )

    # ------------------------------------------------------------ 수동

    def manual(self, symbol: str) -> RawSeries:
        path = self.manual_dir / f"{symbol}.csv"
        src = f"manual:{symbol}"
        if not path.exists():
            return _missing(symbol, src, f"파일 없음 {rel(path)}")
        try:
            s, avail = read_manual_csv(path)
        except ValueError as e:
            return _missing(symbol, src, str(e))
        return RawSeries(symbol, src, SeriesStatus.OK, values=s, available=avail, note=path.name)

    def manual_events(self, symbol: str = POLICY_EVENTS_FILE) -> tuple[pd.DataFrame | None, str]:
        """`policy_events.csv` → (프레임, 메모). 없으면 (None, 이유)."""
        path = self.manual_dir / f"{symbol}.csv"
        if not path.exists():
            return None, f"파일 없음 {rel(path)}"
        df = pd.read_csv(path)
        cols = {c.lower(): c for c in df.columns}
        need = ("date", "theme", "effect")
        if any(c not in cols for c in need):
            return None, f"{path}: 컬럼은 date,theme,effect[,description,confirmed] 여야 한다"
        out = pd.DataFrame(
            {
                "date": pd.to_datetime(df[cols["date"]]),
                "theme": df[cols["theme"]].astype(str),
                "effect": pd.to_numeric(df[cols["effect"]], errors="coerce"),
                "description": df[cols["description"]].astype(str) if "description" in cols else "",
                "confirmed": (
                    df[cols["confirmed"]].astype(str).str.upper().isin(["Y", "YES", "TRUE", "1"])
                    if "confirmed" in cols
                    else True
                ),
            }
        )
        bad = out["effect"].isna() | ~out["effect"].isin([1, -1])
        if bad.any():
            return None, f"{path}: effect 는 +1/-1 이어야 한다 ({int(bad.sum())}행 위반)"
        return out, f"{path.name} ({len(out)}건, 확정 {int(out['confirmed'].sum())}건)"

    # ------------------------------------------------------------ Sharadar

    def sharadar_capex_ttm(
        self, grid: pd.DatetimeIndex, tickers: Sequence[str] = HYPERSCALERS
    ) -> RawSeries:
        """`hyperscaler_capex` 재료 — 5사 TTM capex 합 (월말 격자, datekey as-of).

        다섯 중 하나라도 그 달에 값이 없으면 합계는 NaN 이다 — 넷의 합을 다섯의 합인 양
        내보내면 YoY 가 조용히 틀어진다.
        """
        sym, src = "hyperscaler_capex", "sharadar:capex_ttm"
        if not self.allow_store:
            return _missing(sym, src, "스토어 접근 비활성")
        try:
            from msa.data.store import Store

            with Store(paths().duckdb) as store:
                fund = store.fundamentals(
                    list(tickers), fields=["capex"], min_rows=4 * len(tickers)
                )
        except Exception as e:
            return _missing(sym, src, f"{type(e).__name__}: {e}")
        panel = capex_ttm_asof(fund, grid)
        missing_tk = sorted(set(tickers) - set(panel.columns))
        if missing_tk:
            return _missing(sym, src, f"SF1 에 capex 가 없는 티커: {missing_tk}")
        total = panel[list(tickers)].sum(axis=1, min_count=len(tickers))
        if total.notna().sum() == 0:
            return _missing(sym, src, "5사 동시 가용 월이 0개")
        return RawSeries(
            sym,
            src,
            SeriesStatus.OK,
            values=total,
            available=pd.Series(total.index, index=total.index),
            note=f"{'+'.join(tickers)} TTM |capex| 합 · 가용 월 {int(total.notna().sum())}",
            units="USD",
        )
