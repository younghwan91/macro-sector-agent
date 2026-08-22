"""`msa.data.pit` — PIT/TTM 단일 구현.

순수 부분: SQL 조각이 L1 이 손으로 적었던 문장과 같은지(공백 제외), pandas 경로의 규칙.
`@pytest.mark.data`: 실제 스토어로 L1 재무 패널을 다시 만들어 **옛 SQL 로 만든 캐시와 대조**한다.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from msa.data import pit

# ------------------------------------------------ SQL 조각 (골든 = 옮기기 전 L1 문장)

_OLD_L1_TTM_BLOCK = """
        sum(revenue) over w4 as revenue_ttm, count(revenue) over w4 as n_rev4,
        sum(abs(capex)) over w4 as capex_ttm, count(capex) over w4 as n_capex4,
        sum(depamor) over w4 as da_ttm, count(depamor) over w4 as n_da4,
        sum(ebitda) over w4 as ebitda_ttm, count(ebitda) over w4 as n_ebitda4,
        sum(ebit) over w4 as ebit_ttm, count(ebit) over w4 as n_ebit4,
        sum(netinc) over w4 as netinc_ttm, count(netinc) over w4 as n_netinc4,
        sum(taxexp) over w4 as taxexp_ttm, count(taxexp) over w4 as n_tax4,
        sum(fcf) over w4 as fcf_ttm, count(fcf) over w4 as n_fcf4
"""

_OLD_L1_VALID_BLOCK = """
        case when n_rev4 = 4 and cd_3back >= calendardate - interval 400 day
             then revenue_ttm end as revenue_ttm,
        case when n_capex4 = 4 and cd_3back >= calendardate - interval 400 day
             then capex_ttm end as capex_ttm,
        case when n_da4 = 4 and cd_3back >= calendardate - interval 400 day
             then da_ttm end as da_ttm,
        case when n_ebitda4 = 4 and cd_3back >= calendardate - interval 400 day
             then ebitda_ttm end as ebitda_ttm,
        case when n_ebit4 = 4 and cd_3back >= calendardate - interval 400 day
             then ebit_ttm end as ebit_ttm,
        case when n_netinc4 = 4 and cd_3back >= calendardate - interval 400 day
             then netinc_ttm end as netinc_ttm,
        case when n_tax4 = 4 and cd_3back >= calendardate - interval 400 day
             then taxexp_ttm end as taxexp_ttm,
        case when n_fcf4 = 4 and cd_3back >= calendardate - interval 400 day
             then fcf_ttm end as fcf_ttm
