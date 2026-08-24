# 08 · 데이터 계약과 부트스트랩

## 1. 소스

| 소스 | 테이블/시리즈 | 쓰는 곳 | 키 |
|---|---|---|---|
| **Sharadar** (직판 API + 벌크 CSV) | `SF1` 분기재무 · `SEP` 일별가격 · `DAILY` 시총/EV · `TICKERS` 섹터·산업 메타 · `ACTIONS` 상폐/파산/합병 · `SP500` 편입이력 · `SFP` ETF 가격 | L1 전 블록, L4 전 축 | `SHARADAR_API_KEY` |
| **FRED** | §3 (CPI + 테마 `physical_ref`) | L1 축 1 실물 참조·CPI — 선택 | `FRED_API_KEY` (무료) |
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

> **개정 2026-08-23.** L2 거시 계층이 제거되면서 드라이버 24종 표는 여기서 빠졌다 — 원문은
> `docs/archive/fred-driver-series.md`, 결정은 `docs/13` §9 · `journal/2026-08-23-l2-removed.md`.
> FRED 는 이제 **L1 축 1(단위 수요, `docs/04` 축 1)의 선택적 소스**로만 남는다.

L1 이 쓰는 FRED 시리즈는 두 종류뿐이고, 목록은 코드가 테마 정본에서 푼다
(`msa.data.fred.l1_series()` = `L1_SERIES` + `state/themes.yaml` 의 `physical_ref.source == fred`).

| 용도 | 시리즈 | 어디서 | 없으면 |
|---|---|---|---|
| CPI — `dd_real`(A 블록)·`nominal` 참조의 실질화 | `CPIAUCSL` | `msa.l1.physical.CPI_SERIES` | `cpi: missing` — 실질화 생략을 리포트에 표시 |
| 축 1 실물 참조 (테마별 단위 시리즈) | `state/themes.yaml` 의 `physical_ref` — 2026-08-23 기준 19 테마 · 16 시리즈 (`PALUMUSDM`·`PIORECRUSDM`·`PCOALAUUSDM`·`WPU0652`·`WPU0811`·`WPU061`·`IPN32731S`·`WGFUPUS2`·`RAILFRTCARLOADSD11`·`TRUCKD11`·`AIRRPMTSID11`·`ALTSALES`·`HOUST`·`EXHOSLUSM495S`·`MRTSSM4521USS`·`IPG2211S`) | `msa.l1.physical.load_fred_series` | 해당 테마 `axis1_status = data_missing` (`docs/09` §5) |

캐시는 `state/physical/fred/<SYMBOL>.csv` (`msa data fred-fetch`, 키 필요). 키가 없으면 받지 않고
**캐시에 없는 시리즈는 `data_missing` 으로 남는다** — 조용히 0 으로 채우지 않는다. 발표 지연·개정은
`msa data fred-lag`(ALFRED 빈티지는 `--vintage YYYY-MM-DD`)가 같은 목록에 대해 잰다; `CPIAUCSL` 은
계절조정 개정(매년 2월)이 있다는 것만 미리 안다.

## 4. PIT 정책 — `portfolio-research` 와 갈리는 지점

백테스트를 하지 않으므로 look-ahead 개념이 성립하지 않는다. **그러나 완화 범위는 좁다.**

| 지표 | PIT | 이유 |
|---|---|---|
| 자기이력 백분위 (밸류·ROIC·마진) | **필요** | 과거 시점 값을 정정치로 계산하면 백분위 분포가 왜곡되어 **오늘의 순위**가 틀어진다 |
| 자본 사이클 시계열 (`capex_to_da`, `asset_growth`) | **필요** | 좌동 |
| 테마 지수 구성 (폐지 종목 포함) | **필요** | 생존 편향 — `01-theme-universe.md` §5 |
| 오늘의 스냅샷 (런웨이, 만기벽, 부채비율) | 불필요 | 최신 정정치가 오히려 정확 |
| FRED 실물 참조·CPI (L1 축 1) | 불필요 — 최신 개정치 | 단위 수요의 10년 CAGR 판정이라 개정 전 값이 더 정확하지 않다. (옛 L2 국면 판정의 "PIT 권장" 은 L2 와 함께 빠졌다) |

> 코드는 각 지표가 어느 쪽인지 **명시**한다. 애매하게 두면 몇 달 뒤 백분위가 조용히 틀어진다.
> `portfolio-research` 의 `PanelContext` 는 PIT 를 강제하므로, 완화가 필요한 스냅샷 지표는
> **별도 경로**로 읽는다 — 강제를 우회하는 코드를 `PanelContext` 안에 넣지 않는다.

### 4.1 이 스토어에는 재보고 빈티지가 없다 — 2026-08-24 실측

