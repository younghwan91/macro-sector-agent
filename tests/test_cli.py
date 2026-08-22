from __future__ import annotations

import pytest
from typer.testing import CliRunner

from msa.cli import app

runner = CliRunner()


def test_version() -> None:
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert "msa" in r.stdout


@pytest.mark.parametrize("cmd", ["scan", "macro", "picks", "portfolio", "check", "research"])
def test_stub_commands_appear_in_help(cmd: str) -> None:
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert cmd in r.stdout


@pytest.mark.parametrize(
    ("argv",),
    [(["macro"],), (["check"],), (["picks", "solar"],)],
)
def test_stub_commands_raise_rather_than_return_empty(argv: list[str]) -> None:
    """빈 결과를 내는 스텁은 조용한 절단의 씨앗이다 — 명확히 던진다."""
    r = runner.invoke(app, argv)
    assert r.exit_code != 0
    assert isinstance(r.exception, NotImplementedError)


def test_data_subcommands_registered() -> None:
    r = runner.invoke(app, ["data", "--help"])
    assert r.exit_code == 0
    for c in ("status", "audit", "fred-lag"):
        assert c in r.stdout


def test_portfolio_is_not_a_stub() -> None:
    """`msa portfolio` 는 M6 에서 구현됐다 — 옵션이 보이고 NotImplementedError 가 아니다."""
    r = runner.invoke(app, ["portfolio", "--help"])
    assert r.exit_code == 0
    for opt in ("--inputs", "--asof", "--cases", "--capital", "--cluster-cap", "--no-write"):
        assert opt in r.stdout
    r = runner.invoke(app, ["portfolio", "--inputs", "/nonexistent/dir", "--no-write"])
    assert r.exit_code != 0
    assert not isinstance(r.exception, NotImplementedError)
