"""배선 W4 — 케이던스 오케스트레이터 (`msa.pipeline.run`, `msa run monthly|weekly|quarterly`).

각 계층 진입점을 가짜로 갈아끼우고(스토어 불필요) 순서·중단·격리·선정·리포트를 검사한다.
진짜 캐시로 도는 스모크 1건은 `@pytest.mark.data`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from conftest import make_thesis
from msa.config import MissingApiKey, paths
from msa.l3.schema import ThesisRejected, ValidationResult
from msa.ops.ingest import Ingested, IngestReport
from msa.pipeline import run as R
from msa.thesis import dump_thesis_yaml, thesis_filename

ASOF = "2026-08-22"

# ---------------------------------------------------------------- 합성 입력


def _scoreboard() -> pd.DataFrame:
    """S2 스코어보드 꼴 — 자격 5 (소표본 1 포함) + 풀 미달 3. 순위는 자격 테마에만."""
    rows = [
        # theme, score, eligible, small_sample, secular
        ("t_a", 0.90, True, False, False),
        ("t_b", 0.80, True, False, False),
        ("t_small", 0.95, True, True, False),  # 점수는 1등이지만 소표본 → 뒤로
        ("t_sec", 0.70, True, False, True),
        ("t_e", 0.60, True, False, False),
        ("t_pool1", np.nan, False, False, False),
        ("t_pool2", np.nan, False, False, False),
        ("t_pool3", np.nan, False, False, True),
    ]
    df = pd.DataFrame(
        [
            {
                "cycle_class": "secular_x" if sec else "commodity_supply",
                "score": sc,
                "eligible": el,
                "small_sample": ss,
                "secular": sec,
                "flags": "",
            }
            for _t, sc, el, ss, sec in rows
        ],
        index=pd.Index([r[0] for r in rows], name="theme"),
    )
    df = df.sort_values("score", ascending=False, na_position="last")
    df.insert(0, "rank", np.where(df["score"].notna(), np.arange(1, len(df) + 1), np.nan))
    return df


@dataclass
class _Scan:
    scoreboard: Any
    meta: dict[str, Any]
    out_dir: Path | None


@dataclass
class _SB:
    table: pd.DataFrame


def _fake_scan(out_root: Path | None, **_: Any) -> _Scan:
    d = None
    if out_root is not None:
        d = out_root / ASOF
        d.mkdir(parents=True, exist_ok=True)
        _scoreboard().to_csv(d / "scoreboard.csv")
    return _Scan(_SB(_scoreboard()), {"asof": ASOF, "store_end": ASOF}, d)


@dataclass
class _Drivers:
    available: list[str]
    missing: list[str]


@dataclass
class _Macro:
    drivers: _Drivers
    meta: dict[str, Any]
    out_dir: Path | None


def _fake_macro(**_: Any) -> _Macro:
    return _Macro(
        _Drivers(["a", "b"], ["c"]), {"tailwind": {"status_counts": {"partial": 3}}}, None
    )


@dataclass
class _Ledger:
    def rows(self) -> list[dict[str, Any]]:
        return []

    def estimated_usd(self) -> float | None:
        return None


@dataclass
class _Research:
    theme_id: str
    thesis: dict[str, Any]
    thesis_path: Path | None
    out_dir: Path | None
    ledger: _Ledger = field(default_factory=_Ledger)


@dataclass
class _Inputs:
    theme_id: str


def _make_research_fake(
    gates: dict[str, Any],
) -> Any:
    """`gates[theme]` = "passed" | "contested" | Exception 인스턴스 → 그대로 행동하는
    `run_research`."""

    def fake(inputs: _Inputs, provider: Any, *, theses_root: Path, write: bool) -> _Research:
        th = inputs.theme_id
        g = gates.get(th, "passed")
        if isinstance(g, Exception):
            raise g
        thesis = make_thesis(theme_id=th)
        thesis["gate_result"] = {
            "status": g,
            "portfolio_eligible": g == "passed",
            "rule": "synthetic",
        }
        d = theses_root / ASOF
        p = dump_thesis_yaml(d / thesis_filename(th), thesis)
        return _Research(th, thesis, p, d)

    return fake


@dataclass
class _Picks:
    theme: str
    out_dir: Path | None


@dataclass
class _PA:
    n_included: int


@dataclass
class _Asm:
    themes_included: list[str]
    themes_skipped: dict[str, str]
    picks: _PA
    out_dir: Path | None
    report_text: str = "(묶음)"


@dataclass
class _PF:
    theme_rows: tuple[Any, ...]
    positions: tuple[Any, ...]
    warnings: tuple[str, ...]
    out_dir: Path | None


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """MSA_STATE 를 임시로 돌리고 모든 계층 진입점을 호출 기록이 남는 가짜로 바꾼다."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("MSA_STATE", str(state))
    calls: dict[str, list[Any]] = {
        k: [] for k in ("scan", "macro", "picks", "assemble", "portfolio")
    }

    def scan(**kw: Any) -> _Scan:
        calls["scan"].append(kw)
        return _fake_scan(kw.get("out_root"))

    def macro(**kw: Any) -> _Macro:
        calls["macro"].append(kw)
        return _fake_macro()

    def picks(theme: str, **kw: Any) -> _Picks:
        calls["picks"].append(theme)
        d = kw["out_root"] / ASOF / theme
        d.mkdir(parents=True, exist_ok=True)
        return _Picks(theme, d)

    def assemble(**kw: Any) -> _Asm:
        calls["assemble"].append(kw)
        out = Path(kw["out_dir"])
        out.mkdir(parents=True, exist_ok=True)
        return _Asm(list(kw["themes"]), {}, _PA(2 * len(kw["themes"])), out)

    def portfolio(**kw: Any) -> _PF:
        calls["portfolio"].append(kw)
        out = Path(kw["state_dir"]) / "portfolio" / ASOF
        out.mkdir(parents=True, exist_ok=True)
        (out / "plan.md").write_text("plan", encoding="utf-8")
        (out / "positions-proposal.yaml").write_text("positions: []", encoding="utf-8")
        return _PF((1, 2), (1, 2, 3), (), out)

    monkeypatch.setattr(R, "run_scan", scan)
    monkeypatch.setattr(R, "run_macro", macro)
    monkeypatch.setattr(R, "run_picks", picks)
    monkeypatch.setattr(R, "assemble_inputs", assemble)
    monkeypatch.setattr(R, "run_portfolio", portfolio)
    monkeypatch.setattr(R, "l3_assemble_inputs", lambda th, **kw: _Inputs(th))
    monkeypatch.setattr(R, "make_provider", lambda kind, **kw: object())
    monkeypatch.setattr(R, "run_research", _make_research_fake({}))
    monkeypatch.setattr(
        R,
        "ingest_round",
        lambda d, **kw: IngestReport(kw["asof"], str(d), None, kw["write"]),
    )
    return {"state": state, "calls": calls}


