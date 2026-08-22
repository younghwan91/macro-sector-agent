"""13612W 모멘텀 — `portfolio-research` 에서 벤더링.

출처: https://github.com/younghwan91/portfolio-research
파일: src/opt_portfolio/taa/signals.py
커밋: 4293e7372d43d6d8ea3e25d3692bc9ceb1b41383
복사: 2026-08-23 (M3). 함수 본문은 원본 그대로이며 docstring 만 보강했다.

13612W 의 가중치 12/4/2/1 은 임의가 아니라 **연율화 계수**다 — 1개월 수익 ×12,
3개월 ×4, 6개월 ×2, 12개월 ×1 로 서로 다른 시간축의 연율 수익을 합한 값이다.
"""

from __future__ import annotations

import pandas as pd

#: (개월 수, 가중치) — Keller 13612W
_MOMENTUM_TERMS: tuple[tuple[int, int], ...] = ((1, 12), (3, 4), (6, 2), (12, 1))


def to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """일별 패널 → 월말 종가."""
    return daily.resample("ME").last()


def momentum_13612w(monthly: pd.DataFrame) -> pd.DataFrame:
    """13612W 모멘텀. 12개월 미만 구간은 NaN 이다."""
    score = None
    for months, weight in _MOMENTUM_TERMS:
        # fill_method=None — 기본값(pad)은 결측 가격을 직전 값으로 메워
        # 0% 수익으로 둔갑시킨다. 결측은 NaN 으로 남아야 한다.
        term = weight * monthly.pct_change(months, fill_method=None)
        score = term if score is None else score + term
    assert score is not None  # _MOMENTUM_TERMS 가 비지 않음
    return score


def sma_ratio(monthly: pd.DataFrame, window: int = 13) -> pd.DataFrame:
    """현재가 / 직전 `window` 개월 평균. 1 보다 크면 상승 추세."""
    return monthly / monthly.rolling(window, min_periods=window).mean()
