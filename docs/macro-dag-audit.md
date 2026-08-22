# 거시 인과 DAG 감사 (M4)

`state/macro-dag.yaml` 에 대한 `scripts/audit_dag.py` 실행 결과와 그 해석.
실행: `uv run --with pyyaml python scripts/audit_dag.py` (종료코드 0 = 전 항목 통과)

## 1. 요약

| 항목 | 값 |
|---|---|
| 드라이버 | 26개 (`docs/03-macro-dag.md` §2 전부) |
| 공통 인자 (`common_factor: true`) | 3개 — `usd_liquidity` · `fed_policy_path` · `m2_growth` |
| 엣지 레코드 | 72개 (개별 69 + 공통 인자 3) |
| 테마-엣지 쌍 | **380개** (공통 인자 제외) / 하한 220 |
| 테마 in-degree | **min 2 · median 3 · max 6** (공통 인자 제외) |
| 입력 엣지 2개 미만 테마 | **0개** |
| `channel` 이 빈 엣지 | 0개 |
| `contradicts_when` 을 가진 엣지 | 22개 |
| 강도 분포 | strong 20 · moderate 31 · weak 21 |
| 부호 분포 | +1 37 · −1 35 |

테마 목록의 출처는 `docs/01-theme-universe.md` §3 초안(109개)이다.
**`state/themes.yaml` 이 생기면 그것이 정본이며**, `audit_dag.py` 는 그 파일이 존재할 때
자동으로 그쪽을 읽는다. M2 확정 후 이 감사를 다시 돌려 신설·병합·삭제된 테마의
in-degree 하한을 재확인해야 한다 — 그때 하한 미달이 새로 생길 수 있다.

## 2. 검사 항목별 결과

| 검사 | 기준 | 결과 |
|---|---|---|
| 모든 테마 입력 엣지 ≥ 2 | 공통 인자 제외 | 통과 (미달 0개) |
| `channel` 이 빈 엣지 | 0개 | 통과 |
| 필수 필드 (`from`·`to`·`sign`·`strength`·`channel`·`observable`) | 전부 존재 | 통과 |
| `from` 이 드라이버 목록에 있는가 | 전부 | 통과 |
| `to` 가 테마 id 인가 | 전부 (공통 인자의 `*` 제외) | 통과 |
| `sign` ∈ {+1, −1} | — | 통과 |
| `strength` ∈ {strong, moderate, weak} | — | 통과 |
| 공통 인자가 개별 테마를 지목하지 않는가 | `*` 만 허용 | 통과 |

## 3. 입력 엣지 2개를 못 채운 테마

**없다.** 109개 테마 전부가 개별(비공통) 입력 엣지를 2개 이상 갖는다.

다만 **하한을 겨우 채운 17개 테마**는 "거시로 설명되는 정도가 얕다"는 뜻이며,
이 사실 자체가 정보다. `docs/03` §4 의 `final(t) = 0.70·cycle + 0.30·tailwind` 에서
이들의 tailwind 는 소수 엣지에 의존하므로 한 드라이버가 뒤집히면 점수가 크게 흔들린다.

in-degree 2인 테마 (17개):
`advertising` · `asset_managers_exchanges` · `biotech_clinical` · `datacenter_hw` ·
`food_beverage` · `gaming_interactive` · `insurance_life` · `internet_platform` ·
`life_science_tools` · `lng` · `reinsurance` · `reit_towers` · `semi_eda_ip` ·
`software_vertical` · `space_satellite` · `tobacco` · `water_utility`

성격별로 나누면 셋이다.

- **거시로 설명되는 축이 정말 좁은 것** — `biotech_clinical`(실질금리·HY 스프레드가 사실상 전부),
  `tobacco`·`asset_managers_exchanges`. 엣지를 억지로 늘리는 것이 오히려 왜곡이다.
- **드라이버가 지배적이라 다른 엣지가 잡음인 것** — `datacenter_hw`(하이퍼스케일러 capex),
  `reit_towers`. 하나의 강한 엣지 + 하나의 약한 엣지 구조가 실제를 반영한다.
- **관측 드라이버가 없어서 얕은 것** — `lng`(국내외 가스 스프레드가 드라이버 목록에 없다),
  `semi_eda_ip`(수출통제 이벤트 외에 대리 변수가 없다), `space_satellite`.
  이쪽은 드라이버를 늘려야 해결되는 문제이며, 엣지를 늘려 해결할 문제가 아니다.

`refiners` 는 in-degree 는 4지만 **부호가 가장 약한 테마**다 — 손익이 유가 수준이 아니라
크랙 스프레드라 `oil_wti` 엣지를 `weak` 로 두고 대리 변수임을 명시했다. 크랙 스프레드
시계열이 드라이버로 추가되면 이 엣지는 대체되어야 한다.

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

테마-엣지 쌍 기준. 공통 인자는 `*` 를 109개 테마로 전개한 값이다.

| 드라이버 | out | 드라이버 | out |
|---|---|---|---|
| `real_rate_10y` | 54 | `oil_wti` | 20 |
| `policy_events` | 38 | `hyperscaler_capex` | 19 |
| `employment` | 31 | `industrial_production` | 17 |
| `hy_spread` | 27 | `inventory_sales` | 17 |
| `dollar_broad` | 23 | `cpi_yoy` | 16 |
| `china_credit_impulse` | 16 | `capex_orders_core` | 13 |
| `nat_gas` | 12 | `housing_starts` | 11 |
| `breakeven_10y` | 9 | `ig_spread` | 9 |
| `china_property` | 9 | `ppi_yoy` | 9 |
| `copper_price` | 8 | `defense_outlays` | 8 |
| `new_orders_mfg` | 7 | `term_spread` | 4 |
| `gold_price` | 3 | | |
| `usd_liquidity` (공통) | 109 | `fed_policy_path` (공통) | 109 |
| `m2_growth` (공통) | 109 | | |

