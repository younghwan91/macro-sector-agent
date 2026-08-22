"""L1 백테스트(M3.5) 합성 데이터 검정.

look-ahead 없음 · IC · 스프레드 · 부트스트랩 · DSR/PBO · 시도 수. 수치의 "좋음" 을 검사하는
테스트는 없다. 검사하는 것은 **정의대로 계산되는가**와 **제외가 세어지는가**다.
`_ref_*` 는 2026-08-23 벡터화 전의 구 구현이며 새 구현과 같은 값을 내야 한다.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from _synth_l1 import panel_from_returns, random_panel, theme_record, write_themes
from msa.l1.backtest import (
    BOOT_BLOCK,
    HORIZONS,
    MIN_THEMES_CLASS,
    MIN_THEMES_XS,
    PBO_HORIZON,
    SCORED_INDICATORS,
    VARIANTS,
    Forward,
    _boot_index,
    _spearman_np,
    ar1,
    block_bootstrap_mean,
    breadth_cross_precision,
    breadth_lead_episodes,
    count_trials,
    dsr_of_series,
    effective_n,
    forward_excess,
    indicator_ic_series,
    pbo_of_spreads,
    rank_ic_series,
    run_backtest_frames,
    small_sample_history,
    spearman,
    spread_series,
    summarize_breadth_lead,
    summarize_ic,
    verdict,
    write_outputs,
)
from msa.l1.blocks import Indicators
from msa.l1.panel import ThemePanel
from msa.l1.scoreboard import BLOCKS, ORIENTATION
from msa.themes import CYCLE_CLASSES, ThemeSet
from msa.vendor.overfitting import probability_of_backtest_overfitting

# ---------------------------------------------------------------- 합성 재료

N_THEMES = 30
THEMES = [f"t{i:02d}" for i in range(N_THEMES)]
# 앞 16개는 두 클래스에 8개씩 (클래스 내 IC 계산 가능), 나머지 14개는 6개 클래스에 2~3개씩
# (MIN_THEMES_CLASS 미만 → NaN 이되 n 은 기록되는지 검사)
CLASSES = ["commodity_supply"] * 8 + ["inventory"] * 8
CLASSES += [CYCLE_CLASSES[2 + i % 6] for i in range(N_THEMES - 16)]


@pytest.fixture(scope="module")
def themes(tmp_path_factory: pytest.TempPathFactory) -> ThemeSet:
    recs = [
        theme_record(tid, cc, i) for i, (tid, cc) in enumerate(zip(THEMES, CLASSES, strict=True))
    ]
    return write_themes(tmp_path_factory.mktemp("themes"), recs)


@pytest.fixture(scope="module")
def panel() -> ThemePanel:
    return random_panel(THEMES)


@pytest.fixture(scope="module")
def fwd3(panel: ThemePanel) -> Forward:
    return forward_excess(panel, (3,))


def _days(start: str, end: str) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def _month_ends(panel: ThemePanel) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(panel.index_level("ew").resample("ME").last().index)


# ---------------------------------------------------------------- 전진 수익률 — look-ahead 없음


def test_forward_excess_uses_only_future_prices_and_matches_definition(
    panel: ThemePanel, fwd3: Forward
) -> None:
    fwd = forward_excess(panel, (1, 3))
    Pm = panel.index_level("ew").resample("ME").last()
    Sm = panel.spy["close"].resample("ME").last()
    t = Pm.index[10]
    t3 = Pm.index[13]
    for th in THEMES[:5]:
        expect = (Pm.at[t3, th] / Pm.at[t, th] - 1.0) - (Sm.at[t3] / Sm.at[t] - 1.0)
        assert fwd.excess[3].at[t, th] == pytest.approx(expect)
    pd.testing.assert_frame_equal(fwd.excess[3], fwd3.excess[3])
    # 끝점이 자료 끝을 넘는 월은 NaN 이고 그 건수가 세어진다
    assert fwd.excess[3].iloc[-3:].isna().all().all()
    assert fwd.exclusions["h3"]["dropped_incomplete_endpoint"] == 0  # 12/31 로 끝나 완결
    assert fwd.exclusions["h3"]["kept"] == (len(Pm) - 3) * N_THEMES


def test_forward_excess_perturbing_past_does_not_change_forward() -> None:
    """t 이전 가격을 바꿔도 t 의 전진 수익률은 그대로다 — t 이후만 쓴다는 직접 검사."""
    rng = np.random.default_rng(1)
    days = _days("2012-01-02", "2016-12-30")
    ret = pd.DataFrame(rng.normal(0, 0.01, (len(days), N_THEMES)), index=days, columns=THEMES)
    spy = pd.Series(rng.normal(0, 0.008, len(days)), index=days)
    f1 = forward_excess(panel_from_returns(ret, spy), (3,))
    t = _month_ends(panel_from_returns(ret, spy))[20]
    ret2 = ret.copy()
    ret2.loc[: t - pd.Timedelta(days=40)] *= 3.0  # t 한참 전의 수익률을 흔든다
    f2 = forward_excess(panel_from_returns(ret2, spy), (3,))
    pd.testing.assert_series_equal(f1.excess[3].loc[t], f2.excess[3].loc[t])


def test_forward_excess_partial_last_month_is_not_an_endpoint() -> None:
    panel = random_panel(THEMES, end="2020-12-15")  # 12월이 부분 월
    fwd = forward_excess(panel, (1,))
    assert str(fwd.last_complete.date()) == "2020-11-30"
    # 11월 말 기준 1M 전진(끝점 12/31 라벨)은 실제로 12/15 까지뿐 → 제외
    assert np.isnan(fwd.excess[1].loc["2020-11-30"]).all()
    assert fwd.exclusions["h1"]["dropped_incomplete_endpoint"] == N_THEMES


def test_forward_excess_inactive_window_is_dropped_and_counted() -> None:
    rng = np.random.default_rng(2)
    days = _days("2012-01-02", "2015-12-31")
    ret = pd.DataFrame(rng.normal(0, 0.01, (len(days), N_THEMES)), index=days, columns=THEMES)
    spy = pd.Series(rng.normal(0, 0.008, len(days)), index=days)
    # t00 은 2014-03 한 달 동안 구성원이 없다 (수익률 NaN → 지수 정체)
    ret.loc["2014-03-01":"2014-03-31", "t00"] = np.nan
    fwd = forward_excess(panel_from_returns(ret, spy), (1, 3))
    assert np.isnan(fwd.excess[1].at[pd.Timestamp("2014-02-28"), "t00"])
    assert np.isnan(fwd.excess[3].at[pd.Timestamp("2013-12-31"), "t00"])
    assert not np.isnan(fwd.excess[3].at[pd.Timestamp("2013-12-31"), "t01"])
    assert fwd.exclusions["h1"]["dropped_inactive_window"] == 1
    assert fwd.exclusions["h3"]["dropped_inactive_window"] == 3


# ---------------------------------------------------------------- IC


def test_spearman_known_values() -> None:
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=list("abcde"))
    assert spearman(x, x * 10)[0] == pytest.approx(1.0)
    assert spearman(x, -x)[0] == pytest.approx(-1.0)
    rho, n = spearman(x, x.where(x < 3))
    assert n == 2 and np.isnan(rho)
    # 짝이 맞는 항목만 — 인덱스가 어긋나도 이름으로 맞춘다
    y = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0], index=list("edcba"))
    assert spearman(x, y)[0] == pytest.approx(1.0)


def _scores_from(fwd: pd.DataFrame, *, noise: float = 0.0, seed: int = 0) -> pd.DataFrame:
    """전진 수익률을 그대로 스코어로 심는다 (IC = 1). 블록 열은 잡음."""
    rng = np.random.default_rng(seed)
    long = fwd.stack(future_stack=True).rename("score").to_frame()
    long.index.names = ["date", "theme"]
    long["score"] = long["score"] + noise * rng.normal(size=len(long))
    for b in BLOCKS:
        long[b] = rng.normal(size=len(long))
        long[f"{b}_pct"] = long[b].groupby(level="date").rank(pct=True)
    long["cycle_class"] = [CLASSES[THEMES.index(t)] for t in long.index.get_level_values("theme")]
    return long.sort_index()


def _ref_rank_ic_series(
    scores: pd.DataFrame,
    fwd: Forward,
    classes: pd.Series,
    *,
    variants: tuple[str, ...] = VARIANTS,
    min_n: int = MIN_THEMES_XS,
    min_n_class: int = MIN_THEMES_CLASS,
) -> pd.DataFrame:
    """구 구현 — (월말 × 변형 × 파티션) 마다 `_spearman_np`."""
    rows: list[dict[str, Any]] = []
    wide = {v: scores[v].unstack("theme").sort_index() for v in variants}
    themes = list(wide[variants[0]].columns)
    dates = wide[variants[0]].index
    col_of = {t: j for j, t in enumerate(themes)}
    cls_idx = {
        c: np.array([col_of[t] for t in classes.index[classes == c] if t in col_of], dtype=int)
        for c in CYCLE_CLASSES
    }
    X = {v: wide[v].reindex(index=dates, columns=themes).to_numpy(dtype=float) for v in variants}
    for h, ex in fwd.excess.items():
        Y = ex.reindex(index=dates, columns=themes).to_numpy(dtype=float)
        for i, d in enumerate(dates):
            y = Y[i]
            if np.isnan(y).all():
                continue
            for v in variants:
                x = X[v][i]
                ic, n = _spearman_np(x, y)
                rows.append(
                    {
                        "date": d,
                        "variant": v,
                        "horizon": h,
                        "partition": "all",
                        "ic": ic if n >= min_n else float("nan"),
                        "n": n,
                    }
                )
                for c, idx in cls_idx.items():
                    ic_c, n_c = _spearman_np(x[idx], y[idx]) if len(idx) else (float("nan"), 0)
                    rows.append(
                        {
                            "date": d,
                            "variant": v,
                            "horizon": h,
                            "partition": c,
                            "ic": ic_c if n_c >= min_n_class else float("nan"),
                            "n": n_c,
                        }
                    )
    out = pd.DataFrame(rows)
    return out.sort_values(["horizon", "date"], kind="stable").reset_index(drop=True)


def _ref_indicator_ic_series(
    ind: Indicators, fwd: Forward, *, indicators: tuple[str, ...], min_n: int = MIN_THEMES_XS
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for i in indicators:
        if i not in ind.monthly.columns:
            continue
        w = ind.wide(i).astype(float) * ORIENTATION[i]
        for h, ex in fwd.excess.items():
            dates = w.index.intersection(ex.index)
            themes = w.columns.intersection(ex.columns)
            X = w.reindex(index=dates, columns=themes).to_numpy(dtype=float)
            Y = ex.reindex(index=dates, columns=themes).to_numpy(dtype=float)
            for k, d in enumerate(dates):
                ic, n = _spearman_np(X[k], Y[k])
                rows.append(
                    {
                        "date": d,
                        "indicator": i,
                        "horizon": h,
                        "ic": ic if n >= min_n else float("nan"),
                        "n": n,
                    }
                )
    return pd.DataFrame(rows)


def test_rank_ic_is_one_when_score_equals_forward_and_counts_thresholds(fwd3: Forward) -> None:
    scores = _scores_from(fwd3.excess[3])
    classes = pd.Series(CLASSES, index=THEMES)
    ic = rank_ic_series(scores, fwd3, classes, variants=("score",))
    allp = ic[ic["partition"] == "all"].dropna(subset=["ic"])
    assert (allp["ic"] > 0.999).all()
    assert (allp["n"] == N_THEMES).all()
    # 클래스 파티션: n < MIN_THEMES_CLASS 인 클래스는 NaN 이되 n 은 기록
    small = [c for c in CYCLE_CLASSES if CLASSES.count(c) < MIN_THEMES_CLASS]
    big = [c for c in CYCLE_CLASSES if CLASSES.count(c) >= MIN_THEMES_CLASS]
    assert small and big
    live = set(allp["date"])  # 전진 수익률이 있는 달만
    s = ic[ic["partition"].isin(small) & ic["date"].isin(live)]
    assert s["ic"].isna().all() and (s["n"] > 0).all()
    b = ic[ic["partition"].isin(big)].dropna(subset=["ic"])
    assert (b["ic"] > 0.999).all()


def test_rank_ic_below_min_themes_is_nan_but_month_is_kept(fwd3: Forward) -> None:
    ex = fwd3.excess[3].copy()
    d = ex.index[5]
    ex.loc[d, THEMES[MIN_THEMES_XS - 1 :]] = np.nan  # 그 달만 19개 테마
    f2 = Forward(excess={3: ex}, last_complete=fwd3.last_complete, exclusions=fwd3.exclusions)
    scores = _scores_from(fwd3.excess[3])
    ic = rank_ic_series(scores, f2, pd.Series(CLASSES, index=THEMES), variants=("score",))
    row = ic[(ic["date"] == d) & (ic["partition"] == "all")].iloc[0]
    assert np.isnan(row["ic"]) and row["n"] == MIN_THEMES_XS - 1
    summ = summarize_ic(ic)
    r = summ[(summ["window"] == "full") & (summ["partition"] == "all")].iloc[0]
    assert r["n_months_dropped"] >= 1
    assert list(summ.columns[:4]) == ["window", "horizon", "variant", "partition"]


def test_rank_ic_series_matches_scalar_loop(panel: ThemePanel) -> None:
    """벡터화 IC == 행마다 `_spearman_np` (비트 단위). 결측·동률·소표본 클래스 포함."""
    fwd = forward_excess(panel, (1, 3, 6))
    rng = np.random.default_rng(11)
    scores = _scores_from(fwd.excess[3], noise=1.0, seed=11)
    # 결측과 동률을 섞는다
    arr = scores["score"].to_numpy().copy()
    arr[rng.uniform(size=len(arr)) < 0.15] = np.nan
    arr = np.round(arr, 1)
    scores["score"] = arr
    scores.loc[scores.index.get_level_values("theme") == "t05", "A"] = np.nan
    classes = pd.Series(CLASSES, index=THEMES)
    got = rank_ic_series(scores, fwd, classes, horizons=(3, 6))
    f36 = Forward(
        excess={h: fwd.excess[h] for h in (3, 6)},
        last_complete=fwd.last_complete,
        exclusions=fwd.exclusions,
    )
    ref = _ref_rank_ic_series(scores, f36, classes)
    pd.testing.assert_frame_equal(got, ref, check_exact=True)
    assert set(got["horizon"]) == {3, 6}  # horizons 인자가 1M 을 뺐다


def test_indicator_ic_series_matches_scalar_loop(panel: ThemePanel) -> None:
    fwd = forward_excess(panel, (3, 12))
    me = fwd.excess[3].index
    rng = np.random.default_rng(12)
    cols = {i: rng.normal(size=(len(me), N_THEMES)) for i in SCORED_INDICATORS[:5]}
    frames = {}
    for i, v in cols.items():
        v[rng.uniform(size=v.shape) < 0.1] = np.nan
        frames[i] = pd.DataFrame(v, index=me, columns=THEMES).stack(future_stack=True)
    long = pd.concat(frames, axis=1)
    long.index.names = ["date", "theme"]
    ind = Indicators(monthly=long.sort_index())
    got = indicator_ic_series(ind, fwd, indicators=SCORED_INDICATORS[:6])
    ref = _ref_indicator_ic_series(ind, fwd, indicators=SCORED_INDICATORS[:6])
    pd.testing.assert_frame_equal(got, ref, check_exact=True)


# ---------------------------------------------------------------- 스프레드


def test_spread_top_minus_bottom_and_small_sample_exclusion(fwd3: Forward) -> None:
    ex = fwd3.excess[3]
    scores = _scores_from(ex)
    small = pd.DataFrame(False, index=ex.index, columns=ex.columns)
    sp = spread_series(scores, fwd3, small, variants=("score",), k=8)
    d = ex.index[3]
    row = sp[sp["date"] == d].iloc[0]
    srt = ex.loc[d].sort_values(ascending=False)
    assert row["spread"] == pytest.approx(srt.iloc[:8].mean() - srt.iloc[-8:].mean())
    assert row["n_universe"] == N_THEMES and row["n_small_excluded"] == 0
    # 상위 1개를 소표본으로 표시하면 우주에서 빠진다
    small.loc[d, srt.index[0]] = True
    sp2 = spread_series(scores, fwd3, small, variants=("score",), k=8)
    row2 = sp2[sp2["date"] == d].iloc[0]
    assert row2["n_small_excluded"] == 1 and row2["n_universe"] == N_THEMES - 1
    assert row2["spread"] == pytest.approx(srt.iloc[1:9].mean() - srt.iloc[-8:].mean())


def test_small_sample_history_uses_month_end_n_listed(themes: ThemeSet) -> None:
    rng = np.random.default_rng(3)
    days = _days("2012-01-02", "2012-12-31")
    ret = pd.DataFrame(rng.normal(0, 0.01, (len(days), N_THEMES)), index=days, columns=THEMES)
    nl = pd.DataFrame(20, index=days, columns=THEMES)
    nl.loc["2012-06-01":"2012-06-30", "t03"] = 3  # min_constituents 5 미만
    panel = panel_from_returns(ret, pd.Series(0.0, index=days), n_listed=nl)
    small = small_sample_history(panel, themes)
    assert bool(small.at[pd.Timestamp("2012-06-30"), "t03"])
    assert not bool(small.at[pd.Timestamp("2012-07-31"), "t03"])
    assert not small.drop(columns="t03").any().any()


# ---------------------------------------------------------------- 유효 표본·부트스트랩


def test_block_bootstrap_constant_and_iid_width() -> None:
    c = pd.Series(0.3, index=range(100))
    r = block_bootstrap_mean(c)
    assert r["ci_lo"] == pytest.approx(0.3) and r["ci_hi"] == pytest.approx(0.3)
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(0.5, 1.0, 240))
    r = block_bootstrap_mean(x)
    assert r["ci_lo"] < x.mean() < r["ci_hi"]
    half = (r["ci_hi"] - r["ci_lo"]) / 2
    assert 0.08 < half < 0.20  # iid 이론값 1.96/√240 ≈ 0.127 근방 (블록이라 다소 넓다)
    assert r["block_used"] == BOOT_BLOCK


def test_block_bootstrap_is_wider_for_autocorrelated_series() -> None:
    rng = np.random.default_rng(1)
    e = rng.normal(size=360)
    ar = np.zeros(360)
    for i in range(1, 360):
        ar[i] = 0.8 * ar[i - 1] + e[i]
    wide = block_bootstrap_mean(pd.Series(ar))
    narrow = block_bootstrap_mean(pd.Series(rng.permutation(ar)))
    assert (wide["ci_hi"] - wide["ci_lo"]) > 1.5 * (narrow["ci_hi"] - narrow["ci_lo"])


def test_boot_index_is_cached_and_identical_to_fresh_draw() -> None:
    """`(n, L, n_boot, seed)` 별 재표집 인덱스는 매번 새로 뽑은 것과 같은 난수열이다."""
    idx = _boot_index(175, 12, 2000, 0)
    rng = np.random.default_rng(0)
    starts = rng.integers(0, 175 - 12 + 1, size=(2000, int(np.ceil(175 / 12))))
    fresh = (starts[:, :, None] + np.arange(12)[None, None, :]).reshape(2000, -1)[:, :175]
    assert np.array_equal(idx, fresh)
    assert _boot_index(175, 12, 2000, 0) is idx  # 캐시
    assert not idx.flags.writeable


def test_ar1_and_effective_n() -> None:
    rng = np.random.default_rng(2)
    iid = pd.Series(rng.normal(size=2000))
    assert abs(ar1(iid)) < 0.06
    assert effective_n(100, 0.0) == pytest.approx(100.0)
    assert effective_n(100, 0.5) == pytest.approx(100 / 3)
    assert effective_n(100, 0.999) >= 1.0
    assert np.isnan(effective_n(100, float("nan")))


# ---------------------------------------------------------------- 시도 수 · DSR · PBO


def test_count_trials_rule_is_explicit() -> None:
    t = count_trials(29)
    assert t["variants"] == len(VARIANTS) == 7
    assert t["horizons"] == len(HORIZONS) == 3
    assert t["classes"] == 8 and t["windows"] == 2
    per = 7 * 3 * (2 + 8) + 7 * 1 + 29 * 3
    assert t["per_window"] == per == 304
    assert t["total"] == 2 * per == 608
    assert t["declared_only"] == 1
    assert len(SCORED_INDICATORS) == 29


def test_dsr_declared_vs_many_trials() -> None:
    rng = np.random.default_rng(0)
    strong = pd.Series(rng.normal(0.5, 1.0, 200))  # 기간 SR 0.5
    d1 = dsr_of_series(strong, 1, horizon=1)
    assert d1["dsr_overlapping"] > 0.99 and d1["dsr_nonoverlapping"] > 0.99
    noise = pd.Series(rng.normal(0.0, 1.0, 200))
    dn = dsr_of_series(noise, 608, horizon=1)
    assert dn["dsr_overlapping"] < 0.5
    d3 = dsr_of_series(strong, 1, horizon=3)
    assert d3["n_nonoverlapping"] == 67  # 200 // 3 올림 (offset 0)


def _spread_frame(n: int = 240, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2000-01-31", periods=n, freq="ME")
    rows = []
    for v in VARIANTS:
        x = rng.normal(0.0, 1.0, n)
        for d, val in zip(dates, x, strict=True):
            rows.append({"date": d, "variant": v, "horizon": 1, "spread": val})
    return pd.DataFrame(rows)


def test_pbo_noise_is_high_and_real_signal_is_low() -> None:
    rng = np.random.default_rng(0)
    n = 240
    sp = _spread_frame(n)
    r = pbo_of_spreads(sp, window="full", horizon=1, max_splits=252)
    assert 0.0 <= r["pbo"] <= 1.0 and r["n_splits"] == 252
    assert r["pbo"] > 0.25  # 잡음뿐이면 IS 최고는 OOS 에서 흔히 중앙값 아래
    # score 열에 강한 진짜 신호를 심으면 PBO 가 낮아진다
    sp.loc[sp["variant"] == "score", "spread"] = rng.normal(1.0, 1.0, n)
    r2 = pbo_of_spreads(sp, window="full", horizon=1, max_splits=252)
    assert r2["pbo"] < 0.1


def _ref_pbo(trial_returns: pd.DataFrame, n_blocks: int, max_splits: int, seed: int = 0) -> Any:
    """벤더링 원본의 CSCV 루프 (조합마다 IS/OOS 행렬을 잘라 Sharpe)."""
    m = trial_returns.dropna(how="all").fillna(0.0).to_numpy()
    t_obs, n_cfg = m.shape
    blocks = np.array_split(np.arange(t_obs), n_blocks)
    all_combos = list(combinations(range(n_blocks), n_blocks // 2))
    if len(all_combos) > max_splits:
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(all_combos), size=max_splits, replace=False)
        all_combos = [all_combos[i] for i in idx]

    def _sharpe(block: np.ndarray) -> np.ndarray:
        mu = block.mean(axis=0)
        sd = block.std(axis=0, ddof=1)
        return np.asarray(np.divide(mu, sd, out=np.zeros_like(mu), where=sd > 0))

    logits, oos_best = [], []
    for combo in all_combos:
        is_rows = np.concatenate([blocks[b] for b in combo])
        oos_rows = np.concatenate([blocks[b] for b in range(n_blocks) if b not in combo])
        best = int(np.argmax(_sharpe(m[is_rows])))
        oos_sr = _sharpe(m[oos_rows])
        omega = (stats.rankdata(oos_sr)[best]) / (n_cfg + 1.0)
        logits.append(np.log(omega / (1.0 - omega)))
        oos_best.append(oos_sr[best])
    return np.asarray(logits), np.asarray(oos_best)


def test_pbo_vectorized_matches_original_loop() -> None:
    for seed, n in ((0, 240), (1, 100), (2, 400)):
        sp = _spread_frame(n, seed)
        mat = sp.pivot(index="date", columns="variant", values="spread")[list(VARIANTS)]
        mat.iloc[3, 2] = np.nan  # 결측은 0 으로 (원본 규약)
        res = probability_of_backtest_overfitting(mat, n_blocks=10, max_splits=252)
        logits, oos_best = _ref_pbo(mat, 10, 252)
        assert res.n_splits == len(logits) == 252
        assert res.pbo == pytest.approx(float((logits < 0).mean()), abs=1e-12)
        np.testing.assert_allclose(res.logits, logits, rtol=0, atol=1e-10)
        np.testing.assert_allclose(res.oos_sharpe_of_is_best, oos_best, rtol=0, atol=1e-12)


def test_pbo_too_short_is_reported_not_silent() -> None:
    dates = pd.date_range("2000-01-31", periods=20, freq="ME")
    rows = [
        {"date": d, "variant": v, "horizon": 1, "spread": 0.1 * i}
        for i, d in enumerate(dates)
        for v in VARIANTS
    ]
    r = pbo_of_spreads(pd.DataFrame(rows), window="full", horizon=1)
    assert np.isnan(r["pbo"]) and "note" in r


# ---------------------------------------------------------------- breadth_lead 실측


def _ind_from(above: pd.DataFrame, breadth: pd.DataFrame) -> Indicators:
    long = pd.concat(
        {
            "above_200": above.stack(future_stack=True),
            "breadth_200": breadth.stack(future_stack=True),
        },
        axis=1,
    )
    long.index.names = ["date", "theme"]
    return Indicators(monthly=long.sort_index())


def test_breadth_lead_episodes_lead_lag_none() -> None:
    me = pd.date_range("2015-01-31", periods=24, freq="ME")
    ab = pd.DataFrame(0.0, index=me, columns=["lead", "lag", "none", "same"])
    br = pd.DataFrame(0.2, index=me, columns=ab.columns)
    # lead: 브레드스 5월에 ≥0.5, 지수 8월에 전환 → lead 3
    br.loc[me[4] :, "lead"] = 0.7
    ab.loc[me[7] :, "lead"] = 1.0
    # lag: 지수 4월 전환, 브레드스 6월 → −2
    ab.loc[me[3] :, "lag"] = 1.0
    br.loc[me[5] :, "lag"] = 0.7
    # none: 지수 10월 전환, 브레드스는 끝까지 0.2
    ab.loc[me[9] :, "none"] = 1.0
    # same: 둘 다 12월
    ab.loc[me[11] :, "same"] = 1.0
    br.loc[me[11] :, "same"] = 0.9
    ind = _ind_from(ab, br)
    classes = pd.Series("inventory", index=ab.columns)
    ep = breadth_lead_episodes(ind, classes)
    by = ep.set_index("theme")
    assert by.loc["lead", "lead"] == 3 and by.loc["lead", "kind"] == "lead"
    assert by.loc["lag", "lead"] == -2 and by.loc["lag", "kind"] == "lag"
    assert np.isnan(by.loc["none", "lead"]) and by.loc["none", "kind"] == "none"
    assert by.loc["same", "lead"] == 0 and by.loc["same", "kind"] == "same"
    summ = summarize_breadth_lead(ep).set_index("group")
    a = summ.loc["all"]
    assert a["n_episodes"] == 4 and a["n_lead"] == 1 and a["n_lag"] == 1 and a["n_none"] == 1
    assert a["median_lead_given_lead"] == 3
    prec = breadth_cross_precision(ind)
    # 브레드스 전환 3건 (lead·lag·same): lead 는 12M 안 추종, lag 는 이미 위, same 도 이미 위
    assert prec["n_breadth_crosses"] == 3
    assert prec["index_already_above"] == 2 and prec["index_follows_within_search"] == 1


def test_breadth_lead_episode_with_breadth_nan_is_none() -> None:
    me = pd.date_range("2015-01-31", periods=12, freq="ME")
    ab = pd.DataFrame(0.0, index=me, columns=["x"])
    br = pd.DataFrame(0.2, index=me, columns=["x"])
    ab.loc[me[5] :, "x"] = 1.0
    br.loc[me[5], "x"] = np.nan  # 전환 달에 브레드스 결측
    ep = breadth_lead_episodes(_ind_from(ab, br), pd.Series("inventory", index=["x"]))
    assert len(ep) == 1 and ep["kind"].iloc[0] == "none" and np.isnan(ep["lead"].iloc[0])


def test_breadth_lead_is_uncapped_unlike_indicator() -> None:
    me = pd.date_range("2010-01-31", periods=40, freq="ME")
    ab = pd.DataFrame(0.0, index=me, columns=["x"])
    br = pd.DataFrame(0.1, index=me, columns=["x"])
    br.loc[me[2] :, "x"] = 0.8
    ab.loc[me[30] :, "x"] = 1.0
    ep = breadth_lead_episodes(_ind_from(ab, br), pd.Series("inventory", index=["x"]))
    assert ep["lead"].iloc[0] == 28  # 12 로 자르지 않는다


# ---------------------------------------------------------------- 끝까지 (합성)


def test_run_backtest_frames_and_write_outputs(themes: ThemeSet, tmp_path: Path) -> None:
    panel = random_panel(THEMES, seed=5)
    fwd = forward_excess(panel, (12,))
    scores = _scores_from(fwd.excess[12], noise=0.5, seed=5)  # 12M 에 강한 신호
    me = scores.index.get_level_values("date").unique()
    ab = pd.DataFrame(0.0, index=me, columns=THEMES)
    br = pd.DataFrame(0.3, index=me, columns=THEMES)
    ab.iloc[20:] = 1.0
    br.iloc[17:] = 0.6
    ind = _ind_from(ab, br)
    res = run_backtest_frames(
        panel, ind, themes, scores=scores, with_indicator_ic=False, pbo_max_splits=252
    )
    assert set(res.ic["partition"].unique()) >= {"all", *CYCLE_CLASSES}
    assert set(res.ic["horizon"].unique()) == set(HORIZONS)  # 1M 은 IC 에 없다
    assert set(res.spread["horizon"].unique()) == {PBO_HORIZON, *HORIZONS}
    g = res.verdict
    assert g["gate"] in ("pass", "fail")
    assert g["horizon"] == 12 and g["window"] == "primary"
    # 심은 신호: 12M 복합 IC 는 뚜렷이 양수, CI 하한 > 0 → pass
    assert g["mean_ic"] > 0.15 and g["ci"][0] > 0
    assert g["gate"] == "pass"
    # 합성 지표는 above_200·breadth_200 두 개만 있다 → 지표 단독 IC 칸 2개 × 3 × 2 창
    assert res.overfitting["trials"]["total"] == count_trials(2)["total"]
    assert all("n_trials_declared" not in d for d in res.overfitting["dsr"])
    out = tmp_path / "bt"
    write_outputs(res, out)
    for f in (
        "ic_timeseries.csv",
        "ic_summary.csv",
        "spread.csv",
        "spread_summary.csv",
        "breadth_lead.csv",
        "breadth_lead_summary.csv",
        "overfitting.json",
        "verdict.json",
        "exclusions.json",
        "report.txt",
    ):
        assert (out / f).exists(), f
    txt = (out / "report.txt").read_text()
    assert "판정: PASS" in txt and "CAGR" not in txt and "Sharpe" not in txt
    # JSON 은 numpy 스칼라 없이 평문이어야 한다 (숫자는 숫자로)
    import json

    ov = json.loads((out / "overfitting.json").read_text(encoding="utf-8"))
    assert isinstance(ov["pbo"][0]["n_splits"], int)
    assert isinstance(ov["breadth_cross_precision"]["n_breadth_crosses"], int)


def test_verdict_fails_when_ci_includes_zero(themes: ThemeSet) -> None:
    panel = random_panel(THEMES, seed=7)
    fwd = forward_excess(panel, (12,))
    rng = np.random.default_rng(7)
    scores = _scores_from(fwd.excess[12] * 0.0 + rng.normal(size=fwd.excess[12].shape), seed=7)
    me = scores.index.get_level_values("date").unique()
    ind = _ind_from(
        pd.DataFrame(0.0, index=me, columns=THEMES), pd.DataFrame(0.3, index=me, columns=THEMES)
    )
    res = run_backtest_frames(
        panel, ind, themes, scores=scores, with_indicator_ic=False, pbo_max_splits=252
    )
    assert res.verdict["gate"] == "fail"
    assert res.verdict["ci"][0] <= 0 <= res.verdict["ci"][1]


def test_verdict_undetermined_when_gate_cell_missing() -> None:
    empty = pd.DataFrame(columns=["window", "horizon", "variant", "partition"])
    v = verdict(empty, {"dsr": [], "pbo": []})
    assert v["gate"] == "undetermined"


# ---------------------------------------------------------------- 실데이터 스모크


@pytest.mark.data
def test_backtest_smoke_from_caches() -> None:
    """캐시가 있으면 실제 백테스트를 한 번 돈다 (쓰지 않음). 수치는 검사하지 않는다."""
    from msa.config import paths
    from msa.l1.backtest import run_backtest

    if not paths().duckdb.exists():
        pytest.skip("DuckDB 스토어 없음")
    res = run_backtest(write=False)
    assert res.verdict["gate"] in ("pass", "fail")
    assert res.overfitting["trials"]["total"] >= 600
    assert (res.ic_summary["n_months"] > 0).any()


@pytest.mark.data
def test_rank_ic_matches_scalar_loop_on_real_cache() -> None:
    """실제 지표 캐시 → 스코어보드 이력 → IC: 벡터화와 행별 루프가 비트 단위로 같다 (12M)."""
    from msa.config import paths
    from msa.l1.panel import load_cached_panel
    from msa.l1.scoreboard import scoreboard_history
    from msa.themes import load_themes

    cache = paths().cache
    inds = sorted(cache.glob("l1_indicators_*.parquet"))
    if not inds:
        pytest.skip("지표 캐시 없음")
    themes_all = load_themes()
    panel = load_cached_panel()
    ind = Indicators(monthly=pd.read_parquet(inds[-1]))
    scores = scoreboard_history(ind, themes_all)
    by_id = themes_all.by_id()
    classes = pd.Series(
        {t: by_id[t].cycle_class for t in scores.index.get_level_values("theme").unique()}
    )
    fwd = forward_excess(panel, (12,))
    got = rank_ic_series(scores, fwd, classes)
    ref = _ref_rank_ic_series(scores, fwd, classes)
    pd.testing.assert_frame_equal(got, ref, check_exact=True)
