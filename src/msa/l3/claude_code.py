"""제공자 4: 로컬 `claude` CLI 를 하위 프로세스로 부른다 (API 크레딧을 쓰지 않는다).

`AnthropicProvider` 와 같은 `LLMProvider` 계약을 지키되, 호출을 SDK 가 아니라
`claude -p ... --output-format json` 서브프로세스로 한다. 목적은 하나다 — **구독 로그인으로
L3 를 돌려 API 크레딧 소모를 0 으로 만든다.**

## 왜 키를 지우는가 (이 모듈의 존재 이유)

`ANTHROPIC_API_KEY` 가 환경에 있으면 `claude` CLI 는 그것을 **구독 로그인보다 우선**한다:

    ⚠ claude.ai connectors are disabled because ANTHROPIC_API_KEY ... takes precedence

이때 호출은 크레딧으로 청구된다. Claude Code 는 매 호출에 시스템 프롬프트 ~35k 토큰을
붙이므로 사소한 질문 하나도 $0.09 였다 (2026-08-25 실측). 4역할 × 재시도면 테마당 $1 을
넘는다. 그래서 `_child_env()` 가 하위 프로세스 환경에서 키를 **지운다**. 크레딧으로 돌리려면
`use_api_key=True` 를 명시해야 한다 — 기본값으로 새지 않는다.

`use_api_key=True` 로 굳이 크레딧을 쓰겠다면 모델은 haiku 로 제한된다
(`providers.enforce_api_credit_models`, 2026-08-25 지시). 기본 경로에는 그 제한이 없다 —
크레딧이 나가지 않으므로 `bear`·`referee` 가 상위 모델을 그대로 쓴다.

`--bare` 는 쓰지 않는다. CLAUDE.md 자동 탐색을 끄는 이점이 있지만 인증이 `ANTHROPIC_API_KEY`
전용으로 고정되어(OAuth·키체인을 읽지 않는다) 이 모듈의 목적과 정면으로 충돌한다.
CLAUDE.md 오염은 중립 작업 디렉터리(`cwd`)로 막는다.

## 구조화 출력이 없다

CLI 에는 `output_config.format` 이 없다. 그래서 스키마를 **프롬프트로** 주고, 받은 텍스트를
파싱한 뒤 최상위 `required` 키를 확인한다. 실패하면 무엇이 틀렸는지 적어 한 번 더 부른다
(`max_retries`). 조용히 빈 응답으로 넘어가지 않는다 (CLAUDE.md §2).
깊은 검증은 기존 자리(`roles.check_role_output` → `schema.py`)가 그대로 한다.

## 검색

`--allowed-tools "WebSearch WebFetch"` 로 두 도구만 연다. 파일 수정·셸은 금지 목록에 둔다 —
리서치 역할은 저장소를 만질 이유가 없다. 서버 도구 `max_uses` 는 CLI 에 없으므로 예산은
프롬프트로 알리고 **실제 사용량을 응답에서 세어** 초과하면 경고로 남긴다 (§2 — 조용히 자르지도,
조용히 넘기지도 않는다).

## 비용 표기

봉투의 `total_cost_usd` 는 **구독으로 돌 때도 계산되어 나오는 명목값**이다. 크레딧이 나갔다는
뜻이 아니다. `CostLedger` 에는 토큰만 싣고, 명목 비용은 `notional_usd` 로 따로 들고 다닌다.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from msa.l3.providers import (
    HAIKU_ONLY,
    CompletionRequest,
    CompletionResult,
    ModelConfig,
    ProviderError,
    SearchBudget,
    Usage,
    _parse_json,
    enforce_api_credit_models,
)

log = logging.getLogger(__name__)

#: 열어주는 도구. 리서치 역할이 필요한 것은 검색과 열람뿐이다.
ALLOWED_TOOLS: tuple[str, ...] = ("WebSearch", "WebFetch")

#: 명시적으로 막는 도구. `--allowed-tools` 만으로도 나머지는 승인 없이 못 쓰지만,
#: 의도를 코드에 남긴다 — 리서치가 저장소를 고치는 일은 설계상 없다.
DENIED_TOOLS: tuple[str, ...] = ("Bash", "Edit", "Write", "NotebookEdit", "Task", "Agent")

#: 모델 별칭 — CLI 는 별칭과 전체 이름을 모두 받는다. ModelConfig 값이 전체 이름이면 그대로 쓴다.
DEFAULT_TIMEOUT_S = 900


def _child_env(*, use_api_key: bool) -> dict[str, str]:
    """하위 `claude` 프로세스의 환경. 기본은 API 키를 **지운다** (모듈 docstring 참조)."""
    env = dict(os.environ)
    if not use_api_key:
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            env.pop(k, None)
    return env


def _schema_instruction(schema: dict[str, Any] | None) -> str:
    if schema is None:
        return (
            "\n\n---\n출력 규칙: **JSON 객체 하나만** 출력한다. 앞뒤 설명·머리말·"
            "코드펜스를 붙이지 않는다."
        )
    return (
        "\n\n---\n출력 규칙: 아래 JSON Schema 를 만족하는 **JSON 객체 하나만** 출력한다. "
        "앞뒤 설명·머리말·코드펜스를 붙이지 않는다. 스키마에 없는 키를 만들지 않는다.\n\n"
        f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```"
    )


def _search_instruction(budget: int) -> str:
    return (
        f"\n\n검색 예산: 이 역할에서 WebSearch 를 최대 {budget} 회까지 쓴다. "
        "각 근거에는 출처 URL 과 **그 문서의 발행일**을 적는다 — 검색한 날짜가 아니다. "
        "확인되지 않은 날짜를 지어내지 않는다."
    )


def _flatten(request: CompletionRequest) -> str:
    """messages 를 하나의 프롬프트 본문으로. CLI 는 단일 프롬프트만 받는다."""
    parts: list[str] = []
    for m in request.messages:
        c = m.get("content")
        text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        role = m.get("role", "user")
        parts.append(text if role == "user" else f"[{role}]\n{text}")
    return "\n\n".join(parts)


def _missing_required(obj: dict[str, Any], schema: dict[str, Any] | None) -> list[str]:
    """최상위 `required` 만 본다. 깊은 검증은 roles/schema 가 이미 하고 있다."""
    if not schema:
        return []
    req = schema.get("required") or []
    return [k for k in req if k not in obj]


@dataclass
class _Envelope:
    """`--output-format json` 봉투에서 우리가 쓰는 것만."""

    result: str
    input_tokens: int
    output_tokens: int
    searches: int
    model: str
    notional_usd: float
    is_error: bool
    stop_reason: str | None
    denials: list[Any] = field(default_factory=list)

    @classmethod
    def parse(cls, raw: str) -> _Envelope:
        i = raw.find("{")
        if i < 0:
            raise ProviderError(f"claude CLI 가 JSON 봉투를 내지 않았다: {raw[:300]!r}")
        try:
            d = json.loads(raw[i:])
        except json.JSONDecodeError as e:
            raise ProviderError(f"claude CLI 봉투를 읽지 못했다: {e} — {raw[i : i + 300]!r}") from e
        u = d.get("usage") or {}
        st = u.get("server_tool_use") or {}
        models = list((d.get("modelUsage") or {}).keys())
        return cls(
            result=str(d.get("result") or ""),
            # 캐시 생성/읽기도 입력이다 — 빼면 장부가 실제보다 작아 보인다.
            input_tokens=int(u.get("input_tokens") or 0)
            + int(u.get("cache_creation_input_tokens") or 0)
            + int(u.get("cache_read_input_tokens") or 0),
            output_tokens=int(u.get("output_tokens") or 0),
            searches=int(st.get("web_search_requests") or 0),
            model=models[0] if models else "claude-code",
            notional_usd=float(d.get("total_cost_usd") or 0.0),
            is_error=bool(d.get("is_error")),
            stop_reason=d.get("stop_reason"),
            denials=list(d.get("permission_denials") or []),
        )


class ClaudeCodeProvider:
    """로컬 `claude` CLI 하위 프로세스. 기본은 구독 인증(= API 크레딧 0)."""

    name = "claude_code"

    def __init__(
        self,
        models: ModelConfig | None = None,
        budget: SearchBudget | None = None,
        *,
        binary: str = "claude",
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = 1,
        use_api_key: bool = False,
        cwd: Path | None = None,
        record_dir: Path | None = None,
        theme_id: str = "",
    ) -> None:
        # `use_api_key=True` 는 크레딧 경로다 — 그러면 haiku 만 허용된다 (2026-08-25 지시).
        # 기본(구독)에서는 제한이 없다: 크레딧이 나가지 않으므로 bear·referee 가 상위 모델을 쓴다.
        if models is not None:
            self.models = models
        else:
            self.models = HAIKU_ONLY if use_api_key else ModelConfig.from_env()
        if use_api_key:
            enforce_api_credit_models(self.models)
        self.budget = budget or SearchBudget()
        self.binary = binary
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.use_api_key = use_api_key
        self._cwd = cwd
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.record_dir = record_dir
        self.theme_id = theme_id
        self.notional_usd = 0.0
        if shutil.which(binary) is None:
            raise ProviderError(
                f"`{binary}` 실행 파일을 찾지 못했다 — Claude Code CLI 가 PATH 에 있어야 한다."
            )

    # ------------------------------------------------------------ 실행

    def _work_dir(self) -> Path:
        """중립 작업 디렉터리. 저장소에서 돌리면 CLAUDE.md 가 자동으로 실려 역할을 오염시킨다."""
        if self._cwd is not None:
            return self._cwd
        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="msa-l3-")
        return Path(self._tmp.name)

    def _argv(self, request: CompletionRequest, prompt: str) -> list[str]:
        argv = [
            self.binary,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            self.models.model_for(request.role),
            "--effort",
            self.models.effort_for(request.role),
            "--disallowed-tools",
            " ".join(DENIED_TOOLS),
        ]
        if request.system:
            argv += ["--append-system-prompt", request.system]
        if request.allow_search:
            argv += ["--allowed-tools", " ".join(ALLOWED_TOOLS)]
        return argv

    def _run_once(self, request: CompletionRequest, prompt: str) -> _Envelope:
        argv = self._argv(request, prompt)
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                env=_child_env(use_api_key=self.use_api_key),
                cwd=self._work_dir(),
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ProviderError(
                f"{request.role}: claude CLI 가 {self.timeout_s}s 안에 끝나지 않았다"
            ) from e
        if proc.returncode != 0 and not proc.stdout.strip():
            raise ProviderError(
                f"{request.role}: claude CLI 종료코드 {proc.returncode} — {proc.stderr[:400]!r}"
            )
        env = _Envelope.parse(proc.stdout)
        if env.is_error:
            raise ProviderError(
                f"{request.role}: claude CLI 가 오류를 보고했다 — {env.result[:300]}"
            )
        if env.stop_reason == "max_tokens":
            raise ProviderError(f"{request.role}: 응답이 max_tokens 에서 절단됐다")
        if env.denials:
            # §2 — 권한 거부는 조용히 넘기지 않는다. 검색이 막힌 채 "근거 없음" 이 나오면
            # 그건 모델의 판단이 아니라 설정 사고다.
            log.warning(
                "%s: 도구 권한 거부 %d 건 — %s", request.role, len(env.denials), env.denials
            )
        return env

    def complete(self, request: CompletionRequest) -> CompletionResult:
        base = _flatten(request) + _schema_instruction(request.json_schema)
        if request.allow_search:
            base += _search_instruction(self.budget.remaining(request.role))

        prompt = base
        total = Usage()
        model = "claude-code"
        last_err = ""
        for attempt in range(self.max_retries + 1):
            env = self._run_once(request, prompt)
            total.input_tokens += env.input_tokens
            total.output_tokens += env.output_tokens
            total.search_queries += env.searches
            self.notional_usd += env.notional_usd
            model = env.model
            if env.searches:
                self.budget.used[request.role] += env.searches
                if self.budget.used[request.role] > self.budget.per_role:
                    log.warning(
                        "%s: 검색 예산 %d 초과 — 실제 %d 회 (CLI 는 max_uses 를 강제하지 못한다)",
                        request.role,
                        self.budget.per_role,
                        self.budget.used[request.role],
                    )
            try:
                obj = _parse_json(env.result)
                if not isinstance(obj, dict):
                    raise ProviderError("JSON 객체가 아니다")
                missing = _missing_required(obj, request.json_schema)
                if missing:
                    raise ProviderError(f"최상위 필수 키 누락: {missing}")
            except ProviderError as e:
                last_err = str(e)
                if attempt >= self.max_retries:
                    raise ProviderError(
                        f"{request.role}: {self.max_retries + 1}회 시도 후에도 스키마를 "
                        f"만족하는 JSON 을 받지 못했다 — {last_err}"
                    ) from e
                log.warning("%s: 시도 %d 실패(%s) — 다시 부른다", request.role, attempt + 1, e)
                prompt = (
                    base + f"\n\n---\n직전 응답이 거부됐다: {last_err}\n"
                    "이번에는 규칙을 지켜 JSON 객체 하나만 출력한다."
                )
                continue
            self._record(request.role, obj, env, total)
            return CompletionResult(
                text=json.dumps(obj, ensure_ascii=False),
                usage=total,
                model=model,
                stop_reason=env.stop_reason or "end_turn",
            )
        raise ProviderError(f"{request.role}: 도달 불가")  # pragma: no cover

    # ------------------------------------------------------------ 녹화

    def _record(self, role: str, obj: dict[str, Any], env: _Envelope, usage: Usage) -> None:
        """성공한 역할 산출을 픽스처로 남긴다 — 같은 라운드를 $0·오프라인으로 재현하려고."""
        if self.record_dir is None or not self.theme_id:
            return
        d = Path(self.record_dir) / self.theme_id
        d.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": env.model,
            "provider": self.name,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "search_queries": usage.search_queries,
            },
            "notional_usd": env.notional_usd,
            "output": obj,
        }
        p = d / f"{role}.json"
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log.info("픽스처 녹화: %s", p)
