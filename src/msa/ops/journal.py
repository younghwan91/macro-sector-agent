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
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal, get_args

import yaml

from msa.config import JOURNAL_DIRNAME, REPO_ROOT
from msa.dates import parse_date
from msa.errors import Immutable, RefusedInput
from msa.io import to_plain, yaml_text
from msa.ops.state_files import ROLES, TP_LEVELS
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

BLOCKS = ("A", "B", "C", "D", "E", "F")
ENTRY_TYPES = ("entry", "check", "add", "tp", "exit", "reject")
# 열거형은 `Literal` 에 한 번 적고 런타임 검사는 `get_args` 로 같은 값을 본다 (역할·TP 단계는
# `state_files` 의 것을 쓴다; thesis 열거형은 `msa.thesis` 가 소유하고 `ops.thesis` 가 재수출한다).
ExitVia = Literal["tier1", "tier2", "time_stop", "tp_complete", "human"]
CheckCadence = Literal["weekly", "monthly", "daily"]
LadderStepNo = Literal[2, 3]
EXIT_VIAS: tuple[str, ...] = get_args(ExitVia)
CHECK_CADENCES: tuple[str, ...] = get_args(CheckCadence)
LADDER_STEPS: tuple[int, ...] = get_args(LadderStepNo)

#: libyaml 이 있으면 C 로더 — 평문 로더와 결과가 같다 (템플릿·스냅샷·front matter 로 대조했다).
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _yaml_load(text: str) -> Any:
    return yaml.load(text, Loader=_Loader)  # SafeLoader 계열만 고른다


class IncompleteEntry(RefusedInput, ValueError):
    """필수 필드가 비어 작성이 거부됐다. 어떤 필드인지 전부 나열한다."""


class JournalImmutable(Immutable, RuntimeError):
    """기존 파일을 덮어쓰려 했다 — 생각이 바뀌면 새 항목을 추가하고 링크한다."""


def journal_dir(root: Path | None = None) -> Path:
    return (root or REPO_ROOT) / JOURNAL_DIRNAME


# ---------------------------------------------------------------------------
# 항목 dataclass — 각자 validate() 가 누락 필드 목록을 돌려준다
# ---------------------------------------------------------------------------


def _blank(s: str | None) -> bool:
    return s is None or not str(s).strip()


def _reject(label: str, missing: list[str]) -> None:
    """누락이 하나라도 있으면 전부 나열해 거부한다 — 한 번에 고치게."""
    if missing:
        raise IncompleteEntry(f"{label} 항목 작성 거부 — 누락:\n  - " + "\n  - ".join(missing))


def _axis_problems(verdicts: dict[str, str]) -> list[str]:
    """5축 전부 있고 각 판정이 enum 안인가 (진입·기각 공통)."""
    if sorted(verdicts) != sorted(AXES) or any(v not in AXIS_VERDICTS for v in verdicts.values()):
        return [f"axis_verdicts 5축 {AXES} 각각 ∈ {AXIS_VERDICTS}"]
    return []


def _thesis_problems(thesis: dict[str, Any] | None) -> list[str]:
    """thesis 가 있으면 운영 최소 검증 — 위반 문구를 누락 목록에 그대로 싣는다."""
    if thesis is None:
        return []
    try:
        validate_thesis(thesis)
    except ThesisInvalid as e:
        return [str(e)]
    return []


def _theme_tag(theme: str) -> str:
    """파일명용 테마 토큰 — 소문자·영숫자·`_`·`-` 외는 `_`."""
    return re.sub(r"[^a-z0-9_\-]", "_", theme.lower())


class _Record:
    """여섯 항목의 공통 면 — 파일명 태그 · front matter · 렌더/검증 인터페이스.

    각 dataclass 가 `type` 을 `init=False` 필드로 고정한다. 렌더는 항목마다 다르므로 여기서는 모양만
    정한다: `render(thesis_file=, diff_text=)` 는 쓰지 않는 인자를 무시한다.
    """

    type: str
    date: date
    theme: str
    links: list[str]

    @property
    def tag(self) -> str:
        """파일명의 종류 토큰 — 기본은 `type` (사다리는 `add2`, TP 는 `tp1` 처럼 덮어쓴다)."""
        return self.type

    def validate(self) -> None:
        raise NotImplementedError

    def render(self, *, thesis_file: str | None = None, diff_text: str | None = None) -> str:
        raise NotImplementedError

    def _front_matter(self, extra: dict[str, Any]) -> str:
        d = to_plain(self)
        d.pop("thesis", None)  # 스냅샷은 .thesis.yaml 로 — 본문에는 전문을 싣는다
        d.update(extra)
        return "---\n" + yaml_text(d) + "---\n"

    def _links(self) -> list[str]:
        return ["", "## 관련 항목", *[f"- {x}" for x in self.links]] if self.links else []


