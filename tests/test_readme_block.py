"""README "오늘의 결론" 블록 — 읽는 사람이 잘못 행동하지 않게 하는 것이 이 파일의 목적이다.

가장 중요한 검사는 **탈락한 테마의 종목을 세지 않는다** 이다. 2026-08-25 첫 판이 정확히
그 버그를 냈다: 게이트 `passed` 로 걸러서, 확신도 미달로 편입 불가인 테마 3개의 종목까지
"차트 볼 것 37종목" 에 넣었다. 사용자가 이전에 "내가 샀으면 어떡할뻔했어" 라고 한 그 사고다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from msa.ops.readme_block import (
    BEGIN,
    END,
    PULLBACK_MARK,
    MarkerMissing,
    render_block,
    update_readme,
)


def _theme(
    name: str,
    *,
    rank: int = 1,
    eligible: bool = True,
    found: bool = True,
    conf: float = 0.75,
    picks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tickers = [p["ticker"] for p in (picks or [])]
    return {
        "theme": name,
        "rank": rank,
        "score": 0.8,
        "flags": "",
        "eligible_tickers": tickers,
        "picks": picks or [],
        "thesis": {
            "found": found,
            # 게이트는 통과여도 편입은 불가일 수 있다 — 이 둘을 일부러 어긋나게 둔다
            "gate": "passed",
            "portfolio_eligible": eligible,
            "cycle_confidence": conf,
            "lines": [],
        },
    }


def _pick(ticker: str, from_high: float) -> dict[str, Any]:
    return {"ticker": ticker, "from_52w_high": from_high}


def _digest(themes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"scan": {"asof": "2026-08-14", "store_end": "2026-08-14"}, "themes": themes}


TODAY = date(2026, 8, 25)


# ---------------------------------------------------------------- 결론의 정확성


def test_rejected_themes_do_not_contribute_stocks() -> None:
    """게이트 passed 이지만 편입 불가인 테마의 종목은 **세지 않는다.**

    이 검사가 깨지면 가치 함정 판정을 받은 테마의 종목이 "차트 볼 것" 으로 올라온다.
    """
    dip = _pick("TRAP", -0.60)
    block = render_block(
        _digest([_theme("dead_theme", eligible=False, conf=0.45, picks=[dip])]), today=TODAY
    )
    assert "오늘 살 것은 없다" in block
    assert "TRAP" not in block, "탈락 테마의 종목이 결론에 올라왔다"
    assert "편입 불가" in block


def test_eligible_theme_pullbacks_are_surfaced() -> None:
    picks = [_pick("DEEP", -0.43), _pick("NEAR", -0.02)]
    block = render_block(_digest([_theme("live", picks=picks)]), today=TODAY)
    assert "차트를 볼 것은 1종목" in block
    assert "`DEEP` -43%" in block
    assert "NEAR" not in block  # 고점 근처는 결론에 올리지 않는다


def test_all_near_high_says_no_entry() -> None:
    picks = [_pick("A", -0.02), _pick("B", -0.05)]
    block = render_block(_digest([_theme("live", picks=picks)]), today=TODAY)
    assert "지금 들어갈 자리는 없다" in block
    assert f"−{abs(PULLBACK_MARK):.0%}" in block


def test_unjudged_theme_is_not_a_candidate() -> None:
    block = render_block(
        _digest([_theme("raw", found=False, eligible=False, picks=[_pick("X", -0.5)])]),
        today=TODAY,
    )
    assert "아직 아무 테마도 판별하지 않았다" in block
    assert "판별 안 함" in block
    assert "X" not in block.split("| # |")[0]  # 결론부에 없다


def test_eligible_but_empty_list_is_said_plainly() -> None:
    block = render_block(_digest([_theme("live", picks=[])]), today=TODAY)
    assert "명단이 비었다" in block


# ---------------------------------------------------------------- 표기


def test_table_shows_eligibility_not_gate_status() -> None:
    """표의 '판별' 열은 게이트 status 가 아니라 **편입 여부**를 쓴다."""
    block = render_block(
        _digest(
            [
                _theme("ok", rank=1, eligible=True, conf=0.75, picks=[_pick("A", -0.3)]),
                _theme("no", rank=2, eligible=False, conf=0.45),
            ]
        ),
        today=TODAY,
    )
    assert "**편입 가능** · 0.75" in block
    assert "편입 불가 · 0.45" in block
    assert "passed" not in block, "게이트 status 를 그대로 노출하면 통과로 오해된다"


def test_block_carries_no_performance_numbers() -> None:
    """`CLAUDE.md` §7 — 기대수익률·승률·수익 배수를 쓰지 않는다."""
    block = render_block(_digest([_theme("live", picks=[_pick("A", -0.3)])]), today=TODAY)
    for banned in ("수익률", "승률", "샤프", "Sharpe", "CAGR", "기대수익"):
        assert banned not in block


def test_store_lag_is_visible() -> None:
    d = _digest([_theme("live", picks=[_pick("A", -0.3)])])
    d["scan"]["store_end"] = "2026-08-14"
    block = render_block(d, today=date(2026, 8, 25))
    assert "11일 전" in block


# ---------------------------------------------------------------- 파일 교체


def test_update_replaces_only_between_markers(tmp_path: Path) -> None:
    p = tmp_path / "README.md"
    p.write_text(f"머리\n\n{BEGIN}\n옛 내용\n{END}\n\n꼬리\n", encoding="utf-8")
    assert update_readme(p, f"{BEGIN}\n새 내용\n{END}") is True
    got = p.read_text(encoding="utf-8")
    assert "머리" in got and "꼬리" in got and "새 내용" in got and "옛 내용" not in got
    # 같은 내용이면 쓰지 않는다 — 매일 도는 명령이 무의미한 diff 를 만들지 않게
    assert update_readme(p, f"{BEGIN}\n새 내용\n{END}") is False


def test_missing_marker_refuses_instead_of_appending(tmp_path: Path) -> None:
    """마커가 없으면 조용히 붙이지 않는다 — 어디에 쓸지는 사람이 정한다 (§2)."""
    p = tmp_path / "README.md"
    p.write_text("마커 없는 문서\n", encoding="utf-8")
    with pytest.raises(MarkerMissing):
        update_readme(p, "블록")
    assert p.read_text(encoding="utf-8") == "마커 없는 문서\n"
