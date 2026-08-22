"""L3 — 에이전트 리서치 (`docs/05-agent-research.md`).

LLM 은 파이프라인의 **좁은 허리**에만 있다. 이 패키지가 하는 일:

| 모듈 | 역할 |
|---|---|
| `contracts` | L3 가 받는 입력 계약(스코어카드·축1 입력·구성원 재무·거시 상태·이전 thesis)과 로더 |
| `providers` | `LLMProvider` 프로토콜 + Anthropic/Mock/Fixture 구현, `SearchTool` 훅, 비용 장부 |
| `roles` | 4역할(supply · catalyst · bear · referee) 프롬프트 — 코드가 들고 있는 템플릿 |
| `schema` | thesis 객체 검증 (`docs/specs/thesis.schema.yaml` + `docs/05` §4 규약) |
| `gates` | `docs/04` §3 하드 게이트 · §3.1 contested · §4 확신도 가감점 — 전부 기계적 |
| `pipeline` | supply ‖ catalyst ‖ bear(격리) → referee → 게이트 → 검증 → 저장 |

thesis 의 enum·파일 읽기/쓰기·표류 diff 는 패키지 밖 `msa.thesis` 가 단일 출처다 — L5·운영 계층도
같은 것을 쓴다. `schema`·`gates` 의 옛 이름(`ACTIONS`·`VERDICTS`)은 그 재수출이다.

에이전트는 **테마만** 고른다 (`CLAUDE.md` §4). 종목·비중·스코어는 여기서 만들지 않는다.
"""
