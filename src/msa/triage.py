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

**시장 데이터 위에 새 임계를 긋지 않았다.** 낙폭 기준선은 `ops.readme_block.PULLBACK_MARK`
를 import 해서 쓰고(복사하지 않는다), 낙폭 순서는 백분위라 눈금이 없다.

**그러나 점수를 만드는 선언 상수는 이 모듈이 새로 만들었다** — `EVIDENCE_CAP` ·
`EVIDENCE_CAP_REFUTED` · `UNJUDGED_PENALTY` · `RED_FLAG_PENALTY` · `RED_FLAG_MAX` ·
`PARTIAL_PENALTY` 여섯이다. 초안 독스트링은 "새 수치 상수는 하나도 만들지 않았다" 고
적었는데 **그대로 읽으면 거짓**이었고, `docs/24` 가 존재하는 이유가 정확히 그 드리프트다.
여섯 전부 `msa.basis` 레지스트리에 `NoBasis`(선언값)로 등록돼 있고, 값을 바꾸면 근거도
같이 고치라고 CI 가 막는다 (`tests/test_basis.py`).

`TRIAGE_WEIGHTS` · `R_WEIGHTS` 는 레지스트리에 넣지 않는다 — `AXIS_WEIGHTS` · `S_WEIGHTS`
가 들어 있지 않은 것과 같은 이유다. 레지스트리는 스칼라 임계를 추적하고, 배분 벡터의
근거는 스펙 §4.2 가 문장으로 진다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from msa.l2 import regime as _regime
from msa.l4 import analyst as _l4_analyst
from msa.ops.readme_block import PULLBACK_MARK

#: 축 가중치 — 선언값. 결과를 보고 옮기지 않는다 (`CLAUDE.md` §1 · 스펙 §4.2).
TRIAGE_WEIGHTS = {"J": 0.50, "C": 0.30, "R": 0.20}

#: 판정을 만든 축의 증거가 원문 대조를 통과하지 못했을 때 J 의 상한 (스펙 §5.1.3).
EVIDENCE_CAP = 0.50

#: 증거 처리 대장에서 `refuted` 가 나온 테마의 J 상한 (스펙 §7).
EVIDENCE_CAP_REFUTED = 0.25

