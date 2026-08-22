# 테마 커버리지 감사 — M2 실측

> 대상: `state/themes.yaml` (확정 버킷 **134개**)
> 데이터: `/home/young/data/us_micro.duckdb` (Sharadar). `prices` 최종일 2026-08-14.
> 재현: `uv run --with duckdb --with pyyaml python scripts/audit_themes.py`
> 검사 정의: `docs/01-theme-universe.md` §5

## 0. 유니버스와 배정 규칙

| 항목 | 값 |
|---|---|
| `tickers` 전체 | 43,919 |
| 유니버스 (보통주·ADR 보통주·캐나다 보통주) | **19,717** |
| 버킷에 배정된 종목 | **17,917** |
| `Shell Companies` (분모 밖) | 1,659 |
| `industry` 가 `null` 인 종목 (미분류) | 141 |

유니버스는 `category LIKE '%Common Stock%' AND category NOT LIKE '%Preferred%'` 이다.
ETF(7,632)·CEF(1,072)·우선주(1,137)·`Institutional Investor`(13,230)·ETD·ETN 은
테마 구성원이 아니므로 처음부터 제외한다.

배정은 세 단계다. ① `exclude_tickers` 가 버킷에서 티커를 뺀다 → ② `include_tickers` 가
티커를 배정하며 `industry_match` 를 덮어쓴다 → ③ 나머지는 `industry_match` 로 배정한다.
152개 `industry` 라벨은 각각 정확히 한 버킷의 `industry_match` 에만 등장하므로
③ 경로에서 중복은 구조적으로 발생할 수 없다.

`Shell Companies`(1,659종목 / 86.0 B USD)를 분모에서 뺀 것은 판단이며, 여기 적어 둔다.
SPAC·껍데기 법인이라 영업 실체가 없고 매출·capex·재고가 정의되지 않는다 —
어느 사이클 유형에도 넣을 수 없고, 잔여 버킷을 만들어 담으면 그 버킷의 통계가 무의미해진다.
**분모에 넣고 미분류로 셌다면 미분류 비율은 0.085% 로, 여전히 기준을 통과한다.**

## 1. 미분류 시총 비율 — 기준 < 5% → **PASS**

| 항목 | 값 (M USD) |
|---|---|
| 분모 (생존 종목 시총, Shell 제외) | 101,384,132 |
| 미분류 시총 | **112** |
| **미분류 비율** | **0.000%** |

미분류로 남은 것은 `industry` 라벨 자체가 `null` 인 141종목(생존 1종목, 112 M USD)뿐이다.
벤더가 분류를 붙이지 않은 종목이라 매칭 규칙으로 잡을 방법이 없다.

152개 `industry` 라벨 중 **151개**가 버킷에 배정됐다. 배정되지 않은 1개는 `Shell Companies`
(위의 판단). 초안 대비 미분류가 사라진 이유는 초안 109개가 다루지 않던 산업(IT 서비스·
소비자 전자·할인점·보험중개·포장·렌탈 등)에 버킷을 신설했기 때문이며, 신설 목록과 사유는
`docs/01-theme-universe.md` §3.1 에 있다.

## 2. 중복 소속 티커 — 기준 0개 → **PASS**

| 검사 | 건수 |
|---|---|
| 한 `industry` 라벨이 두 버킷의 `industry_match` 에 등장 | **0** |
| 한 티커가 두 버킷의 `include_tickers` 에 등장 | **0** |

한 티커는 정확히 0개 또는 1개 버킷에 속한다. L5 집중도 계산이 오염되지 않는다.

## 3. `min_constituents` 미달 버킷 — 리포트에 경고 표기 → **9개 미달**

생존 구성원 수 기준. 전체 134개 중 9개(6.7%).

