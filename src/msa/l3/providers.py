"""LLM 제공자 추상화 · 웹 검색 훅 · 비용 장부.

파이프라인(`pipeline.py`)은 `LLMProvider.complete()` 만 호출한다. 구현은 셋:

| 구현 | 용도 | 네트워크 |
|---|---|---|
| `AnthropicProvider` | 실제 실행. 공식 `anthropic` SDK, `ANTHROPIC_API_KEY` 필요 | 있음 |
| `MockProvider` | 테스트·`--dry-run`. 역할별 결정론적 산출 (요청 기록 → bear 격리 검사) | 없음 |
| `FixtureProvider` | `tests/fixtures/l3/<theme>/<role>.json` 을 읽는다 — 오프라인 전체 파이프라인
| 없음 |

**모델 배치** (`docs/05` §5): `bear`·`referee` 는 상위 모델, `supply`·`catalyst` 는 표준 모델.
값은 `ModelConfig` 에 있고 환경변수 `MSA_L3_MODEL_TOP` / `MSA_L3_MODEL_STANDARD` 로 덮어쓴다.
모델 ID 는 `claude-api` 스킬 기준(2026-06 캐시): 상위 `claude-opus-5`, 표준 `claude-sonnet-5`.

**웹 검색**: `SearchTool` 프로토콜. 지금 런타임엔 검색 도구가 없으므로 기본은 `StubSearchTool`
(호출하면 `NotConfigured`). Anthropic 서버 도구(`web_search_20260209`)를 쓰려면
`AnthropicWebSearch` 를
넘긴다 — 쿼리 수는 응답 `usage.server_tool_use.web_search_requests` 로 센다. 역할당 예산 ~15
(`docs/05` §5)
은 `SearchBudget` 이 들고 있고, 서버 도구에는 `max_uses` 로 전달된다.

**비용**: `CostLedger` 가 역할별 호출·토큰·검색 수를 센다. 리포트에 그대로 싣는다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from msa import errors

log = logging.getLogger(__name__)

ROLES: tuple[str, ...] = ("supply_analyst", "catalyst_analyst", "bear", "referee")
SEARCH_BUDGET_PER_ROLE = 15  # docs/05 §5 "~15 쿼리"


class ProviderError(errors.ProviderError, RuntimeError):
    """제공자가 쓸 수 있는 응답을 주지 못했다 (거부·절단·JSON 아님). 빈 응답으로 진행하지 않는다."""


class NotConfigured(errors.ProviderError, RuntimeError):
    """검색 도구가 연결되지 않았다. 조용히 검색 없이 진행하지 않고 호출자가 결정하게 한다."""


class BudgetExceeded(errors.ProviderError, RuntimeError):
    """역할별 검색 예산 초과."""


# ---------------------------------------------------------------- 요청/응답


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    search_queries: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.search_queries += other.search_queries


@dataclass(frozen=True)
class CompletionRequest:
    role: str
    system: str
    messages: list[dict[str, Any]]
    json_schema: dict[str, Any] | None = None
    max_tokens: int = 16_000
    allow_search: bool = True

    def as_text(self) -> str:
        """검사·로그용 — 시스템 + 메시지 본문 전체를 한 문자열로."""
        parts = [self.system]
        for m in self.messages:
            c = m.get("content")
            parts.append(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
        return "\n".join(parts)


@dataclass(frozen=True)
class CompletionResult:
    text: str
    usage: Usage
    model: str
    stop_reason: str | None = None

    def json(self) -> dict[str, Any]:
        obj = _parse_json(self.text)
        if not isinstance(obj, dict):
            raise ProviderError(f"JSON 객체가 아니다: {self.text[:200]!r}")
        return obj


def _parse_json(text: str) -> Any:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        # 앞뒤 서술이 붙은 경우 — 첫 '{' 부터 마지막 '}' 까지
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(t[i : j + 1])
            except json.JSONDecodeError:
                pass
        raise ProviderError(f"응답을 JSON 으로 읽지 못했다: {e}") from e


class LLMProvider(Protocol):
    name: str

    def complete(self, request: CompletionRequest) -> CompletionResult: ...


# ---------------------------------------------------------------- 검색 도구


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    date: str | None = None


class SearchTool(Protocol):
    """검색 훅. 클라이언트 측 도구면 `search()` 를, 서버 측 도구면 `provider_tool_spec()` 을 "
    "구현한다."""

    name: str

    def search(self, query: str, *, role: str) -> list[SearchHit]: ...

    def provider_tool_spec(self, *, max_uses: int) -> dict[str, Any] | None: ...


class StubSearchTool:
    """검색 미설정. `search()` 는 `NotConfigured` 를 던지고, 서버 도구 스펙도 없다."""

    name = "none"

    def search(self, query: str, *, role: str) -> list[SearchHit]:
        raise NotConfigured(
            "웹 검색 도구가 연결되지 않았다 — Anthropic 서버 도구(AnthropicWebSearch) 또는 "
            "외부 검색 어댑터를 SearchTool 로 넘겨라. 검색 없이 돌리면 evidence 가 LLM 기억에 "
            "의존한다."
        )

    def provider_tool_spec(self, *, max_uses: int) -> dict[str, Any] | None:
        return None


