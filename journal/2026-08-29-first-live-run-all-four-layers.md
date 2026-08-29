# 2026-08-29 · 네 계층 첫 실전 가동 — 그리고 증거 대장이 명단을 뒤집었다

`journal/2026-08-29-hedge-fund-p2-p3-p4.md` 가 **"P2·P3 는 아직 한 번도 실제로 안 돌았다"** 고
적었다. 이 항목은 그 두 줄을 지운다.

## 1. P2 매크로 — 첫 실전 판정

`msa regime --provider claude_code --week 2026-W35` (구독 인증, 크레딧 0).

**tailwind 3 · neutral 1 · headwind 4.** `synthetic: false` — 합성이 아니다.

| 칸 | 판정 | 근거 요지 |
|---|---|---|
| `capex_program` | tailwind | 하이퍼스케일러 5사 2026 캐펙스 6,600~6,900억 달러 |
| `commodity_supply` | tailwind | 구리 2026 정제 15만~60만 톤 부족 전망 |
| `inventory` | tailwind | 도매 재고/판매 1.25(1월) → 1.19(6월) |
| `credit_rate` | **headwind** | 3.50~3.75% 동결, 7월 근원 PCE 3.3% |
| `discretionary_demand` | **headwind** | 7월 고용 −2.3만, 소매판매 −0.6% |
| `policy_program` | **headwind** | CHIPS 마지막 배정연도, 세액공제 2026-12-31 시한 |
| `secular_risk` | **headwind** | Section 232 관세 25% 2027-12-31 까지 |
| `secular_growth` | neutral | 정의상 매크로 사이클보다 채택 속도에 좌우 |

`managed_care` 는 `credit_rate` 라 **계수 0.70** 이 붙었다.

## 2. P3 종목 분석가 — 첫 실전, 그리고 코드 지표를 **양방향으로** 교정했다

`msa stock-notes --provider claude_code --top-n 3`. 이게 이 계층을 만든 값이다:

| 종목 | 코드가 본 것 | 분석가 판정 | 무엇이 달랐나 |
|---|---|---|---|
| `CLOV` | ⚠ `consecutive_operating_loss` | **intact** | 이미 흑자 전환 — 2026 Q2 GAAP 순이익 $28M, 매출 +55.6%, 무차입, 현금·투자 $4.43억 |
| `MOH` | 레드플래그 없음 · 순부채/EBITDA −2.78 | **strained** | 정적 스냅샷이 방향성을 못 본다 — Medicaid 요율 +4% 가 의료비 트렌드 +5% 를 못 따라감 |
| `ALHC` | 레드플래그 없음 | intact | $330M 4.25% 전환사채로 11.77% Oxford 텀론 차환, 현금 $702M |

**레드플래그가 붙은 종목이 멀쩡하고, 안 붙은 종목이 압박을 받고 있었다.** 코드는 스냅샷을
보고 분석가는 방향을 본다 — 둘이 다른 것을 본다는 것이 이 배치의 요점이다.

## 3. 증거 대장 — 명단을 뒤집었다

`state/evidence_resolutions/` 를 처음으로 채웠다. 원문을 직접 열어 대조했다.

### `managed_care` — confirmed 2 · **refuted 2** · unresolvable 1

| # | 판정 | 무엇을 찾았나 |
|---|---|---|
| [1] | **refuted** | 2016~2021 연도별 가입자 수(17.6·19.1·20.5·22.1·24.1·27.6백만)가 **KFF 원문에 하나도 없다.** 문서가 주는 것은 "2007년 19% → 2026년 55%" 두 점뿐. claim 자신이 "여러 스냅샷 기사의 종합" 이라 적어 뒀다 |
| [8] | confirmed | "35.2 million out of 64.2 million" · "+1.1 million, or 3%" · "8.2 million … SNPs, +900,000" · "55%" 전부 확인. 기계가 "3,500" 을 못 찾은 것은 원문이 35.2 여서다 — **반올림이지 날조가 아니다** |
| [10] | **refuted** | 114% 는 원문에 있다. 그러나 claim 이 앞세운 **$888 → $1,904 도, CBO "약 25%(400만 명)" 도 이 문서에 없다.** 메커니즘은 맞고 수치의 출처가 틀렸다 |
| [17] | unresolvable | Commonwealth Fund 이 HTTP 403 으로 봇을 막는다. $340B · 120만 명 미확인 |
| [21] | confirmed | "73.9 million" · "declined by 5 million or 6%" 확인. 다만 "2023년 3월 정점 9,400만" 은 없다 — 배경 수치라 confirmed 로 두되 기록에 남긴다 |

