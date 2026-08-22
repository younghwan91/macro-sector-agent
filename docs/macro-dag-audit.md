# 거시 인과 DAG 감사 (M4 · 134 버킷 기준 재감사)

`state/macro-dag.yaml` 에 대한 `scripts/audit_dag.py` 실행 결과와 그 해석.
실행: `uv run --with pyyaml python scripts/audit_dag.py` (종료코드 0 = 전 항목 통과)

> **이 판은 M2 확정 버킷 134개(`state/themes.yaml` 정본) 기준이다.** 이전 판은
> `docs/01-theme-universe.md` §3 초안(109개) 기준이었고, 확정 후 재감사에서 22건이
> 실패했다 — 폐기된 초안 id 6개를 가리키는 `to` 와, 신설 버킷 31개의 in-degree 0.
> 그 보정(M4-134)의 내용은 §10 에 있다.

## 1. 요약

| 항목 | 값 |
|---|---|
| 드라이버 | 26개 (`docs/03-macro-dag.md` §2 전부) |
| 공통 인자 (`common_factor: true`) | 3개 — `usd_liquidity` · `fed_policy_path` · `m2_growth` |
| 엣지 레코드 | 86개 (개별 83 + 공통 인자 3) — 이전 72개 (+14, 전부 M4-134 추가) |
| 테마-엣지 쌍 | **451개** (공통 인자 제외) / 하한 268 (= 2 × 134) — 이전 380 / 218 |
| 테마 in-degree | **min 2 · median 3 · max 6** (공통 인자 제외) |
| 입력 엣지 2개 미만 테마 | **0개** |
| `channel` 이 빈 엣지 | 0개 |
| `contradicts_when` 을 가진 엣지 | 26개 (이전 22) |
| 강도 분포 | strong 22 · moderate 37 · weak 27 |
| 부호 분포 | +1 47 · −1 39 |
| 폐기 초안 id 를 가리키는 `to` | 0개 (6개 id 전부 재매핑, §10-1) |

테마 목록의 출처는 `state/themes.yaml` (정본) 이며 `audit_dag.py` 가 그 파일이 존재할 때
자동으로 그쪽을 읽는다. 출력 첫 줄에 "출처: themes.yaml (정본)" 이 찍히는 것을 확인했다.

## 2. 검사 항목별 결과

| 검사 | 기준 | 결과 |
|---|---|---|
| 모든 테마 입력 엣지 ≥ 2 | 공통 인자 제외 | 통과 (미달 0개) |
| `channel` 이 빈 엣지 | 0개 | 통과 |
| 필수 필드 (`from`·`to`·`sign`·`strength`·`channel`·`observable`) | 전부 존재 | 통과 |
| `from` 이 드라이버 목록에 있는가 | 전부 | 통과 |
| `to` 가 테마 id 인가 | 전부 (공통 인자의 `*` 제외) | 통과 — 폐기 id 6개 재매핑 후 |
| `sign` ∈ {+1, −1} | — | 통과 |
| `strength` ∈ {strong, moderate, weak} | — | 통과 |
| 공통 인자가 개별 테마를 지목하지 않는가 | `*` 만 허용 | 통과 |

## 3. 입력 엣지 2개를 못 채운 테마

**없다.** 134개 테마 전부가 개별(비공통) 입력 엣지를 2개 이상 갖는다.

다만 **하한을 겨우 채운 26개 테마**는 "거시로 설명되는 정도가 얕다"는 뜻이며,
이 사실 자체가 정보다. `docs/03` §4 의 `final(t) = 0.70·cycle + 0.30·tailwind` 에서
이들의 tailwind 는 소수 엣지에 의존하므로 한 드라이버가 뒤집히면 점수가 크게 흔들린다.

in-degree 2인 테마 (26개):
`advertising` · `asset_managers_exchanges` · `auto_dealers` · `biotech_clinical` ·
`business_services` · `consumer_services` · `datacenter_hw` · `education` · `food_beverage` ·
`food_retail_distribution` · `hotels_resorts` · `insurance_brokers` · `insurance_pc` ·
`intl_majors` · `it_services` · `life_science_tools` · `lng` · `medtech_devices` ·
`networking_optical` · `refiners` · `reit_retail` · `retail_discount` · `semi_eda_ip` ·
`software_vertical` · `staffing_consulting` · `trucking_logistics`

