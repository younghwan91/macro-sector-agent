# L2 엣지 부호 일치율 실측 (`docs/10-validation.md` §2.1 · `docs/03` §6)

생성: `msa macro` · 기준일 2026-07-31 · DAG state/macro-dag.yaml

**세는 것이지 고치는 것이 아니다.** 이 표를 보고 `sign` 이나 `strength` 를 바꾸지 않는다 (`CLAUDE.md` §1). 불일치 엣지는 `docs/03` §6 의 절차(사람 검토 → 서술 수정 → 커밋 근거)를 거친다.

## 방법

- x = 드라이버 측정값(발표 지연 반영 as-of transform), y = 테마 EW 지수의 **전방 12개월 초과수익**(vs SPY)
- 36·60개월 롤링 Pearson 상관의 **부호가 선언 `sign` 과 같은 창의 비율**. 전방수익이 겹쳐 자기상관이 크므로 검정이 아니다
- 플래그는 최신 창 기준: `CONTRADICTED` (반대 부호 & |corr|>0.3) · `NO_SIGNAL` (|corr|<0.1) · `CONSISTENT` · `UNAVAILABLE`
- 테마 지수: L1 패널 캐시 (`state/cache/l1_panel_*`), 드라이버: `state/physical/fred/*.csv` (최신 개정치 — ALFRED 빈티지 아님)

## 요약

| 항목 | 값 |
|---|---|
| 테마-엣지 쌍 (공통 인자 제외) | 451 |
| 계산된 쌍 | 29 |
| 엣지 | 83 (계산된 엣지 6) |
| 36개월 창 평균 일치율 | 37.7% · 플래그 CONSISTENT 15 / NO_SIGNAL 10 / CONTRADICTED 4 / UNAVAILABLE 422 |
| 60개월 창 평균 일치율 | 35.9% · 플래그 CONSISTENT 18 / NO_SIGNAL 5 / CONTRADICTED 6 / UNAVAILABLE 422 |

## 실행 결과: **부분 실행** — 29/451 쌍만 계산

422쌍은 드라이버 측정값이 없어 계산하지 못했다 (드라이버 20개: `breakeven_10y`, `capex_orders_core`, `china_credit_impulse`, `china_property`, `cpi_yoy`, `defense_outlays`, `dollar_broad`, `employment`, `housing_starts`, `hy_spread`, `ig_spread`, `industrial_production`, `inventory_sales`, `nat_gas`, `new_orders_mfg`, `oil_wti`, `policy_events`, `ppi_yoy`, `real_rate_10y`, `term_spread`). 아래 요약·엣지 표의 평균은 **계산된 쌍만의 값**이며 DAG 전체를 대표하지 않는다. FRED 기반 드라이버는 `FRED_API_KEY` 가 설정되면 채워진다:

```bash
export FRED_API_KEY=...
uv run msa data fred-fetch          # DRIVER_SERIES + physical_ref + CPIAUCSL 캐시
uv run msa macro --doc-out docs/macro-dag-sign-check.md
```

수동 드라이버(`china_*`)는 `state/physical/manual/<id>.csv`, `policy_events` 는 시계열이 아니라 이 검정의 대상이 아니다.

## 드라이버별 가용성

