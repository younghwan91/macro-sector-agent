# 05 · 에이전트 리서치 (L3)

## 1. 역할과 경계

LLM 이 파이프라인의 **좁은 허리**에만 있는 것이 설계 의도다.

**에이전트가 하는 것** — 코드가 물리적으로 할 수 없는 것만:
- 물리적 수급 (광산 폐쇄·증설 파이프라인, 재고 수준, 리드타임, 원가곡선)
- 정책·규제 (법안 시점, 보조금, 수출통제, 관세, 인허가)
- 대체 기술의 침투율과 비용 교차점 (`04-value-trap.md` 축 3)
- 논지의 서술과 **반증 조건의 명시**

**에이전트가 하지 않는 것**:
- **종목 추천** — `CLAUDE.md` §4. 훈련 데이터의 유명세 편향이 들어온다
- 가격 예측·목표주가
- 스코어 계산 (L1·L2 는 결정론)
- 비중·스탑·TP 결정 (L5 는 최적화)

**투입 대상**: `final(t)` 상위 **K=8** 테마 + 사용자가 수동 지정한 테마.
전수 투입하지 않는 이유는 비용과, 그보다 **넓게 물으면 LLM 이 아무 테마에나
그럴듯한 논지를 만들어 준다**는 것이다. 결정론적 계층이 먼저 좁혀야 한다.

## 2. 4역할 구조

```
              테마 스코어카드 + 거시 상태 + 구성종목 재무 요약
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
  supply_analyst       catalyst_analyst            bear
  물리적 수급           정책·촉매 캘린더        논지 파괴 전담
  (강세 증거 수집)      (시점 증거 수집)      (04 의 5축으로 사망 가설)
        └─────────────────────┼─────────────────────┘
                              ▼
                          referee
              양측 증거 대조 → 5축 판정 → cycle_confidence
              → thesis 객체 (triggers · invalidations 포함)
```

### `supply_analyst`
질문 고정:
1. 현재 글로벌 생산능력과 가동률. 지난 3년 폐쇄·감산 발표 목록
2. 향후 3년 증설 파이프라인 — 프로젝트별 규모·시점·확정도(FID 완료 여부)
3. 재고 수준 — 거래소 재고, 유통 재고, 역사적 백분위
4. 신규 공급의 **리드타임** (광산 7~10년, fab 3년, 조선소 2~3년 …)
5. 원가곡선 — P50/P90 현금원가 추정과 현재 가격의 위치
6. **최종 수요의 실물 소비량 시계열** — 매출이 아니라 물리 단위(톤·온스·MWh·배럴·대수)로,
   **최소 10년**, 연 단위 이상 해상도. 출처(기관·보고서명·URL)와 집계 범위(지역·용도)를 명시한다.
   예: 미국 발전용 석탄 소비 톤수(EIA), 은 산업 수요 온스(Silver Institute),
   우라늄 원자로 소요량 파운드(WNA). **04-value-trap.md 축 1 의 1순위 입력이 이것이다** —
   매출 기반 프록시는 이 시계열이 없을 때만 쓰는 폴백이다.
   찾지 못하면 "없다" 를 산출한다. 매출로 대체해 채우지 않는다 (`CLAUDE.md` §2).

### `catalyst_analyst`
1. 향후 12개월 정책·규제 이벤트 캘린더 (날짜 명시)
2. 확정된 예산·보조금·발주 규모
3. 무역 조치 (관세·수출통제·쿼터) 현황과 예정
4. 수요처의 투자 계획 (발주처 capex 가이던스)

### `bear` — **논지 파괴 전담**
> 이 에이전트의 성공 조건은 **논지를 죽이는 것**이다. 균형 잡힌 시각을 요구하지 않는다.
> 균형은 `referee` 가 잡는다. bear 가 온건해지면 판별기 전체가 무력해진다.

`04-value-trap.md` 의 5축을 무기로:
1. 물량 추세 — 이 산업의 최종 수요량이 줄고 있다는 증거를 찾아라
2. 대체 위협 — 이것을 대체하는 기술·재료·서비스와 그 침투율
3. 이번 사이클이 지난 사이클과 다른 이유 (구조 변화)
4. 강세론자가 **의도적으로 빼놓는** 사실
5. 이 논지가 이미 가격에 반영되었을 가능성 (컨센서스 확인)
6. 터미널 리스크 — 부채 만기, 규제 소멸, 지리적 집중

