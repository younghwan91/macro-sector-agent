# 케이스 · 오프쇼어 드릴링 2016 — 사망

| 항목 | 값 |
|---|---|
| case id | `offshore-drilling-2016` |
| theme id | `offshore_drilling` (`cycle_class: secular_risk`; Sharadar 'Oil & Gas Drilling' 라벨 — 육상 시추 포함) |
| type | death |
| pair | `shale-ep-2020` (에너지 쌍 — `04-value-trap.md` §5) |
| 판정 시점 | **2016-02-29** |
| 국면 기간 | 2014-06 ~ 2020-04 (고점 → 저점; 2016-17 중간 반등 포함), 대형사 Ch.11 2020-04 ~ 2021-02 |
| 작성일 | 2026-08-23 |

> 사후 기입 문서. 임계값 조정의 근거가 아니다 (`04` §5 · `10` §7 · `CLAUDE.md` §1).

## 1. 판정 시점과 국면

유가 $30 안팎, Hercules(2015-08)·Vantage(2015-12)·Paragon(2016-02-14) Ch.11 직후. 버킷 EW 지수는 2014 고점 대비
−83%, 2008 고점 대비 −88%. "공급 파괴가 이미 진행 중이고 가격은 바닥" 으로 보이던 시점이다. 실제로 판정 후
12개월 EW +62% 반등이 왔다 — 그리고 그 반등은 2020 년까지 −99% 로 끝났다. 이 케이스가 중요한 이유는
**반등이 있었기 때문**이다. `04` §1 주석: "사양 산업도 공급이 파괴되면 반등한다 — 진입 가능한 반등인가가 문제다."

## 2. 판정 시점의 L1 상태 (정성)

- `offshore_drilling` 버킷 EW: 2014-06-20 고점 대비 **−83.5%** (2016-02-29), 고점 후 20개월. 구성원 18종.
- 전방 수익률(EW): 12M +62% · 24M +10% · 36M −24%. 최종 저점 2020-04-01 (판정 시점 대비 **−94%**).
- 2014 고점은 2026-08 현재 미회복.

## 3. 5축 사후 기입

| 축 | 판정 시점 관측값 | 근거 | 판정 |
|---|---|---|---|
| 1 물량 | (a) `themes.yaml` physical_ref = 오프쇼어 리그 카운트: 계약 중 플로터 2014-08 280 → 2015-08 **225 (−20%)**, 잭업 450 → 390, 가동률 85→72%. 10y CAGR 은 1차 시계열 미확보 → **미검증**. (b) 최종 수요(해상 원유 생산, IEA): 최근 10년 **26–27 mb/d 로 정체**(점유율 하락) → 10y CAGR ≈ 0 | E1·E2 | **경고** — 최종 수요 정체(10y ∈ [−2%,0) 경계), 리그 수요는 급감. 어느 시계열을 쓰느냐에 따라 사망(리그)과 경고(생산) 사이에서 갈림 — 리그 10y 는 미검증이므로 보수적으로 경고 |
| 2 자본 사이클 | 공급 **과잉** 국면: 2015 잭업 신조 20기 인도, 건조 중 200기+, 스택 150→275기. 플로터 38기 해체(2014-10~). 퇴출: Hercules·Vantage·Paragon Ch.11. capex/D&A 는 신조 인도로 여전히 > 1 (업계 합산 미검증) | E1·E3·E4·E5 | 파괴 시작, 그러나 신조 인도가 계속됨 → `+0.10` 불가 |
| 3 대체 | 2016-01 WoodMac: 지연 프로젝트 68건·$380B, 평균 손익분기 **$62/boe**, 심해가 절반 이상. 같은 시기 셰일 신규 유정 손익분기 **$54** (Dallas Fed, 2016). 자본 배분에서 심해가 셰일에 밀림. 침투율(셰일의 세계 공급 점유) 은 <10% 이지만 규칙의 "비용 역전 완료" 조항에 해당 | E6·E7 | **사망** — 비용 역전 완료 |
| 4 원가곡선 | UDW 일당 2012-13 $530–640k → 2017 $135–206k (−60~70%), 2016 에 24기 퇴역, 2014 이후 64기 콜드스택. 일당이 현금원가 이하 → 해체 강제 | E8·E9 | **강한 사이클** — "반등한다" 만 (트레이딩용) |
| 5 터미널 | Seadrill 2015 말 이자부채 **$11.1B** + 신조 잔금 $5B; 2020 Valaris 부채 $7.85B. 자산(리그) 재활용성 없음(고철). 24M 만기/시총 > 0.5 다수 | E10·E11 | **심각** |

