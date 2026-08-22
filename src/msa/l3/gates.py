"""하드 게이트 · contested · `cycle_confidence` — `docs/04-value-trap.md` §3·§3.1·§4 의 기계적 적용.

**여기 있는 계수와 조건은 선언이다. 데이터에 맞춰 바꾸지 않는다** (`CLAUDE.md` §1).
referee(LLM) 는 축 2~5 의 판정만 내고, 이 모듈이 게이트와 확신도를 계산한다 — 자유 조정은 없다.

게이트 평가 순서 (`docs/04` §3 — "맨 윗줄이 선행 관문"):
1. `axis1_contested` (pre≠post 또는 sign_split) → `contested`.
   referee_ruling + evidence 없으면 `rejected` 로 닫는다 (§3.1).
2. 축1 == death AND 축3 ∈ {warning, death} → `rejected` (path=hard_gate).
3. 축1 == death OR 축3 == death → 확신도 상한 0.35, 포트 편입 불가
   (status 는 passed — 하드 기각은 아니다).
4. 축5 24M 만기부채/시총 > 0.5 → 테마 유지, L4 생존 필터 플래그.
5. `secular_risk` 버킷은 통과를 입증해야 후보 (`docs/01` §3) —
   축1·축3 이 모두 cycle 이 아니면 편입 불가.

확신도 (`docs/04` §4): base 0.5, 해당 항만 가감, [0,1] 클립, 위 3 의 상한 적용.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import Any

from msa.l3.contracts import Axis1Inputs
from msa.thesis import AXES, AXIS_VERDICTS

#: 옛 이름 — enum 은 `msa.thesis` 가 단일 출처다.
VERDICTS = AXIS_VERDICTS

CONF_BASE = 0.5
CONF_CAP_ON_DEATH = 0.35
PORTFOLIO_MIN_CONFIDENCE = 0.5  # docs/07 C6 최소 확신도
CAPEX_BELOW1_QTRS = 8
TAILWIND_MIN = 0.3
DEBT_24M_TO_MCAP_MAX = 0.5

#: (항목 이름, 증감) — 리포트에 적용 항을 그대로 싣는다.
CONF_TERMS: dict[str, float] = {
    "axis1_cycle": +0.15,
    "axis2_capex_below1_8q": +0.10,
    "axis3_no_substitution": +0.15,
    "axis4_strong_cycle": +0.10,
    "macro_tailwind": +0.10,
    "axis1_warning": -0.20,
    "axis3_warning": -0.15,
    "axis5_severe": -0.15,
    "small_sample_or_short_hist": -0.10,
}


@dataclass(frozen=True)
class AxisVerdicts:
    unit_demand: str
    capital_cycle: str
    substitution: str
    cost_curve: str
    terminal_risk: str

    def as_dict(self) -> dict[str, str]:
        return {a: getattr(self, a) for a in AXES}

    def __post_init__(self) -> None:
        for a in AXES:
            v = getattr(self, a)
            if v not in AXIS_VERDICTS:
                raise ValueError(f"{a}: 알 수 없는 판정 {v!r} (허용 {AXIS_VERDICTS})")


@dataclass(frozen=True)
class ConfidenceInputs:
    """확신도 규칙의 입력 — 전부 관측값이며 LLM 의 자유 조정이 아니다."""

    verdicts: AxisVerdicts
    capex_to_da_qtrs_below1: float | None  # L1 indicators
    axis4_strong_cycle: bool  # referee: 가격 < P90 현금원가 + 셧다운 발표 관측
    axis5_severe: bool  # referee: 축5 심각
    tailwind: float | None  # L2 (없으면 항 미적용)
    small_sample: bool  # 소표본 버킷 (n < min_constituents)
    short_hist: bool  # 자기이력 < 7년


@dataclass(frozen=True)
class ConfidenceResult:
    value: float
    raw: float  # 클립·상한 전
    terms: dict[str, float]  # 적용된 항만
    cap: float | None
    notes: tuple[str, ...]


def cycle_confidence(ci: ConfidenceInputs) -> ConfidenceResult:
    """`docs/04` §4 — base 0.5 ± 해당 항, [0,1] 클립. 축1·축3 death 면 상한 0.35 (§3)."""
    v = ci.verdicts
    terms: dict[str, float] = {}
    notes: list[str] = []
    if v.unit_demand == "cycle":
        terms["axis1_cycle"] = CONF_TERMS["axis1_cycle"]
    elif v.unit_demand == "warning":
        terms["axis1_warning"] = CONF_TERMS["axis1_warning"]
    elif v.unit_demand in ("not_applicable", "contested"):
        notes.append(
            f"축1 {v.unit_demand}: 가감 없음 (04 §4 에 항 없음 — 감점하지 않고 key_uncertainties "
            f"에 명시)"
        )
    if ci.capex_to_da_qtrs_below1 is not None and ci.capex_to_da_qtrs_below1 >= CAPEX_BELOW1_QTRS:
        terms["axis2_capex_below1_8q"] = CONF_TERMS["axis2_capex_below1_8q"]
    if v.substitution == "cycle":
        terms["axis3_no_substitution"] = CONF_TERMS["axis3_no_substitution"]
    elif v.substitution == "warning":
        terms["axis3_warning"] = CONF_TERMS["axis3_warning"]
    if ci.axis4_strong_cycle and v.cost_curve == "cycle":
        terms["axis4_strong_cycle"] = CONF_TERMS["axis4_strong_cycle"]
    if ci.tailwind is not None and ci.tailwind > TAILWIND_MIN:
        terms["macro_tailwind"] = CONF_TERMS["macro_tailwind"]
    elif ci.tailwind is None:
        notes.append("거시 순풍 값 없음 — +0.10 항 미적용")
    if ci.axis5_severe or v.terminal_risk == "death":
        terms["axis5_severe"] = CONF_TERMS["axis5_severe"]
    if ci.small_sample or ci.short_hist:
        terms["small_sample_or_short_hist"] = CONF_TERMS["small_sample_or_short_hist"]
    raw = CONF_BASE + sum(terms.values())
    cap: float | None = None
    if v.unit_demand == "death" or v.substitution == "death":
        cap = CONF_CAP_ON_DEATH
    value = min(max(raw, 0.0), 1.0)
    if cap is not None:
        value = min(value, cap)
    return ConfidenceResult(
        value=round(value, 4), raw=round(raw, 4), terms=terms, cap=cap, notes=tuple(notes)
    )


@dataclass(frozen=True)
class GateResult:
    status: str  # passed | contested | rejected
    portfolio_eligible: bool
    rule: str
    path: str | None  # rejected 일 때 기각 대장 경로
    axis_verdicts: dict[str, str]
    reason: str
    referee_ruling: str | None = None
    referee_evidence_refs: tuple[int, ...] = ()
    l4_survival_filter: bool = False
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status,
            "portfolio_eligible": self.portfolio_eligible,
            "rule": self.rule,
            "axis_verdicts": dict(self.axis_verdicts),
            "reason": self.reason,
        }
        if self.path is not None:
            d["path"] = self.path
        if self.status == "contested" or self.referee_ruling:
            d["referee_ruling"] = self.referee_ruling
            d["referee_evidence_refs"] = list(self.referee_evidence_refs)
        if self.l4_survival_filter:
            d["l4_survival_filter"] = True
        if self.notes:
            d["notes"] = list(self.notes)
        return d


def apply_gates(
    verdicts: AxisVerdicts,
    axis1: Axis1Inputs,
    *,
    confidence: float,
    referee_ruling: str | None,
    referee_evidence_refs: tuple[int, ...],
    referee_refs_valid: bool,
    secular_risk: bool,
    debt_24m_over_half: bool,
) -> GateResult:
    """`docs/04` §3 하드 게이트. `confidence` 는 이미 `cycle_confidence()` 로 계산된 값(상한 "
    "포함)."""
    a1, a3 = verdicts.unit_demand, verdicts.substitution
    notes: list[str] = []
    if debt_24m_over_half:
        notes.append(
            "축5: 24M 만기부채/시총 > 0.5 — 테마 유지, L4 종목 선정에서 해당 종목 제외 (생존 필터)"
        )
    if secular_risk:
        notes.append(
            "cycle_class=secular_risk — 게이트 기본 적용, 통과를 입증해야 후보 (docs/01 §3)"
        )
    # 모든 분기가 공유하는 필드 — 분기는 status·rule·reason(·path·ruling)만 말한다
    result = partial(
        GateResult,
        path=None,
        axis_verdicts=verdicts.as_dict(),
        l4_survival_filter=debt_24m_over_half,
        notes=tuple(notes),
    )

    # 1. 선행 관문 — 입력이 안정적인가
    if axis1.contested or a1 == "contested":
        has_ruling = bool(referee_ruling and referee_ruling.strip())
        if has_ruling and referee_evidence_refs and referee_refs_valid:
            return result(
                status="contested",
                portfolio_eligible=False,
                rule=(
                    "축1 판정이 SS 보정 전후로 뒤집힘 또는 sign_split → axis1_contested (04 "
                    "§3.1). referee_ruling 있음 → 보류"
                ),
                reason=(
                    f"verdict_pre_ss={axis1.verdict_pre_ss} · "
                    f"verdict_post_ss={axis1.verdict_post_ss} · sign_split={axis1.sign_split}. "
                    f"관찰 목록에만 올린다."
                ),
                referee_ruling=referee_ruling,
                referee_evidence_refs=referee_evidence_refs,
            )
        why = (
            "referee_ruling 없음"
            if not has_ruling
            else (
                "referee_evidence_refs 비어 있음"
                if not referee_evidence_refs
                else "referee_evidence_refs 가 증거 목록에 없음"
            )
        )
        return result(
            status="rejected",
            portfolio_eligible=False,
            rule=(
                "axis1_contested 인데 referee 가 증거 있는 서술 판정을 내지 못함 → 기각으로 "
                "닫는다 (04 §3.1 '서술 못 하면 기각')"
            ),
            path="hard_gate",
            reason=f"{why}. 보류는 판단 유보이지 면제가 아니다.",
            referee_ruling=referee_ruling,
            referee_evidence_refs=referee_evidence_refs,
        )

    # 2. 자동 기각
    if a1 == "death" and a3 in ("warning", "death"):
        return result(
            status="rejected",
            portfolio_eligible=False,
            rule="축1 사망 AND 축3 ∈ {경고, 사망} → 자동 기각 (04 §3). L1 스코어 무관",
            path="hard_gate",
            reason=f"축1 {a1} (unit_cagr_10y={axis1.unit_cagr_10y}) · 축3 {a3}",
        )

    # 3. 상한 — 편입 불가
    if a1 == "death" or a3 == "death":
        return result(
            status="passed",
            portfolio_eligible=False,
            rule=(
                f"축1 사망 OR 축3 사망 → cycle_confidence 상한 {CONF_CAP_ON_DEATH} · 포트 편입 "
                f"불가, 관찰 목록만 (04 §3)"
            ),
            reason=f"축1 {a1} · 축3 {a3} · cycle_confidence={confidence}",
        )

    # 5. secular_risk — 통과 입증
    if secular_risk and not (a1 == "cycle" and a3 == "cycle"):
        return result(
            status="passed",
            portfolio_eligible=False,
            rule=(
                "secular_risk 버킷: 축1·축3 모두 cycle 이어야 편입 후보 (docs/01 §3 '통과를 "
                "입증') — 입증 안 됨"
            ),
            reason=f"축1 {a1} · 축3 {a3}",
        )

    eligible = confidence >= PORTFOLIO_MIN_CONFIDENCE
    return result(
        status="passed",
        portfolio_eligible=eligible,
        rule="04 §3 의 어느 기각 조항에도 걸리지 않음"
        + (
            ""
            if eligible
            else (
                f" — 단 cycle_confidence {confidence} < {PORTFOLIO_MIN_CONFIDENCE} (07 C6)"
                " 로 편입 불가"
            )
        ),
        reason=f"축1 {a1} · 축3 {a3} · cycle_confidence={confidence}",
    )


def rejection_row(
    *,
    theme_id: str,
    rejected_at: str,
    gate: GateResult,
    cycle_confidence: float | None,
    scoreboard_rank: int | None,
    scan_dir: str,
) -> dict[str, Any]:
    """`docs/09-operations.md` §4 `state/rejections.yaml` 행 — 키는 `ops.state_files.Rejection` 의
    필드와 같다 (임포트하지 않고 이름을 맞춘다). `journal`·`r_12m`·`r_24m` 은 M8 이 채운다."""
    return {
        "theme": theme_id,
        "rejected_at": rejected_at,
        "path": gate.path or "hard_gate",
        "reason": f"{gate.rule} — {gate.reason}",
        "cycle_confidence": cycle_confidence,
        "scoreboard_rank": scoreboard_rank,
        "journal": None,
        "scan": scan_dir,
        "r_12m": None,
        "r_24m": None,
        "axis_verdicts": dict(gate.axis_verdicts),
    }


@dataclass
class ContestedCount:
    round_contested: int = 0
    carried_over: int = 0
    carried_over_themes: list[str] = field(default_factory=list)
    round_themes: list[str] = field(default_factory=list)
