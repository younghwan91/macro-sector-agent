"""모순 감사 — `contradicts_when` 절 평가 (`docs/03-macro-dag.md` §6).

`contradicts_when` 은 서술이다. 기계가 읽을 수 있는 것은 **드라이버 상태 조건**뿐이므로, 그렇게
번역 가능한 엣지에만 선택 필드 `contradicts_rule` 을 둔다:

```yaml
contradicts_rule:
  all_of:                       # 전부 성립해야 플래그 (any_of 도 가능)
    - {driver: dollar_broad, state: 1}
    - {driver: gold_price, state: 1}
```

평가 결과 (엣지별 한 행):

| status | 뜻 |
|---|---|
| `FLAGGED` | 규칙 성립 — 선언된 메커니즘 밖의 국면. **사람이 본다.** 점수는 자동으로 안 바꾼다 |
| `NOT_FLAGGED` | 규칙 있음, 성립하지 않음 |
| `UNAVAILABLE` | 규칙의 드라이버 상태가 없어 판정 불가 (어느 드라이버인지 적는다) |
| `PROSE_ONLY` | 규칙 없음 — 서술만 있어 사람이 읽어야 한다 |

docs/03 §3 예시의 "자동 점수 계산에서 제외 플래그" 는 **플래그**까지다. 제외를 자동으로 하면
선언이 국면마다 자동 조정되는 셈이라 여기서는 하지 않는다 — 리포트에 올리고 사람이 판단한다.
상관 기반 플래그(§6 1~3항)는 `signcheck.py` 가 낸다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from msa.l2.dag import Edge, MacroDag


def _eval_conditions(
    conds: list[Mapping[str, Any]], state_row: pd.Series
) -> tuple[list[bool], list[str]]:
    hits: list[bool] = []
    unavailable: list[str] = []
    for c in conds:
        drv = str(c.get("driver", ""))
        want = c.get("state")
        st = float(state_row.get(drv, np.nan))
        if not np.isfinite(st):
            unavailable.append(drv)
            continue
        if isinstance(want, list):
            hits.append(any(st == float(w) for w in want))
        else:
            hits.append(want is not None and st == float(want))
    return hits, unavailable


def evaluate_rule(rule: Mapping[str, Any], state_row: pd.Series) -> tuple[str, str]:
    """→ (status, detail). `all_of` / `any_of` 중 하나를 받는다."""
    if "all_of" in rule:
        conds = list(rule["all_of"])
        hits, unav = _eval_conditions(conds, state_row)
        if unav:
            return "UNAVAILABLE", f"상태 없음: {', '.join(unav)}"
        return ("FLAGGED" if all(hits) else "NOT_FLAGGED"), _fmt(conds, state_row)
    if "any_of" in rule:
        conds = list(rule["any_of"])
        hits, unav = _eval_conditions(conds, state_row)
        if any(hits):
            return "FLAGGED", _fmt(conds, state_row)
        if unav:
            return "UNAVAILABLE", f"상태 없음: {', '.join(unav)}"
        return "NOT_FLAGGED", _fmt(conds, state_row)
    return "UNAVAILABLE", f"알 수 없는 규칙 형식: {sorted(rule)}"


def _fmt(conds: list[Mapping[str, Any]], state_row: pd.Series) -> str:
    parts = []
    for c in conds:
        drv = str(c.get("driver", ""))
        st = state_row.get(drv, np.nan)
        parts.append(f"{drv}={st:+.0f}(요구 {c.get('state')})")
    return ", ".join(parts)


def evaluate_contradictions(dag: MacroDag, state_row: pd.Series) -> pd.DataFrame:
    recs: list[dict[str, Any]] = []
    e: Edge
    for e in dag.edges:
        if not e.contradicts_when and e.contradicts_rule is None:
            continue
        if e.contradicts_rule is None:
            status, detail = "PROSE_ONLY", "규칙 없음 — 사람이 읽는다"
        else:
            status, detail = evaluate_rule(e.contradicts_rule, state_row)
        recs.append(
            {
                "edge": e.index,
                "from": e.source,
                "to": "*" if e.wildcard else ",".join(e.targets),
                "sign": e.sign,
                "strength": e.strength,
                "status": status,
                "detail": detail,
                "contradicts_when": e.contradicts_when,
            }
        )
    return pd.DataFrame(
        recs,
        columns=["edge", "from", "to", "sign", "strength", "status", "detail", "contradicts_when"],
    )


def summarize(df: pd.DataFrame) -> dict[str, int]:
    return {
        s: int((df["status"] == s).sum())
        for s in ("FLAGGED", "NOT_FLAGGED", "UNAVAILABLE", "PROSE_ONLY")
    }
