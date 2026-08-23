"""M3.6 구조 검정 — S1(절대 게이트)·S2(풀/타이밍 2단) 점수 구성이 `docs/12` §4.1 정의와 같은가.

합성 지표에서 (1) 자격 집합이 선언된 조건 그대로인지, (2) 자격 밖은 NaN 인지, (3) 점수가 S0 과 같은
블록 백분위·클래스 가중치로 재정규화 가중합된 값인지, (4) 선언 상수가 문서 값과 같은지 확인한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from _synth_l1 import theme_record, write_themes
from msa.l1.blocks import Indicators
from msa.l1.scoreboard import BLOCKS, scoreboard_history
from msa.l1.structures import (
    S1_BLOCKS,
    S1_DD_MAX,
    S1_MONTHS_MIN,
    S2_POOL_BLOCKS,
    S2_POOL_MIN,
    S2_TIMING_BLOCKS,
    structure_scores,
)
from msa.themes import BLOCK_WEIGHTS, ThemeSet


@pytest.fixture(scope="module")
def themes(tmp_path_factory: pytest.TempPathFactory) -> ThemeSet:
    classes = ["commodity_supply", "secular_growth", "credit_rate", "inventory"]
    recs = [theme_record(f"t{i:02d}", classes[i % 4], i) for i in range(12)]
    return write_themes(tmp_path_factory.mktemp("themes"), recs)


@pytest.fixture(scope="module")
def ind(themes: ThemeSet) -> Indicators:
    """월말 6개 × 테마 12개. 점수에 들어가는 지표 전부 난수 + dd_10y/months_since_peak 는 격자."""
    from msa.l1.scoreboard import SCORED

    rng = np.random.default_rng(7)
    dates = pd.date_range("2015-01-31", periods=6, freq="ME")
    idx = pd.MultiIndex.from_product([dates, themes.ids()], names=["date", "theme"])
    cols = sorted({i for b in BLOCKS for i in SCORED[b]})
    m = pd.DataFrame(rng.normal(size=(len(idx), len(cols))), index=idx, columns=cols)
    # 게이트 변수: 테마 번호로 결정론적 — 절반은 −60%/18개월(자격), 나머지는 −30% 또는 6개월
    tn = np.array([int(t[1:]) for t in idx.get_level_values("theme")])
    m["dd_10y"] = np.where(tn % 2 == 0, -0.60, -0.30)
    m["months_since_peak"] = np.where(tn % 3 == 0, 6.0, 18.0)
    return Indicators(monthly=m)


def test_declared_constants_match_docs12() -> None:
    assert S1_DD_MAX == -0.50 and S1_MONTHS_MIN == 12 and S2_POOL_MIN == 0.5
    assert S1_BLOCKS == ("B", "C", "D", "E", "F")
    assert S2_POOL_BLOCKS == ("A", "B") and S2_TIMING_BLOCKS == ("C", "E", "F")


def test_s1_gate_and_renormalized_score(ind: Indicators, themes: ThemeSet) -> None:
    sb = scoreboard_history(ind, themes)
    sc = structure_scores(ind, themes, sb)
    assert sc.index.equals(sb.index)
    # 자격 = dd_10y ≤ −50% AND months_since_peak ≥ 12  → 테마 번호 짝수이면서 3의 배수가 아닌 것
    tn = np.array([int(t[1:]) for t in sc.index.get_level_values("theme")])
    expect = (tn % 2 == 0) & (tn % 3 != 0)
    assert (sc["S1_eligible"].to_numpy() == expect).all()
    assert sc.loc[~sc["S1_eligible"], "S1"].isna().all()
    assert sc.loc[sc["S1_eligible"], "S1"].notna().all()
    # 점수 = Σ_{B..F} w·pct / Σ w  (A 제외, 같은 블록 백분위·같은 클래스 가중치)
    for key in sc.index[sc["S1_eligible"]][:5]:
        cc = sb.loc[key, "cycle_class"]
        w = BLOCK_WEIGHTS[cc]
        num = sum(w[b] * sb.loc[key, f"{b}_pct"] for b in S1_BLOCKS)
        den = sum(w[b] for b in S1_BLOCKS)
        assert sc.loc[key, "S1"] == pytest.approx(num / den)
    assert sc["S0"].equals(sb["score_s0"])  # S0 = 구 복합(6블록 가산)


def test_s2_pool_eligibility_and_timing_score(ind: Indicators, themes: ThemeSet) -> None:
    sb = scoreboard_history(ind, themes)
    sc = structure_scores(ind, themes, sb)
    pool = sb[["A_pct", "B_pct"]].mean(axis=1)
    assert np.allclose(sc["S2_pool"].to_numpy(), pool.to_numpy(), equal_nan=True)
    assert (sc["S2_eligible"].to_numpy() == (pool >= S2_POOL_MIN).to_numpy()).all()
    assert sc.loc[~sc["S2_eligible"], "S2"].isna().all()
    # 채택된 스코어보드 `score` 와 S2 는 같은 것이다
    pd.testing.assert_series_equal(sc["S2"], sb["score"], check_names=False)
    # 자격 집합이 비지도, 전부도 아니다 (12 테마 난수라 정확한 절반은 아니다)
    n = sc.groupby(level="date")["S2_eligible"].sum()
    assert (n >= 1).all() and (n <= 11).all()
    for key in sc.index[sc["S2_eligible"]][:5]:
        cc = sb.loc[key, "cycle_class"]
        w = BLOCK_WEIGHTS[cc]
        num = sum(w[b] * sb.loc[key, f"{b}_pct"] for b in S2_TIMING_BLOCKS)
        den = sum(w[b] for b in S2_TIMING_BLOCKS)
        assert sc.loc[key, "S2"] == pytest.approx(num / den)
