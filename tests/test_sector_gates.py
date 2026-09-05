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
            "who_captures_it": "생산자가 가격으로 가져간다",
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


# ---------------------------------------------------------------- 다음 행동


def test_next_actions_are_only_the_actionable_blocks() -> None:
    """**기다릴 것과 할 것을 구분한다.** 못 할 일을 할 일 목록에 넣으면 목록이 죽는다."""
    rows = sector.evaluate(_digest())  # balance 조사 없음 → ④ 에서 막힘
    acts = sector.next_actions(rows)
    assert len(acts) == 1
    assert acts[0].command == "msa balance t1"
    assert "수급 조사" in acts[0].why


def test_loosening_balance_is_not_actionable() -> None:
    """수급이 벌어지지 않는다는 판정은 **답이지 할 일이 아니다.**"""
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "loosening"}}
    )
    assert sector.next_actions(sector.evaluate(d)) == []


def test_entry_block_is_not_actionable() -> None:
    """고점권이라 못 사는 것은 **기다리는 것**이지 실행할 명령이 없다."""
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "tightening"}},
        triage={
            "rows": [{"ticker": "B", "theme": "t1", "partition": "I-B", "triage": 0.9, "j": 0.9}]
        },
    )
    acts = sector.next_actions(sector.evaluate(d))
    assert acts == []


def test_unresolved_evidence_is_actionable() -> None:
    d = _digest(
        evidence_audit={
            "t1": {
                "counts": {"verified": 10, "partial": 5},
                "checked": 20,
                "unverified_axes": [],
            }
        }
    )
    acts = sector.next_actions(sector.evaluate(d))
    assert acts[0].command == "msa ops audit-evidence t1"


def test_refuted_evidence_needs_rejudgement_not_more_reading() -> None:
    """반박된 근거는 더 읽는다고 안 풀린다 — 판별을 다시 받아야 한다."""
    import msa.sector as S

    rows = [
        S.Row(
            "t1",
            (
                S.Result("forgotten", True, ""),
                S.Result("not_a_trap", True, ""),
                S.Result("evidence", False, "사람이 원문 대조에서 **반박**한 근거 3건"),
                S.Result("balance", True, ""),
                S.Result("macro", True, ""),
                S.Result("entry", True, ""),
            ),
        )
    ]
    acts = sector.next_actions(rows)
    assert acts[0].command == "msa research t1"
    assert "반박" in acts[0].why


def test_actions_are_deduplicated_and_ordered_by_progress() -> None:
    """더 멀리 간 테마의 할 일이 먼저 — 그게 통과에 가장 가깝다."""
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
    acts = sector.next_actions(sector.evaluate(d))
    assert acts[0].command == "msa balance far"


def test_no_actions_when_everything_cleared(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "tightening"}}
    )
    assert sector.next_actions(sector.evaluate(d)) == []


# ---------------------------------------------------------------- 종합 결론


def test_verdict_leads_with_the_chain_not_the_stock_list() -> None:
    """**관문이 결론이고 트리아지는 그다음이다.** 둘을 뒤섞으면 모순처럼 읽힌다."""
    lines = sector.verdict_md(sector.evaluate(_digest()))
    text = "\n".join(lines)
    assert text.startswith("\n## 투자 판단") or "## 투자 판단" in text.split("\n")[1]
    assert "신규 편입 없음" in text
    # 관문이 결론이고 종목 목록은 이 절에 아예 없다 — 뒤 절이 진다
    assert "ALHC" not in text and "차트 확인" not in text


def test_verdict_names_the_sector_when_one_clears(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "tightening"}}
    )
    text = "\n".join(sector.verdict_md(sector.evaluate(d)))
    assert "오늘의 섹터: `t1`" in text
    assert "신규 편입 없음" not in text, "통과가 있으면 없다고 말하지 않는다"


def test_verdict_carries_next_actions() -> None:
    text = "\n".join(sector.verdict_md(sector.evaluate(_digest())))
    assert "오늘 할 일" in text
    assert "msa balance t1" in text


