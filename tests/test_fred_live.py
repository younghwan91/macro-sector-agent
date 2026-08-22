"""FRED 실측 — 네트워크 + API 키가 필요하다. `@pytest.mark.net` 으로 CI 에서 제외된다.

M1 완료 판정(`docs/08` §6.3)의 "FRED 시리즈 24종 적재 + 발표 지연 실측" 이 이 테스트다.
**M1 작성 시점에 `FRED_API_KEY` 가 환경에 없어 실행되지 못했다** — 그래서 §3 표의
`발표지연`·`개정` 두 열은 아직 `M1 실측` 인 채로 남아 있다. 키가 생기면
`uv run pytest -m net` 과 `uv run msa data fred-lag` 가 그 열을 채운다.
"""

from __future__ import annotations

import os

import pytest

from msa.data.fred import ALL_SERIES, NEEDS_VERIFICATION, FredClient

pytestmark = [
    pytest.mark.net,
    pytest.mark.skipif(not os.environ.get("FRED_API_KEY"), reason="FRED_API_KEY 없음"),
]


def test_all_24_series_resolve() -> None:
    """존재하지 않는 시리즈가 있으면 `measure_all` 이 던진다 — 조용히 건너뛰지 않는다."""
    with FredClient() as c:
        rows = c.measure_all()
    assert len(rows) == len(ALL_SERIES) == 24
    assert all(r.n_observations > 0 for r in rows)


@pytest.mark.parametrize("series_id", NEEDS_VERIFICATION)
def test_series_flagged_for_verification_actually_exist(series_id: str) -> None:
    """`docs/08` §3 이 "M1 에서 실측 확인 필요" 로 남긴 FDEFX·PCOPPUSDM."""
    with FredClient() as c:
        assert c.series_meta(series_id).series_id == series_id


def test_revision_detected_for_indpro() -> None:
    """`docs/08` §3 각주: INDPRO·PAYEMS 는 개정이 크다."""
    with FredClient() as c:
        m = c.measure_release_lag("INDPRO", vintage_date="2024-01-02")
    assert m.revised is True