def _notes(notes: str) -> list[str]:
    return ["", "## 비고", "", notes.strip()] if notes.strip() else []


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
        if self.role not in ROLES:
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
class EntryRecord(_Record):
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
        missing = _thesis_problems(self.thesis)
        if self.confidence_provenance not in CONFIDENCE_PROVENANCE:
            missing.append(f"confidence_provenance ∈ {CONFIDENCE_PROVENANCE} (누가 c 를 산출했나)")
        if sorted(self.l1_blocks) != list(BLOCKS):
            missing.append(f"l1_blocks 는 {BLOCKS} 6개 값 (있는 것: {sorted(self.l1_blocks)})")
        missing += _axis_problems(self.axis_verdicts)
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
        _reject("진입", missing)

    def render(self, *, thesis_file: str | None = None, diff_text: str | None = None) -> str:
        t = self.thesis
        bear = self.bear_case or t.get("bear_case", "")
        snap = thesis_file or ""
        fm = self._front_matter(
            {
                "cycle_confidence": t.get("cycle_confidence"),
                "horizon_months": t.get("horizon_months"),
                "thesis_snapshot": snap,
            }
        )
        body = [
            f"# {self.theme} · 진입 · {self.date}",
            "",
            f"- thesis 스냅샷: `{snap}`",
            f"- 스코어보드 스냅샷: `{self.scan}`",
            f"- cycle_confidence: **{t.get('cycle_confidence')}** "
            f"(산출: {self.confidence_provenance})",
            f"- horizon_months: {t.get('horizon_months')}",
            "",
            "## 논지 (thesis 전문)",
            "",
            "```yaml",
            yaml_text(t).rstrip(),
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
            + " | ".join(f"{self.l1_blocks[b]:.2f}" for b in BLOCKS)
            + f" | {self.l2_tailwind:+.2f} |",
            "",
            "| " + " | ".join(AXES) + " |",
            "|" + "---|" * 5,
            "| " + " | ".join(self.axis_verdicts[a] for a in AXES) + " |",
            "",
            "## 매매계획 (종목 · 비중 · 사다리 · 스탑 · TP)",
            "",
            *_stock_table(self.stocks),
            "",
            "## 기계 권고와 다르게 결정했다면 그 이유",
            "",
            (
                self.deviation_reason.strip()
                if self.deviated_from_machine
                else "이탈 없음 — 기계 권고대로"
            ),
            *_notes(self.notes),
            *self._links(),
            "",
            "> 측정값과 명시된 가정이다. 투자 조언이 아니며 집행은 사람이 한다.",
        ]
        return fm + "\n".join(body) + "\n"


@dataclass
class StatusChange:
    observable: str
    before: str
    after: str

    def row(self) -> str:
        mark = " ◀ 변화" if self.before != self.after else ""
        return f"| {self.observable} | {self.before} | {self.after}{mark} |"


def _status_table(title: str, rows: list[StatusChange]) -> list[str]:
    return ["", f"## {title}", "", "| observable | 이전 | 현재 |", "|---|---|---|"] + [
        r.row() for r in rows
    ]


@dataclass
class CheckRecord(_Record):
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
        if self.cadence not in CHECK_CADENCES:
            missing.append("cadence ∈ {weekly, monthly, daily}")
        if not self.trigger_status:
            missing.append("trigger_status — 각 trigger 의 상태 (변화 없어도 적는다)")
        if not self.invalidation_status:
            missing.append("invalidation_status — 각 invalidation 의 상태")
        missing += _thesis_problems(self.thesis)
        _reject("점검", missing)

    def render(self, *, thesis_file: str | None = None, diff_text: str | None = None) -> str:
        fm = self._front_matter({"thesis_snapshot": thesis_file} if thesis_file else {})
        body = [f"# {self.theme} · 점검 ({self.cadence}) · {self.date}", ""]
        if self.check_report:
            body.append(f"- 점검 리포트: `{self.check_report}`")
        body += _status_table("트리거 상태", self.trigger_status)
        body += _status_table("무효화 상태", self.invalidation_status)
        if diff_text is not None:
            body += ["", "## thesis 재실행 diff (논지 표류 추적)", "", "```", diff_text, "```"]
        body += _notes(self.notes)
        body += self._links()
        return fm + "\n".join(body) + "\n"


@dataclass
class Fill:
    ticker: str
    price: float
    shares: float | None = None