### `referee`
- 양측 증거를 축별로 대조
- `04-value-trap.md` §3 하드 게이트 적용 → 기각 여부
- §4 규칙으로 `cycle_confidence` 기계적 산출
- **triggers 와 invalidations 를 쓴다** — 여기가 산출물의 핵심

#### `axis1_contested` — `referee` 의 계약

**판정 규칙 본문은 `04-value-trap.md` §3.1 에 있다.** 여기에는 계약만 적는다 —
`referee` 가 무엇을 입력받아 무엇을 산출하는가. 규칙을 두 곳에 적으면 한쪽이 바뀔 때
조용히 어긋나므로, 조건·해석·근거는 04 를 읽는다.

**입력** — 다음을 함께 받는다. 하나라도 빠지면 판정하지 않는다.

| 입력 | 출처 |
|---|---|
| `verdict_pre_ss` · `verdict_post_ss` (보정 전/후 두 산출) | 축 1 (`02-cycle-state.md` §F 계산) |
| `unit_cagr_10y` · `unit_cagr_10y_median` 과 `sign_split` | 좌동 |
| `ss_n` · `ss_coverage` | 좌동 |
| `ma_flag` | 좌동 |
| `exit_count` | 축 2 (`02-cycle-state.md` §E) |

**산출**

| 산출 | 내용 |
|---|---|
| `referee_ruling` | **물량 감소가 산업 축소인가, 수요 소멸인가** 에 대한 서술 판정. 점수를 매기지 않는다 |
| `referee_evidence_refs` | 위 판정의 근거 (`CLAUDE.md` §3) |
| `gate_result.status` | `passed` · `contested` · `rejected` 중 하나로 닫는다 (`specs/thesis.schema.yaml`) |

**증거를 갖추지 못하면 기각으로 닫는다** — 보류는 판단 유보이지 면제가 아니다
(`04-value-trap.md` §3.1).

## 3. thesis 객체 스키마

전체 스키마는 `specs/thesis.schema.yaml`. 요지:

```yaml
theme_id: uranium
generated_at: 2026-08-22
horizon_months: [6, 18]

claim: >                          # 한 문장. 반증 가능해야 함
  우라늄 현물가는 2027년까지 파운드당 $110 이상을 유지하고, 생산자 마진 확대가
  실적에 반영되면서 SPUT 프리미엄과 무관하게 광산주 EBITDA 가 배증한다.

mechanism: >                      # 인과 경로. 상관 서술 금지
  2011-2020 저가격 국면에서 신규 개발이 중단돼 2026년 1차 공급이 수요의 75% 수준이다.
  광산 리드타임 7~10년이라 가격이 올라도 3년 내 공급 반응이 불가능하고,
  원자로 신규 승인은 이미 확정 파이프라인이므로 수요는 가격 비탄력적이다.

triggers:                         # 관측되면 논지 강화 → 물타기 사다리의 조건
  - observable: "Cameco 또는 Kazatomprom 이 생산 가이던스를 상향"
    source: "분기 실적 발표"
    by: "2026-Q4"
  - observable: "장기계약 체결가가 현물가를 상회"
    source: "UxC 주간 리포트"
    by: "2027-Q1"
  - observable: "breadth_200 > 0.6 지속 3개월"
    source: "L1 스캐너"
    by: "2026-Q4"

invalidations:                    # 관측되면 논지 사망 → Tier-1 스탑
  - observable: "카자흐스탄 생산 쿼터 20% 이상 상향 발표"
    source: "Kazatomprom 공시"
    action: exit
  - observable: "주요국 원전 신규 승인 2건 이상 철회"
    source: "IAEA / 각국 규제기관"
    action: exit
  - observable: "현물가 $70 이하 3개월 지속"
    source: "UxC"
    action: exit

key_uncertainties:
  - "SPUT 의 현물 매집이 가격을 인위적으로 지지하는 비중을 분리할 수 없음"
  - "러시아 농축 제재의 우회 경로 규모 불명"

bear_case: >
  bear 에이전트의 최강 논지를 그대로 보존. 요약하지 않는다.

value_trap_axes:
  unit_demand:
    verdict: cycle
    evidence_refs: [3, 7]
    axis1_available: true
    unit_series_source: physical_series      # WNA 원자로 소요량 (매출 프록시 아님)
    verdict_pre_ss: cycle
    verdict_post_ss: cycle
    axis1_contested: false                   # 보정 전후 판정 동일
    ss_n: 9
    ss_coverage: 0.75
    ma_flag: false
    unit_cagr_10y: 0.021
    unit_cagr_10y_median: 0.018
    unit_cagr_5y: 0.034
    sign_split: false
  capital_cycle: {verdict: cycle,   evidence_refs: [1, 2]}
  substitution:  {verdict: cycle,   evidence_refs: [11]}      # SMR 은 대체가 아니라 수요 증가
  cost_curve:    {verdict: cycle,   evidence_refs: [4]}
  terminal_risk: {verdict: warning, evidence_refs: [9]}       # 카자흐 지리 집중

gate_result:
  status: passed                             # passed | contested | rejected
  portfolio_eligible: true                   # contested·rejected 면 반드시 false
  rule: "축1 사이클, 축3 사이클 — 04 §3 의 어느 기각 조항에도 걸리지 않음"
  axis_verdicts:                             # 판정 시점 스냅샷 — 기각 대장의 집계 단위
    unit_demand: cycle
    capital_cycle: cycle
    substitution: cycle
    cost_curve: cycle
    terminal_risk: warning

cycle_confidence: 0.72

evidence:                         # 비면 스키마 검증 실패 (CLAUDE.md §3)
  - id: 1
    claim: "2011-2020 신규 광산 FID 0건"
    source_url: "https://..."
    date: "2026-06-14"
    reliability: high             # high | medium | low
```

