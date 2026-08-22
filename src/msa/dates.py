"""월말·기준일 계산의 단일 구현.

L1(`fundamentals.month_ends`)·L2(`drivers.month_end_grid`·`last_month_end`)·L3(`_months_between`)·
CLI(`_parse_date`) 가 각자 같은 계산을 들고 있었다. 한 곳에 두고 전부 여기서 가져간다 —
월말 라벨 규약이 계층마다 조금씩 달라지면 `Indicators.bucket_for` 와 백테스트 라벨이 어긋난다
(`docs/10` §2). 값·규약은 바꾸지 않았다.

월말 라벨은 전부 pandas 의 `"ME"`(month end) 이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

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
