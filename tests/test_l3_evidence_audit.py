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
