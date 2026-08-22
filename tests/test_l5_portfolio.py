"""L5 합성 테스트 — 최적화기 · 완화 순서 · ENB · 사다리 산술(M0.1) · 확신도 압축 · L_i · 계획서."""

from __future__ import annotations

import json
import textwrap
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from msa.l5 import ladders, optimize, risk
from msa.l5.inputs import (
    CaseTable,
    InputError,
    Pick,
    ThesisInput,
    load_cases,
    load_inputs,
    load_picks,
    parse_thesis,
)
from msa.l5.optimize import Problem, compress_confidence, solve
from msa.l5.plan import render_plan
from msa.l5.run import PortfolioInputs, build_portfolio, write_outputs
from msa.themes import load_themes

REPO = Path(__file__).resolve().parents[1]
ASOF = date(2026, 8, 22)

# ---------------------------------------------------------------- 도우미


def _sigma3() -> np.ndarray:
    # 두 자산 상관 0.75 (같은 테마) · 세 번째는 거의 독립
    return np.array([[0.16, 0.12, 0.02], [0.12, 0.16, 0.02], [0.02, 0.02, 0.09]])


def _problem(**over: object) -> Problem:
    base: dict[str, object] = {
        "tickers": ("A", "B", "C"),
        "themes": ("t1", "t1", "t2"),
        "classes": ("commodity_supply", "commodity_supply", "capex_program"),
        "clusters": ("x", "x", "y"),
        "coef": (0.70, 0.70, 0.60),
        "sigma": _sigma3(),
        "scenario_loss": (0.6, 0.6, 0.5),
        "adv20_usd": (None, None, None),
        "min_weight": (0.0, 0.0, 0.0),
    }
    base.update(over)
    return Problem(**base)  # type: ignore[arg-type]


