---
type: finding
date: 2026-08-24
subject: 가치함정 5축은 원자재 어휘로 쓰였고, 비원자재 테마에서는 축이 빈 채로 게이트를 통과한다
decided_by: none — 발견 기록. 결정하지 않았다
links:
  - journal/2026-08-23-l4-rank-score-unwired.md
  - journal/2026-08-23-l2-removed.md
  - docs/04-value-trap.md#2
  - docs/04-value-trap.md#3
  - src/msa/l3/gates.py#L100
  - src/msa/l3/gates.py#L269
  - state/theses/2026-08-14/home_improvement.thesis.yaml
---

# 발견 — 판별기가 온전히 도는 테마와 축이 비는 테마가 갈리는데, 게이트는 그 차이를 보지 않는다

**이것은 결정이 아니다.** 아래는 오늘 코드와 산출물에서 확인한 사실이다. **코드도 `docs/` 도
한 줄 고치지 않았다** — L4 백테스트가 실행 중이고(`docs/14`), 근거가 사례 하나이기 때문이다.

## 어떻게 시작됐나

사용자가 물었다 — **"왜 자꾸 광산 얘기가 나오냐. 그건 내가 예시로 든 하나의 섹터일 뿐인데."**
그 물음이 맞는지 확인하려고 유니버스 구성과 5축(`docs/04`)의 어휘, 그리고 실제로 나온 논지를
따로따로 세어 봤다. 셋의 답이 서로 달랐다.

## 사실 1 — 유니버스는 원자재 편향이 **아니다**

`state/themes.yaml` 확정 134 테마의 `cycle_class` 를 직접 셌다:

| cycle_class | 테마 수 |
|---|---|
| `credit_rate` | 24 |
| `discretionary_demand` | 21 |
| `commodity_supply` | 20 |
| `secular_growth` | 17 |
| `inventory` | 15 |
| `capex_program` | 15 |
| `policy_program` | 13 |
| `secular_risk` | 9 |

원자재 공급 사이클(`commodity_supply`)은 **134 중 20, 15%** 다. L1 도 클래스를 하나로 취급하지
않는다 — `src/msa/themes.py:328-337` 의 `BLOCK_WEIGHTS` 는 8클래스 각각에 다른 A~F 블록 가중치를
선언한다(예: `credit_rate` 는 D=0.25, `commodity_supply` 는 E=0.30). **사용자의 지적은 유니버스와
L1 에 관한 한 옳다.**

## 사실 2 — 그런데 5축의 **개념**은 원자재에서 왔다

`grep -c "광산\|원자재\|상품가\|생산자" docs/*.md` 로 센 언급 빈도:
`docs/06` 11 · `docs/07` 7 · `docs/05` 6 · `docs/13` 6 · `docs/03` 5 · `docs/picks-m5-check` 5 ·
`docs/04` 4 · `docs/01`·`docs/02`·`docs/11` 3 …

빈도보다 중요한 것은 **정의 자체가 생산업 전용인 축이 있다**는 점이다.

- **축 1** — `docs/04` §2 는 1순위 입력을 "실물 소비량(톤·온스·MWh·배럴)" 으로 정의하고,
  판정 예시를 발전용 석탄 소비 톤수와 은 산업 수요 온스로 든다.
- **축 4** — "가격 < P90 현금원가 + 한계생산자 셧다운 발표". 원가곡선과 셧다운이라는 물건이
  존재하지 않는 산업에서는 개념이 성립하지 않는다.
- **케이스 스터디 라이브러리**(`docs/04` §1)의 11개 사례 중 사망 쪽 비원자재는 몰 REIT·유선통신·
  중국 사교육 셋뿐이고, 사이클 쪽 5개는 전부 원자재·해운이다.

**코드 쪽은 문제가 아니다.** 같은 어휘가 걸리는 곳은 `src/msa/l3/roles.py:191` 의 `lead_time`
질문 설명 한 군데인데("광산 7~10년, fab 3년, 조선소 2~3년 …") 거기는 이미 비원자재를 병기한다.
프롬프트의 축 판정 기준(`roles.py:426-429`)도 산업 중립적 문장으로 쓰여 있다 — 축 4 만은 그
문장 자체가 원가곡선을 전제한다.

