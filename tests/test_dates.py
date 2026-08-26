# ------------------------------------------------- 미 동부 거래 세션


def test_last_possible_session_does_not_count_a_session_still_in_progress() -> None:
    """**KST 달력 날짜로 신선도를 재면 안 된다** (2026-08-27 실측 오탐).

    KST 는 동부보다 13~14시간 앞서므로, 미국 장이 열리기도 전에 "스토어가 하루 뒤졌다" 는
    경고가 난다. 그 로직이면 매일 00:00~18:00 KST 18시간 동안 계속 경고가 뜬다.
    quant-airflow 확인: 그때 동부는 8/26 오전이었고 스토어의 8/25 가 최신이 맞았다.
    """
    from datetime import UTC, date, datetime

    from msa.dates import last_possible_us_session

    # 2026-08-26 11:46 EDT (= KST 8/27 00:46) — 8/26 장이 아직 안 끝났다
    assert last_possible_us_session(datetime(2026, 8, 26, 15, 46, tzinfo=UTC)) == date(2026, 8, 25)
    # 2026-08-26 17:00 EDT (= KST 8/27 06:00) — 마감 뒤라 8/26 이 존재할 수 있다
    assert last_possible_us_session(datetime(2026, 8, 26, 21, 0, tzinfo=UTC)) == date(2026, 8, 26)


def test_last_possible_session_steps_back_over_the_weekend() -> None:
    """토·일은 세션이 아니다 — 월요일 아침이면 금요일이 최신이다."""
    from datetime import UTC, date, datetime

    from msa.dates import last_possible_us_session

    # 2026-08-31 은 월요일 · 09:00 ET → 마감 전이라 일요일 → 토요일 → 금요일 8/28
    assert last_possible_us_session(datetime(2026, 8, 31, 13, 0, tzinfo=UTC)) == date(2026, 8, 28)
    # 토요일 정오 ET → 금요일 8/28
    assert last_possible_us_session(datetime(2026, 8, 29, 16, 0, tzinfo=UTC)) == date(2026, 8, 28)
