# 16 · 계층별 모듈 감사 — 2026-08-24

> **지위: 기록이다. 결정도 사전 등록도 아니다.** 이 문서는 2026-08-24 에 6개 워크트리로 병렬
> 수행한 L0·L1·L3·L4·L5·배선 감사의 결과를 하나로 합친 것이다. **코드는 0줄 바꿨다.**
> §7 의 우선순위는 **제안**이며, 값을 새로 정해야 하는 것은 그렇다고 표시했다 —
> 그것들은 별도 사전 등록 없이 손대지 않는다 (`CLAUDE.md` §1).
> 성과 수치는 없다 (`CLAUDE.md` §7). 있는 것은 측정값과 판정뿐이다.

작성 2026-08-24 · 브랜치 `feat/l4-backtest-and-fixes` · 스토어 `~/data/us_micro.duckdb`
(최종일 2026-08-14 · prices 45,663,901 행 · fundamentals 655,000 행).

---

## 0. 한 문단 요약

`src/msa/` 의 6개 계층(L0 데이터 · L1 스코어보드 · L3 리서치 · L4 종목 · L5 포트 · 운영 배선)을
각각 별도 워크트리에서 감사했다. 물은 것은 두 가지다 — **각 모듈이 자기 업무를 하고 있는가**,
그리고 **남의 업무를 대신 하고 있지는 않은가.** 결함 **57건**을 확인했다: 심각 2 · 높음 8 ·
중간 37 · 낮음 10. 계층 하나가 통째로 망가진 곳은 없었고, 파이프라인은 오늘 실제로 exit 0 으로
끝까지 돈다. 대신 같은 **다섯 가지 양식**이 계층을 가리지 않고 반복됐다 — ① 계산만 되고 아무도
안 읽음 ② 문서에 선언만 있고 코드에 대응물 없음 ③ 판정 불가를 통과로 처리 ④ 단위·공간이 섞임
⑤ 실패가 성공(또는 "건너뜀")으로 보고됨. 이 다섯은 2026-08-22~24 에 이미 다섯 번 발견됐던 바로
그 양식이고, 이번 감사는 그것이 우연이 아니라 저장소 전역의 성질임을 보였다. 잘 도는 것도
확인했고 §5 에 적었다.

---

## 1. 왜 이 감사를 했나

2026-08-22 부터 사흘 사이에 결함이 다섯 건 나왔고, **전부 같은 모양이었다.**

| 발견 | 무엇이었나 | 기록 |
|---|---|---|
| L2 거시 `final(t)` 미배선 | 문서는 "거시 순풍이 순위에 들어간다" 고 적었으나 순위 영향 0 → 계층 자체를 제거 | `journal/2026-08-23-l2-removed.md` |
| L4 `rank_score` 미배선 | 선언된 0.40/0.40/0.20 이 어떤 종목도 고르지 않았다 | `journal/2026-08-23-l4-rank-score-unwired.md` |
| `docs/04:96` 선언에 코드 없음 | "적용 불가를 통과로 취급하지 않는다" 에 대응물이 `src/` 에 없었다 | `journal/2026-08-24-value-trap-axes-commodity-bias.md` → `journal/2026-08-24-l3-gate-not-applicable-fixed.md` |
| `adv20_usd` 단위 혼합 | 소급 분할조정된 `volume` 을 비조정 종가와 곱해 미래를 봤다 | `docs/14` §8 |
| M 축 미배선 | `split_first_leg` 의 컷이 문서에 없어 L5 산출물에 문구가 나오지 않는다 | `docs/07` §470 · `journal/2026-08-23-l4-rank-score-unwired.md` |

다섯 건 다 **선언은 문서에 있고 배선은 코드에 없었으며, 산출물에 필드가 보여서 배선된 것처럼
읽혔다.** 사용자가 물었다 — **"각 모듈이 자기 업무를 제대로 하는지, 과하게 하고 있지 않은지."**

그래서 계층마다 워크트리를 하나씩 띄워 여섯을 동시에 감사했다. 감사관에게 준 규칙은 셋이었다 —
**코드를 고치지 마라 · 호출 경로를 끝까지 따라가라 · 확인하지 않은 것을 확인한 것처럼 쓰지 마라.**

---

## 2. 계층별 판정

