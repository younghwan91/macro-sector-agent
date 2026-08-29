"""L3.5 수급 균형 조사 — `docs/26` 사전 등록의 집행. 합성 dict, 네트워크 없음.

이 파일이 지키는 것 셋 (`docs/26` §3.3):
1. 가격을 말하지 않는다 — 스키마에 칸이 없다
2. 공급 경직성은 다섯 `kind` 중 하나로 분류된다
3. `what_would_close_it` 이 비면 저장 거부
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from msa.l35 import balance


def _ev(n: int = 1) -> list[dict[str, object]]:
    return [
        {
            "id": i + 1,
            "claim": f"근거 {i + 1}",
            "source_url": "https://www.silverinstitute.org/example",
            "date": "2026-06-30",
            "reliability": "high",
        }
        for i in range(n)
    ]


def _doc(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "theme": "silver",
        "asof": "2026-08-29",
        "horizon_years": 5,
        "unit": "온스",
        "demand": {
            "verdict": "expanding",
            "drivers": [
                {
                    "name": "태양광 셀 은 소비",
                    "direction": "up",
                    "magnitude": "산업 수요의 약 20% · 연 8% 성장",
                    "evidence_ids": [1],
                }
            ],
            "cagr_estimate": 0.04,
        },
        "supply": {
            "verdict": "constrained",
            "rigidity": [
                {
                    "kind": "byproduct",
                    "note": "70% 이상이 납·아연·구리 광산의 부산물이라 독립 증산이 안 된다",
                    "evidence_ids": [2],
                }
            ],
            "new_capacity_3y": "확정(FID) 신규 1차 은광 없음",
            "cagr_estimate": 0.01,
        },
        "balance": {
            "verdict": "tightening",
            "ratio_note": "수요 4% · 공급 1% → 연 3%p 벌어진다",
            "what_would_close_it": ["은 가격이 3년 이상 높게 유지되면 1차 은광이 FID 를 받는다"],
            "invalidations": ["태양광 셀당 은 사용량이 연 10% 이상 줄면 수요 축이 무효다"],
        },
        "evidence": _ev(2),
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------- 스키마


def test_valid_document_passes(tmp_path: Path) -> None:
    balance.validate(_doc())


def test_price_talk_has_nowhere_to_live() -> None:
    """가격을 담을 칸이 스키마에 없다 (`docs/26` §3.3 규칙 1)."""
    props = balance.SCHEMA["properties"]
    flat = set(props) | set(props["balance"]["properties"]) | set(props["supply"]["properties"])
    for banned in ("price_target", "upside", "expected_return", "target_price", "rating"):
        assert banned not in flat


def test_unknown_rigidity_kind_is_refused() -> None:
    """다섯 유형을 늘리면 '공급이 제한적이다' 의 동의어가 쌓인다 (`docs/26` §5)."""
    d = _doc()
    d["supply"]["rigidity"][0]["kind"] = "그냥_어려움"  # type: ignore[index]
    with pytest.raises(balance.BalanceRejected, match="kind"):
        balance.validate(d)


def test_rigidity_required_when_supply_is_constrained() -> None:
    """'제한적이다' 라고만 하고 왜인지 안 적으면 동어반복이다."""
    d = _doc()
    d["supply"]["rigidity"] = []  # type: ignore[index]
    with pytest.raises(balance.BalanceRejected, match="rigidity"):
        balance.validate(d)


def test_elastic_supply_needs_no_rigidity() -> None:
    """공급이 탄력적이라고 판정했으면 경직성을 댈 이유가 없다."""
    d = _doc()
    d["supply"]["verdict"] = "elastic"  # type: ignore[index]
    d["supply"]["rigidity"] = []  # type: ignore[index]
    d["balance"]["verdict"] = "balanced"  # type: ignore[index]
    balance.validate(d)


def test_what_would_close_it_is_required_when_tightening() -> None:
    """'벌어진다' 는 **어떻게 메워지나**를 함께 말해야 한다 (`docs/26` §3.3 규칙 3)."""
    d = _doc()
    d["balance"]["what_would_close_it"] = []  # type: ignore[index]
    with pytest.raises(balance.BalanceRejected, match="what_would_close_it"):
        balance.validate(d)


def test_invalidations_required() -> None:
    d = _doc()
    d["balance"]["invalidations"] = []  # type: ignore[index]
    with pytest.raises(balance.BalanceRejected, match="invalidations"):
        balance.validate(d)


def test_evidence_required() -> None:
    with pytest.raises(balance.BalanceRejected, match="evidence"):
        balance.validate(_doc(evidence=[]))


def test_evidence_url_must_be_a_url() -> None:
    d = _doc(evidence=[{"id": 1, "claim": "x", "source_url": "믿어줘", "date": "2026-06-30"}])
    with pytest.raises(balance.BalanceRejected, match="source_url"):
        balance.validate(d)


def test_driver_evidence_ids_must_exist() -> None:
    """근거 번호가 실재하지 않으면 그 주장은 출처가 없는 것이다 (`CLAUDE.md` §3)."""
    d = _doc()
    d["demand"]["drivers"][0]["evidence_ids"] = [99]  # type: ignore[index]
    with pytest.raises(balance.BalanceRejected, match="evidence_ids"):
        balance.validate(d)


def test_unitless_theme_is_refused() -> None:
    """단위가 없으면 매출을 물량인 척하게 된다 (`docs/26` §6.2)."""
    with pytest.raises(balance.BalanceRejected, match="unit"):
        balance.validate(_doc(unit=""))


def test_cagr_may_be_null_but_not_invented() -> None:
    """모르면 null 이다. 0 으로 채우면 '증가율 0' 이라는 판정이 된다 (`CLAUDE.md` §2)."""
    d = _doc()
    d["demand"]["cagr_estimate"] = None  # type: ignore[index]
    d["supply"]["cagr_estimate"] = None  # type: ignore[index]
    balance.validate(d)


# ---------------------------------------------------------------- 저장·조회


def test_roundtrip(tmp_path: Path) -> None:
    p = balance.write(tmp_path, _doc())
    assert p.exists()
    got = balance.read(tmp_path, "silver")
    assert got is not None and got["balance"]["verdict"] == "tightening"


def test_read_missing_is_none(tmp_path: Path) -> None:
    assert balance.read(tmp_path, "nope") is None


def test_staleness_uses_declared_days(tmp_path: Path) -> None:
    balance.write(tmp_path, _doc(asof="2026-01-01"))
    assert balance.is_stale(
        balance.read(tmp_path, "silver"), today=date(2026, 8, 29)
    ), "90일 넘으면 낡았다"
    balance.write(tmp_path, _doc(asof="2026-08-01"))
    assert not balance.is_stale(balance.read(tmp_path, "silver"), today=date(2026, 8, 29))


def test_missing_survey_is_not_neutral(tmp_path: Path) -> None:
    """조사가 없는 테마를 '수급 중립' 으로 읽지 않는다 (`docs/26` §5)."""
    line = balance.summarize_theme(None)
    assert "조사 없음" in line
    # 토큰 부재 검사를 쓰지 않는다 — 문구가 정당하게 "중립이 아니다" 라고 부정하는데
    # `"중립" not in line` 은 그 부정문을 위반으로 센다 (P2 에서 같은 실수를 했다).
    assert "중립이라는 뜻이 아니다" in line
    assert not any(v in line for v in balance.BALANCE_VERDICTS), "없는 판정을 지어내지 않는다"


# ---------------------------------------------------------------- 회전 선정


def test_rotation_picks_the_stalest_first(tmp_path: Path) -> None:
    """가장 오래 조사 안 된 편입 가능 테마부터 — **코드가 고른다.**"""
    balance.write(tmp_path, _doc(theme="a", asof="2026-08-20"))
    balance.write(tmp_path, _doc(theme="b", asof="2026-01-05"))
    got = balance.rotation(tmp_path, ["a", "b", "c"], n=2, today=date(2026, 8, 29))
    assert got == ["c", "b"], "조사 없는 c 가 먼저, 그다음 가장 낡은 b"


def test_rotation_skips_fresh_surveys(tmp_path: Path) -> None:
    balance.write(tmp_path, _doc(theme="a", asof="2026-08-28"))
    assert balance.rotation(tmp_path, ["a"], n=3, today=date(2026, 8, 29)) == []


def test_rotation_zero_is_empty(tmp_path: Path) -> None:
    assert balance.rotation(tmp_path, ["a", "b"], n=0, today=date(2026, 8, 29)) == []


# ---------------------------------------------------------------- 점수 격리


def test_balance_never_reaches_the_triage_score() -> None:
    """**수급은 트리아지 점수에 안 들어간다** (`docs/26` §3.5).

    넣는 순간 "수급이 타이트하면 더 오른다" 는 검정 안 된 명제가 점수가 된다.
    """
    from msa import triage

    d = triage.declared_constants()
    text = repr(d)
    for token in ("balance", "tightening", "rigidity", "supply_demand"):
        assert token not in text, f"트리아지 선언값에 수급이 새어들어갔다: {token}"


def test_summarize_theme_reports_verdict_and_age() -> None:
    line = balance.summarize_theme(_doc(), today=date(2026, 8, 29))
    assert "tightening" in line
    assert "silver" in line


# ---------------------------------------------------------------- 조사 에이전트


def test_prompt_forbids_price_and_stocks() -> None:
    from msa.l35 import analyst

    text = analyst.build_request("silver", "2026-08-29").as_text()
    for phrase in analyst.REQUIRED_PROHIBITIONS:
        assert phrase in text
    assert "물량 대 물량" in text


def test_prompt_lists_all_five_rigidity_kinds() -> None:
    """분류할 수 없으면 그 주장을 싣지 말라고 해야 한다."""
    from msa.l35 import analyst

    text = analyst.build_request("silver", "2026-08-29").as_text()
    for kind in balance.RIGIDITY_KINDS:
        assert kind in text


def test_prompt_carries_the_prior_thesis_to_avoid_double_search() -> None:
    """같은 웹 검색을 두 번 하지 않는다 (`docs/26` §4)."""
    from msa.l35 import analyst

    thesis = {
        "claim": "컨테이너 해운의 자본 사이클은 확장 국면이다",
        "axes": {"unit_demand": {"referee_ruling": "물량은 유지되고 있다"}},
        "invalidations": ["해체가 연 50척을 넘으면 무효"],
    }
    text = analyst.build_request("shipping_container", "2026-08-29", thesis=thesis).as_text()
    assert "자본 사이클은 확장 국면" in text
    assert "물량은 유지되고 있다" in text
    assert "같은 검색을 반복하지 마라" in text

    bare = analyst.build_request("x", "2026-08-29").as_text()
    assert "아직 `msa research` 를 거치지 않았다" in bare


def test_mock_output_is_labelled_and_valid() -> None:
    from msa.l35 import analyst

    doc = {"theme": "t", "asof": "2026-08-29", **analyst.MOCK_OUTPUT}
    balance.validate(doc)
    assert doc["synthetic"] is True
    assert "합성" in doc["balance"]["ratio_note"]


def test_run_preserves_the_synthetic_flag() -> None:
    from msa.l35 import analyst

    class _P:
        def complete(self, req: object) -> object:
            class _R:
                @staticmethod
                def json() -> dict[str, object]:
                    return dict(analyst.MOCK_OUTPUT)

            return _R()

    doc = analyst.run(_P(), "silver", "2026-08-29")
    assert doc["synthetic"] is True
    balance.validate(doc)


def test_report_says_it_is_a_thesis_not_a_list() -> None:
    from msa.l35 import analyst

    md = analyst.render_report(_doc())
    assert "논지이지 명단이 아니다" in md
    assert "byproduct" in md
    assert "무엇이 이 격차를 메우나" in md