**`real_rate_10y` 의 54는 이 DAG 의 최대 집중이며, 이것이 이 저장소의 주된 리스크다.**
전체 테마-엣지 쌍의 14% 가 한 드라이버에 걸려 있다. 실질금리가 한 방향으로 움직이면
tailwind 가 광범위하게 같은 방향으로 밀리고, 그러면 §7 이 경고한 "공통 인자는 테마를
고르는 데 쓸모없다" 는 문제가 공통 인자로 선언되지 않은 드라이버에서 재발한다.

`real_rate_10y` 를 공통 인자로 돌리지 않은 이유는 **부호가 갈리기 때문이다** —
보험 3종(`insurance_pc`·`insurance_life`·`reinsurance`)은 `+1` 이다. 이들은 차입자가
아니라 대여자라 금리 상승이 재투자 수익이다. 부호가 갈리는 드라이버는 정의상 공통 인자가
아니며, 실제로 상대 순위를 만든다. 다만 집중도가 높다는 사실은 리포트에 표기해야 한다.

`term_spread` 의 4가 최소다. 은행 2종 + 생보·자산운용에만 걸린다 — 곡선 기울기가
직접 손익인 사업이 그것뿐이기 때문이며, 억지로 넓히지 않았다.

## 6. 테마 in-degree 분포 (공통 인자 제외)

```
in-degree  2: 테마  17개  #################
in-degree  3: 테마  45개  #############################################
in-degree  4: 테마  29개  #############################
in-degree  5: 테마  13개  #############
in-degree  6: 테마   5개  #####
```

최다(6): `aluminum` · `copper_miners` · `diversified_miners` · `epc_engineering` · `midstream`
최소(2): §3 의 17개 목록

기저금속 광업이 상단에 몰린 것은 우연이 아니다 — 달러·중국 신용·중국 부동산·산업생산·
금속 가격이 전부 걸리는 구조라 **거시로 가장 잘 설명되는 테마군**이다. 뒤집어 말하면
거시가 역풍일 때 개별 논지로 버티기 가장 어려운 테마군이기도 하다.

## 7. 이 감사가 검사하지 **않는** 것

- **엣지의 참/거짓.** 이 스크립트는 스키마와 커버리지만 본다. 엣지가 맞는지는
  `docs/03` §6 의 모순 감사(월간, 36·60개월 상관)가 판정하며, 그 결과는 사람이 검토한다.
- **`channel` 의 품질.** 비었는지만 본다. "역사적으로 함께 움직였다" 류의 문장은
  기계가 거를 수 없다 — 리뷰의 몫이다.
- **시차의 타당성.** `lag_months` 는 선언이고 검증되지 않았다.
- **엣지 간 중복.** 예컨대 `real_rate_10y` 와 `fed_policy_path` 는 경로가 겹친다.
  후자를 공통 인자로 두어 중앙값 차감하는 것으로 완화했을 뿐, 이중 계상이 완전히
  제거되지는 않았다.

## 8. `docs/03` §2 와 `docs/08` §3 의 대조

FRED 시리즈 ID 는 `docs/08` §3 을 정본으로 썼다. 두 문서가 **충돌하는 항목은 없었다.**
`docs/03` §2 가 서술로만 적은 3건에 대해 `docs/08` §3 의 판정을 그대로 반영했다.

| 드라이버 | `docs/03` §2 | `docs/08` §3 (정본) | `state/macro-dag.yaml` 에 적은 것 |
|---|---|---|---|
| `gold_price` | "FRED 직접 시리즈 불안정 — ETF 프록시" | 동일 | `provider: etf, symbol: GLD, alt: [IAU]` |
| `copper_price` | `PCOPPUSDM` — 가용성 확인 필요, 폴백 `CPER` | 동일 | `series: PCOPPUSDM` + `fallback: CPER`, note 에 M1 실측 표기 |
| `defense_outlays` | `FDEFX` 분기 + 예산안(에이전트) | `FDEFX`, M1 실측 확인 필요 | `series: FDEFX`, state 는 집행 실적으로 판정 |
| `fed_policy_path` | `DFEDTARU` + 선물(외부) | `DFEDTARU`, 선물 곡선은 FRED 에 없음 | `series: DFEDTARU`, 기대 경로는 note 로 분리 |

## 9. 선언된 예외 하나 — `policy_events`

다른 25개 드라이버는 `state` 가 스칼라 하나지만 `policy_events` 만 **(테마, 이벤트) 쌍**으로
판정된다. 시계열이 아니라 날짜 목록이기 때문이다 (`docs/08` §3 이 이미 지적).

엣지의 `sign` 은 "해당 테마에 유리한 정책이 확정됐을 때의 방향" 을 뜻하며,
규제가 기본값인 테마(`coal`·`tobacco`·`pharma_large`·`semi_equipment` 등)는 `sign: -1` 로 적었다.
구현 시 `tailwind` 계산이 이 드라이버만 다르게 다뤄야 한다 — 스칼라 state 를 가정하고
짜면 조용히 틀린다.
