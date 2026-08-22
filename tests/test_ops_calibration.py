"""캘리브레이션 — o 규칙 · N<20 결론 없음 · N≥20 기울기."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from msa.ops.calibration import (
    MIN_N,
    BinStat,
    calibrate,
    outcome,
    run,
    samples_from_journal,
    weighted_slope,
)
from msa.ops.journal import ExitRecord, write_record


def test_outcome_rules_are_the_documented_ones() -> None:
    # 과반 충족 AND 무효화 0 → 1
    assert (
        outcome(triggers_met=2, triggers_total=3, invalidations_fired=0, exit_via="tp_complete")
        == 1.0
    )
    # 무효화 발동 → 0 (트리거 과반이어도)
    assert outcome(triggers_met=3, triggers_total=3, invalidations_fired=1, exit_via="tier1") == 0.0
    # 시간 스탑 + 트리거 0 → 0
    assert (
        outcome(triggers_met=0, triggers_total=3, invalidations_fired=0, exit_via="time_stop")
        == 0.0
    )
    # 일부 충족, 미결 → 0.5
    assert outcome(triggers_met=1, triggers_total=3, invalidations_fired=0, exit_via="tier2") == 0.5


def _exit(i: int, c: float, o: float, prov: str = "human") -> ExitRecord:
    if o == 1.0:
        tm, inv, via = 3, 0, "tp_complete"
    elif o == 0.0:
        tm, inv, via = 0, 1, "tier1"
    else:
        tm, inv, via = 1, 0, "tier2"
    return ExitRecord(
        date=date(2027, 1, 1) + __import__("datetime").timedelta(days=i),
        theme=f"theme_{i}",
        exit_via=via,
        realized_return=0.0,
        holding_days=300,
        triggers_met=tm,
        triggers_total=3,
        invalidations_fired=inv,
        mechanism_assessment="서술",
        confidence_assessment="서술",
        cycle_confidence=c,
        confidence_provenance=prov,
        entry_journal="journal/x.md",
        thesis_snapshot="journal/x.thesis.yaml",
    )


def test_small_sample_prints_no_conclusion_but_lists_samples(tmp_path: Path) -> None:
    for i, (c, o) in enumerate([(0.72, 1.0), (0.55, 0.0), (0.81, 1.0), (0.65, 0.5)]):
        write_record(_exit(i, c, o), tmp_path)
    text, cals = run(tmp_path)
    assert f"결론 없음 (N=3 < {MIN_N})" in text
    assert "theme_0" in text and "theme_3" in text  # 미결 표본도 나열
    assert cals[0].n == 3 and cals[0].n_unresolved == 1 and not cals[0].conclusive
    assert cals[0].slope is None and "λ 실측 근거" not in text
    assert "조건부 캘리브레이션" in text
    assert cals[1].label.endswith("human") and cals[1].n == 3
    assert cals[2].label.endswith("referee") and cals[2].n == 0


def test_twenty_plus_samples_across_bins_yield_weighted_slope(tmp_path: Path) -> None:
    # 구간별로 c 가 높을수록 적중률이 높게 — 완벽 캘리브레이션에 가까운 합성 표본 24개
    plan = (
        [(0.55, 1.0)] * 3
        + [(0.55, 0.0)] * 3  # 0.5 적중
        + [(0.65, 1.0)] * 4
        + [(0.65, 0.0)] * 2  # 0.67
        + [(0.75, 1.0)] * 5
        + [(0.75, 0.0)] * 1  # 0.83
        + [(0.85, 1.0)] * 6  # 1.0
    )
    for i, (c, o) in enumerate(plan):
        write_record(_exit(i, c, o, prov="referee" if i % 2 else "human"), tmp_path)
    text, cals = run(tmp_path)
    tot = cals[0]
    assert tot.n == 24 and tot.conclusive and tot.slope is not None and tot.lambda_hint is not None
    assert tot.slope > 1.0 and tot.lambda_hint == 0.0  # 적중률이 c 보다 가파르게 오른다 → λ → 0
    assert "가중 최소자승 기울기" in text and "λ 실측 근거" in text
    bins = {b.lo: b for b in tot.bins}
    assert bins[0.5].n == 6 and bins[0.5].hit_rate == pytest.approx(0.5)
    assert bins[0.8].hit_rate == pytest.approx(1.0)
    # 주체별 분할은 각 12개 → 결론 없음
    assert not cals[1].conclusive and not cals[2].conclusive


def test_concentrated_bins_do_not_conclude(tmp_path: Path) -> None:
    for i in range(22):
        write_record(_exit(i, 0.72, 1.0 if i % 2 else 0.0), tmp_path)
    _, cals = run(tmp_path)
    assert cals[0].n == 22 and not cals[0].conclusive and "몰려" in cals[0].reason


def test_weighted_slope_math() -> None:
    bins = [
        BinStat(0.5, 0.6, 10, 0.5, 0.55),
        BinStat(0.6, 0.7, 10, 0.6, 0.65),
        BinStat(0.7, 0.8, 10, 0.7, 0.75),
        BinStat(0.8, 1.0, 10, 0.85, 0.85),
    ]
    s = weighted_slope(bins)
    assert s is not None and s == pytest.approx(1.0, abs=0.05)
    assert weighted_slope(bins[:1]) is None
    assert calibrate([]).reason.startswith("결론 없음")
    assert samples_from_journal(Path("/nonexistent")) == []
