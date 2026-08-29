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
            "cagr_pct": 4.0,
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
            "cagr_pct": 1.0,
        },
        "balance": {
            "verdict": "tightening",
            "ratio_note": "수요 4% · 공급 1% → 연 3%p 벌어진다",
            "what_would_close_it": ["은 가격이 3년 이상 높게 유지되면 1차 은광이 FID 를 받는다"],
            "who_captures_it": "은광 생산자와 보유자 — 부족분이 가격으로 전가된다",
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
    d["demand"]["cagr_pct"] = None  # type: ignore[index]
    d["supply"]["cagr_pct"] = None  # type: ignore[index]
    balance.validate(d)


def test_cagr_is_percent_points_not_a_ratio() -> None:
    """2026-08-29 실측 회귀 — 에이전트가 "-0.9%" 를 `-0.9` 로 썼는데 스키마는 비율을
    뜻했고, 리포트가 **-90%** 로 찍혔다. 단위가 모호했던 것이 원인이다.

    이제 필드는 퍼센트 포인트이고, **비율로 쓴 것을 거부한다.**
    """
    d = _doc()
    d["supply"]["cagr_pct"] = -0.9  # 실버 실측값 — -0.9%p 로 정당하다  # type: ignore[index]
    balance.validate(d)

    d["supply"]["cagr_pct"] = 0.04  # 4% 를 비율로 쓴 것  # type: ignore[index]
    with pytest.raises(balance.BalanceRejected, match="비율로 잘못 쓴 것"):
        balance.validate(d)


def test_cagr_beyond_the_hygiene_bound_is_refused() -> None:
    """±100%p 를 넘는 실물 증가율은 단위 오류다 — 판정 임계가 아니라 오류 탐지기다."""
    d = _doc()
    d["demand"]["cagr_pct"] = 250.0  # type: ignore[index]
    with pytest.raises(balance.BalanceRejected, match="퍼센트 포인트 단위다"):
        balance.validate(d)


def test_cagr_zero_is_allowed_as_an_explicit_judgment() -> None:
    """0 은 '모른다' 가 아니라 '안 움직인다' 는 판정이다 — 거부하지 않는다."""
    d = _doc()
    d["demand"]["cagr_pct"] = 0.0  # type: ignore[index]
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


# ---------------------------------------------------------------- 일간 리포트 배선


def test_daily_digest_carries_the_balance_block(tmp_path, monkeypatch) -> None:
    """설계 §3.5 가 "리포트에 표시된다" 고 적었으므로 실제로 실려야 한다."""
    from msa.pipeline import daily as D

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    balance.write(tmp_path / "balance", _doc(theme="t1"))
    digest = {
        "judged": [
            {"theme": "t1", "portfolio_eligible": True},
            {"theme": "t2", "portfolio_eligible": True},
            {"theme": "t3", "portfolio_eligible": False},
        ]
    }
    block = D._balance_block(digest)
    assert block["surveyed"] == ["t1"]
    assert block["missing"] == ["t2"], "편입 가능인데 조사 없는 것을 짚어야 한다"
    assert "t3" not in block["missing"], "편입 불가 테마는 조사 대상이 아니다"
    assert "tightening" in block["lines"][0]


def test_surveys_of_non_eligible_themes_are_still_shown(tmp_path, monkeypatch) -> None:
    """**가진 조사는 전부 싣는다.** 2026-08-29 실측: 편입 가능한 것만 싣던 초안이
    `silver_miners` 조사를 리포트에서 통째로 지웠다. 조사해 둔 것이 안 보이면 아무도
    다시 안 본다."""
    from msa.pipeline import daily as D

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    balance.write(tmp_path / "balance", _doc(theme="silver_miners"))
    block = D._balance_block({"judged": [{"theme": "other", "portfolio_eligible": True}]})
    assert block["surveyed"] == ["silver_miners"]
    assert "오늘 편입 가능 테마는 아니다" in block["lines"][0]
    assert block["missing"] == ["other"]


def test_daily_balance_block_survives_missing_store(tmp_path, monkeypatch) -> None:
    from msa.pipeline import daily as D

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    block = D._balance_block({"judged": [{"theme": "t1", "portfolio_eligible": True}]})
    assert block["surveyed"] == []
    assert block["missing"] == ["t1"]


def test_balance_section_md_says_missing_is_not_neutral() -> None:
    from msa.pipeline import daily as D

    block = {"balance": {"lines": [], "missing": ["a"], "surveyed": []}}
    md = "\n".join(D.balance_section_md(block))
    assert "`a`" in md
    assert "중립" not in md.replace("중립이라는 뜻이 아니다", "")


def test_balance_section_empty_when_no_block() -> None:
    from msa.pipeline import daily as D

    assert D.balance_section_md({}) == []


def test_who_captures_it_is_required_when_tightening() -> None:
    """**2026-08-29 실측이 만든 규칙.** `managed_care` 가 tightening 으로 나왔는데 분석가
    스스로 "격차의 실체는 초과수요가 아니라 무보험 전환" 이라고 적었다 — 줄어드는 공급이
    곧 산업 자체의 축소였고, 그 격차를 가져가는 주체가 없었다.

    가져가는 주체가 없으면 그것은 타이트가 아니라 **축소**다.
    """
    d = _doc()
    d["balance"]["who_captures_it"] = ""  # type: ignore[index]
    with pytest.raises(balance.BalanceRejected, match="who_captures_it"):
        balance.validate(d)


def test_who_captures_it_not_required_when_not_tightening() -> None:
    d = _doc()
    d["balance"]["verdict"] = "balanced"  # type: ignore[index]
    d["balance"]["who_captures_it"] = ""  # type: ignore[index]
    balance.validate(d)


def test_report_asks_who_captures_the_gap() -> None:
    from msa.l35 import analyst

    md = analyst.render_report(_doc())
    assert "이 격차를 누가 가져가나" in md
    assert "은광 생산자와 보유자" in md


def test_prompt_warns_about_industry_shrinkage() -> None:
    from msa.l35 import analyst

    text = analyst.build_request("x", "2026-08-29").as_text()
    assert "who_captures_it" in text
    assert "산업의 축소" in text
