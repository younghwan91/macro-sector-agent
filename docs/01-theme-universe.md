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

## 3. 버킷 목록 — 확정본 (134개)

> **이 절은 M2 실측으로 확정됐다.** 초안 109개를 Sharadar `industry` 152종의 실제 분포와
> 하나씩 대조한 결과이며, 정본은 `state/themes.yaml` 이다. 커버리지 감사 결과는
> `theme-coverage-audit.md`. 재현은 `uv run --with duckdb --with pyyaml python scripts/audit_themes.py`.
>
> **확정 버킷 수 134개.** 초안 109개에서 6개를 폐기하고 31개를 신설했다(§3.1).
> `ax1` 열은 `physical_ref` 유무 — 축 1(물량 추세)을 쓸 수 있는가다(45개 Y / 89개 –).
> `industry_match` 가 **(큐레이션 전용)** 인 버킷은 대응하는 Sharadar 라벨이 없어
> `include_tickers` 로만 구성했으며(21개), 사유는 각 버킷의 `notes` 에 있다.
>
> `secular_risk` 는 확정본에서 **9개**다(초안 6개) — `coal` · `offshore_drilling` ·
> `retail_department` · `alcohol` · `tobacco` · `cable_broadband` · `legacy_media` ·
> `reit_office` · `reit_retail`. **기본값이 사양 의심**이라는 뜻이며 `04-value-trap.md` 의
> 하드 게이트를 통과해야만 후보가 된다. 사양 낙인이 아니라 **입증 책임의 전환**이다 —
> 담배와 케이블은 실제로 훌륭한 현금흐름 자산이었던 시기가 있다.

### Basic Materials (19)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `gold_miners` | 금광 | commodity_supply | Gold | GDX | Y |
| `silver_miners` | 은광 | commodity_supply | Silver | SIL | Y |
| `pgm_miners` | 백금·팔라듐·기타 귀금속 | commodity_supply | Other Precious Metals & Mining | — | Y |
| `rare_earth` | 희토류·전략금속 | policy_program | **(큐레이션 전용)** | REMX | – |
| `lithium` | 리튬 | commodity_supply | **(큐레이션 전용)** | LIT | Y |
| `uranium` | 우라늄 | commodity_supply | Uranium | URA | Y |
| `copper_miners` | 구리 | commodity_supply | Copper | COPX | Y |
| `aluminum` | 알루미늄 | commodity_supply | Aluminum | — | Y |
| `steel_iron` | 철강·철광석 | commodity_supply | Steel | SLX | Y |
| `diversified_miners` | 종합광업 | commodity_supply | Other Industrial Metals & Mining · Industrial Metals & Minerals | XME | – |
| `coal` | 석탄 | secular_risk | Thermal Coal · Coking Coal | — | Y |
| `fertilizer_potash` | 비료·칼륨 | commodity_supply | Agricultural Inputs | MOO | Y |
| `lumber_paper` | 제지·목재 | commodity_supply | Lumber & Wood Production · Paper & Paper Products | WOOD | Y |
| `specialty_chem` | 특수화학 | inventory | Specialty Chemicals | XLB | – |
| `commodity_chem` | 범용석유화학 | commodity_supply | Chemicals | XLB | Y |
| `industrial_gas` | 산업가스 | secular_growth | **(큐레이션 전용)** | — | – |
| `coatings_adhesives` | 도료·접착 | inventory | **(큐레이션 전용)** | — | – |
| `cement_aggregates` | 시멘트·골재 | capex_program | Building Materials | PAVE | Y |
| `hvac_building` | HVAC·빌딩제품 | capex_program | Building Products & Equipment | — | – |

