# 01 · 테마 유니버스 — 분석 단위의 정의

## 1. 3중 정의

한 테마 버킷은 세 가지 방법으로 동시에 정의되고, 셋은 서로를 검증한다.

```
① industry 매칭   Sharadar TICKERS.industry 부분일치 → 자동 구성원 수집
        ↓ (자동은 항상 부정확하다)
② 큐레이션        include_tickers / exclude_tickers 로 손으로 교정
        ↓ (구성원이 확정되면)
③ ETF 프록시      지수 프록시. 장기 이력·유동성·외부 검증용
```

**왜 셋 다 필요한가**

- ①만 쓰면 — Sharadar 에 "희토류" industry 는 없다. `Other Industrial Metals & Mining` 안에
  MP · LYSDY · TMC 가 섞여 있고 자동으로는 분리 불가.
- ②만 쓰면 — 큐레이션 목록은 **생존 편향**이 든다. 오늘 아는 티커만 들어가고,
  폐지·합병된 과거 구성원이 빠져 자기이력 백분위가 낙관 방향으로 왜곡된다.
  → 규약: **큐레이션은 `industry` 자동 목록의 부분집합 조정만 한다.**
     `include` 로 추가한 티커는 반드시 이유를 `notes` 에 남긴다.
- ③만 쓰면 — ETF 는 2010년대 이후에 상장된 것이 많아 **사이클 한 바퀴가 안 담긴다**
  (URA 2010, REMX 2010, SIL 2010, LIT 2010). 그리고 ETF 는 구성종목 브레드스를 안 준다 —
  이 저장소가 ETF만 보는 사람 대비 갖는 우위가 바로 브레드스다(`02-cycle-state.md` §C).

**세 정의의 불일치는 신호다.** ETF 프록시 수익률과 자체 구성 동일가중 지수의
12개월 상관이 0.85 미만이면 버킷 정의가 잘못됐다는 뜻 → 감사에서 플래그.

## 2. 버킷 레코드 스키마

```yaml
- id: silver_miners                    # 스네이크케이스, 영구 불변 (저널이 이걸로 참조)
  name_ko: 은광
  parent_sector: Basic Materials       # Sharadar/Morningstar 11섹터
  cycle_class: commodity_supply        # §4 참조 — L1 가중치와 L2 드라이버를 결정
  industry_match: ["Silver"]           # TICKERS.industry 부분일치 (OR)
  include_tickers: []                  # 큐레이션 추가 — 이유 필수
  exclude_tickers: []                  # 큐레이션 제외 — 이유 필수
  etf_proxy: SIL                       # 1차 지수 프록시
  etf_proxy_alt: [SILJ, SLVP]          # 검증용
  physical_ref: {source: etf, symbol: SLV}   # 실물/원자재 참조. 객체 또는 null (아래 규정)
  min_constituents: 5                  # 이하면 중앙값 통계 신뢰 불가 → 경고 표시
  notes: >
    은은 통화 수요와 산업 수요(태양광 페이스트)가 겹친다.
    금광과 상관 0.8 이상이므로 L5 유효 베팅 수 계산에서 같은 클러스터로 묶인다.
```

**`physical_ref` 는 스칼라가 아니라 객체다.** 형식은 `{source, symbol}` 이며 `source` 의
허용값은 `etf`(예: `SLV`) · `fred`(예: `PCOALAUUSDM`) · `manual`(예: `UXC_SPOT` — 수동 갱신)
셋이다. 시리즈 가용성이 불확실하면 `verify: true` 를 덧붙여 M2 실측 확인 대상으로 표시한다
(`specs/themes.example.yaml` 참조). 티커만 적는 스칼라 표기는 어느 소스에서 받는지를
잃어버리므로 쓰지 않는다.

> **`physical_ref: null` 은 "축 1 을 쓸 수 없다"는 뜻이다.** 이 필드가 `04-value-trap.md`
> 축 1 의 적용 가능 여부를 결정하는 스위치이며, `null` 이면 `axis1_available = false` 로
> 내려가 판별의 중심이 축 3(LLM 판정)으로 넘어간다. 그래서 값을 비워 두는 것 자체가 선언이다.

## 3. 버킷 목록 초안 (109개)

