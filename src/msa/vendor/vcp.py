"""VCP(변동성 수축 패턴) 피벗·수축 분해 — `momentum` 저장소에서 벤더링.

출처: https://github.com/younghwan91/momentum
파일: VCP.py (find_pivots · compress_pivots · build_contractions)
커밋: 93742634e42f4175192aad17de637a0df5376003
복사: 2026-08-23 (M3).

**지수 레벨 승격** (`docs/02-cycle-state.md` §B): 원본은 개별 종목의 OHLCV 에 돌며
돌파 확인·거래량 확장까지 한 번에 판정한다. 테마 지수에는 고가·저가가 없고 "매수 시점" 이
아니라 "매도 압력 소진의 정도" 가 필요하므로, 여기서는 **피벗 탐지와 수축 분해**만 가져오고
단조 감소 점수는 `msa.l1.blocks` 가 계산한다. 함수 본문은 원본과 동일하며 타입 힌트와
`Close` 단일 컬럼 사용만 덧붙였다 (원본도 `detect_vcp_with_pivot` 에서 `Close` 를 고가·저가
양쪽에 넣어 호출한다).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

Pivot = tuple[Any, str, float]


def find_pivots(close: pd.Series, left: int = 3, right: int = 3) -> list[Pivot]:
    """local pivot highs/lows using window comparison.

    pivot high: close[t] is max in [t-left .. t+right]
    pivot low : close[t] is min in [t-left .. t+right]
    """
    n = len(close)
    vals = close.to_numpy(dtype=float)
    idx = close.index
    pivots: list[Pivot] = []
    for i in range(left, n - right):
        win = vals[i - left : i + right + 1]
        if vals[i] == win.max():
            pivots.append((idx[i], "H", float(vals[i])))
        if vals[i] == win.min():
            pivots.append((idx[i], "L", float(vals[i])))
    pivots.sort(key=lambda x: x[0])
    return pivots


def compress_pivots(pivots: list[Pivot]) -> list[Pivot]:
    """연속된 같은 타입(H 연속, L 연속)은 H 는 더 높은 것, L 은 더 낮은 것만 남긴다 → H/L/H/L…"""
    if not pivots:
        return []
    out = [pivots[0]]
    for t, typ, price in pivots[1:]:
        _lt, ltyp, lprice = out[-1]
        if typ != ltyp:
            out.append((t, typ, price))
        elif (typ == "H" and price >= lprice) or (typ == "L" and price <= lprice):
            out[-1] = (t, typ, price)
    return out


def build_contractions(
    pivots: list[Pivot], ref_level: float, tol: float = 0.1, max_drop_from_ref: float = 0.60
) -> list[dict[str, Any]]:
    """H→L 쌍을 수축으로 만든다. H 가 `ref_level` 근처(tol 이내)일 때만 인정한다."""
    cons: list[dict[str, Any]] = []
    for i in range(len(pivots) - 1):
        t1, typ1, p1 = pivots[i]
        t2, typ2, p2 = pivots[i + 1]
        if typ1 == "H" and typ2 == "L":
            if p1 < ref_level * (1 - tol):
                continue
            depth = (p1 - p2) / p1
            rec: dict[str, Any] = {
                "peak_t": t1,
                "peak": p1,
                "trough_t": t2,
                "trough": p2,
                "depth": depth,
            }
            if p2 < ref_level * (1 - max_drop_from_ref):
                rec["warning"] = "TOO_DEEP"
            cons.append(rec)
    return cons
