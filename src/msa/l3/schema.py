"""thesis 객체 검증 — `docs/specs/thesis.schema.yaml` + `docs/05-agent-research.md` §4 규약.

스키마 파일은 JSON Schema **스타일**이지 엄밀한 JSON Schema 가 아니다(`type: date`, `note:` 필드
등).
그래서 외부 검증기 대신 손으로 쓴 검증기를 둔다. 다만 **required 목록과 enum 은 스키마 파일에서
읽어**
문서와 코드가 어긋나면 테스트가 잡도록 한다 (`msa.thesis.load_spec()`).

오류(`errors`)는 **저장 거부** 사유고, 경고(`warnings`)는 리포트에 표시만 한다.

| §4 규약 | 여기서 | 종류 |
|---|---|---|
| `evidence` 비면 거부 | `R_EVIDENCE_EMPTY` | error |
| `invalidations` 비면 거부 | `R_INVALIDATIONS_EMPTY` | error |
| `mechanism` 상관 서술 금지 | `R_MECHANISM_CORRELATION` (`CORRELATION_PHRASES`) | error |
| `bear_case` 요약 금지 | 파이프라인이 bear 원문과 대조 → `R_BEAR_CASE_NOT_VERBATIM` | error |
| 종목명이 서술 필드에 등장 | `W_CLAIM_NAMES_STOCK` (`NAME_CHECKED_FIELDS`) | warning |
| `reliability: low` 만으로 축 판정 불가 | `R_AXIS_LOW_RELIABILITY_ONLY` | error |
| contested 는 ruling + refs 필요 | `R_CONTESTED_WITHOUT_RULING` | error (게이트가 먼저 닫는다) |
| 트리거 관측 가능 | `R_TRIGGER_NOT_OBSERVABLE` (`UNOBSERVABLE_PHRASES`) | error |
| 증거 12개월 초과 | `W_EVIDENCE_STALE` | warning |
| 증거 날짜가 `asof` 이후 | `R_EVIDENCE_FUTURE` | error |
| 저장값이 코드 재도출과 불일치 | `R_CONFIDENCE_RECOMPUTE`·`R_GATE_RECOMPUTE` | error |

enum 은 `msa.thesis` 가 단일 출처다 — 여기 이름(`ACTIONS`·`JUDGED`)은 그 재수출이다.

## 재도출 대조 (`_check_recompute`)

**스키마가 관문이다** (`CLAUDE.md` §5 의 정신). 저장된 `cycle_confidence` 와 `gate_result` 를
믿지 않고, 같은 파일에 적힌 `value_trap_axes`(+ 축1 블록)로 `gates.cycle_confidence()` 와
`gates.apply_gates()` 를 **다시 돌려** 대조한다. 불일치는 경고가 아니라 거부다 — 손으로 쓴 숫자든
변조든, 저장값이 규칙(`docs/04` §3·§4)의 산출이 아니라는 뜻이기 때문이다.

재도출에 **필요한데 thesis 에 없는 입력**이 있다 (전부 L1 산출물이고 스키마에 필드가 없다):

| 없는 입력 | 쓰이는 곳 | 여기서 |
|---|---|---|
| `capex_to_da_qtrs_below1` | 확신도 `+0.10` (축2) | `cycle_confidence_terms` 로 확정, 없으면 양쪽 |
| `small_sample` · `short_hist` | 확신도 `−0.10` | 좌동 |
| `cycle_class` | 게이트 `secular_risk` 분기 | `inputs.cycle_class` 로 확정, 없으면 양쪽 |

**없다는 사실은 경고(`W_*_INPUT_ABSENT`)이고 오류가 아니다.** 근거: 이 필드들은
`docs/specs/thesis.schema.yaml` 이 요구하지 않고, 사람이 쓴 논지(`docs/09` §2 · `docs/11` M6 —
"M6 구간에는 사람이 §4 규칙을 적용해 산출한다")에는 애초에 L1 스코어보드가 없다. 없다고 거부하면
선언되지 않은 필수 필드를 발명하는 것이 된다 (`CLAUDE.md` §1). 대신 **조용히 넘기지 않는다**
(`CLAUDE.md` §2) — 경고로 표시하고, 모르는 입력이 만들 수 있는 값을 **전부 열거해** 저장값이
그중 하나인지 본다. 열거는 규칙을 그대로 돌린 결과이지 새 허용 범위가 아니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from msa.coerce import opt_date
from msa.dates import months_between
from msa.errors import Rejected
from msa.l3.contracts import Axis1Inputs
from msa.l3.gates import (
    CAPEX_BELOW1_QTRS,
    AxisVerdicts,
    ConfidenceInputs,
    apply_gates,
    cycle_confidence,
)
from msa.status import Axis1Status
from msa.thesis import (
    AXES,
    AXIS_VERDICTS,
    GATE_STATUS,
    INVALIDATION_ACTIONS,
    JUDGED_VERDICTS,
    REJECTION_PATHS,
    RELIABILITY,
    SPEC_PATH,
    TRIGGER_STATUS,
    UNIT_SERIES_SOURCES,
    load_spec,
)

__all__ = [
    "ACTIONS",
    "AXES",
    "AXIS_VERDICTS",
    "CLAIM_MAX_LEN",
    "CONFIDENCE_RECOMPUTE_TOL",
    "CORRELATION_PHRASES",
    "EVIDENCE_STALE_MONTHS",
    "JUDGED",
    "NAME_CHECKED_FIELDS",
    "RELIABILITY",
    "SPEC_PATH",
    "UNOBSERVABLE_PHRASES",
    "ThesisRejected",
    "ValidationResult",
    "load_spec",
    "validate_thesis",
]

#: : `mechanism` 에서 금지하는 상관 서술 (선언. `docs/05` §4 "역사적으로 함께 움직였다 는
#: 메커니즘이 아니다").
CORRELATION_PHRASES: tuple[str, ...] = (
    "역사적으로 함께",
    "함께 움직",
    "같이 움직",
    "동행해 왔",
    "동행했",
    "상관관계",
    "상관이 높",
    "상관성",
    "과거에도 올랐",
    "과거 사이클에서도 올랐",
    "historically moved together",
    "correlat",
)

#: 트리거·무효화의 `observable` 로 인정하지 않는 어구 (선언. "심리 개선 같은 것은 트리거가 아니다").
UNOBSERVABLE_PHRASES: tuple[str, ...] = (
    "심리 개선",
    "심리가 개선",
    "분위기",
    "관심 증가",
    "관심이 높아",
    "센티먼트 개선",
    "모멘텀이 좋아",
    "시장의 인식",
    "재평가",
    "sentiment improve",
)

CLAIM_MAX_LEN = 400
EVIDENCE_STALE_MONTHS = 12

#: 종목 경계(`CLAUDE.md` §4)를 검사하는 서술 필드. `docs/05` §4 는 `claim` 만 예로 들지만 경계는
#: "에이전트는 테마만 고른다" 이지 "claim 에만 안 쓴다" 가 아니다 — 같은 이름을 `mechanism` 이나
#: `triggers` 에 쓰면 경계가 그대로 뚫린다. **등급은 §4 가 정한 경고 그대로다.**
#: 필드를 늘렸을 뿐 새 판정을 만들지 않았다.
NAME_CHECKED_FIELDS: tuple[str, ...] = (
    "claim",
    "mechanism",
    "triggers",
    "invalidations",
    "key_uncertainties",
)

#: 재도출 대조(`_check_recompute`)의 부동소수 허용오차. **판별 임계가 아니라 검증 도구의 수치
#: 여유다** — `docs/04` §4 의 항은 전부 0.05 단위이고 `cycle_confidence()` 는 `round(_, 4)` 로
#: 돌려주므로, 같은 규칙을 두 번 돌린 값의 차이는 float64 합산 오차(~1e-16)뿐이다. 1e-6 은 그
#: 오차보다 10자리 크고 가장 작은 항(0.05)보다 4자리 작아, 실제 항 하나의 차이를 절대 흡수하지
#: 않는다. 이 값을 키우거나 줄여도 어떤 판정도 바뀌지 않는다.
CONFIDENCE_RECOMPUTE_TOL = 1e-6
#: 증거 날짜로 허용하는 형식 — 일·월·연 단위.
EVIDENCE_DATE_FORMATS: tuple[str, ...] = ("%Y-%m-%d", "%Y-%m", "%Y")

# 옛 이름 — 다른 모듈이 `from msa.l3.schema import ACTIONS` 로 쓰던 것. 값은 `msa.thesis` 와 같다.
ACTIONS = INVALIDATION_ACTIONS
JUDGED = JUDGED_VERDICTS


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, code: str, msg: str) -> None:
        self.errors.append(f"{code}: {msg}")

    def warn(self, code: str, msg: str) -> None:
        self.warnings.append(f"{code}: {msg}")


class ThesisRejected(Rejected, ValueError):
    """스키마 미달 — 산출물이 불완전하다. 저장하지 않는다 (게이트 기각과 다르다, `docs/05` §4)."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        super().__init__("thesis 스키마 검증 실패:\n  - " + "\n  - ".join(result.errors))


