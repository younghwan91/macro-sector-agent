"""P3 종목 분석가 — 설계 §9.2. 합성 dict, 네트워크 없음.

이 파일이 지키는 것은 하나다: **LLM 이 종목을 고르지 못한다** (`CLAUDE.md` §4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from msa import triage
from msa.l4 import analyst


def _note(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "ticker": "AAA",
        "theme": "t1",
        "asof": "2026-08-29",
        "verdict": "intact",
        "mechanism": "2029년까지 만기가 없고 FCF 가 양수다.",
        "invalidations": ["2027년 차환이 8% 이상 금리로 이뤄지면 이 판정은 무효다"],
        "evidence": [
            {
                "claim": "장기부채 만기 2029",
                "source_url": "https://www.sec.gov/example",
                "date": "2026-07-31",
                "reliability": "high",
            }
        ],
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------- 후보는 코드가 정한다


def test_candidates_are_chosen_by_code_from_partition_ia() -> None:
    """LLM 은 명단을 만들지 않고 **받는다** (`CLAUDE.md` §4)."""
    rows = [
        {"ticker": "LOW", "theme": "t", "partition": "I-A", "triage": 0.60},
        {"ticker": "TOP", "theme": "t", "partition": "I-A", "triage": 0.90},
        {"ticker": "OTHER", "theme": "t", "partition": "I-B", "triage": 0.99},
    ]
    got = analyst.candidates(rows, partition="I-A", top_n=2)
    assert [c.ticker for c in got] == ["TOP", "LOW"]


def test_candidates_skip_uncomputable_triage() -> None:
    rows = [
        {"ticker": "NA", "theme": "t", "partition": "I-A", "triage": None},
        {"ticker": "OK", "theme": "t", "partition": "I-A", "triage": 0.5},
    ]
    assert [c.ticker for c in analyst.candidates(rows, partition="I-A", top_n=5)] == ["OK"]


def test_candidates_zero_is_empty_not_everything() -> None:
    rows = [{"ticker": "A", "theme": "t", "partition": "I-A", "triage": 0.5}]
    assert analyst.candidates(rows, partition="I-A", top_n=0) == []


# ---------------------------------------------------------------- 질문은 하나뿐이다


def test_schema_has_nowhere_to_put_a_recommendation() -> None:
    """'살 만한가' 의 답을 담을 칸이 없다 — 진짜 보증은 스키마다."""
    assert set(analyst.SCHEMA["properties"]) == {
        "verdict",
        "mechanism",
        "invalidations",
        "evidence",
    }
    assert analyst.SCHEMA["properties"]["verdict"]["enum"] == list(analyst.VERDICTS)
    assert "목표가" in analyst.SCHEMA["properties"]["mechanism"]["description"]


def test_prompt_carries_the_prohibitions_and_the_single_question() -> None:
    cand = analyst.Candidate("AAA", "t1", 0.8)
    text = analyst.build_request(cand, {"price": 10.0}, "2026-08-29").as_text()
    for phrase in analyst.REQUIRED_PROHIBITIONS:
        assert phrase in text
    assert "재무가 무너지고 있는가" in text


def test_prompt_shows_the_same_numbers_the_human_sees() -> None:
    """분석가가 다른 숫자를 보고 다른 말을 하면 사람이 대조할 수 없다."""
    cand = analyst.Candidate("AAA", "t1", 0.8)
    pick = {"price": 13.56, "cash_runway_q": 6.0, "red_flags": "consecutive_operating_loss"}
    text = analyst.build_request(cand, pick, "2026-08-29").as_text()
    assert "13.56" in text and "consecutive_operating_loss" in text


# ---------------------------------------------------------------- 산출은 재료다


def test_evidence_and_invalidations_are_required() -> None:
    with pytest.raises(analyst.NoteRejected, match="evidence"):
        analyst.validate(_note(evidence=[]))
    with pytest.raises(analyst.NoteRejected, match="invalidations"):
        analyst.validate(_note(invalidations=[]))


def test_unknown_verdict_is_refused() -> None:
    with pytest.raises(analyst.NoteRejected, match="verdict"):
        analyst.validate(_note(verdict="buy"))


def test_note_roundtrip(tmp_path: Path) -> None:
    analyst.write(tmp_path, _note())
    got = analyst.read(tmp_path, "AAA")
    assert got is not None and got["verdict"] == "intact"
    assert analyst.read(tmp_path, "NOPE") is None


def test_load_all_omits_tickers_without_notes(tmp_path: Path) -> None:
    """없음을 0 으로 채우면 안 부른 종목이 '무너지는 종목' 과 같은 값을 받는다."""
    analyst.write(tmp_path, _note(ticker="AAA", verdict="breaking"))
    got = analyst.load_all(tmp_path, ["AAA", "BBB"])
    assert got == {"AAA": 0.20}
    assert "BBB" not in got


def test_summarize_says_missing_is_not_intact() -> None:
    assert "안 불렀다" in analyst.summarize([])


# ---------------------------------------------------------------- 점수 결합


def test_j_without_a_note_is_exactly_the_theme_value() -> None:
    """**오늘의 식이 이 확장의 특수해다** (설계 §9.2)."""
    assert triage.blend_ticker_trust(0.74, None) == 0.74


def test_j_with_a_note_is_the_half_half_blend() -> None:
    assert triage.blend_ticker_trust(0.80, 0.20) == pytest.approx(0.50)
    assert triage.blend_ticker_trust(0.80, 1.00) == pytest.approx(0.90)


def _digest(notes: dict[str, float] | None) -> dict[str, object]:
    d: dict[str, object] = {
        "themes": [
            {
                "theme": "t1",
                "picks": [
                    {"ticker": "AAA", "from_52w_high": -0.40, "red_flags": ""},
                    {"ticker": "BBB", "from_52w_high": -0.30, "red_flags": ""},
                ],
            }
        ],
        "judged": [
            {"theme": "t1", "portfolio_eligible": True, "trusted": True, "gate": "passed"}
        ],
        "evidence_audit": {
            "t1": {"counts": {"verified": 20}, "checked": 20, "unverified_axes": []}
        },
    }
    if notes is not None:
        d["stock_notes"] = notes
    return d


def test_breaking_note_lowers_only_that_ticker() -> None:
    base = {r.ticker: r.j for r in triage.score_digest(_digest(None))}
    with_note = {r.ticker: r.j for r in triage.score_digest(_digest({"AAA": 0.20}))}
    assert base["AAA"] == base["BBB"] == pytest.approx(1.0)
    assert with_note["AAA"] == pytest.approx(0.6)
    assert with_note["BBB"] == pytest.approx(1.0), "노트 없는 종목은 안 움직인다"


def test_note_cannot_move_a_stock_between_partitions() -> None:
    """구획은 판별과 낙폭이 정한다 — 종목 분석가도 발언권이 없다."""
    base = {r.ticker: r.partition for r in triage.score_digest(_digest(None))}
    got = {r.ticker: r.partition for r in triage.score_digest(_digest({"AAA": 0.20}))}
    assert base == got


def test_note_does_not_touch_c_or_r() -> None:
    base = {r.ticker: (r.c, r.r) for r in triage.score_digest(_digest(None))}
    got = {r.ticker: (r.c, r.r) for r in triage.score_digest(_digest({"AAA": 0.20}))}
    assert base == got


def test_declared_constants_carry_note_trust() -> None:
    d = triage.declared_constants()
    assert d["note_trust"] == analyst.NOTE_TRUST
    assert "특수해" in d["note_trust_source"]


def test_mock_output_is_labelled_synthetic() -> None:
    """--dry-run 산출이 실수로 저장돼도 사람이 실제 판정과 구분할 수 있어야 한다."""
    assert "합성" in analyst.MOCK_OUTPUT["mechanism"]
    analyst.validate({**analyst.MOCK_OUTPUT, "ticker": "AAA"})


def test_mock_role_is_registered_once() -> None:
    from msa.l3 import roles

    assert "stock_analyst" in roles.MOCK_OUTPUTS
    with pytest.raises(ValueError, match="이미 등록된 역할"):
        roles.register_mock_output("stock_analyst", {})


def test_daily_stock_notes_block_reads_the_store(tmp_path: Path, monkeypatch) -> None:
    from msa.pipeline import daily as D

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    analyst.write(tmp_path / "stock_notes", _note(ticker="AAA", verdict="breaking"))
    digest = {"themes": [{"picks": [{"ticker": "AAA"}, {"ticker": "BBB"}]}]}
    got = D._stock_notes_block(digest)
    assert got == {"AAA": 0.20}, "노트 없는 BBB 는 키가 없어야 한다"