| 드라이버 | 쌍 | 계산됨 | 이유 |
|---|---|---|---|
| `breakeven_10y` | 9 | 0 | 드라이버 breakeven_10y 측정값 없음 — T10YIE: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/T10YIE.csv |
| `capex_orders_core` | 16 | 0 | 드라이버 capex_orders_core 측정값 없음 — NEWORDER: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/NEWORDER.csv |
| `china_credit_impulse` | 15 | 0 | 드라이버 china_credit_impulse 측정값 없음 — 파일 없음 state/physical/manual/china_credit_impulse.csv |
| `china_property` | 9 | 0 | 드라이버 china_property 측정값 없음 — 파일 없음 state/physical/manual/china_property.csv |
| `copper_price` | 7 | 7 |  |
| `cpi_yoy` | 26 | 0 | 드라이버 cpi_yoy 측정값 없음 — CPIAUCSL: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/CPIAUCSL.csv |
| `defense_outlays` | 8 | 0 | 드라이버 defense_outlays 측정값 없음 — FDEFX: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/FDEFX.csv |
| `dollar_broad` | 25 | 0 | 드라이버 dollar_broad 측정값 없음 — DTWEXBGS: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/DTWEXBGS.csv |
| `employment` | 50 | 0 | 드라이버 employment 측정값 없음 — PAYEMS: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/PAYEMS.csv · UNRATE: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/UNRATE.csv |
| `gold_price` | 3 | 3 |  |
| `housing_starts` | 15 | 0 | 드라이버 housing_starts 측정값 없음 — HOUST: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/HOUST.csv |
| `hy_spread` | 35 | 0 | 드라이버 hy_spread 측정값 없음 — BAMLH0A0HYM2: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/BAMLH0A0HYM2.csv |
| `hyperscaler_capex` | 19 | 19 |  |
| `ig_spread` | 11 | 0 | 드라이버 ig_spread 측정값 없음 — BAMLC0A0CM: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/BAMLC0A0CM.csv |
| `industrial_production` | 20 | 0 | 드라이버 industrial_production 측정값 없음 — INDPRO: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/INDPRO.csv |
| `inventory_sales` | 18 | 0 | 드라이버 inventory_sales 측정값 없음 — ISRATIO: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/ISRATIO.csv |
| `nat_gas` | 12 | 0 | 드라이버 nat_gas 측정값 없음 — DHHNGSP: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/DHHNGSP.csv |
| `new_orders_mfg` | 11 | 0 | 드라이버 new_orders_mfg 측정값 없음 — AMTMNO: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/AMTMNO.csv |
| `oil_wti` | 21 | 0 | 드라이버 oil_wti 측정값 없음 — DCOILWTICO: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/DCOILWTICO.csv |
| `policy_events` | 41 | 0 | policy_events 는 시계열이 아니다 |
| `ppi_yoy` | 11 | 0 | 드라이버 ppi_yoy 측정값 없음 — PPIACO: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/PPIACO.csv |
| `real_rate_10y` | 64 | 0 | 드라이버 real_rate_10y 측정값 없음 — DFII10: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/DFII10.csv |
| `term_spread` | 5 | 0 | 드라이버 term_spread 측정값 없음 — T10Y2Y: FRED_API_KEY 없음 · 캐시 없음 state/physical/fred/T10Y2Y.csv |

## 엣지별

