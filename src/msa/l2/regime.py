"""매크로 레짐 — `cycle_class` 8칸에 대한 3값 판정과 그 저장·검증.

설계·금지는 `docs/25-design-question-macro-regime.md`. 이 모듈이 지키는 것 셋:

1. **8칸을 늘리거나 쪼개지 않는다.** `cycle_class` 는 `state/themes.yaml` 이 M2 에서 이미
   선언한 것이고 이 모듈이 만들지 않는다. 자유도가 8×3 으로 고정되는 것이 제거된 L2 와의
   결정적 차이다 (`docs/25` §3.1).
2. **무효화 조건·증거가 없으면 저장되지 않는다** — L3 계약을 그대로 승계한다
   (`CLAUDE.md` §3·§5). 새 스키마 규약을 발명하지 않는다.
3. **레짐은 R 축에만 곱한다.** J·C·구획은 못 건드린다 (`docs/25` §3.3). 그 강제는
   `msa.triage` 쪽에 있고, 테스트가 양쪽을 다 본다.

레짐이 없으면 계수는 **1.0** 이다 — 없는 것을 역풍으로 읽지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from msa.errors import Rejected
from msa.themes import CYCLE_CLASSES as _THEME_CYCLE_CLASSES

#: 판정 3값. 늘리지 않는다 (`docs/25` §5).
VERDICTS = ("tailwind", "neutral", "headwind")

#: 판정 → R 축 계수. **선언값이고 근거가 없다** (`docs/25` §3.4).
#: `msa.basis` 에 `NoBasis` 로 등록돼 있어 값을 바꾸면 CI 가 근거도 고치라고 막는다.
#: 아무것도 자르지 않으므로 `hard`·`gate` 태그는 붙이지 않았다.
REGIME_TILT = {"tailwind": 1.00, "neutral": 0.85, "headwind": 0.70}

#: 판정을 붙일 수 있는 칸 — **`msa.themes` 의 것을 그대로 쓴다.**
#:
#: 여기서 다시 나열하면 `state/themes.yaml` 이 바뀔 때 한쪽만 고치고 아무도 모른다.
#: `msa.basis` 의 `test_values_that_must_agree_have_one_source` 가 `is` 로 검사하는 것과
#: 같은 규약이다 — 값이 같은 것으로는 부족하고 **같은 객체**여야 따로 옮길 수 없다.
CYCLE_CLASSES = _THEME_CYCLE_CLASSES

_URL = re.compile(r"^https?://\S+$")


class RegimeRejected(Rejected, ValueError):
    """레짐 문서가 계약을 어겼다 — 저장하지 않는다."""


def tilt_for(verdict: str | None) -> float:
    """판정 → 계수. 없으면 1.0, 모르는 값이면 **거부한다**.

    모르는 값을 조용히 중립으로 떨어뜨리면 오타 하나가 판정을 바꾼다 (`CLAUDE.md` §2).
    """
    if not verdict:
        return 1.0
    if verdict not in REGIME_TILT:
        raise ValueError(f"verdict 는 {VERDICTS} 중 하나여야 한다: {verdict!r}")
    return REGIME_TILT[verdict]


def _check_class(name: str, body: Any) -> None:
    if name not in CYCLE_CLASSES:
        raise RegimeRejected(
            f"모르는 cycle_class: {name!r} — 8칸을 늘리지 않는다 (docs/25 §5). "
            f"허용: {CYCLE_CLASSES}"
        )
    if not isinstance(body, Mapping):
        raise RegimeRejected(f"{name}: 본문이 매핑이 아니다")
    if body.get("verdict") not in VERDICTS:
        raise RegimeRejected(f"{name}: verdict 는 {VERDICTS} 중 하나여야 한다")
    if not str(body.get("mechanism") or "").strip():
        raise RegimeRejected(f"{name}: mechanism 이 비었다 — 왜 그렇게 보는지는 적어야 한다")
    if not list(body.get("invalidations") or []):
        raise RegimeRejected(
            f"{name}: invalidations 가 비었다 — 무효화 조건 없는 판정은 판정이 아니라 "
            "희망이다 (CLAUDE.md §5)"
        )
    ev = list(body.get("evidence") or [])
    if not ev:
        raise RegimeRejected(
            f"{name}: evidence 가 비었다 — LLM 의 기억은 증거가 아니다 (CLAUDE.md §3)"
        )
    for i, e in enumerate(ev):
        url = str((e or {}).get("source_url") or "")
        if not _URL.match(url):
            raise RegimeRejected(f"{name}: evidence[{i}] 의 source_url 이 URL 이 아니다: {url!r}")
        if not str((e or {}).get("claim") or "").strip():
            raise RegimeRejected(f"{name}: evidence[{i}] 의 claim 이 비었다")


def validate(doc: Mapping[str, Any]) -> None:
    """레짐 문서를 검증한다. 어기면 `RegimeRejected` — 저장 전에 부른다."""
    if not str(doc.get("week") or "").strip():
        raise RegimeRejected("week 이 비었다 (예: 2026-W35)")
    classes = doc.get("classes")
    if not isinstance(classes, Mapping) or not classes:
        raise RegimeRejected("classes 가 비었다 — 판정이 하나도 없는 문서는 저장하지 않는다")
    for name, body in classes.items():
        _check_class(str(name), body)


def path_for(root: Path, week: str) -> Path:
    return Path(root) / f"{week}.yaml"


def write(root: Path, doc: Mapping[str, Any]) -> Path:
    """검증 후 저장. **덮어쓰기는 허용한다** — 같은 주를 다시 돌리는 것은 정정이지 위조가
    아니고, 판정 이력은 `journal/` 이 아니라 주별 파일이 진다."""
    validate(doc)
    p = path_for(root, str(doc["week"]))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(dict(doc), allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def read(root: Path, week: str) -> dict[str, Any] | None:
    """주간 레짐 문서. 없으면 None — 그러면 계수가 전부 1.0 이 된다."""
    p = path_for(root, week)
    if not p.exists():
        return None
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    return dict(raw) if isinstance(raw, Mapping) else None


def latest(root: Path) -> dict[str, Any] | None:
    """가장 최근 주의 레짐. 파일명이 ISO 주(`YYYY-Www`)라 사전순 = 시간순이다."""
    root = Path(root)
    if not root.exists():
        return None
    files = sorted(root.glob("*.yaml"))
    if not files:
        return None
    raw: Any = yaml.safe_load(files[-1].read_text(encoding="utf-8"))
    return dict(raw) if isinstance(raw, Mapping) else None


def tilts_by_theme(
    doc: Mapping[str, Any] | None, theme_classes: Mapping[str, str]
) -> dict[str, float]:
    """테마 → R 계수. `theme_classes` 는 테마 → `cycle_class` 다.

    문서가 없거나 그 칸의 판정이 없으면 **1.0** 이다 — 빠진 것을 역풍으로 읽지 않는다.
    """
    if (doc or {}).get("synthetic"):
        # **합성 레짐(--dry-run)은 계수를 만들지 않는다.** 경로 검증용 값이 실제 읽는
        # 순서를 조용히 바꾸면 --dry-run 이 dry 가 아니게 된다.
        doc = None
    classes = (doc or {}).get("classes") or {}
    out: dict[str, float] = {}
    for theme, cls in theme_classes.items():
        body = classes.get(cls) if isinstance(classes, Mapping) else None
        verdict = (body or {}).get("verdict") if isinstance(body, Mapping) else None
        out[str(theme)] = tilt_for(verdict if verdict else None)
    return out


def declared_constants() -> dict[str, Any]:
    return {
        "regime_tilt": dict(REGIME_TILT),
        "cycle_classes": list(CYCLE_CLASSES),
        "cadence": (
            "weekly — 매일 돌리지 않는다 "
            "(docs/25 §4.3: 같은 날 두 번 돌리면 재현성을 잃는다)"
        ),
        "applies_to": "트리아지 R 축에만 곱한다. J·C·구획은 못 건드린다 (docs/25 §3.3)",
        "claim": "읽는 순서를 민다 — 수익률을 주장하지 않는다 (docs/25 §3)",
    }
