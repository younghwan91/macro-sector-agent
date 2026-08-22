"""L4 축 수학·하드 필터·바벨·순위 결정론 — 합성 표, 스토어 없음."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from msa.l4 import axes
from msa.l4.barbell import classify
from msa.l4.features import FEATURE_COLUMNS, FeatureSet
from msa.l4.picks import rank_theme


def _frame(rows: dict[str, dict[str, object]]) -> pd.DataFrame:
    df = pd.DataFrame.from_dict(rows, orient="index")
    for c in FEATURE_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df.index.name = "ticker"
    return df[list(FEATURE_COLUMNS)]


def _base(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "fund_calendardate": pd.Timestamp("2026-06-30").date(),
        "fund_status": "ok",
        "price": 10.0,
        "mcap": 1e9,
        "cash": 1e8,
        "cash_runway_q": np.inf,
        "net_debt_ebitda": 1.0,
        "nd_basis": "ebitda",
        "maturity_wall_12m": 0.05,
        "interest_coverage": 5.0,
        "dilution_3y": 0.02,
        "adv20_usd": 5e6,
        "red_flags": "",
        "margin_headroom": 0.1,
        "opleverage": 2.0,
        "fixed_cost_ratio": 0.4,
        "price_beta_hist": 0.5,
        "equity_leverage": 1.2,
        "marginal_producer": False,
        "stage2": False,
        "rs_rating": 50.0,
        "vcp_base": False,
        "from_52w_low": 0.2,
        "above_50d": True,
        "rvol_expansion": 1.0,
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------- 하드 필터


def test_hard_filters_each_rule_logged_with_reason() -> None:
    f = _frame(
        {
            "OK": _base(),
            "RUN": _base(cash_runway_q=3.9),
            "LEV": _base(net_debt_ebitda=6.1),
            "LEVM": _base(net_debt_ebitda=7.0, nd_basis="mcap"),
            "WALL": _base(maturity_wall_12m=0.51),
            "NOFUND": _base(fund_calendardate=np.nan, fund_status="stale"),
            "NOSF1": _base(fund_calendardate=np.nan, fund_status="none"),
            "NORUN": _base(cash_runway_q=np.nan),
            "BOTH": _base(cash_runway_q=1.0, maturity_wall_12m=0.9),
        }
    )
    hf = axes.hard_filters(f)
    assert not hf.loc["OK", "excluded"]
    assert hf.loc["RUN", "excluded"] and "런웨이 3.9" in hf.loc["RUN", "reason"]
    assert hf.loc["LEV", "excluded"] and "순부채/EBITDA 6.1" in hf.loc["LEV", "reason"]
    assert "시총" in hf.loc["LEVM", "reason"]
    assert "만기벽" in hf.loc["WALL", "reason"]
    assert "15개월" in hf.loc["NOFUND", "reason"]
    assert "SF1 에 행 0개" in hf.loc["NOSF1", "reason"]
    assert "판정 불가" in hf.loc["NORUN", "reason"]
    assert hf.loc["BOTH", "reason"].count(" · ") == 1  # 두 사유가 전부 남는다


def _ref_hard_filters(frame: pd.DataFrame) -> pd.DataFrame:
    """벡터화 전의 행 루프 구현 (참조). 사유 문구·순서·연결이 같아야 한다."""
    reasons: dict[str, list[str]] = {str(t): [] for t in frame.index}
    has_fund = frame["fund_calendardate"].notna()
    runway = pd.to_numeric(frame["cash_runway_q"], errors="coerce")
    nd = pd.to_numeric(frame["net_debt_ebitda"], errors="coerce")
    basis = frame["nd_basis"]
    wall = pd.to_numeric(frame["maturity_wall_12m"], errors="coerce")
    status = frame["fund_status"]
    for t in frame.index:
        k = str(t)
        if not bool(has_fund.loc[t]):
            if str(status.loc[t]) == "none":
                reasons[k].append(
                    "재무 없음 (SF1 에 행 0개 — 20-F 해외발행사 등 미수록) — 생존 필터 판정 불가"
                )
            else:
                reasons[k].append("재무 없음 (asof 이전 15개월 내 분기 없음) — 생존 필터 판정 불가")
            continue
        r = runway.loc[t]
        if pd.isna(r):
            reasons[k].append("런웨이 판정 불가 (현금흐름표 또는 현금 없음) — 하드 필터 미통과")
        elif r < axes.RUNWAY_MIN_Q:
            reasons[k].append(f"런웨이 {r:.2f}분기 < {axes.RUNWAY_MIN_Q:.0f}")
        x = nd.loc[t]
        if pd.notna(x) and x > axes.ND_EBITDA_EXCLUDE:
            b = "EBITDA" if basis.loc[t] == "ebitda" else "시총(EBITDA≤0 대체)"
            reasons[k].append(f"순부채/{b} {x:.1f}× > {axes.ND_EBITDA_EXCLUDE:.0f}")
        w = wall.loc[t]
        if pd.notna(w) and w > axes.MATURITY_WALL_EXCLUDE:
            reasons[k].append(f"만기벽(12m 대용) {w:.2f} > {axes.MATURITY_WALL_EXCLUDE}")
    out = pd.DataFrame(index=frame.index)
    out["reason"] = pd.Series({k: " · ".join(v) for k, v in reasons.items()}).reindex(frame.index)
    out["excluded"] = out["reason"].str.len() > 0
    return out


def test_hard_filters_vectorized_equals_reference() -> None:
    rng = np.random.default_rng(11)
    rows: dict[str, dict[str, object]] = {}
    for i in range(300):
        kw: dict[str, object] = {
            "cash_runway_q": rng.choice([np.nan, np.inf, 1.0, 3.99, 4.0, 12.5, 50.0]),
            "net_debt_ebitda": rng.choice([np.nan, -1.0, 2.0, 6.0, 6.1, 9.37]),
            "nd_basis": rng.choice(["ebitda", "mcap", "n/a"]),
            "maturity_wall_12m": rng.choice([np.nan, 0.0, 0.5, 0.51, 1.234]),
        }
        if i % 7 == 0:
            kw["fund_calendardate"] = np.nan
            kw["fund_status"] = rng.choice(["stale", "none"])
        rows[f"T{i:03d}"] = _base(**kw)
    f = _frame(rows)
    pd.testing.assert_frame_equal(axes.hard_filters(f), _ref_hard_filters(f))


def test_hard_filter_boundaries_are_not_inclusive() -> None:
    f = _frame(
        {
            "A": _base(cash_runway_q=4.0),
            "B": _base(net_debt_ebitda=6.0),
            "C": _base(maturity_wall_12m=0.5),
        }
    )
    assert not axes.hard_filters(f)["excluded"].any()


# ---------------------------------------------------------------- S 축


def test_survival_runway_cap_and_inf() -> None:
    f = _frame(
        {
            "INF": _base(cash_runway_q=np.inf),
            "R4": _base(cash_runway_q=4.0),
            "R8": _base(cash_runway_q=8.0),
            "R40": _base(cash_runway_q=40.0),
        }
    )
    s = axes.survival(f)
    assert s.loc["INF", "runway_score"] == 1.0
    assert s.loc["R4", "runway_score"] == pytest.approx(0.5)
    assert s.loc["R8", "runway_score"] == 1.0
    assert s.loc["R40", "runway_score"] == 1.0


def test_survival_leverage_and_penalties() -> None:
    f = _frame(
        {
            "CLEAN": _base(),
            "NETCASH": _base(net_debt_ebitda=-2.0),
            "PEN": _base(
                net_debt_ebitda=4.5,
                interest_coverage=0.5,
                dilution_3y=0.2,
                adv20_usd=1e6,
                price=1.5,
                red_flags="consecutive_operating_loss;zombie_streak",
            ),
        }
    )
    s = axes.survival(f)
    assert s.loc["CLEAN", "leverage_score"] == pytest.approx(1 - 1 / 6)
    assert s.loc["NETCASH", "leverage_score"] == 1.0
    assert s.loc["CLEAN", "n_penalties"] == 0 and s.loc["CLEAN", "n_penalty_evaluable"] == 9
    assert s.loc["PEN", "n_penalties"] == 7
    assert s.loc["PEN", "penalty_score"] == pytest.approx(1 - 7 / 9)
    assert "rf_zombie_streak" in s.loc["PEN", "penalties"]
    assert s.loc["CLEAN", "s_raw"] == pytest.approx(0.4 * 1 + 0.3 * (1 - 1 / 6) + 0.3 * 1)
    assert s.loc["CLEAN", "s_raw"] > s.loc["PEN", "s_raw"]


def test_survival_missing_inputs_reduce_denominator_not_pass() -> None:
    """입력이 없는 감점 항목은 분모에서 빠진다 — 통과로 세지 않는다."""
    f = _frame({"X": _base(interest_coverage=np.nan, dilution_3y=np.nan)})
    s = axes.survival(f)
    assert s.loc["X", "n_penalty_evaluable"] == 7
    assert s.loc["X", "penalty_score"] == 1.0
    assert s.loc["X", "s_inputs_missing"] == ""


def test_survival_reports_missing_leverage() -> None:
    f = _frame({"X": _base(net_debt_ebitda=np.nan, nd_basis="n/a")})
    s = axes.survival(f)
    assert s.loc["X", "s_inputs_missing"] == "leverage"
    # runway 0.4 + penalty 0.3 → 재정규화: (0.4·1 + 0.3·1)/0.7 = 1
    assert s.loc["X", "s_raw"] == pytest.approx(1.0)


# ---------------------------------------------------------------- T·M 축


def test_torque_percentiles_and_min_inputs() -> None:
    f = _frame(
        {
            "HI": _base(
                margin_headroom=0.5,
                opleverage=5,
                fixed_cost_ratio=0.8,
                price_beta_hist=2,
                equity_leverage=2.0,
                marginal_producer=True,
            ),
            "LO": _base(
                margin_headroom=0.0,
                opleverage=0.5,
                fixed_cost_ratio=0.1,
                price_beta_hist=0.1,
                equity_leverage=1.0,
                marginal_producer=False,
            ),
            "THIN": _base(
                margin_headroom=np.nan,
                opleverage=np.nan,
                fixed_cost_ratio=np.nan,
                price_beta_hist=np.nan,
                equity_leverage=1.5,
                marginal_producer=pd.NA,
            ),
        }
    )
    t = axes.torque(f)
    assert t.loc["HI", "t_raw"] > t.loc["LO", "t_raw"]
    assert t.loc["HI", "tp_marginal_producer"] == 1.0 and t.loc["LO", "tp_marginal_producer"] == 0.0
    assert t.loc["THIN", "t_n_inputs"] == 1
    assert np.isnan(t.loc["THIN", "t_raw"])
    assert "margin_headroom" in t.loc["THIN", "t_inputs_missing"]


def test_timing_components() -> None:
    f = _frame(
        {
            "A": _base(
                stage2=True,
                rs_rating=90,
                vcp_base=True,
                above_50d=True,
                from_52w_low=0.8,
                rvol_expansion=1.5,
            ),
            "B": _base(
                stage2=False,
                rs_rating=10,
                vcp_base=False,
                above_50d=False,
                from_52w_low=0.0,
                rvol_expansion=0.8,
            ),
            "C": _base(
                stage2=None,
                rs_rating=np.nan,
                vcp_base=None,
                above_50d=None,
                from_52w_low=np.nan,
                rvol_expansion=np.nan,
            ),
        }
    )
    m = axes.timing(f)
    assert m.loc["A", "m_raw"] > m.loc["B", "m_raw"]
    assert m.loc["A", "m_n_inputs"] == 6
    assert np.isnan(m.loc["C", "m_raw"]) and m.loc["C", "m_n_inputs"] == 0


# ---------------------------------------------------------------- 종합·순위


def test_score_composite_weights_and_partial_flag() -> None:
    f = _frame(
        {
            "A": _base(),
            "B": _base(
                margin_headroom=np.nan,
                opleverage=np.nan,
                fixed_cost_ratio=np.nan,
                price_beta_hist=np.nan,
                marginal_producer=pd.NA,
            ),
        }
    )
    sc = axes.score(f)
    a = sc.loc["A"]
    assert a["composite"] == pytest.approx(0.4 * a["s_pct"] + 0.4 * a["t_pct"] + 0.2 * a["m_pct"])
    assert not a["composite_partial"]
    b = sc.loc["B"]
    assert b["composite_partial"]
    assert b["composite"] == pytest.approx((0.4 * b["s_pct"] + 0.2 * b["m_pct"]) / 0.6)


def test_ranking_is_deterministic_under_shuffle_and_ties() -> None:
    rows = {
        f"T{i:02d}": _base(cash_runway_q=float(i + 1), rs_rating=float(10 * (i % 5)))
        for i in range(12)
    }
    f = _frame(rows)
    r1 = axes.score(f)
    r2 = axes.score(f.sample(frac=1.0, random_state=7))
    assert list(r1.index) == list(r2.index)
    assert list(r1["rank"]) == list(range(1, 13))
    # 완전 동률이면 티커 오름차순
    same = _frame({"ZZZ": _base(), "AAA": _base(), "MMM": _base()})
    assert list(axes.score(same).index) == ["AAA", "MMM", "ZZZ"]


# ---------------------------------------------------------------- 바벨


def test_barbell_anchor_from_top_s_highest_t_and_torque_excludes_bottom_s() -> None:
    sc = pd.DataFrame(
        {
            "s_pct": [1.0, 0.8, 0.6, 0.4, 0.2],
            "t_pct": [0.2, 0.9, 1.0, 0.8, 0.95],
            "marginal_producer": [False, False, True, False, False],
        },
        index=["SAFE", "GOOD", "MARG", "MID", "RISKY"],
    )
    bb = classify(sc, top=4)
    # S̃≥0.5 & 비한계생산자 중 T̃ 최고 → GOOD, 그다음 SAFE (n_anchor = 2)
    assert bb.anchors == ["GOOD", "SAFE"]
    # 토크: T̃ 순 중 S̃ ≤ 0.25(RISKY) 제외, 앵커 제외 → MARG, MID
    assert bb.torques == ["MARG", "MID"]
    assert bb.anchor_share == pytest.approx(0.5)
    assert bb.label("MARG") == "TORQUE" and bb.label("RISKY") == ""


def test_barbell_fills_from_torque_when_no_anchor_candidates() -> None:
    sc = pd.DataFrame(
        {
            "s_pct": [0.4, 0.3, 0.45],
            "t_pct": [0.9, 0.5, 0.7],
            "marginal_producer": [False, False, False],
        },
        index=["A", "B", "C"],
    )
    bb = classify(sc, top=3)
    assert bb.anchors == []
    assert bb.torques == ["A", "C", "B"]
    assert bb.anchor_share == 0.0


def test_barbell_torque_requires_computable_t() -> None:
    sc = pd.DataFrame(
        {
            "s_pct": [0.9, 0.6, 0.8],
            "t_pct": [0.7, np.nan, np.nan],
            "marginal_producer": [False] * 3,
        },
        index=["A", "B", "C"],
    )
    bb = classify(sc, top=4)
    assert bb.anchors == ["A", "C"]  # T̃ NaN 은 앵커에서 맨 뒤 (s_pct 로 C > B)
    assert bb.torques == []  # T̃ 없는 종목은 토크가 될 수 없다
    assert bb.anchor_share == 1.0


def test_barbell_top_1_and_empty() -> None:
    assert classify(pd.DataFrame(columns=["s_pct", "t_pct"]), top=4).n == 0
    sc = pd.DataFrame(
        {"s_pct": [0.9, 0.1], "t_pct": [0.5, 0.9], "marginal_producer": [False, False]},
        index=["A", "B"],
    )
    bb = classify(sc, top=1)
    assert bb.anchors == ["A"] and bb.torques == []
    with pytest.raises(ValueError):
        classify(sc, top=0)


# ---------------------------------------------------------------- 제외 회계 (rank_theme)


def _fs(frame: pd.DataFrame, universe: pd.DataFrame) -> FeatureSet:
    return FeatureSet(
        theme="t",
        asof=pd.Timestamp("2026-08-14"),
        store_end=pd.Timestamp("2026-08-14"),
        frame=frame,
        universe=universe,
    )


def test_rank_theme_accounts_for_every_member() -> None:
    frame = _frame(
        {
            "A": _base(),
            "B": _base(cash_runway_q=2.0),
            "C": _base(),
            "D": _base(fund_calendardate=np.nan),
        }
    )
    uni = pd.DataFrame(
        {
            "name": ["a", "b", "c", "d", "e", "f"],
            "is_delisted": ["N", "N", "N", "N", "Y", "N"],
            "listed": [True, True, True, True, False, False],
            "last_price_date": [None] * 6,
        },
        index=pd.Index(["A", "B", "C", "D", "DEAD", "STALE"], name="ticker"),
    )
    ranking, excluded, _bb = rank_theme(_fs(frame, uni), top=2)
    assert set(ranking.index) == {"A", "C"}
    assert set(excluded.index) == {"B", "D", "DEAD", "STALE"}
    assert excluded.loc["DEAD", "stage"] == "listing" and excluded.loc["DEAD", "reason"] == "폐지"
    assert (
        excluded.loc["STALE", "stage"] == "listing"
        and "가격 없음" in excluded.loc["STALE", "reason"]
    )
    assert excluded.loc["B", "stage"] == "hard_filter"
    assert len(ranking) + len(excluded) == len(uni)
    assert set(ranking["group"]) <= {"ANCHOR", "TORQUE", ""}


def test_rank_theme_empty_eligible() -> None:
    frame = _frame({"A": _base(cash_runway_q=1.0)})
    uni = pd.DataFrame(
        {"name": ["a"], "is_delisted": ["N"], "listed": [True], "last_price_date": [None]},
        index=pd.Index(["A"], name="ticker"),
    )
    ranking, excluded, bb = rank_theme(_fs(frame, uni))
    assert ranking.empty and list(excluded.index) == ["A"] and bb.n == 0
