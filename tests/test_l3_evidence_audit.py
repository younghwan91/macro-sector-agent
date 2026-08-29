"""증거 실사 — `claim` 의 숫자가 그 문서에 실제로 있는지.

이 검사가 존재하는 이유: 스키마는 **형식만** 본다. URL 이 URL 처럼 생기고 날짜가 미래가
아니면 통과하는데, 그러면서도 원문에 없는 수치를 적을 수 있다. 2026-08-25 실사에서 표본
74건 중 약 16건(20%)이 그랬다.
"""

from __future__ import annotations

from typing import Any

from msa.l3.evidence_audit import (
    NO_NUMBERS,
    PARTIAL,
    UNREACHABLE,
    UNSUPPORTED,
    VERIFIED,
    audit_thesis,
    check_one,
    numbers_in,
    strip_html,
)


def _ev(eid: int, claim: str, url: str = "https://example.com/a") -> dict[str, Any]:
    return {"id": eid, "claim": claim, "source_url": url}


# ---------------------------------------------------------------- 숫자 뽑기


def test_dates_and_years_are_not_treated_as_measurements() -> None:
    """날짜 조각·연도는 claim 의 측정값이 아니다 — 남기면 결과가 잡음으로 덮인다."""
    got, _ = numbers_in("2026-08-14 기준 운임은 4,526달러이고 2025년 대비 12% 올랐다")
    assert "4,526" in got and "12" in got
    assert "2026" not in got and "08" not in got and "14" not in got and "2025" not in got


def test_single_digits_are_skipped() -> None:
    """한 자리 수는 어느 문서에나 있어서 확인이 되지 않는다."""
    got, _ = numbers_in("선사 3곳이 점유율 41.2% 를 가진다")
    assert got == ("41.2",)


def test_truncation_is_counted_not_hidden() -> None:
    """상한을 넘긴 수는 **세어서 남긴다** — 조용히 자르지 않는다 (`CLAUDE.md` §2)."""
    text = " ".join(f"{i}.5" for i in range(10, 40))  # 30개 · 연도·한자리 아님
    got, cut = numbers_in(text, limit=5)
    assert len(got) == 5 and cut == 25


# ---------------------------------------------------------------- 대조


def test_all_numbers_found_is_verified() -> None:
    doc = "<p>Revenue was 1,234 million and margin 12.5%.</p>"
    c = check_one(_ev(1, "매출 1,234백만 · 마진 12.5%"), lambda _u: doc)
    assert c.status == VERIFIED and c.ok and not c.missing


def test_one_missing_number_is_partial_not_verified() -> None:
    """**비율 임계를 두지 않는다** — 틀린 숫자 하나가 판정을 만든다 (`CLAUDE.md` §1)."""
    doc = "<p>Revenue was 1,234 million.</p>"
    c = check_one(_ev(2, "매출 1,234백만 · 마진 12.5%"), lambda _u: doc)
    assert c.status == PARTIAL and not c.ok
    assert c.missing == ("12.5",)


def test_comma_formatting_does_not_cause_a_false_miss() -> None:
    c = check_one(_ev(3, "1,180,000 TEU"), lambda _u: "capacity of 1180000 teu")
    assert c.status == VERIFIED


def test_unreachable_is_not_a_failure_verdict() -> None:
    """403·페이월은 "틀리다" 가 아니다 — 아무 말도 못 한 것이다 (`CLAUDE.md` §2)."""
    c = check_one(_ev(4, "매출 1,234백만"), lambda _u: None)
    assert c.status == UNREACHABLE and not c.ok
    assert "맞다는 뜻도 틀리다는 뜻도 아니다" in c.note


def test_binary_and_non_http_sources_are_marked_unsupported() -> None:
    assert (
        check_one(_ev(5, "1,234", "https://x.org/report.pdf"), lambda _u: "").status == UNSUPPORTED
    )
    assert check_one(_ev(6, "1,234", "state/scans/x.csv"), lambda _u: "").status == UNSUPPORTED


def test_claim_without_numbers_says_so() -> None:
    c = check_one(_ev(7, "공급이 줄고 있다"), lambda _u: "anything")
    assert c.status == NO_NUMBERS


def test_strip_html_removes_scripts() -> None:
    got = strip_html("<script>var x = 999;</script><p>real 123</p>")
    assert "123" in got and "999" not in got


# ---------------------------------------------------------------- 논지 단위


