"""느슨한 입력(CSV 셀·YAML 값·pandas 셀) → 선택적 스칼라.

`l3/contracts._f/_i/_b/_s`·`l5/inputs._opt_float/_opt_bool`·`ops/state_files._d` 가 같은 일을
조금씩 다른 꼴로 하고 있었다. 여기 것은 **"모르면 None"** 이 기본이고, 틀린 값을 거부해야 하는
호출자는 `require()` 로 빈 값을 예외로 바꾼다 (빈 값과 틀린 값은 다른 일이다).

`NA_TOKENS` 는 l5 가 CSV 에서 결측으로 치던 문자열 집합이다 — 값을 바꾸지 않았다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

#: 결측으로 읽는 문자열 (소문자 비교). `l5/inputs._opt_float` 의 집합 그대로.
NA_TOKENS: frozenset[str] = frozenset({"", "na", "nan", "none", "null", "—"})

_TRUE = frozenset({"true", "1", "1.0", "yes", "y"})
_FALSE = frozenset({"false", "0", "0.0", "no", "n", ""})


def _is_nan(v: Any) -> bool:
    return isinstance(v, float) and math.isnan(v)


def opt_str(v: Any) -> str | None:
    """None/NaN/공백 → None, 아니면 `str(v).strip()`."""
    if v is None or _is_nan(v):
        return None
    s = str(v).strip()
    return s or None


def opt_float(v: Any) -> float | None:
    """`float(v)` 가 되면 그 값(NaN 은 None), 아니면 None. `NA_TOKENS` 문자열도 None."""
    if v is None or _is_nan(v):
        return None
    if isinstance(v, str) and v.strip().lower() in NA_TOKENS:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def opt_int(v: Any) -> int | None:
    x = opt_float(v)
    return None if x is None else int(x)


def opt_bool(v: Any) -> bool | None:
    """true/1/yes/y · false/0/no/n/"" 문자열과 bool/숫자를 받는다. 모르는 문자열은 None."""
    if v is None or _is_nan(v):
        return None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        return None
    return bool(v)


def opt_date(v: Any, formats: Sequence[str] = ("%Y-%m-%d",)) -> date | None:
    """`date`(`datetime` 포함)는 그대로, 문자열은 `formats` 순서로 시도. 실패/빈 값이면 None."""
    if v is None or _is_nan(v):
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def require(d: Mapping[str, Any], key: str, ctx: str, exc: type[Exception] = ValueError) -> Any:
    """`d[key]` 가 없거나 None 이면 `exc` (문구는 `ops/state_files._req` 와 같다). 있으면 값."""
    if key not in d or d[key] is None:
        raise exc(f"{ctx}: 필수 필드 없음 `{key}`")
    return d[key]
