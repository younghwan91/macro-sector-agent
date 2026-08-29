"""P4 리스크 매니저 + PM — 설계 §9.3.

이 파일이 지키는 것 하나: **점수를 바꾸지 않는다.** 경고를 달고 표시를 나눌 뿐이다.
"""

from __future__ import annotations

import pytest

from msa import triage
from msa.l4 import risk


def _row(ticker: str, theme: str, tri: float, j: float | None = 0.8) -> dict[str, object]:
    return {"ticker": ticker, "theme": theme, "partition": "I-A", "triage": tri, "j": j}


# ---------------------------------------------------------------- 리스크 매니저


def test_theme_concentration_is_flagged() -> None:
    rows = [_row(f"T{i}", "same", 0.9 - i / 100) for i in range(4)] + [_row("X", "other", 0.5)]
    got = risk.concentration_warnings(rows, {"same": "c1", "other": "c2"})
    kinds = {w.kind for w in got}
    assert "theme_concentration" in kinds
    assert "4개가 `same` 한 테마다" in " ".join(w.text for w in got)


def test_cluster_concentration_catches_different_themes_same_bet() -> None:
    """테마는 달라도 같은 것에 걸린다."""
    rows = [
        _row("A", "reit_office", 0.9),
        _row("B", "reit_retail", 0.8),
        _row("C", "reit_industrial", 0.7),
        _row("D", "steel", 0.6),
    ]
    clusters = {
        "reit_office": "reit",
        "reit_retail": "reit",
        "reit_industrial": "reit",
        "steel": "base_metals",
    }
    got = risk.concentration_warnings(rows, clusters)
    assert any(w.kind == "cluster_concentration" for w in got)
    assert any("`reit` 군집" in w.text for w in got)


def test_unknown_cluster_is_reported_not_silently_grouped() -> None:
    """없는 것을 같은 군집으로 묶으면 가짜 집중이 만들어진다 (`CLAUDE.md` §2)."""
    rows = [_row("A", "known", 0.9), _row("B", "mystery", 0.8)]
    got = risk.concentration_warnings(rows, {"known": "c1"})
    assert any(w.kind == "cluster_unknown" for w in got)
    assert any("`mystery`" in w.text for w in got)


def test_no_warning_for_a_single_row() -> None:
    assert risk.concentration_warnings([_row("A", "t", 0.9)], {"t": "c"}) == []


def test_diverse_list_gets_no_concentration_warning() -> None:
    rows = [_row(f"T{i}", f"theme{i}", 0.9) for i in range(5)]
    clusters = {f"theme{i}": f"c{i}" for i in range(5)}
    got = [w for w in risk.concentration_warnings(rows, clusters) if w.kind != "cluster_unknown"]
    assert got == []


# ---------------------------------------------------------------- PM 슬롯


def test_slot_budget_is_proportional_to_j() -> None:
    got = risk.slot_budget({"well_known": 1.0, "half": 0.5, "poor": 0.0})
    assert got["well_known"] == risk.SLOT_MAX
    assert got["poor"] == risk.SLOT_MIN
    assert risk.SLOT_MIN < got["half"] < risk.SLOT_MAX


def test_slot_budget_never_reaches_zero() -> None:
    """슬롯 0 은 '이 테마는 보지 마라' 가 되는데 그 판정은 L3 게이트의 몫이다."""
    assert min(risk.slot_budget({"a": 0.0, "b": None}).values()) == risk.SLOT_MIN >= 1


def test_uncomputable_j_gets_the_minimum_not_the_maximum() -> None:
    assert risk.slot_budget({"unknown": None})["unknown"] == risk.SLOT_MIN


def test_apply_slots_defers_but_never_deletes() -> None:
    """PM 은 화면을 나누는 것이지 명단을 자르는 것이 아니다."""
    rows = [_row(f"T{i}", "same", 0.9 - i / 100) for i in range(6)]
    inside, outside = risk.apply_slots(rows, {"same": 2})
    assert [r["ticker"] for r in inside] == ["T0", "T1"]
    assert [r["ticker"] for r in outside] == ["T2", "T3", "T4", "T5"]
    assert len(inside) + len(outside) == len(rows), "합치면 입력과 같아야 한다"


def test_apply_slots_keeps_relative_order() -> None:
    rows = [_row("A", "x", 0.9), _row("B", "y", 0.8), _row("C", "x", 0.7)]
    inside, outside = risk.apply_slots(rows, {"x": 1, "y": 5})
    assert [r["ticker"] for r in inside] == ["A", "B"]
    assert [r["ticker"] for r in outside] == ["C"]


# ---------------------------------------------------------------- 점수 불변


def test_review_does_not_touch_any_score() -> None:
    """**이 모듈의 존재 이유다** — 점수를 바꾸지 않는다."""
    rows = [_row("A", "t1", 0.9), _row("B", "t1", 0.8), _row("C", "t2", 0.7)]
    before = [dict(r) for r in rows]
    risk.review(rows, {"t1": "c1", "t2": "c2"}, partition="I-A")
    assert rows == before


def test_review_shape() -> None:
    rows = [_row("A", "t1", 0.9, j=1.0), _row("B", "t1", 0.8, j=1.0)]
    got = risk.review(rows, {"t1": "c1"}, partition="I-A")
    assert got["partition"] == "I-A"
    assert got["n"] == 2
    assert set(got["shown"]) == {"A", "B"}
    assert got["deferred"] == []
    assert "점수를 깎지 않는다" in got["note"]


def test_review_ignores_other_partitions() -> None:
    rows = [_row("A", "t1", 0.9), {**_row("B", "t1", 0.99), "partition": "I-B"}]
    got = risk.review(rows, {"t1": "c1"}, partition="I-A")
    assert got["n"] == 1 and got["shown"] == ["A"]


def test_triage_scores_are_identical_with_and_without_risk_review() -> None:
    digest = {
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
    rows = [
        {"ticker": r.ticker, "theme": r.theme, "partition": r.partition, "triage": r.triage,
         "j": r.j}
        for r in triage.score_digest(digest)
    ]
    before = {r["ticker"]: r["triage"] for r in rows}
    risk.review(rows, {"t1": "c1"}, partition="I-A")
    after = {r["ticker"]: r["triage"] for r in rows}
    assert before == after


# ---------------------------------------------------------------- 정본 연결


def test_clusters_come_from_themes_yaml_not_a_new_taxonomy() -> None:
    """새 분류를 만들지 않는다 — M2 가 이미 선언했다."""
    from msa.themes import load_themes

    got = risk.theme_clusters(load_themes())
    assert len(got) > 100
    assert "reit" in set(got.values())


def test_declared_constants_say_it_changes_no_score() -> None:
    d = risk.declared_constants()
    assert "점수를 바꾸지 않는다" in d["effect"]
    assert d["slot_min"] >= 1
    assert 0.0 < d["concentration_fraction"] <= 1.0
    assert pytest.approx(d["concentration_fraction"]) == risk.CONCENTRATION_FRACTION
