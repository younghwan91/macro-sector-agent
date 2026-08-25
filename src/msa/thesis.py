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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from msa.config import REPO_ROOT, paths, rel
from msa.dates import parse_date

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


def all_theses(asof: str, root: Path | str | None = None) -> list[ThesisHead]:
    """`asof` 이하의 모든 라운드에서 **테마마다 최신 논지 하나씩**. 테마 id 순.

    `find_thesis` 와 같은 PIT 규칙(디렉터리 이름 ≤ asof, 최신 우선)이다.

    왜 필요한가: 일간 다이제스트는 **L1 상위 K** 테마만 싣는다. 그 모집단으로 "판별을 통과한
    테마" 를 세면 상위 K 밖의 통과 테마가 통째로 사라지고, 결론이 "통과 0개" 라는 거짓이
    된다 (2026-08-25 실측: 통과 2개가 순위 5위 밖이라 안 보였다). **L1 순위(얼마나
    잊혀졌나)와 L3 판별(함정인가)은 다른 축이다** — 후자를 셀 때는 후자의 모집단을 쓴다.
    """
    r = Path(root) if root is not None else paths().theses
    if not r.is_dir():
        return []
    seen: dict[str, ThesisHead] = {}
    for d in sorted((x for x in r.iterdir() if x.is_dir() and x.name <= asof), reverse=True):
        for f in theses_in(d):
            t = theme_of(f)
            if t not in seen:  # 최신 라운드가 먼저 온다
                seen[t] = thesis_head(t, asof, root=r)
    return [seen[k] for k in sorted(seen)]


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


# ---------------------------------------------------------------- 논지 머리 (명단 위에 붙는 것)


def find_thesis(theme_id: str, asof: str, root: Path | str | None = None) -> Path | None:
    """`state/theses/<date ≤ asof>/<theme>.thesis.yaml` 중 **최신**. 없으면 None.

    `pipeline.assemble._find_latest` 와 **같은 규칙**(날짜 디렉터리 이름 ≤ asof, 최신 우선)이다.
    거기서 옮겨 오지 않고 여기 둔 이유는 임포트 방향 — `assemble` 은 `l1`·`l4`·`l5` 를 임포트하고
    이 모듈은 계층 패키지를 임포트하지 않는다 (모듈 머리말). 규칙은 하나이고 구현이 둘이다.

    PIT 규약 그대로다: **asof 이후에 쓰인 논지는 찾지 않는다.** 그래서 오늘의 명단이 내일의
    논지를 달고 나오지 않는다.
    """
    base = Path(root) if root is not None else paths().theses
    if not base.is_dir():
        return None
    name = thesis_filename(theme_id)
    for d in sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        try:
            parse_date(d.name)
        except ValueError:
            continue
        if d.name > asof:
            continue
        f = d / name
        if f.exists():
            return f
    return None


#: 논지 없음일 때 명단 머리에 적는 문장 — 빈 줄을 두지 않는다 (`CLAUDE.md` §2).
NO_THESIS_NOTE = "논지 없음 — L3 미실행 (msa research <theme> 또는 사람 논지 yaml)"


