"""L3 라운드 산출물(`state/theses/<date>/`) → 운영 파일 적재 — `msa ops ingest-theses`.

`msa research` 는 thesis 를 저장하고 기각 행을 `rejections-pending.yaml` 에 남길 뿐, 저널·기각 대장·
관찰 목록은 건드리지 않는다 (`docs/05` §7 "대장 적재는 M8"). 이 모듈이 그 연결이다 — **기계가 쓸 수
있는 것만 쓰고, 사람의 결정이 필요한 것은 초안으로 남긴다** (`docs/09` §2·§4).

| status | eligible | 기계가 쓰는 것 |
|---|---|---|
| `rejected` | — | 저널 **기각 항목** (`journal/<asof>-<theme>-reject.md` + `.thesis.yaml` 스냅샷) |
|            |   | → 기각 대장 행 (`journal` 열 = 그 항목) |
| `contested` | false | 관찰 목록 행 `reason: contested` (대기 조건 = referee 판정 +
|             |       | key_uncertainties) |
| `passed` | false | 관찰 목록 행 `reason: axis1_unavailable` (축 1 불가가 원인) |
|          |       | 또는 `awaiting_condition` (게이트 사유) |
| `passed` | true | **진입 항목 초안** `state/theses/<date>/journal-draft-<theme>.yaml` |
|          |      | — 저널 항목이 아니다 |

진입 항목을 기계가 쓰지 않는 이유: 진입은 종목·비중·사다리·스탑·TP 와 "기계 권고와 다르게 결정했다면
그 이유" 를 담아야 하고(`docs/09` §2) 그건 사람의 결정이다. 초안은 `msa journal new --from` 이 받는
모양 그대로이며 사람이 채워야 할 필드는 파일 머리 주석과 보고서에 나열한다.

멱등: 기각 대장에 `(theme, rejected_at)` 행이 이미 있으면 건너뛰고 보고한다. 관찰 목록은 테마별
upsert (기존 `added_at` 유지). 저널은 append-only — 기존 파일은 절대 고치지 않고, 같은 이름의 기각
항목이 이미 있으면 그 경로를 대장 행에 쓴다. **조용히 빠지는 테마는 없다** — 읽지 못했거나 적재할 수
없는 것도 `IngestReport` 에 이름과 이유가 남는다 (`CLAUDE.md` §2).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, cast

import pandas as pd

from msa.coerce import opt_float, opt_int
from msa.config import paths, rel
from msa.io import yaml_text
from msa.ops.journal import (
    BLOCKS,
    JournalImmutable,
    RejectRecord,
    Written,
    entry_filename,
    write_record,
)
from msa.ops.state_files import (
    Rejection,
    WatchItem,
    WatchReason,
    load_rejections,
    load_watchlist,
    save_rejections,
    save_watchlist,
)
from msa.thesis import AXES, gate_status, read_thesis_yaml, theme_of, theses_in

log = logging.getLogger(__name__)

DRAFT_PREFIX = "journal-draft-"

#: 진입 초안에서 사람이 반드시 채워야 하는 필드 — `EntryRecord.validate()` 가 비면 거부하는 것들.
HUMAN_FIELDS_ALWAYS: tuple[str, ...] = (
    "stocks — 종목·역할·목표비중·사다리 3단 가격/배분·Tier-2 스탑·시간스탑·TP 3단 "
    "(L5 매매계획서에서)",
    "deviated_from_machine / deviation_reason — 기계 권고와 다르게 결정했다면 그 이유",
)


# ---------------------------------------------------------------------------
# 보고서
# ---------------------------------------------------------------------------


@dataclass
class Ingested:
    """한 테마의 적재 결과 한 줄 — 무엇을 어디에 썼는가(또는 왜 못 썼는가)."""

    theme: str
    status: str  # gate_result.status 또는 "unreadable"
    action: str  # reject_ingested | reject_skipped | reject_blocked | watchlist_added |
    #              watchlist_updated | draft_written | unknown_status
    detail: str = ""
    paths: list[str] = field(default_factory=list)


@dataclass
class IngestReport:
    asof: date
    theses_dir: str
    scan_dir: str | None
    write: bool
    rows: list[Ingested] = field(default_factory=list)
    missing_rank: list[str] = field(default_factory=list)  # scoreboard.csv 에서 순위를 못 찾은 테마
    human_todo: dict[str, list[str]] = field(default_factory=dict)  # 초안별 사람 몫 필드
    notes: list[str] = field(default_factory=list)

    # --- 집계 (보고서 출력과 테스트가 같은 숫자를 본다)
    def count(self, action: str) -> int:
        return sum(1 for r in self.rows if r.action == action)

    @property
    def n_theses(self) -> int:
        return len(self.rows)

    @property
    def n_rejected_ingested(self) -> int:
        return self.count("reject_ingested")

    @property
    def n_rejected_skipped(self) -> int:
        return self.count("reject_skipped")

    @property
    def n_rejected_blocked(self) -> int:
        return self.count("reject_blocked")

    @property
    def n_watchlist_upserts(self) -> int:
        return self.count("watchlist_added") + self.count("watchlist_updated")

    @property
    def n_drafts(self) -> int:
        return self.count("draft_written")

    def render(self) -> str:
        mode = "" if self.write else " (dry-run — 파일을 쓰지 않았다)"
        L = [
            f"# L3 적재 · {self.asof} · {self.theses_dir}{mode}",
            f"스캔: {self.scan_dir or '없음'} · thesis {self.n_theses}개",
            "",
            f"- 기각 → 저널+대장 {self.n_rejected_ingested} · 이미 대장에 있어 건너뜀 "
            f"{self.n_rejected_skipped} · 적재 불가 {self.n_rejected_blocked}",
            f"- 관찰 목록 upsert {self.n_watchlist_upserts} "
            f"(추가 {self.count('watchlist_added')} · 갱신 {self.count('watchlist_updated')})",
            f"- 진입 초안 {self.n_drafts} (저널 항목이 아니다 — 사람이 채워 "
            "`msa journal new --from`)",
        ]
        if self.missing_rank:
            L.append(f"- scoreboard_rank 없음: {', '.join(self.missing_rank)}")
        L.append("")
        for r in self.rows:
            p = f" → {', '.join(r.paths)}" if r.paths else ""
            L.append(f"| {r.theme} | {r.status} | {r.action} | {r.detail}{p}")
        for theme, todo in self.human_todo.items():
            L += ["", f"## {theme} 초안 — 사람이 채울 것"] + [f"- {x}" for x in todo]
        if self.notes:
            L += ["", "## 비고"] + [f"- {n}" for n in self.notes]
        return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# 스캔 스코어보드 (순위 · 블록 6개)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreboardView:
    """`state/scans/<date>/scoreboard.csv` 의 순위·블록만. 파일이 없으면 `table=None` 으로
    **명시**."""

    scan_dir: Path | None
    table: pd.DataFrame | None

    @property
    def label(self) -> str | None:
        return f"state/scans/{self.scan_dir.name}" if self.scan_dir is not None else None

    def rank(self, theme: str) -> int | None:
        if self.table is None or theme not in self.table.index or "rank" not in self.table.columns:
            return None
        return opt_int(self.table.loc[theme, "rank"])

    def blocks(self, theme: str) -> dict[str, float] | None:
        """A..F 6개 전부 있을 때만 돌려준다 — 일부만 채운 표는 값이 아니다."""
        if self.table is None or theme not in self.table.index:
            return None
        if any(b not in self.table.columns for b in BLOCKS):
            return None
        row = self.table.loc[theme]
        vals = {b: opt_float(row[b]) for b in BLOCKS}
        if any(v is None for v in vals.values()):
            return None
        return {b: float(v) for b, v in vals.items() if v is not None}


def load_scoreboard(scan_dir: Path | None) -> ScoreboardView:
    if scan_dir is None or not (scan_dir / "scoreboard.csv").exists():
        return ScoreboardView(scan_dir=scan_dir, table=None)
    return ScoreboardView(
        scan_dir=scan_dir, table=pd.read_csv(scan_dir / "scoreboard.csv", index_col=0)
    )


def resolve_scan_dir(thesis: dict[str, Any], explicit: Path | None) -> Path | None:
    """`--scan` 이 없으면 thesis 가 적어 둔 `inputs.scan_dir` 라벨(`state/scans/<date>`)을 현재
    `state/scans/` 아래에서 찾는다. 못 찾으면 None — 호출자가 보고한다."""
    if explicit is not None:
        return explicit
    label = (thesis.get("inputs") or {}).get("scan_dir")
    if not label:
        return None
    cand = paths().scans / Path(str(label)).name
    return cand if cand.is_dir() else None


# ---------------------------------------------------------------------------
# thesis → 레코드/행
# ---------------------------------------------------------------------------


def _axis_verdicts(thesis: dict[str, Any]) -> dict[str, str]:
    """`value_trap_axes[*].verdict` 5축 — 저널이 요구하는 모양 (`docs/09` §2)."""
    axes = thesis.get("value_trap_axes") or {}
    return {a: str((axes.get(a) or {}).get("verdict")) for a in AXES}


def _evidence_refs(thesis: dict[str, Any]) -> dict[str, list[int]]:
    axes = thesis.get("value_trap_axes") or {}
    return {a: [int(x) for x in (axes.get(a) or {}).get("evidence_refs", []) or []] for a in AXES}


def _gate(thesis: dict[str, Any]) -> dict[str, Any]:
    g = thesis.get("gate_result")
    return g if isinstance(g, dict) else {}


def _conf(thesis: dict[str, Any]) -> float | None:
    c = thesis.get("cycle_confidence")
    return None if c is None else float(c)


def _scan_label(thesis: dict[str, Any], sb: ScoreboardView) -> str:
    """기록에 남기는 스캔 경로 — thesis 가 본 라벨이 우선 (그 결정이 본 스코어보드), 없으면
    `--scan`."""
    label = (thesis.get("inputs") or {}).get("scan_dir")
    return str(label) if label else (sb.label or "")


def reject_record(
    thesis: dict[str, Any], *, asof: date, scoreboard_rank: int | None, scan: str
) -> RejectRecord:
    """기각 thesis → 저널 기각 항목 (기계 작성). `path` 는 `gate_result.path`, 사유는
    `rejections-pending.yaml` 행과 같은 꼴(`rule — reason`). `override_reason` 은 비운다 —
    기계가 기각한 것이므로 "사람이 편입하지 않은 이유" 가 성립하지 않는다."""
    g = _gate(thesis)
    path = g.get("path")
    return RejectRecord(
        date=asof,
        theme=str(thesis["theme_id"]),
        path=str(path) if path else "",
        axis_verdicts=_axis_verdicts(thesis),
        cycle_confidence=_conf(thesis),
        scoreboard_rank=int(scoreboard_rank) if scoreboard_rank is not None else 0,  # 0 → 거부
        scan=scan,
        reason=f"{g.get('rule', '')} — {g.get('reason', '')}".strip(" —"),
        thesis=thesis,
        evidence_refs=_evidence_refs(thesis),
        links=[],
    )


def rejection_from_record(rec: RejectRecord, *, journal_path: str) -> Rejection:
    """저널 기각 항목 → 기각 대장 행 (`docs/09` §4). `journal` 열이 저널 항목을 가리킨다."""
    return Rejection(
        theme=rec.theme,
        rejected_at=rec.date,
        path=rec.path,
        reason=rec.reason,
        cycle_confidence=rec.cycle_confidence,
        scoreboard_rank=rec.scoreboard_rank,
        journal=journal_path,
        scan=rec.scan,
        axis_verdicts=dict(rec.axis_verdicts),
    )


def _waiting_condition_contested(thesis: dict[str, Any]) -> str:
    """referee 의 미해소 판정 + key_uncertainties — 무엇이 관측되면 재검토하는가."""
    g = _gate(thesis)
    parts: list[str] = []
    ruling = g.get("referee_ruling")
    if ruling and str(ruling).strip():
        parts.append(f"referee: {str(ruling).strip()}")
    unc = [str(x).strip() for x in thesis.get("key_uncertainties") or [] if str(x).strip()]
    if unc:
        parts.append("key_uncertainties: " + " · ".join(unc))
    if not parts:
        parts.append(str(g.get("reason") or g.get("rule") or "axis1_contested — 재판정 대기"))
    return " / ".join(parts)


def _watch_reason_ineligible(thesis: dict[str, Any]) -> tuple[str, str]:
    """passed 인데 편입 불가 → (reason, waiting_condition). 축 1 을 쓸 수 없는 것이 원인이면
    `axis1_unavailable`, 아니면 게이트가 적은 사유 그대로 `awaiting_condition`."""
    g = _gate(thesis)
    a1 = (thesis.get("value_trap_axes") or {}).get("unit_demand") or {}
    gate_note = f"{g.get('rule', '')} — {g.get('reason', '')}".strip(" —") or "게이트 사유 없음"
    if a1.get("axis1_available") is False:
        return "axis1_unavailable", f"축 1 가용 시 재검토 — {gate_note}"
    return "awaiting_condition", gate_note


def watch_item(
    thesis: dict[str, Any],
    *,
    asof: date,
    reason: str,
    waiting_condition: str,
    scan: str,
    thesis_path: Path,
    scoreboard_rank: int | None,
) -> WatchItem:
    return WatchItem(
        theme=str(thesis["theme_id"]),
        added_at=asof,
        reason=cast(WatchReason, reason),  # 호출자가 WATCH_REASONS 값만 준다
        waiting_condition=waiting_condition,
        scan=scan,
        thesis_snapshot=rel(thesis_path),
        journal=None,
        scoreboard_rank=scoreboard_rank,
        note="msa ops ingest-theses 가 올림 (L3 게이트 결과)",
    )


def upsert_watch(items: list[WatchItem], new: WatchItem) -> tuple[list[WatchItem], bool]:
    """테마별 upsert — 있으면 `added_at` 은 그대로 두고 나머지를 갱신. 반환 (목록, 추가됐는가)."""
    for i, cur in enumerate(items):
        if cur.theme == new.theme:
            out = list(items)
            out[i] = replace(new, added_at=cur.added_at)
            return out, False
    return [*items, new], True


def entry_draft(
    thesis: dict[str, Any],
    *,
    asof: date,
    scan: str,
    l1_blocks: dict[str, float] | None,
) -> tuple[dict[str, Any], list[str]]:
    """진입 항목 초안 dict (`msa journal new --from` 의 entry 모양) + 사람이 채울 필드 목록.

    기계가 아는 값만 넣는다 — 모르는 값(블록)은 **가짜 0 이 아니라 비운다**: `EntryRecord`
    가 거부하므로 사람이 채울 때까지 저널에 들어가지 않는다."""
    todo = list(HUMAN_FIELDS_ALWAYS)
    if l1_blocks is None:
        todo.append("l1_blocks — 스코어보드(A..F) 6개 값 (scoreboard.csv 에서 읽지 못했다)")
    d: dict[str, Any] = {
        "type": "entry",
        "date": asof.isoformat(),
        "theme": str(thesis["theme_id"]),
        "confidence_provenance": "referee",  # c 는 L3 referee 파이프라인 산출 (05 §7)
        "scan": scan,
        "l1_blocks": l1_blocks if l1_blocks is not None else {},
        "axis_verdicts": _axis_verdicts(thesis),
        "deviated_from_machine": False,
        "deviation_reason": "",
        "bear_case": str(thesis.get("bear_case") or ""),
        "stocks": [],
        "thesis": thesis,
        "links": [],
        "notes": "",
    }
    return d, todo


def render_draft(d: dict[str, Any], todo: list[str]) -> str:
    """초안 파일 본문 — 머리 주석(사람 몫)과 YAML. 주석은 `yaml.safe_load` 가 무시한다."""
    head = [
        "# 진입 항목 초안 — msa ops ingest-theses 가 만들었다. 저널 항목이 아니다.",
        "# 아래를 채운 뒤: msa journal new --from <이 파일>  (비면 EntryRecord 가 거부한다)",
        *[f"#   - {x}" for x in todo],
        "# cycle_confidence 산출 주체: referee (thesis.cycle_confidence_by).",
        "# 사람이 다시 산출했으면 confidence_provenance: human 으로 바꾸고",
        "# thesis.cycle_confidence 를 그 값으로 둔다.",
        "",
    ]
    return "\n".join(head) + yaml_text(d)


# ---------------------------------------------------------------------------
# 라운드 적재
# ---------------------------------------------------------------------------


def _journal_rel(p: Path) -> str:
    """대장·관찰 목록에 적는 저널 경로 — 저장소 안이면 `journal/...`, 밖이면 절대 경로."""
    return rel(p)


def ingest_round(
    theses_dir: Path,
    *,
    asof: date,
    scan_dir: Path | None,
    journal_dir: Path,
    rejections_path: Path,
    watchlist_path: Path,
    write: bool = True,
    thesis_paths: Sequence[Path] | None = None,
) -> IngestReport:
    """`state/theses/<date>/` 한 라운드를 저널·기각 대장·관찰 목록·진입 초안으로 적재한다.

    `write=False` 면 같은 판단을 하되 파일을 쓰지 않는다 (레코드 검증은 돌린다 — 쓰기 직전에
    거부될 것을 미리 보고한다).

    `thesis_paths` 를 주면 디렉터리를 훑는 대신 **그 파일들만** 적재한다 — 새 L3 라운드 없이
    이미 있는 thesis(사람 논지·직전 라운드)로 게이트 판정만 하는 경로(`msa run monthly
    --provider none`)가 쓴다. 판정 규칙은 같다; 진입 초안은 `theses_dir` 에 쓴다.
    """
    report = IngestReport(
        asof=asof,
        theses_dir=rel(theses_dir),
        scan_dir=rel(scan_dir) if scan_dir is not None else None,
        write=write,
    )
    files = theses_in(theses_dir) if thesis_paths is None else [Path(f) for f in thesis_paths]
    if not files:
        report.notes.append(
            f"{theses_dir} 에 *.thesis.yaml 이 없다"
            if thesis_paths is None
            else "적재할 thesis 파일이 0개다"
        )
        return report

    ledger = load_rejections(rejections_path)
    ledger_keys = {r.key for r in ledger}
    watch = load_watchlist(watchlist_path)
    new_rows: list[Rejection] = []
    sb_cache: dict[Path | None, ScoreboardView] = {}

    for tp in files:
        theme = theme_of(tp)
        try:
            thesis = read_thesis_yaml(tp)
        except Exception as e:  # 한 파일 때문에 라운드가 멈추지 않는다 — 이름과 이유를 남긴다
            report.rows.append(Ingested(theme, "unreadable", "unknown_status", f"읽기 실패: {e}"))
            continue
        status = gate_status(thesis)
        sd = resolve_scan_dir(thesis, scan_dir)
        if sd not in sb_cache:
            sb_cache[sd] = load_scoreboard(sd)
        sb = sb_cache[sd]
        if report.scan_dir is None and sb.scan_dir is not None:
            report.scan_dir = rel(sb.scan_dir)
        rank = sb.rank(theme)
        rank_src = "scoreboard.csv"
        if rank is None:
            # thesis 가 연구 시점에 본 순위 — 같은 스캔의 값이다. 스코어보드가 없었음은 보고한다
            r2 = (thesis.get("inputs") or {}).get("scoreboard_rank")
            rank = None if r2 is None else int(r2)
            rank_src = "thesis.inputs.scoreboard_rank" if rank is not None else "없음"
            report.missing_rank.append(theme)
        scan = _scan_label(thesis, sb)
        gate = _gate(thesis)

        if status == "rejected":
            key = (theme, asof.isoformat())
            if key in ledger_keys:
                report.rows.append(
                    Ingested(
                        theme,
                        status,
                        "reject_skipped",
                        "기각 대장에 같은 (theme, rejected_at) 행 있음",
                    )
                )
                continue
            if rank is None:
                report.rows.append(
                    Ingested(
                        theme,
                        status,
                        "reject_blocked",
                        "scoreboard_rank 없음 — 기각 항목은 순위를 요구한다 (09 §2). "
                        "--scan 으로 스코어보드를 주고 다시 돌려라",
                    )
                )
                continue
            rec = reject_record(thesis, asof=asof, scoreboard_rank=rank, scan=scan)
            try:
                rec.validate()
            except Exception as e:
                report.rows.append(
                    Ingested(theme, status, "reject_blocked", f"기각 항목 거부: {e}")
                )
                continue
            md_path = journal_dir / entry_filename(rec)
            if md_path.exists():
                detail = f"저널 기각 항목이 이미 있어 그 경로를 대장에 쓴다 (순위 출처 {rank_src})"
                written: Written | None = Written(markdown=md_path, thesis_snapshot=None)
            elif write:
                try:
                    written = write_record(rec, journal_dir)
                except JournalImmutable as e:
                    report.rows.append(Ingested(theme, status, "reject_blocked", str(e)))
                    continue
                detail = f"저널 기각 항목 + 스냅샷 + 대장 행 (순위 출처 {rank_src})"
            else:
                written = None
                detail = f"(dry-run) 저널 기각 항목 + 대장 행 예정 (순위 출처 {rank_src})"
            jpath = _journal_rel(md_path)
            row = rejection_from_record(rec, journal_path=jpath)
            new_rows.append(row)
            ledger_keys.add(key)
            outs = [jpath] + (
                [rel(written.thesis_snapshot)] if written and written.thesis_snapshot else []
            )
            report.rows.append(
                Ingested(theme, status, "reject_ingested", detail, [*outs, rel(rejections_path)])
            )
            continue

        if status == "contested":
            item = watch_item(
                thesis,
                asof=asof,
                reason="contested",
                waiting_condition=_waiting_condition_contested(thesis),
                scan=scan,
                thesis_path=tp,
                scoreboard_rank=rank,
            )
            watch, added = upsert_watch(watch, item)
            report.rows.append(
                Ingested(
                    theme,
                    status,
                    "watchlist_added" if added else "watchlist_updated",
                    "reason=contested",
                    [rel(watchlist_path)],
                )
            )
            continue

        if status == "passed" and not bool(gate.get("portfolio_eligible")):
            reason, cond = _watch_reason_ineligible(thesis)
            item = watch_item(
                thesis,
                asof=asof,
                reason=reason,
                waiting_condition=cond,
                scan=scan,
                thesis_path=tp,
                scoreboard_rank=rank,
            )
            watch, added = upsert_watch(watch, item)
            report.rows.append(
                Ingested(
                    theme,
                    status,
                    "watchlist_added" if added else "watchlist_updated",
                    f"reason={reason}",
                    [rel(watchlist_path)],
                )
            )
            continue

        if status == "passed":
            blocks = sb.blocks(theme)
            d, todo = entry_draft(thesis, asof=asof, scan=scan, l1_blocks=blocks)
            draft_path = theses_dir / f"{DRAFT_PREFIX}{theme}.yaml"
            if write:
                draft_path.write_text(render_draft(d, todo), encoding="utf-8")
            report.human_todo[theme] = todo
            report.rows.append(
                Ingested(
                    theme,
                    status,
                    "draft_written",
                    "진입 초안 (저널 항목 아님 — 사람이 채운다)" + ("" if write else " (dry-run)"),
                    [rel(draft_path)],
                )
            )
            continue

        report.rows.append(
            Ingested(
                theme,
                str(status),
                "unknown_status",
                "gate_result.status 가 enum 밖이라 적재하지 않았다",
            )
        )

    if write:
        if new_rows:
            save_rejections(rejections_path, [*ledger, *new_rows])  # 기존 행 불변 — 위반이면 예외
        if report.n_watchlist_upserts:
            save_watchlist(watchlist_path, watch)
    return report


__all__ = [
    "DRAFT_PREFIX",
    "HUMAN_FIELDS_ALWAYS",
    "IngestReport",
    "Ingested",
    "ScoreboardView",
    "entry_draft",
    "ingest_round",
    "load_scoreboard",
    "reject_record",
    "rejection_from_record",
    "render_draft",
    "resolve_scan_dir",
    "upsert_watch",
    "watch_item",
]
