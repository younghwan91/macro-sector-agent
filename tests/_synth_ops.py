"""운영 계층 테스트용 합성 입력 — 포지션·기각 행·가격 시리즈 (`make_thesis` 는 `conftest`)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from msa.ops.state_files import LadderStep, Position, Rejection, TpLevel

ASOF = date(2026, 12, 15)


def series(closes: list[float], end: date = ASOF) -> pd.Series:
    """`end` 에서 끝나는 영업일 인덱스의 종가 시리즈."""
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=len(closes))
    return pd.Series(closes, index=idx, dtype=float)


def make_position(**over: Any) -> Position:
    """CCJ 앵커 포지션 — 1단 50 체결, 2·3단 대기, TP1 가격 85, 시간스탑 2028-03-01."""
    kw: dict[str, Any] = {
        "ticker": "CCJ",
        "theme": "uranium",
        "role": "anchor",
        "target_weight": 0.16,
        "opened_at": date(2026, 9, 1),
        "entry_price": 50.0,
        "ladder": [
            LadderStep(1, 0.5, 0.0, 50.0, date(2026, 9, 1), 50.0),
            LadderStep(2, 0.3, 0.13, 43.5),
            LadderStep(3, 0.2, 0.23, 38.5),
        ],
        "tier2_stop_price": 32.5,  # 평단 50 × 0.65
        "time_stop_date": date(2028, 3, 1),
        "horizon_months": (6, 18),
        "thesis_snapshot": "journal/2026-09-01-uranium-entry.thesis.yaml",
        "journal_entry": "journal/2026-09-01-uranium-entry.md",
        "tp": [
            TpLevel("tp1", 1 / 3, "P50 또는 +2R", price=85.0),
            TpLevel("tp2", 1 / 3, "P75 또는 고점 50%"),
            TpLevel("runner", 1 / 3, "트레일 −25% / 10주선"),
        ],
    }
    kw.update(over)
    return Position(**kw)


def make_rejection(**over: Any) -> Rejection:
    """기각 대장 한 행 — `journal`·`scan` 은 theme/rejected_at 에서 만든다 (넘기면 그대로)."""
    kw: dict[str, Any] = {
        "theme": "offshore_drilling",
        "rejected_at": date(2026, 8, 3),
        "path": "hard_gate",
        "reason": "축1 사망 AND 축3 경고",
        "cycle_confidence": 0.31,
        "scoreboard_rank": 3,
    }
    kw.update(over)
    kw.setdefault("journal", f"journal/{kw['rejected_at']}-{kw['theme']}-reject.md")
    kw.setdefault("scan", f"state/scans/{kw['rejected_at']}/")
    return Rejection(**kw)
