# 03 · 거시 인과 DAG (L2)

## 1. 왜 회귀가 아니라 선언인가

드라이버 26개(§2) × 테마 109개 = **2,834개 잠재 엣지**. 여기에 시차까지 탐색하면 수만 개다.
이걸 데이터로 학습하면 무엇이 나오는가 — 우연한 상관의 최대치가 나온다.
표본은 사이클 2~3바퀴뿐이므로 검증도 불가능하다. `portfolio-research` 가 DSR·PBO 로
값을 매기던 바로 그 비용을, 여기서는 **탐색 자체를 하지 않는 것**으로 치른다.

> **엣지는 사람이 선언한다.** 부호·시차·전달 채널·근거·관측 지표·모순 조건을 함께 쓴다.
> 데이터는 선언을 **반박**하는 데만 쓰인다 (§5 모순 감사). 선언을 **조정**하는 데 쓰지 않는다.

부수 효과가 하나 있는데, 이게 실은 주된 효과다: **선언된 엣지는 읽을 수 있다.**
"우라늄이 왜 오르는가" 에 "실질금리 하락 · 원전 재가동 정책 · 공급 파괴" 라고 답할 수 있고,
그 각각이 관측 가능하므로 **논지가 죽었는지 판정할 수 있다.** 회귀 가중치는 그게 안 된다.

## 2. 드라이버 목록

`state_rule` 은 각 드라이버가 "우호적" 인 조건을 정의한다. 값은 3상태: `+1 / 0 / −1`.

### 금리·통화
| id | 소스 | 우호 판정 |
|---|---|---|
| `real_rate_10y` | FRED `DFII10` | 6개월 변화 < 0 → 실질자산·무이자자산·장기듀레이션에 우호 |
| `term_spread` | FRED `T10Y2Y` | 역전 해소(가팔라짐) → 은행·초기 사이클 |
| `breakeven_10y` | FRED `T10YIE` | 상승 → 실물자산 |
| `dollar_broad` | FRED `DTWEXBGS` | 6개월 변화 < 0 → **원자재 전반의 1차 드라이버** |
| `fed_policy_path` | FRED `DFEDTARU` + 선물 (외부) | 완화 방향 |
| `usd_liquidity` | `WALCL − WTREGEN − RRPONTSYD` (파생) | 확장 → 위험자산 전반 |
| `m2_growth` | FRED `M2SL` YoY | |

### 성장·산업
| id | 소스 | 우호 판정 |
|---|---|---|
| `industrial_production` | FRED `INDPRO` YoY | 2계도함수 > 0 (감속의 감속) |
| `new_orders_mfg` | FRED `AMTMNO` | 6개월 변화 > 0 |
| `capex_orders_core` | FRED `NEWORDER` (비국방 자본재 ex 항공) | 기업 투자 사이클의 선행 |
| `inventory_sales` | FRED `ISRATIO` | **하락 → 재고 소진 완료 → 재주문.** `inventory` 클래스의 핵심 |
| `housing_starts` | FRED `HOUST` | |
| `employment` | FRED `PAYEMS`, `UNRATE` | |

### 신용·리스크
| id | 소스 | 우호 판정 |
|---|---|---|
| `hy_spread` | FRED `BAMLH0A0HYM2` | 축소 → 고레버리지 사이클주·임상 바이오텍 |
| `ig_spread` | FRED `BAMLC0A0CM` | |

### 물가·원자재
| id | 소스 | 비고 |
|---|---|---|
| `cpi_yoy` / `ppi_yoy` | FRED `CPIAUCSL` / `PPIACO` | 실질화 계산에도 사용 |
| `oil_wti` | FRED `DCOILWTICO` | |
| `copper_price` | FRED `PCOPPUSDM` (IMF) — **가용성 확인 필요** | 폴백: ETF `CPER` |
| `gold_price` | **FRED 직접 시리즈 불안정 — ETF `GLD`/`IAU` 프록시 사용** | |
| `nat_gas` | FRED `DHHNGSP` | |

### 외부·수동 (FRED 에 없음 — 에이전트 또는 수동 갱신)
| id | 갱신 | 비고 |
|---|---|---|
| `china_credit_impulse` | 월 1회 수동/에이전트 | 중국 사회융자총량(TSF) 12개월 변화/GDP. **원자재의 최강 선행지표 중 하나** |
| `china_property` | 월 1회 | 착공·판매 |
| `defense_outlays` | FRED `FDEFX` 분기 + 예산안(에이전트) | |
| `hyperscaler_capex` | **Sharadar SF1 에서 직접 계산** | MSFT+GOOGL+AMZN+META+ORCL 의 capex 합 YoY. AI 사이클의 실측 드라이버 |
| `policy_events` | 에이전트 | IRA·관세·수출통제·원전 승인 등 이벤트 캘린더 |