> 이 목록은 **출발점**이지 완성이 아니다. 구현 M2 에서 Sharadar `industry` 실측 분포와
> 대조해 확정한다. `cycle_class` 는 §4, ETF 는 대표 1개만 표기.

### Materials — 광업·소재 (14)
| id | 이름 | cycle_class | ETF |
|---|---|---|---|
| `gold_miners` | 금광 | commodity_supply | GDX |
| `silver_miners` | 은광 | commodity_supply | SIL |
| `pgm_miners` | 백금·팔라듐 | commodity_supply | (없음 — 자체구성) |
| `rare_earth` | 희토류·전략금속 | policy_program | REMX |
| `lithium` | 리튬 | commodity_supply | LIT |
| `uranium` | 우라늄 | commodity_supply | URA |
| `copper_miners` | 구리 | commodity_supply | COPX |
| `steel_iron` | 철강·철광석 | commodity_supply | SLX |
| `aluminum` | 알루미늄 | commodity_supply | (자체구성) |
| `nickel_cobalt` | 니켈·코발트 | commodity_supply | (자체구성) |
| `diversified_miners` | 종합광업 | commodity_supply | XME |
| `coal` | 석탄 (연료탄·제철용) | **secular_risk** | KOL/자체 |
| `fertilizer_potash` | 비료·칼륨 | commodity_supply | MOO |
| `lumber_paper` | 제지·목재 | commodity_supply | WOOD |

### Chemicals & Materials — 화학·소재 (5)
`specialty_chem` 특수화학 · `commodity_chem` 범용석유화학 (commodity_supply) ·
`industrial_gas` 산업가스 (secular_growth) · `coatings_adhesives` 도료·접착 ·
`cement_aggregates` 시멘트·골재 (capex_program, PAVE)

### Energy — 에너지 (7)
`oil_gas_ep` 셰일 E&P (commodity_supply, XOP) · `oil_services` 유전서비스 (OIH) ·
`offshore_drilling` 오프쇼어 드릴링 (**secular_risk**) · `refiners` 정유 (CRAK) ·
`midstream` 미드스트림 (AMLP) · `lng` LNG (자체) ·
`intl_majors` 국제 메이저 (XLE)

> 제철용 석탄(`coal_met`)은 별도 버킷이 아니다 — Materials 의 `coal`(연료탄·제철용) 로 통합됐고, 개수에서도 뺐다.

### Energy Transition — 전환 (6)
`solar` 태양광 (policy_program, TAN) · `wind` 풍력 (FAN) ·
`hydrogen_fuelcell` 수소·연료전지 (policy_program) · `energy_storage` ESS ·
`ev_charging` EV·충전 (discretionary_demand) · `nuclear_smr` 원자력·SMR (policy_program, NLR)

### Industrials — 산업재 (13)
`defense` 방산 (capex_program, ITA) · `aerospace_commercial` 상용항공기·부품 (capex_program) ·
`space_satellite` 우주·위성 (policy_program, ARKX) ·
`shipping_tanker` 탱커 (commodity_supply) · `shipping_drybulk` 벌크 (commodity_supply) ·
`shipping_container` 컨테이너 (commodity_supply) · `shipbuilding` 조선 (capex_program) ·
`railroads` 철도 (inventory) · `trucking_logistics` 트럭·물류 (inventory) ·
`airlines` 항공사 (discretionary_demand, JETS) ·
`construction_machinery` 건설기계 (capex_program) · `ag_machinery` 농기계 (commodity_supply) ·
`waste_services` 폐기물 (secular_growth)

### Electrical & Infrastructure — 전력·인프라 (5)
`grid_equipment` 변압기·전력기기 (**capex_program** — AI 데이터센터 전력 수요) ·
`hvac_building` HVAC·빌딩 (capex_program) · `industrial_automation` 산업자동화 (inventory) ·
`epc_engineering` EPC·엔지니어링 (capex_program) · `infra_construction` 인프라 건설 (policy_program, PAVE)

