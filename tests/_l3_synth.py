"""L3 테스트용 합성 입력 — 스토어·네트워크 없이 `ResearchInputs` 와 스캔 디렉터리를 만든다."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pandas as pd

from msa.config import REPO_ROOT
from msa.l3.contracts import (
    Axis1Inputs,
    MacroState,
    MemberSummary,
    ResearchInputs,
    ThemeScorecard,
)

ASOF = "2026-08-14"


def axis1(kind: str = "cycle") -> Axis1Inputs:
    """kind: cycle | warning | death | contested | na"""
    base: dict[str, Any] = {
        "axis1_status": "ok_fallback",
        "unit_source": "etf:DBA:price",
        "verdict_pre_ss": "cycle",
        "verdict_post_ss": "cycle",
        "unit_cagr_10y": 0.021,
        "unit_cagr_5y": 0.03,
        "unit_cagr_10y_median": 0.018,
        "sign_split": False,
        "ss_n": 9,
        "ss_coverage": 0.75,
        "ma_flag": False,
        "exit_count": 3,
    }
    if kind == "warning":
        base.update(verdict_pre_ss="warning", verdict_post_ss="warning", unit_cagr_10y=-0.01)
    elif kind == "death":
        base.update(
            verdict_pre_ss="death",
            verdict_post_ss="death",
            unit_cagr_10y=-0.041,
            unit_cagr_5y=-0.06,
            unit_cagr_10y_median=-0.03,
        )
    elif kind == "contested":
        base.update(verdict_pre_ss="death", verdict_post_ss="warning", unit_cagr_10y=-0.015)
    elif kind == "split":
        base.update(sign_split=True, unit_cagr_10y=-0.005, unit_cagr_10y_median=0.01)
    elif kind == "na":
        base.update(
            axis1_status="not_declared",
            unit_source=None,
            verdict_pre_ss=None,
            verdict_post_ss=None,
            unit_cagr_10y=None,
            unit_cagr_5y=None,
            unit_cagr_10y_median=None,
            sign_split=None,
            ss_n=None,
            ss_coverage=None,
            ma_flag=None,
        )
    return Axis1Inputs(**base)


def scorecard(theme: str = "uranium", a1: Axis1Inputs | None = None, **kw: Any) -> ThemeScorecard:
    d: dict[str, Any] = {
        "theme_id": theme,
        "scan_date": ASOF,
        "rank": 3,
        "score": 0.7123,
        "cycle_class": "commodity_supply",
        "block_scores": {"A": 0.81, "B": 0.77, "C": 0.4, "D": 0.6, "E": 0.9, "F": 0.5},
        "n_live": 13,
        "small_sample": False,
        "secular": False,
        "short_hist": False,
        "capex_to_da_qtrs_below1": 10.0,
        "capex_to_da": 0.62,
        "ebitda_nonpos_share": 0.3,
        "net_debt_ebitda": 1.1,
        "dd_10y": -0.55,
        "months_since_peak": 40.0,
        "breadth_200": 0.45,
        "flags": "",
        "axis1": a1 or axis1(),
    }
    d.update(kw)
    return ThemeScorecard(**d)


MEMBERS = (
    MemberSummary("CCJ", "Cameco Corp", 2.1e10, 2.5e9, 0.7, 0.8, 0.3, 0.02),
    MemberSummary("UEC", "Uranium Energy Corp", 3.0e9, 1.0e8, 1.2, None, -0.1, 0.0),
    MemberSummary("UUUU", "Energy Fuels Inc", 1.5e9, 7.0e7, 2.0, None, -0.2, 0.01),
)


def inputs(
    *,
    theme: str = "uranium",
    a1: Axis1Inputs | None = None,
    macro: MacroState | None = None,
    prior: dict[str, Any] | None = None,
    prior_path: str | None = None,
    cycle_class: str = "commodity_supply",
    **card_kw: Any,
) -> ResearchInputs:
    return ResearchInputs(
        theme_id=theme,
        theme_name="우라늄",
        asof=ASOF,
        industries=("Uranium",),
        scorecard=scorecard(theme, a1, cycle_class=cycle_class, **card_kw),
        members=MEMBERS,
        macro=macro,
        prior_thesis=prior,
        prior_thesis_path=prior_path,
        cases=(),
        scan_dir=f"state/scans/{ASOF}",
        warnings=(),
    )


def write_scan_dir(
    state_dir: Path, asof: str = ASOF, themes: tuple[str, ...] = ("uranium",)
) -> Path:
    """`msa scan` 산출물 형식의 최소 scoreboard.csv + indicators.csv."""
    d = state_dir / "scans" / asof
    d.mkdir(parents=True, exist_ok=True)
    tpath = state_dir / "themes.yaml"  # load_themes() 기본 경로 = MSA_STATE/themes.yaml
    if not tpath.exists():
        tpath.write_text(
            (REPO_ROOT / "state" / "themes.yaml").read_text(encoding="utf-8"), encoding="utf-8"
        )
    sb_rows = []
    ind_rows = []
    for i, t in enumerate(themes):
        sb_rows.append(
            {
                "theme": t,
                "rank": i + 1,
                "cycle_class": "commodity_supply",
                "score": 0.7 - 0.05 * i,
                "A": 0.8,
                "B": 0.7,
                "C": 0.4,
                "D": 0.6,
                "E": 0.9,
                "F": 0.5,
                "n_live": 13,
                "small_sample": False,
                "secular": False,
                "short_hist": False,
                "axis1_status": "ok_fallback",
                "verdict_post_ss": "cycle",
                "axis1_contested": False,
                "flags": "",
            }
        )
        ind_rows.append(
            {
                "theme": t,
                "capex_to_da": 0.62,
                "capex_to_da_qtrs_below1": 10.0,
                "ebitda_nonpos_share": 0.3,
                "net_debt_ebitda": 1.1,
                "dd_10y": -0.55,
                "months_since_peak": 40.0,
                "breadth_200": 0.45,
                "exit_count": 3,
                "unit_cagr_10y": 0.021,
                "unit_cagr_5y": 0.03,
                "unit_cagr_10y_median": 0.018,
                "sign_split": 0.0,
                "ss_n": 9.0,
                "ss_coverage": 0.75,
                "ma_flag": 0.0,
                "axis1_contested": 0.0,
                "verdict_post_ss": "cycle",
                "verdict_pre_ss": "cycle",
                "unit_source": "etf:URA:price",
                "axis1_status": "ok_fallback",
                "short_hist_D": False,
                "short_hist_roic": False,
                "short_hist_margin": False,
                "short_hist_range": False,
                "cpi_missing": True,
            }
        )
    pd.DataFrame(sb_rows).set_index("theme").to_csv(d / "scoreboard.csv")
    pd.DataFrame(ind_rows).set_index("theme").to_csv(d / "indicators.csv")
    return d


def valid_thesis() -> dict[str, Any]:
    """스키마·§4 규약을 전부 만족하는 thesis — 테스트는 여기서 한 필드씩 깨뜨린다."""
    return copy.deepcopy(
        {
            "theme_id": "uranium",
            "generated_at": ASOF,
            "supersedes": None,
            "horizon_months": [6, 18],
            "claim": "우라늄 현물가는 2027년까지 $110 이상을 유지하고 광산 EBITDA 가 배증한다.",
            "mechanism": "2011-2020 저가격 국면에서 신규 개발이 중단돼 1차 공급이 수요의 75% "
            "수준이고, 광산 리드타임 7~10년이라 3년 내 공급 반응이 불가능하다.",
            "triggers": [
                {"observable": "Cameco 생산 가이던스 상향", "source": "분기 실적", "by": "2026-Q4"}
            ],
            "invalidations": [
                {"observable": "카자흐 생산 쿼터 20% 이상 상향", "source": "공시", "action": "exit"}
            ],
            "key_uncertainties": ["SPUT 매집 비중"],
            "bear_case": "원문 bear case",
            "value_trap_axes": {
                "unit_demand": {
                    "verdict": "cycle",
                    "evidence_refs": [1],
                    "axis1_available": True,
                    "unit_series_source": "physical_series",
                    "verdict_pre_ss": "cycle",
                    "verdict_post_ss": "cycle",
                    "axis1_contested": False,
                },
                "capital_cycle": {"verdict": "cycle", "evidence_refs": [1]},
                "substitution": {"verdict": "cycle", "evidence_refs": [2]},
                "cost_curve": {"verdict": "cycle", "evidence_refs": [1]},
                "terminal_risk": {"verdict": "warning", "evidence_refs": [2]},
            },
            "gate_result": {
                "status": "passed",
                "portfolio_eligible": True,
                "rule": "04 §3 의 어느 기각 조항에도 걸리지 않음",
                "axis_verdicts": {
                    "unit_demand": "cycle",
                    "capital_cycle": "cycle",
                    "substitution": "cycle",
                    "cost_curve": "cycle",
                    "terminal_risk": "warning",
                },
                "reason": "",
            },
            "cycle_confidence": 0.72,
            "evidence": [
                {
                    "id": 1,
                    "claim": "2011-2020 신규 광산 FID 0건",
                    "source_url": "https://example.org/1",
                    "date": "2026-06-14",
                    "reliability": "high",
                },
                {
                    "id": 2,
                    "claim": "SMR 파이프라인",
                    "source_url": "https://example.org/2",
                    "date": "2026-05-01",
                    "reliability": "medium",
                },
                {
                    "id": 3,
                    "claim": "포럼 소문",
                    "source_url": "https://example.org/3",
                    "date": "2024-01-01",
                    "reliability": "low",
                },
            ],
        }
    )
