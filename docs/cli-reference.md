# msa 명령 레퍼런스

`CLAUDE.md` 의 '명령' 절에서 2026-10-12 하네스 정리 때 **문구 그대로** 옮겼다.
옵션의 최종 출처는 `uv run msa <cmd> --help` 다 — 여기와 다르면 코드를 믿고 이 문서를 고친다.

## 명령어

```bash
make install          # uv sync
make check            # ruff + mypy + pytest (data/net 마커 제외)
msa data status       # 스토어 상태·결측률 (M1)
msa data audit        # 커버리지 감사 — 데이터 부분 (M1)
msa scan              # L1 사이클 스캐너 → 테마 스코어보드 (M3). --asof --force --no-vcp
                      #   산출물 state/scans/<date>/ (scoreboard·indicators·coverage·report·meta)
msa data fred-fetch   # L1 이 쓰는 FRED 시리즈(CPI + 테마 physical_ref)를 state/physical/fred/ 에 캐시 (키 필요)
msa data fred-lag     # 같은 목록의 발표 지연·개정 실측 (--vintage YYYY-MM-DD 로 ALFRED)
msa portfolio --inputs <dir>   # L5 SOCP + 사다리·스탑·TP + 매매계획서 (M6). --asof --cases --capital
                      #   --cluster-cap name=cap --no-write · 입력 계약: src/msa/l5/inputs.py
                      #   산출물 state/portfolio/<date>/ (weights.csv·plan.md·diagnostics.json)
                      #   --emit-positions: positions.yaml 모양의 미체결 제안(positions-proposal.yaml·.md)
                      #   도 쓴다 — state/positions.yaml 은 건드리지 않는다, 승격(status open)은 사람이
msa portfolio-inputs --asof DATE --themes a,b,c   # L4 picks + L3/사람 thesis → L5 입력 묶음 (배선 W1)
                      #   [--human-theses DIR] [--top N] [--no-write] · 산출물 state/portfolio_inputs/<date>/
                      #   (picks.csv·theses/·assemble_report.json·report.txt) → msa portfolio --inputs 그대로
msa research <theme>  # L3 에이전트 4역할(supply·catalyst·bear·referee) → thesis 객체 (M7)
                      #   **한 번에 하나씩 돌린다.** 2026-08-29 실측: 두 배치를 동시에 돌리자
                      #   4건이 전부 ProviderError(종료코드 3)로 죽었다 — 속도 제한이다.
                      #   순차로 돌리면 같은 테마가 그대로 통과한다. 종료코드: 2=스키마 거부
                      #   (저장 안 함) · 3=제공자 오류(재시도하면 대개 된다)
                      #   기본 --provider claude_code = 로컬 claude CLI 하위 프로세스 (API 크레딧 0).
                      #   --provider anthropic 은 ANTHROPIC_API_KEY 로 크레딧을 쓴다
                      #   오프라인: --dry-run (Mock) · --provider fixture (tests/fixtures/l3/)
                      #   산출물 state/theses/<date>/ (thesis.yaml·report.md·rejections-pending·contested)
msa balance [themes]  # L3.5 수급 균형 조사 — "수요 나누기 공급" (docs/26 사전 등록).
                      #   판별기(L3)는 "안 죽었나" 만 묻는다. 이건 **"쓰는 양이 늘어나는가"** 다:
                      #   향후 3~5년 실물 수요 증가율이 실물 공급 증가율을 앞지르는가.
                      #   **가격이 아니라 물량 대 물량** — 목표가·기대수익을 담을 칸이 없다.
                      #   **회전이다** — 테마를 안 주면 조사 없는 편입 가능 테마 먼저, 그다음
                      #   90일(BALANCE_STALE_DAYS) 지난 것부터 n개. 매일 134 테마를 돌지 않는다.
                      #   -n --unit --provider --dry-run --no-write --show
                      #   산출물 state/balance/<theme>.balance.yaml · .report.md
                      #   **트리아지 점수에 안 들어간다** (docs/26 §3.5) — 명단이 아니라 논지다.
                      #   공급 경직성은 5유형 중 하나로 분류(byproduct·lead_time·permitting·
                      #   capital·resource_depletion) — 분류 못 하면 그 주장을 안 싣는다
                      #   → 관문 체인(msa.sector)의 ④ 관문이 이 판정을 읽는다
msa regime            # P2 매크로 분석가 — cycle_class 8칸에 3값 판정 (docs/25 사전 등록).
                      #   **주간 1회.** --week --asof --provider --dry-run --no-write --show
                      #   산출물 state/regime/<YYYY-Www>.yaml. 트리아지 **R 축의 계수**로만 쓰인다
                      #   (tailwind 1.00 · neutral 0.85 · headwind 0.70) — J·C·구획은 못 건드린다.
                      #   L2(거시 인과 DAG)를 되살린 것이 아니다: 점수를 조정하지 않는다
msa stock-notes       # P3 종목 분석가 — "이 회사의 재무가 무너지고 있는가" (설계 §9.2).
                      #   **후보는 코드가 정한다** (구획 I-A 의 triage 상위 N) — LLM 은 명단을
                      #   만들지 않고 받는다 (CLAUDE.md §4). --top-n --provider --refresh --show
                      #   산출물 state/stock_notes/<TICKER>.yaml → 다음 daily 의 J 축에 반영.
                      #   노트가 없으면 J = J_theme (오늘의 식이 특수해다)
msa picks <theme>     # L4 종목 선정 — **하드 제외 통과 종목 전부 · 테마 내 동일가중** (2026-08-24,
                      #   docs/06 §5.1·§6.1 · journal/2026-08-24-l4-selection-retired.md).
                      #   S·T·M 3축 · 종합 · 순위 · 바벨 라벨은 함께 산출되나 **관찰 지표**이고
                      #   선정에 쓰이지 않는다. --asof --top(관찰용 바벨 라벨 수) --no-write
                      #   --no-physical. 산출물 state/picks/<date>/<theme>/ (ranking·excluded·report·meta)
msa check             # 포지션 점검 (M8) — 트리거·무효화·Tier-2·사다리·시간스탑·TP. --asof --daily|--weekly
                      #   산출물 state/checks/<date>/ (report·alerts.json·journal-draft). 주문은 내지 않는다
msa journal new --from f.yaml   # 저널 항목 추가 (필수 필드 비면 거부 · 덮어쓰기 불가) — template <type>
msa journal verify    # journal/ append-only 검사 (pre-commit: scripts/journal-precommit.sh · install-hook)
msa journal diff <theme>        # 최근 두 thesis 스냅샷 필드 diff (논지 표류)
msa ops schedule --print-cron   # 케이던스 → crontab/systemd 텍스트 (설치는 사람이) · ops due <cadence>
msa ops calibration   # cycle_confidence 캘리브레이션 (N<20 → 결론 없음)
msa ops rejections-update       # 기각 대장 r_12m/r_24m 갱신 + 세 질문 → state/rejections-summary.md
msa ops ingest-theses --theses-dir state/theses/<date> [--scan state/scans/<date>] [--dry-run]
                      #   L3 라운드 → 저널 기각 항목·기각 대장·관찰 목록·진입 초안(journal-draft-*.yaml).
                      #   진입 항목은 쓰지 않는다 — 사람이 초안을 채워 msa journal new --from
msa ops reproduce <date>        # state/scans/<date>/ 스냅샷만으로 리포트 재생성·대조
msa run monthly       # 월간 한 번 (배선 W4): scan → 상위 K 선정 → research → ingest → picks →
                      #   assemble → portfolio(제안). --asof --top-k 8 --themes a,b --provider none|mock|fixture|anthropic
                      #   --human-theses DIR --capital N --skip-research/-picks/-portfolio --no-write
                      #   산출물 state/runs/<date>/ (monthly-report.md·run.json) — 끝은 제안·초안, 집행은 사람.
                      #   기본 --provider none = L3 미호출(키 없음): 사람 논지/직전 thesis 만 찾는다. exit 1 은 스캔 중단만
msa run weekly        # 주간: 전수 스캔 + msa check --weekly + weekly-report.md. --asof --no-write
msa run daily         # 일간: 후보 다이제스트 (스캔→상위 K→테마별 L4 랭킹→직전 diff→보유 점검).
                      #   --asof --top-k 8 --themes a,b --per-theme 5 --no-write --send
                      #   산출물 state/daily/<date>/ (digest.json·digest.md·report.txt·triage.csv)
                      #   triage.csv — 구획(I-A 지금 볼 자리/I-B 고점권/II 판별 대기/III 판별 전) +
                      #   **읽는 순서** 점수. 수익률 순서가 아니다 (docs/superpowers/specs/
                      #   2026-08-29-hedge-fund-evolution-design.md §3.3). 참고 열(s_pct·composite·
                      #   rs_rating)은 실리되 점수 입력이 아니다. 증거 처리 대장
                      #   state/evidence_resolutions/<theme>.yaml 이 있으면 J 축에 반영된다 — 읽기 전용 후보 뷰,
                      #   측정값·후보 목록이지 투자 조언이 아니다. 결정 케이던스는 월간 그대로
                      #   --send 가 그 실행의 모든 발신(다이제스트 + 보유 점검 알림)을 지배한다 —
                      #   없으면 아무것도 나가지 않고 alerts.json 만 남는다 (suppressed)
msa run quarterly     # 분기 명령 목록 (ops calibration · ops rejections-update) — 나열만
msa backtest l1       # L1 백테스트 관문 0 (M3.5) — rank-IC·스프레드·breadth_lead·DSR/PBO.
                      #   산출물 state/backtests/l1/<date>/ · 판정 docs/backtest-l1.md. 튜닝 루프가 아니다
msa backtest l1-structures  # L1 점수 구조 검정 — M3.6 S0/S1/S2 (docs/12 §4) + M3.7 S3(C 단독)/S2ʹ(C·E)
                      #   (docs/17 §4 — 짝지은 스프레드 차 X−S2 의 CI 하한 > 0). 결과 docs/backtest-l1.md §12·§14
msa backtest l4       # L4 종목 선정 백테스트 (docs/14 사전 등록의 집행) — 테마 내 rank-IC·축 단독·하드 필터.
                      #   산출물 state/backtests/l4/<date>/ · --jobs 병렬 · 테마별 parquet 캐시라 중단해도 이어서 돈다
msa backtest l4-structures  # L4 선정 구조 비교 (docs/15 사전 등록의 집행) — B0~B4 후보 규칙의 테마 EW 초과·
                      #   사망률·회전율·PBO. 산출물 state/backtests/l4-structures/<date>/ · 판정 docs/15.
                      #   --force --jobs --themes/--max-months(스모크, 판정 아님) --no-write.
                      #   특성 패널 캐시는 `msa backtest l4` 의 것을 그대로 재사용한다
```

텔레그램 배달은 `MSA_TELEGRAM_TOKEN` · `MSA_TELEGRAM_CHAT_ID` 가 둘 다 있을 때만 — 없으면 "not configured".
보낼지 말지는 명령의 플래그가 정한다 (`msa check --no-send` · `msa run daily --send`) — 껐으면 "suppressed" 이고
어느 경우든 `alerts.json` 은 쓴다.

패키지 관리는 **uv**. `pip install` 하지 않는다.