def _evidence_date(v: Any) -> date | None:
    """`date` 또는 문자열(일·월·연)만 날짜로 읽는다 — 숫자(YAML 의 따옴표 없는 `2024`)는
    거부한다."""
    return opt_date(v, EVIDENCE_DATE_FORMATS) if isinstance(v, str | date) else None


def _contains_any(text: str, phrases: tuple[str, ...]) -> str | None:
    low = text.lower()
    for p in phrases:
        if p.lower() in low:
            return p
    return None


def _stock_mention(text: str, tickers: tuple[str, ...], names: tuple[str, ...]) -> list[str]:
    """구성원 티커(대문자 단어 경계) 또는 영문명이 `text` 에 등장하는가.

    한글 별칭("홈디포")은 잡지 못한다 — 별칭 사전을 만드는 것은 선언되지 않은 값을 발명하는
    것이라 하지 않는다 (`CLAUDE.md` §1). 대신 티커 검사를 서술 필드 전체로 넓혀 `HD`·`LOW` 같은
    표기는 어느 필드에 있든 잡히게 했다.
    """
    hits: list[str] = []
    for t in tickers:
        if len(t) >= 2 and re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", text):
            hits.append(t)
    low = text.lower()
    for n in names:
        n0 = n.strip()
        if len(n0) >= 4 and n0.lower() in low:
            hits.append(n0)
    return hits


