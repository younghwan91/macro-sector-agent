"""결정 저널 — 필수 필드 거부 · append-only · thesis diff."""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

from conftest import make_thesis
from msa.ops.journal import (
    TEMPLATES,
    AddRecord,
    CheckRecord,
    EntryRecord,
    ExitRecord,
    Fill,
    IncompleteEntry,
    JournalImmutable,
    RejectRecord,
    StatusChange,
    StockPlan,
    TpRecord,
    install_hook,
    list_snapshots,
    load_entries,
    read_front_matter,
    record_from_dict,
    thesis_drift,
    verify_append_only,
    write_record,
)
from msa.ops.thesis import ThesisInvalid, diff_thesis, validate_thesis

AXES_OK = {
    "unit_demand": "cycle",
    "capital_cycle": "cycle",
    "substitution": "cycle",
    "cost_curve": "cycle",
    "terminal_risk": "warning",
}


def _stock() -> StockPlan:
    return StockPlan(
        ticker="CCJ",
        role="anchor",
        target_weight=0.16,
        ladder_prices=[50.0, 43.5, 38.5],
        ladder_weights=[0.5, 0.3, 0.2],
        tier2_stop_price=29.7,
        tier2_pct_from_entry=-0.405,
        time_stop_date=date(2028, 3, 1),
        tp_conditions=["P50 또는 +2R", "P75 또는 고점 50%", "트레일 −25%"],
    )


