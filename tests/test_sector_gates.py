"""섹터 관문 체인 — 모든 계층을 하나로 꿰어 "무엇이 막고 있는가" 를 낸다.

**이 파일이 지키는 것 하나: 새 가중치를 만들지 않는다.**

각 관문은 이미 존재하는 계층이 낸 판정을 **그대로 읽는다**. 6개 관문을 가중 합산해
하나의 점수로 만들면 그것이 `docs/15` 가 죽인 종합 점수의 재발이다. 관문은 **순서 있는
체인**이고, 산출은 "몇 번째에서 막혔나" 다.
"""

from __future__ import annotations

import pytest

from msa import sector


def _theme(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "theme": "t1",
        "score": 0.8,
        "pool": 0.7,
        "flags": [],
        "thesis": {"found": True, "portfolio_eligible": True, "trusted": True, "gate": "passed"},
    }
    d.update(kw)
    return d


def _digest(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "themes": [_theme()],
        "judged": [
            {"theme": "t1", "portfolio_eligible": True, "trusted": True, "gate": "passed"}
        ],
        "evidence_audit": {
            "t1": {"counts": {"verified": 20}, "checked": 20, "unverified_axes": []}
        },
        "triage": {
            "rows": [
                {"ticker": "AAA", "theme": "t1", "partition": "I-A", "triage": 0.8, "j": 0.9}
            ]
        },
        "regime": {"tilts": {}},
        "balance": {"surveyed": [], "missing": ["t1"], "lines": []},
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------- 관문 정의


def test_gates_are_ordered_and_named() -> None:
    """순서가 규칙의 일부다 — 판별을 통과하지 않은 테마의 수급을 묻는 것은 낭비다."""
    assert [g.key for g in sector.GATES] == [
        "forgotten",
        "not_a_trap",
        "evidence",
        "balance",
        "macro",
        "entry",
    ]


def test_no_gate_produces_a_number() -> None:
    """**관문은 통과/불통이지 점수가 아니다.** 가중 합산하면 종합 점수의 재발이다."""
    got = sector.evaluate(_digest())
    for row in got:
        for r in row.gates:
            assert isinstance(r.passed, bool)
            assert not hasattr(r, "score")


# ---------------------------------------------------------------- 각 관문


def test_forgotten_gate_reads_the_existing_pool_cut() -> None:
    """새 임계를 만들지 않는다 — `l1.scoreboard.POOL_MIN` 을 그대로 쓴다."""
    from msa.l1.scoreboard import POOL_MIN

    assert sector.POOL_MIN is POOL_MIN
    ok = sector.evaluate(_digest())[0]
    assert ok.gate("forgotten").passed

    low = _digest(themes=[_theme(pool=0.2)])
    assert not sector.evaluate(low)[0].gate("forgotten").passed


def test_trap_gate_needs_both_eligible_and_trusted() -> None:
    d = _digest(
        judged=[{"theme": "t1", "portfolio_eligible": True, "trusted": False, "gate": "passed"}]
    )
    r = sector.evaluate(d)[0].gate("not_a_trap")
    assert not r.passed
    assert "신뢰" in r.why


def test_unjudged_theme_fails_the_trap_gate_with_the_right_reason() -> None:
    d = _digest(judged=[], themes=[_theme(thesis={"found": False})])
    r = sector.evaluate(d)[0].gate("not_a_trap")
    assert not r.passed
    assert "판별" in r.why


def test_evidence_gate_fails_on_a_refuted_item(tmp_path, monkeypatch) -> None:
    """대장에 `refuted` 가 있으면 그 테마의 판정을 못 믿는다."""
    from msa.config import paths
    from msa.ops import resolutions as res

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    res.append(
        paths().evidence_resolutions,
        "t1",
        res.Resolution(1, "human", "2026-08-29", "refuted", "원문에 없다"),
    )
    r = sector.evaluate(_digest())[0].gate("evidence")
    assert not r.passed
    assert "반박" in r.why


def test_evidence_gate_fails_on_unverified_axes() -> None:
    d = _digest(
        evidence_audit={
            "t1": {"counts": {"verified": 10}, "checked": 20, "unverified_axes": ["unit_demand"]}
        }
    )
    r = sector.evaluate(d)[0].gate("evidence")
    assert not r.passed
    assert "unit_demand" in r.why


def test_evidence_gate_is_unknown_without_an_audit() -> None:
    """실사를 안 돌린 것과 실사가 통과한 것은 다르다 (`CLAUDE.md` §2)."""
    d = _digest(evidence_audit={})
    r = sector.evaluate(d)[0].gate("evidence")
    assert not r.passed
    assert "실사" in r.why


def test_balance_gate_needs_a_tightening_survey() -> None:
    """**수요/공급이 이 체인의 핵심 관문이다.** 조사가 없으면 통과가 아니다."""
    no_survey = sector.evaluate(_digest())[0].gate("balance")
    assert not no_survey.passed
    assert "조사" in no_survey.why

    d = _digest(
        balance={
            "surveyed": ["t1"],
            "missing": [],
            "lines": [],
            "verdicts": {"t1": "tightening"},
        }
    )
    assert sector.evaluate(d)[0].gate("balance").passed


def test_balance_gate_fails_when_loosening() -> None:
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "loosening"}}
    )
    r = sector.evaluate(d)[0].gate("balance")
    assert not r.passed
    assert "loosening" in r.why


