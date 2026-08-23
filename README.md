# macro-sector-agent

**거시 → 산업 사이클 → 테마 선정 → 종목 → 포트폴리오** 로 내려오는 하향식 리서치 파이프라인.
"지금 무엇을 사야 하는가" 가 아니라 **"지금 어느 테마가 잊혀졌고, 그것이 사이클 저점인가 구조적 사망인가"** 를 먼저 답한다.

> **상태: M1~M8 전 마일스톤 1차 구현 (2026-08-23).** L0 데이터(M1) · 테마 134 버킷(M2) · L1 스캐너 `msa scan`(M3) ·
> L1 백테스트 관문 `msa backtest l1`(M3.5) · L2 거시 런타임 `msa macro`(M4) · L4 종목 선정 `msa picks`(M5) ·
> L5 포트 구성기 `msa portfolio`(M6) · L3 에이전트 `msa research`(M7) · 운영 `msa check`/`journal`/`ops`(M8) ·
> 배선 `msa portfolio-inputs`(W1) · `msa run monthly|weekly`(W4 — 월간 한 명령, 끝은 제안·초안).
> **L1 집계 구조: 2026-08-23 S2 채택.** M3.5 에서 구 복합 점수(6블록 가산)의 12M rank-IC 는 0 과 구분되지
> 않았고(+0.048 [−0.024, +0.123], FAIL), 사전 등록된 M3.6 에서 "A·B 는 풀 자격, C·E·F 가 순위" 구조(S2)가
> +0.078 [+0.015, +0.145] 로 합격해 채택했다 (`docs/02` §7.1, `docs/backtest-l1.md` §12). 한계도 같이 적혀
> 있다 — DSR(632) 0.003, 12M 스프레드 0 포함, 원자재 클래스 미유의. 가중치 값은 바꾸지 않았다 (`CLAUDE.md` §1).
> 설계 질문 기록은 `docs/12-design-question-a-block.md`. 실측 블로커: `FRED_API_KEY`(L2 드라이버·CPI) ·
> `ANTHROPIC_API_KEY`(L3 실행) · manual 실물 시계열. 진행 상태는 `docs/11-roadmap.md`. 데이터는 `~/data/us_micro.duckdb`(Sharadar) 이며
> 없으면 `docs/08-data-contract.md` §6 부트스트랩 절차를 먼저 밟는다.

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
| **L1** 사이클 상태기 | 134개 테마 버킷의 6블록 상태벡터 — 망각·베이스·턴·밸류·**자본사이클**·펀더멘털 | 결정론 |
| **L2** 거시 인과 DAG | 드라이버 → 채널 → 테마 를 **부호·시차·근거와 함께 선언**. 학습하지 않는다. **순위에 들어가지 않는 오버레이** (역풍 `tailwind < −0.5` 제외·모순 감사·신용 스트레스 플래그·L3 컨텍스트 — 2026-08-23 결정, `docs/03` §4.1·`docs/13`) | 선언적 |
| **L3** 에이전트 리서치 | 상위 K개 테마만 — 물리적 수급 · 정책 촉매 · **베어 에이전트(논지 파괴 전담)** | LLM |
| **L4** 종목 선정 | 테마 구성종목을 **생존 · 토크 · 타이밍** 3축으로 랭킹, 바벨 구성 | 결정론 |
| **L5** 포트 구성기 | MDD 30% 를 리스크 예산으로 배분. 물타기 사다리 · 2단 스탑 · 3단 TP 를 **사전 계획** | 최적화 |
| **L6** 운영 | 월간 풀스캔 · 주간 트리거 점검 · 결정 저널 (append-only) · 텔레그램 | 운영 |

## 이 저장소의 지배적 규약

**백테스트는 절반만 한다.** 결정론 계층(L1 스코어보드 · L2 거시 DAG · L4 종목 선정)은
입력이 가격과 재무제표뿐이라 1998년까지 소급 검정된다 — 폐지 종목 18,169개를 포함한
20,931 종목이 있다. 재는 것은 전략 수익률이 아니라 **스코어의 예측력**(rank-IC)이고,
관문은 `portfolio-research` 의 walk-forward · Deflated Sharpe · PBO 를 그대로 쓴다.

