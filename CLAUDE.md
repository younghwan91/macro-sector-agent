# macro-sector-agent — 작업 규약

거시 → 산업 사이클 → 테마 → 종목 → 포트폴리오 하향식 리서치 파이프라인.
**현재 M3~M8 구현** (`src/msa/` — L0 데이터 · 테마 유니버스 · L1 스캐너 `msa scan` ·
L2 거시 DAG `msa macro` · L4 종목 선정 `msa picks` · L5 포트 구성기 `msa portfolio` ·
L3 에이전트 `msa research` · 운영 `msa check`/`msa journal`/`msa ops`).
이후 단계는 `docs/11-roadmap.md`. 어느 계층이든 손대기 전에 해당 `docs/` 를 먼저 읽는다.

## 절대 규칙

### 1. 탐색으로 가중치를 정하지 않는다 — 이 저장소의 지배적 실패 유형

`portfolio-research` 의 지배적 실패는 "조용한 절단"이었다. 이 저장소의 지배적 실패는
**오버피팅** 이 될 것이다.

결정론 계층(L1·L2·L4)은 백테스트가 가능하고 DSR·PBO 관문이 붙는다
(`docs/10-validation.md` §2). **그러나 그 관문이 이 규칙을 대체하지 않는다.**
표본이 사실상 하나(1998~2026 미국 시장 단일 경로)이고, 사람이 표를 보고 손으로 가중치를
옮기는 것은 **어디에도 기록되지 않는 시도**라 DSR 의 시도 수에 계상할 방법이 없다.
`portfolio-research` 가 35회 탐색을 정산할 수 있었던 것은 그 35회가 스크립트로 남았기
때문이다. 여기서 일어날 탐색은 사람의 머릿속에서 일어난다.

L3(에이전트 리서치)은 아예 백테스트가 불가능하다. 어느 쪽이든 결론은 같다 —
**오버피팅할 기회 자체를 구조적으로 막아야 한다.**

> L1 블록 가중치, L2 엣지 강도, L4 축 가중치는 **선언하고 근거를 적는다.**
> 데이터에 맞춰 조정하지 않는다. 조정하려면 그 근거를 커밋 메시지와 문서에 남긴다.

- 파라미터 스윕 · 그리드 서치 · "성과가 좋아지는 방향으로" 는 이 저장소에서 금지된다.
- 임계값(예: 낙폭 50%, RV 비율 0.8)은 **도메인 근거**에서 오거나, 없으면 그렇다고 적는다.
- 과거 데이터로 확인하는 것은 허용된다 — 오히려 `docs/10-validation.md` §2 가 그것을
  **관문으로 요구한다.** 금지는 그대로다: **확인의 결과로 값을 바꾸는 것.**
  검정이 "이 블록은 일하지 않는다" 고 말하면 **그 사실을 기록**하고 가중치는 그대로 둔다.

### 2. 조용한 절단 금지 (`portfolio-research` 에서 승계)

데이터를 가져오는 코드는 요청한 것보다 적게 받으면 반드시 예외를 던지거나 경고를 남긴다.
테마 버킷 커버리지 감사(§`docs/01-theme-universe.md`)는 매 적재마다 돈다 —
**미분류 시총 비율이 임계를 넘으면 스캔을 진행하지 않는다.**

### 3. 출처 없는 에이전트 주장은 저장되지 않는다

L3 산출물은 `evidence: [{claim, source_url, date, reliability}]` 배열이 비어 있으면
스키마 검증에서 거부된다. LLM 의 기억은 증거가 아니다.

### 4. 에이전트는 테마만 고른다. 종목은 결정론적 계층이 고른다

LLM 에게 종목을 물으면 훈련 데이터의 유명세 편향이 들어온다.
L3 는 테마 논지만 산출하고, L4 는 그 논지를 입력으로 받되 **랭킹은 코드가 한다.**

### 5. 논지는 무효화 조건 없이 저장할 수 없다

`thesis.invalidations` 가 비면 스키마 검증 실패. 무효화 조건이 곧 Tier-1 스탑의 근거다
(`docs/07-portfolio.md` §4). 무효화 조건을 못 쓰겠으면 그건 논지가 아니라 희망이다.

### 6. 결정 저널은 append-only

`journal/` 의 기존 파일을 수정하지 않는다. 생각이 바뀌면 새 항목을 추가하고 이전 항목을 링크한다.
이 저장소에서 성과 검증을 하는 유일한 물건이므로, 사후 편집은 검증 자체를 파괴한다.

### 7. 성과 수치를 광고하지 않는다

전략 성과의 CAGR·Sharpe 를 말할 근거가 없다. L1·L2·L4 의 백테스트는 **스코어의 예측력**
(rank-IC·분위 스프레드)을 재는 것이지 전략의 수익률을 재는 것이 아니다 —
L5(사이징·사다리·스탑)와 L3(확신도)이 백테스트 불가라 **전략 수익률이라는 물건 자체가
만들어지지 않는다** (`docs/10-validation.md` §1·§2.5).

README 와 리포트에 기대수익률·승률·수익 배수를 쓰지 않는다. 쓸 수 있는 것은
**검정 결과**(IC 와 그 신뢰구간, 시도 수를 명시한 DSR·PBO)와
**전향적 기록**(트리거 충족률, 캘리브레이션 Brier score)이며, 후자는 표본이 쌓인 뒤다.

### 8. 투자 조언이 아니다

산출물은 측정값과 명시된 가정이다. 집행은 사람이 하고, 자동 주문 기능은 만들지 않는다.

## PIT 규약 — 두 경로가 다르다