### `shipping_container` — confirmed 2 · refuted 0 · unresolvable 1

| # | 판정 | 무엇을 찾았나 |
|---|---|---|
| [6] | confirmed | "only twelve cellular container vessels scrapped" · "the lowest in twenty years". 기계가 "12" 를 못 찾은 것은 원문이 숫자가 아니라 **낱말 'twelve'** 여서다 |
| [49] | confirmed | H1 2026 "eleven vessels for 36,700 teu" · 2025 "twelve vessels for 8,172 teu" · 상업적 "five ships for about 4,800 teu" 전부 확인. 비자발적 약 32,000 teu 구분도 원문에 있다 |
| [46] | unresolvable | **구조적으로 확인 불가다.** Drewry WCI 라이브 지수 페이지라 항상 최신 주차만 보여준다 — 오늘 열면 08-27 $4,473 이고 claim 의 08-20 $4,526 은 사라졌다 |

### 여기서 나온 규칙 하나

> **시점 수치를 라이브 대시보드 URL 로 인용하면 그 증거는 처음부터 검증 불가다.**

[46] 은 틀린 것이 아니라 **검증할 수 없게 인용된 것**이다. L3 프롬프트가 이 구분을 아직
가르치지 않는다 — 다음 라운드의 과제로 남긴다.

## 4. 그 결과 — 명단이 실제로 뒤집혔다

`refuted` 2건이 `managed_care` 의 J 상한을 **0.25** 로 내렸다 (`EVIDENCE_CAP_REFUTED`).

| | 대장 전 | 대장 후 (레짐·노트 포함) |
|---|---:|---:|
| `ALHC` (I-A) | 0.810 | **0.711** |
| `CLOV` (I-A) | 0.725 | **0.637** |
| `MOH` (I-A) | 0.700 | **0.533** |
| `CMRE` (I-B) | 0.850 | **0.872** |

**구획 I-B 의 `shipping_container` 가 I-A 의 `managed_care` 를 크게 앞선다.** 구획이 다르므로
직접 비교하는 물건은 아니지만, 신뢰도의 차이는 분명하다 — 한쪽은 증거 2건이 반박됐고
다른 쪽은 0건이다.

`MOH` 가 가장 많이 내려간 것(0.700 → 0.533)은 **반박된 테마 증거 + `strained` 종목 노트 +
`credit_rate` 역풍**이 겹쳤기 때문이다. 세 계층이 각자 다른 근거로 같은 방향을 가리켰다.

## 5. P4 가 계속 말하고 있는 것

- 구획 I-A: **3종목이 전부 `managed_care` · `healthcare`** (100%)
- 구획 I-B: **상위 5가 전부 `shipping_container` · `shipping`** (100%), 6종목을 슬롯 밖으로 미룸

**어느 구획을 봐도 한 베팅이다.** 이것이 오늘 명단의 가장 중요한 사실이고, P1~P3 중
어느 것도 이 사실을 말하지 못한다.

## 6. 아직 남은 것 — 정직하게

1. **`[17]` 은 사람이 브라우저로 열어야 한다.** 403 은 기계가 못 넘는다. $340B · 120만 명이
   미확인인 채로 `unresolvable` 에 남아 있고, 그것이 `managed_care` 판정의 한 축
   (`terminal_risk`)을 받친다.
2. **`[46]` 의 교훈이 L3 프롬프트에 아직 안 들어갔다.** 라이브 대시보드를 시점 증거로 인용하지
   말라는 규칙이 필요하다.
3. **트리아지는 여전히 검정되지 않았고 검정될 수 없다** (설계 §8.3). 오늘 순서가 뒤집힌 것은
   "더 맞는 순서가 됐다" 는 뜻이 아니라 **"덜 믿을 근거를 덜 믿게 됐다"** 는 뜻이다.
4. **레짐 판정은 이번 주 것 하나뿐이다.** 매주 뒤집히는지는 표본이 쌓여야 안다
   (`docs/25` §6 이 그 경우의 조치를 미리 고정해 뒀다 — 계수를 줄이지 않고 사실을 싣는다).

이전 항목: `journal/2026-08-29-hedge-fund-p2-p3-p4.md` ·
`journal/2026-08-29-triage-score.md` · `journal/2026-08-29-triage-constants-registered.md`
