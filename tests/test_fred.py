"""FRED 파싱·지연 계산 — 전부 순수 함수라 네트워크 없이 돈다."""

from __future__ import annotations

from datetime import date

import pytest

from msa.data.fred import (
    L1_SERIES,
    FredError,
    Observation,
    detect_revision,
    infer_frequency,
    l1_series,
    lag_days,
    parse_observations,
    parse_series_meta,
)


def _payload(rows: list[tuple[str, str]]) -> dict[str, object]:
    return {"observations": [{"date": d, "value": v} for d, v in rows]}


def test_l1_series_is_cpi_plus_fred_physical_refs() -> None:
    """L2 제거(2026-08-23) 뒤 FRED 대상은 L1 이 쓰는 것뿐 — CPI + 테마 `physical_ref.source ==
    fred`. 24종 드라이버 목록(`ALL_SERIES`·`DRIVER_SERIES`)은 없다 (`docs/archive/macro-dag.yaml`
    에 기록만)."""
    import msa.data.fred as fred

    assert L1_SERIES == ("CPIAUCSL",)
    assert not hasattr(fred, "ALL_SERIES") and not hasattr(fred, "DRIVER_SERIES")

    class _Ref:
        def __init__(self, source: str, symbol: str) -> None:
            self.source, self.symbol = source, symbol

    class _Theme:
        def __init__(self, ref: _Ref | None) -> None:
            self.physical_ref = ref

    themes = [
        _Theme(_Ref("fred", "HOUST")),
        _Theme(_Ref("etf", "GLD")),
        _Theme(None),
        _Theme(_Ref("fred", "CPIAUCSL")),  # CPI 중복은 한 번만
        _Theme(_Ref("fred", "HOUST")),  # 심볼 중복도 한 번만
    ]
    assert l1_series(themes) == ("CPIAUCSL", "HOUST")
    assert l1_series([]) == L1_SERIES


def test_missing_value_is_none_not_zero() -> None:
    """FRED 결측은 '.' 다. 0.0 으로 읽으면 국면 판정이 조용히 틀어진다."""
    obs = parse_observations(_payload([("2026-01-01", "1.5"), ("2026-01-02", ".")]))
    assert obs[0].value == 1.5
    assert obs[1].value is None


def test_error_response_raises_instead_of_empty_list() -> None:
    with pytest.raises(FredError, match="observations"):
        parse_observations({"error_code": 400, "error_message": "Bad Request"})


def test_empty_observations_list_is_valid_but_distinguishable() -> None:
    assert parse_observations(_payload([])) == []


def test_series_meta_parsed() -> None:
    meta = parse_series_meta(
        {
            "seriess": [
                {
                    "id": "INDPRO",
                    "title": "Industrial Production",
                    "frequency_short": "M",
                    "units_short": "Index",
                    "last_updated": "2026-08-15 08:31:02-05",
                    "observation_end": "2026-07-01",
                }
            ]
        }
    )
    assert meta.series_id == "INDPRO"
    assert meta.frequency == "M"
    assert meta.observation_end == date(2026, 7, 1)


def test_empty_series_meta_raises() -> None:
    with pytest.raises(FredError):
        parse_series_meta({"seriess": []})


def test_lag_days() -> None:
    assert lag_days(date(2026, 7, 1), date(2026, 8, 22)) == 52


@pytest.mark.parametrize(
    ("step", "expected"),
    [(1, "D"), (7, "W"), (30, "M"), (91, "Q"), (365, "A")],
)
def test_infer_frequency(step: int, expected: str) -> None:
    from datetime import timedelta

    start = date(2020, 1, 1)
    obs = [Observation(start + timedelta(days=step * i), float(i)) for i in range(12)]
    assert infer_frequency(obs) == expected


def test_infer_frequency_too_few_points() -> None:
    assert infer_frequency([Observation(date(2026, 1, 1), 1.0)]) == "unknown"


def test_detect_revision_finds_changed_vintage() -> None:
    latest = [Observation(date(2026, 1, 1), 103.5), Observation(date(2026, 2, 1), 104.0)]
    vintage = [Observation(date(2026, 1, 1), 102.9), Observation(date(2026, 2, 1), 104.0)]
    revised, note = detect_revision(latest, vintage)
    assert revised
    assert "1건" in note


def test_detect_revision_none_when_identical() -> None:
    obs = [Observation(date(2026, 1, 1), 100.0)]
    revised, note = detect_revision(obs, obs)
    assert not revised
    assert note == ""


def test_detect_revision_ignores_missing_values() -> None:
    latest = [Observation(date(2026, 1, 1), 100.0)]
    vintage = [Observation(date(2026, 1, 1), None), Observation(date(2025, 1, 1), 5.0)]
    assert detect_revision(latest, vintage) == (False, "")