def _thesis() -> dict[str, Any]:
    return {
        "value_trap_axes": {
            "substitution": {"verdict": "cycle", "evidence_refs": [1, 2]},
            "capital_cycle": {"verdict": "warning", "evidence_refs": [3]},
        },
        "evidence": [
            _ev(1, "점유율 41.2%"),
            _ev(2, "물량 1,234만"),
            _ev(3, "설비투자 55.5억"),
            _ev(9, "서술 재료 77.7"),  # 어느 축에도 안 쓰인다
        ],
    }


def test_only_verdict_bearing_evidence_is_audited_by_default() -> None:
    """판정을 만든 증거만 본다 — 나머지는 서술 재료이고 매일 수십 URL 을 받을 이유가 없다."""
    res = audit_thesis(_thesis(), lambda _u: "41.2")
    assert sorted(c.evidence_id for c in res.checks) == [1, 2, 3]

    every = audit_thesis(_thesis(), lambda _u: "41.2", only_axis_refs=False)
    assert sorted(c.evidence_id for c in every.checks) == [1, 2, 3, 9]


def test_axis_with_no_verified_evidence_is_named() -> None:
    """근거 중 확인된 것이 하나도 없는 축 — 그 판정이 무엇 위에 서 있는지 적는다."""
    # 문서에 41.2 만 있다 → 증거 1 은 verified, 2·3 은 partial
    res = audit_thesis(_thesis(), lambda _u: "only 41.2 here")
    assert res.unverified_axes() == ["capital_cycle"]  # substitution 은 1 이 확인됐다
    assert res.counts()[VERIFIED] == 1 and res.counts()[PARTIAL] == 2


# ---------------------------------------------------------------- 단위 변환


def test_korean_scale_units_are_matched_against_english_notation() -> None:
    """오탐의 가장 큰 원인이었다 — claim "2,220만 달러" vs 원문 `$22.2 million`.

    2026-08-26 실측: 이 처리를 넣자 `partial` 이 23건 → 9건, `verified` 가 13건 → 27건이
    됐다(두 테마 합계). 남은 9건이 실제로 봐야 할 것이다.
    """
    doc = "<p>ZIM reported a net loss of $22.2 million for the first half.</p>"
    c = check_one(_ev(1, "ZIM 상반기 순손실 2,220만 달러"), lambda _u: doc)
    assert c.status == VERIFIED, c.missing

    # 억 단위도 같다
    doc2 = "<p>throughput reached 237 million TEU</p>"
    assert check_one(_ev(2, "처리량 2.37억 TEU"), lambda _u: doc2).status == VERIFIED

    # 원 단위 그대로 쓴 문서도 잡는다
    doc3 = "<p>net loss of 22,200,000 dollars</p>"
    assert check_one(_ev(3, "순손실 2,220만 달러"), lambda _u: doc3).status == VERIFIED


def test_scaling_does_not_make_the_check_toothless() -> None:
    """**찾는 쪽만 넓힌다** — claim 이 틀렸는데 맞다고 하면 검사가 무의미해진다.

    후보에서 1 미만과 두 자리 미만을 뺀 이유가 이것이다. `0`·`0.02` 같은 값은 아무 문서에나
    있어서 넓히려다 검사를 꺼 버린다.
    """
    from msa.l3.evidence_audit import _alternates, _has_number, _loose

    # 1 미만 후보는 없다 — 반올림하면 `0` 이 되어 아무 문서에나 있는 값이 된다
    for raw, unit in (("2,220", "만"), ("1", "만"), ("178.8", "만"), ("2.37", "억")):
        for a in _alternates(raw, unit):
            assert float(a) >= 1.0, (raw, unit, a)

    # 한 자리 후보는 **경계**가 지킨다 — 그래서 후보에서 뺄 필요가 없다
    body = _loose("falls by 4 million, across 1,400 plans, with 4.7% churn and 04 codes")
    assert _has_number(body, "4")  # `4 million`
    assert not _has_number(body, "47")  # `4.7%` 안이 아니다
    assert not _has_number(body, "140")  # `1,400` 안이 아니다
    assert _has_number(body, "1400")  # 자릿점은 지운다

    # 원문에 없는 수치는 여전히 잡힌다 — 단위가 붙어 있어도
    doc = "<p>unrelated text with 999 and 12,345</p>"
    c = check_one(_ev(9, "세계 처리량 3,600만 TEU"), lambda _u: doc)
    assert c.status == PARTIAL and "3,600" in c.missing

    # 단위가 없는 숫자에는 후보를 만들지 않는다
    assert _alternates("2,220", "") == []
    assert _alternates("2,220", "개") == []


