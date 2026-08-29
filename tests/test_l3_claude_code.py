"""ClaudeCodeProvider — 하위 프로세스 계약.

`claude` 를 실제로 부르지 않는다. `subprocess.run` 을 가로채 argv·env·stdout 을 검사한다.
가장 중요한 검사는 **API 키가 하위 프로세스로 새지 않는다** 이다 — 새면 구독이 아니라
크레딧으로 청구된다 (모듈 docstring 참조).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from msa.l3 import claude_code as cc
from msa.l3.providers import CompletionRequest, ProviderError, make_provider

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"verdict": {"type": "string"}, "evidence": {"type": "array"}},
    "required": ["verdict", "evidence"],
}


def _envelope(result: str, *, cost: float = 0.12, searches: int = 0, **over: Any) -> str:
    d: dict[str, Any] = {
        "is_error": False,
        "stop_reason": "end_turn",
        "total_cost_usd": cost,
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 35_000,
            "cache_read_input_tokens": 5,
            "output_tokens": 200,
            "server_tool_use": {"web_search_requests": searches},
        },
        "modelUsage": {"claude-sonnet-5": {}},
        "permission_denials": [],
        "result": result,
    }
    d.update(over)
    return json.dumps(d)


class _Recorder:
    """subprocess.run 대역. 호출을 기록하고 미리 준비한 봉투를 돌려준다."""

    def __init__(self, outs: list[str]) -> None:
        self.outs = list(outs)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"argv": argv, "env": kw.get("env"), "cwd": kw.get("cwd")})
        out = self.outs.pop(0) if self.outs else _envelope("{}")
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


@pytest.fixture
def req() -> CompletionRequest:
    return CompletionRequest(
        role="bear",
        system="너는 반대 의견을 낸다",
        messages=[{"role": "user", "content": "이 테마를 반박하라"}],
        json_schema=SCHEMA,
    )


@pytest.fixture(autouse=True)
def _which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc.shutil, "which", lambda _b: "/usr/bin/claude")


def _provider(monkeypatch: pytest.MonkeyPatch, outs: list[str], **kw: Any) -> tuple[Any, _Recorder]:
    rec = _Recorder(outs)
    monkeypatch.setattr(cc.subprocess, "run", rec)
    return cc.ClaudeCodeProvider(**kw), rec


# ---------------------------------------------------------------- 인증 (핵심)


def test_api_key_is_stripped_from_child_env(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    """키가 남아 있으면 CLI 가 구독 대신 크레딧으로 청구한다 — 그래서 지운다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-should-not-leak")
    prov, rec = _provider(monkeypatch, [_envelope('{"verdict":"x","evidence":[]}')])
    prov.complete(req)
    env = rec.calls[0]["env"]
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "PATH" in env  # 나머지 환경은 그대로 물려준다


def test_api_key_kept_only_when_explicitly_asked(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-deliberate")
    prov, rec = _provider(
        monkeypatch, [_envelope('{"verdict":"x","evidence":[]}')], use_api_key=True
    )
    prov.complete(req)
    assert rec.calls[0]["env"]["ANTHROPIC_API_KEY"] == "sk-ant-deliberate"


def test_missing_binary_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc.shutil, "which", lambda _b: None)
    with pytest.raises(ProviderError, match="실행 파일"):
        cc.ClaudeCodeProvider()


# ---------------------------------------------------------------- argv


