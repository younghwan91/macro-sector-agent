# 13 · 설계 질문 2 — 거시(L2)는 선별 기준인가, 조건(오버레이)인가 — "바로 L1 로 가도 되는가"

> **지위: 설계 질문의 기록이다. 결정이 아니다.** 이 문서는 `docs/03` 의 가중치(0.70/0.30)·하드 규칙(−0.5)·
> 엣지 부호·강도·코드를 바꾸지 않고, 바꾸라고도 하지 않는다 (`CLAUDE.md` §1, `docs/10-validation.md` §2.4·§8).
> 하는 일은 셋이다 — L2 가 **오늘 실제로 하는 일**을 선언과 대조하고, 선언 자신의 서술을 다시 읽고,
> **결정 절차를 사전에 고정**한다. 결정은 사람이 하고, 그 결정은 별도 커밋이다. 성과 수치는 어디에도 없다
> (`CLAUDE.md` §7) — 외부 문헌의 수치는 그 문헌의 주장으로 인용할 뿐 이 저장소의 주장이 아니다.

작성 2026-08-23. 질문의 원문: **"매크로(L2)를 분석하는 게 정말 필요한가? 바로 산업 사이클(L1)로 가는 게 낫지 않나?"**
출처: `docs/00-overview.md` §3, `docs/03-macro-dag.md` §1·§4·§5·§6·§8, `docs/macro-dag-sign-check.md`,
`docs/11-roadmap.md` M4, `docs/backtest-l1.md` §0·§12, `docs/12-design-question-a-block.md` §7·§8,
`src/msa/pipeline/run.py`, `src/msa/l2/runtime.py`, `src/msa/l3/gates.py`, `docs/04-value-trap.md` §4.

---

## 1. L2 가 오늘 실제로 하는 일 — 문서가 약속한 것과 대조

`docs/03` §4 (개정 전 판) 가 약속한 것은 두 가지다: (i) `final(t) = 0.70·cycle_score(t) + 0.30·normalize(tailwind(t))` 로
**최종 테마 순위**를 만들고, (ii) `tailwind(t) < −0.5` 면 **후보에서 제외**한다. 이 절은 **질문이 제기된 시점**
(2026-08-23, 이 문서 §8 의 채택 커밋 이전)의 코드를 그대로 읽은 것이다:

| 약속 (`docs/03`) | 코드 현황 (2026-08-23, `src/`) | 선별에 미치는 영향 |
|---|---|---|
| §4 `final(t)` 0.70/0.30 결합 | **어디에도 없다.** `grep 'final(\|0\.70\|tailwind' src/` — `0.70`·`final(` 은 L2 맥락에서 0건. `select_themes` (`pipeline/run.py:296`) 는 S2 스코어보드의 `eligible`·`score` 만 읽고 상위 K=8 을 고른다 | **0** |
| §4 하드 규칙 `tailwind < −0.5` 제외 | `l2/tailwind.py` 가 `hard_exclude` **플래그**만 세운다 (`docs/03` §8.3: "실제 제외는 `final(t)` 단계(M5 이후)의 일"). 질문 시점의 `select_themes` 는 이 플래그를 읽지 않았다 (이 문서 §8 의 채택 커밋이 배선했다) | **0** (당시) |
| §5·§8.4 `credit_stress` 곱셈 페널티 0.5 | 계수를 **선언만** 한다 (`docs/03` §8.4). 적용 지점 없음 | **0** |
| §6 모순 감사 | `contradictions.csv` — 기계 규칙(`contradicts_rule`)이 있는 엣지 2개만 판정, 24개는 `PROSE_ONLY`. 사람이 읽는다 | 0 (리포트) |
| §8.6 엣지 부호 일치율 실측 | 기계는 있다(`l2/signcheck.py`). **451쌍 중 29쌍만 계산** — 드라이버 20개가 FRED 키/수동 CSV 부재로 결측 (`docs/macro-dag-sign-check.md` "부분 실행") | 0 (검정 불가) |
| L3 계약 `state/macro/latest.json` | `l2/runtime.py:_write_latest` 가 쓴다. **그러나 오늘 `state/macro/` 디렉터리 자체가 없다** (`ls state/` — `backtests cache cases macro-dag.yaml physical scans themes.yaml`). 즉 `msa macro` 가 쓰기 모드로 돌아 latest.json 을 남긴 적이 없다 | 아래 |
| L3 확신도 `+0.10 if tailwind > 0.3` (`docs/04` §4, `l3/gates.py:TAILWIND_MIN`) | 유일하게 **배선된** 하류 소비자. 단 `MacroState` 가 None 이면 항 미적용("거시 순풍 값 없음 — +0.10 항 미적용"). latest.json 이 없으므로 **오늘은 미적용** | 0 (잠재적으로 확신도 +0.10 → L5 의 C6 컷·사다리 기울기) |
| L5·저널 | `l5/plan.py` 매매계획서에 `tailwind` 표기, `ops/journal.py` `EntryRecord.l2_tailwind` 필수 필드 (없으면 `todo` 로 남아 항목 거부) | 0 (기록·표시) |

