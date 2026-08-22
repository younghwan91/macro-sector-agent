# 케이스 · 몰 REIT 2018 — 사망

| 항목 | 값 |
|---|---|
| case id | `mall-reit-2018` |
| theme id | `reit_retail` (`cycle_class: secular_risk`; Sharadar 'REIT - Retail' 45종 — 몰·스트립센터·NNN 혼합, `physical_ref: null`) |
| type | death |
| pair | `tankers-2021` (부동산·인프라 쌍 — `04-value-trap.md` §5) |
| 판정 시점 | **2018-12-31** |
| 국면 기간 | 2016-08 ~ 2020-04 (고점 → 저점), B/C 몰 REIT Ch.11 2020-11 ~ 2021-06 |
| 작성일 | 2026-08-23 |

> 사후 기입 문서. 임계값 조정의 근거가 아니다 (`04` §5 · `10` §7 · `CLAUDE.md` §1).

## 1. 판정 시점과 국면

Sears Ch.11(2018-10-15, 부채 $11.3B) 직후. 2017 점포 폐쇄 8,139건(사상 최다), 2018 5,524건. 지역 몰 공실률 2018-Q3 9.1%
(7년래 최고). 그런데 **대형 A 몰 REIT 의 동일점포 NOI 는 여전히 +2.3%** (SPG 2018) — 운영 지표가 가격 신호보다 늦게 꺾인다는
것이 이 케이스의 함정이다. 버킷 EW 는 2016-08 고점 대비 −29% 에 불과했고, 몰 전문 REIT(CBL·WPG·PEI·MAC)는 이미 −50~−70% 였다.

## 2. 판정 시점의 L1 상태 (정성)

- `reit_retail` 버킷 EW: 2016-08-01 고점 대비 **−29.2%** (2018-12-31), 고점 후 29개월. 구성원 35종.
- 전방 수익률(EW): 12M +17% · 24M −11% · 36M +35%. 이후 24개월 최저점 2020-04-03 (판정 대비 −49.1%).
- 버킷 EW 는 2024-09-05 에 2016 고점을 회복했다 — 스트립센터·NNN 이 회복시킨 것이고 몰 REIT 는 아니다(§5).

## 3. 5축 사후 기입

| 축 | 판정 시점 관측값 | 근거 | 판정 |
|---|---|---|---|
| 1 물량 | **저장소 현재 설정으로는 계산 불가** — `reit_retail.physical_ref: null` → `axis1_available: false`, `not_applicable`, 가중치를 축 3 으로 이전. 사후 대조용 그림자 시계열: 백화점 매출(Census, FRED RSDSELD 연합계) 2008 $198.7B → 2013 $170.6B → 2018 $142.3B: **10y CAGR −3.3%/y, 5y CAGR −3.6%/y (가속)** → 규칙 적용 시 **사망**. 몰 방문(C&W/ShopperTrak, 연말 2개월) 2010 350억 → 2013 173억 (medium) | E1·E2·E3 | **not_applicable** (저장소 설정) / 그림자 시계열로는 **사망** |
| 2 자본 사이클 | 신규 몰 건설 사실상 0 (capex/D&A < 1) — 1차 출처 미확보. 퇴출은 **테넌트**(Sears·Toys R Us·Bon-Ton)에서 먼저, REIT 퇴출은 2020-11(CBL·PREIT)·2021-06(WPG) | E4·E5·E9 | 공급 파괴 ≠ 수요 복귀 — 축 2 단독 판별 불가. `+0.10` 미검증 → 보류 |
| 3 대체 | 전자상거래 비중 2018-Q4 **9.9%** (연간 9.7%, 2017 8.9%) — 규칙의 10% 경계. 몰 주력 카테고리(의류·가전)는 더 높음(미인용). 비용 우위 있음, 비가역, 규제 강제 없음 | E1 | **경고** (10~35% 경계 도달 + 비용 교차) — 보수적으로 경고, 카테고리 기준이면 사망 |
| 4 원가곡선 | REIT 에는 원가곡선 개념이 약함(프록시: cap rate vs 조달비용). 미적용 | — | **무관/not_applicable** |
| 5 터미널 | CBL 순부채/EBITDA 2018 **7.1x**, WPG 부채/FFO 2015 ~10x → 2019 ~18x; 자산(B/C 몰) 재활용성 낮음(재개발 자본 소요 큼); A 몰(SPG)은 양호 | E6·E7 | **심각** (B/C 몰) |