## 사실 3 — 그 결과 비원자재 테마에서 축이 빈다

`state/theses/2026-08-14/home_improvement.thesis.yaml` (`cycle_class = credit_rate`) 의
`gate_result` 를 그대로 옮긴다:

```yaml
gate_result:
  status: passed
  portfolio_eligible: true
  rule: 04 §3 의 어느 기각 조항에도 걸리지 않음
  axis_verdicts:
    unit_demand: not_applicable
    capital_cycle: warning
    substitution: not_applicable
    cost_curve: not_applicable
    terminal_risk: warning
  reason: 축1 not_applicable · 축3 not_applicable · cycle_confidence=0.6
cycle_confidence: 0.6
```

**5축 중 3축이 판정을 내지 못했는데 게이트는 통과했고 포트 편입 자격도 났다.**

**예상과 달랐던 점 — 축이 비는 원인이 하나가 아니다.** `home_improvement` 는 `physical_ref` 를
갖고 있다(`state/themes.yaml:1571` — `{source: fred, symbol: EXHOSLUSM495S, kind: volume}`,
기존주택 거래 호수). 즉 축 1 이 빈 이유는 "이 테마에 물량 개념이 없어서" 가 아니라 **시계열의
1차 출처 대조에 실패해서**다 — thesis 의 `axis1_status: data_missing` 이고 `key_uncertainties` 가
"2017~2019년 구간의 1차 출처 대조에 실패" 라고 적는다. 반면 축 3(대체)은 정량 침투율 자료가 없어서,
축 4(원가곡선)는 **개념 자체가 소매 유통업에 없어서** 닫혔다(note: "채굴·제련·정유 등 생산업에
적용되는 개념"). 원인이 최소 셋이고 게이트는 셋을 구분하지 않는다.

## `not_applicable` 이 코드에서 어떻게 처리되는가 — 확인 결과

**"통과로 센다" 도 "분모에서 뺀다" 도 정확한 서술이 아니다. 세는 장치가 아예 없다.**

- `apply_gates()` (`src/msa/l3/gates.py:170-283`)는 카운트도 분모도 쓰지 않는다. 기각 조항의
  나열이고, 각 조항은 축 1·축 3 이 특정 값일 때만 반응한다 — `:195`(`contested`),
  `:236`(축1 `death` AND 축3 ∈ {`warning`,`death`}), `:246`(축1 또는 축3 `death`),
  `:258`(`secular_risk` 인데 축1·축3 이 `cycle` 이 아님). `not_applicable` 은 **어느 조항의
  조건에도 나타나지 않으므로** 전부 통과해 마지막 분기(`:269-283`)로 떨어진다. 그 분기의 문구가
  그대로 산출물에 실린 "04 §3 의 어느 기각 조항에도 걸리지 않음" 이다.
- 확신도에서도 가감이 없다. 축1 `not_applicable` → 항 없이 note 만 남긴다(`:100-105`).
  축3 `not_applicable` → `+0.15`(`:107`)도 `−0.15`(`:109`)도 아니다. 축4 → `+0.10`(`:111`) 없음.
- **그래서 산술이 이렇게 된다.** `CONF_BASE = 0.5`(`:31`) · `PORTFOLIO_MIN_CONFIDENCE = 0.5`
  (`:35`) · `eligible = confidence >= PORTFOLIO_MIN_CONFIDENCE`(`:269`). 부등호가 등호를
  포함하므로 **5축이 전부 `not_applicable` 이어도 확신도는 정확히 0.5 이고 편입 자격이 난다.**
  `home_improvement` 의 0.6 도 남은 두 축에서 온 것이 아니다 — 유일한 가산 항은 L1 이 계산한
  `axis2_capex_below1_8q: 0.1` 이다(thesis 의 `cycle_confidence_terms` 그대로).
- **문서는 반대로 적혀 있다.** `docs/04-value-trap.md:96` — "축 3 에 가중치를 이전하고 그 사실을
  리포트에 표시한다. **적용 불가를 통과로 취급하지 않는다.**" `grep -rn "가중치를 이전" src/ docs/`
  는 이 한 줄만 찾는다. **코드에 대응물이 없다.** 게다가 이번 사례는 이전 대상인 축 3 자신이
  `not_applicable` 이라 이전할 곳도 없었다.

## 왜 문제인가

`docs/04` 머리말은 이 판별기를 "이 저장소의 핵심 IP … 이것이 없으면 전체 파이프라인이 자본 파괴
기계가 된다" 로 규정한다. 싸 보이는 함정과 진짜 사이클 저점을 가르는 **유일한 장치**다.

그 장치가 축을 온전히 채울 수 있는 테마에서만 온전히 돌고, 축이 비는 테마에서는 **덜 검사받고
통과한다.** 검사를 덜 받은 쪽이 더 쉽게 통과하는 방향이라는 것이 핵심이다.

`CLAUDE.md` §2("조용한 절단 금지")에 비추면 **이것은 절단이 아니다** — 판정을 못 했다는 사실은
`note` 와 `key_uncertainties` 와 `axis_verdicts` 에 정직하게 적혀 있고 어디에도 숨지 않았다.
조용하지 않다. 문제는 다른 데 있다: **그 정직한 기록이 게이트에 아무 영향도 주지 않는다.**
`journal/2026-08-23-l4-rank-score-unwired.md` 와 같은 양식이 세 번째로 반복됐다 — 문서에 선언은
있고(`docs/04:96`) 코드에는 배선이 없으며, 산출물에 필드가 보여서 배선된 것처럼 읽힌다.

## 아직 모르는 것 · 결정하지 않은 것

- **사례가 사실상 하나다.** `state/theses/` 에 논지가 둘 있다. `home_improvement`(2026-08-14,
  `credit_rate`)는 3축이 비었고, `commodity_chem`(2026-08-23, `commodity_supply`,
  `physical_ref: WPU061`)은 **5축 전부 판정됐다**(`cycle`·`cycle`·`warning`·`cycle`·`warning`).
  대비는 선명하지만 각각 1건이다. **"85% 테마에서 축이 빈다" 고 말할 근거는 없다.** 지금 말할 수
  있는 것은 두 사례가 각각 어땠는가와, 게이트 코드가 `not_applicable` 에 아무 반응도 하지 않는다는
  것뿐이다. 나머지 클래스(`inventory`·`policy_program`·`secular_growth` …)에서 어떤 양상인지는
  **확인하지 않았다.**
- **`not_applicable` 을 실패로 세는 것이 옳은지 모른다.** 소프트웨어 테마에 "톤 단위 물량 추세" 를
  요구하는 것은 무의미하다. 문제는 **축이 비는 것 자체가 아니라 그 자리를 대신할 질문이 없다는
  것**일 수 있다. 어느 쪽인지 정하지 않았다.
- **원인이 갈린다는 사실(개념 부재 vs 데이터 결측 vs 자료 미확보)을 게이트가 구분해야 하는지도
  정하지 않았다.** 셋은 성격이 다르다 — 데이터 결측은 고치면 채워지고, 개념 부재는 고쳐도 안 채워진다.
- **아무 것도 고치지 않았다.** 코드·문서·사전 등록 어느 것도.

## 검토 후보 — 제안이지 결정이 아니다

`cycle_class` 별로 축을 **다르게 묻는** 방향이 하나 있다. 예를 들어 `credit_rate` 는 물량 대신
신용 사이클·연체율을, `secular_growth` 는 침투율 곡선을, `policy_program` 은 예산 집행률을 묻는
식이다. 축의 **의도**(공급이 파괴될 때 수요가 남아 있는가)는 그대로 두고 관측 대상만 클래스에
맞추는 것이다.

**값도 임계도 가중치도 여기서 정하지 않는다.** 이것은 아이디어 기록이지 사전 등록이 아니다.
실제로 바꾸려면 `docs/12`·`docs/14` 와 같은 꼴의 **새 번호 사전 등록 문서**가 필요하다
(관측 → 선언의 근거 → 외부 증거 → 설계 공간 → 사전 등록, 시도 수 정산 포함). `CLAUDE.md` §1 이
그대로 걸린다 — 결과를 보고 축이나 계수를 옮기는 것은 금지돼 있다. **이 항목은 그 문을 열지 않는다.**

## 다음

2026-08-24 아침 L4 백테스트 결과와 함께 **사람이 검토한다.**
