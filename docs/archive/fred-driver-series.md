> **L2 제거(2026-08-23) 이전 기록** — `docs/08-data-contract.md` §3 의 원문(L2 드라이버 24종 표). `docs/13-design-question-l2-macro.md` §9 · `journal/2026-08-23-l2-removed.md`. 내용은 손대지 않았다.

# 08 §3 (구) · FRED 시리즈 — L2 드라이버


| id | FRED | 확인 상태 | 발표지연 | 개정 |
|---|---|---|---|---|
| `real_rate_10y` | `DFII10` | 확인됨 | M1 실측 | M1 실측 |
| `term_spread` | `T10Y2Y` | 확인됨 | M1 실측 | M1 실측 |
| `breakeven_10y` | `T10YIE` | 확인됨 | M1 실측 | M1 실측 |
| `dollar_broad` | `DTWEXBGS` | 확인됨 | M1 실측 | M1 실측 |
| `hy_spread` | `BAMLH0A0HYM2` | 확인됨 | M1 실측 | M1 실측 |
| `ig_spread` | `BAMLC0A0CM` | 확인됨 | M1 실측 | M1 실측 |
| `industrial_production` | `INDPRO` | 확인됨 | M1 실측 | **큼** — M1 실측 |
| `new_orders_mfg` | `AMTMNO` | 확인됨 | M1 실측 | M1 실측 |
| `capex_orders_core` | `NEWORDER` | 확인됨 | M1 실측 | M1 실측 |
| `inventory_sales` | `ISRATIO` | 확인됨 | M1 실측 | M1 실측 |
| `housing_starts` | `HOUST` | 확인됨 | M1 실측 | M1 실측 |
| `employment` | `PAYEMS`, `UNRATE` | 확인됨 | M1 실측 | **큼** — M1 실측 |
| `cpi_yoy` | `CPIAUCSL` | 확인됨 | M1 실측 | M1 실측 |
| `ppi_yoy` | `PPIACO` | 확인됨 | M1 실측 | M1 실측 |
| `oil_wti` | `DCOILWTICO` | 확인됨 | M1 실측 | M1 실측 |
| `nat_gas` | `DHHNGSP` | 확인됨 | M1 실측 | M1 실측 |
| `m2_growth` | `M2SL` | 확인됨 | M1 실측 | M1 실측 |
| `usd_liquidity` | `WALCL − WTREGEN − RRPONTSYD` | 파생 — 세 시리즈 주기(주간/주간/일간) 정렬 필요 | M1 실측 | M1 실측 |
| `defense_outlays` | `FDEFX` | **M1 에서 실측 확인 필요** | M1 실측 | M1 실측 |
| `copper_price` | `PCOPPUSDM` | **M1 에서 실측 확인 필요.** 폴백 ETF `CPER` | M1 실측 | M1 실측 |
| `gold_price` | — | FRED 직접 시리즈 불안정 → **ETF `GLD` 프록시 사용** | M1 실측 | M1 실측 |
| `china_credit_impulse` | 없음 | 수동/에이전트 월 갱신 | M1 실측 | M1 실측 |
| `hyperscaler_capex` | 없음 | **Sharadar SF1 에서 직접 계산** (MSFT·GOOGL·AMZN·META·ORCL `capex` 합, YoY). 재무제표라 늦고 정확하다 — 시점은 가이던스가 준다 (`03-macro-dag.md` §2) | **분기말 +4~8주** (실적발표 종료 시점) | M1 실측 |
| `fed_policy_path` | `DFEDTARU` | 확인됨 — 다만 **선물 곡선은 FRED 에 없다**. 정책 경로의 시장 기대는 외부 소스 또는 에이전트 | M1 실측 | M1 실측 |
| `china_property` | 없음 | 수동/에이전트 월 갱신 (착공·판매). `china_credit_impulse` 와 같은 경로 | 해당 없음 | 해당 없음 |
| `policy_events` | 없음 | 에이전트 이벤트 캘린더 (IRA·관세·수출통제·원전 승인). 시계열이 아니라 **날짜 목록**이라 `state_rule` 이 다른 드라이버와 다르다 | 해당 없음 | 해당 없음 |

> "확인됨" 은 시리즈 ID 가 존재한다는 뜻이지, **주기·개정 이력·PIT 특성을 검증했다는 뜻이 아니다.**
> 그래서 `발표지연`·`개정` 두 열을 표에 두고 전부 `M1 실측` 으로 채웠다 — 값을 채워 넣는 대신
> **아직 모른다는 사실을 표 안에서 보이게** 하는 것이 목적이다. 각주로만 두면 표를 읽는 사람이 놓친다.
> M1 에서 각 시리즈의 발표 지연(release lag)과 개정 여부를 실측해 두 열을 채운다.
>
> **M1 결과: 두 열은 채워지지 않았다.** 작업 환경에 `FRED_API_KEY` 가 없어 실측을 돌리지
> 못했다. 키가 없을 때 조용히 건너뛰지 않도록 `msa.config.fred_api_key()` 가 `MissingApiKey`
> 를 던지게 해 뒀고, `msa data status` 는 "API 키 없음 → 두 열 미실측" 을 매번 출력한다.
> 키가 생기면 `uv run msa data fred-lag`(개정까지 보려면 `--vintage 2024-01-02`)가
> 전 시리즈를 한 번에 재고, `uv run pytest -m net` 이 `FDEFX`·`PCOPPUSDM` 존재 여부와
> `INDPRO` 개정을 검증한다. 실패한 시리즈가 하나라도 있으면 `measure_all()` 이 예외를
> 던지므로 **일부만 채워진 표가 완성된 것처럼 보이는 일은 없다.**
> 이미 아는 것 하나: `INDPRO`·`PAYEMS` 는 개정이 크고, 개정 전 값으로 국면을 판정해야
> 실시간 판단과 일치한다 (§4 의 "FRED 국면 판정 PIT 권장" 이 여기서 나온다).

