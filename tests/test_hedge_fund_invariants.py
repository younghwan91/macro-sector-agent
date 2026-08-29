"""헷지펀드 4계층(P1~P4)의 **구조 불변식** — 누가 깨면 여기서 알아야 한다.

각 역할이 무엇을 건드릴 수 있고 무엇을 못 건드리는지는 설계의 핵심이고, 개별 모듈
테스트로는 "이 모듈이 자기 일을 한다" 까지만 보인다. 이 파일은 **역할 경계 자체**를 본다.

| 역할 | 건드릴 수 있는 것 | 절대 못 건드리는 것 |
|---|---|---|
| P2 매크로 | R | J · C · 구획 |
| P3 종목 분석가 | J 의 종목 성분 | C · R · 구획 |
| P4 리스크·PM | 아무것도 — 경고와 표시 슬롯뿐 | J · C · R · 구획 · triage |

**구획은 넷 다 못 건드린다.** 판별(L3)과 낙폭(`PULLBACK_MARK`)만이 구획을 정한다.
"""

from __future__ import annotations

import pytest

from msa import triage
from msa.l4 import risk


def _base_digest(**extra: object) -> dict[str, object]:
    d: dict[str, object] = {
        "themes": [
            {
                "theme": "t1",
                "picks": [
                    {"ticker": "DEEP", "from_52w_high": -0.50, "red_flags": "", "stage2": True},
                    {"ticker": "MID", "from_52w_high": -0.25, "red_flags": ""},
                    {"ticker": "HIGH", "from_52w_high": -0.05, "red_flags": ""},
                ],
            },
            {
                "theme": "t2",
                "picks": [
                    {"ticker": "OTHER", "from_52w_high": -0.30, "red_flags": "x"},
                ],
            },
        ],
        "judged": [
            {"theme": "t1", "portfolio_eligible": True, "trusted": True, "gate": "passed"},
            {"theme": "t2", "portfolio_eligible": True, "trusted": True, "gate": "passed"},
        ],
        "evidence_audit": {
            "t1": {"counts": {"verified": 18}, "checked": 20, "unverified_axes": []},
            "t2": {"counts": {"verified": 10}, "checked": 20, "unverified_axes": []},
        },
    }
    d.update(extra)
    return d


def _by_ticker(digest: dict[str, object]) -> dict[str, triage.TriageRow]:
    return {r.ticker: r for r in triage.score_digest(digest)}


BASE = _by_ticker(_base_digest())


# ---------------------------------------------------------------- 구획 불변


@pytest.mark.parametrize(
    ("label", "extra"),
    [
        ("regime headwind", {"regime_tilts": {"t1": 0.70, "t2": 0.70}}),
        ("regime tailwind", {"regime_tilts": {"t1": 1.00}}),
        ("stock note breaking", {"stock_notes": {"DEEP": 0.20, "OTHER": 0.20}}),
        ("stock note intact", {"stock_notes": {"HIGH": 1.00}}),
        (
            "both",
            {"regime_tilts": {"t1": 0.70}, "stock_notes": {"DEEP": 0.20}},
        ),
    ],
)
def test_no_role_can_move_a_stock_between_partitions(label: str, extra: dict) -> None:
    """**구획은 판별과 낙폭만 정한다.** 매크로도 종목 분석가도 발언권이 없다."""
    got = _by_ticker(_base_digest(**extra))
    for t, row in BASE.items():
        assert got[t].partition == row.partition, f"{label}: {t} 의 구획이 움직였다"


def test_partition_is_decided_by_pullback_mark_only() -> None:
    from msa.ops.readme_block import PULLBACK_MARK

    assert BASE["DEEP"].partition == triage.PARTITION_IA
    assert BASE["MID"].partition == triage.PARTITION_IA
    assert BASE["HIGH"].partition == triage.PARTITION_IB
    assert -0.25 <= PULLBACK_MARK <= -0.05, "이 테스트의 픽스처가 기준선을 사이에 두고 있어야 한다"


# ---------------------------------------------------------------- P2 경계


