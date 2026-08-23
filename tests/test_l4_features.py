"""L4 특성 — PIT 컷오프·TTM·희석·회귀·가격 특성·레드플래그 (합성, 스토어 없음)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from msa.l4 import features as F
from msa.vendor.redflags import NOT_COMPUTABLE, AnnualRow, detect_red_flags


def _quarters(n: int, end: str = "2026-06-30") -> pd.DatetimeIndex:
    return pd.date_range(end=end, periods=n, freq="QE")


def _fund(
    ticker: str, n: int = 16, *, lag_days: int = 40, **cols: np.ndarray | float
) -> pd.DataFrame:
    cd = _quarters(n)
    df = pd.DataFrame(
        {
            "ticker": ticker,
            "calendardate": cd,
            "datekey": cd + pd.Timedelta(days=lag_days),
            "dimension": "ARQ",
            "revenue": 100.0,
            "ebitda": 20.0,
            "ebit": 15.0,
            "opinc": 15.0,
            "netinc": 10.0,
            "ncfo": 18.0,
            "fcf": 5.0,
            "capex": -13.0,
            "intexp": 3.0,
            "cor": 60.0,
            "cashneq": 200.0,
            "debt": 100.0,
            "debtc": 10.0,
            "equity": 300.0,
            "sharesbas": 1000.0,
        }
    )
    for k, v in cols.items():
        df[k] = v
    return df


# ---------------------------------------------------------------- PIT


def test_pit_cutoff_drops_filings_after_asof_and_keeps_first_report() -> None:
    f = _fund("A", 8)
    # 2026-06-30 분기의 datekey 는 2026-08-09 → asof 2026-08-01 이면 보이지 않아야 한다
    asof = pd.Timestamp("2026-08-01")
    q = F.pit_quarterly(f, asof)
    assert q["calendardate"].max() == pd.Timestamp("2026-03-31")
    assert (q["datekey"] <= asof).all()
    # 같은 calendardate 의 정정 보고(나중 datekey, 다른 값)는 버린다
    restated = f.loc[f["calendardate"] == "2025-12-31"].copy()
    restated["datekey"] = pd.Timestamp("2026-03-15")
    restated["revenue"] = 999.0
    q2 = F.pit_quarterly(pd.concat([f, restated]), pd.Timestamp("2026-12-31"))
    row = q2.loc[q2["calendardate"] == "2025-12-31"]
    assert len(row) == 1 and row["revenue"].iloc[0] == 100.0
    # 최초 보고분의 정의는 "asof 안에서 가장 이른 datekey"
    q3 = F.pit_quarterly(pd.concat([f, restated]), pd.Timestamp("2026-03-20"))
    assert q3.loc[q3["calendardate"] == "2025-12-31", "revenue"].iloc[0] == 100.0


def test_future_filing_is_not_used_anywhere_in_features() -> None:
    """datekey > asof 인 분기의 값이 최신 스냅샷·TTM 에 섞이면 안 된다."""
    f = _fund("A", 12)
    f.loc[f["calendardate"] == "2026-06-30", ["cashneq", "revenue"]] = [9_999.0, 9_999.0]
    asof = pd.Timestamp("2026-07-15")  # 6/30 분기 datekey = 8/9 → 미래
    qt = F.add_ttm(F.pit_quarterly(f, asof))
    feat, _ = F.fundamental_features(qt, asof, pd.Series({"A": 1e4}))
    assert feat.loc["A", "cash"] == 200.0
    assert feat.loc["A", "revenue_ttm"] == 400.0
    assert feat.loc["A", "fund_calendardate"] == pd.Timestamp("2026-03-31").date()


def test_ttm_requires_four_contiguous_quarters() -> None:
    full = F.add_ttm(F.pit_quarterly(_fund("A", 6), pd.Timestamp("2027-01-01")))
    assert full["revenue_ttm"].tolist()[3:] == [400.0, 400.0, 400.0]
    f = _fund("A", 6)
    f = f.drop(f.index[2])  # 가운데 분기(2025-09) 결측 → 어떤 4행 창도 365일 span → 전부 NaN
    qt = F.add_ttm(F.pit_quarterly(f, pd.Timestamp("2027-01-01")))
    assert qt["revenue_ttm"].isna().all()


def test_stale_latest_quarter_is_dropped() -> None:
    f = _fund("OLD", 8, lag_days=30)
    asof = pd.Timestamp("2027-12-31")  # 2026-06-30 에서 18개월 뒤
    qt = F.add_ttm(F.pit_quarterly(f, asof))
    feat, _ = F.fundamental_features(qt, asof, pd.Series({"OLD": 1e4}))
    assert feat.empty


# ---------------------------------------------------------------- 개별 특성


def test_runway_and_net_debt_rules() -> None:
    burn = _fund("BURN", 8, fcf=-40.0, cashneq=200.0)  # TTM FCF −160 → 분기 40 → 5분기
    cashpos = _fund("POS", 8, fcf=10.0)
    loss = _fund("LOSS", 8, ebitda=-5.0, debt=150.0, cashneq=50.0)  # 순부채 100, EBITDA≤0 → /mcap
    nofcf = _fund("NOCF", 8, fcf=np.nan, ncfo=np.nan, capex=np.nan)
    alt = _fund(
        "ALT", 8, fcf=np.nan, ncfo=10.0, capex=-30.0
    )  # fcf_q = −20 → TTM −80 → 분기 20 → 10q
    asof = pd.Timestamp("2026-09-30")
    qt = F.add_ttm(F.pit_quarterly(pd.concat([burn, cashpos, loss, nofcf, alt]), asof))
    mcap = pd.Series({"BURN": 1000.0, "POS": 1000.0, "LOSS": 400.0, "NOCF": 1000.0, "ALT": 1000.0})
    feat, _ = F.fundamental_features(qt, asof, mcap)
    assert feat.loc["BURN", "cash_runway_q"] == pytest.approx(5.0)
    assert np.isinf(feat.loc["POS", "cash_runway_q"])
    assert feat.loc["LOSS", "nd_basis"] == "mcap"
    assert feat.loc["LOSS", "net_debt_ebitda"] == pytest.approx(100 / 400)
    assert feat.loc["BURN", "nd_basis"] == "ebitda"
    assert feat.loc["BURN", "net_debt_ebitda"] == pytest.approx(-100 / 80)
    assert np.isnan(feat.loc["NOCF", "cash_runway_q"])
    assert feat.loc["ALT", "cash_runway_q"] == pytest.approx(10.0)
    assert feat.loc["BURN", "maturity_wall_12m"] == pytest.approx(10 / 1000)
    assert feat.loc["BURN", "interest_coverage"] == pytest.approx(60 / 12)
    assert feat.loc["BURN", "equity_leverage"] == pytest.approx((-100 + 1000) / 1000)
    assert feat.loc["BURN", "fixed_cost_ratio"] == pytest.approx(0.4)


def test_dilution_uses_date_not_row_position() -> None:
    f = _fund("D", 16)
    f["sharesbas"] = np.linspace(1000, 1000 * 1.5**3, 16) ** 0  # 자리만
    # 2023-06-30 → 1000, 2026-06-30 → 1000·(1.2)^3
    f.loc[f["calendardate"] == "2023-06-30", "sharesbas"] = 1000.0
    f.loc[f["calendardate"] == "2026-06-30", "sharesbas"] = 1000.0 * 1.2**3
    f2 = f.drop(f.index[5:8])  # 중간 분기 3개 제거 — 위치 lag 12 면 틀어진다
    asof = pd.Timestamp("2026-09-30")
    qt = F.add_ttm(F.pit_quarterly(f2, asof))
    d = F.dilution_3y(qt, F.latest_rows(qt, asof))
    assert d.loc["D", "dilution_3y"] == pytest.approx(0.2)


def test_regression_incremental_margin_and_opleverage() -> None:
    n = 20
    f = _fund("R", n)
    rev = 100 + 0.5 * np.arange(n) ** 2  # 비선형 — 차분이 상수가 아니어야 회귀가 선다
    f["revenue"] = rev
    f["ebitda"] = 0.5 * rev - 40  # 증분마진 0.5
    asof = pd.Timestamp("2026-09-30")
    qt = F.add_ttm(F.pit_quarterly(f, asof))
    r = F.regression_features(qt, F.latest_rows(qt, asof))
    assert r.loc["R", "incremental_margin"] == pytest.approx(0.5)
    last = qt.iloc[-1]
    margin = last["ebitda_ttm"] / last["revenue_ttm"]  # 마진은 TTM 기준
    assert r.loc["R", "opleverage"] == pytest.approx(0.5 / margin)
    assert r.loc["R", "reg_pairs"] == 12
    # 완전 선형(차분 상수) 이면 분산 0 → 기울기를 만들지 않는다
    g = _fund("L", n)
    g["revenue"] = np.linspace(100, 200, n)
    g["ebitda"] = 0.5 * g["revenue"] - 40
    qg = F.add_ttm(F.pit_quarterly(g, asof))
    assert np.isnan(
        F.regression_features(qg, F.latest_rows(qg, asof)).loc["L", "incremental_margin"]
    )


def test_theme_margin_history_and_headroom_and_marginal_producer() -> None:
    a = _fund("A", 20, revenue=100.0, ebitda=30.0)
    b = _fund("B", 20, revenue=100.0, ebitda=10.0)
    c = _fund("C", 20, revenue=100.0, ebitda=-5.0)
    d = _fund("D", 20, revenue=100.0, ebitda=15.0)
    asof = pd.Timestamp("2026-09-30")
    qt = F.add_ttm(F.pit_quarterly(pd.concat([a, b, c, d]), asof))
    hist = F.theme_margin_history(qt, asof)
    assert len(hist) >= 12
    assert hist.iloc[-1] == pytest.approx((30 + 10 - 5 + 15) / 400)
    mcap = pd.Series({"A": 1.0, "B": 1.0, "C": 1.0, "D": 1.0})
    feat, stats = F.fundamental_features(qt, asof, mcap)
    assert stats["theme_margin_p75"] == pytest.approx(50 / 400)
    assert feat.loc["A", "margin_headroom"] == pytest.approx(50 / 400 - 0.30)
    assert bool(feat.loc["C", "marginal_producer"]) is True
    assert bool(feat.loc["A", "marginal_producer"]) is False
    # 매출 있는 구성원 4개 미만이면 사분위가 정의되지 않는다 → NA
    qt3 = F.add_ttm(F.pit_quarterly(pd.concat([a, b, c]), asof))
    feat3, stats3 = F.fundamental_features(qt3, asof, mcap)
    assert np.isnan(stats3["theme_margin_p25_xs"])
    assert feat3["marginal_producer"].isna().all()


def test_red_flags_vendored_rules() -> None:
    hist = [
        AnnualRow(2023, 100, -5, -3, -1, 2),
        AnnualRow(2024, 50, -5, -3, -1, 2),
        AnnualRow(2025, -10, -5, 4, -1, 2),
    ]
    keys = {f.key for f in detect_red_flags(hist)}
    assert keys == {
        "full_capital_impairment",
        "consecutive_operating_loss",
        "profit_without_cash",
        "zombie_streak",
    }
    assert {f.key for f in detect_red_flags(hist, financial=True)} == keys - {"zombie_streak"}
    assert detect_red_flags([]) == []
    assert "partial_capital_impairment" in NOT_COMPUTABLE
    # 2년 연속은 플래그가 아니다 (임계 3년)
    assert detect_red_flags(hist[1:]) == [
        f for f in detect_red_flags(hist[1:]) if f.key != "consecutive_operating_loss"
    ]


def test_annual_rows_from_quarters_feed_red_flags() -> None:
    f = _fund("Z", 16, opinc=-1.0, intexp=1.0)
    asof = pd.Timestamp("2026-09-30")
    qt = F.add_ttm(F.pit_quarterly(f, asof))
    rows = F.annual_rows_for(qt, "Z", pd.Timestamp("2026-06-30"))
    assert [r.year for r in rows] == [2023, 2024, 2025, 2026]
    assert rows[-1].operating_income == pytest.approx(-4.0)
    feat, _ = F.fundamental_features(qt, asof, pd.Series({"Z": 1.0}))
    assert "consecutive_operating_loss" in feat.loc["Z", "red_flags"]
    assert "zombie_streak" in feat.loc["Z", "red_flags"]
    assert feat.loc["Z", "n_red_flags"] == 2


# ---------------------------------------------------------------- 가격 특성


def _px(ticker: str, n: int = 300, *, trend: float = 0.001, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-08-14", periods=n)
    close = 10 * np.exp(np.cumsum(trend + 0.01 * rng.standard_normal(n)))
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": dates,
            "close": close,
            "closeunadj": close * 2,
            "volume": 1e5,
            "mcap": 1e9,
        }
    )


def test_price_features_shapes() -> None:
    up = _px("UP", trend=0.004)
    down = _px("DN", trend=-0.003, seed=1)
    short = _px("SH", n=100)
    pf = F.price_features(pd.concat([up, down, short]), pd.Timestamp("2026-08-14"))
    assert set(pf.index) == {"UP", "DN", "SH"}
    assert list(pf.columns) == list(F.PRICE_FEATURE_COLUMNS)
    assert pf.loc["SH", "stage2"] is None
    assert pf.loc["UP", "stage2"] in (True, False)
    # `volume` 이 소급 분할조정 값이므로 짝은 **조정** 종가다 (features.py 주석 참조)
    assert pf.loc["UP", "adv20_usd"] == pytest.approx(
        float((up["close"] * up["volume"]).tail(20).mean())
    )
    assert pf.loc["UP", "price"] == pytest.approx(float(up["closeunadj"].iloc[-1]))
    # asof 이후 행은 쓰지 않는다
    pf2 = F.price_features(up, pd.Timestamp("2026-06-30"))
    assert pf2.loc["UP", "last_price_date"] <= pd.Timestamp("2026-06-30").date()


def _ref_price_features(px: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """벡터화 전의 종목별 루프 구현 (참조). `price_features` 가 이것과 같은 값을 내야 한다."""
    p = px.copy()
    p["date"] = pd.to_datetime(p["date"])
    p = p.loc[p["date"] <= pd.Timestamp(asof)].sort_values(["ticker", "date"])
    rows: dict[str, dict[str, object]] = {}
    for tk, g in p.groupby("ticker", sort=True):
        g = g.tail(252)
        c = g["close"].astype(float).reset_index(drop=True)
        cu = g["closeunadj"].astype(float).reset_index(drop=True)
        v = g["volume"].astype(float).reset_index(drop=True)
        n = len(c)
        last_mcap = g["mcap"].dropna()
        r: dict[str, object] = {
            "price": float(cu.iloc[-1]) if n else np.nan,
            "mcap": float(last_mcap.iloc[-1]) if len(last_mcap) else np.nan,
            "last_price_date": g["date"].iloc[-1].date() if n else None,
            "adv20_usd": float((c * v).tail(20).mean()) if n >= 5 else np.nan,
        }
        sma50 = c.tail(50).mean() if n >= 50 else np.nan
        sma150 = c.tail(150).mean() if n >= 150 else np.nan
        sma200 = c.tail(200).mean() if n >= 200 else np.nan
        sma200_prev = c.iloc[:-21].tail(200).mean() if n >= 221 else np.nan
        lo = c.min() if n >= 120 else np.nan
        hi = c.max() if n >= 120 else np.nan
        last = float(c.iloc[-1]) if n else np.nan
        r["from_52w_low"] = last / lo - 1 if n >= 120 else np.nan
        r["from_52w_high"] = last / hi - 1 if n >= 120 else np.nan
        r["above_50d"] = bool(last > sma50) if n >= 50 else None
        r["sma200_up_1m"] = bool(sma200 > sma200_prev) if n >= 221 else None
        r["stage2"] = (
            bool(
                last > sma150 > sma200
                and sma200 > sma200_prev
                and r["from_52w_low"] >= 0.30  # type: ignore[operator]
                and r["from_52w_high"] >= -0.25  # type: ignore[operator]
            )
            if n >= 221
            else None
        )
        r["rvol_expansion"] = (
            float(v.tail(20).mean() / v.tail(50).mean())
            if n >= 50 and v.tail(50).mean() > 0
            else np.nan
        )
        r["vcp_base"] = F.vcp_base(c, v) if n >= 60 else None
        rows[str(tk)] = r
    return pd.DataFrame.from_dict(rows, orient="index")


def test_price_features_vectorized_equals_reference() -> None:
    """길이 혼합(300·221·120·60·30·3) · NaN 종가/거래량/시총 · 거래량 0 · 기준일 이후 행."""
    rng = np.random.default_rng(3)
    parts = []
    for i, n in enumerate((320, 300, 221, 220, 120, 119, 60, 30, 3)):
        df = _px(f"T{i}", n=n, trend=rng.normal(0, 0.003), seed=10 + i)
        if i == 0:  # NaN 종가·시총이 섞여도 같은 값이어야 한다
            df.loc[df.index[::37], "close"] = np.nan
            df.loc[df.index[-5:], "mcap"] = np.nan
        if i == 1:  # 거래량 0 → RVOL 분모 0
            df["volume"] = 0.0
        if i == 2:  # 마지막 거래량 NaN
            df.loc[df.index[-3:], "volume"] = np.nan
        parts.append(df)
    px = pd.concat(parts, ignore_index=True)
    asof = pd.Timestamp("2026-08-10")  # 이후 행 4개는 버려진다
    got = F.price_features(px, asof)
    ref = _ref_price_features(px, asof)
    assert list(got.index) == list(ref.index)
    for col in F.PRICE_FEATURE_COLUMNS:
        g, r = got[col], ref[col].reindex(got.index)
        if col in ("above_50d", "sma200_up_1m", "stage2", "vcp_base", "last_price_date"):
            assert g.tolist() == r.tolist(), col
        else:
            np.testing.assert_allclose(
                g.to_numpy(dtype=float), r.to_numpy(dtype=float), rtol=0, atol=0, err_msg=col
            )


def _ref_rs_rating(universe_rs_raw: pd.Series) -> pd.Series:
    s = universe_rs_raw.dropna()
    pct = s.rank(pct=True, method="average")
    return (pct * 98 + 1).round().clip(1, 99)


def test_rs_rating_percentile_range_and_matches_reference() -> None:
    rs = pd.Series(np.linspace(-1, 1, 200), index=[f"T{i}" for i in range(200)])
    r = F.rs_rating_from_universe(rs)
    assert r.min() >= 1 and r.max() <= 99
    assert r.iloc[-1] == 99 and r.iloc[0] == 1
    # 동률·NaN 이 섞여도 옛 구현과 같다
    rs2 = pd.Series(
        [0.1, 0.1, np.nan, -0.5, 0.3, 0.3, 0.3, np.nan, 2.0], index=[f"U{i}" for i in range(9)]
    )
    pd.testing.assert_series_equal(F.rs_rating_from_universe(rs2), _ref_rs_rating(rs2))


def test_price_beta_hist_window_and_sign() -> None:
    # 참조가격: 2020-03 저점 → 2025-12 고점
    idx = pd.date_range("2016-01-31", "2026-07-31", freq="ME")
    price = pd.Series(100.0, index=idx)
    price.loc["2020-03-31"] = 50.0
    price.loc["2020-04-30":] = np.linspace(55, 200, len(price.loc["2020-04-30":]))
    a = _fund("A", 44)  # 2015-09 ~ 2026-06
    a["ebitda"] = 0.0
    a.loc[a["calendardate"] >= "2025-01-01", "ebitda"] = 25.0  # TTM 100 ↑ vs 매출 TTM 400 → +0.25
    qt = F.add_ttm(F.pit_quarterly(a, pd.Timestamp("2026-08-14")))
    beta, info = F.price_beta_hist(qt, price, pd.Timestamp("2026-08-14"))
    assert info["status"] == "ok" and info["trough"] == "2020-03-31"
    assert beta.loc["A"] == pytest.approx(0.25 / np.log(200 / 50), rel=1e-6)
    # 짧은 참조 → n/a
    _, info2 = F.price_beta_hist(qt, price.tail(10), pd.Timestamp("2026-08-14"))
    assert info2["status"] == "n/a"
