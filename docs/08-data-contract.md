# 08 · 데이터 계약과 부트스트랩

## 1. 소스

| 소스 | 테이블/시리즈 | 쓰는 곳 | 키 |
|---|---|---|---|
| **Sharadar** (직판 API + 벌크 CSV) | `SF1` 분기재무 · `SEP` 일별가격 · `DAILY` 시총/EV · `TICKERS` 섹터·산업 메타 · `ACTIONS` 상폐/파산/합병 · `SP500` 편입이력 · `SFP` ETF 가격 | L1 전 블록, L4 전 축 | `SHARADAR_API_KEY` |
| **FRED** | §3 시리즈 표 | L2 드라이버 | `FRED_API_KEY` (무료) |
| **ETF 프록시** | Sharadar `SFP` 우선, 없으면 yfinance | L1 지수 프록시 검증 | — |
| **웹 검색** | 에이전트 | L3 | (에이전트 런타임) |

**Nasdaq Data Link** 는 Sharadar 직판 장애 시 폴백. `portfolio-research` 어댑터가 이미 처리한다.

## 2. Sharadar 테이블별 용도

> **아래 표는 Sharadar 벤더 원본의 구조다. 적재된 스토어(`~/data/us_micro.duckdb`)는
> 구조가 다르다** — 테이블이 병합되고, 컬럼명이 바뀌고, 일부는 아예 적재되지 않았다.
> 코드가 따르는 것은 §2.1 의 실측이다. 이 표는 "벤더에서 무엇을 받아 왔는가" 의 기록으로만 읽어라.


| 테이블 | 이 저장소에서 쓰는 필드 | 주의 |
|---|---|---|
| `SF1` (ARQ/ART) | `revenue`, `ebitda`, `ebit`, `capex`, `depamor`, `assets`, `equity`, `ncfo`, `fcf`, `debt`, `cashneq`, `intexp`, `sharesbas`, `roic`, `grossmargin`, `ev`, `evebitda`, `pb`, `ps` | `assetsavg`·`equityavg` 는 ARQ 에서 **전부 null** — 직접 계산 |
| `SEP` | `close`, `closeadj`, `volume` | 배당 재투자는 `closeadj` |
| `DAILY` | `marketcap`, `ev`, `pe`, `pb`, `ps`, `evebitda` | **`marketcap`·`ev` 는 백만 달러 단위** (SF1 은 달러). 미환산 시 10⁶배 왜곡 |
| `TICKERS` | `sector`, `industry`, `sicsector`, `siccode`, `category`, `location`, `firstpricedate`, `lastpricedate` | 테마 버킷 매칭의 원천 |
| `ACTIONS` | `action`, `date`, `ticker` | `exit_count` / `entry_count` (자본 사이클 E 블록) |
| `SFP` | ETF `close`, `closeadj` | 프록시 |

**`category` 필터**: 보통주만. 문서 초안은 `Domestic Common Stock`·`ADR Common Stock`
둘만 적었으나 **실측 결과 이것으로는 부족하다** — §2.1 참조.
워런트·우선주·2종주는 `DAILY` 가 시총을 주지 않아 테마 집계를 오염시킨다.
제외한 종목 수는 로그가 아니라 **반환값**으로 돌린다 (`msa.data.universe.UniverseResult`).
로그는 파이프라인 상류로 올라가지 않아 `CLAUDE.md` §2 를 지키지 못한다.

---

## 2.1 M1 실측 — 문서와 스토어가 다른 지점

M1(2026-08-22)에 `~/data/us_micro.duckdb`(2.1GB)와 벌크 원본을 실측한 결과다.
**코드는 전부 실측 쪽에 맞춰져 있다.** 근거 테스트는 `tests/test_store_data.py`
(`uv run pytest -m data`).

### 스토어의 실제 테이블 8종

