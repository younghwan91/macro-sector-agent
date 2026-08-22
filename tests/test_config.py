from __future__ import annotations

from pathlib import Path

import pytest

from msa.config import MissingApiKey, fred_api_key, paths


def test_paths_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("MSA_DUCKDB", "MSA_SHARADAR_RAW", "MSA_STATE"):
        monkeypatch.delenv(k, raising=False)
    p = paths()
    assert p.duckdb == Path.home() / "data" / "us_micro.duckdb"
    assert p.sharadar_raw == Path.home() / "data" / "sharadar"
    assert p.state.name == "state"


def test_env_overrides_and_expands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSA_DUCKDB", "~/elsewhere/x.duckdb")
    monkeypatch.setenv("MSA_STATE", "/srv/msa-state")
    p = paths()
    assert p.duckdb == Path.home() / "elsewhere" / "x.duckdb"
    assert p.state == Path("/srv/msa-state")


def test_blank_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """빈 문자열은 "설정 안 함" 으로 다룬다 — Path('') 는 cwd 가 되어 조용히 틀린다."""
    monkeypatch.setenv("MSA_DUCKDB", "   ")
    assert paths().duckdb == Path.home() / "data" / "us_micro.duckdb"


def test_missing_fred_key_raises_not_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(MissingApiKey):
        fred_api_key()


def test_fred_key_returned_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "  abc123  ")
    assert fred_api_key() == "abc123"