def test_verdict_says_nothing_to_do_when_waiting() -> None:
    """할 일이 없으면 **없다고 적는다** — 빈 목록을 남기지 않는다."""
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "loosening"}}
    )
    text = "\n".join(sector.verdict_md(sector.evaluate(d)))
    assert "할 일이 없다" in text or "기다린다" in text


# ---------------------------------------------------------------- 무엇이 바뀌면


def _bal_doc(theme: str, verdict: str) -> dict[str, object]:
    return {
        "theme": theme,
        "asof": "2026-08-29",
        "unit": "TEU",
        "horizon_years": 5,
        "demand": {
            "verdict": "expanding",
            "drivers": [{"name": "d", "direction": "up", "magnitude": "m", "evidence_ids": [1]}],
            "cagr_pct": 2.3,
        },
        "supply": {
            "verdict": "expanding",
            "rigidity": [],
            "new_capacity_3y": "확정 800만 TEU",
            "cagr_pct": 5.5,
        },
        "balance": {
            "verdict": verdict,
            "ratio_note": "공급이 3.2%p 앞선다",
            "what_would_close_it": ["조선소 슬롯 지연으로 확정 인도량이 축소되면"],
            "who_captures_it": "선주",
            "invalidations": ["수요 성장률이 4%대로 붙으면 이 판정은 무효다"],
        },
        "evidence": [
            {"id": 1, "claim": "c", "source_url": "https://x.example/a", "date": "2026-01-01"}
        ],
    }


def test_what_would_change_it_comes_from_the_balance_survey(tmp_path, monkeypatch) -> None:
    """좋은 투자 메모의 핵심은 **무엇이 바뀌면 마음이 바뀌나**다.

    수급 조사가 이미 `invalidations` 와 `what_would_close_it` 을 들고 있다 — 다시 묻지 않고
    그것을 그대로 싣는다.
    """
    from msa.l35 import balance as bal

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    bal.write(tmp_path / "balance", _bal_doc("t1", "loosening"))
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "loosening"}}
    )
    got = sector.what_would_change(sector.evaluate(d))
    assert "t1" in got
    joined = " ".join(got["t1"])
    assert "수요 성장률이 4%대로" in joined
    assert "조선소 슬롯 지연" in joined


def test_what_would_change_is_empty_without_a_survey(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    assert sector.what_would_change(sector.evaluate(_digest())) == {}


def test_verdict_carries_what_would_change(tmp_path, monkeypatch) -> None:
    from msa.l35 import balance as bal

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    bal.write(tmp_path / "balance", _bal_doc("t1", "loosening"))
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "loosening"}}
    )
    text = "\n".join(sector.verdict_md(sector.evaluate(d)))
    assert "재진입 트리거" in text
    assert "수요 성장률이 4%대로" in text


def test_verdict_skips_themes_blocked_at_the_first_two_gates() -> None:
    """**1/6 짜리를 길게 보여주는 것은 소음이다.** 투자자는 근접한 것만 본다."""
    d = _digest(
        themes=[_theme(theme="close"), _theme(theme="far_off")],
        judged=[
            {"theme": "close", "portfolio_eligible": True, "trusted": True, "gate": "passed"},
            {"theme": "far_off", "portfolio_eligible": False, "trusted": True, "gate": "passed"},
        ],
        evidence_audit={
            "close": {"counts": {"verified": 20}, "checked": 20, "unverified_axes": []},
        },
        triage={
            "rows": [
                {"ticker": "A", "theme": "close", "partition": "I-A", "triage": 0.8, "j": 0.9}
            ]
        },
    )
    text = "\n".join(sector.verdict_md(sector.evaluate(d)))
    assert "`close`" in text
    assert "**`far_off`** —" not in text, "②에서 막힌 테마를 길게 펴지 않는다"
    assert "far_off" in text, "다만 한 줄로는 언급한다 — 조용히 사라지면 안 된다"


