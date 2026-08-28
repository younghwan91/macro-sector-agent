"""증거 실사 결과의 **트리아지** — 사람이 먼저 열 문서를 고른다.

## 왜 필요한가

`evidence_audit` 은 "claim 의 숫자가 원문에 있는가" 를 재고 목록을 낸다. 그런데 그 목록이
길다 — 2026-08-28 실행에서 `managed_care` 만 13건이었다. 리포트는 **"13건 이상" 이라고
겁만 주고 어느 것을 열지 못 짚어 준다.**

그 13건은 성격이 전혀 다르다:

| | 예 | 무게 |
|---|---|---|
| 반올림 | claim `3,500만 명` ↔ 원문 `35.4 million` | 검사의 한계. 볼 것 없음 |
| 부분 결측 | 6개 중 1개 못 찾음 | 확인은 좋지만 판정을 안 뒤집음 |
| **통째로 없음** | provider tax 문서에 `$340B`·`120만 명` 이 **셋 다** 없음 | **진짜 결함** |
| **출처 불일치** | *2026년* 등록 페이지에 2016~2021 시계열 | **URL 이 근거가 아님** |

이 분류를 사람이 매일 13건씩 손으로 할 수는 없다.

## 역할을 나눈다 — 이것이 설계의 전부다

2026-08-27 리서치(AttrScore, EMNLP 2023 Findings)가 정면으로 경고한다:

> GPT-4 오판의 **30.6% 가 수치·날짜 둔감**이고, `contradictory` 를 `attributable` 로
> 통과시키는 방향으로 치우친다.

즉 **"이 숫자가 원문에 정말 없나" 를 LLM 에 맡기면 가장 못하는 일을 시키는 것**이다.
`109 fewer counties` → `225개 철수` 같은 것을 조용히 통과시킨다.

    숫자가 문서에 있나          →  코드 (`evidence_audit`)  LLM 이 제일 못하는 것
    뭐가 진짜고 뭐가 반올림인가  →  **에이전트**             분류·순위 — LLM 이 잘하는 것
    최종 판정                   →  사람

에이전트에게 **"이 숫자 맞아?" 를 묻지 않는다.** "코드가 못 찾은 것 중 사람이 먼저 열 것을
골라라" 를 묻는다. 순위 매기기라 수치 둔감이 안 걸린다.

## 에이전트가 할 수 없는 것 (구조로 막는다)

- **`verified` 건을 건드릴 수 없다** — 입력에 넣지 않는다.
- **코드의 숫자 판정을 뒤집을 수 없다** — 스키마에 그런 필드가 없다.
- **축 매핑을 지어낼 수 없다** — `axes` 는 코드가 `axis_refs` 로 채운다.
- **판정을 바꾸지 않는다** — 순서만 정한다. 편입 가능 여부는 이 모듈이 만지지 않는다.

실패하면 결정론 순서로 폴백하고 **그 사실을 리포트에 적는다** (`CLAUDE.md` §2).

## 실측 — 이 분류를 얼마나 믿을 수 있나 (2026-08-29 · `managed_care` 7건)

**같은 입력을 세 번 돌렸다.**

| | |
|---|---:|
| 판정이 같은 것 | **6/7** |
| 흔들린 것 | `[22]` (`likely_rounding` ×2 · `open_first` ×1) |
| `open_first` 개수 | 4 · 4 · 5 |

**핵심 4건(`[1]`·`[8]`·`[10]`·`[17]`)은 세 번 다 `open_first` 였다.** 흔들린 것은 경계에
있는 한 건이고, 방향은 "더 열어라" 쪽이다 — 놓치는 쪽이 아니다.

한 번 실행에서 **같은 증거에 두 판정이 온 적도 있다**(`[26]`: minor ↔ open_first).
`parse_triage` 가 그것을 잡아 무거운 쪽을 남기고 `why` 에 흔들렸다고 적는다.

> **결정론이 아니다.** 이 순서는 "오늘 이 모델이 이렇게 봤다" 이지 정답이 아니다.
> 그래서 이 모듈은 **판정을 바꾸지 않고 순서만 정한다** — 흔들려도 잃는 것은 사람이 문서를
> 하나 더 열거나 덜 여는 것뿐이고, 편입 가능 여부는 그대로다.

## 비용

haiku 4.5 · 검색 없음. 실측 견적: 테마당 입력 ~3,100 · 출력 ~1,000 토큰 → **약 $0.008**.
편입 가능 2테마 기준 하루 $0.017 · 월 $0.5. 크레딧 경로는 haiku 만 허용된다
(`providers.enforce_api_credit_models`, 2026-08-25 사용자 지시).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from msa.l3.evidence_audit import PARTIAL, EvidenceCheck

log = logging.getLogger(__name__)

__all__ = [
    "TRIAGE_SCHEMA",
    "VERDICTS",
    "Triage",
    "deterministic_order",
    "render_triage",
    "triage_prompt",
]

#: 판정 셋. **더 늘리지 않는다** — 사람이 "먼저 열 것" 과 "안 열어도 되는 것" 을 가르는 것이
#: 목적이고, 중간 단계를 늘리면 다시 13건을 훑게 된다.
OPEN_FIRST = "open_first"
LIKELY_ROUNDING = "likely_rounding"
MINOR = "minor"
VERDICTS: tuple[str, ...] = (OPEN_FIRST, LIKELY_ROUNDING, MINOR)


@dataclass(frozen=True)
class Triage:
    """증거 한 건의 트리아지. `axes` 는 **코드가 채운다** — 에이전트가 지어낼 수 없다."""

    evidence_id: int
    verdict: str
    why: str
    look_for: str
    axes: tuple[str, ...] = ()
    #: 에이전트 없이 만든 것인가 (폴백). 리포트가 이 사실을 적는다.
    fallback: bool = False

    @property
    def first(self) -> bool:
        return self.verdict == OPEN_FIRST


#: 에이전트 출력 스키마. `evidence_id` 와 `verdict` 만 강제하고 나머지는 짧은 산문이다.
TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    # 구조화 출력은 **모든** object 에 `additionalProperties: false` 를 요구한다 —
    # 빠지면 400 이다 (2026-08-29 실측). 최상위도 예외가 아니다.
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["evidence_id", "verdict", "why", "look_for"],
                "additionalProperties": False,
                "properties": {
                    "evidence_id": {"type": "integer"},
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "why": {"type": "string", "maxLength": 200},
                    "look_for": {"type": "string", "maxLength": 200},
                },
            },
        }
    },
}


def deterministic_order(
    checks: Sequence[EvidenceCheck], axis_refs: Mapping[str, tuple[int, ...]]
) -> tuple[Triage, ...]:
    """에이전트 없이 만드는 순서 — **폴백이자 하한**이다.

    쓸 수 있는 것은 둘뿐이다: 못 찾은 비율과 축 참조 여부. 그래서 `3,500만`(반올림)과
    `$340B`(진짜)를 **구분하지 못한다** — 둘 다 "1개 못 찾음" 이다. 그 구분이 에이전트를
    쓰는 이유이고, 이 함수는 에이전트가 실패했을 때 아무것도 못 내놓는 것보다 낫기 위해
    있다.
    """
    ax = _axes_by_id(axis_refs)
    out: list[Triage] = []
    for c in sorted(checks, key=lambda c: (-_missing_ratio(c), c.evidence_id)):
        if c.status != PARTIAL:
            continue
        r = _missing_ratio(c)
        out.append(
            Triage(
                evidence_id=c.evidence_id,
                verdict=OPEN_FIRST if r >= 0.5 else MINOR,
                why=(
                    f"못 찾은 숫자 {len(c.missing)}/{len(c.wanted)} "
                    "(기계 순서 — 반올림과 구분 못 함)"
                ),
                look_for=f"원문에서 {', '.join(c.missing[:3])} 를 찾아라",
                axes=ax.get(c.evidence_id, ()),
                fallback=True,
            )
        )
    return tuple(out)


def _missing_ratio(c: EvidenceCheck) -> float:
    return len(c.missing) / len(c.wanted) if c.wanted else 0.0


def _axes_by_id(axis_refs: Mapping[str, tuple[int, ...]]) -> dict[int, tuple[str, ...]]:
    out: dict[int, list[str]] = {}
    for axis, refs in axis_refs.items():
        for r in refs:
            out.setdefault(int(r), []).append(str(axis))
    return {k: tuple(sorted(v)) for k, v in out.items()}


def triage_prompt(
    theme: str,
    checks: Sequence[EvidenceCheck],
    evidence: Sequence[Mapping[str, Any]],
    axis_refs: Mapping[str, tuple[int, ...]],
) -> tuple[str, str] | None:
    """`(system, user)` — 볼 것이 없으면 `None`.

    **`verified` 건은 넣지 않는다.** 에이전트가 통과한 증거를 뒤집을 수 있으면 안 된다.
    `unreachable`·`unsupported` 도 넣지 않는다 — 그것은 "못 읽었다" 이지 "틀렸다" 가 아니고,
    사람이 열어도 같은 이유로 막힌다.
    """
    by_id = {int(e.get("id", -1)): e for e in evidence}
    ax = _axes_by_id(axis_refs)
    rows: list[dict[str, Any]] = []
    for c in checks:
        if c.status != PARTIAL:
            continue
        e = by_id.get(c.evidence_id, {})
        rows.append(
            {
                "evidence_id": c.evidence_id,
                "claim": str(e.get("claim", ""))[:600],
                "url": c.url,
                "numbers_checked": list(c.wanted),
                "numbers_not_found": list(c.missing),
                "axes_this_supports": list(ax.get(c.evidence_id, ())),
            }
        )
    if not rows:
        return None

    system = (
        "너는 투자 리서치의 증거 실사를 **분류**한다. 한국어로 답한다.\n"
        "\n"
        "이미 코드가 '이 숫자가 원문에 있는가' 를 문자열 대조로 검사했고, 그 결과가 입력이다.\n"
        "**너는 그 판정을 다시 하지 않는다.** 숫자가 정말 있는지 없는지는 네 일이 아니다 —\n"
        "너는 사람이 **어느 것을 먼저 열어야 하는지** 를 고른다.\n"
        "\n"
        "판정 셋:\n"
        f"- `{OPEN_FIRST}` — 사람이 먼저 열어야 한다. 못 찾은 숫자가 claim 의 핵심 주장을\n"
        "  이루거나, 여러 개가 통째로 없거나, claim 스스로 출처가 약하다고 적었거나,\n"
        "  그 근거가 축 판정을 떠받치는 경우.\n"
        f"- `{LIKELY_ROUNDING}` — 반올림·근사·단위 표기 차이로 보인다. 예: claim `3,500만 명`\n"
        "  ↔ 원문 `35.4 million`. 사람이 열 필요가 낮다.\n"
        f"- `{MINOR}` — 못 찾은 숫자가 곁가지다. 판정을 뒤집지 않는다.\n"
        "\n"
        "규칙:\n"
        "- 입력에 없는 사실을 지어내지 마라. 원문을 읽지 않았으므로 '원문에 있다/없다' 를\n"
        "  단정하지 마라. 네가 아는 것은 **코드가 못 찾았다** 는 사실뿐이다.\n"
        "- `look_for` 는 사람이 문서를 열고 **무엇을 찾을지** 한 문장으로 적어라.\n"
        f"- `{OPEN_FIRST}` 를 남발하지 마라. 전부 중요하면 아무것도 중요하지 않다.\n"
        "- 모든 항목에 대해 정확히 한 번씩 판정하라."
    )
    user = (
        f"테마: {theme}\n"
        f"판정을 만든 증거 중 **숫자를 못 찾은 것** {len(rows)}건이다.\n\n"
        f"```json\n{json.dumps(rows, ensure_ascii=False, indent=1)}\n```\n\n"
        "각 항목을 분류해라."
    )
    return system, user


def parse_triage(
    payload: Mapping[str, Any], axis_refs: Mapping[str, tuple[int, ...]]
) -> tuple[Triage, ...]:
    """에이전트 응답 → `Triage`. **축은 코드가 덮어쓴다** (에이전트 값을 믿지 않는다)."""
    ax = _axes_by_id(axis_refs)
    seen: dict[int, Triage] = {}
    for it in payload.get("items") or []:
        try:
            eid = int(it["evidence_id"])
            verdict = str(it["verdict"])
        except (KeyError, TypeError, ValueError):
            continue
        if verdict not in VERDICTS:
            continue
        t = Triage(
            evidence_id=eid,
            verdict=verdict,
            why=str(it.get("why", "")).strip(),
            look_for=str(it.get("look_for", "")).strip(),
            axes=ax.get(eid, ()),
        )
        prev = seen.get(eid)
        if prev is None:
            seen[eid] = t
            continue
        # **한 증거에 두 판정이 오면 그것은 에이전트가 흔들린 것이다** (2026-08-29 실측:
        # `[26]` 에 minor 와 open_first 가 같이 왔다). 조용히 하나를 고르지 않는다 —
        # 더 무거운 쪽을 남기고 그 사실을 `why` 에 적어 사람이 알게 한다 (`CLAUDE.md` §2).
        # 무거운 쪽으로 가는 이유는 하나다: 열어서 아무것도 아닌 것보다 안 열고 놓치는
        # 쪽이 비싸다.
        if prev.verdict == verdict:
            # 같은 판정이 두 번 온 것은 흔들린 것이 아니다 — 그냥 중복이다.
            seen[eid] = Triage(
                evidence_id=eid,
                verdict=verdict,
                why=prev.why or t.why,
                look_for=prev.look_for or t.look_for,
                axes=prev.axes,
            )
            continue
        keep, drop = (t, prev) if _weight(t) > _weight(prev) else (prev, t)
        seen[eid] = Triage(
            evidence_id=eid,
            verdict=keep.verdict,
            why=f"{keep.why} ⚠ 분류가 흔들렸다 ({prev.verdict}↔{t.verdict}) — 무거운 쪽을 남겼다",
            look_for=keep.look_for or drop.look_for,
            axes=keep.axes,
        )
    return tuple(seen.values())


def _weight(t: Triage) -> int:
    return {OPEN_FIRST: 2, MINOR: 1, LIKELY_ROUNDING: 0}.get(t.verdict, 0)


def render_triage(items: Sequence[Triage], *, total_partial: int) -> list[str]:
    """리포트 줄 — **먼저 열 것만 이름으로 적고 나머지는 수로 적는다.**"""
    if not items:
        return []
    first = [t for t in items if t.first]
    rest = len(items) - len(first)
    src = " (기계 순서 — 에이전트 실패)" if any(t.fallback for t in items) else ""
    if not first:
        return [
            f"증거 실사: 숫자를 못 찾은 {total_partial}건 중 **먼저 열 것 없음**{src} — "
            "전부 반올림·곁가지로 분류됐다. 그래도 사지 전에 한 번은 보라."
        ]
    out = [f"**먼저 열 것 {len(first)}건**{src}"]
    for t in first:
        ax = f" · {'·'.join(t.axes)} 근거" if t.axes else ""
        out.append(f"  [{t.evidence_id}] {t.why}{ax}")
        if t.look_for:
            out.append(f"       → {t.look_for}")
    if rest:
        out.append(f"  나머지 {rest}건은 반올림·곁가지 (`msa ops audit-evidence` 로 전문)")
    return out


#: 트리아지 모델. 크레딧 경로는 haiku 만 허용된다 (2026-08-25 사용자 지시) — 그리고 이
#: 작업에는 그것으로 충분하다. 2026-08-29 실측: `managed_care` 13건 중 7건(partial)을
#: 12초·$0.0083 에 분류했고, 사람이 손으로 고른 것과 일치했다. 오히려 사람이 "곁가지" 로
#: 넘긴 `[10]`(ACA 보조금 888→1,904달러)을 핵심으로 올렸고 그쪽이 옳았다.
TRIAGE_MODEL = "claude-haiku-4-5"
TRIAGE_MAX_TOKENS = 4000


def run_triage(
    theme: str,
    checks: Sequence[EvidenceCheck],
    evidence: Sequence[Mapping[str, Any]],
    axis_refs: Mapping[str, tuple[int, ...]],
    *,
    model: str = TRIAGE_MODEL,
) -> tuple[tuple[Triage, ...], str]:
    """`(항목, 사유)` — 에이전트로 분류하고, **안 되면 결정론 순서로 내려간다.**

    사유는 성공하면 빈 문자열, 폴백이면 왜 내려갔는지다. 조용히 폴백하지 않는다
    (`CLAUDE.md` §2) — 기계 순서는 반올림과 진짜 결함을 구분하지 못하므로, 그 목록을
    에이전트가 만든 것처럼 읽으면 사람이 엉뚱한 문서를 연다.

    이 함수는 **판정을 바꾸지 않는다.** 편입 가능 여부·게이트·확신도를 만지지 않고,
    사람이 볼 순서만 정한다.
    """
    p = triage_prompt(theme, checks, evidence, axis_refs)
    if p is None:
        return (), ""
    system, user = p

    from msa.l3.providers import API_CREDIT_ALLOWED_MODELS

    if model not in API_CREDIT_ALLOWED_MODELS:
        # 조용히 haiku 로 낮추지 않는다 — 요청한 모델과 실제로 돈 모델이 다르면 그것이
        # §2 가 금지하는 조용한 절단이다.
        return deterministic_order(checks, axis_refs), (
            f"크레딧 경로에 허용되지 않은 모델 {model!r} (허용: {API_CREDIT_ALLOWED_MODELS})"
        )

    try:
        import anthropic

        r = anthropic.Anthropic().messages.create(
            model=model,
            max_tokens=TRIAGE_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": TRIAGE_SCHEMA}},
        )
        txt = "".join(b.text for b in r.content if b.type == "text")
        items = parse_triage(json.loads(txt), axis_refs)
    except Exception as e:  # 키 없음·네트워크·스키마 위반 — 다이제스트를 죽이지 않는다
        log.info("트리아지 폴백: %s", e)
        return deterministic_order(checks, axis_refs), f"{type(e).__name__}: {e}"

    if not items:
        return deterministic_order(checks, axis_refs), "에이전트가 빈 목록을 냈다"
    return items, ""
