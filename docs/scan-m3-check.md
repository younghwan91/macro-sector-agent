# M3 육안 검증 · 사후 확인 (2026-08-23)

`docs/11-roadmap.md` M3 의 마지막 완료 기준 — "2026-08 시점 스코어보드에 원자재 계열이 이미 상위에
있는가?" — 의 답이다. **사후 확인이지 튜닝 근거가 아니다.** 여기서 본 것으로 가중치·방향·임계를
바꾸지 않는다 (`CLAUDE.md` §1). 재현: `uv run msa scan --asof <date> --no-write`.

## 1. 2026-08-14 (버킷 2026-08) 상위 20

| rank | theme | class | score | A | B | C | D | E | F | flags |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `media_streaming` | secular_growth | 0.84 | 0.87 | 0.91 | 0.74 | 0.88 | 0.78 | 0.88 | [SECULAR — 게이트 필요; no_etf_proxy] |
| 2 | `health_it` | secular_growth | 0.80 | 0.81 | 0.56 | 0.83 | 0.89 | 0.96 | 0.76 | [SECULAR — 게이트 필요; no_etf_proxy] |
| 3 | `retail_department` | secular_risk | 0.80 | 0.58 | 0.78 | 0.78 | 0.72 | 0.91 | 0.81 | [n=4 소표본; SECULAR — 게이트 필요; axis1:data_missing; no_etf_proxy] |
| 4 | `insurance_brokers` | secular_growth | 0.71 | 0.90 | 1.00 | 0.51 | 0.72 | 0.55 | 0.71 | [SECULAR — 게이트 필요; no_etf_proxy] |
| 5 | `shipping_container` | commodity_supply | 0.71 | 0.33 | 0.84 | 0.90 | 0.64 | 0.78 | 0.53 | [breadth_lead=1m; axis1:data_missing; no_etf_proxy] |
| 6 | `it_services` | secular_growth | 0.70 | 0.47 | 0.74 | 0.33 | 1.00 | 0.66 | 0.76 | [SECULAR — 게이트 필요; no_etf_proxy] |
| 7 | `home_improvement` | credit_rate | 0.70 | 0.93 | 0.74 | 0.93 | 0.34 | 0.87 | 0.61 | [axis1:data_missing; no_etf_proxy] |
| 8 | `fintech_payments` | discretionary_demand | 0.70 | 0.24 | 0.89 | 0.96 | 0.94 | 0.54 | 0.37 | [no_etf_proxy] |
| 9 | `staffing_consulting` | discretionary_demand | 0.69 | 0.67 | 0.60 | 0.81 | 0.90 | 0.13 | 0.57 | [no_etf_proxy] |
| 10 | `apparel_footwear` | discretionary_demand | 0.68 | 0.84 | 0.93 | 0.57 | 0.60 | 0.57 | 0.62 | [no_etf_proxy] |
| 11 | `household_products` | secular_growth | 0.68 | 0.65 | 0.43 | 0.81 | 0.98 | 0.72 | 0.26 | [SECULAR — 게이트 필요; no_etf_proxy] |
| 12 | `coatings_adhesives` | inventory | 0.68 | 0.46 | 0.75 | 0.72 | 0.84 | 0.63 | 0.63 | [short_hist; no_etf_proxy] |
| 13 | `rental_leasing` | capex_program | 0.67 | 0.06 | 0.66 | 0.75 | 0.16 | 0.74 | 0.82 | [no_etf_proxy] |
| 14 | `fertilizer_potash` | commodity_supply | 0.67 | 0.85 | 0.90 | 0.13 | 0.84 | 0.97 | 0.04 | [axis1:data_missing] |
| 15 | `real_estate_services` | credit_rate | 0.66 | 0.80 | 0.84 | 0.16 | 0.85 | 0.59 | 0.91 | [axis1:data_missing; no_etf_proxy] |
| 16 | `reit_industrial` | inventory | 0.65 | 0.57 | 0.63 | 0.59 | 0.90 | 0.50 | 0.72 | [no_etf_proxy] |
| 17 | `home_furnishings` | credit_rate | 0.65 | 0.69 | 0.58 | 0.69 | 0.70 | 0.66 | 0.49 | [no_etf_proxy] |
| 18 | `lng` | capex_program | 0.64 | 0.01 | 0.54 | 0.86 | 0.29 | 0.04 | 0.97 | [breadth_lead=1m; axis1:data_missing; no_etf_proxy] |
| 19 | `managed_care` | policy_program | 0.64 | 0.73 | 0.35 | 0.99 | 0.50 | 0.94 | 0.16 | nan |
| 20 | `commodity_chem` | commodity_supply | 0.64 | 0.74 | 0.79 | 0.25 | 0.48 | 0.81 | 0.66 | [breadth_lead=1m; axis1:data_missing] |

상단은 `secular_growth`(게이트 필요 표시) 와 소비·헬스케어·부동산 서비스다. 원자재는 `shipping_container`
(8위)·`fertilizer_potash`(18위) 를 빼면 상위 20 에 없다.

## 2. 원자재 계열의 2026-08-14 위치