### Energy (7)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `oil_gas_ep` | 셰일 E&P | commodity_supply | Oil & Gas E&P | XOP | Y |
| `oil_services` | 유전서비스 | commodity_supply | Oil & Gas Equipment & Services | OIH | Y |
| `offshore_drilling` | 시추 (오프쇼어·육상) | secular_risk | Oil & Gas Drilling | — | Y |
| `refiners` | 정유 | commodity_supply | Oil & Gas Refining & Marketing | CRAK | Y |
| `midstream` | 미드스트림 | capex_program | Oil & Gas Midstream | AMLP | – |
| `lng` | LNG | capex_program | **(큐레이션 전용)** | — | Y |
| `intl_majors` | 국제 메이저 | commodity_supply | Oil & Gas Integrated | XLE | Y |

### Utilities (4)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `utility_regulated` | 규제전력 | credit_rate | Utilities - Regulated Electric · Utilities - Diversified | XLU | Y |
| `utility_ipp` | IPP·발전 (재생 포함) | capex_program | Utilities - Independent Power Producers · Utilities - Renewable | — | Y |
| `gas_utility` | 가스유틸 | credit_rate | Utilities - Regulated Gas | — | – |
| `water_utility` | 수도 | credit_rate | Utilities - Regulated Water | PHO | – |

### Industrials (26)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `wind` | 풍력 | policy_program | **(큐레이션 전용)** | FAN | Y |
| `hydrogen_fuelcell` | 수소·연료전지 | policy_program | **(큐레이션 전용)** | — | – |
| `energy_storage` | ESS·배터리 | policy_program | **(큐레이션 전용)** | — | Y |
| `nuclear_smr` | 원자력·SMR | policy_program | **(큐레이션 전용)** | NLR | – |
| `defense` | 방산·항공우주 | capex_program | Aerospace & Defense | ITA | – |
| `space_satellite` | 우주·위성 | policy_program | **(큐레이션 전용)** | ARKX | – |
| `shipping_tanker` | 탱커 | commodity_supply | **(큐레이션 전용)** | — | Y |
| `shipping_drybulk` | 벌크·기타 해운 | commodity_supply | Marine Shipping · Shipping & Ports | — | Y |
| `shipping_container` | 컨테이너 | commodity_supply | **(큐레이션 전용)** | — | Y |
| `shipbuilding` | 조선 | capex_program | **(큐레이션 전용)** | — | – |
| `railroads` | 철도 | inventory | Railroads | — | Y |
| `trucking_logistics` | 트럭·물류 | inventory | Trucking · Integrated Freight & Logistics | IYT | Y |
| `airlines` | 항공사·공항서비스 | discretionary_demand | Airlines · Airports & Air Services | JETS | Y |
| `construction_machinery` | 건설·농기계 | capex_program | Farm & Heavy Construction Machinery | — | – |
| `industrial_automation` | 산업자동화·특수기계 | inventory | Specialty Industrial Machinery | — | – |
| `grid_equipment` | 변압기·전력기기 | capex_program | Electrical Equipment & Parts | — | – |
| `epc_engineering` | EPC·엔지니어링 | capex_program | Engineering & Construction | — | – |
| `infra_construction` | 인프라 운영·건설 | policy_program | Infrastructure Operations | PAVE | – |
| `waste_services` | 폐기물·환경 | secular_growth | Waste Management · Pollution & Treatment Controls | EVX | – |
| `conglomerates` | 복합기업 | inventory | Conglomerates · Diversified Industrials | — | – |
| `industrial_distribution` | 산업재 유통 | inventory | Industrial Distribution | — | – |
| `rental_leasing` | 렌탈·리스 | capex_program | Rental & Leasing Services | — | – |
| `staffing_consulting` | 인력·컨설팅 | discretionary_demand | Staffing & Employment Services · Consulting Services | — | – |
| `business_services` | 기업서비스 | secular_growth | Specialty Business Services · Security & Protection Services · Business Equipment & Supplies | — | – |
| `metal_fabrication` | 금속가공·공구 | inventory | Metal Fabrication · Tools & Accessories | — | – |
| `travel_booking` | 여행 예약·플랫폼 | discretionary_demand | Travel Services | — | – |