**이전 판은 "백테스트를 하지 않으므로 look-ahead 개념이 성립하지 않는다" 고 적었다. 틀렸다.**
결정론 계층을 백테스트하기로 한 이상 look-ahead 는 정면으로 성립한다.

경로가 둘이고 요구가 다르다.

| 경로 | PIT | 이유 |
|---|---|---|
| **백테스트 경로** (`docs/10-validation.md` §2) | **전부 필요. 예외 없음** | look-ahead 가 IC 를 부풀리는 가장 흔한 방법이다. `datekey` 기준 적재만 쓰고 `reportperiod` 로 정렬하지 않는다 |
| **오늘의 스캔 경로** (월간 운영) | 아래 표 | 미래를 보는 것이 불가능하므로 look-ahead 가 아니라 **분포 왜곡**이 문제다 |

오늘의 스캔 경로 안에서:

| 지표 종류 | PIT 필요 | 이유 |
|---|---|---|
| 자기이력 백분위 (밸류·ROIC·마진) | **필요** | 과거 시점 값을 정정치로 계산하면 백분위 분포가 왜곡되고, 오늘의 순위가 틀어진다 |
| 자본 사이클 시계열 (capex/D&A, 자산성장) | **필요** | 같은 이유 |
| 오늘의 스냅샷 (부채비율, 현금 런웨이) | 불필요 | 최신 정정치가 오히려 정확하다 |

> 코드는 각 지표가 **어느 쪽인지 명시**하고, **어느 경로에서 호출됐는지**도 명시한다.
> 같은 지표가 백테스트에서는 PIT 를 요구받고 오늘의 스캔에서는 아닌 경우가 있다 —
> 그 분기를 코드가 아니라 호출자가 알고 있으면 몇 달 뒤 조용히 섞인다.

## 명령어

```bash
make install          # uv sync
make check            # ruff + mypy + pytest (data/net 마커 제외)
msa data status       # 스토어 상태·결측률 (M1)
msa data audit        # 커버리지 감사 — 데이터 부분 (M1)
msa scan              # L1 사이클 스캐너 → 테마 스코어보드 (M3). --asof --force --no-vcp
                      #   산출물 state/scans/<date>/ (scoreboard·indicators·coverage·report·meta)
msa macro             # L2 거시 DAG (M4): 드라이버 상태·tailwind·4분면·모순 감사·부호 실측
                      #   --asof --no-fetch --no-etf --no-store --no-write --no-sign-check --doc-out
                      #   산출물 state/macro/<date>/ · FRED 캐시 없으면 결측 드라이버를 이름으로 보고
msa data fred-fetch   # FRED 드라이버 24종 + physical_ref + CPI 를 state/physical/fred/ 에 캐시 (키 필요)
msa portfolio --inputs <dir>   # L5 SOCP + 사다리·스탑·TP + 매매계획서 (M6). --asof --cases --capital
                      #   --cluster-cap name=cap --no-write · 입력 계약: src/msa/l5/inputs.py
                      #   산출물 state/portfolio/<date>/ (weights.csv·plan.md·diagnostics.json)
msa research <theme>  # L3 에이전트 4역할(supply·catalyst·bear·referee) → thesis 객체 (M7)
                      #   실제 실행은 ANTHROPIC_API_KEY 필요 (--provider anthropic, 기본값)
                      #   오프라인: --dry-run (Mock) · --provider fixture (tests/fixtures/l3/)
                      #   산출물 state/theses/<date>/ (thesis.yaml·report.md·rejections-pending·contested)
msa picks <theme>     # L4 종목 선정 — S·T·M 3축 · 하드 필터 · 바벨 (M5). --asof --top --no-write
                      #   --no-physical. 산출물 state/picks/<date>/<theme>/ (ranking·excluded·report·meta)
msa check             # 포지션 점검 (M8) — 트리거·무효화·Tier-2·사다리·시간스탑·TP. --asof --daily|--weekly
                      #   산출물 state/checks/<date>/ (report·alerts.json·journal-draft). 주문은 내지 않는다
msa journal new --from f.yaml   # 저널 항목 추가 (필수 필드 비면 거부 · 덮어쓰기 불가) — template <type>
msa journal verify    # journal/ append-only 검사 (pre-commit: scripts/journal-precommit.sh · install-hook)
msa journal diff <theme>        # 최근 두 thesis 스냅샷 필드 diff (논지 표류)
msa ops schedule --print-cron   # 케이던스 → crontab/systemd 텍스트 (설치는 사람이) · ops due <cadence>
msa ops calibration   # cycle_confidence 캘리브레이션 (N<20 → 결론 없음)
msa ops rejections-update       # 기각 대장 r_12m/r_24m 갱신 + 세 질문 → state/rejections-summary.md
msa ops reproduce <date>        # state/scans/<date>/ 스냅샷만으로 리포트 재생성·대조
msa backtest l1       # L1 백테스트 관문 0 (M3.5) — rank-IC·스프레드·breadth_lead·DSR/PBO.
                      #   산출물 state/backtests/l1/<date>/ · 판정 docs/backtest-l1.md. 튜닝 루프가 아니다
msa backtest l1-structures  # M3.6 — A 집계 구조 검정 S0/S1/S2 (docs/12 §4 사전 등록). 결과 docs/backtest-l1.md §12
```

텔레그램 배달은 `MSA_TELEGRAM_TOKEN` · `MSA_TELEGRAM_CHAT_ID` 가 둘 다 있을 때만 — 없으면 "not configured".

패키지 관리는 **uv**. `pip install` 하지 않는다.
