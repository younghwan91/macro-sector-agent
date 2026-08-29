def test_staleness_is_measured_in_trading_days_not_kst_calendar() -> None:
    """**KST 달력 날짜에서 미 거래일을 빼면 멀쩡한 데이터가 "낡음" 으로 나온다.**

    KST 는 동부보다 13~14시간 앞서고 벤더는 세션 다음날 낮에 올린다. 그래서 스토어가
    최신일 때도 달력으로는 이틀 차이가 난다.

    2026-08-29 실측: 스토어 08-27 이 그 시점에 **존재 가능한 마지막 세션**이었는데 문구는
    "2일 낡음" 이었다. 그 문구에 속아 크론 시각을 옮길 뻔했다 — 옮겼으면 DAG 가 돌기 전에
    실행돼 실제로 하루 더 낡은 데이터로 돌았다.
    """
    from msa.dates import last_possible_us_session

    newest = last_possible_us_session().isoformat()
    digest = {
        "asof": newest,
        "generated_at": "2026-08-29",  # KST 달력으로는 이틀 뒤
        "scan": {"store_end": newest},
        "themes": [],
        "judged": [],
    }
    from msa.ops.readme_block import render_block

    out = render_block(digest)
    assert "낡음" not in out, "존재 가능한 최신 세션인데 '낡음' 이라고 적으면 안 된다"
    assert "최신" in out
    assert "KST 달력 날짜와 다른 것은 정상이다" in out


def test_a_genuinely_behind_store_still_warns() -> None:
    """진짜로 뒤처지면 경고한다 — 오탐을 없애려다 진짜를 놓치면 안 된다."""
    digest = {
        "asof": "2026-01-05",
        "generated_at": "2026-08-29",
        "scan": {"store_end": "2026-01-05"},
        "themes": [],
        "judged": [],
    }
    from msa.ops.readme_block import render_block

    out = render_block(digest)
    assert "마지막 거래일보다 뒤처졌다" in out and "적재를 확인해라" in out


def test_readme_block_orders_pullbacks_by_triage() -> None:
    """triage 가 있으면 명단 순서가 **읽는 순서**다 (스펙 §6.1).

    낙폭 순서와 일부러 어긋나게 짰다 — `DEEP` 이 가장 깊지만 레드플래그로 C 가 깎여
    triage 가 낮다. 순서가 바뀌는 것이 이 기능의 전부이므로 갈리는 경우로 검사한다.
    """
    from msa.ops import readme_block as RB

    rows = [
        {"ticker": "DEEP", "theme": "th", "partition": "I-A", "triage": 0.60,
         "j": 0.74, "c": 0.70, "r": 0.70, "note": ""},
        {"ticker": "SHAL", "theme": "th", "partition": "I-A", "triage": 0.81,
         "j": 0.74, "c": 1.00, "r": 0.35, "note": ""},
    ]
    order = RB._triage_order({"triage": {"rows": rows}})
    assert order == {"DEEP": 0.60, "SHAL": 0.81}
    picks = [
        {"ticker": "DEEP", "from_52w_high": -0.45},
        {"ticker": "SHAL", "from_52w_high": -0.20},
    ]
    themes = [{"theme": "th", "thesis": {"portfolio_eligible": True}, "picks": picks}]
    assert [p["ticker"] for p in RB._pullbacks(themes)] == ["DEEP", "SHAL"], "낙폭 순"
    assert [p["ticker"] for p in RB._pullbacks(themes, order=order)] == ["SHAL", "DEEP"]


def test_readme_block_pullbacks_keep_drawdown_order_without_triage() -> None:
    """triage 가 없으면 기존 낙폭 순서를 그대로 둔다 — 없는 것을 있다고 말하지 않는다."""
    from msa.ops import readme_block as RB

    picks = [
        {"ticker": "SHAL", "from_52w_high": -0.20},
        {"ticker": "DEEP", "from_52w_high": -0.45},
    ]
    themes = [{"theme": "th", "thesis": {"portfolio_eligible": True}, "picks": picks}]
    assert [p["ticker"] for p in RB._pullbacks(themes)] == ["DEEP", "SHAL"]
    assert RB._triage_order({}) == {}
