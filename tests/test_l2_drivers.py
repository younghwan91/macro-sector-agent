"""드라이버 상태 — 발표 지연·측정값·방향 상태·결측 보고 (합성 시리즈, 가짜 스토어)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from _l2_helpers import FakeStore, daily, monthly, write_dag
from msa.l2.dag import load_dag
from msa.l2.drivers import (
    PUB_LAG,
    PubLag,
    asof_on_grid,
    availability_dates,
    compute_driver_states,
    direction_states,
    employment_composite_z,
    last_month_end,
    measure_from_series,
    month_end_grid,
    usd_liquidity_level,
)
from msa.l2.sources import capex_ttm_asof

ASOF = pd.Timestamp("2024-07-31")


def test_last_month_end() -> None:
    assert last_month_end(pd.Timestamp("2026-08-23")) == pd.Timestamp("2026-07-31")
    assert last_month_end(pd.Timestamp("2026-07-31")) == pd.Timestamp("2026-07-31")


def test_availability_dates_monthly_quarterly_daily() -> None:
    m = availability_dates(pd.DatetimeIndex(["2024-07-01"]), PubLag("M", months=1))
    assert m[0] == pd.Timestamp("2024-08-31")
    m2 = availability_dates(pd.DatetimeIndex(["2024-07-01"]), PubLag("M", months=2))
    assert m2[0] == pd.Timestamp("2024-09-30")
    q = availability_dates(pd.DatetimeIndex(["2024-04-01"]), PubLag("Q", months=1))
    assert q[0] == pd.Timestamp("2024-07-31")  # Q2 말 6/30 + 1개월
    d = availability_dates(pd.DatetimeIndex(["2024-07-25"]), PubLag("D", days=7))
    assert d[0] == pd.Timestamp("2024-08-01")


def test_asof_on_grid_respects_publication_lag_and_staleness() -> None:
    grid = month_end_grid(ASOF, "2024-01-31")
    cpi = monthly("2024-01-01", "2024-07-01", lambda t: 100 + t)  # 1월=100 … 7월=106
    avail = availability_dates(pd.DatetimeIndex(cpi.index), PUB_LAG["CPIAUCSL"])
    g = asof_on_grid(cpi, avail, grid, max_stale_days=120)
    # 7/31 격자: 7월치(106)는 8/31 에야 보인다 → 6월치 105
    assert g.loc["2024-07-31"] == 105
    assert g.loc["2024-02-29"] == 100  # 1월치가 2월 말에 처음 보임
    assert np.isnan(g.loc["2024-01-31"])
    # 죽은 시리즈: 마지막 관측 이후 stale 한도를 넘으면 NaN
    grid2 = month_end_grid(pd.Timestamp("2025-06-30"), "2024-01-31")
    g2 = asof_on_grid(cpi, avail, grid2, max_stale_days=120)
    assert g2.loc["2024-10-31"] == 106
    assert np.isnan(g2.loc["2025-06-30"])


def test_measures() -> None:
    idx = pd.date_range("2020-01-31", periods=24, freq="ME")
    s = pd.Series(np.arange(1.0, 25.0), index=idx)
    assert measure_from_series("level", s).iloc[-1] == 24.0
    assert measure_from_series("yoy", s).iloc[-1] == pytest.approx(24 / 12 - 1)
    assert measure_from_series("change_6m", s).iloc[-1] == pytest.approx(24 / 18 - 1)
    assert measure_from_series("change_3m_bp", s).iloc[-1] == pytest.approx(300.0)
    assert measure_from_series("change_6m_bp", s).iloc[-1] == pytest.approx(600.0)
    d2 = measure_from_series("yoy_second_derivative", s)
    assert np.isfinite(d2.iloc[-1])
    with pytest.raises(ValueError):
        measure_from_series("nope", s)


def test_direction_states_and_employment_and_liquidity() -> None:
    m = pd.Series([-40.0, -10.0, 0.0, 10.0, 40.0, np.nan])
    st = direction_states(m, -25, 25)
    assert st.tolist()[:5] == [-1, 0, 0, 0, 1] and np.isnan(st.iloc[-1])
    idx = pd.date_range("2000-01-31", periods=150, freq="ME")
    rng = np.random.default_rng(1)
    pay = pd.Series(np.cumsum(200 + rng.normal(0, 50, 150)), index=idx)  # 매월 +200 ± 잡음
    unr = pd.Series(5.0 + np.cumsum(rng.normal(0, 0.05, 150)), index=idx)
    pay.iloc[-3:] = pay.iloc[-4] + np.array([1000, 2000, 3000])  # 최근 고용 급증
    unr.iloc[-1] = unr.iloc[-7] - 1.0  # 실업률 급락
    z = employment_composite_z(pay, unr)
    assert z.iloc[:60].isna().all()  # 60개월 전에는 z 없음
    assert z.iloc[-1] > 1.0  # 고용↑·실업률↓ → 양의 복합 z
    liq = usd_liquidity_level(pd.Series([8000.0]), pd.Series([500.0]), pd.Series([1.0]))
    assert liq.iloc[0] == 8000 - 500 - 1000  # RRP 십억 → 백만


def test_compute_driver_states_reports_missing_and_uses_fallback(tmp_path: Path) -> None:
    dag = load_dag(write_dag(tmp_path))
    # DFII10: 최근 6개월 −0.6%p → change_6m_bp = −60 → state −1, favorable True
    dfii = daily("2015-01-01", "2024-07-31", lambda t: 2.0 - (t / len(t)) * 0 - 0.0)
    dfii.loc["2024-02-01":] = 1.4
    dfii.loc[:"2024-01-31"] = 2.0
    # DTWEXBGS: +5% 6개월 → state +1 (dollar up)
    dx = daily("2015-01-01", "2024-07-31", lambda t: 100.0)
    dx.loc["2024-02-01":] = 105.0
    # CPI: YoY 4% → state +1
    cpi = monthly("2010-01-01", "2024-07-01", lambda t: 100 * (1.04 ** (t / 12)))
    # CPER: 6M +10% → copper state +1 via fallback (PCOPPUSDM 없음)
    cper = daily("2015-01-01", "2024-07-31", lambda t: 20.0)
    cper.loc["2024-02-01":] = 22.0
    # GLD: 6M −10% → −1
    gld = daily("2015-01-01", "2024-07-31", lambda t: 180.0)
    gld.loc["2024-02-01":] = 162.0
    # 수동 china_property: available 열로 PIT
    cp = monthly("2020-01-01", "2024-06-01", lambda t: 100 + 2.0 * t)
    cp_avail = pd.Series(pd.DatetimeIndex(cp.index) + pd.DateOffset(days=45), index=cp.index)
    # capex TTM: YoY +50% → +1
    grid = month_end_grid(ASOF)
    capex = pd.Series(np.where(grid >= pd.Timestamp("2023-08-31"), 150.0, 100.0), index=grid)
    store = FakeStore(
        fred={"DFII10": dfii, "DTWEXBGS": dx, "CPIAUCSL": cpi},
        etf={"CPER": cper, "GLD": gld},
        manual={"china_property": (cp, cp_avail)},
        capex=capex,
    )
    ds = compute_driver_states(dag, store, ASOF)  # type: ignore[arg-type]
    snap = ds.snapshot()
    assert ds.asof == ASOF
    assert snap.loc["real_rate_10y", "state"] == -1 and snap.loc["real_rate_10y", "favorable"]
    assert snap.loc["real_rate_10y", "value"] == pytest.approx(-60.0, abs=1e-6)
    assert snap.loc["dollar_broad", "state"] == 1
    assert snap.loc["cpi_yoy", "state"] == 1 and snap.loc["cpi_yoy", "value"] == pytest.approx(
        0.04, abs=1e-3
    )
    assert snap.loc["copper_price", "status"] == "ok"
    assert snap.loc["copper_price", "source_used"] == "etf:CPER (fallback)"
    assert snap.loc["copper_price", "missing_series"] == "PCOPPUSDM"
    assert snap.loc["gold_price", "state"] == -1
    assert snap.loc["china_property", "status"] == "ok" and snap.loc["china_property", "state"] == 1
    assert snap.loc["hyperscaler_capex", "state"] == 1
    # 없는 것: employment(PAYEMS·UNRATE), usd_liquidity(3종), policy_events
    assert set(ds.missing) == {"employment", "usd_liquidity", "policy_events"}
    assert snap.loc["employment", "missing_series"] == "PAYEMS,UNRATE"
    assert snap.loc["usd_liquidity", "missing_series"] == "WALCL,WTREGEN,RRPONTSYD"
    # ETF 벌크는 한 번에 모아서 — GLD·IAU(대체)·CPER(폴백) 전부 요청됐다
    assert store.prefetched == ["CPER", "GLD", "IAU"]
    # 시계열 출력 모양
    assert list(ds.measures.columns) == [d.id for d in dag.drivers]
    assert ds.states.loc[ASOF, "dollar_broad"] == 1


def test_liquidity_unit_mismatch_is_reported_not_computed(tmp_path: Path) -> None:
    dag = load_dag(write_dag(tmp_path))
    w = daily("2020-01-01", "2024-07-31", lambda t: 8_000_000.0)
    store = FakeStore(
        fred={"WALCL": w, "WTREGEN": w * 0.1, "RRPONTSYD": w * 0.0001},
        units={
            "WALCL": "Millions of Dollars",
            "WTREGEN": "Millions of Dollars",
            "RRPONTSYD": "Millions of Dollars",
        },
    )
    ds = compute_driver_states(dag, store, ASOF)  # type: ignore[arg-type]
    row = ds.snapshot().loc["usd_liquidity"]
    assert row["status"] == "missing" and "단위" in row["note"]


def test_capex_ttm_asof_pit_and_consecutive_quarters() -> None:
    q = pd.date_range("2022-03-31", periods=8, freq="QE")
    rows = []
    for tk in ("A", "B"):
        for i, cd in enumerate(q):
            rows.append(
                {
                    "ticker": tk,
                    "calendardate": cd,
                    "datekey": cd + pd.Timedelta(days=40),
                    "capex": -10.0 * (i + 1),
                }
            )
    # A 의 마지막 분기 정정 공시 (더 늦은 datekey, 다른 값) — 최초 공시가 쓰여야 한다
    rows.append(
        {
            "ticker": "A",
            "calendardate": q[-1],
            "datekey": q[-1] + pd.Timedelta(days=120),
            "capex": -999.0,
        }
    )
    fund = pd.DataFrame(rows)
    grid = pd.date_range("2022-01-31", "2024-06-30", freq="ME")
    panel = capex_ttm_asof(fund, grid)
    assert set(panel.columns) == {"A", "B"}
    # 4분기(2022-12-31, datekey 2023-02-09) 이후 첫 월말 2023-02-28 에 TTM = 10+20+30+40 = 100
    assert panel.loc["2023-02-28", "A"] == 100.0
    assert np.isnan(panel.loc["2023-01-31", "A"])
    # 마지막: 50+60+70+80 = 260 (정정치 999 미사용)
    assert panel.loc["2024-03-31", "A"] == 260.0
    # 4분기 연속성 위반 → NaN
    fund2 = fund[fund["calendardate"] != q[2]]
    p2 = capex_ttm_asof(fund2, grid)
    assert np.isnan(p2.loc["2023-05-31", "B"])
