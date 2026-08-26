"""월말·기준일 계산의 단일 구현.

L1(`fundamentals.month_ends`)·L3(`_months_between`)·
CLI(`_parse_date`) 가 각자 같은 계산을 들고 있었다. 한 곳에 두고 전부 여기서 가져간다 —
월말 라벨 규약이 계층마다 조금씩 달라지면 `Indicators.bucket_for` 와 백테스트 라벨이 어긋난다
(`docs/10` §2). 값·규약은 바꾸지 않았다.

월말 라벨은 전부 pandas 의 `"ME"`(month end) 이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.tseries.offsets import MonthEnd

DATE_FMT = "%Y-%m-%d"


DateLike = str | pd.Timestamp | date


def month_ends(start: DateLike, end: DateLike) -> pd.DatetimeIndex:
    """`[start, end]` 안의 월말 격자 (`freq="ME"`). 끝이 월말이 아니면 그 달은 **안 들어간다.**"""
    return pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="ME")


def month_end_label(ts: DateLike) -> pd.Timestamp:
    """임의 날짜 → 그 달의 월말 라벨 (`ts + MonthEnd(0)`). 월말이면 그대로."""
    return pd.Timestamp(ts) + MonthEnd(0)


def last_month_end(asof: DateLike) -> pd.Timestamp:
    """`asof` **이하의** 마지막 월말. 8/23 이면 7/31 — 그 달이 끝나야 월말 값이 있다."""
    a = pd.Timestamp(asof)
    me = a + MonthEnd(0)
    return me if me == a else a - MonthEnd(1)


def to_month_end[T: (pd.Series, pd.DataFrame)](x: T) -> T:
    """임의 주기 → 월말 마지막 관측. 월 안에 관측이 없으면 NaN 으로 남긴다 (앞으로 안 채운다)."""
    return x.resample("ME").last()


def months_between(a: date, b: date) -> int:
    """달력 개월 차 `b − a` (일자는 무시한다). 1/31 → 2/1 은 1."""
    return (b.year - a.year) * 12 + (b.month - a.month)


def parse_date(s: str, formats: Sequence[str] = (DATE_FMT,)) -> date:
    """문자열 → `date`. `formats` 를 차례로 시도하고 전부 실패하면 `ValueError`.

    추정하지 않는다 — 모호한 입력(`"2026-8"`)은 호출자가 허용 포맷을 넓혀야 통과한다.
    """
    raw = s.strip()
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"날짜 형식이 아니다: {s!r} (허용 {list(formats)})")


def asof_or_today(s: str | None) -> date:
    """CLI `--asof` 규약: 빈 문자열/None 이면 오늘, 아니면 `YYYY-MM-DD`."""
    return date.today() if not s or not s.strip() else parse_date(s)


#: 미 주식 정규장 마감 (동부). 세션 D 의 종가는 이 시각 이후에야 존재한다.
US_CLOSE_HOUR_ET = 16


def last_possible_us_session(now: datetime | None = None) -> date:
    """**지금 시점에 데이터가 존재할 수 있는 마지막 미 동부 거래일.**

    스토어 신선도를 로컬(KST) 달력 날짜와 비교하면 안 된다 — KST 는 동부보다 13~14시간
    앞서므로, 미국 장이 열리기도 전에 "스토어가 하루 뒤졌다" 는 오탐이 난다. 실제로
    2026-08-27 KST 실행에서 그렇게 났고, 그때 동부는 8/26 오전이라 8/25 가 최신이 맞았다
    (quant-airflow 확인). 그 로직이면 매일 00:00~18:00 KST 18시간 동안 경고가 뜬다.

    규칙은 정의이지 고른 값이 아니다 (`CLAUDE.md` §1):
      - 동부 기준 마감(16:00 ET) 전이면 오늘 세션은 아직 없다 → 하루 뒤로.
      - 토·일은 세션이 아니다 → 금요일까지 물러난다.

    **휴장일은 모른다.** 달력을 들이지 않았으므로 미 공휴일에는 하루 앞을 가리킬 수 있다.
    그쪽으로 틀리면 "스토어를 확인하라" 는 말이 한 번 더 나올 뿐, 낡은 데이터를 새 것으로
    보이게 하지는 않는다.
    """
    et = (now or datetime.now(UTC)).astimezone(ZoneInfo("America/New_York"))
    d = et.date()
    if et.hour < US_CLOSE_HOUR_ET:
        d -= timedelta(days=1)
    while d.weekday() >= 5:  # 5=토 6=일
        d -= timedelta(days=1)
    return d
