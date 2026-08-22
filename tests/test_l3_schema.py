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