def test_what_would_change_dedupes_and_caps(tmp_path, monkeypatch) -> None:
    """두 목록은 자주 겹친다 — 2026-08-29 실측에서 수에즈 항로가 양쪽에 있었다."""
    from msa.l35 import balance as bal

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    doc = _bal_doc("t1", "loosening")
    doc["balance"]["invalidations"] = [  # type: ignore[index]
        "수에즈 항로가 정상화되지 않으면 이 판정은 왜곡이다",
        "다른 조건 A",
        "다른 조건 B",
        "다른 조건 C",
        "다른 조건 D",
    ]
    doc["balance"]["what_would_close_it"] = [  # type: ignore[index]
        "수에즈 항로가 정상화되지 않으면 톤마일이 흡수한다",
    ]
    bal.write(tmp_path / "balance", doc)
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "loosening"}}
    )
    got = sector.what_would_change(sector.evaluate(d))["t1"]
    assert len(got) <= sector.WHAT_CHANGES_MAX
    assert sum(1 for x in got if x.startswith("수에즈")) == 1, "겹친 항목이 두 번 실렸다"


def test_blocked_reasons_come_before_passing_ones() -> None:
    """답이 '안 산다' 이므로 **왜 안 사는지가 먼저**다."""
    text = "\n".join(sector.verdict_md(sector.evaluate(_digest())))
    # 헤더에도 `t1` 이 나오므로 **마지막** 조각(관문 목록)을 본다
    body = text.split("**`t1`** — ")[-1]
    assert body.index("❌") < body.index("✅"), "왜 안 사는지가 먼저 와야 한다"


def test_judged_out_and_unjudged_are_reported_separately() -> None:
    """**판정을 받고 떨어진 것과 아직 안 받은 것은 다른 사실이다.**

    뭉뚱그리면 투자자가 "돌리면 될 수도" 라고 읽는다 — 앞은 이미 답이 나온 것이다.
    """
    d = _digest(
        themes=[_theme(theme="close"), _theme(theme="rejected"), _theme(theme="never")],
        judged=[
            {"theme": "close", "portfolio_eligible": True, "trusted": True, "gate": "passed"},
            {"theme": "rejected", "portfolio_eligible": False, "trusted": True, "gate": "passed"},
        ],
        evidence_audit={
            "close": {"counts": {"verified": 20}, "checked": 20, "unverified_axes": []},
        },
        triage={
            "rows": [
                {"ticker": "A", "theme": "close", "partition": "I-A", "triage": 0.8, "j": 0.9}
            ]
        },
    )
    text = "\n".join(sector.verdict_md(sector.evaluate(d)))
    assert "확신도 미달 1개" in text and "`rejected`" in text
    assert "아직 판별을 안 받은 1개" in text and "`never`" in text


# ---------------------------------------------------------------- 체인의 우주


def test_themes_with_a_survey_enter_the_chain_even_outside_top_k(tmp_path, monkeypatch) -> None:
    """**조사해 둔 테마가 관문표에서 사라지면 안 된다.**

    2026-08-29 실측: `silver_miners` 수급 조사(tightening)를 돌렸는데 상위 K 밖이라
    체인에 아예 안 들어갔다. 리포트는 그 조사를 보여주면서 관문표에는 없어, 읽는 사람이
    "왜 실버는 없나" 를 알 수 없었다. 실제 답은 ① 에서 떨어진다는 것(pool 0.27)이고,
    **그 답이 보여야 한다.**
    """
    from msa.l35 import balance as bal
    from msa.pipeline import daily as D

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    bal.write(tmp_path / "balance", _bal_doc("outsider", "tightening"))
    digest = {
        "themes": [_theme(theme="inside")],
        "judged": [
            {"theme": "inside", "portfolio_eligible": True, "trusted": True, "gate": "passed"}
        ],
        "evidence_audit": {},
        "triage": {"rows": []},
        "regime": {"tilts": {}},
        "scan_all": {"outsider": {"pool": 0.27}},
    }
    digest["balance"] = D._balance_block(digest)
    rows = sector.evaluate(digest)
    names = [r.theme for r in rows]
    assert "outsider" in names, "조사한 테마가 관문표에서 사라졌다"
    out = next(r for r in rows if r.theme == "outsider")
    assert not out.gate("forgotten").passed
    assert "0.27" in out.gate("forgotten").why