# ---------------------------------------------------------------- select_themes


def test_select_themes_honours_s2_eligible_and_extra() -> None:
    sel = R.select_themes(_scoreboard(), top_k=3, extra_themes=["t_pool3", "t_a", "ghost"])
    # 자격 5 중 K=3 — 소표본 t_small 은 뒤로 밀린다 (점수 1등이어도)
    assert sel.from_scoreboard == ("t_a", "t_b", "t_sec")
    assert sel.n_eligible == 5 and sel.n_total == 8 and not sel.short_of_k
    # 지정: 이미 뽑힌 t_a 는 중복 제거, 풀 미달·없는 테마는 플래그와 함께 붙는다
    assert sel.extra == ("t_pool3", "ghost")
    assert sel.selected == ("t_a", "t_b", "t_sec", "t_pool3", "ghost")
    assert "SECULAR — 게이트 필요" in sel.flags["t_sec"]
    assert set(sel.flags["t_pool3"]) >= {"풀 미달(관찰)", "SECULAR — 게이트 필요"}
    assert sel.flags["ghost"] == ("스코어보드에 없음",)
    # 순위는 점수순(스코어보드 그대로 — 소표본 t_small 이 #1), 선정 순서만 소표본을 뒤로 민다
    assert sel.ranks["t_a"] == 2 and sel.ranks["t_pool3"] is None and sel.ranks["ghost"] is None
    assert any("ghost" in n for n in sel.notes)
    text = sel.render()
    assert "t_sec" in text and "지정" in text


