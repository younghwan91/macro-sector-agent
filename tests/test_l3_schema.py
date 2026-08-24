"""thesis 스키마 검증 — `docs/05` §4 규약의 각 행이 검증기/테스트가 된다."""

from __future__ import annotations

import pytest

from _l3_synth import valid_thesis
from msa.l3.schema import load_spec, validate_thesis


def _codes(res) -> set[str]:  # type: ignore[no-untyped-def]
    return {e.split(":")[0] for e in res.errors}


def _wcodes(res) -> set[str]:  # type: ignore[no-untyped-def]
    return {w.split(":")[0] for w in res.warnings}


def test_spec_required_matches_code() -> None:
    """스키마 파일의 required 목록이 바뀌면 여기서 잡힌다."""
    spec = load_spec()
    assert set(spec["required"]) >= {
        "theme_id",
        "claim",
        "mechanism",
        "triggers",
        "invalidations",
        "bear_case",
        "value_trap_axes",
        "cycle_confidence",
        "evidence",
    }


def test_valid_thesis_passes() -> None:
    res = validate_thesis(valid_thesis(), asof="2026-08-14")
    assert res.ok, res.errors
    # low 등급 증거 3번(2024-01)은 12개월 초과 → 경고만
    assert "W_EVIDENCE_STALE" in _wcodes(res)


def test_evidence_empty_rejected() -> None:
    t = valid_thesis()
    t["evidence"] = []
    res = validate_thesis(t, asof="2026-08-14")
    assert "R_EVIDENCE_EMPTY" in _codes(res)


def test_evidence_item_fields_required() -> None:
    t = valid_thesis()
    del t["evidence"][0]["source_url"]
    t["evidence"][1]["date"] = ""
    res = validate_thesis(t, asof="2026-08-14")
    assert "R_EVIDENCE_FIELD" in _codes(res)


def test_invalidations_empty_rejected() -> None:
    t = valid_thesis()
    t["invalidations"] = []
    res = validate_thesis(t, asof="2026-08-14")
    assert "R_INVALIDATIONS_EMPTY" in _codes(res)


def test_invalidation_action_enum() -> None:
    t = valid_thesis()
    t["invalidations"][0]["action"] = "sell"
    assert "R_INVALIDATION_ACTION" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_triggers_must_be_observable() -> None:
    t = valid_thesis()
    t["triggers"][0]["observable"] = "시장 심리 개선"
    assert "R_TRIGGER_NOT_OBSERVABLE" in _codes(validate_thesis(t, asof="2026-08-14"))
    t = valid_thesis()
    t["triggers"] = []
    assert "R_TRIGGERS_EMPTY" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_mechanism_correlation_language_rejected() -> None:
    t = valid_thesis()
    t["mechanism"] = "우라늄주는 역사적으로 함께 움직였으므로 이번에도 오른다."
    assert "R_MECHANISM_CORRELATION" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_claim_stock_name_warns() -> None:
    t = valid_thesis()
    t["claim"] = "CCJ 가 2027년까지 두 배 오른다."
    res = validate_thesis(t, asof="2026-08-14", member_tickers=("CCJ", "UEC"))
    assert "W_CLAIM_NAMES_STOCK" in _wcodes(res)
    assert res.ok  # 경고이지 거부가 아니다
    res2 = validate_thesis(t, asof="2026-08-14", member_names=("Cameco Corp",))
    assert "W_CLAIM_NAMES_STOCK" not in _wcodes(
        res2
    )  # 이름은 없고 티커만 — 티커 목록 없으면 못 잡는다


def test_claim_too_long() -> None:
    t = valid_thesis()
    t["claim"] = "가" * 401
    assert "R_CLAIM_TOO_LONG" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_low_reliability_only_cannot_judge_axis() -> None:
    t = valid_thesis()
    t["value_trap_axes"]["substitution"]["evidence_refs"] = [3]  # low only
    assert "R_AXIS_LOW_RELIABILITY_ONLY" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_axis_judged_without_evidence_rejected() -> None:
    t = valid_thesis()
    t["value_trap_axes"]["cost_curve"]["evidence_refs"] = []
    assert "R_AXIS_NO_EVIDENCE" in _codes(validate_thesis(t, asof="2026-08-14"))
    t = valid_thesis()
    t["value_trap_axes"]["cost_curve"]["verdict"] = "not_applicable"
    t["value_trap_axes"]["cost_curve"]["evidence_refs"] = []
    # 축 판정을 바꾸면 gate_result.axis_verdicts 스냅샷도 같이 바뀌어야 한다 (재도출 대조)
    t["gate_result"]["axis_verdicts"]["cost_curve"] = "not_applicable"
    assert validate_thesis(t, asof="2026-08-14").ok  # not_applicable 은 증거 없이 닫을 수 있다