@dataclass(frozen=True)
class ThesisHead:
    """명단 머리에 붙는 논지 요약 — 한 줄 논지 + 무효화 조건. 판정은 하나도 하지 않는다."""

    theme: str
    claim: str = ""
    invalidations: tuple[str, ...] = ()
    horizon_months: tuple[int, ...] = ()
    cycle_confidence: float | None = None
    #: `gate_result.status` — `passed`/`rejected`. **`passed` 는 "살 수 있다" 가 아니다.**
    gate: str | None = None
    #: `gate_result.portfolio_eligible` — **이것이 편입 여부다.** 게이트 조항에 안 걸려도
    #: 확신도가 기준선 미만이면 `passed` 이면서 `False` 다. 둘을 같은 것으로 읽으면
    #: 탈락한 테마의 종목이 "볼 만한 것" 으로 올라온다 (2026-08-25 실측: 4테마 중 3테마).
    portfolio_eligible: bool = False
    #: 게이트가 켠 L4 생존 플래그 (`gate_result.l4_survival_filter`). **L4 는 이것으로 종목을
    #: 자동 제외하지 않는다** — 테마 단위 판정이라 어느 종목인지 모른다. 사람이 명단의
    #: 부채 열을 직접 보라는 표시다. 예전에는 이 값이 게이트 dict 에만 남고 아무도 읽지
    #: 않았다 (2026-08-25, 선언-미구현).
    l4_survival_filter: bool = False
    source: str = ""  # 논지 파일 경로 (표시용)

    @property
    def found(self) -> bool:
        return bool(self.source)

    def lines(self, *, claim_chars: int = 220, max_invalidations: int = 4) -> list[str]:
        """리포트·다이제스트가 공유하는 머리 줄. **자른 것은 잘랐다고 적는다.**"""
        if not self.found:
            return [f"논지: {NO_THESIS_NOTE}"]
        head = [f"논지: {_clip(self.claim, claim_chars) or '(claim 비어 있음)'}"]
        meta = []
        if self.horizon_months:
            meta.append("지평 " + "~".join(str(h) for h in self.horizon_months) + "개월")
        if self.cycle_confidence is not None:
            meta.append(f"확신도 {self.cycle_confidence:g}")
        if self.gate:
            meta.append(f"게이트 {self.gate}")
        meta.append("편입 가능" if self.portfolio_eligible else "편입 불가")
        if self.l4_survival_filter:
            meta.append("축5 생존 경고")
        meta.append(self.source)
        head.append("  (" + " · ".join(meta) + ")")
        if not self.invalidations:
            head.append("무효화 조건: 없음 — 스키마상 있을 수 없다 (CLAUDE.md §5). 논지를 확인하라")
            return head
        if self.l4_survival_filter:
            head.append(
                "축5 경고: 24M 만기부채/시총이 크다고 판정됐다 — **자동 제외는 없다.** "
                "테마 단위 판정이라 어느 종목인지 모른다. 아래 표의 `net_debt_ebitda`·"
                "만기벽·`cash_runway_q` 를 직접 보라"
            )
        shown = self.invalidations[:max_invalidations]
        head.append("무효화 조건:")
        head += [f"  - {x}" for x in shown]
        if len(self.invalidations) > len(shown):
            head.append(f"  - … 외 {len(self.invalidations) - len(shown)}개 (전문은 {self.source})")
        return head


def _clip(s: str, n: int) -> str:
    t = " ".join(str(s or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def thesis_head(theme_id: str, asof: str, root: Path | str | None = None) -> ThesisHead:
    """테마의 논지 머리. 파일이 없으면 `found=False` 인 빈 머리 — 예외를 던지지 않는다.

    명단은 논지가 없어도 나온다 (논지는 L3 의 산출이고 L4 는 그것 없이도 돈다). 없다는 **사실**을
    적는 것이 여기서 하는 일의 전부이며, 어떤 판정도 바꾸지 않는다.
    """
    f = find_thesis(theme_id, asof, root)
    if f is None:
        return ThesisHead(theme_id)
    try:
        raw = read_thesis_yaml(f)
    except (OSError, ValueError):
        # 읽지 못한 것과 없는 것은 다르다 — 사유를 claim 자리에 남긴다 (조용히 없는 척하지 않는다)
        return ThesisHead(theme_id, claim=f"논지 파일을 읽지 못했다: {f}", source=str(f))
    hz = raw.get("horizon_months") or []
    if isinstance(hz, int | float):
        hz = [hz]
    conf = raw.get("cycle_confidence")
    return ThesisHead(
        theme=theme_id,
        claim=str(raw.get("claim") or ""),
        invalidations=tuple(_obs(x) for x in (raw.get("invalidations") or [])),
        horizon_months=tuple(int(h) for h in hz if isinstance(h, int | float)),
        cycle_confidence=float(conf) if isinstance(conf, int | float) else None,
        gate=gate_status(raw),
        portfolio_eligible=bool((raw.get("gate_result") or {}).get("portfolio_eligible", False)),
        l4_survival_filter=bool((raw.get("gate_result") or {}).get("l4_survival_filter", False)),
        source=rel(f),
    )


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