> 기존 103개 테마의 in-degree 는 M4-134 보정으로 **바뀌지 않았다** — 재매핑은 `to` 에서
> 폐기 id 를 빼거나 바꾼 것뿐이라 기존 테마의 개수를 건드리지 않는다. 예외는 병합의 수혜자
> 둘: `defense` 3→5 (`aerospace_commercial` 의 엣지 흡수), `construction_machinery` 3→5
> (`ag_machinery` 의 엣지 흡수). 위 26개 중 17개는 커밋된 yaml 기준으로 이전에도 2였고,
> 9개(`auto_dealers`·`business_services`·`consumer_services`·`education`·`food_retail_distribution`·
> `insurance_brokers`·`it_services`·`retail_discount`·`staffing_consulting`)는 M4-134 신설 버킷이다.
> (이전 판 문서의 "17개" 목록은 당시 커밋된 yaml 과 8개 이름이 어긋나 있었다 — 문서가 yaml 보다
> 앞선 초안을 옮긴 것으로 보인다. 이번 판의 목록은 스크립트 출력 그대로다.)

성격별로 나누면 넷이다.

- **거시로 설명되는 축이 정말 좁은 것** — `biotech_clinical`(실질금리·HY 스프레드가 사실상 전부),
  `asset_managers_exchanges`·`food_beverage`. 엣지를 억지로 늘리는 것이 오히려 왜곡이다.
- **드라이버가 지배적이라 다른 엣지가 잡음인 것** — `datacenter_hw`(하이퍼스케일러 capex),
  `staffing_consulting`(고용 그 자체), `auto_dealers`(고용 + 할부 금리). 하나의 강한 엣지 +
  하나의 약한 엣지 구조가 실제를 반영한다.
- **관측 드라이버가 없어서 얕은 것** — `lng`(국내외 가스 스프레드가 드라이버 목록에 없다),
  `semi_eda_ip`(수출통제 이벤트 외에 대리 변수가 없다), `refiners`(크랙 스프레드 없음).
  이쪽은 드라이버를 늘려야 해결되는 문제이며, 엣지를 늘려 해결할 문제가 아니다.