### Technology (13)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `solar` | 태양광 | policy_program | Solar | TAN | Y |
| `semi_equipment` | 반도체 장비 | inventory | Semiconductor Equipment & Materials | SOXX | – |
| `semi_devices` | 반도체 (소자·로직·아날로그·메모리) | inventory | Semiconductors | SOXX | Y |
| `semi_eda_ip` | EDA·반도체 IP | secular_growth | **(큐레이션 전용)** | — | – |
| `networking_optical` | 네트워킹·광통신 | capex_program | Communication Equipment | — | – |
| `datacenter_hw` | 데이터센터 하드웨어 | capex_program | Computer Hardware · Computer Systems | — | – |
| `consumer_electronics` | 소비자 전자 | discretionary_demand | Consumer Electronics | — | – |
| `ems_pcb` | EMS·전자부품·유통 | inventory | Electronic Components · Electronics & Computer Distribution | — | – |
| `instruments_test` | 계측·시험장비 | capex_program | Scientific & Technical Instruments | — | – |
| `it_services` | IT 서비스 | secular_growth | Information Technology Services | — | – |
| `cybersecurity` | 사이버보안 | secular_growth | **(큐레이션 전용)** | HACK | – |
| `software_infra` | 인프라 SaaS | secular_growth | Software - Infrastructure | IGV | – |
| `software_vertical` | 응용·수직 SaaS | secular_growth | Software - Application | IGV | – |

### Healthcare (9)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `biotech_clinical` | 임상단계 바이오텍 | credit_rate | Biotechnology | XBI | – |
| `pharma_large` | 대형 제약 | secular_growth | Drug Manufacturers - General · Drug Manufacturers - Major | — | – |
| `pharma_generic` | 제네릭·스페셜티 제약 | policy_program | Drug Manufacturers - Specialty & Generic | — | – |
| `medtech_devices` | 의료기기 | secular_growth | Medical Devices · Medical Instruments & Supplies | IHI | – |
| `life_science_tools` | 생명과학 도구·CRO | inventory | Diagnostics & Research | — | – |
| `health_it` | 헬스케어 IT | secular_growth | Health Information Services | — | – |
| `hospitals_providers` | 병원·의료서비스 | policy_program | Medical Care Facilities | — | – |
| `medical_distribution` | 의약품 유통 | secular_growth | Medical Distribution | — | – |
| `managed_care` | 관리의료 | policy_program | Healthcare Plans | IHF | – |

### Financial Services (11)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `banks_large` | 대형은행 | credit_rate | Banks - Diversified | — | – |
| `banks_regional` | 지역은행 | credit_rate | Banks - Regional · Savings & Cooperative Banks | KRE | – |
| `insurance_pc` | 손해보험 | credit_rate | Insurance - Property & Casualty · Insurance - Specialty | KIE | – |
| `insurance_life` | 생명보험 | credit_rate | Insurance - Life | — | – |
| `insurance_diversified` | 종합보험·지주 | credit_rate | Insurance - Diversified | — | – |
| `reinsurance` | 재보험 | credit_rate | Insurance - Reinsurance | — | – |
| `insurance_brokers` | 보험중개 | secular_growth | Insurance Brokers | — | – |
| `asset_managers_exchanges` | 자산운용·거래소 | credit_rate | Asset Management · Capital Markets · Financial Data & Stock Exchanges · Financial Conglomerates | — | – |
| `consumer_finance` | 소비자금융 | credit_rate | Credit Services | — | – |
| `fintech_payments` | 핀테크·결제 | discretionary_demand | **(큐레이션 전용)** | — | – |
| `mortgage_finance` | 모기지 금융 | credit_rate | Mortgage Finance | — | – |

