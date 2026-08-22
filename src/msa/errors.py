"""계층 공통 예외 뿌리 — CLI 종료 코드와 1:1 로 맞춘다.

각 계층의 예외(`ThemeSpecError`·`InputsError`·`ThesisRejected`·…)는 **이름과 기존 부모를
그대로 둔 채** 여기 있는 뿌리를 앞에 하나 더 상속한다 (`class ThemeSpecError(RefusedInput,
ValueError)`). 그래서 `except ValueError` 로 잡던 호출자·테스트는 그대로 동작하고, CLI 는
`MsaError` 하나만 잡아 `exit_code` 로 종료한다 (`msa.cli.cli_guard`).

| 뿌리 | 뜻 | exit |
|---|---|---|
| `RefusedInput` | 입력(파일·인자·스키마)이 규약을 어겨 **시작하지 않았다** | 1 |
| `Rejected` | 산출물이 검증에 걸려 **저장하지 않았다** (thesis 스키마 등) | 2 |
| `Immutable` | append-only · 불변 행을 고치려 했다 | 1 |
| `ProviderError` | 외부 제공자(LLM·검색)가 쓸 수 있는 응답을 주지 못했다 | 3 |

종료 코드는 기존 `msa research` 의 1/2/3 규약(`docs/05`)을 그대로 옮긴 것이다 — 바꾸지 않는다.
"""

from __future__ import annotations


class MsaError(Exception):
    """이 저장소의 도메인 예외 뿌리. `exit_code` 는 CLI 가 그대로 쓴다."""

    exit_code: int = 1


class RefusedInput(MsaError):
    """입력이 규약을 어긴다 — 추정하지 않고 거부한다 (`CLAUDE.md` §2)."""


class Rejected(MsaError):
    """산출물이 검증에 걸려 저장하지 않았다 (`CLAUDE.md` §3·§5)."""

    exit_code = 2


class Immutable(MsaError):
    """append-only 규약 위반 (`CLAUDE.md` §6)."""


class ProviderError(MsaError):
    """외부 제공자 오류 — 빈 응답으로 진행하지 않는다."""

    exit_code = 3
