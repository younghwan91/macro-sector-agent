"""결정 저널 — `journal/` append-only (`CLAUDE.md` §6, `docs/09-operations.md` §2).

항목 6종: `entry` · `check` · `add` · `tp` · `exit` · `reject`. 각 항목은 dataclass 로 받아
**필수 필드가 비면 작성을 거부한다** (`IncompleteEntry`). 파일명은
`YYYY-MM-DD-<theme>-<type>.md` 이고, 이미 있으면 덮어쓰지 않는다 — 같은 날 같은 종류가 둘이면
`suffix` 를 준다. 진입·(재실행이 있는) 점검·기각 항목은 `.thesis.yaml` 스냅샷을 옆에 남긴다.

append-only 강제는 git 으로 한다: `verify_append_only()` 는 HEAD 에 들어 있는 `journal/` 파일이
작업트리·인덱스에서 바뀌었거나 지워졌으면 실패한다. `scripts/journal-precommit.sh` 가 커밋 직전에
같은 검사를 돌린다 (설치는 `msa journal install-hook` — 자동으로 깔지 않는다).

마크다운 항목의 머리에는 YAML front matter 가 있다. 캘리브레이션·기각 대장은 그 front matter 를
읽는다 — 사람이 읽는 본문과 기계가 읽는 필드를 한 파일에 두되, 기계는 본문을 파싱하지 않는다.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml

from msa.config import REPO_ROOT
from msa.ops.thesis import (
    AXES,
    AXIS_VERDICTS,
    CONFIDENCE_PROVENANCE,
    REJECTION_PATHS,
    ThesisInvalid,
    diff_thesis,
    render_diff,
    validate_thesis,
)

JOURNAL_DIRNAME = "journal"
BLOCKS = ("A", "B", "C", "D", "E", "F")
ENTRY_TYPES = ("entry", "check", "add", "tp", "exit", "reject")
ExitVia = Literal["tier1", "tier2", "time_stop", "tp_complete", "human"]


class IncompleteEntry(ValueError):
    """필수 필드가 비어 작성이 거부됐다. 어떤 필드인지 전부 나열한다."""


class JournalImmutable(RuntimeError):
    """기존 파일을 덮어쓰려 했다 — 생각이 바뀌면 새 항목을 추가하고 링크한다."""


def journal_dir(root: Path | None = None) -> Path:
    return (root or REPO_ROOT) / JOURNAL_DIRNAME


# ---------------------------------------------------------------------------
# 항목 dataclass — 각자 validate() 가 누락 필드 목록을 돌려준다
# ---------------------------------------------------------------------------


def _blank(s: str | None) -> bool:
    return s is None or not str(s).strip()


@dataclass
class StockPlan:
    """매매계획서 한 줄 (docs/07 §6) — 진입 항목이 종목별로 담는 것."""

    ticker: str
    role: str  # anchor | torque
    target_weight: float
    ladder_prices: list[float]  # 1·2·3단 가격
    ladder_weights: list[float]  # 목표비중 대비 배분
    tier2_stop_price: float
    tier2_pct_from_entry: float  # 초기가 대비 (음수, 예 −0.405) — 사용자가 보는 숫자
    time_stop_date: date
    tp_conditions: list[str]  # TP1 · TP2 · 러너 조건 문구 3개
    tp_prices: list[float | None] = field(default_factory=lambda: [None, None, None])

    def problems(self) -> list[str]:
        p: list[str] = []
        if _blank(self.ticker):
            p.append("stocks[*].ticker")
        if self.role not in ("anchor", "torque"):
            p.append(f"stocks[{self.ticker}].role ∈ {{anchor, torque}}")
        if len(self.ladder_prices) != 3 or len(self.ladder_weights) != 3:
            p.append(f"stocks[{self.ticker}].ladder_prices/ladder_weights 는 3단이어야 한다")
        if len(self.tp_conditions) != 3 or any(_blank(c) for c in self.tp_conditions):
            p.append(f"stocks[{self.ticker}].tp_conditions 3단 (TP1·TP2·러너) 문구")
        if not isinstance(self.time_stop_date, date):
            p.append(f"stocks[{self.ticker}].time_stop_date")
        if self.tier2_pct_from_entry >= 0:
            p.append(f"stocks[{self.ticker}].tier2_pct_from_entry 는 음수(초기가 대비 하락률)")
        return p


@dataclass
class EntryRecord:
    """진입 항목 — docs/09 §2 "진입 항목이 담는 것" 을 하나라도 빼면 거부."""

    date: date
    theme: str
    thesis: dict[str, Any]
    confidence_provenance: str  # human | referee — 누가 c 를 산출했는가
    l1_blocks: dict[str, float]  # A..F 블록 점수 6개
    l2_tailwind: float
    axis_verdicts: dict[str, str]  # 5축 판정
    stocks: list[StockPlan]
    deviated_from_machine: bool
    deviation_reason: str = ""  # deviated_from_machine 이면 필수
    bear_case: str = ""  # 비면 thesis.bear_case 를 쓴다 — 그것도 비면 거부
    scan: str = ""  # state/scans/<date>/
    links: list[str] = field(default_factory=list)
    notes: str = ""
    type: str = field(default="entry", init=False)

    def validate(self) -> None:
        missing: list[str] = []
        try:
            validate_thesis(self.thesis)
        except ThesisInvalid as e:
            missing.append(str(e))
        if self.confidence_provenance not in CONFIDENCE_PROVENANCE:
            missing.append(f"confidence_provenance ∈ {CONFIDENCE_PROVENANCE} (누가 c 를 산출했나)")
        if sorted(self.l1_blocks) != list(BLOCKS):
            missing.append(f"l1_blocks 는 {BLOCKS} 6개 값 (있는 것: {sorted(self.l1_blocks)})")
        if sorted(self.axis_verdicts) != sorted(AXES) or any(
            v not in AXIS_VERDICTS for v in self.axis_verdicts.values()
        ):
            missing.append(f"axis_verdicts 5축 {AXES} 각각 ∈ {AXIS_VERDICTS}")
        if not self.stocks:
            missing.append("stocks (종목·비중·사다리·스탑·TP) 최소 1개")
        for s in self.stocks:
            missing.extend(s.problems())
        if self.deviated_from_machine and _blank(self.deviation_reason):
            missing.append("deviation_reason — 기계 권고와 다르게 결정했다면 그 이유")
        if _blank(self.bear_case) and _blank(self.thesis.get("bear_case")):
            missing.append("bear_case 원문")
        if _blank(self.scan):
            missing.append("scan — 이 결정이 본 스코어보드 스냅샷 경로")
        if missing:
            raise IncompleteEntry("진입 항목 작성 거부 — 누락:\n  - " + "\n  - ".join(missing))


@dataclass
class StatusChange:
    observable: str
    before: str
    after: str


@dataclass
class CheckRecord:
    """점검 항목 — 트리거/무효화 상태 변화 + (재실행 시) thesis diff."""

    date: date
    theme: str
    cadence: str  # weekly | monthly | daily
    trigger_status: list[StatusChange]  # 모든 트리거의 (이전 → 현재). 변화 없으면 before == after
    invalidation_status: list[StatusChange]
    check_report: str = ""  # state/checks/<date>/report.txt
    thesis: dict[str, Any] | None = None  # 재실행된 thesis — 있으면 스냅샷 + diff
    notes: str = ""
    links: list[str] = field(default_factory=list)
    type: str = field(default="check", init=False)

    def validate(self) -> None:
        missing: list[str] = []
        if self.cadence not in ("weekly", "monthly", "daily"):
            missing.append("cadence ∈ {weekly, monthly, daily}")
        if not self.trigger_status:
            missing.append("trigger_status — 각 trigger 의 상태 (변화 없어도 적는다)")
        if not self.invalidation_status:
            missing.append("invalidation_status — 각 invalidation 의 상태")
        if self.thesis is not None:
            try:
                validate_thesis(self.thesis)
            except ThesisInvalid as e:
                missing.append(str(e))
        if missing:
            raise IncompleteEntry("점검 항목 작성 거부 — 누락:\n  - " + "\n  - ".join(missing))


@dataclass
class Fill:
    ticker: str
    price: float
    shares: float | None = None


@dataclass
class AddRecord:
    """사다리 n단 실행 — 가격 조건 + 논지 조건 동시 충족이 전제다 (docs/07 §3)."""

    date: date
    theme: str
    step: int  # 2 | 3
    fills: list[Fill]
    price_move_from_entry: float  # 초기가 대비 (음수)
    invalidations_fired: int
    triggers_met: int
    triggers_total: int
    judgment: str  # 그때의 판단 — 왜 지금 실행했는가
    override_reason: str = ""  # invalidations_fired > 0 인데 실행했다면 필수 (규칙 위반 기록)
    links: list[str] = field(default_factory=list)
    type: str = field(default="add", init=False)

    def validate(self) -> None:
        missing: list[str] = []
        if self.step not in (2, 3):
            missing.append("step ∈ {2, 3}")
        if not self.fills:
            missing.append("fills (체결 종목·가격)")
        if _blank(self.judgment):
            missing.append("judgment — 그때의 판단")
        if self.invalidations_fired > 0 and _blank(self.override_reason):
            missing.append(
                "override_reason — 무효화 발동 상태에서 추가 매수는 규칙 위반이다(07 §3). "
                "그래도 했다면 이유를 적어야 기록된다"
            )
        if (
            self.triggers_total <= 0
            or self.triggers_met < 0
            or self.triggers_met > self.triggers_total
        ):
            missing.append("triggers_met/triggers_total")
        if missing:
            raise IncompleteEntry("사다리 항목 작성 거부 — 누락:\n  - " + "\n  - ".join(missing))


@dataclass
class TpRecord:
    date: date
    theme: str
    level: str  # tp1 | tp2 | runner
    fills: list[Fill]
    condition_met: str  # 어떤 조건이 충족됐나 (측정값)
    judgment: str
    new_tier2_stop_price: float | None = None  # tp1 이면 필수 — 본전으로 상향 (07 §5)
    links: list[str] = field(default_factory=list)
    type: str = field(default="tp", init=False)

    def validate(self) -> None:
        missing: list[str] = []
        if self.level not in ("tp1", "tp2", "runner"):
            missing.append("level ∈ {tp1, tp2, runner}")
        if not self.fills:
            missing.append("fills")
        if _blank(self.condition_met):
            missing.append("condition_met")
        if _blank(self.judgment):
            missing.append("judgment")
        if self.level == "tp1" and self.new_tier2_stop_price is None:
            missing.append("new_tier2_stop_price — TP1 체결 후 Tier-2 스탑을 본전으로 상향 (07 §5)")
        if missing:
            raise IncompleteEntry("TP 항목 작성 거부 — 누락:\n  - " + "\n  - ".join(missing))


@dataclass
class ExitRecord:
    """청산 + 사후 대조 — 캘리브레이션(`docs/10` §4)·전향적 기록(§6)의 입력."""

    date: date
    theme: str
    exit_via: str  # tier1 | tier2 | time_stop | tp_complete | human
    realized_return: float
    holding_days: int
    triggers_met: int
    triggers_total: int
    invalidations_fired: int
    mechanism_assessment: str  # 메커니즘이 서술대로 작동했는가 (다른 이유로 맞았을 수 있다)
    confidence_assessment: str  # cycle_confidence 가 사후에 적절했는가
    cycle_confidence: float
    confidence_provenance: str
    entry_journal: str  # 진입 항목 링크
    thesis_snapshot: str  # 진입 시점 thesis 스냅샷
    horizon_elapsed: bool = False  # 청산 시점에 horizon 상한이 지났는가
    links: list[str] = field(default_factory=list)
    notes: str = ""
    type: str = field(default="exit", init=False)

    def validate(self) -> None:
        missing: list[str] = []
        if self.exit_via not in ("tier1", "tier2", "time_stop", "tp_complete", "human"):
            missing.append("exit_via ∈ {tier1, tier2, time_stop, tp_complete, human}")
        if self.triggers_total <= 0 or not (0 <= self.triggers_met <= self.triggers_total):
            missing.append("triggers_met/triggers_total (트리거 충족률)")
        if self.invalidations_fired < 0:
            missing.append("invalidations_fired")
        if _blank(self.mechanism_assessment):
            missing.append("mechanism_assessment")
        if _blank(self.confidence_assessment):
            missing.append("confidence_assessment")
        if not (0.0 <= self.cycle_confidence <= 1.0):
            missing.append("cycle_confidence ∈ [0,1]")
        if self.confidence_provenance not in CONFIDENCE_PROVENANCE:
            missing.append(f"confidence_provenance ∈ {CONFIDENCE_PROVENANCE}")
        if _blank(self.entry_journal):
            missing.append("entry_journal 링크")
        if _blank(self.thesis_snapshot):
            missing.append("thesis_snapshot 경로")
        if self.holding_days < 0:
            missing.append("holding_days")
        if missing:
            raise IncompleteEntry("청산 항목 작성 거부 — 누락:\n  - " + "\n  - ".join(missing))


@dataclass
class RejectRecord:
    """기각 항목 — 기각 대장(`state/rejections.yaml`) 의 원본."""

    date: date
    theme: str
    path: str  # REJECTION_PATHS
    axis_verdicts: dict[str, str]
    cycle_confidence: float | None  # 산출 안 됐으면 None 을 **명시**
    scoreboard_rank: int
    scan: str
    reason: str
    override_reason: str = ""  # path == human (기계 통과를 사람이 편입 안 함) 이면 필수
    thesis: dict[str, Any] | None = None
    evidence_refs: dict[str, list[int]] = field(default_factory=dict)  # 축별 근거 id
    links: list[str] = field(default_factory=list)
    type: str = field(default="reject", init=False)

    def validate(self) -> None:
        missing: list[str] = []
        if self.path not in REJECTION_PATHS:
            missing.append(f"path ∈ {REJECTION_PATHS}")
        if sorted(self.axis_verdicts) != sorted(AXES) or any(
            v not in AXIS_VERDICTS for v in self.axis_verdicts.values()
        ):
            missing.append(f"axis_verdicts 5축 {AXES} 각각 ∈ {AXIS_VERDICTS}")
        if self.cycle_confidence is not None and not (0.0 <= self.cycle_confidence <= 1.0):
            missing.append("cycle_confidence ∈ [0,1] 또는 None")
        if self.scoreboard_rank <= 0:
            missing.append("scoreboard_rank (양의 정수)")
        if _blank(self.scan):
            missing.append("scan — state/scans/<date>/ 경로")
        if _blank(self.reason):
            missing.append("reason")
        if self.path == "human" and _blank(self.override_reason):
            missing.append("override_reason — 기계가 통과시킨 것을 사람이 편입하지 않은 이유")
        if self.thesis is not None:
            try:
                validate_thesis(self.thesis)
            except ThesisInvalid as e:
                missing.append(str(e))
        if missing:
            raise IncompleteEntry("기각 항목 작성 거부 — 누락:\n  - " + "\n  - ".join(missing))


JournalRecord = EntryRecord | CheckRecord | AddRecord | TpRecord | ExitRecord | RejectRecord


# ---------------------------------------------------------------------------
# 렌더링
# ---------------------------------------------------------------------------


def _plain(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return _plain(asdict(obj))
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_plain(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def _yaml(obj: Any) -> str:
    return yaml.safe_dump(
        _plain(obj), allow_unicode=True, sort_keys=False, default_flow_style=False
    )


def _front_matter(rec: JournalRecord, extra: dict[str, Any]) -> str:
    d = _plain(rec)
    d.pop("thesis", None)  # 스냅샷은 .thesis.yaml 로 — 본문에는 전문을 싣는다
    d.update(extra)
    return "---\n" + _yaml(d) + "---\n"


def _stock_table(stocks: list[StockPlan]) -> list[str]:
    lines = [
        "| 종목 | 역할 | 목표 | 1단 | 2단 | 3단 | Tier2 | 초기가 대비 | 시간스탑 "
        "| TP1 | TP2 | 러너 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in stocks:
        lp = s.ladder_prices
        lw = s.ladder_weights
        lines.append(
            f"| {s.ticker} | {s.role} | {s.target_weight:.1%} | "
            f"{lp[0]:.2f} ({lw[0]:.0%}) | {lp[1]:.2f} ({lw[1]:.0%}) | {lp[2]:.2f} ({lw[2]:.0%}) | "
            f"{s.tier2_stop_price:.2f} | {s.tier2_pct_from_entry:+.1%} | {s.time_stop_date} | "
            f"{s.tp_conditions[0]} | {s.tp_conditions[1]} | {s.tp_conditions[2]} |"
        )
    return lines


def _links(links: list[str]) -> list[str]:
    return ["", "## 관련 항목", *[f"- {x}" for x in links]] if links else []


def render_entry(rec: EntryRecord, thesis_file: str) -> str:
    t = rec.thesis
    bear = rec.bear_case or t.get("bear_case", "")
    fm = _front_matter(
        rec,
        {
            "cycle_confidence": t.get("cycle_confidence"),
            "horizon_months": t.get("horizon_months"),
            "thesis_snapshot": thesis_file,
        },
    )
    body = [
        f"# {rec.theme} · 진입 · {rec.date}",
        "",
        f"- thesis 스냅샷: `{thesis_file}`",
        f"- 스코어보드 스냅샷: `{rec.scan}`",
        f"- cycle_confidence: **{t.get('cycle_confidence')}** (산출: {rec.confidence_provenance})",
        f"- horizon_months: {t.get('horizon_months')}",
        "",
        "## 논지 (thesis 전문)",
        "",
        "```yaml",
        _yaml(t).rstrip(),
        "```",
        "",
        "## bear_case 원문",
        "",
        bear.strip(),
        "",
        "## L1 블록 6개 · L2 tailwind · 가치함정 5축",
        "",
        "| " + " | ".join(BLOCKS) + " | tailwind |",
        "|" + "---|" * 7,
        "| "
        + " | ".join(f"{rec.l1_blocks[b]:.2f}" for b in BLOCKS)
        + f" | {rec.l2_tailwind:+.2f} |",
        "",
        "| " + " | ".join(AXES) + " |",
        "|" + "---|" * 5,
        "| " + " | ".join(rec.axis_verdicts[a] for a in AXES) + " |",
        "",
        "## 매매계획 (종목 · 비중 · 사다리 · 스탑 · TP)",
        "",
        *_stock_table(rec.stocks),
        "",
        "## 기계 권고와 다르게 결정했다면 그 이유",
        "",
        (
            rec.deviation_reason.strip()
            if rec.deviated_from_machine
            else "이탈 없음 — 기계 권고대로"
        ),
    ]
    if rec.notes.strip():
        body += ["", "## 비고", "", rec.notes.strip()]
    body += _links(rec.links)
    body += ["", "> 측정값과 명시된 가정이다. 투자 조언이 아니며 집행은 사람이 한다."]
    return fm + "\n".join(body) + "\n"


def render_check(rec: CheckRecord, thesis_file: str | None, diff_text: str | None) -> str:
    fm = _front_matter(rec, {"thesis_snapshot": thesis_file} if thesis_file else {})
    body = [f"# {rec.theme} · 점검 ({rec.cadence}) · {rec.date}", ""]
    if rec.check_report:
        body.append(f"- 점검 리포트: `{rec.check_report}`")
    body += ["", "## 트리거 상태", "", "| observable | 이전 | 현재 |", "|---|---|---|"]
    body += [
        f"| {s.observable} | {s.before} | {s.after}{' ◀ 변화' if s.before != s.after else ''} |"
        for s in rec.trigger_status
    ]
    body += ["", "## 무효화 상태", "", "| observable | 이전 | 현재 |", "|---|---|---|"]
    body += [
        f"| {s.observable} | {s.before} | {s.after}{' ◀ 변화' if s.before != s.after else ''} |"
        for s in rec.invalidation_status
    ]
    if diff_text is not None:
        body += ["", "## thesis 재실행 diff (논지 표류 추적)", "", "```", diff_text, "```"]
    if rec.notes.strip():
        body += ["", "## 비고", "", rec.notes.strip()]
    body += _links(rec.links)
    return fm + "\n".join(body) + "\n"


def _fills(fills: list[Fill]) -> list[str]:
    return ["| 종목 | 가격 | 수량 |", "|---|---|---|"] + [
        f"| {f.ticker} | {f.price:.2f} | {'' if f.shares is None else f.shares} |" for f in fills
    ]


def render_add(rec: AddRecord) -> str:
    body = [
        f"# {rec.theme} · 사다리 {rec.step}단 · {rec.date}",
        "",
        f"- 가격 조건: 초기가 대비 {rec.price_move_from_entry:+.1%}",
        f"- 논지 조건: 무효화 {rec.invalidations_fired}건 · "
        f"트리거 {rec.triggers_met}/{rec.triggers_total}",
        "",
        *_fills(rec.fills),
        "",
        "## 그때의 판단",
        "",
        rec.judgment.strip(),
    ]
    if rec.override_reason.strip():
        body += [
            "",
            "## 규칙 이탈 사유 (무효화 발동 중 추가 매수)",
            "",
            rec.override_reason.strip(),
        ]
    body += _links(rec.links)
    return _front_matter(rec, {}) + "\n".join(body) + "\n"


def render_tp(rec: TpRecord) -> str:
    body = [
        f"# {rec.theme} · {rec.level.upper()} · {rec.date}",
        "",
        f"- 충족 조건: {rec.condition_met}",
    ]
    if rec.new_tier2_stop_price is not None:
        body.append(f"- Tier-2 스탑 → {rec.new_tier2_stop_price:.2f} (본전 상향, 07 §5)")
    body += ["", *_fills(rec.fills), "", "## 판단", "", rec.judgment.strip()]
    body += _links(rec.links)
    return _front_matter(rec, {}) + "\n".join(body) + "\n"


def render_exit(rec: ExitRecord) -> str:
    rate = rec.triggers_met / rec.triggers_total if rec.triggers_total else float("nan")
    body = [
        f"# {rec.theme} · 청산 · {rec.date}",
        "",
        f"- 청산 경로: **{rec.exit_via}**",
        f"- 실현 수익률: {rec.realized_return:+.1%} · 보유 {rec.holding_days}일",
        f"- 트리거 충족률: {rec.triggers_met}/{rec.triggers_total} ({rate:.0%}) · "
        f"무효화 발동 {rec.invalidations_fired}건 · horizon 경과 {rec.horizon_elapsed}",
        f"- cycle_confidence: {rec.cycle_confidence} ({rec.confidence_provenance})",
        f"- 진입 항목: `{rec.entry_journal}` · thesis: `{rec.thesis_snapshot}`",
        "",
        "## 메커니즘 실측 대조 (맞았어도 다른 이유로 맞았을 수 있다)",
        "",
        rec.mechanism_assessment.strip(),
        "",
        "## cycle_confidence 사후 평가 (→ docs/10 §4 캘리브레이션 입력)",
        "",
        rec.confidence_assessment.strip(),
    ]
    if rec.notes.strip():
        body += ["", "## 비고", "", rec.notes.strip()]
    body += _links(rec.links)
    return _front_matter(rec, {}) + "\n".join(body) + "\n"


def render_reject(rec: RejectRecord, thesis_file: str | None) -> str:
    fm = _front_matter(rec, {"thesis_snapshot": thesis_file} if thesis_file else {})
    body = [
        f"# {rec.theme} · 기각 · {rec.date}",
        "",
        f"- 기각 경로: **{rec.path}** (정본: docs/10 §5 표 · enum: thesis.schema gate_result.path)",
        f"- 스코어보드 순위: {rec.scoreboard_rank} · 스냅샷 `{rec.scan}`",
        "- cycle_confidence: "
        f"{'산출되지 않음' if rec.cycle_confidence is None else rec.cycle_confidence}",
        "",
        "## 가치함정 5축 판정",
        "",
        "| 축 | 판정 | evidence_refs |",
        "|---|---|---|",
        *[f"| {a} | {rec.axis_verdicts[a]} | {rec.evidence_refs.get(a, [])} |" for a in AXES],
        "",
        "## 기각 사유",
        "",
        rec.reason.strip(),
    ]
    if rec.override_reason.strip():
        body += [
            "",
            "## 기계가 통과시킨 것을 사람이 편입하지 않은 이유",
            "",
            rec.override_reason.strip(),
        ]
    body += [
        "",
        "> 이후 12·24개월 수익률은 여기에 쓰지 않는다 — `state/rejections.yaml` 이 "
        "기계적으로 채운다.",
    ]
    body += _links(rec.links)
    return fm + "\n".join(body) + "\n"


# ---------------------------------------------------------------------------
# 쓰기
# ---------------------------------------------------------------------------


def _type_tag(rec: JournalRecord) -> str:
    if isinstance(rec, AddRecord):
        return f"add{rec.step}"
    if isinstance(rec, TpRecord):
        return rec.level
    return rec.type


def entry_filename(rec: JournalRecord, suffix: str = "") -> str:
    theme = re.sub(r"[^a-z0-9_\-]", "_", rec.theme.lower())
    return f"{rec.date.isoformat()}-{theme}-{_type_tag(rec)}{('-' + suffix) if suffix else ''}.md"


@dataclass(frozen=True)
class Written:
    markdown: Path
    thesis_snapshot: Path | None
    diff_text: str | None = None


def list_snapshots(jdir: Path, theme: str) -> list[Path]:
    """테마의 thesis 스냅샷을 날짜 순으로 (파일명 앞의 날짜로 정렬)."""
    theme_tag = re.sub(r"[^a-z0-9_\-]", "_", theme.lower())
    return sorted(jdir.glob(f"*-{theme_tag}-*.thesis.yaml"))


def load_snapshot(path: Path) -> dict[str, Any]:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(d, dict):
        raise ThesisInvalid(f"{path}: thesis 스냅샷이 dict 가 아니다")
    return d


def write_record(rec: JournalRecord, jdir: Path, *, suffix: str = "") -> Written:
    """검증 → (스냅샷) → 마크다운. 기존 파일은 절대 덮어쓰지 않는다."""
    rec.validate()
    jdir.mkdir(parents=True, exist_ok=True)
    md_path = jdir / entry_filename(rec, suffix)
    if md_path.exists():
        raise JournalImmutable(
            f"{md_path.name} 이 이미 있다. 저널은 append-only 다 — "
            "suffix 를 주어 새 항목으로 추가하고 "
            "이전 항목을 links 에 적어라."
        )
    thesis_obj: dict[str, Any] | None = getattr(rec, "thesis", None)
    snap_path: Path | None = None
    diff_text: str | None = None
    if thesis_obj is not None:
        snap_path = md_path.with_suffix("").with_suffix(".thesis.yaml")
        if snap_path.exists():
            raise JournalImmutable(f"{snap_path.name} 이 이미 있다 (append-only).")
        prev = list_snapshots(jdir, rec.theme)
        if prev and not isinstance(rec, EntryRecord):
            old = load_snapshot(prev[-1])
            diff_text = render_diff(
                diff_thesis(old, thesis_obj), old_label=prev[-1].name, new_label=snap_path.name
            )
    snap_name = snap_path.name if snap_path else None
    if isinstance(rec, EntryRecord):
        text = render_entry(rec, snap_name or "")
    elif isinstance(rec, CheckRecord):
        text = render_check(rec, snap_name, diff_text)
    elif isinstance(rec, AddRecord):
        text = render_add(rec)
    elif isinstance(rec, TpRecord):
        text = render_tp(rec)
    elif isinstance(rec, ExitRecord):
        text = render_exit(rec)
    else:
        text = render_reject(rec, snap_name)
    if snap_path is not None and thesis_obj is not None:
        snap_path.write_text(_yaml(thesis_obj), encoding="utf-8")
    md_path.write_text(text, encoding="utf-8")
    return Written(markdown=md_path, thesis_snapshot=snap_path, diff_text=diff_text)


# ---------------------------------------------------------------------------
# 읽기 — front matter
# ---------------------------------------------------------------------------

_FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def read_front_matter(path: Path) -> dict[str, Any]:
    m = _FM.match(path.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"{path}: front matter 없음")
    d = yaml.safe_load(m.group(1))
    if not isinstance(d, dict):
        raise ValueError(f"{path}: front matter 가 dict 가 아니다")
    d["_path"] = str(path)
    return d


def load_entries(jdir: Path, type_: str | None = None) -> list[dict[str, Any]]:
    """저널 항목의 front matter 를 날짜 순으로. `type_` 로 거른다."""
    out: list[dict[str, Any]] = []
    for p in sorted(jdir.glob("*.md")):
        if p.name.upper().startswith("README"):
            continue
        try:
            fm = read_front_matter(p)
        except ValueError:
            continue
        if type_ is None or fm.get("type") == type_:
            out.append(fm)
    return out


# ---------------------------------------------------------------------------
# thesis 재실행 diff (CLI: msa journal diff <theme>)
# ---------------------------------------------------------------------------


def thesis_drift(jdir: Path, theme: str) -> str:
    snaps = list_snapshots(jdir, theme)
    if len(snaps) < 2:
        return f"{theme}: thesis 스냅샷이 {len(snaps)}개뿐이라 diff 할 쌍이 없다"
    old, new = snaps[-2], snaps[-1]
    return render_diff(
        diff_thesis(load_snapshot(old), load_snapshot(new)), old_label=old.name, new_label=new.name
    )


# ---------------------------------------------------------------------------
# append-only 강제 (git)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    path: str
    status: str  # M(수정) D(삭제) R(이름변경) T(형식변경) 등 git 상태 코드

    def render(self) -> str:
        label = {"M": "수정", "D": "삭제", "R": "이름 변경", "T": "형식 변경"}.get(
            self.status[0], "변경"
        )
        return f"{label} [{self.status}] {self.path}"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패: {r.stderr.strip()}")
    return r.stdout


def verify_append_only(
    repo: Path, *, rel: str = JOURNAL_DIRNAME, staged_only: bool = False
) -> list[Violation]:
    """HEAD 에 커밋된 `journal/` 파일이 바뀌었거나 지워졌으면 위반 목록을 돌려준다.

    새 파일(untracked · 새로 add)은 위반이 아니다. `staged_only` 면 인덱스만 본다(pre-commit 용).
    HEAD 가 없는 빈 저장소면 위반 없음.
    """
    if not (repo / ".git").exists():
        raise RuntimeError(f"{repo} 는 git 저장소가 아니다")
    has_head = (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )
    if not has_head:
        return []
    args = ["diff", "--name-status", "--no-renames", "-M0"]
    args += ["--cached", "HEAD", "--", rel] if staged_only else ["HEAD", "--", rel]
    out = _git(repo, *args)
    violations: list[Violation] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        if status.startswith("A"):
            continue
        violations.append(Violation(path=path.strip(), status=status.strip()))
    return violations


PRECOMMIT_SCRIPT = """#!/usr/bin/env sh
# journal/ append-only 검사 (CLAUDE.md §6).
# 기존 저널 파일의 수정·삭제가 스테이징돼 있으면 커밋을 막는다.
# 설치: `msa journal install-hook` (또는 이 파일을 .git/hooks/pre-commit 에서 호출)
set -e
cd "$(git rev-parse --show-toplevel)"
if command -v uv >/dev/null 2>&1; then
  uv run msa journal verify --staged