| 테이블 | 행수 | 종목 | 기간 |
|---|---:|---:|---|
| `prices` | 45,663,901 | 20,931 | 1997-12-31 ~ 2026-08-14 |
| `institutions` | 669,992 | 31,195 | 2013-08-14 ~ 2026-08-14 |
| `actions` | 665,817 | 30,923 | 1997-12-31 ~ 2026-09-03 |
| `fundamentals` | 655,000 | 17,041 | 1993-12-22 ~ 2026-08-14 (`datekey`) |
| `insiders` | 312,856 | 12,203 | 2008-04-03 ~ 2026-10-03 |
| `sp500` | 59,672 | 1,203 | 1957-03-04 ~ 2026-08-15 |
| `tickers` | 43,919 | 43,919 | — |
| `estimates` | **0** | — | — |

### 문서가 틀렸거나 스토어가 다른 것

| # | 문서 | 실제 | 결과 |
|---|---|---|---|
| 1 | `DAILY` 별도 테이블, `marketcap`·`ev` | **`daily` 테이블 없음.** `prices.mcap`·`prices.ev` 로 병합 | 조회 경로가 하나뿐 |
| 2 | "`DAILY` 의 `marketcap`·`ev` 는 백만 달러 단위 — 미환산 시 10⁶배 왜곡" | **환산이 적재 시점에 이미 끝났다.** 원본 `daily.csv` `AAPL,2026-08-12,marketcap=4411090.9` → 스토어 `mcap=4.4110909e12` | **여기서 다시 곱하면 그때 왜곡이 생긴다.** 경고의 방향이 반대다 |
| 3 | `SEP.closeadj` / `close` | 스토어는 `close`(=원본 `closeadj`, 분할+배당 조정)와 `closeunadj` 두 개. `closeadj` 라는 이름의 컬럼은 없다 | 배당 재투자 수익률은 `close` |
| 4 | `TICKERS.isdelisted` | **`is_delisted`** (Y 18,169 / N 12,520 / NULL 13,230) | NULL 30.1% 는 대부분 `Institutional Investor` 13,230행 — 티커가 아니다 |
| 5 | `TICKERS.sicsector`·`firstpricedate`·`lastpricedate` | **없음** | 상장·폐지 시점은 `actions` 로 구해야 한다 |
| 6 | `DAILY.pe`·`pb`·`ps`·`evebitda` | **적재되지 않았다** (원본 CSV 에는 있다) | 밸류 지표는 `fundamentals` 로 파생 계산 |
| 7 | `SF1` 의 `roic`·`grossmargin`·`ev`·`evebitda`·`pb`·`ps` | **없음** | 파생 계산 대상 |
| 8 | `SF1` ARQ/ART | **`dimension` 은 `ARQ` 뿐** (655,000행 전부) | ART(trailing) 이 필요하면 직접 굴려야 한다 |
| 9 | "`assetsavg`·`equityavg` 는 ARQ 에서 전부 null — 직접 계산" | **맞다.** `invcapavg` 까지 셋 다 655,000행 100% null | 문서가 옳았다. 그대로 유지 |
| 10 | `SFP` (ETF 가격) | **스토어에 없다.** `prices` 안의 ETF 는 `SPY` 하나뿐 | §6.2 의 "SPY 외 ETF 가 있는지" 의 답은 **없다**. 벌크 `funds.csv.zip` 을 직접 읽는다 (`msa.data.store.etf_prices`) |
| 11 | — | `prices.short_interest` 는 **컬럼만 있고 100% null** | 있는 줄 알고 쓰면 L4 토크 축이 조용히 빈다 |
| 12 | — | `estimates` 테이블 **0행** | 컨센서스는 이 스토어에 없다 |
| 13 | — | `prices.mcap`·`ev` 결측 **12.2%** | 시총 결측 종목의 테마 집계 제외 수를 매번 리포트해야 한다 (§7) |
| 14 | — | `actions` 에 미래 날짜 17건(전부 `split`, 2026-08-14 초과) | 예고된 분할이다. `date <= today` 로 자르지 않으면 카운트가 부풀 수 있다 |

