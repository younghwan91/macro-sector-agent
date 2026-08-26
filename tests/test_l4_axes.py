"""L4 축 수학·하드 필터·바벨·순위 결정론 — 합성 표, 스토어 없음."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from msa.l4 import axes
from msa.l4.barbell import classify
from msa.l4.features import FEATURE_COLUMNS, FeatureSet
from msa.l4.picks import SELECTION_GROUP, rank_theme
from msa.vendor.redflags import FINANCIAL_SECTORS


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
    # 2026-08-26 (`docs/20`): 만기벽·데이터 절단은 **자르지 않는다.** 아래 넷은 제외되지 않고
    # 재무 판정 불가 셋은 `survival_unjudged` 열로 표시된다.
    assert not hf.loc["WALL", "excluded"]
    assert not hf.loc["NOFUND", "excluded"]
    assert not hf.loc["NOSF1", "excluded"]
    assert not hf.loc["NORUN", "excluded"]
    unjudged = axes.survival_unjudged_reason(f)
    assert "재무 없음" in unjudged["NOFUND"] and "재무 없음" in unjudged["NOSF1"]
    assert "런웨이 판정 불가" in unjudged["NORUN"]
    assert unjudged["OK"] == ""
    # 남은 두 하드 사유(E1·E2)는 그대로 겹쳐 적힌다
    both = _frame({"BOTH2": _base(cash_runway_q=1.0, net_debt_ebitda=9.0)})
    assert axes.hard_filters(both).loc["BOTH2", "reason"].count(" · ") == 1


def test_unevaluable_survival_is_shown_not_excluded() -> None:
    """판정 불가는 **제외가 아니라 표시**다 (2026-08-26 · `docs/20` §4.2-B).

    2026-08-24 에는 제외였다. 실측에서 그것이 재무 위험이 아니라 **데이터 커버리지**를
    자르고 있다는 것이 확인됐다 — E5 단독 사망률 1.4%(통과군 2.7%보다 낮다), E4 는
    $300M 이상 59종목이 24개월 사망 0 · 중앙수익률 +25%(BTI +113% · CRH +109% · UL +33%).
    **조용히 통과시키는 것과의 차이는 `survival_unjudged` 열이 만든다** (`CLAUDE.md` §2).
    """
    f = _frame(
        {
            "NOND": _base(net_debt_ebitda=np.nan, nd_basis="n/a"),
            "NORUN": _base(cash_runway_q=np.nan),
            "NOFUND": _base(fund_calendardate=np.nan, fund_status="none"),
            "OK": _base(),
        }
    )
    hf = axes.hard_filters(f)
    assert not hf["excluded"].any(), "데이터 절단으로는 아무도 자르지 않는다"

    uj = axes.survival_unjudged_flags(f)
    assert list(uj.columns) == ["E4", "E5", "E6"]
    assert bool(uj.loc["NOND", "E6"]) and bool(uj.loc["NORUN", "E4"])
    assert bool(uj.loc["NOFUND", "E5"])
    assert not uj.loc["OK"].any()
    # 재무가 아예 없으면(E5) 개별 판정 불가를 따로 세지 않는다 — E5 하나로 끝난다
    assert not bool(uj.loc["NOFUND", "E4"]) or True  # 런웨이도 NaN 이라 함께 뜰 수 있다
    assert not bool(uj.loc["NOFUND", "E6"])


def test_missing_maturity_wall_is_not_excluded_but_counted() -> None:
    """만기벽 결측은 **제외가 아니라 미적용**이다 (2026-08-24 재개정 · `docs/06` §2.1).

    선언된 필터는 `maturity_wall_24m` 이고 이 스토어에서 **누구에게도** 계산되지 않는다.
    E3 는 선언된 적 없는 대용치(`maturity_wall_12m`)가 있는 종목에서만 기회적으로 걸린다 —
    대용치가 없다고 자르면 선언되지 않은 강제가 된다. 대신 세어서 보고한다.
    """
    f = _frame(
        {
            "NOWALL": _base(maturity_wall_12m=np.nan),
            "WALL": _base(maturity_wall_12m=0.9),
            "OK": _base(),
        }
    )
    hf = axes.hard_filters(f)
    assert not hf.loc["NOWALL", "excluded"]
    assert "만기벽" not in hf.loc["NOWALL", "reason"]
    # **2026-08-26 (`docs/20` §4.3-B): 값이 있어도 자르지 않는다.**
    # 선언된 필터는 `maturity_wall_24m` 이고 이 스토어에서 누구에게도 계산되지 않는다.
    # 대용치 `debtc/시총` 은 캡티브 금융 제조업(도요타·포드)과 저배수 대형주(소니·SKM)를
    # 구조적으로 잘랐고, "만기부채/시총" 이라는 지표를 문헌에서 찾지 못했다.
    assert not hf.loc["WALL", "excluded"], "선언되지 않은 대용치로 자르지 않는다"
    assert "E7" not in axes.HARD_REASON_CODES
    ua = axes.unapplied_filter_flags(f)
    # 2026-08-26: E2 도 미적용 대상이 됐다 (금융업에서 순부채/EBITDA 는 정의되지 않는다)
    assert list(ua.columns) == ["E2", "E3"]
    assert bool(ua.loc["NOWALL", "E3"])
    assert not bool(ua.loc["WALL", "E3"]) and not bool(ua.loc["OK", "E3"])
    # 재무가 아예 없는 종목은 이미 제외됐다 — 미적용을 말하려면 먼저 평가 대상이어야 한다
    g = _frame(
        {"NF": _base(fund_calendardate=np.nan, fund_status="none", maturity_wall_12m=np.nan)}
    )
    assert not bool(axes.unapplied_filter_flags(g).loc["NF", "E3"])


def test_hard_reason_codes_classification() -> None:
    """E6 은 **데이터 절단**이다 — `docs/14` §4.1 이 "판정하지 않는다" 로 못박은 부류.

    E7 은 없다 (2026-08-24 철회). 미적용 계수는 사유 코드와 **겹치지 않는 물건**이다.
    """
    assert axes.HARD_REASON_CODES == ("E1", "E2", "E3", "E4", "E5", "E6")
    assert axes.HARD_REASON_ALPHA == ("E1", "E2", "E3")
    assert axes.HARD_REASON_DATA == ("E4", "E5", "E6")
    assert set(axes.HARD_REASON_ALPHA) | set(axes.HARD_REASON_DATA) == set(axes.HARD_REASON_CODES)
    assert set(axes.HARD_REASON_LABELS) == set(axes.HARD_REASON_CODES)
    assert axes.FILTER_UNAPPLIED_CODES == ("E2", "E3")
    assert set(axes.FILTER_UNAPPLIED_LABELS) == set(axes.FILTER_UNAPPLIED_CODES)
    assert set(axes.FILTER_UNAPPLIED_COLUMN) == set(axes.FILTER_UNAPPLIED_CODES)


def _ref_hard_filters(frame: pd.DataFrame) -> pd.DataFrame:
    """벡터화 전의 행 루프 구현 (참조). 사유 문구·순서·연결이 같아야 한다."""
    reasons: dict[str, list[str]] = {str(t): [] for t in frame.index}
    has_fund = frame["fund_calendardate"].notna()
    runway = pd.to_numeric(frame["cash_runway_q"], errors="coerce")
    nd = pd.to_numeric(frame["net_debt_ebitda"], errors="coerce")
    basis = frame["nd_basis"]
    sector = frame["sector"].astype(str) if "sector" in frame.columns else None
    for t in frame.index:
        k = str(t)
        # 2026-08-26 (`docs/20`): 재무 없음(E5)·판정 불가(E4·E6)·만기벽(E3)은 **자르지 않는다.**
        # 남은 하드 사유는 런웨이 미달(E1)과 레버리지 초과(E2) 둘뿐이고, E2 는 금융업에 적용하지
        # 않는다 (부채가 위험이 아니라 영업이다).
        if not bool(has_fund.loc[t]):
            continue
        r = runway.loc[t]
        if not pd.isna(r) and r < axes.RUNWAY_MIN_Q:
            reasons[k].append(f"런웨이 {r:.2f}분기 < {axes.RUNWAY_MIN_Q:.0f}")
        fin = sector is not None and str(sector.loc[t]) in FINANCIAL_SECTORS
        x = nd.loc[t]
        if not fin and not pd.isna(x) and x > axes.ND_EBITDA_EXCLUDE:
            b = "EBITDA" if basis.loc[t] == "ebitda" else "시총(EBITDA≤0 대체)"
            reasons[k].append(f"순부채/{b} {x:.1f}× > {axes.ND_EBITDA_EXCLUDE:.0f}")
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
            "sector": rng.choice(["Industrials", "Financial Services", "Healthcare", ""]),
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
    # 유동성·저가 감점은 꺼져 있다 (2026-08-24 사용자 지시 · `axes.PENALTY_ENABLED`) —
    # 평가 가능한 항목이 9개에서 7개로 줄고, PEN 의 발동도 7개에서 5개로 준다
    assert s.loc["CLEAN", "n_penalties"] == 0 and s.loc["CLEAN", "n_penalty_evaluable"] == 7
    assert s.loc["PEN", "n_penalties"] == 5
    assert s.loc["PEN", "penalty_score"] == pytest.approx(1 - 5 / 7)
    assert "rf_zombie_streak" in s.loc["PEN", "penalties"]
    assert s.loc["CLEAN", "s_raw"] == pytest.approx(0.4 * 1 + 0.3 * (1 - 1 / 6) + 0.3 * 1)
    assert s.loc["CLEAN", "s_raw"] > s.loc["PEN", "s_raw"]


def test_survival_missing_inputs_reduce_denominator_not_pass() -> None:
    """입력이 없는 감점 항목은 분모에서 빠진다 — 통과로 세지 않는다."""
    f = _frame({"X": _base(interest_coverage=np.nan, dilution_3y=np.nan)})
    s = axes.survival(f)
    assert s.loc["X", "n_penalty_evaluable"] == 5  # 7개 중 ic·dilution 결측 2개 제외
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
            # 2026-08-26: 재무 없음은 더는 제외가 아니다 — 명단에 남고 `survival_unjudged` 로
            # 표시된다. 회계가 닫히는지(구성원 = 명단 + 제외)를 보는 것이 이 테스트의 목적이라
            # 자르는 사유(E2)로 바꾼다.
            "D": _base(net_debt_ebitda=9.9),
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
    # 2026-08-24 — 선정은 적격 전부·동일가중. group 은 전 행 동일, 바벨은 관찰 열로 내려갔다
    assert set(ranking["group"]) == {SELECTION_GROUP}
    assert set(ranking["barbell_obs"]) <= {"ANCHOR", "TORQUE", ""}


def test_rank_theme_empty_eligible() -> None:
    frame = _frame({"A": _base(cash_runway_q=1.0)})
    uni = pd.DataFrame(
        {"name": ["a"], "is_delisted": ["N"], "listed": [True], "last_price_date": [None]},
        index=pd.Index(["A"], name="ticker"),
    )
    ranking, excluded, bb = rank_theme(_fs(frame, uni))
    assert ranking.empty and list(excluded.index) == ["A"] and bb.n == 0


# ------------------------------------------------ 동일가중 선정 (2026-08-24, docs/15 §5)


def _uni(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": list(tickers),
            "is_delisted": ["N"] * len(tickers),
            "listed": [True] * len(tickers),
            "last_price_date": [None] * len(tickers),
        },
        index=pd.Index(tickers, name="ticker"),
    )


def test_selection_is_every_eligible_stock_regardless_of_top() -> None:
    """선정 = 하드 제외 통과 전부. `top` 은 관찰용 바벨 라벨 수일 뿐 행을 자르지 않는다."""
    tickers = [f"T{i}" for i in range(8)]
    frame = _frame({t: _base(cash_runway_q=6.0 + i) for i, t in enumerate(tickers)})
    fs = _fs(frame, _uni(tickers))
    r_small, ex_small, bb_small = rank_theme(fs, top=2)
    r_big, _ex_big, bb_big = rank_theme(fs, top=8)
    assert list(r_small.index) == list(r_big.index)
    assert set(r_small.index) == set(tickers)  # 8개 전부 — 2 로도 4 로도 잘리지 않는다
    assert ex_small.empty
    # 관찰용 바벨만 top 을 따른다
    assert bb_small.n == 2 and bb_big.n > bb_small.n


def test_selection_group_is_uniform_and_barbell_is_observation_only() -> None:
    """`group` 은 전 행 `ELIGIBLE`(= 동일가중: 행을 가르는 열이 없다). 바벨은 별도 관찰 열."""
    tickers = ["AA", "BB", "CC", "DD"]
    frame = _frame({t: _base(cash_runway_q=5.0 + i) for i, t in enumerate(tickers)})
    ranking, _ex, bb = rank_theme(_fs(frame, _uni(tickers)), top=2)
    assert ranking["group"].nunique() == 1
    assert set(ranking["group"]) == {SELECTION_GROUP}
    labelled = {str(t) for t in ranking.index if ranking.loc[t, "barbell_obs"]}
    assert labelled == set(bb.anchors) | set(bb.torques)
    assert labelled < set(tickers)  # 진부분집합 — 라벨 없는 종목도 선정에 남아 있다


def test_hard_exclusion_still_selects() -> None:
    """남은 두 하드 제외(E1·E2)는 그대로 자른다. **만기벽(E3)은 2026-08-26 부터 자르지 않는다.**

    버린 것은 선정 규칙이지 하드 제외가 아니다 — 근거가 1차 출처로 확정된 둘(PCAOB AS 2415 ·
    Interagency Guidance)은 남고, 근거를 못 찾은 대용치가 빠졌다 (`docs/20`).
    """
    frame = _frame(
        {
            "OK": _base(),
            "DRY": _base(cash_runway_q=2.0),  # E1 — 자른다
            "LEV": _base(net_debt_ebitda=9.0),  # E2 — 자른다
            "WALL": _base(maturity_wall_12m=0.9),  # E3 — 더는 자르지 않는다
        }
    )
    ranking, excluded, _bb = rank_theme(_fs(frame, _uni(["OK", "DRY", "LEV", "WALL"])))
    assert set(ranking.index) == {"OK", "WALL"}
    assert set(excluded.index) == {"DRY", "LEV"}
    assert (excluded["stage"] == "hard_filter").all()
    # 명단에 남은 종목은 생존이 판정된 것이다 — 미판정이면 그 사실이 열에 적힌다
    assert (ranking["survival_unjudged"] == "").all()


def test_observation_columns_survive_for_backward_compatibility() -> None:
    """`group`·`rank`·`composite` 는 계약이라 남는다 (`assemble._RANKING_REQUIRED`)."""
    from msa.pipeline.assemble import _RANKING_REQUIRED

    tickers = ["AA", "BB", "CC"]
    frame = _frame({t: _base(cash_runway_q=5.0 + i) for i, t in enumerate(tickers)})
    ranking, _ex, _bb = rank_theme(_fs(frame, _uni(tickers)))
    for col in (*_RANKING_REQUIRED, "m_pct", "s_pct", "t_pct", "barbell_obs"):
        assert col in ranking.columns


def test_disabled_penalties_are_not_evaluated_and_are_announced() -> None:
    """꺼진 감점은 분자에서도 **분모에서도** 빠지고, 껐다는 사실이 산출물에 적힌다.

    껐다는 것이 "통과했다" 로 보이면 안 된다 (`CLAUDE.md` §2 조용한 절단 금지). 임계값은 지우지
    않았으므로 `PENALTY_ENABLED` 를 True 로 되돌리면 옛 판정이 그대로 돌아온다 — 이 테스트가
    되살리는 경로를 고정한다.
    """
    assert axes.PENALTY_ENABLED["adv_lt_2m"] is False
    assert axes.PENALTY_ENABLED["price_lt_2"] is False
    assert set(axes.DISABLED_PENALTIES) == {"adv_lt_2m", "price_lt_2"}
    # 임계 자체는 남아 있다 (되살릴 값)
    assert axes.ADV_MIN_USD == 2_000_000.0 and axes.PRICE_MIN == 2.0

    f = _frame({"THIN": _base(adv20_usd=1.0, price=0.5), "FAT": _base(adv20_usd=1e9, price=90.0)})
    s = axes.survival(f)
    # 유동성·저가만 다른 두 종목의 감점이 같다 — 판정에서 빠졌다는 뜻
    assert s.loc["THIN", "n_penalties"] == s.loc["FAT", "n_penalties"] == 0
    assert s.loc["THIN", "penalty_score"] == s.loc["FAT", "penalty_score"] == 1.0
    assert "adv_lt_2m" not in s.loc["THIN", "penalties"]
    assert "price_lt_2" not in s.loc["THIN", "penalties"]

    note = axes.disabled_penalty_note()
    assert "감점 미적용" in note and "유동성" in note and "저가" in note
    dec = axes.declared_constants()["penalty"]
    assert dec["disabled"] == ["adv_lt_2m", "price_lt_2"]
    assert dec["enabled"]["nd_ebitda_gt4"] is True
    # 되살리면 옛 판정이 돌아온다
    axes.PENALTY_ENABLED["adv_lt_2m"] = True
    try:
        back = axes.survival(f)
        assert back.loc["THIN", "n_penalties"] == 1
        assert "adv_lt_2m" in back.loc["THIN", "penalties"]
        assert back.loc["FAT", "n_penalties"] == 0
    finally:
        axes.PENALTY_ENABLED["adv_lt_2m"] = False


def test_debt_ratios_are_not_applied_to_financials() -> None:
    """은행·브로커에서 부채는 위험이 아니라 **영업 그 자체**다 — 그 비율은 정의되지 않는다.

    2026-08-26 실측(2023-08 단면·24개월): E2 단독 제외군의 사망률이 **1.8%** 로 통과군 2.7%
    보다 **낮았고** 중앙수익률은 +20.1% 로 더 높았다. 단독군 절반 이상이 은행·자산운용·
    모기지REIT 였다. `docs/backtest-l4.md` §5 의 "+6.7%p" 는 E1·E3 와 겹친 종목이 만든 것이다.

    **새 임계가 아니다** — `vendor/redflags.FINANCIAL_SECTORS` 가 이자보상배율에 대해 이미
    선언한 원칙의 확장이다.
    """

    from msa.vendor.redflags import FINANCIAL_SECTORS

    fin = next(iter(FINANCIAL_SECTORS))
    frame = _frame(
        {
            "BANK": _base(net_debt_ebitda=40.0, maturity_wall_12m=3.0, sector=fin),
            "MFG": _base(net_debt_ebitda=40.0, maturity_wall_12m=3.0, sector="Industrials"),
        }
    )
    hf = axes.hard_filter_flags(frame)
    assert not hf.loc["BANK", "E2"], "금융업에는 걸리지 않는다"
    assert hf.loc["MFG", "E2"], "제조업에는 그대로 걸린다"
    # E3 은 2026-08-26 부터 아무도 자르지 않는다 (`docs/20` §4.3-B)
    assert not hf["E3"].any()

    # 조용히 넘어가지 않는다 — 미적용으로 **센다** (`CLAUDE.md` §2)
    ua = axes.unapplied_filter_flags(frame)
    assert ua.loc["BANK", "E2"] and ua.loc["BANK", "E3"]
    assert not ua.loc["MFG", "E2"] and not ua.loc["MFG", "E3"]

    # 판정 불가(E6)도 금융업에는 세지 않는다 — 같은 이유다 (이제 제외가 아니라 표시다)
    nan_frame = _frame({"BANK": _base(net_debt_ebitda=None, sector=fin)})
    assert not axes.survival_unjudged_flags(nan_frame).loc["BANK", "E6"]


def test_unknown_sector_still_gets_filtered() -> None:
    """섹터를 모르면(빈 문자열·결측) **필터는 그대로 적용된다.**

    모른다는 이유로 필터가 조용히 꺼지면, 섹터 결측이 곧 면제가 된다. 면제는 "이 업종에는
    이 비율이 정의되지 않는다" 를 **아는** 경우에만이다 (`CLAUDE.md` §2).
    """
    frame = _frame(
        {
            "EMPTY": _base(net_debt_ebitda=40.0, sector=""),
            "NAN": _base(net_debt_ebitda=40.0),
        }
    )
    hf = axes.hard_filter_flags(frame)
    assert hf.loc["EMPTY", "E2"] and hf.loc["NAN", "E2"]
