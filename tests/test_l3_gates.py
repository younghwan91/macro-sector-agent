"""하드 게이트 · contested · 확신도 산술 — `docs/04` §3·§3.1·§4 를 합성 판정 집합으로 확인한다."""

from __future__ import annotations

import pytest

from _l3_synth import axis1
from msa.l3.gates import (
    CONF_CAP_ON_DEATH,
    CONF_TERMS,
    AxisVerdicts,
    ConfidenceInputs,
    apply_gates,
    cycle_confidence,
    rejection_row,
)


def _v(
    a1: str = "cycle", a2: str = "cycle", a3: str = "cycle", a4: str = "cycle", a5: str = "warning"
) -> AxisVerdicts:
    return AxisVerdicts(a1, a2, a3, a4, a5)


def _ci(v: AxisVerdicts, **kw) -> ConfidenceInputs:  # type: ignore[no-untyped-def]
    base = {
        "capex_to_da_qtrs_below1": 10.0,
        "axis4_strong_cycle": True,
        "axis5_severe": False,
        "small_sample": False,
        "short_hist": False,
    }
    base.update(kw)
    return ConfidenceInputs(verdicts=v, **base)


# ---------------------------------------------------------------- 확신도


def test_confidence_all_positive_terms_clips_to_one() -> None:
    r = cycle_confidence(_ci(_v()))
    # 0.5 +0.15 +0.10 +0.15 +0.10 = 1.00 → 1.0 (거시 순풍 +0.10 항은 L2 제거로 없다 — docs/04 §4)
    assert r.raw == pytest.approx(1.00)
    assert r.value == 1.0
    assert set(r.terms) == {
        "axis1_cycle",
        "axis2_capex_below1_8q",
        "axis3_no_substitution",
        "axis4_strong_cycle",
    }
    assert "macro_tailwind" not in CONF_TERMS


def test_confidence_base_only() -> None:
    r = cycle_confidence(
        _ci(
            _v("not_applicable", "cycle", "not_applicable", "warning", "warning"),
            capex_to_da_qtrs_below1=3.0,
            axis4_strong_cycle=False,
        )
    )
    assert r.value == 0.5 and r.terms == {}


def test_confidence_negative_terms() -> None:
    r = cycle_confidence(
        _ci(
            _v("warning", "cycle", "warning", "warning", "death"),
            capex_to_da_qtrs_below1=None,
            axis4_strong_cycle=False,
            small_sample=True,
        )
    )
    # 0.5 −0.20 −0.15 −0.15 −0.10 = −0.10 → 0
    assert r.raw == pytest.approx(-0.10)
    assert r.value == 0.0


def test_confidence_death_cap() -> None:
    r = cycle_confidence(_ci(_v("death", "cycle", "cycle", "cycle", "warning")))
    # 0.5 +0.10 +0.15 +0.10 = 0.85 → cap 0.35 (거시 순풍 +0.10 항은 L2 제거로 없다)
    assert r.raw == pytest.approx(0.85)
    assert r.cap == CONF_CAP_ON_DEATH and r.value == CONF_CAP_ON_DEATH
    r3 = cycle_confidence(_ci(_v("cycle", "cycle", "death", "cycle", "warning")))
    assert r3.value == CONF_CAP_ON_DEATH


def test_confidence_axis4_requires_strong_and_cycle() -> None:
    r = cycle_confidence(_ci(_v(a4="warning"), axis4_strong_cycle=True))
    assert "axis4_strong_cycle" not in r.terms
    r = cycle_confidence(_ci(_v(a4="cycle"), axis4_strong_cycle=False))
    assert "axis4_strong_cycle" not in r.terms


def test_confidence_contested_axis1_no_penalty() -> None:
    a = cycle_confidence(_ci(_v("contested")))
    b = cycle_confidence(_ci(_v("not_applicable")))
    assert a.terms == b.terms and "axis1_cycle" not in a.terms and "axis1_warning" not in a.terms


def test_confidence_short_hist_or_small_sample_once() -> None:
    r = cycle_confidence(_ci(_v(), small_sample=True, short_hist=True))
    assert r.terms["small_sample_or_short_hist"] == -0.10


# ---------------------------------------------------------------- 게이트


def _gate(v: AxisVerdicts, a1kind: str = "cycle", **kw):  # type: ignore[no-untyped-def]
    base = {
        "confidence": 0.7,
        "referee_ruling": None,
        "referee_evidence_refs": (),
        "referee_refs_valid": True,
        "secular_risk": False,
        "debt_24m_over_half": False,
    }
    base.update(kw)
    return apply_gates(v, axis1(a1kind), **base)


def test_gate_passed_and_eligible() -> None:
    g = _gate(_v())
    assert g.status == "passed" and g.portfolio_eligible and g.path is None
    assert g.axis_verdicts["terminal_risk"] == "warning"


def test_gate_passed_but_confidence_below_floor() -> None:
    g = _gate(_v(), confidence=0.45)
    assert g.status == "passed" and not g.portfolio_eligible
    assert "07 C6" in g.rule