def _field_text(value: Any) -> str:
    """서술 필드를 검사용 평문으로. 문자열은 그대로, 목록/매핑은 값을 이어 붙인다
    (`triggers[].observable` 처럼 중첩된 곳의 종목명도 보이게)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_field_text(v) for v in value.values())
    if isinstance(value, list | tuple):
        return " ".join(_field_text(v) for v in value)
    return ""


# ---------------------------------------------------------------- 부분 검사


def _check_required(r: ValidationResult, thesis: dict[str, Any], spec: dict[str, Any]) -> None:
    """required 는 스키마 파일에서 읽는다. 하나라도 빠지면 호출자가 거기서 끝낸다."""
    for k in spec.get("required", []):
        if k not in thesis or thesis[k] is None:
            r.error("R_REQUIRED", f"필수 필드 없음: {k}")


def _check_claim(
    r: ValidationResult,
    thesis: dict[str, Any],
    member_tickers: tuple[str, ...],
    member_names: tuple[str, ...],
) -> None:
    h = thesis["horizon_months"]
    if not (
        isinstance(h, list) and len(h) == 2 and all(isinstance(x, int) for x in h) and h[0] <= h[1]
    ):
        r.error("R_HORIZON", f"horizon_months 는 [min, max] 정수 2개여야 한다: {h!r}")

    claim = str(thesis["claim"])
    if not claim.strip():
        r.error("R_CLAIM_EMPTY", "claim 이 비었다")
    if len(claim) > CLAIM_MAX_LEN:
        r.error("R_CLAIM_TOO_LONG", f"claim {len(claim)}자 > {CLAIM_MAX_LEN}")
    for f in NAME_CHECKED_FIELDS:
        hit = _stock_mention(_field_text(thesis.get(f)), member_tickers, member_names)
        if hit:
            r.warn(
                "W_CLAIM_NAMES_STOCK",
                f"{f} 에 종목명/티커 등장: {sorted(set(hit))} "
                f"(CLAUDE.md §4 — 에이전트는 테마만)",
            )

    mech = str(thesis["mechanism"])
    if not mech.strip():
        r.error("R_MECHANISM_EMPTY", "mechanism 이 비었다")
    p = _contains_any(mech, CORRELATION_PHRASES)
    if p:
        r.error(
            "R_MECHANISM_CORRELATION",
            f"mechanism 에 상관 서술 어구 {p!r} — 인과 경로로 다시 쓴다 (05 §4)",
        )


def _check_evidence(r: ValidationResult, ev: Any, today: date) -> tuple[set[int], dict[int, str]]:
    """증거 배열 검사. 반환: (유효 id 집합, id → reliability) — 축·ruling 참조 검사에 쓴다."""
    ev_ids: set[int] = set()
    rel_of: dict[int, str] = {}
    if not isinstance(ev, list) or len(ev) == 0:
        r.error(
            "R_EVIDENCE_EMPTY", "evidence 가 비었다 — LLM 의 기억은 증거가 아니다 (CLAUDE.md §3)"
        )
        return ev_ids, rel_of
    for i, e in enumerate(ev):
        if not isinstance(e, dict):
            r.error("R_EVIDENCE_ITEM", f"evidence[{i}] 가 객체가 아니다")
            continue
        for k in ("id", "claim", "source_url", "date", "reliability"):
            if k not in e or e[k] in (None, ""):
                r.error("R_EVIDENCE_FIELD", f"evidence[{i}] 에 {k} 없음")
        if "id" in e and isinstance(e["id"], int):
            if e["id"] in ev_ids:
                r.error("R_EVIDENCE_DUP_ID", f"evidence id 중복: {e['id']}")
            ev_ids.add(e["id"])
            rel_of[e["id"]] = str(e.get("reliability"))
        if e.get("reliability") not in RELIABILITY:
            r.error(
                "R_EVIDENCE_RELIABILITY",
                f"evidence[{i}] reliability {e.get('reliability')!r} ∉ {RELIABILITY}",
            )
        url = str(e.get("source_url", ""))
        if url and not re.match(r"^(https?://|state/|file://)", url):
            r.warn(
                "W_EVIDENCE_URL",
                f"evidence[{i}] source_url 이 URL/경로 형식이 아니다: {url[:60]}",
            )
        d = _evidence_date(e.get("date"))
        if e.get("date") and d is None:
            r.error("R_EVIDENCE_DATE", f"evidence[{i}] date 를 읽을 수 없다: {e.get('date')!r}")
        elif d is not None and d > today:
            # 새 임계가 아니라 이미 있는 기준(`asof`)의 적용이다. 상한이 없으면 미래 정보가
            # 논지에 들어오고, 그대로 `docs/10` §4 캘리브레이션의 입력이 된다.
            r.error(
                "R_EVIDENCE_FUTURE",
                f"evidence[{e.get('id', i)}] 날짜 {d} 가 asof {today} 이후다 — "
                f"판정 시점에 존재하지 않은 정보다",
            )
        elif d is not None and months_between(d, today) > EVIDENCE_STALE_MONTHS:
            r.warn(
                "W_EVIDENCE_STALE",
                f"evidence[{e.get('id', i)}] 날짜 {d} — {EVIDENCE_STALE_MONTHS}개월 초과 (05 §6)",
            )
    return ev_ids, rel_of


def _check_observables(
    r: ValidationResult,
    items: Any,
    label: str,
    keys: tuple[str, ...],
    *,
    empty_msg: str,
    enum_key: str,
    enum: tuple[str, ...],
    enum_code: str,
    enum_default: str | None = None,
) -> None:
    """`triggers` / `invalidations` 공통 — 비면 거부, 항목마다 필수 키·enum·관측 가능성.

    `label` 은 `"triggers"`·`"invalidations"` 이고 오류 코드는 거기서 만든다
    (`R_TRIGGERS_EMPTY`·`R_TRIGGER_FIELD`). 관측 불가 어구 코드는 둘 다 `R_TRIGGER_NOT_OBSERVABLE`.
    """
    singular = label[:-1].upper()
    if not isinstance(items, list) or len(items) == 0:
        r.error(f"R_{label.upper()}_EMPTY", empty_msg)
        return
    for i, t in enumerate(items):
        for k in keys:
            if not isinstance(t, dict) or not str(t.get(k, "")).strip():
                r.error(f"R_{singular}_FIELD", f"{label}[{i}] 에 {k} 없음")
        if not isinstance(t, dict):
            continue
        v = t.get(enum_key, enum_default)
        if v not in enum:
            r.error(enum_code, f"{label}[{i}] {enum_key} {v!r} ∉ {enum}")
        p = _contains_any(str(t.get("observable", "")), UNOBSERVABLE_PHRASES)
        if p:
            r.error(
                "R_TRIGGER_NOT_OBSERVABLE",
                f"{label}[{i}] observable 에 {p!r} — 관측 가능하지 않다",
            )


def _check_axes(
    r: ValidationResult,
    thesis: dict[str, Any],
    ev_ids: set[int],
    rel_of: dict[int, str],
) -> None:
    axes = thesis["value_trap_axes"]
    if not isinstance(axes, dict):
        r.error("R_AXES", "value_trap_axes 가 객체가 아니다")
        axes = {}
    for a in AXES:
        if a not in axes or not isinstance(axes[a], dict):
            r.error("R_AXIS_MISSING", f"value_trap_axes.{a} 없음")
            continue
        ax = axes[a]
        v = ax.get("verdict")
        if v not in AXIS_VERDICTS:
            r.error("R_AXIS_VERDICT", f"{a}.verdict {v!r} ∉ {AXIS_VERDICTS}")
        refs = ax.get("evidence_refs", [])
        if not isinstance(refs, list):
            r.error("R_AXIS_REFS", f"{a}.evidence_refs 가 배열이 아니다")
            refs = []
        dangling = [x for x in refs if x not in ev_ids]
        if dangling:
            r.error(
                "R_AXIS_REFS_DANGLING", f"{a}.evidence_refs 가 없는 증거를 가리킨다: {dangling}"
            )
        if v in JUDGED_VERDICTS:
            if not refs:
                r.error(
                    "R_AXIS_NO_EVIDENCE",
                    f"{a}: 판정 {v} 인데 evidence_refs 가 비었다 (CLAUDE.md §3)",
                )
            elif not any(rel_of.get(x) in ("high", "medium") for x in refs):
                r.error(
                    "R_AXIS_LOW_RELIABILITY_ONLY",
                    f"{a}: low 등급 증거만으로 판정 불가 — medium 이상 1개 필요 (05 §4)",
                )
    ud = axes.get("unit_demand", {})
    if isinstance(ud, dict) and ud:
        _check_unit_demand(r, thesis, ud)


def _check_unit_demand(r: ValidationResult, thesis: dict[str, Any], ud: dict[str, Any]) -> None:
    """축 1 의 일관성 — `axis1_available` · `unit_series_source` · `axis1_contested` (04 축1 적용
    범위 · §3.1)."""
    avail = ud.get("axis1_available")
    src = ud.get("unit_series_source")
    if not isinstance(avail, bool):
        r.error("R_AXIS1_AVAILABLE", "unit_demand.axis1_available 은 bool 이어야 한다")
    if src not in UNIT_SERIES_SOURCES:
        r.error("R_AXIS1_SOURCE", f"unit_demand.unit_series_source {src!r}")
    if avail is False:
        if ud.get("verdict") != "not_applicable":
            r.error("R_AXIS1_NA", "axis1_available=false 면 verdict 는 not_applicable 이어야 한다")
        if src != "none":
            r.error(
                "R_AXIS1_NA_SOURCE",
                "axis1_available=false 면 unit_series_source 는 none 이어야 한다",
            )
        ku = thesis.get("key_uncertainties") or []
        if not any("axis1_available" in str(x) for x in ku):
            r.error(
                "R_AXIS1_NA_UNCERTAINTY",
                "axis1_available=false 는 key_uncertainties 에 명시해야 한다 (04 축1 적용 범위)",
            )
    elif avail is True and src == "none":
        r.error(
            "R_AXIS1_SOURCE_NONE",
            "axis1_available=true 면 unit_series_source 는 none 일 수 없다",
        )
    if ud.get("axis1_contested") is True and ud.get("verdict") != "contested":
        r.error(
            "R_AXIS1_CONTESTED_VERDICT",
            "axis1_contested=true 면 verdict 는 contested 여야 한다 (04 §3.1)",
        )
    # 스펙이 선언한 파생: axis1_contested = (verdict_pre_ss != verdict_post_ss) or sign_split
    # (`docs/specs/thesis.schema.yaml` axis1_contested note · `docs/04` §3.1). 입력 셋이 파일에
    # 다 있을 때만 대조한다 — 없는 것을 요구하지는 않는다.
    pre, post = ud.get("verdict_pre_ss"), ud.get("verdict_post_ss")
    if isinstance(pre, str) and isinstance(post, str) and "axis1_contested" in ud:
        derived = pre != post or bool(ud.get("sign_split"))
        if bool(ud.get("axis1_contested")) != derived:
            r.error(
                "R_AXIS1_CONTESTED_DERIVED",
                f"axis1_contested={ud.get('axis1_contested')!r} 인데 "
                f"pre={pre} · post={post} · sign_split={ud.get('sign_split')!r} 로 다시 계산하면 "
                f"{derived} 다 (스키마 axis1_contested note)",
            )


def _check_gate(r: ValidationResult, g: Any, ev_ids: set[int]) -> None:
    if not isinstance(g, dict):
        r.error("R_GATE_MISSING", "gate_result 없음")
        return
    st = g.get("status")
    if st not in GATE_STATUS:
        r.error("R_GATE_STATUS", f"gate_result.status {st!r}")
    if st in ("contested", "rejected") and g.get("portfolio_eligible") is not False:
        r.error("R_GATE_ELIGIBLE", f"status={st} 면 portfolio_eligible 은 반드시 false")
    if st == "contested":
        if not str(g.get("referee_ruling") or "").strip():
            r.error(
                "R_CONTESTED_WITHOUT_RULING",
                "contested 인데 referee_ruling 없음 → 기각으로 닫아야 한다 (04 §3.1)",
            )
        refs = g.get("referee_evidence_refs") or []
        if not refs:
            r.error("R_CONTESTED_WITHOUT_RULING", "contested 인데 referee_evidence_refs 비어 있음")
        elif any(x not in ev_ids for x in refs):
            r.error(
                "R_CONTESTED_REFS_DANGLING",
                f"referee_evidence_refs 가 없는 증거를 가리킨다: "
                f"{[x for x in refs if x not in ev_ids]}",
            )
    if st == "rejected" and g.get("path") not in REJECTION_PATHS:
        r.error("R_GATE_PATH", f"rejected 인데 path {g.get('path')!r} 가 대장 enum 이 아니다")
    av = g.get("axis_verdicts")
    if not isinstance(av, dict) or any(a not in av for a in AXES):
        r.error("R_GATE_SNAPSHOT", "gate_result.axis_verdicts 5축 스냅샷 없음 (10 §5)")


# ------------------------------------------------- 재도출 대조 (저장값 vs 코드)


def _axis_verdicts(axes: Any) -> AxisVerdicts | None:
    """저장된 5축 verdict → `AxisVerdicts`. 하나라도 enum 밖이면 None (그건 이미 다른 규칙이
    거부했다 — 여기서 두 번 말하지 않는다)."""
    if not isinstance(axes, dict):
        return None
    vals: dict[str, str] = {}
    for a in AXES:
        ax = axes.get(a)
        v = ax.get("verdict") if isinstance(ax, dict) else None
        if v not in AXIS_VERDICTS:
            return None
        vals[a] = str(v)
    return AxisVerdicts(**vals)


def _axis1_inputs(ud: dict[str, Any]) -> Axis1Inputs:
    """저장된 축1 블록 → `Axis1Inputs`. 게이트 재도출이 실제로 읽는 것은 `contested` 뿐이고
    나머지는 reason 문자열에만 쓰인다. `axis1_status` 는 `Axis1Inputs.unit_series_source` 가
    선언한 대응(`ok_external`↔`physical_series` · `ok_fallback`↔`revenue_proxy`)의 역이다."""
    src = ud.get("unit_series_source")
    if ud.get("axis1_available") is False:
        status = str(ud.get("axis1_status") or Axis1Status.DATA_MISSING)
    elif src == "physical_series":
        status = str(Axis1Status.OK_EXTERNAL)
    elif src == "revenue_proxy":
        status = str(Axis1Status.OK_FALLBACK)
    else:
        status = str(Axis1Status.DATA_MISSING)
    return Axis1Inputs(
        axis1_status=status,
        unit_source=opt_str_or_none(ud.get("unit_source")),
        verdict_pre_ss=opt_str_or_none(ud.get("verdict_pre_ss")),
        verdict_post_ss=opt_str_or_none(ud.get("verdict_post_ss")),
        unit_cagr_10y=_opt_num(ud.get("unit_cagr_10y")),
        unit_cagr_5y=_opt_num(ud.get("unit_cagr_5y")),
        unit_cagr_10y_median=_opt_num(ud.get("unit_cagr_10y_median")),
        sign_split=None if ud.get("sign_split") is None else bool(ud.get("sign_split")),
        ss_n=None,
        ss_coverage=None,
        ma_flag=None if ud.get("ma_flag") is None else bool(ud.get("ma_flag")),
        exit_count=None,
    )


def opt_str_or_none(v: Any) -> str | None:
    return str(v) if isinstance(v, str) and v.strip() else None


def _opt_num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _confidence_candidates(
    thesis: dict[str, Any], v: AxisVerdicts
) -> tuple[list[float], list[str]]:
    """저장된 축 판정으로 `cycle_confidence()` 를 다시 돌린 값들 + 확정하지 못한 입력 이름.

    thesis 에 없는 L1 입력(축2 분기수 · 소표본/짧은이력)은 `cycle_confidence_terms`(기계 산출물이
    적는 적용 항 목록)로 확정하고, 그것도 없으면 **두 경우를 다 돌려** 후보로 남긴다.
    """
    axes = thesis["value_trap_axes"]
    cc = axes.get("cost_curve") if isinstance(axes, dict) else None
    tr = axes.get("terminal_risk") if isinstance(axes, dict) else None
    terms = thesis.get("cycle_confidence_terms")
    absent: list[str] = []
    if isinstance(terms, dict):
        qtrs = [float(CAPEX_BELOW1_QTRS) if "axis2_capex_below1_8q" in terms else 0.0]
        smalls = [bool("small_sample_or_short_hist" in terms)]
    else:
        absent.append("capex_to_da_qtrs_below1 · small_sample · short_hist (L1 스코어보드)")
        qtrs = [0.0, float(CAPEX_BELOW1_QTRS)]
        smalls = [False, True]
    out: set[float] = set()
    for q in qtrs:
        for s in smalls:
            out.add(
                cycle_confidence(
                    ConfidenceInputs(
                        verdicts=v,
                        capex_to_da_qtrs_below1=q,
                        # 축4 '강한 사이클'·축5 '심각' 은 referee 산출이고 thesis 에 그대로
                        # 실린다 (`l3/pipeline._axis_block` 이 남는 키를 옮긴다). 없으면
                        # false — 파이프라인이 쓰는 기본값과 같다.
                        axis4_strong_cycle=bool(cc.get("strong_cycle", False))
                        if isinstance(cc, dict)
                        else False,
                        axis5_severe=bool(tr.get("severe", False))
                        if isinstance(tr, dict)
                        else False,
                        small_sample=s,
                        short_hist=False,
                    )
                ).value
            )
    return sorted(out), absent


def _gate_candidates(
    thesis: dict[str, Any],
    v: AxisVerdicts,
    g: dict[str, Any],
    ev_ids: set[int],
    confidence: float,
) -> tuple[list[tuple[str, bool, str | None]], list[str]]:
    """저장된 입력으로 `apply_gates()` 를 다시 돌린 (status, portfolio_eligible, path) 후보들."""
    axes = thesis["value_trap_axes"]
    ud = axes.get("unit_demand") if isinstance(axes, dict) else None
    tr = axes.get("terminal_risk") if isinstance(axes, dict) else None
    refs = tuple(int(x) for x in (g.get("referee_evidence_refs") or []) if isinstance(x, int))
    ruling = g.get("referee_ruling")
    blk = thesis.get("inputs")
    absent: list[str] = []
    if isinstance(blk, dict) and blk.get("cycle_class") is not None:
        seculars = [str(blk["cycle_class"]) == "secular_risk"]
    else:
        absent.append("inputs.cycle_class (secular_risk 여부 — L1 스코어보드)")
        seculars = [False, True]
    out: list[tuple[str, bool, str | None]] = []
    for sec in seculars:
        gr = apply_gates(
            v,
            _axis1_inputs(ud if isinstance(ud, dict) else {}),
            confidence=confidence,
            referee_ruling=str(ruling) if ruling and str(ruling).strip() else None,
            referee_evidence_refs=refs,
            referee_refs_valid=all(x in ev_ids for x in refs),
            secular_risk=sec,
            debt_24m_over_half=bool(tr.get("debt_maturity_24m_over_half", False))
            if isinstance(tr, dict)
            else False,
        )
        out.append((gr.status, gr.portfolio_eligible, gr.path))
    return out, absent


def _check_recompute(r: ValidationResult, thesis: dict[str, Any], ev_ids: set[int]) -> None:
    """저장된 `cycle_confidence` · `gate_result` 를 코드로 다시 도출해 대조 (모듈 docstring)."""
    v = _axis_verdicts(thesis.get("value_trap_axes"))
    if v is None:
        return  # 축 판정 자체가 깨졌다 — `_check_axes` 가 이미 거부했다
    g = thesis.get("gate_result")
    g = g if isinstance(g, dict) else {}

    # (1) gate_result.axis_verdicts 스냅샷은 value_trap_axes 의 복사본이어야 한다 (스펙 note)
    av = g.get("axis_verdicts")
    if isinstance(av, dict):
        body = v.as_dict()
        bad = {a: (av.get(a), body[a]) for a in AXES if av.get(a) != body[a]}
        if bad:
            r.error(
                "R_GATE_VERDICTS_MISMATCH",
                f"gate_result.axis_verdicts 가 value_trap_axes 와 다르다 "
                f"(축: 스냅샷 → 본문) {bad} — 스냅샷은 복사본이다 (스키마 axis_verdicts note)",
            )

    # (2) cycle_confidence 재도출
    stored_c = thesis.get("cycle_confidence")
    if isinstance(stored_c, int | float) and not isinstance(stored_c, bool):
        cands, absent = _confidence_candidates(thesis, v)
        for a in absent:
            r.warn("W_CONFIDENCE_INPUT_ABSENT", f"확신도 재도출 입력이 thesis 에 없다: {a}")
        if not any(abs(float(stored_c) - c) <= CONFIDENCE_RECOMPUTE_TOL for c in cands):
            r.error(
                "R_CONFIDENCE_RECOMPUTE",
                f"저장된 cycle_confidence {stored_c} 는 이 파일의 축 판정으로 docs/04 §4 를 다시 "
                f"돌린 값 {cands} 중 어느 것도 아니다 — 규칙의 산출이 아니다 (CLAUDE.md §1)",
            )

    # (3) gate_result 재도출 — 저장된 확신도를 그대로 넣는다 (게이트는 c 의 함수다)
    if not g:
        return
    c_for_gate = float(stored_c) if isinstance(stored_c, int | float) else 0.0
    cands_g, absent_g = _gate_candidates(thesis, v, g, ev_ids, c_for_gate)
    for a in absent_g:
        r.warn("W_GATE_INPUT_ABSENT", f"게이트 재도출 입력이 thesis 에 없다: {a}")
    st, el, path = g.get("status"), g.get("portfolio_eligible"), g.get("path")
    if isinstance(el, bool):
        if (st, el, path) not in cands_g:
            r.error(
                "R_GATE_RECOMPUTE",
                f"저장된 gate_result (status={st!r}, portfolio_eligible={el!r}, path={path!r}) 는 "
                f"이 파일의 축 판정으로 docs/04 §3 을 다시 돌린 결과 {cands_g} 중 어느 것도 "
                f"아니다",
            )
    else:
        r.error("R_GATE_ELIGIBLE_MISSING", "gate_result.portfolio_eligible 이 bool 이 아니다")
        if (st, path) not in [(a, c) for a, _b, c in cands_g]:
            r.error(
                "R_GATE_RECOMPUTE",
                f"저장된 gate_result (status={st!r}, path={path!r}) 가 재도출 결과 "
                f"{[(a, c) for a, _b, c in cands_g]} 와 다르다",
            )


# ---------------------------------------------------------------- 진입점


def validate_thesis(
    thesis: dict[str, Any],
    *,
    asof: str | None = None,
    member_tickers: tuple[str, ...] = (),
    member_names: tuple[str, ...] = (),
    bear_case_original: str | None = None,
    spec: dict[str, Any] | None = None,
) -> ValidationResult:
    """스키마 + §4 규약 검증. `bear_case_original` 을 주면 원문 보존을 대조한다."""
    r = ValidationResult()
    spec = spec or load_spec()
    today = _evidence_date(asof) or date.today()

    _check_required(r, thesis, spec)
    if r.errors:
        return r

    _check_claim(r, thesis, member_tickers, member_names)
    ev_ids, rel_of = _check_evidence(r, thesis["evidence"], today)
    _check_observables(
        r,
        thesis["triggers"],
        "triggers",
        ("observable", "source", "by"),
        empty_msg="triggers 가 비었다 — 맞았는지 판정할 수 없다 (10 §3)",
        enum_key="status",
        enum=TRIGGER_STATUS,
        enum_code="R_TRIGGER_STATUS",
        enum_default="pending",
    )
    _check_observables(
        r,
        thesis["invalidations"],
        "invalidations",
        ("observable", "source", "action"),
        empty_msg="invalidations 가 비었다 — 무효화 조건이 곧 Tier-1 스탑 (CLAUDE.md §5)",
        enum_key="action",
        enum=INVALIDATION_ACTIONS,
        enum_code="R_INVALIDATION_ACTION",
    )

    bc = str(thesis["bear_case"])
    if not bc.strip():
        r.error("R_BEAR_CASE_EMPTY", "bear_case 가 비었다")
    if bear_case_original is not None and bc.strip() != bear_case_original.strip():
        r.error("R_BEAR_CASE_NOT_VERBATIM", "bear_case 가 bear 원문과 다르다 — 요약 금지 (05 §4)")

    _check_axes(r, thesis, ev_ids, rel_of)
    _check_gate(r, thesis.get("gate_result"), ev_ids)

    c = thesis["cycle_confidence"]
    if not isinstance(c, int | float) or not (0.0 <= float(c) <= 1.0):
        r.error("R_CONFIDENCE_RANGE", f"cycle_confidence {c!r} ∉ [0, 1]")

    _check_recompute(r, thesis, ev_ids)

    if not thesis.get("key_uncertainties"):
        r.warn(
            "W_NO_UNCERTAINTIES",
            "key_uncertainties 가 비었다 — '비어 있으면 의심하라' (스키마 note)",
        )
    return r