else
  python -m msa.cli journal verify --staged
fi
"""


def install_hook(repo: Path, *, force: bool = False) -> Path:
    """`.git/hooks/pre-commit` 에 저널 검사를 건다. 이미 있으면 `force` 없이는 건드리지 않는다."""
    hooks = repo / ".git" / "hooks"
    if not hooks.is_dir():
        # worktree 인 경우 .git 은 파일이다 — 공용 훅 디렉터리를 찾는다
        git_dir = _git(repo, "rev-parse", "--git-common-dir").strip()
        hooks = (repo / git_dir).resolve() / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / "pre-commit"
    if target.exists() and not force:
        raise FileExistsError(
            f"{target} 이 이미 있다. --force 로 덮어쓰거나 "
            "직접 scripts/journal-precommit.sh 를 호출해라"
        )
    target.write_text(
        "#!/usr/bin/env sh\n"
        'exec "$(git rev-parse --show-toplevel)/scripts/journal-precommit.sh" "$@"\n'
    )
    target.chmod(0o755)
    return target


# ---------------------------------------------------------------------------
# YAML 입력 → 레코드 (CLI `msa journal new --from file.yaml`)
# ---------------------------------------------------------------------------


def _date(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def record_from_dict(d: dict[str, Any]) -> JournalRecord:
    """YAML 한 덩어리 → 레코드. `type` 키로 분기. 필드가 모자라면 dataclass 생성 자체가 실패한다."""
    t = d.get("type")
    body = {k: v for k, v in d.items() if k != "type"}
    body["date"] = _date(body["date"])
    try:
        if t == "entry":
            stocks = [
                StockPlan(**{**s, "time_stop_date": _date(s["time_stop_date"])})
                for s in body.pop("stocks", [])
            ]
            return EntryRecord(stocks=stocks, **body)
        if t == "check":
            body["trigger_status"] = [StatusChange(**x) for x in body.pop("trigger_status", [])]
            body["invalidation_status"] = [
                StatusChange(**x) for x in body.pop("invalidation_status", [])
            ]
            return CheckRecord(**body)
        if t == "add":
            body["fills"] = [Fill(**x) for x in body.pop("fills", [])]
            return AddRecord(**body)
        if t == "tp":
            body["fills"] = [Fill(**x) for x in body.pop("fills", [])]
            return TpRecord(**body)
        if t == "exit":
            return ExitRecord(**body)
        if t == "reject":
            return RejectRecord(**body)
    except TypeError as e:
        raise IncompleteEntry(f"{t} 항목 필드 오류: {e}") from e
    raise IncompleteEntry(f"type 은 {ENTRY_TYPES} 중 하나여야 한다: {t!r}")


TEMPLATES: dict[str, str] = {
    "entry": """type: entry
