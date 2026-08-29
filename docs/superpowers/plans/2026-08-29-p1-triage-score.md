# P1 트리아지 점수 + P1b 증거 처리 대장 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `msa run daily` 가 매일 내는 명단에 **구획 + 트리아지 점수**를 붙여, 사람이 어느 차트를 어느 순서로 열지 정할 수 있게 한다.

**Architecture:** 새 순수 모듈 `src/msa/triage.py` 하나가 `digest.json` 모양의 dict 를 받아 종목별 (구획 · J · C · R · triage) 을 낸다. 스토어도 네트워크도 모르고 LLM 도 부르지 않는다 — 전부 합성 dict 로 테스트된다. 파이프라인은 이미 만들어진 digest 에 `triage` 블록을 덧붙이고 `triage.csv` 를 쓰는 것뿐이다. 렌더링(digest.md · README 블록)은 그 블록을 읽어 구획별로 정렬한다.

**Tech Stack:** Python 3.12 · pandas (기존) · pytest · ruff · mypy · uv

**Spec:** `docs/superpowers/specs/2026-08-29-hedge-fund-evolution-design.md`

## Global Constraints

이 절의 값은 **스펙에서 그대로 옮긴 것**이다. 모든 태스크의 요구사항에 암묵적으로 포함된다.

- **가중치는 선언값이고 고정이다** — `TRIAGE_WEIGHTS = {"J": 0.50, "C": 0.30, "R": 0.20}`. 테스트 결과·실데이터를 보고 옮기지 않는다 (`CLAUDE.md` §1).
- **시장 데이터 위에 새 임계를 긋지 않는다.** 낙폭 기준선은 기존 `msa.ops.readme_block.PULLBACK_MARK = -0.15` 를 **import 해서** 쓴다. 복사하지 않는다. (점수를 만드는 선언 상수 여섯은 이 모듈이 새로 만들며, 전부 `msa.basis` 레지스트리에 `NoBasis` 로 등록한다 — 실행 중 발견해 Task 8 에서 닫았다.)
- **`s_pct` · `t_pct` · `m_pct` · `composite` · `rank` · `rs_rating` · `from_52w_low` 는 점수 입력이 아니다.** 참고 열로만 싣는다. 넣으면 이 점수가 조용히 수익률 주장이 된다 (스펙 §5.2 · §5.3).
- **`vcp_base` 를 쓰지 않는다** — `docs/backtest-l4.md` §14 에 "폭락 중에도 True 를 낸다" 는 결함이 문서화돼 있다.
- **결측은 0 이 아니다** (`CLAUDE.md` §2 조용한 절단 금지). 계산 불가는 `None` 으로 두고 그 사실을 산출물에 적는다.
- **`AXIS_WEIGHTS` · `S_WEIGHTS` · 하드 제외 임계 · `PULLBACK_MARK` 값을 건드리지 않는다.**
- **리포트 고정 문장** (스펙 §8.1, 토씨까지 그대로):
  > **triage 는 읽는 순서다. 수익률 순서가 아니다.** 이 점수는 초과수익을 주장하지 않으며 그렇게 검정된 적도 없다. 높은 triage 는 "먼저 차트를 열어라" 이지 "먼저 사라" 가 아니다.
- 명령은 전부 `uv run` 으로 돈다. `pip install` 금지.
- 커밋 신원은 레포 설정(`chyohw97@gmail.com`)을 그대로 쓴다. `git -c user.email=` 로 덮어쓰지 않는다.
- `journal/` 은 append-only — 기존 파일을 고치지 않는다 (`CLAUDE.md` §6).

## 파일 구조

| 파일 | 책임 |
|---|---|
| `src/msa/triage.py` (신규) | **순수 함수 전부.** 선언 상수 · J · C · R · 구획 · 합성. digest 모양 dict in → `TriageRow` 리스트 out. 스토어·네트워크 모름 |
| `src/msa/ops/resolutions.py` (신규, Task 7) | 증거 처리 대장 읽기/쓰기 (append-only). `state/evidence_resolutions/<theme>.yaml` |
| `src/msa/pipeline/daily.py` (수정) | digest 에 `triage` 블록 덧붙이기 · `triage.csv` 쓰기 · `render_digest_md` 에 구획 절 추가 |
| `src/msa/ops/readme_block.py` (수정) | 종목 표를 구획별·triage 내림차순으로 |
| `src/msa/l4/features.py` (수정, Task 3) | `from_52w_high` 의 "관찰용 열" 주석을 승격 사실로 고침 |
| `tests/test_triage.py` (신규) | 축 수학·구획·결측 — 합성 dict |
| `tests/test_triage_golden.py` (신규) | 2026-08-29 고정 입력 골든 |
| `tests/fixtures/triage/digest-2026-08-29.json` (신규) | 골든 입력 (실데이터에서 축약) |
| `tests/test_ops_resolutions.py` (신규, Task 7) | 대장 append-only · J 상한 연동 |

---

### Task 1: `triage.py` 골격 — 선언 상수와 J 축

**Files:**
- Create: `src/msa/triage.py`
- Test: `tests/test_triage.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `TRIAGE_WEIGHTS: dict[str, float]`, `EVIDENCE_CAP: float`, `EVIDENCE_CAP_REFUTED: float`
  - `judgment_state(judged: Mapping[str, Any]) -> float`
  - `evidence_quality(audit: Mapping[str, Any]) -> float`
  - `theme_trust(judged: Mapping[str, Any] | None, audit: Mapping[str, Any] | None) -> float | None` — `None` 은 "판별은 됐는데 실사가 없다 → 계산 불가"

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_triage.py` 를 새로 만든다.

```python
"""트리아지 점수 — 합성 dict, 스토어 없음.

`docs/superpowers/specs/2026-08-29-hedge-fund-evolution-design.md` §4~§6.
"""

from __future__ import annotations

import pytest

from msa import triage


def _judged(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "theme": "t",
        "portfolio_eligible": True,
        "trusted": True,
        "gate": "passed",
        "cycle_confidence": 0.75,
    }
    d.update(kw)
    return d


def _audit(verified: int = 11, checked: int = 23, **kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "counts": {"verified": verified},
        "checked": checked,
        "unverified_axes": [],
    }
    d.update(kw)
    return d


def test_weights_are_declared_and_sum_to_one() -> None:
    assert triage.TRIAGE_WEIGHTS == {"J": 0.50, "C": 0.30, "R": 0.20}
    assert abs(sum(triage.TRIAGE_WEIGHTS.values()) - 1.0) < 1e-9


def test_judgment_state_precedence_untrusted_beats_eligible() -> None:
    """`trusted: false` 가 먼저다 — 편입 가능이어도 0.30 (스펙 §5.1.1 표의 1번 줄)."""
    assert triage.judgment_state(_judged(portfolio_eligible=True, trusted=False)) == 0.30


def test_judgment_state_ladder() -> None:
    assert triage.judgment_state(_judged(portfolio_eligible=True)) == 1.00
    assert triage.judgment_state(_judged(portfolio_eligible=False)) == 0.50
    assert triage.judgment_state(_judged(portfolio_eligible=False, gate="blocked")) == 0.30


def test_evidence_quality_counts_unreachable_in_denominator() -> None:
    """'못 읽었다' 는 '맞다' 가 아니다 — 분모에 남는다."""
    assert triage.evidence_quality(_audit(verified=11, checked=23)) == pytest.approx(11 / 23)


def test_theme_trust_is_half_state_half_evidence() -> None:
    assert triage.theme_trust(_judged(), _audit(11, 23)) == pytest.approx(0.5 + 0.5 * 11 / 23)


def test_theme_trust_capped_when_unverified_axes_present() -> None:
    """판정을 만든 축의 증거가 검증 안 됐으면 그 판정을 절반만 믿는다 (스펙 §5.1.3)."""
    got = triage.theme_trust(_judged(), _audit(22, 23, unverified_axes=["unit_demand"]))
    assert got == triage.EVIDENCE_CAP == 0.50


def test_theme_trust_zero_when_no_thesis() -> None:
    assert triage.theme_trust(None, None) == 0.0


def test_theme_trust_none_when_judged_but_no_audit() -> None:
    """결측을 0.5 로 채우지 않는다 — 계산 불가는 None (`CLAUDE.md` §2)."""
    assert triage.theme_trust(_judged(), None) is None


def test_theme_trust_rejects_zero_checked() -> None:
    with pytest.raises(ZeroDivisionError):
        triage.evidence_quality(_audit(0, 0))
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run pytest tests/test_triage.py -v
```

기대: `ModuleNotFoundError: No module named 'msa.triage'` 로 수집 단계에서 전부 실패.

- [ ] **Step 3: 최소 구현**

`src/msa/triage.py` 를 새로 만든다.