### Consumer Cyclical (18)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `ev_charging` | EV·충전 | policy_program | **(큐레이션 전용)** | — | – |
| `auto_oem` | 자동차 OEM | discretionary_demand | Auto Manufacturers | — | Y |
| `auto_parts` | 자동차 부품 | inventory | Auto Parts | — | Y |
| `auto_dealers` | 자동차 딜러 | discretionary_demand | Auto & Truck Dealerships | — | Y |
| `homebuilders` | 주택건설 | credit_rate | Residential Construction | XHB | Y |
| `home_improvement` | 주택개량 | credit_rate | Home Improvement Retail | — | Y |
| `retail_specialty` | 전문·의류 소매 | discretionary_demand | Specialty Retail · Apparel Retail | XRT | – |
| `retail_department` | 백화점 | secular_risk | Department Stores | — | Y |
| `ecommerce` | 이커머스 | discretionary_demand | Internet Retail | — | – |
| `restaurants` | 레스토랑 | discretionary_demand | Restaurants | — | – |
| `hotels_resorts` | 호텔·리조트 | discretionary_demand | Lodging | — | Y |
| `cruise_lines` | 크루즈 | discretionary_demand | **(큐레이션 전용)** | — | – |
| `casinos_gaming` | 카지노·갬블링 | discretionary_demand | Resorts & Casinos · Gambling | BJK | – |
| `apparel_footwear` | 의류·신발·명품 | discretionary_demand | Apparel Manufacturing · Footwear & Accessories · Luxury Goods · Textile Manufacturing | — | – |
| `leisure_products` | 레저용품·RV | discretionary_demand | Leisure · Recreational Vehicles | — | – |
| `home_furnishings` | 가구·가전 | credit_rate | Furnishings Fixtures & Appliances · Furnishings | — | – |
| `packaging` | 포장·용기 | inventory | Packaging & Containers | — | – |
| `consumer_services` | 소비자 서비스 | discretionary_demand | Personal Services | — | – |

### Consumer Defensive (8)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `retail_discount` | 할인점·대형마트 | discretionary_demand | Discount Stores | — | – |
| `food_beverage` | 식음료 | secular_growth | Packaged Foods · Confectioners · Beverages - Non-Alcoholic | PBJ | – |
| `alcohol` | 주류 | secular_risk | Beverages - Brewers · Beverages - Wineries & Distilleries | — | Y |
| `tobacco` | 담배 | secular_risk | Tobacco | — | Y |
| `household_products` | 가정용품 | secular_growth | Household & Personal Products | — | – |
| `agribusiness` | 애그리비즈니스 | commodity_supply | Farm Products | MOO | Y |
| `food_retail_distribution` | 식품 유통·소매 | secular_growth | Food Distribution · Grocery Stores · Pharmaceutical Retailers | — | – |
| `education` | 교육 | policy_program | Education & Training Services | — | – |

### Communication Services (7)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `telecom_carriers` | 통신사 | credit_rate | Telecom Services | — | – |
| `cable_broadband` | 케이블·유료방송 | secular_risk | **(큐레이션 전용)** | — | Y |
| `media_streaming` | 미디어·스트리밍 | secular_growth | Entertainment | — | – |
| `legacy_media` | 방송·출판 | secular_risk | Broadcasting · Publishing | — | – |
| `advertising` | 광고 | discretionary_demand | Advertising Agencies | — | – |
| `gaming_interactive` | 게임 | discretionary_demand | Electronic Gaming & Multimedia | — | – |
| `internet_platform` | 소비자 인터넷 | discretionary_demand | Internet Content & Information | — | – |

### Real Estate (12)

