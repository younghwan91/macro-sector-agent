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
| `dv` | Σ `close × volume` — 달러 거래대금. `volume` 이 소급 분할조정이라 **조정** 종가와 곱한다 |
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
import logging
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Any, cast

import pandas as pd

from msa.data.store import Store, StoreError
from msa.l1.cache import FingerprintCache, newest_fingerprint
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

    @cached_property
    def _wide_all(self) -> pd.DataFrame:
        """전 컬럼을 한 번에 unstack 한 (date × (column, theme)) 행렬 — `wide()` 가 잘라 쓴다."""
        return cast(pd.DataFrame, self.frame.unstack("theme")).sort_index()

    def wide(self, column: str) -> pd.DataFrame:
        """`column` 을 date × theme 행렬로."""
        if column not in self.frame.columns:
            raise KeyError(f"패널에 없는 컬럼: {column}. 있는 것: {list(self.frame.columns)}")
        out = cast(pd.DataFrame, self._wide_all[column])
        out.columns.name = "theme"
        return out

    @cached_property
    def _level_ew(self) -> pd.DataFrame:
        return self._cum_index("ret_ew")

    @cached_property
    def _level_cw(self) -> pd.DataFrame:
        return self._cum_index("ret_cw")

    def _cum_index(self, col: str) -> pd.DataFrame:
        r = self.wide(col)
        return (1.0 + r.fillna(0.0)).cumprod().where(r.notna().cummax())

    def index_level(self, weighting: str = "ew") -> pd.DataFrame:
        """`P_t` — 수익률 누적 지수 (시작 1.0). 수익률이 NaN 인 날은 지수가 정체한다.

        가중 방식별로 한 번만 계산해 둔다 (`compute_indicators`·백테스트가 여러 번 부른다)."""
        return {"ew": self._level_ew, "cw": self._level_cw}[weighting]

    def save(self, cache_dir: Path | None = None) -> FingerprintCache:
        """`state/cache/l1_panel_<지문>.parquet` · `l1_spy_…` · `l1_panel_….json` 으로 쓴다."""
        fc = FingerprintCache.at(self.built_from["fingerprint"], cache_dir)
        self.frame.to_parquet(fc.panel)
        self.spy.to_parquet(fc.spy)
        fc.write_meta(fc.panel_meta, self.built_from)
        log.info("panel: 저장 %s (%d행)", fc.panel.name, len(self.frame))
        return fc


def load_cached_panel(cache_dir: Path | None = None, fingerprint: str | None = None) -> ThemePanel:
    """캐시된 패널을 읽는다. `fingerprint=None` 이면 수정시각이 가장 최근인 패널.

    세 파일(frame·spy·json) 중 하나라도 없으면 `StoreError` — 다른 계층(L5·ops)이 스토어 없이
    테마 지수를 쓸 때의 진입점이다.
    """
    fc = FingerprintCache.at(fingerprint or "", cache_dir)
    if fingerprint is None:
        fp = newest_fingerprint(fc.cache_dir)
        if fp is None:
            raise StoreError(f"캐시된 L1 패널이 없다: {fc.cache_dir} (먼저 `msa scan` 을 돌려라)")
        fc = FingerprintCache(fc.cache_dir, fp)
    if not fc.has(fc.panel, fc.spy, fc.panel_meta):
        raise StoreError(f"L1 패널 캐시가 불완전하다: {fc.panel} (frame·spy·json 셋 다 필요)")
    log.info("panel: 캐시 사용 %s", fc.panel.name)
    return ThemePanel(
        frame=fc.read_frame(fc.panel),
        spy=fc.read_frame(fc.spy),
        built_from=fc.read_meta(fc.panel_meta),
    )


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
    -- `volume` 은 소급 분할조정 값이므로 조정 종가 `close` 와 곱해야 한다. 비조정
    -- `closeunadj` 와 곱하면 asof 이후의 분할 계수만큼 틀리고, 그것은 미래를 보는 것이다
    -- (2026-08-24 · `l4/features.py` `adv20_usd` 가 2026-08-23 에 같은 이유로 고쳐졌다).
    sum(close * volume)                                 as dv,
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
-- dv 는 조정 종가 × 소급 분할조정 거래량 (테마 패널의 `dv` 와 같은 이유 — 위 주석 참조).
select date, close, close * volume as dv
from prices where ticker = 'SPY' and close is not null order by date
"""


def _panel_code_version() -> str:
    """집계 코드 자체의 버전 — 패널·SPY·재무 SQL 본문의 해시.

    지문에 상수만 넣으면 **SQL 을 고쳐도 옛 캐시를 그대로 읽는다** (2026-08-24 `dv` 수정이
    그 사례였다). 임계값이 아니라 캐시 위생이므로 §1 의 "새 값 발명" 에 해당하지 않는다.

    재무 SQL 까지 넣는 이유: 세 캐시(패널·재무·지표)가 **같은 지문 접미어**를 쓴다
    (`l1/cache.py`). 재무 캐시는 파일 존재만 보므로 지문이 안 바뀌면 옛 parquet 을 읽는다.
    """
    from msa.l1 import fundamentals as f

    parts = (
        _PANEL_SQL,
        _SPY_SQL,
        f._QUARTERLY_SQL,
        f._GRID_SQL,
        f._AGG_SQL,
        f._ACTIONS_SQL,
        f._ss_sql(10),
        f._ss_sql(5),
    )
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:12]


def _fingerprint(members: pd.DataFrame, store_end: date | None) -> str:
    h = hashlib.sha256()
    hashed = pd.util.hash_pandas_object(members[["ticker", "theme"]], index=False)
    h.update(hashed.to_numpy().tobytes())
    h.update(str(store_end).encode())
    h.update(f"{MIN_PRICE_USD}|{RET_CAP_HI}|{RET_CAP_LO}|{SMA_WINDOW}|{NH_WINDOW}".encode())
    h.update(_panel_code_version().encode())
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

    지문 = 구성원 배정 + 스토어 최종일 + 위생 상수 + **집계 SQL 본문 해시**.
    넷 중 하나라도 바뀌면 다시 만든다 — SQL 을 고치면 캐시가 자동으로 무효화된다.
    """
    members = membership.frame[["ticker", "theme"]].drop_duplicates()
    if members.empty:
        raise StoreError("구성원이 0개다 — 테마 배정이 비었다.")
    store_end = store.store_end()
    fp = _fingerprint(members, store_end)
    fc = FingerprintCache.at(fp, cache_dir)
    if not force and fc.has(fc.panel, fc.spy, fc.panel_meta):
        return load_cached_panel(fc.cache_dir, fp)

    store.configure(threads=threads, memory_limit=memory_limit)
    log.info(
        "panel: 구성원 %d 종목 · 테마 %d — DuckDB 집계 시작",
        len(members),
        members["theme"].nunique(),
    )
    frame = store.query(_PANEL_SQL, frames={"members": members})
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
    spy = store.query(_SPY_SQL)
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
    panel = ThemePanel(frame=frame, spy=spy, built_from=built)
    panel.save(fc.cache_dir)
    return panel


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
