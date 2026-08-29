"""2026-08-29 고정 입력 골든 — 설계가 그날 리포트의 결론을 재현하는지.

구획 I-A 는 그날 README 헤드라인이 이미 뽑은 "차트 확인 대상 3종목" 과 같아야 한다.
스펙 §6.1 의 표가 이 테스트의 기대값이다.

`state/daily/` 는 gitignore 라 실데이터를 그대로 쓸 수 없다 — 축약본을 커밋해 둔다
(`tests/fixtures/triage/digest-2026-08-29.json`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from msa import triage

FIXTURE = Path(__file__).parent / "fixtures" / "triage" / "digest-2026-08-29.json"


@pytest.fixture(scope="module")
def rows() -> list[triage.TriageRow]:
    return triage.score_digest(json.loads(FIXTURE.read_text()))


def test_partition_ia_matches_that_days_headline(rows: list[triage.TriageRow]) -> None:
    ia = [r for r in rows if r.partition == triage.PARTITION_IA]
    assert [r.ticker for r in ia] == ["ALHC", "CLOV", "MOH"]


def test_partition_ia_scores(rows: list[triage.TriageRow]) -> None:
    got = {r.ticker: r.triage for r in rows if r.partition == triage.PARTITION_IA}
    assert got["ALHC"] == pytest.approx(0.8096, abs=5e-4)
    assert got["CLOV"] == pytest.approx(0.7246, abs=5e-4)
    assert got["MOH"] == pytest.approx(0.6996, abs=5e-4)


def test_clov_is_docked_for_its_red_flag(rows: list[triage.TriageRow]) -> None:
    """오늘 리포트가 ⚠ 로만 표시하던 것이 순서로 올라온다."""
    clov = next(r for r in rows if r.ticker == "CLOV")
    moh = next(r for r in rows if r.ticker == "MOH")
    assert clov.c == pytest.approx(0.85)
    assert moh.c == pytest.approx(1.00)


def test_evidence_defect_holds_j_below_point_eight(rows: list[triage.TriageRow]) -> None:
    """편입 가능·신뢰인데도 증거품질이 11/23·12/23 이라 J 가 멈춘다 (스펙 §6.1)."""
    j = {r.theme: r.j for r in rows}
    assert j["managed_care"] == pytest.approx(17 / 23)
    assert j["shipping_container"] == pytest.approx(35 / 46)
    assert all(v is not None and v < 0.8 for v in j.values())


def test_partition_ib_top_is_cmre(rows: list[triage.TriageRow]) -> None:
    ib = [r for r in rows if r.partition == triage.PARTITION_IB]
    assert len(ib) == 12
    assert ib[0].ticker == "CMRE"


def test_rows_are_sorted_by_partition_then_score(rows: list[triage.TriageRow]) -> None:
    seen = [triage.PARTITION_ORDER.index(r.partition) for r in rows]
    assert seen == sorted(seen), "구획 순서가 먼저다"
    for part in triage.PARTITION_ORDER:
        vals = [r.triage for r in rows if r.partition == part and r.triage is not None]
        assert vals == sorted(vals, reverse=True)


def test_scores_are_not_comparable_across_partitions(rows: list[triage.TriageRow]) -> None:
    """I-B 의 값이 I-A 보다 클 수 있다 — 백분위가 구획별로 따로 매겨지기 때문이다.

    이 사실이 깨지면 리포트가 구획을 넘어 정렬해도 된다는 오해가 생긴다 (스펙 §6).
    """
    ia_max = max(r.triage for r in rows if r.partition == triage.PARTITION_IA)
    ib_max = max(r.triage for r in rows if r.partition == triage.PARTITION_IB)
    assert ib_max > ia_max