## 4. 규약

| 규약 | 근거 |
|---|---|
| `evidence` 배열이 비면 저장 거부 | `CLAUDE.md` §3. LLM 의 기억은 증거가 아니다 |
| **게이트 기각된 thesis 는 저장한다** | 스키마 미달과 게이트 기각은 다르다. 스키마 미달은 **산출물이 불완전한 것**이라 저장을 거부하지만, 게이트 기각은 **완전한 산출물에 대한 판정**이므로 감사 대상이다. `gate_result.status: rejected` 로 저장하고 기각 대장에 적재한다 (`10-validation.md` §5, `09-operations.md` §4) |
| `gate_result.status: contested` 는 포트 편입 불가 | `04-value-trap.md` §3.1. 관찰 목록에만 올린다. `referee_ruling` 과 `referee_evidence_refs` 없이 contested 를 유지할 수 없다 |
| `invalidations` 가 비면 저장 거부 | `CLAUDE.md` §5. 무효화 조건이 곧 스탑의 근거 |
| `mechanism` 에 상관 서술 금지 | "역사적으로 함께 움직였다" 는 메커니즘이 아니다 |
| `bear_case` 요약 금지 | 요약은 반론을 약하게 만든다. 원문 보존 |
| 종목명이 `claim` 에 등장하면 경고 | 에이전트는 테마만 (`CLAUDE.md` §4) |
| `reliability: low` 증거만으로 축 판정 불가 | 최소 1개 medium 이상 필요 |
| 동일 테마 재실행 시 이전 thesis 를 **입력으로** 제공 | 논지 표류(drift) 추적. 무엇이 바뀌었는지 diff |

## 5. 비용 통제

| 항목 | 값 | 근거 |
|---|---|---|
| 라운드당 테마 수 | K = 8 | 월 1회 × 8테마 × 4역할 = 32 에이전트 호출 |
| 역할당 웹 검색 예산 | ~15 쿼리 | |
| 재실행 조건 | 스코어 상위 진입 · 트리거/무효화 발동 · 90일 경과 | 매달 전부 다시 돌리지 않는다 |
| 모델 배치 | `bear`·`referee` 는 상위 모델, `supply`·`catalyst` 는 표준 | 판정이 가장 어려운 두 역할에 자원 집중 |

## 6. 알려진 실패 모드

