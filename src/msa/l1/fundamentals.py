"""테마 × 월말 재무 집계 — D(밸류)·E(자본사이클)·F(펀더멘털) 블록의 재료.

**PIT 는 `datekey` 다** (`CLAUDE.md` PIT 규약). 월말 `t` 에서 각 구성원의 "그때 알려진 최신 분기"
= `datekey ≤ t` 인 가장 최근 행이며, 같은 `calendardate` 가 여러 `datekey` 로 다시 보고된 경우
**최초 보고분(가장 이른 `datekey`)만** 쓴다 — 정정치를 소급 적용하면 자기이력 백분위가 왜곡된다.
오늘의 스캔 경로에서도 같은 규칙을 쓴다 — 스냅샷 지표(부채비율)는 정정치가 더 정확하지만
(`CLAUDE.md` PIT 표), 한 모듈 안에서 두 규칙을 섞으면 몇 달 뒤 조용히 섞인다. 경로별 분기는
하지 않고 **더 엄격한 쪽(PIT)으로 통일**한다. 이 선택을 여기 적어 둔다.

## 단위·부호 (Sharadar SF1 실측)
- `capex` 는 **음수**(현금 유출) → `abs()`. `depamor` 는 양수.
- `dimension` 은 `ARQ` 뿐이다. TTM 은 직전 4개 분기의 합이며 4개가 **전부 있고**
  4번째가 현재 분기로부터 400일 이내일 때만 유효하다 (결측 분기를 0 으로 더하지 않는다).
- 월말 가격(`mcap`·`ev`)은 `prices` 의 그 달 마지막 행이다.

## 동일 구성원(same-store) — `docs/04-value-trap.md` 축 1 규정 1~3
`rev_ss10_t1 / rev_ss10_t0` 는 `t` 와 `t−10y` **양쪽에 TTM 매출이 있는** 기업만 합산한 비율이다.
`ss10_n`·`ss10_coverage`(= `ss10_n / n_reporting(t0)`) 를 함께 돌려준다 — 표기 없으면 조용한 절단.
`ss10_ratio_med` 는 기업당 비율의 중앙값이다. 5년(`ss5_*`)도 같다. 가격지수 나눗셈은 여기서
하지 않는다 — 가격지수는 외부 데이터라 `msa.l1.physical` 이 테마 단위로 적용한다.
`ss10_ma_n` 은 동일 구성원 중 구간 안에 `acquisitionof` 액션이 1건 이상 있는 기업 수다 —
`ma_flag` 의 재료이며, "유의미한" 인수의 기준이 없으므로 **건수 1 이상이면 표시**한다(보수적).

## 적자 기업 처리 (`docs/02` §D)
`ev_ebitda_med` 는 `ebitda_ttm > 0` 인 기업만 중앙값에 넣고, 제외 비율을 `ebitda_nonpos_share`
로 **반드시 돌려준다.** `pb`·`ev_sales` 는 전 기업 포함(분모 > 0 인 한).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property
from typing import Any, cast

import pandas as pd

from msa.data.pit import (
    L1_TTM_FIELDS,
    first_reported_quarterly_sql,
    ttm_valid_replace_sql,
    ttm_window_sql,
)
from msa.data.store import ENTRY_ACTIONS, EXIT_ACTIONS, Store, StoreError
from msa.dates import month_ends
from msa.themes import Membership

log = logging.getLogger(__name__)

TTM_MAX_SPAN_DAYS = 400
STALE_MONTHS = 15  # 월말 t 에서 calendardate 가 이보다 오래된 분기는 "모른다" 로 취급

FUND_COLUMNS = (
    "n_reporting",
    "n_ebitda_pos",
    "ebitda_nonpos_share",
    "ev_ebitda_med",
    "ev_sales_med",
    "pb_med",
    "fcf_yield_med",
    "ev_replacement_med",
    "capex_ttm_sum",
    "da_ttm_sum",
    "assets_sum",
    "revenue_ttm_sum",
    "ebitda_ttm_sum",
    "ebit_ttm_sum",
    "taxexp_ttm_sum",
    "netinc_ttm_sum",
    "invcap_sum",
    "debt_sum",
    "cash_sum",
    "assets_ss",
    "assets_prev_ss",
    "n_assets_ss",
    "shares_ss",
    "shares_prev3y_ss",
    "n_shares_ss",
    "revenue_ss",
    "revenue_prev_ss",
    "n_revenue_ss",
    "ebitda_ss",
    "ebitda_prev_ss",
    "revenue_for_ebitda_ss",
    "revenue_prev_for_ebitda_ss",
)


@dataclass(frozen=True)
class FundPanel:
    """월말 × 테마 재무 집계 + 동일 구성원 비율 + 액션 카운트."""

    frame: pd.DataFrame  # index (date, theme) — FUND_COLUMNS
    same_store: pd.DataFrame  # index (date, theme) — ss10_*, ss5_*
    actions: pd.DataFrame  # index (date, theme) — exits_36m, entries_36m
    built_from: dict[str, Any]

    @cached_property
    def _wides(self) -> tuple[pd.DataFrame, ...]:
        """세 표를 각각 한 번만 unstack 한 (date × (column, theme)) 행렬 — `wide()` 가 골라 쓴다."""
        return tuple(
            cast(pd.DataFrame, src.unstack("theme")).sort_index()
            for src in (self.frame, self.same_store, self.actions)
        )

    def wide(self, column: str) -> pd.DataFrame:
        for w in self._wides:
            if column in w.columns.get_level_values(0):
                out = cast(pd.DataFrame, w[column])
                out.columns.name = "theme"
                return out
        raise KeyError(f"재무 패널에 없는 컬럼: {column}")


_QUARTERLY_SQL = f"""
create or replace temp table q_ttm as
with m as (select ticker, theme from members),
{
    first_reported_quarterly_sql(
        "f.ticker, m.theme, f.calendardate, f.datekey, "
        "f.revenue, f.capex, f.depamor, f.assets, f.ebitda, f.ebit, f.netinc, f.taxexp, "
        "f.debt, f.cashneq, f.sharesbas, f.equity, f.intangibles, f.invcap, f.fcf",
        from_clause="fundamentals f join m using (ticker)",
    )
},
ttm as (
    select *,
{ttm_window_sql(L1_TTM_FIELDS)},
        lag(calendardate, 3) over wt as cd_3back
    from q
    window w4 as (partition by ticker order by calendardate
                  rows between 3 preceding and current row),
           wt as (partition by ticker order by calendardate)
),
valid as (
    select * replace (
        {ttm_valid_replace_sql(L1_TTM_FIELDS, TTM_MAX_SPAN_DAYS)}
    ) from ttm
)
select *,
    lag(revenue_ttm, 4) over wt as revenue_ttm_prev,
    lag(calendardate, 4) over wt as cd_prev4,
    lag(assets, 4) over wt as assets_prev,
    lag(ebitda_ttm, 4) over wt as ebitda_ttm_prev,
    lag(sharesbas, 12) over wt as shares_prev3y,
    lag(calendardate, 12) over wt as cd_prev12