"""

_OLD_L1_Q_BLOCK = """
q0 as (
    select f.ticker, m.theme, f.calendardate, f.datekey,
           f.revenue, f.capex, f.depamor, f.assets, f.ebitda, f.ebit, f.netinc, f.taxexp,
           f.debt, f.cashneq, f.sharesbas, f.equity, f.intangibles, f.invcap, f.fcf,
           row_number() over (partition by f.ticker, f.calendardate order by f.datekey) as rn
    from fundamentals f join m using (ticker)
    where f.dimension = 'ARQ' and f.datekey is not null and f.calendardate is not null
),
q as (select * exclude (rn) from q0 where rn = 1)
"""


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_ttm_window_sql_equals_old_l1_text() -> None:
    assert _norm(pit.ttm_window_sql(pit.L1_TTM_FIELDS)) == _norm(_OLD_L1_TTM_BLOCK)


def test_ttm_valid_replace_sql_equals_old_l1_text() -> None:
    assert _norm(pit.ttm_valid_replace_sql(pit.L1_TTM_FIELDS, 400)) == _norm(_OLD_L1_VALID_BLOCK)


def test_first_reported_quarterly_sql_equals_old_l1_text() -> None:
    got = pit.first_reported_quarterly_sql(
        "f.ticker, m.theme, f.calendardate, f.datekey, "
        "f.revenue, f.capex, f.depamor, f.assets, f.ebitda, f.ebit, f.netinc, f.taxexp, "
        "f.debt, f.cashneq, f.sharesbas, f.equity, f.intangibles, f.invcap, f.fcf",
        from_clause="fundamentals f join m using (ticker)",
    )
    assert _norm(got) == _norm(_OLD_L1_Q_BLOCK)


def test_l3_fields_are_first_four_and_span_is_explicit() -> None:
    assert [f.out for f in pit.L3_TTM_FIELDS] == [
        "revenue_ttm",
        "capex_ttm",
        "da_ttm",
        "ebitda_ttm",
    ]
    one = pit.ttm_valid_case_sql(pit.L1_TTM_FIELDS[0], 300)
    assert "interval 300 day" in one and "n_rev4 = 4" in one


# ---------------------------------------------------------------- pandas 경로


def _fund() -> pd.DataFrame:
    q = pd.date_range("2023-03-31", periods=5, freq="QE")
    rows = []
    for i, cd in enumerate(q):
        rows.append(
            {
                "ticker": "A",
                "calendardate": cd,
                "datekey": cd + pd.Timedelta(days=40),
                "dimension": "ARQ",
                "revenue": 10.0 * (i + 1),
                "ebitda": 1.0,
            }
        )
    # 정정 공시 — 같은 calendardate, 더 늦은 datekey. 최초 보고분만 남아야 한다
    rows.append(
        {
            "ticker": "A",
            "calendardate": q[0],
            "datekey": q[0] + pd.Timedelta(days=200),
            "dimension": "ARQ",
            "revenue": 999.0,
            "ebitda": 1.0,
        }
    )
    # ART 행은 버린다
    rows.append({**rows[0], "dimension": "ART", "revenue": -1.0})
    return pd.DataFrame(rows)


def test_pit_quarterly_first_reported_and_cutoff() -> None:
    f = _fund()
    q = pit.pit_quarterly(f, asof="2024-02-15")
    assert q["dimension"].eq("ARQ").all()
    assert q["revenue"].tolist() == [
        10.0,
        20.0,
        30.0,
        40.0,
    ]  # 5번째 분기(datekey 2024-05-10)는 미래
    assert len(q) == 4 and q["calendardate"].is_monotonic_increasing
    q_all = pit.pit_quarterly(f, asof=None)
    assert len(q_all) == 5 and q_all["revenue"].iloc[0] == 10.0  # 상한 없음, 정정치 999 미사용
    with pytest.raises(KeyError, match="fundamentals 에 없는 열"):
        pit.pit_quarterly(f.drop(columns=["datekey"]), asof=None)


def test_add_ttm_requires_four_quarters_within_span() -> None:
    q = pit.pit_quarterly(_fund(), asof=None)
    out = pit.add_ttm(q, ("revenue", "missing_col"), span_days=300)
    assert np.isnan(out["revenue_ttm"].iloc[2]) and out["revenue_ttm"].iloc[3] == 100.0
    assert out["revenue_ttm"].iloc[4] == 140.0
    assert out["missing_col_ttm"].isna().all()
    # 4번째 분기가 span 밖 — 분기 간격이 ~91일이라 cd_3back 은 ~273일 전. span 200 이면 전부 NaN
    assert pit.add_ttm(q, ("revenue",), span_days=200)["revenue_ttm"].isna().all()


def test_latest_fresh_rows_stale_months() -> None:
    q = pit.pit_quarterly(_fund(), asof=None)
    fresh = pit.latest_fresh_rows(q, "2024-06-30", stale_months=15)
    assert list(fresh.index) == ["A"] and fresh.loc["A", "revenue"] == 50.0
    assert pit.latest_fresh_rows(q, "2026-06-30", stale_months=15).empty


# ---------------------------------------------------------------- 실제 스토어 대조


@pytest.mark.data
def test_l1_fund_panel_identical_to_cache_built_with_old_sql(store, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """새 SQL 조각으로 만든 재무 패널 == 옛 손글씨 SQL 로 만든 `state/cache/l1_fund_*.parquet`."""
    from msa.config import paths
    from msa.l1.fundamentals import build_fund_panel
    from msa.l1.panel import _fingerprint
    from msa.themes import load_themes, membership_from_store

    ms = membership_from_store(store, load_themes())
    members = ms.frame[["ticker", "theme"]].drop_duplicates()
    fp = _fingerprint(members, store.store_end())
    cache = paths().cache
    old_paths = {
        "l1_fund": cache / f"l1_fund_{fp}.parquet",
        "l1_fund_ss": cache / f"l1_fund_ss_{fp}.parquet",
        "l1_fund_actions": cache / f"l1_fund_actions_{fp}.parquet",
    }
    if not all(p.exists() for p in old_paths.values()):
        pytest.skip(f"옛 SQL 로 만든 캐시가 없다: {fp}")
    fund = build_fund_panel(store, ms)
    for name, new in (
        ("l1_fund", fund.frame),
        ("l1_fund_ss", fund.same_store),
        ("l1_fund_actions", fund.actions),
    ):
        # 캐시는 parquet 왕복본이라 같은 왕복을 거쳐 비교한다 (datetime 단위 [s]/[ms] 차이 제거)
        new.to_parquet(tmp_path / f"{name}.parquet")
        pd.testing.assert_frame_equal(
            pd.read_parquet(tmp_path / f"{name}.parquet"), pd.read_parquet(old_paths[name])
        )


@pytest.mark.data
def test_l2_capex_ttm_dedup_matches_hand_rolled(store) -> None:  # type: ignore[no-untyped-def]
    """`pit_quarterly(asof=None)` 의 최초 보고분 규칙 == 옛 `sort_values + drop_duplicates`."""
    from msa.l2.sources import HYPERSCALERS

    fund = store.fundamentals(list(HYPERSCALERS), fields=["capex"], min_rows=4)
    f = fund.copy()
    f["calendardate"] = pd.to_datetime(f["calendardate"])
    f["datekey"] = pd.to_datetime(f["datekey"])
    f = f.sort_values(["ticker", "calendardate", "datekey"])
    old = f.drop_duplicates(["ticker", "calendardate"], keep="first").reset_index(drop=True)
    new = pit.pit_quarterly(fund, asof=None)
    pd.testing.assert_frame_equal(new, old)