def test_gate_auto_reject_axis1_death_and_axis3_warning() -> None:
    g = _gate(_v("death", a3="warning"), a1kind="death")
    assert g.status == "rejected" and g.path == "hard_gate" and not g.portfolio_eligible
    g2 = _gate(_v("death", a3="death"), a1kind="death")
    assert g2.status == "rejected"


def test_gate_cap_path_axis1_death_alone() -> None:
    g = _gate(_v("death", a3="cycle"), a1kind="death", confidence=0.35)
    assert g.status == "passed" and not g.portfolio_eligible and "상한" in g.rule
    g3 = _gate(_v("cycle", a3="death"), confidence=0.35)
    assert g3.status == "passed" and not g3.portfolio_eligible


def test_gate_contested_with_ruling_is_held() -> None:
    g = _gate(
        _v("contested"), a1kind="contested", referee_ruling="산업 축소", referee_evidence_refs=(4,)
    )
    assert g.status == "contested" and not g.portfolio_eligible and g.path is None
    assert g.referee_ruling == "산업 축소"


def test_gate_contested_without_ruling_closes_rejected() -> None:
    g = _gate(_v("contested"), a1kind="contested")
    assert g.status == "rejected" and g.path == "hard_gate"
    assert "서술 못 하면 기각" in g.rule
    g2 = _gate(
        _v("contested"), a1kind="contested", referee_ruling="서술만", referee_evidence_refs=()
    )
    assert g2.status == "rejected" and "비어 있음" in g2.reason
    g3 = _gate(
        _v("contested"),
        a1kind="contested",
        referee_ruling="서술",
        referee_evidence_refs=(99,),
        referee_refs_valid=False,
    )
    assert g3.status == "rejected" and "증거 목록에 없음" in g3.reason


def test_gate_contested_precedes_death_rejection() -> None:
    """선행 관문: 보정 전후 뒤집힘이면 사망 기각보다 먼저 contested 로 간다."""
    g = _gate(
        _v("contested", a3="warning"),
        a1kind="contested",
        referee_ruling="x",
        referee_evidence_refs=(1,),
    )
    assert g.status == "contested"


def test_gate_sign_split_is_contested() -> None:
    a = axis1("split")
    assert a.contested and a.verdict == "contested"


def test_gate_secular_risk_requires_proof() -> None:
    g = _gate(_v(a3="warning"), secular_risk=True)
    assert g.status == "passed" and not g.portfolio_eligible and "secular_risk" in g.rule
    g2 = _gate(_v(), secular_risk=True)
    assert g2.portfolio_eligible


def test_gate_debt_flag_keeps_theme_and_says_it_is_not_an_auto_exclusion() -> None:
    """축5 플래그는 테마를 유지하고, **자동 제외가 아님을 명시**한다 (2026-08-25).

    예전 문구는 "L4 종목 선정에서 해당 종목 제외" 였는데 L4 는 이 플래그를 읽지 않았다 —
    선언-미구현이다. 게다가 테마 단위 판정이라 "해당 종목" 이라는 것 자체가 없다.
    이제 문구가 사실을 말하고, 경고는 `ThesisHead` 를 타고 명단 머리로 간다.
    """
    g = _gate(_v(), debt_24m_over_half=True)
    assert g.status == "passed" and g.l4_survival_filter
    note = next(n for n in g.notes if "축5" in n)
    assert "자동 제외" in note and "0.5" in note
    assert g.as_dict()["l4_survival_filter"] is True


def test_gate_axis1_not_applicable_not_treated_as_pass_for_secular() -> None:
    g = _gate(_v("not_applicable"), a1kind="na", secular_risk=True)
    assert not g.portfolio_eligible


def test_gate_axis1_and_axis3_both_not_applicable_is_not_a_pass() -> None:
    """04 §2·§3.2 — 판별의 중심 질문에 답한 축이 없으면 편입 불가. 확신도와 무관하다."""
    g = _gate(_v("not_applicable", a3="not_applicable"), a1kind="na")
    assert g.status == "passed" and not g.portfolio_eligible
    assert g.path is None  # 사망의 증거가 아니라 판정의 부재 — 기각 조항이 아니다
    assert "적용 불가를 통과로 취급하지 않는다" in g.rule
    # 확신도가 편입 하한을 넘겨도(등호 포함) 게이트가 막는다
    g2 = _gate(_v("not_applicable", a3="not_applicable"), a1kind="na", confidence=0.5)
    assert not g2.portfolio_eligible
    g3 = _gate(_v("not_applicable", a3="not_applicable"), a1kind="na", confidence=0.9)
    assert not g3.portfolio_eligible


def test_gate_axis1_not_applicable_but_axis3_judges_keeps_old_behaviour() -> None:
    """축1 적용 불가 → 축 3 이 게이트를 쥔다. 축 3 이 판정을 내면 기존 동작 그대로."""
    ok = _gate(_v("not_applicable", a3="cycle"), a1kind="na")
    assert ok.status == "passed" and ok.portfolio_eligible
    assert any("축 3" in n for n in ok.notes)  # 그 사실을 리포트에 표시한다 (04 §2)
    assert any("미구현" in n for n in ok.notes)  # 정량적 이전은 아직 없다
    warn = _gate(_v("not_applicable", a3="warning"), a1kind="na", confidence=0.35)
    assert warn.status == "passed" and not warn.portfolio_eligible and "07 C6" in warn.rule
    dead = _gate(_v("not_applicable", a3="death"), a1kind="na")
    assert dead.status == "passed" and not dead.portfolio_eligible
    assert str(CONF_CAP_ON_DEATH) in dead.rule