def _synthetic_daily_ew(themes: list[str], *, seed: int = 0) -> pd.DataFrame:
    """10년 일별 EW 수익률 — 한 테마에 −60% 에피소드를 심는다."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-01", "2026-08-20")
    n = len(idx)
    out = pd.DataFrame(index=idx)
    for t in themes:
        out[t] = rng.normal(0.0003, 0.012, n)
    # 첫 테마: 2018-01 ~ 2019-06 사이에 −70% 까지 무너졌다가 회복
    t0 = themes[0]
    s = out[t0].to_numpy().copy()
    crash = (idx >= "2018-01-01") & (idx <= "2019-06-30")
    s[crash] = -0.0035 + rng.normal(0, 0.008, crash.sum())
    rec = (idx > "2019-06-30") & (idx <= "2021-06-30")
    s[rec] = 0.0035 + rng.normal(0, 0.008, rec.sum())
    out[t0] = s
    return out


def _thesis(theme: str, c: float, **over: object) -> ThesisInput:
    base: dict[str, object] = {
        "theme": theme,
        "cycle_confidence": c,
        "confidence_source": "human",
        "horizon_months": (6, 18),
        "invalidations": ("카자흐 쿼터 +20% 발표 [Kazatomprom]", "원전승인 2건 철회 [NRC]"),
        "triggers": ("현물 $80 회복 [UxC]",),
        "tailwind": 0.41,
    }
    base.update(over)
    return ThesisInput(**base)  # type: ignore[arg-type]


def _cases_verified(theme: str, dd: float = 0.90) -> CaseTable:
    return load_cases_from_text(
        f"""
        cases:
          - id: death_{theme}
            name_ko: x
            type: death
            theme_ids: [{theme}]
            clusters: []
            drawdown_peak_to_trough: {dd}
            peak_date: "2011-04"
            trough_date: "2016-01"
            verified: true
            sources: [{{url: "https://example.org/x", title: t, date: "2020-01-01"}}]
        """
    )


def load_cases_from_text(text: str, tmp: Path | None = None) -> CaseTable:
    import tempfile

    d = Path(tmp or tempfile.mkdtemp())
    p = d / "cases.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return load_cases(p)


# ---------------------------------------------------------------- 확신도 압축


def test_compress_confidence_preserves_mean_and_shrinks_spread() -> None:
    c = {"a": 0.85, "b": 0.55}
    ct = compress_confidence(c, 0.3)
    assert ct["a"] + ct["b"] == pytest.approx(0.85 + 0.55)
    assert ct["a"] == pytest.approx(0.805) and ct["b"] == pytest.approx(0.595)
    # 평행이동이 아니라 압축: 비율이 1.75 → 1.35 쪽으로 **줄어든다**
    assert ct["a"] / ct["b"] < 0.85 / 0.55
    assert compress_confidence(c, 1.0)["a"] == pytest.approx(0.70)
    assert compress_confidence(c, 0.0) == c
    assert compress_confidence({}, 0.3) == {}


# ---------------------------------------------------------------- 최적화기


def test_solve_toy_known_solution_caps_bind() -> None:
    """3자산: 상한 0.15 가 전부 걸리는 해. 계수가 전부 양수면 가능한 만큼 채운다."""
    s = solve(_problem())
    assert s.status == "optimal"
    assert s.solver == "CLARABEL"
    for t in ("A", "B", "C"):
        assert s.weights[t] == pytest.approx(0.15, abs=1e-5)
    assert s.gross == pytest.approx(0.45, abs=1e-5)
    assert s.stage == 0 and s.relaxed == ()
    assert s.mdd_vol <= 0.30 + 1e-6
    assert s.mdd_scenario == pytest.approx(0.45 * 0.6 - 0.15 * 0.1, abs=1e-5)  # 0.15·.6·2+.15·.5
    assert any(b.startswith("C3-stock") for b in s.binding_caps)


def test_solve_scenario_constraint_is_conservative_side() -> None:
    """L_i 가 크면 C1-(ii) 가 (i) 보다 먼저 구속한다 — 동시 부과이므로 자동으로 보수적인 쪽."""
    s = solve(_problem(scenario_loss=(0.9, 0.9, 0.9), min_weight=(0.0, 0.0, 0.0)))
    assert s.mdd_binding in ("scenario", "both")
    assert s.mdd_scenario == pytest.approx(0.30, abs=1e-4)
    assert s.gross == pytest.approx(0.30 / 0.9, abs=1e-4)


def test_solve_vol_constraint_binds_when_sigma_large() -> None:
    sig = _sigma3() * 6.0  # σ 가 크면 (i) 가 먼저
    s = solve(_problem(sigma=sig, scenario_loss=(None, None, None)))
    assert s.mdd_binding == "vol"
    assert s.mdd_scenario is None
    assert set(s.scenario_missing) == {"A", "B", "C"}
    assert s.mdd_vol == pytest.approx(0.30, abs=1e-4)


def test_solve_theme_and_class_caps() -> None:
    p = _problem(
        tickers=("A", "B", "C", "D", "E"),
        themes=("t1", "t1", "t1", "t2", "t2"),
        classes=("commodity_supply",) * 5,
        clusters=("x", "x", "x", "y", "y"),
        coef=(0.8, 0.8, 0.8, 0.5, 0.5),
        sigma=np.eye(5) * 0.01,
        scenario_loss=(0.3, 0.3, 0.3, 0.3, 0.3),
        adv20_usd=(None,) * 5,
        min_weight=(0.0,) * 5,
    )
    s = solve(p)
    # t1: 3종목 × 0.15 = 0.45 가능하지만 테마 상한 0.35 · t2: 0.30 가능 → 클래스 합 0.65 > 0.55
    assert s.theme_weights["t1"] == pytest.approx(0.35, abs=1e-4)
    assert s.class_weights["commodity_supply"] == pytest.approx(0.55, abs=1e-4)
    assert s.theme_weights["t2"] == pytest.approx(0.20, abs=1e-4)


def test_solve_liquidity_c4_and_skip_reported() -> None:
    s = solve(_problem(adv20_usd=(5e5, None, 1e9), capital_usd=1e6))
    # A: 0.10·5e5/1e6 = 0.05 상한
    assert s.weights["A"] == pytest.approx(0.05, abs=1e-5)
    assert s.c4_applied and s.c4_skipped == ("B",)


def test_relaxation_order_c3_then_c1() -> None:
    """하한이 C3 와 충돌 → 1단(C3 완화). 하한이 C1 과도 충돌 → 2단(예산 상향)."""
    # 하한 0.20 > 단일 종목 상한 0.15 → C3 완화로 해결 (σ 작음)
    p1 = _problem(
        sigma=np.eye(3) * 0.001, min_weight=(0.20, 0.0, 0.0), scenario_loss=(0.1, 0.1, 0.1)
    )
    s1 = solve(p1)
    assert s1.stage == 1 and s1.relaxed == ("C3",)
    assert s1.weights["A"] >= 0.20 - 1e-6
    # 하한 합 0.60, L=0.6 → Σ w·L ≥ 0.36 > 0.30 → C3 로는 안 되고 예산 0.40 에서 해결
    p2 = _problem(
        sigma=np.eye(3) * 0.001, min_weight=(0.20, 0.20, 0.20), scenario_loss=(0.6, 0.6, 0.6)
    )
    s2 = solve(p2)
    assert s2.stage == 2
    assert s2.budget_used == pytest.approx(0.40)
    assert "C3" in s2.relaxed
    # 완화를 꺼 두면 예외
    with pytest.raises(optimize.OptimizeError):
        solve(p2, relax=False)
    # 하한 합이 현금 하한과 충돌하면 어떤 완화로도 안 된다
    p3 = _problem(min_weight=(0.5, 0.5, 0.0))
    with pytest.raises(optimize.OptimizeError):
        solve(p3)


def test_cluster_cap_optional() -> None:
    s = solve(_problem(cluster_caps={"x": 0.10}))
    assert s.cluster_weights["x"] == pytest.approx(0.10, abs=1e-5)
    with pytest.raises(optimize.OptimizeError):
        solve(_problem(cluster_caps={"nope": 0.1}))


# ---------------------------------------------------------------- ENB


def test_enb_identity_equal_weights_is_n() -> None:
    sig = np.eye(4) * 0.04
    w = np.full(4, 0.25)
    r = risk.effective_number_of_bets(sig, w)
    assert r.enb == pytest.approx(4.0)
    assert r.p_top3[0] == pytest.approx(0.25)


def test_enb_perfect_correlation_is_one() -> None:
    sig = np.full((4, 4), 0.04)
    w = np.full(4, 0.25)
    r = risk.effective_number_of_bets(sig, w)
    assert r.enb == pytest.approx(1.0)
    assert r.p_top3[0] == pytest.approx(1.0)
    assert risk.effective_number_of_bets(sig, np.zeros(4)).enb == 0.0


def test_enb_two_blocks() -> None:
    sig = np.array([[1, 1, 0, 0], [1, 1, 0, 0], [0, 0, 1, 1], [0, 0, 1, 1]], dtype=float) * 0.04
    w = np.full(4, 0.25)
    r = risk.effective_number_of_bets(sig, w)
    assert r.enb == pytest.approx(2.0)
    assert r.p_top3 == pytest.approx((0.5, 0.5, 0.0))


# ---------------------------------------------------------------- 축소 공분산


def test_constant_correlation_shrinkage() -> None:
    s = np.array([[0.04, 0.01, 0.0], [0.01, 0.09, 0.03], [0.0, 0.03, 0.16]])
    out = risk.shrink_constant_correlation(s, 0.5)
    # 대각 보존
    assert np.allclose(np.diag(out), np.diag(s))
    # δ=0 이면 그대로, δ=1 이면 상수상관
    assert np.allclose(risk.shrink_constant_correlation(s, 0.0), s)
    full = risk.shrink_constant_correlation(s, 1.0)
    sd = np.sqrt(np.diag(s))
    corr = full / np.outer(sd, sd)
    off = corr[~np.eye(3, dtype=bool)]
    assert np.allclose(off, off[0])
    assert np.allclose(out, out.T)


def test_theme_covariance_requires_enough_history() -> None:
    daily = _synthetic_daily_ew(["a", "b"])
    m = risk.monthly_returns(daily)
    cov = risk.theme_covariance(m, ["a", "b"], asof=pd.Timestamp("2026-08-20"))
    assert cov.sigma.shape == (2, 2) and cov.n_obs == 60
    assert cov.source == "theme_ew_monthly"
    with pytest.raises(risk.RiskInputError):
        risk.theme_covariance(m.tail(6), ["a", "b"])
    with pytest.raises(risk.RiskInputError):
        risk.theme_covariance(m, ["a", "zzz"])


def test_map_theme_cov_to_stocks_idio() -> None:
    daily = _synthetic_daily_ew(["a", "b"])
    tcov = risk.theme_covariance(risk.monthly_returns(daily), ["a", "b"])
    sc = risk.map_theme_cov_to_stocks(tcov, ["a", "a", "b"], [None, 0.3, None], ["X", "Y", "Z"])
    assert sc.sigma.shape == (3, 3)
    assert sc.sigma[0, 0] == pytest.approx(tcov.sigma[0, 0])
    assert sc.sigma[1, 1] == pytest.approx(tcov.sigma[0, 0] + 0.09)
    assert sc.sigma[0, 1] == pytest.approx(tcov.sigma[0, 0])


# ---------------------------------------------------------------- 유사 국면 낙폭 · L_i


def test_similar_regime_drawdown_finds_episode() -> None:
    # 100 → 40 (−60%) → 20 → 120 회복 → 110
    lvl = pd.Series(
        [100, 80, 60, 50, 40, 30, 20, 50, 90, 120, 110, 100],
        index=pd.date_range("2020-01-31", periods=12, freq="ME"),
        dtype=float,
    )
    h = risk.similar_regime_drawdown(lvl, theme="x")
    assert len(h.episodes) == 1
    e = h.episodes[0]
    # −50% 최초 도달 = 50 (2020-04), 최저 20 → 진입 후 손실 0.6
    assert e.entry_date == "2020-04-30" and e.trough_date == "2020-07-31"
    assert e.loss_from_entry == pytest.approx(0.6)
    assert not e.ongoing
    assert h.max_loss == pytest.approx(0.6)
    # 에피소드 없음
    flat = pd.Series(
        [100, 90, 95, 100, 105],
        index=pd.date_range("2020-01-31", periods=5, freq="ME"),
        dtype=float,
    )
    assert risk.similar_regime_drawdown(flat).max_loss is None
    assert risk.similar_regime_drawdown(flat.iloc[:0]).history is None


def test_similar_regime_ongoing_episode_counts() -> None:
    lvl = pd.Series(
        [100, 50, 40, 45], index=pd.date_range("2020-01-31", periods=4, freq="ME"), dtype=float
    )
    h = risk.similar_regime_drawdown(lvl)
    assert h.episodes[0].ongoing and h.max_loss == pytest.approx(0.2)


def test_scenario_loss_formula_and_binding() -> None:
    hist = risk.HistoricalDrawdown("u", 0.5, 0.42, (), ("2000-01-01", "2026-01-01"))
    cases = _cases_verified("u", 0.78)
    sl = risk.scenario_loss("u", cluster=None, hist=hist, cases=cases)
    assert sl.computable
    assert sl.case_term == pytest.approx(0.39) and sl.value == pytest.approx(0.42)
    assert sl.binding == "hist" and sl.case_id == "death_u"
    # 사망 사례 × 0.5 가 더 크면 그쪽이 구속
    sl2 = risk.scenario_loss("u", cluster=None, hist=hist, cases=_cases_verified("u", 0.95))
    assert sl2.binding == "case" and sl2.value == pytest.approx(0.475)


def test_scenario_loss_missing_case_is_visible_not_silent() -> None:
    hist = risk.HistoricalDrawdown("u", 0.5, 0.42, (), ("2000-01-01", "2026-01-01"))
    # (1) 표 자체가 없음
    sl = risk.scenario_loss("u", cluster=None, hist=hist, cases=CaseTable((), "", exists=False))
    assert not sl.computable and sl.value is None and sl.hist_term == pytest.approx(0.42)
    assert any("케이스 스터디 표 없음" in r for r in sl.reasons)
    # (2) 표는 있으나 해당 행 없음
    sl = risk.scenario_loss("zzz", cluster="nope", hist=hist, cases=_cases_verified("u"))
    assert not sl.computable and any("해당하는 행 없음" in r for r in sl.reasons)
    # (3) 행은 있으나 미검증 (예시 파일) → 사유에 verified=false
    ex = load_cases(REPO / "docs" / "specs" / "cases.example.yaml")
    sl = risk.scenario_loss("coal", cluster="fossil", hist=hist, cases=ex)
    assert not sl.computable
    assert any("sources 비어 있음" in r or "verified=false" in r for r in sl.reasons)
    # (4) 과거 유사 국면이 없어도 못 만든다
    sl = risk.scenario_loss(
        "u",
        cluster=None,
        hist=risk.HistoricalDrawdown("u", 0.5, None, (), ("2000-01-01", "2026-01-01")),
        cases=_cases_verified("u"),
    )
    assert not sl.computable and any("에피소드 없음" in r for r in sl.reasons)


def test_cases_example_file_loads_and_is_all_unverified() -> None:
    ex = load_cases(REPO / "docs" / "specs" / "cases.example.yaml")
    assert len(ex) == 11
    assert all(not c.verified and not c.sources for c in ex.cases)
    assert not any(c.usable_for_loss for c in ex.cases)
    assert sum(1 for c in ex.cases if c.type == "death") == 6


def test_cases_verified_without_sources_rejected() -> None:
    with pytest.raises(InputError):
        load_cases_from_text(
            """
            cases:
              - {id: a, type: death, theme_ids: [x], drawdown_peak_to_trough: 0.5,
                 verified: true, sources: []}
            """
        )


# ---------------------------------------------------------------- 사다리 산술 (M0.1 정정값)


@pytest.mark.parametrize(
    ("c", "frac", "avg", "avg_vs", "t2", "t2_vs"),
    [
        (0.80, (0.60, 0.25, 0.15), 0.9330, -0.067, 0.6065, -0.394),
        (0.65, (0.50, 0.30, 0.20), 0.9150, -0.085, 0.5948, -0.405),
        (0.55, (0.35, 0.35, 0.30), 0.8855, -0.115, 0.5756, -0.424),
    ],
)
def test_ladder_math_matches_docs07_table(
    c: float, frac: tuple[float, float, float], avg: float, avg_vs: float, t2: float, t2_vs: float
) -> None:
    lm = ladders.ladder_math(c)
    assert lm.fractions == frac
    assert lm.avg_cost == pytest.approx(avg, abs=5e-5)
    assert lm.avg_vs_initial == pytest.approx(avg_vs, abs=5e-4)
    assert lm.tier2_price == pytest.approx(t2, abs=1e-4)  # 문서 표는 소수 4자리 반올림
    assert lm.tier2_vs_initial == pytest.approx(t2_vs, abs=5e-4)
    # 손실 기여는 사다리와 무관하게 12.25% (= 예산 30% 의 40.8%)
    assert lm.loss_contribution_at_theme_cap == pytest.approx(0.1225)
    assert lm.loss_contribution_at_theme_cap / 0.30 == pytest.approx(0.408, abs=1e-3)


def test_ladder_below_min_confidence_rejected() -> None:
    with pytest.raises(ladders.LadderError):
        ladders.ladder_fractions(0.49)
    assert ladders.ladder_fractions(0.75) == ladders.LADDER_HIGH
    assert ladders.ladder_fractions(0.60) == ladders.LADDER_MID
    assert ladders.ladder_fractions(0.50) == ladders.LADDER_LOW


def test_position_plan_prices_and_time_stop() -> None:
    pick = Pick(
        theme="uranium", ticker="CCJ", role="anchor", entry_price=100.0, prev_cycle_peak_price=300.0
    )
    th = _thesis("uranium", 0.72)
    pp = ladders.build_position_plan(pick, th, target_weight=0.16, asof=ASOF)
    assert pp.leg_weights == pytest.approx((0.08, 0.048, 0.032))
    assert pp.leg_prices == pytest.approx((100.0, 87.0, 77.0))
    assert pp.tier2_price == pytest.approx(59.48, abs=0.01)
    assert pp.tier2_vs_initial == pytest.approx(-0.405, abs=5e-4)
    # w=0.16 → 자본 8% 규칙은 평단 −50% 라 −35% 보다 멀다 → avg−35% 가 유효
    assert pp.tier2_rule == "avg−35%" and pp.tier2_effective_price == pp.tier2_price
    assert pp.r_unit == pytest.approx(100 - 59.48, abs=0.01)
    assert pp.tp1_price == pytest.approx(100 + 2 * (100 - 59.48), abs=0.02)
    assert pp.tp2_r_price == pytest.approx(200.0)
    assert pp.time_stop == date(2028, 2, 22)
    assert pp.tier1_invalidations == th.invalidations
    # 가격이 없으면 비율만
    pp2 = ladders.build_position_plan(
        Pick(theme="uranium", ticker="UEC", role="torque"), th, target_weight=0.1, asof=ASOF
    )
    assert pp2.leg_prices == (None, None, None) and pp2.tier2_effective_price is None
    assert pp2.tier2_vs_initial == pytest.approx(-0.405, abs=5e-4)


def test_position_plan_capital_rule_when_weight_large() -> None:
    """완화로 비중이 0.2286 을 넘으면 자본 8% 규칙이 −35% 보다 먼저 온다."""
    pick = Pick(theme="u", ticker="X", role="anchor", entry_price=100.0)
    pp = ladders.build_position_plan(pick, _thesis("u", 0.65), target_weight=0.40, asof=ASOF)
    assert pp.tier2_rule == "capital 8%"
    assert pp.tier2_effective_price == pytest.approx(91.5 * (1 - 0.08 / 0.40))


# ---------------------------------------------------------------- 입력 계약


def test_load_picks_contract(tmp_path: Path) -> None:
    p = tmp_path / "picks.csv"
    p.write_text(
        "theme,ticker,role,entry_price,adv20_usd,split_first_leg\n"
        "uranium,ccj,anchor,52.1,250000000,false\n"
        "uranium,UEC,torque,,,true\n",
        encoding="utf-8",
    )
    picks = load_picks(p)
    assert [x.ticker for x in picks] == ["CCJ", "UEC"]
    assert picks[0].adv20_usd == 250000000 and picks[1].entry_price is None
    assert picks[1].split_first_leg
    p.write_text("theme,ticker,role\nu,A,anchor\nu,A,torque\n", encoding="utf-8")
    with pytest.raises(InputError, match="중복"):
        load_picks(p)
    p.write_text("theme,ticker,role\nu,A,hero\n", encoding="utf-8")
    with pytest.raises(InputError, match="role"):
        load_picks(p)
    p.write_text("theme,ticker,role,bogus\nu,A,anchor,1\n", encoding="utf-8")
    with pytest.raises(InputError, match="모르는 열"):
        load_picks(p)


def test_parse_thesis_requires_invalidations_and_source() -> None:
    good = {
        "theme_id": "uranium",
        "cycle_confidence": 0.72,
        "cycle_confidence_source": "human",
        "horizon_months": [6, 18],
        "invalidations": [{"observable": "x", "source": "s", "action": "exit"}],
        "triggers": [{"observable": "t", "source": "s", "by": "2027-01"}],
        "gate_result": {"status": "passed", "portfolio_eligible": True},
        "value_trap_axes": {"unit_demand": {"axis1_available": True}},
    }
    t = parse_thesis(good)
    assert t.invalidations == ("x [s]",) and t.triggers == ("t [s]",)
    assert t.axis1_available is True and t.portfolio_eligible
    bad = dict(good, invalidations=[])
    with pytest.raises(InputError, match="invalidations"):
        parse_thesis(bad)
    bad = {k: v for k, v in good.items() if k != "cycle_confidence_source"}
    with pytest.raises(InputError, match="cycle_confidence_source"):
        parse_thesis(bad)
    bad = dict(good, cycle_confidence=1.2)
    with pytest.raises(InputError):
        parse_thesis(bad)
    contested = dict(good, gate_result={"status": "contested"})
    assert parse_thesis(contested).portfolio_eligible is False


# ---------------------------------------------------------------- 끝에서 끝 (합성)


def _write_inputs(
    d: Path, *, c_uranium: float = 0.72, c_grid: float = 0.66, c_low: float = 0.40
) -> None:
    (d / "theses").mkdir(parents=True)
    (d / "picks.csv").write_text(
        "theme,ticker,role,entry_price,adv20_usd,prev_cycle_peak_price\n"
        "uranium,CCJ,anchor,50.0,300000000,120\n"
        "uranium,UEC,torque,6.0,50000000,\n"
        "grid_equipment,PWR,anchor,200.0,400000000,\n"
        "grid_equipment,GEV,torque,300.0,900000000,\n"
        "coal,BTU,torque,20.0,80000000,\n",
        encoding="utf-8",
    )
    for theme, c in (("uranium", c_uranium), ("grid_equipment", c_grid), ("coal", c_low)):
        yaml.safe_dump(
            {
                "theme_id": theme,
                "generated_at": "2026-08-20",
                "cycle_confidence": c,
                "cycle_confidence_source": "human",
                "horizon_months": [6, 18],
                "invalidations": [
                    {"observable": f"{theme} 무효화 1", "source": "src", "action": "exit"}
                ],
                "triggers": [{"observable": f"{theme} 트리거 1", "source": "src", "by": "2027-02"}],
                "tailwind": 0.41,
            },
            (d / "theses" / f"{theme}.yaml").open("w", encoding="utf-8"),
            allow_unicode=True,
        )


def test_build_portfolio_end_to_end(tmp_path: Path) -> None:
    themes = load_themes(REPO / "state" / "themes.yaml")
    _write_inputs(tmp_path)
    cases_path = tmp_path / "cases.yaml"
    cases_path.write_text(
        textwrap.dedent(
            """
            cases:
              - id: death_nuclear_x
                name_ko: x
                type: death
                theme_ids: []
                clusters: [nuclear]
                drawdown_peak_to_trough: 0.80
                peak_date: "2011"
                trough_date: "2016"
                verified: true
                sources: [{url: "https://example.org", title: t, date: "2020"}]
            """
        ),
        encoding="utf-8",
    )
    inputs = load_inputs(tmp_path, cases_path=cases_path, capital_usd=2_000_000)
    daily = _synthetic_daily_ew(["uranium", "grid_equipment", "coal"])  # uranium 에 −70% 에피소드
    res = build_portfolio(
        inputs, asof=ASOF, themes=themes, daily_ew=daily, inputs_dir=str(tmp_path)
    )
    assert res.solution is not None and res.solution.status == "optimal"
    w = res.solution.weights
    assert "BTU" not in w  # C6: coal c=0.40 < 0.5 → 변수에서 빠짐
    assert set(w) == {"CCJ", "UEC", "PWR", "GEV"}
    assert all(v <= 0.15 + 1e-6 for v in w.values())
    assert res.solution.theme_weights["uranium"] <= 0.35 + 1e-6
    # L_i: uranium 은 hist(−70% 에피소드) + 케이스(클러스터 nuclear) → 계산됨; grid 는 케이스 없음
    rows = {r.theme: r for r in res.theme_rows}
    assert (
        rows["uranium"].scenario.computable
        and rows["uranium"].scenario.case_id == "death_nuclear_x"
    )
    assert (
        rows["uranium"].scenario.hist_term is not None and rows["uranium"].scenario.hist_term > 0.3
    )
    assert not rows["grid_equipment"].scenario.computable
    assert "PWR" in res.solution.scenario_missing and "GEV" in res.solution.scenario_missing
    assert any("grid_equipment: L_i 형성 불가" in x for x in res.warnings)
    # c̃: 편입 후보 둘의 평균 0.69, λ=0.3
    assert rows["uranium"].c_tilde == pytest.approx(0.69 + 0.7 * 0.03)
    assert rows["grid_equipment"].c_tilde == pytest.approx(0.69 - 0.7 * 0.03)
    assert rows["coal"].c_tilde is None and not rows["coal"].eligible
    # 축 1: uranium·coal 은 physical_ref 보유, grid_equipment 는 아님 → 경고
    assert rows["uranium"].axis1_declared and not rows["grid_equipment"].axis1_declared
    assert any("grid_equipment: 축 1 적용 불가" in x for x in res.warnings)
    assert res.axis1_universe == (45, 134)
    assert res.enb is not None and 1.0 <= res.enb.enb <= 2.0 + 1e-6  # 테마 사상(β=1) → 테마 수 이하
    assert res.cov is not None and res.cov.source == "theme_ew_monthly"
    # 앵커 비중
    assert res.anchor_share is not None and 0.0 < res.anchor_share < 1.0

    # 렌더링 — 필수 표기 항목
    text = render_plan(res)
    for must in (
        "확신도 압축 λ = 0.3",
        "ENB:",
        "p₁",
        "MDD 방식",
        "μ 방식: (a) 균등",
        "L = ",
        "[death_nuclear_x]",
        "C1-(ii) 에서 빠짐",
        "축 1 (물량 추세) 적용 가능 여부",
        "확신도 출처",
        "사람",
        "Tier1",
        "Tier2",
        "초기가 −40.5%",
        "시간스탑  2028-02-22",
        "TP1",
        "러너 트레일 25%",
        "C6 최소 확신도 미달",
        "CLAUDE.md §8",
    ):
        assert must in text, must
    for banned in ("CAGR", "Sharpe", "승률", "기대수익률"):
        assert banned not in text

    # 파일 산출
    out = write_outputs(res, tmp_path / "out")
    assert out.out_dir is not None
    wcsv = pd.read_csv(tmp_path / "out" / "weights.csv")
    assert set(wcsv["ticker"]) == {"CCJ", "UEC", "PWR", "GEV"}
    assert wcsv["target_weight"].sum() == pytest.approx(res.solution.gross, abs=1e-5)
    diag = json.loads((tmp_path / "out" / "diagnostics.json").read_text(encoding="utf-8"))
    assert diag["declared"]["lambda_compress"] == 0.3
    assert diag["solution"]["solver"] == "CLARABEL"
    assert diag["enb"]["enb"] == pytest.approx(res.enb.enb)
    th = {t["theme"]: t for t in diag["themes"]}
    assert th["grid_equipment"]["scenario_loss"]["value"] is None
    assert th["grid_equipment"]["scenario_loss"]["reasons"]
    assert th["uranium"]["c_source"] == "human"
    assert (tmp_path / "out" / "plan.md").read_text(encoding="utf-8") == text


def test_build_portfolio_no_cases_file_is_flagged(tmp_path: Path) -> None:
    themes = load_themes(REPO / "state" / "themes.yaml")
    _write_inputs(tmp_path)
    inputs = load_inputs(tmp_path, cases_path=tmp_path / "nope.yaml")
    daily = _synthetic_daily_ew(["uranium", "grid_equipment", "coal"])
    res = build_portfolio(inputs, asof=ASOF, themes=themes, daily_ew=daily)
    assert res.solution is not None
    assert res.solution.mdd_scenario is None and res.solution.mdd_binding in ("vol", "none")
    assert any("케이스 스터디 표가 없다" in w for w in res.warnings)
    assert any("변동성 기반(i) 만 구속" in w for w in res.warnings)
    assert "C1-(ii) 에서 빠짐" in render_plan(res)


def test_build_portfolio_all_excluded(tmp_path: Path) -> None:
    themes = load_themes(REPO / "state" / "themes.yaml")
    _write_inputs(tmp_path, c_uranium=0.3, c_grid=0.2)
    inputs = load_inputs(tmp_path, cases_path=None)
    daily = _synthetic_daily_ew(["uranium", "grid_equipment", "coal"])
    res = build_portfolio(inputs, asof=ASOF, themes=themes, daily_ew=daily)
    assert res.solution is None and res.positions == ()
    assert "포트폴리오 없음" in render_plan(res)


def test_load_inputs_rejects_missing_thesis(tmp_path: Path) -> None:
    _write_inputs(tmp_path)
    (tmp_path / "theses" / "coal.yaml").unlink()
    with pytest.raises(InputError, match="thesis 가 없는 테마"):
        load_inputs(tmp_path, cases_path=None)


def test_portfolio_inputs_themes_sorted(tmp_path: Path) -> None:
    _write_inputs(tmp_path)
    pi: PortfolioInputs = load_inputs(tmp_path, cases_path=None)
    assert pi.themes() == ["coal", "grid_equipment", "uranium"]