### `category` 실측 분포 (43,919행)

| category | 수 | 유니버스 |
|---|---:|---|
| Domestic Common Stock | 13,547 | 포함 |
| Institutional Investor | 13,230 | 제외 — 티커가 아님 |
| ETF | 7,632 | 제외 |
| Domestic Common Stock Primary Class | 2,176 | 포함 |
| ADR Common Stock | 1,850 | 포함 |
| Domestic Common Stock Secondary Class | 1,320 | 포함(유니버스) / 제외(시총 집계) |
| Domestic Preferred Stock | 1,137 | 제외 |
| CEF | 1,072 | 제외 |
| ETD 492 · ETN 414 · CEF Preferred 82 · UNIT 24 · ETMF 18 · IDX 5 · MF 1 | 1,036 | 제외 |
| Canadian Common Stock (+Class 변종 18) | 400 | 제외 — `01-theme-universe.md` §6-3 "순수 해외 상장은 범위 밖" |
| ADR Common Stock Primary/Secondary Class | 424 | 포함 |
| ADR Preferred 92 · Canadian Preferred 3 | 95 | 제외 |

> **문서 초안대로 `Domestic Common Stock`·`ADR Common Stock` 둘만 쓰면 Primary/Secondary
> Class 변종 3,920 종목이 조용히 사라진다.** 그래서 `COMMON_STOCK_CATEGORIES` 는 6종이다.
> 2종주는 같은 기업의 다른 의결권 주식이라 시총 이중계상을 일으키므로, 유니버스에는
> 넣되 **집계 단계에서 `drop_secondary_class()` 로 한 번 더 뺀다** — 유니버스에서 빼는 것과
> 집계에서 빼는 것은 다른 결정이다.
>
> 실측: 보통주 유니버스 **19,317** / 43,919 (제외 24,602) → 2종주 제외 후 집계 유니버스 **17,838**.

### 폐지 종목 포함 감사 (`01-theme-universe.md` §5)

2010-01-01 ~ 2026-08-14 구간에서 `actions.delisted` 인 종목 11,072개 중,
**보통주 7,015개의 99.99%(7,014개)가 `prices` 에 이력을 갖는다.**

- 검사 모집단을 보통주로 한정한 근거: `prices` 는 주식만 담는다. 폐지된 ETF 1,982종은
  전부 `prices` 에 0행이다 — 이것을 한정하지 않으면 감사가 늘 실패하고,
  **늘 실패하는 관문은 곧 무시된다.** 뺀 개수는 category 별로 반환값에 남는다.
- 남은 누락 1건은 `TFSA`(TERRA INCOME FUND 6 LLC) — 비상장 BDC 라 시장가격이 존재하지 않는다.
  `msa data audit` 은 이 1건 때문에 **exit 1 로 실패한다.** 임계값을 넣어 통과시키지 않았다
  (`CLAUDE.md` §1 — 근거 없는 임계값 금지). M2 에서 테마 버킷을 정의할 때
  근거를 적은 명시적 제외 목록으로 처리한다.

### ETF 프록시 — 벌크 `funds.csv.zip`

`docs/01` 의 프록시 21종을 실측한 결과 **전부 존재한다** (zip 1회 스트리밍 스캔, 약 12초).

| ETF | 시작 | ETF | 시작 |
|---|---|---|---|
| SPY | 1997-12-31 | TAN | 2008-04-15 |
| SOXX | 2001-07-13 | COPX·SIL | 2010-04-20 |
| GLD | 2004-11-18 | LIT | 2010-07-23 |
| XBI·XHB | 2006-02-06 | REMX | 2010-10-28 |
| ITA | 2006-05-05 | URA | 2010-11-05 |
| GDX | 2006-05-22 | CPER | 2011-11-15 |
| KRE·XME·XOP | 2006-06-22 | JETS | 2015-04-30 |
| NLR | 2007-08-15 | PAVE | 2017-03-08 |

