"""L4 백테스트 — `docs/14` §2·§3.4·§4 의 정의가 코드와 같은가. 합성 데이터, 스토어 없음.

`tests/test_l1_structures.py` 와 같은 자리다: 사전 등록 문서를 코드로 옮긴 것이 맞는지만 본다.
성과가 좋은지는 여기서 묻지 않는다 (`CLAUDE.md` §7).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from msa.l1.backtest import (
    BOOT_BLOCK,
    BOOT_N,
    BOOT_SEED,
    GATE_HORIZON,
    HORIZONS,
    PARTITION_ALL,
    PRIMARY_START,
    spearman,
)
from msa.l4 import axes
from msa.l4.backtest import (
    DEATH_ACTIONS,
    GRID_START,
    INDICATORS,
    MIN_MEMBERS_POSSIBLE,
    MIN_STOCKS_XS,
    PANEL_COLUMNS,
    SPREAD_K,
    VARIANT_COLUMN,
    VARIANTS,
    count_trials,
    month_panel,
    run_backtest_frames,
    stock_forward,
    theme_equal_weight,
    theme_month_metrics,
    verdict,
)
from msa.l4.features import FEATURE_COLUMNS, FeatureSet

# ---------------------------------------------------------------- 합성 도구

DATES = pd.date_range("2011-01-31", periods=48, freq="ME")


def _forward(
    close: pd.DataFrame,
    deaths: pd.DataFrame | None = None,
    horizons: tuple[int, ...] = (1, 3, 6, 12),
):
    d = (
        deaths
        if deaths is not None
        else pd.DataFrame(False, index=close.index, columns=close.columns)
    )
    return stock_forward(close, d, horizons, last_complete=pd.Timestamp(close.index[-1]))


def _panel(
    theme: str,
    dates: pd.DatetimeIndex,
    tickers: list[str],
    *,
    rng: np.random.Generator,
    n_excl: int = 0,
    cycle_reasons: bool = False,
) -> pd.DataFrame:
    """(date × ticker) 패널. 앞 `n_excl` 종목이 제외 — 기본 E1, `cycle_reasons` 면 E1~E5 순환."""
    rows: list[dict[str, Any]] = []
    for d in dates:
        for j, tk in enumerate(tickers):
            excluded = j < n_excl
            code = (
                axes.HARD_REASON_CODES[j % len(axes.HARD_REASON_CODES)] if cycle_reasons else "E1"
            )
            rec: dict[str, Any] = {"date": d, "ticker": tk, "eligible": not excluded}
            for c in axes.HARD_REASON_CODES:
                rec[c] = excluded and c == code
            vals = rng.random(4)
            rec["composite"] = np.nan if excluded else float(vals[0])
            rec["s_pct"] = np.nan if excluded else float(vals[1])
            rec["t_pct"] = np.nan if excluded else float(vals[2])
            rec["m_pct"] = np.nan if excluded else float(vals[3])
            rec["composite_partial"] = False
            for ind in INDICATORS:
                rec[ind] = np.nan if excluded else float(rng.random())
            rows.append(rec)
    df = pd.DataFrame(rows)[list(PANEL_COLUMNS)]
    df["theme"] = theme
    return df


def _close(dates: pd.DatetimeIndex, tickers: list[str], rng: np.random.Generator) -> pd.DataFrame:
    steps = 1.0 + rng.normal(0.005, 0.06, size=(len(dates), len(tickers)))
    return pd.DataFrame(100.0 * np.cumprod(steps, axis=0), index=dates, columns=tickers)


# ---------------------------------------------------------------- §2 · §6 선언값


def test_declared_constants_match_preregistration() -> None:
    """docs/14 §2.2·§2.4·§6.2 의 숫자가 코드 상수와 같다."""
    assert MIN_STOCKS_XS == 20  # §2.2 — L1 MIN_THEMES_XS 와 같은 규칙의 같은 숫자
    assert SPREAD_K == 3  # §2.4 상위 3 − 하위 3
    assert tuple(HORIZONS) == (3, 6, 12) and GATE_HORIZON == 12  # §2.4
    assert pd.Timestamp("2011-01-31") == PRIMARY_START  # §2.4 주 창
    assert pd.Timestamp("1998-01-31") == GRID_START  # §2.4 보조 창
    assert VARIANTS == ("rank_score", "S", "T", "M")  # §6.2 변형 4
    assert VARIANT_COLUMN["rank_score"] == "composite"  # docs/06 §6 과 같은 물건
    assert len(INDICATORS) == 15  # §1 Q4 — S 3 + T 6 + M 6
    assert len(axes.S_COMPONENTS) == 3 and len(axes.T_COMPONENTS) == 6
    assert len(axes.M_COMPONENTS) == 6
    assert DEATH_ACTIONS == ("bankruptcyliquidation", "regulatorydelisting")  # §2.5
    assert axes.HARD_REASON_CODES == ("E1", "E2", "E3", "E4", "E5")  # §1 Q3
    assert axes.HARD_REASON_ALPHA == ("E1", "E2", "E3")  # §4.1 — 판정은 이 셋만
    assert (BOOT_BLOCK, BOOT_N, BOOT_SEED) == (12, 2000, 0)  # §2.2 부트스트랩
    assert MIN_MEMBERS_POSSIBLE == MIN_STOCKS_XS


def test_count_trials_matches_docs14_section_6_2() -> None:
    """§6.2 의 식과 458 이라는 값을 그대로 낸다 (선언만 세면 1)."""
    t = count_trials()
    assert (t["variants"], t["horizons"], t["windows"]) == (4, 3, 2)
    assert (t["classes"], t["indicators"], t["filter_reasons"]) == (8, 15, 5)
    assert t["per_window"] == 4 * 3 * 10 + 4 + 15 * 3 + 5 * 3 * 2 == 199
    assert t["windows_total"] == 398
    assert t["sensitivity_d1"] == 5 * 3 * 2 * 2 == 60
    assert t["total"] == 458
    assert t["declared_only"] == 1


# ---------------------------------------------------------------- §3.4 전진 수익률


def test_stock_forward_freeze_and_endpoint_rules() -> None:
    """§3.4 의 네 줄 — 연속 · 동결 · t 에 가격 없음 · 표본 끝."""
    dates = pd.date_range("2011-01-31", periods=6, freq="ME")
    close = pd.DataFrame(
        {
            "LIVE": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
            "DEAD": [10.0, 11.0, 12.0, np.nan, np.nan, np.nan],  # 3번째 달에 끊긴다
            "LATE": [np.nan, np.nan, 20.0, 22.0, 24.0, 26.0],  # t 에 가격이 없다
        },
        index=dates,
    )
    fwd = _forward(close, horizons=(2,))
    r = fwd.raw[2]
    # 연속: close[t+2]/close[t] − 1
    assert r.loc[dates[0], "LIVE"] == pytest.approx(12.0 / 10.0 - 1)
    # 동결: 마지막 종가 12.0 에서 멈춘다 (−100% 가 아니다)
    assert r.loc[dates[1], "DEAD"] == pytest.approx(12.0 / 11.0 - 1)
    assert r.loc[dates[2], "DEAD"] == pytest.approx(0.0)
    # t 에 가격이 없으면 그 달은 랭킹에 없다 → NaN
    assert np.isnan(r.loc[dates[0], "LATE"])
    # 표본 끝 — t+2 가 마지막 완결 월을 넘으면 NaN 으로 두고 센다
    assert np.isnan(r.loc[dates[5], "LIVE"]) and np.isnan(r.loc[dates[4], "LIVE"])
    assert fwd.exclusions["h2"]["dropped_incomplete_endpoint"] == 2 + 2 + 2 - 2  # LATE 2달은 가격無
    assert fwd.exclusions["h2"]["frozen_last_price"] >= 2


def test_stock_forward_d1_sets_minus_100_only_for_deaths() -> None:
    """민감도 D1 (§3.4) — 파산·규제폐지 구간만 −100%. 기본은 동결 그대로."""
    dates = pd.date_range("2011-01-31", periods=5, freq="ME")
    close = pd.DataFrame(
        {"BK": [10.0, 11.0, 12.0, np.nan, np.nan], "OK": [10.0, 11.0, 12.0, 13.0, 14.0]},
        index=dates,
    )
    deaths = pd.DataFrame(False, index=dates, columns=close.columns)
    deaths.loc[dates[3], "BK"] = True  # (t, t+h] 안에 파산
    fwd = _forward(close, deaths, horizons=(2,))
    assert fwd.raw[2].loc[dates[1], "BK"] == pytest.approx(12.0 / 11.0 - 1)  # 기본 = 동결
    assert fwd.raw_d1[2].loc[dates[1], "BK"] == pytest.approx(-1.0)  # D1 = −100%
    assert fwd.raw_d1[2].loc[dates[1], "OK"] == fwd.raw[2].loc[dates[1], "OK"]
    assert bool(fwd.death[2].loc[dates[1], "BK"]) and not bool(fwd.death[2].loc[dates[1], "OK"])
    # t=1·t=2 두 달의 (t, t+2] 안에 그 파산이 들어온다
    assert fwd.exclusions["h2"]["d1_set_to_minus_100"] == 2


# ---------------------------------------------------------------- §2.2 횡단면과 최소 크기


def test_theme_month_ic_matches_spearman_and_min_n_rule() -> None:
    """테마-월 IC 는 적격 종목의 Spearman 이고, n < 20 이면 값을 만들지 않고 행만 남긴다 (§2.2)."""
    rng = np.random.default_rng(11)
    tickers = [f"A{i:03d}" for i in range(25)]
    panel = _panel("t_big", DATES, tickers, rng=rng)
    close = _close(DATES, tickers, rng)
    fwd = _forward(close)
    f = theme_month_metrics(panel, fwd, horizons=(12,))
    ic = f.ic[f.ic["variant"] == "rank_score"].set_index("date")
    assert len(ic) == len(DATES)  # 빠진 달도 행은 있다
    d = DATES[0]
    x = panel[panel["date"] == d].set_index("ticker")["composite"]
    y = fwd.raw[12].loc[d]
    ref, n_ref = spearman(x, y.reindex(x.index))
    assert ic.loc[d, "n"] == n_ref
    assert ic.loc[d, "ic"] == pytest.approx(ref)
    assert ic.loc[d, "n_eligible"] == 25

    # 종목 19개 → 어느 달도 IC 를 만들지 않는다
    small = _panel("t_small", DATES, tickers[:19], rng=np.random.default_rng(12))
    fs = theme_month_metrics(small, fwd, horizons=(12,))
    small_ic = fs.ic[fs.ic["variant"] == "rank_score"]
    assert len(small_ic) == len(DATES) and small_ic["ic"].isna().all()
    assert (small_ic["n"] <= 19).all()


def test_monthly_ic_is_theme_equal_weight_not_stock_weighted() -> None:
    """§2.2 — 월별 IC 는 자격 테마들의 **테마 동일가중** 평균이다. 종목 수 가중이 아니다."""
    df = pd.DataFrame(
        {
            "date": [DATES[0]] * 2,
            "theme": ["big", "small"],
            "variant": ["rank_score"] * 2,
            "horizon": [12, 12],
            "ic": [0.10, 0.50],
            "n": [1000, 20],
        }
    )
    out = theme_equal_weight(df, ("variant", "horizon"), "ic")
    assert out["ic"].iloc[0] == pytest.approx(0.30)  # (0.10 + 0.50) / 2 — 종목 수 무시
    assert out["n_themes"].iloc[0] == 2


def test_monthly_ic_partition_by_cycle_class() -> None:
    """클래스 파티션은 그 클래스 테마만 평균한다 (시도 수에 계상된 칸, §6.2)."""
    df = pd.DataFrame(
        {
            "date": [DATES[0]] * 2,
            "theme": ["a", "b"],
            "variant": ["rank_score"] * 2,
            "horizon": [12, 12],
            "ic": [0.2, 0.4],
            "n": [30, 30],
        }
    )
    classes = pd.Series({"a": "commodity_supply", "b": "secular_growth"})
    out = theme_equal_weight(df, ("variant", "horizon"), "ic", partition=classes)
    got = out.set_index("partition")["ic"]
    assert got[PARTITION_ALL] == pytest.approx(0.3)
    assert got["commodity_supply"] == pytest.approx(0.2)
    assert got["secular_growth"] == pytest.approx(0.4)


# ---------------------------------------------------------------- §2.4 스프레드


def test_spread_is_top3_minus_bottom3_of_theme_excess() -> None:
    """§2.4 — 컷오프는 상위 3 − 하위 3, 기준은 테마 EW 초과다."""
    rng = np.random.default_rng(3)
    tickers = [f"B{i:03d}" for i in range(24)]
    panel = _panel("t", DATES, tickers, rng=rng)
    close = _close(DATES, tickers, rng)
    fwd = _forward(close)
    f = theme_month_metrics(panel, fwd, horizons=(12,))
    sp = f.spread[f.spread["variant"] == "rank_score"].set_index("date")
    d = DATES[0]
    x = panel[panel["date"] == d].set_index("ticker")["composite"]
    y = fwd.raw[12].loc[d].reindex(x.index)
    ew = y.mean()
    ranked = (y - ew).reindex(x.sort_values(ascending=False).index).dropna()
    assert sp.loc[d, "ret_top"] == pytest.approx(ranked.iloc[:SPREAD_K].mean())
    assert sp.loc[d, "ret_bot"] == pytest.approx(ranked.iloc[-SPREAD_K:].mean())
    assert sp.loc[d, "spread"] == pytest.approx(sp.loc[d, "ret_top"] - sp.loc[d, "ret_bot"])


# ---------------------------------------------------------------- §2.5 Q3 필터


def test_filter_diff_is_excluded_minus_passing_excess_per_reason() -> None:
    """§2.5 — 사유별 `제외군 평균 초과 − 통과군 평균 초과`. 기준은 테마-월 전체 구성원 EW."""
    rng = np.random.default_rng(5)
    tickers = [f"C{i:03d}" for i in range(26)]
    panel = _panel("t", DATES, tickers, rng=rng, n_excl=4)  # 앞 4개가 E1
    close = _close(DATES, tickers, rng)
    fwd = _forward(close)
    f = theme_month_metrics(panel, fwd, horizons=(12,))
    d = DATES[0]
    row = f.filters[
        (f.filters["date"] == d)
        & (f.filters["reason"] == "E1")
        & (f.filters["gauge"] == "excess")
        & (f.filters["basis"] == "base")
    ].iloc[0]
    y = fwd.raw[12].loc[d].reindex(tickers)
    ew = y.mean()  # 전체 구성원 (제외군 포함) 동일가중
    diff = (y.iloc[:4] - ew).mean() - (y.iloc[4:] - ew).mean()
    assert row["diff"] == pytest.approx(diff)
    assert row["n_excluded"] == 4 and row["n_passing"] == 22
    # 제외군이 0인 사유는 값을 만들지 않는다
    e2 = f.filters[
        (f.filters["date"] == d) & (f.filters["reason"] == "E2") & (f.filters["gauge"] == "excess")
    ].iloc[0]
    assert e2["n_excluded"] == 0 and np.isnan(e2["diff"])
    # 사망률 눈금은 기본 기준으로 한 번만 잰다 (수익률 규약과 무관)
    gauges = set(f.filters[f.filters["gauge"] == "death"]["basis"])
    assert gauges == {"base"}


def test_filter_needs_20_eligible_and_at_least_one_excluded() -> None:
    """§2.5 — n ≥ 20 은 여기에도 적용하되, 제외군이 1종목 이상일 때만 그 테마-월을 센다."""
    rng = np.random.default_rng(7)
    tickers = [f"D{i:03d}" for i in range(21)]
    panel = _panel("t", DATES, tickers, rng=rng, n_excl=3)  # 적격 18 < 20
    close = _close(DATES, tickers, rng)
    f = theme_month_metrics(panel, _forward(close), horizons=(12,))
    ex = f.filters[(f.filters["reason"] == "E1") & (f.filters["gauge"] == "excess")]
    assert ex["diff"].isna().all()


# ---------------------------------------------------------------- §4.1 합격 기준


def _summary_row(**kw: Any) -> dict[str, Any]:
    base = {
        "window": "primary",
        "horizon": GATE_HORIZON,
        "partition": PARTITION_ALL,
        "n_months": 100,
        "n_months_dropped": 0,
        "n_eff": 30.0,
        "mean": 0.0,
        "ci_lo": 0.0,
        "ci_hi": 0.0,
        "mean_n_themes": 40.0,
        "mean_n_stocks": 50.0,
    }
    base.update(kw)
    return base


def test_verdict_q1_gate_is_ci_lower_bound_above_zero() -> None:
    """§4.1 Q1 — 주 창·12M·rank_score IC 의 CI 하한 > 0 이면 합격, 아니면 실패."""
    over = {"dsr": [], "pbo": [], "trials": count_trials()}
    for lo, hi, want in ((0.01, 0.05, "pass"), (-0.01, 0.05, "fail"), (-0.05, -0.01, "fail")):
        ic = pd.DataFrame(
            [_summary_row(variant=v, mean=(lo + hi) / 2, ci_lo=lo, ci_hi=hi) for v in VARIANTS]
        )
        v = verdict(ic, pd.DataFrame(), over)
        assert v["q1"]["gate"] == want
        assert v["dsr_pbo_in_gate"] is False  # §4.1 — DSR·PBO 는 합격 기준이 아니다


def test_verdict_q2_axis_labels() -> None:
    """§4.1 Q2 — CI 하한>0 '일한다' · 상한<0 '반대로 일한다' · 0 포함 '0'. 관문이 아니다."""
    rows = [
        _summary_row(variant="rank_score", ci_lo=0.01, ci_hi=0.03),
        _summary_row(variant="S", ci_lo=0.01, ci_hi=0.03),
        _summary_row(variant="T", ci_lo=-0.03, ci_hi=-0.01),
        _summary_row(variant="M", ci_lo=-0.01, ci_hi=0.02),
    ]
    v = verdict(
        pd.DataFrame(rows), pd.DataFrame(), {"dsr": [], "pbo": [], "trials": count_trials()}
    )
    q2 = v["q2_axes_12m_primary"]
    assert q2["S"]["works"] == "works"
    assert q2["T"]["works"] == "negative"
    assert q2["M"]["works"] == "indistinguishable_from_0"


def test_verdict_q3_judges_only_e1_e2_e3() -> None:
    """§4.1 — E1~E3 은 CI 상한 < 0 이면 '손실을 막았다', 0 을 포함하면 '표본 절단'.
    E4·E5 는 판정하지 않는다."""
    rows = []
    for code, lo, hi in (
        ("E1", -0.20, -0.05),  # 상한 < 0 → 막았다
        ("E2", -0.10, 0.05),  # 0 포함 → 알파가 아니다
        ("E3", -0.10, 0.05),
        ("E4", -0.30, -0.10),  # 상한 < 0 이지만 판정하지 않는다
        ("E5", -0.30, -0.10),
    ):
        rows.append(
            {
                "window": "primary",
                "horizon": GATE_HORIZON,
                "reason": code,
                "gauge": "excess",
                "basis": "base",
                "mean": (lo + hi) / 2,
                "ci_lo": lo,
                "ci_hi": hi,
            }
        )
        rows.append(
            {
                "window": "primary",
                "horizon": GATE_HORIZON,
                "reason": code,
                "gauge": "death",
                "basis": "base",
                "mean": 0.05,
                "ci_lo": 0.01,
                "ci_hi": 0.09,
            }
        )
    ic = pd.DataFrame([_summary_row(variant=v) for v in VARIANTS])
    v = verdict(ic, pd.DataFrame(rows), {"dsr": [], "pbo": [], "trials": count_trials()})
    q3 = v["q3_filters_12m_primary"]
    assert q3["E1"]["verdict"] == "blocked_losses"
    assert q3["E2"]["verdict"] == "sample_truncation_not_alpha"
    assert q3["E3"]["verdict"] == "sample_truncation_not_alpha"
    assert q3["E4"]["verdict"].startswith("not_judged")
    assert q3["E5"]["verdict"].startswith("not_judged")
    assert q3["E1"]["mechanism_confirmed"] is True  # 사망률 차 CI 하한 > 0


# ---------------------------------------------------------------- axes 배선 (백테스트가 부르는 것)


def _feature_frame(rows: dict[str, dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame.from_dict(rows, orient="index")
    for c in FEATURE_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df.index.name = "ticker"
    return df[list(FEATURE_COLUMNS)]


def _ok_row(**kw: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "fund_calendardate": pd.Timestamp("2015-06-30").date(),
        "fund_status": "ok",
        "price": 10.0,
        "mcap": 1e9,
        "cash_runway_q": 12.0,
        "net_debt_ebitda": 1.0,
        "nd_basis": "ebitda",
        "maturity_wall_12m": 0.05,
        "interest_coverage": 5.0,
        "dilution_3y": 0.02,
        "adv20_usd": 5e6,
        "red_flags": "",
        "margin_headroom": 0.1,
        "opleverage": 2.0,
        "fixed_cost_ratio": 0.4,
        "price_beta_hist": 0.5,
        "equity_leverage": 1.2,
        "marginal_producer": False,
        "stage2": True,
        "rs_rating": 50.0,
        "vcp_base": False,
        "from_52w_low": 0.2,
        "above_50d": True,
        "rvol_expansion": 1.0,
    }
    d.update(kw)
    return d


def test_hard_filter_flags_agree_with_hard_filters_and_map_to_e1_e5() -> None:
    """사유 코드가 `docs/14` §1 Q3 표의 다섯과 같은 조건이고, `hard_filters` 와 같은 마스크다."""
    f = _feature_frame(
        {
            "PASS": _ok_row(),
            "E1": _ok_row(cash_runway_q=axes.RUNWAY_MIN_Q - 0.1),
            "E2": _ok_row(net_debt_ebitda=axes.ND_EBITDA_EXCLUDE + 0.1),
            "E3": _ok_row(maturity_wall_12m=axes.MATURITY_WALL_EXCLUDE + 0.1),
            "E4": _ok_row(cash_runway_q=np.nan),
            "E5": _ok_row(fund_calendardate=None, fund_status="none"),
        }
    )
    flags = axes.hard_filter_flags(f)
    for code in axes.HARD_REASON_CODES:
        assert bool(flags.loc[code, code]), code
        assert not bool(flags.loc["PASS", code])
    hf = axes.hard_filters(f)
    assert (hf["excluded"].to_numpy() == flags.any(axis=1).to_numpy()).all()
    assert not bool(hf.loc["PASS", "excluded"])


def test_timing_components_average_to_m_raw() -> None:
    """`timing_components` 는 `timing` 이 실제로 평균하는 값이다 (Q4 가 그 값을 읽는다)."""
    f = _feature_frame({f"T{i}": _ok_row(rs_rating=10.0 * i) for i in range(1, 6)})
    comps = axes.timing_components(f)
    assert list(comps.columns) == list(axes.M_COMPONENTS)
    t = axes.timing(f)
    assert np.allclose(t["m_raw"].to_numpy(), comps.mean(axis=1).to_numpy())


def test_month_panel_wires_listing_hard_filter_and_score() -> None:
    """`month_panel` 은 `msa picks` 와 같은 순서로 부른다 — 상장 → 하드 필터 → 적격 안 백분위."""
    tickers = [f"P{i:02d}" for i in range(6)]
    frame = _feature_frame(
        {t: _ok_row(rs_rating=10.0 * i, margin_headroom=0.01 * i) for i, t in enumerate(tickers)}
    )
    frame.loc["P00", "cash_runway_q"] = axes.RUNWAY_MIN_Q - 1  # E1 제외
    uni = pd.DataFrame(
        {
            "name": tickers,
            "is_delisted": ["N"] * 6,
            "last_price_date": [pd.Timestamp("2015-06-30")] * 6,
            "listed": [True] * 6,
        },
        index=pd.Index(tickers, name="ticker"),
    )
    # 폐지 종목 하나를 유니버스에만 둔다 (상장 판정 탈락 → 패널 행 없음)
    uni.loc["DEL"] = {
        "name": "DEL",
        "is_delisted": "Y",
        "last_price_date": None,
        "listed": False,
    }
    fs = FeatureSet("t", pd.Timestamp("2015-06-30"), pd.Timestamp("2015-06-30"), frame, uni)
    rows, counts = month_panel(fs)
    assert list(rows.columns) == list(PANEL_COLUMNS)
    assert counts["n_members"] == 7 and counts["n_listed"] == 6 and counts["n_delisted"] == 1
    assert counts["n_eligible"] == 5 and counts["n_E1"] == 1 and counts["n_excluded_any"] == 1
    assert len(rows) == 6  # 상장 6종목 (제외된 것도 행은 있다 — 사유별로 세야 한다)
    assert not bool(rows.set_index("ticker").loc["P00", "eligible"])
    elig = rows[rows["eligible"]]
    assert elig["composite"].notna().all() and elig["s_pct"].notna().all()
    assert rows.loc[rows["ticker"] == "P00", "composite"].isna().all()
    # 백분위는 **적격 5종목 안에서** 매겨진다 (제외 종목이 분모에 들어가지 않는다)
    assert set(np.round(elig["m_pct"].to_numpy(), 6)) == {0.2, 0.4, 0.6, 0.8, 1.0}
    # 15개 지표가 전부 실린다 (Q4)
    assert elig[list(INDICATORS)].notna().any().all()


# ---------------------------------------------------------------- 전체 배선 (합성)


def test_run_backtest_frames_end_to_end_on_synthetic_panel() -> None:
    """두 테마 · 48개월 합성으로 파이프 전체가 돌고 산출물 모양이 §2.1 의 표와 맞는가."""
    rng = np.random.default_rng(42)
    tickers_a = [f"A{i:03d}" for i in range(30)]
    tickers_b = [f"B{i:03d}" for i in range(28)]
    panel = pd.concat(
        [
            _panel("theme_a", DATES, tickers_a, rng=rng, n_excl=5, cycle_reasons=True),
            _panel("theme_b", DATES, tickers_b, rng=rng, n_excl=5, cycle_reasons=True),
        ],
        ignore_index=True,
    )
    close = _close(DATES, tickers_a + tickers_b, rng)
    fwd = _forward(close)
    classes = pd.Series({"theme_a": "commodity_supply", "theme_b": "secular_growth"})
    counts = pd.DataFrame(
        {
            "date": list(DATES) * 2,
            "theme": ["theme_a"] * len(DATES) + ["theme_b"] * len(DATES),
            "n_members": 30,
            "n_listed": 30,
            "n_delisted": 0,
            "n_no_recent_price": 0,
            "n_eligible": 25,
            "n_E1": 1,
            "n_E2": 1,
            "n_E3": 1,
            "n_E4": 1,
            "n_E5": 1,
            "n_excluded_any": 5,
            "n_composite_partial": 0,
            "n_s_na": 0,
            "n_t_na": 0,
            "n_m_na": 0,
            "error": "",
        }
    )
    res = run_backtest_frames(panel, counts, fwd, close, classes, pbo_max_splits=200)

    gate = res.ic_summary[
        (res.ic_summary["window"] == "primary")
        & (res.ic_summary["horizon"] == GATE_HORIZON)
        & (res.ic_summary["variant"] == "rank_score")
        & (res.ic_summary["partition"] == PARTITION_ALL)
    ]
    assert len(gate) == 1  # 1차 지표가 정확히 한 줄이다 (§2.1 "하나만")
    assert res.verdict["q1"]["gate"] in ("pass", "fail")
    # 부차 지표가 전부 있다 (§2.1 표)
    assert set(res.ic_summary["horizon"]) >= set(HORIZONS)
    assert set(res.ic_summary["window"]) == {"primary", "full"}
    assert set(res.indicator_ic_summary["indicator"]) == set(INDICATORS)
    assert set(res.spread_summary["variant"]) == set(VARIANTS)
    assert set(res.filters_summary["reason"]) == set(axes.HARD_REASON_CODES)
    assert set(res.filters_summary["basis"]) == {"base", "d1"}
    assert set(res.filters_summary["gauge"]) == {"excess", "death"}
    # 클래스 파티션 칸이 있다 (시도 수에 계상됨)
    assert set(res.ic_summary["partition"]) >= {PARTITION_ALL, "commodity_supply"}
    # 과최적화는 계산해서 싣되 판정에 들어가지 않는다
    assert res.overfitting["trials"]["total"] == 458
    assert res.verdict["dsr_pbo_in_gate"] is False
    assert res.exclusions["theme_months"]["min_stocks_xs"] == MIN_STOCKS_XS
    # 리포트가 렌더된다
    from msa.l4.backtest import render_report

    res.meta.update(store_end="2026-08-14", grid_first="2011-01-31", grid_last="2014-12-31")
    text = render_report(res)
    assert "Q1 판정" in text and "docs/14" in text


def test_effective_sample_reports_theme_ic_and_within_theme_stock_correlation() -> None:
    """§2.3 — 리포트 첫 표의 두 숫자: 테마 간 IC 상관과 테마 내 종목 상관 → 유효 종목 수."""
    from msa.l4.backtest import effective_sample

    dates = pd.date_range("2011-01-31", periods=90, freq="ME")
    rng = np.random.default_rng(1)
    themes = ["ta", "tb", "tc"]
    ic_tm = pd.DataFrame(
        {
            "date": np.tile(dates, len(themes)),
            "theme": np.repeat(themes, len(dates)),
            "variant": "rank_score",
            "horizon": GATE_HORIZON,
            "ic": rng.normal(0, 0.1, size=len(dates) * len(themes)),
            "n": 30,
        }
    )
    tickers = [f"{t}_{i}" for t in themes for i in range(5)]
    # 공통 요인 + 고유 잡음 → 테마 내 종목 상관이 0 보다 확실히 크다
    common = rng.normal(0, 0.05, size=(len(dates), 1))
    steps = 1.0 + common + rng.normal(0, 0.02, size=(len(dates), len(tickers)))
    close = pd.DataFrame(100 * np.cumprod(steps, axis=0), index=dates, columns=tickers)
    panel = pd.DataFrame(
        {"theme": [t.split("_")[0] for t in tickers], "ticker": tickers, "eligible": True}
    )
    e = effective_sample(ic_tm, close, panel)
    for w in ("primary", "full"):
        d = e[f"theme_ic_corr_{w}"]
        assert d["n_themes"] == 3 and not np.isnan(d["avg_corr"])
    s = e["within_theme_stock_corr_primary"]
    assert s["n_themes_measured"] == 3
    assert s["median_avg_corr"] > 0  # 같은 상품가 노출 → 명목 5종목이 유효 5종목이 아니다
    assert 1.0 <= s["median_n_eff_stocks"] < s["median_n_stocks"]