`unit_series_source: none` (저장소 설정), `axis1_available: false`. **이 테마에서는 게이트를 쥔 축이 축 3(LLM)이다** — `04` 축 1
"적용 가능 범위" 가 경고한 바로 그 상황이다. 그림자 시계열(백화점 매출)은 사후 대조용이며, 이 문서가 그것을 `physical_ref` 로
채우라고 요구하지는 않는다(그건 `themes.yaml` 의 별도 결정이고 임계값과 무관한 **입력** 문제다 — 검토 과제로만 남긴다).

## 4. 하드 게이트와 확신도 — 기계적 적용

```
(저장소 설정: 축1 = not_applicable)
축1 == 사망 AND 축3 ∈ {경고,사망} → 해당 없음 (축1 n/a)
축1 == 사망 OR  축3 == 사망       → 해당 없음 (축3 경고)
축5 24M 만기/시총 > 0.5           → CBL·WPG·PEI 해당 추정 → L4 제외

base 0.5
+0.00 축1 (n/a — 가감 없음, 가중치 축3 이전, key_uncertainties 명시)
+0.00 축2 (미검증)
−0.15 축3 경고
+0.00 축4 (n/a)
−0.15 축5 심각
+0.00 거시 순풍 (미평가)
= 0.20 → 포트 편입 불가 (최소 0.5 미달)

(그림자 시계열 적용 시: 축1 사망 AND 축3 경고 → 자동 기각)
```

**게이트 결과: 저장소 설정으로는 `passed`(게이트 자체는 통과)이나 확신도 0.20 으로 편입 불가; 그림자 시계열로는 `rejected`.**
**역사적 결과와 일치하는가: 예 (편입 불가).** 단 **일치의 경로가 약하다** — 축 1 이 꺼져 있어 게이트가 아니라 확신도 바닥(−0.30)이
막았고, 그 −0.30 의 절반은 LLM 영역(축 3)이다. 2018-12-31→2020-12-31: MAC −71%(최저 −87%), SPG −43%(최저 −72%), SKT −43%,
CBL·WPG·PEI Ch.11. 버킷 EW 는 24M −11% 로 "−80%" 가 아니다 — 몰과 스트립센터가 한 버킷에 있기 때문이다.

**어긋남·주의 기록.**
1. `04` §1 의 "몰·백화점 REIT −80%, 회복 없음" 은 몰 전문 REIT 개별 종목에는 맞고(−77~−100%), `reit_retail` **버킷**에는 맞지 않는다
   (−64%, 2024-09 회복). L_i 에 어느 숫자를 쓸지는 `07` 의 결정이며 여기서는 둘 다 적는다.
2. 축 3 의 "침투율 10%" 경계에 정확히 걸쳐 있었다(9.9%). 경계값에 있는 사례가 판정을 가르는 구조는 기록해 둔다. 임계값은 그대로.

## 5. 낙폭 (L_i 입력용)

- `reit_retail` 버킷 EW: **고점 2016-08-01 → 저점 2020-04-03, −64.0%** (COVID 저점; 2024-09-05 고점 회복).
- 몰 전문 REIT(2016-01~2020-12 최대 낙폭): CBLAQ −100% (2016-09-07→2020-11-05), PRET(PEI) −98%, WPGGQ −93% (→2020-11-06),
  MAC −93% (2016-08-01→2020-04-02), SRG −88%, SKT −87%, SPG −77% (2016-08-01→2020-04-02), TCO −62% (2020 SPG 피인수).