def test_outsider_without_scan_data_says_so() -> None:
    """스캔 밖 테마의 pool 을 모르면 **모른다고 적는다** (`CLAUDE.md` §2)."""
    d = _digest()
    d["balance"] = {"surveyed": ["ghost"], "missing": [], "lines": [], "verdicts": {}}
    rows = sector.evaluate(d)
    ghost = next((r for r in rows if r.theme == "ghost"), None)
    assert ghost is not None
    assert not ghost.gate("forgotten").passed
    assert "계산하지 못했다" in ghost.gate("forgotten").why or "없다" in ghost.gate("forgotten").why


def test_not_a_trap_distinguishes_low_confidence_from_missing_axes() -> None:
    """**확신도 미달과 '축이 적용 불가라 판정이 없다' 는 다른 사실이다.**

    2026-08-29 실측: `insurance_brokers` 는 확신도 0.6 으로 편입선(0.50)을 넘었는데
    리포트가 "확신도가 편입선에 못 미친다" 고 적었다 — **거짓이었다.** 실제 사유는
    5축 중 셋이 적용 불가라 판정 자체가 없었던 것이다.
    """
    low = _digest(
        judged=[
            {
                "theme": "t1",
                "portfolio_eligible": False,
                "trusted": True,
                "gate": "passed",
                "cycle_confidence": 0.45,
                "gate_rule": "확신도 미달",
            }
        ]
    )
    r = sector.evaluate(low)[0].gate("not_a_trap")
    assert "가치 함정 혐의를 못 벗었다" in r.why and "0.45" in r.why

    no_axis = _digest(
        judged=[
            {
                "theme": "t1",
                "portfolio_eligible": False,
                "trusted": True,
                "gate": "passed",
                "cycle_confidence": 0.6,
                "gate_rule": "축1·축3 모두 적용 불가 → 판별의 중심 질문에 답한 축이 없다",
            }
        ]
    )
    r2 = sector.evaluate(no_axis)[0].gate("not_a_trap")
    assert "답한 축이 없다" in r2.why
    assert "0.6" in r2.why
    assert "확신도가 편입선에 못 미친다" not in r2.why


# ---------------------------------------------------------------- 탐색 공간


def test_neutral_regime_passes_gate_five() -> None:
    """**중립은 역풍이 아니다.** 2026-08-29 실측: 탐색 공간을 짤 때 순풍 3종만 세고
    `secular_growth`(중립)를 빼먹어 9개 테마를 놓쳤다. 관문 ⑤ 는 `headwind` 만 막는다.
    """
    from msa.l2.regime import REGIME_TILT

    for verdict in ("tailwind", "neutral"):
        d = _digest(regime={"tilts": {"t1": REGIME_TILT[verdict]}})
        assert sector.evaluate(d)[0].gate("macro").passed, f"{verdict} 가 막혔다"
    d = _digest(regime={"tilts": {"t1": REGIME_TILT["headwind"]}})
    assert not sector.evaluate(d)[0].gate("macro").passed


def test_searchable_classes_names_every_non_headwind_class() -> None:
    """탐색 공간을 손으로 세지 않게 코드가 낸다 — 손으로 세다 9개를 놓쳤다."""
    doc = {
        "classes": {
            "capex_program": {"verdict": "tailwind"},
            "commodity_supply": {"verdict": "tailwind"},
            "inventory": {"verdict": "tailwind"},
            "secular_growth": {"verdict": "neutral"},
            "credit_rate": {"verdict": "headwind"},
        }
    }
    got = sector.searchable_classes(doc)
    assert got == {"capex_program", "commodity_supply", "inventory", "secular_growth"}
    assert "credit_rate" not in got


