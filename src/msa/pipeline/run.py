"""케이던스 오케스트레이터 — `msa run monthly` · `msa run weekly` · `msa run quarterly` (배선 W4).

`docs/09` §1 의 한 줄(월간 = L0 적재 → L1 전수 스캔 → 상위 K L3 → L4 → L5)을
**순서대로 호출**하고, 각 단계의 결과를 `RunReport` 에 `{status, reason, outputs, seconds}` 로
남긴다. 새 계산은 없다 — 각 계층의 진입점(`run_scan`·`run_research`·`ingest_round`·
`run_picks`·`assemble_inputs`·`run_portfolio`·`run_check`)을 그대로 부른다. 임계값도 가중치도
만들지 않는다 (`CLAUDE.md` §1).

## 월간 단계와 실패 규약 (`docs/09` §5)

| 단계 | 호출 | 실패 시 |
|---|---|---|
| `scan` | `run_scan` | **중단** — 데이터·커버리지 관문 실패면 부분 데이터로 진행하지 않는다 |
| | | (`CLAUDE.md` §2). 뒤 단계는 전부 `skipped` |
| `select` | 상위 K **자격**(S2 `eligible`) + 사용자 지정 | 자격 < K 면 적는다 — 채우지 않는다 |
| | | (`docs/02` §7.1 풀 미달 = 관찰) |
| `research` | `none` → 사람 논지/직전 thesis 를 **찾기만** | 테마별 격리 — 스키마 기각은 제외 |
| | `mock`·`fixture`·`anthropic` → 테마별 L3 | 제공자 오류는 보고. 라운드는 계속 |
| `ingest` | `ingest_round` — 새 L3 라운드, 또는 `none`·`--skip-research` 면 | 보고 |
| | 찾은 thesis 를 그 라운드 날짜로 (관찰 목록·기각·초안은 게이트 판정의 산출물이다) | |
| `picks` | 게이트 편입 가능 테마만 `run_picks` | 테마별 격리 |
| `assemble`·`portfolio` | `assemble_inputs` → `run_portfolio(emit_positions=True)` | 0 → skipped; |
| | | **입력 계약 위반은 `failed` + 중단**(exit 1) |
| `report` | `state/runs/<asof>/monthly-report.md` · `run.json` | |

**끝은 제안과 초안이다.** 진입 초안(`journal-draft-*.yaml`)·미체결 제안(`positions-proposal.yaml`)·
관찰 목록 행까지 만들고 멈춘다. 저널 확정·`positions.yaml` 승격·주문은 사람이 한다 (`CLAUDE.md` §8,
`docs/09` §1 "기계 vs 사람"). 자동 주문 기능은 없다.

`write=False` 면 **`state/` 에 아무것도 쓰지 않는다** — 중간 산출물(스캔 스냅샷·thesis·picks·
묶음·포트)은 임시 샌드박스 디렉터리에 쓰고(각 계층이 파일 계약으로 이어지므로 어딘가에는 써야
한다) 끝나면 지운다. 저널·기각 대장·관찰 목록은 `ingest_round(write=False)` 로 판정만 한다.

주간(`run_weekly`) = `run_scan` (전수 스캔이 캐시 덕에 ~12 초라 "경량 갱신" 을 따로 두지 않는다) +
`run_check(mode="weekly")` + 주간 리포트. 분기(`run_quarterly`) 는 두 명령의 목록이다 — 읽는 것은
사람이라 여기서 돌리지 않고 적는다.

L2 거시 단계(`macro`)와 선정의 `hard_exclude` 오버레이는 **2026-08-23 에 제거됐다** (`docs/13` §9 ·
`journal/2026-08-23-l2-removed.md`). 선정은 L1 순위(S2 자격)만으로 한다.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from msa.coerce import opt_int
from msa.config import REPO_ROOT, paths, rel
from msa.dates import parse_date
from msa.errors import ProviderError
from msa.io import write_snapshot
from msa.l1.scan import ScanResult, asof_note, run_scan, scan_dirs
from msa.l3.contracts import InputsError
from msa.l3.contracts import assemble_inputs as l3_assemble_inputs
from msa.l3.pipeline import ResearchResult, run_research
from msa.l3.providers import make_provider
from msa.l3.schema import ThesisRejected
from msa.l4.picks import PicksResult, run_picks
from msa.l5.run import PortfolioResult, run_portfolio
from msa.ops.alerts import deliver
from msa.ops.check import CheckReport, StorePriceSource, run_check
from msa.ops.ingest import IngestReport, ingest_round
from msa.ops.journal import journal_dir
from msa.pipeline.assemble import AssembleError, AssembleResult, assemble_inputs
from msa.thesis import gate_status, read_thesis_yaml, thesis_filename

log = logging.getLogger(__name__)

#: 단계 상태 — 이 넷뿐이다.
STATUSES: tuple[str, ...] = ("ok", "skipped", "unavailable", "failed")

#: 월간 단계 이름 (순서 = 실행 순서 = 리포트 순서).
MONTHLY_STEPS: tuple[str, ...] = (
    "scan",
    "select",
    "research",
    "ingest",
    "picks",
    "assemble",
    "portfolio",
    "report",
)
WEEKLY_STEPS: tuple[str, ...] = ("scan", "check", "report")

#: `msa research` 와 같은 제공자 이름 + `none`(L3 를 부르지 않는다 — 사람 논지/직전 thesis 만
#: 찾는다).
PROVIDERS: tuple[str, ...] = ("none", "claude_code", "mock", "fixture", "anthropic")

#: 분기 작업 — 실행하지 않고 나열한다 (`docs/09` §1 분기 행).
QUARTERLY_COMMANDS: tuple[tuple[str, str], ...] = (
    ("msa ops calibration", "cycle_confidence 캘리브레이션 — N<20 이면 결론 없음 (docs/10 §4)"),
    ("msa ops rejections-update", "기각 대장 r_12m/r_24m 갱신 + 세 질문 (docs/10 §5)"),
)

#: `assemble_inputs` 가 내는 **정상적인 "0건"** 의 표지 (`pipeline/assemble.py` 의 마지막 raise).
#: 같은 `AssembleError` 가 계약 위반(ranking 열 없음 · 사람 논지 디렉터리 없음 · top_per_theme)
#: 에서도 나므로, 이 문구가 없으면 `skipped` 가 아니라 `failed` 다 (`CLAUDE.md` §2).
ASSEMBLE_EMPTY_MARKER = "묶을 테마가 0개다"

#: 리포트 꼬리 — 모든 리포트가 같은 문장으로 끝난다.
TRAILER = (
    "이 리포트는 측정값·제안·초안이다. 집행(저널 확정 · positions.yaml 승격 · 주문)은 사람이 한다 "
    "(CLAUDE.md §8)."
)


class RunError(ValueError):
    """오케스트레이터 인자가 틀렸다 (provider·top_k·asof)."""


# ---------------------------------------------------------------- 보고서


@dataclass
class StepResult:
    """한 단계의 결과 한 줄 — 무엇이 됐고(또는 왜 안 됐고) 무엇을 썼는가."""

    name: str
    status: str  # STATUSES
    reason: str = ""
    outputs: list[str] = field(default_factory=list)
    seconds: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise RunError(f"status ∈ {STATUSES}: {self.status!r}")


@dataclass
class RunReport:
    """한 번의 실행 — 단계 목록 + 사람 몫 TODO + 비고. `render()` 가 마크다운, `as_dict()` 가
    `run.json`."""

    cadence: str  # monthly | weekly
    asof: str
    started_at: str
    write: bool
    state_root: str
    params: dict[str, Any] = field(default_factory=dict)
    steps: list[StepResult] = field(default_factory=list)
    human_todo: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stopped: bool = False  # 경성 실패로 중단됐다 (종료 코드 1)
    stopped_reason: str = ""
    out_dir: str | None = None

    def step(self, name: str) -> StepResult | None:
        for s in self.steps:
            if s.name == name:
                return s
        return None

    def add(self, step: StepResult) -> StepResult:
        self.steps.append(step)
        return step

    def statuses(self) -> dict[str, str]:
        return {s.name: s.status for s in self.steps}

    @property
    def exit_code(self) -> int:
        return 1 if self.stopped else 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "cadence": self.cadence,
            "asof": self.asof,
            "started_at": self.started_at,
            "write": self.write,
            "state_root": self.state_root,
            "params": self.params,
            "stopped": self.stopped,
            "stopped_reason": self.stopped_reason,
            "exit_code": self.exit_code,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "reason": s.reason,
                    "outputs": list(s.outputs),
                    "seconds": round(s.seconds, 3),
                    "details": s.details,
                }
                for s in self.steps
            ],
            "human_todo": list(self.human_todo),
            "notes": list(self.notes),
            "out_dir": self.out_dir,
        }

    def render(self) -> str:
        mode = "" if self.write else " (no-write — state/ 에 쓰지 않았다, 샌드박스)"
        title = {"monthly": "월간 실행", "weekly": "주간 실행"}.get(self.cadence, self.cadence)
        L = [
            f"# {title} · {self.asof}{mode}",
            "",
            f"시작 {self.started_at} · state {self.state_root}"
            + (f" · 중단: {self.stopped_reason}" if self.stopped else ""),
            "",
            "| 단계 | 상태 | 초 | 사유 | 산출물 |",
            "|---|---|---:|---|---|",
        ]
        for s in self.steps:
            outs = "<br>".join(s.outputs) if s.outputs else "—"
            L.append(
                f"| {s.name} | {s.status} | {s.seconds:.1f} | {_md(s.reason) or '—'} | "
                f"{_md(outs)} |"
            )
        for s in self.steps:
            txt = s.details.get("text")
            if txt:
                L += ["", f"## {s.name}", "", "```", str(txt).rstrip(), "```"]
        L += ["", "## 사람이 할 것"]
        L += [f"- {x}" for x in self.human_todo] or ["- (없음)"]
        if self.notes:
            L += ["", "## 비고"] + [f"- {n}" for n in self.notes]
        L += ["", TRAILER, ""]
        return "\n".join(L)


def _md(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------- 테마 선정


@dataclass(frozen=True)
class ThemeSelection:
    """`select_themes` 의 결과 — 무엇을 왜 골랐고 자격 테마가 몇이었는가."""

    top_k: int
    selected: tuple[str, ...]  # 순서 = 스코어보드 순 + 사용자 지정
    from_scoreboard: tuple[str, ...]
    extra: tuple[str, ...]
    n_eligible: int
    n_total: int
    ranks: dict[str, int | None]
    flags: dict[str, tuple[str, ...]]  # 테마 → (SECULAR, 소표본, 풀 미달, 스코어보드에 없음 …)
    notes: tuple[str, ...]
    #: 점수 순으로는 상위 K 였으나 **소표본이라 뒤로 밀려** 선정에서 빠진 테마 → 스코어보드 순위.
    #: 재정렬 자체는 선언된 동작이다 — 사라지는 것을 말없이 두지 않으려고 센다 (`CLAUDE.md` §2).
    demoted: tuple[tuple[str, int | None], ...] = ()

    @property
    def short_of_k(self) -> bool:
        return self.n_eligible < self.top_k

    def as_dict(self) -> dict[str, Any]:
        return {
            "top_k": self.top_k,
            "selected": list(self.selected),
            "from_scoreboard": list(self.from_scoreboard),
            "extra": list(self.extra),
            "n_eligible": self.n_eligible,
            "n_total": self.n_total,
            "short_of_k": self.short_of_k,
            "ranks": dict(self.ranks),
            "flags": {t: list(f) for t, f in self.flags.items()},
            "notes": list(self.notes),
            "demoted_small_sample": [{"theme": t, "rank": r} for t, r in self.demoted],
        }

    def render(self) -> str:
        L = [
            f"상위 K={self.top_k} — 자격(S2 eligible) 테마 {self.n_eligible}/{self.n_total}"
            + (" · K 미만이라 그만큼만 골랐다 (채우지 않는다)" if self.short_of_k else ""),
            f"선정 {len(self.selected)} = 스코어보드 {len(self.from_scoreboard)} "
            f"+ 지정 {len(self.extra)}",
        ]
        for t in self.selected:
            rk = self.ranks.get(t)
            fl = ", ".join(self.flags.get(t, ())) or "—"
            src = "지정" if t in self.extra else "스코어보드"
            L.append(f"  {'—' if rk is None else f'#{rk}':>4}  {t:<28} {src:<8} [{fl}]")
        for t, rk in self.demoted:
            L.append(
                f"  {'—' if rk is None else f'#{rk}':>4}  {t:<28} {'강등':<8} "
                "[소표본 — 점수 순 상위 K 였으나 뒤로 밀려 빠짐]"
            )
        L += [f"  · {n}" for n in self.notes]
        return "\n".join(L)


def _flags(row: pd.Series | None) -> tuple[str, ...]:
    if row is None:
        return ("스코어보드에 없음",)
    f: list[str] = []
    if "eligible" in row.index and not bool(row["eligible"]):
        f.append("풀 미달(관찰)")
    if bool(row.get("small_sample", False)):
        f.append("소표본")
    if bool(row.get("secular", False)):
        f.append("SECULAR — 게이트 필요")
    return tuple(f)


def select_themes(
    scoreboard: pd.DataFrame,
    *,
    top_k: int = 8,
    extra_themes: Sequence[str] = (),
) -> ThemeSelection:
    """스코어보드(`Scoreboard.table` 또는 `scoreboard.csv`) → L3 투입 테마.

    `docs/05` §1 (상위 K=8 + 사용자 지정) 과 `docs/02` §7.1 (S2: 순위는 **자격** 테마에만 있다 —
    풀 미달은 관찰 목록) 을 그대로 적용한다. 자격 테마를 `Scoreboard.top_k` 와 같은 순서(소표본은
    뒤로, 점수 내림차순)로 K 개 고른다. 자격 테마가 K 미만이면 **그만큼만** 고르고 그 사실을
    적는다 — 풀 미달 테마로 채우지 않는다. `extra_themes` 는 자격·순위와 무관하게 붙인다(사용자
    지정) — SECULAR·소표본·풀 미달·스코어보드에 없음 플래그를 같이 적는다. SECULAR 테마는 L3 의
    게이트(`docs/04`)가 다룬다 — 여기서 빼지 않는다. 거시 오버레이는 없다 (L2 제거, 2026-08-23).

    소표본을 뒤로 미는 재정렬 때문에 **스코어보드 순위 상위가 선정에서 빠질 수 있다** (rank 열은
    순수 점수 순이다). 규칙은 그대로 두되 빠진 테마와 사유를 `demoted` 와 `notes` 에 남긴다 —
    말없이 사라지지 않게 (`CLAUDE.md` §2).
    """
    if top_k < 0:
        raise RunError(f"top_k 는 0 이상: {top_k}")
    sb = scoreboard
    if "eligible" in sb.columns:
        elig_mask = sb["eligible"].fillna(False).astype(bool)
    else:  # S2 이전 스코어보드(구 복합) — 점수가 있으면 자격으로 본다. 그 사실을 적는다
        elig_mask = sb["score"].notna()
    if "score" in sb.columns:
        elig_mask &= sb["score"].notna()
    elig = sb.loc[elig_mask].copy()
    if "small_sample" in elig.columns:
        elig["_penal"] = elig["small_sample"].fillna(False).astype(int)
    else:
        elig["_penal"] = 0
    by_score = elig.sort_values("score", ascending=False, kind="mergesort")
    elig = elig.sort_values(["_penal", "score"], ascending=[True, False], kind="mergesort")
    from_sb = tuple(str(t) for t in elig.index[:top_k])
    # 점수만 봤으면 상위 K 였는데 소표본 재정렬로 빠진 테마 — 규칙은 그대로 두고 세어서 남긴다
    demoted_names = [str(t) for t in by_score.index[:top_k] if str(t) not in from_sb]

    extra: list[str] = []
    for t in extra_themes:
        t = str(t).strip()
        if t and t not in from_sb and t not in extra:
            extra.append(t)
    selected = (*from_sb, *extra)

    ranks: dict[str, int | None] = {}
    flags: dict[str, tuple[str, ...]] = {}
    for t in selected:
        row: pd.Series | None = None
        if t in sb.index:
            got = sb.loc[t]
            row = got.iloc[0] if isinstance(got, pd.DataFrame) else got  # 중복 index 방어
        r: int | None = None
        if row is not None and "rank" in row.index and pd.notna(row["rank"]):
            r = int(float(row["rank"]))
        ranks[t] = r
        flags[t] = _flags(row)

    notes: list[str] = []
    n_elig = int(elig_mask.sum())
    if "eligible" not in sb.columns:
        notes.append(
            "스코어보드에 `eligible` 열이 없다 (S2 이전) — 점수가 있는 테마를 자격으로 봤다"
        )
    if n_elig < top_k:
        notes.append(
            f"자격 테마 {n_elig} < K={top_k} — {len(from_sb)} 개만 골랐다. "
            "풀 미달 테마는 관찰 목록이다 (docs/02 §7.1)"
        )
    for t in extra:
        if t not in sb.index:
            notes.append(f"{t}: 스코어보드에 없는 지정 테마 — L3 입력 조립이 거부할 수 있다")

    demoted: list[tuple[str, int | None]] = []
    for t in demoted_names:
        rk_val = opt_int(sb.loc[t, "rank"]) if t in sb.index and "rank" in sb.columns else None
        demoted.append((t, rk_val))
    if demoted:
        who = ", ".join(f"{t}(#{r})" if r is not None else t for t, r in demoted)
        notes.append(
            f"소표본 강등 {len(demoted)} — 점수 순 상위 K 였으나 뒤로 밀려 선정에서 빠졌다: {who}. "
            "소표본을 뒤로 미는 것은 선언된 동작이다 (Scoreboard.top_k 와 같은 순서) — "
            "스코어보드 `rank` 는 순수 점수 순이라 선정 표의 순위가 1 부터 시작하지 않을 수 있다"
        )
    return ThemeSelection(
        top_k=top_k,
        selected=selected,
        from_scoreboard=from_sb,
        extra=tuple(extra),
        n_eligible=n_elig,
        n_total=len(sb),
        ranks=ranks,
        flags=flags,
        notes=tuple(notes),
        demoted=tuple(demoted),
    )


# ---------------------------------------------------------------- thesis 장부


@dataclass
class ThesisRecord:
    """선정 테마 하나의 thesis 상태 — 어디서 왔고(또는 왜 없고) 게이트 편입이 가능한가."""

    theme: str
    source: str  # l3 | l3-prior | human | none
    status: str  # researched | found | absent | rejected_schema | provider_error | failed
    path: str | None = None
    gate_status: str | None = None
    portfolio_eligible: bool | None = None
    reason: str = ""

    @property
    def eligible(self) -> bool:
        return bool(self.portfolio_eligible) and self.path is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "source": self.source,
            "status": self.status,
            "path": self.path,
            "gate_status": self.gate_status,
            "portfolio_eligible": self.portfolio_eligible,
            "reason": self.reason,
        }


def gate_eligible(thesis: Mapping[str, Any]) -> tuple[bool, str | None]:
    """thesis 객체 → (편입 가능, gate status). `msa.l5.inputs.parse_thesis` 와 같은 규칙 —
    `gate_result` 가 없으면(사람 논지) 가능, `contested`·`rejected` 또는 `portfolio_eligible: false`
    면 불가."""
    gs = gate_status(thesis)
    gate = thesis.get("gate_result") or {}
    eligible = True
    if isinstance(gate, Mapping):
        pe = gate.get("portfolio_eligible")
        if pe is not None:
            eligible = bool(pe)
    if gs in ("contested", "rejected"):
        eligible = False
    return eligible, (str(gs) if gs else None)


def _find_human_thesis(human_dir: Path, theme: str) -> Path | None:
    for name in (f"{theme}.yaml", f"{theme}.yml", thesis_filename(theme)):
        f = human_dir / name
        if f.exists():
            return f
    return None


def _find_prior_thesis(theses_root: Path, theme: str, asof: str) -> Path | None:
    """`theses_root/<date≤asof>/<theme>.thesis.yaml` 의 최신."""
    for d, p in reversed(scan_dirs(theses_root)):
        if d.isoformat() <= asof and (p / thesis_filename(theme)).exists():
            return p / thesis_filename(theme)
    return None


def _record_from_path(theme: str, path: Path, source: str, status: str) -> ThesisRecord:
    try:
        raw = read_thesis_yaml(path)
    except Exception as e:  # 한 파일 때문에 라운드가 멈추지 않는다
        return ThesisRecord(theme, source, "failed", rel(path), reason=f"읽기 실패: {e}")
    ok, gs = gate_eligible(raw)
    why = "" if ok else f"gate 편입 불가 (status={gs})"
    return ThesisRecord(theme, source, status, rel(path), gs, ok, why)


# ---------------------------------------------------------------- 결과


@dataclass
class MonthlyRunResult:
    report: RunReport
    out_dir: Path | None
    scan: ScanResult | None = None
    selection: ThemeSelection | None = None
    theses: dict[str, ThesisRecord] = field(default_factory=dict)
    research: dict[str, ResearchResult] = field(default_factory=dict)
    ingest: IngestReport | None = None
    picks: dict[str, PicksResult] = field(default_factory=dict)
    assemble: AssembleResult | None = None
    portfolio: PortfolioResult | None = None

    @property
    def exit_code(self) -> int:
        return self.report.exit_code


@dataclass
class WeeklyRunResult:
    report: RunReport
    out_dir: Path | None
    scan: ScanResult | None = None
    check: CheckReport | None = None

    @property
    def exit_code(self) -> int:
        return self.report.exit_code


# ---------------------------------------------------------------- 단계 실행 도우미


class _Timer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    @property
    def seconds(self) -> float:
        return time.perf_counter() - self.t0


def _n_eligible(sb: pd.DataFrame) -> str:
    return str(int(sb["eligible"].fillna(False).astype(bool).sum())) if "eligible" in sb else "—"


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}".replace("\n", " ")


def _skip_rest(report: RunReport, steps: Sequence[str], reason: str) -> None:
    done = {s.name for s in report.steps}
    for name in steps:
        if name not in done:
            report.add(StepResult(name, "skipped", reason))


def _asof_str(asof: str | date | None) -> str:
    if asof is None:
        return date.today().isoformat()
    s = asof.isoformat() if isinstance(asof, date) else str(asof).strip()
    try:
        parse_date(s)
    except ValueError as e:
        raise RunError(f"asof={asof!r}: YYYY-MM-DD 가 아니다") from e
    return s


@dataclass
class _Roots:
    """이번 실행이 쓰는 루트 — `write` 면 `state/`, 아니면 샌드박스. 계층들은 파일 계약으로
    이어지므로 `write=False` 여도 **어딘가에는** 써야 한다; 그곳이 샌드박스다."""

    state: Path  # 산출물 루트 (state/ 또는 샌드박스)
    real: Path  # 진짜 state/ — 읽기 전용 입력(themes·cases·positions)
    sandbox: bool

    @property
    def scans(self) -> Path:
        return self.state / "scans"

    @property
    def theses(self) -> Path:
        return self.state / "theses"

    @property
    def picks(self) -> Path:
        return self.state / "picks"

    @property
    def portfolio_inputs(self) -> Path:
        return self.state / "portfolio_inputs"

    @property
    def runs(self) -> Path:
        return self.state / "runs"


def _roots(write: bool, sandbox_dir: Path | None) -> tuple[_Roots, Path | None]:
    """(루트, 끝나고 지울 임시 디렉터리)."""
    p = paths()
    if write:
        return _Roots(p.state, p.state, False), None
    if sandbox_dir is not None:
        sb = Path(sandbox_dir)
        sb.mkdir(parents=True, exist_ok=True)
        return _Roots(sb, p.state, True), None
    tmp = Path(tempfile.mkdtemp(prefix="msa-run-"))
    return _Roots(tmp, p.state, True), tmp


# ---------------------------------------------------------------- 월간


def run_monthly(
    *,
    asof: str | None = None,
    top_k: int = 8,
    extra_themes: Sequence[str] = (),
    provider: str = "none",
    human_theses_dir: Path | None = None,
    write: bool = True,
    skip_research: bool = False,
    skip_picks: bool = False,
    skip_portfolio: bool = False,
    capital: float | None = None,
    sandbox_dir: Path | None = None,
) -> MonthlyRunResult:
    """월간 케이던스 한 번 (`docs/09` §1 월간 행). 단계는 모듈 머리말의 표 순서.

    - `provider="none"` — L3 를 부르지 않는다. 선정 테마마다 `human_theses_dir/<theme>.yaml` 또는
      직전 `state/theses/<date≤asof>/<theme>.thesis.yaml` 을 **찾기만** 하고, 없으면 "thesis 없음 →
      관찰" 로 적는다(오류가 아니다). 키가 없는 오늘의 기본값이다.
    - `provider="claude_code"|"mock"|"fixture"|"anthropic"` — 테마별로 L3 파이프라인을 돌린다.
      `claude_code` 는 로컬 CLI 하위 프로세스라 API 크레딧을 쓰지 않는다. 테마별 실패는
      격리된다.
    - `write=False` — `state/` 에 아무것도 쓰지 않는다. 중간 산출물은 `sandbox_dir`(기본 임시
      디렉터리, 끝나면 삭제)에 쓰고, 저널·대장·관찰 목록은 dry-run 판정만 한다.
    - 반환의 `report.exit_code` 는 스캔 중단 또는 묶음 입력 **계약 위반**일 때 1 이다.
      부분 가용(테마별 실패·정상적인 0건)은 0 + 리포트.
    """
    if provider not in PROVIDERS:
        raise RunError(f"provider ∈ {PROVIDERS}: {provider!r}")
    if top_k < 0:
        raise RunError(f"top_k 는 0 이상: {top_k}")
    asof_s = _asof_str(asof)
    hdir = Path(human_theses_dir) if human_theses_dir is not None else None
    if hdir is not None and not hdir.is_dir():
        raise RunError(f"사람 논지 디렉터리가 없다: {hdir}")
    roots, tmp = _roots(write, sandbox_dir)
    report = RunReport(
        cadence="monthly",
        asof=asof_s,
        started_at=datetime.now().isoformat(timespec="seconds"),
        write=write,
        state_root=str(roots.state),
        params={
            "top_k": top_k,
            "extra_themes": [str(t) for t in extra_themes],
            "provider": provider,
            "human_theses_dir": str(hdir) if hdir is not None else None,
            "skip": {
                "research": skip_research,
                "picks": skip_picks,
                "portfolio": skip_portfolio,
            },
            "capital": capital,
        },
    )
    if roots.sandbox:
        report.notes.append(
            f"no-write: 중간 산출물은 샌드박스 {roots.state} 에 썼다"
            + (" (끝나고 지운다)" if tmp is not None else "")
        )
    result = MonthlyRunResult(report=report, out_dir=None)
    try:
        _monthly_steps(
            result,
            roots,
            asof_s,
            top_k=top_k,
            extra_themes=extra_themes,
            provider=provider,
            hdir=hdir,
            skip_research=skip_research,
            skip_picks=skip_picks,
            skip_portfolio=skip_portfolio,
            capital=capital,
        )
        _write_report(result.report, roots, "monthly-report.md")
        if write:
            result.out_dir = Path(result.report.out_dir) if result.report.out_dir else None
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    return result


def _monthly_steps(
    result: MonthlyRunResult,
    roots: _Roots,
    asof_s: str,
    *,
    top_k: int,
    extra_themes: Sequence[str],
    provider: str,
    hdir: Path | None,
    skip_research: bool,
    skip_picks: bool,
    skip_portfolio: bool,
    capital: float | None,
) -> None:
    report = result.report
    p = paths()

    # 1) scan — 경성. 실패면 중단
    t = _Timer()
    try:
        scan = run_scan(asof=asof_s, write=True, out_root=roots.scans)
    except Exception as e:
        log.exception("run monthly: scan 실패 — 중단")
        report.add(StepResult("scan", "failed", _err(e), seconds=t.seconds))
        report.stopped = True
        report.stopped_reason = f"scan 실패 — {_err(e)} (docs/09 §5: 부분 데이터로 진행하지 않는다)"
        _skip_rest(report, MONTHLY_STEPS[:-1], "scan 실패로 중단")
        return
    result.scan = scan
    scan_dir = scan.out_dir
    sb = scan.scoreboard.table
    report.add(
        StepResult(
            "scan",
            "ok",
            f"테마 {len(sb)} · 자격 {_n_eligible(sb)} · "
            f"스캔 기준일 {scan.meta.get('asof')} (스토어 {scan.meta.get('store_end')})"
            # 요청 asof 를 내렸으면 그 사실을 단계 노트에 싣는다 (`CLAUDE.md` §2)
            + (f" · {asof_note(scan.meta)}" if scan.meta.get("asof_clamped") else ""),
            [rel(scan_dir)] if scan_dir else [],
            t.seconds,
            {
                "asof": scan.meta.get("asof"),
                "store_end": scan.meta.get("store_end"),
                "asof_requested": scan.meta.get("asof_requested"),
                "asof_clamped": scan.meta.get("asof_clamped"),
            },
        )
    )

    # 2) select — L1 순위(S2 자격)만으로 고른다
    t = _Timer()
    sel = select_themes(sb, top_k=top_k, extra_themes=extra_themes)
    result.selection = sel
    report.add(
        StepResult(
            "select",
            "ok",
            f"선정 {len(sel.selected)} (자격 {sel.n_eligible}/{sel.n_total}"
            + (f", K={top_k} 미만" if sel.short_of_k else "")
            + f", 지정 {len(sel.extra)}"
            + (f", 소표본 강등 {len(sel.demoted)}" if sel.demoted else "")
            + ")",
            seconds=t.seconds,
            details={"selection": sel.as_dict(), "text": sel.render()},
        )
    )
    for n in sel.notes:
        report.notes.append(f"select: {n}")
    if not sel.selected:
        report.notes.append("선정 테마 0 — research 이하를 건너뛴다")
        _skip_rest(report, MONTHLY_STEPS[:-1], "선정 테마 0")
        return

    # 3) research (+ 4 ingest)
    if skip_research:
        report.add(StepResult("research", "skipped", "--skip-research"))
        # 논지는 그래도 찾는다 — picks·portfolio 가 쓸 수 있게 (provider none 과 같은 경로)
        result.theses = _locate_theses(sel.selected, roots, asof_s, hdir)
        _ingest_step(
            result,
            roots,
            scan_dir,
            _located_jobs(result, asof_s),
            empty_reason="--skip-research · 찾은 thesis 0 — 적재할 것이 없다",
        )
    elif provider == "none":
        t = _Timer()
        result.theses = _locate_theses(sel.selected, roots, asof_s, hdir)
        found = [r for r in result.theses.values() if r.path]
        absent = [r.theme for r in result.theses.values() if r.status == "absent"]
        report.add(
            StepResult(
                "research",
                "ok",
                f"provider none — L3 를 부르지 않았다. 논지 찾음 {len(found)}/{len(sel.selected)} "
                f"(human {sum(r.source == 'human' for r in found)} · 직전 L3 "
                f"{sum(r.source == 'l3-prior' for r in found)}) · thesis 없음 → 관찰 {len(absent)}",
                [r.path for r in found if r.path],
                t.seconds,
                {
                    "theses": [r.as_dict() for r in result.theses.values()],
                    "text": _theses_text(result),
                },
            )
        )
        for th in absent:
            report.human_todo.append(
                f"{th}: thesis 없음 → 관찰. 사람 논지(<dir>/{th}.yaml)를 쓰거나 `msa research {th}`"
            )
        # 새 L3 라운드는 없지만 **게이트 판정의 산출물(관찰 목록·기각 항목·초안)은 나와야 한다**
        _ingest_step(
            result,
            roots,
            scan_dir,
            _located_jobs(result, asof_s),
            empty_reason="provider none — 찾은 thesis 0 (적재할 것이 없다)",
        )
    else:
        _research_step(result, roots, asof_s, sel.selected, provider, hdir)
        _ingest_step(
            result,
            roots,
            scan_dir,
            _round_jobs(result),
            empty_reason="이번 실행이 쓴 L3 라운드가 없다",
        )

    # 5) picks
    eligible = [
        th for th in sel.selected if result.theses.get(th, None) and result.theses[th].eligible
    ]
    if skip_picks:
        report.add(StepResult("picks", "skipped", "--skip-picks"))
    elif not eligible:
        report.add(
            StepResult(
                "picks",
                "skipped",
                "게이트 편입 가능 thesis 가 있는 테마 0 — L4 를 돌릴 대상이 없다",
            )
        )
    else:
        _picks_step(result, roots, asof_s, eligible)

    # 6) assemble + portfolio
    if skip_portfolio:
        report.add(StepResult("assemble", "skipped", "--skip-portfolio"))
        report.add(StepResult("portfolio", "skipped", "--skip-portfolio"))
    elif not eligible:
        why = "게이트 편입 가능 테마 0 — 묶을 것이 없다 (오류가 아니다)"
        report.add(StepResult("assemble", "skipped", why))
        report.add(StepResult("portfolio", "skipped", why))
    else:
        _portfolio_step(result, roots, asof_s, eligible, hdir, capital, p)


def _locate_theses(
    themes: Sequence[str], roots: _Roots, asof_s: str, hdir: Path | None
) -> dict[str, ThesisRecord]:
    """provider none — 사람 논지 → 직전 L3 thesis(실 state/ 와 샌드박스 둘 다 본다) 순으로
    찾는다."""
    out: dict[str, ThesisRecord] = {}
    for th in themes:
        path: Path | None = None
        src = "human"
        if hdir is not None:
            path = _find_human_thesis(hdir, th)
        if path is None:
            src = "l3-prior"
            path = _find_prior_thesis(roots.theses, th, asof_s)
            if path is None and roots.sandbox:
                path = _find_prior_thesis(roots.real / "theses", th, asof_s)
        if path is None:
            where = f"state/theses/<≤{asof_s}>/{thesis_filename(th)}"
            if hdir is not None:
                where = f"{hdir}/{th}.yaml · " + where
            out[th] = ThesisRecord(th, "none", "absent", reason=f"thesis 없음 ({where}) → 관찰")
        else:
            out[th] = _record_from_path(th, path, src, "found")
    return out


def _theses_text(result: MonthlyRunResult) -> str:
    L = [f"{'theme':<28} {'source':<9} {'status':<16} {'gate':<10} elig  path / reason"]
    for r in result.theses.values():
        L.append(
            f"{r.theme:<28} {r.source:<9} {r.status:<16} {r.gate_status or '—':<10} "
            f"{'Y' if r.eligible else 'n':<4}  {r.path or ''} {r.reason}".rstrip()
        )
    return "\n".join(L)


def _research_step(
    result: MonthlyRunResult,
    roots: _Roots,
    asof_s: str,
    themes: Sequence[str],
    provider: str,
    hdir: Path | None,
) -> None:
    """테마별 L3 — 실패는 격리하고 이름·사유로 남긴다 (`docs/09` §5 에이전트 스키마 실패 행)."""
    report = result.report
    p = paths()
    t = _Timer()
    cost: dict[str, Any] = {}
    for th in themes:
        if hdir is not None:
            hp = _find_human_thesis(hdir, th)
            if hp is not None:
                result.theses[th] = _record_from_path(th, hp, "human", "found")
                result.theses[th].reason = (
                    result.theses[th].reason + " · 사람 논지 우선 — L3 생략"
                ).strip(" ·")
                continue
        try:
            inputs = l3_assemble_inputs(
                th,
                state_dir=roots.state,
                asof=asof_s,
                cases_dir=p.cases_dir,
                with_store=True,
            )
            prov = make_provider(provider, theme_id=th)
            res = run_research(inputs, prov, theses_root=roots.theses, write=True)
        except ThesisRejected as e:
            result.theses[th] = ThesisRecord(
                th,
                "l3",
                "rejected_schema",
                reason="스키마 검증 실패 → 제외: " + "; ".join(e.result.errors),
            )
            continue
        except InputsError as e:
            result.theses[th] = ThesisRecord(th, "l3", "failed", reason=f"입력 조립 불가: {e}")
            continue
        except Exception as e:
            kind = "provider_error" if isinstance(e, ProviderError) else "failed"
            log.warning("run monthly: research %s — %s", th, _err(e))
            if kind == "failed":
                log.debug("research 실패 상세", exc_info=True)
            result.theses[th] = ThesisRecord(th, "l3", kind, reason=_err(e))
            continue
        result.research[th] = res
        ok, gs = gate_eligible(res.thesis)
        result.theses[th] = ThesisRecord(
            th,
            "l3",
            "researched",
            rel(res.thesis_path) if res.thesis_path else None,
            gs,
            ok,
            "" if ok else f"gate 편입 불가 (status={gs})",
        )
        cost[th] = {"rows": res.ledger.rows(), "estimated_usd": res.ledger.estimated_usd()}
    # 선정됐지만 장부에 없는 테마는 없어야 한다 — 방어
    for th in themes:
        result.theses.setdefault(th, ThesisRecord(th, "none", "failed", reason="기록 없음"))
    recs = [result.theses[th] for th in themes]
    n_ok = sum(r.status in ("researched", "found") for r in recs)
    by_status: dict[str, int] = {}
    for r in recs:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    status = "ok" if n_ok else ("failed" if recs else "skipped")
    report.add(
        StepResult(
            "research",
            status,
            f"provider {provider} — thesis 확보 {n_ok}/{len(recs)} · 상태 {by_status}",
            [r.path for r in recs if r.path],
            t.seconds,
            {"theses": [r.as_dict() for r in recs], "cost": cost, "text": _theses_text(result)},
        )
    )
    for r in recs:
        if r.status == "rejected_schema":
            report.notes.append(f"research {r.theme}: {r.reason}")
        elif r.status in ("provider_error", "failed"):
            report.notes.append(f"research {r.theme}: {r.status} — {r.reason}")
        elif r.gate_status == "contested":
            report.human_todo.append(f"{r.theme}: referee contested → 관찰 목록 · 재연구 대상")


@dataclass(frozen=True)
class _IngestJob:
    """적재 한 묶음 — 어느 디렉터리를, 어느 기준일로, (선택) 어느 파일들만."""

    theses_dir: Path
    asof: str
    paths: tuple[Path, ...] | None = None  # None = 디렉터리 전체 (새 L3 라운드)


def _round_jobs(result: MonthlyRunResult) -> list[_IngestJob]:
    """이번 실행이 쓴 L3 라운드 → 적재 묶음 (기존 동작)."""
    round_dirs = {r.out_dir for r in result.research.values() if r.out_dir is not None}
    if not round_dirs:
        return []
    if len(round_dirs) > 1:
        result.report.notes.append(
            f"ingest: 라운드 디렉터리가 {len(round_dirs)} 개 — 첫 번째만 적재한다"
        )
    d = sorted(round_dirs)[0]
    return [_IngestJob(d, result.report.asof)]


def _located_jobs(result: MonthlyRunResult, asof_s: str) -> list[_IngestJob]:
    """`_locate_theses` 가 찾은 thesis → 적재 묶음.

    새 L3 라운드가 없어도(`--provider none`·`--skip-research`) **게이트 판정의 산출물인 관찰
    목록·기각 항목·진입 초안은 나와야 한다** — 그러지 않으면 리포트는 "관찰" 이라 적는데 파일이
    없다. 판정 자체는 `ingest_round` 가 하던 그대로다 (LLM 호출 없음).

    기준일은 **그 thesis 가 나온 라운드의 날짜**다 (디렉터리 이름). 오늘 날짜로 적재하면 이미
    적재된 기각이 매달 새 저널 항목으로 복제된다 — 대장의 멱등 키가 `(theme, rejected_at)` 라서다.
    날짜를 읽을 수 없는 사람 논지 디렉터리만 이번 실행의 `asof` 를 쓴다.
    """
    by_dir: dict[Path, list[Path]] = {}
    for rec in result.theses.values():
        if rec.path is None or rec.status not in ("found", "researched"):
            continue
        f = Path(rec.path)
        if not f.is_absolute():
            f = REPO_ROOT / f
        if not f.exists():
            continue
        by_dir.setdefault(f.parent, []).append(f)
    jobs: list[_IngestJob] = []
    for d, files in sorted(by_dir.items()):
        try:
            round_asof = parse_date(d.name).isoformat()
        except ValueError:
            round_asof = asof_s  # 사람 논지 디렉터리 등 — 날짜가 아니다
        jobs.append(_IngestJob(d, round_asof, tuple(sorted(files))))
    return jobs


def _ingest_step(
    result: MonthlyRunResult,
    roots: _Roots,
    scan_dir: Path | None,
    jobs: Sequence[_IngestJob],
    *,
    empty_reason: str,
) -> None:
    """`jobs` 를 차례로 적재하고 **한 줄로 합산**해 보고한다. 묶음이 0 이면 사유와 함께 skipped."""
    report = result.report
    p = paths()
    t = _Timer()
    if not jobs:
        report.add(StepResult("ingest", "skipped", empty_reason))
        return
    reps: list[IngestReport] = []
    fails: list[str] = []
    for job in jobs:
        try:
            reps.append(
                ingest_round(
                    job.theses_dir,
                    asof=parse_date(job.asof),
                    scan_dir=scan_dir,
                    journal_dir=journal_dir(REPO_ROOT),
                    rejections_path=p.rejections,
                    watchlist_path=p.watchlist,
                    write=not roots.sandbox,
                    thesis_paths=list(job.paths) if job.paths is not None else None,
                )
            )
        except Exception as e:
            log.warning("run monthly: ingest %s 실패 — %s", job.theses_dir, _err(e))
            fails.append(f"{rel(job.theses_dir)}: {_err(e)}")
    if not reps:
        report.add(StepResult("ingest", "failed", "; ".join(fails), seconds=t.seconds))
        return
    result.ingest = reps[0]
    rows = [r for rep in reps for r in rep.rows]
    outs = sorted({x for r in rows for x in r.paths})
    n = {
        k: sum(rep.count(k) for rep in reps)
        for k in (
            "reject_ingested",
            "reject_skipped",
            "reject_blocked",
            "watchlist_added",
            "watchlist_updated",
            "draft_written",
            "unknown_status",
        )
    }
    status = "ok" if not (n["reject_blocked"] or n["unknown_status"] or fails) else "failed"
    report.add(
        StepResult(
            "ingest",
            status,
            f"thesis {len(rows)} · 기각→저널+대장 {n['reject_ingested']} (건너뜀 "
            f"{n['reject_skipped']}, 불가 {n['reject_blocked']}) · 관찰 upsert "
            f"{n['watchlist_added'] + n['watchlist_updated']} · 진입 초안 {n['draft_written']}"
            + ("" if not roots.sandbox else " · dry-run")
            + (f" · 묶음 실패 {len(fails)}: " + "; ".join(fails) if fails else ""),
            outs,
            t.seconds,
            {
                "text": "\n".join(rep.render() for rep in reps),
                "jobs": [
                    {
                        "theses_dir": rel(j.theses_dir),
                        "asof": j.asof,
                        "n_paths": None if j.paths is None else len(j.paths),
                    }
                    for j in jobs
                ],
                "failed": fails,
            },
        )
    )
    for rep in reps:
        for theme, todo in rep.human_todo.items():
            report.human_todo.append(
                f"{theme}: 진입 초안 채우기 → `msa journal new --from` — " + " / ".join(todo)
            )
    for r in rows:
        if r.action in ("watchlist_added", "watchlist_updated"):
            report.human_todo.append(f"{r.theme}: 관찰 목록 행 ({r.status}) — {r.detail}")
        elif r.action == "reject_blocked":
            report.notes.append(f"ingest {r.theme}: 적재 불가 — {r.detail}")


def _picks_step(
    result: MonthlyRunResult, roots: _Roots, asof_s: str, themes: Sequence[str]
) -> None:
    report = result.report
    t = _Timer()
    failed: dict[str, str] = {}
    for th in themes:
        try:
            result.picks[th] = run_picks(th, asof=asof_s, write=True, out_root=roots.picks)
        except Exception as e:
            log.warning("run monthly: picks %s 실패 — %s", th, _err(e))
            failed[th] = _err(e)
    outs = [rel(r.out_dir) for r in result.picks.values() if r.out_dir]
    status = "ok" if result.picks else "failed"
    reason = f"테마 {len(result.picks)}/{len(themes)} 랭킹" + (
        f" · 실패 {len(failed)}: " + "; ".join(f"{k} ({v})" for k, v in failed.items())
        if failed
        else ""
    )
    report.add(
        StepResult(
            "picks", status, reason, outs, t.seconds, {"failed": failed, "themes": list(themes)}
        )
    )


def _portfolio_step(
    result: MonthlyRunResult,
    roots: _Roots,
    asof_s: str,
    themes: Sequence[str],
    hdir: Path | None,
    capital: float | None,
    p: Any,
) -> None:
    report = result.report
    t = _Timer()
    out_dir = roots.portfolio_inputs / asof_s
    try:
        asm = assemble_inputs(
            asof=asof_s,
            themes=themes,
            picks_root=roots.picks,
            theses_root=roots.theses,
            out_dir=out_dir,
            human_theses_dir=hdir,
            write=True,
        )
    except AssembleError as e:
        if ASSEMBLE_EMPTY_MARKER in str(e):  # 정상적인 "0건" — 오류가 아니다
            report.add(StepResult("assemble", "skipped", f"묶을 테마 0 — {e}", seconds=t.seconds))
            report.add(StepResult("portfolio", "skipped", "묶음이 없다"))
            return
        # 계약 위반 (ranking.csv 가 L4 산출물이 아니다 · 사람 논지 디렉터리 없음 · top_per_theme)
        # — "0건" 으로 위장하지 않는다 (CLAUDE.md §2)
        log.error("run monthly: assemble 계약 위반 — %s", _err(e))
        report.add(
            StepResult("assemble", "failed", f"입력 계약 위반 — {_err(e)}", seconds=t.seconds)
        )
        report.add(StepResult("portfolio", "skipped", "묶음 계약 위반"))
        report.stopped = True
        report.stopped_reason = (
            f"assemble 입력 계약 위반 — {_err(e)} (CLAUDE.md §2: 정상적인 0건이 아니다)"
        )
        return
    except Exception as e:
        log.warning("run monthly: assemble 실패 — %s", _err(e))
        report.add(StepResult("assemble", "failed", _err(e), seconds=t.seconds))
        report.add(StepResult("portfolio", "skipped", "묶음 실패"))
        return
    result.assemble = asm
    report.add(
        StepResult(
            "assemble",
            "ok",
            f"포함 {len(asm.themes_included)} [{', '.join(asm.themes_included)}] · 건너뜀 "
            f"{len(asm.themes_skipped)} · 종목 {asm.picks.n_included}",
            [rel(asm.out_dir)] if asm.out_dir else [],
            t.seconds,
            {"skipped": asm.themes_skipped, "text": asm.report_text},
        )
    )
    for th, why in asm.themes_skipped.items():
        report.notes.append(f"assemble {th}: {why}")

    t = _Timer()
    try:
        pf = run_portfolio(
            asof=asof_s,
            inputs_dir=asm.out_dir or out_dir,
            capital_usd=capital,
            write=True,
            state_dir=roots.state,
            emit_positions=True,
        )
    except Exception as e:
        log.warning("run monthly: portfolio 실패 — %s", _err(e))
        report.add(StepResult("portfolio", "failed", _err(e), seconds=t.seconds))
        return
    result.portfolio = pf
    outs: list[str] = []
    if pf.out_dir:
        outs = [rel(pf.out_dir / "plan.md"), rel(pf.out_dir / "positions-proposal.yaml")]
    n_pos = len(pf.positions)
    report.add(
        StepResult(
            "portfolio",
            "ok",
            f"테마 {len(pf.theme_rows)} · 포지션 {n_pos} · 경고 {len(pf.warnings)}"
            + (f" · 자본 {capital:,.0f}" if capital else ""),
            outs,
            t.seconds,
            {"warnings": list(pf.warnings)},
        )
    )
    if pf.out_dir:
        report.human_todo.append(
            f"미체결 제안 {n_pos}건 — {rel(pf.out_dir / 'positions-proposal.md')} 절차대로 "
            "검토·체결 후 state/positions.yaml 로 승격 (기계는 쓰지 않는다)"
        )


# ---------------------------------------------------------------- 주간


def run_cadence_check(
    asof_s: str, *, mode: str, write: bool, send: bool = True
) -> tuple[CheckReport, dict[str, Any]]:
    """`msa check --daily|--weekly` 와 같은 경로 — 스토어 가격으로 점검하고, `write` 면 알림
    파일·마지막 성공 시각까지 남긴다. (실패·제공자 오류는 호출자가 받는다.)
    주간(`run_weekly`)과 일간(`run_daily`)이 공유한다 — 점검 논리는 여기 한 벌뿐이다.

    `send` 는 **이 점검이 만든 알림(무효화·사다리·TP·시간스탑·Tier-2)의 발신**을 지배한다.
    `False` 면 `alerts.json` 만 쓰고 텔레그램은 보지 않는다 (`msa check --no-send` 와 같은 규약).
    `msa run daily` 는 `--send` 를 그대로 넘긴다 — 한 실행의 발신은 그 플래그 하나가 정한다."""
    from msa.data.store import Store
    from msa.vendor.scheduler import LastRunStore, RunTracker

    p = paths()
    asof_d = parse_date(asof_s)
    tracker = RunTracker(LastRunStore(p.checks / "last_run.json"), key=f"check.{mode}")
    info: dict[str, Any] = {"lookback_days": tracker.lookback_days(asof_d)}
    with Store(p.duckdb) as store:
        rep = run_check(
            asof=asof_d,
            mode=mode,
            prices=StorePriceSource(store),
            positions_path=p.positions,
            journal_dir=journal_dir(REPO_ROOT),
            repo_root=REPO_ROOT,
            out_root=p.checks if write else None,
        )
    if rep.out_dir is not None:
        dres = deliver(rep.alerts, rep.out_dir, use_env=send, send=send)
        info["alerts_json"] = rel(dres.json_path)
        info["telegram"] = str(dres.status)
        if write:
            tracker.mark_polled()
    return rep, info


def run_weekly_check(
    asof_s: str, *, write: bool, send: bool = False
) -> tuple[CheckReport, dict[str, Any]]:
    """`run_cadence_check(mode="weekly")` — 테스트는 이 함수를 갈아끼운다.

    `send` 는 **호출자가 정한다.** 예전에는 `send` 를 넘기지 않아 기본값 `True` 로 흘렀고,
    `msa run weekly` 에 끌 플래그가 없어 텔레그램이 항상 나갔다 (2026-08-26 코드 리뷰).
    "보낼지 말지는 명령의 플래그가 정한다" (`CLAUDE.md`) — `msa run daily` 와 같은 규약이다.
    """
    return run_cadence_check(asof_s, mode="weekly", write=write, send=send)


def run_weekly(
    *,
    asof: str | None = None,
    write: bool = True,
    send: bool = False,
    sandbox_dir: Path | None = None,
) -> WeeklyRunResult:
    """주간 케이던스 (`docs/09` §1 주간 행) = 전수 스캔(경량 갱신 대용 — 캐시 덕에 ~12 초) + 보유
    포지션 트리거·무효화 점검 + 주간 리포트. 스캔 실패는 중단(exit 1); 점검 문제는 리포트에 남기고
    0."""
    asof_s = _asof_str(asof)
    roots, tmp = _roots(write, sandbox_dir)
    report = RunReport(
        cadence="weekly",
        asof=asof_s,
        started_at=datetime.now().isoformat(timespec="seconds"),
        write=write,
        state_root=str(roots.state),
    )
    result = WeeklyRunResult(report=report, out_dir=None)
    try:
        t = _Timer()
        try:
            scan = run_scan(asof=asof_s, write=True, out_root=roots.scans)
        except Exception as e:
            log.exception("run weekly: scan 실패 — 중단")
            report.add(StepResult("scan", "failed", _err(e), seconds=t.seconds))
            report.stopped = True
            report.stopped_reason = f"scan 실패 — {_err(e)}"
            _skip_rest(report, WEEKLY_STEPS[:-1], "scan 실패로 중단")
        else:
            result.scan = scan
            sb = scan.scoreboard.table
            report.add(
                StepResult(
                    "scan",
                    "ok",
                    f"테마 {len(sb)} · 자격 {_n_eligible(sb)} · "
                    f"스캔 기준일 {scan.meta.get('asof')}",
                    [rel(scan.out_dir)] if scan.out_dir else [],
                    t.seconds,
                )
            )
            t = _Timer()
            try:
                chk, info = run_weekly_check(asof_s, write=write, send=send)
            except Exception as e:
                log.warning("run weekly: check 실패 — %s", _err(e))
                report.add(StepResult("check", "failed", _err(e), seconds=t.seconds))
            else:
                result.check = chk
                outs = [rel(chk.out_dir)] if chk.out_dir else []
                report.add(
                    StepResult(
                        "check",
                        "ok",
                        f"포지션 {len(chk.positions)} · 알림 {len(chk.alerts)} · "
                        f"문제 {len(chk.problems)} · 미체결 제안 {len(chk.unchecked)}"
                        + (f" · 텔레그램 {info['telegram']}" if "telegram" in info else ""),
                        outs,
                        t.seconds,
                        {"problems": list(chk.problems), "text": chk.render(), **info},
                    )
                )
                for pr in chk.problems:
                    report.human_todo.append(f"check 문제: {pr}")
                if chk.unchecked:
                    report.human_todo.append(
                        f"미체결 제안 {len(chk.unchecked)}건 — 체결 반영 후 positions.yaml 승격 "
                        "(사람)"
                    )
        _write_report(report, roots, "weekly-report.md")
        if write and report.out_dir:
            result.out_dir = Path(report.out_dir)
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
    return result


# ---------------------------------------------------------------- 분기


def run_quarterly() -> str:
    """분기 작업 목록 — 실행하지 않는다. 세 명령과 그 뜻을 돌려준다 (`docs/09` §1 분기 행)."""
    L = [
        "분기 작업 (docs/09 §1) — 각 명령을 사람이 돌리고 1시간 읽는다. 여기서 실행하지 않는다.",
        "",
    ]
    for cmd, why in QUARTERLY_COMMANDS:
        L.append(f"  {cmd:<28} {why}")
    L += ["", "cron 은 `msa ops schedule --print-cron` 의 quarterly 행이 이 둘을 잇는다."]
    return "\n".join(L)


# ---------------------------------------------------------------- 리포트 쓰기


def _write_report(report: RunReport, roots: _Roots, name: str) -> None:
    """`<roots.runs>/<asof>/<name>` + `run.json`. 샌드박스면 쓰긴 하되 `report.out_dir` 는
    비운다."""
    step_t = _Timer()
    try:
        d = write_snapshot(
            roots.runs / report.asof,
            texts={name: report.render()},
            jsons={"run.json": report.as_dict()},
        )
    except Exception as e:  # 리포트를 못 쓴 것도 리포트에 남긴다 — 돌려주는 객체엔 있다
        report.add(StepResult("report", "failed", _err(e), seconds=step_t.seconds))
        return
    if roots.sandbox:
        report.add(
            StepResult("report", "ok", "no-write — 샌드박스에만 썼다", seconds=step_t.seconds)
        )
        return
    report.out_dir = str(d)
    report.add(StepResult("report", "ok", "", [rel(d / name), rel(d / "run.json")], step_t.seconds))
    # 단계 행이 하나 늘었으니 파일을 한 번 더 쓴다 — 파일과 객체가 같은 표를 갖게
    write_snapshot(d, texts={name: report.render()}, jsons={"run.json": report.as_dict()})


__all__ = [
    "ASSEMBLE_EMPTY_MARKER",
    "MONTHLY_STEPS",
    "PROVIDERS",
    "QUARTERLY_COMMANDS",
    "STATUSES",
    "WEEKLY_STEPS",
    "MonthlyRunResult",
    "RunError",
    "RunReport",
    "StepResult",
    "ThemeSelection",
    "ThesisRecord",
    "WeeklyRunResult",
    "gate_eligible",
    "run_cadence_check",
    "run_monthly",
    "run_quarterly",
    "run_weekly",
    "run_weekly_check",
    "select_themes",
]