```python
"""트리아지 점수 — **읽는 순서**이지 수익률 순서가 아니다.

설계는 `docs/superpowers/specs/2026-08-29-hedge-fund-evolution-design.md`.

## 이 점수가 주장하는 것과 하지 않는 것

L4 의 선정 규칙은 2026-08-24 에 은퇴했다 — `docs/15` 검정에서 B0·B1·B2 셋 다 B3(하드 제외
통과 전부 동일가중)를 이기지 못했기 때문이다. **이 모듈은 그 규칙을 되살리지 않는다.**
종합 점수가 묻던 "무엇이 더 오를 것인가" 대신 **"다음 10분을 어느 차트에 쓸 것인가"** 를
묻는다. 수익률을 주장하지 않으므로 `docs/15` 관문의 대상이 아니고, 그 대가로 **검정될 수도
없다** (스펙 §8.3).

그래서 `s_pct`·`t_pct`·`m_pct`·`composite`·`rank`·`rs_rating`·`from_52w_low` 는 **점수 입력이
아니다.** 넣는 순간 이 점수는 조용히 수익률 주장이 된다. 참고 열로만 싣는다.

## 선언값 (`CLAUDE.md` §1 — 데이터에 맞춰 바꾸지 않는다)

`TRIAGE_WEIGHTS`(0.50/0.30/0.20)는 이 저장소가 자기 깔때기의 순서로 이미 선언해 둔 우선순위를
옮긴 것이다: 테마 판별(J) > 재무 판정(C) > 차트(R). R 이 가장 작은 이유는 2026-08-24 에
**차트는 사람이 본다** 고 역할이 못박혔기 때문이다.

**새 수치 상수는 하나도 만들지 않았다.** 낙폭 기준선은 `ops.readme_block.PULLBACK_MARK` 를
import 해서 쓰고(복사하지 않는다), 낙폭 순서는 백분위라 눈금이 없다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: 축 가중치 — 선언값. 결과를 보고 옮기지 않는다 (`CLAUDE.md` §1 · 스펙 §4.2).
TRIAGE_WEIGHTS = {"J": 0.50, "C": 0.30, "R": 0.20}

#: 판정을 만든 축의 증거가 원문 대조를 통과하지 못했을 때 J 의 상한 (스펙 §5.1.3).
EVIDENCE_CAP = 0.50

#: 증거 처리 대장에서 `refuted` 가 나온 테마의 J 상한 (스펙 §7). Task 7 에서 쓰인다.
EVIDENCE_CAP_REFUTED = 0.25

assert abs(sum(TRIAGE_WEIGHTS.values()) - 1.0) < 1e-9


def judgment_state(judged: Mapping[str, Any]) -> float:
    """판별 상태 — **위에서부터 먼저 맞는 줄 하나**만 적용한다 (스펙 §5.1.1).

    순서가 규칙의 일부다: 한 테마가 여러 줄에 해당할 수 있고, `trusted: false` 는
    편입 가능이어도 먼저 걸린다.
    """
    if not judged.get("trusted"):
        return 0.30
    if judged.get("portfolio_eligible"):
        return 1.00
    if judged.get("gate") == "passed":
        return 0.50
    return 0.30


def evidence_quality(audit: Mapping[str, Any]) -> float:
    """`verified / checked`.

    `unreachable`·`unsupported` 는 **분모에 남는다** — "못 읽었다" 는 "맞다" 가 아니다
    (`l3.evidence_audit` 모듈 독스트링).
    """
    counts = audit.get("counts") or {}
    checked = int(audit["checked"])
    return int(counts.get("verified", 0)) / checked


def theme_trust(
    judged: Mapping[str, Any] | None,
    audit: Mapping[str, Any] | None,
) -> float | None:
    """J 축의 테마 성분.

    - 판별이 없으면 **0.0**. 증거품질 항은 아예 없다 — 평균 내지 않는다.
    - 판별은 있는데 실사가 없으면 **None**(계산 불가). 0.5 로 채우지 않는다
      (`CLAUDE.md` §2 조용한 절단 금지).
    """
    if judged is None:
        return 0.0
    if audit is None:
        return None
    value = 0.5 * judgment_state(judged) + 0.5 * evidence_quality(audit)
    if audit.get("unverified_axes"):
        return min(value, EVIDENCE_CAP)
    return value
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run pytest tests/test_triage.py -v
```

기대: 9 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/msa/triage.py tests/test_triage.py
git commit -m "트리아지 J 축 — 판별 상태와 증거 품질, 결측은 0 이 아니라 None"
```

---

### Task 2: C 축 — 재무 판정 명료도

**Files:**
- Modify: `src/msa/triage.py`
- Test: `tests/test_triage.py`

**Interfaces:**
- Consumes: Task 1 의 `TRIAGE_WEIGHTS`
- Produces:
  - `UNJUDGED_PENALTY = 0.50`, `RED_FLAG_PENALTY = 0.15`, `RED_FLAG_MAX = 2`, `PARTIAL_PENALTY = 0.10`
  - `clarity(pick: Mapping[str, Any]) -> float`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_triage.py` 끝에 덧붙인다.

```python
def _pick(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "ticker": "AAA",
        "survival_unjudged": None,
        "red_flags": "",
        "s_partial": False,
        "composite_partial": False,
        "from_52w_high": -0.30,
        "stage2": False,
        "above_50d": False,
    }
    d.update(kw)
    return d


def test_clarity_clean_pick_is_one() -> None:
    assert triage.clarity(_pick()) == 1.0


def test_clarity_unjudged_survival_costs_half() -> None:
    """하드필터를 '통과한 것' 과 '판정 불가라 통과 취급된 것' 은 다르다."""
    assert triage.clarity(_pick(survival_unjudged="재무 없음")) == pytest.approx(0.50)


def test_clarity_red_flags_capped_at_two() -> None:
    one = triage.clarity(_pick(red_flags="consecutive_operating_loss"))
    two = triage.clarity(_pick(red_flags="a,b"))
    three = triage.clarity(_pick(red_flags="a,b,c"))
    assert one == pytest.approx(0.85)
    assert two == pytest.approx(0.70)
    assert three == pytest.approx(0.70), "3건이 2건보다 두 배 나쁘다고 말할 근거가 없다"


def test_clarity_partial_inputs_small_penalty() -> None:
    assert triage.clarity(_pick(s_partial=True)) == pytest.approx(0.90)
    assert triage.clarity(_pick(composite_partial=True)) == pytest.approx(0.90)
    assert triage.clarity(_pick(s_partial=True, composite_partial=True)) == pytest.approx(
        0.90
    ), "둘 다 참이어도 한 번만 깎는다 — 같은 사실의 두 표시다"


def test_clarity_clipped_at_zero() -> None:
    got = triage.clarity(
        _pick(survival_unjudged="x", red_flags="a,b,c", s_partial=True)
    )
    assert got == pytest.approx(0.0)


def test_clarity_ignores_return_predictive_axes() -> None:
    """S 축은 rank-IC 가 양수로 측정된 축이다 — 넣으면 수익률 주장이 된다 (스펙 §5.2)."""
    low = triage.clarity(_pick(s_pct=0.01, composite=0.01))
    high = triage.clarity(_pick(s_pct=0.99, composite=0.99))
    assert low == high == 1.0
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run pytest tests/test_triage.py -k clarity -v
```

기대: `AttributeError: module 'msa.triage' has no attribute 'clarity'` 로 6개 실패.

- [ ] **Step 3: 최소 구현**

`src/msa/triage.py` 의 `EVIDENCE_CAP_REFUTED` 선언 바로 아래에 상수를 넣는다.

```python
#: C 축 감점 — 전부 선언값이다 (스펙 §5.2).
#: 미판정이 가장 큰 이유: 사람이 재무제표를 직접 열어야 한다 — 가장 비싼 노동이다.
UNJUDGED_PENALTY = 0.50
RED_FLAG_PENALTY = 0.15
#: 레드플래그 감점의 상한 건수. 3건이 2건보다 두 배 나쁘다고 말할 근거가 없다.
RED_FLAG_MAX = 2
#: 입력 결측. 작은 감점 — 결측은 나쁨이 아니라 **모름**이다.
PARTIAL_PENALTY = 0.10
```

그리고 `theme_trust` 아래에 함수를 덧붙인다.

```python
def _red_flag_count(pick: Mapping[str, Any]) -> int:
    raw = pick.get("red_flags") or ""
    return len([x for x in str(raw).split(",") if x.strip()])


def clarity(pick: Mapping[str, Any]) -> float:
    """C 축 — **차트를 열기 전에 재무를 다시 확인해야 하는가.**

    `s_pct` 를 쓰지 않는다: S 는 `docs/backtest-l4.md` §Q2 에서 rank-IC 가 양수로 측정된
    축이고, 그것을 읽는 순서에 넣으면 이 점수가 조용히 수익률 주장이 된다 (스펙 §5.2).
    """
    value = 1.0
    if pick.get("survival_unjudged") is not None:
        value -= UNJUDGED_PENALTY
    value -= RED_FLAG_PENALTY * min(_red_flag_count(pick), RED_FLAG_MAX)
    if pick.get("s_partial") or pick.get("composite_partial"):
        value -= PARTIAL_PENALTY
    return max(value, 0.0)
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run pytest tests/test_triage.py -v
```

기대: 15 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/msa/triage.py tests/test_triage.py
git commit -m "트리아지 C 축 — 미판정·레드플래그·결측. S 축은 넣지 않는다"
```

---

### Task 3: R 축과 구획 — 그리고 `from_52w_high` 의 승격

**Files:**
- Modify: `src/msa/triage.py`
- Modify: `src/msa/l4/features.py:65-68`
- Test: `tests/test_triage.py`

**Interfaces:**
- Consumes: Task 2 의 `clarity`
- Produces:
  - `R_WEIGHTS = {"drawdown": 0.7, "base": 0.3}`
  - `PARTITION_IA/IB/II/III: str` (값은 `"I-A"` · `"I-B"` · `"II"` · `"III"`)
  - `partition(judged: Mapping[str, Any] | None, pick: Mapping[str, Any]) -> str`
  - `readiness(pick: Mapping[str, Any], peer_drawdowns: Sequence[float]) -> float`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_triage.py` 끝에 덧붙인다.