| 엣지 | from | sign | 강도 | 테마 | 계산됨 | 일치율 36M | 창수 | C/N/K 36M | 일치율 60M | 창수 | C/N/K 60M |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | `dollar_broad` | -1 | strong | 11 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 1 | `dollar_broad` | -1 | moderate | 4 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 2 | `dollar_broad` | -1 | moderate | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 3 | `dollar_broad` | -1 | weak | 7 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 4 | `dollar_broad` | +1 | weak | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 5 | `real_rate_10y` | -1 | strong | 3 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 6 | `real_rate_10y` | -1 | strong | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 7 | `real_rate_10y` | -1 | strong | 6 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 8 | `real_rate_10y` | -1 | strong | 10 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 9 | `real_rate_10y` | -1 | moderate | 8 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 10 | `real_rate_10y` | -1 | moderate | 9 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 11 | `real_rate_10y` | -1 | strong | 9 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 12 | `real_rate_10y` | -1 | moderate | 8 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 13 | `real_rate_10y` | -1 | moderate | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 14 | `real_rate_10y` | +1 | moderate | 4 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 15 | `real_rate_10y` | -1 | moderate | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 16 | `real_rate_10y` | -1 | weak | 3 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 17 | `term_spread` | +1 | strong | 3 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 18 | `term_spread` | +1 | moderate | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 19 | `breakeven_10y` | +1 | moderate | 7 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 20 | `breakeven_10y` | +1 | weak | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 21 | `hy_spread` | -1 | strong | 9 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 22 | `hy_spread` | -1 | moderate | 14 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 23 | `hy_spread` | -1 | weak | 10 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 24 | `ig_spread` | -1 | moderate | 11 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 25 | `inventory_sales` | -1 | strong | 7 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 26 | `inventory_sales` | -1 | moderate | 10 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 27 | `inventory_sales` | -1 | weak | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 28 | `new_orders_mfg` | +1 | moderate | 10 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 29 | `capex_orders_core` | +1 | moderate | 13 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 30 | `capex_orders_core` | +1 | weak | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 31 | `industrial_production` | +1 | moderate | 18 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 32 | `industrial_production` | +1 | weak | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 33 | `housing_starts` | +1 | strong | 9 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 34 | `housing_starts` | +1 | weak | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 35 | `housing_starts` | -1 | moderate | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 36 | `employment` | +1 | strong | 28 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 37 | `employment` | +1 | moderate | 4 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 38 | `employment` | +1 | weak | 11 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 39 | `oil_wti` | +1 | strong | 6 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 40 | `oil_wti` | -1 | moderate | 7 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 41 | `oil_wti` | -1 | weak | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 42 | `oil_wti` | -1 | moderate | 5 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 43 | `oil_wti` | +1 | weak | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 44 | `nat_gas` | +1 | strong | 4 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 45 | `nat_gas` | -1 | moderate | 6 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 46 | `nat_gas` | +1 | weak | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 47 | `copper_price` | +1 | strong | 3 | 3 | 28% | 375 | 0/3/0 | 31% | 303 | 0/1/2 |
| 48 | `copper_price` | -1 | weak | 4 | 4 | 65% | 431 | 0/2/2 | 86% | 335 | 1/2/1 |
| 49 | `gold_price` | +1 | strong | 3 | 3 | 36% | 627 | 0/0/3 | 36% | 555 | 0/0/3 |
| 50 | `cpi_yoy` | -1 | moderate | 12 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 51 | `cpi_yoy` | -1 | moderate | 4 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 52 | `cpi_yoy` | +1 | weak | 8 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 53 | `ppi_yoy` | +1 | moderate | 3 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 54 | `ppi_yoy` | -1 | moderate | 4 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 55 | `ppi_yoy` | -1 | moderate | 3 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 56 | `china_credit_impulse` | +1 | strong | 9 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 57 | `china_credit_impulse` | +1 | weak | 6 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 58 | `china_property` | +1 | strong | 5 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 59 | `china_property` | +1 | weak | 4 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 60 | `defense_outlays` | +1 | strong | 3 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 61 | `defense_outlays` | +1 | weak | 5 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 62 | `hyperscaler_capex` | +1 | strong | 7 | 7 | 28% | 728 | 0/2/5 | 20% | 560 | 0/1/6 |
| 63 | `hyperscaler_capex` | +1 | moderate | 9 | 9 | 27% | 936 | 4/1/4 | 16% | 720 | 5/1/3 |
| 64 | `hyperscaler_capex` | +1 | weak | 3 | 3 | 66% | 312 | 0/2/1 | 69% | 240 | 0/0/3 |
| 65 | `policy_events` | +1 | strong | 11 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 66 | `policy_events` | -1 | moderate | 12 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 67 | `policy_events` | +1 | moderate | 9 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 68 | `policy_events` | -1 | weak | 8 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 69 | `employment` | +1 | strong | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 70 | `employment` | +1 | moderate | 3 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 71 | `employment` | -1 | moderate | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 72 | `employment` | +1 | weak | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 73 | `new_orders_mfg` | +1 | weak | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 74 | `capex_orders_core` | +1 | weak | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 75 | `housing_starts` | +1 | moderate | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 76 | `housing_starts` | +1 | weak | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 77 | `hy_spread` | -1 | strong | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 78 | `hy_spread` | -1 | moderate | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 79 | `real_rate_10y` | -1 | moderate | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 80 | `ppi_yoy` | +1 | moderate | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 81 | `cpi_yoy` | +1 | weak | 2 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |
| 82 | `policy_events` | +1 | weak | 1 | 0 | — | 0 | 0/0/0 | — | 0 | 0/0/0 |

C/N/K = 최신 창 기준 CONTRADICTED / NO_SIGNAL / CONSISTENT 인 테마 수.

## 해석 규칙

- 일치율이 낮은 엣지를 **고치지 않는다.** `docs/03` §6 의 세 조치(엣지 서술 수정 · 국면 조건 추가 · 유지)는 사람이 근거를 적고 커밋한다.
- 표본은 사이클 2~3바퀴다. 60개월 창의 개수가 한 자릿수인 엣지는 어느 쪽으로도 말할 수 없다.
- 드라이버 캐시가 최신 개정치라 `INDPRO`·`PAYEMS`(개정 큼) 엣지의 과거 상관은 실시간 판단과 다를 수 있다 (`docs/08` §4).
