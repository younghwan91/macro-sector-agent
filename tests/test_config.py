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


def test_store_lag_is_reported_when_stale(capsys: pytest.CaptureFixture[str]) -> None:
    """스토어가 뒤처진 사실은 문서가 아니라 화면에 나와야 한다 (`CLAUDE.md` §2).

    이 저장소는 적재를 하지 않으므로(`docs/18` §6) 뒤처짐을 알려주지 않으면 사용자는
    묵은 가격으로 순위를 보면서 그것을 모른다.
    """
    from dataclasses import dataclass
    from datetime import date, timedelta

    from msa.cli import STORE_LAG_WARN_DAYS, _echo_store_lag

    @dataclass
    class _S:
        name: str
        end: date | None

    fresh = [_S("prices", date.today() - timedelta(days=STORE_LAG_WARN_DAYS))]
    _echo_store_lag(fresh)  # type: ignore[arg-type]
    assert "정상" in capsys.readouterr().out

    stale = [_S("prices", date.today() - timedelta(days=STORE_LAG_WARN_DAYS + 1))]
    _echo_store_lag(stale)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "뒤처져 있다" in out and "opt-factor ingest" in out

    _echo_store_lag([_S("prices", None)])  # type: ignore[arg-type]
    assert "end 가 없다" in capsys.readouterr().out