| id | 이름 | cycle_class | industry_match | ETF | ax1 |
|---|---|---|---|---|:-:|
| `reit_office` | 오피스 REIT | secular_risk | REIT - Office | — | Y |
| `reit_retail` | 리테일 REIT | secular_risk | REIT - Retail | — | – |
| `reit_industrial` | 산업·물류 REIT | inventory | REIT - Industrial | — | – |
| `reit_residential` | 주거 REIT | credit_rate | REIT - Residential | — | – |
| `reit_datacenter` | 데이터센터 REIT | capex_program | **(큐레이션 전용)** | — | – |
| `reit_towers` | 통신타워 REIT | credit_rate | **(큐레이션 전용)** | — | – |
| `reit_healthcare` | 헬스케어 REIT | credit_rate | REIT - Healthcare Facilities | — | – |
| `reit_hotel` | 호텔 REIT | discretionary_demand | REIT - Hotel & Motel | — | Y |
| `reit_diversified` | 종합 REIT | credit_rate | REIT - Diversified | — | – |
| `reit_mortgage` | 모기지 REIT | credit_rate | REIT - Mortgage | REM | – |
| `reit_specialty` | 특수 REIT (팀버·카지노·옥외광고) | credit_rate | REIT - Specialty | — | – |
| `real_estate_services` | 부동산 서비스·개발 | credit_rate | Real Estate Services · Real Estate - Development · Real Estate - Diversified | — | Y |

## 3.1 초안과 실측이 달랐던 지점

### (a) 폐기된 초안 id — 6개

라벨이 하나인데 초안이 여럿으로 나눠 뒀고, 손으로 나누면 큐레이션 목록이 곧 버킷의 정의가 되어
생존 편향을 낳는 경우다. 결정 저널이 옛 id 를 참조할 수 있으므로 대응을 여기 남긴다.

| 폐기된 초안 id | 흡수한 버킷 | 사유 |
|---|---|---|
| `aerospace_commercial` | `defense` | Sharadar 는 `Aerospace & Defense` 단일 라벨(212종목). 폐지 119종을 편향 없이 방산/상용으로 가를 방법이 없다 |
| `ag_machinery` | `construction_machinery` | `Farm & Heavy Construction Machinery` 단일 라벨. CAT·DE·CNH·AGCO 가 한 통에 있다 |
| `semi_memory` | `semi_devices` (신설) | `Semiconductors` 단일 라벨(285종목, 폐지 217). 세 초안 버킷을 하나로 합쳤고 어느 초안 id 도 나머지의 상위집합이 아니라 새 id 를 뒀다 |
| `semi_analog_power` | `semi_devices` (신설) | 좌동 |
| `semi_foundry_logic` | `semi_devices` (신설) | 좌동 |
| `nickel_cobalt` | `diversified_miners` | 니켈·코발트 라벨이 없고, 미국 상장 순수 니켈주는 큐레이션해도 `min_constituents` 를 못 채운다 |

`semi_devices` 통합의 대가는 크다 — 메모리 사이클(재고)과 아날로그 사이클(자동차·산업)이
한 지수 안에서 상쇄된다. §6-2 의 매출 노출 비중이 도입되면 가장 먼저 재분할할 버킷이다.

### (b) 신설 버킷 — 31개

초안 109개는 원자재·에너지·전환에 집중돼 있어, 시총이 큰 여러 산업에 대응 버킷이 없었다.
미분류로 두면 §5 의 첫 검사(미분류 시총 < 5%)가 깨진다. 신설 사유는 두 가지뿐이다 —
**(A) 초안에 없던 실제 라벨의 커버리지 확보**, **(B) 한 버킷에 넣으면 통계를 단일 종목이 삼킴**.