```python
def test_partition_splits_eligible_by_pullback_mark() -> None:
    from msa.ops.readme_block import PULLBACK_MARK

    ok = _judged()
    assert triage.partition(ok, _pick(from_52w_high=PULLBACK_MARK)) == triage.PARTITION_IA
    assert triage.partition(ok, _pick(from_52w_high=-0.44)) == triage.PARTITION_IA
    assert triage.partition(ok, _pick(from_52w_high=-0.14)) == triage.PARTITION_IB


def test_partition_untrusted_theme_is_two_not_one() -> None:
    got = triage.partition(_judged(trusted=False), _pick(from_52w_high=-0.44))
    assert got == triage.PARTITION_II


def test_partition_unjudged_theme_is_three() -> None:
    assert triage.partition(None, _pick(from_52w_high=-0.90)) == triage.PARTITION_III


def test_partition_missing_drawdown_is_ib_not_ia() -> None:
    """낙폭을 모르면 '지금 자리' 라고 말하지 않는다 (`CLAUDE.md` §2)."""
    assert triage.partition(_judged(), _pick(from_52w_high=None)) == triage.PARTITION_IB


def test_readiness_drawdown_percentile_within_peers() -> None:
    peers = [0.182, 0.218, 0.448]
    deepest = triage.readiness(_pick(from_52w_high=-0.448), peers)
    middle = triage.readiness(_pick(from_52w_high=-0.218), peers)
    shallow = triage.readiness(_pick(from_52w_high=-0.182), peers)
    assert deepest == pytest.approx(0.7 * 1.0)
    assert middle == pytest.approx(0.7 * 0.5)
    assert shallow == pytest.approx(0.0)


def test_readiness_base_component_from_stage2_and_above_50d() -> None:
    peers = [0.30]
    both = triage.readiness(_pick(from_52w_high=-0.30, stage2=True, above_50d=True), peers)
    one = triage.readiness(_pick(from_52w_high=-0.30, stage2=True), peers)
    assert both == pytest.approx(0.7 * 1.0 + 0.3 * 1.0)
    assert one == pytest.approx(0.7 * 1.0 + 0.3 * 0.5)


def test_readiness_ignores_vcp_base() -> None:
    """`vcp_base` 는 폭락 중에도 True 를 낸다 — 결함이 문서화된 입력이다 (docs/backtest-l4 §14)."""
    peers = [0.30]
    with_vcp = triage.readiness(_pick(from_52w_high=-0.30, vcp_base=True), peers)
    without = triage.readiness(_pick(from_52w_high=-0.30, vcp_base=False), peers)
    assert with_vcp == without


def test_readiness_shallow_theme_does_not_outrank_deep_one() -> None:
    """2026-08-29 회귀 — 백분위를 테마 안에서 재면 -3.7% 인 ESEA 가 -44.8% 인 ALHC 를 이겼다.

    구획 안에서 재면 그 일이 안 일어난다 (스펙 §5.3).
    """
    peers = [0.037, 0.448]
    esea = triage.readiness(_pick(from_52w_high=-0.037), peers)
    alhc = triage.readiness(_pick(from_52w_high=-0.448), peers)
    assert alhc > esea


def test_readiness_single_member_partition_is_top() -> None:
    assert triage.readiness(_pick(from_52w_high=-0.30), [0.30]) == pytest.approx(0.7)
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run pytest tests/test_triage.py -k "partition or readiness" -v
```

기대: `AttributeError: module 'msa.triage' has no attribute 'partition'` 로 9개 실패.

- [ ] **Step 3: 최소 구현**

`src/msa/triage.py` 의 import 절에 `Sequence` 와 `PULLBACK_MARK` 를 더한다.

```python
from collections.abc import Mapping, Sequence

from msa.ops.readme_block import PULLBACK_MARK
```

`PARTIAL_PENALTY` 아래에 상수를 넣는다.

```python
#: R 축 안의 배분 — 선언값. 낙폭이 기저보다 큰 이유: 기저 판정(`stage2`·`above_50d`)은
#: 불리언 둘이라 해상도가 낮고, 낙폭은 연속이라 순서를 실제로 만든다.
R_WEIGHTS = {"drawdown": 0.7, "base": 0.3}

#: 구획 — **점수보다 먼저 온다.** triage 값은 같은 구획 안에서만 비교 가능하다 (스펙 §6).
PARTITION_IA = "I-A"
PARTITION_IB = "I-B"
PARTITION_II = "II"
PARTITION_III = "III"

#: 표시 순서. 구획 간 정렬은 하지 않는다 — 이 순서가 곧 읽는 순서다.
PARTITION_ORDER = (PARTITION_IA, PARTITION_IB, PARTITION_II, PARTITION_III)

assert abs(sum(R_WEIGHTS.values()) - 1.0) < 1e-9
```

`clarity` 아래에 함수 셋을 덧붙인다.

```python
def _drawdown(pick: Mapping[str, Any]) -> float | None:
    """양수로 뒤집은 52주 고점 대비 낙폭. 모르면 None."""
    raw = pick.get("from_52w_high")
    if raw is None:
        return None
    return -float(raw)


def partition(judged: Mapping[str, Any] | None, pick: Mapping[str, Any]) -> str:
    """구획 — 판별을 통과한 테마만 I 이고, 그 안에서 낙폭이 I-A/I-B 를 가른다.

    `III` 이 `I` 위로 올라오는 일은 점수가 아니라 **이 함수로** 막힌다. 가중치를 잘못
    골라도 그 성질은 안 깨진다 (`docs/18` §1).
    """
    if judged is None:
        return PARTITION_III
    if not (judged.get("portfolio_eligible") and judged.get("trusted")):
        return PARTITION_II
    dd = _drawdown(pick)
    if dd is None:
        # 낙폭을 모르면 "지금 자리" 라고 말하지 않는다 (`CLAUDE.md` §2).
        return PARTITION_IB
    return PARTITION_IA if -dd <= PULLBACK_MARK else PARTITION_IB


def _percentile(x: float, peers: Sequence[float]) -> float:
    """`peers` 안에서 `x` 보다 작은 것의 비율. `peers` 는 `x` 자신을 포함한다.

    눈금이 없다 — 그래서 옮길 눈금도 없다 (스펙 §5.3).
    """
    if len(peers) <= 1:
        return 1.0
    return sum(1 for v in peers if v < x) / (len(peers) - 1)


def readiness(pick: Mapping[str, Any], peer_drawdowns: Sequence[float]) -> float:
    """R 축 — **지금 이 차트가 할 말이 있는가.**

    `peer_drawdowns` 는 **같은 구획** 종목들의 낙폭이다. 테마 안에서 재면 낙폭이 얕은
    테마의 종목이 상위 백분위를 받는다 (2026-08-29 실측: -3.7% 가 -44.8% 를 이겼다).
    """
    dd = _drawdown(pick)
    dd_part = 0.0 if dd is None else _percentile(dd, peer_drawdowns)
    base = (int(bool(pick.get("stage2"))) + int(bool(pick.get("above_50d")))) / 2
    return R_WEIGHTS["drawdown"] * dd_part + R_WEIGHTS["base"] * base
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run pytest tests/test_triage.py -v
```

기대: 24 passed.

- [ ] **Step 5: `features.py` 의 승격 주석을 고친다**

`src/msa/l4/features.py` 의 65~68행이 지금 이렇다:

```python
- **관찰용 열 — 아무 로직도 읽지 않는다**: `from_52w_high` · `sma200_up_1m` · `m_n_inputs`.
  `from_52w_high`·`sma200_up_1m` 은 `stage2` 안에서 **다시 계산**되어 쓰이고, 열 자체는 리포트·
```

앞 줄을 다음으로 바꾼다 (뒤 문장은 그대로 둔다).

```python
- **관찰용 열**: `sma200_up_1m` · `m_n_inputs`. **`from_52w_high` 는 2026-08-29 에
  관찰용에서 점수 입력으로 승격됐다** — `msa.triage` 의 R 축과 구획 분할이 읽는다
  (`docs/superpowers/specs/2026-08-29-hedge-fund-evolution-design.md` §5.3).
  L4 의 선정은 여전히 이 열을 읽지 않는다.
  `sma200_up_1m` 은 `stage2` 안에서 **다시 계산**되어 쓰이고, 열 자체는 리포트·
```

- [ ] **Step 6: 전체 검사**

```bash
uv run make check
```

기대: ruff · mypy · pytest 전부 통과.

- [ ] **Step 7: 커밋**

```bash
git add src/msa/triage.py src/msa/l4/features.py tests/test_triage.py
git commit -m "트리아지 R 축과 구획 — 낙폭 백분위는 구획 안에서 잰다

테마 안에서 재면 52주 고점 -3.7% 인 ESEA 가 -44.8% 인 ALHC 를 이긴다. 실데이터가
잡은 결함이고 회귀 테스트로 박았다. 낙폭 기준선은 새로 만들지 않고 기존 선언값
readme_block.PULLBACK_MARK 를 import 한다.

from_52w_high 이 관찰용 열에서 점수 입력으로 승격됐다 — features.py 주석을 함께 고쳤다."
```

