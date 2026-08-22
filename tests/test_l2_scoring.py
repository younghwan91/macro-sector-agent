"""tailwind 산술(중앙값 차감) · 4분면 · 모순 감사 · 부호 일치율 — 전부 합성."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from _l2_helpers import THEMES, write_dag
from msa.l2 import audit
from msa.l2.dag import load_dag, validate_dag
from msa.l2.drivers import DriverStates
from msa.l2.regime import classify, compute_regime, render_ascii
from msa.l2.signcheck import (
    flag_for,
    forward_excess_return,
    render_markdown,
    rolling_sign_agreement,
    run_sign_check,
)
from msa.l2.tailwind import compute_tailwind, policy_event_effect

ASOF = pd.Timestamp("2024-07-31")


@pytest.fixture
def dag(tmp_path: Path):  # type: ignore[no-untyped-def]
    return load_dag(write_dag(tmp_path))


def _states(**kw: float) -> pd.Series:
    base = {
        d: np.nan
        for d in (
            "real_rate_10y",
            "dollar_broad",
            "cpi_yoy",
            "employment",
            "usd_liquidity",
            "copper_price",
            "gold_price",
            "china_property",
            "hyperscaler_capex",
            "policy_events",
        )
    }
    base.update(kw)
    return pd.Series(base)


def test_tailwind_arithmetic_and_common_factor_median(dag) -> None:  # type: ignore[no-untyped-def]
    # alpha: real_rate(-1,3) dollar(-1,3) gold(+1,3) copper(+1,2) + cf usd_liquidity(+1,2)
    # beta : real_rate(-1,3) cpi(-1,2) + cf
    # gamma: dollar(+1,1) cpi(-1,2) hyperscaler(+1,3) employment(+1,1) + cf
    # delta: policy(+1,3) china_property(+1,2) + cf
    # epsilon: cf 만
    st = _states(
        real_rate_10y=-1,
        dollar_broad=1,
        cpi_yoy=1,
        usd_liquidity=1,
        gold_price=-1,
        copper_price=1,
        hyperscaler_capex=1,
        employment=0,
        china_property=np.nan,
    )
    v = validate_dag(dag, THEMES)
    res = compute_tailwind(dag, THEMES, st, asof=ASOF, events=None, validation=v)
    t = res.table
    # alpha: ind = (3·(-1)(-1) + 3·(-1)(1) + 3·(1)(-1) + 2·(1)(1)) / (3+3+3+2+2)
    #            = (3-3-3+2)/13 = -1/13
    #        cf  = 2·1·1 / 13 = 2/13
    assert t.loc["alpha", "ind_part"] == pytest.approx(-1 / 13)
    assert t.loc["alpha", "cf_part"] == pytest.approx(2 / 13)
    # beta: ind = (3·1 + 2·(-1)) / 7 = 1/7 ; cf = 2/7
    assert t.loc["beta", "ind_part"] == pytest.approx(1 / 7)
    # gamma: ind = (1·1·1 + 2·(-1)(1) + 3·1·1 + 1·1·0) / (1+2+3+1+2) = 2/9 ; cf = 2/9
    assert t.loc["gamma", "ind_part"] == pytest.approx(2 / 9)
    # delta: policy 없음(events None) · china_property 없음 → cf 만: ind 0, cf = 2/2 = 1
    assert t.loc["delta", "ind_part"] == 0.0 and t.loc["delta", "cf_part"] == pytest.approx(1.0)
    assert t.loc["delta", "n_edges_missing"] == 2 and t.loc["delta", "status"] == "partial"
    # epsilon: cf 만 → cf 1.0, undercovered
    assert t.loc["epsilon", "cf_part"] == pytest.approx(1.0) and t.loc["epsilon", "undercovered"]
    # 중앙값 차감: cf_part 중앙값 = median(2/13, 2/7, 2/9, 1, 1) = 2/7
    assert res.cf_median == pytest.approx(2 / 7)
    assert t.loc["alpha", "tailwind"] == pytest.approx(-1 / 13 + 2 / 13 - 2 / 7)
    assert t.loc["alpha", "tailwind_raw"] == pytest.approx(-1 / 13 + 2 / 13)
    assert t.loc["beta", "tailwind"] == pytest.approx(1 / 7)  # cf 가 중앙값 그 자체
    # 기여 행: alpha 의 gold 기여 = 3·1·(-1) = -3
    c = res.contributions
    assert c.loc[(c["theme"] == "alpha") & (c["from"] == "gold_price"), "contrib"].item() == -3
    assert (
        c.loc[c["theme"] == "delta", "status"].isin(["missing_events", "missing_driver"])
    ).sum() == 2
    assert res.n_pairs == len(c)


def test_tailwind_all_missing_is_unavailable_not_zero(dag) -> None:  # type: ignore[no-untyped-def]
    res = compute_tailwind(dag, THEMES, _states(), asof=ASOF)
    assert (res.table["status"] == "unavailable").all()
    assert res.table["tailwind"].isna().all()
    assert not res.table["hard_exclude"].any()


def test_hard_exclude_requires_coverage(dag) -> None:  # type: ignore[no-untyped-def]
    # alpha 에 gold(+1,3) 만 관측, state −1 → tailwind −1 이지만 커버리지 3/13 < 0.5 → 플래그 안 섬
    res = compute_tailwind(dag, THEMES, _states(gold_price=-1), asof=ASOF)
    assert res.table.loc["alpha", "tailwind"] == pytest.approx(-1.0)
    assert not res.table.loc["alpha", "hard_exclude"]
    # real_rate(+1→-3) dollar(+1→-3) gold(-1→-3) copper(-1→-2) cf(+1→+2): 13/13 관측, 전부 역풍
    st = _states(real_rate_10y=1, dollar_broad=1, gold_price=-1, copper_price=-1, usd_liquidity=1)
    res2 = compute_tailwind(dag, THEMES, st, asof=ASOF)
    assert res2.table.loc["alpha", "hard_exclude"]


def test_policy_event_effect_window_and_sign() -> None:
    ev = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-15", "2023-05-01", "2024-03-01", "2024-06-01"]),
            "theme": ["delta", "delta", "gamma", "gamma"],
            "effect": [1, -1, 1, -1],
            "confirmed": [True, True, True, False],
        }
    )
    assert policy_event_effect(ev, "delta", ASOF) == 1.0  # 불리 이벤트는 12개월 밖
    assert policy_event_effect(ev, "gamma", ASOF) == 1.0  # 미확정 불리는 안 센다
    assert policy_event_effect(ev, "alpha", ASOF) == 0.0
    assert np.isnan(policy_event_effect(None, "alpha", ASOF))
    ev2 = ev.assign(confirmed=True)
    assert policy_event_effect(ev2, "gamma", ASOF) == 0.0  # 공존 → 0


def test_policy_events_in_tailwind(dag) -> None:  # type: ignore[no-untyped-def]
    ev = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-05-01")],
            "theme": ["delta"],
            "effect": [-1],
            "confirmed": [True],
        }
    )
    res = compute_tailwind(dag, THEMES, _states(), asof=ASOF, events=ev)
    # delta: policy sign +1, effect −1 → state = −1 → 기여 3·1·(−1) = −3 → tailwind −1
    assert res.table.loc["delta", "tailwind"] == pytest.approx(-1.0)
    row = res.contributions.loc[res.contributions["from"] == "policy_events"].iloc[0]
    assert row["state"] == -1 and row["status"] == "ok"


# ---------------------------------------------------------------- 4분면


def test_classify_quadrants() -> None:
    assert classify(1.0, 1.0) == "과열(리플레)"
    assert classify(1.0, -1.0) == "골디락스"
    assert classify(-1.0, 1.0) == "스태그플레이션"
    assert classify(-1.0, -1.0) == "디플레 침체"
    assert classify(float("nan"), 1.0) == "unavailable"


def _driver_states_from(
    measures: pd.DataFrame, states: pd.DataFrame, asof: pd.Timestamp
) -> DriverStates:
    return DriverStates(
        asof=asof, grid=pd.DatetimeIndex(measures.index), measures=measures, states=states, rows=[]
    )


def test_compute_regime_with_partial_components_and_credit() -> None:
    grid = pd.date_range("2010-01-31", "2024-07-31", freq="ME")
    rng = np.random.default_rng(3)
    n = len(grid)
    base = rng.normal(0, 1, n)
    m = pd.DataFrame(index=grid)
    # 성장 3종 (employment 없음): 최근 강한 양수
    for c in ("industrial_production", "new_orders_mfg"):
        m[c] = base + 0.1
    m["inventory_sales"] = -base  # 부호 반전 → 성장에 +
    m.loc[grid[-3:], ["industrial_production", "new_orders_mfg"]] = 3.0
    m.loc[grid[-3:], "inventory_sales"] = -3.0
    # 인플레 2종만 (ppi·oil 없음): 최근 음수
    m["cpi_yoy"] = 0.02 + 0.005 * base
    m["breakeven_10y"] = 10 * base
    m.loc[grid[-3:], "cpi_yoy"] = 0.0
    m.loc[grid[-3:], "breakeven_10y"] = -40.0
    st = pd.DataFrame({"hy_spread": np.full(n, 1.0)}, index=grid)
    ds = _driver_states_from(m, st, grid[-1])
    rg = compute_regime(ds)
    assert rg.current["quadrant"] == "골디락스"
    assert rg.current["n_growth"] == 3 and rg.current["n_inflation"] == 2
    assert rg.missing_growth == ["employment"] and rg.missing_inflation == ["ppi_yoy", "oil_wti"]
    assert rg.current["credit_stress"] is True and rg.current["credit_penalty"] == 0.5
    assert len(rg.axes) == 24
    txt = render_ascii(rg)
    assert "골디락스" in txt and "@" in txt and "employment" in txt


def test_compute_regime_unavailable_lists_missing() -> None:
    grid = pd.date_range("2020-01-31", "2024-07-31", freq="ME")
    m = pd.DataFrame({"cpi_yoy": np.full(len(grid), 0.02)}, index=grid)
    ds = _driver_states_from(m, pd.DataFrame(index=grid), grid[-1])
    rg = compute_regime(ds)
    assert not rg.available
    txt = render_ascii(rg)
    assert "계산 불가" in txt and "industrial_production" in txt and "hy_spread" in txt


# ---------------------------------------------------------------- 모순 감사


def test_contradiction_rules(dag) -> None:  # type: ignore[no-untyped-def]
    df = audit.evaluate_contradictions(dag, _states(dollar_broad=1, gold_price=1))
    by = df.set_index("edge")["status"]
    assert by.loc[1] == "FLAGGED"
    assert by.loc[2] == "PROSE_ONLY"
    df2 = audit.evaluate_contradictions(dag, _states(dollar_broad=1, gold_price=-1))
    assert df2.set_index("edge").loc[1, "status"] == "NOT_FLAGGED"
    df3 = audit.evaluate_contradictions(dag, _states(dollar_broad=1))
    r = df3.set_index("edge").loc[1]
    assert r["status"] == "UNAVAILABLE" and "gold_price" in r["detail"]
    assert audit.summarize(df3) == {
        "FLAGGED": 0,
        "NOT_FLAGGED": 0,
        "UNAVAILABLE": 1,
        "PROSE_ONLY": 1,
    }
    assert (
        audit.evaluate_rule({"any_of": [{"driver": "x", "state": 1}]}, pd.Series({"x": 1.0}))[0]
        == "FLAGGED"
    )


# ---------------------------------------------------------------- 부호 일치율


def test_rolling_sign_agreement_and_flags() -> None:
    idx = pd.date_range("2000-01-31", periods=200, freq="ME")
    rng = np.random.default_rng(7)
    x = pd.Series(rng.normal(0, 1, 200), index=idx)
    y = x * 0.8 + pd.Series(rng.normal(0, 0.3, 200), index=idx)
    r = rolling_sign_agreement(x, y, 36, sign=1)
    assert r["n_windows"] == 200 - 36 + 1 and r["agree_share"] == 1.0 and r["latest_corr"] > 0.3
    r2 = rolling_sign_agreement(x, y, 36, sign=-1)
    assert r2["agree_share"] == 0.0
    short = rolling_sign_agreement(x.iloc[:20], y.iloc[:20], 36, sign=1)
    assert short["n_windows"] == 0 and np.isnan(short["agree_share"])
    assert flag_for(0.5, 1) == "CONSISTENT"
    assert flag_for(-0.5, 1) == "CONTRADICTED"
    assert flag_for(-0.2, 1) == "CONSISTENT"  # 반대 부호지만 0.3 미만 → 플래그 아님
    assert flag_for(0.05, -1) == "NO_SIGNAL"
    assert flag_for(float("nan"), 1) == "UNAVAILABLE"


def test_forward_excess_return() -> None:
    idx = pd.date_range("2020-01-31", periods=14, freq="ME")
    p = pd.DataFrame({"a": 1.0 * 1.1 ** np.arange(14)}, index=idx)
    spy = pd.Series(1.0 * 1.05 ** np.arange(14), index=idx)
    f = forward_excess_return(p, spy, horizon=12)
    assert f["a"].iloc[0] == pytest.approx(1.1**12 - 1.05**12)
    assert f["a"].iloc[-1] != f["a"].iloc[-1]  # 마지막 12개월은 NaN


def test_run_sign_check_synthetic(dag) -> None:  # type: ignore[no-untyped-def]
    idx = pd.date_range("2000-01-31", periods=240, freq="ME")
    rng = np.random.default_rng(11)
    x = pd.Series(rng.normal(0, 1, 240), index=idx)
    measures = pd.DataFrame({"real_rate_10y": x, "cpi_yoy": -x}, index=idx)
    # alpha 의 전방 초과수익이 real_rate 측정값과 반대로 움직이면 sign −1 엣지는 일치율 1.0
    fwd = pd.DataFrame({"alpha": -x + rng.normal(0, 0.2, 240), "beta": x, "gamma": x}, index=idx)
    res = run_sign_check(dag, THEMES, measures, fwd)
    p = res.pairs.set_index(["from", "theme"])
    assert p.loc[("real_rate_10y", "alpha"), "agree_36"] == 1.0
    assert p.loc[("real_rate_10y", "alpha"), "flag_60"] == "CONSISTENT"
    # beta 는 양의 상관 → sign −1 과 반대 → 0 · CONTRADICTED
    assert p.loc[("real_rate_10y", "beta"), "agree_36"] == 0.0
    assert p.loc[("real_rate_10y", "beta"), "flag_36"] == "CONTRADICTED"
    # cpi(-x) vs gamma(x): 음의 상관, sign −1 → 일치
    assert p.loc[("cpi_yoy", "gamma"), "agree_60"] == 1.0
    # 측정값 없는 드라이버 → 이유 기록, 창 0
    assert p.loc[("dollar_broad", "alpha"), "n_windows_36"] == 0
    assert "dollar_broad" in p.loc[("dollar_broad", "alpha"), "reason"]
    # policy_events 는 시계열이 아님
    assert "시계열" in p.loc[("policy_events", "delta"), "reason"]
    # 공통 인자(와일드카드)는 쌍에 없다
    assert "usd_liquidity" not in set(res.pairs["from"])
    assert res.summary["n_pairs_available"] == 4  # real_rate×2 + cpi×2 (gamma·beta)
    md = render_markdown(res, {"asof": "2024-07-31"})
    assert "real_rate_10y" in md and "일치율" in md
    # fwd 없음 → 전부 UNAVAILABLE, 문서는 실행 불가를 말한다
    res2 = run_sign_check(dag, THEMES, measures, None, unavailable_reason="패널 없음")
    assert res2.summary["n_pairs_available"] == 0 and not res2.ran
    assert "계산 불가" in render_markdown(res2, {})