| 계층 | 자기 업무를 하는가 | 결함 | 가장 무거운 것 |
|---|---|---|---|
| **L0 데이터** | **한다. 단, 선언한 PIT 보증은 서지 않는다** | 6 | PIT "최초 보고분" 규칙이 발동 불가 (#1) |
| **L1 스코어보드** | **한다. 단, 선언한 가중치의 절반이 죽어 있다** | 10 | `BLOCK_WEIGHTS` 48칸 중 24칸 미사용 (#7) · `--asof` 미래 참조 (#8) |
| **L3 리서치** | **부분적으로만. 1순위 입력을 손에 쥔 채 축이 닫힌다** | 11 | `unit_demand_series` 소비처 0 (#16) · 검증기가 게이트를 재도출하지 않는다 (#17) |
| **L4 종목** | **한다 — 선정 규칙을 버린 뒤로는 거의 하드 제외뿐이다** | 9 | 지지·ATR·수렴 지표 부재 (#31) · `vcp_base` 가 폭락 중 True (P2) |
| **L5 포트폴리오** | **한다. 단, 계산한 규칙 하나가 운영 경로에서 사라진다** | 7 | Tier2 자본 8% 규칙 (#46) |
| **배선(ops·pipeline)** | **한다 — 끝까지 돈다. 단, 실패를 실패로 보고하지 않는다** | 14 | 관찰 목록 미배선 (#34) · `--send` 없이 텔레그램 전송 (#35) |

계층별 한 문단:

**L0.** 스토어는 있고, 적재는 돌고, 유니버스 필터는 순수 함수로 테스트된다. 문제는 **보증의
공백**이다. `CLAUDE.md` PIT 규약과 `docs/08` §4 가 선언한 "최초 보고분만 쓴다" 는 벤더 벌크에
빈티지가 없어 발동할 수 없고(#1), 유니버스 정의가 세 벌로 갈려(#2) 감사 명령이 L1 과 다른
모집단을 감사한다. 캐시 지문에 코드 버전이 없어(#3) 고쳐도 옛 값을 읽는다. **자기 업무는
하지만, 자기가 보증한다고 적어 둔 것 중 일부는 보증하지 않는다.**

**L1.** 스코어보드는 실제로 나오고, PIT 는 단일 구현이며, S2 구조는 사전 등록된 검정을 거쳐
채택됐다. 문제는 **선언과 산출의 괴리**다. 8클래스 × 6블록 = 48칸의 `BLOCK_WEIGHTS` 중 S2 가
쓰는 것은 C·E·F 24칸뿐이고, `docs/02` §7 이 "가치함정 방어의 1차선" 이라고 적은 A 블록의
클래스별 차등이 통째로 죽었다(#7). `--asof` 는 같은 달 월말 버킷을 돌려줘 최대 4주 미래를
본다(#8). **순위를 내는 일은 하지만, 문서가 선언한 방식으로 내지는 않는다.**

**L3.** 4역할·게이트·스키마·bear 격리는 살아 있고 오늘 고친 §3.5 조항도 코드 안에서는
동작한다. 문제는 **입력과 검증의 두 구멍**이다. 축 1 의 1순위 입력(`unit_demand_series`)을
supply 에게 필수로 강제해 놓고 소비처가 하나도 없으며(#16), 저장된 thesis 를 다시 읽는 쪽은
`cycle_confidence` 도 `gate_result` 도 재도출하지 않아 파일이 자기 자신에 대해 선언한 것을
그대로 믿는다(#17). **오늘 고친 게이트가 파이프라인 밖 파일에는 적용되지 않는다** — 이 사실은
오늘 실제 실행에서 확인됐다(#17 · #53).

**L4.** 2026-08-24 결정으로 선정 규칙을 버렸으므로, L4 가 지금 하는 일은 **하드 제외**와 **관찰
지표 산출**이다. 하드 제외는 실제로 종목을 뺀다. 문제는 그 하드 제외 셋 중 둘이 판정 불가를
통과로 처리하고(#27), 하나는 두 단위 공간에 같은 임계를 써서 표적(적자기업)에 거의 발동하지
않는다는 것(#26)이다. 관찰 지표 쪽은 `docs/06` 이 말하는 "변동성 수축" 을 재는 재료(고가·저가)를
스토어에 두고도 읽지 않는다(#31). **빼는 일은 하지만, 빼겠다고 한 것을 다 빼지는 않는다.**

**L5.** SOCP·사다리·스탑·TP·매매계획서는 전부 나오고, 시간 스탑은 알림·리포트·저널·캘리브레이션
네 곳에 배선돼 있으며, 물타기는 가격 AND 논지 두 조건을 실제로 건다. 문제는 **계산된 규칙이
운영 파일에 도달하지 않는 것**이다. Tier2 자본 8% 규칙은 계산되고, 계획서에 라벨이 어긋난 채
찍히고, `positions.yaml` 에는 도달하지 않으며, `msa check` 는 그 불일치를 **사람의 갱신 누락으로
지목**한다(#46). **비중을 정하는 일은 하지만, 정한 것 중 하나가 집행 경로에서 증발한다.**

**배선.** `msa run daily` 와 `msa run monthly` 는 오늘 실제로 exit 0 으로 끝까지 돈다(§5).
문제는 **보고의 정직성**이다. 계약 위반이 `skipped` 로 위장되고(#36), 깨진 직전 다이제스트가
"첫 실행" 으로 둔갑하고(#37), 선정에서 빠진 테마가 아무 데도 기록되지 않고(#38), `--provider
none` 에서 관찰 목록이 한 줄도 써지지 않는다(#34). **일은 하지만, 안 한 일을 안 했다고 말하지
않는다.**

---

## 3. 결함 목록

심각도 순 → 계층 순. **표가 아니라 항목별로 적는다** — 표에 넣으면 근거가 잘린다.
번호는 감사 원자료의 번호를 유지한다. `P1`~`P4` 는 감사 이전에 이미 직접 확인된 4건이다.

### 심각 (2)

---

#### 16 · [심각] L3 — 축 1 의 1순위 입력이 수집만 되고 아무도 읽지 않는다

**어디** `src/msa/l3/roles.py:196-203` (질문) · `:222-236` (스키마) · `:237` (`required`)

**확인** `grep -rn "unit_demand_series" src/ tests/*.py docs/` → **`roles.py` 5줄이 전부.**
스키마 선언과 Mock 응답뿐이고, `src/` 어디에도 이 필드를 읽는 코드가 없다.
`l3/pipeline.py` 의 thesis 조립(`:320-360`)에도 들어가지 않는다 — **저장조차 되지 않는다.**

**무엇** `SUPPLY_SCHEMA` 는 supply 역할에게 `unit_demand_series`(실물 단위 10년 이상 시계열 ·
출처 · 집계 범위 · 증거 id)를 `required` 로 강제한다. `docs/04` §2 가 축 1 의 **1순위 입력**으로
정의한 바로 그것이다. 모델은 그것을 만들어 오고, 파이프라인은 그것을 버린다.

**실증** `state/theses/2026-08-14/home_improvement.thesis.yaml` — supply 가 NAR 기존주택 판매
10년 시계열을 증거 2~8·25~30 으로 실제 확보했다. 그런데 축 1 은 L1 의 FRED 경로만 보고
`axis1_status: data_missing` → `unit_demand: not_applicable` 로 닫혔다.
**가장 결정적인 축이 데이터를 손에 쥔 채 닫혔다.**

**왜 문제인가** `docs/04` 머리말은 5축 판별기를 "이 저장소의 핵심 IP … 이것이 없으면 전체
파이프라인이 자본 파괴 기계가 된다" 로 규정한다. 그 판별기의 1순위 축이, 입력을 요구하고
받아 놓고, 쓰지 않는다. 게다가 이 공백은 2026-08-24 의 §3.5 배선과 맞물려 **편입 불가**를
만든다 — 데이터가 있는데 없다고 판정해서 막는 것이다. 방향은 보수적이지만 이유는 틀렸다.

**무엇을 해야 하는가** L1 의 FRED 경로와 L3 의 `unit_demand_series` 를 축 1 판정에서 어떻게
화해시킬지는 **새 선언이 필요한 문제다**(§8 열린 질문 2). 그 전에 할 수 있는 것은 두 가지 —
(a) `unit_demand_series` 를 thesis 에 **저장**해 사후 감사가 가능하게 하고,
(b) `axis1_status: data_missing` 인데 supply 가 시계열을 가져온 경우를 게이트 `notes` 에
드러내는 것. 둘 다 새 임계를 만들지 않는다.

---

#### 17 · [심각] L3 — 검증기가 `cycle_confidence` 와 `gate_result` 를 재도출하지 않는다

**어디** `src/msa/l3/schema.py:363-392` (`_check_gate`) · `:448-450` (확신도) ·
`src/msa/pipeline/run.py:401-413` (`gate_eligible`) · `src/msa/ops/ingest.py` ·
`src/msa/pipeline/assemble.py:381-390`

**확인** 코드 읽기 + **오늘 실제 실행**. `_check_gate` 가 하는 일은 넷뿐이다 — `status` 가
enum 안인가 · `contested|rejected` 면 `portfolio_eligible` 이 false 인가 · `contested` 면
`referee_ruling`+refs 가 있는가 · `axis_verdicts` 5축 키가 있는가. **`portfolio_eligible` 이
`axis_verdicts`·`cycle_confidence` 와 정합한지는 검사하지 않는다.** `cycle_confidence` 는
`0 ≤ c ≤ 1` 범위만 본다(`:449`). 합성 변조 3종이 전부 통과한다 — 5축 전부 `not_applicable` +
`portfolio_eligible: true` / `axis_verdicts` 와 `value_trap_axes` 불일치 / 확신도 0.99.

**오늘 실제로 일어난 일** `msa run monthly --no-write --provider none` 을 돌렸더니
`state/theses/2026-08-14/home_improvement.thesis.yaml` 이 그대로 받아들여지고 L4 picks 가 돌았다.
그 파일의 `gate_result` 는 이렇다:

```yaml
gate_result:
  status: passed
  portfolio_eligible: true
  axis_verdicts: {unit_demand: not_applicable, ..., substitution: not_applicable, ...}
```

**이것이 정확히 2026-08-24 §3.5 가 막기로 한 조합이다**(축1·축3 둘 다 적용 불가). 게이트는
고쳐졌는데 **저장된 파일에는 옛 판정이 굳어 있고, 파이프라인은 그 굳은 플래그를 믿는다.**

**왜 문제인가** `journal/2026-08-24-l3-gate-not-applicable-fixed.md` 의 검증표는 "이후: 편입
불가" 라고 적었다. 그것은 **같은 축 판정을 새 `apply_gates()` 에 다시 넣었을 때**의 결과이고,
운영 경로는 그 재계산을 하지 않는다. 저널의 기술은 정확했지만, **그 재계산이 어디서도 자동으로
일어나지 않는다는 사실은 그 항목에 적혀 있지 않다.** 앞으로 게이트를 고칠 때마다 같은 간극이
생긴다.

**무엇을 해야 하는가** 저장된 thesis 의 `axis_verdicts`·L1 입력으로 `cycle_confidence()` 와
`apply_gates()` 를 **다시 돌려 파일의 값과 대조**하는 검사. 불일치면 거부하거나 최소한 경고를
남긴다. **새 규칙을 만드는 것이 아니라 이미 있는 함수를 한 번 더 부르는 것이다** (§7-1).

---

### 높음 (8)

---

#### P1 · [높음] L1 — `dv` 가 소급 분할조정된 `volume` 을 비조정 종가와 곱한다

**어디** `src/msa/l1/panel.py:201` (`sum(closeunadj * volume) as dv`) · `:214` (SPY 도 같다) ·
머리말 `:16` 이 그 정의를 명시한다

**확인** 스토어 직접 조회. NVDA 10:1 분할(2024-06-10) 직전:

| date | close(조정) | closeunadj | volume |
|---|---|---|---|
| 2024-06-06 | 120.793 | **1209.98** | **655,351,000** |
| 2024-06-10 | 121.583 | 121.79 | 308,135,000 |

`volume` 은 소급 분할조정 값(실제 그날 거래량 약 65M 주)이고 `closeunadj` 는 비조정이다.
곱하면 **분할 계수(10배)만큼 틀린다.** `l4/features.py:584` 는 2026-08-23 에 `close*volume` 으로
고쳤고 주석에 "asof 이후의 분할 계수만큼 틀리고, 그것은 미래를 보는 것이다" 라고 적었다.
**같은 오류가 L1 에는 남아 있다.**

**흘러드는 곳** `dv` → `liquidity_decay`(A 블록) · `volume_dryup`(B 블록).
**A·B 는 S2 의 자격 게이트(`pool = mean(A_pct, B_pct) ≥ 0.5`) 그 자체다**
(`l1/scoreboard.py:67-68,221-222`). 오염되는 것은 순위가 아니라 **"누가 후보에 드는가"** 다.

**왜 문제인가** 분할이 잦은 종목이 많은 테마일수록 과거 `dv` 가 부풀고, 그것이 A·B 백분위를
통해 자격 판정을 흔든다. 백테스트 경로에서는 look-ahead 다 (`CLAUDE.md` PIT 규약 표 첫 행 —
"전부 필요. 예외 없음").

**무엇을 해야 하는가** `close * volume` 으로 고친다. **새 값을 정하는 것이 아니라 이미 L4 에서
내려진 같은 판단을 L1 에 적용하는 것이다.** 단, #3(캐시 지문)을 같이 고치지 않으면 고쳐도
옛 캐시를 읽는다 — 오늘 실행 로그가 `panel: 캐시 사용 l1_panel_2fe9806ad09c49a3.parquet` 이다.

---

#### 1 · [높음] L0 — PIT "최초 보고분" 규칙이 발동 불가다

**어디** `src/msa/data/pit.py:6-7` · `src/msa/l1/fundamentals.py:3-5` · `docs/08` §4 ·
`CLAUDE.md` PIT 규약

**확인** 스토어 직접 조회:

```sql
select count(*), count(distinct (ticker, calendardate)) from fundamentals;
-- 655,000 · 655,000  → (ticker, calendardate) 당 datekey 가 전부 유일. multi = 0
```

**무엇** 코드는 `row_number() over (partition by ticker, calendardate order by datekey)` 로
최초 보고분을 고르지만, **고를 것이 하나뿐이다.** Sharadar 벌크 `SF1` 에는 빈티지(정정 이력)가
없다. `datekey` 는 **타이밍만** PIT 이고 금액은 최신 정정치다.

**왜 문제인가** `docs/08` §4 가 선언한 왜곡 방지 — "과거 시점 값을 정정치로 계산하면 백분위
분포가 왜곡되고, 오늘의 순위가 틀어진다"(`CLAUDE.md` PIT 표) — 가 **실현되지 않는다.**
자기이력 백분위(D 블록)와 자본 사이클 시계열(E 블록)이 그 표에서 "PIT 필요" 로 분류된 바로
그것들이다. 코드가 규칙을 적었으므로 읽는 사람은 그것이 걸린다고 믿는다.

**무엇을 해야 하는가** 이것은 **재적재 없이 고칠 수 없다**(§8 열린 질문 1). 지금 할 수 있는
것은 그 사실을 코드 주석과 `docs/08` §4 에 적는 것 — "이 필터는 현재 데이터에서 아무 행도
제거하지 않는다" 를 실측치와 함께.

---

#### 7 · [높음] L1 — `BLOCK_WEIGHTS` 48칸 중 24칸(A·B·D)이 어떤 순위에도 쓰이지 않는다

**어디** `src/msa/themes.py:328-337` (선언) · `src/msa/l1/scoreboard.py:67-69` (`POOL_BLOCKS` /
`TIMING_BLOCKS`) · `:212-224` (`aggregate_scores`)

**확인** 코드 읽기 + 산술. S2 집계는 이렇다:

```python
score_s0, avail = _weighted_score(BP, W)            # 6블록 — 감사용
pool = BP[["A","B"]].mean(axis=1, skipna=True)      # 가중치 없음
eligible = pool >= 0.5
timing, _ = _weighted_score(BP[["C","E","F"]], W[["C","E","F"]])
score = timing.where(eligible)                       # ← 이것이 순위다
```

**A·B 는 가중치 없는 단순 평균으로만 들어가고, D 는 S2 에서 아예 빠진다.**
`BLOCK_WEIGHTS` 의 A·B·D 열을 소비하는 곳은 `score_s0`(감사용)와 S0 구조 검정뿐이다.

**따라 나오는 것 둘.**

1. `docs/02` §7 의 이 선언이 **죽었다**:
   > `secular_*` 의 망각 0.05 — **낙폭에 점수를 주면 사양 산업이 스코어보드 상단을 점령한다.**
   > **이 한 줄이 가치함정 방어의 1차선이다.** 2차선은 `04-value-trap.md` 의 하드 게이트.

   지금 `secular_risk`(A 0.05)와 `commodity_supply`(A 0.15)의 A 취급이 **완전히 동일하다.**
2. C·E·F 재정규화 후 **8클래스가 실제로는 7개**다:

| cycle_class | C·E·F 원값 | 재정규화 |
|---|---|---|
| `commodity_supply` | .20 / .30 / .10 | .333 / .500 / .167 |
| `inventory` | .25 / .15 / .25 | .385 / .231 / .385 |
| `credit_rate` | .25 / .05 / .15 | .556 / .111 / .333 |
| `capex_program` | .25 / .15 / .35 | .333 / .200 / .467 |
| `policy_program` | .30 / .10 / .15 | .545 / .182 / .273 |
| **`discretionary_demand`** | .25 / .05 / .20 | **.500 / .100 / .400** |
| **`secular_growth`** | .25 / .05 / .20 | **.500 / .100 / .400** |
| `secular_risk` | .25 / .20 / .20 | .385 / .308 / .308 |

**왜 문제인가** 가치함정 방어의 1차선과 2차선이 **양쪽 끝에서 각각 배선 문제를 갖고 있다** —
1차선(A 블록 차등)은 여기서 죽었고, 2차선(`docs/04` 게이트)은 어제 고쳤으나 저장된 파일에
적용되지 않는다(#17). 그리고 `CLAUDE.md` §1 이 "선언하고 근거를 적는다" 고 한 값의 절반이
선언만 되어 있다.

**무엇을 해야 하는가** **여기서 가중치를 옮기지 않는다.** 할 수 있는 것은 사실을 적는 것 —
`docs/02` §7 표에 "S2 에서 A·B 는 가중치 없이, D 는 미사용" 을 표시하고, `themes.py` 의
`BLOCK_WEIGHTS` docstring 에 소비처를 명시하는 것. 이 구조를 바꾸려면 `docs/12` §4 꼴의
**새 사전 등록**이 필요하다.

---

#### 8 · [높음] L1 — `--asof` 가 같은 달 월말 버킷을 돌려준다 (최대 4주 미래 참조)

**어디** `src/msa/l1/blocks.py:199-213` (`bucket_for`) · `src/msa/cli.py:288-290` (도움말)

**확인** 코드 읽기. `bucket_for` 는 `month_end_label(date)` 를 만들고 그것이 인덱스에 있으면
**그대로 돌려준다.** 인덱스는 1998~store_end 의 월말 라벨 전부이므로 과거 asof 는 항상 걸린다.
CLI 도움말은 정반대를 약속한다:

```
--asof  기준일 YYYY-MM-DD (그 이전 마지막 월말). 기본 = 스토어 최종일
```

`asof 2020-07-03` → 버킷 `2020-07-31`. **4주 뒤의 데이터로 만든 지표를 쓴다.**

**왜 문제인가** docstring 은 "오늘의 스캔(8/14)은 8월 부분 버킷(라벨 8/31, 데이터 8/14 까지)을
쓴다" 며 이 동작을 의도로 설명한다. 그 서술은 **store_end 가 asof 인 오늘의 스캔에서만** 참이다.
과거 asof 로 재현·검증을 돌리면 그 버킷은 부분이 아니라 완성본이고, 그때는 미래다. 게다가
스냅샷 디렉터리는 `min(asof, store_end)` 로 이름 붙으므로 **잘못 라벨된 스냅샷이 L3·L4 로
그대로 흘러간다.**

**무엇을 해야 하는가** 두 경로를 구분한다 — 오늘의 스캔(asof ≥ store_end)은 현행 유지,
과거 asof 는 도움말대로 **이전 월말**을 쓰거나, 최소한 "이 버킷은 asof 이후 데이터를 포함한다"
를 `meta.json` 과 리포트에 적는다. 새 값을 정할 필요가 없다.

---

#### 31 · [높음] L4 — 지지·ATR·수렴을 직접 보는 지표가 하나도 없다

**어디** `src/msa/l4/features.py:744-750` (읽는 열) · `src/msa/data/store.py:289`
(`PRICE_COLUMNS` 에 `open, high, low` 가 있다)

**확인** `grep -rniE "\batr\b|true_range|wedge|support_level|지지" src/msa/` → **0 건.**
L4 가 스토어에서 읽는 가격 열은 `["ticker","date","close","closeunadj","volume","mcap"]` 넷뿐.
`high`·`low` 는 스토어에 있는데 요청하지 않는다.

**무엇** `docs/06` 의 M 축이 말하는 "변동성 수축" 은 지금 **종가 피벗 낙폭의 단조 감소**
하나로만 근사된다(`vcp_base`). true range 도, 평균 실체 범위도, 쐐기·수렴 각도도, 지지 레벨
이탈도, 거래량 수축률(임계 있는)도 없다.

**왜 문제인가** 재료가 이미 스토어에 있는데 쓰지 않는다는 것이 핵심이다. 이것은 "데이터가
없어서 못 한다" 가 아니라 "안 읽는다" 다. 그리고 그 사실이 `docs/06` 이나 `features.py`
머리말에 적혀 있지 않아, 읽는 사람은 M 축이 문서가 서술한 만큼을 재고 있다고 믿는다.

**무엇을 해야 하는가** **지표를 새로 만드는 것은 새 선언이다** — 임계도 창 길이도 문서에 없다.
지금 할 수 있는 것은 `docs/06` 과 `features.py` 머리말에 "M 축이 실제로 보는 것" 을 열거하고
못 보는 것을 명시하는 것이다. 지표를 추가하려면 `docs/12`·`docs/14` 꼴의 사전 등록이 필요하다.

---

#### 34 · [높음] 배선 — `--provider none` 에서 관찰 목록이 한 줄도 써지지 않는다

**어디** `src/msa/pipeline/run.py:735` (`ingest skipped`) · `:730-733` (`human_todo`) ·
`:895-904` (`_ingest_step` — `result.research` 가 있을 때만) ·
`src/msa/ops/ingest.py:586` (`save_watchlist` 호출처 **1곳뿐**)

**확인** **오늘 실제 실행.** `msa run monthly --no-write --provider none`:

```
  research   ok   provider none — L3 를 부르지 않았다. 논지 찾음 1/8 · thesis 없음 → 관찰 7
  ingest     skipped   provider none — 새 L3 라운드가 없다
사람이 할 것:
  - health_it: thesis 없음 → 관찰. 사람 논지(...) 를 쓰거나 `msa research health_it`
  ... (7건)
```

**7개 테마가 "관찰" 로 분류됐고, `state/watchlist.yaml` 은 만들어지지 않는다.**
`save_watchlist` 를 부르는 코드는 `ops/ingest.py` 한 곳뿐이고, 그 경로는 이번 실행에서 통째로
건너뛰어졌다.

**왜 문제인가** 기본값이 `--provider none` 이다(`ANTHROPIC_API_KEY` 부재). 즉 **현재 표준
실행에서 관찰 목록은 절대 갱신되지 않는다.** `human_todo` 는 화면에만 남고 다음 달이면 사라진다.
`docs/09` §5 가 관찰 목록을 상태 파일로 규정한 이유 — 표류를 추적하기 위해서 — 가 무력화된다.
오늘 `home_improvement` 이 §3.5 로 편입 불가가 되어도(#17 이 막고 있어 실제로는 되지도 않았다)
관찰 목록에는 아무것도 남지 않는다.

**무엇을 해야 하는가** `--provider none` 경로에서도 관찰 항목(thesis 없음 · 게이트 편입 불가)을
`watchlist.yaml` 에 upsert 한다. **이미 있는 `save_watchlist`/`WatchItem` 을 부르는 것이고
새 값을 정하지 않는다** (§7-5).

---

#### 35 · [높음] 배선 — `msa run daily` 가 `--send` 없이도 텔레그램을 보낸다

**어디** `src/msa/pipeline/run.py:1082-1085` (`run_cadence_check`) ·
`src/msa/pipeline/daily.py:645` (호출) · `:704-712` (`--send` 는 다이제스트만 감싼다) ·
`src/msa/cli.py:825,868` (`msa check` 에는 `--no-send` 가 있다)

**확인** 코드 읽기:

```python
# run.py:1082
if rep.out_dir is not None:                       # = write=True 면 항상
    dres = deliver(rep.alerts, rep.out_dir, use_env=True)   # ← --send 와 무관
```

`--send` 는 `daily.py:705` 의 다이제스트 알림만 막는다. 보유 점검 알림(무효화 발동 · 사다리
n단 · 시간 스탑 · TP · Tier2)은 `run_cadence_check` 가 **항상** `deliver` 한다.

**왜 문제인가** `--send` 는 "보낼지 말지" 를 사람이 정하는 스위치로 읽힌다. `msa check` 는
`--no-send` 라는 정반대 기본값(보낸다)을 갖고 그 사실을 이름으로 드러내는데, `msa run daily` 는
기본값이 "안 보낸다" 인 척하면서 절반을 보낸다. **현재 `MSA_TELEGRAM_*` 미설정이라 잠재**이고,
설정하는 순간 발현된다.

**무엇을 해야 하는가** `run_cadence_check` 에 `send` 인자를 뚫어 `run daily`/`run weekly` 의
스위치와 묶거나, `run daily` 에 `--no-send` 를 붙여 `msa check` 와 같은 규약으로 만든다.
어느 쪽이든 **동작 규약을 하나로 만드는 것이지 새 규약이 아니다.**

---

#### 46 · [높음] L5 — Tier2 자본 8% 규칙이 계산되고, 라벨이 틀리고, 운영 경로에서 사라진다

**어디** `src/msa/l5/ladders.py:186-198` (계산) · `src/msa/l5/plan.py:87-94` (라벨) ·
`src/msa/l5/run.py:422,439-440` (`weights.csv`) · `src/msa/l5/positions.py:161-163` (운영 파일) ·
`src/msa/ops/check.py:390-396` (대조)

**확인** 코드 읽기. 세 단계에서 각각 다른 일이 일어난다.

**(a) 계산은 맞다.** `ladders.py:190-198` 이 `cap_px = avg × (1 − 0.08/w)` 를 만들고
`t2_px = avg × 0.65` 와 비교해 **더 가까운(높은) 쪽**을 `tier2_effective_price` 로 삼는다.
`tier2_rule` 에 `"capital 8%"` 를 적는다. 여기까지는 `docs/07` §4 대로다.

**(b) 라벨이 어긋난다.** `plan.py:87-94`:

```python
f"{_px(p.tier2_effective_price)} (평단 −35% = 초기가 −{abs(p.tier2_vs_initial)*100:.1f}%"
+ (f"; 자본 8% 규칙 {_px(p.tier2_capital_rule_price)} 이 더 가까움" if p.tier2_rule == "capital 8%" else "")
```

자본 규칙이 구속하면 **앞의 가격은 자본 규칙가**인데 바로 뒤 괄호는 **평단 −35% 에서 나온
하락률**을 붙인다. 가격과 퍼센트가 서로 다른 규칙을 가리킨다. (정상 참작 — 자본 규칙가가
꼬리에 한 번 더 찍히므로 **정보 자체가 숨지는 것은 아니다.** 어긋난 것은 라벨이다.
`weights.csv` 는 `tier2_effective_price` 와 `tier2_vs_initial` 을 나란히 쓰면서 이 꼬리가 없다.)

**(c) 운영 파일에 도달하지 않는다.** `positions.py:161-163` 은 **항상** `entry × 0.65` 를 쓰고
`tier2_basis: "avg_minus_35"` 를 박는다. 근거는 코드 주석에 있다 — "1단만 체결된 시점의 평단 =
진입가". 그 논리는 일관되지만, **자본 8% 규칙은 `positions.yaml` 에도 `msa check` 에도 도달하지
않는다.** 그리고 `check.py:391-395` 는 `stop` 이 `avg × 0.65` 와 1% 이상 다르면
**"positions.yaml 갱신 누락인지 확인" 이라며 사람을 오류로 지목한다.**

**왜 문제인가** `docs/07` §4 가 두 규칙 중 먼저 오는 쪽을 쓰라고 한 이유는 큰 비중 포지션에서
평단 −35% 가 총자본 8% 를 넘기 때문이다. 그 보호가 계획서에서는 계산되고, 운영 파일에서는
사라지고, 점검기는 그 사라짐을 **사람의 실수로 해석한다.** 세 모듈이 같은 규칙에 대해 서로 다른
것을 믿는다.

**무엇을 해야 하는가** 어느 규칙이 운영 파일의 정본인지를 한 곳에서 정한다. **값은 이미 문서에
있다**(−35% · 자본 8%). 정할 것은 "1단만 체결된 상태에서 자본 규칙을 걸 것인가" 이고, 이는
`docs/07` §4 를 다시 읽어 결정할 문제이지 새 임계가 아니다. 라벨 어긋남(b)은 즉시 고칠 수 있다.

---

### 중간 (37)

---

#### P2 · [중간] L4 — `vcp_base` 가 폭락 중에도 True 를 낸다

**어디** `src/msa/l4/features.py:622-636` · `src/msa/vendor/vcp.py:59-81`
(`build_contractions`) · 호출 `features.py:613` (`n >= 60`)

**확인** 합성 시드 5개 — 수축 베이스(20%→12%→6%) 뒤 40봉 −40% 붕괴 → **5/5 True.**

**원인 셋.**
1. `build_contractions(piv, ref_level=float(c.max()), tol=0.10, max_drop_from_ref=1.0)` —
   고점 −10% 아래의 피벗 쌍은 `continue` 로 버려진다(`vcp.py:68-69`). 폭락 구간의 수축은
   애초에 목록에 들어오지 않으므로, **남은 것은 붕괴 전의 옛 수축들**이고 그것들은 여전히
   단조 감소한다. `max_drop_from_ref=1.0` 이라 `TOO_DEEP` 경고도 절대 붙지 않는다.
2. **현재가가 그 베이스의 어디에 있는지를 확인하는 조건이 없다.** `from_52w_high` 열은
   같은 함수가 이미 계산해 두었는데(`features.py:601`) `vcp_base` 는 읽지 않는다(#32).
3. `dry = v10 < v50` — 임계 없는 순부등호. 1% 차이도 통과한다.

**왜 문제인가** M 축 6구성요소 중 하나이고, `docs/06` 이 "베이스" 라 부르는 것의 조작적
정의다. 폭락을 베이스로 읽으면 **M 축이 정확히 반대 방향을 가리킨다.**
(M̃ 단독 IC 는 `docs/backtest-l4.md` Q2 에서 +0.0327 [+0.0096, +0.0539] 로 나왔다 — 그 값은
이 결함을 **포함한 채** 측정된 것이다.)

**무엇을 해야 하는가** `from_52w_high` 조건을 붙이면 이 경로는 막힌다 — **열은 이미 계산돼
있다.** 다만 **임계값(−25%? −30%?)은 문서에 없다 → 별도 사전 등록이 필요하다** (§7-4).
임계 없이 할 수 있는 것: 창 길이 불일치(#30)와 dry-up 임계를 문서에 맞추는 것.

---

#### P3 · [중간] L3 — `commodity_chem.thesis.yaml` 은 파이프라인 산출물이 아니다

**어디** `state/theses/2026-08-23/commodity_chem.thesis.yaml` ·
비교 대상 `src/msa/l3/pipeline.py:335-360`

**확인** 키 대조:

| 파이프라인이 쓰는 키 | 이 파일 |
|---|---|
| `cycle_confidence_terms` | **`confidence_terms`** (이름이 다르다) |
| `cycle_confidence_by` | **`cycle_confidence_source: referee`** (다른 필드) |
| `bear_rebuttal` · `consensus_since` · `inputs` | **전부 없음** |
| evidence id 1 부터 | **0 부터** |

같은 디렉터리의 `home_improvement.thesis.yaml` 은 `cycle_confidence_terms` 를 갖는다 —
**그쪽은 진짜 파이프라인 산출물이다.** 대비가 선명하다.

**무엇** 손으로 쓴 논지가 L3 산출 디렉터리에 들어 있다. 확신도 0.70 은 코드로 재계산하면
**0.60**(축4 `strong_cycle` 항이 성립하지 않는다)이고, L1 축1 상태를 반영하면 **0.45 → 편입
불가**다.

**왜 문제인가** #17(검증기가 재도출하지 않는다)과 #P4(`_declared_source`)와 맞물려,
**손으로 쓴 확신도가 `referee` 로 라벨된 채 캘리브레이션 장부에 들어간다.**
`docs/10` §4 의 캘리브레이션은 "referee 의 확신도가 실제로 맞았는가" 를 재는 물건이다.

**무엇을 해야 하는가** 이 파일 자체는 **고치지 않는다** — 그 시점의 기록이다
(`journal/2026-08-24-l3-gate-not-applicable-fixed.md` 가 같은 판단을 내렸다). 고칠 것은
**경로**다: 사람 논지는 `--human-theses <dir>` 로만 들어오게 하고, `state/theses/<date>/` 에
있는 파일은 파이프라인 키 집합을 만족하는지 검사한다.

---

#### P4 · [중간] 배선 — 기계가 쓴 출처는 무시되고 손기재 자기선언이 채택된다

**어디** `src/msa/pipeline/assemble.py:332-339` (`_declared_source`) · `:357-363` (적용) ·
`src/msa/l3/pipeline.py:352` (파이프라인이 쓰는 키)

**확인** 코드 읽기:

```python
def _declared_source(thesis):
    for k in ("confidence_provenance", "cycle_confidence_source"):   # ← 둘뿐
        ...
declared = _declared_source(thesis)
if declared is not None:
    confidence_source = declared        # 위치로 아는 값을 이긴다
```

파이프라인이 실제로 쓰는 키는 **`cycle_confidence_by`**(`"referee-pipeline (04 §4 기계 적용…)"`)
이고 목록에 없다. `assemble.py:376-377` 은 그것을 **통과시키기만** 한다.

**왜 문제인가** 자기선언이 위치 정보를 이긴다는 설계 자체는 docstring 에 근거가 적혀 있다
("파일이 어디 있든 누가 `c` 를 만들었는지는 파일이 더 잘 안다"). 문제는 **기계가 남긴 진짜
출처 표기가 그 판단에 참여하지 않는다**는 것이다. 결과적으로 사람이 손으로 적은 `referee` 만
채택된다(#P3 이 정확히 그 경우다).

**무엇을 해야 하는가** `cycle_confidence_by` 를 판단에 넣거나, 최소한 `_declared_source` 가
고른 값과 `cycle_confidence_by` 가 어긋날 때 경고를 남긴다.

---

#### 2 · [중간] L0 — 유니버스 정의가 세 벌이다

**어디** `src/msa/themes.py:66` (`MEMBER_CATEGORIES`) · `src/msa/cli.py:235,243` ·
`scripts/audit_themes.py:37` · `src/msa/themes.py:3-5` (머리말의 주장)

**확인** 세 곳을 나란히 읽었다:

| 경로 | 정의 | 캐나다 | 2종주 |
|---|---|---|---|
| `themes.MEMBER_CATEGORIES` (**L1 이 실제 사용**) | `COMMON_STOCK + CANADIAN` | 포함 | 포함 |
| `msa audit universe` | `common_stock(meta)` → `drop_secondary_class` | **제외** | **제외** |
| `scripts/audit_themes.py` | SQL `category like '%Common Stock%' and not like '%Preferred%'` | 포함 | 포함 |

**`themes.py:3-5` 머리말은 정반대를 주장한다** — "규칙을 여기 한 곳에 두고 둘 다 이 모듈을
쓴다. 감사 스크립트와 스캐너가 다른 규칙으로 구성원을 세면 감사가 통과한 유니버스와 스캔이
도는 유니버스가 달라진다." `audit_themes.py` 는 이 모듈을 쓰지 않고 SQL 을 다시 짰다.

**왜 문제인가** 머리말이 경고한 그 일이 일어나고 있다. `msa data audit` 은 캐나다·2종주를 뺀
모집단을 감사하고, L1 은 그것들을 포함한 모집단으로 스캔한다.

**무엇을 해야 하는가** `audit_themes.py` 가 `themes.assign_members` 를 쓰게 하거나, 셋의
차이를 머리말에 실측치와 함께 명시한다.

---

#### 3 · [중간] L0 — 캐시 지문에 코드 버전이 없다

**어디** `src/msa/l1/panel.py:219-225` (`_fingerprint`) · `src/msa/l4/features.py:688`
(RS 캐시 키)

**확인** 코드 읽기:

```python
h.update(hash(members[["ticker","theme"]]))
h.update(str(store_end))
h.update(f"{MIN_PRICE_USD}|{RET_CAP_HI}|{RET_CAP_LO}|{SMA_WINDOW}|{NH_WINDOW}")
```

**구성원 + store_end + 위생 상수 5개.** SQL 본문도, 지표 정의도, 코드 버전도 들어가지 않는다.
L4 의 RS 캐시 키는 `rs_universe_<asof>_<store_end>.parquet` — 특성 정의 버전이 없다.

**왜 문제인가** `dv`(#P1)를 고쳐도 옛 캐시를 읽는다. 오늘 실행 로그가 그 증거다 —
`panel: 캐시 사용 l1_panel_2fe9806ad09c49a3.parquet`. `--force` 를 기억해서 붙이는 사람에게만
수정이 반영되고, 잊으면 **고쳤다고 믿으면서 옛 값을 본다.** 이것은 `CLAUDE.md` §2("조용한 절단
금지")가 막으려는 것과 같은 종류의 침묵이다.

**무엇을 해야 하는가** 지문에 SQL 본문 해시(또는 모듈 소스 해시)를 넣는다. 값을 정하는 일이
아니다.

---

#### 4 · [중간] L0 — 시총 결측을 0 으로 덮고 몇 개를 덮었는지 세지 않는다

**어디** `src/msa/l1/scan.py:114` · 관문 `:220-222`

**확인** 코드 읽기:

```python
uni["mcap"] = uni["ticker"].str.upper().map(mcap_of).fillna(0.0).where(uni["live"], 0.0)
```

시총 결측 종목이 **0** 이 된다. 분자(미분류 시총)와 분모(전체 시총) 양쪽에서 사라진다.

**원자료와 달랐던 점 — 규모를 다시 쟀다.** 원자료는 "생존 보통주 5,866 중 338 종(5.8%)" 이라
적었다. **오늘 스토어로 같은 경로를 그대로 재현하면 다른 수가 나온다:**

```
membership_from_store(store, load_themes())   # min_rows=10,000 — scan 과 같은 프롤로그
생존 비Shell 보통주 5,276 · 시총 결측 63 (1.2%)
unclassified_mcap_share → {'share': 1.11e-06, 'unclassified_musd': 112.2}
```

원자료의 수가 어떤 `min_rows` 나 필터에서 나왔는지는 확인하지 못했다. **여기서는 재현된 수를
쓴다** — 결측 63 종(1.2%)이고, **관문 값은 임계 5% 에서 매우 멀다(1.1e-06).**

**왜 문제인가** 이것이 흘러드는 곳은 **저장소에서 유일하게 강제되는 관문**이다 —
`unclassified_mcap_share < 0.05` 면 `StoreError`(`scan.py:220`). 결측을 0 으로 덮으면
미분류 쪽이 과소평가돼 **관문이 통과 쪽으로만 틀린다.** 지금은 관문 값이 임계에서 워낙 멀어
**실무적으로 구속하지 않는다** — 그래서 높음이 아니라 중간이다. 그러나 `docs/08` §7 은
"매번 리포트" 를 요구하는데 **몇 종목이 덮였는지 세지 않으므로**, 나중에 이 값이 임계에
가까워졌을 때 그 원인을 알 방법이 없다.

**무엇을 해야 하는가** 덮은 종목 수와 그 비율을 세어 `coverage.json` 과 리포트에 적는다.
임계(5%)는 건드리지 않는다.

---

#### 5 · [중간] L0 — `msa data status` 가 벌크 원본과 대조하지 않는다

**어디** `src/msa/status.py` · `docs/08` §6.3 의 `[x]`

**확인** 매니페스트와 DB 를 직접 대조했다:

| 테이블 | `us_micro.duckdb.manifest.json` | 실제 DB | 차 |
|---|---|---|---|
| `prices` | 45,656,702 | **45,663,901** | **+7,199** |
| `fundamentals` | 655,000 | 655,000 | 0 |

**7,199 행 차이가 지금까지 한 번도 관측되지 않았다.**

**왜 문제인가** `docs/08` §6.3 은 "적재 후 원본 행수와 대조" 를 체크(`[x]`)로 적었으나
대조하는 코드가 없다. `[x]` 에 근거가 없다. 차이의 원인(재적재 중복? 추가 적재?)은 이 감사에서
확인하지 않았다.

**무엇을 해야 하는가** `msa data status` 가 매니페스트를 읽어 대조하고 차이를 보고한다.
새 임계 없이 "차가 있으면 적는다" 로 충분하다.

---

#### 9 · [중간] L1 — lag 간격 검증용 열을 만들고 읽지 않는다

**어디** `src/msa/l1/fundamentals.py:142,146` (`cd_prev4`·`cd_prev12` 생성) ·
`:160-161` (grid 로 운반) · `_AGG_SQL:183-229` (읽지 않음)

**확인** `_AGG_SQL` 전문을 읽었다 — `cd_prev4`·`cd_prev12` 를 참조하는 절이 **하나도 없다.**

**무엇** `lag(revenue_ttm, 4)` 는 "4행 전" 이지 "4분기 전" 이 아니다. 분기를 거른 기업에서는
그 둘이 다르다. 두 열은 정확히 그 간격을 검증하려고 만들어졌는데, 검증하는 절이 없다.

**왜 문제인가** `rev_yoy`(F) · `asset_growth`(E) · `share_change`(E) 가 기업마다 **다른 길이의
구간**을 재고, 같은 횡단면에서 백분위가 매겨진다.

**무엇을 해야 하는가** `_AGG_SQL` 의 각 `..._ss` 합계에 `datediff('month', cd_prev4,
calendardate) between 11 and 13` 류의 조건을 붙이거나, 최소한 어긋난 행 수를 세어 리포트에 적는다.
전자는 값(허용 폭)을 정해야 하고, 후자는 정하지 않아도 된다.

---

#### 10 · [중간] L1 — FRED·CPI 의 발표 지연·개정을 처리하지 않는다

**어디** `src/msa/l1/physical.py` (`grep "lag|shift|지연"` → **0 건**) ·
`src/msa/data/fred.py:157,186-197` (지연 **측정** 도구는 있다)

**확인** `msa data fred-lag` 는 ALFRED 빈티지로 발표 지연을 **잰다.** 그런데 `l1/physical.py` 는
시리즈를 관측 기준일 그대로 월말 버킷에 붙인다 — 지연만큼 밀지 않는다.

**무엇** M 월 CPI 를 M 월말에 쓴다. 실제 발표는 M+1 중순이다. 흘러드는 곳:
`dd_real`(실질화) · `unit_cagr_5y`(F 블록 점수) · `verdict_post_ss`(L3 게이트 입력).

**왜 문제인가** 백테스트 경로에서 look-ahead 다. **현재는 `FRED_API_KEY` 부재로 잠재** —
오늘 실행 로그가 `physical: 선언 45 · 데이터 있음 7 · 없음 38 · CPI missing` 이다.
키가 들어오는 순간 발현된다.

**무엇을 해야 하는가** `fred-lag` 가 이미 재는 지연을 적용해 시리즈를 밀거나, 지연을 적용하지
않는다는 사실을 `physical.py` 머리말에 명시한다. 지연 값은 측정에서 오므로 **새로 정하는 값이
아니다.**

---

#### 11 · [중간] L1 — `breadth_lead` 가 얼어붙고, 자기 백테스트가 0 이라고 말한 지표를 "핵심 산출물" 이라 부른다

**어디** `src/msa/l1/blocks.py:15-17` (정의) · `docs/02` §C:67 (선언) ·
`docs/backtest-l1.md` §5:175 (실측)

**확인 (a) — 얼어붙는다.** 정의가 "지수가 SMA200 **위로 돌아선 시점**(없으면 오늘) 기준" 이다.
지수가 상단에 머무는 동안 새 전환이 없으므로 기준점이 고정되고, `breadth_lead` 는 **마지막
전환 시점의 과거 사실**을 계속 되풀이한다. `docs/02` §C 는 이 값을 "현재 상태" 로 읽으라 한다.
(L1 감사관의 합성 실행에서 7개월 내내 `lead=5`.)

**확인 (b) — IC.** `state/backtests/l1/2026-08-14/ic_indicator.csv`, primary 창:

| 호라이즌 | `breadth_lead` mean [95% CI] |
|---|---|
| 3M | +0.0115 [−0.0184, +0.0312] |
| 6M | +0.0185 [−0.0149, +0.0407] |
| 12M | +0.0058 [−0.0250, +0.0287] |

**세 호라이즌 전부 CI 가 0 을 포함한다.** 그런데 `docs/02` §C:67 은 이렇게 적는다 —
"`breadth_lead` 가 **이 블록의 핵심 산출물이다.** 값이 3~6개월이면 … 정확히 우리가 원하는 상태."
그리고 C 블록 9지표 동일가중이므로 이 지표가 C 점수의 **1/9** 를 차지한다.

**원자료와 달랐던 점** 원자료는 "C 9개 중 4개가 IC 0" 이라고 적었다. **틀렸다.** primary 창
전 호라이즌에서 CI 가 0 을 포함하는 것은 `breadth_lead` **하나뿐**이다. `breadth_nh6m` 은
12M 에서만(+0.0193 [−0.0075, +0.0499]), `ew_vs_cw` 는 3M 에서만(+0.0323 [−0.0017, +0.0535])
0 을 포함하고, 나머지 6개(`mom_13612w`·`above_200`·`rs_slope`·`rs_trough_bounce`·`breadth_200`·
`breadth_nhnl`)는 세 호라이즌 모두 하한이 0 초과다.

**왜 문제인가** `CLAUDE.md` §1 은 "검정이 '이 블록은 일하지 않는다' 고 말하면 **그 사실을
기록**하고 가중치는 그대로 둔다" 고 한다. 가중치를 그대로 둔 것은 맞다. **기록이 빠졌다** —
`docs/backtest-l1.md` §5 는 정직하게 적었는데 `docs/02` §C 의 "핵심 산출물" 문장은 그대로다.
두 문서가 같은 지표에 대해 반대로 말한다.

**무엇을 해야 하는가** `docs/02` §C 에 §5 의 실측을 각주로 붙인다. **가중치는 그대로 둔다.**

---

#### 12 · [중간] L1 — 관문 6개를 선언하고 1개만 강제한다

**어디** `docs/01` §5 (6개 선언 · "하나라도 실패하면 스캔이 진행되지 않는다") ·
`src/msa/l1/scan.py:220-222` (유일한 `raise`)

**확인** `scan.py` 에서 `raise` 하는 관문은 둘 — 구성원 0개(`:217`)와 미분류 시총 ≥ 5%(`:220`).
나머지는:

| 관문 | 실제 |
|---|---|
| 미분류 시총 < 5% | **강제됨** (`StoreError`) |
| 중복 소속 0개 | 검사기는 있으나 호출되지 않는다 (#6) |
| 구성원 < `min_constituents` | 플래그로만 (`scoreboard.py:313`) |
| ETF 프록시 상관 > 0.85 | 계산은 하되 관문이 아니다 |
| 폐지 티커 포함 | `msa data audit` 에만 (스캔과 분리) |
| 버킷별 시총 추이 급변 | **없다** |

**왜 문제인가** 문서의 굵은 글씨("하나라도 실패하면 스캔이 진행되지 않는다")가 1/6 에만
해당한다.

**무엇을 해야 하는가** `docs/01` §5 표에 각 행의 실제 강제 여부를 열로 추가하거나, 관문을
스캔 경로에 붙인다. 후자는 임계가 이미 문서에 있으므로 새 값을 정하지 않는다.

---

#### 13 · [중간] L1 — F 블록 지표 구성이 테마마다 다른데 같은 횡단면에서 순위를 매긴다

**어디** `src/msa/l1/scoreboard.py:134` (`SCORED["F"] = ("rev_yoy_d2","ebitda_margin_d4",
"unit_cagr_5y")`) · `src/msa/l1/physical.py`

**확인** 오늘 실행 로그 + 산출물:

```
physical: 선언 45 · 데이터 있음 7 · 없음 38 · CPI missing
```
```
state/scans/2026-08-14/indicators.csv:
  unit_cagr_5y notna: 7 / 134
  rev_yoy_d2   notna: 134
  ebitda_margin_d4 notna: 134
```

**7개 테마는 3지표 평균, 127개는 2지표 평균이고, 그 둘이 같은 횡단면에서 백분위를 겨룬다.**

**왜 문제인가** 블록 점수는 `mat.mean(axis=1, skipna=True)`(`scoreboard.py:288`)라 결측을
그냥 뺀다. 지표 수가 다르면 분산이 다르고, 백분위는 분산에 민감하다. 어느 방향으로 얼마나
치우치는지는 이 감사에서 **재지 않았다.**

**무엇을 해야 하는가** `F_n_ind` 열이 이미 스코어보드에 있다 — 리포트가 그 차이를 드러내게
한다. 보정(예: 3지표 테마만 따로 순위)은 **새 구조라 사전 등록이 필요하다.**

---

#### 14 · [중간·경계] L1 — L1 이 `docs/04` 축1 판정을 대신 내린다 (과잉)

**어디** `src/msa/l1/blocks.py:385-396` (`axis1_verdict`) · `:398-408` (`_verdicts` 벡터판) ·
`docs/04` §2 판정표 · `blocks.py:32-33` (스스로 적은 각주)

**확인** 코드 읽기. `axis1_verdict(cagr10, cagr5)` 가 `cycle|warning|death|n/a` 를 만들고,
L3 는 그 **문자열을 그대로 받는다.** 게다가:

```python
np.select([isnan, c10 >= 0, c10 >= -0.02, c5 < c10],
          ["n/a", "cycle", "warning", "death"], default="warning")
```

`default="warning"` 이 채우는 칸 — `cagr10 < −2%` 이고 `cagr5 ≥ cagr10`(감소가 **감속**) —
은 **`docs/04` 판정표에 없는 칸**이다. `blocks.py:32-33` 이 그 사실을 스스로 적는다:
"표의 어느 칸에도 없다 → `warning`. 사이클도 사망도 단정하지 않는 쪽이 보수적."

**왜 문제인가** 판단 자체는 보수적이고 근거도 적혀 있다. 문제는 **경계**다 — 게이트 결정표가
두 문서(`docs/02` 와 `docs/04`)에 나뉘고, **빈칸은 한쪽에서만 메워졌다.** `docs/04` 를 읽는
사람은 그 칸이 존재하는 줄 모른다. L1 은 "이 테마의 물량 CAGR 은 얼마인가" 를 답하면 되고,
"그 값이 사이클인가 사망인가" 는 `docs/04` 의 질문이다.

**무엇을 해야 하는가** 빈칸을 `docs/04` §2 판정표에 **명시적으로 추가**하고(그 칸의 값은
이미 코드에 있으므로 새 값이 아니다), 판정 함수의 소재를 정한다. 어느 쪽이든 표는 한 곳에.

---

#### 18 · [중간] L3 — 축 2·4·5 가 적용 불가일 때 완전 무음이다

**어디** `src/msa/l3/gates.py:100-130` (`cycle_confidence`)

**확인** 코드 읽기. `not_applicable` 에 `notes` 를 남기는 축은 **둘뿐**이다:

| 축 | `not_applicable` 처리 |
|---|---|
| 축1 unit_demand | 항 없음 + **note** (`:106-110`) |
| 축3 substitution | 항 없음 + **note** (`:117-123`) |
| 축4 cost_curve | 항 없음 · **note 없음** (`:125`) |
| 축5 terminal_risk | 항 없음 · **note 없음** (`:127`) |
| 축2 capital_cycle | 애초에 verdict 가 아니라 L1 수치(`capex_to_da_qtrs_below1`)로 붙는다 |

**실증** `home_improvement` 은 5축 중 **3축**이 `not_applicable` 인데(`unit_demand`,
`substitution`, `cost_curve`) 표시는 **2축**뿐이다 — 축4 는 note 도 `key_uncertainty` 도 없다.

**왜 문제인가** `CLAUDE.md` §2 의 정신은 "적게 받으면 반드시 남긴다" 다. 축4 는 남기지 않는다.
그리고 `docs/04` §2 각주가 요구한 "그 사실을 리포트에 표시한다" 가 축1·축3 에만 적용됐다.

**무엇을 해야 하는가** 축4·축5 의 `not_applicable` 에도 note 를 남긴다. **산술은 건드리지
않는다** — `docs/04` §4 에 항이 없다.

---

#### 19 · [중간] L3 — 축1 이 NA 이고 축3 이 경고면 축2 혼자 편입을 만들 수 있다

**어디** `src/msa/l3/gates.py:31` (`CONF_BASE = 0.5`) · `:47-54` (`CONF_TERMS`) ·
`:198` (§3.5 는 축1·축3 **둘 다** NA 일 때만 닫는다) · `:313` (`>=`)

**확인** 산술:

```
0.50 (base) − 0.15 (axis3_warning) + 0.10 (axis2_capex_below1_8q)
             + 0.10 (axis4_strong_cycle)                          = 0.55 ≥ 0.50 → 편입 가능
```

축1 이 `not_applicable` 이므로 판별의 중심 축은 판정하지 않았고, 축3 은 **경고**다.
§3.5 는 축3 이 판정을 냈으므로 발동하지 않는다. **남은 가산은 전부 축2·축4** 다.

**왜 문제인가** `docs/04` 는 축2(자본 사이클)를 **"단독 판별 불가"** 로 못박는다 — 자본 지출
감소는 사이클 저점에서도 사양 산업에서도 똑같이 나타나기 때문이다. 그 축이 편입을 결정한다.
그리고 `docs/04:96` 이 요구한 "축 3 에 가중치를 **이전**한다" 는 **미구현**이고
(`journal/2026-08-24-l3-gate-not-applicable-fixed.md` 열린 질문 1), 미구현의 방향이
**안전한 쪽이 아니라 느슨한 쪽**이다 — 이전이 구현됐다면 축3 의 `−0.15` 가 더 무겁게 실렸을 것이다.

**무엇을 해야 하는가** "가중치 이전" 의 정량적 형태는 **`docs/04` §4 에 계수가 없다 → 새 선언이
필요하다.** 지금 할 수 있는 것은 이 조합(축1 NA + 축3 warning)을 게이트 `notes` 에 드러내는 것.

---

#### 20 · [중간·경계] L3 — 종목 경계는 `claim` 하나만 검사하고 한글 표기로 우회된다

**어디** `src/msa/l3/schema.py:146-156` (`_stock_mention`) · `:186-190` (호출 — `claim` 만) ·
`CLAUDE.md` §4

**확인** 코드 읽기. `_stock_mention` 은 `claim` 에서만 돌고, 결과는 **경고**
(`W_CLAIM_NAMES_STOCK`)다. 이름 매칭은 `n0.lower() in claim.lower()` — 멤버 메타의 **영문명**
(`"Home Depot Inc"`)이 문자 그대로 들어 있어야 한다.

**실증** `home_improvement` thesis 의 claim 에 "홈디포·로우스" 가 나온다. 영문명과 매칭되지
않아 **경고조차 뜨지 않는다.** `mechanism`·`triggers`·`invalidations` 는 애초에 검사 대상이
아니다.

**왜 문제인가** `CLAUDE.md` §4 는 "에이전트는 테마만 고른다. 종목은 결정론적 계층이 고른다" 를
**절대 규칙**으로 세우고, 이 저장소는 그것을 "헌법" 이라 부른다. 강제력이 `claim` 한 필드의
경고 하나다.

**무엇을 해야 하는가** 검사 범위를 `mechanism`·`triggers`·`invalidations` 로 넓히고,
멤버 메타에 한글 별칭이 있으면 함께 매칭한다. **경고를 오류로 올릴지는 판단이 필요하다** —
테마 이름 자체가 회사명인 경우가 있어 오탐이 생긴다. 그 판단은 여기서 하지 않는다.

---

#### 21 · [중간] L3 — 증거 규약에 구멍 셋

**어디** `src/msa/l3/schema.py:229-243`

**확인** 코드 읽기:

| 규약 | 실제 |
|---|---|
| `source_url: "내 기억"` | `W_EVIDENCE_URL` **경고**만 (`:231-236`) |
| **미래 날짜 증거** | `_evidence_date` 가 파싱되면 통과. `months_between(d, today) > STALE` 만 본다 → **미래는 음수라 걸리지 않는다** (`:237-243`) |
| 전 증거 `reliability: high` | enum 검사만. 자기승격 통과 |

**왜 문제인가** `CLAUDE.md` §3 은 "LLM 의 기억은 증거가 아니다" 를 절대 규칙으로 세웠고,
`R_EVIDENCE_EMPTY` 는 배열이 비면 거부한다. 그런데 **배열이 차 있기만 하면 내용은 거의
검사되지 않는다.** 미래 날짜는 특히 나쁘다 — `docs/10` §4 캘리브레이션이 증거 날짜로 시점을
정렬하므로 **오염 경로**가 된다.

**무엇을 해야 하는가** 미래 날짜를 오류로 만든다(`d > today` → `R_EVIDENCE_DATE`). 이것은 새
임계가 아니라 산술적 불가능이다. `source_url` 과 `reliability` 자기승격은 판단이 필요하다.

---

#### 22 · [중간] L3 — 같은 라운드 재실행이 무음 덮어쓰기다

**어디** `src/msa/l3/contracts.py:286-293` (`find_prior_thesis`) ·
`src/msa/l3/pipeline.py:328` (`supersedes: inputs.prior_thesis_path`)

**확인** 코드 읽기:

```python
cands = sorted(p for p in theses_root.glob(f"*/{thesis_filename(theme_id)}")
               if p.parent.name < before)      # ← 엄격 부등호
```

**같은 날짜 디렉터리를 못 본다.** 그래서 같은 asof 로 다시 돌리면 직전 산출물을 찾지 못하고
`supersedes: null` 로 저장되며, 파일은 덮어쓰인다.

**원자료와 달랐던 점** 같은 이름의 함수가 하나 더 있다 — `pipeline/run.py:425-430`
`_find_prior_thesis` 는 `<= asof` 를 쓴다(결함 없음). 결함이 있는 것은 `contracts.py` 쪽이다.

**왜 문제인가** `msa journal diff <theme>` 가 재는 "논지 표류" 의 사슬이 끊긴다. 그리고
`CLAUDE.md` §6(저널 append-only)의 정신과 어긋난다 — `state/theses/` 는 저널이 아니지만
캘리브레이션의 입력이다.

**무엇을 해야 하는가** `<=` 로 바꾸되 자기 자신을 제외하거나, 같은 날짜 재실행을 `-2`, `-3`
접미사로 남긴다. 어느 쪽이든 새 값이 없다.

---

#### 23 · [중간·경계] L3 — 같은 것이 두 곳에 정의돼 있다 (3건)

**어디**

| 무엇 | 정본이 둘 |
|---|---|
| C6 최소 확신도 0.5 | `src/msa/l3/gates.py:41` (`PORTFOLIO_MIN_CONFIDENCE`) · `src/msa/l5/optimize.py:56` (`MIN_CONFIDENCE`) |
| thesis 필수 11필드 | `src/msa/l3/schema.py:162-168` (**스펙 파일에서 읽는다** — `docs/specs/thesis.schema.yaml:6-17`) · `src/msa/ops/thesis.py:45-57` (`_REQUIRED_TOP` — **손으로 베낀 상수**) |
| thesis 검증기 | `msa.l3.schema.validate_thesis`(39개 거부 규칙) · `msa.ops.thesis.validate_thesis`(최소 검증) |

**확인** 코드 읽기. 세 번째는 `ops/thesis.py:71-73` 이 그 이유를 적는다 — "예외·문구가 다르다".
그러나 저널 경로(`msa journal new --from`)는 **최소 검증만** 거치므로, 스키마가 거부할 thesis 가
저널에는 들어갈 수 있다.

**왜 문제인가** 값 하나가 두 곳에 있으면 한쪽만 바뀐다. 특히 `_REQUIRED_TOP` 은 스펙 파일이
바뀌어도 따라가지 않는다 — 지금은 같지만 그것을 보증하는 테스트가 없다.

**무엇을 해야 하는가** 상수를 한 곳에서 import 하거나, 최소한 두 곳이 같음을 테스트로 못박는다.

---

#### 24 · [중간·경계] L3 — 죽은 표면 넷

**어디**

| 표면 | 호출처 |
|---|---|
| `providers.SearchBudget.charge()` (`:199`) | **0** |
| `providers.SearchTool.search()` (`:146,156,175`) | **0** — 프로토콜과 두 구현만 있고 부르는 곳이 없다 |
| `providers.CostLedger.total()` (`:229`) | **0** |
| bear 의 `attacks`(6축 강도 판정, `roles.py:350`) · catalyst 의 `calendar`(`roles.py:271`) | 스키마에 `required` 인데 **thesis 에 저장되지 않는다** (`l3/pipeline.py:320-360` 에 없다) |

**왜 문제인가** 앞 셋은 유지비만 있다. 넷째가 더 무겁다 — bear 가 6축 각각에 대해 낸 **강도
판정**과 catalyst 의 **캘린더**는 사후에 "bear 가 맞았는가" 를 재는 유일한 재료인데, 라운드가
끝나면 사라진다. `docs/10` §4 캘리브레이션이 그것을 필요로 한다.

**무엇을 해야 하는가** `attacks` 와 `calendar` 를 thesis(또는 `report.md`)에 저장한다.
앞 셋은 지우거나 배선하거나 — 어느 쪽이든 값 결정이 아니다.

---

#### 25 · [중간] L3 — 검색 없이 조용히 돈다

**어디** `src/msa/l3/providers.py:340-343` · `:151-164` (`StubSearchTool`)

**확인** 코드 읽기:

```python
if request.allow_search:
    spec = self.search.provider_tool_spec(max_uses=self.budget.remaining(request.role))
    if spec is not None:
        kwargs["tools"] = [spec]        # ← None 이면 tools 없이 그냥 부른다
```

`StubSearchTool.provider_tool_spec()` 은 `None` 을 돌려준다(`:163-164`). 그래서 검색이 미설정인
상태로 `allow_search=True` 요청이 **아무 경고 없이** 검색 없이 실행된다. docstring 이 약속한
`NotConfigured` 는 **사문화된 `search()` 에만** 있다(`:157`).

또한 서버 검색이 실패해도(HTTP 200 + `web_search_tool_result` 안의 error 블록) 검사하지
않는다 — `:353` 은 `type == "text"` 블록만 모은다.

**왜 문제인가** L3 산출물의 증거는 검색에서 온다. 검색이 없으면 증거는 모델의 기억이고,
그것은 `CLAUDE.md` §3 이 금지한 바로 그것이다. **아무 표시 없이** 그 상태로 돌 수 있다.

**무엇을 해야 하는가** `allow_search=True` 인데 `spec is None` 이면 예외를 던지거나 최소한
`report.md` 와 thesis 의 `inputs.warnings` 에 "검색 없이 생성됨" 을 남긴다.

---

#### 26 · [중간] L4 — E2 가 두 단위 공간에 같은 임계 6× 를 쓴다

**어디** `src/msa/l4/features.py:445-446` (`nd_basis`) · `src/msa/l4/axes.py:182` (E2) ·
`:237` (`leverage_score`) · `axes.HARD_REASON_LABELS["E2"] = "net_debt_ebitda > 6x"`

**확인** 코드 읽기:

```python
f["nd_basis"] = np.where(eb_pos, "ebitda", "mcap")     # EBITDA ≤ 0 이면 순부채/시총
out["E2"] = has_fund & (nd > ND_EBITDA_EXCLUDE)        # ND_EBITDA_EXCLUDE = 6.0, 단위 무관
```

**무엇** EBITDA ≤ 0 인 기업은 `net_debt_ebitda` 가 실은 **순부채/시총**이다. 그 비율이 6 을
넘으려면 순부채가 시총의 6배여야 한다 — 상장 상태에서 드문 조건이다. 즉 **E2 는 적자기업 —
생존 필터의 표적 — 에 발동하기 매우 어려운 임계를 쓴다.**
*(이것은 정의에서 따라 나오는 추론이고, `nd_basis == "mcap"` 인 종목 중 실제로 E2 에 걸린
비율은 **이 감사에서 재지 않았다.** 백테스트 산출물
`state/backtests/l4/2026-08-14/filters.csv` 는 사유별 제외군을 테마-월 단위로만 남기고
`nd_basis` 로 나누지 않는다.)*

같은 혼합이 `leverage_score` 에도 있다:

```python
leverage_score = 1 - clip(nd / 6.0, 0, 1)
```

순부채/시총 = 1.0 인 적자·저부채 기업 → **0.833**. ND/EBITDA = 3× 인 흑자기업 → **0.500**.
**S 축이 적자기업에 더 높은 점수를 준다.**

**왜 문제인가** `docs/06` §2 의 하드 제외는 "이 종목이 다음 사이클을 볼 수 있는가" 를 묻는다.
적자기업이 정확히 그 질문의 대상인데, 그 대상에 대해 임계가 사실상 무한대가 된다.
(`docs/backtest-l4.md` Q3 는 E2 제외군의 사망률 차 CI 하한이 0 초과라고 재었다 — 즉 발동한
소수에 대해서는 일했다. 문제는 **발동하지 않는 다수**다.)

**무엇을 해야 하는가** 시총 기준의 임계는 **문서에 없다 → 새 사전 등록이 필요하다.**
지금 할 수 있는 것: `nd_basis == "mcap"` 인 행이 몇 개이고 그중 몇 개가 E2 에 걸렸는지를
`meta.json` 과 리포트에 적어 이 공백을 보이게 하는 것. (`picks.py:297-302` 가 이미 `nd_basis`
를 표시하므로 재료가 있다.)

---

#### 27 · [중간] L4 — E2·E3 는 판정 불가를 통과로 처리한다

**어디** `src/msa/l4/axes.py:181-185` (`hard_filter_flags`) · `:192-193` (모듈이 스스로 적은 원칙)

**확인** 코드 읽기:

```python
out["E1"] = (has_fund & (runway < RUNWAY_MIN_Q)).fillna(False)
out["E2"] = (has_fund & (nd    > ND_EBITDA_EXCLUDE)).fillna(False)   # nd NaN → False
out["E3"] = (has_fund & (wall  > MATURITY_WALL_EXCLUDE)).fillna(False)  # wall NaN → False
out["E4"] = (has_fund & runway.isna()).fillna(False)   # ← E1 에만 있는 짝
```

**E1 만 결측 짝(E4)을 갖는다.** E2·E3 의 입력이 NaN 이면 조용히 통과한다.

같은 함수의 docstring 이 정반대를 적는다(`:192-193`):
> 재무가 없는(신선도 탈락) 종목도 제외한다 — 생존 필터를 **평가할 수 없는** 종목을 통과시키면
> 필터가 있는 척하는 것이다.

**원칙을 적어 놓고 셋 중 하나에만 적용했다.**

**왜 문제인가** 이것은 어제 L3 에서 고친 것(`journal/2026-08-24-l3-gate-not-applicable-fixed.md`)
과 **완전히 같은 결함**이다 — 판정 불가가 통과 쪽으로 열린다. 그리고 L4 쪽은 원칙이 이미
같은 파일에 적혀 있어, 선언을 찾을 필요조차 없다.

**무엇을 해야 하는가** E2·E3 에 결측 짝(E6·E7)을 붙인다. **이미 선언된 원칙의 구현이지 새
임계가 아니다** (§7-3).

**2026-08-24 조치 — 절반만 유효한 지적이었다. E6 만 붙이고 E7 은 붙였다가 철회했다.**

*(위 발견은 기록이므로 지우지 않는다. 아래가 그 뒤에 실제로 일어난 일이다.)*

E6(`net_debt_ebitda` 결측)은 지적대로 붙였고 남아 있다. E7(`maturity_wall_12m` 결측)은
같은 날 붙였다가 **철회**했다 (`docs/06` §2.1.1 · `docs/14` §8 재개정).

이 지적이 놓친 것: **E3 의 임계가 걸리는 대상은 선언된 필터가 아니다.** `docs/06` §2 가
선언한 것은 `maturity_wall_24m` 이고, SF1 에 만기 스케줄이 없어 그 값은 **어느 종목에도**
계산되지 않는다. E3 가 보는 `maturity_wall_12m = debtc/시총` 은 **선언된 적 없는 대용치**다.
따라서 "판정 불가를 통과로 열어 뒀다" 는 이 항목의 프레임이 E3 에는 맞지 않는다 — 애초에
**판정할 필터가 구현되지 않았다.** 대용치의 부재로 자르는 것은 결측 처리의 복원이 아니라
**선언되지 않은 강제를 새로 만드는 것**이고, 그것은 이 감사가 §7-3 에서 경계한 방향과 같다.

같은 문서(`docs/06` §8.1)의 `going_concern` 이 정확히 그 취급을 받고 있다 — 하드 제외로
선언됐으나 미구현이고, 그래서 **미적용으로 보고**될 뿐 그 부재로 아무도 자르지 않는다.
E3 도 같은 자리에 둔다.

E6 과 E7 을 가른 근거(비대칭):

- `net_debt_ebitda` 는 EBITDA≤0 이면 순부채/시총으로 **대체 계산된다.** NaN 이면 재무가
  아예 없다는 뜻이고 그것은 E5 와 같은 층위의 사실이다 — 업종 구조적 결측이 아니다.
- `debtc` 결측은 위험이 아니라 **회계 구조**다 (실측 REIT 100.0% · 은행 99.7% · 보험 98.2%
  vs 원유 E&P 0.1% · 금 0.0%). 은행·REIT 는 유동부채를 그렇게 보고하지 않는다.

**실측** — E7 은 `banks_regional` 적격 259 → 1 · `reit_retail` 15 → 0 · `insurance_pc`
57 → 3 으로 업종을 통째로 비웠고, 전 테마 하드 제외를 2,253 → 2,788 로 늘렸다. 철회로
**2,253 으로 정확히 복귀**했다. 반면 **E6 은 전 테마에서 3 종목-테마를 자르고, 그중 E6 이
유일 사유인 것은 0 이다** — 업종 쏠림 없음(`software_infra`·`hospitals_providers`·
`asset_managers_exchanges` 각 1). 즉 E6 은 적격군을 바꾸지 않으면서 원칙의 구멍만 메운다.

**대신 세어서 보고한다** (`CLAUDE.md` §2). `axes.unapplied_filter_flags` 가 E3 를 적용하지
못한 종목을 세고 `meta.json` `filters_unapplied` · `report.txt` "걸지 못한 하드 필터" 절이
그것을 싣는다 (실측 **809 종목-테마**). **필터가 있는 척하지 않는 방법은 제외가 아니라
계수다.** 시도 수는 E=7 의 506 이 아니라 **E=6 의 482** 가 된다 (`docs/14` §6.2).

---

#### 28 · [중간] L4 — S 축 결측 재정규화가 "모름" 을 "최상" 으로 만든다

**어디** `src/msa/l4/axes.py:267-273`

**확인** 코드 읽기 + 산술:

```python
avail = parts.notna()                        # runway .4 / leverage .3 / penalty .3
wsum  = avail.mul(w, axis=1).sum(axis=1)
s_raw = parts.fillna(0).mul(w, axis=1).sum(axis=1) / wsum
```

결측 축을 **버리고** 남은 축으로 재정규화한다 = 결측 축에 **남은 축의 평균을 대입**하는 것과
같다. 따라서 `runway_score = 1.0`(현금흐름 흑자 → `inf` → 캡 1.0) · `penalty_score = 1.0`
(감점 0) · `leverage_score = NaN` 이면 **`s_raw = 1.00`** — 순현금 기업과 동률 최상위.

**왜 문제인가** S 는 "생존" 축이다. 레버리지를 **모르는** 기업이 레버리지가 **없는** 기업과
같은 점수를 받는다. `s_inputs_missing` 열이 그 사실을 적기는 하지만(`:283`), 점수는 이미
최상위다. (2026-08-24 선정 규칙 폐기로 `s_raw` 는 관찰 지표로 강등됐다 — **그래서 낮음이
아니라 중간이다.** L5 로 넘어가는 행을 고르지는 않지만 리포트·다이제스트가 그대로 표시한다.)

**무엇을 해야 하는가** 결측을 재정규화 대신 하한(0)으로 대입할지, 아니면 `s_raw` 자체를 NaN 으로
둘지는 **값 판단이다.** 지금 할 수 있는 것은 `s_inputs_missing` 이 비지 않은 행의 `s_pct` 를
리포트에서 시각적으로 구분하는 것.

---

#### 29 · [중간] L4 — 리포트가 일어나지 않은 ETF 대체를 일어난 것처럼 적는다

**어디** `src/msa/l4/picks.py:198` (`"etf_fallback": theme.etf_proxy`) · `:371` (문구)

**확인** 코드 읽기:

```python
f"   ※ min_constituents {u['min_constituents']} 미달 — ETF 대체 {u['etf_fallback']}"
if u["below_min_constituents"] else ""
```

**대체하는 코드가 없다.** `etf_proxy` 의 유일한 소비처는 L1 의 자체지수 검증
(`l1/scan.py:124` `etf_proxy_corr`)과 `l1/physical.py:207` 의 심볼 수집이다. L4/L5 경로가 없다.

**왜 문제인가** 리포트를 읽는 사람은 소표본 테마에서 ETF 로 대체된 무언가를 보고 있다고 믿는다.
그리고 `docs/06` §8.4 "아직 없는 것" 목록에도 이 항목이 **없다** — 즉 미구현이라는 사실조차
어디에도 적혀 있지 않다.

**무엇을 해야 하는가** 문구를 사실대로 바꾼다 — "min_constituents 미달 (ETF 프록시 {…} 는
L1 검증용이고 L4 는 대체하지 않는다)". 또는 `docs/06` §8.4 에 추가한다.

---

#### 30 · [중간] L4 — `vcp_base` 의 부수 결함 셋

**어디** `src/msa/l4/features.py:60` (docstring "최근 252일") · `:613` (`n >= 60`) ·
`:622-636` · `PRICE_LOOKBACK_DAYS = 430` (`:98`)

**확인** 코드 읽기.

1. **창 길이 불일치.** 머리말은 "최근 252일" 이라 적는데 계산 조건은 `n >= 60` 이고,
   `vcp_base(pd.Series(c), pd.Series(v))` 에 넘기는 것은 **적재된 창 전체**(430 캘린더일 ≈
   290 거래일)다. 252 로 자르는 코드가 없다.
2. **수축 최신성 요구 없음.** `cons[-max_cons:]` 는 마지막 4개를 가져오지만 그것이 **얼마나
   오래전인지**를 보지 않는다. 베이스 후 120봉이 지나도 True 다.
3. **dry-up 임계 없음.** `v10 < v50` 순부등호 — 1% 차이도 통과한다. `docs/06` 이 말하는
   "거래량 수축" 에 정도가 없다.

**왜 문제인가** 셋 다 `vcp_base` 를 실제보다 훨씬 자주 True 로 만든다. P2 와 같은 방향이다.

**무엇을 해야 하는가** (1)은 문서와 코드 중 하나를 맞추는 것으로 새 값이 없다. (2)(3)의
임계는 **문서에 없다 → 사전 등록이 필요하다.**

---

#### 36 · [중간] 배선 — 계약 위반이 `skipped` 로 위장된다

**어디** `src/msa/pipeline/run.py:997-999` · `src/msa/pipeline/assemble.py:239,249,482,563`

**확인** 코드 읽기:

```python
except AssembleError as e:
    report.add(StepResult("assemble", "skipped", f"묶을 테마 0 — {e}", seconds=t.seconds))
    report.add(StepResult("portfolio", "skipped", "묶음이 없다"))
```

`AssembleError` 를 던지는 곳은 넷이고, **그중 하나만 정상 상황**이다:

| 소재 | 성격 |
|---|---|
| `:563` "묶을 테마가 0개다 — 전부 건너뜀" | **정상** (오류 아님) |
| `:249` "ranking 에 열이 없다 — L4 산출물이 아니다" | **계약 위반** |
| `:482` "사람 논지 디렉터리가 없다" | **입력 오류** |
| `:239` "top_per_theme 은 1 이상이어야 한다" | **프로그래밍 오류** |

넷 다 "묶을 테마 0 — …" 로 보고되고 종료 코드 0 이다.

**왜 문제인가** 사람이 매일 보는 것은 요약 줄이다. `skipped` 는 "할 일이 없었다" 로 읽힌다.
L4 산출물 계약이 깨진 날과 그냥 편입 테마가 없던 날이 **화면에서 구분되지 않는다.**

**무엇을 해야 하는가** `AssembleError` 를 계약 위반과 정상 공집합으로 나누고, 전자는
`failed` 로 보고한다. 종료 코드를 바꿀지는 별개 판단이다.

---

#### 37 · [중간] 배선 — 깨진 직전 다이제스트가 "첫 실행" 으로 둔갑한다

**어디** `src/msa/pipeline/daily.py:130-131` (선언) · `:621-625` (삼킴) · `:342` (문구)

**확인** 코드 읽기:

```python
# daily.py:130 — "깨진 기준은 건너뛰지 않고 그 사실이 남게 던진다"
raise RunError(f"직전 다이제스트를 읽을 수 없다 ({f}): {e}")
...
# daily.py:621
try:    prev = previous_digest(p.daily, asof_s)
except RunError as e:
    report.notes.append(str(e))     # ← 노트에는 남는다
    prev = None                     # ← 그리고 첫 실행처럼 진행한다
```

그 뒤 `:342` 가 산출물에 이렇게 적는다 — `기준 다이제스트 없음 (첫 실행 — 전부 신규)`.

**원자료와 달랐던 점** 원자료는 "삼킨다" 고 적었는데, `report.notes` 에는 남는다.
**완전히 조용하지는 않다.** 문제는 **산출물이 반대로 말한다**는 것이다 — 노트는 "읽을 수
없었다", 다이제스트 본문은 "첫 실행이다".

**왜 문제인가** 그날 diff 전체(`new_since_prev` 플래그 · "오늘 새로 올라온 것" 섹션 ·
텔레그램 머리)가 **전부 신규**가 되어 무의미해진다. 그리고 그 무의미함이 정상 출력처럼 보인다.

**무엇을 해야 하는가** 문구를 갈라 놓는다 — "첫 실행" 과 "직전 기준을 읽지 못해 비교 불가"
는 다른 말이다. 던질지 말지는 판단이지만, 문구를 나누는 것은 판단이 아니다.

---

#### 38 · [중간] 배선 — 선정에서 빠진 자격 테마가 아무 데도 기록되지 않는다

**어디** `src/msa/pipeline/run.py:316-321` (재정렬) · `:343-357` (`notes` — 이 경우가 없다)

**확인** 저장된 스캔으로 **재현했다**:

```
state/scans/2026-08-14/scoreboard.csv → select_themes(top_k=8)
selected: media_streaming(1) health_it(2) insurance_brokers(4) shipping_container(5)
          it_services(6) home_improvement(7) fintech_payments(8) staffing_consulting(9)
notes: ()
retail_department: rank 3 · eligible True · small_sample True · 선정에서 빠짐
```

**원자료와 달랐던 점** 원자료는 "`retail_department` rank 1" 이라 적었다. 저장된 2026-08-14
스캔에서 그 테마는 **rank 3** 이다. 현상은 정확히 재현된다.

**무엇** `rank` 는 순수 점수 순인데 `select_themes` 는 `(small_sample, score)` 로 재정렬한다.
그 **규칙 자체는 문서화돼 있다**(`select_themes` docstring · `Scoreboard.top_k` · `docs/02`
§7.1). 기록되지 않는 것은 **사건**이다 — 어떤 자격 테마가 소표본 감점으로 K 밖으로 밀렸는지가
`ThemeSelection.notes` 에도, 다이제스트에도, 월간 리포트에도 없다.

**왜 문제인가** 다이제스트가 순위 2 또는 4 부터 시작하고, 그 사이의 빈 자리에 대한 설명이
어디에도 없다. 사람은 그 테마가 자격 미달이라고 추정하게 되는데 사실은 자격이 있다.

**무엇을 해야 하는가** `notes` 에 "자격 테마 N 개가 소표본 감점으로 상위 K 밖 — {목록}" 을
추가한다. 규칙은 그대로 둔다.

---

#### 39 · [중간] 배선 — L3 → L4 배선이 아예 없다

**어디** `src/msa/l4/picks.py:154-164` (`run_picks` 시그니처) · `docs/06` 머리말 · `docs/06` §8.4

**확인** 코드 읽기:

```python
def run_picks(theme_id, *, asof=None, top=DEFAULT_TOP, write=True,
              themes_path=None, out_root=None, allow_fetch=True, with_physical=True)
```

**thesis 인자가 없다.** L3 가 L4 에 주는 것은 `pipeline/run.py:741-743` 의 불리언 하나 —
"이 테마의 게이트가 편입 가능한가" 뿐이다.

**왜 문제인가** `docs/06` 머리말은 이렇게 적는다 — "L3 는 테마 논지만 산출하고, **L4 는 그
논지를 입력으로 받되** 랭킹은 코드가 한다." 받지 않는다. (같은 문서 §8.4 는 "M7 뒤" = 미구현이라
적어 **두 서술이 서로 모순**이다.) 그리고 `CLAUDE.md` §4 의 문장도 같은 형태다.

**무엇을 해야 하는가** 어느 서술이 맞는지 정한다. thesis 를 L4 입력으로 실제로 쓰려면 **무엇에
쓸지가 새 설계 결정**이다 — `docs/06` 은 그것을 말하지 않는다. 지금 할 수 있는 것은 머리말을
§8.4 와 일치시키는 것.

---

#### 40 · [중간] 배선 — `thesis_snapshots`·`journal_entries` 는 아무도 넘기지 않는 죽은 파라미터다

**어디** `src/msa/l5/positions.py:180-181,280-281` · 호출처 **0**
(`grep -rn "thesis_snapshots=" src/` → positions.py 밖에 없음) ·
`src/msa/pipeline/assemble.py` (경로를 이미 안다)

**확인** 코드 읽기. 두 매개변수는 기본값 `None` 이고, 어느 호출자도 넘기지 않는다.
결과적으로 모든 제안 행이 `thesis_snapshot: null` 이고, `_note()` 가 "사람이 채울 것" 을 붙인다.

**왜 문제인가** `assemble` 은 각 테마의 thesis 파일 경로를 이미 손에 들고 있다
(`assemble.py` 의 `theses/` 산출). 사람이 손으로 채우게 하는 대신 넘기기만 하면 된다.
그리고 `positions.yaml` 의 `thesis_snapshot` 은 `msa check` 가 무효화 조건을 읽는 자리다 —
비어 있으면 그 점검이 서지 않는다.

**무엇을 해야 하는가** `assemble` 이 아는 경로를 `emit_positions` 로 넘긴다. 값 결정 없음.

---

#### 41 · [중간] 배선 — 텔레그램 다이제스트에만 L4 폐기 고지가 없다

**어디** `src/msa/pipeline/daily.py:71-75` (`HONESTY_HEADER`) · `:339,407,686` (쓰이는 곳) ·
`src/msa/ops/alerts.py:188-189` (텔레그램 꼬리)

**확인** 코드 읽기.

```python
HONESTY_HEADER = ("측정값·후보 목록 — 투자 조언 아님; L1 점수 예측력 약함(docs/02 §7.1); "
                  "L4 선정 = 하드 제외 통과 전부·동일가중, 종합·순위·바벨은 관찰 지표(docs/06 §6.1).")
```

`digest.md`(`:339`) · `report.txt`(`:407`) · `digest.json`(`:686`) 셋 다 이 문장을 싣는다.
텔레그램 꼬리(`alerts.py:189`)는 다르다:

```
"측정값·후보 목록이다 — L1 점수의 예측력은 약하다 (docs/02 §7.1)"
```

**L4 절반이 빠졌다.**

**원자료와 달랐던 점** 원자료는 텔레그램이 "파일보다 더 순위처럼 읽힌다" 고 했다. 종목 줄은
`_alert_pick_line`(`daily.py:438`)이 **"관찰종합"** 이라는 단어를 쓰고 그룹 라벨이 `ELIGIBLE`
이라 완전히 벌거벗지는 않았다. 그래도 **정렬 순서는 랭킹 순**이고, 폐기 고지 문장이 없다.

**무엇을 해야 하는가** 꼬리를 `HONESTY_HEADER` 로 통일한다. 문구는 이미 있다.

---

#### 47 · [중간] L5 — C4 유동성 제약이 기본값에서 꺼져 있다

**어디** `src/msa/cli.py:683` (`--capital` 기본 0.0) · `src/msa/l5/optimize.py:228-231,317`

**확인** 코드 읽기:

```python
if p.capital_usd is not None and p.capital_usd > 0:
    add(f"C4:{ticker}", w[i] <= LIQ_FRACTION_OF_ADV * adv / p.capital_usd)
...
c4_applied = p.capital_usd is not None and p.capital_usd > 0
```

`msa run monthly` 의 `--capital` 기본값이 `0.0` 이므로 **표준 실행에서 C4 는 한 번도 걸리지
않는다.** (`c4_applied: false` 가 진단에 남고 경고도 찍힌다 — 조용하지는 않다.)

**왜 문제인가** `docs/07` §2.4 가 C4 를 제약 목록에 넣은 이유는 소형주 테마에서 비중 상한이
유동성보다 클 수 있기 때문이다. 오늘 실제로 `LEGH`(ADV $4.0M) 같은 종목이 후보에 있다.
`--capital` 은 사람이 매번 기억해서 넣어야 하는 값이다.

**무엇을 해야 하는가** 총자본을 설정 파일(또는 환경변수)에서 읽거나, 미지정 시 리포트 머리에
"C4 미적용" 을 **경고가 아니라 판정**으로 올린다. 자본 값 자체는 사람의 것이다.

---

#### 48 · [중간] L5 — M 축이 L5 에서도 읽히지 않는다 (선언된 포기)

**어디** `src/msa/pipeline/assemble.py:122-127` (`OMITTED_COLUMNS`) ·
`src/msa/l5/inputs.py:122` (기본 `False`) · `src/msa/l5/positions.py:126`

**확인** 코드 읽기:

```python
"split_first_leg": (
    "docs/07 §3 'M 축이 낮으면 25%+25% 분할' 의 컷이 문서에 없다 — 컷을 만들지 않는다 "
    "(CLAUDE.md §1). M̃ 는 notes 에 적혀 있어 사람이 정할 수 있다"
),
```

`assemble` 이 이 열을 **항상 비운다.** 따라서 "1단 25+25 분할" 문구가 산출물에 절대 나타나지
않는다.

**정상 참작 — 이것은 조용한 누락이 아니다.** `docs/07:470` 이 "컷이 문서에 없어 만들지 않는다"
를 명시하고, 코드가 그 이유를 문자열로 들고 있으며, `Pick.notes` 에 M̃ 백분위가 실려 사람이
판단할 수 있게 해 뒀다. **`CLAUDE.md` §1 을 지키기 위한 의도적 미구현이다.**

**왜 여전히 결함인가** `docs/07` §3 본문은 여전히 이 기능이 있는 것처럼 서술한다. 그리고
`Pick.notes` 를 L5 의 어느 모듈도 읽지 않으므로(#43) "사람이 정할 수 있다" 의 재료가 실제로는
매매계획서에 나타나지 않는다. **두 결함이 맞물려 선언된 포기가 무음 누락이 된다.**

**무엇을 해야 하는가** #43 을 먼저 고친다(notes 를 계획서에 싣는다). 컷 자체는 **새 선언이
필요하다** (§8 열린 질문 3).

---

#### 49 · [중간] L5 — 계획서가 "앵커 : 토크 = 0 : 100" 을 단언한다

**어디** `src/msa/l5/plan.py:155-161` · `src/msa/l5/run.py:366` (`anchor_share`) ·
`src/msa/l5/inputs.py:129` (`is_anchor`)

**확인** 코드 읽기. `is_anchor` 는 `role == "anchor"` 를 본다. 2026-08-24 결정으로 L4 는
모든 적격 종목에 `ELIGIBLE` 라벨을 붙이고 `assemble` 이 그것을 `role = "eligible"` 로 사상하므로
**`is_anchor` 가 항상 False** 다. `anchor_share = 0.0` → 계획서가 `앵커 : 토크 = 0 : 100`.

**왜 문제인가** `journal/2026-08-24-l4-selection-retired.md` 는 이 부수 효과를 예견하고 적었다 —
"L4 가 앵커를 **지정하지 않기** 때문이지 앵커 비중을 0 으로 정한 것이 아니다." 그런데
**계획서 문구는 그 구분을 하지 않는다.** `0 : 100` 은 바벨이 무너졌다는 뜻으로 읽힌다.

**무엇을 해야 하는가** `anchor_share` 가 `role` 라벨 부재에서 온 경우 `— (L4 가 앵커를 지정하지
않는다, docs/06 §6.1)` 로 표시한다. 저널이 이미 그 문장을 갖고 있다.

---

#### 50 · [중간] L5 — `docs/07` 의 세 서술에 대응 코드가 없다

**어디**

| `docs/07` | 서술 | 코드 |
|---|---|---|
| §2.5:231-232 | 계층적 클러스터링으로 상관 0.7 이상 묶고 그룹 합 상한 → 목표 ENB 까지 **반복** | `optimize.py:96` 은 **사용자가 준** `cluster_caps` 만 받는다. 클러스터링도 반복 루프도 없다 |
| §6 | 종목 상관 경고 | 없음 |
| §5:325 | TP1 후 그 분이 **MDD 예산에서 해제** | `optimize.py`·`risk.py` 에 TP 상태를 읽는 코드 없음 (`grep "tp1|해제"` → 0) |

**확인** 위 grep 과 코드 읽기.

**왜 문제인가** ENB 는 계산되고 계획서에 찍히지만(`plan.py:136-142`) **아무것도 조정하지
않는다.** §2.5 는 ENB 를 목표로 삼아 반복하라고 했는데 반복이 없으므로 ENB 는 사후 관찰값이다.
`plan.py:213` 이 "눈금 없음" 이라 적어 부분적으로 정직하다.

**무엇을 해야 하는가** 셋 다 구현하려면 값(상관 임계 0.7 은 있으나 그룹 캡·목표 ENB 는 없다)이
필요하다 → **사전 등록 대상.** 지금 할 수 있는 것은 `docs/07` 에 미구현 표시를 다는 것
(`docs/06` §8.4 형식).

---

#### 53 · [중간] 배선 — `--no-write` 월간에서 assemble 이 직전 thesis 를 못 본다 *(이번 통합 중 새로 확인)*

**어디** `src/msa/pipeline/run.py:777-784` (`_locate_theses` — 실 `state/` 로 폴백한다) ·
`src/msa/pipeline/assemble.py:482` 이하 (샌드박스 루트만 본다)

**확인** **오늘 실제 실행.** `msa run monthly --no-write --provider none`:

```
research  ok       논지 찾음 1/8 (human 0 · 직전 L3 1)
                   → state/theses/2026-08-14/home_improvement.thesis.yaml
picks     ok       테마 1/1 랭킹
assemble  skipped  묶을 테마 0 — asof 2026-08-24: 묶을 테마가 0개다 — 전부 건너뜀:
                   home_improvement: thesis 없음 (/tmp/msa-run-mfy325ez/theses/<≤2026-08-24>/...)
portfolio skipped  묶음이 없다
```

**같은 실행 안에서 한 단계는 실 `state/` 의 파일을 찾았고, 다음 단계는 샌드박스만 보고 없다고
했다.** `_locate_theses` 는 `roots.sandbox` 일 때 `roots.real / "theses"` 로 명시적으로
폴백하는데(`run.py:783-784`), assemble 경로에는 그 폴백이 없다.

**왜 문제인가** `--no-write` 는 "쓰지 않고 확인만" 하는 표준 시연·검증 경로다. 그 경로에서
**L5 까지 도달하는 것이 구조적으로 불가능하다.** 그리고 그 실패가 #36 을 통해 `skipped` 로
보고돼 정상처럼 보인다.

**무엇을 해야 하는가** assemble 의 thesis 탐색에 같은 실-루트 폴백을 붙인다. 값 결정 없음.

---

### 낮음 (10)

---

#### 6 · [낮음] L0 — `msa data audit` 이 한 종목 때문에 영구 exit 1 이고, 구현된 검사는 호출되지 않는다

**어디** `src/msa/cli.py:260-262` (exit) · `:256-258` (`[3]` 자리) ·
`src/msa/data/universe.py:233` (구현된 검사기)

**확인** **실행했다:**

```
폐지 종목 포함 감사 [2010-01-01~2026-08-24]: 7,014/7,015 (99.99%) · 실패 — 1종목 누락
  누락: ['TFSA']
[3] 중복 소속
  테마 버킷 정의가 없다 (M2). 검사기는 있으나 입력이 없어 실행하지 않는다.
```

**두 가지.** (a) `TFSA` 한 건 때문에 명령이 항상 exit 1 이다 — `docs/08` 이 스스로
"늘 실패하는 관문은 무시된다" 고 적었다. (b) `[3]` 의 문구가 **stale** 이다: M2 는 끝났고
`state/themes.yaml` 에 확정 134 테마가 있다. `audit_duplicate_membership` 은 구현·테스트돼
있는데 호출되지 않는다.

**무엇을 해야 하는가** `TFSA` 를 알려진 예외로 등록하거나 임계를 비율로 바꾼다(값 결정).
`[3]` 은 `themes.load_themes()` 를 불러 실제로 검사하면 된다(값 결정 없음).

---

#### 15 · [낮음·경계] L1 — 저장소 공용 통계 라이브러리가 L1 아래 살고, private 이름이 계층을 넘는다

**어디** `src/msa/l1/backtest.py` · `src/msa/l4/backtest.py:83` · `src/msa/l4/structures.py:66,80-81`

**확인** `l4/structures.py` 가 `msa.l1.backtest` 에서 **private 이름**을 가져온다:

```python
from msa.l1.backtest import (BOOT_BLOCK, ..., _plain, _summarize)
```

**원자료와 달랐던 점** 원자료는 `_spearman_rows` 도 임포트한다고 적었다. **아니다** —
그 이름은 `l4/backtest.py:9,39` 의 docstring 에서 **언급**될 뿐 임포트되지 않는다.
실제로 계층을 넘는 private 이름은 `_plain` 과 `_summarize` 둘이다.

**왜 문제인가** L4 백테스트가 L1 의 내부 구현에 묶인다. `_summarize` 의 시그니처가 바뀌면
L4 가 조용히 깨진다. (완화 요인 — 상수 12개는 public 이고, 두 백테스트가 **같은 관문 정의**를
써야 한다는 요구는 `docs/10` §2.2 에서 온 정당한 것이다.)

**무엇을 해야 하는가** 공용 통계 부분을 `msa/vendor/` 나 `msa/stats.py` 로 올리고 두 이름을
public 으로 만든다. 수학은 한 줄도 바뀌지 않는다.

---

#### 32 · [낮음] L4 — 계산되고 아무도 안 읽는 열 셋

**어디** `src/msa/l4/features.py:601` (`from_52w_high`) · `:604` (`sma200_up_1m`) ·
`src/msa/l4/axes.py:327` (`m_n_inputs`)

**확인** `grep -rn "from_52w_high|sma200_up_1m|m_n_inputs" src/msa/` → **features.py·axes.py
밖에 소비처 없음.** 그리고 `s_inputs_missing`·`t_inputs_missing` 은 있는데
**`m_inputs_missing` 은 아예 존재하지 않는다**(`axes.py:322-327` — M 은 `m_n_inputs` 만 낸다).

**왜 문제인가** `from_52w_high` 는 P2 가 필요로 하는 바로 그 열이다 — **이미 계산돼 있는데
한 줄도 쓰이지 않는다.** `m_inputs_missing` 부재는 M 축의 결측 이유가 S·T 와 달리 추적되지
않는다는 뜻이다.

**무엇을 해야 하는가** `m_inputs_missing` 을 S·T 와 같은 방식으로 추가한다(대칭 복원이지 새
값이 아니다). `from_52w_high` 소비는 P2·§7-4 참조.

---

#### 33 · [낮음] L4 — README 자기모순

**어디** `README.md:458` 과 `README.md:520`

**확인** 같은 파일이 `:458` 에 L4 백테스트 결과를 싣는다 —
"**Q1 FAIL** — `rank_score` 주 창 12M rank-IC **+0.0144 [−0.0008, +0.0266]**". 그런데 62줄
아래 `:520` 의 상태 표는 이렇게 적는다:

| 계층 | 백테스트 | 상태 |
|---|---|---|
| **L4 종목 선정** | 가능 | **2026-08-23 최초 실행 중. 결과 없음** |

**무엇을 해야 하는가** 표를 갱신한다.

---

#### 42 · [낮음] 배선 — `triggers[].check`(가격 DSL)가 묶음 yaml 에서 탈락한다

**어디** `src/msa/pipeline/assemble.py:139` (`_OBS_KEYS`) · `src/msa/ops/check.py:18-22,156`

**확인** 코드 읽기:

```python
_OBS_KEYS = ("observable", "source", "by", "action", "status")     # ← "check" 없음
```

`ops/check.py:18-22` 는 `thesis.triggers[*].check` / `invalidations[*].check` 를 가격 DSL 로
읽는다(`price_below`/`price_above`). `assemble` 을 거치면 그 키가 사라진다.

**살아 있는 결함은 아니다** — 현재 `msa check` 는 `positions.yaml` 의 `thesis_snapshot`
(저널 스냅샷)을 읽지 묶음 yaml 을 읽지 않는다. 경로가 이어지면 발현된다.

**무엇을 해야 하는가** `_OBS_KEYS` 에 `"check"` 를 넣는다.

---

#### 43 · [낮음] 배선 — `Pick.notes` 를 L5 의 어느 모듈도 읽지 않는다

**어디** `src/msa/pipeline/assemble.py:179-186,298` (`_pick_notes` 가 채운다) ·
`src/msa/l5/inputs.py:126,199` (필드로 받는다) · `grep "\.notes" src/msa/l5/` → `plan`·
`positions`·`optimize` 에 **0**

**확인** 코드 읽기. `_pick_notes` 는 감점·레드플래그·3축 백분위·바벨 라벨·`composite_partial`
을 전부 담는다. `plan.md` 와 `positions-proposal` 에는 **한 글자도 나오지 않는다.**

**왜 문제인가** #48 이 "M̃ 는 notes 에 적혀 있어 사람이 정할 수 있다" 를 근거로 미구현을
정당화하는데, **그 notes 가 사람 앞에 도달하지 않는다.**

**무엇을 해야 하는가** `plan.md` 의 종목 블록에 `notes` 를 한 줄 싣는다.

---

#### 44 · [낮음] 배선 — `msa backtest l4-structures` CLI 가 등록돼 있지 않다

**어디** `src/msa/cli.py:373,392,409` (`l1`·`l1-structures`·`l4` 만 등록) ·
`src/msa/l4/structures.py` (모듈은 있다) · `docs/15` §4 (그 모듈이 만든 근거)

**확인** `grep -n "l4-structures" src/msa/cli.py` → **0.**

**왜 문제인가** `docs/15` §4 의 표(B0~B3 비교)와
`journal/2026-08-24-l4-selection-retired.md` 의 근거 수치가 **이 모듈에서 나왔는데 재실행할
명령이 없다.** `msa ops reproduce` 의 정신과 어긋난다.

**무엇을 해야 하는가** `backtest_app` 에 커맨드를 등록한다.

---

#### 45 · [낮음] 배선 — `docs/09` ingest 표에 `l2_tailwind` 잔재

**어디** `docs/09-operations.md:242`

**확인** L2 는 2026-08-23 에 제거됐고 `ops/journal.py:842-845` 는 그 필드를 들고 오는 초안을
**거부**한다. 그런데 `docs/09` §7 진입 초안 표는 여전히 `l2_tailwind`(`state/macro/latest.json`,
없으면 thesis 의 `inputs.macro_tailwind`)를 채우라고 적는다. 두 경로 모두 이제 존재하지 않는다.

**무엇을 해야 하는가** 그 문장을 지우지 말고 제거 표시를 단다(`docs/03` 머리글 형식).

---

#### 51 · [낮음] L5 — 월 중 결측일을 수익률 0 으로 메우고 세지 않는다

**어디** `src/msa/l5/risk.py:114-118` (`monthly_returns`) · `:120-124` (`index_level`)

**확인** 코드 읽기:

```python
def monthly_returns(daily):
    has  = daily.notna().resample("ME").sum() > 0
    comp = (1.0 + daily.fillna(0.0)).resample("ME").prod() - 1.0
    return comp.where(has)          # 한 달 전부 NaN 이면 NaN — 그건 지킨다
```

**한 달이 통째로 비면** NaN 으로 남긴다(docstring 이 그렇게 약속하고 지킨다). **월 중 일부**
결측은 수익률 0 으로 채워지고 세지 않는다. `index_level` 도 같다(`:122`).

**왜 문제인가** 이 지수가 `L_i` 의 첫째 항(과거 유사 국면 최대 낙폭)을 만든다. 결측일이
0 으로 채워지면 낙폭이 **작게** 나오고, `L_i` 가 작아지면 C1-(ii) 제약이 **느슨해진다.**
(`docs/07:135` 이 `L_i` 오차의 방향에 대해 같은 말을 이미 한다 — "안전한 쪽으로 틀린 값이
아니다".)

**무엇을 해야 하는가** 월별 결측일 수를 세어 진단에 남긴다. 임계는 필요 없다.

---

#### 52 · [낮음] L5 — `L_i` 는 사실상 여전히 서지 않고, `docs/07` 의 설명이 stale 이다

**어디** `src/msa/l5/risk.py:474-493` · `state/cases/cases.yaml` · `docs/07:391` (사용 조건)

**확인** 케이스 표 전수:

| id | type | verified | sources | drawdown | cluster |
|---|---|---|---|---|---|
| `coal-2013` | **death** | **true** | ✓ | 0.953 | fossil |
| `offshore-drilling-2016` | **death** | **true** | ✓ | 0.990 | fossil |
| `mall-reit-2018` | death | **false** | ✓ | 0.640 | reit |
| `shale-ep-2020` | cycle | true | ✓ | 0.949 | fossil |
| `silver-miners-2015` | cycle | false | ✓ | 0.852 | precious_metals |
| `tankers-2021` | cycle | false | ✓ | 0.539 | shipping |

**4조건(type death · verified · sources ≥ 1 · 낙폭 not null)을 만족하는 것은 2건이고 둘 다
`fossil`** 이다.

**원자료와 달랐던 점** 원자료는 "운영 테마에 매칭 없음" 이라 적었다. **그렇지 않다** — 두
케이스의 `theme_ids` 는 `coal` 과 `offshore_drilling` 이고, 둘 다 `state/themes.yaml` 의 확정
테마이며 **`offshore_drilling` 은 오늘 일간 다이제스트의 상위 8 안에 실제로 들어왔다.**
즉 매칭은 일어날 수 있다. 서지 않는 것은 **나머지 132 테마**다.

**왜 문제인가** `docs/07` 구현노트가 `L_i` 미작동의 이유를 "0개라서다" 로 적었는데 **2개다.**
설명이 stale 이고, 실제 이유(케이스 표가 `fossil` 두 건 외에는 `verified: true` 인 사망 사례를
갖지 않는다)와 다르다.

**무엇을 해야 하는가** `docs/07` 구현노트를 실측으로 갱신한다. 케이스를 늘리는 것은 리서치
작업이지 코드 작업이 아니다.

---

## 4. 반복되는 다섯 양식

**이것이 이 문서의 핵심이다.** 57건을 계층이 아니라 **모양**으로 다시 묶는다.

### ① 계산만 되고 아무도 읽지 않는다

**해당** P4 · 7 · 9 · 11(a) · 16 · 24 · 32 · 39 · 40 · 42 · 43 · 48 · 52 — **13건**

값이 만들어지고, 열이나 필드로 산출물에 나가고, 그 값을 **판정에 쓰는 코드가 없다.**
`unit_demand_series`(#16)가 극단이다 — 필수 출력으로 강제해 놓고 저장조차 하지 않는다.
`BLOCK_WEIGHTS` A·B·D 24칸(#7)은 규모가 가장 크다.

**왜 이 저장소에서 반복되는가 — 관찰.** 이 저장소는 구조를 **문서에서 코드로** 내려 짓는다.
문서가 먼저 있고, 그 문서의 어휘를 필드 이름으로 삼아 스키마를 만들고, 스키마를 채우는 코드를
쓰고, 마지막에 그 값을 읽는 코드를 쓴다. 앞의 세 단계는 결과물이 눈에 보이므로 완료 여부를
알기 쉽고, 네 번째는 **없어도 파이프라인이 돈다.** 게다가 산출물에 필드가 보이므로
"배선됐다" 는 인상을 준다. `journal/2026-08-23-l4-rank-score-unwired.md` 가 같은 관찰을 했다 —
"표시용 산출물이 있어서 **배선된 것처럼 보였다.**" 단정하지는 않겠다: 이것이 설계 순서의
필연인지, 아니면 리뷰가 "이 값을 누가 읽는가" 를 묻지 않아서인지는 이 감사로 갈리지 않는다.

### ② 문서에 선언만 있고 코드에 대응물이 없다

**해당** 1 · 2 · 5 · 6 · 8 · 12 · 14 · 29 · 30(창 길이) · 33 · 39 · 45 · 50 — **13건**

`docs/01` §5 의 관문 6개 중 1개만 강제되고(#12), `docs/08` §6.3 의 `[x]` 에 근거가 없고(#5),
`docs/06` 머리말과 §8.4 가 서로 모순되고(#39), `msa data audit` 의 `[3]` 문구가 M2 이전에
멈춰 있다(#6). 반대 방향도 있다 — 코드가 문서에 없는 칸을 메운다(#14).

**왜 반복되는가 — 관찰.** ①과 짝이다. ①은 코드가 문서를 넘어 만들고, ②는 문서가 코드를 넘어
선언한다. 이 저장소는 문서를 **설계 도구**로 쓴다 — `docs/12`·`docs/13`·`docs/14`·`docs/15`
가 전부 "쓰고 나서 돌린다" 는 규약을 명시한다. 그 규약은 오버피팅을 막는 데 효과가 있었지만
(§5), **문서가 코드보다 먼저 완성된다는 것은 문서에 미구현이 항상 섞여 있다는 뜻**이기도 하다.
그리고 그 사실을 표시하는 관습(`docs/06` §8.4 "아직 없는 것")이 일부 문서에만 있다.

### ③ 판정 불가를 통과로 처리한다

**해당** 4 · 17 · 19 · 26 · 27 · 28 · P2 — **7건**

E2·E3 의 NaN 이 통과(#27), S 축 결측이 최상위(#28), 시총 결측이 0 이라 관문이 통과 쪽으로
틀림(#4), 검증기가 판정을 재도출하지 않아 파일의 자기선언이 통과(#17), `vcp_base` 가 폭락을
베이스로 읽음(P2).

**왜 반복되는가 — 관찰.** 세 가지가 겹쳐 보인다. (a) pandas/numpy 의 기본 동작이 이 방향이다 —
`NaN > 6` 은 `False` 이고, `fillna(False)` 는 통과이며, `mean(skipna=True)` 는 결측을 뺀다.
**언어가 기본으로 관대한 쪽을 고른다.** (b) 이 저장소는 `CLAUDE.md` §2 로 "조용한 절단" 을
금지했는데, 그 규칙은 **데이터를 적게 받는 것**을 겨눈다. 판정을 못 내리는 것은 다른 종류의
사건이고, 그것을 다루는 규칙이 §2 만큼 명확하지 않다. (c) 어제 L3 에서 이 양식 하나를 고쳤을
때(`journal/2026-08-24-l3-gate-not-applicable-fixed.md`) 그 결정은 `docs/04` §2 의 한 줄
("적용 불가를 통과로 취급하지 않는다")을 근거로 삼았다. **그 한 줄이 `docs/06` 에는 없다.**
같은 원칙이 계층마다 다시 선언돼야 하는 구조인지도 모른다.

### ④ 단위·공간이 섞인다

**해당** P1 · 10 · 13 · 26 · 46 · 51 — **6건**

`dv` 가 조정 거래량 × 비조정 종가(P1), E2 가 배수와 비율에 같은 임계(#26), Tier2 가격과
하락률이 서로 다른 규칙(#46), CPI 가 관측 시점과 발표 시점 사이(#10), F 블록이 2지표와 3지표
평균을 같은 횡단면에서(#13), 결측일과 0% 수익률(#51).

**왜 반복되는가 — 관찰.** 이 저장소의 지표는 대부분 **비율**이고, 비율은 단위가 사라진 것처럼
보인다. `net_debt_ebitda` 라는 이름이 붙은 열이 때로는 순부채/시총이라는 사실은 `nd_basis`
열에만 있고 이름에는 없다. `dv` 도 마찬가지다 — 이름이 "달러 거래대금" 이므로 그것이 두 개의
다른 조정 규약에서 온 두 수의 곱이라는 사실은 정의를 읽어야 보인다. **이름이 단위를 숨긴다.**
2026-08-23 에 L4 에서 같은 오류를 고치면서 주석에 "미래를 보는 것" 이라고 적었는데, L1 의
같은 줄까지 가지 않았다(P1) — 한 곳을 고칠 때 같은 이름의 다른 소재를 찾는 습관이 없었다는
쪽으로도 읽을 수 있다.

### ⑤ 실패가 성공(또는 "건너뜀")으로 보고된다

**해당** 5 · 6 · 29 · 34 · 36 · 37 · 38 · 41 · 49 · 53 — **10건**

계약 위반이 `skipped`(#36), 깨진 기준이 "첫 실행"(#37), 일어나지 않은 ETF 대체(#29),
빠진 테마의 무기록(#38), 라벨 부재가 "앵커 0%"(#49), 샌드박스 경로 불일치가 `skipped`(#53),
관찰 목록 미기록(#34), `TFSA` 하나로 영구 exit 1(#6 — 반대 방향: 성공이 실패로).

**왜 반복되는가 — 관찰.** 이 저장소의 보고 단위는 `StepResult(name, status, detail)` 이고
`status` 의 값이 `ok|skipped|failed` 셋이다. **`skipped` 하나가 두 가지 뜻을 겸한다** —
"할 일이 없었다" 와 "할 수 없었다". 파이프라인이 끝까지 도는 것을 우선한 설계
(`_record_from_path:436` — "한 파일 때문에 라운드가 멈추지 않는다")는 합리적이지만, 그
관대함이 보고 어휘의 부족과 만나면 실패가 정상으로 보인다. 그리고 사람이 매일 보는 것은
요약 줄이지 로그가 아니다.

---

### 경계 축 — 같은 57건을 다르게 묶는다

**과잉 (남의 일을 한다)** — #14. L1 이 `docs/04` 의 축1 판정표를 적용하고, 판정표에 없는 칸을
스스로 메웠다. 계층 하나뿐이라는 것은 좋은 소식이다. (#28·#26 도 넓게 보면 L4 가 "모른다" 를
"점수" 로 바꾸는 과잉이지만, 그것은 결측 처리 문제로 ③에 넣었다.)

**책임 누수 (해야 할 일이 아무 계층에도 없다)** — #34(관찰 목록: ingest 가 할 일인데 그
경로가 안 도는 실행이 표준) · #39(L3 → L4: 문서는 L4 가 받는다고 하고 L4 는 받지 않는다) ·
#46(자본 8% 규칙: 계산은 ladders, 표시는 plan, 저장은 positions — 셋이 서로 다른 것을 믿는다) ·
#40(thesis 경로: assemble 이 알고 positions 가 필요한데 아무도 안 넘긴다) ·
#53(thesis 탐색 폴백: research 에는 있고 assemble 에는 없다).

**중복 정의** — #2(유니버스 세 벌) · #23(최소 확신도 두 곳 · 필수 필드 두 곳 · 검증기 두 벌) ·
#14(게이트 판정표 두 문서).

**죽은 표면** — #24(`charge()`·`search()`·`total()`·`attacks`·`calendar`) · #25 · #32 ·
#40 · #42 · #43 · #44.

**경계 위반 import** — #15 하나. `l4/structures.py` 가 `msa.l1.backtest._plain`·`._summarize`
를 가져온다. **계층 간 public import 는 전부 정당하다**(`l4` → `l1.scoreboard.xs_pct` ·
`l1.physical.load_ref` · `l3` → `l1.scan.scan_dirs`) — 아래에서 위로 가는 import 는 없다.

---

### 통합 중 새로 보인 연결 다섯

감사관들은 각자의 계층만 봤다. 여섯을 합치니 **혼자서는 안 보이던 짝**이 나왔다.

**1. 가치함정 방어의 1차선과 2차선이 양쪽 끝에서 동시에 끊겼다.** `docs/02` §7 은 A 블록의
클래스별 차등을 "1차선", `docs/04` 의 하드 게이트를 "2차선" 이라 부른다. 1차선은 S2 가 A·B 를
가중치 없이 쓰기 때문에 죽었고(#7), 2차선은 어제 고쳤지만 **저장된 파일에 적용되지 않는다**
(#17). 두 결함은 다른 계층·다른 감사관에게서 왔고 서로를 모른다.

**2. `dv` 오류가 흘러가는 곳이 하필 가중치가 죽은 곳이다.** `dv`(P1) → `liquidity_decay`(A) ·
`volume_dryup`(B) → `pool = mean(A_pct, B_pct)` → **자격 판정.** A·B 는 S2 에서 가중치를 갖지
않으므로(#7) 클래스별로 이 오염을 덜 실을 방법조차 없다. **단위 혼합(④)과 죽은 가중치(①)가
같은 지점에서 만난다.**

**3. `dv` 를 고쳐도 캐시가 막는다.** #3(지문에 코드 버전 없음)과 P1 은 서로 다른 감사관이
냈는데, 오늘 실행 로그가 둘을 잇는다 — `panel: 캐시 사용 l1_panel_2fe9806ad09c49a3.parquet`.
**따로 고치면 안 고친 것과 같다** (§7-2 가 둘을 묶은 이유).

**4. `home_improvement` 하나에 세 결함이 사슬로 걸린다.** supply 가 축1 의 1순위 시계열을
확보했으나 읽히지 않아(#16) 축이 `not_applicable` 로 닫히고 → 그 결과가 파일에 굳어 어제
고친 §3.5 를 우회하며(#17) → 편입 불가가 되어도 관찰 목록에 남지 않는다(#34).
**§7 의 1·5 번이 같은 사슬의 양 끝이다.**

**5. 선언된 포기가 무음 누락으로 바뀐다.** #48(M 축 미배선)은 `CLAUDE.md` §1 을 지키려는
**의도적** 미구현이고, 코드가 그 이유를 문자열로 들고 있으며, "M̃ 는 notes 에 적혀 있어 사람이
정할 수 있다" 를 대안으로 제시한다. 그런데 그 `notes` 를 L5 의 어느 모듈도 읽지 않는다(#43).
**두 결함이 맞물려, 정직하게 선언된 포기가 사람 앞에서는 그냥 없는 기능이 된다.**

---

## 5. 무엇이 잘 작동하는가

감사가 **"확인함, 문제 없음"** 으로 판정한 것들. 균형을 위해서가 아니라, **이것들이 §4 의
다섯 양식을 피한 사례**라서 적는다.

**bear 격리 — 세 겹, 우회로 없음.** `l3/contracts.py:206` 의 `BearView` 는 타입 자체가 격리
계약이다("L1 스코어·순위·블록·축1 판정이 없다"). `l3/pipeline.py:151` 이 `bear_request(
inputs.bear_view())` 로만 부르고, `MockProvider` 가 모든 요청을 기록해
`tests/test_l3_pipeline.py:98` 이 프롬프트 본문에 금지 토큰이 없음을 검사한다. **타입 · 조립 ·
테스트 세 겹이고, L1 정보를 bear 에게 넣는 우회로가 없다.** 이 저장소에서 가장 잘 지켜진
경계다.

**L5 시간 스탑 — 네 곳에 배선.** `l5/ladders.py`(계산) → `l5/positions.py`(`time_stop_date`
저장) → `ops/check.py`(30일 전 경고 · 경과 판정 · 트리거 0건 조건) → `ops/alerts.py`
(`TIME_STOP_WARNING`) → `ops/journal.py` · `ops/calibration.py`. **계산에서 캘리브레이션까지
끊긴 데가 없다.** `split_first_leg`(#48)와 정확히 대비된다 — 차이는 **컷이 문서에 있었는가**다.

**물타기의 가격 AND 논지 조건.** `ops/check.py:14` 의 규약표대로, 사다리 n단은
가격(초기가 대비 −x%) **AND** 논지(무효화 0건 · 트리거 ≥ 1) 둘 다 만족해야 `ls.both` 가 서고
그때만 `LADDER_STEP_MET` 이 뜬다(`:488-499`). 알림 payload 에 `invalidations_fired`·
`triggers_met`·`triggers_total` 이 함께 실린다 — **판정 근거가 알림에 들어 있다.**

**thesis 스키마 — 거부 규칙과 테스트.** `l3/schema.py` 는 39개의 `R_*` 거부 코드를 갖고,
`required` 목록을 **스펙 파일에서 읽는다**(`:164` — 손으로 베끼지 않는다). `bear_case` 는
bear 원문과 문자 단위로 대조된다(`R_BEAR_CASE_NOT_VERBATIM`). `tests/test_l3_schema.py`
**24건 전부 통과**.
*(원자료는 "R_* 24개 전수 거부" 라고 적었다 — **24 는 테스트 수이지 규칙 수가 아니다.**
규칙은 39개이고 테스트가 직접 이름으로 겨누는 것은 그중 약 22개다. "전수" 는 정확한 서술이
아니다. 그래도 이 저장소에서 가장 조밀한 검증 표면인 것은 맞다.)*

**자동 주문 흔적 0.** `grep -rniE "broker|order_submit|place_order|execute_order" src/msa/` →
**0 건.** `CLAUDE.md` §8("자동 주문 기능은 만들지 않는다")이 실제로 지켜진다. `msa portfolio
--emit-positions` 조차 `state/positions.yaml` 을 건드리지 않고 별도 제안 파일만 쓴다.
알림 문구는 `assert_wording_ok` 가 권유 어휘 목록으로 강제한다(`ops/alerts.py:56-67`).

**L1 PIT 단일 구현.** `datekey ≤ me` 의 asof join 이 `l1/fundamentals.py:163` 한 곳에 있고,
`data/pit.py` 가 그 규약의 정본이다. **L1 안에 PIT 처리가 두 벌 있지 않다.** (그 규약이 데이터
쪽에서 발동하지 못하는 것은 별개 문제 — #1.)

**계층 경계 import.** 아래에서 위로 가는 import(`l1` → `l3`/`l4`/`l5`)가 **0 건**이고, 위에서
아래로 가는 것도 public 이름이다 — `_plain`·`_summarize` 둘만 예외(#15). 계층 순서가 실제로
지켜진다.

**파이프라인이 끝까지 돈다.** 오늘 실측:

```
msa run daily --no-write                        → exit 0
  scan ok 2.0s · select ok · picks ok 11.4s (8/8) · diff ok · check skipped
msa run monthly --no-write --provider none      → exit 0
  scan ok · select ok · research ok · ingest skipped · picks ok (1/1)
  assemble skipped · portfolio skipped · report ok
msa data audit                                  → 완주 (exit 1 은 #6)
```

**S2 구조 채택 절차.** `docs/12` §4 사전 등록 → `msa backtest l1-structures` 실행 →
`docs/backtest-l1.md` §12 판정 → `journal/2026-08-23-l1-structure-s2-adoption.md`.
L4 도 같다 — `docs/14`·`docs/15` 사전 등록 → 실행 → `docs/backtest-l4.md` →
`journal/2026-08-24-l4-selection-retired.md`. **결과를 보고 값을 옮긴 흔적을 감사가 찾지
못했다.** `CLAUDE.md` §1 이 겨눈 실패 유형은 이 감사 범위에서 발견되지 않았다.

---

## 6. 이 감사가 못 본 것

**정직하게 적는다.**

**감사관 둘이 `dv` 에 대해 상반된 결론을 냈고, 데이터 쿼리가 결판냈다.** L1 감사관은
`prices.volume` 이 **원본(비조정)** 이라고 **가정**하고 "`closeunadj × volume` 이 옳다" 고
판정했다. L4 감사관은 2026-08-23 의 `adv20_usd` 수정 이력을 근거로 반대로 판정했다.
NVDA 분할 직전 행을 실제로 조회하고서야(P1 의 표) `volume` 이 소급 분할조정 값임이 확정됐다.
**여섯 감사가 병렬로 돌았기 때문에 이 충돌이 드러났다** — 하나였으면 어느 한쪽 결론이 그대로
남았을 것이다. 반대로, 다른 항목에서 같은 종류의 가정이 검증 없이 남아 있을 수 있다.

**L1 감사는 일부를 추정으로 남겼다.** 워크트리에 스토어가 없어(스토어는 `~/data/` 에 있고
경로가 절대경로다) L1 감사관은 몇 항목을 코드 읽기와 합성 실행으로만 판정했다. 이번 통합에서
`#4`(338 종)·`#13`(7/134)·`#11`(IC CSV)·`#38`(재현)·`#1`·`#5`(스토어 쿼리)는 **실측으로
바꿨다.** 그러나 `#8`(asof 버킷)의 합성 실행과 `#11(a)`(breadth_lead 7개월 동결)은
**감사관의 합성 실행을 그대로 인용했고 이번에 재현하지 않았다** — 코드 논리로는 확인된다.
`P2`(vcp 5/5 True)의 5개 시드도 재실행하지 않았다.

**원자료와 어긋나 정정한 항목 9건.** §3 의 각 항목에 "원자료와 달랐던 점" 으로 적었다 —

| 항목 | 원자료 | 재확인 결과 |
|---|---|---|
| #4 | 생존 보통주 5,866 중 338 종(5.8%) | **5,276 중 63 종(1.2%)** · 관문 값 1.1e-06 |
| #11 | C 9개 중 4개가 IC 0 | **`breadth_lead` 하나만** 세 호라이즌 전부 0 포함 |
| #15 | `_spearman_rows`·`_summarize`·`_plain` 임포트 | **`_plain`·`_summarize` 둘만.** `_spearman_rows` 는 docstring 언급 |
| #22 | `find_prior_thesis` 가 `parent.name < asof` | 맞다 — 단 **`contracts.py` 쪽**이고, `run.py` 의 동명 함수는 `<=` 라 무결함 |
| #37 | 예외를 삼킨다 | `report.notes` 에는 남는다 — **산출물 문구가 반대로 말하는 것**이 결함 |
| #38 | `retail_department` rank **1** | 저장된 2026-08-14 스캔에서 **rank 3**. 현상은 그대로 재현 |
| #46 | 가격과 하락률이 다른 값을 가리킨다 | 맞다 — 단 자본 규칙가가 꼬리에 한 번 더 찍혀 **정보가 숨지지는 않는다** |
| #52 | 운영 테마에 매칭 없음 | **매칭 가능** — `offshore_drilling` 은 오늘 상위 8 안에 있었다 |
| §5 | 스키마 `R_*` **24개** 전수 거부 | **24 는 테스트 수.** 규칙은 39개, "전수" 는 부정확 |

나머지 항목은 원자료와 일치했고, 상당수는 이번에 코드·쿼리·실행으로 **강화**됐다.

**새로 나온 것 1건** — #53(`--no-write` 월간의 assemble thesis 경로). 통합 중 실행으로 발견.

**범위 밖이었던 것.** 성능(쿼리 계획 · 메모리) · 보안(비밀 취급 · 의존성 CVE) · 동시성
(`ThreadPoolExecutor` 의 경합 · 캐시 파일 경합) · 테스트 커버리지의 양적 평가 · 의존성 버전
고정 — **하나도 보지 않았다.**

**수치로 재지 않은 것.** 각 결함이 산출물에 **얼마나** 영향을 주는지는 대부분 재지 않았다.
예: `dv` 오류가 A·B 백분위를 몇 위 흔드는지, F 블록 지표 수 차이(#13)가 어느 방향으로 치우치는지,
E2 가 적자기업 몇 종을 놓치는지. **"틀렸다" 는 말할 수 있고 "얼마나" 는 말할 수 없다.**

**L2 는 감사하지 않았다** — 2026-08-23 에 제거됐다. `docs/archive/` 의 보관물도 보지 않았다.

---

## 7. 수정 우선순위 (제안)

> **결정이 아니라 제안이다.** 무엇을 언제 고칠지는 사람이 정한다.
> 아래 다섯은 전부 **"이미 선언된 것의 복원"** 이라 `CLAUDE.md` §1 위반이 아니다 —
> 새 값을 발명하지 않는다. 값을 새로 정해야 하는 것은 그렇다고 표시했다.

### 1. 저장된 thesis 를 코드로 재도출해 대조하는 검사 (#17)

**왜 첫째인가.** 이 하나가 ①②③ 을 **광범위하게 잡는다.** `apply_gates()` 와
`cycle_confidence()` 를 저장된 `axis_verdicts`·L1 입력으로 다시 돌려 파일의 값과 비교하면,
#17(파일의 자기선언) · #P3(손기재 thesis) · #19(축2 단독 편입) · #18(무음 축) 이 전부 **한
검사에 걸린다.** 그리고 앞으로 게이트를 고칠 때마다 저장된 산출물이 자동으로 재검사된다 —
어제 고친 §3.5 가 오늘 실행에서 발동하지 않은 일(#17)이 반복되지 않는다.

**§1 위반이 아닌 이유.** 새 임계도 새 계수도 만들지 않는다. **이미 있는 두 함수를 한 번 더
부르고 결과를 비교하는 것**이다. 불일치 시 거부할지 경고할지는 판단이 필요하지만, 그것은
가중치가 아니다.

### 2. `dv` 단위 혼합 + 캐시 지문에 코드 버전 (#P1 · #3)

**왜 둘을 묶는가.** **따로 고치면 안 고친 것과 같다.** `dv` 만 고치면 오늘 실행처럼 옛 캐시를
읽고(`panel: 캐시 사용 …`), 지문만 고치면 틀린 값을 다시 계산한다. 그리고 `dv` 가 흘러드는
곳이 순위가 아니라 **자격 게이트**(A·B → pool)라서 영향이 크다 — 순위는 틀려도 후보 목록은
남지만, 자격은 후보 목록 자체를 바꾼다.

**§1 위반이 아닌 이유.** `close * volume` 은 2026-08-23 에 L4 에서 이미 내려진 판단이고
(`features.py:584` 의 주석이 근거를 적는다), 그것을 같은 이름의 다른 소재에 적용하는 것이다.
지문에 소스 해시를 넣는 것은 값이 아니다.

### 3. L4 E2·E3 결측 처리 (#27)

**왜 셋째인가.** **어제 L3 에서 고친 것과 정확히 같은 것**이다
(`journal/2026-08-24-l3-gate-not-applicable-fixed.md`). 근거 문장이 이미
`axes.hard_filters` 의 docstring 에 있다 — "평가할 수 없는 종목을 통과시키면 필터가 있는 척하는
것이다." E1 은 이미 E4 라는 결측 짝을 갖고 있으므로 **형태도 이미 저장소 안에 있다.**
그리고 2026-08-24 결정 이후 L4 가 하는 일이 사실상 하드 제외뿐이므로, 이 셋이 L4 의 전부다.

**§1 위반이 아닌 이유.** 임계(4분기 · 6× · 0.5)를 한 자리도 옮기지 않는다. **판정 불가를
통과로 세지 않게 하는 것**이고, 그 원칙은 같은 파일에 이미 적혀 있다.

### 4. `vcp_base` 에 `from_52w_high` 조건 (#P2 · #32)

**왜 넷째인가.** 이미 계산된 열 하나로 막힌다. `from_52w_high` 는 `features.py:601` 에서
매번 계산되고 아무도 읽지 않는다(#32). 폭락을 베이스로 읽는 경로(P2)는 M 축의 6구성요소 중
하나를 반대 방향으로 만든다.

**⚠️ 값을 새로 정해야 한다.** "고점 대비 몇 % 이내여야 베이스인가" 의 임계가 **문서에 없다.**
`stage2` 는 `from_high >= -0.25` 를 쓰지만(`features.py:604`) 그것은 다른 조건의 값이고,
가져다 쓰는 것은 근거 없는 이식이다. **따라서 이 항목은 `docs/12`·`docs/14` 꼴의 별도 사전
등록이 필요하다** — 임계를 데이터를 보기 전에 적고, 합격 기준을 고정하고, 시도 수를 정산한다.
사전 등록 없이 할 수 있는 것은 #30 의 창 길이 불일치(문서 252일 vs 코드 60봉/430일)를 맞추는
것뿐이다.

### 5. 관찰 목록 배선 (#34)

**왜 다섯째인가.** 기본 실행(`--provider none`)에서 **매달 나오는 산출물 하나가 통째로
비어 있다.** 오늘 7개 테마가 "관찰" 로 분류됐고 파일은 만들어지지 않았다. 그리고 이것은
#16 과 같은 테마의 반대쪽 끝이다 — `home_improvement` 은 축1 의 1순위 입력을 손에 쥐고도
축이 닫혔고, 그래서 관찰로 갔고, 관찰 목록에 남지 않았다.

**§1 위반이 아닌 이유.** `WatchItem` 타입과 `save_watchlist` 함수와 `docs/09` §5 의 규약이
전부 이미 있다. **부르지 않는 함수를 부르는 것**이다.

### 그 다음 (묶어서)

- **표시·문구만 고치면 되는 것 (값 결정 없음)** — #29(ETF 대체 문구) · #37(첫 실행 vs 비교
  불가) · #41(텔레그램 꼬리) · #45(`l2_tailwind` 잔재) · #49(앵커 0% 라벨) · #33(README) ·
  #52(`docs/07` 구현노트 stale) · #6 의 `[3]` 문구.
- **한 줄~몇 줄 배선 (값 결정 없음)** — #42(`_OBS_KEYS` 에 `"check"`) · #43(`plan.md` 에
  notes) · #40(thesis 경로 전달) · #44(CLI 등록) · #53(assemble 실-루트 폴백) ·
  #21(미래 날짜를 오류로) · #18(축4·5 note) · #32(`m_inputs_missing`).
- **사전 등록이 필요한 것** — #7(A·B·D 가중치 구조) · #13(F 블록 지표 수 보정) ·
  #26(시총 기준 E2 임계) · #28(S 축 결측 대입) · #30(수축 최신성·dry-up 임계) ·
  #31(ATR·지지 지표) · #50(클러스터링·ENB 목표) · P2 의 임계.
- **재적재가 필요한 것** — #1(PIT 빈티지). §8 참조.

---

## 8. 열린 질문

지금 답할 수 없는 것들. **답을 추측해 적지 않는다.**

**1. PIT 빈티지 부재는 재적재 없이 고칠 수 없다.** Sharadar 벌크 `SF1` 에는 정정 이력이 없고,
빈티지를 얻으려면 벤더의 다른 산출물이거나 시점별 스냅샷 적재가 필요하다. 그때까지
`docs/08` §4 와 `CLAUDE.md` PIT 규약의 "최초 보고분" 조항은 **선언으로만 존재한다.**
질문은 둘이다 — (a) 그 사실을 어디에 어떻게 적어 읽는 사람이 착각하지 않게 할 것인가,
(b) 빈티지 없이 백테스트한 IC 를 어떻게 해석할 것인가(`docs/10` §2 는 이 경우를 다루지 않는다).

**2. 축 1 을 되살리려면 `unit_demand_series` 를 L1 판정과 어떻게 화해시킬 것인가.**
현재 축1 판정은 L1 의 FRED `physical_ref` 경로 하나에서만 나온다(134 중 7). L3 의 supply 는
같은 축의 1순위 입력을 **웹에서** 가져온다(#16 — `home_improvement` 이 실제 사례다). 둘이
충돌하면 어느 쪽이 이기는가? 둘 다 있으면 대조하는가? L3 쪽이 이기면 **게이트를 쥐는 것이
LLM 이 된다** — `docs/04` §2 각주가 경계한 바로 그 상태이고, 그 각주는 축3 에 대해서만
쓰였다. **이것은 `docs/04` 의 개정이지 배선이 아니다.**

**3. M 축을 되살리려면 문서에 컷이 필요하고, 그것은 새 선언이다.** `docs/07` §3 은 "M 축이
낮으면 1단을 25%+25% 로 나눈다" 고 적으면서 **"낮다" 의 값을 주지 않는다.** 코드는 그래서
만들지 않았다(#48 — `assemble.py:124` 가 이유를 문자열로 들고 있다). 컷을 정하려면 그것이
어디서 오는지를 먼저 답해야 한다 — 도메인 근거인가, 아니면 데이터를 본 결과인가. 후자면
`CLAUDE.md` §1 이 정면으로 걸린다.

**4. `not_applicable` 의 원인 셋을 게이트가 구분해야 하는가.**
`journal/2026-08-24-value-trap-axes-commodity-bias.md` 가 이미 이 질문을 열어 두었고,
이번 감사가 그것을 **강화했다** — #16 이 네 번째 원인을 추가한다: **자료를 확보했는데 코드가
읽지 않아서.** 개념 부재(소매업에 원가곡선이 없다) · 데이터 결측(FRED 키 없음) · 자료
미확보(1차 출처 대조 실패) · **배선 부재**. 넷은 성격이 다르고, 넷째는 고치면 사라진다.
게이트가 이것들을 구분해야 하는지는 여전히 미정이다.

**5. `skipped` 하나로 두 가지를 말할 수 있는가.** §4-⑤ 의 뿌리다. `StepResult.status` 에
값을 하나 더 만들 것인지(예: `blocked`), 아니면 `skipped` 의 detail 문구 규약을 정할 것인지.
전자는 리포트 렌더러·테스트·저널 형식에 파급된다.

**6. `maturity_wall_24m` 을 실제로 걸려면 어디서 만기 스케줄을 가져오는가** (2026-08-24 추가 —
#27 조치의 잔여 질문). E7 철회로 **아무도 자르지 않는다**는 답은 났지만, 13~24개월 만기벽을
보는 필터는 여전히 **선언만 있고 구현이 없다** (`docs/06` §8.4). 질문은 둘이다 — (a) SF1
밖에서 만기 스케줄을 주는 소스가 있는가(새 데이터 계약이다), (b) 은행·보험·REIT 처럼
`debtc` 를 보고하지 않는 업종에는 만기벽에 **해당하는 개념 자체가 다른가.** 후자면 업종별
면제 목록이 아니라 **업종별로 다른 지표**가 답이고, 그것은 `docs/06` §2 의 개정이다.
`docs/06` §8.4.1 #4 가 이 질문의 정본이다.

**7. 이 감사가 재지 못한 "얼마나".** §6 에 적은 대로 각 결함의 크기를 재지 않았다. 특히
`dv`(P1) 수정 전후로 자격 테마 집합이 실제로 얼마나 바뀌는지는 **고치기 전에 재 두는 것이
낫다** — 고친 뒤에는 비교 대상이 사라진다. 그러나 그 측정을 어떻게 사전 등록 규약과
양립시킬지(측정이 곧 "결과를 보는 것" 인가)는 정해져 있지 않다.

---

## 9. 개정 이력

| 날짜 | 무엇 |
|---|---|
| 2026-08-24 | 최초 작성. 6개 워크트리 병렬 감사(L0·L1·L3·L4·L5·배선)의 통합. 결함 57건(심각 2 · 높음 8 · 중간 37 · 낮음 10). **코드 0줄 수정.** |
| 2026-08-24 | §3-#27 에 **조치**를 덧붙였다 (원 발견은 그대로). E6 은 신설·유지, **E7 은 신설했다가 철회** — 선언된 필터(`maturity_wall_24m`)가 이 스토어에서 계산되지 않으므로 대용치의 부재로 자르면 선언되지 않은 강제가 된다. 대신 **미적용 계수**로 보고한다. §8 에 열린 질문 6(만기 스케줄 소스)을 추가하고 기존 6 을 7 로 밀었다. 근거·실측은 `docs/06` §2.1.1 |
