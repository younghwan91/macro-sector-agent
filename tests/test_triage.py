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


def test_partition_splits_eligible_by_pullback_mark() -> None:
    from msa.ops.readme_block import PULLBACK_MARK

    ok = _judged()
    assert triage.partition(ok, _pick(from_52w_high=PULLBACK_MARK)) == triage.PARTITION_IA
    assert triage.partition(ok, _pick(from_52w_high=-0.44)) == triage.PARTITION_IA
    assert triage.partition(ok, _pick(from_52w_high=-0.14)) == triage.PARTITION_IB


def test_partition_untrusted_theme_is_two_not_one() -> None:
    got = triage.partition(_judged(trusted=False), _pick(from_52w_high=-0.44))
    assert got == triage.PARTITION_II


def test_partition_unjudged_theme_is_three() -> None:
    assert triage.partition(None, _pick(from_52w_high=-0.90)) == triage.PARTITION_III


def test_partition_missing_drawdown_is_ib_not_ia() -> None:
    """낙폭을 모르면 '지금 자리' 라고 말하지 않는다 (`CLAUDE.md` §2)."""
    assert triage.partition(_judged(), _pick(from_52w_high=None)) == triage.PARTITION_IB


def test_readiness_drawdown_percentile_within_peers() -> None:
    peers = [0.182, 0.218, 0.448]
    deepest = triage.readiness(_pick(from_52w_high=-0.448), peers)
    middle = triage.readiness(_pick(from_52w_high=-0.218), peers)
    shallow = triage.readiness(_pick(from_52w_high=-0.182), peers)
    assert deepest == pytest.approx(0.7 * 1.0)
    assert middle == pytest.approx(0.7 * 0.5)
    assert shallow == pytest.approx(0.0)


def test_readiness_base_component_from_stage2_and_above_50d() -> None:
    peers = [0.30]
    both = triage.readiness(_pick(from_52w_high=-0.30, stage2=True, above_50d=True), peers)
    one = triage.readiness(_pick(from_52w_high=-0.30, stage2=True), peers)
    assert both == pytest.approx(0.7 * 1.0 + 0.3 * 1.0)
    assert one == pytest.approx(0.7 * 1.0 + 0.3 * 0.5)


def test_readiness_ignores_vcp_base() -> None:
    """`vcp_base` 는 폭락 중에도 True 를 낸다 — 결함이 문서화된 입력이다 (docs/backtest-l4 §14)."""
    peers = [0.30]
    with_vcp = triage.readiness(_pick(from_52w_high=-0.30, vcp_base=True), peers)
    without = triage.readiness(_pick(from_52w_high=-0.30, vcp_base=False), peers)
    assert with_vcp == without


def test_readiness_shallow_theme_does_not_outrank_deep_one() -> None:
    """2026-08-29 회귀 — 백분위를 테마 안에서 재면 -3.7% 인 ESEA 가 -44.8% 인 ALHC 를 이겼다.

    구획 안에서 재면 그 일이 안 일어난다 (스펙 §5.3).
    """
    peers = [0.037, 0.448]
    esea = triage.readiness(_pick(from_52w_high=-0.037), peers)
    alhc = triage.readiness(_pick(from_52w_high=-0.448), peers)
    assert alhc > esea


def test_readiness_single_member_partition_is_top() -> None:
    assert triage.readiness(_pick(from_52w_high=-0.30), [0.30]) == pytest.approx(0.7)


def test_note_distinguishes_audit_not_run_from_theme_missing() -> None:
    """'실사가 안 돌았다' 와 '이 테마의 실사가 없다' 는 다른 사실이다.

    둘 다 J 계산 불가지만 사람이 할 일이 다르다 — 앞은 실행 방식, 뒤는 그 테마의 문제다.
    """
    themes = [{"theme": "t1", "picks": [_pick()]}]
    judged = [_judged(theme="t1")]

    not_run = triage.score_digest({"themes": themes, "judged": judged})
    assert not_run[0].triage is None
    assert "실사 단계가 돌지 않았다" in not_run[0].note

    ran_but_empty = triage.score_digest(
        {"themes": themes, "judged": judged, "evidence_audit": {}}
    )
    assert ran_but_empty[0].triage is None
    assert "`t1` 의 증거 실사 결과가 없다" in ran_but_empty[0].note