def test_regime_touches_r_only() -> None:
    got = _by_ticker(_base_digest(regime_tilts={"t1": 0.70}))
    for t in ("DEEP", "MID", "HIGH"):
        assert got[t].j == BASE[t].j, f"{t}: 레짐이 J 를 건드렸다"
        assert got[t].c == BASE[t].c, f"{t}: 레짐이 C 를 건드렸다"
        assert got[t].r == pytest.approx(BASE[t].r * 0.70)
    assert got["OTHER"].r == pytest.approx(BASE["OTHER"].r), "다른 테마는 안 움직인다"


# ---------------------------------------------------------------- P3 경계


def test_stock_note_touches_j_only_and_only_that_ticker() -> None:
    got = _by_ticker(_base_digest(stock_notes={"DEEP": 0.20}))
    assert got["DEEP"].j == pytest.approx(0.5 * BASE["DEEP"].j + 0.5 * 0.20)
    assert got["DEEP"].c == BASE["DEEP"].c
    assert got["DEEP"].r == BASE["DEEP"].r
    for t in ("MID", "HIGH", "OTHER"):
        assert got[t].j == BASE[t].j, f"{t}: 노트 없는 종목이 움직였다"


def test_absent_note_is_the_identity_not_a_penalty() -> None:
    """**오늘의 식이 확장의 특수해다** — 안 부른 종목이 벌을 받으면 안 된다."""
    got = _by_ticker(_base_digest(stock_notes={}))
    for t, row in BASE.items():
        assert got[t].j == row.j


# ---------------------------------------------------------------- P4 경계


def test_risk_review_changes_no_score_at_all() -> None:
    rows = [
        {
            "ticker": r.ticker,
            "theme": r.theme,
            "partition": r.partition,
            "triage": r.triage,
            "j": r.j,
            "c": r.c,
            "r": r.r,
        }
        for r in triage.score_digest(_base_digest())
    ]
    snapshot = [dict(x) for x in rows]
    risk.review(rows, {"t1": "c1", "t2": "c1"}, partition=triage.PARTITION_IA)
    risk.review(rows, {"t1": "c1", "t2": "c1"}, partition=triage.PARTITION_IB)
    assert rows == snapshot, "리스크·PM 이 점수를 되썼다"


def test_pm_slots_never_drop_anyone() -> None:
    rows = [
        {"ticker": f"T{i}", "theme": "t1", "partition": "I-A", "triage": 0.9 - i / 100, "j": 0.0}
        for i in range(8)
    ]
    got = risk.review(rows, {"t1": "c1"}, partition="I-A")
    assert len(got["shown"]) + len(got["deferred"]) == len(rows)
    assert got["shown"], "슬롯 하한이 1 이므로 최소 한 줄은 남는다"


# ---------------------------------------------------------------- 선언값 감사


def test_every_new_declared_constant_is_in_the_basis_registry() -> None:
    """P1~P4 가 새로 만든 스칼라 선언값이 전부 근거 레지스트리에 있어야 한다.

    `docs/24` §1 이 막으려는 것이 "필터 상수를 근거 없이 추가" 다. 배분 벡터
    (`TRIAGE_WEIGHTS`·`R_WEIGHTS`·`REGIME_TILT`·`NOTE_TRUST`)는 `AXIS_WEIGHTS` 와 같은
    취급이지만, `REGIME_TILT`·`NOTE_TRUST` 는 새 계층이 만든 것이라 등록해 뒀다.
    """
    from msa.basis import BASES

    must = {
        "EVIDENCE_CAP",
        "EVIDENCE_CAP_REFUTED",
        "UNJUDGED_PENALTY",
        "RED_FLAG_PENALTY",
        "RED_FLAG_MAX",
        "PARTIAL_PENALTY",
        "PULLBACK_MARK",
        "REGIME_TILT",
        "NOTE_TRUST",
        "CONCENTRATION_FRACTION",
        "CONCENTRATION_WINDOW",
        "SLOT_MAX",
        "SLOT_MIN",
    }
    assert must <= set(BASES), f"레지스트리에 없는 선언값: {sorted(must - set(BASES))}"