def test_gate_rejection_clauses_unchanged_by_na_wiring() -> None:
    """기존 기각 조항은 그대로 작동한다 — 적용 불가 조항이 앞에서 가로채지 않는다."""
    assert _gate(_v("death", a3="warning"), a1kind="death").status == "rejected"
    assert _gate(_v("death", a3="death"), a1kind="death").status == "rejected"
    assert _gate(_v("contested"), a1kind="contested").status == "rejected"  # ruling 없음
    held = _gate(
        _v("contested"),
        a1kind="contested",
        referee_ruling="산업 축소이지 수요 소멸이 아니다",
        referee_evidence_refs=(1,),
    )
    assert held.status == "contested" and not held.portfolio_eligible
    # 적용 불가 + secular_risk 는 secular 조항이 아니라 §3.2 로 닫혀도 결과는 같다 (편입 불가)
    assert not _gate(_v("not_applicable"), a1kind="na", secular_risk=True).portfolio_eligible
    assert _gate(_v()).portfolio_eligible  # 5축 정상 판정은 그대로 통과


def test_confidence_arithmetic_unchanged_by_na_wiring() -> None:
    """04 §4 의 산술은 한 항도 바뀌지 않았다 — 적용 불가는 note 만 남긴다."""
    v = _v("not_applicable", "cycle", "not_applicable", "warning", "warning")
    r = cycle_confidence(_ci(v, capex_to_da_qtrs_below1=3.0, axis4_strong_cycle=False))
    assert r.terms == {} and r.value == 0.5 and r.cap is None
    assert any("축3 not_applicable" in n for n in r.notes)
    # 항이 붙는 판정에서는 note 가 생기지 않고 값도 그대로
    r2 = cycle_confidence(_ci(_v()))
    assert r2.value == 1.0 and not any("축3" in n for n in r2.notes)
    r3 = cycle_confidence(_ci(_v("not_applicable", a3="cycle")))
    assert r3.terms == {
        "axis2_capex_below1_8q": 0.10,
        "axis3_no_substitution": 0.15,
        "axis4_strong_cycle": 0.10,
    }
    assert r3.value == pytest.approx(0.85)


def test_rejection_row_format() -> None:
    g = _gate(_v("death", a3="warning"), a1kind="death")
    row = rejection_row(
        theme_id="coal",
        rejected_at="2026-08-14",
        gate=g,
        cycle_confidence=0.31,
        scoreboard_rank=3,
        scan_dir="state/scans/2026-08-14",
    )
    assert list(row) == [
        "theme",
        "rejected_at",
        "path",
        "reason",
        "cycle_confidence",
        "scoreboard_rank",
        "journal",
        "scan",
        "r_12m",
        "r_24m",
        "axis_verdicts",
    ]
    assert row["path"] == "hard_gate" and row["r_12m"] is None and row["journal"] is None
    assert row["axis_verdicts"]["unit_demand"] == "death"  # 대장 (a)(b) 집계용 스냅샷


def test_axis_verdict_enum_enforced() -> None:
    with pytest.raises(ValueError):
        AxisVerdicts("cycle", "cycle", "strong", "cycle", "cycle")


def test_every_not_applicable_axis_is_reported() -> None:
    """판정하지 못한 축을 전부 남긴다 (CLAUDE.md §2). 게이트 동작·확신도 항은 그대로."""
    v = AxisVerdicts(
        unit_demand="not_applicable",
        capital_cycle="not_applicable",
        substitution="cycle",
        cost_curve="not_applicable",
        terminal_risk="not_applicable",
    )
    conf = cycle_confidence(
        ConfidenceInputs(
            verdicts=v,
            capex_to_da_qtrs_below1=None,
            axis4_strong_cycle=False,
            axis5_severe=False,
            small_sample=False,
            short_hist=False,
        )
    )
    joined = " ".join(conf.notes)
    for label in ("축1", "축2", "축4", "축5"):
        assert label in joined, (label, conf.notes)
    # 산술은 손대지 않았다 — 축3 cycle 한 항만 붙는다
    assert conf.terms == {"axis3_no_substitution": 0.15} and conf.value == 0.65

    g = apply_gates(
        v,
        axis1("na"),
        confidence=conf.value,
        referee_ruling=None,
        referee_evidence_refs=(),
        referee_refs_valid=True,
        secular_risk=False,
        debt_24m_over_half=False,
    )
    note = " ".join(g.notes)
    assert "판정되지 않은 축 4/5" in note
    assert "unit_demand" in note and "terminal_risk" in note
    assert g.status == "passed" and g.portfolio_eligible is True  # 동작은 그대로