def test_macro_gate_fails_only_on_headwind() -> None:
    from msa.l2.regime import REGIME_TILT

    tail = _digest(regime={"tilts": {}})
    assert sector.evaluate(tail)[0].gate("macro").passed

    head = _digest(regime={"tilts": {"t1": REGIME_TILT["headwind"]}})
    r = sector.evaluate(head)[0].gate("macro")
    assert not r.passed
    assert "역풍" in r.why

    neutral = _digest(regime={"tilts": {"t1": REGIME_TILT["neutral"]}})
    assert sector.evaluate(neutral)[0].gate("macro").passed, "중립은 막지 않는다"


def test_entry_gate_needs_a_partition_ia_stock() -> None:
    r = sector.evaluate(_digest())[0].gate("entry")
    assert r.passed and "AAA" in r.why

    none_ia = _digest(
        triage={
            "rows": [
                {"ticker": "BBB", "theme": "t1", "partition": "I-B", "triage": 0.9, "j": 0.9}
            ]
        }
    )
    r2 = sector.evaluate(none_ia)[0].gate("entry")
    assert not r2.passed
    assert "고점권" in r2.why


# ---------------------------------------------------------------- 체인 결과


def test_a_theme_that_clears_everything_is_the_answer(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "tightening"}}
    )
    row = sector.evaluate(d)[0]
    assert row.cleared
    assert row.blocked_at is None


def test_blocked_at_names_the_first_failing_gate() -> None:
    d = _digest(themes=[_theme(pool=0.1)])
    row = sector.evaluate(d)[0]
    assert not row.cleared
    assert row.blocked_at == "forgotten"


def test_later_gates_still_report_even_after_a_block() -> None:
    """**막힌 뒤에도 나머지를 본다.** '무엇을 더 해야 통과하나' 가 이 체인의 산출이다."""
    d = _digest(themes=[_theme(pool=0.1)])
    row = sector.evaluate(d)[0]
    assert len(row.gates) == len(sector.GATES)
    assert row.gate("balance").why  # 관문마다 사유가 있다


def test_rows_are_sorted_by_how_far_they_got() -> None:
    d = _digest(
        themes=[_theme(theme="far"), _theme(theme="near", pool=0.1)],
        judged=[
            {"theme": "far", "portfolio_eligible": True, "trusted": True, "gate": "passed"},
            {"theme": "near", "portfolio_eligible": True, "trusted": True, "gate": "passed"},
        ],
        evidence_audit={
            "far": {"counts": {"verified": 20}, "checked": 20, "unverified_axes": []},
            "near": {"counts": {"verified": 20}, "checked": 20, "unverified_axes": []},
        },
        triage={
            "rows": [
                {"ticker": "A", "theme": "far", "partition": "I-A", "triage": 0.8, "j": 0.9},
                {"ticker": "B", "theme": "near", "partition": "I-A", "triage": 0.9, "j": 0.9},
            ]
        },
    )
    got = sector.evaluate(d)
    assert [r.theme for r in got] == ["far", "near"], "더 멀리 간 테마가 위"


def test_zero_cleared_is_an_honest_answer() -> None:
    """오늘 통과가 0개일 수 있고 **그것이 정직한 답이다.**"""
    rows = sector.evaluate(_digest())
    assert not any(r.cleared for r in rows)
    line = sector.headline(rows)
    assert "없다" in line
    assert "수요/공급" in line, "무엇이 막았는지 이름으로 짚어야 한다"