---

### Task 4: 합성 — `score_digest` 와 골든 테스트

**Files:**
- Modify: `src/msa/triage.py`
- Create: `tests/fixtures/triage/digest-2026-08-29.json`
- Create: `tests/test_triage_golden.py`

**Interfaces:**
- Consumes: Task 3 의 `partition` · `readiness`, Task 2 의 `clarity`, Task 1 의 `theme_trust`
- Produces:
  - `@dataclass(frozen=True) TriageRow` — 필드: `ticker: str`, `theme: str`, `partition: str`, `triage: float | None`, `j: float | None`, `c: float`, `r: float`, `note: str`
  - `score_digest(digest: Mapping[str, Any]) -> list[TriageRow]` — `PARTITION_ORDER` → `triage` 내림차순 → `ticker` 오름차순으로 정렬해 반환
  - `declared_constants() -> dict[str, Any]`

- [ ] **Step 1: 골든 입력 픽스처를 만든다**

`state/daily/` 는 gitignore 라 실데이터를 그대로 쓸 수 없다. 축약본을 커밋한다.

```bash
mkdir -p tests/fixtures/triage
uv run python - <<'PY'
import json, pathlib
src = json.load(open("state/daily/2026-08-29/digest.json"))
keep = {"managed_care", "shipping_container"}
cols = ("ticker", "survival_unjudged", "red_flags", "s_partial", "composite_partial",
        "from_52w_high", "stage2", "above_50d")
out = {
    "asof": src["asof"],
    "themes": [
        {"theme": t["theme"],
         "picks": [{k: p.get(k) for k in cols} for p in (t.get("picks") or [])]}
        for t in src["themes"] if t["theme"] in keep
    ],
    "judged": [j for j in src["judged"] if j["theme"] in keep],
    "evidence_audit": {
        k: {"counts": v["counts"], "checked": v["checked"],
            "unverified_axes": v.get("unverified_axes") or []}
        for k, v in src["evidence_audit"].items() if k in keep
    },
}
p = pathlib.Path("tests/fixtures/triage/digest-2026-08-29.json")
p.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
print(p, p.stat().st_size, "bytes")
PY
```

기대: 파일이 생기고 크기가 10KB 미만.

- [ ] **Step 2: 실패하는 골든 테스트를 쓴다**

`tests/test_triage_golden.py` 를 새로 만든다.

```python
"""2026-08-29 고정 입력 골든 — 설계가 그날 리포트의 결론을 재현하는지.

구획 I-A 는 그날 README 헤드라인이 이미 뽑은 "차트 확인 대상 3종목" 과 같아야 한다.
스펙 §6.1 의 표가 이 테스트의 기대값이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from msa import triage

FIXTURE = Path(__file__).parent / "fixtures" / "triage" / "digest-2026-08-29.json"


@pytest.fixture(scope="module")
def rows() -> list[triage.TriageRow]:
    return triage.score_digest(json.loads(FIXTURE.read_text()))


def test_partition_ia_matches_that_days_headline(rows: list[triage.TriageRow]) -> None:
    ia = [r for r in rows if r.partition == triage.PARTITION_IA]
    assert [r.ticker for r in ia] == ["ALHC", "CLOV", "MOH"]


def test_partition_ia_scores(rows: list[triage.TriageRow]) -> None:
    got = {r.ticker: r.triage for r in rows if r.partition == triage.PARTITION_IA}
    assert got["ALHC"] == pytest.approx(0.8096, abs=5e-4)
    assert got["CLOV"] == pytest.approx(0.7246, abs=5e-4)
    assert got["MOH"] == pytest.approx(0.6996, abs=5e-4)


def test_clov_is_docked_for_its_red_flag(rows: list[triage.TriageRow]) -> None:
    """오늘 리포트가 ⚠ 로만 표시하던 것이 순서로 올라온다."""
    clov = next(r for r in rows if r.ticker == "CLOV")
    moh = next(r for r in rows if r.ticker == "MOH")
    assert clov.c == pytest.approx(0.85)
    assert moh.c == pytest.approx(1.00)


def test_evidence_defect_holds_j_below_point_eight(rows: list[triage.TriageRow]) -> None:
    """편입 가능·신뢰인데도 증거품질이 11/23·12/23 이라 J 가 멈춘다 (스펙 §6.1)."""
    j = {r.theme: r.j for r in rows}
    assert j["managed_care"] == pytest.approx(17 / 23)
    assert j["shipping_container"] == pytest.approx(35 / 46)
    assert all(v < 0.8 for v in j.values())


def test_partition_ib_top_is_cmre(rows: list[triage.TriageRow]) -> None:
    ib = [r for r in rows if r.partition == triage.PARTITION_IB]
    assert len(ib) == 12
    assert ib[0].ticker == "CMRE"


def test_rows_are_sorted_by_partition_then_score(rows: list[triage.TriageRow]) -> None:
    seen: list[int] = [triage.PARTITION_ORDER.index(r.partition) for r in rows]
    assert seen == sorted(seen), "구획 순서가 먼저다"
    for part in triage.PARTITION_ORDER:
        vals = [r.triage for r in rows if r.partition == part and r.triage is not None]
        assert vals == sorted(vals, reverse=True)
```

- [ ] **Step 3: 실패를 확인한다**

```bash
uv run pytest tests/test_triage_golden.py -v
```

기대: `AttributeError: module 'msa.triage' has no attribute 'score_digest'` 로 6개 실패.

- [ ] **Step 4: 최소 구현**

`src/msa/triage.py` 의 import 절에 `dataclass` 를 더한다.

```python
from dataclasses import dataclass
```

파일 끝에 덧붙인다.

```python
@dataclass(frozen=True)
class TriageRow:
    """종목 한 줄. `triage` 가 None 이면 계산 불가이고 `note` 가 이유를 든다."""

    ticker: str
    theme: str
    partition: str
    triage: float | None
    j: float | None
    c: float
    r: float
    note: str = ""


def score_digest(digest: Mapping[str, Any]) -> list[TriageRow]:
    """digest 모양 dict → 구획·점수가 붙은 종목 줄.

    정렬은 **구획 먼저, 그 안에서 triage 내림차순**이다. 구획 간 정렬은 하지 않는다 —
    백분위가 구획별로 따로 매겨지므로 I-B 의 값이 I-A 보다 커질 수 있다 (스펙 §6).
    """
    judged = {str(j["theme"]): j for j in (digest.get("judged") or [])}
    audits = digest.get("evidence_audit") or {}

    staged: list[tuple[str, str, str, float | None, float, str]] = []
    for entry in digest.get("themes") or []:
        theme = str(entry.get("theme"))
        jrow = judged.get(theme)
        arow = audits.get(theme)
        j_value = theme_trust(jrow, arow)
        note = "" if j_value is not None else "증거 실사 없음 — J 계산 불가"
        for pick in entry.get("picks") or []:
            part = partition(jrow, pick)
            staged.append(
                (str(pick.get("ticker")), theme, part, j_value, clarity(pick), note)
            )

    # 낙폭 백분위의 모집단은 **구획**이다 (스펙 §5.3).
    peers: dict[str, list[float]] = {}
    picks_by_ticker = {
        str(p.get("ticker")): p
        for e in (digest.get("themes") or [])
        for p in (e.get("picks") or [])
    }
    for ticker, _theme, part, _j, _c, _n in staged:
        dd = _drawdown(picks_by_ticker[ticker])
        if dd is not None:
            peers.setdefault(part, []).append(dd)

    rows: list[TriageRow] = []
    for ticker, theme, part, j_value, c_value, note in staged:
        r_value = readiness(picks_by_ticker[ticker], peers.get(part, []))
        total = (
            None
            if j_value is None
            else TRIAGE_WEIGHTS["J"] * j_value
            + TRIAGE_WEIGHTS["C"] * c_value
            + TRIAGE_WEIGHTS["R"] * r_value
        )
        rows.append(
            TriageRow(ticker, theme, part, total, j_value, c_value, r_value, note)
        )

    rows.sort(
        key=lambda r: (
            PARTITION_ORDER.index(r.partition),
            -(r.triage if r.triage is not None else -1.0),
            r.ticker,
        )
    )
    return rows


def declared_constants() -> dict[str, Any]:
    """산출물에 싣는 선언값 — 무엇을 어떤 값으로 돌렸는지 남긴다."""
    return {
        "triage_weights": TRIAGE_WEIGHTS,
        "r_weights": R_WEIGHTS,
        "evidence_cap": EVIDENCE_CAP,
        "evidence_cap_refuted": EVIDENCE_CAP_REFUTED,
        "unjudged_penalty": UNJUDGED_PENALTY,
        "red_flag_penalty": RED_FLAG_PENALTY,
        "red_flag_max": RED_FLAG_MAX,
        "partial_penalty": PARTIAL_PENALTY,
        "pullback_mark": PULLBACK_MARK,
        "pullback_mark_source": "msa.ops.readme_block.PULLBACK_MARK — 이 모듈이 만든 값이 아니다",
        "excluded_inputs": [
            "s_pct", "t_pct", "m_pct", "composite", "rank",
            "rs_rating", "from_52w_low", "vcp_base",
        ],
        "claim": "읽는 순서 — 초과수익을 주장하지 않는다 (docs/superpowers/specs/2026-08-29 §3.3)",
    }
```

