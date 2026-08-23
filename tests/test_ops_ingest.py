"""L3 라운드 → 운영 파일 적재 (`msa.ops.ingest`) — 게이트 상태별 산출물 · 멱등 · append-only."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from _l3_synth import ASOF, write_scan_dir
from conftest import make_thesis
from msa.cli import app
from msa.ops.ingest import DRAFT_PREFIX, IngestReport, ingest_round
from msa.ops.journal import (
    EntryRecord,
    IncompleteEntry,
    load_entries,
    read_front_matter,
    record_from_dict,
    verify_append_only,
    write_record,
)
from msa.ops.state_files import (
    ImmutableRowChanged,
    load_rejections,
    load_watchlist,
    save_rejections,
)
from msa.thesis import dump_thesis_yaml, thesis_filename

ASOF_D = date.fromisoformat(ASOF)
SCAN_LABEL = f"state/scans/{ASOF}"

# ---------------------------------------------------------------------------
# 합성 thesis — 게이트 상태별
# ---------------------------------------------------------------------------


def _verdicts(**over: str) -> dict[str, str]:
    v = {
        "unit_demand": "cycle",
        "capital_cycle": "cycle",
        "substitution": "cycle",
        "cost_curve": "cycle",
        "terminal_risk": "warning",
    }
    v.update(over)
    return v


def _axes(verdicts: dict[str, str], *, axis1_available: bool = True) -> dict[str, Any]:
    axes: dict[str, Any] = {a: {"verdict": v, "evidence_refs": [1]} for a, v in verdicts.items()}
    axes["unit_demand"].update(
        {"axis1_available": axis1_available, "unit_series_source": "physical_series"}
    )
    return axes


def _thesis(theme: str, *, gate: dict[str, Any], verdicts: dict[str, str], **over: Any) -> dict:
    axis1_available = bool(over.pop("axis1_available", True))
    g = {"axis_verdicts": verdicts, **gate}
    return make_thesis(
        theme_id=theme,
        generated_at=ASOF,
        value_trap_axes=_axes(verdicts, axis1_available=axis1_available),
        gate_result=g,
        inputs={"scan_dir": SCAN_LABEL, "scoreboard_rank": 7, "macro_tailwind": 0.42},
        **over,
    )


def rejected_thesis(theme: str = "offshore_drilling") -> dict[str, Any]:
    v = _verdicts(unit_demand="death", substitution="warning")
    return _thesis(
        theme,
        gate={
            "status": "rejected",
            "portfolio_eligible": False,
            "path": "hard_gate",
            "rule": "축1 사망 AND 축3 ∈ {경고, 사망} → 자동 기각 (04 §3). L1 스코어 무관",
            "reason": "축1 death (unit_cagr_10y=-0.041) · 축3 warning",
        },
        verdicts=v,
        cycle_confidence=0.31,
    )


def contested_thesis(theme: str = "coal") -> dict[str, Any]:
    v = _verdicts(unit_demand="contested")
    return _thesis(
        theme,
        gate={
            "status": "contested",
            "portfolio_eligible": False,
            "rule": "axis1_contested → 보류 (04 §3.1)",
            "reason": "verdict_pre_ss=death · verdict_post_ss=warning · sign_split=False",
            "referee_ruling": "해상 물량은 감소, 야금탄은 유지 — 두 시계열 분리 관측 필요",
            "referee_evidence_refs": [1],
        },
        verdicts=v,
        key_uncertainties=["야금탄/발전탄 물량 분리 불가"],
    )


def capped_thesis(theme: str = "newspapers") -> dict[str, Any]:
    v = _verdicts(unit_demand="death")
    return _thesis(
        theme,
        gate={
            "status": "passed",
            "portfolio_eligible": False,
            "rule": "축1 사망 OR 축3 사망 → cycle_confidence 상한 0.35 · 포트 편입 불가",
            "reason": "축1 death · 축3 cycle · cycle_confidence=0.35",
        },
        verdicts=v,
        cycle_confidence=0.35,
    )


def axis1_na_thesis(theme: str = "shipping") -> dict[str, Any]:
    v = _verdicts(unit_demand="not_applicable")
    return _thesis(
        theme,
        gate={
            "status": "passed",
            "portfolio_eligible": False,
            "rule": "04 §3 의 어느 기각 조항에도 걸리지 않음 — 단 c 0.45 < 0.5 (07 C6)",
            "reason": "축1 not_applicable · 축3 cycle · cycle_confidence=0.45",
        },
        verdicts=v,
        axis1_available=False,
        cycle_confidence=0.45,
    )


def eligible_thesis(theme: str = "uranium") -> dict[str, Any]:
    return _thesis(
        theme,
        gate={
            "status": "passed",
            "portfolio_eligible": True,
            "rule": "04 §3 의 어느 기각 조항에도 걸리지 않음",
            "reason": "축1 cycle · 축3 cycle · cycle_confidence=0.72",
        },
        verdicts=_verdicts(),
    )


# ---------------------------------------------------------------------------
# 픽스처 — state/ 루트 · 라운드 디렉터리 · 스캔
# ---------------------------------------------------------------------------


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    st = tmp_path / "state"
    st.mkdir()
    monkeypatch.setenv("MSA_STATE", str(st))
    return st


def _round(state: Path, *theses: dict[str, Any]) -> Path:
    d = state / "theses" / ASOF
    for t in theses:
        dump_thesis_yaml(d / thesis_filename(t["theme_id"]), t)
    return d


def _scan(state: Path, themes: tuple[str, ...]) -> Path:
    return write_scan_dir(state, ASOF, themes)


def _run(
    state: Path, rdir: Path, *, scan: Path | None, write: bool = True, **kw: Any
) -> IngestReport:
    return ingest_round(
        rdir,
        asof=ASOF_D,
        scan_dir=scan,
        journal_dir=state.parent / "journal",
        rejections_path=state / "rejections.yaml",
        watchlist_path=state / "watchlist.yaml",
        macro_latest=kw.pop("macro_latest", None),
        write=write,
        **kw,
    )


# ---------------------------------------------------------------------------
# rejected → 저널 기각 항목 + 스냅샷 + 대장 행, 멱등
# ---------------------------------------------------------------------------


def test_rejected_writes_journal_snapshot_and_ledger(state: Path) -> None:
    t = rejected_thesis()
    rdir = _round(state, t)
    scan = _scan(state, ("uranium", "offshore_drilling"))
    rep = _run(state, rdir, scan=scan)

    assert rep.n_rejected_ingested == 1 and rep.n_rejected_blocked == 0
    jdir = state.parent / "journal"
    md = jdir / f"{ASOF}-offshore_drilling-reject.md"
    snap = jdir / f"{ASOF}-offshore_drilling-reject.thesis.yaml"
    assert md.exists() and snap.exists()
    fm = read_front_matter(md)
    assert fm["type"] == "reject"
    assert fm["path"] == "hard_gate"
    assert fm["cycle_confidence"] == 0.31
    assert fm["scoreboard_rank"] == 2  # scoreboard.csv 의 순위 (thesis 의 7 이 아니다)
    assert fm["scan"] == SCAN_LABEL
    assert fm["axis_verdicts"]["unit_demand"] == "death"
    assert fm["override_reason"] == ""  # 기계가 기각 — 사람의 편입 거부 사유가 아니다
    assert fm["thesis_snapshot"] == snap.name
    body = md.read_text(encoding="utf-8")
    assert "자동 기각 (04 §3)" in body and "| unit_demand | death |" in body
    assert yaml.safe_load(snap.read_text(encoding="utf-8"))["theme_id"] == "offshore_drilling"

    rows = load_rejections(state / "rejections.yaml")
    assert len(rows) == 1
    r = rows[0]
    assert r.key == ("offshore_drilling", ASOF)
    assert r.path == "hard_gate" and r.scoreboard_rank == 2 and r.cycle_confidence == 0.31
    assert r.journal.endswith(md.name) and r.scan == SCAN_LABEL
    assert r.axis_verdicts == t["gate_result"]["axis_verdicts"]
    assert r.r_12m is None and r.r_24m is None
    assert "offshore_drilling" not in rep.missing_rank
    assert "reject_ingested" in rep.render()


def test_rejected_rerun_is_idempotent(state: Path) -> None:
    rdir = _round(state, rejected_thesis())
    scan = _scan(state, ("uranium", "offshore_drilling"))
    _run(state, rdir, scan=scan)
    jdir = state.parent / "journal"
    before = {p.name: p.read_text(encoding="utf-8") for p in jdir.iterdir()}
    ledger_before = (state / "rejections.yaml").read_text(encoding="utf-8")

    rep2 = _run(state, rdir, scan=scan)
    assert rep2.n_rejected_ingested == 0 and rep2.n_rejected_skipped == 1
    assert {p.name: p.read_text(encoding="utf-8") for p in jdir.iterdir()} == before
    assert (state / "rejections.yaml").read_text(encoding="utf-8") == ledger_before
    assert len(load_rejections(state / "rejections.yaml")) == 1


def test_rejected_without_any_rank_is_blocked_and_reported(state: Path) -> None:
    t = rejected_thesis()
    t["inputs"] = {"scan_dir": SCAN_LABEL}  # 순위 없음 · 스코어보드도 없음
    rdir = _round(state, t)
    rep = _run(state, rdir, scan=None)
    assert rep.n_rejected_blocked == 1 and rep.n_rejected_ingested == 0
    assert rep.missing_rank == ["offshore_drilling"]
    assert not (state / "rejections.yaml").exists()
    assert not (state.parent / "journal").exists()
    assert "scoreboard_rank 없음" in rep.render()


def test_rejected_falls_back_to_thesis_rank_but_reports_missing_scoreboard(state: Path) -> None:
    rdir = _round(state, rejected_thesis())
    rep = _run(state, rdir, scan=None)  # --scan 없음, state/scans/<date>/ 도 없음
    assert rep.n_rejected_ingested == 1
    assert rep.missing_rank == ["offshore_drilling"]
    assert load_rejections(state / "rejections.yaml")[0].scoreboard_rank == 7
    assert "thesis.inputs.scoreboard_rank" in rep.render()


def test_existing_ledger_rows_untouched_and_immutability_enforced(state: Path) -> None:
    rdir = _round(state, rejected_thesis())
    scan = _scan(state, ("uranium", "offshore_drilling"))
    # 이전 라운드의 행이 이미 있다
    from msa.ops.state_files import Rejection

    old = Rejection(
        theme="coal",
        rejected_at=date(2026, 7, 1),
        path="conf_floor",
        reason="c=0.2",
        cycle_confidence=0.2,
        scoreboard_rank=9,
        journal="journal/2026-07-01-coal-reject.md",
        scan="state/scans/2026-07-01",
        r_12m=0.05,
    )
    save_rejections(state / "rejections.yaml", [old])
    _run(state, rdir, scan=scan)
    rows = load_rejections(state / "rejections.yaml")
    assert [r.key for r in rows] == [("coal", "2026-07-01"), ("offshore_drilling", ASOF)]
    assert rows[0] == old
    # 기각 시점 필드를 고쳐 저장하려 하면 거부된다
    tampered = [Rejection(**{**rows[0].__dict__, "path": "human"}), rows[1]]
    with pytest.raises(ImmutableRowChanged):
        save_rejections(state / "rejections.yaml", tampered)


# ---------------------------------------------------------------------------
# contested · passed-ineligible → 관찰 목록 (upsert)
# ---------------------------------------------------------------------------


def test_contested_goes_to_watchlist_and_upserts(state: Path) -> None:
    rdir = _round(state, contested_thesis())
    scan = _scan(state, ("uranium", "coal"))
    rep = _run(state, rdir, scan=scan)
    assert rep.n_watchlist_upserts == 1 and rep.count("watchlist_added") == 1
    items = load_watchlist(state / "watchlist.yaml")
    assert len(items) == 1
    w = items[0]
    assert w.theme == "coal" and w.reason == "contested" and w.added_at == ASOF_D
    assert "referee:" in w.waiting_condition and "key_uncertainties:" in w.waiting_condition
    assert w.scan == SCAN_LABEL and w.scoreboard_rank == 2
    assert w.thesis_snapshot and w.thesis_snapshot.endswith("coal.thesis.yaml")
    assert w.journal is None

    # 재실행 — 행 하나 그대로, added_at 유지
    rep2 = _run(state, rdir, scan=scan)
    assert rep2.count("watchlist_updated") == 1 and rep2.count("watchlist_added") == 0
    items2 = load_watchlist(state / "watchlist.yaml")
    assert len(items2) == 1 and items2[0].added_at == ASOF_D


def test_passed_ineligible_reasons(state: Path) -> None:
    rdir = _round(state, capped_thesis(), axis1_na_thesis())
    scan = _scan(state, ("uranium", "newspapers", "shipping"))
    rep = _run(state, rdir, scan=scan)
    assert rep.n_watchlist_upserts == 2 and rep.n_drafts == 0 and rep.n_rejected_ingested == 0
    by = {w.theme: w for w in load_watchlist(state / "watchlist.yaml")}
    assert by["newspapers"].reason == "awaiting_condition"
    assert "상한 0.35" in by["newspapers"].waiting_condition
    assert by["shipping"].reason == "axis1_unavailable"
    assert "축 1 가용 시 재검토" in by["shipping"].waiting_condition


# ---------------------------------------------------------------------------
# passed & eligible → 진입 초안 (저널 항목이 아니다)
# ---------------------------------------------------------------------------


def _stock_plan() -> dict[str, Any]:
    return {
        "ticker": "CCJ",
        "role": "anchor",
        "target_weight": 0.16,
        "ladder_prices": [50.0, 43.5, 38.5],
        "ladder_weights": [0.5, 0.3, 0.2],
        "tier2_stop_price": 29.7,
        "tier2_pct_from_entry": -0.405,
        "time_stop_date": "2028-03-01",
        "tp_conditions": ["P50 또는 +2R", "P75 또는 고점 50%", "트레일 −25%"],
    }


def test_eligible_writes_entry_draft_that_journal_accepts_once_filled(state: Path) -> None:
    rdir = _round(state, eligible_thesis())
    scan = _scan(state, ("uranium",))
    macro = state / "macro" / "latest.json"
    macro.parent.mkdir(parents=True)
    macro.write_text(json.dumps({"asof": ASOF, "tailwind": {"uranium": 0.55}}), encoding="utf-8")

    rep = _run(state, rdir, scan=scan, macro_latest=macro)
    assert rep.n_drafts == 1 and rep.n_rejected_ingested == 0 and rep.n_watchlist_upserts == 0
    draft = rdir / f"{DRAFT_PREFIX}uranium.yaml"
    assert draft.exists()
    assert not (state.parent / "journal").exists()  # 저널에는 아무것도 쓰지 않았다
    assert "stocks" in " ".join(rep.human_todo["uranium"])
    text = draft.read_text(encoding="utf-8")
    assert text.startswith("# 진입 항목 초안")

    d = yaml.safe_load(text)
    assert d["type"] == "entry" and d["theme"] == "uranium" and str(d["date"]) == ASOF
    assert d["confidence_provenance"] == "referee"
    assert d["l1_blocks"] == {"A": 0.8, "B": 0.7, "C": 0.4, "D": 0.6, "E": 0.9, "F": 0.5}
    assert d["l2_tailwind"] == 0.55  # latest.json 이 thesis 의 0.42 보다 우선
    assert d["axis_verdicts"]["terminal_risk"] == "warning"
    assert d["stocks"] == [] and d["deviated_from_machine"] is False
    assert d["thesis"]["theme_id"] == "uranium"
    assert d["scan"] == SCAN_LABEL

    # 초안 그대로는 거부된다 — 사람 몫(stocks)이 비어 있다
    rec = record_from_dict(d)
    assert isinstance(rec, EntryRecord)
    with pytest.raises(IncompleteEntry, match="stocks"):
        rec.validate()

    # 사람이 채우면 `msa journal new --from` 경로(record_from_dict → write_record)가 받는다
    d["stocks"] = [_stock_plan()]
    w = write_record(record_from_dict(d), state.parent / "journal")
    assert w.markdown.name == f"{ASOF}-uranium-entry.md" and w.thesis_snapshot is not None
    assert load_entries(state.parent / "journal", "entry")[0]["l2_tailwind"] == 0.55


def test_eligible_draft_without_scoreboard_or_macro_leaves_blanks_not_zeros(state: Path) -> None:
    t = eligible_thesis()
    t["inputs"] = {"scan_dir": SCAN_LABEL}  # 순위·tailwind 없음
    rdir = _round(state, t)
    rep = _run(state, rdir, scan=None)
    assert rep.n_drafts == 1
    todo = " ".join(rep.human_todo["uranium"])
    assert "l1_blocks" in todo and "l2_tailwind" in todo
    d = yaml.safe_load((rdir / f"{DRAFT_PREFIX}uranium.yaml").read_text(encoding="utf-8"))
    assert d["l1_blocks"] == {} and d["l2_tailwind"] is None
    d["stocks"] = [_stock_plan()]
    with pytest.raises(IncompleteEntry) as ei:
        record_from_dict(d).validate()
    assert "l1_blocks" in str(ei.value) and "l2_tailwind" in str(ei.value)


# ---------------------------------------------------------------------------
# 라운드 혼합 · dry-run · append-only · CLI
# ---------------------------------------------------------------------------


def test_mixed_round_counts_every_thesis(state: Path) -> None:
    themes = ("uranium", "offshore_drilling", "coal", "newspapers", "shipping")
    rdir = _round(
        state,
        eligible_thesis(),
        rejected_thesis(),
        contested_thesis(),
        capped_thesis(),
        axis1_na_thesis(),
    )
    (rdir / "broken.thesis.yaml").write_text("- not a mapping\n", encoding="utf-8")
    scan = _scan(state, themes)
    rep = _run(state, rdir, scan=scan)
    assert rep.n_theses == 6
    assert rep.n_rejected_ingested == 1
    assert rep.n_watchlist_upserts == 3
    assert rep.n_drafts == 1
    assert rep.count("unknown_status") == 1  # 깨진 파일도 이름과 이유가 남는다
    assert "broken" in rep.render()


def test_dry_run_writes_nothing(state: Path) -> None:
    rdir = _round(state, eligible_thesis(), rejected_thesis(), contested_thesis())
    scan = _scan(state, ("uranium", "offshore_drilling", "coal"))
    rep = _run(state, rdir, scan=scan, write=False)
    assert rep.n_rejected_ingested == 1 and rep.n_watchlist_upserts == 1 and rep.n_drafts == 1
    assert not (state.parent / "journal").exists()
    assert not (state / "rejections.yaml").exists()
    assert not (state / "watchlist.yaml").exists()
    assert not (rdir / f"{DRAFT_PREFIX}uranium.yaml").exists()
    assert "dry-run" in rep.render()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_journal_verify_stays_green_after_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    st = repo / "state"
    st.mkdir(parents=True)
    monkeypatch.setenv("MSA_STATE", str(st))
    jdir = repo / "journal"
    jdir.mkdir()
    (jdir / "README.md").write_text("# journal\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")

    rdir = _round(st, rejected_thesis(), contested_thesis())
    scan = _scan(st, ("uranium", "offshore_drilling", "coal"))
    rep = ingest_round(
        rdir,
        asof=ASOF_D,
        scan_dir=scan,
        journal_dir=jdir,
        rejections_path=st / "rejections.yaml",
        watchlist_path=st / "watchlist.yaml",
    )
    assert rep.n_rejected_ingested == 1
    assert verify_append_only(repo) == []  # 새 파일만 — 기존 항목 변경 없음
    _git(repo, "add", "journal")
    assert verify_append_only(repo, staged_only=True) == []


def test_cli_ingest_theses(state: Path) -> None:
    rdir = _round(state, rejected_thesis(), eligible_thesis())
    scan = _scan(state, ("uranium", "offshore_drilling"))
    runner = CliRunner()
    jdir = state.parent / "journal"
    r = runner.invoke(
        app,
        [
            "ops",
            "ingest-theses",
            "--theses-dir",
            str(rdir),
            "--scan",
            str(scan),
            "--journal",
            str(jdir),
            "--dry-run",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "dry-run" in r.output and not jdir.exists()
    r2 = runner.invoke(
        app,
        [
            "ops",
            "ingest-theses",
            "--theses-dir",
            str(rdir),
            "--scan",
            str(scan),
            "--journal",
            str(jdir),
        ],
    )
    assert r2.exit_code == 0, r2.output
    assert (jdir / f"{ASOF}-offshore_drilling-reject.md").exists()
    assert (rdir / f"{DRAFT_PREFIX}uranium.yaml").exists()
    assert len(load_rejections(state / "rejections.yaml")) == 1
    assert "offshore_drilling" in r2.output and "uranium" in r2.output
