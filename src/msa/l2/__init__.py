"""L2 거시 인과 DAG 런타임 (`docs/03-macro-dag.md`) — `msa macro`.

| 모듈 | 역할 |
|---|---|
| `dag` | `state/macro-dag.yaml` 적재·스키마 검증·(엣지, 테마) 쌍 전개 |
| `sources` | 드라이버 원시 시계열 로더 (FRED 캐시 · 파생 · ETF 프록시 · 수동 CSV · Sharadar) |
| `drivers` | 발표 지연 반영 → 측정값(transform) → 방향 상태 {−1, 0, +1} |
| `tailwind` | §4 순풍 점수 + 공통 인자 횡단면 중앙값 차감 |
| `regime` | §5 국면 4분면 (성장·인플레 z 축 + 신용 3차원) |
| `audit` | §6 `contradicts_when` 평가 |
| `signcheck` | 엣지 부호 일치율 실측 (`docs/10-validation.md` §2.1) |
| `runtime` | 오케스트레이션 · 리포트 · `state/macro/<date>/` 기록 |

데이터로 엣지를 조정하지 않는다 (`CLAUDE.md` §1). 없는 시리즈는 **이름을 적어 보고**한다 (§2).
"""