def test_trailing_zero_notation_matches() -> None:
    """claim `6.0%` 는 원문에 `6 percent` 로 있다 — 표기 차이지 다른 수가 아니다."""
    doc = "<p>the safe harbor threshold of 6 percent falls to 3.5 percent</p>"
    assert check_one(_ev(1, "상한이 6.0%에서 3.5%로"), lambda _u: doc).status == VERIFIED

    # 그래도 다른 수는 다른 수다
    assert check_one(_ev(2, "상한이 6.4%로"), lambda _u: doc).status == PARTIAL


# ---------------------------------------------------------------- 미리 받기


def test_prefetch_asks_once_per_url_and_skips_what_is_not_fetched() -> None:
    """같은 URL 을 두 근거가 인용하면 한 번만 받는다 — 실제로 있는 일이다 (KFF).

    그리고 `_early_verdict` 로 판정이 끝나는 것(PDF·숫자 없는 claim)은 아예 받지 않는다.
    규칙이 `check_one` 과 한 벌이라 미리 받는 목록과 실제로 받는 목록이 어긋나지 않는다.
    """
    from msa.l3.evidence_audit import fetch_urls, prefetch

    same = "https://example.com/kff"
    items = [
        _ev(1, "가입자 3,400만 명", url=same),
        _ev(2, "가입자 3,500만 명", url=same),  # 같은 문서
        _ev(3, "표는 PDF 에 있다 12건", url="https://example.com/a.pdf"),  # 받지 않는다
        _ev(4, "숫자가 없는 서술", url="https://example.com/b"),  # 받지 않는다
    ]
    assert fetch_urls(items) == {same}

    calls: list[str] = []

    def fetch(u: str) -> str | None:
        calls.append(u)
        return "<p>34.0 million and 35.4 million</p>"

    got = prefetch(items, fetch)
    assert calls == [same], calls
    assert set(got) == {same}


def test_audit_uses_the_prefetched_body_not_a_second_request() -> None:
    """실사 전체가 URL 당 한 번만 받는다 — audit_thesis 가 prefetch 를 거친다."""
    from msa.l3.evidence_audit import audit_thesis

    calls: list[str] = []

    def fetch(u: str) -> str | None:
        calls.append(u)
        return "<p>throughput 36 million TEU</p>"

    thesis = {
        "value_trap_axes": {"A": {"evidence_refs": [1, 2]}},
        "evidence": [
            _ev(1, "3,600만 TEU", url="https://example.com/x"),
            _ev(2, "3,600만 TEU", url="https://example.com/x"),
        ],
    }
    res = audit_thesis(thesis, fetch)
    assert calls == ["https://example.com/x"], calls
    assert [c.status for c in res.checks] == [VERIFIED, VERIFIED]


def test_a_number_inside_a_bigger_number_is_not_a_match() -> None:
    """**이 모듈이 존재하는 이유가 이 사례다** (모듈 docstring: "109개 카운티" → "225개").

    쉼표를 지운 본문에 부분 문자열로 찾으면 `225` 가 `34,225,000` 안에서 걸려 날조된 수치가
    `verified` 로 통과한다. 2026-08-26 코드 리뷰에서 재현됐다 — 경계를 보는 `_has_number`
    하나만 쓴다.
    """
    doc = "<p>total enrollment was 34,225,000 members</p>"
    c = check_one(_ev(1, "UnitedHealthcare는 225개 카운티에서 철수했다"), lambda _u: doc)
    assert c.status == PARTIAL and "225" in c.missing

    # 진짜로 적혀 있으면 통과한다
    assert check_one(
        _ev(2, "225개 카운티 철수"), lambda _u: "<p>exited 225 counties</p>"
    ).status == (VERIFIED)

    # 자릿점이 있는 원문도 통과한다 — 경계 검사가 천 단위 구분만 지운다
    assert check_one(_ev(3, "34,225,000명"), lambda _u: doc).status == VERIFIED


# ---------------------------------------------------------------- 영문 표기


