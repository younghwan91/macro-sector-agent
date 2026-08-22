"""thesis 객체의 공용 — enum · 스키마 파일 · 읽기/쓰기 · 표류 diff.

L3(`l3/schema`·`l3/gates`·`l3/roles`·`l3/pipeline`)·L5(`l5/inputs`)·운영(`ops/thesis`·`ops/journal`·
`ops/state_files`)이 `docs/specs/thesis.schema.yaml` 의 같은 enum 을 각자 튜플로 들고 있었고,
`*.thesis.yaml` 을 읽는 `yaml.safe_load` 도 네 군데였다. **값·문자열·직렬화 옵션은 바꾸지 않았다** —
저장된 thesis 와 `journal/` 스냅샷이 이 문자열을 쓴다.

| 이름 | 스키마 위치 |
|---|---|
| `AXES` | `value_trap_axes` 5축 키 (`gate_result.axis_verdicts` 도 같은 키) |
| `AXIS_VERDICTS` | 축 `verdict` enum |
| `JUDGED_VERDICTS` | 그중 증거가 있어야 하는 판정 (`docs/05` §4) |
| `INVALIDATION_ACTIONS` | `invalidations[].action` |
| `TRIGGER_STATUS` · `INVALIDATION_STATUS` | `triggers[].status` · `invalidations[].status` |
| `GATE_STATUS` | `gate_result.status` |
| `REJECTION_PATHS` | `gate_result.path` = `rejections.yaml` 의 `path` 열 (`docs/09` §4) |
| `UNIT_SERIES_SOURCES` | `value_trap_axes.unit_demand.unit_series_source` |
| `RELIABILITY` | `evidence[].reliability` |
| `CONFIDENCE_PROVENANCE` | 저널 `confidence_provenance` (누가 c 를 산출했나, `docs/09` §2) |

이 모듈은 계층 패키지(`l1`~`l5`·`ops`)를 임포트하지 않는다 — 그들이 이것을 임포트한다.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from msa.config import REPO_ROOT

# ---------------------------------------------------------------- enum (스키마 파일과 같은 순서)

AXES: tuple[str, ...] = (
    "unit_demand",
    "capital_cycle",
    "substitution",
    "cost_curve",
    "terminal_risk",
)
AXIS_VERDICTS: tuple[str, ...] = ("cycle", "warning", "death", "contested", "not_applicable")
JUDGED_VERDICTS: tuple[str, ...] = ("cycle", "warning", "death")
INVALIDATION_ACTIONS: tuple[str, ...] = ("exit", "halve", "freeze_ladder")
TRIGGER_STATUS: tuple[str, ...] = ("pending", "met", "missed")
INVALIDATION_STATUS: tuple[str, ...] = ("pending", "fired")
GATE_STATUS: tuple[str, ...] = ("passed", "contested", "rejected")
REJECTION_PATHS: tuple[str, ...] = (
    "hard_gate",
    "conf_floor",
    "secular_risk",
    "rank_cutoff",
    "human",
)
UNIT_SERIES_SOURCES: tuple[str, ...] = ("physical_series", "revenue_proxy", "none")
RELIABILITY: tuple[str, ...] = ("high", "medium", "low")
CONFIDENCE_PROVENANCE: tuple[str, ...] = ("human", "referee")

# ---------------------------------------------------------------- 스키마 파일

SPEC_PATH = REPO_ROOT / "docs" / "specs" / "thesis.schema.yaml"


@functools.lru_cache(maxsize=4)
def load_spec(path: Path = SPEC_PATH) -> dict[str, Any]:
    """`docs/specs/thesis.schema.yaml` (required 목록·enum 의 정본). 호출자는 고치지 않는다."""
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(obj, dict)
    return obj


# ---------------------------------------------------------------- 파일 읽기/쓰기

THESIS_SUFFIX = ".thesis.yaml"

_Loader: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_Dumper: Any = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def thesis_filename(theme_id: str) -> str:
    """`<theme>.thesis.yaml` — `state/theses/<date>/` 와 `journal/` 스냅샷이 같은 꼴이다."""
    return f"{theme_id}{THESIS_SUFFIX}"


def read_thesis_yaml(path: Path | str) -> dict[str, Any]:
    """`*.thesis.yaml` → dict. 최상위가 매핑이 아니면 `ValueError` (빈 파일도 거부한다)."""
    p = Path(path)
    obj = yaml.load(p.read_text(encoding="utf-8"), Loader=_Loader)  # SafeLoader 계열만 쓴다
    if not isinstance(obj, Mapping):
        raise ValueError(f"{p}: thesis 최상위가 매핑이 아니다")
    return dict(obj)


def theses_in(round_dir: Path | str) -> list[Path]:
    """한 라운드 디렉터리(`state/theses/<date>/`)의 `*.thesis.yaml` — 이름순. 없으면 빈 목록."""
    d = Path(round_dir)
    if not d.is_dir():
        return []
    return sorted(d.glob(f"*{THESIS_SUFFIX}"))


def theme_of(path: Path | str) -> str:
    """`<theme>.thesis.yaml` → `<theme>`."""
    return Path(path).name.removesuffix(THESIS_SUFFIX)


def gate_status(thesis: Mapping[str, Any]) -> str | None:
    """`gate_result.status` — 없으면 None."""
    return (thesis.get("gate_result") or {}).get("status")


def dump_thesis_yaml(path: Path | str, thesis: Mapping[str, Any]) -> Path:
    """`yaml.safe_dump(thesis, allow_unicode=True, sort_keys=False, width=110)` 와 같은 텍스트를
    UTF-8 로 쓴다 (C 덤퍼가 있으면 그것으로 — 출력은 같다)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.dump(dict(thesis), Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=110),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------- 표류 diff (docs/05 §6 · 09 §2)

