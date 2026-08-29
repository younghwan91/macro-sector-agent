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
