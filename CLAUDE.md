# macro-sector-agent — 작업 규약

산업 사이클 → 테마 → 종목 → 포트폴리오 하향식 리서치 파이프라인 (`src/msa/`, CLI `msa`).
계층: L0 데이터 · L1 스캐너(`scan`) · L3 에이전트(`research`) · L3.5 수급(`balance`) ·
P2 매크로(`regime`) · P3 종목 노트(`stock-notes`) · L4 종목(`picks`) · L5 포트(`portfolio`) ·
운영(`check`/`journal`/`ops`) · 케이던스(`run monthly|weekly|daily|quarterly`) · 관문 0(`backtest`).
**L2 거시 DAG 는 2026-08-23 에 제거됐다** (설계 질문 2 → C, `docs/13` §9 ·
`journal/2026-08-23-l2-removed.md`) — 되살리려면 revert 가 아니라 새 설계 질문과 사전 등록이 필요하다.
이후 단계는 `docs/11-roadmap.md`. **어느 계층이든 손대기 전에 해당 `docs/` 를 먼저 읽는다.**

## 절대 규칙

코드·문서 주석 수백 곳이 `CLAUDE.md §N` 으로 이 번호를 가리킨다 — **번호를 바꾸지 않는다.**
여기는 요약이고, 근거·사례를 담은 전문은 `docs/rules.md`.

1. **탐색으로 가중치를 정하지 않는다 — 이 저장소의 지배적 실패 유형(오버피팅).**
   L1 블록 가중치·L4 축 가중치·임계값은 **선언하고 근거를 적는다.** 근거가 없으면 없다고 적는다
   (`src/msa/basis.py` `NoBasis`). 파라미터 스윕·그리드 서치·"성과가 좋아지는 방향으로" 는 금지.
   과거 데이터로 확인하는 것은 허용(`docs/10` §2 관문이 요구) — 금지는 **확인 결과로 값을 바꾸는 것.**
   검정이 "이 블록은 일하지 않는다" 고 하면 그 사실을 기록하고 가중치는 둔다.
   구조를 바꾸려면 먼저 사전 등록 문서를 쓴다(`docs/12`·`14`·`15`·`17` 이 그 예).
2. **조용한 절단 금지.** 요청한 것보다 적게 받으면 예외를 던지거나 경고를 남긴다. 제외한 것은 세어서
   돌려준다. 테마 버킷 커버리지 감사(`docs/01`)는 매 적재마다 — 미분류 시총 비율이 임계를 넘으면 스캔 중단.
3. **출처 없는 에이전트 주장은 저장되지 않는다.** L3 산출물의
   `evidence: [{claim, source_url, date, reliability}]` 가 비면 스키마 거부. LLM 의 기억은 증거가 아니다.
4. **에이전트는 테마만 고른다. 종목은 결정론적 계층이 고른다.** LLM 에게 종목 명단을 만들게 하지 않는다
   (유명세 편향). L3 는 논지만, L4 랭킹·P3 후보 선정은 코드가 한다.
5. **논지는 무효화 조건 없이 저장할 수 없다.** `thesis.invalidations` 가 비면 스키마 실패
   (Tier-1 스탑의 근거, `docs/07` §4).
6. **결정 저널은 append-only.** `journal/` 의 기존 파일을 수정·삭제하지 않는다. 생각이 바뀌면 새 항목을
   추가하고 이전 항목을 링크한다. 항목은 `msa journal template <type>` → `msa journal new --from f.yaml`.
   PreToolUse 훅 `.claude/hooks/journal-guard.sh` 가 커밋된 저널 파일의 Edit/Write 를 막는다(새 파일은 통과).
7. **성과 수치를 광고하지 않는다.** README·리포트에 기대수익률·승률·수익 배수·전략 CAGR/Sharpe 를 쓰지
   않는다. L1·L4 백테스트는 스코어의 예측력(rank-IC·분위 스프레드)이지 전략 수익률이 아니다.
   쓸 수 있는 것: 검정 결과(IC 와 CI, 시도 수를 명시한 DSR·PBO)와 전향적 기록(트리거 충족률·Brier).
8. **투자 조언이 아니다.** 산출물은 측정값과 명시된 가정이다. 집행은 사람이 하고, 자동 주문 기능은 만들지 않는다.

## PIT 규약 (표·이유 전문: `docs/rules.md` 'PIT 규약')

- **백테스트 경로**(`docs/10` §2): PIT 전부 필요, 예외 없음. `datekey` 기준 적재만 쓰고 `reportperiod` 로 정렬하지 않는다.
- **오늘의 스캔 경로**: 자기이력 백분위(밸류·ROIC·마진)·자본 사이클 시계열(capex/D&A, 자산성장)은 PIT 필요,
  오늘의 스냅샷(부채비율·현금 런웨이)은 불필요.
- 코드는 각 지표가 **어느 쪽인지**와 **어느 경로에서 호출됐는지**를 명시한다(`src/msa/data/pit.py`).
  그 분기를 호출자만 알고 있으면 몇 달 뒤 조용히 섞인다.

## 명령

```bash
make install     # uv sync — 패키지 관리는 uv. pip install 하지 않는다
make check       # ruff check + ruff format --check + mypy(strict) + pytest -m "not data and not net" (~40초)
make fmt         # ruff format + ruff check --fix — CI 가 format --check 로 막는다 (056f5ee)
make test-all    # data·net 마커 포함 — 실제 DuckDB 스토어·FRED 키 필요
uv run msa <cmd> --help
```

`msa` 각 명령의 옵션·산출물 경로·종료코드는 `docs/cli-reference.md` (옛 CLAUDE.md 명령 절 전문).

## 운영 흐름과 함정

