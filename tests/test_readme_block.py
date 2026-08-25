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


def _digest(
    themes: list[dict[str, Any]], *, judged: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """`judged` 를 주지 않으면 상위 K 테마에서 만든다 (= 상위 K 밖에 아무것도 없는 경우)."""
    if judged is None:
        judged = [
            {
                "theme": t["theme"],
                "portfolio_eligible": (t["thesis"] or {}).get("portfolio_eligible", False),
                "cycle_confidence": (t["thesis"] or {}).get("cycle_confidence"),
                "in_top_k": True,
            }
            for t in themes
            if (t.get("thesis") or {}).get("found")
        ]
    return {
        "scan": {"asof": "2026-08-14", "store_end": "2026-08-14"},
        "themes": themes,
        "judged": judged,
    }


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
    assert "편입 가능 판정을 받은 테마가 없다" in block
    assert "TRAP" not in block, "탈락 테마의 종목이 결론에 올라왔다"
    assert "편입 불가" in block


def test_eligible_theme_pullbacks_are_surfaced() -> None:
    picks = [_pick("DEEP", -0.43), _pick("NEAR", -0.02)]
    block = render_block(_digest([_theme("live", picks=picks)]), today=TODAY)
    assert "차트 확인 대상 1종목" in block
    assert "`DEEP`" in block and "-43%" in block
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


# ---------------------------------------------------------------- 모집단 (상위 K 밖)


def test_eligible_theme_outside_top_k_is_not_lost() -> None:
    """상위 K 로 판별 결과를 세면 순위 밖의 편입 가능 테마가 사라진다.

    2026-08-25 실측: 통과 2개(`managed_care`·`shipping_container`)가 5위 밖이라
    결론이 "판별을 통과한 테마가 0개" 라는 **거짓**이 됐다. L1 순위(얼마나 잊혀졌나)와
    L3 판별(함정인가)은 다른 축이다.
    """
    top_k = [_theme("loud", rank=1, eligible=False, conf=0.45)]
    judged = [
        {"theme": "loud", "portfolio_eligible": False, "cycle_confidence": 0.45, "in_top_k": True},
        {"theme": "quiet", "portfolio_eligible": True, "cycle_confidence": 0.75, "in_top_k": False},
    ]
    block = render_block(_digest(top_k, judged=judged), today=TODAY)
    assert "0개" not in block
    assert "`quiet`" in block
    assert "상위 K 밖" in block


def test_no_judged_theme_says_so() -> None:
    block = render_block(
        _digest([_theme("raw", found=False, eligible=False)], judged=[]), today=TODAY
    )
    assert "아직 아무 테마도 판별하지 않았다" in block


# ---------------------------------------------------------------- 표시


def test_dip_list_is_not_sorted_by_depth() -> None:
    """낙폭 순 정렬은 "더 눌린 것이 더 볼 만하다" 는 근거 없는 주장이다."""
    picks = [
        {"ticker": "ZZZ", "from_52w_high": -0.90, "price": 0.64, "adv20_usd": 125_600},
        {"ticker": "AAA", "from_52w_high": -0.20, "price": 40.0, "adv20_usd": 12_000_000},
    ]
    block = render_block(_digest([_theme("t", picks=picks)]), today=TODAY)
    assert block.index("`AAA`") < block.index("`ZZZ`"), "테마·티커 순이어야 한다"
    assert "순서에 의미는 없다" in block or "볼 만한 순서가 아니다" in block
    assert "$125.6K" in block, "거래대금을 같이 실어야 껍데기를 알아볼 수 있다"


def test_red_flagged_dip_is_marked() -> None:
    picks = [
        {
            "ticker": "BAD",
            "from_52w_high": -0.85,
            "price": 0.64,
            "adv20_usd": 125_600,
            "red_flags": "zombie_streak",
        }
    ]
    block = render_block(_digest([_theme("t", picks=picks)]), today=TODAY)
    assert "⚠" in block and "zombie_streak" in block
    assert "레드플래그·감점이 붙은 것 1종목" in block


def test_stale_price_warning_sits_in_the_conclusion() -> None:
    """낡음 표시가 각주에만 있으면 결론과 같은 무게를 못 갖는다."""
    d = _digest([_theme("t", picks=[_pick("A", -0.3)])])
    block = render_block(d, today=date(2026, 8, 25))
    head = block.split("| # |")[0]
    assert "11일 낡음" in head


def test_flags_are_not_python_literals() -> None:
    t = _theme("t", picks=[_pick("A", -0.3)])
    t["flags"] = ["SECULAR — 게이트 필요", "no_etf_proxy"]
    block = render_block(_digest([t]), today=TODAY)
    assert "['SECULAR" not in block
    assert "SECULAR — 게이트 필요, no_etf_proxy" in block


def test_zero_picks_and_unknown_picks_are_different() -> None:
    judged_ok = [
        {"theme": "z", "portfolio_eligible": True, "cycle_confidence": 0.75, "in_top_k": True}
    ]
    zero = _theme("z", picks=[])
    block = render_block(_digest([zero], judged=judged_ok), today=TODAY)
    assert "| 0 |" in block

    unknown = _theme("z", picks=[])
    unknown["picks"] = None
    unknown["picks_error"] = "picks 실패"
    block2 = render_block(_digest([unknown], judged=judged_ok), today=TODAY)
    assert "| — |" in block2


def test_verdict_has_no_nested_bold() -> None:
    """결론은 렌더러가 굵게 감싼다 — 안에서 다시 `**` 를 쓰면 중첩돼 마크다운이 깨진다."""
    cases = [
        _digest([_theme("x", eligible=False, conf=0.45)]),
        _digest([_theme("x", picks=[_pick("A", -0.3)])]),
        _digest([_theme("x", picks=[_pick("A", -0.02)])]),
        _digest([_theme("x", picks=[])]),
        _digest(
            [_theme("loud", eligible=False)],
            judged=[
                {"theme": "loud", "portfolio_eligible": False, "in_top_k": True},
                {"theme": "quiet", "portfolio_eligible": True, "in_top_k": False},
            ],
        ),
    ]
    for d in cases:
        block = render_block(d, today=TODAY)
        head = next(x for x in block.splitlines() if x.startswith("> **"))
        assert head.count("**") == 2, f"굵게가 중첩됐다: {head}"


def test_untrusted_thesis_is_not_counted_as_eligible() -> None:
    """산출 주체 표기가 없는 논지는 편입으로 세지 않는다.

    2026-08-25 실측: `commodity_chem`(2026-08-23, 손으로 씀, conf 0.70 이지만
    `cycle_confidence_by`·`cycle_confidence_terms` 없음, 재도출하면 0.45/0.60)이
    저장 전 재도출 대조가 붙기 전 파일이라 검증을 피해 "편입 가능" 으로 결론에 들어왔다.
    """
    judged = [
        {"theme": "handwritten", "portfolio_eligible": False, "trusted": False, "in_top_k": True},
    ]
    block = render_block(
        _digest([_theme("handwritten", eligible=False)], judged=judged), today=TODAY
    )
    assert "편입 가능 판정을 받은 테마가 없다" in block
    assert "`handwritten`" not in block.split("| # |")[0]
