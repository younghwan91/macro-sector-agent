# 케이스 · 셰일 E&P 2020 — 사이클

| 항목 | 값 |
|---|---|
| case id | `shale-ep-2020` |
| theme id | `oil_gas_ep` (실측 420종, 생존 74 — 2015-2020 파산 물결 포함) |
| type | cycle |
| pair | `offshore-drilling-2016` (에너지 쌍 — `04-value-trap.md` §5) |
| 판정 시점 | **2020-04-30** |
| 국면 기간 | 2014-06 ~ 2020-03 (고점 → 저점), 반등 2020-04 ~ 2022-06 |
| 작성일 | 2026-08-23 |

> 사후 기입 문서. 임계값 조정의 근거가 아니다 (`04` §5 · `10` §7 · `CLAUDE.md` §1).

## 1. 판정 시점과 국면

2020-04-20 WTI 5월물이 **−$37.63** 에 정산됐고, 4월 1일 Whiting 이 Ch.11 을 신청했다. 2014-06 고점부터
6년 가까운 하락에 2015-2019 파산 208건이 누적된 뒤였다. 판정 시점을 4월 말로 둔 이유: 가격 붕괴·파산·감산이
모두 관측된 뒤지만 반등(5월~)은 아직 아닌 시점이다.

## 2. 판정 시점의 L1 상태 (정성)

- `oil_gas_ep` 버킷 EW 지수: 2014-06-23 고점 대비 **−89.9%** (2020-04-30), 5년 고점(2015-04-30) 대비 −82.1%. 구성원 75종.
- 저점은 2020-03-18 (고점 대비 −94.9%) — 판정 시점은 저점 6주 뒤. 이후 24개월 최저점은 2020-11-06 (판정 대비 −16.2%).
- 전방 수익률(EW): 12M +97% · 24M +321% · 36M +299%. 2014 고점은 2026-08 현재 미회복.

## 3. 5축 사후 기입

| 축 | 판정 시점 관측값 | 근거 | 판정 |
|---|---|---|---|
| 1 물량 | 세계 석유 소비(EIA STEO, 각 연도의 이듬해 1월 추정치 = PIT 값, mb/d): 2009 84.10 → 2014 91.39 → 2019 100.87. **10y CAGR +1.8%/y, 5y CAGR +2.0%/y.** 2020 은 팬데믹으로 급감(−8% 전망)하지만 일시적 충격으로 분류 | E1·E2·E3 | **사이클** — `unit_cagr_10y ≥ 0`, 5y 가 진폭 안 |
| 2 자본 사이클 | 2015-2019 북미 E&P 파산 208건($121.7B 부채), 2020 에도 Whiting(4/1)·Chesapeake(6월)·Oasis(9/30) 등 — `exit_count` 매우 높음. 5월 미국 원유 생산 −1.99 mb/d(사상 최대 월간 감소). capex/D&A < 1 8분기+ 는 업계 합산으로 미검증 | E4·E5·E6 | 공급 파괴 진행 — `+0.10` 요건(8분기+) 미검증 → 가점 보류 |
| 3 대체 | EV 신차 판매 비중 2019 **2.6%** (IEA), 보유 차량 기준 < 1%. 비용 교차점 미도달. 규제 강제 없음(2020 시점) | E7 | **사이클** — 침투율 < 10% |
| 4 원가곡선 | Dallas Fed 2020-Q1: 신규 유정 손익분기 평균 **$49** ($46–52), WTI 주간 평균 $24 → "거의 어느 기업도 신규 유정 채산 불가". 4/20 음의 유가, 5월 셧인 1.99 mb/d | E8·E9·E6 | **강한 사이클** — 가격 < 원가, 셧다운 관측 |
| 5 터미널 | 2020 파산 다수(Whiting·Chesapeake·Oasis 등) — 테마 수준에서 24M 만기 위험 심각. 단 생존자의 자산(유정·광구)은 논지 성립 시 가치 회복 | E4·E5 | **심각** (종목별 L4 생존 필터 필수) |

`unit_series_source: physical_series` (EIA 세계 석유 소비 — `themes.yaml` 의 `physical_ref` 는 USO 가격이지만
이 케이스는 실물 소비량을 1순위로 썼다), `axis1_available: true`.

## 4. 하드 게이트와 확신도 — 기계적 적용