@dataclass
class AddRecord(_Record):
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

    @property
    def tag(self) -> str:
        return f"add{self.step}"

    def validate(self) -> None:
        missing: list[str] = []
        if self.step not in LADDER_STEPS:
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
        _reject("사다리", missing)

    def render(self, *, thesis_file: str | None = None, diff_text: str | None = None) -> str:
        body = [
            f"# {self.theme} · 사다리 {self.step}단 · {self.date}",
            "",
            f"- 가격 조건: 초기가 대비 {self.price_move_from_entry:+.1%}",
            f"- 논지 조건: 무효화 {self.invalidations_fired}건 · "
            f"트리거 {self.triggers_met}/{self.triggers_total}",
            "",
            *_fills(self.fills),
            "",
            "## 그때의 판단",
            "",
            self.judgment.strip(),
        ]
        if self.override_reason.strip():
            body += [
                "",
                "## 규칙 이탈 사유 (무효화 발동 중 추가 매수)",
                "",
                self.override_reason.strip(),
            ]
        body += self._links()
        return self._front_matter({}) + "\n".join(body) + "\n"


@dataclass
class TpRecord(_Record):
    date: date
    theme: str
    level: str  # tp1 | tp2 | runner
    fills: list[Fill]
    condition_met: str  # 어떤 조건이 충족됐나 (측정값)
    judgment: str
    new_tier2_stop_price: float | None = None  # tp1 이면 필수 — 본전으로 상향 (07 §5)
    links: list[str] = field(default_factory=list)
    type: str = field(default="tp", init=False)

    @property
    def tag(self) -> str:
        return self.level

    def validate(self) -> None:
        missing: list[str] = []
        if self.level not in TP_LEVELS:
            missing.append("level ∈ {tp1, tp2, runner}")
        if not self.fills:
            missing.append("fills")
        if _blank(self.condition_met):
            missing.append("condition_met")
        if _blank(self.judgment):
            missing.append("judgment")
        if self.level == "tp1" and self.new_tier2_stop_price is None:
            missing.append("new_tier2_stop_price — TP1 체결 후 Tier-2 스탑을 본전으로 상향 (07 §5)")
        _reject("TP", missing)

    def render(self, *, thesis_file: str | None = None, diff_text: str | None = None) -> str:
        body = [
            f"# {self.theme} · {self.level.upper()} · {self.date}",
            "",
            f"- 충족 조건: {self.condition_met}",
        ]
        if self.new_tier2_stop_price is not None:
            body.append(f"- Tier-2 스탑 → {self.new_tier2_stop_price:.2f} (본전 상향, 07 §5)")
        body += ["", *_fills(self.fills), "", "## 판단", "", self.judgment.strip()]
        body += self._links()
        return self._front_matter({}) + "\n".join(body) + "\n"


@dataclass
class ExitRecord(_Record):
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
        if self.exit_via not in EXIT_VIAS:
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
        _reject("청산", missing)

    def render(self, *, thesis_file: str | None = None, diff_text: str | None = None) -> str:
        rate = self.triggers_met / self.triggers_total if self.triggers_total else float("nan")
        body = [
            f"# {self.theme} · 청산 · {self.date}",
            "",
            f"- 청산 경로: **{self.exit_via}**",
            f"- 실현 수익률: {self.realized_return:+.1%} · 보유 {self.holding_days}일",
            f"- 트리거 충족률: {self.triggers_met}/{self.triggers_total} ({rate:.0%}) · "
            f"무효화 발동 {self.invalidations_fired}건 · horizon 경과 {self.horizon_elapsed}",
            f"- cycle_confidence: {self.cycle_confidence} ({self.confidence_provenance})",
            f"- 진입 항목: `{self.entry_journal}` · thesis: `{self.thesis_snapshot}`",
            "",
            "## 메커니즘 실측 대조 (맞았어도 다른 이유로 맞았을 수 있다)",
            "",
            self.mechanism_assessment.strip(),
            "",
            "## cycle_confidence 사후 평가 (→ docs/10 §4 캘리브레이션 입력)",
            "",
            self.confidence_assessment.strip(),
            *_notes(self.notes),
            *self._links(),
        ]
        return self._front_matter({}) + "\n".join(body) + "\n"


@dataclass
class RejectRecord(_Record):
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
        missing += _axis_problems(self.axis_verdicts)
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
        missing += _thesis_problems(self.thesis)
        _reject("기각", missing)

    def render(self, *, thesis_file: str | None = None, diff_text: str | None = None) -> str:
        fm = self._front_matter({"thesis_snapshot": thesis_file} if thesis_file else {})
        c = "산출되지 않음" if self.cycle_confidence is None else self.cycle_confidence
        body = [
            f"# {self.theme} · 기각 · {self.date}",
            "",
            f"- 기각 경로: **{self.path}** "
            "(정본: docs/10 §5 표 · enum: thesis.schema gate_result.path)",
            f"- 스코어보드 순위: {self.scoreboard_rank} · 스냅샷 `{self.scan}`",
            f"- cycle_confidence: {c}",
            "",
            "## 가치함정 5축 판정",
            "",
            "| 축 | 판정 | evidence_refs |",
            "|---|---|---|",
            *[f"| {a} | {self.axis_verdicts[a]} | {self.evidence_refs.get(a, [])} |" for a in AXES],
            "",
            "## 기각 사유",
            "",
            self.reason.strip(),
        ]
        if self.override_reason.strip():
            body += [
                "",
                "## 기계가 통과시킨 것을 사람이 편입하지 않은 이유",
                "",
                self.override_reason.strip(),
            ]
        body += [
            "",
            "> 이후 12·24개월 수익률은 여기에 쓰지 않는다 — `state/rejections.yaml` 이 "
            "기계적으로 채운다.",
        ]
        body += self._links()
        return fm + "\n".join(body) + "\n"


