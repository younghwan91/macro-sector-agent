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

| 테이블 | 이 저장소에서 쓰는 필드 | 주의 |
|---|---|---|
| `SF1` (ARQ/ART) | `revenue`, `ebitda`, `ebit`, `capex`, `depamor`, `assets`, `equity`, `ncfo`, `fcf`, `debt`, `cashneq`, `intexp`, `sharesbas`, `roic`, `grossmargin`, `ev`, `evebitda`, `pb`, `ps` | `assetsavg`·`equityavg` 는 ARQ 에서 **전부 null** — 직접 계산 |
| `SEP` | `close`, `closeadj`, `volume` | 배당 재투자는 `closeadj` |
| `DAILY` | `marketcap`, `ev`, `pe`, `pb`, `ps`, `evebitda` | **`marketcap`·`ev` 는 백만 달러 단위** (SF1 은 달러). 미환산 시 10⁶배 왜곡 |
| `TICKERS` | `sector`, `industry`, `sicsector`, `siccode`, `category`, `location`, `firstpricedate`, `lastpricedate` | 테마 버킷 매칭의 원천 |
| `ACTIONS` | `action`, `date`, `ticker` | `exit_count` / `entry_count` (자본 사이클 E 블록) |
| `SFP` | ETF `close`, `closeadj` | 프록시 |

**`category` 필터**: 보통주만 (`Domestic Common Stock`, `ADR Common Stock`).
워런트·우선주·2종주는 `DAILY` 가 시총을 주지 않아 테마 집계를 오염시킨다.
제외한 종목 수를 **반드시 로그로 남긴다** (`CLAUDE.md` §2).

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
| `ACTIONS` 테이블 | 자본 사이클 E 블록의 `exit_count`/`entry_count` | 스토어에 테이블 존재 여부 |
| `SFP` (ETF 가격) | 테마 ETF 프록시 ~60종 | `SPY` 외 ETF 가 있는지 |
| `TICKERS.industry` 전체 | 테마 버킷 매칭 | `select count(distinct industry) from tickers` |
| FRED 시리즈 24종 | L2 | 신규 (§3) |
| 1997년 이전 | 사이클 2바퀴를 보려면 부족할 수 있음 | Sharadar SEP 는 1997-12-31 시작 — **한계로 수용**하고 문서화 |

> **마지막 항목이 이 저장소의 근본적 제약이다.** SEP 가 1998년부터라
> 1970년대 원자재 사이클, 1980년대 디스인플레이션은 관측할 수 없다.
> 10년 백분위는 계산되지만 "역사적 저점" 이라는 표현은 **1998년 이후 저점**을 뜻한다.
> 리포트는 이 사실을 매번 표기한다.

### 6.3 M1 완료 판정
- [ ] 스토어 접속 · 행수·기간이 벌크 원본과 일치 (조용한 절단 없음)
- [ ] `ACTIONS`·`SFP`·`TICKERS.industry` 적재 완료
- [ ] FRED 시리즈 24종 적재 + 발표 지연 실측 표 작성 (§3 의 "확인 필요" 3건 해소)
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
