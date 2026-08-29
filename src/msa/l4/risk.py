"""P4 리스크 매니저 + PM — 설계 §9.3. **점수를 바꾸지 않는다. 점수 뒤에 붙는다.**

이 모듈이 다른 셋(P1·P2·P3)과 다른 점이 그것이다. J·C·R 어디에도 손대지 않고, 이미 매겨진
순서 위에 **경고를 달고** **표시 슬롯을 나눈다.**

## 왜 점수를 안 깎는가

집중돼 있다는 사실은 *이 종목이 나쁘다* 는 말이 아니다. "상위 5 중 4 가 같은 테마" 는
**명단 전체의 성질**이고, 그것을 개별 종목의 점수에서 빼면 두 가지가 섞인다 — 그 종목이
읽을 만한가와, 이미 읽은 것들과 겹치는가. 사람이 판단한다는 역할 분담(2026-08-24)이
여기서도 그대로다: **기계는 겹친다고 말하고, 자를지는 사람이 정한다.**

## 리스크 매니저 — 무엇을 보는가

`state/themes.yaml` 의 `correlation_cluster` 를 쓴다. **새 분류를 만들지 않는다** — M2 가
이미 선언했고 `healthcare` 9 · `reit` 9 · `fossil` 7 … 로 채워져 있다.

가격 상관을 직접 계산하지 않는 것이 의도다. 60일 상관은 표본이 짧으면 요동치고, 길게 잡으면
오늘의 겹침을 못 본다. 어느 창을 고를지가 곧 자유도이고 그것이 `CLAUDE.md` §1 이 막는 것이다.
**선언된 군집은 자유도가 0 이다.**

## PM — 무엇을 하는가

테마별 **표시 슬롯 상한**이다. 한 테마가 상위 N 을 다 채우면 사람은 그 테마만 보게 된다.
슬롯 예산은 **J(판정 신뢰도)에 비례**한다 — 잘 아는 테마에 더 많은 슬롯. 자본 배분이 아니다
(그건 L5 SOCP 가 이미 한다).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: 한 구획의 표시 상위 몇 개를 보고 집중을 셀 것인가. **표시 상한이지 선정이 아니다.**
CONCENTRATION_WINDOW = 5

#: 그 창 안에서 한 테마·군집이 이만큼을 넘게 차지하면 경고를 단다.
#: **선언값이다** — 0.6 이어야 할 근거는 없고, "과반을 넘으면 사실상 한 베팅" 이라는
#: 서술을 숫자로 옮긴 것뿐이다.
CONCENTRATION_FRACTION = 0.6

#: PM 이 한 테마에 줄 수 있는 슬롯의 하한·상한. 하한이 1 인 것은 **판별을 통과한 테마를
#: 화면에서 통째로 지우지 않기 위해서**다 — 슬롯 0 은 "이 테마는 보지 마라" 가 되는데
#: 그 판정은 L3 게이트의 몫이지 PM 의 몫이 아니다.
SLOT_MIN = 1
SLOT_MAX = 5


@dataclass(frozen=True)
class Warning_:
    """경고 하나. **점수를 깎지 않는다** — 표시될 뿐이다."""

    kind: str
    text: str


def _fraction(counts: Mapping[str, int], total: int) -> list[tuple[str, int, float]]:
    return sorted(
        ((k, n, n / total) for k, n in counts.items() if total),
        key=lambda x: (-x[2], x[0]),
    )


def concentration_warnings(
    rows: Sequence[Mapping[str, Any]],
    clusters: Mapping[str, str],
    *,
    window: int = CONCENTRATION_WINDOW,
) -> list[Warning_]:
    """구획 상위 `window` 개의 테마·군집 집중을 본다.

    `clusters` 는 테마 → `correlation_cluster`. 모르는 테마는 **세지 않는다** — 없는 것을
    같은 군집으로 묶으면 가짜 집중이 만들어진다 (`CLAUDE.md` §2).
    """
    top = list(rows)[:window]
    if len(top) < 2:
        return []
    n = len(top)
    out: list[Warning_] = []

    themes: dict[str, int] = {}
    for r in top:
        themes[str(r.get("theme"))] = themes.get(str(r.get("theme")), 0) + 1
    for name, count, frac in _fraction(themes, n):
        if frac > CONCENTRATION_FRACTION:
            out.append(
                Warning_(
                    "theme_concentration",
                    f"상위 {n} 중 {count}개가 `{name}` 한 테마다 ({frac:.0%}) — "
                    "사실상 한 베팅이다",
                )
            )

    known = {str(r.get("theme")): clusters.get(str(r.get("theme"))) for r in top}
    groups: dict[str, int] = {}
    for r in top:
        c = known.get(str(r.get("theme")))
        if c:
            groups[c] = groups.get(c, 0) + 1
    counted = sum(groups.values())
    for name, count, _frac in _fraction(groups, counted):
        if counted and count / counted > CONCENTRATION_FRACTION and count > 1:
            out.append(
                Warning_(
                    "cluster_concentration",
                    f"상위 {counted}(군집을 아는 것 기준) 중 {count}개가 `{name}` 군집이다 — "
                    "테마는 달라도 같은 것에 걸린다",
                )
            )
    missing = [t for t, c in known.items() if not c]
    if missing:
        out.append(
            Warning_(
                "cluster_unknown",
                f"군집을 모르는 테마 {len(missing)}개는 집중 계산에서 빠졌다: "
                + " · ".join(f"`{t}`" for t in sorted(missing)),
            )
        )
    return out


def slot_budget(
    theme_trust: Mapping[str, float | None],
    *,
    slot_min: int = SLOT_MIN,
    slot_max: int = SLOT_MAX,
) -> dict[str, int]:
    """테마 → 표시 슬롯 수. **J 에 비례한다** — 잘 아는 테마에 더 많은 슬롯.

    J 가 계산 불가(`None`)인 테마는 `slot_min` 이다: 모르는 것을 0 으로 깎지도, 잘 아는
    것처럼 대접하지도 않는다.
    """
    out: dict[str, int] = {}
    for theme, j in theme_trust.items():
        if j is None:
            out[str(theme)] = slot_min
            continue
        span = slot_max - slot_min
        out[str(theme)] = slot_min + math.floor(max(0.0, min(1.0, j)) * span + 1e-9)
    return out


def apply_slots(
    rows: Sequence[Mapping[str, Any]], budget: Mapping[str, int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """슬롯을 넘긴 줄을 **뒤로 미룬다. 지우지 않는다.**

    반환은 `(안, 밖)` 이고 둘을 합치면 입력과 같다 — PM 은 화면을 나누는 것이지 명단을
    자르는 것이 아니다 (`journal/2026-08-24-l4-selection-retired.md` 의 정신).
    """
    used: dict[str, int] = {}
    inside: list[dict[str, Any]] = []
    outside: list[dict[str, Any]] = []
    for r in rows:
        theme = str(r.get("theme"))
        cap = budget.get(theme, SLOT_MAX)
        if used.get(theme, 0) < cap:
            used[theme] = used.get(theme, 0) + 1
            inside.append(dict(r))
        else:
            outside.append(dict(r))
    return inside, outside


def review(
    rows: Sequence[Mapping[str, Any]],
    clusters: Mapping[str, str],
    *,
    partition: str,
    window: int = CONCENTRATION_WINDOW,
) -> dict[str, Any]:
    """한 구획에 대한 리스크·PM 산출 묶음. **점수는 손대지 않는다.**"""
    part_rows = [r for r in rows if r.get("partition") == partition]
    trust: dict[str, float | None] = {}
    for r in part_rows:
        theme = str(r.get("theme"))
        if theme not in trust:
            trust[theme] = r.get("j")
    budget = slot_budget(trust)
    inside, outside = apply_slots(part_rows, budget)
    warns = concentration_warnings(part_rows, clusters, window=window)
    return {
        "partition": partition,
        "n": len(part_rows),
        "warnings": [{"kind": w.kind, "text": w.text} for w in warns],
        "slot_budget": budget,
        "shown": [str(r.get("ticker")) for r in inside],
        "deferred": [str(r.get("ticker")) for r in outside],
        "note": (
            "경고는 점수를 깎지 않는다 — 겹친다고 말할 뿐이고 자를지는 사람이 정한다. "
            "슬롯은 표시를 나누는 것이지 명단을 자르는 것이 아니다"
        ),
    }


def theme_clusters(themes: Iterable[Any]) -> dict[str, str]:
    """테마 → `correlation_cluster`. `msa.themes.load_themes()` 산출을 그대로 받는다."""
    return {t.id: t.correlation_cluster for t in themes if t.correlation_cluster}


def declared_constants() -> dict[str, Any]:
    return {
        "concentration_window": CONCENTRATION_WINDOW,
        "concentration_fraction": CONCENTRATION_FRACTION,
        "slot_min": SLOT_MIN,
        "slot_max": SLOT_MAX,
        "cluster_source": "state/themes.yaml 의 correlation_cluster — M2 선언, 자유도 0",
        "effect": "점수를 바꾸지 않는다. 경고를 달고 표시 슬롯을 나눈다 (설계 §9.3)",
    }
