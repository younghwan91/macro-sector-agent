"""수급 균형 문서의 계약·검증·저장·회전 선정. 순수 함수, 네트워크 모름.

설계·금지는 `docs/26-design-question-supply-demand-balance.md`.

## 이 모듈이 지키는 것 셋

1. **가격을 말하지 않는다.** 스키마에 목표가·기대수익을 담을 칸이 없다. 수급이 타이트한
   것과 주가가 오르는 것은 다른 명제이고, 후자를 말하는 순간 `docs/15` 가 닫은 문이 열린다.
2. **공급 경직성은 `RIGIDITY_KINDS` 다섯 중 하나로 분류한다.** 자유 서술만 받으면 "공급이
   제한적이다" 라는 동어반복이 들어온다.
3. **`what_would_close_it` 이 비면 저장 거부.** "수요가 공급을 앞지른다" 는 주장은 그 격차가
   **어떻게 메워지는가**를 함께 말해야 한다. 안 그러면 영구 부족이라는 주장이 되고, 그건
   자본주의에서 거의 항상 틀린다.

## 점수에 들어가지 않는다

트리아지의 J·C·R 어디에도 안 들어간다 (`docs/26` §3.5). 수급이 타이트하다고 차트를 먼저
열어야 할 이유가 없다 — 오히려 이미 오른 뒤일 수 있다. 이 계층의 산출은 **명단이 아니라
논지**이고, 사람이 읽는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from msa.errors import Rejected

#: 수요 판정 3값.
DEMAND_VERDICTS = ("expanding", "flat", "contracting")

#: 공급 판정 3값. `constrained` 는 **경직성 근거를 요구한다**.
SUPPLY_VERDICTS = ("constrained", "elastic", "expanding")

#: 균형 판정 3값.
BALANCE_VERDICTS = ("tightening", "balanced", "loosening")

#: **공급이 왜 못 늘어나는가** — 다섯 유형. 늘리지 않는다 (`docs/26` §5).
#: 늘리면 "공급이 제한적이다" 의 동의어가 쌓이고 분류의 뜻이 없어진다.
RIGIDITY_KINDS = (
    "byproduct",  # 다른 금속·제품의 부산물이라 독립 증산 불가 (예: 은)
    "lead_time",  # 신규 공급까지 물리적 시간 (광산 7~10년 · fab 3년)
    "permitting",  # 허가·환경 규제 병목
    "capital",  # 자본이 안 들어옴 (수익성·ESG·주주 압력)
    "resource_depletion",  # 품위 저하·매장량 고갈
)

#: 조사가 낡았다고 보는 기간. **선언값이다** — 90 이어야 할 근거는 없고, "수급 구조는 분기
#: 단위로도 잘 안 바뀐다" 는 서술을 옮긴 것뿐이다. 결과를 보고 옮기지 않는다.
BALANCE_STALE_DAYS = 90

#: `cagr_pct` 의 위생 상한 — **판정 임계가 아니라 단위 오류 탐지기다.**
#:
#: 2026-08-29 실측에서 에이전트가 "-0.9%" 를 `-0.9` 로 썼는데 스키마는 비율(0.04=4%)을
#: 뜻했다. 리포트가 **-90%** 로 찍혔다. 원인은 단위가 모호했던 것이고, 그래서 필드를
#: 퍼센트 포인트로 바꿨다. 이 상한은 반대 방향의 실수(4% 를 0.04 로 쓰는 것)를 못 잡는다 —
#: 그건 100 이 아니라 **1 미만**으로 들어오므로, 아래 `_SUSPICIOUS_RATIO` 가 따로 본다.
#:
#: `docs/24` 의 필터 상수가 아니다: 판정을 만들지 않고 **입력을 거부**할 뿐이다
#: (`TTM_MAX_SPAN_DAYS` 같은 데이터 위생 상수와 같은 취급).
CAGR_PCT_MAX = 100.0

#: 이 절댓값보다 작고 0 이 아닌 값은 **비율로 잘못 쓴 것을 의심**한다. 실물 수요·공급이
#: 연 0.05%p 씩 움직인다는 판정은 의미가 없고, 0.04(=4%)를 그대로 넣었을 가능성이 훨씬 크다.
_SUSPICIOUS_RATIO = 0.1

_URL = re.compile(r"^https?://\S+$")


class BalanceRejected(Rejected, ValueError):
    """수급 문서가 계약을 어겼다 — 저장하지 않는다."""


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "unit": {
            "type": "string",
            "description": "실물 단위 (톤·온스·TEU·MWh…). **매출을 쓰지 않는다**",
        },
        "horizon_years": {"type": "integer"},
        "demand": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": list(DEMAND_VERDICTS)},
                "drivers": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "direction": {"type": "string", "enum": ["up", "flat", "down"]},
                            "magnitude": {
                                "type": "string",
                                "description": "실물 단위로. 가격·수익률 금지",
                            },
                            "evidence_ids": {"type": "array", "items": {"type": "integer"}},
                        },
                        "required": ["name", "direction", "magnitude", "evidence_ids"],
                    },
                },
                "cagr_pct": {
                    "type": ["number", "null"],
                    "description": (
                        "실물 단위 기준 연평균 증가율 — **퍼센트 포인트 단위**. "
                        "4% 는 `4.0`, -0.9% 는 `-0.9` 로 쓴다. 비율(0.04)로 쓰지 마라. "
                        "**모르면 null — 0 이 아니다**"
                    ),
                },
            },
            "required": ["verdict", "drivers", "cagr_pct"],
        },
        "supply": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": list(SUPPLY_VERDICTS)},
                "rigidity": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": list(RIGIDITY_KINDS)},
                            "note": {"type": "string"},
                            "evidence_ids": {"type": "array", "items": {"type": "integer"}},
                        },
                        "required": ["kind", "note", "evidence_ids"],
                    },
                    "description": "`constrained` 이면 **최소 1건 필수**",
                },
                "new_capacity_3y": {
                    "type": "string",
                    "description": "**확정(FID)된 증설만.** 발표·구상은 세지 않는다",
                },
                "cagr_pct": {
                    "type": ["number", "null"],
                    "description": "퍼센트 포인트 단위 (수요와 같다). 모르면 null",
                },
            },
            "required": ["verdict", "rigidity", "new_capacity_3y", "cagr_pct"],
        },
        "balance": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": list(BALANCE_VERDICTS)},
                "ratio_note": {"type": "string", "description": "수요·공급 증가율의 차. 가격 금지"},
                "what_would_close_it": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "**무엇이 이 격차를 메우나.** `tightening` 이면 필수",
                },
                "who_captures_it": {
                    "type": "string",
                    "description": (
                        "**이 격차를 누가 가져가는가.** `tightening` 이면 필수. "
                        "'아무도' 라면 그것은 타이트가 아니라 **산업의 축소**다 — "
                        "그때는 verdict 를 loosening 이나 balanced 로 고쳐라"
                    ),
                },
                "invalidations": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                },
            },
            "required": [
                "verdict",
                "ratio_note",
                "what_would_close_it",
                "who_captures_it",
                "invalidations",
            ],
        },
        "evidence": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "claim": {"type": "string"},
                    "source_url": {"type": "string"},
                    "date": {"type": "string"},
                    "reliability": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["id", "claim", "source_url", "date"],
            },
        },
    },
    "required": ["unit", "horizon_years", "demand", "supply", "balance", "evidence"],
}


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise BalanceRejected(msg)


def _check_cagr(label: str, block: Mapping[str, Any]) -> None:
    """`cagr_pct` 의 **단위**를 검사한다. 값의 좋고 나쁨은 보지 않는다."""
    raw = block.get("cagr_pct")
    if raw is None:
        return
    v = float(raw)
    _need(
        abs(v) <= CAGR_PCT_MAX,
        f"{label}.cagr_pct 가 ±{CAGR_PCT_MAX:.0f}%p 를 넘는다: {v} — 퍼센트 포인트 단위다",
    )
    _need(
        v == 0.0 or abs(v) >= _SUSPICIOUS_RATIO,
        f"{label}.cagr_pct 가 {v} 다 — **비율로 잘못 쓴 것으로 보인다.** "
        f"4% 는 0.04 가 아니라 4.0 이다. 실물 물량이 연 {abs(v):.3f}%p 움직인다는 판정이 "
        "정말 맞다면 null 로 두고 ratio_note 에 서술해라",
    )


def validate(doc: Mapping[str, Any]) -> None:
    """수급 문서를 검증한다. 어기면 `BalanceRejected` — 저장 전에 부른다."""
    _need(bool(str(doc.get("theme") or "").strip()), "theme 이 비었다")
    _need(
        bool(str(doc.get("unit") or "").strip()),
        "unit 이 비었다 — 실물 단위가 없는 테마는 이 조사를 하지 않는다. "
        "매출을 물량인 척 쓰면 축 1 이 이미 폴백으로 강등한 실수를 반복한다 (docs/26 §6.2)",
    )

    ev = list(doc.get("evidence") or [])
    _need(bool(ev), "evidence 가 비었다 — LLM 의 기억은 증거가 아니다 (CLAUDE.md §3)")
    ids: set[int] = set()
    for i, e in enumerate(ev):
        _need(
            _URL.match(str((e or {}).get("source_url") or "")) is not None,
            f"evidence[{i}] 의 source_url 이 URL 이 아니다",
        )
        _need(bool(str((e or {}).get("claim") or "").strip()), f"evidence[{i}] 의 claim 이 비었다")
        ids.add(int((e or {}).get("id", -1)))

    demand = doc.get("demand") or {}
    _need(demand.get("verdict") in DEMAND_VERDICTS, f"demand.verdict 는 {DEMAND_VERDICTS} 중 하나")
    _check_cagr("demand", demand)
    drivers = list(demand.get("drivers") or [])
    _need(bool(drivers), "demand.drivers 가 비었다 — 무엇이 수요를 미는지 적어야 한다")

    supply = doc.get("supply") or {}
    _need(supply.get("verdict") in SUPPLY_VERDICTS, f"supply.verdict 는 {SUPPLY_VERDICTS} 중 하나")
    _check_cagr("supply", supply)
    rigidity = list(supply.get("rigidity") or [])
    if supply.get("verdict") == "constrained":
        _need(
            bool(rigidity),
            "supply.rigidity 가 비었다 — '제한적이다' 라고만 하고 왜인지 안 적으면 "
            "동어반복이다 (docs/26 §3.3 규칙 2)",
        )
    for i, r in enumerate(rigidity):
        _need(
            (r or {}).get("kind") in RIGIDITY_KINDS,
            f"supply.rigidity[{i}].kind 는 {RIGIDITY_KINDS} 중 하나여야 한다 — "
            "유형을 늘리면 '공급이 제한적이다' 의 동의어가 쌓인다 (docs/26 §5)",
        )
        _need(bool(str((r or {}).get("note") or "").strip()), f"rigidity[{i}].note 가 비었다")

    bal = doc.get("balance") or {}
    _need(bal.get("verdict") in BALANCE_VERDICTS, f"balance.verdict 는 {BALANCE_VERDICTS} 중 하나")
    _need(
        bool(list(bal.get("invalidations") or [])),
        "balance.invalidations 가 비었다 — 무효화 조건 없는 판정은 판정이 아니라 희망이다 "
        "(CLAUDE.md §5)",
    )
    if bal.get("verdict") == "tightening":
        _need(
            bool(str(bal.get("who_captures_it") or "").strip()),
            "balance.who_captures_it 이 비었다 — **이 격차를 누가 가져가는가.** "
            "2026-08-29 실측에서 managed_care 가 tightening 으로 나왔는데 분석가 스스로 "
            "'격차의 실체는 초과수요가 아니라 무보험 전환' 이라고 적었다: 줄어드는 공급이 "
            "곧 이 산업 자체의 축소였고, 그 격차를 가져가는 주체가 없었다. "
            "가져가는 주체가 없으면 그것은 타이트가 아니라 축소다 (docs/26 §3.3 규칙 4)",
        )
        _need(
            bool(list(bal.get("what_would_close_it") or [])),
            "balance.what_would_close_it 이 비었다 — '벌어진다' 는 그 격차가 **어떻게 "
            "메워지는가**를 함께 말해야 한다. 안 그러면 영구 부족이라는 주장이 되고 "
            "그건 자본주의에서 거의 항상 틀린다 (docs/26 §3.3 규칙 3)",
        )

    # 근거 번호가 실재하는지 — 없는 번호를 가리키면 그 주장은 출처가 없는 것이다
    for label, rows in (("demand.drivers", drivers), ("supply.rigidity", rigidity)):
        for i, r in enumerate(rows):
            for rid in (r or {}).get("evidence_ids") or []:
                _need(
                    int(rid) in ids,
                    f"{label}[{i}] 의 evidence_ids 가 없는 번호를 가리킨다: {rid} (있는 것: "
                    f"{sorted(ids)})",
                )


def path_for(root: Path, theme: str) -> Path:
    return Path(root) / f"{theme}.balance.yaml"


def write(root: Path, doc: Mapping[str, Any]) -> Path:
    """검증 후 저장. 같은 테마를 다시 조사하면 덮어쓴다 — 수급 구조는 시점의 판단이고
    이력은 `journal/` 이 진다."""
    validate(doc)
    p = path_for(root, str(doc["theme"]))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(dict(doc), allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def read(root: Path, theme: str) -> dict[str, Any] | None:
    p = path_for(root, theme)
    if not p.exists():
        return None
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    return dict(raw) if isinstance(raw, Mapping) else None


def _asof(doc: Mapping[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(doc.get("asof")))
    except (TypeError, ValueError):
        return None


def is_stale(doc: Mapping[str, Any] | None, *, today: date) -> bool:
    """조사가 낡았나. **문서가 없으면 낡은 것이 아니라 없는 것**이고, 그 구분은 호출자가 한다."""
    if not doc:
        return False
    d = _asof(doc)
    if d is None:
        return True  # 날짜를 못 읽으면 믿지 않는다
    return (today - d).days > BALANCE_STALE_DAYS


def rotation(
    root: Path, themes: Iterable[str], *, n: int, today: date
) -> list[str]:
    """다음에 조사할 테마 — **조사 없는 것 먼저, 그다음 가장 낡은 것.**

    `n` 은 한 번에 부를 개수다. 134 테마를 다 돌지 않는 것이 설계이지 제약이 아니다
    (`docs/26` §3.4). 신선한 조사가 있는 테마는 아예 후보가 아니다.
    """
    if n <= 0:
        return []
    missing: list[str] = []
    stale: list[tuple[date, str]] = []
    for t in themes:
        doc = read(root, t)
        if doc is None:
            missing.append(str(t))
            continue
        if is_stale(doc, today=today):
            d = _asof(doc)
            stale.append((d or date.min, str(t)))
    stale.sort()
    return [*sorted(missing), *[t for _, t in stale]][:n]


def summarize_theme(doc: Mapping[str, Any] | None, *, today: date | None = None) -> str:
    """리포트 한 줄. **조사가 없으면 '중립' 이 아니라 '없음' 이다** (`docs/26` §5)."""
    if not doc:
        return "수급 조사 없음 — 조사를 안 했다는 뜻이지 수급이 중립이라는 뜻이 아니다"
    bal = doc.get("balance") or {}
    dem = (doc.get("demand") or {}).get("verdict")
    sup = (doc.get("supply") or {}).get("verdict")
    age = ""
    if today is not None:
        d = _asof(doc)
        if d is not None:
            days = (today - d).days
            age = f" · {days}일 전" + (" **(낡음)**" if days > BALANCE_STALE_DAYS else "")
    return (
        f"`{doc.get('theme')}` 수급 **{bal.get('verdict')}** "
        f"(수요 {dem} / 공급 {sup}){age} — {bal.get('ratio_note', '')}"
    )


def declared_constants() -> dict[str, Any]:
    return {
        "balance_stale_days": BALANCE_STALE_DAYS,
        "rigidity_kinds": list(RIGIDITY_KINDS),
        "cadence": "회전 — 한 번에 1~3 테마. 134 전수 조사를 자동화하지 않는다 (docs/26 §3.4)",
        "effect": "**트리아지 점수에 들어가지 않는다** — 논지를 준다 (docs/26 §3.5)",
        "claim": "물량 대 물량. 가격·수익률을 말하지 않는다",
    }


def summarize(docs: Sequence[Mapping[str, Any]]) -> str:
    if not docs:
        return "수급 조사 0건"
    counts = {
        v: sum(1 for d in docs if (d.get("balance") or {}).get("verdict") == v)
        for v in BALANCE_VERDICTS
    }
    return "수급 조사 " + " · ".join(f"{k} {counts[k]}" for k in BALANCE_VERDICTS)