> `hyperscaler_capex` 는 이 저장소가 Sharadar 를 갖고 있어서 가능한 항목이다.
> `grid_equipment` · `utility_ipp` · `datacenter_hw` · `networking_optical` 의 상류다.

**시차의 방향을 분명히 한다: 뉴스(가이던스·발표)가 빠르고, 재무제표가 정확하다.**
분기 재무제표는 분기말 후 4~8주 뒤에 나온다. 그 사이 하류 테마의 가격은 이미 움직여 있으므로
재무제표 합산을 **선행지표로 쓰면 시차 손실이 크다.** 정확도를 얻는 대신 시점을 잃는 것이다.

따라서 두 소스의 역할을 나눈다.

| 소스 | 역할 | 무엇을 주는가 | 누가 수집 |
|---|---|---|---|
| Sharadar SF1 5사 capex 합 | **검증·확정** | 수준과 추세의 진실. 개정되지 않는 확정치 | L0 (결정론) |
| 발주처 capex 가이던스 | **시점** | 분기말 직후~실적발표 사이의 유일한 정보 | `catalyst_analyst` (`05-agent-research.md` §2 의 4항 "수요처의 투자 계획") |

- 드라이버 `state` 판정은 **재무제표 기준**으로 한다. 가이던스로 `state` 를 바꾸지 않는다 —
  가이던스는 개정되고, 그것에 맞춰 상태를 흔들면 선언이 아니라 뉴스 추종이 된다.
- 다만 **가이던스가 재무제표와 어긋나면 리포트에 표시한다.** 예: 재무제표 합은 YoY 둔화인데
  가이던스는 상향. 이 불일치 자체가 사람이 봐야 할 정보이며, 다음 분기 확정치가 판정한다.

## 3. 엣지 스키마

```yaml
- from: dollar_broad
  to: gold_miners
  sign: -1                      # 드라이버 상승 → 테마 하락
  lag_months: [0, 3]
  strength: strong              # strong | moderate | weak
  channel: >
    달러 표시 원자재 가격의 역수 관계 + 비미국 생산자의 원가는 현지통화라
    달러 약세 시 마진이 이중으로 확대된다
  evidence: "1971-1980, 2001-2011, 2019-2020, 2024-2026 국면에서 일관"
  observable: "DTWEXBGS 6개월 변화 < −2%"
  contradicts_when: >
    달러와 금이 동반 강세면 통화체계 신뢰 훼손(안전자산 동반 매수) 국면이다.
    이 엣지로 설명되지 않으므로 별도 논지가 필요하다 — 자동 점수 계산에서 제외 플래그
```

**필수 필드**: `from`, `to`, `sign`, `strength`, `channel`, `observable`.
`channel` 이 비면 스키마 검증 실패 — **메커니즘 없는 상관은 엣지가 아니다.**

## 4. 거시 순풍 점수

테마 `t` 에 대해:

```
tailwind(t) = Σ_{e ∈ in(t)} w(e.strength) · e.sign · state(e.from)
              ────────────────────────────────────────────────────
                          Σ_{e ∈ in(t)} w(e.strength)

w: strong=3, moderate=2, weak=1        state ∈ {−1, 0, +1}
```

값역 [−1, +1]. 최종 테마 순위는:

```
final(t) = 0.70 · cycle_score(t)  +  0.30 · normalize(tailwind(t))
```

> 0.70/0.30 은 **선언**이다. 근거: 사이클 상태(L1)는 테마 자체의 관측이고,
> 거시(L2)는 외생 조건이다. 외생 조건은 자주 뒤집히고 예측 정확도가 낮으므로 가중을 낮춘다.
> "거시가 좋아서 샀는데 산업이 여전히 공급 과잉" 은 실패하지만,
> "산업 공급이 파괴됐는데 거시가 아직 안 도와줌" 은 기다리면 되는 문제다.

**하드 규칙**: `tailwind(t) < −0.5` 면 L1 스코어와 무관하게 **후보에서 제외**한다.
거시가 정면으로 역풍인 테마는 사이클이 맞아도 시점이 이르다.

## 5. 국면 4분면 (Regime quadrant)

드라이버를 사람이 읽을 수 있는 요약으로 축약한다. 리포트 첫 장에 온다.

```
                  인플레 ↑
                     │
   ┌─────────────────┼─────────────────┐
   │  스태그플레이션   │   과열(리플레)    │
   │  금·은·에너지     │  구리·산업재·은행 │
   │  방산·필수소비    │  해운·화학·에너지 │
성장↓─────────────────┼─────────────────성장↑
   │   디플레 침체     │   골디락스        │
   │  장기국채·유틸    │  성장주·반도체    │
   │  대형제약        │  소비재·기술      │
   └─────────────────┼─────────────────┘
                     │
                  인플레 ↓
```