def test_english_word_numbers_are_matched() -> None:
    """claim 의 `12척` 은 원문에 `twelve ships` 로 있다 — 표기 차이지 다른 수가 아니다.

    2026-08-29 사람이 원문을 대조한 오탐 4건 중 2건이 이것이었다 (해체 척수 `twelve`·`eleven`).
    """
    doc = "<p>only twelve ships for a total capacity of 8,172 teu were scrapped</p>"
    assert check_one(_ev(1, "2025년 해체량 12척·8,172 TEU"), lambda _u: doc).status == VERIFIED

    doc2 = "<p>only eleven cellular vessels for a capacity of 36,700 TEU</p>"
    assert check_one(_ev(2, "해체 11척·36,700 TEU"), lambda _u: doc2).status == VERIFIED


def test_word_numbers_respect_word_boundaries() -> None:
    """넓히려다 검사를 꺼 버리면 안 된다 — `one` 이 `money`·`phone` 안에서 걸리면 그것이다."""
    from msa.l3.evidence_audit import _has_word, _word_forms

    body = "money phoned someone at tenant nineteenth"
    for w in ("one", "ten", "nine", "nineteen"):
        assert not _has_word(body, w), w
    assert _has_word("only ten ships", "ten")

    # 맨 단위 낱말은 값이 아니다 — `five hundred ships` 가 claim 의 `100` 을 통과시키면 안 된다
    assert "hundred" not in _word_forms("100")
    assert not check_one(
        _ev(3, "100개 이상"), lambda _u: "<p>five hundred ships</p>"
    ).ok

    # 없는 수는 여전히 없다
    assert check_one(_ev(4, "13척"), lambda _u: "<p>twelve ships</p>").status == PARTIAL


def test_english_abbreviated_units_in_the_body_are_expanded() -> None:
    """원문의 `4.3k TEU`·`0.6 million` 은 claim 의 `4,300`·`60만` 과 같은 수다.

    2026-08-29 오탐 4건 중 나머지 2건이 이것이었다.
    """
    doc = "<p>One-year T/C rates for 4.3k TEU Non-Eco Classic Panamax vessels</p>"
    assert check_one(_ev(1, "4,300TEU 파나막스"), lambda _u: doc).status == VERIFIED

    doc2 = "<p>in 2016, when 185 ships totaling 0.6 million TEU were scrapped</p>"
    assert check_one(_ev(2, "2016년 185척·60만 TEU"), lambda _u: doc2).status == VERIFIED

    doc3 = "<p>from 36.2 million on June 30, 2025 to 34.0 million on June 30, 2026</p>"
    assert check_one(_ev(3, "3,400만 명으로 감소"), lambda _u: doc3).status == VERIFIED

    doc4 = "<p>net debt of 2.5bn and cash of 1.8M</p>"
    assert check_one(_ev(4, "순부채 25억·현금 180만"), lambda _u: doc4).status == VERIFIED


def test_unit_expansion_does_not_make_the_check_toothless() -> None:
    """**찾는 쪽만 넓힌다.** 단위 확장이 없는 수치를 있다고 하면 검사가 무의미해진다."""
    from msa.l3.evidence_audit import _expanded_units

    # 붙여 쓴 한 글자 약어만 본다 — `40 M` 은 미터일 수도 있어 확장하지 않는다
    assert "4300" in _expanded_units("rates for 4.3k TEU")
    assert "40000000" not in _expanded_units("a span of 40 M across")

    # 반올림은 여전히 남는다 — 3,500만 ≠ 35.2 million (KFF 실측, 2026-08-29)
    doc = "<p>55% of eligible beneficiaries – 35.2 million out of 64.2 million</p>"
    c = check_one(_ev(9, "가입자 3,500만 명 이상"), lambda _u: doc)
    assert c.status == PARTIAL and "3,500" in c.missing


def test_korean_year_month_is_a_date_not_a_measurement() -> None:
    """`2025년 12월 기준` 의 `12` 는 claim 의 측정값이 아니다 — 남기면 오탐이 된다.

    실측: managed_care [26]·shipping_container [4] 의 못 찾은 `12` 가 전부 이것이었다.
    """
    got, _ = numbers_in("2025년 12월 기준 발주잔량 11.61백만 TEU")
    assert "12" not in got and "11.61" in got

    got2, _ = numbers_in("하원은 2026년 1월 8일 230-196으로 가결")
    assert "230" in got2 and "196" in got2 and "8" not in got2

    # 달이 붙지 않은 숫자는 그대로 남는다
    got3, _ = numbers_in("2025년 대비 12% 올랐다")
    assert "12" in got3