def test_none_of_the_new_constants_claims_to_cut() -> None:
    """P1~P4 는 아무것도 자르지 않는다 — `hard`·`gate` 태그가 붙으면 안 된다.

    붙으면 `weakest_links()` 가 "근거 없이 자르는 값" 으로 잘못 세고, 그 목록의 뜻이 흐려진다.
    """
    from msa.basis import BASES

    new = (
        "EVIDENCE_CAP",
        "EVIDENCE_CAP_REFUTED",
        "UNJUDGED_PENALTY",
        "RED_FLAG_PENALTY",
        "RED_FLAG_MAX",
        "PARTIAL_PENALTY",
        "PULLBACK_MARK",
        "REGIME_TILT",
        "NOTE_TRUST",
        "CONCENTRATION_FRACTION",
        "CONCENTRATION_WINDOW",
        "SLOT_MAX",
        "SLOT_MIN",
    )
    for name in new:
        tags = set(BASES[name].tags)
        assert not (tags & {"hard", "gate"}), f"{name}: 자르지 않는데 {tags} 태그가 붙었다"


def test_claim_note_never_promises_returns() -> None:
    """리포트 고정 문장이 사라지거나 약해지면 안 된다 (`CLAUDE.md` §7)."""
    assert "수익률 순서가 아니다" in triage.CLAIM_NOTE
    assert "초과수익을 주장하지 않으며" in triage.CLAIM_NOTE
    d = triage.declared_constants()
    assert "초과수익을 주장하지 않는다" in d["claim"]


def test_llm_layers_cannot_emit_a_recommendation() -> None:
    """P2·P3 의 출력 스키마에 '사라' 를 담을 칸이 없다 (`CLAUDE.md` §4·§8)."""
    from msa.l2 import analyst as macro
    from msa.l4 import analyst as stock

    stock_fields = set(stock.SCHEMA["properties"])
    assert stock_fields == {"verdict", "mechanism", "invalidations", "evidence"}
    macro_one = macro.SCHEMA["properties"]["classes"]["properties"]["credit_rate"]
    assert set(macro_one["properties"]) == {
        "verdict",
        "mechanism",
        "invalidations",
        "evidence",
    }
    for schema in (stock.SCHEMA["properties"]["verdict"], macro_one["properties"]["verdict"]):
        assert "buy" not in schema["enum"] and "sell" not in schema["enum"]


# ---------------------------------------------------------------- 합성 응답 격리


def test_synthetic_stock_notes_never_reach_the_score(tmp_path) -> None:
    """**--dry-run 이 dry 여야 한다.** 경로 검증용 값이 실제 읽는 순서를 바꾸면 안 된다."""
    from msa.l4 import analyst as stock

    real = {**stock.MOCK_OUTPUT, "ticker": "REAL"}
    real.pop("synthetic")
    stock.write(tmp_path, real)
    stock.write(tmp_path, {**stock.MOCK_OUTPUT, "ticker": "FAKE"})

    got = stock.load_all(tmp_path, ["REAL", "FAKE"])
    assert "REAL" in got
    assert "FAKE" not in got, "합성 노트가 점수에 들어갔다"
    assert stock.skipped_synthetic(tmp_path, ["REAL", "FAKE"]) == ["FAKE"]


def test_synthetic_regime_produces_no_tilt() -> None:
    from msa.l2 import regime as regime_mod

    doc = {
        "week": "2026-W35",
        "synthetic": True,
        "classes": {"credit_rate": {"verdict": "headwind"}},
    }
    assert regime_mod.tilts_by_theme(doc, {"t": "credit_rate"}) == {"t": 1.0}
    real = {k: v for k, v in doc.items() if k != "synthetic"}
    assert regime_mod.tilts_by_theme(real, {"t": "credit_rate"}) == {"t": 0.70}


def test_mock_outputs_are_all_marked_synthetic() -> None:
    from msa.l2 import analyst as macro
    from msa.l4 import analyst as stock

    assert macro.MOCK_OUTPUT["synthetic"] is True
    assert stock.MOCK_OUTPUT["synthetic"] is True