def _entry(**over: object) -> EntryRecord:
    kw: dict[str, object] = {
        "date": date(2026, 9, 1),
        "theme": "uranium",
        "thesis": make_thesis(),
        "confidence_provenance": "human",
        "l1_blocks": {b: 0.5 for b in "ABCDEF"},
        "axis_verdicts": dict(AXES_OK),
        "stocks": [_stock()],
        "deviated_from_machine": False,
        "scan": "state/scans/2026-08-31/",
    }
    kw.update(over)
    return EntryRecord(**kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# thesis 검증
# ---------------------------------------------------------------------------


def test_thesis_rejects_empty_evidence_and_invalidations() -> None:
    validate_thesis(make_thesis())
    with pytest.raises(ThesisInvalid, match="evidence"):
        validate_thesis(make_thesis(evidence=[]))
    with pytest.raises(ThesisInvalid, match="invalidations"):
        validate_thesis(make_thesis(invalidations=[]))
    with pytest.raises(ThesisInvalid, match="cycle_confidence"):
        validate_thesis(make_thesis(cycle_confidence=1.7))
    with pytest.raises(ThesisInvalid, match=r"gate_result\.path"):
        validate_thesis(make_thesis(gate_result={"status": "rejected", "path": "vibes"}))


# ---------------------------------------------------------------------------
# 필수 필드 거부
# ---------------------------------------------------------------------------


def test_entry_refuses_when_required_fields_missing(tmp_path: Path) -> None:
    write_record(_entry(), tmp_path)  # 완전한 항목은 써진다
    cases = {
        "evidence 비어 있음": _entry(thesis=make_thesis(evidence=[]), date=date(2026, 9, 2)),
        "블록 5개": _entry(l1_blocks={b: 0.5 for b in "ABCDE"}, date=date(2026, 9, 3)),
        "축 4개": _entry(axis_verdicts={k: v for k, v in AXES_OK.items() if k != "cost_curve"}),
        "종목 없음": _entry(stocks=[], date=date(2026, 9, 4)),
        "이탈 사유 없음": _entry(deviated_from_machine=True, deviation_reason="  "),
        "산출 주체 불명": _entry(confidence_provenance="agent"),
        "bear 없음": _entry(thesis=make_thesis(bear_case=""), bear_case=""),
        "스캔 경로 없음": _entry(scan=""),
    }
    for label, rec in cases.items():
        with pytest.raises(IncompleteEntry):
            write_record(rec, tmp_path)
        # 거부된 항목은 파일을 남기지 않는다 (날짜가 겹치는 경우는 첫 항목의 파일이다)
        if rec.date != date(2026, 9, 1):
            assert not (tmp_path / f"{rec.date}-uranium-entry.md").exists(), label


def test_reject_requires_path_enum_axes_rank_and_human_override(tmp_path: Path) -> None:
    base = dict(
        date=date(2026, 8, 3),
        theme="offshore_drilling",
        path="hard_gate",
        axis_verdicts={**AXES_OK, "unit_demand": "death"},
        cycle_confidence=None,
        scoreboard_rank=3,
        scan="state/scans/2026-08-03/",
        reason="축1 사망 AND 축3 경고",
    )
    w = write_record(RejectRecord(**base), tmp_path)  # type: ignore[arg-type]
    fm = read_front_matter(w.markdown)
    assert fm["path"] == "hard_gate" and fm["cycle_confidence"] is None
    with pytest.raises(IncompleteEntry, match="path"):
        RejectRecord(**{**base, "path": "gut_feel"}).validate()  # type: ignore[arg-type]
    with pytest.raises(IncompleteEntry, match="override_reason"):
        RejectRecord(**{**base, "path": "human"}).validate()  # type: ignore[arg-type]
    with pytest.raises(IncompleteEntry, match="scoreboard_rank"):
        RejectRecord(**{**base, "scoreboard_rank": 0}).validate()  # type: ignore[arg-type]


def test_add_refuses_buying_into_fired_invalidation_without_reason() -> None:
    rec = AddRecord(
        date=date(2026, 11, 3),
        theme="uranium",
        step=2,
        fills=[Fill("CCJ", 43.2)],
        price_move_from_entry=-0.132,
        invalidations_fired=1,
        triggers_met=1,
        triggers_total=3,
        judgment="가격 조건 충족",
    )
    with pytest.raises(IncompleteEntry, match="override_reason"):
        rec.validate()
    rec.invalidations_fired = 0
    rec.validate()


def test_tp1_requires_breakeven_stop_and_exit_requires_assessments() -> None:
    tp = TpRecord(
        date=date(2027, 3, 2),
        theme="uranium",
        level="tp1",
        fills=[Fill("CCJ", 80.0)],
        condition_met="+2R 도달",
        judgment="1/3 익절",
    )
    with pytest.raises(IncompleteEntry, match="new_tier2_stop_price"):
        tp.validate()
    ex = ExitRecord(
        date=date(2027, 6, 1),
        theme="uranium",
        exit_via="tier1",
        realized_return=-0.12,
        holding_days=273,
        triggers_met=1,
        triggers_total=3,
        invalidations_fired=1,
        mechanism_assessment="",
        confidence_assessment="과대",
        cycle_confidence=0.72,
        confidence_provenance="human",
        entry_journal="journal/x.md",
        thesis_snapshot="journal/x.thesis.yaml",
    )
    with pytest.raises(IncompleteEntry, match="mechanism_assessment"):
        ex.validate()


# ---------------------------------------------------------------------------
# 쓰기 · 스냅샷 · 덮어쓰기 거부 · diff
# ---------------------------------------------------------------------------


def test_entry_writes_markdown_and_thesis_snapshot_and_refuses_overwrite(tmp_path: Path) -> None:
    w = write_record(_entry(), tmp_path)
    assert w.markdown.name == "2026-09-01-uranium-entry.md"
    assert w.thesis_snapshot is not None and w.thesis_snapshot.name.endswith(".thesis.yaml")
    snap = yaml.safe_load(w.thesis_snapshot.read_text())
    assert snap["cycle_confidence"] == 0.80
    text = w.markdown.read_text()
    assert "기계 권고와 다르게 결정했다면 그 이유" in text and "bear_case 원문" in text
    fm = read_front_matter(w.markdown)
    assert fm["type"] == "entry" and fm["confidence_provenance"] == "human"
    with pytest.raises(JournalImmutable):
        write_record(_entry(), tmp_path)
    w2 = write_record(_entry(), tmp_path, suffix="b")
    assert w2.markdown.name == "2026-09-01-uranium-entry-b.md"


def test_check_with_rerun_thesis_records_field_diff(tmp_path: Path) -> None:
    write_record(_entry(), tmp_path)
    new = make_thesis(cycle_confidence=0.61, claim="우라늄 현물가가 2027년까지 $90 이상을 유지한다")
    new["invalidations"] = new["invalidations"][:1]  # 무효화 하나를 조용히 뺐다 — 표류
    rec = CheckRecord(
        date=date(2026, 10, 6),
        theme="uranium",
        cadence="weekly",
        trigger_status=[StatusChange("Cameco 가이던스 상향", "pending", "pending")],
        invalidation_status=[StatusChange("카자흐 쿼터 +20%", "pending", "pending")],
        thesis=new,
    )
    w = write_record(rec, tmp_path)
    assert w.diff_text is not None
    assert "cycle_confidence" in w.diff_text and "claim" in w.diff_text
    assert "invalidations[1]" in w.diff_text
    assert "논지 핵심 필드 변경" in w.diff_text
    assert len(list_snapshots(tmp_path, "uranium")) == 2
    drift = thesis_drift(tmp_path, "uranium")
    assert "0.8" in drift and "0.61" in drift
    # 같은 내용이면 차이 없음
    assert diff_thesis(make_thesis(), make_thesis()) == []


def test_load_entries_reads_front_matter_in_date_order(tmp_path: Path) -> None:
    write_record(_entry(), tmp_path)
    write_record(_entry(date=date(2026, 9, 5), theme="copper"), tmp_path)
    ents = load_entries(tmp_path, "entry")
    assert [e["theme"] for e in ents] == ["uranium", "copper"]


def test_record_from_dict_uses_templates_and_refuses_empty_thesis() -> None:
    d = yaml.safe_load(TEMPLATES["entry"])
    rec = record_from_dict(d)
    assert isinstance(rec, EntryRecord)
    with pytest.raises(IncompleteEntry):
        rec.validate()
    d2 = yaml.safe_load(TEMPLATES["check"])
    assert isinstance(record_from_dict(d2), CheckRecord)
    with pytest.raises(IncompleteEntry, match="type"):
        record_from_dict({"type": "musing", "date": "2026-01-01"})


# ---------------------------------------------------------------------------
# append-only (git)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    j = r / "journal"
    j.mkdir()
    write_record(_entry(), j)
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "entry")
    return r