| 버킷 | 생존 | 기준 | 미달 사유 |
|---|---|---|---|
| `shipbuilding` | 1 | 5 | 세계 조선의 중심이 미국 미상장(HD현대·한화오션·삼성중공업·CSSC). 미국 상장은 HII 뿐 |
| `industrial_gas` | 2 | 5 | 미국 상장 순수 산업가스가 LIN·APD 둘뿐 (ARG 는 2016 피인수) |
| `reit_datacenter` | 2 | 5 | DLR·EQIX 외 4종이 2017-2022 사모 피인수로 상장 폐지 |
| `wind` | 3 | 5 | Vestas·Siemens Gamesa·Ørsted 전원 미국 미상장 |
| `infra_construction` | 3 | 5 | `Infrastructure Operations` 라벨 자체가 3종목 |
| `silver_miners` | 4 | 5 | Sharadar 가 은 생산자 대부분을 `Other Precious Metals & Mining` 으로 분류 |
| `aluminum` | 4 | 5 | 미국 상장 알루미늄이 AA·CENX·CSTM·KALU 넷 |
| `retail_department` | 4 | 5 | **소멸이 실측으로 확인된 경우** — 29종목 중 25종 폐지 |
| `reit_towers` | 4 | 5 | 미국 상장 타워 REIT 가 AMT·CCI·SBAC·UNIT 넷 |

세 종류로 갈린다. (a) 미국 상장 유니버스에 그 산업이 없다 — `shipbuilding`·`wind`.
`docs/01` §6-3 의 "순수 해외 상장은 범위 밖" 규약에 정면으로 걸리며, 이 두 버킷은
**미국 시장을 통해서는 볼 수 없는 테마**다. (b) 산업은 있으나 상장 표본이 인수로 줄었다 —
`reit_datacenter`·`industrial_gas`. 사양이 아니라 사모화이므로 반대 해석을 하면 안 된다.
(c) 실제 소멸 — `retail_department`.

**억지로 채우지 않았다.** 구성원을 늘리려면 `include_tickers` 로 인접 산업을 끌어와야 하는데,
그렇게 만든 버킷은 큐레이션 목록이 곧 정의가 되어 `docs/01` §1 이 경고한 생존 편향을 낳는다.
이 9개는 스코어를 산출하되 **중앙값 통계 신뢰도를 하향**해 쓰고, 리포트에 경고를 표기한다.

## 4. 폐지 종목 포함 여부 — 자기이력 구간에 반드시 포함 → **PASS (단, 9개 버킷 주의)**

| 항목 | 값 |
|---|---|
| 배정된 폐지 종목 | **12,628** / 17,917 (70.5%) |
| 폐지 구성원이 0인 버킷 | 9개 |

폐지 종목이 0인 9개는 두 갈래다.

**(a) 산업 자체가 최근에 생겨 폐지될 시간이 없었다** — `ev_charging`(2020년 이후 상장),
`nuclear_smr`(7종 중 5종이 2021년 이후), `space_satellite`(대부분 2021 SPAC),
`infra_construction`, `cruise_lines`(3대 선사가 30년째 생존). 편향이 아니다.

**(b) `include_tickers` 큐레이션의 생존 편향이 실재한다** — `coatings_adhesives`(5종 전원 생존),
`fintech_payments`(14종 전원 생존), `reit_towers`(4종 전원 생존), `shipbuilding`(1종).
이 넷은 오늘 아는 대형주만 들어가 있어 **자기이력 백분위가 낙관 방향으로 왜곡된다.**
`docs/01` §5 가 지목한 바로 그 실패다. M3 에서 과거 폐지 구성원(Valspar·Airgas 계열,
2000년대 결제 처리업체 등)을 보강해야 하며, 그 전까지 이 넷의 백분위는 신뢰하지 않는다.

반면 큐레이션 버킷이라도 폐지를 명시적으로 넣은 곳은 편향이 통제됐다 —
`rare_earth`(MCPIQ/Molycorp 2015 파산 등 4종), `shipping_tanker`(GMRRQ·OSGIQ 등 11종),
`cybersecurity`(MNDT·PFPT·MIME·SPLK 등 7종), `reit_datacenter`(CONE·QTS·DFT·SWCH 4종),
`lithium`(LTHM·PLL·AMLIF 3종), `pgm_miners`(SWC·PALDF 2종).

## 5. ETF 프록시 vs 자체지수 12M 상관 — 기준 > 0.85 → **미실행**