def test_argv_opens_search_and_closes_mutation(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    prov, rec = _provider(monkeypatch, [_envelope('{"verdict":"x","evidence":[]}')])
    prov.complete(req)
    argv = rec.calls[0]["argv"]
    assert argv[1] == "-p"
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--allowed-tools") + 1] == "WebSearch WebFetch"
    denied = argv[argv.index("--disallowed-tools") + 1]
    for t in ("Bash", "Edit", "Write"):
        assert t in denied
    assert argv[argv.index("--append-system-prompt") + 1] == "너는 반대 의견을 낸다"
    # 구독 경로는 역할 구분 없이 sonnet — 다만 bear 의 깊이(effort)는 high 로 남는다
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"
    assert argv[argv.index("--effort") + 1] == "high"


def test_prompt_carries_schema_and_date_rule(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    prov, rec = _provider(monkeypatch, [_envelope('{"verdict":"x","evidence":[]}')])
    prov.complete(req)
    prompt = rec.calls[0]["argv"][2]
    assert "이 테마를 반박하라" in prompt
    assert '"verdict"' in prompt  # 스키마가 프롬프트에 실렸다 (CLI 에 구조화 출력이 없다)
    assert "발행일" in prompt and "검색한 날짜가 아니다" in prompt


def test_runs_outside_the_repo(monkeypatch: pytest.MonkeyPatch, req: CompletionRequest) -> None:
    """저장소에서 돌리면 CLAUDE.md 가 자동으로 실려 역할 프롬프트를 오염시킨다."""
    prov, rec = _provider(monkeypatch, [_envelope('{"verdict":"x","evidence":[]}')])
    prov.complete(req)
    assert not str(rec.calls[0]["cwd"]).startswith(str(Path(cc.__file__).parents[3]))


# ---------------------------------------------------------------- 재시도·실패


def test_retries_once_when_required_key_is_missing(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    prov, rec = _provider(
        monkeypatch,
        [_envelope('{"verdict":"x"}'), _envelope('{"verdict":"x","evidence":[]}')],
    )
    res = prov.complete(req)
    assert len(rec.calls) == 2
    assert "evidence" in rec.calls[1]["argv"][2]  # 무엇이 틀렸는지 알려주고 다시 부른다
    assert res.json() == {"verdict": "x", "evidence": []}
    assert res.usage.input_tokens == 2 * 35_015  # 두 호출의 토큰이 모두 장부에 실린다


def test_gives_up_loudly_after_retries(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    prov, _ = _provider(monkeypatch, [_envelope("설명만 하고 JSON 이 없다")] * 2)
    with pytest.raises(ProviderError, match="2회 시도"):
        prov.complete(req)


def test_cli_error_envelope_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    prov, _ = _provider(monkeypatch, [_envelope("한도 초과", is_error=True)])
    with pytest.raises(ProviderError, match="오류를 보고했다"):
        prov.complete(req)


def test_truncation_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    prov, _ = _provider(monkeypatch, [_envelope('{"verdict":"x"', stop_reason="max_tokens")])
    with pytest.raises(ProviderError, match="절단"):
        prov.complete(req)


def test_timeout_is_reported(monkeypatch: pytest.MonkeyPatch, req: CompletionRequest) -> None:
    def boom(*_a: Any, **_kw: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(cc.subprocess, "run", boom)
    with pytest.raises(ProviderError, match="끝나지 않았다"):
        cc.ClaudeCodeProvider(timeout_s=1).complete(req)


# ---------------------------------------------------------------- 장부·검색·녹화


def test_search_overrun_is_logged_not_hidden(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest, caplog: pytest.LogCaptureFixture
) -> None:
    """CLI 에는 max_uses 가 없다. 강제할 수 없으면 최소한 조용하지는 않아야 한다 (§2)."""
    prov, _ = _provider(monkeypatch, [_envelope('{"verdict":"x","evidence":[]}', searches=99)])
    with caplog.at_level("WARNING"):
        res = prov.complete(req)
    assert res.usage.search_queries == 99
    assert "검색 예산" in caplog.text


def test_notional_cost_is_tracked_separately(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    """구독으로 돌아도 봉투는 total_cost_usd 를 낸다 — 크레딧이 나갔다는 뜻이 아니다."""
    prov, _ = _provider(monkeypatch, [_envelope('{"verdict":"x","evidence":[]}', cost=0.34)])
    prov.complete(req)
    assert prov.notional_usd == pytest.approx(0.34)


def test_record_writes_a_replayable_fixture(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest, tmp_path: Path
) -> None:
    prov, _ = _provider(
        monkeypatch,
        [_envelope('{"verdict":"x","evidence":[]}')],
        record_dir=tmp_path,
        theme_id="solar_panels",
    )
    prov.complete(req)
    p = tmp_path / "solar_panels" / "bear.json"
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["output"] == {"verdict": "x", "evidence": []}
    assert saved["provider"] == "claude_code"

    # 녹화한 것을 FixtureProvider 가 그대로 되읽는다 — $0 재현 경로가 실제로 닫힌다
    fx = make_provider("fixture", theme_id="solar_panels", fixture_root=tmp_path)
    assert fx.complete(req).json() == {"verdict": "x", "evidence": []}


def test_make_provider_accepts_the_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("claude_code", "claude-code", "cc"):
        assert make_provider(name, theme_id="t").name == "claude_code"


# ---------------------------------------------------------------- 크레딧 정책


def test_subscription_path_is_sonnet_for_every_role(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    """구독 경로는 전부 sonnet (2026-08-25 지시) — 모델은 낮추되 깊이는 낮추지 않는다.

    실측 근거: `bear`(opus·high)가 9분으로 sonnet 역할의 3배였고, `referee` 가 그것을
    기다리므로 병렬로 돌려도 라운드 시간이 줄지 않았다.
    """
    monkeypatch.delenv("MSA_L3_MODEL_TOP", raising=False)
    monkeypatch.delenv("MSA_L3_MODEL_STANDARD", raising=False)
    prov, rec = _provider(monkeypatch, [_envelope('{"verdict":"x","evidence":[]}')])
    prov.complete(req)
    argv = rec.calls[0]["argv"]
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"
    assert argv[argv.index("--effort") + 1] == "high"


def test_env_override_still_wins_on_the_subscription_path(
    monkeypatch: pytest.MonkeyPatch, req: CompletionRequest
) -> None:
    monkeypatch.setenv("MSA_L3_MODEL_TOP", "claude-opus-5")
    prov, rec = _provider(monkeypatch, [_envelope('{"verdict":"x","evidence":[]}')])
    prov.complete(req)
    argv = rec.calls[0]["argv"]
    assert argv[argv.index("--model") + 1] == "claude-opus-5"


def test_credit_path_is_haiku_only(monkeypatch: pytest.MonkeyPatch, req: CompletionRequest) -> None:
    """`use_api_key=True` 는 크레딧을 쓴다 — 그러면 haiku 로 내려간다 (2026-08-25 지시)."""
    prov, rec = _provider(
        monkeypatch, [_envelope('{"verdict":"x","evidence":[]}')], use_api_key=True
    )
    prov.complete(req)
    argv = rec.calls[0]["argv"]
    assert argv[argv.index("--model") + 1] == "claude-haiku-4-5"


def test_credit_path_refuses_an_explicit_top_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from msa.l3.providers import ModelConfig

    with pytest.raises(ProviderError, match="haiku"):
        cc.ClaudeCodeProvider(
            models=ModelConfig(top="claude-opus-5", standard="claude-sonnet-5"),
            use_api_key=True,
        )


# ---------------------------------------------------------------- 라운드 파일 잠금


def test_parallel_rejections_do_not_clobber_each_other(tmp_path: Path) -> None:
    """테마를 병렬로 돌리면 `rejections-pending.yaml` 이 읽고→고쳐→쓰기로 경합한다.

    잠금이 없으면 늦게 끝난 테마가 먼저 끝난 테마의 기각 행을 **오류 없이** 지운다.
    여기서는 여러 프로세스가 같은 파일을 누적 갱신해도 행이 모두 남는지 본다.
    """
    import multiprocessing as mp

    import yaml as _yaml

    from msa.io import dir_lock

    d = tmp_path / "round"

    def worker(theme: str) -> None:
        rp = d / "rejections-pending.yaml"
        with dir_lock(d):
            rows = _yaml.safe_load(rp.read_text(encoding="utf-8")) if rp.exists() else []
            rows = [r for r in (rows or []) if r.get("theme") != theme]
            rows.append({"theme": theme})
            rp.write_text(_yaml.safe_dump(rows, allow_unicode=True), encoding="utf-8")

    themes = [f"theme_{i}" for i in range(8)]
    ctx = mp.get_context("fork")
    procs = [ctx.Process(target=worker, args=(t,)) for t in themes]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)

    rows = yaml.safe_load((d / "rejections-pending.yaml").read_text(encoding="utf-8"))
    assert sorted(r["theme"] for r in rows) == sorted(themes)


def test_work_dir_survives_being_deleted_mid_round() -> None:
    """**라운드가 몇 분이라 그 사이 작업 디렉터리가 사라질 수 있다.**

    2026-08-29 실측: 판별이 277초 돌다 `FileNotFoundError: /tmp/msa-l3-...` 로 죽었다.
    중립 디렉터리라 내용이 없으므로, 없으면 다시 만들면 된다 — 끝나가던 작업을 디렉터리
    하나 때문에 버리지 않는다.
    """
    import shutil

    from msa.l3.claude_code import ClaudeCodeProvider

    p = ClaudeCodeProvider(theme_id="t")
    first = p._work_dir()
    assert first.is_dir()

    shutil.rmtree(first)  # 누가 지웠다
    assert not first.exists()

    again = p._work_dir()
    assert again.is_dir(), "지워졌으면 다시 만든다"


def test_work_dir_does_not_depend_on_a_finalizer() -> None:
    """**파이널라이저에 기대면 검사와 exec 사이에 경쟁이 남는다.**

    2026-08-29 실측: `_work_dir()` 이 존재를 확인하고 돌려준 뒤, subprocess 가 exec 하기
    전에 `TemporaryDirectory` 파이널라이저가 그 디렉터리를 지웠다 —
    `FileNotFoundError: PosixPath('/tmp/msa-l3-kf85w8sl')` 로 죽었다. 판별 두 개를
    병렬로 돌릴 때 나왔다.

    존재 확인을 더 촘촘히 해도 그 창은 안 닫힌다. 파이널라이저를 아예 안 쓰는 것이
    유일한 수정이다.
    """
    from msa.l3.claude_code import ClaudeCodeProvider

    p = ClaudeCodeProvider(theme_id="t")
    d = p._work_dir()
    assert d.is_dir()
    assert p._tmp is None, "TemporaryDirectory 객체를 들고 있으면 파이널라이저가 산다"


def test_work_dir_is_stable_across_calls() -> None:
    from msa.l3.claude_code import ClaudeCodeProvider

    p = ClaudeCodeProvider(theme_id="t")
    assert p._work_dir() == p._work_dir()


def test_work_dir_is_recreated_if_deleted() -> None:
    """지워져도 다시 만든다 — 중립 디렉터리라 내용이 없어도 잃을 것이 없다."""
    import shutil

    from msa.l3.claude_code import ClaudeCodeProvider

    p = ClaudeCodeProvider(theme_id="t")
    d = p._work_dir()
    shutil.rmtree(d)
    assert not d.exists()
    assert p._work_dir().is_dir()


def test_two_providers_get_different_work_dirs() -> None:
    """병렬 판별이 서로의 디렉터리를 건드리면 안 된다."""
    from msa.l3.claude_code import ClaudeCodeProvider

    a = ClaudeCodeProvider(theme_id="a")._work_dir()
    b = ClaudeCodeProvider(theme_id="b")._work_dir()
    assert a != b
