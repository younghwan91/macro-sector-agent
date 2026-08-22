"""L1 백테스트(M3.5) 합성 데이터 검정.

look-ahead 없음 · IC · 스프레드 · 부트스트랩 · DSR/PBO · 시도 수. 수치의 "좋음" 을 검사하는
테스트는 없다. 검사하는 것은 **정의대로 계산되는가**와 **제외가 세어지는가**다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from msa.l1.backtest import (
    BOOT_BLOCK,
    HORIZONS,
    MIN_THEMES_CLASS,
    MIN_THEMES_XS,
    PBO_HORIZON,
    SCORED_INDICATORS,
    VARIANTS,
    Forward,
    ar1,
    block_bootstrap_mean,
    breadth_cross_precision,
    breadth_lead_episodes,
    count_trials,
    dsr_of_series,
    effective_n,
    forward_excess,
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
from msa.l1.panel import PANEL_COLUMNS, ThemePanel, panel_from_frames
from msa.l1.scoreboard import BLOCKS
from msa.themes import CYCLE_CLASSES, ThemeSet, load_themes

# ---------------------------------------------------------------- 합성 재료

N_THEMES = 30
THEMES = [f"t{i:02d}" for i in range(N_THEMES)]
# 앞 16개는 두 클래스에 8개씩 (클래스 내 IC 계산 가능), 나머지 14개는 6개 클래스에 2~3개씩
# (MIN_THEMES_CLASS 미만 → NaN 이되 n 은 기록되는지 검사)
CLASSES = ["commodity_supply"] * 8 + ["inventory"] * 8
CLASSES += [CYCLE_CLASSES[2 + i % 6] for i in range(N_THEMES - 16)]


@pytest.fixture
def themes(tmp_path: Path) -> ThemeSet:
    recs = []
    for i, (tid, cc) in enumerate(zip(THEMES, CLASSES, strict=True)):
        recs.append(
            {
                "id": tid,
                "name_ko": tid,
                "parent_sector": "X",
                "cycle_class": cc,
                "industry_match": [f"Ind{i}"],
                "include_tickers": [],
                "exclude_tickers": [],
                "etf_proxy": None,
                "etf_proxy_alt": [],
                "physical_ref": None,
                "correlation_cluster": None,
                "min_constituents": 5,
            }
        )
    p = tmp_path / "themes.yaml"
    p.write_text(yaml.safe_dump({"schema_version": 1, "defaults": {}, "themes": recs}))
    return load_themes(p)


def _panel(
    daily_ret: pd.DataFrame,
    spy_ret: pd.Series,
    *,
    n_listed: pd.DataFrame | None = None,
) -> ThemePanel:
    """일별 수익률 행렬(date × theme) → 패널. n_ret 은 수익률이 NaN 이면 0."""
    days = daily_ret.index
    r = daily_ret.stack(future_stack=True)
    r.index.names = ["date", "theme"]
    nl = (
        n_listed.stack(future_stack=True).reindex(r.index).astype(int)
        if n_listed is not None
        else pd.Series(20, index=r.index)
    )
    frame = pd.DataFrame(
        {
            "ret_ew": r,
            "ret_cw": r,
            "n_ret": nl.where(r.notna(), 0),
            "n_listed": nl,
            "n_cw": nl,
            "dv": 1e7,
            "mcap_sum": 1e10,
            "n_sma200": nl,
            "n_above200": nl // 2,
            "n_nh6m": 1,
            "n_nl6m": 1,
            "n_capped": 0,
        }
    ).sort_index()
    assert set(PANEL_COLUMNS) <= set(frame.columns)
    spy = pd.DataFrame({"close": 100 * (1 + spy_ret).cumprod(), "dv": 5e10}, index=days)
    return panel_from_frames(frame, spy)


def _days(start: str, end: str) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def _random_panel(seed: int = 0, end: str = "2020-12-31") -> ThemePanel:
    rng = np.random.default_rng(seed)
    days = _days("2012-01-02", end)
    ret = pd.DataFrame(rng.normal(0.0002, 0.01, (len(days), N_THEMES)), index=days, columns=THEMES)
    spy = pd.Series(rng.normal(0.0003, 0.008, len(days)), index=days)
    return _panel(ret, spy)


def _month_ends(panel: ThemePanel) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(panel.index_level("ew").resample("ME").last().index)


# ---------------------------------------------------------------- 전진 수익률 — look-ahead 없음


def test_forward_excess_uses_only_future_prices_and_matches_definition() -> None:
    panel = _random_panel(end="2020-12-31")
    fwd = forward_excess(panel, (1, 3))
    Pm = panel.index_level("ew").resample("ME").last()
    Sm = panel.spy["close"].resample("ME").last()
    t = Pm.index[10]
    t3 = Pm.index[13]
    for th in THEMES[:5]:
        expect = (Pm.at[t3, th] / Pm.at[t, th] - 1.0) - (Sm.at[t3] / Sm.at[t] - 1.0)
        assert fwd.excess[3].at[t, th] == pytest.approx(expect)
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
    f1 = forward_excess(_panel(ret, spy), (3,))
    t = _month_ends(_panel(ret, spy))[20]
    ret2 = ret.copy()
    ret2.loc[: t - pd.Timedelta(days=40)] *= 3.0  # t 한참 전의 수익률을 흔든다
    f2 = forward_excess(_panel(ret2, spy), (3,))
    pd.testing.assert_series_equal(f1.excess[3].loc[t], f2.excess[3].loc[t])


def test_forward_excess_partial_last_month_is_not_an_endpoint() -> None:
    panel = _random_panel(end="2020-12-15")  # 12월이 부분 월
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
    fwd = forward_excess(_panel(ret, spy), (1, 3))
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


def test_rank_ic_is_one_when_score_equals_forward_and_counts_thresholds() -> None:
    panel = _random_panel()
    fwd = forward_excess(panel, (3,))
    scores = _scores_from(fwd.excess[3])
    classes = pd.Series(CLASSES, index=THEMES)
    ic = rank_ic_series(scores, fwd, classes, variants=("score",))
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


def test_rank_ic_below_min_themes_is_nan_but_month_is_kept() -> None:
    panel = _random_panel()
    fwd = forward_excess(panel, (3,))
    ex = fwd.excess[3].copy()
    d = ex.index[5]
    ex.loc[d, THEMES[MIN_THEMES_XS - 1 :]] = np.nan  # 그 달만 19개 테마
    f2 = Forward(
        excess={3: ex},
        theme_ret=fwd.theme_ret,
        spy_ret=fwd.spy_ret,
        month_ends=fwd.month_ends,
        last_complete=fwd.last_complete,
        exclusions=fwd.exclusions,
    )
    scores = _scores_from(fwd.excess[3])
    ic = rank_ic_series(scores, f2, pd.Series(CLASSES, index=THEMES), variants=("score",))
    row = ic[(ic["date"] == d) & (ic["partition"] == "all")].iloc[0]
    assert np.isnan(row["ic"]) and row["n"] == MIN_THEMES_XS - 1
    summ = summarize_ic(ic)
    r = summ[(summ["window"] == "full") & (summ["partition"] == "all")].iloc[0]
    assert r["n_months_dropped"] >= 1


# ---------------------------------------------------------------- 스프레드


def test_spread_top_minus_bottom_and_small_sample_exclusion() -> None:
    panel = _random_panel()
    fwd = forward_excess(panel, (3,))
    ex = fwd.excess[3]
    scores = _scores_from(ex)
    small = pd.DataFrame(False, index=ex.index, columns=ex.columns)
    sp = spread_series(scores, fwd, small, variants=("score",), k=8)
    d = ex.index[3]
    row = sp[sp["date"] == d].iloc[0]
    srt = ex.loc[d].sort_values(ascending=False)
    assert row["spread"] == pytest.approx(srt.iloc[:8].mean() - srt.iloc[-8:].mean())
    assert row["n_universe"] == N_THEMES and row["n_small_excluded"] == 0
    # 상위 1개를 소표본으로 표시하면 우주에서 빠진다
    small.loc[d, srt.index[0]] = True
    sp2 = spread_series(scores, fwd, small, variants=("score",), k=8)
    row2 = sp2[sp2["date"] == d].iloc[0]
    assert row2["n_small_excluded"] == 1 and row2["n_universe"] == N_THEMES - 1
    assert row2["spread"] == pytest.approx(srt.iloc[1:9].mean() - srt.iloc[-8:].mean())


def test_small_sample_history_uses_month_end_n_listed(themes: ThemeSet) -> None:
    rng = np.random.default_rng(3)
    days = _days("2012-01-02", "2012-12-31")
    ret = pd.DataFrame(rng.normal(0, 0.01, (len(days), N_THEMES)), index=days, columns=THEMES)
    nl = pd.DataFrame(20, index=days, columns=THEMES)
    nl.loc["2012-06-01":"2012-06-30", "t03"] = 3  # min_constituents 5 미만
    panel = _panel(ret, pd.Series(0.0, index=days), n_listed=nl)
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


def test_pbo_noise_is_high_and_real_signal_is_low() -> None:
    rng = np.random.default_rng(0)
    n = 240
    dates = pd.date_range("2000-01-31", periods=n, freq="ME")
    rows = []
    for v in VARIANTS:
        x = rng.normal(0.0, 1.0, n)
        for d, val in zip(dates, x, strict=True):
            rows.append({"date": d, "variant": v, "horizon": 1, "spread": val})
    sp = pd.DataFrame(rows)
    r = pbo_of_spreads(sp, window="full", horizon=1, max_splits=252)
    assert 0.0 <= r["pbo"] <= 1.0 and r["n_splits"] == 252
    assert r["pbo"] > 0.25  # 잡음뿐이면 IS 최고는 OOS 에서 흔히 중앙값 아래
    # score 열에 강한 진짜 신호를 심으면 PBO 가 낮아진다
    sp.loc[sp["variant"] == "score", "spread"] = rng.normal(1.0, 1.0, n)
    r2 = pbo_of_spreads(sp, window="full", horizon=1, max_splits=252)
    assert r2["pbo"] < 0.1


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
    panel = _random_panel(seed=5, end="2020-12-31")
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
    assert set(res.spread["horizon"].unique()) == {PBO_HORIZON, *HORIZONS}
    g = res.verdict
    assert g["gate"] in ("pass", "fail")
    assert g["horizon"] == 12 and g["window"] == "primary"
    # 심은 신호: 12M 복합 IC 는 뚜렷이 양수, CI 하한 > 0 → pass
    assert g["mean_ic"] > 0.15 and g["ci"][0] > 0
    assert g["gate"] == "pass"
    # 합성 지표는 above_200·breadth_200 두 개만 있다 → 지표 단독 IC 칸 2개 × 3 × 2 창
    assert res.overfitting["trials"]["total"] == count_trials(2)["total"]
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


def test_verdict_fails_when_ci_includes_zero(themes: ThemeSet) -> None:
    panel = _random_panel(seed=7, end="2020-12-31")
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