- **방어적·잔여 버킷이라 거시 민감도 자체가 낮은 것** (M4-134 신설 버킷 다수) —
  `retail_discount`·`food_retail_distribution`(필수 소비 유통, 두 엣지 모두 weak),
  `business_services`(커버리지용 잔여집합, `state/themes.yaml` 노트가 "사이클 논지의 대상이
  아니다" 라고 적은 버킷), `consumer_services`·`insurance_brokers`·`it_services`·`education`.
  이들은 `secular_growth`/잔여 분류와 겹치며, L1 이 낙폭 가중치를 낮게 주는 것과 일관되게
  L2 tailwind 도 얕다. **억지로 2개를 채웠다는 뜻이 아니라, 2개가 정직한 개수라는 뜻이다.**

`refiners` 는 여전히 **부호가 가장 약한 테마**다 — 손익이 유가 수준이 아니라 크랙 스프레드라
`oil_wti` 엣지를 `weak` 로 두고 대리 변수임을 명시했다. 크랙 스프레드 시계열이 드라이버로
추가되면 이 엣지는 대체되어야 한다.

## 4. 공통 인자 — tailwind 계산 시 처리

`common_factor: true` 인 드라이버는 전 테마에 같은 부호로 들어와 **상대 순위를 만들지 않는다.**
`docs/03` §7 규약대로 tailwind 계산에서 **횡단면 중앙값을 뺀 뒤** 사용한다.

| 드라이버 | 부호 | 강도 | 왜 공통인가 |
|---|---|---|---|
| `usd_liquidity` | +1 | moderate | 준비금 확대 → 위험 선호 전반 |
| `fed_policy_path` | −1 | moderate | 정책금리 = 전 테마 공통 할인율 기준선 |
| `m2_growth` | +1 | weak | 명목 매출·자산가격의 공통 성분. `usd_liquidity` 와 경로가 겹쳐 강도를 낮춤 |

> `m2_growth` 를 `weak` 로 둔 것은 **선언이다.** 근거: `usd_liquidity` 와 같은 유동성
> 경로를 두 번 세면 공통 성분이 이중 계상된다. 데이터로 정한 값이 아니다.

이 셋은 테마의 in-degree 하한(≥2) 계산에서 제외된다. 감사 스크립트가 두 종류의
in-degree(공통 포함/제외)를 따로 세는 이유가 이것이다.

## 5. 드라이버별 out-degree

테마-엣지 쌍 기준. 공통 인자는 `*` 를 134개 테마로 전개한 값이다. 괄호는 이전 판(109개 기준).

| 드라이버 | out | 드라이버 | out |
|---|---|---|---|
| `real_rate_10y` | 64 (54) | `oil_wti` | 21 (20) |
| `employment` | 50 (31) | `industrial_production` | 20 (17) |
| `policy_events` | 41 (38) | `hyperscaler_capex` | 19 (19) |
| `hy_spread` | 35 (27) | `inventory_sales` | 18 (17) |
| `cpi_yoy` | 26 (16) | `capex_orders_core` | 16 (13) |
| `dollar_broad` | 25 (23) | `housing_starts` | 15 (11) |
| `china_credit_impulse` | 15 (16) | `nat_gas` | 12 (12) |
| `ig_spread` | 11 (9) | `new_orders_mfg` | 11 (7) |
| `ppi_yoy` | 11 (9) | `breakeven_10y` | 9 (9) |
| `china_property` | 9 (9) | `defense_outlays` | 8 (8) |
| `copper_price` | 7 (8) | `term_spread` | 5 (4) |
| `gold_price` | 3 (3) | | |
| `usd_liquidity` (공통) | 134 | `fed_policy_path` (공통) | 134 |
| `m2_growth` (공통) | 134 | | |

**`real_rate_10y` 의 64는 이 DAG 의 최대 집중이며, 이것이 이 저장소의 주된 리스크다.**
전체 테마-엣지 쌍의 14.2% 가 한 드라이버에 걸려 있다 (이전 판과 같은 비율 — 신설 버킷에
리츠·모기지·내구재가 많아 같은 비율로 늘었다). 실질금리가 한 방향으로 움직이면
tailwind 가 광범위하게 같은 방향으로 밀리고, 그러면 §7 이 경고한 "공통 인자는 테마를
고르는 데 쓸모없다" 는 문제가 공통 인자로 선언되지 않은 드라이버에서 재발한다.

`real_rate_10y` 를 공통 인자로 돌리지 않은 이유는 **부호가 갈리기 때문이다** —
보험 4종(`insurance_pc`·`insurance_life`·`reinsurance`·`insurance_diversified`)은 `+1` 이다.
이들은 차입자가 아니라 대여자라 금리 상승이 재투자 수익이다. 부호가 갈리는 드라이버는
정의상 공통 인자가 아니며, 실제로 상대 순위를 만든다. 다만 집중도가 높다는 사실은
리포트에 표기해야 한다.

**두 번째 집중은 `employment` 의 50 (이전 31)이다.** 신설 버킷 31개 중 `discretionary_demand`
클래스가 9개라 재량 소비 엣지(strong)에 대거 붙었다. 이쪽도 부호가 갈린다 — `education`
은 −1 (영리 교육 등록의 역경기성, §10-2). 집중 자체는 이 드라이버가 소비 사이클의
정의라는 사실의 반영이지만, 고용 통계의 개정이 크다는 점(`docs/08` §3)과 결합하면
**개정 전 값으로 국면을 판정해야 할 이유가 하나 더 늘었다.**

`gold_price` 의 3이 최소다. 귀금속 광업 3종에만 걸린다 — 금 가격이 매출 단가인 사업이
그것뿐이기 때문이며, 억지로 넓히지 않았다. `term_spread` 는 5 — 은행 2종 + 생보·자산운용에
이번에 `reit_mortgage`(레포 조달 → MBS 장기 보유, 만기 변환의 가장 순수한 형태)가 붙었다.

## 6. 테마 in-degree 분포 (공통 인자 제외)

```
in-degree  2: 테마  26개  ##########################
in-degree  3: 테마  60개  ############################################################
in-degree  4: 테마  27개  ###########################
in-degree  5: 테마  15개  ###############
in-degree  6: 테마   6개  ######
```

최다(6): `aluminum` · `copper_miners` · `diversified_miners` · `epc_engineering` · `midstream` · `semi_devices`
최소(2): §3 의 26개 목록

기저금속 광업이 상단에 몰린 것은 우연이 아니다 — 달러·중국 신용·중국 부동산·산업생산·
금속 가격이 전부 걸리는 구조라 **거시로 가장 잘 설명되는 테마군**이다. 뒤집어 말하면
거시가 역풍일 때 개별 논지로 버티기 가장 어려운 테마군이기도 하다.

`semi_devices` 가 6 으로 올라온 것은 병합의 산술이다 — 초안의 `semi_memory`·`semi_analog_power`·
`semi_foundry_logic` 이 각각 갖던 엣지(재고·신규수주·산업생산·방산·하이퍼스케일러·CHIPS)가
한 버킷에 합류했다. **이것은 정보량이 아니라 집계 수준의 변화다.** `state/themes.yaml` 이
적었듯 메모리 사이클과 아날로그 사이클이 한 지수 안에서 상쇄되므로, 엣지가 많다고
tailwind 의 신뢰도가 높은 것이 아니다 — 부호가 같은 방향으로 모이는 국면(전면 재고 소진 +
AI capex)에서만 뚜렷하고, 갈리는 국면에서는 평균이 0 에 가까워진다. 매출 노출 비중
(`docs/01` §6-2)이 도입되어 재분할되면 이 6은 다시 셋으로 나뉜다.

## 7. 이 감사가 검사하지 **않는** 것

- **엣지의 참/거짓.** 이 스크립트는 스키마와 커버리지만 본다. 엣지가 맞는지는
  `docs/03` §6 의 모순 감사(월간, 36·60개월 상관)가 판정하며, 그 결과는 사람이 검토한다.
- **`channel` 의 품질.** 비었는지만 본다. "역사적으로 함께 움직였다" 류의 문장은
  기계가 거를 수 없다 — 리뷰의 몫이다.
- **시차의 타당성.** `lag_months` 는 선언이고 검증되지 않았다.
- **엣지 간 중복.** 예컨대 `real_rate_10y` 와 `fed_policy_path` 는 경로가 겹친다.
  후자를 공통 인자로 두어 중앙값 차감하는 것으로 완화했을 뿐, 이중 계상이 완전히
  제거되지는 않았다.
- **`to` 목록 안의 중복.** 스크립트는 같은 테마가 한 엣지의 `to` 에 두 번 들어가도 잡지
  않는다 (in-degree 가 1 과다 계상된다). M4-134 재매핑에서 "폐기 id 의 대체 버킷이 이미
  목록에 있으면 폐기 id 를 제거만 한다" 로 처리해 중복을 만들지 않았고, 위 §1 의 451 은
  중복 없이 센 값이다.

## 8. `docs/03` §2 와 `docs/08` §3 의 대조

FRED 시리즈 ID 는 `docs/08` §3 을 정본으로 썼다. 두 문서가 **충돌하는 항목은 없었다.**
`docs/03` §2 가 서술로만 적은 3건에 대해 `docs/08` §3 의 판정을 그대로 반영했다.

| 드라이버 | `docs/03` §2 | `docs/08` §3 (정본) | `state/macro-dag.yaml` 에 적은 것 |
|---|---|---|---|
| `gold_price` | "FRED 직접 시리즈 불안정 — ETF 프록시" | 동일 | `provider: etf, symbol: GLD, alt: [IAU]` |
| `copper_price` | `PCOPPUSDM` — 가용성 확인 필요, 폴백 `CPER` | 동일 | `series: PCOPPUSDM` + `fallback: CPER`, note 에 M1 실측 표기 |
| `defense_outlays` | `FDEFX` 분기 + 예산안(에이전트) | `FDEFX`, M1 실측 확인 필요 | `series: FDEFX`, state 는 집행 실적으로 판정 |
| `fed_policy_path` | `DFEDTARU` + 선물(외부) | `DFEDTARU`, 선물 곡선은 FRED 에 없음 | `series: DFEDTARU`, 기대 경로는 note 로 분리 |

M4-134 추가 엣지의 `observable` 도 같은 시리즈 id 만 썼다. 한 곳에서 `docs/08` §3 표 밖의
시리즈를 보조 조건으로 언급했다 — `employment → staffing_consulting` 의 `TEMPHELPS`
(임시직 고용). 드라이버 소스가 아니라 관측 보조 조건이며, 드라이버 목록에 추가하지 않았다.
L0 가 이 시리즈를 적재하지 않으면 그 조건은 무시되고 PAYEMS 조건만 남는다.

## 9. 선언된 예외 하나 — `policy_events`

다른 25개 드라이버는 `state` 가 스칼라 하나지만 `policy_events` 만 **(테마, 이벤트) 쌍**으로
판정된다. 시계열이 아니라 날짜 목록이기 때문이다 (`docs/08` §3 이 이미 지적).

엣지의 `sign` 은 "해당 테마에 유리한 정책이 확정됐을 때의 방향" 을 뜻하며,
규제가 기본값인 테마(`coal`·`tobacco`·`pharma_large`·`semi_equipment`·`education`·`pharma_generic` 등)는
`sign: -1` 로 적었다. 구현 시 `tailwind` 계산이 이 드라이버만 다르게 다뤄야 한다 —
스칼라 state 를 가정하고 짜면 조용히 틀린다.

## 10. M4-134 부록 — 134 버킷 기준 보정 내역

### 10-1. 폐기 초안 id 6개의 재매핑

`state/themes.yaml` 의 `notes` 가 적은 병합 방향을 그대로 따랐다. 재매핑 대상 버킷이
이미 같은 엣지의 `to` 에 있으면 폐기 id 를 **제거만** 했다(중복 방지). 채널 본문은
고치지 않았고, 병합 후 채널의 서술이 버킷의 일부에만 해당하게 된 곳은 엣지 위에
`# M4-134:` 주석으로 적었다 — 강도는 바꾸지 않았다(바꾸려면 근거가 따로 필요하다).

| 폐기 id | → 확정 버킷 | 근거 (`themes.yaml` notes) | 걸린 엣지 (드라이버) | 처리 |
|---|---|---|---|---|
| `nickel_cobalt` | `diversified_miners` | 니켈·코발트 라벨 없음, 종합광업에 흡수 | `dollar_broad` · `industrial_production` · `copper_price` · `china_credit_impulse` | 4건 모두 대체 버킷이 이미 있어 **제거** |
| `ag_machinery` | `construction_machinery` | 'Farm & Heavy Construction Machinery' 단일 라벨 (DE·AGCO·CNH + CAT) | `dollar_broad`(농가 소득→장비) · `ppi_yoy`(곡물가→장비) | **교체** + 주석: 채널의 '농기계' 는 병합 버킷의 농업 장비 부분에만 해당 |
| | | | `real_rate_10y`(할부 내구재) · `capex_orders_core` | 이미 있어 **제거** |
| `semi_memory` · `semi_analog_power` · `semi_foundry_logic` | `semi_devices` | 'Semiconductors' 단일 라벨 285종 — 손으로 가르면 생존 편향 | `inventory_sales` · `new_orders_mfg` · `industrial_production` · `hyperscaler_capex` | **교체**(중복 제거) |
| | | | `defense_outlays`(방산용 아날로그) · `policy_events`(CHIPS 파운드리) | **교체** + 주석: 병합 버킷의 일부(INTC·MU 팹 보유사 / 방산 아날로그)에만 해당 — 실효 강도는 선언보다 낮아졌으나 수치는 두었다 |
| `aerospace_commercial` | `defense` | 'Aerospace & Defense' 단일 라벨 212종 — 방산/상용 분리는 큐레이션 범위 밖 | `capex_orders_core`(항공기 자본재) · `employment`(항공 여객) | **교체** + 주석: 채널은 BA·TDG 등 상용 부분에만 해당 (둘 다 weak) |
| | | | `defense_outlays` | 이미 있어 **제거** |

### 10-2. 신설 버킷 31개에 붙인 엣지

원칙: 같은 채널이 그대로 성립하면 기존 엣지의 `to` 에 붙였다(엣지 위 `# M4-134:` 주석으로
무엇을 왜 붙였는지 적음). 채널이 고유하거나 부호가 다르면 새 레코드를 만들었다
(`# M4-134 추가` 주석, 파일 끝 공통 인자 절 바로 앞의 전용 블록). 새 레코드 14개:

| 새 엣지 | 부호·강도 | 왜 기존 엣지에 못 붙였나 |
|---|---|---|
| `employment → staffing_consulting` | +1 strong | 임시직은 고용의 선행 항목이라 재량 소비 엣지보다 시차가 짧다 [0,3] |
| `employment → business_services·consumer_services·insurance_brokers` | +1 moderate | 과금 단위가 "고객사 인원수" — 소비 지출 경로가 아니다 |
| `employment → education` | **−1** moderate | 영리 교육 등록은 역경기 (2008-2010) — 부호가 반대 |
| `employment → retail_discount·food_retail_distribution` | +1 weak | 필수 소비는 방어적 + 트레이드다운 상쇄 — strong 재량 엣지에 못 넣는다 |
| `new_orders_mfg → staffing_consulting` | +1 weak | 제조 수주 → 산업 임시직 (MAN·KELYA 부분만) |
| `capex_orders_core → business_services` | +1 weak | 사무가구·사무기기 부분만 자본재 |
| `housing_starts → metal_fabrication·rental_leasing` | +1 moderate | 착공의 2차 수요(공구·가공재·장비 렌탈). 자재 strong 엣지보다 약함 |
| `housing_starts → reit_specialty` | +1 weak | 팀버 리츠 부분만 |
| `hy_spread → reit_mortgage` | −1 strong | 레포 레버리지 → 마진콜. 기존 strong 리스트(해운·항공)와 메커니즘이 다르다 |
| `hy_spread → real_estate_services` | −1 moderate | 차입 매수 거래 건수 경로 — 고부채 엣지가 아니다 |
| `real_rate_10y → reit_mortgage` | −1 moderate | 캡레이트가 아니라 채권 듀레이션 경로. `contradicts_when`: MSR 보유사는 반대, term_spread 엣지와 국면 충돌 |
| `ppi_yoy → insurance_brokers` | **+1** moderate | 손보(−1)와 부호 반대 — 보험료 정률 수수료, 인수 리스크 없음 |
| `cpi_yoy → retail_discount·food_retail_distribution` | **+1** weak | 재량 유통(−1)과 부호 반대 — 필수품 명목 매출 + 트레이드다운. `contradicts_when`: 저소득 고객 기반(DG·DLTR) |
| `policy_events → health_it` | +1 weak | HITECH·원격의료 수가 — 정책 수요 strong 리스트(IRA·CHIPS)와 규모가 다르다 |

테마별 최종 입력 엣지 (드라이버 · 부호 · 강도). `*` 는 새 레코드, 나머지는 기존 엣지에 추가.

| 테마 (cycle_class) | in | 엣지 |
|---|---|---|
| `auto_dealers` (discretionary) | 2 | employment +1 strong · real_rate_10y −1 moderate(할부·플로어플랜) |
| `business_services` (secular_growth 잔여) | 2 | employment +1 moderate* · capex_orders_core +1 weak* |
| `conglomerates` (inventory) | 3 | new_orders_mfg +1 moderate · capex_orders_core +1 moderate · industrial_production +1 moderate |
| `consumer_electronics` (discretionary) | 3 | employment +1 strong · cpi_yoy −1 moderate · dollar_broad −1 weak(환산) |
| `consumer_services` (discretionary) | 2 | employment +1 moderate* · cpi_yoy −1 moderate |
| `education` (policy_program) | 2 | policy_events −1 moderate · employment **−1** moderate* |
| `food_retail_distribution` (secular_growth) | 2 | employment +1 weak* · cpi_yoy +1 weak* |
| `health_it` (secular_growth) | 3 | real_rate_10y −1 moderate · employment +1 weak · policy_events +1 weak* |
| `home_furnishings` (credit_rate) | 3 | real_rate_10y −1 strong · housing_starts +1 strong · employment +1 strong |
| `industrial_distribution` (inventory) | 3 | inventory_sales −1 strong · new_orders_mfg +1 moderate · industrial_production +1 moderate |
| `instruments_test` (capex_program) | 3 | capex_orders_core +1 moderate · new_orders_mfg +1 moderate · defense_outlays +1 weak |
| `insurance_brokers` (secular_growth) | 2 | ppi_yoy **+1** moderate* · employment +1 moderate* |
| `insurance_diversified` (credit_rate) | 3 | real_rate_10y **+1** moderate · ppi_yoy −1 moderate · hy_spread −1 weak |
| `it_services` (secular_growth) | 2 | hyperscaler_capex +1 moderate · employment +1 weak |
| `legacy_media` (secular_risk) | 3 | employment +1 strong · hy_spread −1 moderate · cpi_yoy +1 weak |
| `leisure_products` (discretionary) | 3 | employment +1 strong · real_rate_10y −1 moderate · cpi_yoy −1 moderate |
| `medical_distribution` (secular_growth) | 3 | employment +1 moderate · inventory_sales −1 moderate · cpi_yoy +1 weak |
| `metal_fabrication` (inventory) | 3 | new_orders_mfg +1 moderate · industrial_production +1 moderate · housing_starts +1 moderate* |
| `mortgage_finance` (credit_rate) | 3 | real_rate_10y −1 strong · hy_spread −1 moderate · employment +1 strong |
| `packaging` (inventory) | 3 | inventory_sales −1 moderate · industrial_production +1 moderate · oil_wti −1 moderate(수지 원료비) |
| `pharma_generic` (policy_program) | 3 | hy_spread −1 moderate · policy_events −1 moderate · dollar_broad −1 weak |
| `real_estate_services` (credit_rate) | 3 | real_rate_10y −1 strong · hy_spread −1 moderate* · employment +1 weak |
| `reit_diversified` (credit_rate) | 3 | real_rate_10y −1 strong · ig_spread −1 moderate · cpi_yoy +1 weak(CPI 연동 임대료) |
| `reit_hotel` (discretionary) | 3 | real_rate_10y −1 strong · employment +1 strong · hy_spread −1 moderate |
| `reit_mortgage` (credit_rate) | 3 | term_spread +1 strong · hy_spread −1 strong* · real_rate_10y −1 moderate* |
| `reit_specialty` (credit_rate 잔여) | 4 | real_rate_10y −1 strong · ig_spread −1 moderate · cpi_yoy +1 weak · housing_starts +1 weak* |
| `rental_leasing` (capex_program) | 3 | capex_orders_core +1 moderate · hy_spread −1 moderate · housing_starts +1 moderate* |
| `retail_discount` (discretionary, Consumer Defensive) | 2 | employment +1 weak* · cpi_yoy +1 weak* |
| `semi_devices` (inventory) | 6 | 재매핑만으로 충족 — inventory_sales −1 strong · new_orders_mfg +1 moderate · industrial_production +1 moderate · hyperscaler_capex +1 strong · policy_events +1 strong · defense_outlays +1 weak |
| `staffing_consulting` (discretionary) | 2 | employment +1 strong* · new_orders_mfg +1 weak* |
| `travel_booking` (discretionary) | 3 | employment +1 strong · cpi_yoy −1 moderate · dollar_broad −1 weak(BKNG·TCOM 해외 매출) |

### 10-3. 이 보정에서 하지 않은 것

- **기존 엣지의 부호·시차·강도·채널 본문을 고치지 않았다.** 병합으로 채널의 서술이 버킷의
  일부에만 해당하게 된 6건은 주석으로만 적었다 (§10-1). 강도를 내리는 것이 맞아 보이는
  곳(`policy_events → semi_devices` 의 CHIPS 경로)도 수치는 두었다 — 내리려면 모순 감사나
  부호 일치율 실측이라는 기록된 근거를 거쳐야 한다 (CLAUDE.md §1).
- **드라이버를 추가하지 않았다.** `lng`·`refiners`·`semi_eda_ip` 가 얕은 것은 드라이버 문제라는
  §3 의 판단은 그대로다.
- **데이터를 보고 엣지를 고르지 않았다.** 새 엣지의 `evidence` 는 기억하는 역사적 국면이며,
  `새 엣지 14개` 중 일부는 "2008-2009·2020" 같은 큰 국면 외에 인용할 사례가 없다. 이들은
  M4 마지막 항목(엣지 부호 일치율 실측)이 36·60개월 창에서 판정하고, **불일치하면 고치는
  것이 아니라 센다.**