def test_dangling_evidence_ref_rejected() -> None:
    t = valid_thesis()
    t["value_trap_axes"]["capital_cycle"]["evidence_refs"] = [99]
    assert "R_AXIS_REFS_DANGLING" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_bear_case_must_be_verbatim() -> None:
    t = valid_thesis()
    res = validate_thesis(t, asof="2026-08-14", bear_case_original="원문 bear case 의 긴 서술 ...")
    assert "R_BEAR_CASE_NOT_VERBATIM" in _codes(res)
    assert validate_thesis(t, asof="2026-08-14", bear_case_original="원문 bear case").ok


def test_contested_requires_ruling_and_refs() -> None:
    t = valid_thesis()
    # contested 는 축1 이 실제로 contested 일 때만 나온다 (04 §3.1) — 재도출 대조가 그것을
    # 요구하므로 축1·스냅샷·확신도를 함께 맞춘다 (축1 무가감 + 축3 cycle → 0.50 + 0.15)
    t["value_trap_axes"]["unit_demand"].update({"verdict": "contested", "axis1_contested": True})
    t["gate_result"]["axis_verdicts"]["unit_demand"] = "contested"
    t["cycle_confidence"] = 0.65
    t["gate_result"].update({"status": "contested", "portfolio_eligible": False})
    assert "R_CONTESTED_WITHOUT_RULING" in _codes(validate_thesis(t, asof="2026-08-14"))
    t["gate_result"]["referee_ruling"] = "산업 축소이지 수요 소멸이 아니다"
    t["gate_result"]["referee_evidence_refs"] = [1]
    assert validate_thesis(t, asof="2026-08-14").ok


def test_contested_or_rejected_cannot_be_eligible() -> None:
    t = valid_thesis()
    t["gate_result"].update({"status": "rejected", "path": "hard_gate", "portfolio_eligible": True})
    assert "R_GATE_ELIGIBLE" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_rejected_needs_ledger_path() -> None:
    t = valid_thesis()
    t["gate_result"].update({"status": "rejected", "portfolio_eligible": False})
    assert "R_GATE_PATH" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_axis1_not_applicable_consistency() -> None:
    t = valid_thesis()
    ud = t["value_trap_axes"]["unit_demand"]
    ud.update({"axis1_available": False})  # verdict 는 cycle 그대로 → 모순
    codes = _codes(validate_thesis(t, asof="2026-08-14"))
    assert (
        "R_AXIS1_NA" in codes and "R_AXIS1_NA_SOURCE" in codes and "R_AXIS1_NA_UNCERTAINTY" in codes
    )
    ud.update({"verdict": "not_applicable", "unit_series_source": "none", "evidence_refs": []})
    t["key_uncertainties"].append("axis1_available = false")
    t["gate_result"]["axis_verdicts"]["unit_demand"] = "not_applicable"
    t["cycle_confidence"] = 0.65  # 축1 적용 불가 → +0.15 가 빠진다 (04 §4 재도출)
    assert validate_thesis(t, asof="2026-08-14").ok
    ud.update({"axis1_available": True, "verdict": "cycle", "evidence_refs": [1]})
    assert "R_AXIS1_SOURCE_NONE" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_axis1_contested_flag_forces_verdict() -> None:
    t = valid_thesis()
    t["value_trap_axes"]["unit_demand"]["axis1_contested"] = True
    assert "R_AXIS1_CONTESTED_VERDICT" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_confidence_range() -> None:
    t = valid_thesis()
    t["cycle_confidence"] = 1.2
    assert "R_CONFIDENCE_RANGE" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_missing_required_field_short_circuits() -> None:
    t = valid_thesis()
    del t["bear_case"]
    res = validate_thesis(t, asof="2026-08-14")
    assert "R_REQUIRED" in _codes(res)


@pytest.mark.parametrize(
    "phrase", ["상관관계가 높다", "과거에도 올랐다", "historically moved together"]
)
def test_correlation_phrase_list(phrase: str) -> None:
    t = valid_thesis()
    t["mechanism"] = f"공급 부족. 그리고 {phrase}."
    assert "R_MECHANISM_CORRELATION" in _codes(validate_thesis(t, asof="2026-08-14"))


# ---------------------------------------------------------------------------
# 재도출 대조 — 저장된 cycle_confidence · gate_result 를 코드로 다시 도출해 본다
# ---------------------------------------------------------------------------


