"""FRED 실측 — 네트워크 + API 키가 필요하다. `@pytest.mark.net` 으로 CI 에서 제외된다.

M1 완료 판정(`docs/08` §6.3)의 "FRED 시리즈 적재 + 발표 지연 실측" 이 이 테스트다 — 대상은
L1 이 쓰는 시리즈(CPI + physical_ref)뿐이다 (L2 드라이버 24종은 2026-08-23 제거).
**M1 작성 시점에 `FRED_API_KEY` 가 환경에 없어 실행되지 못했다** — 그래서 §3 표의
`발표지연`·`개정` 두 열은 아직 `M1 실측` 인 채로 남아 있다. 키가 생기면
`uv run pytest -m net` 과 `uv run msa data fred-lag` 가 그 열을 채운다.
"""

from __future__ import annotations

import os

import pytest

from msa.data.fred import L1_SERIES, FredClient, l1_series

pytestmark = [
    pytest.mark.net,
    pytest.mark.skipif(not os.environ.get("FRED_API_KEY"), reason="FRED_API_KEY 없음"),
]


def test_all_l1_series_resolve() -> None:
    """존재하지 않는 시리즈가 있으면 `measure_all` 이 던진다 — 조용히 건너뛰지 않는다."""
    series = l1_series()
    assert set(L1_SERIES) <= set(series)
    with FredClient() as c:
        rows = c.measure_all(series)
    assert len(rows) == len(series)
    assert all(r.n_observations > 0 for r in rows)


def test_revision_detected_for_cpi() -> None:
    """`docs/08` §3 각주: CPIAUCSL 은 계절조정 개정이 있다 (매년 2월)."""
    with FredClient() as c:
        m = c.measure_release_lag("CPIAUCSL", vintage_date="2024-01-02")
    assert m.revised is True