**이 검사는 M2 에서 돌리지 않았다.** 자체 구성 지수(동일가중·시총가중)를 만드는 코드가
아직 없기 때문이다(`src/` 는 다른 작업 단위). 기준을 통과했다고 적을 근거가 없으므로
미실행으로 기록한다.

실행 시 주의할 점을 미리 적어 둔다. `etf_proxy` 가 `null` 인 버킷이 **134개 중 89개**로,
이 검사가 애초에 적용되지 않는 버킷이 다수다. 그리고 통과할 가능성이 낮은 것이 이미 보인다 —
`shipping_drybulk`(잔여집합이라 KEX·SFL 등 비벌크 혼입), `semi_devices`(메모리·아날로그·
로직이 한 지수에 섞임), `business_services`(세 라벨을 묶은 잔여성 버킷),
`utility_ipp`(가스 IPP 와 재생 IPP 혼합). 넷 다 `state/themes.yaml` 의 `notes` 에
혼입 사실을 적어 두었다.

## 6. 버킷별 시총 합계 추이 — 급변 시 로그 → **미실행 (기준선만 확보)**

시계열 추이 비교는 이전 적재본이 있어야 성립한다. M2 가 첫 적재이므로 **이번 값이 기준선**이다.
다음 적재부터 이 표와 비교해 급변을 로그한다.

## 7. 버킷별 구성원 수 · 시총 (기준선)

`n` = 폐지 포함 전체 구성원, `live` = 생존, `mcap` = 생존 구성원의 최근 시총 합(M USD),
`ax1` = `physical_ref` 가 있어 축 1(물량 추세)을 쓸 수 있는가.

시총 상위 40개만 싣는다. 전체 134행은 `scripts/audit_themes.py` 실행으로 얻는다.

| id | cycle_class | n | live | mcap (M) | ax1 |
|---|---|---:|---:|---:|:-:|
| `semi_devices` | inventory | 282 | 65 | 14,700,688 | Y |
| `internet_platform` | discretionary_demand | 200 | 68 | 6,210,488 | – |
| `software_infra` | secular_growth | 271 | 150 | 5,161,530 | – |
| `consumer_electronics` | discretionary_demand | 42 | 17 | 4,613,741 | – |
| `banks_large` | credit_rate | 41 | 21 | 4,280,754 | – |
| `pharma_large` | secular_growth | 31 | 20 | 3,968,962 | – |
| `defense` | capex_program | 204 | 85 | 3,742,509 | – |
| `ecommerce` | discretionary_demand | 114 | 42 | 3,589,712 | – |
| `asset_managers_exchanges` | credit_rate | 500 | 218 | 3,183,694 | – |
| `intl_majors` | commodity_supply | 29 | 19 | 2,193,988 | Y |
| `software_vertical` | secular_growth | 1,681 | 232 | 2,129,104 | – |
| `banks_regional` | credit_rate | 1,445 | 320 | 2,033,572 | – |
| `semi_equipment` | inventory | 123 | 30 | 2,015,143 | – |
| `auto_oem` | discretionary_demand | 88 | 31 | 1,917,150 | Y |
| `biotech_clinical` | credit_rate | 1,493 | 614 | 1,646,272 | – |
| `retail_discount` | discretionary_demand | 30 | 9 | 1,493,531 | – |
| `utility_regulated` | credit_rate | 169 | 54 | 1,399,980 | Y |
| `datacenter_hw` | capex_program | 216 | 41 | 1,399,569 | – |
| `fintech_payments` | discretionary_demand | 14 | 14 | 1,375,796 | – |
| `insurance_diversified` | credit_rate | 19 | 14 | 1,280,873 | – |
| `medtech_devices` | secular_growth | 653 | 187 | 1,261,200 | – |
| `food_beverage` | secular_growth | 271 | 88 | 1,233,513 | – |
| `industrial_automation` | inventory | 238 | 76 | 1,099,546 | – |
| `networking_optical` | capex_program | 416 | 50 | 986,304 | – |
| `telecom_carriers` | credit_rate | 503 | 45 | 922,953 | – |
| `cybersecurity` | secular_growth | 21 | 13 | 855,554 | – |
| `media_streaming` | secular_growth | 214 | 54 | 854,780 | – |
| `midstream` | capex_program | 153 | 31 | 823,766 | – |
| `life_science_tools` | inventory | 227 | 50 | 804,068 | – |
| `oil_gas_ep` | commodity_supply | 420 | 74 | 792,788 | Y |
| `managed_care` | policy_program | 45 | 10 | 752,923 | – |
| `household_products` | secular_growth | 77 | 30 | 711,027 | – |
| `ems_pcb` | inventory | 221 | 53 | 696,701 | – |
| `insurance_pc` | credit_rate | 221 | 60 | 687,009 | – |
| `gold_miners` | commodity_supply | 121 | 50 | 680,018 | Y |
| `construction_machinery` | capex_program | 63 | 23 | 677,323 | – |
| `it_services` | secular_growth | 127 | 70 | 677,082 | – |
| `retail_specialty` | discretionary_demand | 369 | 79 | 665,587 | – |
| `restaurants` | discretionary_demand | 210 | 54 | 558,017 | – |
| `railroads` | inventory | 31 | 11 | 556,349 | Y |