date: 2026-09-01
theme: uranium
confidence_provenance: human        # human | referee
scan: state/scans/2026-08-31/
l1_blocks: {A: 0.0, B: 0.0, C: 0.0, D: 0.0, E: 0.0, F: 0.0}
l2_tailwind: 0.0
axis_verdicts:
  {unit_demand: cycle, capital_cycle: cycle, substitution: cycle, cost_curve: cycle,
   terminal_risk: warning}
deviated_from_machine: false
deviation_reason: ""                # deviated_from_machine 이면 필수
bear_case: ""                       # 비면 thesis.bear_case 를 쓴다
stocks:
  - ticker: CCJ
    role: anchor
    target_weight: 0.16
    ladder_prices: [0.0, 0.0, 0.0]
    ladder_weights: [0.5, 0.3, 0.2]
    tier2_stop_price: 0.0
    tier2_pct_from_entry: -0.405
    time_stop_date: 2028-03-01
    tp_conditions:
      ["밸류 P50 회복 또는 +2R", "P75 또는 직전 고점 50% 회복", "트레일 −25% 또는 10주선 이탈"]
    tp_prices: [null, null, null]
thesis: {}                          # docs/specs/thesis.schema.yaml 전문
links: []
notes: ""
""",
    "check": """type: check
date: 2026-10-06
theme: uranium
cadence: weekly
check_report: state/checks/2026-10-06/report.txt
trigger_status:
  - {observable: "...", before: pending, after: pending}
