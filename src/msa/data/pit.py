"""PIT(point-in-time) 분기 재무와 TTM 의 **단일 구현** — SQL 조각과 pandas 두 경로.

`CLAUDE.md` PIT 규약의 구현이 L1(`fundamentals`)·L3(`contracts`)·L4(`features`) 에
세 번 있었다 (제거된 L2 `sources` 까지 네 번). 규칙은 하나다:

1. **최초 보고분** — 같은 `(ticker, calendardate)` 가 여러 `datekey` 로 다시 보고되면 가장 이른
   `datekey` 행만 쓴다 (`row_number() over (partition by ticker, calendardate order by datekey)
   = 1`). 정정치를 소급 적용하면 자기이력 백분위가 왜곡된다.
2. **TTM** = 직전 4개 분기의 합. 4개가 **전부 있고** 4번째(`cd_3back`)가 현재 분기로부터
   `span_days` 이내일 때만 유효하다 — 결측 분기를 0 으로 더하지 않는다.
3. **신선도** — 기준일에서 `stale_months` 보다 오래된 최신 분기는 "모른다" 로 취급한다.

`span_days`·`stale_months` 는 **호출자가 넘긴다** — L1 은 400일, L4 는 300일을 쓰며 그 차이는
각 모듈의 구현 노트에 근거가 있다. 여기서는 기본값을 두지 않는다 (값이 한 곳으로 조용히
수렴하는 것을 막는다).

`ttm_window_sql` 이 만드는 텍스트는 `l1/fundamentals._QUARTERLY_SQL` 이 손으로 적었던 것과
같은 문장이다 (공백만 다르다) — `tests/test_pit.py` 가 실제 스토어로 두 결과를 대조한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import numpy as np
import pandas as pd

#: 최초 보고분 판별 창 — `first_reported_quarterly_sql` 과 `pit_quarterly` 가 같은 키를 쓴다.
PIT_KEY = ("ticker", "calendardate")


class TtmField(NamedTuple):
    """TTM 한 항목의 SQL 철자.

    `col` 은 `count()` 대상(결측 판정), `expr` 은 `sum()` 대상(`abs(capex)` 처럼 변환이 붙는다),
    `out`/`n` 은 결과 컬럼 이름이다 — L1 이 쓰는 이름(`da_ttm`·`n_rev4`)을 그대로 둔다.
    """

    col: str
    expr: str
    out: str
    n: str


#: L1 `fundamentals` 가 쓰는 8개 항목 — 순서·이름 그대로.
L1_TTM_FIELDS: tuple[TtmField, ...] = (
    TtmField("revenue", "revenue", "revenue_ttm", "n_rev4"),
    TtmField("capex", "abs(capex)", "capex_ttm", "n_capex4"),
    TtmField("depamor", "depamor", "da_ttm", "n_da4"),
    TtmField("ebitda", "ebitda", "ebitda_ttm", "n_ebitda4"),
    TtmField("ebit", "ebit", "ebit_ttm", "n_ebit4"),
    TtmField("netinc", "netinc", "netinc_ttm", "n_netinc4"),
    TtmField("taxexp", "taxexp", "taxexp_ttm", "n_tax4"),
    TtmField("fcf", "fcf", "fcf_ttm", "n_fcf4"),
)

#: L3 `contracts.members_from_store` 가 쓰는 앞 4개.
L3_TTM_FIELDS: tuple[TtmField, ...] = L1_TTM_FIELDS[:4]


# ---------------------------------------------------------------- SQL 조각


def first_reported_quarterly_sql(
    select_list: str,
    *,
    from_clause: str = "fundamentals f",
    where_extra: str = "",
) -> str:
    """`q0`(최초 보고분 번호 매김)·`q`(rn=1) 두 CTE 본문. `with … ,` 안에 끼워 넣는다.

    `select_list` 는 `f.` 접두어가 붙은 컬럼 목록(`"f.ticker, f.calendardate, f.datekey, …"`),
    `where_extra` 는 `" and f.datekey <= '…'"` 처럼 `and` 로 시작하는 추가 조건이다.
    """
    return f"""q0 as (
    select {select_list},
           row_number() over (partition by f.ticker, f.calendardate order by f.datekey) as rn
    from {from_clause}
    where f.dimension = 'ARQ' and f.datekey is not null and f.calendardate is not null{where_extra}
),
q as (select * exclude (rn) from q0 where rn = 1)"""


def ttm_window_sql(fields: Sequence[TtmField] = L1_TTM_FIELDS) -> str:
    """`select *, <여기>, lag(calendardate, 3) over wt as cd_3back from q …` 의 합·개수 열.

    `w4` 는 호출자가 `window w4 as (partition by ticker order by calendardate rows between
    3 preceding and current row)` 로 선언한다.
    """
    return ",\n".join(
        f"        sum({f.expr}) over w4 as {f.out}, count({f.col}) over w4 as {f.n}" for f in fields
    )


def ttm_valid_case_sql(field: TtmField, span_days: int) -> str:
    """한 항목의 유효성 조건 — 4분기 전부 있고 4번째가 `span_days` 이내."""
    return (
        f"case when {field.n} = 4 and cd_3back >= calendardate - interval {span_days} day\n"
        f"             then {field.out} end as {field.out}"
    )


def ttm_valid_replace_sql(fields: Sequence[TtmField], span_days: int) -> str:
    """`select * replace (<여기>) from ttm` 의 괄호 안 — 항목별 유효성 case 목록."""
    return ",\n        ".join(ttm_valid_case_sql(f, span_days) for f in fields)


# ---------------------------------------------------------------- pandas


def pit_quarterly(fund: pd.DataFrame, asof: pd.Timestamp | str | None) -> pd.DataFrame:
    """`datekey ≤ asof` · ARQ · 같은 `calendardate` 는 최초 보고분만. ticker·calendardate 오름차순.

    입력 열: ticker, calendardate, datekey, [dimension], + 재무 필드. 순수 함수.
    `asof=None` 이면 `datekey` 상한을 두지 않는다 (백테스트용 전체 이력 — 최초 보고분 규칙만 적용).
    """
    need = {"ticker", "calendardate", "datekey"}
    if missing := need - set(fund.columns):
        raise KeyError(f"fundamentals 에 없는 열: {sorted(missing)}")
    q = fund.copy()
    q["calendardate"] = pd.to_datetime(q["calendardate"])
    q["datekey"] = pd.to_datetime(q["datekey"])
    if "dimension" in q.columns:
        q = q.loc[q["dimension"] == "ARQ"]
    if asof is not None:
        q = q.loc[q["datekey"] <= pd.Timestamp(asof)]
    q = q.dropna(subset=["calendardate", "datekey"])
    q = q.sort_values(["ticker", "calendardate", "datekey"])
    q = q.drop_duplicates(list(PIT_KEY), keep="first")
    return q.reset_index(drop=True)


def add_ttm(q: pd.DataFrame, fields: Sequence[str], *, span_days: int) -> pd.DataFrame:
    """분기 표(`pit_quarterly` 출력)에 `<field>_ttm` 을 붙인다.

    4개 분기 전부 있고(`count == 4`) 4번째가 `span_days` 이내일 때만 값, 아니면 NaN.
    `fields` 중 표에 없는 열은 전부 NaN 인 `<field>_ttm` 으로 남긴다 — 열 자체를 빼면 하류가
    KeyError 대신 조용히 건너뛴다.
    """
    out = q.copy()
    g = out.groupby("ticker", sort=False)
    cd3 = g["calendardate"].shift(3)
    span_ok = cd3 >= out["calendardate"] - pd.Timedelta(days=span_days)
    for f in fields:
        if f not in out.columns:
            out[f"{f}_ttm"] = np.nan
            continue
        s = g[f].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
        n = g[f].rolling(4, min_periods=1).count().reset_index(level=0, drop=True)
        out[f"{f}_ttm"] = s.where((n == 4) & span_ok)
    return out


def latest_fresh_rows(
    qt: pd.DataFrame, asof: pd.Timestamp | str, *, stale_months: int
) -> pd.DataFrame:
    """ticker 별 최신 분기 중 `calendardate ≥ asof − stale_months` 인 것. index ticker."""
    last = qt.groupby("ticker", sort=False).tail(1).set_index("ticker")
    fresh = last["calendardate"] >= pd.Timestamp(asof) - pd.DateOffset(months=stale_months)
    return last.loc[fresh]
