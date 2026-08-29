"""증거 처리 대장 — append-only, `journal/` 과 같은 규약 (`CLAUDE.md` §6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from msa import triage
from msa.ops import resolutions as res


def _entry(**kw: object) -> res.Resolution:
    d: dict[str, object] = {
        "evidence_id": 17,
        "resolved_by": "human",
        "date": "2026-08-30",
        "verdict": "confirmed",
        "note": "Commonwealth Fund 원문 표 3 에 340억 확인.",
    }
    d.update(kw)
    return res.Resolution(**d)  # type: ignore[arg-type]


def test_append_then_load_roundtrip(tmp_path: Path) -> None:
    res.append(tmp_path, "managed_care", _entry())
    got = res.load(tmp_path, "managed_care")
    assert [e.evidence_id for e in got] == [17]
    assert got[0].verdict == "confirmed"


def test_load_missing_theme_is_empty(tmp_path: Path) -> None:
    assert res.load(tmp_path, "nope") == []


def test_append_is_append_only(tmp_path: Path) -> None:
    res.append(tmp_path, "managed_care", _entry())
    with pytest.raises(ValueError, match="이미 있다"):
        res.append(tmp_path, "managed_care", _entry(note="다시 쓴다"))


def test_append_keeps_earlier_entries(tmp_path: Path) -> None:
    res.append(tmp_path, "managed_care", _entry(evidence_id=1))
    res.append(tmp_path, "managed_care", _entry(evidence_id=10))
    assert [e.evidence_id for e in res.load(tmp_path, "managed_care")] == [1, 10]


def test_unknown_verdict_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="verdict"):
        res.append(tmp_path, "managed_care", _entry(verdict="probably_fine"))


def test_summary_counts_by_verdict() -> None:
    entries = [_entry(evidence_id=1), _entry(evidence_id=2, verdict="refuted")]
    assert res.summary(entries) == {"confirmed": 1, "refuted": 1, "unresolvable": 0}


def test_refuted_drives_theme_trust_below_cap() -> None:
    """`refuted` 가 하나라도 있으면 J 상한이 0.25 로 내려간다 (스펙 §7)."""
    judged = {"portfolio_eligible": True, "trusted": True, "gate": "passed"}
    audit = {"counts": {"verified": 23}, "checked": 23, "unverified_axes": []}
    clean = triage.theme_trust(judged, audit, resolutions=[])
    dirty = triage.theme_trust(judged, audit, resolutions=[_entry(verdict="refuted")])
    assert clean == pytest.approx(1.0)
    assert dirty == triage.EVIDENCE_CAP_REFUTED == 0.25


def test_confirmed_counts_as_verified() -> None:
    """사람이 확인한 것은 verified 로 계상한다 — 증거품질이 올라간다."""
    judged = {"portfolio_eligible": True, "trusted": True, "gate": "passed"}
    audit = {"counts": {"verified": 10}, "checked": 20, "unverified_axes": []}
    before = triage.theme_trust(judged, audit, resolutions=[])
    after = triage.theme_trust(
        judged, audit, resolutions=[_entry(evidence_id=1), _entry(evidence_id=2)]
    )
    assert before == pytest.approx(0.5 + 0.5 * 10 / 20)
    assert after == pytest.approx(0.5 + 0.5 * 12 / 20)


def test_confirmed_cannot_exceed_checked() -> None:
    """확인 건수가 실사 건수를 넘어도 증거품질이 1 을 넘지 않는다."""
    judged = {"portfolio_eligible": True, "trusted": True, "gate": "passed"}
    audit = {"counts": {"verified": 2}, "checked": 2, "unverified_axes": []}
    got = triage.theme_trust(
        judged, audit, resolutions=[_entry(evidence_id=i) for i in range(5)]
    )
    assert got == pytest.approx(1.0)


def test_unresolvable_neither_helps_nor_caps() -> None:
    """'열어봤지만 판단 못 하겠다' 는 증거품질을 올리지도 J 를 깎지도 않는다.

    사람이 시간을 썼다는 사실이 증거를 검증하지는 않는다.
    """
    judged = {"portfolio_eligible": True, "trusted": True, "gate": "passed"}
    audit = {"counts": {"verified": 10}, "checked": 20, "unverified_axes": []}
    base = triage.theme_trust(judged, audit, resolutions=[])
    got = triage.theme_trust(
        judged, audit, resolutions=[_entry(verdict="unresolvable")]
    )
    assert got == base


def test_paths_owns_the_ledger_directory() -> None:
    """계층 모듈이 `p.state / "..."` 를 각자 만들지 않는다 (`config.py` 머리말)."""
    from msa.config import paths

    assert paths().evidence_resolutions.name == "evidence_resolutions"
    assert paths().evidence_resolutions.parent == paths().state