```
자동 기각 / 상한 조항 → 해당 없음
축5 24M 만기/시총 > 0.5 → 종목 다수 해당 추정 → L4 에서 종목 제외 (테마 유지)

base 0.5
+0.15 축1 사이클
+0.00 축2 (8분기+ 미검증)
+0.15 축3 대체 위협 없음
+0.10 축4 가격 < 원가, 셧다운 관측
−0.15 축5 심각
+0.00 거시 순풍 (미평가)
= 0.75  → 포트 편입 가능
```

**게이트 결과: `passed`.** **역사적 결과와 일치하는가: 예.** 24M +321% (EW). 대표 생존 종목 2020-04-30→2022-06-30:
DVN +408%, CLR +307%, MRO +277%, FANG +201%, PXD +176%, APA +172%, EOG +160%; SM +750%, MTDR +566%.
같은 기간 OASPQ·CHKAQ·WLL 구주는 −100% — **축 5 의 생존 필터가 없으면 테마 판정이 맞아도 종목에서 죽는다**는 것이
이 케이스가 보여주는 점이다.

## 5. 낙폭

- `oil_gas_ep` EW: **고점 2014-06-23 → 저점 2020-03-18, −94.9%.**
- 대표 종목(2014-01~2022-12 최대 낙폭): SM −99% (2014-02-18→2020-04-01), APA −96%, MTDR −96%, DVN −93%, MRO −92%,
  CLR −91%, FANG −89% (2018-10-03→2020-03-18), EOG −77%, PXD −75%; 파산: OASPQ −100%, CHKAQ −100%, DNRCQ −100%, UNTCQ −100%.

## 6. evidence

| id | claim | source_url | date | reliability |
|---|---|---|---|---|
| E1 | 세계 석유·액체연료 소비 2019 = 100.87 mb/d (STEO 2020-06 Table 3a) | https://www.eia.gov/outlooks/steo/archives/jun20.pdf | 2020-06 | high |
| E2 | 2009 = 84.10 mb/d (STEO 2010-01) | https://www.eia.gov/outlooks/steo/archives/jan10.pdf | 2010-01 | high |
| E3 | 2014 = 91.39 mb/d (STEO 2015-01) | https://www.eia.gov/outlooks/steo/archives/jan15.pdf | 2015-01 | high |
| E4 | 2015–2019 북미 E&P 파산 208건, 부채 $121.7B (Haynes & Boone Oil Patch Bankruptcy Monitor) | https://www.haynesboone.com/news/publications/energy-bankruptcy-monitors-and-surveys | 2020-01 | medium (요약 인용) |
| E5 | Whiting Petroleum Ch.11 2020-04-01 | https://www.sec.gov/Archives/edgar/data/1255474/000125547420000011/wll-20200331x10q.htm | 2020-05 | high |
| E6 | 2020-05 미국 원유 생산 −1.99 mb/d, 1980 이후 최대 월간 감소 (셧인) | https://www.eia.gov/todayinenergy/detail.php?id=44616 | 2020-08 | high |
| E7 | 2019 전기차 신차 판매 비중 2.6% | https://www.iea.org/reports/global-ev-outlook-2020 | 2020-06 | high |
| E8 | Dallas Fed Energy Survey 2020Q1: 신규 유정 손익분기 평균 $49 ($46–52), WTI 주간 평균 $24 | https://www.dallasfed.org/research/surveys/des/2020/2001 | 2020-03-25 | high |
| E9 | WTI 2020-04-20 −$37.63 정산 | https://www.eia.gov/todayinenergy/detail.php?id=46336 | 2020-12 | high |
| E10 | Oasis Petroleum Ch.11 2020-09-30 | https://www.hartenergy.com/exclusives/shale-producer-oasis-petroleum-files-bankruptcy-189936 | 2020-09-30 | medium |
| E11 | `oil_gas_ep` EW 낙폭 −94.9%, 전방 수익률, 대표 종목 | 저장소 L1 패널 + `prices` (store_end 2026-08-14) | 2026-08-23 | high (내부 계산) |

## 7. 미검증·한계

- 축 2 의 capex/D&A 8분기 요건 미검증 (가점 보류). 북미 리그 카운트 2014 고점(약 1,900대)·2020 저점(244대)은
  1차 출처 본문으로 확인하지 못해 본문에서 뺐다.
- 축 1 은 **세계** 소비량이다. 셰일 E&P 의 최종 수요는 세계 유가에 연동되므로 적절하지만, 미국 내 제품 공급량
  (EIA product supplied)으로 재도 같은 부호다(미인용).
- 전방 수익률은 생존 종목이 주도한다. 파산 종목을 포함한 EW 지수(+321%)와 개별 생존주 수익률을 섞어 읽지 않는다.