class AnthropicWebSearch:
    """Anthropic 서버 측 웹 검색 (`web_search_20260209`). 클라이언트 측 `search()` 는 없다."""

    name = "anthropic_web_search"

    def __init__(self, allowed_domains: list[str] | None = None) -> None:
        self.allowed_domains = allowed_domains

    def search(self, query: str, *, role: str) -> list[SearchHit]:
        raise NotConfigured("서버 측 도구다 — 모델이 직접 호출한다. 클라이언트 search() 는 없다.")

    def provider_tool_spec(self, *, max_uses: int) -> dict[str, Any] | None:
        spec: dict[str, Any] = {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": max_uses,
        }
        if self.allowed_domains:
            spec["allowed_domains"] = self.allowed_domains
        return spec


class SearchBudget:
    """역할당 검색 예산. 서버 도구에는 `max_uses` 로, 클라이언트 도구에는 `charge()` 로 강제한다."""

    def __init__(self, per_role: int = SEARCH_BUDGET_PER_ROLE) -> None:
        self.per_role = per_role
        self.used: Counter[str] = Counter()

    def remaining(self, role: str) -> int:
        return max(0, self.per_role - self.used[role])

    def charge(self, role: str, n: int = 1) -> None:
        if self.used[role] + n > self.per_role:
            raise BudgetExceeded(
                f"{role}: 검색 예산 {self.per_role} 초과 (사용 {self.used[role]} + {n})"
            )
        self.used[role] += n


# ---------------------------------------------------------------- 비용 장부

#: USD / 1M 토큰 (claude-api 스킬 캐시 2026-06). 추정치이며 리포트에 "추정" 으로 표기된다.
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass
class CostLedger:
    calls: dict[str, int] = field(default_factory=lambda: dict.fromkeys(ROLES, 0))
    usage: dict[str, Usage] = field(default_factory=lambda: {r: Usage() for r in ROLES})
    models: dict[str, str] = field(default_factory=dict)

    def record(self, role: str, result: CompletionResult) -> None:
        self.calls[role] = self.calls.get(role, 0) + 1
        self.usage.setdefault(role, Usage()).add(result.usage)
        self.models[role] = result.model

    def total(self) -> Usage:
        t = Usage()
        for u in self.usage.values():
            t.add(u)
        return t

    def estimated_usd(self) -> float | None:
        total = 0.0
        known = False
        for role, u in self.usage.items():
            m = self.models.get(role)
            if m in PRICE_PER_MTOK:
                known = True
                pin, pout = PRICE_PER_MTOK[m]
                total += u.input_tokens / 1e6 * pin + u.output_tokens / 1e6 * pout
        return total if known else None

    def rows(self) -> list[dict[str, Any]]:
        return [
            {
                "role": r,
                "model": self.models.get(r, "—"),
                "calls": self.calls.get(r, 0),
                "input_tokens": self.usage[r].input_tokens,
                "output_tokens": self.usage[r].output_tokens,
                "search_queries": self.usage[r].search_queries,
                "search_budget": SEARCH_BUDGET_PER_ROLE,
            }
            for r in ROLES
            if r in self.usage
        ]


# ---------------------------------------------------------------- 모델 배치


@dataclass(frozen=True)
class ModelConfig:
    """`docs/05` §5 모델 배치. 상위 = bear·referee, 표준 = supply·catalyst."""

    top: str = "claude-opus-5"
    standard: str = "claude-sonnet-5"
    effort_top: str = "high"
    effort_standard: str = "medium"

    @classmethod
    def from_env(cls) -> ModelConfig:
        return cls(
            top=os.environ.get("MSA_L3_MODEL_TOP", cls.top).strip() or cls.top,
            standard=os.environ.get("MSA_L3_MODEL_STANDARD", cls.standard).strip() or cls.standard,
        )

    def model_for(self, role: str) -> str:
        return self.top if role in ("bear", "referee") else self.standard

    def effort_for(self, role: str) -> str:
        return self.effort_top if role in ("bear", "referee") else self.effort_standard


# ---------------------------------------------------------------- 구현 1: Anthropic


