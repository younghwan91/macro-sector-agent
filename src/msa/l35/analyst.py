"""수급 균형 조사 에이전트 — 역할 프롬프트와 실행. `docs/26`.

L3 의 provider 추상을 그대로 재사용한다 (`msa.l3.providers`).

## 이 역할이 기존 `supply_analyst` 와 다른 점

겹치는 것이 많다 — 둘 다 생산능력·리드타임·원가곡선을 본다. 그런데 **묻는 방향이 반대다**:

| | `supply_analyst` (L3) | 이 역할 (L3.5) |
|---|---|---|
| 목적 | 5축 판별의 **입력** | **독립 논지** |
| 방향 | 부정형 — 과잉인가·줄었나 | 긍정형 — 막혔나·늘어나나 |
| 지평 | 현재 상태 | **향후 3~5년** |
| 결론 | "안 죽었다" | "벌어진다 / 아니다" |

**중복 검색을 피하려고 기존 thesis 를 입력으로 받는다.** `supply_analyst` 가 이미 모은
수치 위에서 "그래서 벌어지는가" 만 새로 묻는다 (`docs/26` §4).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from msa.l3 import roles as _roles
from msa.l3.providers import CompletionRequest, LLMProvider
from msa.l35.balance import (
    BALANCE_VERDICTS,
    DEMAND_VERDICTS,
    RIGIDITY_KINDS,
    SCHEMA,
    SUPPLY_VERDICTS,
)

#: 프롬프트가 **반드시 담아야 하는** 금지 문구. 토큰 부재 검사가 아니라 존재 검사다 —
#: 이유는 `msa.l2.analyst.REQUIRED_PROHIBITIONS` 주석에 있다.
REQUIRED_PROHIBITIONS: tuple[str, ...] = (
    "가격을 말하지 마라",
    "종목을 말하지 마라",
)

SYSTEM = (
    "너는 원자재·산업 리서치 팀의 **수급 애널리스트**다. 묻는 것은 하나다 —\n\n"
    "> **향후 3~5년, 이 테마의 실물 수요 증가율이 실물 공급 증가율을 앞지르는가?**\n\n"
    "가격이 아니라 **물량 대 물량**이다. 톤·온스·TEU·MWh 처럼 셀 수 있는 단위로 말한다.\n\n"
    "## 절대 규칙\n"
    "1. **가격을 말하지 마라.** 목표가·기대수익·'저평가' 를 쓰지 않는다. 수급이 타이트한 "
    "것과 주가가 오르는 것은 다른 명제이고, 그 답을 담을 칸이 스키마에 없다.\n"
    "2. **종목을 말하지 마라.** 개별 기업은 생산량·발표의 출처로만 언급한다.\n"
    "3. **매출을 물량인 척 쓰지 마라.** 실물 단위 시계열이 없으면 `unit` 을 비우고 "
    "그렇다고 말해라 — 이 조사를 안 하는 것이 맞는 답일 수 있다.\n"
    "4. **공급이 '제한적' 이라면 왜인지를 다섯 유형 중 하나로 분류하라.** 분류할 수 없으면 "
    "그 주장을 싣지 마라. '공급이 제한적이다' 는 그 자체로는 동어반복이다.\n"
    f"   {' · '.join(f'`{k}`' for k in RIGIDITY_KINDS)}\n"
    "5. **`what_would_close_it` 을 반드시 채워라.** '수요가 공급을 앞지른다' 고 말하려면 "
    "**그 격차가 어떻게 메워지는가**를 같이 말해야 한다. 영구 부족은 자본주의에서 거의 "
    "항상 틀린다. 이 칸이 네 논지를 스스로 공격하는 자리다.\n"
    "6. **증설은 확정(FID)된 것만 센다.** 발표·구상·MOU 는 공급이 아니다.\n"
    "7. **출처 없는 주장은 저장되지 않는다.** 모든 driver·rigidity 가 `evidence_ids` 로 "
    "실재하는 근거를 가리켜야 한다. 네 기억은 증거가 아니다.\n"
    "8. **모르면 `cagr_estimate` 를 null 로 둬라.** 0 으로 채우면 '증가율 0' 이라는 판정이 "
    "된다.\n\n"
    "## 판정 세 벌\n"
    f"- 수요: {' | '.join(DEMAND_VERDICTS)}\n"
    f"- 공급: {' | '.join(SUPPLY_VERDICTS)}\n"
    f"- 균형: {' | '.join(BALANCE_VERDICTS)}\n\n"
    "균형은 수요·공급 판정의 기계적 조합이 아니다 — 증가율의 **차**를 보고 정한다."
)


def _thesis_block(thesis: Mapping[str, Any] | None) -> str:
    """기존 판별 논지를 프롬프트에 싣는다 — 같은 검색을 두 번 하지 않게."""
    if not thesis:
        return "## 기존 판별 논지\n(없다 — 이 테마는 아직 `msa research` 를 거치지 않았다)"
    parts = [
        "## 기존 판별 논지 (L3 · 같은 검색을 반복하지 마라)",
        f"- claim: {str(thesis.get('claim') or '')[:600]}",
    ]
    axes = thesis.get("axes") or {}
    for name in ("unit_demand", "capital_cycle", "cost_curve"):
        body = axes.get(name) if isinstance(axes, Mapping) else None
        if isinstance(body, Mapping):
            ruling = str(body.get("referee_ruling") or "")[:300]
            if ruling:
                parts.append(f"- {name}: {ruling}")
    inv = list(thesis.get("invalidations") or [])[:3]
    if inv:
        parts.append("- 기존 무효화 조건: " + " / ".join(str(x)[:120] for x in inv))
    return "\n".join(parts)


def build_request(
    theme: str, asof: str, *, unit_hint: str = "", thesis: Mapping[str, Any] | None = None
) -> CompletionRequest:
    """한 테마에 대한 수급 조사 요청 하나."""
    hint = f"\n실물 단위 힌트: **{unit_hint}**" if unit_hint else ""
    user = (
        f"## 대상\n테마 `{theme}` · 기준일 {asof} · 지평 **3~5년**{hint}\n\n"
        f"{_thesis_block(thesis)}\n\n"
        "## 조사\n"
        "1. **수요** — 무엇이 실물 소비량을 미는가. 각 driver 의 크기와 성장률을 실물 "
        "단위로. 최근 기관 전망·연구 결과를 출처로 든다.\n"
        "2. **공급** — 향후 3년 **확정된** 증설이 얼마인가. 늘지 못한다면 **왜** 인가 "
        "(다섯 유형 중 하나로 분류).\n"
        "3. **균형** — 두 증가율의 차. 그리고 **무엇이 그 격차를 메우는가**.\n\n"
        "## 산출\n위 스키마의 JSON 하나. `theme`·`asof` 는 코드가 채우니 나머지를 채워라."
    )
    return CompletionRequest(
        role="balance_analyst",
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        json_schema=SCHEMA,
    )


def run(
    provider: LLMProvider,
    theme: str,
    asof: str,
    *,
    unit_hint: str = "",
    thesis: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """조사를 한 번 부르고 수급 문서 모양으로 돌려준다. 검증은 호출자(`balance.write`)가."""
    obj = provider.complete(
        build_request(theme, asof, unit_hint=unit_hint, thesis=thesis)
    ).json()
    out: dict[str, Any] = {"theme": theme, "asof": asof, **obj}
    if obj.get("synthetic"):
        out["synthetic"] = True
    return out


def render_report(doc: Mapping[str, Any]) -> str:
    """사람이 읽는 조사 보고. **결론과 그 반대편이 나란히 온다.**"""
    dem, sup, bal = doc.get("demand") or {}, doc.get("supply") or {}, doc.get("balance") or {}
    lines = [
        f"# 수급 균형 · `{doc.get('theme')}` · {doc.get('asof')}",
        "",
        f"> **{bal.get('verdict')}** — {bal.get('ratio_note', '')}",
        "",
        f"단위 **{doc.get('unit')}** · 지평 {doc.get('horizon_years')}년. "
        "**가격을 말하지 않는다 — 물량 대 물량이다.**",
        "",
        f"## 수요 — {dem.get('verdict')}"
        + (f" (연 {dem['cagr_estimate']:.1%})" if dem.get("cagr_estimate") is not None else ""),
        "",
    ]
    for d in dem.get("drivers") or []:
        ids = ",".join(str(i) for i in (d.get("evidence_ids") or []))
        lines.append(f"- **{d.get('name')}** ({d.get('direction')}) — {d.get('magnitude')} [{ids}]")
    lines += [
        "",
        f"## 공급 — {sup.get('verdict')}"
        + (f" (연 {sup['cagr_estimate']:.1%})" if sup.get("cagr_estimate") is not None else ""),
        "",
        f"확정(FID) 증설 3년: {sup.get('new_capacity_3y')}",
        "",
    ]
    if sup.get("rigidity"):
        lines.append("**왜 못 늘어나나**")
        lines.append("")
        for r in sup["rigidity"]:
            ids = ",".join(str(i) for i in (r.get("evidence_ids") or []))
            lines.append(f"- `{r.get('kind')}` — {r.get('note')} [{ids}]")
        lines.append("")
    lines += ["## 무엇이 이 격차를 메우나", ""]
    lines += [f"- {x}" for x in (bal.get("what_would_close_it") or ["(없음)"])]
    lines += ["", "## 무효화 조건", ""]
    lines += [f"- {x}" for x in (bal.get("invalidations") or [])]
    lines += ["", "## 근거", ""]
    for e in doc.get("evidence") or []:
        lines.append(f"[{e.get('id')}] {e.get('claim')} — {e.get('source_url')} ({e.get('date')})")
    lines += [
        "",
        "---",
        "",
        "**이 문서는 논지이지 명단이 아니다.** 수급 판정은 트리아지 점수에 들어가지 않는다 "
        "(`docs/26` §3.5) — 수급이 타이트한 것과 지금 살 자리인 것은 다른 명제다.",
    ]
    return "\n".join(lines)


#: `--dry-run`(MockProvider) 용 결정론 응답. **합성이라는 것이 본문에 적혀 있다.**
MOCK_OUTPUT: dict[str, Any] = {
    "synthetic": True,
    "unit": "합성단위",
    "horizon_years": 5,
    "demand": {
        "verdict": "flat",
        "drivers": [
            {
                "name": "합성 driver",
                "direction": "flat",
                "magnitude": "합성 응답(--dry-run) — 실제 조사가 아니다",
                "evidence_ids": [1],
            }
        ],
        "cagr_estimate": None,
    },
    "supply": {
        "verdict": "elastic",
        "rigidity": [],
        "new_capacity_3y": "합성 응답 — 실제 조사가 아니다",
        "cagr_estimate": None,
    },
    "balance": {
        "verdict": "balanced",
        "ratio_note": "합성 응답(--dry-run) — 실제 판정이 아니다. 경로 검증용이다.",
        "what_would_close_it": [],
        "invalidations": ["합성 응답이므로 무효화 조건도 합성이다"],
    },
    "evidence": [
        {
            "id": 1,
            "claim": "합성 증거 — 실제 출처가 아니다",
            "source_url": "https://example.invalid/mock",
            "date": "2026-01-01",
            "reliability": "low",
        }
    ],
}

_roles.register_mock_output("balance_analyst", MOCK_OUTPUT)


def schema_json() -> str:
    """프롬프트 디버깅용 — 스키마를 사람이 읽게."""
    return json.dumps(SCHEMA, ensure_ascii=False, indent=2)