- [ ] **Step 5: 통과를 확인한다**

```bash
uv run pytest tests/test_triage.py tests/test_triage_golden.py -v
```

기대: 30 passed.

- [ ] **Step 6: 커밋**

```bash
git add src/msa/triage.py tests/test_triage_golden.py tests/fixtures/triage/
git commit -m "트리아지 합성과 2026-08-29 골든 — 그날 헤드라인 3종목을 재현한다

구획 I-A 가 ALHC · CLOV · MOH 로 나오고 순서까지 박았다. 설계가 그날 리포트의
결론을 바꾸지 않고 순서를 더한다는 것이 이 테스트의 내용이다."
```

---

### Task 5: 파이프라인 배선 — digest 블록과 `triage.csv`

**Files:**
- Modify: `src/msa/pipeline/daily.py`
- Test: `tests/test_pipeline_daily.py`

**Interfaces:**
- Consumes: Task 4 의 `score_digest` · `declared_constants` · `TriageRow`
- Produces: `digest["triage"] = {"declared": {...}, "rows": [ {...}, ... ]}` — `rows` 는 `TriageRow` 를 dict 로 편 것. `state/daily/<date>/triage.csv`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_pipeline_daily.py` 끝에 덧붙인다. (파일 상단 import 절에 `from msa import triage as triage_mod` 를 더한다.)

```python
def test_digest_carries_triage_block() -> None:
    digest = {
        "themes": [
            {
                "theme": "t1",
                "picks": [
                    {"ticker": "AAA", "from_52w_high": -0.40, "red_flags": ""},
                    {"ticker": "BBB", "from_52w_high": -0.02, "red_flags": ""},
                ],
            }
        ],
        "judged": [
            {"theme": "t1", "portfolio_eligible": True, "trusted": True, "gate": "passed"}
        ],
        "evidence_audit": {
            "t1": {"counts": {"verified": 10}, "checked": 20, "unverified_axes": []}
        },
    }
    block = daily.build_triage_block(digest)
    assert block["declared"]["triage_weights"] == {"J": 0.50, "C": 0.30, "R": 0.20}
    by = {r["ticker"]: r for r in block["rows"]}
    assert by["AAA"]["partition"] == triage_mod.PARTITION_IA
    assert by["BBB"]["partition"] == triage_mod.PARTITION_IB


def test_triage_csv_has_reference_columns_but_they_are_not_inputs() -> None:
    rows = [
        {"ticker": "AAA", "theme": "t1", "partition": "I-A", "triage": 0.8,
         "j": 0.7, "c": 1.0, "r": 0.7, "note": ""}
    ]
    picks = {"AAA": {"ticker": "AAA", "s_pct": 0.5, "composite": 0.6, "rs_rating": 90.0,
                     "price": 10.0, "adv20_usd": 1e7, "from_52w_high": -0.4}}
    text = daily.render_triage_csv(rows, picks)
    header = text.splitlines()[0].split(",")
    assert header[:8] == [
        "partition", "triage", "ticker", "theme", "j", "c", "r", "from_52w_high"
    ]
    assert "s_pct" in header and "composite" in header and "rs_rating" in header


def test_build_triage_block_survives_missing_evidence_audit() -> None:
    digest = {
        "themes": [{"theme": "t1", "picks": [{"ticker": "AAA", "from_52w_high": -0.40}]}],
        "judged": [
            {"theme": "t1", "portfolio_eligible": True, "trusted": True, "gate": "passed"}
        ],
    }
    block = daily.build_triage_block(digest)
    row = block["rows"][0]
    assert row["triage"] is None
    assert "증거 실사 없음" in row["note"]
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run pytest tests/test_pipeline_daily.py -k triage -v
```

기대: `AttributeError: module 'msa.pipeline.daily' has no attribute 'build_triage_block'` 로 3개 실패.

- [ ] **Step 3: 최소 구현**

`src/msa/pipeline/daily.py` 의 import 절에 더한다.

```python
from msa import triage as triage_mod
```

`_update_readme` 정의 바로 위에 함수 둘을 넣는다.

```python
#: `triage.csv` 의 앞 열 — 점수와 그 성분. 뒤에는 참고 열이 붙는다.
TRIAGE_LEAD_COLUMNS = (
    "partition", "triage", "ticker", "theme", "j", "c", "r", "from_52w_high",
)

#: **참고 열 — 점수 입력이 아니다.** 사람이 읽으라고 싣는다 (스펙 §5.2·§5.3).
TRIAGE_REFERENCE_COLUMNS = (
    "price", "adv20_usd", "red_flags", "survival_unjudged",
    "s_pct", "t_pct", "m_pct", "composite", "rs_rating", "from_52w_low",
)


def build_triage_block(digest: dict[str, Any]) -> dict[str, Any]:
    """digest 에 붙일 `triage` 블록. 새 계산은 `msa.triage` 안에만 있다."""
    rows = triage_mod.score_digest(digest)
    return {
        "declared": triage_mod.declared_constants(),
        "claim_note": triage_mod.CLAIM_NOTE,
        "rows": [asdict(r) for r in rows],
    }


def render_triage_csv(
    rows: list[dict[str, Any]], picks_by_ticker: dict[str, dict[str, Any]]
) -> str:
    """구획·점수 + 참고 열. 참고 열은 점수에 안 들어간다는 사실이 열 이름 순서로 드러난다."""
    header = [*TRIAGE_LEAD_COLUMNS, *TRIAGE_REFERENCE_COLUMNS]
    out = [",".join(header)]
    for r in rows:
        src = picks_by_ticker.get(str(r["ticker"]), {})
        cells: list[str] = []
        for col in header:
            value = r.get(col, src.get(col))
            if value is None:
                cells.append("")
            elif isinstance(value, float):
                cells.append(f"{value:.6g}")
            else:
                cells.append(str(value).replace(",", " "))
        out.append(",".join(cells))
    return "\n".join(out) + "\n"
```

`from dataclasses import asdict` 를 import 절에 더한다.

`src/msa/triage.py` 에는 고정 문장을 상수로 넣는다 (`declared_constants` 위).

```python
#: 리포트에 매번 싣는 고정 문장 (`CLAUDE.md` §7 · 스펙 §8.1). 토씨를 바꾸지 않는다.
CLAIM_NOTE = (
    "**triage 는 읽는 순서다. 수익률 순서가 아니다.** 이 점수는 초과수익을 주장하지 "
    "않으며 그렇게 검정된 적도 없다. 높은 triage 는 \"먼저 차트를 열어라\" 이지 "
    "\"먼저 사라\" 가 아니다."
)
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run pytest tests/test_pipeline_daily.py -k triage -v
```

기대: 3 passed.

- [ ] **Step 5: `run_daily` 에 실제로 배선한다**

`src/msa/pipeline/daily.py` 의 `_audit_eligible(...)` 호출 **바로 다음**, README 블록 갱신 **앞**에 넣는다. 실사 결과가 J 에 반영돼야 하므로 순서가 중요하다.

```python
    # 트리아지 — 실사 뒤에 돈다. J 축이 `evidence_audit` 을 읽기 때문이다.
    with StepTimer() as t:
        digest["triage"] = build_triage_block(digest)
    picks_by_ticker = {
        str(p.get("ticker")): p
        for e in (digest.get("themes") or [])
        for p in (e.get("picks") or [])
    }
    triage_csv = render_triage_csv(digest["triage"]["rows"], picks_by_ticker)
    result.digest_md = render_digest_md(digest)
    if write and out_dir is not None:
        write_snapshot(
            out_dir,
            texts={"digest.md": result.digest_md, "report.txt": result.digest_md,
                   "triage.csv": triage_csv},
            jsons={"digest.json": digest},
        )
        report.add(
            StepResult("triage", "ok", "", [rel(out_dir / "triage.csv")], t.seconds)
        )
    else:
        report.add(
            StepResult("triage", "ok", "no-write — 파일을 쓰지 않았다", seconds=t.seconds)
        )
```

`StepTimer` 가 이 파일에서 쓰이는 이름과 다르면 같은 파일의 다른 단계(`digest` 단계)가 쓰는 것을 그대로 따른다.

- [ ] **Step 6: 스모크로 확인한다**

```bash
uv run msa run daily --asof 2026-08-29 --no-write 2>&1 | tail -30
```

기대: 단계 목록에 `triage ok` 가 보인다.

- [ ] **Step 7: 전체 검사**

```bash
uv run make check
```

기대: 전부 통과.

- [ ] **Step 8: 커밋**

```bash
git add src/msa/pipeline/daily.py src/msa/triage.py tests/test_pipeline_daily.py
git commit -m "트리아지를 일간 실행에 배선 — 실사 뒤, README 앞