def test_searchable_classes_without_a_regime_is_everything() -> None:
    """레짐이 없으면 아무것도 막지 않는다 — 없는 것을 역풍으로 읽지 않는다."""
    from msa.l2.regime import CYCLE_CLASSES

    assert sector.searchable_classes(None) == set(CYCLE_CLASSES)


def test_searchable_classes_does_not_treat_missing_as_tailwind() -> None:
    """**판정이 없는 칸을 순풍으로 읽지 않는다** (`CLAUDE.md` §2).

    `_macro` 는 계수가 없으면 막지 않지만, 탐색 공간을 짤 때 '모르는 칸' 을 후보에 넣으면
    판별을 돌린 뒤 ⑤ 에서 걸리는 일이 생긴다 — 비싼 낭비다.
    """
    doc = {"classes": {"inventory": {"verdict": "tailwind"}}}
    assert sector.searchable_classes(doc) == {"inventory"}


def test_every_gate_is_evaluated_for_every_theme() -> None:
    """**여섯 관문이 모든 테마에서 평가된다** — 하나라도 조용히 빠지면 종합이 아니다.

    관문이 실패하는 것과 **평가되지 않는 것**은 다르다. 앞은 답이고 뒤는 침묵이다
    (`CLAUDE.md` §2). 리포트가 "종합해서 결론을 낸다" 고 말하려면 78칸이 다 차야 한다.
    """
    rows = sector.evaluate(
        _digest(
            themes=[_theme(theme="a"), _theme(theme="b", pool=0.1), _theme(theme="c")],
            judged=[
                {"theme": "a", "portfolio_eligible": True, "trusted": True, "gate": "passed"}
            ],
            evidence_audit={},
        )
    )
    assert rows
    for r in rows:
        got = [g.key for g in r.gates]
        assert got == [g.key for g in sector.GATES], f"{r.theme}: 관문이 빠졌다 — {got}"
        for g in r.gates:
            assert g.why.strip(), f"{r.theme}/{g.key}: 사유가 비었다"
            assert isinstance(g.passed, bool)


def test_a_failing_gate_still_carries_a_reason() -> None:
    """실패한 관문도 **왜** 인지를 말한다 — 투자자가 읽는 문서다."""
    rows = sector.evaluate(_digest(themes=[_theme(pool=0.1)]))
    blocked = [g for g in rows[0].gates if not g.passed]
    assert blocked
    for g in blocked:
        assert len(g.why) > 5, f"{g.key}: 사유가 너무 짧다"


# ------------------------------------------- 체인 표기 (2026-08-31 리포트 검토)


def test_verdict_does_not_print_two_of_six_beside_four_checkmarks() -> None:
    """**`depth` 는 통과 개수가 아니라 '어디서 멈췄나' 다.**

    2026-08-31 리포트 실측: `cement_aggregates` 가 "2/6 관문" 이라 적혀 있는데 바로 아래
    ✅ 가 넷이었다. 둘 다 맞는 말이지만 **같이 놓으면 독자가 하나를 거짓으로 읽는다.**
    투자자가 읽는 문서에서 그 모순은 그대로 신뢰 비용이다.

    체인이므로 셋째 관문에서 멈췄다면 넷째 이후는 **통과가 아니라 미도달**이다.
    """
    d = _digest()
    rows = sector.evaluate(d)
    text = "\n".join(sector.verdict_md(rows))
    assert "/6 관문" not in text, "분수 표기가 ✅ 개수와 충돌한다"
    assert "에서 막혔다" in text


def test_verdict_separates_reached_passes_from_unreached_gates() -> None:
    """막힘 **앞**의 통과와 **뒤**의 칸은 다른 사실이다 (`CLAUDE.md` §2)."""
    d = _digest(
        balance={"surveyed": ["t1"], "missing": [], "lines": [], "verdicts": {"t1": "loosening"}}
    )
    text = "\n".join(sector.verdict_md(sector.evaluate(d)))
    assert "미도달" in text