def test_tampered_confidence_rejected() -> None:
    """확신도를 손으로 올려 적으면 거부한다 (04 §4 의 산출이 아니다)."""
    t = valid_thesis()
    t["cycle_confidence"] = 0.99
    assert "R_CONFIDENCE_RECOMPUTE" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_confidence_recompute_allows_unknown_l1_terms() -> None:
    """L1 입력(축2 분기수·소표본)이 thesis 에 없으면 그 항이 붙은 값도 붙지 않은 값도 통과 —
    다만 없다는 사실은 경고로 남는다 (CLAUDE.md §2)."""
    for c in (0.70, 0.80, 0.90):  # -0.10 / 0 / +0.10
        t = valid_thesis()
        t["cycle_confidence"] = c
        res = validate_thesis(t, asof="2026-08-14")
        assert res.ok, (c, res.errors)
        assert "W_CONFIDENCE_INPUT_ABSENT" in _wcodes(res)
    t = valid_thesis()
    t["cycle_confidence"] = 0.85  # 어떤 항 조합으로도 나오지 않는다
    assert "R_CONFIDENCE_RECOMPUTE" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_confidence_terms_pin_the_unknown_inputs() -> None:
    """기계 산출물이 적어 둔 `cycle_confidence_terms` 가 있으면 값이 하나로 고정된다."""
    t = valid_thesis()
    t["cycle_confidence_terms"] = {"base": 0.5, "axis1_cycle": 0.15, "axis3_no_substitution": 0.15}
    t["cycle_confidence"] = 0.80
    res = validate_thesis(t, asof="2026-08-14")
    assert res.ok, res.errors
    assert "W_CONFIDENCE_INPUT_ABSENT" not in _wcodes(res)
    t["cycle_confidence"] = 0.90  # 축2 항을 적지 않았으므로 이제 허용되지 않는다
    assert "R_CONFIDENCE_RECOMPUTE" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_all_axes_not_applicable_cannot_be_eligible() -> None:
    """5축 전부 적용 불가인데 portfolio_eligible: true — 04 §3.5 재도출이 잡는다."""
    t = valid_thesis()
    for a in ("unit_demand", "capital_cycle", "substitution", "cost_curve", "terminal_risk"):
        t["value_trap_axes"][a]["verdict"] = "not_applicable"
        t["value_trap_axes"][a]["evidence_refs"] = []
        t["gate_result"]["axis_verdicts"][a] = "not_applicable"
    t["value_trap_axes"]["unit_demand"].update(
        {"axis1_available": False, "unit_series_source": "none"}
    )
    t["key_uncertainties"].append("axis1_available = false")
    t["cycle_confidence"] = 0.50
    codes = _codes(validate_thesis(t, asof="2026-08-14"))
    assert "R_GATE_RECOMPUTE" in codes
    t["gate_result"]["portfolio_eligible"] = False
    assert validate_thesis(t, asof="2026-08-14").ok


def test_axis_verdicts_snapshot_must_match_body() -> None:
    t = valid_thesis()
    t["gate_result"]["axis_verdicts"]["substitution"] = "death"
    assert "R_GATE_VERDICTS_MISMATCH" in _codes(validate_thesis(t, asof="2026-08-14"))


def test_axis1_contested_derived_from_pre_post() -> None:
    """스키마가 선언한 파생 — pre != post 면 axis1_contested 는 true 여야 한다."""
    t = valid_thesis()
    t["value_trap_axes"]["unit_demand"].update(
        {"verdict_pre_ss": "cycle", "verdict_post_ss": "warning", "axis1_contested": False}
    )
    assert "R_AXIS1_CONTESTED_DERIVED" in _codes(validate_thesis(t, asof="2026-08-14"))


# ---------------------------------------------------------------------------
# 증거 규약 — 미래 날짜
# ---------------------------------------------------------------------------


def test_future_evidence_date_rejected() -> None:
    t = valid_thesis()
    t["evidence"][0]["date"] = "2026-08-15"  # asof 다음 날
    assert "R_EVIDENCE_FUTURE" in _codes(validate_thesis(t, asof="2026-08-14"))
    assert validate_thesis(t, asof="2026-08-31").ok  # asof 를 넘기면 더 이상 미래가 아니다


def test_source_url_memory_stays_a_warning() -> None:
    """`docs/05` §3·§6 은 `source_url` 필수 + 12개월 표시만 요구한다 — 형식 위반은 경고 그대로."""
    t = valid_thesis()
    t["evidence"][0]["source_url"] = "내 기억"
    res = validate_thesis(t, asof="2026-08-14")
    assert "W_EVIDENCE_URL" in _wcodes(res)
    assert res.ok


# ---------------------------------------------------------------------------
# 종목 경계 — 검사 필드 확대 (등급은 경고 그대로, docs/05 §4)
# ---------------------------------------------------------------------------


def test_stock_mention_checked_beyond_claim() -> None:
    t = valid_thesis()
    t["mechanism"] = "HD 가 재고를 늘린다 — " + t["mechanism"]
    t["triggers"][0]["observable"] = "LOW 분기 실적에서 동일점포 매출 반등"
    t["key_uncertainties"].append("HD 의 프로 매출 비중 불명")
    res = validate_thesis(t, asof="2026-08-14", member_tickers=("HD", "LOW"))
    ws = " ".join(res.warnings)
    assert "mechanism 에 종목명" in ws
    assert "triggers 에 종목명" in ws
    assert "key_uncertainties 에 종목명" in ws
    assert res.ok  # 경고이지 거부가 아니다
