"""증거 트리아지 — **에이전트가 무엇을 할 수 없는지**를 붙잡아 둔다.

이 모듈의 설계 전부가 "역할을 나눈다" 는 한 문장이다. 에이전트에게 수치 판정을 시키면
가장 못하는 일을 시키는 것이고(AttrScore: GPT-4 오판의 30.6% 가 수치 둔감), 그래서 여기
테스트는 **에이전트가 코드의 판정을 뒤집을 수 없다**는 것을 주로 검사한다.
"""

from __future__ import annotations

from typing import Any

from msa.l3.evidence_audit import NO_NUMBERS, PARTIAL, UNREACHABLE, VERIFIED, EvidenceCheck
from msa.l3.evidence_triage import (
    LIKELY_ROUNDING,
    MINOR,
    OPEN_FIRST,
    TRIAGE_SCHEMA,
    Triage,
    deterministic_order,
    parse_triage,
    render_triage,
    run_triage,
    triage_prompt,
)

AXES = {"unit_demand": (1, 10), "terminal_risk": (17,)}


def _checks() -> tuple[EvidenceCheck, ...]:
    return (
        EvidenceCheck(1, PARTIAL, "https://kff.org/a", tuple("abcdefghi"), tuple("abcdefgh")),
        EvidenceCheck(8, PARTIAL, "https://kff.org/b", tuple("abcdefg"), ("a",)),
        EvidenceCheck(17, PARTIAL, "https://cwf.org/c", tuple("abcdef"), ("a", "b", "c")),
        EvidenceCheck(99, VERIFIED, "https://ok.org/d", ("x",), ()),
        EvidenceCheck(98, UNREACHABLE, "https://403.org/e", ("y",), ("y",)),
        EvidenceCheck(97, NO_NUMBERS, "https://none.org/f"),
    )


def _evidence() -> list[dict[str, Any]]:
    return [
        {"id": 1, "claim": "가입자 시계열"},
        {"id": 8, "claim": "3,500만 명"},
        {"id": 17, "claim": "$340B · 120만 명"},
        {"id": 99, "claim": "통과한 것"},
    ]


# ------------------------------------------------- 에이전트가 볼 수 없는 것


def test_verified_and_unreadable_never_reach_the_agent() -> None:
    """**통과한 증거를 에이전트가 뒤집을 수 없다** — 입력에 넣지 않기 때문이다.

    `unreachable`·`unsupported` 도 넣지 않는다. 그것은 "못 읽었다" 이지 "틀렸다" 가 아니고,
    사람이 열어도 같은 이유로 막힌다.
    """
    got = triage_prompt("t", _checks(), _evidence(), AXES)
    assert got is not None
    _system, user = got
    assert "99" not in user and "ok.org" not in user, "verified 가 새어 들어갔다"
    assert "403.org" not in user, "unreachable 이 새어 들어갔다"
    assert "none.org" not in user, "no_numbers 가 새어 들어갔다"
    for eid in ("1", "8", "17"):
        assert f'"evidence_id": {eid}' in user


def test_nothing_to_triage_returns_none() -> None:
    """볼 것이 없으면 호출하지 않는다 — 빈 요청에 돈을 쓰지 않는다."""
    clean = (EvidenceCheck(1, VERIFIED, "https://ok/a", ("x",), ()),)
    assert triage_prompt("t", clean, _evidence(), AXES) is None


def test_axes_come_from_code_not_the_agent() -> None:
    """에이전트가 축 매핑을 **지어낼 수 없다** — 응답에 뭐라 적든 코드가 덮어쓴다."""
    payload = {
        "items": [
            {"evidence_id": 17, "verdict": OPEN_FIRST, "why": "w", "look_for": "l"},
            {"evidence_id": 1, "verdict": MINOR, "why": "w", "look_for": "l"},
        ]
    }
    got = {t.evidence_id: t.axes for t in parse_triage(payload, AXES)}
    assert got == {17: ("terminal_risk",), 1: ("unit_demand",)}


def test_unknown_verdicts_are_dropped_not_guessed() -> None:
    """스키마 밖의 판정은 버린다 — 임의로 가장 가까운 것에 붙이지 않는다."""
    payload = {
        "items": [
            {"evidence_id": 1, "verdict": "매우 중요", "why": "w", "look_for": "l"},
            {"evidence_id": 17, "verdict": OPEN_FIRST, "why": "w", "look_for": "l"},
        ]
    }
    got = parse_triage(payload, AXES)
    assert [t.evidence_id for t in got] == [17]


def test_schema_forbids_extra_properties_everywhere() -> None:
    """구조화 출력은 **모든** object 에 `additionalProperties: false` 를 요구한다.

    빠지면 400 이다 — 2026-08-29 에 최상위에서 실제로 걸렸다.
    """
    assert TRIAGE_SCHEMA["additionalProperties"] is False
    assert TRIAGE_SCHEMA["properties"]["items"]["items"]["additionalProperties"] is False


# ------------------------------------------------- 폴백


def test_fallback_orders_by_ratio_and_says_it_cannot_tell() -> None:
    """기계 순서는 **반올림과 진짜 결함을 구분 못 한다** — 그 사실을 문구가 말한다."""
    got = deterministic_order(_checks(), AXES)
    assert [t.evidence_id for t in got] == [1, 17, 8], "못 찾은 비율 순"
    assert got[0].verdict == OPEN_FIRST  # 8/9
    assert got[2].verdict == MINOR  # 1/7
    assert all(t.fallback for t in got)
    assert "구분 못 함" in got[0].why


