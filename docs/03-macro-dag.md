# 03 · 거시 인과 DAG (L2)

> ## **제거됨 (2026-08-23, 설계 질문 2 → C)**
>
> 이 계층은 **더 이상 파이프라인에 없다.** `docs/13-design-question-l2-macro.md` 가 세운
> 설계 질문 2 — "거시로 테마를 골라도 되는가" — 에 대한 답은 **아니다** 였다: 거시 기반 선택의
> 표본외 예측력이 약하고(`docs/13` §4~§6), 같은 날 채택했던 B 안(순위에서 빼고 오버레이만,
> 58c006a)도 남길 만한 입력이 없었다. 그래서 C 안 — **계층 자체를 뺀다** — 를 택했다.
> 결정 기록: `docs/13` §9 · `journal/2026-08-23-l2-removed.md`.
>
> | 무엇 | 어디로 |
> |---|---|
> | `src/msa/l2/*` · `msa macro` · `msa run monthly` 의 macro 단계 · 선정 `hard_exclude` 오버레이 | 삭제 |
> | L3 확신도의 거시 순풍 항(+0.10) · `MacroState` · 저널 진입 항목 `l2_tailwind` · L5 `tailwind` | 삭제 (`docs/04` §4 · `docs/09` §2 · `docs/07`) |
> | `state/macro-dag.yaml` · `specs/macro-dag.example.yaml` · `scripts/audit_dag.py` · `macro-dag-audit.md` · `macro-dag-sign-check.md` | `docs/archive/` (기록) |
> | FRED 어댑터 | **남는다** — L1 축 1 실물 참조(`physical_ref.source == fred`)와 CPI 만 (`docs/08` §3) |
>
> **되살리는 길은 revert 가 아니다.** 새 설계 질문을 세우고(`docs/12`·`docs/13` 의 꼴), 무엇을
> 재면 "거시가 일한다" 고 할지 **사전 등록**한 뒤에만 돌아온다. 아래 본문은 그때의 출발점이
> 되도록 **원문 그대로** 남긴다 — 현행 명세가 아니라 역사 기록이다.

---


## 1. 왜 회귀가 아니라 선언인가

드라이버 26개(§2) × 테마 134개(`state/themes.yaml` 확정 기준) = **3,484개 잠재 엣지**.
여기에 시차까지 탐색하면 수만 개다.
이걸 데이터로 학습하면 무엇이 나오는가 — 우연한 상관의 최대치가 나온다.
표본은 사이클 2~3바퀴뿐이므로 검증도 불가능하다.
**탐색 공간이 넓을수록 이 논지는 강해진다** — 표본은 그대로인데 후보만 늘면
우연히 유의해 보이는 엣지의 수도 함께 늘기 때문이다. `portfolio-research` 가 DSR·PBO 로
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
| `cpi_yoy` | FRED `CPIAUCSL` | 실질화 계산에도 사용 |
| `ppi_yoy` | FRED `PPIACO` | 실질화 계산에도 사용 |
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

값역 [−1, +1].

### 4.1 거시는 순위에 들어가지 않는다 — 2026-08-23 개정 (설계 질문 2, `docs/13`)

이전 판은 `final(t) = 0.70 · cycle_score(t) + 0.30 · normalize(tailwind(t))` 를 선언했다. 그 선언은
**코드에 배선된 적이 없고**(선별은 처음부터 L1 스코어보드만 썼다), 근거 문장 자신이 — "외생 조건은
자주 뒤집히고 예측 정확도가 낮으므로 가중을 낮춘다 … 산업 공급이 파괴됐는데 거시가 아직 안 도와줌은
기다리면 되는 문제다" — 거시를 **선별 기준이 아니라 조건**으로 보고 있었다. `docs/13-design-question-l2-macro.md`
가 내부 사실(3/26 드라이버, 부호 검정 불가)과 외부 증거(거시 기반 섹터 로테이션의 표본 외 예측력은 약하고,
산업 수준의 사이클·자본 사이클 신호는 거시와 독립적으로 작동한다는 문헌)를 모았고, 사용자가 **B안**을
결정했다:

| 남기는 것 (오버레이) | 빼는 것 |
|---|---|
| **하드 규칙**: `tailwind(t) < −0.5` 이고 가중치 커버리지 ≥ 0.5 이면 후보에서 제외 — 제외한 테마와 수를 리포트에 적는다 (`msa run monthly` 의 select 단계, `src/msa/pipeline/run.py`) | `final(t)` 의 0.30 가중 — **순위에 거시를 더하지 않는다** |
| 모순 감사 (§6) · 국면 4분면과 `credit_stress` 플래그 (§5) · 엣지 부호 일치율 실측 (§8, `msa macro`) | — |
| L3 컨텍스트: `state/macro/latest.json` 의 tailwind 가 thesis 의 `inputs.macro_tailwind` 로 들어가고 `docs/04` §4 의 확신도 규칙(+0.10, tailwind > 0.3)에 쓰인다 | — |

