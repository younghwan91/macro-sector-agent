"""DAG 적재·스키마·커버리지 검증 — 합성 YAML."""

from __future__ import annotations

from pathlib import Path

import pytest

from _l2_helpers import THEMES, small_dag_dict, write_dag
from msa.l2.dag import (
    STRENGTH_WEIGHT,
    DagError,
    expand_edges,
    load_dag,
    parse_state_rule,
    validate_dag,
)


def test_load_small_dag(tmp_path: Path) -> None:
    dag = load_dag(write_dag(tmp_path))
    assert len(dag.drivers) == 10
    assert dag.common_factors == ["usd_liquidity"]
    e = dag.edges[0]
    assert e.source == "real_rate_10y" and e.sign == -1 and e.weight == STRENGTH_WEIGHT["strong"]
    assert e.lag_months == (0, 3)
    rule = dag.driver("real_rate_10y").rule
    assert rule is not None and rule.band_lo == -25 and rule.band_hi == 25
    # policy_events 의 서술형 규칙은 rule=None
    assert dag.driver("policy_events").rule is None
    # contradicts_rule 이 읽힌다
    assert dag.edges[1].contradicts_rule is not None


def test_state_rule_direction_and_favorable() -> None:
    r = parse_state_rule(
        {"favorable_when": "change_6m_bp < -25", "neutral_band": [-25, 25]}, "change_6m_bp"
    )
    assert r is not None
    assert r.direction(-40) == -1 and r.favorable(-40)
    assert r.direction(40) == 1 and not r.favorable(40)
    assert r.direction(0) == 0
    # 밴드 없으면 임계값 하나가 경계
    r2 = parse_state_rule({"favorable_when": "change_6m > 0"}, "change_6m")
    assert r2 is not None and r2.band_lo == 0 == r2.band_hi
    assert r2.direction(0.01) == 1 and r2.direction(-0.01) == -1
    # 측정값 이름이 measure 와 다르면 실패
    with pytest.raises(DagError):
        parse_state_rule({"favorable_when": "yoy > 0"}, "change_6m")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["edges"][0].pop("channel"),
        lambda d: d["edges"][0].update(channel="   "),
        lambda d: d["edges"][0].update(sign=2),
        lambda d: d["edges"][0].update(strength="huge"),
        lambda d: d["edges"][0].update({"from": "not_a_driver"}),
        lambda d: d["edges"][0].update(to=["*"]),  # 비공통 드라이버의 와일드카드
        lambda d: d["edges"][4].update(to=["alpha"]),  # 공통 인자가 개별 테마 지목
        lambda d: d["drivers"].append(dict(d["drivers"][0])),  # id 중복
    ],
)
def test_schema_errors_raise(tmp_path: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    doc = small_dag_dict()
    mutate(doc)
    with pytest.raises(DagError):
        load_dag(write_dag(tmp_path, doc))


def test_coverage_validation_reports_unknown_and_undercovered(tmp_path: Path) -> None:
    dag = load_dag(write_dag(tmp_path))
    v = validate_dag(dag, THEMES)
    assert v.schema_ok
    assert not v.coverage_ok
    assert v.unknown_theme_refs == {2: ["zeta_unknown"]}
    assert "epsilon" in v.undercovered and v.undercovered["epsilon"] == 0
    # alpha: real_rate, dollar, gold, copper = 4 (공통 인자 제외)
    assert v.in_degree["alpha"] == 4
    assert v.n_pairs == sum(v.in_degree.values())
    assert "epsilon" in v.summary() and "zeta_unknown" in v.summary()


def test_expand_edges_skips_unknown_and_expands_wildcard(tmp_path: Path) -> None:
    dag = load_dag(write_dag(tmp_path))
    pairs = expand_edges(dag, THEMES)
    themes_hit = {p.theme for p in pairs}
    assert "zeta_unknown" not in themes_hit
    cf = [p for p in pairs if p.edge.wildcard]
    assert len(cf) == len(THEMES)


def test_empty_theme_list_raises(tmp_path: Path) -> None:
    dag = load_dag(write_dag(tmp_path))
    with pytest.raises(DagError):
        validate_dag(dag, [])


def test_real_dag_loads_and_schema_passes() -> None:
    """저장소의 실제 DAG 는 스키마를 통과해야 한다 (커버리지는 별도 — 134 테마 대비 미달 있음)."""
    dag = load_dag()
    assert len(dag.drivers) == 26
    assert len(dag.edges) == 72
    rules = sum(1 for e in dag.edges if e.contradicts_rule is not None)
    assert rules == 2
