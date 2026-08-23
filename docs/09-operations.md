# 09 · 운영 — 케이던스 · 결정 저널 · 배달

## 1. 케이던스

의사결정자가 직업이 있다는 제약에서 나온다. **월간이 의사결정 주기, 주간이 점검 주기.**

| 주기 | 작업 | 소요 | 산출 |
|---|---|---|---|
| **월간** (1영업일) | L0 적재 → L1 전수 스캔 → L2 국면 갱신 → 상위 K L3 → L4 → L5 | 사람 30~60분 검토 | 테마 스코어보드 + 매매계획서 |
| **주간** (월요일) | 보유 포지션의 **트리거·무효화 점검** + L1 경량 갱신 (가격 블록만) | 사람 5~10분 | 점검 리포트 |
| **일간** | 무효화 트리거 발동 여부만 자동 확인 | 0분 (알림 시에만) | 알림 |
| **분기** | 모순 감사(`03-macro-dag.md` §6) + 캘리브레이션 갱신(`10-validation.md` §4) + **기각 대장의 12·24M 수익률 갱신**(`10-validation.md` §5) | 사람 1시간 | 감사 리포트 |
| **수시** | 신규 테마 진입 검토 (사용자 발의) | | |

> **배선 (2026-08-23, W4).** `msa run monthly` 가 월간 행의 순서(스캔 → 거시 → 상위 K 선정 → L3 → 적재 →
> L4 → L5)를 그대로 실행하고 `state/runs/<date>/monthly-report.md` 에 단계별 `ok|skipped|unavailable|failed`
> 와 사유를 남긴다 — **끝은 제안·초안**(진입 초안 · `positions-proposal.yaml` · 관찰 목록 행)이며 집행은
> 사람이 한다. `msa run weekly` 가 주간 행(전수 스캔 + `msa check --weekly`)이다 — "L1 경량 갱신(가격
> 블록만)" 은 따로 만들지 않았다: 캐시가 있으면 전수 스캔이 ~12 초라 경량 경로의 이유가 없다. 일간은
> `msa check --daily` 그대로, 분기는 `msa run quarterly` 가 세 명령(`msa macro` 모순 감사 · `ops
> calibration` · `ops rejections-update`)을 **나열만** 한다. cron 은 `msa ops schedule --print-cron`.
> 구현 노트는 이 문서 끝 "케이던스 오케스트레이터".

**월간 스캔이 만드는 것 vs 사람이 하는 것**

| 기계 | 사람 |
|---|---|
| 스코어보드 · 국면 · thesis · 종목 랭킹 · 비중 · 스탑 · TP | **어느 테마를 실제로 편입할지 최종 결정** |
| 하드 게이트 기각 | 기각을 뒤집을지 (근거를 저널에 기재) |
| 트리거·무효화 관측 | 관측의 해석이 애매할 때의 판정 |
| 사다리 조건 충족 알림 | **주문 집행** |

> 자동 주문은 만들지 않는다 (`00-overview.md` §5). 사이클 논지는 6~18개월 걸리고,
> 그 사이 세상이 바뀐다. 사람이 개입하지 않는 구조는 여기서 이점이 아니라 위험이다.

## 2. 결정 저널 — 이 저장소에서 검증을 하는 유일한 물건

`journal/` 아래에 **append-only** (`CLAUDE.md` §6).

```
journal/
├── 2026-08-03-offshore-drilling-reject.md # 기각 결정 + 게이트 판정 (편입 안 해도 남긴다)
├── 2026-09-01-uranium-entry.md          # 논지 전문 + 진입 계획 전문
├── 2026-09-01-uranium-entry.thesis.yaml # 기계 판독용 thesis 객체 스냅샷
├── 2026-10-06-uranium-check.md          # 주간/월간 점검: 트리거 상태 변화만
├── 2026-11-03-uranium-add2.md           # 사다리 2단 실행 + 그때의 판단
├── 2027-03-02-uranium-tp1.md
└── 2027-06-01-uranium-exit.md           # 청산 + 사후 대조
```

