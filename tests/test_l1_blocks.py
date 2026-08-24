"""L1 블록 수학 헬퍼·VCP·브레드스 리드·축 1 판정 — 합성 데이터, 스토어 없음.

`_ref_*` 는 2026-08-23 벡터화 전의 구 구현(스칼라 루프)이다. 새 구현은 이것과 **같은 값**을
내야 한다 — Φ(z) 만 `math.erf` → `scipy.special.ndtr` 로 바뀌어 ≤ 1 ulp 허용.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from msa.l1.blocks import (
    Indicators,
    _verdicts,
    axis1_verdict,
    breadth_lead_months,
    months_since_peak,
    own_history_pct,
    rolling_slope,
    vcp_index_matrix,
    vcp_index_score,
)
from msa.vendor.taa_signals import momentum_13612w
from msa.vendor.vcp import build_contractions, compress_pivots, find_pivots

# ---------------------------------------------------------------- 구 구현 (대조용)


def _ref_breadth_lead_months(
    breadth: pd.DataFrame, above: pd.DataFrame, cap: int = 12
) -> pd.DataFrame:
    br = (breadth >= 0.5) & breadth.notna()
    ab = above.fillna(False).astype(bool)
    pos = pd.DataFrame(
        np.tile(np.arange(len(br))[:, None], (1, br.shape[1])), index=br.index, columns=br.columns
    ).astype(float)
    start_br = pos.where(br & ~br.shift(1, fill_value=False)).ffill().where(br)
    start_ab = pos.where(ab & ~ab.shift(1, fill_value=False)).ffill().where(ab)
    ref = start_ab.where(ab, pos)
    sb = start_br.to_numpy(dtype=float)
    rf = ref.to_numpy(dtype=float)
    out = np.full(br.shape, np.nan)
    for j in range(br.shape[1]):
        for i in range(br.shape[0]):
            r = rf[i, j]
            if np.isnan(r):
                continue
            s = sb[int(r), j]
            out[i, j] = 0.0 if np.isnan(s) else min(float(r - s), float(cap))
    return pd.DataFrame(out, index=br.index, columns=br.columns)


def _ref_months_since_max(a: np.ndarray) -> float:
    if np.isnan(a).all():
        return np.nan
    return float(len(a) - 1 - int(np.nanargmax(a)))


def _ref_months_since_peak(pm: pd.DataFrame) -> pd.DataFrame:
    return pm.rolling(120, min_periods=12).apply(_ref_months_since_max, raw=True)


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _ref_own_history_pct(
    m: pd.DataFrame, window: int = 120, min_periods: int = 84, z_min: int = 36
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pct = m.rolling(window, min_periods=min_periods).rank(pct=True)
    cnt = m.rolling(window, min_periods=1).count()
    mu = m.rolling(window, min_periods=z_min).mean()
    sd = m.rolling(window, min_periods=z_min).std()
    z = (m - mu) / sd.replace(0.0, np.nan)
    zpct = z.apply(lambda col: col.map(lambda v: _phi(v) if pd.notna(v) else np.nan))
    short = (cnt < min_periods) & (cnt >= z_min) & m.notna()
    return pct.where(~short, zpct), short


def _ref_vcp_index_score(
    close: pd.Series, *, left: int = 5, right: int = 5, max_cons: int = 4
) -> float:
    c = close.dropna()
    if len(c) < 60:
        return np.nan
    piv = compress_pivots(find_pivots(c, left=left, right=right))
    cons = build_contractions(piv, ref_level=float(c.max()), tol=0.10, max_drop_from_ref=1.0)
    cons = [x for x in cons if x["depth"] > 0.0][-max_cons:]
    if len(cons) < 2:
        return 0.0
    depths = [x["depth"] for x in cons]
    steps = len(depths) - 1
    shrinking = sum(1 for i in range(1, len(depths)) if depths[i] < depths[i - 1])
    return shrinking / steps


def _ref_vcp_matrix(P: pd.DataFrame, me: pd.DatetimeIndex) -> pd.DataFrame:
    """구 `compute_indicators` 의 VCP 루프 — 월말마다 252일 창을 잘라 `vcp_index_score`."""
    vcp = pd.DataFrame(np.nan, index=me, columns=P.columns)
    pos = P.index.searchsorted(me, side="right")
    for j, col in enumerate(P.columns):
        s = P[col]
        for i, end in enumerate(pos):
            if end < 60:
                continue
            vcp.iat[i, j] = _ref_vcp_index_score(s.iloc[max(0, end - 252) : end])
    return vcp


# ---------------------------------------------------------------- 테스트


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


def test_own_history_pct_matches_scalar_erf_within_1ulp() -> None:
    rng = np.random.default_rng(3)
    idx = pd.date_range("2000-01-31", periods=150, freq="ME")
    m = pd.DataFrame(rng.normal(size=(150, 6)), index=idx, columns=list("abcdef"))
    m.iloc[10:20, 2] = np.nan
    m.iloc[:, 5] = 3.0  # 표준편차 0 → z 정의 안 됨
    got, short = own_history_pct(m)
    ref, short_ref = _ref_own_history_pct(m)
    pd.testing.assert_frame_equal(short, short_ref)
    np.testing.assert_allclose(got.to_numpy(), ref.to_numpy(), rtol=0, atol=3e-16, equal_nan=True)
    # z 대체 구간 밖(순위 백분위)은 비트 단위로 같다
    plain = ~short.to_numpy()
    assert np.array_equal(got.to_numpy()[plain], ref.to_numpy()[plain], equal_nan=True)


def test_months_since_peak_matches_rolling_apply() -> None:
    rng = np.random.default_rng(4)
    idx = pd.date_range("1998-01-31", periods=300, freq="ME")
    pm = pd.DataFrame(
        np.cumsum(rng.normal(size=(300, 5)), axis=0) + 50, index=idx, columns=list("abcde")
    )
    pm.iloc[:40, 1] = np.nan  # 늦게 시작하는 테마
    pm.iloc[100:130, 2] = np.nan  # 중간 결측
    pm.iloc[:, 3] = 7.0  # 평탄 → 최초 도달(첫 번째 최댓값) 규칙
    pm.iloc[:, 4] = np.nan  # 전부 결측
    got = months_since_peak(pm)
    ref = _ref_months_since_peak(pm)
    pd.testing.assert_frame_equal(got, ref, check_exact=True)
    assert got["d"].iloc[200] == 119  # 평탄: 창의 첫 값이 최초 최댓값


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


def test_breadth_lead_matches_double_loop() -> None:
    rng = np.random.default_rng(5)
    idx = pd.date_range("2000-01-31", periods=240, freq="ME")
    breadth = pd.DataFrame(rng.uniform(0, 1, (240, 8)), index=idx, columns=list("abcdefgh"))
    breadth.iloc[:30, 0] = np.nan
    breadth.iloc[:, 7] = 0.9  # 런이 한 번도 끊기지 않고 지수는 30개월 뒤에 돈다 → 상한 12
    above = pd.DataFrame(rng.uniform(0, 1, (240, 8)) > 0.5, index=idx, columns=breadth.columns)
    above.iloc[:30, 7] = False
    above.iloc[30:, 7] = True
    got = breadth_lead_months(breadth, above)
    pd.testing.assert_frame_equal(got, _ref_breadth_lead_months(breadth, above), check_exact=True)
    assert got["h"].iloc[-1] == 12
    # 빈 입력
    empty = breadth.iloc[:0]
    assert breadth_lead_months(empty, above.iloc[:0]).shape == (0, 8)


def test_axis1_verdict_table() -> None:
    assert axis1_verdict(0.03, 0.01) == "cycle"
    assert axis1_verdict(0.0, -0.05) == "cycle"
    assert axis1_verdict(-0.01, -0.05) == "warning"
    assert axis1_verdict(-0.05, -0.08) == "death"  # 가속
    assert axis1_verdict(-0.05, -0.01) == "warning"  # 감속 — 표의 공백
    assert axis1_verdict(float("nan"), 0.0) == "n/a"


def test_verdicts_vector_equals_scalar_table() -> None:
    rng = np.random.default_rng(6)
    idx = pd.date_range("2000-01-31", periods=500, freq="ME")
    c10 = pd.Series(rng.uniform(-0.1, 0.1, 500), index=idx)
    c5 = pd.Series(rng.uniform(-0.1, 0.1, 500), index=idx)
    c10.iloc[::7] = np.nan
    c5.iloc[::11] = np.nan
    c10.iloc[3] = 0.0
    c10.iloc[4] = -0.02  # 경계
    got = _verdicts(c10, c5)
    ref = pd.Series([axis1_verdict(a, b) for a, b in zip(c10, c5, strict=True)], index=idx)
    pd.testing.assert_series_equal(got, ref)
    assert isinstance(got.iloc[0], str)


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


def test_vcp_index_matrix_matches_per_window_loop() -> None:
    rng = np.random.default_rng(7)
    days = pd.bdate_range("2012-01-02", "2016-12-30")
    ret = rng.normal(0, 0.012, (len(days), 6))
    P = pd.DataFrame(np.cumprod(1 + ret, axis=0), index=days, columns=list("abcdef"))
    P.iloc[:300, 1] = np.nan  # 늦게 상장
    P.iloc[:, 2] = 1.0  # 평탄 — 0 폭 수축은 수축이 아니다
    P.iloc[:, 3] = np.round(P.iloc[:, 3], 2)  # 동률 많음 (피벗이 H·L 동시)
    P.iloc[700:720, 4] = np.nan  # 중간 결측
    me = pd.DatetimeIndex(P.resample("ME").last().index)
    got = vcp_index_matrix(P, me)
    ref = _ref_vcp_matrix(P, me)
    pd.testing.assert_frame_equal(got, ref, check_exact=True)
    assert got.notna().to_numpy().sum() > 0


def test_momentum_13612w_weights() -> None:
    idx = pd.date_range("2020-01-31", periods=14, freq="ME")
    m = pd.DataFrame({"p": 1.01 ** np.arange(14)}, index=idx)  # 월 1%
    s = momentum_13612w(m)["p"]
    r1, r3, r6, r12 = 0.01, 1.01**3 - 1, 1.01**6 - 1, 1.01**12 - 1
    assert s.iloc[-1] == pytest.approx(12 * r1 + 4 * r3 + 2 * r6 + r12)
    assert s.iloc[:12].isna().all()


# ---------------------------------------------------------------- 실데이터 대조


@pytest.mark.data
def test_vcp_index_matrix_matches_loop_on_real_panel() -> None:
    """실제 패널 캐시의 테마 8개로 전 월말 VCP — 창마다 계산한 값과 최대 절대 차 0."""
    from msa.config import paths
    from msa.l1.panel import load_cached_panel

    if not (paths().cache).exists():
        pytest.skip("L1 캐시 없음")
    panel = load_cached_panel()
    P = panel.index_level("ew").iloc[:, :8]
    me = pd.DatetimeIndex(P.resample("ME").last().index)
    got = vcp_index_matrix(P, me)
    ref = _ref_vcp_matrix(P, me)
    pd.testing.assert_frame_equal(got, ref, check_exact=True)


# ---------------------------------------------------------------- 버킷 선택 (asof 규약)


def _ind_for_buckets(labels: list[str]) -> Indicators:
    """월말 라벨만 있는 최소 `Indicators` — `bucket_for` 만 본다."""
    idx = pd.MultiIndex.from_product(
        [pd.DatetimeIndex([pd.Timestamp(x) for x in labels]), ["t"]], names=["date", "theme"]
    )
    return Indicators(monthly=pd.DataFrame({"x": 0.0}, index=idx))


def test_bucket_for_past_asof_does_not_return_future_month_end() -> None:
    """과거 `--asof` 는 그 이전 마지막 **완결** 월말을 돌려준다 (2026-08-24 수정).

    예전에는 2020-07-03 → 2020-07-31 (최대 4주 미래) 이었다.
    """
    ind = _ind_for_buckets(["2020-05-31", "2020-06-30", "2020-07-31", "2020-08-31"])
    assert ind.bucket_for(pd.Timestamp("2020-07-03")) == pd.Timestamp("2020-06-30")
    assert ind.bucket_for(pd.Timestamp("2020-07-30")) == pd.Timestamp("2020-06-30")
    assert ind.bucket_for(pd.Timestamp("2020-07-31")) == pd.Timestamp("2020-07-31")


def test_bucket_for_today_scan_keeps_partial_last_bucket() -> None:
    """오늘의 스캔(asof = store_end)은 예전 그대로 부분 버킷을 쓴다 — 회귀 고정."""
    ind = _ind_for_buckets(["2026-06-30", "2026-07-31", "2026-08-31"])
    assert ind.bucket_for(pd.Timestamp("2026-08-14")) == pd.Timestamp("2026-08-31")


def test_bucket_for_raises_before_first_bucket() -> None:
    ind = _ind_for_buckets(["2020-05-31", "2020-06-30"])
    with pytest.raises(KeyError):
        ind.bucket_for(pd.Timestamp("2020-05-02"))


# ---------------------------------------------------------------- 축 1 발표 시차


def test_lagged_reference_reaches_the_last_bucket() -> None:
    """발표 시차 때문에 축 1 판정이 통째로 사라지던 결함의 회귀 테스트 (2026-08-25).

    미국 월간 통계는 익월 중순에 나온다. 8월에 스캔하면 참조의 마지막 관측은 6~7월이다.
    `reindex(me)` 만 하면 마지막 버킷이 NaN 이 되고, 축 1 이 "데이터 있음" 인데도 판정
    불가가 된다 — 실제로 데이터가 있는 27개 테마 **전부**가 그 상태였다.
    """
    import pandas as pd

    from msa.l1.blocks import PHYSICAL_STALE_TOL_MONTHS, _ref_lag_months, _to_panel

    me = pd.date_range("2026-01-31", "2026-08-31", freq="ME")
    # 참조는 6월까지만 있다 (= 2개월 시차)
    ref = pd.Series(
        range(6), index=pd.date_range("2026-01-31", "2026-06-30", freq="ME"), dtype=float
    )

    got = _to_panel(ref, me)
    assert got.notna().all(), "시차만큼 앞으로 끌어오지 못하면 마지막 버킷이 비고 축 1 이 죽는다"
    assert got.loc["2026-08-31"] == ref.iloc[-1]

    lag = _ref_lag_months(ref, me)
    assert lag.loc["2026-06-30"] == 0.0
    assert 1.5 <= lag.loc["2026-08-31"] <= 2.5  # 약 2개월

    # 한도를 넘으면 채우지 않는다 — 무한정 끌어오면 폐기된 시리즈가 살아 있어 보인다
    dead = pd.Series([1.0], index=pd.DatetimeIndex(["2026-01-31"]))  # 7개월 전에서 멈춘 시리즈
    stale = _to_panel(dead, me)
    assert stale.loc["2026-08-31"] != stale.loc["2026-08-31"]  # NaN
    filled = int(stale.notna().sum())
    assert filled == PHYSICAL_STALE_TOL_MONTHS + 1  # 관측 당월 + 한도 개월
