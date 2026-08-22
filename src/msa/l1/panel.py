"""테마 지수 패널 — 구성원 일별 가격을 테마 단위로 집계한다.

`docs/02-cycle-state.md` 의 `P_t`(테마 지수), `DV`(달러 거래대금), 브레드스 3종의 재료를
**한 번의 DuckDB 패스**로 만든다. 44M 행의 구성원 가격을 pandas 로 올리지 않는다 —
종목별 윈도(SMA200·126일 고저)를 SQL 에서 계산하고 테마-일 단위(134 × ~7,200 행)로 줄여 받는다.

## 산출 컬럼 (테마 × 일)

| 컬럼 | 정의 |
|---|---|
| `ret_ew` | 구성원 일별 수익률의 동일가중 평균 (`close` = 조정 종가이므로 총수익) |
| `ret_cw` | 전일 시총 가중 평균. 전일 `mcap` 이 null 인 구성원은 제외 |
| `n_ret` | 그 날 수익률 계산에 들어간 구성원 수 |
| `n_listed` | 그 날 가격 행이 있는 구성원 수 (`count_decay` 재료) |
| `n_cw` | 시총 가중에 들어간 구성원 수 |
| `dv` | Σ `closeunadj × volume` — 달러 거래대금 (명목) |
| `mcap_sum` | Σ `mcap` |
| `n_sma200` · `n_above200` | 200일 이력이 있는 구성원 수 · 그중 `close > SMA200` 인 수 |
| `n_nh6m` · `n_nl6m` | 126일 고가 갱신 · 저가 갱신 구성원 수 (당일 포함) |
| `n_capped` | 수익률 상·하한에 걸린 구성원 수 (아래) |

## 데이터 위생 규칙 — **선언이며 탐색으로 정하지 않았다**

1. **수익률 포함 조건: 전일 `closeunadj ≥ $1.** 1달러 미만 종목의 호가 단위 반동은 동일가중
   지수에 양(+)의 편향을 만든다(학계 표준 필터, 예: Fama-French 의 $1 제외). 제외된 종목-일은
   `n_listed − n_ret` 로 드러난다.
2. **일별 수익률 상한 +300% · 하한 −95%.** 분할 미조정 같은 데이터 오류 한 건이 구성원 6개짜리
   지수를 10배 튀게 하는 것을 막는다. 걸린 건수는 `n_capped` 로 **센다** — 조용히 자르지 않는다.
   실제 +300% 상승이 잘리는 비용을 받아들인다 (사이클 저점 판정에 하루 수익률의 크기는 중요하지
   않다).
3. **연속성 조건 없음.** 직전 가격 행 대비 수익률이며, 거래 정지 후 재개 첫날의 수익도 포함한다
   (폐지 직전·직후의 급락이 지수에 반영돼야 생존 편향이 없다).

구성원은 **오늘의 분류를 전 구간에 소급**한다 (`docs/02` §9 "지수 소급 구성"). 폐지 종목이
포함되므로 1998년의 금광 지수에는 그때 상장돼 있던 금광이 들어간다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from msa.config import paths
from msa.data.store import Store, StoreError
from msa.themes import Membership

log = logging.getLogger(__name__)

MIN_PRICE_USD = 1.0
RET_CAP_HI = 3.0
RET_CAP_LO = -0.95
SMA_WINDOW = 200
NH_WINDOW = 126

PANEL_COLUMNS = (
    "ret_ew",
    "ret_cw",
    "n_ret",
    "n_listed",
    "n_cw",
    "dv",
    "mcap_sum",
    "n_sma200",
    "n_above200",
    "n_nh6m",
    "n_nl6m",
    "n_capped",
)


@dataclass(frozen=True)
class ThemePanel:
    """테마 × 일 패널과 SPY 일별 시계열."""

    frame: pd.DataFrame  # index: (date, theme) / columns: PANEL_COLUMNS
    spy: pd.DataFrame  # index: date / columns: close, dv
    built_from: dict[str, Any]

    def wide(self, column: str) -> pd.DataFrame:
        """`column` 을 date × theme 행렬로."""
        if column not in self.frame.columns:
            raise KeyError(f"패널에 없는 컬럼: {column}. 있는 것: {list(self.frame.columns)}")
        return self.frame[column].unstack("theme").sort_index()

    def index_level(self, weighting: str = "ew") -> pd.DataFrame:
        """`P_t` — 수익률 누적 지수 (시작 1.0). 수익률이 NaN 인 날은 지수가 정체한다."""
        col = {"ew": "ret_ew", "cw": "ret_cw"}[weighting]
        r = self.wide(col)
        return (1.0 + r.fillna(0.0)).cumprod().where(r.notna().cummax())

    @property
    def themes(self) -> list[str]:
        return sorted(self.frame.index.get_level_values("theme").unique())

    def summary(self) -> str:
        f = self.frame
        capped = int(f["n_capped"].sum())
        return (
            f"패널: 테마 {len(self.themes)} · {f.index.get_level_values('date').min()} ~ "
            f"{f.index.get_level_values('date').max()} · 행 {len(f):,} · "
            f"상·하한 적용 종목-일 {capped:,}"
        )


def _members_sql(members: pd.DataFrame) -> str:
    return "select ticker, theme from members"


_PANEL_SQL = f"""
with m as (
    select ticker, theme from members
),
px as (
    select p.ticker, m.theme, p.date, p.close, p.closeunadj, p.volume, p.mcap
    from prices p join m using (ticker)
    where p.close is not null
),
w as (
    select
        ticker, theme, date, close, closeunadj, volume, mcap,
        lag(close)      over (partition by ticker order by date) as close_prev,
        lag(closeunadj) over (partition by ticker order by date) as unadj_prev,
        lag(mcap)       over (partition by ticker order by date) as mcap_prev,
        avg(close) over (partition by ticker order by date
                         rows between {SMA_WINDOW - 1} preceding and current row) as sma200,
        count(close) over (partition by ticker order by date
                         rows between {SMA_WINDOW - 1} preceding and current row) as n_hist200,
        max(close) over (partition by ticker order by date
                         rows between {NH_WINDOW - 1} preceding and current row) as hi126,
        min(close) over (partition by ticker order by date
                         rows between {NH_WINDOW - 1} preceding and current row) as lo126,
        count(close) over (partition by ticker order by date
                         rows between {NH_WINDOW - 1} preceding and current row) as n_hist126
    from px
),
r as (
    select *,
        case when close_prev is not null and close_prev > 0 and unadj_prev >= {MIN_PRICE_USD}
             then close / close_prev - 1.0 end as ret_raw
    from w
),
c as (
    select *,
        case when ret_raw is null then null
             when ret_raw > {RET_CAP_HI} then {RET_CAP_HI}
             when ret_raw < {RET_CAP_LO} then {RET_CAP_LO}
             else ret_raw end as ret,
        case when ret_raw is not null and (ret_raw > {RET_CAP_HI} or ret_raw < {RET_CAP_LO})
             then 1 else 0 end as capped
    from r
)
select
    theme, date,
    avg(ret)                                            as ret_ew,
    sum(case when mcap_prev is not null and mcap_prev > 0 and ret is not null
             then ret * mcap_prev end)
      / nullif(sum(case when ret is not null and mcap_prev > 0 then mcap_prev end), 0) as ret_cw,
    count(ret)                                          as n_ret,
    count(*)                                            as n_listed,
    count(case when ret is not null and mcap_prev > 0 then 1 end) as n_cw,
    sum(closeunadj * volume)                            as dv,
    sum(mcap)                                           as mcap_sum,
    count(case when n_hist200 >= {SMA_WINDOW} then 1 end)                      as n_sma200,
    count(case when n_hist200 >= {SMA_WINDOW} and close > sma200 then 1 end)   as n_above200,
    count(case when n_hist126 >= {NH_WINDOW} and close >= hi126 then 1 end)    as n_nh6m,
    count(case when n_hist126 >= {NH_WINDOW} and close <= lo126 then 1 end)    as n_nl6m,
    sum(capped)                                         as n_capped