> 이 개정은 "거시가 쓸모없다" 가 아니다. **거시가 어느 테마를 고를지는 말해 주지 못하고, 어느 테마를
> 지금은 건드리지 말아야 하는지(역풍·신용 스트레스)와 논지의 모순은 말해 줄 수 있다** 는 자리 재배치다.
> 드라이버 데이터(FRED)가 들어온 뒤 `docs/13` §5 의 사전 등록된 증분 검정이 "거시를 순위에 다시 넣을
> 이유가 있는가" 를 답한다 — 그 전까지 가중은 0 이고, 그 후에도 값을 데이터에 맞춰 고르지 않는다.

## 5. 국면 4분면 (Regime quadrant)

드라이버를 사람이 읽을 수 있는 요약으로 축약한다. 리포트 첫 장에 온다.

```
                   인플레 ↑
                       │
   ┌───────────────────┼───────────────────┐
   │  스태그플레이션   │   과열(리플레)    │
   │  금·은·에너지     │  구리·산업재·은행 │
   │  방산·필수소비    │  해운·화학·에너지 │
성장↓──────────────────┼───────────────────성장↑
   │   디플레 침체     │   골디락스        │
   │  장기국채·유틸    │  성장주·반도체    │
   │  대형제약         │  소비재·기술      │
   └───────────────────┼───────────────────┘
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

## 7. DAG 엣지 (발췌)

전체는 `state/macro-dag.yaml` (스키마 예시는 `specs/macro-dag.example.yaml`).
감사 결과는 `macro-dag-audit.md`.

**현황** (134 버킷 기준, M4-134 재감사) — 드라이버 26개 · 엣지 레코드 86개(개별 83 + 공통 인자 3) ·
**테마-엣지 쌍 451개** (공통 인자 제외, 하한 268 = 2 × 134).
테마 in-degree **min 2 · median 3 · max 6**. 입력 엣지 2개를 못 채운 테마는 **없다.**
강도 분포 strong 22 · moderate 37 · weak 27, 부호 +1 47 · −1 39,
`contradicts_when` 을 가진 엣지 26개.

> 테마 id 의 정본은 `state/themes.yaml` 이다. 위 수치는 M2 확정 버킷 134개 기준이다.
> 초안 109개 기준(엣지 72 · 쌍 380)에서 확정 버킷으로 재감사하자 폐기 id 6개와 신설 버킷
> 31개 때문에 22건이 실패했고, 재매핑과 엣지 14개 추가로 해소했다 — 내역은
> `macro-dag-audit.md` §10. 기존 엣지의 부호·강도·채널은 그 과정에서 바꾸지 않았다.

밀도가 높은 부분과 부호가 갈리는 부분만 옮긴다.

| from | to | sign | strength | 채널 요약 |
|---|---|---|---|---|
| `dollar_broad` | 광물 11종 (`gold_miners`…`fertilizer_potash`) | −1 | strong | 달러 표시 가격 + 현지통화 원가의 이중 확대 |
| `dollar_broad` | `apparel_footwear` | **+1** | weak | 매출은 달러·소싱 원가는 아시아 — 소비재와 부호 반대 |
| `real_rate_10y` | `gold_miners`, `silver_miners`, `pgm_miners` | −1 | strong | 무이자 자산의 캐리 코스트 |
| `real_rate_10y` | `biotech_clinical` | −1 | strong | 원거리 현금흐름 할인 + 2차 발행 창구 |
| `real_rate_10y` | REIT 10종 (`reit_office`…`reit_specialty`) | −1 | strong | 캡레이트 = 실질금리 + 리스크 프리미엄. `reit_mortgage` 는 캡레이트가 아니라 듀레이션 경로라 별도 엣지(moderate) |
| `real_rate_10y` | 프로젝트 파이낸싱 9종 (`solar`…`lng`) | −1 | strong | 자본비용이 곧 LCOE — 밸류가 아니라 발주 물량이 준다 |
| `real_rate_10y` | 보험 4종 (`insurance_pc`, `insurance_life`, `reinsurance`, `insurance_diversified`) | **+1** | moderate | 플로트 재투자 수익 — 차입자가 아니라 대여자다 |
| `real_rate_10y` | `banks_regional` | −1 | moderate | AFS 평가손 → 자본. `term_spread` 엣지와 부호 충돌(국면 의존) |
| `term_spread` | `banks_large`, `banks_regional`, `reit_mortgage` | +1 | strong | 만기 변환 마진 (모기지 리츠는 레포 조달 → MBS 보유, 가장 순수한 형태) |
| `hy_spread` | 고레버리지 9종 (`oil_gas_ep`…`biotech_clinical`) | −1 | strong | 리파이낸싱 가능 여부가 생존 조건 |
| `ig_spread` | 규제·대형 11종 (`utility_regulated`…`reit_specialty`) | −1 | moderate | 요금기저 투자의 자본비용은 IG 시장에서 온다 |
| `china_credit_impulse` | 기저금속·벌크 10종 | +1 | strong | 중국 고정자산투자가 한계 수요 |
| `china_property` | `steel_iron`, `copper_miners`, `shipping_drybulk` 등 | +1 | strong | 착공 면적이 실제 물량 (신용은 자금 조건) |
| `inventory_sales` | `semi_devices`, `semi_equipment`, `industrial_automation`, `industrial_distribution`, `railroads` 등 7종 | −1 | strong | 재고 소진 → 재주문 |
| `hyperscaler_capex` | `grid_equipment`, `datacenter_hw`, `semi_devices`, `semi_equipment` 등 7종 | +1 | strong | 발주처 capex 가 직접 매출 |
| `hyperscaler_capex` | `epc_engineering`, `hvac_building`, `nuclear_smr` 등 8종 | +1 | moderate | 데이터센터 건설의 2차 수혜 |
| `defense_outlays` | `defense`, `shipbuilding`, `space_satellite` | +1 | strong | 예산 → 계약 → 수주잔고 (CR 구간은 발동 안 함). 상용항공은 `defense` 에 병합됨 |
| `capex_orders_core` | `construction_machinery`, `epc_engineering`, `instruments_test`, `rental_leasing` 등 13종 | +1 | moderate | 기업 투자 사이클 |
| `oil_wti` | `oil_gas_ep`, `oil_services`, `shipbuilding` 등 | +1 | strong | 매출 = 유가, 하류는 발주처 예산 |
| `oil_wti` | `airlines`, `trucking_logistics`, `cruise_lines` 등 | −1 | moderate | 연료비 20~35% |
| `oil_wti` | `refiners` | −1 | **weak** | 손익은 크랙 스프레드다 — 유가는 대리 변수일 뿐 |
| `nat_gas` | `oil_gas_ep`, `midstream`, `utility_ipp`, `coal` | +1 | strong | 판가·처리량·도매전력가·급전 대체 |
| `nat_gas` | `fertilizer_potash`, `commodity_chem`, `aluminum`, `lng` 등 6종 | **−1** | moderate | 같은 드라이버가 여기서는 원가다 |
| `housing_starts` | `lumber_paper`, `cement_aggregates`, `home_furnishings` 등 9종 | +1 | strong | 착공이 자재 물량을 정의 |
| `housing_starts` | `reit_residential` | **−1** | moderate | 착공은 임대 시장의 신규 **공급**이다 |
| `employment` | 재량소비 28종 | +1 | strong | 임금 소득 총액 = 재량 지출 능력 |
| `employment` | `education` | **−1** | moderate | 영리 교육 등록은 실업의 기회비용 함수 — 역경기 |
| `employment` | `retail_discount`, `food_retail_distribution` | +1 | **weak** | 필수 소비는 방어적 + 침체기 트레이드다운이 상쇄 |
| `employment` | `hospitals_providers`, `managed_care`, `medtech_devices` | +1 | moderate | 미국 의료보험은 고용주 기반 |
| `cpi_yoy` | 유통·재량 12종 | −1 | moderate | 필수 지출이 실질 가처분소득을 잠식 |
| `cpi_yoy` | `retail_discount`, `food_retail_distribution` | **+1** | weak | 필수품 명목 매출 + 트레이드다운 점유율 — 재량 유통과 부호 반대 |
| `cpi_yoy` | `waste_services`, `fintech_payments`, `advertising` | **+1** | weak | 매출이 명목 금액에 연동 |
| `ppi_yoy` | `insurance_pc`, `reinsurance`, `insurance_diversified` | −1 | moderate | 수리·재건축비가 곧 손해액 |
| `ppi_yoy` | `insurance_brokers` | **+1** | moderate | 손해액 인플레 → 요율 인상 → 보험료 정률 수수료. 인수 리스크 없이 손보와 부호 반대 |
| `policy_events` | 정책 수요 11종 (`solar`…`lithium`) | +1 | strong | 수요 자체가 정책으로 만들어진다 |
| `policy_events` | 규제 리스크 10종 (`coal`…`casinos_gaming`) | **−1** | moderate | 규제가 물량·판가의 상한을 정한다 |
| `usd_liquidity` · `fed_policy_path` · `m2_growth` | 전 테마 (공통 인자) | +1 / −1 / +1 | moderate·moderate·weak | 위험 선호·할인율 기준선·명목 성분 |

> 마지막 줄이 중요하다. **공통 인자는 테마를 고르는 데 쓸모없다** (전부에 같은 부호).
> `tailwind` 계산에서 공통 인자는 **횡단면 중앙값을 빼고** 사용한다 — 상대 순풍만 남긴다.
> 세 드라이버는 테마의 "입력 엣지 최소 2개" 하한 계산에서도 제외된다.

**부호가 갈리는 드라이버가 이 표의 핵심이다.** `nat_gas` 는 생산자에겐 매출이고
화학·제련엔 원가다. `real_rate_10y` 는 차입자에겐 비용이고 보험사에겐 수익이다.
`housing_starts` 는 자재엔 수요이고 주거 리츠엔 공급이다. `cpi_yoy` 는 소비자에겐
구매력 잠식이고 정률 과금 사업엔 매출이다. `ppi_yoy` 는 손보사엔 손해액이고 보험 중개사엔
수수료다. `employment` 는 소비재엔 소득이고 영리 교육엔 기회비용이다. 이런 분기를 담을 수 없다는 것이
§5 의 4분면을 점수 계산에 쓰지 않는 이유이며, 회귀 한 벌로 부호를 뽑을 수 없는 이유다.

**집중도 경고**: `real_rate_10y` 하나에 테마-엣지 쌍 64개(전체의 14%)가 걸려 있고,
`employment` 에 50개(11%)가 걸려 있다.
공통 인자로 돌리지 않은 이유는 보험 4종(실질금리)·영리 교육(고용)에서 부호가 갈리기 때문이지만, 실질금리가
한 방향으로 움직이면 tailwind 가 광범위하게 같은 방향으로 밀린다는 사실은
리포트에 표기한다 (`macro-dag-audit.md` §5).

## 8. 구현 노트 (M4 런타임 — `src/msa/l2/`, `msa macro`)

위 §2~§7 이 못 박지 않은 것을 런타임이 어떻게 정했는지의 기록이다. 전부 **선언**이며 데이터로
정하지 않았다. 바꾸려면 근거를 여기와 커밋에 적는다.

### 8.1 `state` 는 값의 방향이다

`state/macro-dag.yaml` 의 부호 규약("sign = +1 은 드라이버 값 상승 → 테마 우호")과 §4 의
`sign × state` 가 함께 성립하려면 `state` 는 **측정값의 방향**이어야 한다:
측정값 > `neutral_band` 상한 → +1, < 하한 → −1, 안 → 0. `favorable_when` 은 리포트의 `favorable`
열(표시용)에만 쓴다. 예: 실질금리 6개월 −40bp → state −1(favorable Y), `real_rate_10y → gold_miners
(sign −1)` 기여 = (−1)(−1) = +1. `neutral_band` 가 없는 드라이버는 임계값 하나가 경계다.

### 8.2 측정값·z 창·발표 지연 — `msa.l2.drivers` 모듈 docstring 의 표가 정본

- `yoy_second_derivative` = yoy 의 **3개월 보폭** 2계 차분 (월 보폭은 잡음이 개정폭보다 크다).
- `composite_z`(employment) = (z(PAYEMS 월간 증가분 3M 평균) − z(UNRATE 6M 변화)) / 2,
  z 창 **120개월·최소 60** (L1 의 자기이력 창과 같다).
- 발표 지연은 `PUB_LAG` 에 시리즈별로 선언돼 있다 (일간 0일 · DTWEXBGS/WALCL/WTREGEN 7일 · 월간
  대부분 +1개월 · AMTMNO/ISRATIO +2개월 · FDEFX 분기말 +1개월). **`docs/08` §3 의 실측이 없어서**
  발표 일정에서 온 값이며, `msa data fred-fetch` 뒤 `msa data fred-lag` 로 실측되면 그 값으로 **대체**한다.
  월말 격자 T 에서는 T 까지 발표된 관측만 쓴다. 선언되지 않은 시리즈는 예외다.
- FRED 캐시는 최신 개정치다 (ALFRED 아님). 오늘의 판정에는 무관, 과거 상관(8.6)에는 한계로 적는다.
- 기준일은 **마지막 월말**이다 (8/23 실행 → 7/31). 그 달이 끝나야 월말 값이 있다.

### 8.3 tailwind 의 분모와 공통 인자 차감

- 분모는 **가용 엣지의 가중치 합**이다. 드라이버가 없는 엣지는 분자·분모에서 빠지고 `n_edges_missing`·
  `weight_coverage` 로 보고된다 (전체 가중치로 나누면 결측이 "중립" 으로 둔갑한다).
- 공통 인자 기여 `cf(t) = Σ w·sign·state / W_avail(t)` 는 분자가 전 테마에 같아도 분모가 달라 테마마다
  다르다. 그 **테마별 기여분의 횡단면 중앙값**을 빼고 더한다 (`tailwind`), 차감 전 값은 `tailwind_raw`.
- 하드 규칙 `tailwind < −0.5` 는 `hard_exclude` **플래그**만 세우고, `weight_coverage ≥ 0.5` 일 때만
  선다 (엣지 하나로 제외하면 결측이 판정이 된다). 실제 제외는 `final(t)` 를 만드는 단계(M5 이후)의 일.
- `policy_events` 는 테마별이다. `state/physical/manual/policy_events.csv` 의 `effect` 가 **해당 테마에**
  유리(+1)/불리(−1)이고, `state := sign × effect` 라 `sign × state = effect`. 창 12개월, `confirmed=Y` 만.

### 8.4 4분면 — 축 구성과 신용 페널티

성장축·인플레축은 §5 의 드라이버 측정값을 각각 z(120개월) 한 뒤 평균 (employment 는 이미 z).
**구성 드라이버 2개 이상**이 있어야 축을 내고 `n_growth`·`n_inflation` 을 매 행에 적는다.
`hy_spread` 상태 +1(확대) 이면 `credit_stress`, 페널티 계수 **0.5 를 선언**만 한다 — 적용은
`final(t)` 단계. 출력은 ASCII 차트(`regime.txt`) + 최근 24개월 CSV (`regime.csv`). PNG 없음 (matplotlib 미의존).

### 8.5 `contradicts_when` 은 서술이다

기계가 읽는 것은 선택 필드 `contradicts_rule` (`all_of`/`any_of` 의 드라이버 상태 조건) 뿐이다.
서술이 순수 드라이버 상태 조건인 엣지 2개(달러·금 동반 강세, 실질금리 상승 동반)에만 규칙을 달았고
나머지(134 버킷 재감사 후 24개)는 `PROSE_ONLY` 로 표에 올라 사람이 읽는다. `FLAGGED` 는 플래그까지다 — 자동 제외 없음.

### 8.6 엣지 부호 일치율 실측 (`docs/macro-dag-sign-check.md`)

x = 드라이버 측정값(as-of), y = 테마 EW 지수(L1 패널 캐시)의 **전방 12개월 초과수익**(vs SPY).
엣지가 `lag_months` 로 선행을 선언했으므로 전방 수익을 쓴다. 36·60개월 롤링 상관의 부호 일치 비율과
창 수를 세며 **검정이 아니다** (전방수익 중첩). 플래그는 최신 창 기준 §6 의 0.3/0.1. 결과 문서는
`uv run msa macro --doc-out docs/macro-dag-sign-check.md` 가 만든다.

### 8.7 데이터 소스와 오늘의 가용성

| provider | 경로 | 2026-08 현재 |
|---|---|---|
| `fred` | `state/physical/fred/<SYM>.csv` (L1 과 공유). `msa data fred-fetch` 가 24종+physical_ref+CPI 를 받는다 | **없음** — `FRED_API_KEY` 미설정, 캐시 없음 |
| `derived` (`usd_liquidity`) | 위 캐시 3종. 단위는 `<SYM>.meta.json` 과 대조 (RRP 십억→백만) | 없음 |
| `etf` (`gold_price` GLD·IAU, `copper_price` 폴백 CPER) | 벌크 `funds.csv.zip` | 있음 |
| `manual` (`china_credit_impulse`·`china_property`) | `state/physical/manual/<id>.csv` (`date,value[,available]`) | 없음 |
| `agent` (`policy_events`) | `state/physical/manual/policy_events.csv` | 없음 |
| `sharadar_derived` (`hyperscaler_capex`) | DuckDB SF1 ARQ `capex`, datekey as-of, 5사 동시 가용 월만 | 있음 |

`msa macro` 는 없는 것을 **이름으로** 적는다 (`drivers.csv` 의 `missing_series`, 리포트의 결측 목록).