| 신설 id | 받은 `industry` 라벨 | 사유 |
|---|---|---|
| `semi_devices` | Semiconductors | A (위의 통합) |
| `consumer_electronics` | Consumer Electronics | A — 4.61조. AAPL |
| `it_services` | Information Technology Services | A — 677 B |
| `instruments_test` | Scientific & Technical Instruments | A — 318 B |
| `pharma_generic` | Drug Manufacturers - Specialty & Generic | A — 296 B. 약가 규제가 드라이버라 대형 제약과 사이클이 다름 |
| `health_it` | Health Information Services | A — 176 B |
| `medical_distribution` | Medical Distribution | A — 227 B |
| `insurance_diversified` | Insurance - Diversified | B — 1.28조. BRK 가 손보/생보 어느 쪽에 넣어도 그 버킷을 삼킴 |
| `insurance_brokers` | Insurance Brokers | A — 315 B. 인수 사이클이 아니라 수수료 사업 |
| `mortgage_finance` | Mortgage Finance | A — 65 B |
| `retail_discount` | Discount Stores | A — 1.49조. WMT·COST |
| `auto_dealers` | Auto & Truck Dealerships | A — 153 B |
| `travel_booking` | Travel Services | A — 352 B. 크루즈를 분리한 뒤의 잔여 |
| `leisure_products` | Leisure · Recreational Vehicles | A — 108 B |
| `home_furnishings` | Furnishings Fixtures & Appliances · Furnishings | A — 67 B |
| `packaging` | Packaging & Containers | A — 166 B |
| `consumer_services` | Personal Services | A — 51 B |
| `food_retail_distribution` | Food Distribution · Grocery Stores · Pharmaceutical Retailers | A — 149 B |
| `education` | Education & Training Services | A — 54 B. §4 의 중국 사교육 사례가 이 버킷 |
| `legacy_media` | Broadcasting · Publishing | A — 30 B. 초안은 `secular_risk` 자리를 케이블 하나로 대표시켰다 |
| `conglomerates` | Conglomerates · Diversified Industrials | A — 203 B |
| `industrial_distribution` | Industrial Distribution | A — 263 B |
| `rental_leasing` | Rental & Leasing Services | A — 221 B |
| `staffing_consulting` | Staffing & Employment Services · Consulting Services | A — 262 B |
| `business_services` | Specialty Business Services · Security & Protection · Business Equipment & Supplies | A — 373 B |
| `metal_fabrication` | Metal Fabrication · Tools & Accessories | A — 184 B |
| `reit_hotel` | REIT - Hotel & Motel | A — 43 B |
| `reit_diversified` | REIT - Diversified | A — 65 B |
| `reit_mortgage` | REIT - Mortgage | A — 67 B. 레버리지 채권 포트폴리오라 다른 REIT 와 사이클이 전혀 다름 |
| `reit_specialty` | REIT - Specialty | A — 106 B. 데이터센터·타워를 뺀 잔여(팀버·카지노·옥외광고) |
| `real_estate_services` | Real Estate Services · Development · Diversified | A — 152 B |

### (c) `industry_match` 정정 — 초안이 상상한 라벨이 실재하지 않았다

초안의 `industry_match` 는 추정으로 쓰였고, **상당수가 실제 Sharadar 라벨과 달랐다.**
없는 라벨을 적어 두면 그 버킷은 영원히 비어 있다. 주요 정정:

| 버킷 | 초안이 가정한 것 | 실제 라벨 |
|---|---|---|
| `oil_gas_ep` 외 에너지 6개 | 셰일 E&P·유전서비스… | `Oil & Gas E&P` · `Oil & Gas Equipment & Services` · `Oil & Gas Drilling` · `Oil & Gas Refining & Marketing` · `Oil & Gas Midstream` · `Oil & Gas Integrated` |
| `gold_miners` | Gold Miners | `Gold` |
| `commodity_chem` | 범용석유화학 | `Chemicals` (특수화학은 `Specialty Chemicals`) |
| `fertilizer_potash` | 비료·칼륨 | `Agricultural Inputs` |
| `cement_aggregates` | 시멘트·골재 | `Building Materials` (Basic Materials 섹터) |
| `homebuilders` | 주택건설 | `Residential Construction` |
| `life_science_tools` | 생명과학 도구·CRO | `Diagnostics & Research` |
| `managed_care` | 관리의료 | `Healthcare Plans` |
| `hospitals_providers` | 병원 | `Medical Care Facilities` |
| `banks_large` | 대형은행 | `Banks - Diversified` |
| `internet_platform` | 소비자 인터넷 | `Internet Content & Information` |
| `ecommerce` | 이커머스 | `Internet Retail` |
| `media_streaming` | 미디어·스트리밍 | `Entertainment` |
| `gaming_interactive` | 게임 | `Electronic Gaming & Multimedia` |
| `hotels_resorts` | 호텔·리조트 | `Lodging` |
| `agribusiness` | 애그리비즈니스 | `Farm Products` |
| `industrial_automation` | 산업자동화 | `Specialty Industrial Machinery` |
| `water_utility` | 수도 | `Utilities - Regulated Water` |