> `docs/01` §1 이 경고한 "ETF 는 2010년대 상장이 많아 사이클 한 바퀴가 안 담긴다" 가
> 실측으로 확인됐다 — URA·REMX·SIL·LIT 는 전부 2010년, PAVE 는 2017년이다.


## 3. FRED 시리즈

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

## 4. PIT 정책 — `portfolio-research` 와 갈리는 지점

백테스트를 하지 않으므로 look-ahead 개념이 성립하지 않는다. **그러나 완화 범위는 좁다.**

| 지표 | PIT | 이유 |
|---|---|---|
| 자기이력 백분위 (밸류·ROIC·마진) | **필요** | 과거 시점 값을 정정치로 계산하면 백분위 분포가 왜곡되어 **오늘의 순위**가 틀어진다 |
| 자본 사이클 시계열 (`capex_to_da`, `asset_growth`) | **필요** | 좌동 |
| 테마 지수 구성 (폐지 종목 포함) | **필요** | 생존 편향 — `01-theme-universe.md` §5 |
| 오늘의 스냅샷 (런웨이, 만기벽, 부채비율) | 불필요 | 최신 정정치가 오히려 정확 |
| FRED 국면 판정 | **권장** | 개정 전 값으로 판정해야 실시간과 일치. M1 에서 ALFRED 사용 여부 결정 |

> 코드는 각 지표가 어느 쪽인지 **명시**한다. 애매하게 두면 몇 달 뒤 백분위가 조용히 틀어진다.
> `portfolio-research` 의 `PanelContext` 는 PIT 를 강제하므로, 완화가 필요한 스냅샷 지표는
> **별도 경로**로 읽는다 — 강제를 우회하는 코드를 `PanelContext` 안에 넣지 않는다.

## 5. 재사용 경계

| 원본 | 가져오는 파일 | 방식 |
|---|---|---|
| `portfolio-research` | `factor/data/sharadar.py`, `factor/data/store.py`, `factor/data/schema.py`, `factor/data/provider.py`, `taa/signals.py` | **vendoring** — `src/msa/vendor/` 아래. 헤더에 출처 저장소·커밋 해시·복사 일자 기재 |
| `momentum` | `indicators.py`, `VCP.py`, `filters.py` (Stage/RS/VCP 부분) | vendoring + 지수 레벨 승격 래퍼 |
| `fin-checkup` | `metrics/redflags.py`, `alerts/telegram.py`, `alerts/scheduler.py` | vendoring |

**의존이 아니라 복사인 이유**: 세 저장소는 각자의 규약과 릴리스 주기를 갖고,
git 의존으로 묶으면 `portfolio-research` 의 "서브시스템 간 import 금지" 규약이 우회된다.
복사본은 **독립 진화**하며, 상류 변경을 자동 반영하지 않는다 (변경이 필요하면 사람이 판단).

## 6. 부트스트랩 절차 — Sharadar 스토어가 있는 머신에서

> 이 절차가 M1 의 전부다. 코딩은 여기서 시작한다.

### 6.1 전제 확인
```sh
# 1) 기존 portfolio-research 스토어 위치와 규모 확인
ls -la ~/data/sharadar/
python -c "import duckdb; c=duckdb.connect('<store>.duckdb','r'); \
  print(c.execute('select count(distinct ticker), min(date), max(date), count(*) from prices').fetchall())"

# 기대: 종목 20,000+ · 1997-12-31 ~ 최근 거래일 · 4,500만 행 내외
# ※ 이 숫자는 고정 상수가 아니다 — 벤더 벌크가 바뀐다.
#    판정은 숫자 대조가 아니라 원본(벌크 CSV) 대조로 한다.

# 2) 원본 벌크의 종목 수 (스토어가 가져야 할 수)
unzip -p ~/data/sharadar/raw/stocks.csv.zip | awk -F, 'NR>1{a[$1]}END{print length(a)}'

# 3) API 키
echo "${SHARADAR_API_KEY:+SHARADAR ok}" "${FRED_API_KEY:+FRED ok}"
```