**나머지 절반은 불가능하다.** L3(에이전트 리서치)·가치함정 축 3(대체 위협)·`cycle_confidence` 는
2015년의 정책과 광산 폐쇄를 오늘의 지식 없이 재구성할 수 없다.
대신 관문을 **사전 반증가능성(ex-ante falsifiability)** 으로 옮긴다 —
모든 테마 논지는 *관측 가능한 트리거* 와 *무효화 조건* 없이는 저장될 수 없고,
그 절반의 검증은 **전향적 기록** 과 **확신도 캘리브레이션(Brier score)** 이 한다.
자세히는 `docs/10-validation.md`.

## 문서

| | |
|---|---|
| [00-overview](docs/00-overview.md) | 문제 정의 · 계층 구조 · 비목표 · 기존 저장소와의 경계 |
| [01-theme-universe](docs/01-theme-universe.md) | 3중 테마 정의 (industry + 큐레이션 + ETF 프록시), 134개 버킷(M2 실측 확정), 사이클 유형 분류 |
| [02-cycle-state](docs/02-cycle-state.md) | L1 상태벡터 6블록 전 지표 정의와 수식 |
| [03-macro-dag](docs/03-macro-dag.md) | L2 거시 인과 DAG 스펙 · 드라이버 목록 · 국면 4분면 · 모순 감사 |
| [04-value-trap](docs/04-value-trap.md) | **사이클 저점 vs 구조적 사망 판별기** — 이 저장소의 핵심 IP |
| [05-agent-research](docs/05-agent-research.md) | L3 에이전트 계약 · thesis 객체 스키마 · 베어/레퍼리 구조 |
| [06-stock-selection](docs/06-stock-selection.md) | L4 생존 · 토크 · 타이밍 3축과 바벨 구성 |
| [07-portfolio](docs/07-portfolio.md) | L5 리스크 예산 최적화 정식화 · 물타기 사다리 · 2단 스탑 · TP 사다리 |
| [08-data-contract](docs/08-data-contract.md) | 데이터 계약 · 재사용 경계 · **부트스트랩 절차** |
| [09-operations](docs/09-operations.md) | 케이던스 · 결정 저널 · 배달 |
| [10-validation](docs/10-validation.md) | 무엇을 재고 무엇을 못 재는가 — 결정론 계층의 백테스트 관문 + 캘리브레이션 |
| [11-roadmap](docs/11-roadmap.md) | 구현 순서와 마일스톤 완료 판정 기준 |
| [12-design-question-a-block](docs/12-design-question-a-block.md) | **설계 질문 1** — A(망각)는 가중합의 항인가 후보 집합의 조건인가. M3.5 FAIL 의 구조적 원인, 사전 등록된 결정 절차(M3.6) |
| [13-design-question-l2-macro](docs/13-design-question-l2-macro.md) | **설계 질문 2** — 거시(L2)는 선별 기준인가 오버레이인가. 내부 실태·외부 증거·B안 채택(순위 가중 0)·사전 등록 증분 검정(M4.5) |
| [specs/](docs/specs/) | `themes.example.yaml` · `macro-dag.example.yaml` · `thesis.schema.yaml` |

## 관련 저장소

| 저장소 | 이 저장소가 가져가는 것 |
|---|---|
| `portfolio-research` | Sharadar 직판 어댑터 · DuckDB PIT 스토어 · 팩터 DSL · 13612W 시그널 |
| `momentum` | Minervini Stage 분석 · VCP 탐지 · RS Rating (**지수 레벨로 승격해 사용**) |
| `fin-checkup` | 재무 레드플래그 · 텔레그램 알림 · 스케줄러 |

## 면책

투자 조언이 아니다. 이 저장소는 측정값과 명시된 가정을 산출할 뿐이며, 집행은 사람이 한다.
