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
