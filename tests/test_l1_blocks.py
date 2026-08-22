"""L1 블록 수학 헬퍼·VCP·브레드스 리드·축 1 판정 — 합성 데이터, 스토어 없음."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from msa.l1.blocks import (
    axis1_verdict,
    breadth_lead_months,
    own_history_pct,
    rolling_slope,
    vcp_index_score,
)
from msa.vendor.taa_signals import momentum_13612w
from msa.vendor.vcp import build_contractions, compress_pivots, find_pivots


def test_rolling_slope_matches_polyfit() -> None:
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2020-01-01", periods=400)
    df = pd.DataFrame(
        {"a": np.cumsum(rng.normal(size=400)), "b": np.linspace(0, 10, 400)}, index=idx
    )
    got = rolling_slope(df, 63)
    for t in (100, 250, 399):
        y = df["a"].iloc[t - 62 : t + 1].to_numpy()
        exp = np.polyfit(np.arange(63), y, 1)[0]
        assert got["a"].iloc[t] == pytest.approx(exp, rel=1e-9, abs=1e-12)
    # 선형 열은 어디서나 같은 기울기
    assert got["b"].iloc[100] == pytest.approx(10 / 399, rel=1e-9)
    assert got["a"].iloc[:62].isna().all()


def test_own_history_pct_and_short_history_flag() -> None:
    idx = pd.date_range("2000-01-31", periods=200, freq="ME")
    m = pd.DataFrame({"x": np.arange(200, dtype=float)}, index=idx)
    pct, short = own_history_pct(m, window=120, min_periods=84, z_min=36)
    assert pct["x"].iloc[:35].isna().all()
    assert short["x"].iloc[36:83].all()  # z-score 대체 구간
    assert not short["x"].iloc[84:].any()
    assert pct["x"].iloc[150] == pytest.approx(1.0)  # 단조 증가 → 늘 최고 백분위
    assert 0.9 < pct["x"].iloc[50] <= 1.0  # z → Φ 도 상단


def test_breadth_lead_counts_months_before_index_turn() -> None:
    idx = pd.date_range("2020-01-31", periods=12, freq="ME")
    # 브레드스는 3월부터 0.5 위, 지수는 7월부터 SMA200 위 → 리드 4개월
    breadth = pd.DataFrame(
        {"t": [0.2, 0.3, 0.6, 0.6, 0.7, 0.7, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8]}, index=idx
    )
    above = pd.DataFrame({"t": [False] * 6 + [True] * 6}, index=idx)
    lead = breadth_lead_months(breadth, above)
    assert lead["t"].iloc[2] == 0  # 지수 아래, 브레드스 런 시작 달 → 0
    assert lead["t"].iloc[5] == 3  # 지수 아래, 브레드스 3개월째
    assert lead["t"].iloc[6] == 4  # 지수 전환 달: 4개월 리드
    assert lead["t"].iloc[11] == 4  # 이후에도 전환 시점 기준으로 유지
    # 브레드스가 지수보다 늦으면 0
    breadth2 = pd.DataFrame({"t": [0.2] * 8 + [0.6] * 4}, index=idx)
    lead2 = breadth_lead_months(breadth2, above)
    assert lead2["t"].iloc[6] == 0
    assert lead2["t"].iloc[11] == 0


def test_axis1_verdict_table() -> None:
    assert axis1_verdict(0.03, 0.01) == "cycle"
    assert axis1_verdict(0.0, -0.05) == "cycle"
    assert axis1_verdict(-0.01, -0.05) == "warning"
    assert axis1_verdict(-0.05, -0.08) == "death"  # 가속
    assert axis1_verdict(-0.05, -0.01) == "warning"  # 감속 — 표의 공백
    assert axis1_verdict(float("nan"), 0.0) == "n/a"


def test_vendored_vcp_pivots_and_contractions() -> None:
    idx = pd.bdate_range("2021-01-01", periods=10)
    close = pd.Series([95, 100, 90, 100, 94, 100, 97, 100, 99, 100], index=idx, dtype=float)
    piv = compress_pivots(find_pivots(close, left=1, right=1))
    kinds = [p[1] for p in piv]
    assert kinds == ["H", "L", "H", "L", "H", "L", "H", "L"]  # 양 끝은 피벗이 될 수 없다
    cons = build_contractions(piv, ref_level=100.0, tol=0.1, max_drop_from_ref=1.0)
    depths = [round(c["depth"], 2) for c in cons]
    assert depths == [0.10, 0.06, 0.03, 0.01]


def test_vcp_index_score_shrinking_vs_expanding() -> None:
    def zig(troughs: list[float], seg: int = 10) -> pd.Series:
        # 100 → trough → 100 … 를 선형 램프로 (평탄 구간 없음)
        pts: list[float] = [100.0]
        for t in troughs:
            pts += list(np.linspace(100, t, seg + 1)[1:]) + list(np.linspace(t, 100, seg + 1)[1:])
        pts += list(np.linspace(100, 99, 6)[1:]) + [100.0] * 1
        return pd.Series(pts, index=pd.bdate_range("2021-01-01", periods=len(pts)), dtype=float)

    shrinking = zig([80, 90, 95])  # 20% → 10% → 5%
    assert vcp_index_score(shrinking, left=3, right=3) == pytest.approx(1.0)
    expanding = zig([95, 90, 80])  # 5% → 10% → 20%
    assert vcp_index_score(expanding, left=3, right=3) == pytest.approx(0.0)
    assert np.isnan(vcp_index_score(shrinking.iloc[:30]))


def test_momentum_13612w_weights() -> None:
    idx = pd.date_range("2020-01-31", periods=14, freq="ME")
    m = pd.DataFrame({"p": 1.01 ** np.arange(14)}, index=idx)  # 월 1%
    s = momentum_13612w(m)["p"]
    r1, r3, r6, r12 = 0.01, 1.01**3 - 1, 1.01**6 - 1, 1.01**12 - 1
    assert s.iloc[-1] == pytest.approx(12 * r1 + 4 * r3 + 2 * r6 + r12)
    assert s.iloc[:12].isna().all()
