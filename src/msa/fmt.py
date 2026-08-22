"""리포트용 숫자 포맷 — NaN/None 안전.

`ops/alerts._pct`·`ops/check._fmt_pct`(`"n/a"`, 부호 있음)·`l5/plan._pct`(`"—"`, 부호 없음)·
`l1/backtest._fmt/_pct`(고정폭)·`l4/axes.fmt_ratio`(`"n/a"`·`"∞"`) 가 같은 일을 각자 들고 있었다.
여기 세 함수가 그 전부를 표현한다 — 기본값은 `ops` 쪽(`"n/a"`, `+.1%`) 이고 나머지는 인자로 맞춘다.
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


def ratio(x: Any, unit: str = "", digits: int = 1) -> str:
    """리포트용 비율·배수 (`l4/picks`). None/NaN 은 `n/a`, ±inf 는 `∞`, 숫자가 아니면 `str(x)`."""
    if x is None:
        return "n/a"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if math.isnan(v):
        return "n/a"
    if math.isinf(v):
        return "∞"
    return f"{v:.{digits}f}{unit}"
