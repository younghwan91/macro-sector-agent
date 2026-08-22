"""thesis 객체의 최소 검증과 스냅샷 diff (`docs/specs/thesis.schema.yaml`, `docs/05` §6).

L3 의 전체 스키마 검증기는 M7 에 온다. 여기서는 **운영 계층이 저장·대조에 필요한 만큼만** 본다 —
비어 있으면 저장이 거부되는 필드(`evidence` · `invalidations`, `CLAUDE.md` §3·§5)와
`cycle_confidence` · 트리거/무효화 상태값 · `gate_result.path` enum.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from msa.errors import RefusedInput

#: `gate_result.path` / `rejections.yaml` 의 `path` 열 — 두 곳이 같은 값을 쓴다 (docs/09 §4).
REJECTION_PATHS: tuple[str, ...] = (
    "hard_gate",
    "conf_floor",
    "secular_risk",
    "rank_cutoff",
    "human",
)
AXES: tuple[str, ...] = (
    "unit_demand",
    "capital_cycle",
    "substitution",
    "cost_curve",
    "terminal_risk",
)
AXIS_VERDICTS: tuple[str, ...] = ("cycle", "warning", "death", "contested", "not_applicable")
TRIGGER_STATUS: tuple[str, ...] = ("pending", "met", "missed")
INVALIDATION_STATUS: tuple[str, ...] = ("pending", "fired")
INVALIDATION_ACTIONS: tuple[str, ...] = ("exit", "halve", "freeze_ladder")
CONFIDENCE_PROVENANCE: tuple[str, ...] = ("human", "referee")

_REQUIRED_TOP = (
    "theme_id",
    "generated_at",
    "horizon_months",
    "claim",
    "mechanism",
    "triggers",
    "invalidations",
    "bear_case",
    "value_trap_axes",
    "cycle_confidence",
    "evidence",
)


class ThesisInvalid(RefusedInput, ValueError):
    """저장을 거부해야 하는 thesis — 불완전한 산출물은 기록되지 않는다."""


def _nonempty_list(d: dict[str, Any], key: str, errors: list[str]) -> list[Any]:
    v = d.get(key)
    if not isinstance(v, list) or len(v) == 0:
        errors.append(f"{key} 가 비어 있다")
        return []
    return v


def validate_thesis(t: dict[str, Any]) -> None:
    """운영 계층 최소 검증. 실패하면 `ThesisInvalid` (모든 위반을 한 번에 보고한다)."""
    errors: list[str] = []
    for k in _REQUIRED_TOP:
        if k not in t or t[k] is None or t[k] == "" or t[k] == {} or t[k] == []:
            errors.append(f"필수 필드 없음: {k}")
    for item in _nonempty_list(t, "triggers", errors):
        for k in ("observable", "source", "by"):
            if not item.get(k):
                errors.append(f"triggers[*].{k} 없음: {item}")
        st = item.get("status", "pending")
        if st not in TRIGGER_STATUS:
            errors.append(f"triggers[*].status 값 불가: {st}")
    for item in _nonempty_list(t, "invalidations", errors):
        for k in ("observable", "source", "action"):
            if not item.get(k):
                errors.append(f"invalidations[*].{k} 없음: {item}")
        if item.get("action") not in INVALIDATION_ACTIONS:
            errors.append(f"invalidations[*].action 값 불가: {item.get('action')}")
        st = item.get("status", "pending")
        if st not in INVALIDATION_STATUS:
            errors.append(f"invalidations[*].status 값 불가: {st}")
    for ev in _nonempty_list(t, "evidence", errors):
        for k in ("id", "claim", "source_url", "date", "reliability"):
            if ev.get(k) in (None, ""):
                errors.append(f"evidence[*].{k} 없음: {ev}")
    c = t.get("cycle_confidence")
    if not isinstance(c, int | float) or isinstance(c, bool) or not (0.0 <= float(c) <= 1.0):
        errors.append(f"cycle_confidence 는 [0,1] 실수여야 한다: {c!r}")
    hz = t.get("horizon_months")
    if not (isinstance(hz, list) and len(hz) == 2 and all(isinstance(x, int) for x in hz)):
        errors.append(f"horizon_months 는 [하한, 상한] 정수 2개여야 한다: {hz!r}")
    axes = t.get("value_trap_axes")
    if isinstance(axes, dict):
        for a in AXES:
            if a not in axes:
                errors.append(f"value_trap_axes.{a} 없음")
            elif axes[a].get("verdict") not in AXIS_VERDICTS:
                errors.append(f"value_trap_axes.{a}.verdict 값 불가: {axes[a].get('verdict')}")
    gate = t.get("gate_result")
    if isinstance(gate, dict):
        path = gate.get("path")
        if path is not None and path not in REJECTION_PATHS:
            errors.append(f"gate_result.path 값 불가: {path} (허용 {REJECTION_PATHS})")
        if gate.get("status") in ("contested", "rejected") and gate.get("portfolio_eligible"):
            errors.append("gate_result: contested/rejected 인데 portfolio_eligible 이 true 다")
    if errors:
        raise ThesisInvalid("thesis 저장 거부:\n  - " + "\n  - ".join(errors))


def axis_verdicts(t: dict[str, Any]) -> dict[str, str]:
    """5축 verdict 스냅샷 — `gate_result.axis_verdicts` 가 있으면 그것, 없으면 value_trap_axes."""
    gate = t.get("gate_result") or {}
    snap = gate.get("axis_verdicts")
    if isinstance(snap, dict) and all(a in snap for a in AXES):
        return {a: str(snap[a]) for a in AXES}
    axes = t.get("value_trap_axes") or {}
    return {a: str(axes.get(a, {}).get("verdict", "?")) for a in AXES}


def trigger_counts(t: dict[str, Any]) -> tuple[int, int, int]:
    """(met, missed, total) — 트리거 충족률의 재료 (`docs/10` §6)."""
    trig = t.get("triggers") or []
    met = sum(1 for x in trig if x.get("status") == "met")
    missed = sum(1 for x in trig if x.get("status") == "missed")
    return met, missed, len(trig)


def invalidations_fired(t: dict[str, Any]) -> int:
    return sum(1 for x in (t.get("invalidations") or []) if x.get("status") == "fired")


# ---------------------------------------------------------------------------
# 필드 단위 diff — 논지 표류 추적 (docs/05 §6, docs/09 §2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldChange:
    path: str
    old: Any
    new: Any

    @property
    def kind(self) -> str:
        if self.old is _MISSING:
            return "+"
        if self.new is _MISSING:
            return "-"
        return "~"

    def render(self) -> str:
        if self.kind == "+":
            return f"+ {self.path}: {self.new!r}"
        if self.kind == "-":
            return f"- {self.path}: {self.old!r}"
        return f"~ {self.path}: {self.old!r} → {self.new!r}"


class _Missing:
    def __repr__(self) -> str:
        return "<없음>"


_MISSING = _Missing()


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """중첩 dict/list → 점 경로. 리스트는 인덱스로 편다 (순서 변경도 표류다)."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def diff_thesis(old: dict[str, Any], new: dict[str, Any]) -> list[FieldChange]:
    """두 thesis 스냅샷의 필드 단위 차이. 같은 필드는 나오지 않는다."""
    a, b = flatten(old), flatten(new)
    changes: list[FieldChange] = []
    for k in sorted(set(a) | set(b)):
        va, vb = a.get(k, _MISSING), b.get(k, _MISSING)
        if va is _MISSING or vb is _MISSING or va != vb:
            changes.append(FieldChange(k, va, vb))
    return changes


def render_diff(changes: list[FieldChange], *, old_label: str, new_label: str) -> str:
    head = [f"thesis diff: {old_label} → {new_label}", f"변경 필드 {len(changes)}개"]
    if not changes:
        return "\n".join([*head, "(차이 없음)"])
    core = [c for c in changes if c.path.split(".")[0].split("[")[0] in _DRIFT_FIELDS]
    lines = [*head]
    if core:
        lines.append(
            f"⚠ 논지 핵심 필드 변경 {len(core)}개 (claim/mechanism/triggers/invalidations/"
            "cycle_confidence) — 무효화 회피성 표류인지 사람이 판정한다"
        )
    lines.extend(c.render() for c in changes)
    return "\n".join(lines)


_DRIFT_FIELDS = frozenset(
    {"claim", "mechanism", "triggers", "invalidations", "cycle_confidence", "horizon_months"}
)