### Technology — 기술 (12)
`semi_equipment` 반도체 장비 (inventory, SOXX) · `semi_memory` 메모리 (inventory) ·
`semi_analog_power` 아날로그·파워 (inventory) · `semi_foundry_logic` 파운드리·로직 ·
`semi_eda_ip` EDA·IP (secular_growth) ·
`networking_optical` 네트워킹·광통신 (capex_program) ·
`datacenter_hw` 데이터센터 하드웨어 (capex_program) ·
`ems_pcb` EMS·기판 (inventory) · `cybersecurity` 사이버보안 (secular_growth, HACK) ·
`software_infra` 인프라 SaaS (secular_growth, IGV) · `software_vertical` 수직 SaaS ·
`internet_platform` 소비자 인터넷 (discretionary_demand)

### Healthcare — 헬스케어 (6)
`biotech_clinical` 임상단계 바이오텍 (**credit_rate** — 금리 민감, XBI) ·
`pharma_large` 대형 제약 (secular_growth) · `medtech_devices` 의료기기 ·
`life_science_tools` 생명과학 도구·CRO (inventory) ·
`hospitals_providers` 병원·의료서비스 (policy_program) ·
`managed_care` 관리의료 (policy_program)

### Financials — 금융 (8)
`banks_large` 대형은행 (credit_rate) · `banks_regional` 지역은행 (credit_rate, KRE) ·
`insurance_pc` 손해보험 (credit_rate) · `insurance_life` 생명보험 (credit_rate) ·
`reinsurance` 재보험 · `asset_managers_exchanges` 자산운용·거래소 ·
`consumer_finance` 소비자금융 (credit_rate) · `fintech_payments` 핀테크·결제 (discretionary_demand)

### Consumer — 소비재 (12)
`auto_oem` 자동차 OEM (discretionary_demand) · `auto_parts` 자동차 부품 ·
`homebuilders` 주택건설 (credit_rate, XHB) · `home_improvement` 주택개량 (credit_rate) ·
`retail_specialty` 전문소매 (discretionary_demand, XRT) · `retail_department` 백화점 (**secular_risk**) ·
`ecommerce` 이커머스 · `restaurants` 레스토랑 · `hotels_resorts` 호텔·리조트 ·
`cruise_lines` 크루즈 (discretionary_demand) · `casinos_gaming` 카지노 ·
`apparel_footwear` 의류·신발 (discretionary_demand)

### Consumer Defensive — 필수소비 (5)
`food_beverage` 식음료 · `tobacco` 담배 (**secular_risk**) · `alcohol` 주류 ·
`household_products` 가정용품 · `agribusiness` 애그리비즈니스 (commodity_supply)

### Communication & Media (5)
`telecom_carriers` 통신사 (credit_rate) · `cable_broadband` 케이블 (**secular_risk**) ·
`media_streaming` 미디어·스트리밍 · `advertising` 광고 (discretionary_demand) ·
`gaming_interactive` 게임 (discretionary_demand)

### Real Estate — REIT (7)
`reit_office` 오피스 (**secular_risk** + credit_rate) · `reit_retail` 리테일 ·
`reit_industrial` 산업·물류 (inventory) · `reit_residential` 주거 (credit_rate) ·
`reit_datacenter` 데이터센터 (capex_program) · `reit_towers` 통신타워 (credit_rate) ·
`reit_healthcare` 헬스케어 부동산

### Utilities — 유틸리티 (4)
`utility_regulated` 규제전력 (credit_rate) · `utility_ipp` IPP·발전 (**capex_program** — AI 전력) ·
`water_utility` 수도 · `gas_utility` 가스유틸

> 합계 109 (섹션 헤더 숫자의 합). `secular_risk` 표기(6개)는 **기본값이 사양 의심**이라는 뜻이며,
> `04-value-trap.md` 의 하드 게이트를 통과해야만 후보가 된다. 사양 낙인이 아니라
> **입증 책임의 전환**이다 — 담배와 케이블은 실제로 훌륭한 현금흐름 자산이었던 시기가 있다.

## 4. `cycle_class` — 사이클 유형 분류

사이클 유형이 다르면 **어떤 지표를 봐야 하는지가 다르다.** 이 분류가 L1 블록 가중치와
L2 드라이버 집합을 결정한다. (가중치 표는 `02-cycle-state.md` §7)