#: C 축 감점 — 전부 선언값이다 (스펙 §5.2).
#: 미판정이 가장 큰 이유: 사람이 재무제표를 직접 열어야 한다 — 가장 비싼 노동이다.
UNJUDGED_PENALTY = 0.50
RED_FLAG_PENALTY = 0.15
#: 레드플래그 감점의 상한 건수. 3건이 2건보다 두 배 나쁘다고 말할 근거가 없다.
RED_FLAG_MAX = 2
#: 입력 결측. 작은 감점 — 결측은 나쁨이 아니라 **모름**이다.
PARTIAL_PENALTY = 0.10

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
    *,
    resolutions: Sequence[Any] | None = None,
) -> float | None:
    """J 축의 테마 성분.

    - 판별이 없으면 **0.0**. 증거품질 항은 아예 없다 — 평균 내지 않는다.
    - 판별은 있는데 실사가 없으면 **None**(계산 불가). 0.5 로 채우지 않는다
      (`CLAUDE.md` §2 조용한 절단 금지).
    - 대장(`ops.resolutions`)에 `refuted` 가 하나라도 있으면 상한이
      `EVIDENCE_CAP_REFUTED` 로 내려간다 — 판별을 떠받친 증거가 반박됐다는 뜻이라
      `unverified_axes` 상한(0.50)보다 무겁다.
    - `confirmed` 는 `verified` 로 계상한다 — 사람이 원문을 열어 확인했다.
    - `unresolvable` 은 **아무 영향도 없다.** 시간을 썼다는 사실이 증거를 검증하지는 않는다.
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
    # 사람이 확인한 건수가 실사 건수를 넘어도 품질은 1 을 넘지 않는다.
    quality = min(int(counts.get("verified", 0)) + confirmed, checked) / checked

    value = 0.5 * judgment_state(judged) + 0.5 * quality
    if refuted:
        return min(value, EVIDENCE_CAP_REFUTED)
    if audit.get("unverified_axes"):
        return min(value, EVIDENCE_CAP)
    return value


def _red_flag_count(pick: Mapping[str, Any]) -> int:
    raw = pick.get("red_flags") or ""
    return len([x for x in str(raw).split(",") if x.strip()])


def clarity(pick: Mapping[str, Any]) -> float:
    """C 축 — **차트를 열기 전에 재무를 다시 확인해야 하는가.**

    `s_pct` 를 쓰지 않는다: S 는 `docs/backtest-l4.md` §Q2 에서 rank-IC 가 양수로 측정된
    축이고, 그것을 읽는 순서에 넣으면 이 점수가 조용히 수익률 주장이 된다 (스펙 §5.2).

    **실제 하한은 0.10 이다** — 감점 최대가 0.50+0.30+0.10 = 0.90 이기 때문이다.
    끝의 `max(..., 0.0)` 은 앞으로 감점 항목이 늘어날 때를 위한 방어이지 지금 돌아가는
    가지가 아니다 (`test_clarity_worst_case_floor_is_point_one`).
    """
    value = 1.0
    if pick.get("survival_unjudged") is not None:
        value -= UNJUDGED_PENALTY
    value -= RED_FLAG_PENALTY * min(_red_flag_count(pick), RED_FLAG_MAX)
    if pick.get("s_partial") or pick.get("composite_partial"):
        value -= PARTIAL_PENALTY
    return max(value, 0.0)


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


def readiness(
    pick: Mapping[str, Any], peer_drawdowns: Sequence[float], tilt: float = 1.0
) -> float:
    """R 축 — **지금 이 차트가 할 말이 있는가.**

    `peer_drawdowns` 는 **같은 구획** 종목들의 낙폭이다. 테마 안에서 재면 낙폭이 얕은
    테마의 종목이 상위 백분위를 받는다 (2026-08-29 실측: -3.7% 가 -44.8% 를 이겼다).

    `tilt` 는 매크로 레짐 계수다 (P2, `docs/25` §3.3). **R 에만 곱한다** — 레짐은 그 테마의
    가치함정 판별이 옳은지(J)에 대해서도 그 회사의 재무(C)에 대해서도 아무 말을 하지 않는다.
    레짐이 없으면 1.0 이고, 그것이 이 인자의 기본값인 이유다.
    """
    dd = _drawdown(pick)
    dd_part = 0.0 if dd is None else _percentile(dd, peer_drawdowns)
    base = (int(bool(pick.get("stage2"))) + int(bool(pick.get("above_50d")))) / 2
    return (R_WEIGHTS["drawdown"] * dd_part + R_WEIGHTS["base"] * base) * tilt


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


def blend_ticker_trust(theme_trust_value: float, ticker_trust: float | None) -> float:
    """J = 0.5·J_theme + 0.5·J_ticker (P3, 설계 §9.2).

    **노트가 없으면 `J = J_theme` 이다** — 오늘의 식이 이 확장의 특수해가 된다. 없음을
    0 이나 0.5 로 채우면 분석가를 안 부른 종목이 "재무가 무너지는 종목" 과 섞인다
    (`CLAUDE.md` §2).
    """
    if ticker_trust is None:
        return theme_trust_value
    return 0.5 * theme_trust_value + 0.5 * ticker_trust


def score_digest(
    digest: Mapping[str, Any],
    resolutions: Mapping[str, Sequence[Any]] | None = None,
) -> list[TriageRow]:
    """digest 모양 dict → 구획·점수가 붙은 종목 줄.

    정렬은 **구획 먼저, 그 안에서 triage 내림차순**이다. 구획 간 정렬은 하지 않는다 —
    백분위가 구획별로 따로 매겨지므로 I-B 의 값이 I-A 보다 커질 수 있다 (스펙 §6).
    """
    judged = {str(j["theme"]): j for j in (digest.get("judged") or [])}
    audits = digest.get("evidence_audit") or {}
    # **실사 단계가 안 돈 것**과 **이 테마의 실사가 없는 것**은 다른 사실이다.
    # 둘 다 J 는 계산 불가지만, 사람이 할 일이 다르다 — 앞은 실행 방식의 문제고
    # 뒤는 그 테마의 문제다. 한 문장으로 뭉뚱그리면 어느 쪽인지 알 수 없다.
    audit_ran = "evidence_audit" in digest
    # 매크로 레짐 계수 (P2). **구획 계산 전에 읽지 않는다** — 구획은 판별과 낙폭이 정하고
    # 매크로는 둘 다에 발언권이 없다 (`docs/25` §3.3).
    tilts: Mapping[str, float] = digest.get("regime_tilts") or {}
    # 종목 노트 (P3). **키가 없는 종목은 노트가 없다는 뜻**이고, 그러면 J = J_theme 이다.
    notes: Mapping[str, float] = digest.get("stock_notes") or {}

    staged: list[tuple[dict[str, Any], str, str, float | None, float, str]] = []
    for entry in digest.get("themes") or []:
        theme = str(entry.get("theme"))
        jrow = judged.get(theme)
        arow = audits.get(theme)
        j_value = theme_trust(jrow, arow, resolutions=(resolutions or {}).get(theme))
        if j_value is not None:
            note = ""
        elif not audit_ran:
            note = (
                "증거 실사 단계가 돌지 않았다 (--no-write 또는 --no-audit) — J 계산 불가. "
                "점수를 보려면 실사를 켜고 다시 돌린다"
            )
        else:
            note = f"`{theme}` 의 증거 실사 결과가 없다 — J 계산 불가"
        for pick in entry.get("picks") or []:
            part = partition(jrow, pick)
            j_pick = (
                None
                if j_value is None
                else blend_ticker_trust(j_value, notes.get(str(pick.get("ticker"))))
            )
            staged.append((dict(pick), theme, part, j_pick, clarity(pick), note))

    # 낙폭 백분위의 모집단은 **구획**이다 (스펙 §5.3). 테마 안에서 재면 낙폭이 얕은
    # 테마의 종목이 상위 백분위를 받는다 (2026-08-29 실측).
    peers: dict[str, list[float]] = {}
    for pick, _theme, part, _j, _c, _n in staged:
        dd = _drawdown(pick)
        if dd is not None:
            peers.setdefault(part, []).append(dd)

    rows: list[TriageRow] = []
    for pick, theme, part, j_value, c_value, note in staged:
        r_value = readiness(pick, peers.get(part, []), tilts.get(theme, 1.0))
        total = (
            None
            if j_value is None
            else TRIAGE_WEIGHTS["J"] * j_value
            + TRIAGE_WEIGHTS["C"] * c_value
            + TRIAGE_WEIGHTS["R"] * r_value
        )
        rows.append(
            TriageRow(
                str(pick.get("ticker")), theme, part, total, j_value, c_value, r_value, note
            )
        )

    rows.sort(
        key=lambda r: (
            PARTITION_ORDER.index(r.partition),
            -(r.triage if r.triage is not None else -1.0),
            r.ticker,
        )
    )
    return rows


#: 리포트에 매번 싣는 고정 문장 (`CLAUDE.md` §7 · 스펙 §8.1). 토씨를 바꾸지 않는다.
CLAIM_NOTE = (
    "**triage 는 읽는 순서다. 수익률 순서가 아니다.** 이 점수는 초과수익을 주장하지 "
    "않으며 그렇게 검정된 적도 없다. 높은 triage 는 \"먼저 차트를 열어라\" 이지 "
    "\"먼저 사라\" 가 아니다."
)


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
        "pullback_mark_source": (
            "msa.ops.readme_block.PULLBACK_MARK — 이 모듈이 만든 값이 아니다"
        ),
        "excluded_inputs": [
            "s_pct",
            "t_pct",
            "m_pct",
            "composite",
            "rank",
            "rs_rating",
            "from_52w_low",
            "vcp_base",
        ],
        "note_trust": dict(_l4_analyst.NOTE_TRUST),
        "note_trust_source": (
            "msa.l4.analyst.NOTE_TRUST — 설계 §9.2. 노트가 없으면 J = J_theme (특수해)"
        ),
        "regime_tilt": dict(_regime.REGIME_TILT),
        "regime_tilt_source": (
            "msa.l2.regime.REGIME_TILT — docs/25 §3.4 선언값. R 축에만 곱한다"
        ),
        "claim": (
            "읽는 순서 — 초과수익을 주장하지 않는다 "
            "(docs/superpowers/specs/2026-08-29-hedge-fund-evolution-design.md §3.3)"
        ),
    }