**진입 항목이 담는 것** (하나라도 빠지면 항목이 불완전):
- thesis 객체 전문 (claim · mechanism · triggers · invalidations · evidence · `cycle_confidence`)
  — `cycle_confidence` 는 **누가 산출했는지**(사람 / `referee`)를 함께 적는다. M6 구간에는
  사람이 `04-value-trap.md` §4 규칙을 적용해 산출하며(`11-roadmap.md` "M6 구간에 `c` 를
  누가 만드는가"), 그 표본도 `10-validation.md` §4 캘리브레이션에 들어간다
- `bear_case` 원문
- L1 블록 6개 값 + L2 tailwind + 가치함정 5축 판정
- 종목 · 비중 · 사다리 3단 가격 · Tier1/2 스탑 · 시간 스탑 날짜 · TP 3단
- **기계 권고와 다르게 결정했다면 그 이유**

**점검 항목이 담는 것**:
- 각 trigger 의 상태 변화 (`pending` → `met` / `missed`)
- 각 invalidation 의 상태
- thesis 재실행 시 **이전 버전과의 diff** (논지 표류 추적 — `05-agent-research.md` §6)

**기각 항목이 담는 것** (편입하지 않은 것도 결정이다 — `10-validation.md` §5 기각 대장의 입력):
- 기각 경로 — **분류 목록은 여기서 다시 적지 않는다.** 정본은 `10-validation.md` §5 의
  기각 대장 표이고, 기계 판독용 값은 `specs/thesis.schema.yaml` `gate_result.path` 의 enum 이다
  (§4 `rejections.yaml` 의 `path` 열과 같은 값). 저널 항목에는 그중 **어느 경로였는지**를 적는다
- thesis 의 `value_trap_axes` 전문 (`05-agent-research.md` §3) — 5축 판정과 그 근거 `evidence_refs`
  (`04-value-trap.md` §3 이 이미 "리포트에 기각 사유 기재" 를 요구한다. 저널은 그 사유의 원본이다)
- 기각 시점의 `cycle_confidence` (산출된 경우) 와 스코어보드 순위
- **기계가 통과시킨 것을 사람이 편입하지 않았다면 그 이유** (§1 표의 반대 방향 개입)
- 이후 12·24개월 수익률은 **여기에 쓰지 않는다.** 저널은 append-only 이므로
  나중에 값이 채워지는 기록을 담을 수 없다 → `state/rejections.yaml` (§4) 이 기계적으로 갱신한다

**청산 항목이 담는 것**:
- 어느 스탑/TP 로 나갔는가
- 실현 수익률과 보유 기간
- **트리거 충족률** — 몇 개 중 몇 개가 실제로 관측되었나
- 메커니즘이 서술대로 작동했는가 (맞았어도 **다른 이유로** 맞았을 수 있다)
- `cycle_confidence` 가 사후에 적절했는가 → `10-validation.md` 의 입력

> 사후 편집 금지가 왜 절대 규칙인가: 이 저널이 이 저장소에서 성과를 검증하는
> **유일한** 데이터다. 백테스트가 없으므로 다른 증거가 없다.
> 진입 시점의 논지를 나중에 손보면 검증 대상 자체가 사라진다.
> 생각이 바뀌면 새 항목을 추가하고 이전 항목을 링크한다.

## 3. 배달

`fin-checkup` 의 알림 스택을 이식한다.

| 채널 | 내용 | 시점 |
|---|---|---|
| 마크다운 리포트 | 스코어보드 · 국면 · thesis · 매매계획서 전문 | 월간 |
| 텔레그램 | 월간 요약 (상위 5테마 + 계획 변경분) | 월간 |
| 텔레그램 | **무효화 트리거 발동** | 즉시 |
| 텔레그램 | 사다리 조건 충족 (가격 + 논지 조건 **동시** 충족) | 일간 확인 |
| 텔레그램 | **시간 스탑 30일 전 예고** | 해당 시 |
| 텔레그램 | TP 조건 충족 | 일간 확인 |

알림 문구 규약 (`fin-checkup` 승계): **측정값과 사실만 전달하고 투자 권유를 하지 않는다.**
"CCJ 사세요" 가 아니라 "CCJ 사다리 2단 조건 충족: 가격 −13.2%, 무효화 0건, 트리거 1/3 충족".

## 4. 상태 파일

```
state/
├── themes.yaml              # 테마 버킷 정의 (수동 편집 대상)
├── macro-dag.yaml           # 인과 DAG (수동 편집 대상)
├── positions.yaml           # 현재 보유 + 사다리 진행 상태
├── watchlist.yaml           # 편입 전 관찰 테마 + 대기 조건
├── rejections.yaml          # 기각 대장 — 기각 시점 행 + 사후 12·24M 수익률 열 (기계 갱신)
└── scans/YYYY-MM-DD/        # 월간 스캔 산출물 스냅샷 (재현용)
    ├── scoreboard.parquet
    ├── macro_state.json
    └── theses/*.yaml
```

`scans/` 는 재현성을 위해 보존한다. **몇 달 뒤 "그때 왜 이 테마가 3위였나" 를
답할 수 없으면 캘리브레이션이 불가능하다.** 같은 이유로 기각 대장의
"상위 K 컷오프 바로 아래" 질문(`10-validation.md` §5 (c))도 `scans/` 의 순위 스냅샷에 의존한다.

**`rejections.yaml` 이 `journal/` 이 아니라 `state/` 에 있는 이유.** 각 행은 기각 시점에
append 되지만 `r_12m`·`r_24m` 열은 12·24개월 뒤에 기계가 채운다. 저널은 append-only 이고
사후 편집이 금지되므로(`CLAUDE.md` §6), **나중에 값이 채워지는 기록은 저널에 둘 수 없다.**
대신 **기각 결정 자체**는 저널 항목으로 남고(§2), 대장의 각 행은 그 저널 항목을 참조한다.

```yaml
- theme: offshore_drilling
  rejected_at: 2026-08-03
  path: hard_gate              # hard_gate | conf_floor | secular_risk | rank_cutoff | human
  reason: "축1 사망(unit_cagr_10y −4.1%) AND 축3 경고"
  cycle_confidence: 0.31       # 산출되지 않았으면 null
  scoreboard_rank: 3
  journal: journal/2026-08-03-offshore-drilling-reject.md
  scan: state/scans/2026-08-03/
  r_12m: null                  # 분기 감사에서 기계가 채운다
  r_24m: null
```

행 추가는 자유롭되 **기존 행의 기각 시점 필드(`path` 이하 `scan` 까지)는 수정하지 않는다.**
채울 수 있는 것은 사후 수익률 열뿐이며, 그 값으로 임계값을 조정하는 것은
`CLAUDE.md` §1 위반이다 (`10-validation.md` §5 경계).

### 구현 노트 (M8) — 상태 파일 스키마와 점검 규약

구현은 `src/msa/ops/` (`journal` · `state_files` · `check` · `alerts` · `scheduler` · `calibration` ·
`rejections` · `reproduce`). 아래는 문서 본문이 정하지 않은 것을 **구현이 선언**한 부분이다.
L3·L4·L5 와의 연결은 전부 이 파일 계약으로 한다 — `msa.ops` 는 다른 계층 패키지를 import 하지 않는다.

**`positions.yaml`** (`state_files.Position`, L5 매매계획 → 사람이 체결을 반영, `msa check` 는 읽기만):

```yaml
asof: 2026-09-01
positions:
  - ticker: CCJ
    theme: uranium
    role: anchor                      # anchor | torque (07 §1)
    target_weight: 0.16
    opened_at: 2026-09-01
    entry_price: 50.00                # 1단 진입가 — 사다리·Tier-2 "초기가 대비 %" 의 기준
    ladder:                           # 07 §3. trigger_pct 는 초기가 대비 하락률(양수)
      - {step: 1, weight: 0.50, trigger_pct: 0.00, trigger_price: 50.00,
         filled_date: 2026-09-01, filled_price: 50.00, filled_shares: 100}
      - {step: 2, weight: 0.30, trigger_pct: 0.13, trigger_price: 43.50}
      - {step: 3, weight: 0.20, trigger_pct: 0.23, trigger_price: 38.50}
    tier2_stop_price: 32.50           # 평단 −35% (07 §4). TP1 체결 후 check 가 본전으로 읽는다
    tier2_basis: avg_minus_35         # avg_minus_35 | breakeven
    time_stop_date: 2028-03-01        # opened_at + horizon 상한
    horizon_months: [6, 18]
    tp:                               # 07 §5. price 가 있으면 기계가 본다, 없으면 manual
      - {level: tp1, fraction: 0.333, condition: "밸류 P50 회복 또는 +2R", price: 85.00}
      - {level: tp2, fraction: 0.333, condition: "P75 또는 직전 고점 50% 회복"}
      - {level: runner, fraction: 0.334, condition: "10주선 이탈 또는 고점 −25%"}
    runner_trail_pct: 0.25
    runner_ma_weeks: 10
    thesis_snapshot: journal/2026-09-01-uranium-entry.thesis.yaml
    journal_entry: journal/2026-09-01-uranium-entry.md
    status: open                      # proposed | open | closed
```

`status: proposed` 는 L5 가 낸 **미체결 제안** 행이다 (`msa portfolio --emit-positions` →
`state/portfolio/<date>/positions-proposal.yaml`, 배선 W2 2026-08-23). 이 상태에서만 `thesis_snapshot`·
`journal_entry` 를 비워 둘 수 있고, `msa check` 는 이 행을 **점검하지 않고** 리포트 머리에 "미체결 제안 N건 — 점검하지
않았다. 집행은 사람이 한다" 로만 적는다 (문제·종료 코드에 넣지 않는다 — 제안은 오류가 아니다). 사람이 체결을 반영해
`open` 으로 올리면 그때부터 저널 링크가 필수가 되고 점검 대상이 된다. 승격 절차는 같은 디렉터리의
`positions-proposal.md`. **기계는 `state/positions.yaml` 을 쓰지 않는다.**

**`watchlist.yaml`** (`state_files.WatchItem`): `theme` · `added_at` · `reason`
(`contested` | `axis1_unavailable` | `awaiting_condition` | `human`) · `waiting_condition`(비면 거부 —
관찰이 아니라 방치다) · `scan` · `thesis_snapshot?` · `journal?` · `scoreboard_rank?`.

**`rejections.yaml`**: 본문 §4 의 스키마 그대로 + 선택 `axis_verdicts`(5축 스냅샷, (a)(b) 집계용).
`save_rejections()` 는 이전 파일과 대조해 **행 삭제 · 기각 시점 필드 변경 · 채워진 `r_*` 변경**을
전부 예외로 막는다. 채울 수 있는 것은 `null → 값` 한 번뿐이다.

**기계 판정 DSL** — thesis 의 `triggers[*]` · `invalidations[*]` 에 선택 `check:` 블록:

```yaml
check: {kind: price_below, ticker: URA, level: 70, days: 63}          # 종가 < level 이 days 거래일 연속
check: {kind: price_above, ticker: CCJ, level: 60, days: 1}
check: {kind: drawdown_from_high, ticker: CCJ, pct: 0.30, lookback_days: 252}
```

`check:` 가 없으면 `manual` 이고 리포트가 사람 몫으로 나열한다. 현재 상태의 출처는 **가장 최근 점검 저널
항목의 `after`** (없으면 스냅샷의 `status`). 기계는 저널을 쓰지 않는다 — `state/checks/<date>/journal-draft-<theme>.yaml`
초안을 남기고 사람이 `msa journal new --from` 으로 확정한다. 사다리 3단의 "트리거 진행 중" 은
**충족 ≥1 AND 2단 체결** 로 읽는다 (선언).

**`state/checks/<date>/`**: `report.txt` · `alerts.json`(항상) · `positions.json` · `journal-draft-*.yaml`.
`state/checks/last_run.json` 은 마지막 성공 점검 시각 (벤더링한 `fin-checkup` 스케줄러의 "놓친 구간" 로직).
`state/calibration/<date>.{txt,json}` · `state/rejections-summary.md` 도 생성물이다. 모두 `.gitignore`.

**알림 종류**: §3 표의 6종 (`monthly_report` · `monthly_summary` · `invalidation_fired` ·
`ladder_step_met` · `time_stop_warning` · `tp_met`) + `tier2_stop_hit` (07 §4 — 표에는 없지만 점검이
평가하므로 알림도 낸다). 텔레그램은 `MSA_TELEGRAM_TOKEN` · `MSA_TELEGRAM_CHAT_ID` 가 **둘 다** 있을 때만
보내고, 없으면 "not configured" 로 보고한다. 문구는 `alerts.FORBIDDEN_WORDING` 을 통과해야 하며 테스트가
모든 템플릿을 그 목록에 통과시킨다.

**케이던스**: `msa ops schedule --print-cron` 이 crontab 텍스트를 출력한다 (설치는 사람이). cron 이
"1영업일" 을 못 쓰므로 1~3일에 깨우고 `msa ops due monthly` 가 그 달 첫 평일일 때만 0 을 돌려준다 —
미국 공휴일은 보지 않는다 (1일이 공휴일이면 하루 늦게 돈다).

**아직 연결되지 않은 것**: thesis 스냅샷은 L3(M7) 또는 사람(M6 구간)이 만든다. `positions.yaml` 은 L5 가
**제안**(`positions-proposal.yaml`, 위 `proposed`)까지만 만들고 실제 파일은 사람이 쓴다 — 배선 W2.
`rejections.yaml` 행 적재와 관찰 목록은 아래 "L3 → 운영 적재" 가 연결했다 — 배선 W3. 월간·주간 한 명령은
아래 "케이던스 오케스트레이터" — 배선 W4. 월간 요약 알림(`monthly_summary`)의 "계획 변경분" 은 아직
`msa run monthly` 가 보내지 않는다 (리포트 파일만).

### 구현 노트 — L3 → 운영 적재 (`msa ops ingest-theses`, `src/msa/ops/ingest.py`)

`msa research` 가 남긴 라운드(`state/theses/<date>/`)를 저널·기각 대장·관찰 목록으로 옮긴다. **기계가
쓰는 것과 사람이 써야 하는 것의 경계**가 이 명령의 전부다:

| `gate_result` | 기계가 쓴다 | 사람이 쓴다 |
|---|---|---|
| `rejected` | 저널 **기각 항목** `journal/<asof>-<theme>-reject.md` + `.thesis.yaml` 스냅샷 (§2 "기각 항목이 담는 것" — 경로 enum · 5축 판정 · `cycle_confidence` 또는 null · 스코어보드 순위 · 스캔 경로; `override_reason` 은 비운다 — 기계가 기각한 것이라 "사람이 편입하지 않은 이유" 가 성립하지 않는다) → `rejections.yaml` 행 (`journal` 열 = 그 항목) | 없음. 기계 통과를 사람이 뒤집어 기각하는 경우(`path: human`)만 사람이 `msa journal template reject` 로 직접 쓴다 |
| `contested` | `watchlist.yaml` 행 `reason: contested` — `waiting_condition` = referee 판정 + `key_uncertainties`, `thesis_snapshot`, `scoreboard_rank` | 없음 (재연구가 해소한다) |
| `passed` · `portfolio_eligible: false` | `watchlist.yaml` 행 — 축 1 불가(`axis1_available: false`)가 원인이면 `axis1_unavailable`, 아니면 `awaiting_condition` + 게이트가 적은 사유 | 없음 |
| `passed` · `portfolio_eligible: true` | **진입 항목 초안** `state/theses/<date>/journal-draft-<theme>.yaml` — `msa journal new --from` 이 받는 entry 모양. thesis 전문 · 5축 · `scan` · L1 블록 6개(`scoreboard.csv`) · `l2_tailwind`(`state/macro/latest.json`, 없으면 thesis 의 `inputs.macro_tailwind`) · `confidence_provenance: referee` 까지 채운다 | `stocks`(종목·비중·사다리·Tier-2·시간스탑·TP — L5 매매계획서에서) · `deviated_from_machine`/`deviation_reason`. 초안에 없는 값(블록·tailwind 를 못 읽은 경우)은 **0 이 아니라 비워** 두므로 `EntryRecord` 가 채울 때까지 거부한다 |

저널은 여기서도 append-only 다 — 기존 파일은 건드리지 않고 같은 이름의 기각 항목이 있으면 그 경로를 대장에
쓴다. 기각 대장은 `(theme, rejected_at)` 이 이미 있으면 건너뛰고 보고한다 (재실행 멱등). 관찰 목록은 테마별
upsert (기존 `added_at` 유지). 스코어보드 순위는 `--scan` 의 `scoreboard.csv` 에서 읽고, 없으면 thesis 가
연구 시점에 기록한 `inputs.scoreboard_rank` 로 대체하되 **그 사실을 보고한다**; 둘 다 없으면 기각 항목은
쓰지 않는다(§2 가 순위를 요구한다) 하고 "적재 불가" 로 보고한다. 읽지 못한 파일·enum 밖 상태도 이름과 이유가
보고서에 남는다 — 조용히 빠지는 테마는 없다. `--dry-run` 은 같은 판정을 하되 쓰지 않는다.

### 구현 노트 — 케이던스 오케스트레이터 (`msa run monthly|weekly|quarterly`, `src/msa/pipeline/run.py`, 배선 W4)

§1 의 월간·주간 행을 **한 명령**으로 잇는다. 새 계산·임계값은 없다 — 각 계층의 진입점(`run_scan` ·
`run_macro` · `run_research` · `ingest_round` · `run_picks` · `assemble_inputs` · `run_portfolio` · `run_check`)을
순서대로 부르고, 단계마다 `{status, reason, outputs, seconds}` 를 `RunReport` 에 남긴다.

| 단계 | 호출 | 실패 시 (§5 와 같다) |
|---|---|---|
| `scan` | `run_scan` | **중단** (exit 1). 데이터·커버리지 관문 실패면 뒤 단계 전부 `skipped` |
| `macro` | `run_macro` | 중단하지 않는다. 예외·가용 드라이버 0 → `unavailable`; 결측 드라이버는 사유에 수로 |
| `select` | 스코어보드 상위 K **자격** 테마(S2 `eligible`) + `--themes` 지정 | 자격이 K 미만이면 그만큼만 — 풀 미달로 채우지 않는다 (`02` §7.1). SECULAR·소표본은 플래그만, 제외하지 않는다 (게이트는 L3 몫) |
| `research` | `--provider none`: 사람 논지(`--human-theses <dir>/<theme>.yaml`) → 직전 `state/theses/<date≤asof>/` 순으로 **찾기만**; `mock\|fixture\|anthropic`: 테마별 L3 | 테마별 격리 — 스키마 기각은 그 테마 제외 + 사유, 제공자 오류는 보고, 라운드는 계속. `none` 에서 논지가 없는 테마는 "thesis 없음 → 관찰" (오류가 아니다) |
| `ingest` | 이번 실행이 쓴 L3 라운드 → `ingest_round` (기각→저널+대장 · contested→관찰 · 통과→진입 초안) | `none` 이면 새 라운드가 없어 `skipped` |
| `picks` | 게이트 편입 가능(`portfolio_eligible`) thesis 가 있는 테마만 `run_picks` | 테마별 격리 |
| `assemble` · `portfolio` | `assemble_inputs` → `run_portfolio(emit_positions=True)` → `plan.md` · `positions-proposal.yaml` | 묶을 테마가 0 이면 `skipped` (오류가 아니다) |
| `report` | `state/runs/<asof>/monthly-report.md` · `run.json` — 단계 표 + **사람이 할 것**(채울 초안 · 승격할 제안 · 관찰 행) | |

**오늘 `--provider none` 이 뜻하는 것.** `ANTHROPIC_API_KEY` 가 없는 현재 기본값이다. L3 를 부르지 않으므로
새 thesis 는 생기지 않고, 사람이 쓴 논지 디렉터리나 직전 라운드의 thesis 가 있는 테마만 L4·L5 로 간다.
둘 다 없으면 그 달의 월간 실행은 스코어보드·거시 상태·선정 목록과 "thesis 없음 → 관찰" 목록에서 끝난다 —
그것이 키 없이 기계가 할 수 있는 전부이고, 그렇게 **보고한다.** 키가 생기면 cron 행에 `--provider anthropic`
을 사람이 붙인다 (비용이 드는 호출을 기본값으로 두지 않는다).

`--no-write` 는 `state/` 에 아무것도 쓰지 않는다. 계층들이 파일 계약으로 이어지므로 중간 산출물은 임시
샌드박스 디렉터리에 쓰고 끝나면 지우며, 저널·기각 대장·관찰 목록은 `ingest_round(write=False)` 로 판정만
한다. 종료 코드는 스캔 중단일 때만 1 — 거시 불가·테마별 실패·편입 가능 테마 0 은 0 + 리포트다.

`msa run weekly` = `run_scan` + `run_check(mode="weekly")` (알림 파일·텔레그램·`last_run.json` 은
`msa check --weekly` 와 같다) + `weekly-report.md`. 점검의 문제(스냅샷 없음 등)는 리포트의 "사람이 할 것" 에
들어가고 종료 코드에는 넣지 않는다. `state/runs/` 는 `.gitignore`.

## 5. 실패 시 동작

| 상황 | 동작 |
|---|---|
| 데이터 적재 실패 | **스캔 중단.** 부분 데이터로 스코어를 내지 않는다 (`CLAUDE.md` §2) |
| 커버리지 감사 실패 | 스캔 중단 + 알림 |
| FRED 시리즈 결측 | 해당 드라이버 `state = 0` (중립) 처리 + 리포트에 표시. 중단하지 않음 |
| 에이전트 스키마 검증 실패 | 해당 테마 thesis 없음 → 후보에서 제외 + 사유 기록 |
| 최적화 infeasible | 제약 완화 순서를 **고정**: C3(집중도) → C1(MDD). MDD 는 마지막까지 지킨다. C2(ENB)는 구속 제약이 아니라 리포트 지표이므로(`07-portfolio.md` §2) 애초에 완화 대상이 아니다 — infeasible 의 원인도 될 수 없다 |
