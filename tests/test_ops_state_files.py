"""state 파일 — positions/watchlist 타입 로드, rejections 불변성."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import yaml

from _synth_ops import make_position
from _synth_ops import make_rejection as _rej
from msa.ops.state_files import (
    ImmutableRowChanged,
    Position,
    PositionsFile,
    StateFileError,
    TpLevel,
    load_positions,
    load_rejections,
    load_watchlist,
    save_positions,
    save_rejections,
)


def _pos() -> Position:
    # 소문자 티커 — 로드 시 대문자로 정규화되는지 본다
    return make_position(
        ticker="ccj",
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
    # 틀린 날짜 문자열은 조용히 date.min 이 되지 않는다
    raw = {"asof": "2026-09-01", "positions": [{"ticker": "X", "theme": "t", "role": "anchor"}]}
    raw["positions"][0].update(
        target_weight=0.1,
        opened_at="2026/09/01",
        entry_price=1.0,
        ladder=[{"step": 1, "weight": 1.0, "trigger_pct": 0.0}],
        tier2_stop_price=0.5,
        time_stop_date="2027-01-01",
        horizon_months=[6, 18],
        thesis_snapshot="j",
        journal_entry="j",
    )
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(StateFileError, match="날짜 형식"):
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