invalidation_status:
  - {observable: "...", before: pending, after: pending}
thesis: null                        # 재실행했으면 전문 — 스냅샷 + diff 가 남는다
notes: ""
links: []
""",
    "add": """type: add
date: 2026-11-03
theme: uranium
step: 2
fills: [{ticker: CCJ, price: 0.0, shares: null}]
price_move_from_entry: -0.132
invalidations_fired: 0
triggers_met: 1
triggers_total: 3
judgment: "..."
override_reason: ""
links: []
""",
    "tp": """type: tp
date: 2027-03-02
theme: uranium
level: tp1                          # tp1 | tp2 | runner
fills: [{ticker: CCJ, price: 0.0, shares: null}]
condition_met: "..."
judgment: "..."
new_tier2_stop_price: 0.0           # tp1 이면 필수 (본전 상향)
links: []
""",
    "exit": """type: exit
date: 2027-06-01
theme: uranium
exit_via: tier1                     # tier1 | tier2 | time_stop | tp_complete | human
realized_return: 0.0
holding_days: 0
triggers_met: 0
triggers_total: 3
invalidations_fired: 0
horizon_elapsed: false
mechanism_assessment: "..."
confidence_assessment: "..."
cycle_confidence: 0.0
confidence_provenance: human
entry_journal: journal/2026-09-01-uranium-entry.md
thesis_snapshot: journal/2026-09-01-uranium-entry.thesis.yaml
notes: ""
links: []
""",
    "reject": """type: reject
date: 2026-08-03
theme: offshore_drilling
path: hard_gate                     # hard_gate | conf_floor | secular_risk | rank_cutoff | human
axis_verdicts:
  {unit_demand: death, capital_cycle: cycle, substitution: warning, cost_curve: cycle,
   terminal_risk: warning}
cycle_confidence: null              # 산출 안 됐으면 null 을 명시
scoreboard_rank: 3
scan: state/scans/2026-08-03/
reason: "..."
override_reason: ""                 # path == human 이면 필수
evidence_refs: {}
thesis: null
links: []
""",
}
