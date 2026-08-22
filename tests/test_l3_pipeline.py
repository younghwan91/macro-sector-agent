"""L3 파이프라인 — Mock/Fixture 제공자로 전체 경로 (스토어·네트워크 없음)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml
from typer.testing import CliRunner

from _l3_synth import ASOF, axis1, inputs, write_scan_dir
from msa.config import REPO_ROOT
from msa.l3.contracts import (
    L1_SCORE_FIELDS,
    InputsError,
    assemble_inputs,
    latest_scan_dir,
    load_scorecard,
)
from msa.l3.pipeline import count_contested, run_research
from msa.l3.providers import (
    BudgetExceeded,
    CompletionRequest,
    FixtureProvider,
    MockProvider,
    NotConfigured,
    SearchBudget,
    StubSearchTool,
    make_provider,
)
from msa.l3.roles import default_mock_output
from msa.l3.schema import ThesisRejected, validate_thesis
from msa.thesis import thesis_diff

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "l3"


def _referee_override(**patch: Any):  # type: ignore[no-untyped-def]
    def f(req: CompletionRequest) -> dict[str, Any]:
        out = default_mock_output(req)
        for k, v in patch.items():
            if k == "axes":
                for ak, av in v.items():
                    out["axes"][ak].update(av)
            else:
                out[k] = v
        return out

    return f


# ---------------------------------------------------------------- 정상 경로


def test_mock_full_run_writes_outputs(tmp_path: Path) -> None:
    prov = MockProvider()
    res = run_research(inputs(), prov, theses_root=tmp_path / "theses")
    assert res.validation.ok
    assert res.gate.status == "passed"
    assert res.thesis_path is not None and res.thesis_path.exists()
    out_dir = res.thesis_path.parent
    assert (out_dir / "uranium.report.md").exists()
    assert (out_dir / "contested.json").exists()
    assert not (out_dir / "rejections-pending.yaml").exists()
    saved = yaml.safe_load(res.thesis_path.read_text(encoding="utf-8"))
    assert validate_thesis(saved, asof=ASOF).ok
    assert saved["value_trap_axes"]["unit_demand"]["verdict"] == "cycle"
    assert saved["value_trap_axes"]["unit_demand"]["axis1_contested"] is False
    assert saved["cycle_confidence_terms"]["base"] == 0.5
    # 4역할 각 1회 — supply·catalyst·bear 는 병렬이라 순서가 없고, referee 는 반드시 마지막
    assert sorted(r.role for r in prov.requests) == sorted(
        ["supply_analyst", "catalyst_analyst", "bear", "referee"]
    )
    assert prov.requests[-1].role == "referee"
    assert all(res.ledger.calls[r] == 1 for r in res.ledger.calls)
    assert "## bear_case (원문 보존" in res.report_md


def test_confidence_in_pipeline_is_mechanical(tmp_path: Path) -> None:
    """축1 cycle +0.15 · capex 10q +0.10 · 축3 cycle +0.15 · 축4 strong +0.10 · 순풍 없음 → 1.0"""
    res = run_research(inputs(), MockProvider(), theses_root=tmp_path, write=False)
    assert res.confidence.raw == pytest.approx(1.0)
    assert res.thesis["cycle_confidence"] == 1.0
    assert "macro_tailwind" not in res.confidence.terms


def test_bear_case_is_verbatim_from_bear(tmp_path: Path) -> None:
    prov = MockProvider()
    res = run_research(inputs(), prov, theses_root=tmp_path, write=False)
    assert res.thesis["bear_case"] == res.roles.bear["bear_case"]
    assert "(합성 bear_case" in res.thesis["bear_case"]


# ---------------------------------------------------------------- bear 격리


def test_bear_prompt_hides_l1_score(tmp_path: Path) -> None:
    prov = MockProvider()
    res = run_research(inputs(), prov, theses_root=tmp_path, write=False)
    by_role = {r.role: r for r in prov.requests}
    bear_txt = by_role["bear"].as_text()
    supply_txt = by_role["supply_analyst"].as_text()
    # 스코어 숫자·순위·블록 점수·L1 축1 판정이 bear 에 없다
    assert "0.7123" not in bear_txt
    assert "스코어카드" not in bear_txt
    for tok in L1_SCORE_FIELDS:
        assert tok not in bear_txt, tok
    # 같은 토큰이 supply 에는 있다 (대조군)
    assert "0.7123" in supply_txt and '"rank": 3' in supply_txt
    # bear 시스템 프롬프트가 그 사실을 명시한다
    assert "모른다" in by_role["bear"].system
    # 사실 자료(구성원 재무)는 bear 도 받는다
    assert "CCJ" in bear_txt
    assert res.gate.status == "passed"


def test_bear_view_contract_has_no_score_attributes() -> None:
    bv = inputs().bear_view()
    assert not hasattr(bv, "scorecard")
    for f in ("score", "rank", "block_scores"):
        assert not hasattr(bv, f)


# ---------------------------------------------------------------- 게이트 결과


def test_hard_gate_rejection_is_saved_with_pending_row(tmp_path: Path) -> None:
    prov = MockProvider(
        {
            "referee": _referee_override(
                axes={"substitution": {"verdict": "warning", "evidence_refs": [9]}}
            )
        }
    )
    res = run_research(inputs(a1=axis1("death")), prov, theses_root=tmp_path / "theses")
    assert res.gate.status == "rejected" and res.gate.path == "hard_gate"
    assert res.thesis_path is not None and res.thesis_path.exists()  # 기각도 저장한다
    rows = yaml.safe_load(
        (res.thesis_path.parent / "rejections-pending.yaml").read_text(encoding="utf-8")
    )
    assert rows[0]["theme"] == "uranium" and rows[0]["path"] == "hard_gate"
    assert rows[0]["journal"] is None and rows[0]["r_12m"] is None
    assert rows[0]["scoreboard_rank"] == 3
    assert res.thesis["gate_result"]["portfolio_eligible"] is False
    assert res.thesis["gate_result"]["axis_verdicts"]["unit_demand"] == "death"


def test_death_cap_path(tmp_path: Path) -> None:
    res = run_research(inputs(a1=axis1("death")), MockProvider(), theses_root=tmp_path, write=False)
    assert res.gate.status == "passed" and not res.gate.portfolio_eligible
    assert res.thesis["cycle_confidence"] == 0.35
    assert res.thesis["cycle_confidence_terms"]["cap"] == 0.35


def test_schema_failure_is_not_saved(tmp_path: Path) -> None:
    prov = MockProvider({"referee": _referee_override(invalidations=[])})
    with pytest.raises(ThesisRejected) as ei:
        run_research(inputs(), prov, theses_root=tmp_path / "theses")
    assert any("R_INVALIDATIONS_EMPTY" in e for e in ei.value.result.errors)
    assert not (tmp_path / "theses").exists()


def test_schema_failure_on_correlation_mechanism(tmp_path: Path) -> None:
    prov = MockProvider({"referee": _referee_override(mechanism="역사적으로 함께 움직였다.")})
    with pytest.raises(ThesisRejected):
        run_research(inputs(), prov, theses_root=tmp_path, write=False)


def test_axis1_not_applicable_flow(tmp_path: Path) -> None:
    res = run_research(inputs(a1=axis1("na")), MockProvider(), theses_root=tmp_path, write=False)
    ud = res.thesis["value_trap_axes"]["unit_demand"]
    assert ud["verdict"] == "not_applicable" and ud["unit_series_source"] == "none"
    assert ud["axis1_available"] is False
    assert any("axis1_available = false" in k for k in res.thesis["key_uncertainties"])
    assert "axis1_cycle" not in res.confidence.terms  # 감점도 가점도 없다


# ---------------------------------------------------------------- contested


def test_contested_without_ruling_closes_rejected(tmp_path: Path) -> None:
    res = run_research(
        inputs(a1=axis1("contested")), MockProvider(), theses_root=tmp_path / "theses"
    )
    assert res.gate.status == "rejected" and "서술 못 하면 기각" in res.gate.rule
    assert res.thesis["value_trap_axes"]["unit_demand"]["verdict"] == "contested"
    assert res.thesis["value_trap_axes"]["unit_demand"]["axis1_contested"] is True
    assert res.contested.round_contested == 0


def test_contested_with_ruling_is_held_and_counted(tmp_path: Path) -> None:
    # 직전 라운드: coal 이 contested 였고 이번 라운드에 재실행되지 않음 → 이월 1
    prev = tmp_path / "theses" / "2026-07-31"
    prev.mkdir(parents=True)
    (prev / "coal.thesis.yaml").write_text(
        yaml.safe_dump({"theme_id": "coal", "gate_result": {"status": "contested"}}),
        encoding="utf-8",
    )
    (prev / "gold.thesis.yaml").write_text(
        yaml.safe_dump({"theme_id": "gold", "gate_result": {"status": "passed"}}), encoding="utf-8"
    )
    prov = MockProvider(
        {
            "referee": _referee_override(
                axes={
                    "unit_demand": {
                        "referee_ruling": "합산↓ 중앙값→ — 산업 축소이지 수요 소멸이 아니다 (합성)",
                        "referee_evidence_refs": [5],
                    }
                }
            )
        }
    )
    res = run_research(inputs(a1=axis1("contested")), prov, theses_root=tmp_path / "theses")
    assert res.gate.status == "contested" and not res.gate.portfolio_eligible
    g = res.thesis["gate_result"]
    assert g["referee_ruling"] and g["referee_evidence_refs"] == [5]
    assert res.contested.round_contested == 1 and res.contested.round_themes == ["uranium"]
    assert res.contested.carried_over == 1 and res.contested.carried_over_themes == ["coal"]
    cj = json.loads((res.thesis_path.parent / "contested.json").read_text(encoding="utf-8"))  # type: ignore[union-attr]
    assert cj["carried_over"] == 1


def test_count_contested_resolution_clears_carry(tmp_path: Path) -> None:
    prev = tmp_path / "2026-07-31"
    prev.mkdir(parents=True)
    (prev / "coal.thesis.yaml").write_text(
        yaml.safe_dump({"gate_result": {"status": "contested"}}), encoding="utf-8"
    )
    cur = tmp_path / "2026-08-14"
    cur.mkdir()
    (cur / "coal.thesis.yaml").write_text(
        yaml.safe_dump({"gate_result": {"status": "passed"}}), encoding="utf-8"
    )
    cc = count_contested(tmp_path, "2026-08-14", "uranium", "passed")
    assert cc.carried_over == 0 and cc.round_contested == 0


# ---------------------------------------------------------------- drift diff


def test_thesis_diff_detects_drift(tmp_path: Path) -> None:
    first = run_research(inputs(), MockProvider(), theses_root=tmp_path, write=False).thesis
    prior = json.loads(json.dumps(first))
    prior["invalidations"].append(
        {
            "observable": "현물가 $70 이하 3개월",
            "source": "UxC",
            "action": "exit",
            "status": "pending",
        }
    )
    prior["generated_at"] = "2026-07-31"
    second = run_research(
        inputs(prior=prior, prior_path="state/theses/2026-07-31/uranium.thesis.yaml"),
        MockProvider(),
        theses_root=tmp_path,
        write=False,
    )
    d = second.diff
    assert d["has_prior"] and "invalidations" in d["changed"]
    assert d["invalidations"]["removed"] == ["현물가 $70 이하 3개월"]
    assert "claim" in d["unchanged"]
    assert "drift_suspect" in d
    assert second.thesis["supersedes"] == "state/theses/2026-07-31/uranium.thesis.yaml"
    assert "무효화 회피 의심" in second.report_md


def test_thesis_diff_no_prior() -> None:
    assert thesis_diff(None, {"claim": "x"}) == {"has_prior": False}


# ---------------------------------------------------------------- 비용 · 검색 예산


def test_cost_ledger_counts_and_budget(tmp_path: Path) -> None:
    prov = MockProvider()
    res = run_research(inputs(), prov, theses_root=tmp_path, write=False)
    rows = {r["role"]: r for r in res.ledger.rows()}
    assert set(rows) == {"supply_analyst", "catalyst_analyst", "bear", "referee"}
    assert all(r["calls"] == 1 and r["search_budget"] == 15 for r in rows.values())
    assert res.ledger.total().input_tokens > 0
    assert (
        res.ledger.estimated_usd() is None
    )  # mock-model 은 가격표에 없다 → 추정 불가를 숨기지 않는다
    assert "| supply_analyst | mock-model | 1 |" in res.report_md


def test_search_budget_enforced() -> None:
    b = SearchBudget(per_role=15)
    b.charge("bear", 15)
    assert b.remaining("bear") == 0
    with pytest.raises(BudgetExceeded):
        b.charge("bear", 1)
    assert b.remaining("referee") == 15


def test_stub_search_raises_not_configured() -> None:
    with pytest.raises(NotConfigured):
        StubSearchTool().search("uranium spot price", role="supply_analyst")
    assert StubSearchTool().provider_tool_spec(max_uses=15) is None


def test_anthropic_search_spec_carries_budget() -> None:
    from msa.l3.providers import AnthropicWebSearch

    spec = AnthropicWebSearch().provider_tool_spec(max_uses=7)
    assert spec == {"type": "web_search_20260209", "name": "web_search", "max_uses": 7}


def test_anthropic_provider_builds_request_and_counts_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """가짜 클라이언트로 요청 형태(모델 배치·구조화 출력·도구)와 사용량 집계를 본다."""
    from msa.l3.providers import AnthropicProvider, AnthropicWebSearch, ModelConfig

    captured: dict[str, Any] = {}

    class _Block:
        type = "text"
        text = '{"ok": true}'

    class _ST:
        web_search_requests = 4

    class _Usage:
        input_tokens = 100
        output_tokens = 20
        server_tool_use = _ST()

    class _Resp:
        content: ClassVar[list[Any]] = [_Block()]
        usage = _Usage()
        model = "claude-opus-5"
        stop_reason = "end_turn"

    class _Messages:
        def create(self, **kw: Any) -> _Resp:
            captured.update(kw)
            return _Resp()

    class _Client:
        messages = _Messages()

    p = AnthropicProvider(models=ModelConfig(), search=AnthropicWebSearch(), client=_Client())
    req = CompletionRequest(
        role="bear",
        system="s",
        messages=[{"role": "user", "content": "u"}],
        json_schema={"type": "object"},
    )
    r = p.complete(req)
    assert captured["model"] == "claude-opus-5"
    assert captured["thinking"] == {"type": "adaptive"}
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert (
        captured["tools"][0]["type"] == "web_search_20260209"
        and captured["tools"][0]["max_uses"] == 15
    )
    assert r.usage.search_queries == 4 and p.budget.used["bear"] == 4
    assert r.json() == {"ok": True}
    # 표준 모델 배치
    req2 = CompletionRequest(
        role="supply_analyst", system="s", messages=[{"role": "user", "content": "u"}]
    )
    p.complete(req2)
    assert captured["model"] == "claude-sonnet-5"


# ---------------------------------------------------------------- 픽스처 제공자


def test_fixture_provider_full_run(tmp_path: Path) -> None:
    prov = FixtureProvider(FIXTURES, "uranium")
    res = run_research(inputs(), prov, theses_root=tmp_path / "theses")
    assert res.validation.ok, res.validation.errors
    assert res.gate.status == "passed"
    assert res.ledger.models["bear"] == "claude-opus-5"
    assert res.ledger.usage["supply_analyst"].search_queries == 9
    assert res.ledger.estimated_usd() is not None and res.ledger.estimated_usd() > 0
    # 픽스처의 bear_case 가 그대로
    bear = json.loads((FIXTURES / "uranium" / "bear.json").read_text(encoding="utf-8"))
    assert res.thesis["bear_case"] == bear["output"]["bear_case"]
    # referee 추가 증거가 병합됐다
    assert any(e.get("role") == "referee" for e in res.thesis["evidence"])
    assert "W_EVIDENCE_STALE" in " ".join(res.validation.warnings)  # 12개월 초과 증거 표시


def test_fixture_provider_missing_file_raises() -> None:
    from msa.l3.providers import ProviderError

    prov = FixtureProvider(FIXTURES, "no_such_theme")
    with pytest.raises(ProviderError):
        prov.complete(CompletionRequest(role="bear", system="", messages=[]))


def test_make_provider_kinds() -> None:
    assert make_provider("mock", theme_id="x").name == "mock"
    assert make_provider("fixture", theme_id="uranium").name == "fixture"
    assert make_provider("anthropic", theme_id="x").name == "anthropic"  # 클라이언트는 지연 생성
    with pytest.raises(ValueError):
        make_provider("openai", theme_id="x")


# ---------------------------------------------------------------- 입력 조립 (스캔 파일)


def test_assemble_inputs_from_scan_files(tmp_path: Path) -> None:
    write_scan_dir(tmp_path, "2026-07-31", ("uranium", "coal"))
    write_scan_dir(tmp_path, "2026-08-14", ("uranium",))
    assert latest_scan_dir(tmp_path / "scans").name == "2026-08-14"
    assert latest_scan_dir(tmp_path / "scans", asof="2026-08-01").name == "2026-07-31"
    card = load_scorecard(tmp_path / "scans" / "2026-08-14", "uranium")
    assert card.rank == 1 and card.axis1.available and card.axis1.verdict == "cycle"
    assert card.capex_to_da_qtrs_below1 == 10.0
    with pytest.raises(InputsError):
        load_scorecard(tmp_path / "scans" / "2026-08-14", "coal")
    inp = assemble_inputs("uranium", state_dir=tmp_path, with_store=False)
    assert inp.theme_name == "우라늄" and inp.members == ()
    assert any("--no-store" in w for w in inp.warnings)
    assert any("few-shot 없음" in w for w in inp.warnings)
    assert inp.scan_dir == "state/scans/2026-08-14"


def test_assemble_inputs_loads_macro_prior_and_cases(tmp_path: Path) -> None:
    write_scan_dir(tmp_path, ASOF, ("uranium",))
    (tmp_path / "macro").mkdir()
    (tmp_path / "macro" / "latest.json").write_text(
        json.dumps({"asof": ASOF, "regime": "reflation", "tailwind": {"uranium": 0.6}}),
        encoding="utf-8",
    )
    (tmp_path / "cases").mkdir()
    (tmp_path / "cases" / "silver-2015.md").write_text("# 은광 2015\n축1 +3%/y", encoding="utf-8")
    prev = tmp_path / "theses" / "2026-07-31"
    prev.mkdir(parents=True)
    (prev / "uranium.thesis.yaml").write_text(yaml.safe_dump({"claim": "이전"}), encoding="utf-8")
    inp = assemble_inputs("uranium", state_dir=tmp_path, with_store=False)
    assert inp.macro is not None and inp.macro.tailwind == 0.6
    assert inp.prior_thesis == {"claim": "이전"}
    assert inp.prior_thesis_path == "theses/2026-07-31/uranium.thesis.yaml"
    assert [c.case_id for c in inp.cases] == ["silver-2015"]
    prov = MockProvider()
    res = run_research(inp, prov, theses_root=tmp_path / "theses", write=False)
    assert "macro_tailwind" in res.confidence.terms
    by_role = {r.role: r for r in prov.requests}
    assert "silver-2015" in by_role["bear"].as_text()  # few-shot 투입
    assert "## 이전 thesis (theses/2026-07-31" in by_role["referee"].as_text()


def test_missing_scan_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(InputsError):
        assemble_inputs("uranium", state_dir=tmp_path, with_store=False)


# ---------------------------------------------------------------- CLI


def test_cli_research_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from msa.cli import app

    write_scan_dir(tmp_path, ASOF, ("uranium",))
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    r = CliRunner().invoke(app, ["research", "uranium", "--dry-run", "--no-store"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "theses" / ASOF / "uranium.thesis.yaml").exists()
    assert "합성/녹화 산출물" in r.output


def test_cli_research_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from msa.cli import app

    write_scan_dir(tmp_path, ASOF, ("uranium",))
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    r = CliRunner().invoke(
        app, ["research", "uranium", "--provider", "fixture", "--no-store", "--no-write"]
    )
    assert r.exit_code == 0, r.output
    assert not (tmp_path / "theses").exists()
    assert "provider: **fixture**" in r.output


def test_cli_research_schema_failure_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from msa import cli as cli_mod
    from msa.l3 import providers as prov_mod

    write_scan_dir(tmp_path, ASOF, ("uranium",))
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    bad = MockProvider({"referee": _referee_override(invalidations=[])})
    monkeypatch.setattr(prov_mod, "make_provider", lambda *a, **k: bad)
    r = CliRunner().invoke(cli_mod.app, ["research", "uranium", "--provider", "mock", "--no-store"])
    assert r.exit_code == 2
    assert not (tmp_path / "theses").exists()


def test_cli_research_unknown_theme_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from msa.cli import app

    write_scan_dir(tmp_path, ASOF, ("uranium",))
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    r = CliRunner().invoke(app, ["research", "coal", "--dry-run", "--no-store"])
    assert r.exit_code == 1
