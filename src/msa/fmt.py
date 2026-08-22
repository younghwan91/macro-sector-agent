"""리포트용 숫자 포맷 — NaN/None 안전.

`ops/alerts._pct`·`ops/check._fmt_pct`(`"n/a"`, 부호 있음)·`l5/plan._pct`(`"—"`, 부호 없음)·
`l1/backtest._fmt/_pct`(고정폭) 가 같은 일을 각자 들고 있었다. 여기 두 함수가 그 셋을 전부
표현한다 — 기본값은 `ops` 쪽(`"n/a"`, `+.1%`) 이고 나머지는 인자로 맞춘다.
"""

from __future__ import annotations

import math
from typing import Any


def _nan(x: Any) -> bool:
    if x is None:
        return True
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return True


def pct(x: Any, *, sign: bool = True, na: str = "n/a", nd: int = 1) -> str:
    """비율 → 백분율 문자열. `sign=True` 면 `+12.3%` 꼴, 아니면 `12.3%`. 결측은 `na`."""
    if _nan(x):
        return na
    v = float(x)
    return f"{v:+.{nd}%}" if sign else f"{v * 100:.{nd}f}%"


def num(x: Any, w: int = 6, p: int = 3) -> str:
    """고정폭 실수 (`l1/backtest._fmt`). 결측은 같은 폭의 `nan`."""
    if _nan(x):
        return f"{'nan':>{w}}"
    return f"{float(x):{w}.{p}f}"