**`(ticker, calendardate)` 당 `datekey` 는 655,000행 전부 유일하다.** 즉 같은 분기가 두 번
보고된 행이 스토어에 하나도 없다 (`select count(*), count(distinct (ticker, calendardate))
from fundamentals where dimension = 'ARQ'` → `655000, 655000`).

결과: `datekey` 기준 필터와 "최초 보고분만" 규칙(`msa.data.pit`)이 실제로 거르는 것은
**시점(언제 알 수 있었나)뿐이고, 금액은 벤더가 마지막으로 정정한 값**이다. 분기 재보고·
restatement 가 있었다면 그 이전 판은 이 스토어에 없다.

- **타이밍은 PIT 다** — `datekey ≤ asof` 로 미래 발표를 보지 않는 것은 그대로 성립한다.
- **금액은 PIT 가 아니다** — 2005년 시점에 사람이 봤을 매출이 아니라 오늘의 정정치다.
- 이것은 **재적재 없이 고칠 수 없는 한계**다. 벤더의 빈티지 스냅샷(ARQ 의 과거 판)을 따로
  받아 적재해야 하고, 그건 새 데이터 계약이다. 지금은 **한계로 적어 둔다.**
- 영향 범위: `docs/10` §2 백테스트 경로의 IC 는 이만큼 낙관 쪽으로 편향될 수 있다
  (restatement 가 잦은 종목·시기일수록). L1 의 "오늘의 스캔" 경로는 자기이력 백분위의
  분포 왜곡으로만 나타난다.

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
| FRED CPI + 축 1 실물 참조 (§3) | L1 | **미해결** — `FRED_API_KEY` 가 환경에 없어 캐시가 비어 있다. 축 1 은 `data_missing` 으로 돈다 (드라이버 24종 요구는 L2 와 함께 빠졌다) |
| 1997년 이전 | 사이클 2바퀴를 보려면 부족할 수 있음 | Sharadar SEP 는 1997-12-31 시작 — **한계로 수용**하고 문서화 |

> **마지막 항목이 이 저장소의 근본적 제약이다.** SEP 가 1998년부터라
> 1970년대 원자재 사이클, 1980년대 디스인플레이션은 관측할 수 없다.
> 10년 백분위는 계산되지만 "역사적 저점" 이라는 표현은 **1998년 이후 저점**을 뜻한다.
> 리포트는 이 사실을 매번 표기한다.

### 6.3 M1 완료 판정
- [ ] 스토어 접속 · 행수·기간이 **벌크 원본과 일치** (조용한 절단 없음) — §2.1, `msa data status`
      — **2026-08-24 정정: `[x]` 였으나 근거가 없다.** `msa data status` 는 DuckDB 만 조회하고
        `~/data/sharadar/*.csv.zip` 을 열지 않는다 (`cli.py` `data_status` — `--etf` 를 줄 때
        `funds.csv.zip` 을 스캔하는 것이 유일한 원본 접촉이고, 그것도 행수 대조가 아니다).
        즉 "스토어 접속·행수·기간" 까지는 확인됐지만 **"벌크 원본과 일치" 는 한 번도 대조된 적이
        없다.** 대조하려면 zip 을 열어 행수를 세는 코드가 필요하고, 그건 아직 없다
- [ ] `ACTIONS`·`SFP`·`TICKERS.industry` 적재 완료
      — `ACTIONS`·`TICKERS.industry` 는 있다. **`SFP` 는 스토어에 없다** (§2.1 #10).
        벌크 `funds.csv.zip` 직독으로 우회했고 프록시 21종은 전부 확인됐다.
        스토어 적재는 M2 로 넘긴다
- [ ] FRED 시리즈 적재 + 발표 지연 실측 — **2026-08-23 개정:** 대상은 §3 의 CPI + 축 1 실물 참조
      (`l1_series()`, 17종)뿐이다. 드라이버 24종·`hyperscaler_capex` 검증은 L2 와 함께 빠졌다
      (`docs/archive/fred-driver-series.md`). **키 미보유로 미착수.** 어댑터(`msa.data.fred`)와
      명령(`msa data fred-fetch`·`fred-lag`)은 준비됐다
- [ ] 커버리지 감사(`01-theme-universe.md` §5) 전 항목 통과

## 7. 조용한 절단 금지 (승계)

`portfolio-research` 의 지배적 실패 유형이며 이 저장소도 같은 API 를 쓴다.

- 페이지네이션은 "빈 응답" 이 아니라 **기대 범위 도달**로 종료를 판정한다
- 필터·조인·병합 후 행 수가 줄면 로그
- 티커 청크는 **30개 상한** (벤더 하드 리밋)
- `limit` (10,000) 도달 응답은 **절단 의심**으로 다룬다
- 테마 집계에서 제외된 종목 수(적자·시총결측·category 필터)를 **매번 리포트**한다