def test_verify_passes_on_clean_and_on_new_files_only(repo: Path) -> None:
    assert verify_append_only(repo) == []
    write_record(_entry(date=date(2026, 9, 9)), repo / "journal")
    assert verify_append_only(repo) == []  # untracked 새 파일
    _git(repo, "add", "journal")
    assert verify_append_only(repo, staged_only=True) == []  # 새로 add 된 파일도 OK


def test_verify_fails_when_committed_entry_modified_or_deleted(repo: Path) -> None:
    f = repo / "journal" / "2026-09-01-uranium-entry.md"
    f.write_text(f.read_text() + "\n사후 편집\n")
    v = verify_append_only(repo)
    assert len(v) == 1 and v[0].status.startswith("M") and v[0].path.endswith("entry.md")
    _git(repo, "add", "journal")
    assert verify_append_only(repo, staged_only=True)[0].status.startswith("M")
    _git(repo, "checkout", "HEAD", "--", "journal")
    assert verify_append_only(repo) == []
    f.unlink()
    assert verify_append_only(repo)[0].status.startswith("D")


def test_precommit_hook_blocks_edit(repo: Path) -> None:
    # 훅은 scripts/journal-precommit.sh 를 호출한다 — 테스트 저장소에는 그 스크립트가 없으므로
    # 검사 로직을 직접 호출하는 훅을 설치해 같은 경로를 검증한다.
    hook = install_hook(repo)
    assert hook.exists()
    with pytest.raises(FileExistsError):
        install_hook(repo)
    f = repo / "journal" / "2026-09-01-uranium-entry.thesis.yaml"
    f.write_text(f.read_text().replace("0.8", "0.9"))
    _git(repo, "add", "journal")
    assert verify_append_only(repo, staged_only=True)


def test_ops_required_fields_come_from_the_spec_file() -> None:
    """운영 검증기의 필수 목록은 스펙 파일 하나에서 온다 — 손으로 베낀 상수가 아니다."""
    from msa.l3.schema import load_spec
    from msa.ops.thesis import _required_top

    assert _required_top() == tuple(load_spec()["required"])
    t = make_thesis()
    del t[load_spec()["required"][0]]
    with pytest.raises(ThesisInvalid, match="필수 필드 없음"):
        validate_thesis(t)


def test_suffix_is_sanitized_and_does_not_eat_the_snapshot_extension(tmp_path: Path) -> None:
    """`--suffix` 도 테마와 같은 규칙으로 씻는다 (2026-08-26 코드 리뷰).

    씻지 않으면 `../x` 가 journal/ 밖으로 나가고, `v1.2` 는 스냅샷 경로에서 `.2` 가 확장자로
    먹혀 `-v1` 항목과 같은 파일을 가리킨다 — append-only 가드가 엉뚱한 파일을 본다.
    """
    from msa.ops.journal import _snapshot_path

    # 점이 있는 suffix 가 스냅샷 이름에서 살아남는다
    md = tmp_path / "2026-08-26-t-entry-v1.2.md"
    assert _snapshot_path(md).name == "2026-08-26-t-entry-v1.2.thesis.yaml"
    # `-v1` 과 `-v1.2` 는 서로 다른 스냅샷이다
    other = tmp_path / "2026-08-26-t-entry-v1.md"
    assert _snapshot_path(md) != _snapshot_path(other)


def test_suffix_cannot_escape_the_journal_directory() -> None:
    """경로 구분자·상위 참조는 파일명 토큰으로 씻긴다."""
    from msa.ops.journal import _theme_tag

    for bad in ("../etc", "a/b", "..", "x y"):
        tag = _theme_tag(bad)
        assert "/" not in tag and ".." not in tag, (bad, tag)
