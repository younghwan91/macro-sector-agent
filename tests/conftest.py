from __future__ import annotations

from typing import Any

import pytest

from msa.config import paths


@pytest.fixture(autouse=True)
def _plain_cli_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI help 문자열 assert 가 ANSI 로 쪼개지지 않게 한다.

    rich 는 GITHUB_ACTIONS 가 있으면 비-TTY 여도 컬러를 강제로 켠다 — 그러면
    help 의 `--no-write` 가 `ESC[1;36m-ESC[0m...-write` 로 나와서 substring
    assert 가 CI 에서만 깨진다. TERM=dumb 는 rich 가 컬러를 포기하는 유일한 신호다.
    """
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("TERM", "dumb")


@pytest.fixture(scope="session")
def store():
    """실제 DuckDB 스토어. 없으면 스킵한다 — `@pytest.mark.data` 테스트에서만 쓴다."""
    from msa.data.store import Store

    p = paths().duckdb
    if not p.exists():
        pytest.skip(f"DuckDB 스토어 없음: {p}")
    with Store(p) as s:
        yield s


def make_thesis(**over: Any) -> dict[str, Any]:
    """검증을 통과하는 최소 thesis (docs/specs/thesis.schema.yaml). 테스트에서 덮어써서 깨뜨린다."""
    t: dict[str, Any] = {
        "theme_id": "uranium",
        "generated_at": "2026-09-01",
        "horizon_months": [6, 18],
        "claim": "우라늄 현물가가 2027년까지 $110 이상을 유지한다",
        "mechanism": "2011-2020 저가격으로 신규 개발 중단 → 1차 공급 부족, 리드타임 7~10년",
        "triggers": [
            {"observable": "Cameco 가이던스 상향", "source": "분기 실적", "by": "2026-Q4"},
            {
                "observable": "URA 종가 > 40 (5일 연속)",
                "source": "가격",
                "by": "2027-03-31",
                "check": {"kind": "price_above", "ticker": "URA", "level": 40, "days": 5},
            },
            {"observable": "장기계약가 > 현물가", "source": "UxC", "by": "2027-Q1"},
        ],
        "invalidations": [
            {"observable": "카자흐 쿼터 +20%", "source": "Kazatomprom 공시", "action": "exit"},
            {
                "observable": "URA 종가 < 20 (3일 연속)",
                "source": "가격",
                "action": "exit",
                "check": {"kind": "price_below", "ticker": "URA", "level": 20, "days": 3},
            },
        ],
        "key_uncertainties": ["SPUT 매집 비중 분리 불가"],
        "bear_case": "SPUT 프리미엄이 꺼지면 현물가는 $70 으로 회귀한다 — 원문 보존.",
        "value_trap_axes": {
            "unit_demand": {
                "verdict": "cycle",
                "evidence_refs": [1],
                "axis1_available": True,
                "unit_series_source": "physical_series",
            },
            "capital_cycle": {"verdict": "cycle", "evidence_refs": [1]},
            "substitution": {"verdict": "cycle", "evidence_refs": [1]},
            "cost_curve": {"verdict": "cycle", "evidence_refs": [1]},
            "terminal_risk": {"verdict": "warning", "evidence_refs": [1]},
        },
        "gate_result": {
            "status": "passed",
            "portfolio_eligible": True,
            "rule": "어느 기각 조항에도 걸리지 않음",
            "axis_verdicts": {
                "unit_demand": "cycle",
                "capital_cycle": "cycle",
                "substitution": "cycle",
                "cost_curve": "cycle",
                "terminal_risk": "warning",
            },
        },
        # 0.80 = docs/04 §4 를 이 축 판정에 실제로 적용한 값 (base 0.50 + 0.15 축1 cycle
        # + 0.15 축3 cycle). 예전 값 0.72 는 docs/05 §3 예시에서 옮겨 온 예시 숫자였고 §4 의
        # 항(전부 0.05 단위)으로는 나올 수 없다 — 재도출 대조(l3/schema)가 이제 그것을 거부한다.
        "cycle_confidence": 0.80,
        "evidence": [
            {
                "id": 1,
                "claim": "2011-2020 신규 광산 FID 0건",
                "source_url": "https://example.org/fid",
                "date": "2026-06-14",
                "reliability": "high",
            }
        ],
    }
    t.update(over)
    return t


@pytest.fixture
def thesis_ok() -> dict[str, Any]:
    return make_thesis()