| class | 사이클의 엔진 | 결정적 지표 | 전형 |
|---|---|---|---|
| `commodity_supply` | **자본 사이클** — 저가격 → 투자 중단 → 공급 파괴 → 가격 스파이크 | capex/D&A, 자산성장률, 원가곡선 위치 | 광업·에너지·해운·범용화학 |
| `inventory` | 재고 사이클 — 과잉 축적 → 소진 → 재주문 | 재고/매출 비율, 리드타임, 수주잔고 | 반도체·산업재·유통 |
| `credit_rate` | 금리·신용 사이클 | 실질금리, 수익률 곡선, 신용 스프레드 | 은행·리츠·주택·임상 바이오텍 |
| `capex_program` | 특정 투자 프로그램의 다년 집행 | 수주잔고, 예산 집행률, 발주처 capex | 방산·전력망·인프라·데이터센터 |
| `policy_program` | 정책·규제가 수요를 만듦 | 법안 시점, 보조금 규모, 수출통제 | 신재생·희토류·원자력·의료수가 |
| `discretionary_demand` | 소비 사이클 | 실질소득, 고용, 소비자심리 | 항공·크루즈·소매·자동차 |
| `secular_growth` | **사이클이 아님** | 침투율 S커브, 성장 감속 여부 | SaaS·산업가스·폐기물 |
| `secular_risk` | **사이클 아님이 기본 가정** | 물량 추세, 대체 침투율 | 석탄·오피스·케이블·담배·백화점 |

> `secular_growth` 가 낙폭 상위에 뜨면 **가장 위험하다.** "성장주가 싸졌다" 는
> 사이클 논지가 아니라 밸류에이션 논지이며, 이 저장소의 논리 구조로 다룰 수 없다.
> L1 이 이 클래스에 낙폭 가중치를 낮게 준다(`02-cycle-state.md` §7).

## 5. 커버리지 감사 (`CLAUDE.md` §2 의 이 저장소 버전)

매 적재마다 실행. **하나라도 실패하면 스캔이 진행되지 않는다.**

| 검사 | 기준 | 실패 시 의미 |
|---|---|---|
| 미분류 시총 비율 | < 5% | 버킷 정의에 큰 구멍. 새 산업이 생겼거나 매칭 규칙이 깨짐 |
| 중복 소속 티커 | 0개 | 한 티커는 정확히 0 또는 1개 버킷. 중복은 L5 집중도 계산을 오염 |
| 구성원 < `min_constituents` 인 버킷 | 리포트에 경고 표기 | 중앙값 통계 신뢰 불가 — 스코어를 쓰되 신뢰도 하향 |
| ETF 프록시 vs 자체지수 12M 상관 | > 0.85 | 버킷 정의가 ETF 와 다른 것을 담고 있음 |
| 폐지 티커 포함 여부 | 자기이력 구간에 반드시 포함 | 빠지면 백분위가 낙관 방향으로 왜곡 (생존 편향) |
| 버킷별 시총 합계 추이 | 급변 시 로그 | 벤더 분류 변경 또는 매칭 규칙 회귀 |

> 특히 마지막에서 두 번째. `portfolio-research` 가 20,931 종목과 폐지 종목을 보존하는
> 이유가 정확히 여기 있다. **오늘 상장된 은광만으로 은광의 10년 밸류 백분위를 계산하면
> 파산한 고비용 생산자들이 빠져 "역사적으로 싸다" 는 결론이 자동으로 나온다.**

## 6. 열린 질문 (M2 에서 결정)

1. **테마 지수 가중** — 동일가중 vs 시총가중. 동일가중은 소형주 노이즈를, 시총가중은
   단일 종목 지배(예: `rare_earth` 의 MP)를 얻는다. 잠정: **동일가중 + 시총가중 병기**,
   둘의 괴리 자체를 브레드스 신호로 사용.
2. **다중 소속 처리** — 예: 알코아는 알루미늄 제련이자 종합광업. 현재 규약은 단일 소속이며
   1차 매출 기준. 매출 노출 비중(revenue exposure map)을 도입할지는 M2 이후로 미룬다.
3. **비미국 상장 노출** — ADR 은 포함(SBSW·LYSDY). 순수 해외 상장은 범위 밖.
4. **버킷 신설 절차** — 새 테마(예: 2030년의 무언가)가 생겼을 때 과거 이력을 어떻게 소급할지.
   잠정: 구성원의 개별 이력으로 지수를 소급 구성하되, 소급 구간은 리포트에 표시.
