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
| 종목명이 `claim` 에 등장 | `W_CLAIM_NAMES_STOCK` | warning |
| `reliability: low` 만으로 축 판정 불가 | `R_AXIS_LOW_RELIABILITY_ONLY` | error |
| contested 는 ruling + refs 필요 | `R_CONTESTED_WITHOUT_RULING` | error (게이트가 먼저 닫는다) |
| 트리거 관측 가능 | `R_TRIGGER_NOT_OBSERVABLE` (`UNOBSERVABLE_PHRASES`) | error |
| 증거 12개월 초과 | `W_EVIDENCE_STALE` | warning |

enum 은 `msa.thesis` 가 단일 출처다 — 여기 이름(`ACTIONS`·`JUDGED`)은 그 재수출이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from msa.coerce import opt_date
from msa.dates import months_between
from msa.errors import Rejected
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
    "CORRELATION_PHRASES",
    "EVIDENCE_STALE_MONTHS",
    "JUDGED",
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


def _stock_mention(claim: str, tickers: tuple[str, ...], names: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for t in tickers:
        if len(t) >= 2 and re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", claim):
            hits.append(t)
    low = claim.lower()
    for n in names:
        n0 = n.strip()
        if len(n0) >= 4 and n0.lower() in low:
            hits.append(n0)
    return hits


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
    hit = _stock_mention(claim, member_tickers, member_names)
    if hit:
        r.warn(
            "W_CLAIM_NAMES_STOCK",
            f"claim 에 종목명/티커 등장: {hit} (CLAUDE.md §4 — 에이전트는 테마만)",
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

    if not thesis.get("key_uncertainties"):
        r.warn(
            "W_NO_UNCERTAINTIES",
            "key_uncertainties 가 비었다 — '비어 있으면 의심하라' (스키마 note)",
        )
    return r