**섹터 배정 정정** — `uranium`·`coal` 은 Energy 가 아니라 **Basic Materials**,
`solar` 는 별도 그룹이 아니라 **Technology**, `travel_booking`(크루즈 포함 원 라벨)은
Consumer 가 아니라 **Industrials**, `hvac_building` 은 Industrials 가 아니라 **Basic Materials**,
`retail_discount` 는 Cyclical 이 아니라 **Consumer Defensive** 다. 전부 실측을 따랐다.

**초안이 겹쳐 놨던 것** — `grid_equipment` 의 `industry_match` 는 초안에서
`Electrical Equipment & Parts` 와 `Specialty Industrial Machinery` 둘이었다. 그대로 두면
`industrial_automation` 과 중복 소속이 생겨 §5 의 두 번째 검사(중복 0개)가 깨진다.
→ 라벨을 갈라 `grid_equipment` 는 전자만, `industrial_automation` 은 후자만 갖는다.

### (d) 큐레이션 전용 버킷이 늘어난 이유 — 21개

`industry_match` 가 비고 `include_tickers` 로만 구성되는 버킷이 21개다. 초안이 예상한 것은
`rare_earth` 하나였다. 실측에서 드러난 것은 **테마가 라벨을 가로지르는 일이 흔하다**는 점이다.

- **탱커가 두 라벨에 쪼개져 있다** — FRO·DHT·INSW·STNG·TNK·TEN·TRMD·TK·CMBT 는
  `Oil & Gas Midstream`, ASC·ECO·HAFN·NAT·PXS 는 `Marine Shipping`.
  어느 한쪽만 봐도 탱커 버킷이 되지 않는다.
- **리튬은 화학과 광업에 걸쳐 있다** — ALB·SQM·LTHM 은 `Specialty Chemicals`,
  LAC·SLI·SGML 등은 `Other Industrial Metals & Mining`.
- **벤더 오분류가 실재한다** — SWC(Stillwater, 팔라듐)가 `Uranium`, SBSW 가 `Gold`,
  CHPT·EVGO(EV 충전)가 `Specialty Retail`, BLNK 가 `Engineering & Construction`,
  OKLO(SMR)가 `Utilities - Regulated Electric`.
- **전환 테마에는 전용 라벨이 아예 없다** — 수소·ESS·EV충전·SMR·우주·사이버보안·EDA 모두.

큐레이션 버킷은 생존 편향 위험이 가장 크다(§1). 그래서 폐지 종목을 명시적으로 넣었다 —
`rare_earth` 에 MCPIQ(Molycorp 2015 파산) 등 4종, `shipping_tanker` 에 GMRRQ·OSGIQ 등 11종,
`cybersecurity` 에 MNDT·PFPT·SPLK 등 7종, `reit_datacenter` 에 CONE·QTS·DFT·SWCH 4종.
그럼에도 `coatings_adhesives`·`fintech_payments`·`reit_towers`·`shipbuilding` 넷은
구성원 전원이 생존자라 **편향이 남아 있다** — `theme-coverage-audit.md` §4 에 적었다.

### (e) 커버리지 결과 요약

미분류 시총 **0.000%**(기준 < 5%), 중복 소속 **0건**(기준 0) — 둘 다 통과.
`min_constituents` 미달 9개, ETF 상관 검사와 시총 추이 검사는 **미실행**(지수 구성 코드가
아직 없다 — 통과가 아니라 미실행으로 기록했다). 축 1 적용 가능 버킷은 **45 / 134** 이며,
`verify: true` 16개를 빼면 확정 가용은 29개다. 상세는 `theme-coverage-audit.md`.

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