from valid
window wt as (partition by ticker order by calendardate)
"""

_GRID_SQL = f"""
create or replace temp table grid as
with m as (select ticker, theme from members),
me as (select me, bucket from month_ends),
g as (select m.ticker, m.theme, me.me, me.bucket from m cross join me),
aj as (
    select g.ticker, g.theme, g.me, g.bucket, q.calendardate, q.datekey,
           q.revenue_ttm, q.capex_ttm, q.da_ttm, q.assets, q.ebitda_ttm, q.ebit_ttm, q.netinc_ttm,
           q.taxexp_ttm, q.debt, q.cashneq, q.sharesbas, q.equity, q.intangibles, q.invcap,
           q.fcf_ttm, q.revenue_ttm_prev, q.cd_prev4, q.assets_prev, q.ebitda_ttm_prev,
           q.shares_prev3y, q.cd_prev12
    from g asof join q_ttm q
      on g.ticker = q.ticker and q.datekey <= g.me
),
fresh as (
    select * from aj
    where calendardate >= me - interval {STALE_MONTHS} month
),
mp as (
    select ticker, last_day(date) as me, mcap, ev
    from (
        select ticker, date, mcap, ev,
               row_number() over (partition by ticker, date_trunc('month', date)
                                  order by date desc) as rn
        from prices p
        where ticker in (select ticker from members)
    ) where rn = 1
)
select f.*, mp.mcap, mp.ev
from fresh f left join mp on f.ticker = mp.ticker and f.bucket = mp.me
"""

_AGG_SQL = """
select
    theme, bucket as date,
    count(*) as n_reporting,
    count(case when ebitda_ttm > 0 then 1 end) as n_ebitda_pos,
    1.0 - count(case when ebitda_ttm > 0 then 1 end)
          / nullif(count(case when ebitda_ttm is not null then 1 end), 0) as ebitda_nonpos_share,
    median(case when ebitda_ttm > 0 and ev > 0 then ev / ebitda_ttm end) as ev_ebitda_med,
    median(case when revenue_ttm > 0 and ev > 0 then ev / revenue_ttm end) as ev_sales_med,
    median(case when equity > 0 and mcap > 0 then mcap / equity end) as pb_med,
    median(case when mcap > 0 and fcf_ttm is not null then fcf_ttm / mcap end) as fcf_yield_med,
    median(case when (equity - coalesce(intangibles, 0)) > 0 and ev > 0
                then ev / (equity - coalesce(intangibles, 0)) end) as ev_replacement_med,
    sum(capex_ttm) as capex_ttm_sum,
    sum(case when capex_ttm is not null then da_ttm end) as da_ttm_sum,
    sum(assets) as assets_sum,
    sum(revenue_ttm) as revenue_ttm_sum,
    sum(ebitda_ttm) as ebitda_ttm_sum,
    sum(ebit_ttm) as ebit_ttm_sum,
    sum(taxexp_ttm) as taxexp_ttm_sum,
    sum(netinc_ttm) as netinc_ttm_sum,
    sum(case when ebit_ttm is not null then invcap end) as invcap_sum,
    sum(debt) as debt_sum,
    sum(cashneq) as cash_sum,
    sum(case when assets_prev is not null then assets end) as assets_ss,
    sum(case when assets is not null then assets_prev end) as assets_prev_ss,
    count(case when assets is not null and assets_prev is not null then 1 end) as n_assets_ss,
    sum(case when shares_prev3y is not null then sharesbas end) as shares_ss,
    sum(case when sharesbas is not null then shares_prev3y end) as shares_prev3y_ss,
    count(case when sharesbas is not null and shares_prev3y is not null then 1 end) as n_shares_ss,
    sum(case when revenue_ttm_prev is not null then revenue_ttm end) as revenue_ss,
    sum(case when revenue_ttm is not null then revenue_ttm_prev end) as revenue_prev_ss,
    count(case when revenue_ttm is not null and revenue_ttm_prev is not null then 1 end)
        as n_revenue_ss,
    sum(case when ebitda_ttm_prev is not null and revenue_ttm_prev is not null
                  and revenue_ttm is not null then ebitda_ttm end) as ebitda_ss,
    sum(case when ebitda_ttm is not null and revenue_ttm_prev is not null
                  and revenue_ttm is not null then ebitda_ttm_prev end) as ebitda_prev_ss,
    sum(case when ebitda_ttm is not null and ebitda_ttm_prev is not null
                  and revenue_ttm_prev is not null then revenue_ttm end) as revenue_for_ebitda_ss,
    sum(case when ebitda_ttm is not null and ebitda_ttm_prev is not null
                  and revenue_ttm is not null then revenue_ttm_prev end)
        as revenue_prev_for_ebitda_ss
