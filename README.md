# macro-sector-agent

**거시 → 산업 사이클 → 테마 선정 → 종목 → 포트폴리오** 로 내려오는 하향식 리서치 파이프라인.
"지금 무엇을 사야 하는가" 가 아니라 **"지금 어느 테마가 잊혀졌고, 그것이 사이클 저점인가 구조적 사망인가"** 를 먼저 답한다.

> **상태: 설계 단계 (M0).** 이 저장소에는 아직 코드가 없다. `docs/` 의 설계가 합의되면 구현을 시작한다.
> 구현은 Sharadar 스토어가 있는 머신에서 시작한다 (`docs/08-data-contract.md` §6 부트스트랩 절차).

---

## 무엇을 푸는가

직업이 있는 개인이 **월 단위**로 의사결정하며 낼 수 있는 최선의 초과수익은
데이 트레이딩도, 팩터 알파의 소수점 경쟁도 아니다.
**아무도 보지 않는 테마가 사이클 저점에서 돌아설 때 먼저 들어가 있는 것**이다.

2026년 원자재 사례가 이 저장소의 원형이다 — 고점 대비 50% 이상 하락한
AG(은) · SBSW(PGM) · MP(희토류) · ALM(리튬) 로 구성해 단기에 30%+ 를 실현했다.
그 판단은 재현 가능한 절차가 아니었다. **이 저장소는 그 절차를 만든다.**

## 파이프라인

| 계층 | 하는 일 | 성격 |
|---|---|---|
| **L0** 데이터 | Sharadar (SF1·SEP·DAILY·TICKERS·ACTIONS·SFP) + FRED 거시 + ETF 프록시 | 결정론 |
| **L1** 사이클 상태기 | 85개 테마 버킷의 6블록 상태벡터 — 망각·베이스·턴·밸류·**자본사이클**·펀더멘털 | 결정론 |
| **L2** 거시 인과 DAG | 드라이버 → 채널 → 테마 를 **부호·시차·근거와 함께 선언**. 학습하지 않는다 | 선언적 |
| **L3** 에이전트 리서치 | 상위 K개 테마만 — 물리적 수급 · 정책 촉매 · **베어 에이전트(논지 파괴 전담)** | LLM |
| **L4** 종목 선정 | 테마 구성종목을 **생존 · 토크 · 타이밍** 3축으로 랭킹, 바벨 구성 | 결정론 |
| **L5** 포트 구성기 | MDD 30% 를 리스크 예산으로 배분. 물타기 사다리 · 2단 스탑 · 3단 TP 를 **사전 계획** | 최적화 |
| **L6** 운영 | 월간 풀스캔 · 주간 트리거 점검 · 결정 저널 (append-only) · 텔레그램 | 운영 |

## 이 저장소의 지배적 규약

**백테스트를 하지 않는다.** 테마 사이클은 표본이 20~30개뿐이라 통계적 검증이 성립하지 않는다.
대신 관문을 **사전 반증가능성(ex-ante falsifiability)** 으로 옮긴다 —
모든 테마 논지는 *관측 가능한 트리거* 와 *무효화 조건* 없이는 저장될 수 없고,
검증은 백테스트가 아니라 **전향적 기록** 과 **확신도 캘리브레이션(Brier score)** 이 한다.
자세히는 `docs/10-validation.md`.

## 문서

| | |
|---|---|
| [00-overview](docs/00-overview.md) | 문제 정의 · 계층 구조 · 비목표 · 기존 저장소와의 경계 |
| [01-theme-universe](docs/01-theme-universe.md) | 3중 테마 정의 (industry + 큐레이션 + ETF 프록시), 85개 버킷 초안, 사이클 유형 분류 |
| [02-cycle-state](docs/02-cycle-state.md) | L1 상태벡터 6블록 전 지표 정의와 수식 |
| [03-macro-dag](docs/03-macro-dag.md) | L2 거시 인과 DAG 스펙 · 드라이버 목록 · 국면 4분면 · 모순 감사 |
| [04-value-trap](docs/04-value-trap.md) | **사이클 저점 vs 구조적 사망 판별기** — 이 저장소의 핵심 IP |
| [05-agent-research](docs/05-agent-research.md) | L3 에이전트 계약 · thesis 객체 스키마 · 베어/레퍼리 구조 |
| [06-stock-selection](docs/06-stock-selection.md) | L4 생존 · 토크 · 타이밍 3축과 바벨 구성 |
| [07-portfolio](docs/07-portfolio.md) | L5 리스크 예산 최적화 정식화 · 물타기 사다리 · 2단 스탑 · TP 사다리 |
| [08-data-contract](docs/08-data-contract.md) | 데이터 계약 · 재사용 경계 · **부트스트랩 절차** |
| [09-operations](docs/09-operations.md) | 케이던스 · 결정 저널 · 배달 |
| [10-validation](docs/10-validation.md) | 백테스트 없는 관문 |
| [11-roadmap](docs/11-roadmap.md) | 구현 순서와 마일스톤 완료 판정 기준 |
| [specs/](docs/specs/) | `themes.example.yaml` · `macro-dag.example.yaml` · `thesis.schema.yaml` |

## 관련 저장소

| 저장소 | 이 저장소가 가져가는 것 |
|---|---|
| `portfolio-research` | Sharadar 직판 어댑터 · DuckDB PIT 스토어 · 팩터 DSL · 13612W 시그널 |
| `momentum` | Minervini Stage 분석 · VCP 탐지 · RS Rating (**지수 레벨로 승격해 사용**) |
| `fin-checkup` | 재무 레드플래그 · 텔레그램 알림 · 스케줄러 |

## 면책

투자 조언이 아니다. 이 저장소는 측정값과 명시된 가정을 산출할 뿐이며, 집행은 사람이 한다.