J 축이 evidence_audit 을 읽으므로 순서가 규칙의 일부다. triage.csv 는 점수 성분을
앞에, 참고 열을 뒤에 싣는다 — 참고 열이 점수 입력이 아니라는 사실이 열 순서로 보인다."
```

---

### Task 6: 렌더링 — `digest.md` 와 README 블록

**Files:**
- Modify: `src/msa/pipeline/daily.py` (`render_digest_md`)
- Modify: `src/msa/ops/readme_block.py`
- Test: `tests/test_pipeline_daily.py` · `tests/test_ops_readme_block.py`

**Interfaces:**
- Consumes: Task 5 의 `digest["triage"]`
- Produces: `daily.triage_section_md(digest: dict[str, Any]) -> list[str]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_pipeline_daily.py` 끝에 덧붙인다.

```python
def test_triage_section_leads_with_partition_ia_and_claim_note() -> None:
    digest = {
        "triage": {
            "claim_note": "**triage 는 읽는 순서다. 수익률 순서가 아니다.** …",
            "declared": {},
            "rows": [
                {"ticker": "AAA", "theme": "t1", "partition": "I-A", "triage": 0.81,
                 "j": 0.74, "c": 1.0, "r": 0.70, "note": ""},
                {"ticker": "BBB", "theme": "t1", "partition": "I-B", "triage": 0.85,
                 "j": 0.74, "c": 1.0, "r": 0.85, "note": ""},
            ],
        }
    }
    lines = daily.triage_section_md(digest)
    text = "\n".join(lines)
    assert "읽는 순서다" in text
    assert text.index("I-A") < text.index("I-B"), "구획 순서가 점수보다 먼저다"
    assert text.index("AAA") < text.index("BBB"), "값이 낮아도 I-A 가 위다"


def test_triage_section_empty_when_no_block() -> None:
    assert daily.triage_section_md({}) == []
```

`tests/test_ops_readme_block.py` 끝에 덧붙인다.

```python
def test_readme_block_orders_picks_by_triage(tmp_path) -> None:
    digest = _digest_with_triage(
        rows=[
            {"ticker": "MOH", "theme": "managed_care", "partition": "I-A",
             "triage": 0.70, "j": 0.74, "c": 1.0, "r": 0.15, "note": ""},
            {"ticker": "ALHC", "theme": "managed_care", "partition": "I-A",
             "triage": 0.81, "j": 0.74, "c": 1.0, "r": 0.70, "note": ""},
        ]
    )
    block = readme_block.render_block(digest, today=date(2026, 8, 29))
    assert block.index("ALHC") < block.index("MOH")
```

`_digest_with_triage` 는 이 파일에 이미 있는 digest 만들기 헬퍼를 재사용해 `triage` 키만 더하는 얇은 함수로 쓴다. 기존 헬퍼 이름은 파일을 열어 확인하고 그대로 쓴다.

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run pytest tests/test_pipeline_daily.py -k triage_section tests/test_ops_readme_block.py -k triage -v
```

기대: `AttributeError: ... 'triage_section_md'` 로 실패.

- [ ] **Step 3: `digest.md` 절을 구현한다**

`src/msa/pipeline/daily.py` 의 `render_digest_md` 정의 **위**에 넣는다.

```python
#: 구획 머리말 — 각 구획이 무엇인지 매번 적는다. 값만 있는 표는 오해를 만든다.
_PARTITION_HEADINGS = {
    "I-A": "구획 I-A · 지금 볼 자리 — 판별을 통과했고 눌려 있다",
    "I-B": "구획 I-B · 편입 가능 · 고점권 — 테마는 좋으나 지금 자리가 아니다",
    "II": "구획 II · 판별 대기 — 알고 있는 것이 있고 결론이 부정이다",
    "III": "구획 III · 판별 전 참고 — 아무것도 모른다. 후보가 아니다",
}


def triage_section_md(digest: dict[str, Any]) -> list[str]:
    """구획별 트리아지 표. **구획 간 정렬은 하지 않는다** (스펙 §6)."""
    block = digest.get("triage") or {}
    rows = block.get("rows") or []
    if not rows:
        return []
    out = ["## 트리아지 — 읽는 순서", "", str(block.get("claim_note", "")), ""]
    for part in triage_mod.PARTITION_ORDER:
        group = [r for r in rows if r.get("partition") == part]
        if not group:
            continue
        out += [
            f"### {_PARTITION_HEADINGS.get(part, part)} ({len(group)})",
            "",
            "| triage | 종목 | 테마 | J | C | R |",
            "|---:|---|---|---:|---:|---:|",
        ]
        for r in group:
            score = "—" if r.get("triage") is None else f"{r['triage']:.3f}"
            j = "—" if r.get("j") is None else f"{r['j']:.3f}"
            out.append(
                f"| {score} | `{r['ticker']}` | `{r['theme']}` | "
                f"{j} | {r['c']:.2f} | {r['r']:.2f} |"
            )
        notes = {str(r.get("note")) for r in group if r.get("note")}
        if notes:
            out += ["", *(f"- {n}" for n in sorted(notes))]
        out.append("")
    return out
```

`render_digest_md` 안에서 종목 표 절이 끝난 뒤 `out += triage_section_md(digest)` 를 넣는다. 정확한 위치는 함수를 읽어 "테마별 표" 가 끝나는 지점 바로 뒤로 한다.

- [ ] **Step 4: README 블록의 순서를 바꾼다**

`src/msa/ops/readme_block.py` 의 `_pullbacks` 는 지금 테마·티커 순으로 낸다. triage 가 있으면 그 순서를 쓴다.

```python
def _triage_order(digest: dict[str, Any]) -> dict[str, float]:
    """티커 → triage. 블록이 없으면 빈 dict — 그러면 기존 순서를 그대로 쓴다."""
    rows = (digest.get("triage") or {}).get("rows") or []
    return {
        str(r["ticker"]): float(r["triage"])
        for r in rows
        if r.get("triage") is not None
    }
```

`_pullbacks` 를 호출하는 자리에서 정렬을 더한다. `_pullbacks(themes)` 의 시그니처를 `_pullbacks(themes, order=None)` 로 넓히고 마지막에:

```python
    if order:
        out.sort(key=lambda p: -order.get(str(p.get("ticker")), -1.0))
```

`_dip_lines` 와 `render_block` 의 "순서 = 테마·티커 순, 볼 만한 순서가 아니다" 문구는 **triage 가 있을 때** 다음으로 바꾼다:

```python
"순서 = triage(읽는 순서). 수익률 순서가 아니다."
```

triage 가 없으면 기존 문구를 그대로 둔다 — 없는 것을 있다고 말하지 않는다.

- [ ] **Step 5: 통과를 확인한다**

```bash
uv run pytest tests/test_pipeline_daily.py tests/test_ops_readme_block.py -v
```

기대: 전부 통과.

- [ ] **Step 6: 실제 리포트를 눈으로 본다**

```bash
uv run msa run daily --asof 2026-08-29 --no-write 2>&1 | sed -n '/트리아지/,/^$/p' | head -40
```

기대: 구획 I-A 에 `ALHC` · `CLOV` · `MOH` 가 이 순서로 보인다.

- [ ] **Step 7: 전체 검사와 커밋**

```bash
uv run make check
git add src/msa/pipeline/daily.py src/msa/ops/readme_block.py tests/
git commit -m "리포트가 구획별 트리아지로 정렬된다

구획 머리말을 매번 적는다 — 값만 있는 표는 오해를 만든다. triage 가 없으면 기존
'테마·티커 순' 문구를 그대로 둔다: 없는 것을 있다고 말하지 않는다."
```

---

### Task 7: P1b — 증거 처리 대장과 J 상한 연동

**Files:**
- Create: `src/msa/ops/resolutions.py`
- Modify: `src/msa/triage.py` (`theme_trust` 에 `resolutions` 인자)
- Modify: `src/msa/pipeline/daily.py` (`build_triage_block` 에 대장 전달)
- Test: `tests/test_ops_resolutions.py`

**Interfaces:**
- Consumes: Task 4 의 `theme_trust` · `EVIDENCE_CAP_REFUTED`
- Produces:
  - `@dataclass(frozen=True) Resolution` — `evidence_id: int`, `resolved_by: str`, `date: str`, `verdict: str`, `note: str`
  - `VERDICTS = ("confirmed", "refuted", "unresolvable")`
  - `load(root: Path, theme: str) -> list[Resolution]`
  - `append(root: Path, theme: str, entry: Resolution) -> Path` — 같은 `evidence_id` 가 이미 있으면 `ValueError`
  - `summary(entries: Sequence[Resolution]) -> dict[str, int]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_ops_resolutions.py` 를 새로 만든다.