def test_select_themes_short_of_k_does_not_fill_from_pool() -> None:
    sel = R.select_themes(_scoreboard(), top_k=8)
    assert sel.short_of_k and len(sel.from_scoreboard) == 5
    assert "t_pool1" not in sel.selected
    assert any("관찰 목록" in n for n in sel.notes)
    # 소표본은 마지막
    assert sel.from_scoreboard[-1] == "t_small"


def test_select_themes_rejects_negative_k() -> None:
    with pytest.raises(R.RunError):
        R.select_themes(_scoreboard(), top_k=-1)


# ---------------------------------------------------------------- run_monthly (합성)


def test_monthly_step_order_and_report_files(fakes: dict[str, Any], tmp_path: Path) -> None:
    hdir = tmp_path / "human"
    hdir.mkdir()
    dump_thesis_yaml(hdir / "t_a.yaml", make_thesis(theme_id="t_a"))  # gate_result 없음 → 편입 가능
    res = R.run_monthly(asof=ASOF, top_k=2, provider="none", human_theses_dir=hdir)
    rep = res.report
    assert [s.name for s in rep.steps] == list(R.MONTHLY_STEPS)
    assert rep.statuses() == {
        "scan": "ok",
        "macro": "ok",
        "select": "ok",
        "research": "ok",
        "ingest": "skipped",  # provider none — 새 라운드 없음
        "picks": "ok",
        "assemble": "ok",
        "portfolio": "ok",
        "report": "ok",
    }
    assert res.exit_code == 0 and not rep.stopped
    # 사람 논지가 있는 t_a 만 picks·portfolio 로 간다, t_b 는 "thesis 없음 → 관찰"
    assert fakes["calls"]["picks"] == ["t_a"]
    assert fakes["calls"]["assemble"][0]["themes"] == ["t_a"]
    assert res.theses["t_a"].source == "human" and res.theses["t_a"].eligible
    assert res.theses["t_b"].status == "absent" and "관찰" in res.theses["t_b"].reason
    assert any("t_b" in x and "관찰" in x for x in rep.human_todo)
    assert any("positions-proposal.md" in x for x in rep.human_todo)
    # 파일: state/runs/<asof>/monthly-report.md + run.json
    out = fakes["state"] / "runs" / ASOF
    assert res.out_dir == out
    md = (out / "monthly-report.md").read_text(encoding="utf-8")
    assert "| scan | ok |" in md and "집행" in md and "사람이 한다" in md
    js = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert [s["name"] for s in js["steps"]] == list(R.MONTHLY_STEPS)
    assert js["exit_code"] == 0 and js["params"]["provider"] == "none"
    # 스캔은 state/scans 에, 포트는 state/portfolio 에 — 루트가 state 다
    assert fakes["calls"]["scan"][0]["out_root"] == fakes["state"] / "scans"
    assert fakes["calls"]["portfolio"][0]["state_dir"] == fakes["state"]
    assert fakes["calls"]["portfolio"][0]["emit_positions"] is True