| theme | rank | score | A | B | C | D | E | F |
|---|---|---|---|---|---|---|---|---|
| `silver_miners` | 105 | 0.40 | 0.32 | 0.19 | 0.72 | 0.49 | 0.22 | 0.69 |
| `pgm_miners` | 124 | 0.31 | 0.27 | 0.02 | 0.69 | 0.41 | 0.04 | 0.79 |
| `rare_earth` | 131 | 0.21 | 0.34 | 0.31 | 0.21 | 0.36 | 0.01 | 0.01 |
| `lithium` | 64 | 0.52 | 0.81 | 0.73 | 0.12 | 0.69 | 0.35 | 0.94 |
| `gold_miners` | 127 | 0.29 | 0.35 | 0.18 | 0.45 | 0.49 | 0.05 | 0.54 |
| `uranium` | 133 | 0.19 | 0.40 | 0.41 | 0.13 | 0.27 | 0.02 | 0.02 |
| `copper_miners` | 90 | 0.45 | 0.32 | 0.37 | 0.79 | 0.19 | 0.37 | 0.60 |
| `aluminum` | 99 | 0.42 | 0.35 | 0.09 | 0.55 | 0.40 | 0.37 | 0.92 |
| `oil_services` | 102 | 0.41 | 0.01 | 0.66 | 0.91 | 0.24 | 0.20 | 0.46 |
| `offshore_drilling` | 30 | 0.62 | 0.88 | 0.14 | 0.63 | 0.31 | 1.00 | 0.73 |
| `coal` | 112 | 0.38 | 0.59 | 0.82 | 0.11 | 0.15 | 0.72 | 0.15 |
| `solar` | 76 | 0.48 | 0.99 | 0.22 | 0.08 | 0.75 | 0.56 | 0.89 |

**답: 상위에 없다. 어긋났다.** 다만 어긋남의 이유가 설계와 일치한다 — 2025-H2 급등 뒤 2026-02 고점에서
7월까지 −40% 급락했고(`gold_miners` EW 지수 2.40 → 1.41, `NEM` 129 → 93), A 블록은 `months_since_peak`
5~6 개월을 **패닉**으로 읽지 망각으로 읽지 않는다 (`02` §A: "6개월 −50% 는 패닉, 48개월 −50% 는 망각").
C 블록도 `above_200 = 0`·`breadth_200 ≈ 0` 으로 "아직 안 돌았다" 를 말한다. 프로필로는 **A↑ B↑ C↓ = 아직
바닥, 관심 목록** 에 가깝지 진입 구간이 아니다.

## 3. 되감기 — 원형 사례는 미리 잡혔는가

원형 사례(AG·SBSW·MP·ALM → `silver_miners`·`pgm_miners`·`rare_earth`·`lithium`)는 2025 년 안에 매수돼
단기 +30% 를 냈다. 그 직전 시점의 스코어보드 순위:

| theme | 2024-12-31 | 2025-03-31 | 2025-06-30 |
|---|---|---|---|
| `silver_miners` | 122 | 87 | 83 |
| `pgm_miners` | 107 | 44 | 90 |
| `rare_earth` | 13 | 84 | 86 |
| `lithium` | 63 | 48 | 56 |
| `aluminum` | 30 | 8 | 3 |
| `oil_services` | 12 | 20 | 79 |
| `copper_miners` | 129 | 119 | 29 |
| `uranium` | 134 | 132 | 121 |

**미리 잡지 못했다.** `rare_earth` 가 2024-12 에 13위였던 것 외에는 넷 다 중·하위였다. 원인을 블록별로
보면 공통으로 **E(자본사이클) 백분위가 낮다** — `silver_miners` 0.13/0.02, `rare_earth` 0.03/0.03,
`pgm_miners` 0.41/0.34. 2023~2025 의 광업은 금·은 가격 상승으로 capex/D&A 가 1 을 넘는 확장기였고,
자산 성장도 양수였다. `commodity_supply` 에 E 가중치 0.30 을 준 선언("공급이 유일한 인과 엔진")이
**이 사례에서는 반대 방향으로 작동했다** — 저점이 공급 파괴가 아니라 **가격 붕괴(수요·심리)**에서 왔기
때문이다. 반면 A(망각)·B(베이스)는 `lithium`(0.89/0.98)·`solar`(1.00/0.99) 에서 설계대로 높았다.

## 4. 이것으로 무엇을 하는가

- **가중치를 옮기지 않는다.** 표본 하나로 0.30 을 내리는 것이 정확히 `CLAUDE.md` §1 이 금지하는 일이다.
- M3.5 가 **정량으로** 답한다 — 블록별 단독 IC 와 `cycle_class` 별 분해가 "E 가 `commodity_supply` 에서
  정말 가장 센가" 를 1998~2026 전 구간에서 묻는다 (`10-validation.md` §2.1). 여기서 본 것은 그 검정의
  **가설**이지 결론이 아니다.
- 선언의 근거를 다시 읽는다: `02` §7 "공급이 이 클래스의 유일한 인과 엔진" 은 **공급 파괴형** 저점의
  서술이다. 가격 붕괴형 저점(2025 귀금속)은 다른 모양일 수 있다는 사실을 기록해 둔다.

## 5. 데이터 한계 (이 표를 읽을 때)

- CPI·FRED 참조 없음(`FRED_API_KEY` 미설정) → `dd_real` 미계산, 축 1 데이터 보유 7/45.
- 9개 소표본 버킷(`silver_miners` 생존 4 등)은 중앙값 통계 신뢰 불가 — 플래그 표기.
- ETF 프록시 상관 > 0.85 는 44개 중 17개 — 상관이 낮은 버킷의 프록시는 자체지수를 대표하지 않는다.