| 실패 | 증상 | 대응 |
|---|---|---|
| **에이전트가 항상 강세 논지를 만든다** | 스코어 상위라는 프레이밍 자체가 강세 편향 | `bear` 를 독립 컨텍스트로 실행하고, 입력에서 L1 스코어를 **숨긴다** |
| 컨센서스 반복 | 웹 검색 결과가 이미 알려진 서사 | `bear` 에게 "이 서사가 언제부터 컨센서스였는가" 를 명시적으로 묻는다 |
| 오래된 정보 | 훈련 데이터의 과거 사실을 현재로 서술 | 모든 evidence 에 `date` 필수, 12개월 초과 시 리포트에 표시 |
| 숫자 환각 | 생산량·재고 수치 조작 | `reliability` 등급 + `source_url` 필수. 수치는 원문 대조 없이 `high` 불가 |
| 논지 표류 | 재실행마다 논지가 조금씩 바뀌어 무효화를 회피 | 이전 thesis 를 입력으로 주고 diff 를 저널에 기록 (`09-operations.md`) |
| **`contested` 가 상시 보류로 굳는다** | `referee` 가 판단을 미루는 편한 출구로 쓰면 기각도 통과도 하지 않게 되고, 하드 게이트가 무력해진다 | `04-value-trap.md` §3.1 의 **"서술 못 하면 기각으로 닫는다"** 를 기계적으로 적용한다. 더해 **보류 건수를 리포트에 센다** — 라운드별 `contested` 수와 직전 라운드에서 넘어온 미해소 건수를 함께 적어, 보류가 쌓이는 것이 보이게 한다 |

## 7. 구현 노트 (M7)

코드: `src/msa/l3/` (`contracts` · `providers` · `roles` · `schema` · `gates` · `pipeline`), CLI `msa research <theme>`.

**제공자 추상화.** 파이프라인은 `LLMProvider.complete(request) -> CompletionResult` 만 호출한다.
구현 셋 — `AnthropicProvider`(공식 `anthropic` SDK, 구조화 출력 `output_config.format`, adaptive thinking,
`bear`·`referee` = `claude-opus-5`, `supply`·`catalyst` = `claude-sonnet-5`; 환경변수
`MSA_L3_MODEL_TOP` / `MSA_L3_MODEL_STANDARD` 로 덮어쓴다), `MockProvider`(결정론적 합성 산출, 테스트·`--dry-run`),
`FixtureProvider`(`tests/fixtures/l3/<theme>/<role>.json` 녹화 형식). 웹 검색은 `SearchTool` 프로토콜 —
기본 `StubSearchTool` 은 호출 시 `NotConfigured` 를 던지고, `AnthropicWebSearch` 는 서버 도구
(`web_search_20260209`, `max_uses` = 남은 예산)를 싣는다. 역할당 예산 15 는 `SearchBudget` 이 강제하고
사용량은 `CostLedger` 가 역할별 호출·토큰·검색 수로 세어 리포트에 싣는다 (§5).

**이 런타임에서 막힌 것.** `ANTHROPIC_API_KEY` 가 없고 검색 도구가 없어 **실제 모델 호출은 한 번도 돌리지
않았다.** 4역할 프롬프트·JSON 스키마·게이트·검증·저장 경로는 Mock/Fixture 로 전부 돌렸고 테스트가 있다.
실제 실행은 `ANTHROPIC_API_KEY=... msa research <theme>` — 첫 실행에서 확인할 것: (1) 구조화 출력이 역할
스키마를 실제로 만족하는가, (2) 서버 검색 쿼리 수가 `usage.server_tool_use.web_search_requests` 로 잡히는가,
(3) `referee` 가 `axis1_contested` 에서 `referee_ruling` + 증거를 내는가 (못 내면 기각으로 닫힌다).

**입력 계약.** L2·L4·L5 모듈을 임포트하지 않는다. 스코어카드는 `state/scans/<date>/` 파일, 거시 상태는 선택
JSON(`state/macro/latest.json`, `tailwind` 키), 구성원 PIT 재무 요약은 DuckDB 에서 직접(시총 상위 12),
이전 thesis 는 `state/theses/<이전 date>/`, few-shot 은 `state/cases/*.md`(없으면 "few-shot 없음").

**축 1 은 L1 값을 그대로 옮긴다.** `verdict_post_ss`·`axis1_contested`·`ss_n`·`ss_coverage`·`ma_flag` 를 thesis 에
복사하고 `referee` 는 contested 일 때의 서술 판정만 낸다. 스캔 자체를 `reliability: medium` 증거로 한 줄 추가한다.

**산출물.** `state/theses/<asof>/<theme>.thesis.yaml` · `<theme>.report.md` · `rejections-pending.yaml`
(기각 행, `09` §4 형식 — 대장 적재는 M8) · `contested.json`(라운드 보류 수 + 이월 수). 스키마 미달은
저장하지 않고 종료 코드 2, 게이트 기각은 저장한다 (§4).