JournalRecord = EntryRecord | CheckRecord | AddRecord | TpRecord | ExitRecord | RejectRecord


# ---------------------------------------------------------------------------
# 렌더링 보조 (표)
# ---------------------------------------------------------------------------


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


def _fills(fills: list[Fill]) -> list[str]:
    return ["| 종목 | 가격 | 수량 |", "|---|---|---|"] + [
        f"| {f.ticker} | {f.price:.2f} | {'' if f.shares is None else f.shares} |" for f in fills
    ]


# ---------------------------------------------------------------------------
# 쓰기
# ---------------------------------------------------------------------------


def entry_filename(rec: JournalRecord, suffix: str = "") -> str:
    tail = f"-{suffix}" if suffix else ""
    return f"{rec.date.isoformat()}-{_theme_tag(rec.theme)}-{rec.tag}{tail}.md"


@dataclass(frozen=True)
class Written:
    markdown: Path
    thesis_snapshot: Path | None
    diff_text: str | None = None


def list_snapshots(jdir: Path, theme: str) -> list[Path]:
    """테마의 thesis 스냅샷을 날짜 순으로 (파일명 앞의 날짜로 정렬)."""
    return sorted(jdir.glob(f"*-{_theme_tag(theme)}-*.thesis.yaml"))


def load_snapshot(path: Path) -> dict[str, Any]:
    d = _yaml_load(path.read_text(encoding="utf-8"))
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
    text = rec.render(thesis_file=snap_path.name if snap_path else None, diff_text=diff_text)
    if snap_path is not None and thesis_obj is not None:
        snap_path.write_text(yaml_text(thesis_obj), encoding="utf-8")
    md_path.write_text(text, encoding="utf-8")
    return Written(markdown=md_path, thesis_snapshot=snap_path, diff_text=diff_text)


# ---------------------------------------------------------------------------
# 읽기 — front matter
# ---------------------------------------------------------------------------

_FENCE = "---\n"


def read_front_matter(path: Path) -> dict[str, Any]:
    """첫 줄 `---` 부터 다음 `---` 줄까지만 읽는다 (본문은 읽지 않는다)."""
    lines: list[str] = []
    with path.open(encoding="utf-8") as fh:
        if fh.readline() != _FENCE:
            raise ValueError(f"{path}: front matter 없음")
        for line in fh:
            if line == _FENCE:
                break
            lines.append(line)
        else:
            raise ValueError(f"{path}: front matter 없음")
    d = _yaml_load("".join(lines))
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


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """`git -C repo …`. `check` 면 0 아닌 종료는 `RuntimeError` — 조용히 빈 출력을 내지 않는다."""
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패: {r.stderr.strip()}")
    return r


def verify_append_only(
    repo: Path, *, rel: str = JOURNAL_DIRNAME, staged_only: bool = False
) -> list[Violation]:
    """HEAD 에 커밋된 `journal/` 파일이 바뀌었거나 지워졌으면 위반 목록을 돌려준다.

    새 파일(untracked · 새로 add)은 위반이 아니다. `staged_only` 면 인덱스만 본다(pre-commit 용).
    HEAD 가 없는 빈 저장소면 위반 없음.
    """
    if not (repo / ".git").exists():
        raise RuntimeError(f"{repo} 는 git 저장소가 아니다")
    if _git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0:
        return []
    args = ["diff", "--name-status", "--no-renames", "-M0"]
    args += ["--cached", "HEAD", "--", rel] if staged_only else ["HEAD", "--", rel]
    violations: list[Violation] = []
    for line in _git(repo, *args).stdout.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        if status.startswith("A"):
            continue
        violations.append(Violation(path=path.strip(), status=status.strip()))
    return violations


def install_hook(repo: Path, *, force: bool = False) -> Path:
    """`.git/hooks/pre-commit` 에 저널 검사를 건다. 이미 있으면 `force` 없이는 건드리지 않는다."""
    hooks = repo / ".git" / "hooks"
    if not hooks.is_dir():
        # worktree 인 경우 .git 은 파일이다 — 공용 훅 디렉터리를 찾는다
        git_dir = _git(repo, "rev-parse", "--git-common-dir").stdout.strip()
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
    return v if isinstance(v, date) else parse_date(str(v))


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