축 정의:
- **성장축**: `industrial_production` YoY 2계도함수, `new_orders_mfg`, `inventory_sales`(역), `employment` 의 z-score 평균
- **인플레축**: `cpi_yoy`, `breakeven_10y`, `ppi_yoy`, `oil_wti` 의 z-score 평균
- **신용축(3차원)**: `hy_spread` — 확대 시 어느 분면이든 위험자산을 눌러 **전체 스코어에 곱셈 페널티**

4분면은 설명 도구이고, 점수 계산은 §4 의 엣지 기반이다. **분면으로 테마를 고르지 않는다** —
분면은 너무 거칠어서 (예) 같은 "리플레" 안에서 구리와 은이 갈리는 이유를 못 담는다.

## 6. 모순 감사 (Contradiction audit)

> 여기가 데이터를 쓰는 **유일한** 지점이며, **가중치를 바꾸지 않는다.**

매 월간 스캔에서:

1. 각 엣지에 대해 `corr(Δdriver, Δtheme_return)` 을 36개월·60개월 창으로 계산
2. 부호가 선언과 **반대**이고 |corr| > 0.3 이면 → `CONTRADICTED` 플래그
3. |corr| < 0.1 이면 → `NO_SIGNAL` 플래그
4. 플래그된 엣지는 **리포트에 뜨고, 사람이 검토한다.** 자동 조정은 없다

검토 후 가능한 조치는 셋뿐:
- **엣지 수정** — 왜 틀렸는지를 `channel` 에 반영하고 커밋에 근거를 남긴다
- **국면 조건 추가** — "이 엣지는 신용 스프레드 축소 국면에서만 성립" 같은 조건부 엣지
- **유지** — 표본 부족이라 판단. 그 판단의 이유를 문서에 남긴다

이 절차가 "학습" 과 다른 점: **변경이 사람의 서술을 거치고, 커밋에 흔적이 남고,
성과가 좋아지는 방향인지를 보지 않는다.** 성과를 보는 순간 그게 오버피팅이다.

## 7. DAG 초기 엣지 (발췌)

전체는 `specs/macro-dag.example.yaml`. 여기서는 밀도가 높은 부분만.

| from | to | sign | strength | 채널 요약 |
|---|---|---|---|---|
| `dollar_broad` | 모든 `commodity_supply` | −1 | strong | 달러 표시 가격 + 현지통화 원가 |
| `real_rate_10y` | `gold_miners`, `silver_miners` | −1 | strong | 무이자 자산의 기회비용 |
| `real_rate_10y` | `biotech_clinical` | −1 | strong | 장기 현금흐름 할인 + 자금조달 창구 |
| `real_rate_10y` | `homebuilders`, `reit_*` | −1 | strong | 모기지·캡레이트 |
| `term_spread` | `banks_regional`, `banks_large` | +1 | strong | 순이자마진 |
| `hy_spread` | `oil_gas_ep`, `biotech_clinical`, `shipping_*` | −1 | strong | 고레버리지 재융자 |
| `china_credit_impulse` | `copper_miners`, `steel_iron`, `shipping_drybulk` | +1 | strong | 중국 고정자산투자가 한계 수요 |
| `inventory_sales` | `semi_*`, `industrial_automation`, `trucking_logistics` | −1 | strong | 재고 소진 → 재주문 |
| `hyperscaler_capex` | `grid_equipment`, `datacenter_hw`, `networking_optical`, `utility_ipp` | +1 | strong | 발주처 capex 가 직접 매출 |
| `defense_outlays` | `defense`, `aerospace_commercial`, `rare_earth` | +1 | strong | 예산 집행 → 수주 |
| `capex_orders_core` | `construction_machinery`, `epc_engineering`, `industrial_automation` | +1 | moderate | 기업 투자 사이클 |
| `oil_wti` | `oil_services`, `offshore_drilling` | +1 | strong | 발주처 예산 |
| `oil_wti` | `airlines`, `trucking_logistics`, `refiners`(복잡) | −1 | moderate | 연료비. 정유는 크랙스프레드라 부호가 단순치 않음 |
| `housing_starts` | `lumber_paper`, `home_improvement`, `cement_aggregates` | +1 | strong | |
| `usd_liquidity` | 전 테마 (공통 인자) | +1 | moderate | 위험 선호 전반 — 테마 선택엔 무력, 시점엔 유효 |

> 마지막 줄이 중요하다. **공통 인자는 테마를 고르는 데 쓸모없다** (전부에 같은 부호).
> `tailwind` 계산에서 공통 인자는 **횡단면 중앙값을 빼고** 사용한다 — 상대 순풍만 남긴다.
