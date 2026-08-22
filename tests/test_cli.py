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


@pytest.mark.parametrize(
    ("argv",),
    [(["macro"],), (["portfolio"],), (["picks", "solar"],), (["research", "solar"],)],
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