class AnthropicProvider:
    """공식 `anthropic` SDK. 키는 `ANTHROPIC_API_KEY`(또는 `ant auth login` 프로필)로 SDK 가 푼다.

    구조화 출력은 `output_config.format` (json_schema), 사고는 adaptive, 깊이는
    `output_config.effort`.
    검색은 `SearchTool.provider_tool_spec()` 이 주는 서버 도구를 `tools` 에 싣는다.
    """

    name = "anthropic"

    def __init__(
        self,
        models: ModelConfig | None = None,
        search: SearchTool | None = None,
        budget: SearchBudget | None = None,
        client: Any | None = None,
    ) -> None:
        self.models = models or ModelConfig.from_env()
        self.search = search or StubSearchTool()
        self.budget = budget or SearchBudget()
        self._client = client
        self._lock = threading.Lock()  # 역할 병렬 호출 시 클라이언트를 한 번만 만든다

    def _get_client(self) -> Any:
        with self._lock:
            if self._client is None:
                try:
                    import anthropic
                except ImportError as e:  # pragma: no cover
                    raise ProviderError("`anthropic` 패키지가 없다 — `uv add anthropic`") from e
                self._client = anthropic.Anthropic()
            return self._client

    def complete(self, request: CompletionRequest) -> CompletionResult:
        client = self._get_client()
        model = self.models.model_for(request.role)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": request.messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.models.effort_for(request.role)},
        }
        if request.json_schema is not None:
            kwargs["output_config"]["format"] = {
                "type": "json_schema",
                "schema": request.json_schema,
            }
        if request.allow_search:
            spec = self.search.provider_tool_spec(max_uses=self.budget.remaining(request.role))
            if spec is not None:
                kwargs["tools"] = [spec]
        resp = client.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            raise ProviderError(
                f"{request.role}: 모델이 거부했다 (stop_reason=refusal) — "
                f"{getattr(resp, 'stop_details', None)}"
            )
        if resp.stop_reason == "max_tokens":
            raise ProviderError(
                f"{request.role}: max_tokens={request.max_tokens} 에서 절단됐다 — 늘려서 다시"
            )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        st = getattr(resp.usage, "server_tool_use", None)
        queries = int(getattr(st, "web_search_requests", 0) or 0) if st is not None else 0
        if queries:
            self.budget.used[request.role] += queries
        usage = Usage(
            input_tokens=int(resp.usage.input_tokens),
            output_tokens=int(resp.usage.output_tokens),
            search_queries=queries,
        )
        return CompletionResult(
            text=text, usage=usage, model=str(resp.model), stop_reason=resp.stop_reason
        )


# ---------------------------------------------------------------- 구현 2: Mock


class MockProvider:
    """결정론적 응답. `responses[role]` 이 dict 면 그대로, callable 이면 요청을 받아 dict 를 낸다.

    모든 요청을 `requests` 에 남긴다 — bear 격리 테스트가 이 기록을 검사한다.
    """

    name = "mock"

    def __init__(
        self,
        responses: dict[str, dict[str, Any] | Callable[[CompletionRequest], dict[str, Any]]]
        | None = None,
        *,
        model_name: str = "mock-model",
    ) -> None:
        from msa.l3.roles import default_mock_output

        self._responses = responses or {}
        self._fallback = default_mock_output
        self.model_name = model_name
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        r = self._responses.get(request.role)
        obj: dict[str, Any]
        if r is None:
            obj = self._fallback(request)
        elif callable(r):
            obj = r(request)
        else:
            obj = r
        text = json.dumps(obj, ensure_ascii=False)
        usage = Usage(
            input_tokens=len(request.as_text()) // 4, output_tokens=len(text) // 4, search_queries=0
        )
        return CompletionResult(
            text=text, usage=usage, model=self.model_name, stop_reason="end_turn"
        )


# ---------------------------------------------------------------- 구현 3: 녹화 픽스처


class FixtureProvider:
    """`<root>/<theme>/<role>.json` 을 읽는다. 파일이 없으면 예외 — 빈 응답으로 때우지 않는다.

    파일 형식: `{"model": "...", "usage": {...}, "output": {...}}` 또는 출력 객체 자체.
    """

    name = "fixture"

    def __init__(self, root: Path, theme_id: str) -> None:
        self.root = Path(root)
        self.theme_id = theme_id
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        p = self.root / self.theme_id / f"{request.role}.json"
        if not p.exists():
            raise ProviderError(f"픽스처 없음: {p}")
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "output" in raw:
            out = raw["output"]
            u = raw.get("usage", {})
            usage = Usage(
                input_tokens=int(u.get("input_tokens", 0)),
                output_tokens=int(u.get("output_tokens", 0)),
                search_queries=int(u.get("search_queries", 0)),
            )
            model = str(raw.get("model", "fixture"))
        else:
            out, usage, model = raw, Usage(), "fixture"
        return CompletionResult(
            text=json.dumps(out, ensure_ascii=False),
            usage=usage,
            model=model,
            stop_reason="end_turn",
        )


def make_provider(
    kind: str, *, theme_id: str, fixture_root: Path | None = None, search: SearchTool | None = None
) -> LLMProvider:
    if kind == "anthropic":
        return AnthropicProvider(search=search)
    if kind == "mock":
        return MockProvider()
    if kind == "fixture":
        root = (
            fixture_root
            if fixture_root is not None
            else Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "l3"
        )
        return FixtureProvider(root, theme_id)
    raise ValueError(f"알 수 없는 provider: {kind} (anthropic | mock | fixture)")