- 판정 시점(2018-12-31)→2020-12-31: MAC −71%, SPG −43%, SKT −43%, TCO +2%.

## 6. evidence

| id | claim | source_url | date | reliability |
|---|---|---|---|---|
| E1 | 전자상거래 비중 2018-Q4 9.9%(계절조정), 2018 연간 9.7%, 2017 8.9% | https://www2.census.gov/retail/releases/historical/ecomm/18q4.pdf | 2019-03-13 | high |
| E2 | 백화점 매출(Census Advance Retail Sales, 월별 합계, 십억$): 2000 231.6 · 2008 198.7 · 2013 170.6 · 2018 142.3 · 2019 134.9 | https://fred.stlouisfed.org/series/RSDSELD | 2026-08-23 (접근) | high |
| E3 | 연말(11-12월) 소매 방문 2010 350억 → 2013 173억 (Cushman & Wakefield / ShopperTrak) | https://www.usnews.com/news/articles/2015/03/10/shopping-malls-middle-class-face-a-bleak-future | 2015-03-10 | medium |
| E4 | 지역 몰 공실률 2018-Q3 9.1%(7년 최고) → Q4 9.0%, 2017 말 8.3%, 10년 평균 8.4% (Reis) | https://www.cnbc.com/2019/01/03/us-malls-handle-store-closures-by-sears-others-better-than-expected.html | 2019-01-03 | medium |
| E5 | 점포 폐쇄 2017 8,139건, 2018 5,524건 (Coresight) | https://coresight.com/research/reviewing-2018-u-s-and-u-k-store-closures/ | 2019-01 | medium |
| E6 | CBL 순부채/EBITDA 7.1x (2018) | https://seekingalpha.com/article/4315215-mall-reit-debt-and-liquidity | 2019-12 | medium |
| E7 | WPG 부채/FFO 2015 <10x → 2019 ~18x (업계 8–10x) | https://restructuringnewsletter.com/p/washington-prime-group-from-tenant-churn-to-balance-sheet-failure | 2021 | medium |
| E8 | Sears Ch.11 2018-10-15, 부채 $11.3B | https://www.forbes.com/sites/bradthomas/2018/10/15/sears-finally-sells-out/ | 2018-10-15 | medium |
| E9 | CBL Ch.11 2020-11-01; PREIT Ch.11 2020-11-01; WPG Ch.11 2021-06-13 | https://www.abi.org/feed-item/new-chapter-11-filing-%E2%80%93-cbl-associates-properties ; https://www.preit.com/news/preit-commences-process-to-implement-prepackaged-plan-to-strengthen-the-business-and-enhance-financial-flexibility/ ; https://www.benzinga.com/news/21/06/21549481/washington-prime-group-a-shopping-mall-reit-declares-chapter-11-bankruptcy | 2020-11 / 2021-06 | medium–high |
| E10 | SPG 2018 동일점포 NOI +2.3%, 포트폴리오 NOI +3.7% | https://investors.simon.com/news-releases/news-release-details/simon-property-group-reports-record-fourth-quarter-and-full-year | 2019-02 | high |
| E11 | `reit_retail` EW 낙폭 −64.0%, 몰 REIT 개별 낙폭, 전방 수익률 | 저장소 L1 패널 + `prices` (store_end 2026-08-14) | 2026-08-23 | high (내부 계산) |

## 7. 미검증·한계

- 축 1 은 저장소 설정상 계산되지 않는다. 그림자 시계열(백화점 매출)은 **몰 최종 수요의 프록시**이지 몰 방문·매출 자체가 아니다 →
  `verified: false` (축 1 판정이 1차 실물 시계열에 기반하지 않음).
- 축 2 의 capex/D&A, 축 3 의 카테고리별 침투율은 1차 출처 미확보.
- 버킷이 이질적(몰·스트립·NNN)이라 버킷 낙폭(−64%)과 몰 REIT 낙폭(−77~−100%)이 크게 다르다. `L_i` 산출 시 어느 쪽을 쓰는지 명시해야 한다.