```python
"""증거 처리 대장 — append-only, `journal/` 과 같은 규약 (`CLAUDE.md` §6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from msa import triage
from msa.ops import resolutions as res


def _entry(**kw: object) -> res.Resolution:
    d: dict[str, object] = {
        "evidence_id": 17,
        "resolved_by": "human",
        "date": "2026-08-30",
        "verdict": "confirmed",
        "note": "Commonwealth Fund 원문 표 3 에 340억 확인.",
    }
    d.update(kw)
    return res.Resolution(**d)  # type: ignore[arg-type]


def test_append_then_load_roundtrip(tmp_path: Path) -> None:
    res.append(tmp_path, "managed_care", _entry())
    got = res.load(tmp_path, "managed_care")
    assert [e.evidence_id for e in got] == [17]
    assert got[0].verdict == "confirmed"


def test_load_missing_theme_is_empty(tmp_path: Path) -> None:
    assert res.load(tmp_path, "nope") == []


def test_append_is_append_only(tmp_path: Path) -> None:
    res.append(tmp_path, "managed_care", _entry())
    with pytest.raises(ValueError, match="이미 있다"):
        res.append(tmp_path, "managed_care", _entry(note="다시 쓴다"))


def test_append_keeps_earlier_entries(tmp_path: Path) -> None:
    res.append(tmp_path, "managed_care", _entry(evidence_id=1))
    res.append(tmp_path, "managed_care", _entry(evidence_id=10))
    assert [e.evidence_id for e in res.load(tmp_path, "managed_care")] == [1, 10]


def test_unknown_verdict_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="verdict"):
        res.append(tmp_path, "managed_care", _entry(verdict="probably_fine"))


def test_summary_counts_by_verdict() -> None:
    entries = [_entry(evidence_id=1), _entry(evidence_id=2, verdict="refuted")]
    assert res.summary(entries) == {"confirmed": 1, "refuted": 1, "unresolvable": 0}


def test_refuted_drives_theme_trust_below_cap() -> None:
    """`refuted` 가 하나라도 있으면 J 상한이 0.25 로 내려간다 (스펙 §7)."""
    judged = {"portfolio_eligible": True, "trusted": True, "gate": "passed"}
    audit = {"counts": {"verified": 23}, "checked": 23, "unverified_axes": []}
    clean = triage.theme_trust(judged, audit, resolutions=[])
    dirty = triage.theme_trust(judged, audit, resolutions=[_entry(verdict="refuted")])
    assert clean == pytest.approx(1.0)
    assert dirty == triage.EVIDENCE_CAP_REFUTED == 0.25


def test_confirmed_counts_as_verified() -> None:
    """사람이 확인한 것은 verified 로 계상한다 — 증거품질이 올라간다."""
    judged = {"portfolio_eligible": True, "trusted": True, "gate": "passed"}
    audit = {"counts": {"verified": 10}, "checked": 20, "unverified_axes": []}
    before = triage.theme_trust(judged, audit, resolutions=[])
    after = triage.theme_trust(
        judged, audit, resolutions=[_entry(evidence_id=1), _entry(evidence_id=2)]
    )
    assert before == pytest.approx(0.5 + 0.5 * 10 / 20)
    assert after == pytest.approx(0.5 + 0.5 * 12 / 20)
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run pytest tests/test_ops_resolutions.py -v
```

기대: `ModuleNotFoundError: No module named 'msa.ops.resolutions'`.

- [ ] **Step 3: 대장 모듈을 구현한다**

`src/msa/ops/resolutions.py` 를 새로 만든다.

```python
"""증거 처리 대장 — 사람이 원문을 열어 확인한 결과를 남기는 자리.

2026-08-25 실사에서 표본의 20% 가 원문에 없는 숫자였다. 리포트는 "먼저 열 것" 을
찍어 주지만, **사람이 열어서 확인한 결과가 남을 곳이 없었다.** 이 모듈이 그 자리다.

`journal/` 과 같은 append-only 규약이다 (`CLAUDE.md` §6) — 같은 `evidence_id` 를 다시
쓰지 못한다. 생각이 바뀌면 새 `evidence_id` 항목이 아니라 **재판별**이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

#: 사람이 낼 수 있는 판정. 임계를 두지 않는다 — 셋 중 하나다.
VERDICTS = ("confirmed", "refuted", "unresolvable")


@dataclass(frozen=True)
class Resolution:
    evidence_id: int
    resolved_by: str
    date: str
    verdict: str
    note: str = ""


def path_for(root: Path, theme: str) -> Path:
    return Path(root) / f"{theme}.yaml"


def load(root: Path, theme: str) -> list[Resolution]:
    p = path_for(root, theme)
    if not p.exists():
        return []
    raw: Any = yaml.safe_load(p.read_text()) or []
    return [Resolution(**dict(r)) for r in raw]


def append(root: Path, theme: str, entry: Resolution) -> Path:
    if entry.verdict not in VERDICTS:
        raise ValueError(f"verdict 는 {VERDICTS} 중 하나여야 한다: {entry.verdict!r}")
    existing = load(root, theme)
    if any(e.evidence_id == entry.evidence_id for e in existing):
        raise ValueError(
            f"evidence_id {entry.evidence_id} 는 이미 있다 — 대장은 append-only 다"
        )
    p = path_for(root, theme)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(e) for e in [*existing, entry]]
    p.write_text(yaml.safe_dump(rows, allow_unicode=True, sort_keys=False))
    return p


def summary(entries: Sequence[Resolution]) -> dict[str, int]:
    return {v: sum(1 for e in entries if e.verdict == v) for v in VERDICTS}
```

- [ ] **Step 4: `theme_trust` 를 대장에 연결한다**

`src/msa/triage.py` 의 `theme_trust` 를 다음으로 바꾼다.

```python
def theme_trust(
    judged: Mapping[str, Any] | None,
    audit: Mapping[str, Any] | None,
    *,
    resolutions: Sequence[Any] | None = None,
) -> float | None:
    """J 축의 테마 성분.

    - 판별이 없으면 **0.0**. 증거품질 항은 아예 없다 — 평균 내지 않는다.
    - 판별은 있는데 실사가 없으면 **None**(계산 불가). 0.5 로 채우지 않는다
      (`CLAUDE.md` §2 조용한 절단 금지).
    - 대장(`ops.resolutions`)에 `refuted` 가 하나라도 있으면 상한이
      `EVIDENCE_CAP_REFUTED` 로 내려간다 — 판별을 떠받친 증거가 반박됐다는 뜻이다.
    - `confirmed` 는 `verified` 로 계상한다 — 사람이 원문을 열어 확인했다.
    """
    if judged is None:
        return 0.0
    if audit is None:
        return None
    entries = list(resolutions or [])
    confirmed = sum(1 for e in entries if getattr(e, "verdict", None) == "confirmed")
    refuted = any(getattr(e, "verdict", None) == "refuted" for e in entries)

    counts = audit.get("counts") or {}
    checked = int(audit["checked"])
    quality = min(int(counts.get("verified", 0)) + confirmed, checked) / checked

    value = 0.5 * judgment_state(judged) + 0.5 * quality
    if refuted:
        return min(value, EVIDENCE_CAP_REFUTED)
    if audit.get("unverified_axes"):
        return min(value, EVIDENCE_CAP)
    return value
```

`evidence_quality` 는 그대로 둔다 — Task 1 의 테스트가 계속 쓴다.

- [ ] **Step 5: `score_digest` 와 파이프라인에 대장을 전달한다**

`score_digest` 시그니처를 넓힌다.

```python
def score_digest(
    digest: Mapping[str, Any],
    resolutions: Mapping[str, Sequence[Any]] | None = None,
) -> list[TriageRow]:
```

본문의 `j_value = theme_trust(jrow, arow)` 를 다음으로 바꾼다.

```python
        j_value = theme_trust(
            jrow, arow, resolutions=(resolutions or {}).get(theme)
        )
```

`daily.build_triage_block` 을 다음으로 바꾼다.

```python
def build_triage_block(
    digest: dict[str, Any], *, resolutions_root: Path | None = None
) -> dict[str, Any]:
    """digest 에 붙일 `triage` 블록. 새 계산은 `msa.triage` 안에만 있다."""
    ledger: dict[str, list[Any]] = {}
    if resolutions_root is not None:
        from msa.ops import resolutions as res_mod

        for j in digest.get("judged") or []:
            entries = res_mod.load(resolutions_root, str(j["theme"]))
            if entries:
                ledger[str(j["theme"])] = entries
    rows = triage_mod.score_digest(digest, ledger)
    return {
        "declared": triage_mod.declared_constants(),
        "claim_note": triage_mod.CLAIM_NOTE,
        "resolutions": {k: len(v) for k, v in sorted(ledger.items())},
        "rows": [asdict(r) for r in rows],
    }
```

`run_daily` 안의 호출을 `build_triage_block(digest, resolutions_root=p.state / "evidence_resolutions")` 로 바꾼다. `p.state` 가 이 파일에서 쓰이는 경로 객체의 실제 이름과 다르면 같은 함수 안의 `p.daily` 사용례를 보고 맞춘다.

- [ ] **Step 6: 통과를 확인한다**

```bash
uv run pytest tests/test_ops_resolutions.py tests/test_triage.py tests/test_triage_golden.py -v
```

기대: 전부 통과. 골든은 대장이 비어 있으므로 값이 안 바뀐다.

- [ ] **Step 7: 전체 검사와 커밋**

```bash
uv run make check
git add src/msa/ops/resolutions.py src/msa/triage.py src/msa/pipeline/daily.py tests/test_ops_resolutions.py
git commit -m "증거 처리 대장 — 사람이 원문을 열어 확인한 결과가 남을 자리

2026-08-25 실사가 20% 결함을 찾았지만 사람이 확인한 결과를 적을 곳이 없었다.
refuted 가 하나라도 있으면 J 상한이 0.25 로 내려가고, confirmed 는 verified 로
계상돼 증거품질이 올라간다. journal/ 과 같은 append-only 규약이다."
```

---

### Task 8: 문서와 저널 — 무엇이 바뀌었는지 남긴다

**Files:**
- Create: `journal/2026-08-29-triage-score.md`
- Modify: `CLAUDE.md` (명령 절에 `triage.csv` 한 줄)
- Modify: `docs/18-daily-run.md` (§0 역할 표에 트리아지 행)

**Interfaces:**
- Consumes: Task 1~7 전부
- Produces: 없음 (문서)

- [ ] **Step 1: 저널 항목을 쓴다**

`journal/2026-08-29-triage-score.md` 를 새로 만든다. `journal/` 은 append-only 이므로 기존 파일은 열지 않는다.

