"""L1 점수 구조 검정의 후보 구성이 문서 정의와 같은가 — M3.6(`docs/12` §4.1)·M3.7(`docs/17` §2).

합성 지표에서 (1) 자격 집합이 선언된 조건 그대로인지, (2) 자격 밖은 NaN 인지, (3) 점수가 S0 과 같은
블록 백분위·클래스 가중치로 재정규화 가중합된 값인지, (4) 선언 상수가 문서 값과 같은지 확인한다.

M3.7 은 여기에 둘을 더 본다: (5) **S2·S3·S2ʹ 의 자격이 정확히 같은지** — 짝지은 스프레드 차
(`docs/17` §3.1)가 정당하려면 셋이 같은 달 같은 우주를 봐야 한다, (6) 차 긴 표가 `summarize_spread`
를 그대로 통과하고 값이 `후보 − 기준` 과 같은지.
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


# ---------------------------------------------------------------- M3.7 (docs/17)


def test_m37_declared_constants_match_docs17() -> None:
    from msa.l1.structures import (
        CANDIDATES_M37,
        DIFF_BASE,
        DIFF_PAIRS,
        N_TRIALS_ADDED_M37,
        PBO_VARIANTS,
        S2P_TIMING_BLOCKS,
        S3_BLOCK,
        STRUCTURES,
    )

    assert S3_BLOCK == "C"  # 점수 = C_pct, 가중치 없음
    assert S2P_TIMING_BLOCKS == ("C", "E")  # S2 에서 F 만 뺀 것
    assert CANDIDATES_M37 == ("S3", "S2p") and DIFF_BASE == "S2"
    assert DIFF_PAIRS == (("S3", "S2"), ("S2p", "S2"))
    assert STRUCTURES == ("S0", "S1", "S2", "S3", "S2p")
    assert PBO_VARIANTS == ("S2", "S3", "S2p")
    # 2 후보 × 창 2 × 호라이즌 3 × (IC+스프레드) + 차 2 × 창 2 × 호라이즌 3 = 24 + 12
    assert N_TRIALS_ADDED_M37 == 36


def test_s3_is_c_pct_and_s2p_is_c_e_on_the_same_eligibility(
    ind: Indicators, themes: ThemeSet
) -> None:
    from msa.l1.structures import S2P_TIMING_BLOCKS

    sb = scoreboard_history(ind, themes)
    sc = structure_scores(ind, themes, sb)
    elig = sc["S2_eligible"]
    # 자격은 셋이 정확히 같다 — 그래야 스프레드를 짝지을 수 있다 (docs/17 §3)
    assert sc.loc[~elig, ["S2", "S3", "S2p"]].isna().all().all()
    assert sc.loc[elig, ["S2", "S3", "S2p"]].notna().all().all()
    # S3 = C_pct 그대로 (재정규화·가중치 없음)
    pd.testing.assert_series_equal(sc.loc[elig, "S3"], sb.loc[elig, "C_pct"], check_names=False)
    # S2ʹ = C·E 재정규화 가중합
    for key in sc.index[elig][:5]:
        w = BLOCK_WEIGHTS[sb.loc[key, "cycle_class"]]
        num = sum(w[b] * sb.loc[key, f"{b}_pct"] for b in S2P_TIMING_BLOCKS)
        den = sum(w[b] for b in S2P_TIMING_BLOCKS)
        assert sc.loc[key, "S2p"] == pytest.approx(num / den)


def test_spread_diff_series_is_paired_and_summarizes_with_the_same_machine() -> None:
    """차 긴 표가 `summarize_spread` 를 그대로 통과하고, 값이 후보 − 기준과 같은가."""
    from msa.l1.backtest import summarize_spread
    from msa.l1.structures import spread_diff_series

    dates = pd.date_range("2011-01-31", periods=60, freq="ME")
    rows = []
    rng = np.random.default_rng(3)
    vals = {v: rng.normal(size=len(dates)) for v in ("S2", "S3", "S2p")}
    for h in (3, 12):
        for i, d in enumerate(dates):
            for v in ("S0", "S1", "S2", "S3", "S2p"):
                rows.append(
                    {
                        "date": d,
                        "variant": v,
                        "horizon": h,
                        # S3 은 S2 를 정확히 h 만큼 올린 것 → 차가 상수 h 여야 한다
                        "spread": (vals["S2"][i] + h) if v == "S3" else vals.get(v, vals["S2"])[i],
                        "ret_top": 0.0,
                        "ret_bot": 0.0,
                        "n_universe": 60,
                        "n_small_excluded": 3,
                    }
                )
    sp = pd.DataFrame(rows)
    d = spread_diff_series(sp)
    assert set(d["variant"]) == {"S3-S2", "S2p-S2"}
    got = d[(d["variant"] == "S3-S2") & (d["horizon"] == 12)]["spread"].to_numpy()
    assert np.allclose(got, 12.0)  # S3 − S2 = h 로 심어 뒀다
    assert np.allclose(
        d[(d["variant"] == "S2p-S2") & (d["horizon"] == 3)]["spread"].to_numpy(),
        vals["S2p"] - vals["S2"],
    )
    summ = summarize_spread(d)
    cell = summ[
        (summ["window"] == "primary") & (summ["horizon"] == 12) & (summ["variant"] == "S3-S2")
    ]
    assert len(cell) == 1 and cell.iloc[0]["mean"] == pytest.approx(12.0)
    assert cell.iloc[0]["ci_lo"] == pytest.approx(12.0)  # 상수열이라 CI 가 붙는다


def test_diff_verdict_reads_one_side_only() -> None:
    from msa.l1.structures import _diff_verdict

    assert _diff_verdict(pd.Series({"ci_lo": 0.01, "ci_hi": 0.05})) == "beats_S2"
    assert _diff_verdict(pd.Series({"ci_lo": -0.05, "ci_hi": -0.01})) == "worse_than_S2"
    assert _diff_verdict(pd.Series({"ci_lo": -0.01, "ci_hi": 0.05})) == "indistinguishable"
    assert _diff_verdict(pd.Series({"ci_lo": np.nan, "ci_hi": np.nan})) == "undetermined"