def test_disallowed_model_falls_back_loudly() -> None:
    """크레딧 경로에 haiku 아닌 모델을 주면 **조용히 낮추지 않는다** (`CLAUDE.md` §2)."""
    items, why = run_triage("t", _checks(), _evidence(), AXES, model="claude-opus-5")
    assert items and all(t.fallback for t in items)
    assert "허용되지 않은 모델" in why and "claude-opus-5" in why


def test_empty_agent_result_falls_back_with_a_reason() -> None:
    """에이전트가 빈 목록을 내면 폴백한다 — 빈 결과를 '볼 것 없음' 으로 읽지 않는다."""
    assert parse_triage({"items": []}, AXES) == ()


# ------------------------------------------------- 리포트


def test_report_names_what_to_open_and_counts_the_rest() -> None:
    """**먼저 열 것만 이름으로, 나머지는 수로.** 13건을 다 적으면 다시 아무도 안 본다."""
    items = (
        Triage(17, OPEN_FIRST, "셋 다 없다", "$340B 를 찾아라", ("terminal_risk",)),
        Triage(8, LIKELY_ROUNDING, "반올림", ""),
        Triage(22, LIKELY_ROUNDING, "반올림", ""),
    )
    out = "\n".join(render_triage(items, total_partial=3))
    assert "먼저 열 것 1건" in out
    assert "[17]" in out and "$340B 를 찾아라" in out and "terminal_risk 근거" in out
    assert "나머지 2건" in out
    assert "[8]" not in out, "곁가지를 이름으로 적으면 목록이 다시 길어진다"


def test_report_says_when_the_order_came_from_the_machine() -> None:
    """폴백을 에이전트 결과처럼 읽으면 엉뚱한 문서를 연다 — 출처를 적는다."""
    items = (Triage(1, OPEN_FIRST, "비율 높음", "찾아라", (), fallback=True),)
    out = "\n".join(render_triage(items, total_partial=1))
    assert "기계 순서" in out and "에이전트 실패" in out


def test_report_is_explicit_when_nothing_needs_opening() -> None:
    """'먼저 열 것 없음' 도 결론이다 — 빈 줄로 두면 실사를 안 한 것과 같아 보인다."""
    items = (Triage(8, LIKELY_ROUNDING, "반올림", ""),)
    out = "\n".join(render_triage(items, total_partial=1))
    assert "먼저 열 것 없음" in out and "사지 전에 한 번은 보라" in out


def test_conflicting_verdicts_for_one_item_are_flagged_not_silently_picked() -> None:
    """**한 증거에 두 판정이 오면 에이전트가 흔들린 것이다** (2026-08-29 실측: `[26]`).

    조용히 하나를 고르지 않는다. 무거운 쪽을 남기되 `why` 가 그 사실을 말한다 —
    열어서 아무것도 아닌 것보다 안 열고 놓치는 쪽이 비싸다.
    """
    payload = {
        "items": [
            {"evidence_id": 26, "verdict": MINOR, "why": "곁가지", "look_for": ""},
            {"evidence_id": 26, "verdict": OPEN_FIRST, "why": "핵심", "look_for": "HR 1834"},
        ]
    }
    got = parse_triage(payload, AXES)
    assert len(got) == 1, "중복이 두 건으로 세어지면 '먼저 열 것' 개수가 부풀려진다"
    (t,) = got
    assert t.verdict == OPEN_FIRST
    assert "분류가 흔들렸다" in t.why and "minor" in t.why
    assert t.look_for == "HR 1834", "빈 쪽이 아니라 채워진 쪽을 남긴다"


def test_duplicate_with_same_verdict_is_just_deduped() -> None:
    """같은 판정이 두 번 오면 흔들린 것이 아니다 — 경고를 붙이지 않는다."""
    payload = {
        "items": [
            {"evidence_id": 8, "verdict": LIKELY_ROUNDING, "why": "반올림", "look_for": ""},
            {"evidence_id": 8, "verdict": LIKELY_ROUNDING, "why": "반올림", "look_for": ""},
        ]
    }
    (t,) = parse_triage(payload, AXES)
    assert t.verdict == LIKELY_ROUNDING and "흔들" not in t.why


def test_urls_sit_next_to_their_item_not_at_the_end() -> None:
    """끝에 몰아 찍으면 "나머지 N건" 줄 아래 붙어 **그것들의 URL 처럼 보인다**.

    2026-08-29 실측 — 사람이 열어야 할 문서와 안 열어도 되는 문서의 링크가 뒤섞였다.
    """
    items = (
        Triage(17, OPEN_FIRST, "셋 다 없다", "$340B", ("terminal_risk",)),
        Triage(8, LIKELY_ROUNDING, "반올림", ""),
    )
    lines = render_triage(
        items, total_partial=2, urls={17: "https://cwf.org/c", 8: "https://kff.org/b"}
    )
    i_item = next(i for i, x in enumerate(lines) if "[17]" in x)
    i_url = next(i for i, x in enumerate(lines) if "cwf.org" in x)
    i_rest = next(i for i, x in enumerate(lines) if "나머지" in x)
    assert i_item < i_url < i_rest, "URL 이 항목 바로 아래, '나머지' 앞에 와야 한다"
    assert not any("kff.org" in x for x in lines), "곁가지의 URL 은 찍지 않는다"