## 8. 축 1(물량 추세) 적용 가능 범위

| 항목 | 값 |
|---|---|
| `physical_ref` 가 채워진 버킷 (`axis1_available = true`) | **45 / 134 (33.6%)** |
| `physical_ref: null` (`axis1_available = false`) | **89 / 134 (66.4%)** |

`docs/04-value-trap.md` 축 1 은 "어느 쪽 시계열이든 존재하는 테마는 109개 중 20개 안팎"
이라고 추정했다. **실측은 45개로, 추정의 두 배가 넘는다.** 늘어난 이유는 원자재 계열 밖에서
물량 시계열이 잡혔기 때문이다 — 철도 화물 적재 건수, 트럭 톤수, 항공 유상여객마일,
경상용차 판매 대수, 주택 착공 호수, 시멘트 산업생산, 유료방송 가입자 수, 담배 출하 개비 수,
전력 생산 지수. 이들은 전부 금액이 아니라 **물량**이라 축 1 의 1순위 입력 자격을 만족한다.

그럼에도 **89개 버킷에서는 가장 결정적인 축이 계산되지 않는다.** 특히 `secular_risk` 9개 중
`legacy_media`·`reit_retail` 둘이 `physical_ref: null` 이며, 이 둘은 하드 게이트를 쥔 축이
LLM(축 3)이 된다 — 리포트의 `key_uncertainties` 에 `axis1_available = false` 를 명시해야 한다.

소스 구성은 `fred` 20 · `manual` 18 · `etf` 7 이다. 이 중 `verify: true` 가 붙은 것이 **16개**로,
FRED 시리즈 ID 의 실재 여부를 확인하지 않았다는 뜻이다. M3 적재 시 확인해 실패하면 해당 버킷은
`null` 로 내린다. **확인 전까지 이 16개를 축 1 적용 가능으로 계산에 넣지 않는다 — 확정 가용은 29개다.**
`manual` 18개는 자동 수집 경로가 없어 사람이 갱신해야 하며, 갱신이 밀리면 그 버킷의 축 1 은
낡은 값으로 판정하게 된다. 이것도 위험이므로 여기 적어 둔다.

## 9. 종합

| 검사 | 기준 | 결과 |
|---|---|---|
| 1. 미분류 시총 비율 | < 5% | **PASS** (0.000%) |
| 2. 중복 소속 티커 | 0개 | **PASS** (0건) |
| 3. `min_constituents` 미달 | 경고 표기 | **9개 미달** — 표기함 |
| 4. 폐지 티커 포함 | 반드시 포함 | **PASS** — 단 4개 버킷에 큐레이션 생존 편향 잔존 |
| 5. ETF 프록시 상관 | > 0.85 | **미실행** (지수 구성 코드 없음) |
| 6. 시총 합계 추이 | 급변 시 로그 | **미실행** (첫 적재 — 기준선 확보) |

스캔을 막는 하드 실패(1·2)는 없다. 3·4 는 경고이며 해당 버킷의 신뢰도를 하향해 쓴다.
5·6 은 M2 범위 밖이라 **통과가 아니라 미실행**으로 기록했다.
