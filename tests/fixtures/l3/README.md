# L3 녹화 픽스처

`FixtureProvider` 가 읽는 역할별 산출 (`<theme>/<role>.json`). 형식:

```json
{"model": "...", "usage": {"input_tokens": 0, "output_tokens": 0, "search_queries": 0}, "output": {...}}
```

`uranium/` 의 4건은 **API 호출 없이 손으로 쓴 녹화 형식 예시**다 — 실제 모델 산출이 아니며 수치·URL 은
형식 검증용이다. 실제 실행(`msa research uranium --provider anthropic`)이 가능해지면 응답을 이 형식으로
저장해 교체한다. 증거 번호는 역할별 로컬(1..n)이고 referee 만 전역 번호(supply→catalyst→bear 순 병합)를 쓴다.