- **`msa research` 는 한 번에 하나씩 돌린다.** 2026-08-29 두 배치를 동시에 돌리자 4건이 전부
  ProviderError(종료코드 3, 속도 제한)로 죽었고 순차로 돌리니 통과했다(3956883). `docs/18` §4 의
  병렬 예시보다 이 규칙이 우선. 종료코드 2=스키마 거부(저장 안 함) · 3=제공자 오류(재시도하면 대개 된다).
- LLM 단계 기본 제공자는 `--provider claude_code`(로컬 `claude` CLI 하위 프로세스, API 크레딧 0). 키 없는
  운영이 기본이라 새 LLM 단계도 이 제공자로 맞춘다(ed9f92f — 증거 트리아지만 API 직행이라 매번 기계 순서로 떨어졌다).
  하위 프로세스는 중립 작업 디렉터리에서 돈다 — 저장소에서 돌리면 이 CLAUDE.md 가 실려 역할이 오염된다(`src/msa/l3/claude_code.py`).
- **`state/` 는 `<repo>/state`(`MSA_STATE`)이고 대부분 gitignore 된 실행·LLM 산출물이다** — 워크트리에는
  theses·balance·daily·scans 가 없다. 이전 산출물을 읽는 실행(`msa run daily`·`research`·`ops`)은
  `~/git/macro-sector-agent` 본 체크아웃에서 돌린다. `state/evidence_resolutions/` 와 `journal/` 은 사람의
  기록이라 커밋한다.
- **스토어 `~/data/us_micro.duckdb`(`MSA_DUCKDB`)는 읽기 전용이고 2026-09-10 에서 멈춰 있다.** Sharadar
  구독을 2026-09-14 해지했고 quant-airflow `dags/daily_sharadar.py` 가 꺼졌다(quant-airflow 86885b8).
  `docs/18` §6 의 `opt-factor ingest` 일간 적재 안내는 그 이전 서술이다. 리포트의 낙폭·가격은 스토어
  기준일 기준이라고 적는다 — 오늘 기준인 척하지 않는다.
- **daily 리포트 커밋은 main 에 직접 들어간다.** `msa run daily` 는 `README.md` 의
  `<!-- MSA:LATEST -->` … `<!-- /MSA:LATEST -->` 블록을 다시 쓴다(`--no-readme` 로 끔, 커밋은 사람이).
  그 블록은 손으로 고치지 않고, 커밋 메시지는 `daily 리포트 자동 갱신 — <실행일> (스토어 기준일 <날짜>)`
  (8d4358d·932ca3d). README 다른 부분을 고칠 때 블록 안을 건드리지 않는다.
- 결과 해석: triage 는 **읽는 순서**이지 수익률 순서·매수 신호가 아니다. 편입 가능 ≠ 매수 신호(`docs/18` §7.5).
- 텔레그램 발신은 `MSA_TELEGRAM_TOKEN`·`MSA_TELEGRAM_CHAT_ID` 가 둘 다 있고 명령 플래그가 켤 때만
  (`msa run daily --send`, `msa check --no-send`) — 아니면 `alerts.json` 만 남는다.

## 테스트·커밋

- 임시 git 저장소를 만드는 테스트는 `tests/conftest.py` 의 autouse `_hermetic_git` 픽스처에 기댄다 — 지우지
  않는다. 전역 `core.hooksPath` 의 커밋 신원 훅이 `t@example.com` 커밋을 거부해 `make check` 가 깨졌었다(8721201).
- 커밋 신원은 레포 git 설정(`chyohw97@gmail.com`) 그대로. `git -c user.email=...` 로 덮지 않는다 —
  세션 컨텍스트의 회사 이메일이 그렇게 섞인 사고가 있었고 `.github/workflows/commit-identity.yml` 이 거부한다.
- 커밋 메시지는 한국어로, 무엇보다 **왜 문제였는지**를 쓴다(기존 로그 문체). 저널 커밋은 `저널 — <요지>`.
- `journal/` append-only 검사 `msa journal verify` 는 로컬 훅에 **설치돼 있지 않다**(`msa journal install-hook`
  으로 설치 — 사람이 결정). 저널을 건드린 커밋 전에는 직접 돌린다.

## 문서 지도 — 해당 작업 전에 읽는다

| 언제 | 문서 |
|---|---|
| 처음·전체 구조 | `README.md` → `docs/00-overview.md` → `docs/18-daily-run.md`(운영·읽는 법) |
| 테마 유니버스·커버리지 | `docs/01-theme-universe.md`, `docs/theme-coverage-audit.md` |
| L1 스캔 | `docs/02-cycle-state.md`, `docs/12`·`docs/17`(점수 구조 사전 등록), `docs/backtest-l1.md` |
| 가치함정·L3 에이전트 | `docs/04-value-trap.md`, `docs/05-agent-research.md`, `docs/cases/`(few-shot) |
| L4 종목 선정 | `docs/06-stock-selection.md`, `docs/14`·`docs/15`(사전 등록), `docs/backtest-l4.md` |
| L5 포트·스탑 | `docs/07-portfolio.md` |
| 데이터 계약 | `docs/08-data-contract.md` |
| 운영·저널·케이던스 | `docs/09-operations.md` |
| 검증 관문(DSR·PBO) | `docs/10-validation.md` |
| 상수의 근거 | `docs/24-basis-registry.md` |
| 설계 질문 | `docs/19`~`docs/23`, `docs/25`(매크로 regime), `docs/26`(수급), `docs/27` |
| 헤지펀드 구조·triage 설계 | `docs/superpowers/specs/2026-08-29-hedge-fund-evolution-design.md` |
| 모듈 감사 후속 | `docs/16-module-audit-2026-08-24.md` |
