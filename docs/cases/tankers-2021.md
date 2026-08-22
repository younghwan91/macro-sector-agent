# 케이스 · 탱커 2021 — 사이클

| 항목 | 값 |
|---|---|
| case id | `tankers-2021` |
| theme id | `shipping_tanker` (include 전용 구성, 폐지 11종 포함) |
| type | cycle |
| pair | `mall-reit-2018` (부동산·인프라 쌍 — `04-value-trap.md` §5) |
| 판정 시점 | **2021-12-31** |
| 국면 기간 | 2020-04 ~ 2022-01 (2020 운임 초호황 후 붕괴 → 저점), 반등 2022-02 ~ 2023 |
| 작성일 | 2026-08-23 |

> 사후 기입 문서. 임계값 조정의 근거가 아니다 (`04` §5 · `10` §7 · `CLAUDE.md` §1).

## 1. 판정 시점과 국면

2021년 VLCC 현물 TCE 는 연중 대부분 **음수**(3월 −$7,400/일, 1H 비스크러버 평균 ~$500/일 — 2000년 이후 최저)였고,
Euronav 는 연간 −$339M 손실. 그러나 발주잔량은 선대의 7%대(1996 이후 최저), 해체는 급증(2021 탱커 301척, 2020 대비 +242%).
판정 시점 12월 말은 저점(2022-01-24) 한 달 전이다.

## 2. 판정 시점의 L1 상태 (정성)

- `shipping_tanker` 버킷 EW: 5년 고점(2016-11-16) 대비 **−62.0%**, 2020-04-27 국면 고점 대비 −52% (2021-12-31). 구성원 13종.
- 최종 저점 2022-01-24 (국면 고점 대비 **−53.9%**; 판정 시점 대비 −9.5%).
- 전방 수익률(EW): 12M +131% · 24M +239% · 36M +190%.

## 3. 5축 사후 기입

| 축 | 판정 시점 관측값 | 근거 | 판정 |
|---|---|---|---|
| 1 물량 | 세계 석유 소비(EIA STEO, 이듬해 1월 추정 = PIT, mb/d): 2011 88.11 → 2016 95.57 → 2019 100.87 → 2021 96.90. **10y CAGR +1.0%/y, 5y CAGR +0.3%/y** (2021 이 2019 대비 −3.9% 인 팬데믹 잔여). 원유 톤마일 2021 −4.5% (Clarksons) | E1·E2·E3·E4·E5 | **사이클** — 10y ≥ 0, 5y 가 진폭 안(팬데믹 충격) |
| 2 자본 사이클 | 탱커 발주잔량/선대 7%대 (1996 이후 최저, 장기평균 ~20%) — 신조 capex 가 선대 감가를 밑도는 상태가 2020 하반기부터 지속. 해체 2021 301척(화물선 해체의 59%, 2020 88척 대비 +242%); 9월 한 달 190만 dwt(39개월 최대). 상장사 파산은 없음 | E6·E7·E8 | **사이클** — 공급 파괴 진행. 발주잔량 최저가 8분기 근접 → `+0.10` 적용 (근거: E6·E7) |
| 3 대체 | EV 신차 판매 비중 2021 9% (IEA) — 보유 차량 기준 ~1%, 원유 해상 운송의 대체재(파이프라인·수요 소멸)는 침투율 <10%, 비용 역전 없음. IMO 2023 EEXI/CII 는 대체가 아니라 **공급 제약**(감속) | E9 | **사이클** — 침투율 < 10% |
| 4 원가곡선 | VLCC TCE 음수(운항비 이하) 장기화 → 노후선 해체 강제. "셧다운" 에 해당하는 해체 급증 관측 | E10·E11·E7·E8 | **강한 사이클** |
| 5 터미널 | 2020 초호황으로 대형사 재무 개선; Euronav 2021 말 유동성 $708M. 자산(선박) 재활용성 높음 — S&P·해체 시장 존재. 24M 만기/시총 > 0.5 종목은 확인 못함 | E12 | 심각 아님 |

`unit_series_source: physical_series` (EIA 세계 석유 소비 + Clarksons 톤마일), `axis1_available: true`.
`themes.yaml` 의 physical_ref(Baltic Dirty Tanker Index)는 **가격**이므로 축 1 에는 실물 소비·톤마일을 썼다.

## 4. 하드 게이트와 확신도 — 기계적 적용

```
자동 기각 / 상한 조항 → 해당 없음

base 0.5
+0.15 축1 사이클
+0.10 축2 capex(발주잔량) 최저 지속
+0.15 축3 대체 위협 없음
+0.10 축4 가격 < 원가, 해체 관측
+0.00 축5
+0.00 거시 순풍 (미평가)
= 1.00 → [0,1] 클립 → 1.00
```

**게이트 결과: `passed`.** **역사적 결과와 일치하는가: 예.** 24M +239%. STNG +277%, TNK +262%, INSW +197%, NAT +144%,
FRO +132%, TK +92%, DHT +78% (2021-12-31→2023-06-30).

