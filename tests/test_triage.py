"""트리아지 점수 — 합성 dict, 스토어 없음.

`docs/superpowers/specs/2026-08-29-hedge-fund-evolution-design.md` §4~§6.
"""

from __future__ import annotations

import pytest

from msa import triage


def _judged(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "theme": "t",
        "portfolio_eligible": True,
        "trusted": True,
        "gate": "passed",
        "cycle_confidence": 0.75,
    }
    d.update(kw)
    return d


def _audit(verified: int = 11, checked: int = 23, **kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "counts": {"verified": verified},
        "checked": checked,
        "unverified_axes": [],
    }
    d.update(kw)
    return d


def test_weights_are_declared_and_sum_to_one() -> None:
    assert triage.TRIAGE_WEIGHTS == {"J": 0.50, "C": 0.30, "R": 0.20}
    assert abs(sum(triage.TRIAGE_WEIGHTS.values()) - 1.0) < 1e-9


def test_judgment_state_precedence_untrusted_beats_eligible() -> None:
    """`trusted: false` 가 먼저다 — 편입 가능이어도 0.30 (스펙 §5.1.1 표의 1번 줄)."""
    assert triage.judgment_state(_judged(portfolio_eligible=True, trusted=False)) == 0.30


def test_judgment_state_ladder() -> None:
    assert triage.judgment_state(_judged(portfolio_eligible=True)) == 1.00
    assert triage.judgment_state(_judged(portfolio_eligible=False)) == 0.50
    assert triage.judgment_state(_judged(portfolio_eligible=False, gate="blocked")) == 0.30


def test_evidence_quality_counts_unreachable_in_denominator() -> None:
    """'못 읽었다' 는 '맞다' 가 아니다 — 분모에 남는다."""
    assert triage.evidence_quality(_audit(verified=11, checked=23)) == pytest.approx(11 / 23)


def test_theme_trust_is_half_state_half_evidence() -> None:
    assert triage.theme_trust(_judged(), _audit(11, 23)) == pytest.approx(0.5 + 0.5 * 11 / 23)


def test_theme_trust_capped_when_unverified_axes_present() -> None:
    """판정을 만든 축의 증거가 검증 안 됐으면 그 판정을 절반만 믿는다 (스펙 §5.1.3)."""
    got = triage.theme_trust(_judged(), _audit(22, 23, unverified_axes=["unit_demand"]))
    assert got == triage.EVIDENCE_CAP == 0.50


def test_theme_trust_zero_when_no_thesis() -> None:
    assert triage.theme_trust(None, None) == 0.0


def test_theme_trust_none_when_judged_but_no_audit() -> None:
    """결측을 0.5 로 채우지 않는다 — 계산 불가는 None (`CLAUDE.md` §2)."""
    assert triage.theme_trust(_judged(), None) is None


def test_theme_trust_rejects_zero_checked() -> None:
    with pytest.raises(ZeroDivisionError):
        triage.evidence_quality(_audit(0, 0))


def _pick(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "ticker": "AAA",
        "survival_unjudged": None,
        "red_flags": "",
        "s_partial": False,
        "composite_partial": False,
        "from_52w_high": -0.30,
        "stage2": False,
        "above_50d": False,
    }
    d.update(kw)
    return d


def test_clarity_clean_pick_is_one() -> None:
    assert triage.clarity(_pick()) == 1.0


def test_clarity_unjudged_survival_costs_half() -> None:
    """하드필터를 '통과한 것' 과 '판정 불가라 통과 취급된 것' 은 다르다."""
    assert triage.clarity(_pick(survival_unjudged="재무 없음")) == pytest.approx(0.50)


def test_clarity_red_flags_capped_at_two() -> None:
    one = triage.clarity(_pick(red_flags="consecutive_operating_loss"))
    two = triage.clarity(_pick(red_flags="a,b"))
    three = triage.clarity(_pick(red_flags="a,b,c"))
    assert one == pytest.approx(0.85)
    assert two == pytest.approx(0.70)
    assert three == pytest.approx(0.70), "3건이 2건보다 두 배 나쁘다고 말할 근거가 없다"


def test_clarity_partial_inputs_small_penalty() -> None:
    assert triage.clarity(_pick(s_partial=True)) == pytest.approx(0.90)
    assert triage.clarity(_pick(composite_partial=True)) == pytest.approx(0.90)
    assert triage.clarity(_pick(s_partial=True, composite_partial=True)) == pytest.approx(
        0.90
    ), "둘 다 참이어도 한 번만 깎는다 — 같은 사실의 두 표시다"


def test_clarity_worst_case_floor_is_point_one() -> None:
    """감점 전부를 맞아도 0.10 이다 — 0 으로 클립되는 경로는 도달 불가다.

    0.50(미판정) + 0.30(레드플래그 2건) + 0.10(결측) = 0.90 이 감점의 최대다.
    `clarity` 의 `max(..., 0.0)` 은 **앞으로 감점이 늘어날 때를 위한 방어**이지 지금
    돌아가는 가지가 아니다. 그 사실을 테스트가 박아 둔다.
    """
    got = triage.clarity(_pick(survival_unjudged="x", red_flags="a,b,c", s_partial=True))
    assert got == pytest.approx(0.10)


def test_clarity_ignores_return_predictive_axes() -> None:
    """S 축은 rank-IC 가 양수로 측정된 축이다 — 넣으면 수익률 주장이 된다 (스펙 §5.2)."""
    low = triage.clarity(_pick(s_pct=0.01, composite=0.01))
    high = triage.clarity(_pick(s_pct=0.99, composite=0.99))
    assert low == high == 1.0