from grid
group by theme, bucket
order by theme, bucket
"""


def _ss_sql(years: int) -> str:
    months = years * 12
    tag = f"ss{years}"
    return f"""
    with a as (select ticker, theme, bucket, revenue_ttm from grid where revenue_ttm > 0),
         b as (select ticker, bucket, revenue_ttm from grid where revenue_ttm > 0),
         j as (
            select a.theme, a.bucket, a.ticker, a.revenue_ttm as rev_t1, b.revenue_ttm as rev_t0
            from a join b on a.ticker = b.ticker
                         and b.bucket = last_day(a.bucket - interval {months} month)
         ),
         ma as (
            select j.theme, j.bucket, j.ticker
            from j join actions x on x.ticker = j.ticker
            where x.action = 'acquisitionof'
              and x.date > j.bucket - interval {months} month and x.date <= j.bucket
            group by j.theme, j.bucket, j.ticker
         ),
         mac as (select theme, bucket, count(*) as ma_n from ma group by theme, bucket),
         n0 as (
            select theme, last_day(bucket + interval {months} month) as bucket, count(*) as n_t0
            from grid where revenue_ttm > 0 group by theme, bucket
         )
    select j.theme, j.bucket as date,
           sum(j.rev_t1) as {tag}_rev_t1,
           sum(j.rev_t0) as {tag}_rev_t0,
           median(j.rev_t1 / j.rev_t0) as {tag}_ratio_med,
           count(*) as {tag}_n,
           any_value(n0.n_t0) as {tag}_n_t0,
           count(*) / nullif(any_value(n0.n_t0), 0) as {tag}_coverage,
           coalesce(any_value(mac.ma_n), 0) as {tag}_ma_n
    from j left join n0 on n0.theme = j.theme and n0.bucket = j.bucket
           left join mac on mac.theme = j.theme and mac.bucket = j.bucket
    group by j.theme, j.bucket
    order by j.theme, j.bucket
    """


_ACTIONS_SQL = """
select m.theme, last_day(a.date) as date,
       count(case when a.action in ({exits}) then 1 end) as exits,
       count(case when a.action in ({entries}) then 1 end) as entries