`unit_series_source: physical_series` (IEA 해상 원유 생산 + IHS 리그 카운트), `axis1_available: true`.
**`sign_split` 유사 상황**: 두 실물 시계열의 판정이 갈린다(생산 정체 vs 리그 급감). 실물 시계열 간 충돌은 `04` §3.1
의 정의(합산 vs 중앙값) 밖이지만 성격이 같다 — 리포트에 `key_uncertainties` 로 적는다.

## 4. 하드 게이트와 확신도 — 기계적 적용

```
축1 == 사망 AND 축3 ∈ {경고,사망} → 해당 없음 (축1 = 경고; 리그 10y 가 검증됐다면 사망 → 자동 기각이었을 것)
축1 == 사망 OR  축3 == 사망       → 해당: 축3 사망 → 상한 0.35, 포트 편입 불가
축5 24M 만기/시총 > 0.5           → 다수 종목 해당 → L4 제외

base 0.5
−0.20 축1 경고
+0.00 축2 (신조 인도 지속 — 요건 불충족)
+0.00 축3 (사망 — 상한 적용)
+0.10 축4 가격 < 원가, 퇴역 관측
−0.15 축5 심각
+0.00 거시 순풍 (미평가)
= 0.25 → min(0.25, 0.35) = 0.25 → 포트 편입 불가
```

**게이트 결과: 상한 0.35 (관찰 목록).** **역사적 결과와 일치하는가: 예.** 12M +62% 반등은 축 4 가 예고한 "반등" 이었고,
축 1·3 이 "진입 불가" 라고 한 대로 36M −24%, 2020-04 까지 −94%. Diamond(2020-04)·Noble(2020-07/08)·Valaris(2020-08)
·Pacific Drilling(2020-11)·Seadrill(2021-02) Ch.11.

**어긋남 기록.** `04` 축 3 본문은 "2014년 셰일 손익분기 $50 아래, 심해 $70+" 로 적었다. 1차·2차 출처로 확인되는 것은
2016-01 기준 **심해(지연 프로젝트) $62 vs 셰일 $54** 이며, 역전 폭은 문서 서술보다 좁다. 역전 자체는 성립한다.
이 차이를 서술로 남기고 규칙은 손대지 않는다.

## 5. 낙폭 (L_i 입력용)

- `offshore_drilling` EW: **고점 2014-06-20 → 저점 2020-04-01, −99.0%.** (버킷에는 육상 시추 HP·PTEN·NBR 도 포함 — 그들도 −86~−99%)
- 대표 종목(2013-01~2020-12 최대 낙폭): RIG −99% (2013-02-14→2020-10-30), VALPQ(Ensco/Valaris) −100%, SDLPQ(Seadrill Partners) −100%,
  ORIG −100% (→2018-05), PACDQ −100%, NADLQ −99%, HEROQ −99% (→2015-09), ATW −91% (→2016-02, 2017 Ensco 피인수), RDC −79%;
  육상: NBR −99%, PTEN −95%, HP −86%.
- 판정 시점(2016-02-29) 이후: RIG 최대 +83% 후 2020-12 −73%; VALPQ −100%; PACDQ −100%; ATW +35% (피인수 시점).

## 6. evidence