def test_headline_names_the_cleared_theme(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "tightening"}}
    )
    line = sector.headline(sector.evaluate(d))
    assert "`t1`" in line


def test_render_shows_the_chain_per_theme() -> None:
    md = "\n".join(sector.render_md(sector.evaluate(_digest())))
    assert "관문" in md
    for g in sector.GATES:
        assert g.title in md


def test_declared_constants_say_no_new_numbers() -> None:
    d = sector.declared_constants()
    assert "새 가중치" in d["claim"]
    assert d["pool_min"] == sector.POOL_MIN


# ---------------------------------------------------------------- 점수 격리


def test_chain_produces_no_composite_score() -> None:
    """관문 체인은 **점수를 만들지 않는다** — 만들면 docs/15 가 죽인 종합 점수의 재발이다."""
    rows = sector.evaluate(_digest())
    for r in rows:
        assert not hasattr(r, "score")
        assert not hasattr(r, "composite")
    with pytest.raises(AttributeError):
        _ = rows[0].total_score  # type: ignore[attr-defined]


# ---------------------------------------------------------------- 파이프라인 배선


def test_daily_carries_the_sector_block() -> None:
    from msa.pipeline import daily as D

    block = D._sector_block(_digest())
    assert block["cleared"] == []
    assert "없다" in block["headline"]
    assert len(block["rows"][0]["gates"]) == len(sector.GATES)


def test_sector_section_is_rendered_from_the_stored_block() -> None:
    """저장된 블록만으로 절을 복원한다 — 재계산하지 않는다 (재현 가능성)."""
    from msa.pipeline import daily as D

    digest = dict(_digest())
    digest["sector"] = D._sector_block(digest)
    md = "\n".join(D.sector_section_md(digest))
    assert "오늘의 섹터 — 관문 체인" in md
    assert "관문이다" in md and "가중 합산하지 않는다" in md


def test_sector_section_empty_without_block() -> None:
    from msa.pipeline import daily as D

    assert D.sector_section_md({}) == []


def test_balance_block_exposes_verdicts_for_the_chain(tmp_path, monkeypatch) -> None:
    """관문이 요약 문장을 다시 파싱하지 않게 판정을 따로 싣는다."""
    from msa.l35 import balance as bal
    from msa.pipeline import daily as D

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    doc = {
        "theme": "t1",
        "asof": "2026-08-29",
        "unit": "온스",
        "horizon_years": 5,
        "demand": {
            "verdict": "expanding",
            "drivers": [
                {"name": "d", "direction": "up", "magnitude": "m", "evidence_ids": [1]}
            ],
            "cagr_pct": 4.0,
        },
        "supply": {
            "verdict": "constrained",
            "rigidity": [{"kind": "byproduct", "note": "n", "evidence_ids": [1]}],
            "new_capacity_3y": "없음",
            "cagr_pct": 1.0,
        },
        "balance": {
            "verdict": "tightening",
            "ratio_note": "r",
            "what_would_close_it": ["x"],
            "invalidations": ["y"],
        },
        "evidence": [
            {"id": 1, "claim": "c", "source_url": "https://x.example/a", "date": "2026-01-01"}
        ],
    }
    bal.write(tmp_path / "balance", doc)
    block = D._balance_block({"judged": [{"theme": "t1", "portfolio_eligible": True}]})
    assert block["verdicts"] == {"t1": "tightening"}


def test_readme_conclusion_carries_the_chain_result() -> None:
    """체인이 digest.md 에만 있으면 README 결론만 읽는 사람은 못 본다."""
    from msa.ops import readme_block as RB
    from msa.pipeline import daily as D

    digest = dict(_digest())
    digest["sector"] = D._sector_block(digest)
    line = RB._sector_line(digest)
    assert "관문" in line
    assert RB._sector_line({}) == "", "블록이 없으면 아무 말도 덧붙이지 않는다"


def test_readme_line_names_the_cleared_sector(tmp_path, monkeypatch) -> None:
    from msa.ops import readme_block as RB
    from msa.pipeline import daily as D

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    digest = dict(
        _digest(
            balance={
                "surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "tightening"}
            }
        )
    )
    digest["sector"] = D._sector_block(digest)
    line = RB._sector_line(digest)
    assert "`t1`" in line and "전부 통과" in line
