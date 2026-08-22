from __future__ import annotations

import pytest
from typer.testing import CliRunner

from msa.cli import app

runner = CliRunner()


def test_version() -> None:
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert "msa" in r.stdout


@pytest.mark.parametrize(
    "cmd", ["scan", "macro", "picks", "portfolio", "check", "research", "journal", "ops"]
)
def test_stub_commands_appear_in_help(cmd: str) -> None:
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert cmd in r.stdout


def test_data_subcommands_registered() -> None:
    r = runner.invoke(app, ["data", "--help"])
    assert r.exit_code == 0
    for c in ("status", "audit", "fred-lag", "fred-fetch"):
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


def test_picks_registered_with_options() -> None:
    r = runner.invoke(app, ["picks", "--help"])
    assert r.exit_code == 0
    for opt in ("--asof", "--top", "--no-write", "--no-physical"):
        assert opt in r.stdout


def test_m8_subcommands_registered() -> None:
    r = runner.invoke(app, ["journal", "--help"])
    assert r.exit_code == 0
    for c in ("new", "verify", "diff", "template", "install-hook"):
        assert c in r.stdout
    r = runner.invoke(app, ["ops", "--help"])
    assert r.exit_code == 0
    for c in ("schedule", "calibration", "rejections-update", "reproduce", "due"):
        assert c in r.stdout


def test_ops_schedule_prints_cron_without_installing(tmp_path) -> None:
    r = runner.invoke(app, ["ops", "schedule", "--print-cron"])
    assert r.exit_code == 0
    assert "msa check --daily" in r.stdout
    assert "crontab -e" in r.stdout


def test_journal_template_and_new_refuses_incomplete(tmp_path) -> None:
    r = runner.invoke(app, ["journal", "template", "reject"])
    assert r.exit_code == 0 and "path:" in r.stdout
    f = tmp_path / "r.yaml"
    f.write_text(r.stdout.replace('reason: "..."', 'reason: ""'), encoding="utf-8")
    r2 = runner.invoke(app, ["journal", "new", "--from", str(f), "--journal", str(tmp_path / "j")])
    assert r2.exit_code == 1
    assert "작성 거부" in (r2.stdout + (r2.stderr or ""))


def test_backtest_subgroup_registered() -> None:
    r = runner.invoke(app, ["backtest", "--help"])
    assert r.exit_code == 0
    assert "l1" in r.stdout
    r2 = runner.invoke(app, ["backtest", "l1", "--help"])
    assert r2.exit_code == 0
    assert "--no-write" in r2.stdout