### 6.2 이 저장소가 추가로 필요로 하는 것

`portfolio-research` 스토어에 **없을 가능성이 높은** 것들. M1 에서 적재한다.

| 필요 | 왜 | 확인 방법 |
|---|---|---|
| `ACTIONS` 테이블 | 자본 사이클 E 블록의 `exit_count`/`entry_count` | **있다** — 665,817행, `action` 19종 |
| `SFP` (ETF 가격) | 테마 ETF 프록시 ~60종 | **없다** — `prices` 안의 ETF 는 `SPY` 뿐. 벌크 `funds.csv.zip` 에서 읽는다 (§2.1) |
| `TICKERS.industry` 전체 | 테마 버킷 매칭 | **있다** — `industry` 152종, `sector` 11종. 다만 결측 51.6% (대부분 `Institutional Investor` 행) |
| FRED 시리즈 24종 | L2 | **미해결** — `FRED_API_KEY` 가 환경에 없어 실측하지 못했다 |
| 1997년 이전 | 사이클 2바퀴를 보려면 부족할 수 있음 | Sharadar SEP 는 1997-12-31 시작 — **한계로 수용**하고 문서화 |

> **마지막 항목이 이 저장소의 근본적 제약이다.** SEP 가 1998년부터라
> 1970년대 원자재 사이클, 1980년대 디스인플레이션은 관측할 수 없다.
> 10년 백분위는 계산되지만 "역사적 저점" 이라는 표현은 **1998년 이후 저점**을 뜻한다.
> 리포트는 이 사실을 매번 표기한다.

### 6.3 M1 완료 판정
- [x] 스토어 접속 · 행수·기간이 벌크 원본과 일치 (조용한 절단 없음) — §2.1, `msa data status`
- [ ] `ACTIONS`·`SFP`·`TICKERS.industry` 적재 완료
      — `ACTIONS`·`TICKERS.industry` 는 있다. **`SFP` 는 스토어에 없다** (§2.1 #10).
        벌크 `funds.csv.zip` 직독으로 우회했고 프록시 21종은 전부 확인됐다.
        스토어 적재는 M2 로 넘긴다
- [ ] FRED 시리즈 24종 적재 + 발표 지연 실측 표 작성 (§3 의 "확인 필요" 3건 해소)
      — **키 미보유로 미착수.** 어댑터(`msa.data.fred`)와 명령(`msa data fred-lag`)은 준비됐다
      — 24 = §3 표의 FRED 직접 시리즈 20 + `usd_liquidity` 파생 3(`WALCL`·`WTREGEN`·`RRPONTSYD`) + `DFEDTARU`.
      드라이버 26개 중 나머지 2개(`china_property`·`policy_events`)와 `china_credit_impulse`·`gold_price`·`hyperscaler_capex` 는 FRED 밖이다
- [ ] **§3 표의 `발표지연`·`개정` 두 열에 `M1 실측` 이 하나도 남지 않음** (전 시리즈 실측 완료)
- [ ] `hyperscaler_capex` 파생 계산 검증 (5사 capex 합이 공개 수치와 일치)
- [ ] 커버리지 감사(`01-theme-universe.md` §5) 전 항목 통과

## 7. 조용한 절단 금지 (승계)

`portfolio-research` 의 지배적 실패 유형이며 이 저장소도 같은 API 를 쓴다.

- 페이지네이션은 "빈 응답" 이 아니라 **기대 범위 도달**로 종료를 판정한다
- 필터·조인·병합 후 행 수가 줄면 로그
- 티커 청크는 **30개 상한** (벤더 하드 리밋)
- `limit` (10,000) 도달 응답은 **절단 의심**으로 다룬다
- 테마 집계에서 제외된 종목 수(적자·시총결측·category 필터)를 **매번 리포트**한다