from c
group by theme, date
order by theme, date
"""

_SPY_SQL = """
select date, close, closeunadj * volume as dv
from prices where ticker = 'SPY' and close is not null order by date
"""


def _fingerprint(members: pd.DataFrame, store_end: date | None) -> str:
    h = hashlib.sha256()
    hashed = pd.util.hash_pandas_object(members[["ticker", "theme"]], index=False)
    h.update(hashed.to_numpy().tobytes())
    h.update(str(store_end).encode())
    h.update(f"{MIN_PRICE_USD}|{RET_CAP_HI}|{RET_CAP_LO}|{SMA_WINDOW}|{NH_WINDOW}".encode())
    return h.hexdigest()[:16]


def build_panel(
    store: Store,
    membership: Membership,
    *,
    cache_dir: Path | None = None,
    force: bool = False,
    threads: int = 4,
    memory_limit: str = "10GB",
) -> ThemePanel:
    """패널을 만든다. 캐시(`state/cache/`)가 있고 지문이 같으면 그것을 읽는다.

    지문 = 구성원 배정 + 스토어 최종일 + 위생 상수. 셋 중 하나라도 바뀌면 다시 만든다.
    """
    members = membership.frame[["ticker", "theme"]].drop_duplicates()
    if members.empty:
        raise StoreError("구성원이 0개다 — 테마 배정이 비었다.")
    store_end = _store_end(store)
    fp = _fingerprint(members, store_end)
    cdir = cache_dir if cache_dir is not None else paths().state / "cache"
    cdir.mkdir(parents=True, exist_ok=True)
    panel_path = cdir / f"l1_panel_{fp}.parquet"
    spy_path = cdir / f"l1_spy_{fp}.parquet"
    meta_path = cdir / f"l1_panel_{fp}.json"
    if not force and panel_path.exists() and spy_path.exists() and meta_path.exists():
        log.info("panel: 캐시 사용 %s", panel_path.name)
        frame = pd.read_parquet(panel_path)
        spy = pd.read_parquet(spy_path)
        built = json.loads(meta_path.read_text())
        return ThemePanel(frame=frame, spy=spy, built_from=built)

    con = store._con
    con.execute(f"set threads = {int(threads)}")
    con.execute(f"set memory_limit = '{memory_limit}'")
    con.register("members", members)
    log.info(
        "panel: 구성원 %d 종목 · 테마 %d — DuckDB 집계 시작",
        len(members),
        members["theme"].nunique(),
    )
    frame = con.execute(_PANEL_SQL).fetch_df()
    con.unregister("members")
    if frame.empty:
        raise StoreError("패널 집계 결과가 0행이다 — prices 와 구성원 티커가 만나지 않는다.")
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index(["date", "theme"]).sort_index()
    for c in (
        "n_ret",
        "n_listed",
        "n_cw",
        "n_sma200",
        "n_above200",
        "n_nh6m",
        "n_nl6m",
        "n_capped",
    ):
        frame[c] = frame[c].fillna(0).astype("int64")
    spy = con.execute(_SPY_SQL).fetch_df()
    if spy.empty:
        raise StoreError("SPY 가 prices 에 없다 — 상대지표를 계산할 수 없다.")
    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.set_index("date").sort_index()

    themes_missing = sorted(set(members["theme"]) - set(frame.index.get_level_values("theme")))
    if themes_missing:
        log.warning(
            "panel: 가격 행이 하나도 없는 테마 %d개: %s", len(themes_missing), themes_missing
        )
    built = {
        "fingerprint": fp,
        "store_end": str(store_end),
        "n_members": len(members),
        "n_themes": int(members["theme"].nunique()),
        "themes_without_prices": themes_missing,
        "min_price_usd": MIN_PRICE_USD,
        "ret_cap": [RET_CAP_LO, RET_CAP_HI],
        "n_capped_total": int(frame["n_capped"].sum()),
        "rows": len(frame),
    }
    frame.to_parquet(panel_path)
    spy.to_parquet(spy_path)
    meta_path.write_text(json.dumps(built, ensure_ascii=False, indent=1))
    log.info("panel: 저장 %s (%d행)", panel_path.name, len(frame))
    return ThemePanel(frame=frame, spy=spy, built_from=built)


def _store_end(store: Store) -> date | None:
    row = store._con.execute("select max(date) from prices").fetchone()
    return row[0] if row else None


def panel_from_frames(frame: pd.DataFrame, spy: pd.DataFrame) -> ThemePanel:
    """테스트·합성 데이터용 — 이미 만들어진 프레임으로 패널 객체를 만든다."""
    need = set(PANEL_COLUMNS)
    missing = need - set(frame.columns)
    if missing:
        raise KeyError(f"패널 컬럼 누락: {sorted(missing)}")
    if list(frame.index.names) != ["date", "theme"]:
        raise KeyError("frame 의 인덱스는 (date, theme) 여야 한다")
    return ThemePanel(
        frame=frame.sort_index(), spy=spy.sort_index(), built_from={"synthetic": True}
    )


def register_duckdb(path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=True)