**기록.** 기계적 산출이 1.00 으로 **포화**한다. `04` §4 의 가점 합이 0.60 이라 4축 가점 + 거시 순풍이 모두 붙으면
1.0 을 넘는다. 계수는 선언이므로 바꾸지 않는다 — 다만 "1.0 = 확신" 이 아니라 "감점 사유가 관측되지 않았다" 로 읽어야
한다는 점을 `key_uncertainties` 에 적는다. 캘리브레이션(`10-validation.md`)의 대상이다.

## 5. 낙폭

- `shipping_tanker` EW: **국면 고점 2020-04-27 → 저점 2022-01-24, −53.9%** (러닝 MDD). 2007-07 사상 고점 대비로는 −94%.
- 대표 종목(2019-01~2023-06 최대 낙폭): NAT −78% (2020-04-28→2022-02-03), STNG −77% (2020-01-02→2020-11-04), ASC −71%,
  TK −70%, TNK −63%, INSW −57%, FRO −50%, DHT −40%; TOPS −100% (희석).

## 6. evidence

| id | claim | source_url | date | reliability |
|---|---|---|---|---|
| E1 | 세계 석유·액체연료 소비 2021 = 96.90 mb/d (STEO 2022-01) | https://www.eia.gov/outlooks/steo/archives/jan22.pdf | 2022-01 | high |
| E2 | 2011 = 88.11 mb/d (STEO 2012-01) | https://www.eia.gov/outlooks/steo/archives/jan12.pdf | 2012-01 | high |
| E3 | 2016 = 95.57 mb/d (STEO 2017-01) | https://www.eia.gov/outlooks/steo/archives/jan17.pdf | 2017-01 | high |
| E4 | 2019 = 100.87 mb/d (STEO 2020-06) | https://www.eia.gov/outlooks/steo/archives/jun20.pdf | 2020-06 | high |
| E5 | 2021 원유 톤마일 −4.5% (Clarksons; 장거리 항로 축소) | https://annualreport2021.hafnia.com/industry-overview/the-product-tanker-market/ | 2022-03 | medium |
| E6 | 탱커 발주잔량 2022-01 선대의 7.3%, 1996 이후 최저, 장기평균 ~20% | (1차 출처 본문 미확인 — 검색 요약만; 아래 §7) | 2022-01 | unverified |
| E7 | 2021 탱커 해체 301척, 화물선 해체의 59%, 2020(88척) 대비 +242% | https://www.marinelog.com/news/scrapping-tankers-dominated-2021-demo-numbers/ | 2022-01 | medium (요약 인용) |
| E8 | 2021-09 탱커 해체 190만 dwt (39개월 최대), 1~8월 합계 220만 dwt; VLCC 4척 등 (BIMCO) | https://www.maritime-executive.com/article/sales-of-tankers-for-scrap-hit-39-month-high-in-september | 2021-10-08 | medium |
| E9 | 2021 전기차 신차 판매 비중 9% | https://www.iea.org/reports/global-ev-outlook-2022/executive-summary | 2022-05 | high |
| E10 | VLCC 중동-아시아 TCE −$7,400/일, "25년래 최저" (Clarksons Platou) | https://www.freightwaves.com/news/minus-7400-a-day-how-can-shipping-rates-fall-below-zero | 2021-03-14 | medium |
| E11 | 비스크러버 VLCC 현물 수익 1H 2021 평균 ~$500/일, 2000 이후 최저 | https://shipandbunker.com/news/world/828256-non-scrubber-vlcc-spot-rates-hit-record-low | 2021-07 | medium (요약 인용) |
| E12 | Euronav 2021 순손실 $339M, 2021 말 유동성 $708M | https://live.euronext.com/en/products/equities/company-news/2022-02-03-euronav-announces-fourth-quarter-2021-results | 2022-02-03 | medium |
| E13 | `shipping_tanker` EW 낙폭 −53.9%, 전방 수익률, 대표 종목 | 저장소 L1 패널 + `prices` (store_end 2026-08-14) | 2026-08-23 | high (내부 계산) |

## 7. 미검증·한계

- E6(발주잔량 7.3%)은 1차 출처(선사 20-F/6-K 의 Clarksons 인용)를 본문으로 확인하지 못했다. 축 2 의 `+0.10` 이 여기에 기대므로
  **`verified: false`**. E6 을 빼면 축 2 는 E7·E8(해체 급증)만으로 "파괴 진행" 이고 `+0.10` 요건(capex 8분기)은 미검증 →
  확신도 0.90. 어느 쪽이든 편입 가능.
- 축 1 을 세계 석유 소비로 쟀다. 탱커의 진짜 단위는 톤마일이며 2021 은 −4.5% 였다 — 5년 CAGR 로는 양수(미인용, Clarksons 유료).
- 2020-04 의 "국면 고점" 은 운임 초호황의 산물이고, 5년 고점(2016-11) 대비 −62% 가 L1 의 "고점 대비 낙폭" 에 더 가깝다. 둘 다 적었다.
