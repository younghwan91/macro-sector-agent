"""L4 종목 선정 (`docs/06-stock-selection.md`) — 전 과정 결정론. LLM 없음 (`CLAUDE.md` §4).

| 모듈 | 역할 |
|---|---|
| `features` | 테마 구성원의 종목 레벨 PIT 재무·가격 특성 (S·T·M 의 원재료) |
| `axes` | 하드 제외 필터 · 3축 원점수 · 테마 내 백분위 · 종합 점수 (순수 함수) |
| `barbell` | 앵커/토크 분류 |
| `picks` | `msa picks <theme>` 오케스트레이션 · 리포트 · 파일 |
"""