def test_monthly_scan_failure_stops_everything(
    fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(**kw: Any) -> Any:
        raise RuntimeError("커버리지 감사 실패: 미분류 시총 7%")

    monkeypatch.setattr(R, "run_scan", boom)
    res = R.run_monthly(asof=ASOF, provider="none")
    rep = res.report
    assert rep.stopped and res.exit_code == 1
    assert rep.step("scan").status == "failed"  # type: ignore[union-attr]
    assert "커버리지" in rep.step("scan").reason  # type: ignore[union-attr]
    for name in R.MONTHLY_STEPS[1:-1]:
        assert rep.step(name).status == "skipped"  # type: ignore[union-attr]
    assert fakes["calls"]["macro"] == [] and fakes["calls"]["picks"] == []
    # 중단돼도 리포트는 남는다
    assert rep.step("report").status == "ok"  # type: ignore[union-attr]
    assert (fakes["state"] / "runs" / ASOF / "run.json").exists()


def test_monthly_macro_unavailable_does_not_stop(
    fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_fred(**kw: Any) -> Any:
        raise MissingApiKey("FRED_API_KEY 가 비어 있다")

    monkeypatch.setattr(R, "run_macro", no_fred)
    res = R.run_monthly(asof=ASOF, top_k=2, provider="none")
    st = res.report.statuses()
    assert st["macro"] == "unavailable" and "FRED_API_KEY" in res.report.step("macro").reason  # type: ignore[union-attr]
    assert st["select"] == "ok" and st["research"] == "ok" and res.exit_code == 0
    assert any("FRED" in x for x in res.report.human_todo)


def test_monthly_macro_zero_drivers_is_unavailable(
    fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        R, "run_macro", lambda **kw: _Macro(_Drivers([], ["x", "y"]), {"tailwind": {}}, None)
    )
    res = R.run_monthly(asof=ASOF, top_k=1, provider="none")
    assert res.report.statuses()["macro"] == "unavailable"
    assert "가용 드라이버 0" in res.report.step("macro").reason  # type: ignore[union-attr]


def test_monthly_provider_none_without_any_thesis_skips_downstream(fakes: dict[str, Any]) -> None:
    res = R.run_monthly(asof=ASOF, top_k=3, provider="none")
    st = res.report.statuses()
    assert st["research"] == "ok"  # 오류가 아니다 — "thesis 없음 → 관찰"
    assert all(r.status == "absent" for r in res.theses.values())
    assert st["picks"] == "skipped" and st["assemble"] == "skipped" and st["portfolio"] == "skipped"
    assert "편입 가능" in res.report.step("portfolio").reason  # type: ignore[union-attr]
    assert fakes["calls"]["picks"] == [] and fakes["calls"]["portfolio"] == []
    assert res.exit_code == 0


def test_monthly_provider_none_finds_prior_l3_thesis(fakes: dict[str, Any]) -> None:
    # 직전 라운드(asof 이하)의 L3 thesis 가 있으면 그것을 쓴다 — 게이트 contested 면 편입 불가
    prior = fakes["state"] / "theses" / "2026-08-01"
    ta = make_thesis(theme_id="t_a")
    ta["gate_result"] = {"status": "passed", "portfolio_eligible": True, "rule": "x"}
    tb = make_thesis(theme_id="t_b")
    tb["gate_result"] = {"status": "contested", "portfolio_eligible": False, "rule": "x"}
    dump_thesis_yaml(prior / thesis_filename("t_a"), ta)
    dump_thesis_yaml(prior / thesis_filename("t_b"), tb)
    # asof 보다 뒤의 라운드는 보지 않는다
    later = fakes["state"] / "theses" / "2026-09-01"
    dump_thesis_yaml(later / thesis_filename("t_b"), ta | {"theme_id": "t_b"})
    res = R.run_monthly(asof=ASOF, top_k=2, provider="none")
    assert res.theses["t_a"].source == "l3-prior" and res.theses["t_a"].eligible
    assert res.theses["t_b"].source == "l3-prior" and not res.theses["t_b"].eligible
    assert res.theses["t_b"].gate_status == "contested"
    assert fakes["calls"]["picks"] == ["t_a"]


def test_monthly_research_failures_are_isolated(
    fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from msa.l3.providers import ProviderError

    vr = ValidationResult(errors=["evidence 가 비어 있다"])
    gates = {
        "t_a": ThesisRejected(vr),  # 스키마 기각 → 제외 + 사유
        "t_b": ProviderError("예산 초과"),  # 제공자 오류 → 보고
        "t_sec": "passed",  # 정상
    }
    monkeypatch.setattr(R, "run_research", _make_research_fake(gates))
    res = R.run_monthly(asof=ASOF, top_k=3, provider="mock")
    st = res.report.statuses()
    assert st["research"] == "ok"  # 하나라도 확보 → ok, 나머지는 이름·사유로
    assert res.theses["t_a"].status == "rejected_schema" and "evidence" in res.theses["t_a"].reason
    assert res.theses["t_b"].status == "provider_error" and "예산" in res.theses["t_b"].reason
    assert res.theses["t_sec"].status == "researched" and res.theses["t_sec"].eligible
    assert fakes["calls"]["picks"] == ["t_sec"]
    assert st["ingest"] == "ok"
    assert any("t_a" in n and "스키마" in n for n in res.report.notes)
    assert any("t_b" in n and "provider_error" in n for n in res.report.notes)
    assert res.exit_code == 0


def test_monthly_research_all_failed_then_portfolio_skipped(
    fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        R, "run_research", _make_research_fake({"t_a": "contested", "t_b": "rejected"})
    )
    res = R.run_monthly(asof=ASOF, top_k=2, provider="mock")
    st = res.report.statuses()
    assert st["research"] == "ok"  # thesis 는 확보됐다 (게이트가 막았을 뿐)
    assert not any(r.eligible for r in res.theses.values())
    assert st["picks"] == "skipped" and st["assemble"] == "skipped" and st["portfolio"] == "skipped"
    assert any("contested" in x for x in res.report.human_todo)
    assert res.exit_code == 0


def test_monthly_ingest_reports_drafts_and_watchlist(
    fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def ingest(d: Path, **kw: Any) -> IngestReport:
        rep = IngestReport(kw["asof"], str(d), None, kw["write"])
        rep.rows.append(
            Ingested("t_a", "passed", "draft_written", "초안", [f"{d}/journal-draft-t_a.yaml"])
        )
        rep.rows.append(Ingested("t_b", "contested", "watchlist_added", "referee 보류"))
        rep.human_todo["t_a"] = ["stocks", "deviation_reason"]
        return rep

    monkeypatch.setattr(R, "ingest_round", ingest)
    res = R.run_monthly(asof=ASOF, top_k=2, provider="mock")
    ing = res.report.step("ingest")
    assert ing is not None and ing.status == "ok" and "진입 초안" in ing.reason
    assert any("t_a" in x and "journal new --from" in x for x in res.report.human_todo)
    assert any("t_b" in x and "관찰 목록" in x for x in res.report.human_todo)


def test_monthly_skip_flags(fakes: dict[str, Any]) -> None:
    res = R.run_monthly(
        asof=ASOF,
        top_k=2,
        provider="mock",
        skip_macro=True,
        skip_research=True,
        skip_picks=True,
        skip_portfolio=True,
    )
    st = res.report.statuses()
    assert st["macro"] == "skipped" and st["research"] == "skipped" and st["ingest"] == "skipped"
    assert st["picks"] == "skipped" and st["assemble"] == "skipped" and st["portfolio"] == "skipped"
    assert fakes["calls"]["macro"] == [] and fakes["calls"]["picks"] == []
    assert "--skip-macro" in res.report.step("macro").reason  # type: ignore[union-attr]


def test_monthly_no_write_uses_sandbox_and_leaves_state_untouched(
    fakes: dict[str, Any], tmp_path: Path
) -> None:
    sandbox = tmp_path / "sb"
    res = R.run_monthly(asof=ASOF, top_k=2, provider="mock", write=False, sandbox_dir=sandbox)
    st = res.report.statuses()
    assert st["scan"] == "ok" and st["portfolio"] == "ok" and st["report"] == "ok"
    assert res.out_dir is None and res.report.out_dir is None
    # state/ 에는 아무것도 없다 — 전부 샌드박스에
    assert not (fakes["state"] / "runs").exists()
    assert not (fakes["state"] / "scans").exists()
    assert (sandbox / "scans" / ASOF / "scoreboard.csv").exists()
    assert (sandbox / "runs" / ASOF / "monthly-report.md").exists()
    assert fakes["calls"]["scan"][0]["out_root"] == sandbox / "scans"
    assert fakes["calls"]["macro"][0]["write"] is False
    assert fakes["calls"]["portfolio"][0]["state_dir"] == sandbox
    assert "no-write" in res.report.render()


def test_monthly_rejects_bad_args(fakes: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(R.RunError, match="provider"):
        R.run_monthly(asof=ASOF, provider="openai")
    with pytest.raises(R.RunError, match="YYYY-MM-DD"):
        R.run_monthly(asof="2026-8")
    with pytest.raises(R.RunError, match="디렉터리"):
        R.run_monthly(asof=ASOF, human_theses_dir=tmp_path / "nope")
    assert fakes["calls"]["scan"] == []  # 인자 검사는 스캔 전에


def test_gate_eligible_rules() -> None:
    assert R.gate_eligible({}) == (True, None)
    assert R.gate_eligible({"gate_result": {"status": "passed", "portfolio_eligible": True}}) == (
        True,
        "passed",
    )
    assert R.gate_eligible({"gate_result": {"status": "passed", "portfolio_eligible": False}}) == (
        False,
        "passed",
    )
    assert R.gate_eligible({"gate_result": {"status": "contested"}}) == (False, "contested")
    assert R.gate_eligible({"gate_result": {"status": "rejected", "portfolio_eligible": True}}) == (
        False,
        "rejected",
    )


# ---------------------------------------------------------------- run_weekly


def test_weekly_is_scan_plus_check(fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from msa.ops.check import CheckReport

    seen: list[Any] = []

    def chk(asof_s: str, *, write: bool) -> Any:
        seen.append((asof_s, write))
        from datetime import date as _d

        out = paths().checks / asof_s
        out.mkdir(parents=True)
        rep = CheckReport(
            asof=_d.fromisoformat(asof_s),
            mode="weekly",
            positions=[],
            alerts=[],
            out_dir=out,
            problems=["CCJ: thesis 스냅샷 없음"],
            unchecked=["X (t_a)"],
        )
        return rep, {"telegram": "not_configured", "lookback_days": 1}

    monkeypatch.setattr(R, "run_weekly_check", chk)
    res = R.run_weekly(asof=ASOF)
    assert [s.name for s in res.report.steps] == list(R.WEEKLY_STEPS)
    assert res.report.statuses() == {"scan": "ok", "check": "ok", "report": "ok"}
    assert seen == [(ASOF, True)]
    assert res.exit_code == 0  # 점검 문제는 리포트로, 종료 코드는 스캔 중단에만
    assert any("thesis 스냅샷" in x for x in res.report.human_todo)
    assert any("미체결 제안" in x for x in res.report.human_todo)
    out = fakes["state"] / "runs" / ASOF
    assert (out / "weekly-report.md").exists() and (out / "run.json").exists()
    assert res.out_dir == out


def test_weekly_scan_failure_stops(fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kw: Any) -> Any:
        raise RuntimeError("store down")

    called: list[str] = []
    monkeypatch.setattr(R, "run_scan", boom)
    monkeypatch.setattr(R, "run_weekly_check", lambda a, **k: called.append(a))
    res = R.run_weekly(asof=ASOF)
    assert res.exit_code == 1 and res.report.statuses() == {
        "scan": "failed",
        "check": "skipped",
        "report": "ok",
    }
    assert called == []


def test_weekly_check_failure_is_reported_not_fatal(
    fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(a: str, **k: Any) -> Any:
        raise RuntimeError("positions.yaml 깨짐")

    monkeypatch.setattr(R, "run_weekly_check", boom)
    res = R.run_weekly(asof=ASOF)
    assert res.report.statuses()["check"] == "failed" and res.exit_code == 0


# ---------------------------------------------------------------- quarterly · CLI


def test_quarterly_lists_three_commands() -> None:
    text = R.run_quarterly()
    for cmd, _why in R.QUARTERLY_COMMANDS:
        assert cmd in text
    assert "msa macro" in text and "calibration" in text and "rejections-update" in text
    assert "실행하지 않는다" in text


def test_cli_run_commands(fakes: dict[str, Any]) -> None:
    from msa.cli import app

    runner = CliRunner()
    r = runner.invoke(app, ["run", "quarterly"])
    assert r.exit_code == 0 and "msa ops calibration" in r.output

    r = runner.invoke(app, ["run", "monthly", "--asof", ASOF, "--top-k", "2", "--provider", "none"])
    assert r.exit_code == 0, r.output
    assert "scan" in r.output and "research" in r.output and "저장:" in r.output
    assert (fakes["state"] / "runs" / ASOF / "monthly-report.md").exists()

    r = runner.invoke(app, ["run", "monthly", "--provider", "openai"])
    assert r.exit_code != 0

    r = runner.invoke(app, ["run", "weekly", "--asof", ASOF, "--no-write"])
    # 점검은 진짜 스토어를 열려 한다 — 여기서는 실패로 보고되고 종료 코드는 0 (스캔은 가짜로 성공)
    assert r.exit_code == 0, r.output
    assert "check" in r.output


# ---------------------------------------------------------------- data 스모크


@pytest.mark.data
def test_monthly_mock_smoke_on_real_cache(tmp_path: Path) -> None:
    """진짜 캐시 + mock L3 — state/ 에 쓰지 않고 샌드박스에서 끝까지 (완료 또는 보고)."""
    p = paths()
    if not p.duckdb.exists() or not (p.cache).exists():
        pytest.skip("스토어/캐시 없음")
    before = {x.name for x in p.state.iterdir()}
    res = R.run_monthly(provider="mock", top_k=2, write=False, sandbox_dir=tmp_path / "sb")
    after = {x.name for x in p.state.iterdir()}
    assert after == before, f"write=False 인데 state/ 가 바뀌었다: {after - before}"
    assert not (p.state / "runs").exists() or "runs" in before
    st = res.report.statuses()
    assert st["scan"] == "ok" and st["select"] == "ok" and st["research"] == "ok"
    assert res.exit_code == 0
    assert res.selection is not None and len(res.selection.selected) <= 2
    # 나머지 단계는 ok 이거나 사유가 있는 unavailable/skipped/failed — 조용히 빠진 단계는 없다
    for name in R.MONTHLY_STEPS:
        step = res.report.step(name)
        assert step is not None and (step.status == "ok" or step.reason), name
    assert (tmp_path / "sb" / "runs" / res.report.asof / "monthly-report.md").exists()


def test_select_themes_applies_l2_hard_exclude_overlay() -> None:
    """L2 는 오버레이 — hard_exclude 테마는 상위 K 후보에서 빠지고 이름이 기록된다.

    사용자 지정은 유지하되 플래그를 단다."""
    import pandas as pd

    from msa.pipeline.run import select_themes

    sb = pd.DataFrame(
        {
            "score": [0.9, 0.8, 0.7, 0.6, float("nan")],
            "eligible": [True, True, True, True, False],
            "rank": [1, 2, 3, 4, float("nan")],
            "small_sample": [False] * 5,
        },
        index=pd.Index(["a", "b", "c", "d", "e"], name="theme"),
    )
    sel = select_themes(sb, top_k=3, hard_exclude={"b"})
    assert sel.from_scoreboard == ("a", "c", "d")
    assert any("hard_exclude" in n and "b" in n for n in sel.notes)
    sel2 = select_themes(sb, top_k=2, extra_themes=["b"], hard_exclude={"b"})
    assert "b" in sel2.selected and any("hard_exclude" in f for f in sel2.flags["b"])
    # 오버레이가 없으면 순위 그대로
    assert select_themes(sb, top_k=3).from_scoreboard == ("a", "b", "c")
