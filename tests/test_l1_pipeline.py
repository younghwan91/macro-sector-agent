"""합성 데이터로 패널 → 지표 → 스코어보드를 끝까지 돌린다 (스토어 없음).

목적은 수치의 정확성이 아니라 **모양·결측·가중치 재정규화·플래그**가 설계대로 나오는지다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from msa.l1.blocks import BLOCK_INDICATORS, compute_indicators
from msa.l1.fundamentals import FUND_COLUMNS, FundPanel, grid_dates
from msa.l1.panel import PANEL_COLUMNS, panel_from_frames
from msa.l1.physical import PhysicalBundle, PhysicalSeries
from msa.l1.scoreboard import BLOCKS, SCORED, build_scoreboard, scoreboard_history
from msa.themes import BLOCK_WEIGHTS, ThemeSet, load_themes

THEMES = ["alpha", "beta", "gamma", "delta"]
CLASSES = ["commodity_supply", "secular_growth", "credit_rate", "commodity_supply"]


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
                "etf_proxy": "GDX" if i == 0 else None,
                "etf_proxy_alt": [],
                "physical_ref": (
                    {"source": "etf", "symbol": "GLD", "kind": "price"}
                    if i == 0
                    else {"source": "manual", "symbol": "VOL", "kind": "volume"}
                    if i == 1
                    else {"source": "fred", "symbol": "MISSING", "kind": "volume"}
                    if i == 2
                    else None
                ),
                "correlation_cluster": None,
                "min_constituents": 5,
            }
        )
    p = tmp_path / "themes.yaml"
    p.write_text(yaml.safe_dump({"schema_version": 1, "defaults": {}, "themes": recs}))
    return load_themes(p)


def _synthetic_panel(seed: int = 1):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2010-01-01", "2016-12-30")
    rows = []
    for j, t in enumerate(THEMES):
        drift = (-0.0004, 0.0005, 0.0001, -0.0002)[j]
        ret = rng.normal(drift, 0.012, size=len(days))
        n_listed = 20 + j * 5
        for i, d in enumerate(days):
            rows.append(
                {
                    "date": d,
                    "theme": t,
                    "ret_ew": ret[i],
                    "ret_cw": ret[i] * 0.9,
                    "n_ret": n_listed - 1,
                    "n_listed": n_listed,
                    "n_cw": n_listed - 2,
                    "dv": 1e7 * (1 + 0.2 * np.sin(i / 50)),
                    "mcap_sum": 1e10,
                    "n_sma200": n_listed if i >= 200 else 0,
                    "n_above200": int(n_listed * (0.3 + 0.4 * (np.sin(i / 120) > 0)))
                    if i >= 200
                    else 0,
                    "n_nh6m": int(rng.integers(0, 4)),
                    "n_nl6m": int(rng.integers(0, 4)),
                    "n_capped": 0,
                }
            )
    frame = pd.DataFrame(rows).set_index(["date", "theme"]).sort_index()
    spy_ret = rng.normal(0.0003, 0.01, size=len(days))
    spy = pd.DataFrame({"close": 100 * np.cumprod(1 + spy_ret), "dv": 5e10}, index=days)
    return panel_from_frames(frame, spy)


def _synthetic_fund(seed: int = 2) -> FundPanel:
    rng = np.random.default_rng(seed)
    gd = grid_dates("2010-01-31", "2016-12-30")
    buckets = pd.to_datetime(gd["bucket"])
    rows = []
    for j, t in enumerate(THEMES):
        for b in buckets:
            base = {c: float(abs(rng.normal(10, 2)) + 1) for c in FUND_COLUMNS}
            base.update(
                n_reporting=15 + j,
                n_ebitda_pos=10,
                ebitda_nonpos_share=0.3,
                ev_ebitda_med=8 + rng.normal(),
                ev_sales_med=2 + rng.normal() * 0.1,
                pb_med=1.5 + rng.normal() * 0.1,
                fcf_yield_med=0.05 + rng.normal() * 0.01,
                ev_replacement_med=1.2,
            )
            rows.append({"date": b, "theme": t, **base})
    frame = pd.DataFrame(rows).set_index(["date", "theme"]).sort_index()
    ss_rows = []
    for t in THEMES:
        for b in buckets:
            ss_rows.append(
                {
                    "date": b,
                    "theme": t,
                    "ss10_rev_t1": 120.0,
                    "ss10_rev_t0": 100.0,
                    "ss10_ratio_med": 1.1,
                    "ss10_n": 8,
                    "ss10_n_t0": 10,
                    "ss10_coverage": 0.8,
                    "ss10_ma_n": 1,
                    "ss5_rev_t1": 110.0,
                    "ss5_rev_t0": 100.0,
                    "ss5_ratio_med": 1.05,
                    "ss5_n": 9,
                    "ss5_n_t0": 10,
                    "ss5_coverage": 0.9,
                    "ss5_ma_n": 0,
                }
            )
    ss = pd.DataFrame(ss_rows).set_index(["date", "theme"]).sort_index()
    act = pd.DataFrame(
        {"exits_36m": 3.0, "entries_36m": 1.0, "exits_1m": 0.0, "entries_1m": 0.0},
        index=frame.index,
    )
    return FundPanel(frame=frame, same_store=ss, actions=act, built_from={"synthetic": True})


def _physical() -> PhysicalBundle:
    me = pd.date_range("2000-01-31", "2016-12-31", freq="ME")
    gld = pd.Series(np.linspace(50, 120, len(me)), index=me)
    vol = pd.Series(np.linspace(100, 130, len(me)), index=me)
    cpi = pd.Series(np.linspace(170, 240, len(me)), index=me)
    return PhysicalBundle(
        refs={
            "alpha": PhysicalSeries("GLD", "etf", "price", "ok", gld),
            "beta": PhysicalSeries("VOL", "manual", "volume", "ok", vol),
            "gamma": PhysicalSeries("MISSING", "fred", "volume", "missing", None, "no key"),
        },
        cpi=PhysicalSeries("CPIAUCSL", "fred", "?", "ok", cpi),
    )


def test_panel_index_level_and_wide() -> None:
    panel = _synthetic_panel()
    P = panel.index_level("ew")
    assert list(P.columns) == sorted(THEMES)
    assert (P.iloc[-1] > 0).all()
    assert set(PANEL_COLUMNS) <= set(panel.frame.columns)
    with pytest.raises(KeyError):
        panel.wide("nope")


def test_grid_dates_adds_partial_month() -> None:
    g = grid_dates("2020-01-31", "2020-03-15")
    assert list(map(str, g["me"])) == ["2020-01-31", "2020-02-29", "2020-03-15"]
    assert list(map(str, g["bucket"])) == ["2020-01-31", "2020-02-29", "2020-03-31"]
    g2 = grid_dates("2020-01-31", "2020-03-31")
    assert len(g2) == 3 and str(g2["me"].iloc[-1]) == "2020-03-31"


def test_pipeline_shapes_flags_and_weights(themes: ThemeSet) -> None:
    panel = _synthetic_panel()
    fund = _synthetic_fund()
    ind = compute_indicators(panel, fund, _physical(), themes, compute_vcp=True)
    m = ind.monthly
    assert m.index.names == ["date", "theme"]
    for b, names in BLOCK_INDICATORS.items():
        for n in names:
            assert n in m.columns, (b, n)
    last = ind.at(pd.Timestamp("2016-12-30"))
    assert set(last.index) == set(THEMES)
    # 축 1 상태가 선언/데이터 유무로 갈린다
    assert last.loc["alpha", "axis1_status"] == "ok_fallback"
    assert last.loc["beta", "axis1_status"] == "ok_external"
    assert last.loc["gamma", "axis1_status"] == "data_missing"
    assert last.loc["delta", "axis1_status"] == "not_declared"
    assert last.loc["beta", "verdict_post_ss"] == "cycle"  # 선형 증가 물량
    assert np.isnan(last.loc["delta", "unit_cagr_10y"])
    # 서프라이즈·리비전은 계산하지 않는다 (없는 데이터) — NaN 이되 열은 있다
    assert m["surprise_dir"].isna().all()
    # 브레드스·VCP 가 값을 갖는다
    assert last["breadth_200"].notna().all()
    assert last["vcp_index"].notna().all()

    sb = build_scoreboard(
        ind,
        themes,
        pd.Timestamp("2016-12-30"),
        n_live=pd.Series({"alpha": 3, "beta": 20, "gamma": 20, "delta": 20}),
    )
    t = sb.table
    assert list(t["rank"].dropna().astype(int)) == [1, 2, 3, 4]
    assert t["score"].between(0, 1).all()
    for b in BLOCKS:
        assert t[f"{b}_pct"].between(0, 1).all()
    # 가중합 재현: score = Σ w × block_pct (블록 전부 있을 때)
    for _tid, r in t.iterrows():
        w = BLOCK_WEIGHTS[r["cycle_class"]]
        if not r["blocks_missing"]:
            assert r["score"] == pytest.approx(sum(w[b] * r[f"{b}_pct"] for b in BLOCKS))
    assert t.loc["alpha", "small_sample"]
    assert "소표본" in t.loc["alpha", "flags"]
    assert t.loc["beta", "secular"] and "SECULAR" in t.loc["beta", "flags"]
    assert "axis1:ok_fallback" in t.loc["alpha", "flags"]
    assert "axis1:data_missing" in t.loc["gamma", "flags"]
    assert "no_etf_proxy" in t.loc["beta", "flags"]
    # top_k 는 소표본을 뒤로
    assert sb.top_k(1).index[0] != "alpha"
    # 점수에 들어간 지표 백분위 표
    assert set(sb.indicator_pct.columns) <= {i for v in SCORED.values() for i in v}
    # 렌더
    txt = sb.render()
    assert "테마 스코어보드" in txt and "alpha" in txt


def test_missing_block_renormalizes_weights(themes: ThemeSet) -> None:
    panel = _synthetic_panel()
    fund = _synthetic_fund()
    ind = compute_indicators(panel, fund, _physical(), themes, compute_vcp=False)
    # F 블록 지표를 전부 지우면 F 없이 재정규화돼야 한다
    m = ind.monthly.copy()
    for c in SCORED["F"]:
        m[c] = np.nan
    from msa.l1.blocks import Indicators

    sb = build_scoreboard(Indicators(monthly=m), themes, pd.Timestamp("2016-12-30"))
    t = sb.table
    assert (t["blocks_missing"] == "F").all()
    for _tid, r in t.iterrows():
        w = BLOCK_WEIGHTS[r["cycle_class"]]
        num = sum(w[b] * r[f"{b}_pct"] for b in BLOCKS if b != "F")
        den = sum(w[b] for b in BLOCKS if b != "F")
        assert r["score"] == pytest.approx(num / den)
    assert "blocks_missing=F" in t["flags"].iloc[0]


def test_scoreboard_history_stacks_all_month_ends(themes: ThemeSet) -> None:
    panel = _synthetic_panel()
    fund = _synthetic_fund()
    ind = compute_indicators(panel, fund, _physical(), themes, compute_vcp=False)
    hist = scoreboard_history(ind, themes)
    assert hist.index.names == ["date", "theme"]
    n_dates = ind.monthly.index.get_level_values("date").nunique()
    assert len(hist) == n_dates * len(THEMES)
    assert {"score", "cycle_class", *BLOCKS} <= set(hist.columns)