DIFF_FIELDS: tuple[str, ...] = (
    "claim",
    "mechanism",
    "horizon_months",
    "triggers",
    "invalidations",
    "cycle_confidence",
    "bear_case",
)


def _obs(x: Any) -> str:
    return str(x.get("observable", x)) if isinstance(x, dict) else str(x)


def thesis_diff(prior: Mapping[str, Any] | None, current: Mapping[str, Any]) -> dict[str, Any]:
    """이전 thesis 와의 필드별 차이 — 논지 표류 추적. L3 파이프라인이 리포트·`ResearchResult.diff`
    에 싣는다 (`ops/thesis.diff_thesis` 는 저널 스냅샷용 평탄 diff 로 별개다)."""
    if prior is None:
        return {"has_prior": False}
    out: dict[str, Any] = {
        "has_prior": True,
        "prior_generated_at": str(prior.get("generated_at")),
        "changed": [],
        "unchanged": [],
    }
    for f in DIFF_FIELDS:
        a, b = prior.get(f), current.get(f)
        if f in ("triggers", "invalidations"):
            a = [_obs(x) for x in (a or [])]
            b = [_obs(x) for x in (b or [])]
            added = [x for x in b if x not in a]
            removed = [x for x in a if x not in b]
            if added or removed:
                out["changed"].append(f)
                out[f] = {"added": added, "removed": removed}
            else:
                out["unchanged"].append(f)
        elif a != b:
            out["changed"].append(f)
            out[f] = {"before": a, "after": b}
        else:
            out["unchanged"].append(f)
    pa = (prior.get("gate_result") or {}).get("axis_verdicts") or {}
    ca = (current.get("gate_result") or {}).get("axis_verdicts") or {}
    ax_changed = {
        k: {"before": pa.get(k), "after": ca.get(k)} for k in ca if pa.get(k) != ca.get(k)
    }
    if ax_changed:
        out["changed"].append("axis_verdicts")
        out["axis_verdicts"] = ax_changed
    ps, cs = gate_status(prior), gate_status(current)
    if ps != cs:
        out["changed"].append("gate_status")
        out["gate_status"] = {"before": ps, "after": cs}
    # 무효화 회피 의심: 이전 무효화 조건이 사라졌는데 논지는 유지
    inv = out.get("invalidations", {})
    if isinstance(inv, dict) and inv.get("removed") and "claim" not in out["changed"]:
        out["drift_suspect"] = (
            "이전 invalidations 가 제거됐는데 claim 은 그대로 — 무효화 회피 의심 (05 §6)"
        )
    return out
