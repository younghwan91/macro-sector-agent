"""state 파일 — positions/watchlist 타입 로드, rejections 불변성."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import yaml

from msa.ops.state_files import (
    ImmutableRowChanged,
    LadderStep,
    Position,
    PositionsFile,
    Rejection,
    StateFileError,
    TpLevel,
    load_positions,
    load_rejections,
    load_watchlist,
    save_positions,
    save_rejections,
)


def _pos() -> Position:
    return Position(
        ticker="ccj",
        theme="uranium",
        role="anchor",
        target_weight=0.16,
        opened_at=date(2026, 9, 1),
        entry_price=50.0,
        ladder=[
            LadderStep(1, 0.5, 0.0, 50.0, date(2026, 9, 1), 50.0),
            LadderStep(2, 0.3, 0.13, 43.5),
            LadderStep(3, 0.2, 0.23, 38.5),
        ],
        tier2_stop_price=32.5,
        time_stop_date=date(2028, 3, 1),
        horizon_months=(6, 18),
        thesis_snapshot="journal/2026-09-01-uranium-entry.thesis.yaml",
        journal_entry="journal/2026-09-01-uranium-entry.md",
        tp=[TpLevel("tp1", 1 / 3, "+2R", price=85.0), TpLevel("runner", 1 / 3, "트레일")],
    )


def test_positions_roundtrip_and_avg_price(tmp_path: Path) -> None:
    p = tmp_path / "positions.yaml"
    save_positions(p, PositionsFile(date(2026, 9, 1), [_pos()]))
    pf = load_positions(p)
    pos = pf.positions[0]
    assert pos.ticker == "CCJ" and pos.horizon_months == (6, 18)
    assert pos.avg_price == 50.0 and not pos.tp1_filled
    pos.ladder[1].filled_price = 43.0
    assert pos.avg_price == pytest.approx((0.5 * 50 + 0.3 * 43) / 0.8)
    assert load_positions(tmp_path / "missing.yaml").positions == []


def test_positions_schema_violations_raise(tmp_path: Path) -> None:
    p = tmp_path / "positions.yaml"
    raw = {"asof": "2026-09-01", "positions": [{"ticker": "X", "theme": "t", "role": "hero"}]}
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(StateFileError, match="role"):
        load_positions(p)
    p.write_text(yaml.safe_dump({"nope": 1}))
    with pytest.raises(StateFileError):
        load_positions(p)


def test_watchlist_requires_waiting_condition(tmp_path: Path) -> None:
    p = tmp_path / "watchlist.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "watchlist": [
                    {
                        "theme": "copper",
                        "added_at": "2026-09-01",
                        "reason": "contested",
                        "waiting_condition": "  ",
                        "scan": "state/scans/2026-08-31/",
                    }
                ]
            }
        )
    )
    with pytest.raises(StateFileError, match="waiting_condition"):
        load_watchlist(p)
    assert load_watchlist(tmp_path / "none.yaml") == []


def _rej(**over: object) -> Rejection:
    kw: dict[str, object] = {
        "theme": "offshore_drilling",
        "rejected_at": date(2026, 8, 3),
        "path": "hard_gate",
        "reason": "축1 사망 AND 축3 경고",
        "cycle_confidence": 0.31,
        "scoreboard_rank": 3,
        "journal": "journal/2026-08-03-offshore_drilling-reject.md",
        "scan": "state/scans/2026-08-03/",
    }
    kw.update(over)
    return Rejection(**kw)  # type: ignore[arg-type]


def test_rejections_append_only_rows(tmp_path: Path) -> None:
    p = tmp_path / "rejections.yaml"
    save_rejections(p, [_rej()])
    rows = load_rejections(p)
    assert rows[0].r_12m is None and rows[0].path == "hard_gate"

    # 행 추가 — 자유
    save_rejections(p, [*rows, _rej(theme="coal", path="secular_risk")])
    assert len(load_rejections(p)) == 2

    # 기각 시점 필드 수정 — 거부
    rows = load_rejections(p)
    with pytest.raises(ImmutableRowChanged, match="기각 시점 필드"):
        save_rejections(p, [replace(rows[0], reason="생각이 바뀜"), rows[1]])
    with pytest.raises(ImmutableRowChanged):
        save_rejections(p, [replace(rows[0], path="human"), rows[1]])
    with pytest.raises(ImmutableRowChanged):
        save_rejections(p, [replace(rows[0], cycle_confidence=None), rows[1]])

    # 행 삭제 — 거부
    with pytest.raises(ImmutableRowChanged, match="삭제"):
        save_rejections(p, [rows[0]])

    # r_12m 채우기 — 허용 (null → 값)
    save_rejections(p, [replace(rows[0], r_12m=0.12), rows[1]])
    rows = load_rejections(p)
    assert rows[0].r_12m == pytest.approx(0.12)

    # 채워진 값 변경 — 거부
    with pytest.raises(ImmutableRowChanged, match="r_12m"):
        save_rejections(p, [replace(rows[0], r_12m=0.5), rows[1]])
    # 다시 null 로 — 거부
    with pytest.raises(ImmutableRowChanged):
        save_rejections(p, [replace(rows[0], r_12m=None), rows[1]])


def test_rejections_path_enum_and_confidence_key_required(tmp_path: Path) -> None:
    p = tmp_path / "rejections.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "rejections": [
                    {
                        "theme": "x",
                        "rejected_at": "2026-08-03",
                        "path": "meh",
                        "reason": "r",
                        "cycle_confidence": None,
                        "scoreboard_rank": 1,
                        "journal": "j",
                        "scan": "s",
                    }
                ]
            }
        )
    )
    with pytest.raises(StateFileError, match="path"):
        load_rejections(p)
    p.write_text(
        yaml.safe_dump(
            {
                "rejections": [
                    {
                        "theme": "x",
                        "rejected_at": "2026-08-03",
                        "path": "conf_floor",
                        "reason": "r",
                        "scoreboard_rank": 1,
                        "journal": "j",
                        "scan": "s",
                    }
                ]
            }
        )
    )
    with pytest.raises(StateFileError, match="cycle_confidence"):
        load_rejections(p)
