"""증거 처리 대장 — 사람이 원문을 열어 확인한 결과를 남기는 자리.

2026-08-25 실사에서 표본의 20% 가 원문에 없는 숫자였다. 리포트는 "먼저 열 것" 을 찍어
주지만(`l3.evidence_triage`), **사람이 열어서 확인한 결과가 남을 곳이 없었다.** 그래서
같은 문서를 매일 다시 열게 되고, 결국 아무도 안 연다. 이 모듈이 그 자리다.

`journal/` 과 같은 append-only 규약이다 (`CLAUDE.md` §6) — 같은 `evidence_id` 를 다시 쓰지
못한다. 생각이 바뀌면 항목을 고치는 것이 아니라 **재판별**(`msa research`)이다. 대장을
고칠 수 있으면 대장이 검증하는 대상이 대장 자신이 되어 버린다.

## 판정 셋의 뜻 (임계를 만들지 않는다)

| verdict | 뜻 | 점수에 미치는 영향 (`triage.theme_trust`) |
|---|---|---|
| `confirmed` | 원문에서 그 숫자를 찾았다 | `verified` 로 계상 → 증거품질이 오른다 |
| `refuted` | 원문에 없거나 다른 뜻이다 | **J 상한이 `EVIDENCE_CAP_REFUTED`(0.25) 로** |
| `unresolvable` | 열었지만 판단 못 하겠다 (페이월·모호) | **아무 영향 없음** |

`unresolvable` 이 아무것도 안 하는 것이 의도다 — 사람이 시간을 썼다는 사실이 증거를
검증하지는 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

#: 사람이 낼 수 있는 판정. 비율·임계를 두지 않는다 — 셋 중 하나다.
VERDICTS = ("confirmed", "refuted", "unresolvable")


@dataclass(frozen=True)
class Resolution:
    """대장 한 줄. `evidence_id` 는 그 테마 thesis 안의 증거 번호다.

    `supersedes` 가 참이면 **같은 `evidence_id` 의 앞 기록을 대체한다.** 앞 기록을 지우지
    않고 뒤에 덧붙이므로 append-only 가 유지된다 — `journal/` 이 "생각이 바뀌면 새 항목을
    추가하고 이전 항목을 링크한다" 고 하는 것과 같은 방식이다 (`CLAUDE.md` §6).

    이 필드가 필요했던 이유: 2026-08-29 에 `managed_care` [17] 을 `unresolvable`(403)로
    적었는데, 나중에 같은 문서가 열려 **판정이 뒤집혔다.** 고칠 수 없고 다시 쓸 수도 없으면
    대장은 첫 판정에 영원히 묶인다.
    """

    evidence_id: int
    resolved_by: str
    date: str
    verdict: str
    note: str = ""
    supersedes: bool = False


def path_for(root: Path, theme: str) -> Path:
    return Path(root) / f"{theme}.yaml"


def load(root: Path, theme: str) -> list[Resolution]:
    """대장 **전문**을 파일 순서 그대로 읽는다 (승계된 옛 기록 포함)."""
    p = path_for(root, theme)
    if not p.exists():
        return []
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return [Resolution(**dict(r)) for r in raw]


def effective(root: Path, theme: str) -> list[Resolution]:
    """**오늘 유효한 판정만** — 같은 `evidence_id` 는 마지막 기록이 이긴다.

    점수(`triage.theme_trust`)가 읽는 것은 이것이다. `load` 는 이력 전문이라 옛 판정이
    섞여 있고, 그것을 그대로 점수에 넣으면 뒤집힌 판정이 두 번 세어진다.
    """
    latest: dict[int, Resolution] = {}
    for e in load(root, theme):
        latest[e.evidence_id] = e
    return [latest[k] for k in sorted(latest)]


def append(root: Path, theme: str, entry: Resolution) -> Path:
    """항목 하나를 덧붙인다. **덮어쓰기는 거부한다** (`CLAUDE.md` §6)."""
    if entry.verdict not in VERDICTS:
        raise ValueError(f"verdict 는 {VERDICTS} 중 하나여야 한다: {entry.verdict!r}")
    existing = load(root, theme)
    if any(e.evidence_id == entry.evidence_id for e in existing) and not entry.supersedes:
        raise ValueError(
            f"evidence_id {entry.evidence_id} 는 이미 있다 — 대장은 append-only 다. "
            "판정이 뒤집혔으면 `supersedes=True` 로 **덧붙여라** (앞 기록은 남는다). "
            "앞 기록을 지우거나 고치는 경로는 없다"
        )
    if entry.supersedes and not any(e.evidence_id == entry.evidence_id for e in existing):
        raise ValueError(
            f"evidence_id {entry.evidence_id} 는 대장에 없다 — 승계할 앞 기록이 없으면 "
            "`supersedes=True` 를 붙이지 않는다"
        )
    p = path_for(root, theme)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(e) for e in [*existing, entry]]
    p.write_text(yaml.safe_dump(rows, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def summary(entries: Sequence[Resolution]) -> dict[str, int]:
    """판정별 건수. 세 칸은 항상 있다 — 0 건도 사실이다.

    **유효 판정을 세려면 `effective()` 의 결과를 넘긴다.** `load()` 를 그대로 넘기면
    승계된 옛 판정까지 세어진다.
    """
    return {v: sum(1 for e in entries if e.verdict == v) for v in VERDICTS}