드라이버는 26개 중 **3개**(`gold_price` GLD · `copper_price` CPER 폴백 · `hyperscaler_capex` Sharadar)만 가용하다
(`docs/11` M4, `docs/03` §8.7). 4분면은 성장·인플레 축 구성 드라이버가 전부 FRED 라 **계산 불가**.

> 요약하면 **오늘 운용상 L2 는 테마 선별에 영향이 0 이다.** 이것은 L2 가 쓸모없다는 뜻이 아니라, "L2 를 뺄까"
> 라는 질문이 **현재 파이프라인에 대해서는 이미 사실상 답해져 있다**는 뜻이다 — 뺀 상태로 돌고 있다.
> 질문의 실체는 "FRED 가 들어왔을 때 §4 를 **배선할 것인가**" 다.

**비용 쪽.** L2 를 선언대로 살리려면 (a) `FRED_API_KEY` + 24종 시계열 캐시, (b) 수동 CSV 3종 월 1회
(`china_credit_impulse`·`china_property`·`policy_events`), (c) 86개 엣지 레코드(`state/macro-dag.yaml` 1,516줄)의
분기 모순 감사(`docs/09` §1 "사람 1시간"), (d) `src/msa/l2/` 2,572줄의 유지. 이 가운데 (b) 가 가장 무겁다 —
중국 신용·부동산 시계열은 사람이 매달 채우는 것이고, 빠지면 `dollar_broad`·`china_*` 가 상류인
원자재 테마(이 저장소의 원형)의 엣지가 통째로 결측된다.

---

## 2. 선언의 근거를 다시 읽는다 — 문서 자신이 이미 "조건"이라고 말한다

| 자리 | 서술 | L2 의 역할 |
|---|---|---|
| `docs/00` §3 도식 | L1 "테마 자체의 관측 · 결정론·전수" / L2 "드라이버 → 채널 → 테마. 부호·시차·근거를 사람이 선언" — 둘이 **같은 높이**에서 스코어보드로 합류 | 선별의 **공동 입력** |
| `docs/00` §2 | "지금 어느 테마가 잊혀졌고, 돌아설 준비가 되었는가? (L1 + L2)" | 선별의 공동 입력 |
| `docs/03` §4 근거 | "사이클 상태(L1)는 테마 자체의 관측이고, 거시(L2)는 **외생 조건**이다. 외생 조건은 자주 뒤집히고 **예측 정확도가 낮으므로** 가중을 낮춘다" | **조건** — 그러나 가산 항으로 집계 |
| `docs/03` §4 같은 문단 | "'거시가 좋아서 샀는데 산업이 여전히 공급 과잉' 은 실패하지만, '산업 공급이 파괴됐는데 거시가 아직 안 도와줌' 은 **기다리면 되는 문제**다" | 거시는 **시점**(언제)이지 **대상**(무엇)이 아니다 |
| `docs/03` §4 하드 규칙 | "거시가 정면으로 역풍인 테마는 사이클이 맞아도 **시점이 이르다**" | 제외 조건 = 역풍 회피 |
| `docs/03` §5 | "분면으로 테마를 고르지 않는다 — 분면은 너무 거칠다" | 4분면은 **설명 도구** |
| `docs/03` §1 | "선언된 엣지는 읽을 수 있다 … 논지가 죽었는지 판정할 수 있다" — "이게 실은 주된 효과다" | 엣지의 1차 용도 = **논지의 무효화 조건**(L3 `invalidations`) |

`docs/12` §2 와 같은 구조다. `docs/03` 은 한 문단 안에서 L2 를 "예측 정확도가 낮은 외생 조건" 이라 부르면서
그것을 **0.30 의 가산 항**으로 순위에 넣는다. 자기 서술대로라면 L2 는 "무엇을 살까" 의 입력이 아니라
"지금 사도 되는가 / 논지가 아직 살아 있는가" 의 입력이다 — 즉 **후보 집합의 조건(오버레이)** 과
**논지의 관측 가능한 무효화 조건** 이 선언이 실제로 의도한 자리다. 0.30 은 그 의도를 가산 항으로 번역하면서
생긴 잔여물일 가능성이 있다. 이것이 이 문서가 적어 두는 설계 질문이다:

> **L2 는 순위에 더하는 것인가(0.30), 후보를 거르는 조건·L3 의 맥락인가(0 + hard_exclude + 모순 감사)?**

같은 질문의 다른 면: L1 은 **이미** 시장이 거시를 가격에 반영한 결과를 본다(테마 지수의 낙폭·SMA·브레드스).
거시가 테마 가격에 들어오는 경로는 L1 이 보는 가격 그 자체이므로, L2 가 순위에 **추가로** 주는 정보는
"시장이 아직 반영하지 않은 거시" 뿐이다 — 그것이 있다는 주장이 §3 의 외부 증거가 가장 약한 곳이다.

---

## 3. 외부 증거 — 무엇을 읽었고 무엇을 말하는가

아래는 읽은 범위 안에서만 적는다. 한 줄 요약은 해당 문헌의 주장이지 이 저장소의 검정이 아니다.

| 갈래 | 출처 (연도) | 한 줄 발견 | 이 질문에 대한 방향 |
|---|---|---|---|
| (a) 거시 기반 섹터 로테이션 | Stangl·Jacobsen·Visaltanachoti, *Sector Rotation across the Business Cycle* (SSRN 2009; https://papers.ssrn.com/abstract=1467457 · 요약 https://www.cxoadvisory.com/economic-indicators/perfect-sector-rotation/) | 1948–2007, **경기 국면을 완벽히 예견해도** 관행적 로테이션의 초과수익은 연 2.3%(총); 1~2개월만 어긋나도 1~1.9% 로 줄고, 거래비용 반영 시 1.1~1.9% 로 **0 과 구분되지 않음** | L2 **반대** — 국면 판별이 완벽해도 섹터 해상도에선 남는 게 적다 |
| (a) | Conover·Jensen·Johnson·Mercer, *Sector Rotation and Monetary Conditions*, J. Investing 17(1) (2008; https://joi.pm-research.com/content/17/1/34 · 요약 https://www.cxoadvisory.com/economic-indicators/sector-rotation-based-on-monetary-policy/) | 1973–2005, Fed 할인율 방향(완화→경기민감 / 긴축→방어)만으로 시장 대비 연 3.78%(비용 전), 전·후반기 비슷. **표본 밖 검증은 없음** | L2 **찬성**(약) — 단 드라이버 1개(통화정책)·11섹터·단일 경로 |
| (a) | Alexiou·Tyagi, *Gauging the effectiveness of sector rotation strategies: USA and Europe*, J. Asset Mgmt 21 (2020; https://link.springer.com/article/10.1057/s41260-020-00161-6) | 1999–2019, 금리·모멘텀·FF 알파 신호. 유럽에선 통화 국면 불문 벤치마크 상회, 미국은 혼재 | 중립 — 신호 종류·시장에 따라 갈린다 |
| (a) 실무 | Fidelity, *The Business Cycle Approach to Equity Sector Investing* (백서, 2020 판; https://www.fidelity.com/webcontent/ap101883-markets_sectors-content/21.01.0/business_cycle/Business_Cycle_Sector_Approach_2020.pdf) | 국면별 섹터 "경향"을 제시하되 "국면이 선형으로 진행하지 않고 건너뛰거나 되돌아간다", "산업·인플레·개별 리서치로 **보완해야** 한다" 고 스스로 적음 | 중립 — 실무도 거시를 단독 선별기로 쓰지 않는다 |
| (a) 거시 예측 자체 | Tetlock, *Expert Political Judgment* (2005; https://press.princeton.edu/books/hardcover/9780691178288/expert-political-judgment) · St. Louis Fed, *Revisiting Professional Forecasters' Past Performance* (2025; https://www.stlouisfed.org/on-the-economy/2025/dec/professional-forecasters-past-performance-outlook-2026) | 전문가 예측은 단순 통계 모형에 뒤지고, SPF 4분기 앞 평균 예측은 한 번도 마이너스 성장을 예측한 적이 없다 | L2 를 **예측기**로 쓰는 것에 반대 — `docs/03` §4 의 자기 서술과 일치 |
| (b) 산업 자체의 지속성 | Moskowitz·Grinblatt, *Do Industries Explain Momentum?*, JF 54 (1999; https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00146) | 산업 모멘텀이 개별주 모멘텀의 대부분을 설명; 매수 쪽·대형주에서 이익 | L1 **찬성** — 산업 수준의 가격 추세 자체가 정보다 (C 블록이 보는 것) |
| (b) | Hong·Torous·Valkanov, *Do industries lead stock markets?*, JFE 83 (2007; https://www.sciencedirect.com/science/article/abs/pii/S0304405X06001383) · Tse, *A reexamination*, J. Empirical Finance 34 (2015; https://ideas.repec.org/a/eee/empfin/v34y2015icp195-203.html) | 1946–2002 소매·금속·석유 등이 시장을 1~2개월 선행(정보의 점진적 확산). 재검토(1946–2013)에선 유의한 산업이 1~7개로 줄고 역방향 인과도 보임 | 중립 — 산업→거시 방향의 정보가 있지만 **표본 밖에서 약하다** |
| (b) | Hou, *Industry Information Diffusion and the Lead-Lag Effect*, RFS 20 (2007; https://academic.oup.com/rfs/article-abstract/20/4/1113/1615954) | 선후행은 **산업 내** 현상이며 "작고, 경쟁이 덜하고, **방치된** 산업"에서 강하다 | L1 **찬성** — `docs/00` §1 "아무도 안 보는 곳" 과 같은 방향 |
| (b) | Rapach·Strauss·Tu·Zhou, *Industry Return Predictability: A Machine Learning Approach*, JFDS 1(3) (2019; https://papers.ssrn.com/abstract=3120110) | 시차 산업 수익률(특히 금융·원자재·소재)이 다른 산업을 표본 밖에서 예측 — 거시 변수가 아니라 **산업 간 연결**의 정보 | L1 **찬성**(산업 수준 정보) — 단 이 저장소는 산업 간 시차를 쓰지 않는다 |
| (c) 자본 사이클 | Cooper·Gulen·Schill, *Asset Growth and the Cross-Section of Stock Returns*, JF 63 (2008; https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01370.x) · Titman·Wei·Xie, JFQA 39 (2004; https://papers.ssrn.com/abstract=441584) · Hou·Xue·Zhang, *Digesting Anomalies*, RFS 28 (2015; https://academic.oup.com/rfs/article/28/3/650/1574802) | 자산 성장·설비투자 증가 → 이후 수익률 저하; 투자 팩터가 q-모형의 핵심 | E 블록(자본사이클) **찬성** — 기업·산업의 **공급 측** 변수가 거시 없이 예측력을 갖는다 |
| (c) | Greenwood·Hanson, *Waves in Ship Prices and Investment*, QJE 130 (2015; https://academic.oup.com/qje/article-abstract/130/1/55/2337948) | 해운: 높은 현재 수익 → 중고선가↑·발주↑ → **낮은 미래 수익**. 기업은 수요 충격을 과대 외삽하고 경쟁자의 투자 반응을 무시한다 | 산업 사이클은 **산업 내부의 공급 반응**으로 설명된다 — 거시 없이 |
| (c) | Chancellor(편), *Capital Returns* (Marathon, 2015; https://www.edwardchancellor.com/books/capital-returns) | "자본의 공급이 수익의 결정 요인이며 **수요보다 분석하기 쉽다**" | 실무의 같은 주장 — `docs/02` E 블록·`commodity_supply` 0.30 의 근거 문헌 |
| (d) 거시 = 리스크 오버레이 | Faber, *A Quantitative Approach to Tactical Asset Allocation* (2007/2013; https://papers.ssrn.com/abstract=962461) · Hurst·Ooi·Pedersen, *A Century of Evidence on Trend-Following*, JPM 44 (2017; https://papers.ssrn.com/abstract=2993026) | 추세 필터는 수익률은 비슷하게 두고 **낙폭·변동성을 줄인다**; 추세 추종은 60/40 의 10대 위기 중 8번에서 양의 수익 | 국면/추세 오버레이의 가치는 **선별이 아니라 낙폭 관리**에 있다 |
| (d) | Gilchrist·Zakrajšek, *Credit Spreads and Business Cycle Fluctuations*, AER 102 (2012; https://www.aeaweb.org/articles?id=10.1257/aer.102.4.1692) | 초과 채권 프리미엄(EBP) 충격 → 실물 활동·자산가격 하락; Fed 가 12개월 침체 확률 지표로 사용 | `hy_spread`/`credit_stress` 는 **조건(플래그)** 으로서 근거가 가장 단단한 L2 드라이버 |
| (d) 자산군 거시 | Brooks, *A Half Century of Macro Momentum* (AQR 2017; https://www.aqr.com/Insights/Research/White-Papers/A-Half-Century-of-Macro-Momentum) | 거시 추세(성장·무역·통화·위험선호)의 **방향**이 자산군 수준에서 표본 내 1970–2016 예측력 — 단 백테스트, 자산군 수준, 섹터 아님 | L2 **찬성**(자산군) — 테마 해상도로 내려오는 증거는 아니다 |
| (e) 원자재·거시 채널 | Erb·Harvey, *The Golden Dilemma*, FAJ 69 (2013; https://www.nber.org/papers/w18706) · *Is There Still a Golden Dilemma?* (2024; https://papers.ssrn.com/abstract=4807895) | 1997–2012 금 vs 10년 TIPS 실질수익률 상관 −0.82 — 그러나 저자들 스스로 표본이 짧고 시간추세와 혼재돼 **허위일 수 있다** 고 적음; 2024 판은 실질 금값 수준(≠실질금리)이 10년 수익을 결정한다고 | `real_rate_10y → gold_miners` 엣지(strong, 64쌍 집중)의 근거가 **생각보다 약하다** |
| (e) | Chen·Rogoff·Rossi, *Can Exchange Rates Forecast Commodity Prices?*, QJE 125 (2010; https://academic.oup.com/qje/article-abstract/125/3/1145/1903653) | 원자재 통화(AUD·CAD·CLP·NZD·ZAR)가 원자재 가격을 표본 밖 예측 — 데이터 정렬 비판 있음 | `dollar_broad` 채널 **찬성**(약) — 환율 쪽이 가격보다 앞선다는 근거 |
| (e) | 중국 신용 충격→금속 (실무 보고: ING THINK 2026 https://think.ing.com/articles/industrial-metals-monthly-china-copper-optimism-is-fading/ 등) | 신용 충격이 중국 연동 자산(금속)에 먼저, 기타 성장 민감 자산엔 4~5분기 뒤 | `china_credit_impulse` 선행 주장의 실무 근거 — **동료평가 문헌은 읽지 못했다** |

**읽은 범위의 무게 배분.** 거시를 **섹터 선별기**로 쓰는 것의 표본 밖 증거는 약하다(Stangl 외; Conover 외는
표본 내). 산업 수준의 **자체 정보**(모멘텀·공급 측 자본 사이클)는 거시 없이 예측력을 갖는다는 증거가 더
두텁고, 이것이 L1 의 C·E 블록이 서 있는 자리이며 M3.5·M3.6 에서 C 가 일하고 E 가 12M 에서 약한 양을
보인 것과 방향이 같다(`docs/backtest-l1.md` §2·§12). 거시가 가장 단단하게 일하는 형태는 **조건/오버레이**
(신용 스트레스·추세)다. 원자재에서의 거시 채널(달러·실질금리·중국 신용)은 실무 통념이 강하지만 문헌상
근거는 채널마다 고르지 않다 — 실질금리↔금은 그 통념의 저자들이 직접 의심했다.

이 표가 **말하지 않는 것**: L2 를 지워도 된다는 것. 표의 어느 행도 "역풍 조건을 무시해도 된다" 거나
"논지의 무효화 조건을 관측하지 않아도 된다" 고 말하지 않는다. 말하는 것은 "거시를 **순위 점수에 더하는
것**의 근거가 약하다" 까지다.

---

## 4. 설계 공간 — 선택지와 각각의 비용

아래는 **열거**다. 이 문서는 고르지 않는다 (§5 의 절차가 고른다).

| # | 구조 | 서술 | 장점 | 위험·비용 | 규약과의 관계 |
|---|---|---|---|---|---|
| (A) | **현행 선언 유지** — FRED 확보 후 §4 를 배선 | `final = 0.70·S2 + 0.30·pct(tailwind)`, `hard_exclude` 실제 제외, `credit_stress` 페널티 | 문서 그대로. 이미 지은 코드(`l2/` 2,572줄·DAG 86엣지)를 쓴다 | FRED 키 + 수동 CSV 3종 월 1회 + 분기 감사 1시간. **배선 자체가 미검정 선언을 선별에 넣는 일** — M3.5 가 L1 에 요구한 관문을 L2 는 통과한 적이 없다(부호 실측 29/451). 0.30 이 S2 의 IC 를 깎을 수도 있다 | 가장 보수적(선언 불변). 단 배선은 `docs/10` §2 관문 없이 하면 안 된다 — 관문이 §5 |
| (B) | **선별에서 빼고 오버레이만** — tailwind 가중 **0** | 순위 = S2 단독. 남기는 것: `hard_exclude`(tailwind<−0.5, weight_coverage≥0.5) · 모순 감사(§6) · 국면의 `credit_stress` 플래그 · L3 `MacroState` 컨텍스트(확신도 +0.10 포함) · 저널 `l2_tailwind` | `docs/03` §4 의 **자기 서술**("예측 정확도가 낮은 외생 조건", "기다리면 되는 문제")과 정합. 외부 증거의 무게(§3)와 정합. 드라이버가 결측이면 조건이 **발동하지 않을 뿐** 순위는 멀쩡하다 | 유지비는 (A) 와 같다(조건을 계산하려면 같은 데이터가 필요). `hard_exclude` 가 맞는 제외인지는 여전히 미검정. L3 +0.10 항은 남으므로 "L2 가 선별에 영향 0" 은 아니고 "순위에 영향 0, 확신도에 +0.10" 이다 | 가중치 0.30→0 은 **값 변경**이다. `CLAUDE.md` §1 이 허용하는 길은 하나 — 사전 등록된 검정(§5)의 결과와 근거를 문서·커밋에 남기고 바꾸는 것 |
| (C) | **L2 전면 삭제** | `l2/`·DAG·`MacroState`·저널 필드 제거 | 유지비 0. 수동 CSV 의무 소멸 | `docs/03` §1 의 "주된 효과"(읽을 수 있는 엣지 → 논지 무효화 조건)를 버린다. L3 `invalidations` 의 관측 가능한 어휘(실질금리·달러·신용 스프레드)를 잃는다. `credit_stress` 같은 낙폭 조건(§3 (d))도 잃는다. 되돌리기 비싸다 | 선언의 삭제. 금지는 아니지만 §3 의 어느 증거도 이걸 지지하지 않는다 |
| (D) | **원자재 클래스에만 L2 채널** (`commodity_supply`: 달러·실질금리·중국 신용), 나머지 0 | 클래스별 가중치처럼 클래스별 L2 가중 | 이 저장소의 원형(2026 원자재)에 집중. 유지할 드라이버가 `dollar_broad`·`real_rate_10y`·`china_*` 로 준다 | **클래스를 데이터로 고르는 것**과 구분이 어렵다 — §12 결과("`commodity_supply` 에서 S2 가 0 과 구분 안 됨")를 본 뒤 그 클래스에 거시를 넣는 것은 정확히 "성과가 좋아지는 방향" 의 탐색 모양이다. 근거가 될 수 있는 건 오직 도메인 서술(`docs/03` §2 "달러 = 원자재 전반의 1차 드라이버") 뿐이고, 그 서술의 문헌 근거는 §3 (e) 가 보듯 고르지 않다. 중국 CSV 수동 유지비는 그대로 | 새 구조 = 새 후보 = 시도 수 가산. 이 문서는 이 문을 **열지 않는다**(§5.4) |

문서의 원래 서술(`docs/03` §4 근거 문단·§5·§1)과 가장 정합적인 것은 (B) 다. 그러나 (B) 도 **데이터를 보기
전의 선언(0.30)을 데이터 없이 0 으로 옮기는 것**이고, `CLAUDE.md` §1 은 그 이동에 사전 등록된 검정을
요구한다. 그래서 이 문서는 (B) 를 고르지 않고, **(A) 와 (B) 를 가르는 절차를 고정**한다.

---

## 5. 결정 절차 — 사전 등록 (M4.5 제안)

**원칙: 합격 기준과 조치를 FRED 데이터를 받기 전에 적는다. 받은 뒤에 돌린다. 돌린 뒤에 값을 고치지 않는다.**

### 5.1 전제 — 데이터

`FRED_API_KEY` 설정 → `uv run msa data fred-fetch` → `msa data fred-lag`(발표 지연 실측) → `msa macro --doc-out`.
수동 CSV(`china_*`·`policy_events`)는 과거 시계열이 없으므로 검정에서 해당 엣지는 **결측으로 빠지고**
`weight_coverage` 가 그것을 보고한다 — 결측을 0(중립)으로 채우지 않는다(`docs/03` §8.3). FRED 캐시는 최신
개정치(ALFRED 아님)라 과거 `state` 는 사후 개정분을 포함한다 — 한계로 적는다(§8.2).

### 5.2 검정 (i) — 엣지 부호 일치율 실측 (이미 구현, 검정 아님)

`docs/macro-dag-sign-check.md` 를 451/451 로 채운다. **세는 것이지 고치는 것이 아니다**(§8.6). 이 표는
§5.4 의 결정 입력이 아니라 **부록**이다 — 일치율이 낮다고 (B) 를 고르지 않고, 높다고 (A) 를 고르지 않는다.
불일치 엣지는 `docs/03` §6 의 절차(사람 검토 → 서술 수정 → 커밋 근거)로 간다.

### 5.3 검정 (ii) — 증분 검정 (여기서 고정)

| 항목 | 정의 |
|---|---|
| 후보 | **F0**: S2 순위 점수 `T` 단독 (현행). **F1**: `0.70·T + 0.30·pct_cs(tailwind)` — `normalize` 는 `docs/03` §4 가 정의하지 않았으므로 **여기서 횡단면 백분위로 고정**한다(L1 의 `pct` 와 같은 연산). `tailwind` 는 `driver_states.csv` 의 월말 격자에서 as-of 로 재구성, 공통 인자 중앙값 차감 후(§8.3) |
| 데이터·창·호라이즌 | M3.6 과 동일 — `state/cache/l1_*`, 주 창 2011– · 보조 전 구간, 3·6·12M, 12개월 블록 부트스트랩 2000회 시드 0, 최소 횡단면 20. 단 `tailwind` 가 `weight_coverage < 0.5` 인 테마-월은 **F1 에서 제외하고 F0 도 같은 집합으로 맞춘다**(비교 집합 동일) |
| 주 통계 | `ΔIC = IC(F1) − IC(F0)` 의 월별 쌍차이 평균과 95% 블록 부트스트랩 CI (주 창·12M) |
| 합격 | **`ΔIC` 의 CI 하한 > 0** (L2 가 S2 위에 정보를 **더한다**). 보조로 top-8 vs bottom-8 12M 스프레드 차이 |
| hard_exclude 검정 | 주 창에서 `hard_exclude=True` 였던 (테마, 월) 의 전방 12M 초과수익(vs SPY) 평균과 CI, 그리고 같은 달 `eligible` 비제외 테마 평균과의 차. "제외가 맞았다" = 제외 집합 평균 ≤ 비제외 평균 (CI 로 판단). 표본 수를 먼저 적는다 — 한 자리면 판정하지 않고 기록만 |
| 시도 수 | 기존 632 + F1 × 창 2 × 호라이즌 3 × (ΔIC + 스프레드) = +12, hard_exclude × 창 2 = +2 → **646**. DSR 은 646 으로 정산한다. (i) 의 부호 실측은 검정이 아니므로 더하지 않는다 |
| 기록 위치 | `docs/macro-dag-sign-check.md` 옆에 **새 문서** `docs/backtest-l2.md`. 이 문서(13)는 고치지 않고 §7 에 결과를 덧붙인다 |

### 5.4 결과별 조치 (미리 고정)

| 결과 | 조치 |
|---|---|
| ΔIC CI 하한 > 0 | **(A) 유지** — 자동 배선 아님. 사람이 읽고, 배선한다면 `select_themes` 에 `final(t)`+`hard_exclude` 추가 · `docs/03` §4 에 검정 근거 추가 · README · 저널을 한 커밋으로. 합격은 "한 경로에서 어긋나지 않았다" 다 |
| ΔIC CI 가 0 을 포함 | **(B) 로 강등** — 자동 아님. 사람이 결정하면 `docs/03` §4 의 0.30 을 0 으로 바꾸고(근거 = 이 검정 + §2 의 자기 서술), `hard_exclude`·모순 감사·`credit_stress` 플래그·`MacroState` 는 남긴다. 하나의 별도 커밋 |
| ΔIC CI 상한 < 0 | (B) 와 같다 + 그 사실을 `docs/03` 에 적는다(L2 가 S2 를 **깎는다**는 관측) |
| hard_exclude 표본 < 10 | 판정 없음. 플래그는 남기되 실제 제외 배선은 하지 않는다 |
| **FRED 키가 끝내 없으면** | **(B) 가 기본값** — 이유는 "데이터 없는 선언은 실측할 수 없다" 이지 "틀렸다" 가 아니다. 이것도 사람이 결정하고 저널에 적는다. (C) 는 기본값이 아니다 |

### 5.5 하지 않는 것

- 0.30 을 0.15 나 0.50 으로 **옮겨 보는 것**, `pct_cs` 대신 z-score 를 써 보는 것, −0.5 를 −0.3 으로 풀어 보는 것 —
  각각 새 후보이며 이 문서는 그 문을 열지 않는다.
- (D) 를 후보에 넣는 것 — §4 의 이유. 클래스별 L2 가중은 별도 번호의 새 사전 등록이며 시도 수에 더한다.
- 부호 일치율(5.2)을 보고 엣지의 `sign`·`strength` 를 바꾸는 것(`CLAUDE.md` §1, `docs/03` §6).
- 검정 통과를 이유로 L3 `+0.10`·L5 의 입력을 자동으로 바꾸는 것.
- `docs/03` 의 어느 줄도 이 문서가 고치지 않는다. 고칠 것이 있으면 §5.4 의 커밋이 고친다.

---

## 6. 권고 — 의견임을 명시한다

이것은 작성자의 의견이고 결정이 아니다. **(B) 가 기본이어야 한다고 본다.** 이유는 셋이다. 첫째, `docs/03`
§4 는 스스로 L2 를 "예측 정확도가 낮은 외생 조건" 이라 부르며 "거시가 아직 안 도와줌은 기다리면 되는 문제"
라 적었다 — 그 서술이 가리키는 자리는 가산 항이 아니라 조건이다(§2). 둘째, 읽은 외부 증거의 무게는 "거시는
섹터 **선별기**로서 표본 밖 근거가 약하고, 산업 내부 정보(모멘텀·공급 측 자본 사이클)는 거시 없이 일하며,
거시가 단단히 일하는 형태는 낙폭 조건" 쪽이다(§3). 셋째, 오늘 L2 는 이미 순위에 영향 0 으로 돌고 있으므로
(B) 는 **현재 상태를 선언으로 확정하는 것**에 가깝고 되돌리기 쉽다(§1). 그러나 그 의견으로 0.30 을 0 으로
옮기지 않는다 — `CLAUDE.md` §1 이 요구하는 것은 의견이 아니라 §5 의 절차이고, FRED 가 들어오면 (A) 가
이길 가능성은 열려 있다. (C) 는 권하지 않는다 — L2 의 주된 효과(읽을 수 있는 엣지 = L3 의 무효화 어휘,
`credit_stress`)는 순위 가중과 무관하게 남아야 한다.

**"바로 L1 로 가도 되는가"** 에 대한 짧은 답: **운용상 이미 그렇게 가고 있다.** 남은 질문은 L2 를 순위에
다시 넣을지이고, 그 답은 §5 가 낸다.

---

## 7. 요약 — 이 문서가 바꾸는 것

- 바꾸는 것: **없다.** 코드 0줄, 가중치 0개(0.70/0.30·−0.5·0.5·+0.10 전부 그대로), 엣지 0개.
- 적어 두는 것: L2 의 실제 런타임 역할(§1 — 순위 영향 0, L3 확신도 +0.10 항만 배선, 오늘은 latest.json 부재로
  그것도 미적용), 선언의 자기 서술(§2), 외부 증거 표(§3), 설계 공간 (A)~(D)(§4), 사전 등록된 절차 M4.5
  (§5 — F0/F1, `normalize = pct_cs` 고정, 합격 = ΔIC CI 하한 > 0, 시도 수 646, 결과별 조치, FRED 부재 시 기본값 (B)).
- 다음 사람이 할 일: FRED 키가 오면 §5 를 그대로 실행하는 `M4.5` (`docs/11-roadmap.md` 에 항목 추가는 별도
  커밋). 실행 전에 이 문서를 고치지 않는다. 결과는 §9 로 덧붙인다.


---

## 8. 채택 기록 (2026-08-23)

§1~§7 이 쓰이는 동안 사용자가 **(B) 를 결정**했다 — 그 결정은 이 문서의 것이 아니라 별도 커밋의 것이다.
같은 날 한 묶음으로: `docs/03` §4.1 신설("거시는 순위에 들어가지 않는다" — 0.30 가중 철회, 오버레이 네 가지
유지), `src/msa/pipeline/run.py` 의 select 단계가 `tailwind.csv` 의 `hard_exclude` 를 읽어 `select_themes(...,
hard_exclude=)` 로 넘기고 제외한 이름과 수를 적는다(사용자 지정 테마는 빼지 않고 플래그만), `README` L2 행,
`docs/11` M4, `journal/2026-08-23-l2-macro-overlay-only.md`.

그래서 이 문서의 §4·§5 는 다음과 같이 읽는다:

- **기본값은 이제 (B) 다.** §5 의 사전 등록 검정은 "(A) 로 **돌아갈** 이유가 있는가" 를 답하는 절차가 된다
  (저널의 "되돌리는 조건" 과 동일 — ΔIC CI 하한 > 0 이면 새 절로 기록하고 사람이 다시 결정).
- §5.4 의 "ΔIC CI 가 0 을 포함 → (B) 로 강등" 은 "**(B) 유지**" 로 읽는다. 나머지 행은 그대로다.
- §1 표의 "선별에 미치는 영향 0" 은 질문 시점의 관측이다. 채택 후 L2 는 **순위에 0, 후보 집합에 hard_exclude,
  L3 확신도에 +0.10(latest.json 이 있을 때)** 이다 — 단 오늘은 드라이버 3/26 이라 `weight_coverage ≥ 0.5` 를
  만족하는 테마가 거의 없어 hard_exclude 가 실제로 서는 일은 FRED 가 들어온 뒤에나 생긴다.
- §6 의 권고는 결정과 같은 방향이었으나, 결정의 근거는 저널에 적힌 네 가지이지 이 권고가 아니다.

이 문서는 여기서 닫는다. §5 의 실행 결과는 §9 로 덧붙이고, 그 전에 §5 를 고치지 않는다.