```markdown
# 2026-08-29 · 트리아지 점수 — 은퇴한 선정 규칙을 되살리지 않고 순서를 만들었다

사용자 요구는 "매일 종목을 점수제로 추천" 이었다. 그 점수는 이미 있었고
2026-08-24 에 은퇴했다 (`docs/15` · `journal/2026-08-24-l4-selection-retired.md`).
그대로 켜는 것은 검정 결과를 보고 결과를 뒤집는 것이라 `CLAUDE.md` §1 이 금지한다.

**그래서 다른 물건을 만들었다.** 종합 점수가 묻던 "무엇이 더 오를 것인가" 가 아니라
"다음 10분을 어느 차트에 쓸 것인가" 를 묻는다. 수익률을 주장하지 않으므로 `docs/15`
관문의 대상이 아니고, 대가로 **검정될 수도 없다.**

## 설계 중 두 번 틀렸고 두 번 다 실데이터가 잡았다

1. 낙폭 포화점 0.50 을 `docs/24` 근거라며 인용했다 — **그런 상수는 없었다.** 내가 만든
   새 임계였다.
2. 백분위를 테마 안에서 쟀다 — 52주 고점 **−3.7%** 인 `ESEA` 가 **−44.8%** 인 `ALHC` 를
   이기고 1위가 됐다.

확정안은 **새 수치 상수를 하나도 만들지 않는다.** 낙폭 기준선은 기존 선언값
`readme_block.PULLBACK_MARK`(−0.15)를 그 값이 이미 뜻하던 그대로 구획 분할에 쓰고,
낙폭 순서는 백분위라 눈금이 없다.

## 조사 중 나온 사실 — T 축은 반대로 일한다

`docs/backtest-l4.md` §Q2 가 축 단독 rank-IC 를 이미 재 놨다:
**S +0.0449** [+0.0203, +0.0658] · **M +0.0327** [+0.0096, +0.0539] ·
**T −0.0425** [−0.0699, −0.0162]. `AXIS_WEIGHTS` 에서 **0.40 을 받은 축의 부호가 반대**다.
종합 점수가 테마 EW 를 못 이긴 것의 기계적 설명이 여기 있다.

**그럼에도 `AXIS_WEIGHTS` 를 옮기지 않았다** — `CLAUDE.md` §1 대로, 검정이 말하면
기록하고 값은 둔다.

## 남긴 위험

트리아지의 축 선택은 위 결과를 **본 뒤에** 내려졌다. 도메인 근거만으로 골랐다고 말하면
거짓이다. 허용되는 이유는 하나뿐이다 — **이 점수가 수익률을 주장하지 않기 때문이다.**
언젠가 "이 순서로 사면 낫다" 로 승격하려 한다면 그때는 새 사전 등록이 필요하고,
§Q2 를 본 것이 시도 수에 들어간다. **그 문은 이 항목이 열지 않는다.**

설계 전문: `docs/superpowers/specs/2026-08-29-hedge-fund-evolution-design.md`
구현 계획: `docs/superpowers/plans/2026-08-29-p1-triage-score.md`
```

- [ ] **Step 2: 저널 검사를 돌린다**

```bash
uv run msa journal verify
```

기대: 통과 (새 파일만 추가했고 기존 파일은 안 건드렸다).

- [ ] **Step 3: `CLAUDE.md` 의 `msa run daily` 설명에 한 줄 더한다**

`msa run daily` 블록의 산출물 줄을 찾아 다음을 덧붙인다.

```
                      #   triage.csv — 구획(I-A/I-B/II/III) + 읽는 순서 점수. **수익률 순서가
                      #   아니다** (docs/superpowers/specs/2026-08-29 §3.3). 참고 열(s_pct·
                      #   composite·rs_rating)은 실리되 점수 입력이 아니다
```

- [ ] **Step 4: `docs/18-daily-run.md` §0 의 역할 표에 행을 더한다**

기존 표:

```
| 종목 명단 | **시스템** | 결정론적 계층이 고른다 (`CLAUDE.md` §4) |
| **종목·시점·비중** | **사람** | 차트·손익비를 보고 |
```

가운데에 넣는다.

```
| **읽는 순서** | **시스템** | 구획 + triage — 어느 차트를 먼저 열지. **무엇을 살지가 아니다** |
```

- [ ] **Step 5: 전체 검사**

```bash
uv run make check && uv run msa journal verify
```

기대: 둘 다 통과.

- [ ] **Step 6: 실제 실행으로 끝을 확인한다**

```bash
uv run msa run daily --asof 2026-08-29 --no-write 2>&1 | tail -40
```

기대: `triage ok` 단계가 보이고, 트리아지 절의 구획 I-A 가 `ALHC` · `CLOV` · `MOH` 순이다.

- [ ] **Step 7: 커밋**

```bash
git add journal/2026-08-29-triage-score.md CLAUDE.md docs/18-daily-run.md
git commit -m "저널과 문서 — 두 번 틀린 경위와 T 축 부호를 기록한다

AXIS_WEIGHTS 는 안 옮겼다. 트리아지의 축 선택이 백테스트 결과를 본 뒤에 내려졌다는
사실과, 승격하려면 새 사전 등록이 필요하다는 것도 함께 적었다."
```

---

## 자체 검토

**1. 스펙 커버리지**

| 스펙 절 | 태스크 |
|---|---|
| §4.1 축 셋 · §4.2 가중치 근거 | Task 1 (상수) · Task 4 (합성) |
| §5.1 J · 5.1.1 선행순서 · 5.1.2 증거품질 · 5.1.3 상한 | Task 1 |
| §5.2 C · S 축 배제 | Task 2 |
| §5.3 R · `vcp_base` 배제 · `from_52w_high` 승격 | Task 3 |
| §6 구획 · 비교 가능성 | Task 3 (분류) · Task 4 (정렬) |
| §6.1 2026-08-29 실측 | Task 4 (골든) |
| §7 증거 처리 대장 | Task 7 |
| §8.1 산출물 · 고정 문장 | Task 5 (`triage.csv`·`CLAIM_NOTE`) · Task 6 (렌더링) |
| §8.2 테스트 표 6종 + 추가 3종 | Task 1~4 · Task 7 |
| §11 규약 대조 | Task 8 (저널·문서) |

**§9(P2~P4)는 이 계획의 범위가 아니다** — 각자의 스펙과 계획으로 간다.

**2. 스펙 §8.2 테스트 표와의 대조**

| 스펙이 요구한 테스트 | 이 계획의 자리 |
|---|---|
| `test_triage_partition` | Task 3 `test_partition_*` · Task 4 `test_rows_are_sorted_by_partition_then_score` |
| `test_triage_evidence_cap` | Task 1 `test_theme_trust_capped_when_unverified_axes_present` |
| `test_triage_weights_declared` | Task 1 `test_weights_are_declared_and_sum_to_one` · Task 4 `declared_constants` |
| `test_triage_no_return_claim` | Task 2 `test_clarity_ignores_return_predictive_axes` · Task 5 `test_triage_csv_has_reference_columns_but_they_are_not_inputs` |
| `test_triage_missing_inputs` | Task 1 `test_theme_trust_none_when_judged_but_no_audit` · Task 3 `test_partition_missing_drawdown_is_ib_not_ia` · Task 5 `test_build_triage_block_survives_missing_evidence_audit` |
| `test_triage_reproduce` | **미배정** — `msa ops reproduce` 는 `state/scans/` 스냅샷만 재생성하고 digest 는 다루지 않는다. triage 는 digest 의 순수 함수라 골든 테스트(Task 4)가 결정론을 이미 고정한다. **스펙 §8.2 의 그 줄은 골든으로 대체됐다** — Task 8 에서 스펙의 그 행에 이 주석을 단다 |
| `test_triage_pullback_split` | Task 3 `test_partition_splits_eligible_by_pullback_mark` |
| `test_triage_percentile_scope` | Task 3 `test_readiness_shallow_theme_does_not_outrank_deep_one` |
| `test_triage_2026_08_29_golden` | Task 4 전부 |

**3. 타입 일관성**

- `theme_trust` 는 Task 1 에서 위치인자 2개로 정의되고 Task 7 에서 **키워드 전용** `resolutions` 를 더한다. Task 1 의 테스트는 위치인자만 쓰므로 깨지지 않는다.
- `score_digest` 는 Task 4 에서 1인자, Task 7 에서 2인자(둘째는 기본값 `None`). Task 4 의 골든 테스트는 1인자 호출이라 깨지지 않는다.
- `TriageRow.triage` 는 `float | None` 이고 정렬 키가 `None` 을 `-1.0` 으로 낮춰 뒤로 보낸다 — 계산 불가가 위로 올라오지 않는다.
- `partition()` 의 반환은 `PARTITION_ORDER` 의 원소뿐이다. `PARTITION_ORDER.index()` 가 Task 4 정렬에서 KeyError 없이 돈다.
- Task 5 의 `build_triage_block` 은 Task 7 에서 키워드 전용 `resolutions_root` 를 더한다 — Task 5 의 테스트는 1인자 호출이라 깨지지 않는다.

**4. 발견해 고친 것**

- 스펙 §8.2 의 `test_triage_reproduce` 가 실제로는 배정 불가였다 (`msa ops reproduce` 의 대상이 digest 가 아니다). 위 표에 그 사실과 대체물을 적었고, Task 8 에서 스펙 본문에도 주석을 단다.