| id | claim | source_url | date | reliability |
|---|---|---|---|---|
| E1 | 오프쇼어 리그 가동 2014-08→2015-08 −20%; 계약 플로터 280→225, 가동률 85→72%; 잭업 450→390; 플로터 38기 해체; 건조 중 200기+; 스택 150→275 (IHS) | https://drillingcontractor.org/offshore-drilling-industry-must-cooperate-to-recalibrate-market-37392 | 2015-10-26 | medium |
| E2 | 해상 원유 생산 최근 10년 26–27 mb/d 정체, 점유율 하락; 현재 27 mb/d | https://iea.blob.core.windows.net/assets/f4694056-8223-4b14-b688-164d6407bf03/WEO_2018_Special_Report_Offshore_Energy_Outlook.pdf | 2018-05 | high |
| E3 | Hercules Offshore Ch.11 2015-08-13 | https://www.sec.gov/Archives/edgar/data/0001330849/000133084915000082/a8koctober2015chap11confir.htm | 2015-10 | high |
| E4 | Vantage Drilling Ch.11 2015-12-03 | https://globalrestructuringreview.com/article/vantage-drilling-files-24-chapter-11-cases-restructuring-plan | 2015-12 | medium |
| E5 | Paragon Offshore Ch.11 2016-02-14 | https://www.sec.gov/Archives/edgar/data/1594590/000114036116052391/form8k.htm | 2016-02-12 | high |
| E6 | WoodMac: 지연 프로젝트 68건, $380B, 평균 손익분기 $62/boe, 심해가 절반 이상(17→29건) | https://www.rigzone.com/news/wood_mackenzie_68_upstream_projects_deferred_deepwater_hardest_hit-13-jan-2016-142478-article/ | 2016-01-13 | medium |
| E7 | 2016 셰일 신규 유정 손익분기 $54 (Dallas Fed Energy Survey, 2018Q1 보고서의 연도별 비교) | https://www.dallasfed.org/research/surveys/des/2018/1801 | 2018-03 | high (요약 인용) |
| E8 | 2012-13 UDW 계약 일당 $530k–$640k+ (Noble Jim Day $530k, Deepwater Champion $640k 등) | http://www.drillingcontractor.org/global-deepwater-exploration-sustains-strong-rig-activity-15695 | 2012-04-24 | medium |
| E9 | 일당 고점 대비 −60~70%, 2017 UDW 드릴십 $135–206k; 2014 이후 64기 콜드스택, 2016 24기 퇴역 | https://drillingcontractor.org/deepwater-drilling-segment-reaches-nadir-in-2017-may-see-beginnings-of-a-steady-recovery-in-2018-44729 | 2017-11-02 | medium |
| E10 | Seadrill 2015 말 이자부채 $11.1B (담보 $8.3B), 신조 잔금 $5B | https://www.nasdaq.com/articles/seadrills-potential-debt-time-bomb-3-vitally-important-things-investors-need-know-now-2015 | 2015 | medium |
| E11 | Valaris Ch.11 2020-08-19: 자산 ~$13B, 부채 ~$7.85B; Noble·Diamond 도 2020 파산 | https://www.worldoil.com/news/2020/8/19/valaris-world-s-largest-offshore-rig-owner-declares-bankruptcy | 2020-08-19 | medium |
| E12 | Pacific Drilling Ch.11 2020-11 ($1.1B 채권 소거) | https://www.offshore-energy.biz/pacific-drilling-files-for-chapter-11-to-eliminate-1-1-billion-of-debt/ | 2020-11 | medium |
| E13 | `offshore_drilling` EW 낙폭 −99.0%, 전방 수익률, 대표 종목 | 저장소 L1 패널 + `prices` (store_end 2026-08-14) | 2026-08-23 | high (내부 계산) |

## 7. 미검증·한계

- 축 1 의 리그 카운트 10년 CAGR (Baker Hughes 연평균 시계열)을 확보하지 못했다 → `verified: false`. 확보되면 축 1 이
  사망으로 바뀌어 자동 기각될 가능성이 높다 — 그래도 결론(편입 불가)은 같다.
- 버킷이 육상 시추를 포함한다(`themes.yaml` 주석). 낙폭 −99.0% 는 오프쇼어+육상 합산이며, 오프쇼어만 떼면 더 나쁘다(전원 −99~−100%).
- 2016-17 반등(+62%)은 실제로 존재했다. 이 케이스는 "차트·원가곡선만으로는 진입 가능 반등과 구분되지 않는다" 는 것을 보여주는
  사례이지, 판별기가 반등을 부정했다는 사례가 아니다.