from actions a join members m using (ticker)
where a.action in ({exits}, {entries})
group by m.theme, last_day(a.date)
order by 1, 2
"""


def grid_dates(start: str | pd.Timestamp, end: str | pd.Timestamp) -> pd.DataFrame:
    """asof 날짜(`me`)와 월 버킷 라벨(`bucket` = 그 달 월말). `end` 가 월말이 아니면 **부분 월**을
    `me=end, bucket=end 의 월말` 로 한 행 더 둔다 — 오늘의 스캔이 지난 월말이 아니라 최신
    데이터로 돈다."""
    mes = month_ends(start, end)
    rows = [(d, d) for d in mes]
    e = pd.Timestamp(end)
    if len(mes) == 0 or mes[-1] < e:
        rows.append((e, e + pd.offsets.MonthEnd(0)))
    df = pd.DataFrame(rows, columns=["me", "bucket"])
    df["me"] = df["me"].dt.date
    df["bucket"] = df["bucket"].dt.date
    return df


def build_fund_panel(
    store: Store,
    membership: Membership,
    *,
    start: str = "1998-01-31",
    end: str | None = None,
) -> FundPanel:
    """테마 × 월말 재무 패널을 만든다. 캐시는 `scan` 계층이 맡는다 (이 함수는 항상 계산한다)."""
    members = membership.frame[["ticker", "theme"]].drop_duplicates()
    if members.empty:
        raise StoreError("구성원이 0개다.")
    if end is None:
        se = store.store_end()
        end = str(se) if se else pd.Timestamp.today().strftime("%Y-%m-%d")
    mes = grid_dates(start, end)
    try:
        with store.temp_tables(members=members, month_ends=mes):
            log.info("fund: 분기 TTM 테이블 생성")
            store.execute(_QUARTERLY_SQL)
            log.info("fund: 월말 × 구성원 asof 그리드 생성")
            store.execute(_GRID_SQL)
            n_grid = int(store.scalar("select count(*) from grid"))
            log.info("fund: 그리드 %s행 → 테마 집계", f"{n_grid:,}")
            agg = store.query(_AGG_SQL)
            ss10 = store.query(_ss_sql(10))
            ss5 = store.query(_ss_sql(5))
            exits = ",".join(f"'{a}'" for a in EXIT_ACTIONS)
            entries = ",".join(f"'{a}'" for a in ENTRY_ACTIONS)
            acts = store.query(_ACTIONS_SQL.format(exits=exits, entries=entries))
    finally:
        store.execute("drop table if exists grid")
        store.execute("drop table if exists q_ttm")
    if agg.empty:
        raise StoreError("재무 집계 결과가 0행이다 — fundamentals 와 구성원이 만나지 않는다.")

    def _idx(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index(["date", "theme"]).sort_index()

    agg = _idx(agg)
    ss = _idx(ss10).join(_idx(ss5), how="outer") if not ss10.empty else _idx(ss5)

    # 액션: 월별 카운트 → 전 월말 격자로 펼친 뒤 36개월 이동합
    all_me = pd.DatetimeIndex(pd.to_datetime(mes["bucket"]))
    themes = sorted(members["theme"].unique())
    acts["date"] = pd.to_datetime(acts["date"])
    ex = acts.pivot_table(index="date", columns="theme", values="exits", aggfunc="sum")
    en = acts.pivot_table(index="date", columns="theme", values="entries", aggfunc="sum")
    ex = ex.reindex(index=all_me, columns=themes).fillna(0.0)
    en = en.reindex(index=all_me, columns=themes).fillna(0.0)
    # 부분 월 버킷의 1m 카운트는 그 달의 실제 액션(라벨이 월말이므로 월 전체가 잡힌다 —
    # 미래 며칠 포함 가능성은 store_end 이후 액션이 스토어에 없으므로 실제로는 없다)
    ex36 = ex.rolling(36, min_periods=1).sum()
    en36 = en.rolling(36, min_periods=1).sum()
    actions = pd.concat(
        {
            "exits_36m": ex36.stack(),
            "entries_36m": en36.stack(),
            "exits_1m": ex.stack(),
            "entries_1m": en.stack(),
        },
        axis=1,
    )
    actions.index.names = ["date", "theme"]

    built = {
        "start": start,
        "end": str(end),
        "n_members": len(members),
        "grid_rows": int(n_grid),
        "stale_months": STALE_MONTHS,
        "ttm_max_span_days": TTM_MAX_SPAN_DAYS,
        "pit": "datekey, first-reported",
    }
    return FundPanel(frame=agg, same_store=ss, actions=actions.sort_index(), built_from=built)
