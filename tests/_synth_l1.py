"""L1 테스트용 합성 재료 — 테마 정의·패널·재무 패널·실물 참조 (스토어 없음).

`test_l1_pipeline.py`·`test_l1_backtest.py`·`test_l1_blocks.py` 가 같이 쓴다.
수치의 "좋음" 이 아니라 **모양·결측·규약**을 검사하는 데이터다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from msa.l1.fundamentals import FUND_COLUMNS, FundPanel, grid_dates
from msa.l1.panel import PANEL_COLUMNS, ThemePanel, panel_from_frames
from msa.l1.physical import PhysicalBundle, PhysicalSeries
from msa.themes import ThemeSet, load_themes

# ---------------------------------------------------------------- 테마 정의


def theme_record(
    tid: str,
    cycle_class: str,
    i: int = 0,
    *,
    etf_proxy: str | None = None,
    physical_ref: dict[str, str] | None = None,
    min_constituents: int = 5,
) -> dict[str, Any]:
    """`state/themes.yaml` 한 항목 (`industry_match` 는 `Ind<i>` 하나)."""
    return {
        "id": tid,
        "name_ko": tid,
        "parent_sector": "X",
        "cycle_class": cycle_class,
        "industry_match": [f"Ind{i}"],
        "include_tickers": [],
        "exclude_tickers": [],
        "etf_proxy": etf_proxy,
        "etf_proxy_alt": [],
        "physical_ref": physical_ref,
        "correlation_cluster": None,
        "min_constituents": min_constituents,
    }


def write_themes(tmp_path: Path, recs: list[dict[str, Any]]) -> ThemeSet:
    p = tmp_path / "themes.yaml"
    p.write_text(yaml.safe_dump({"schema_version": 1, "defaults": {}, "themes": recs}))
    return load_themes(p)


# ---------------------------------------------------------------- 패널


def panel_from_returns(
    daily_ret: pd.DataFrame,
    spy_ret: pd.Series,
    *,
    n_listed: pd.DataFrame | None = None,
    extra: dict[str, pd.DataFrame] | None = None,
) -> ThemePanel:
    """일별 수익률 행렬(date × theme) → 패널. n_ret 은 수익률이 NaN 이면 0.

    `extra` 로 `dv`·`n_above200`·`n_nh6m` 같은 열을 (date × theme) 행렬로 덮어쓸 수 있다.
    행 루프 없이 전부 stack 으로 만든다."""
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
    )
    for k, v in (extra or {}).items():
        frame[k] = v.stack(future_stack=True).reindex(frame.index)
    frame = frame.sort_index()
    assert set(PANEL_COLUMNS) <= set(frame.columns)
    spy = pd.DataFrame({"close": 100 * (1 + spy_ret).cumprod(), "dv": 5e10}, index=days)
    return panel_from_frames(frame, spy)


def pipeline_panel(themes: list[str], seed: int = 1) -> ThemePanel:
    """파이프라인 테스트용 4테마 패널 (2010~2016, 드리프트·브레드스 패턴 포함)."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2010-01-01", "2016-12-30")
    i = np.arange(len(days))
    drifts = (-0.0004, 0.0005, 0.0001, -0.0002)
    ret = pd.DataFrame(
        {
            t: rng.normal(drifts[j % len(drifts)], 0.012, size=len(days))
            for j, t in enumerate(themes)
        },
        index=days,
    )
    nl = pd.DataFrame({t: 20 + j * 5 for j, t in enumerate(themes)}, index=days)
    above = pd.DataFrame(
        {
            t: np.where(i >= 200, (nl[t] * (0.3 + 0.4 * (np.sin(i / 120) > 0))).astype(int), 0)
            for t in themes
        },
        index=days,
    )
    sma = pd.DataFrame({t: np.where(i >= 200, nl[t], 0) for t in themes}, index=days)
    extra = {
        "ret_cw": ret * 0.9,
        "n_ret": nl - 1,
        "n_cw": nl - 2,
        "dv": pd.DataFrame({t: 1e7 * (1 + 0.2 * np.sin(i / 50)) for t in themes}, index=days),
        "n_sma200": sma,
        "n_above200": above,
        "n_nh6m": pd.DataFrame(
            rng.integers(0, 4, size=(len(days), len(themes))), index=days, columns=themes
        ),
        "n_nl6m": pd.DataFrame(
            rng.integers(0, 4, size=(len(days), len(themes))), index=days, columns=themes
        ),
    }
    spy_ret = pd.Series(rng.normal(0.0003, 0.01, size=len(days)), index=days)
    return panel_from_returns(ret, spy_ret, n_listed=nl, extra=extra)


def random_panel(
    themes: list[str], seed: int = 0, start: str = "2012-01-02", end: str = "2020-12-31"
) -> ThemePanel:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, end)
    ret = pd.DataFrame(
        rng.normal(0.0002, 0.01, (len(days), len(themes))), index=days, columns=themes
    )
    spy = pd.Series(rng.normal(0.0003, 0.008, len(days)), index=days)
    return panel_from_returns(ret, spy)


def write_panel_cache(
    panel: ThemePanel, cache_dir: Path, fingerprint: str = "deadbeef00000000"
) -> Path:
    """패널을 `cache_dir` 에 지문 캐시로 쓴다 (`ThemePanel.save`). 지문이 없으면 붙인다."""
    built = {**panel.built_from, "fingerprint": fingerprint, "store_end": "2016-12-30"}
    return ThemePanel(frame=panel.frame, spy=panel.spy, built_from=built).save(cache_dir).panel


# ---------------------------------------------------------------- 재무 패널·실물


def synthetic_fund(
    themes: list[str], seed: int = 2, start: str = "2010-01-31", end: str = "2016-12-30"
) -> FundPanel:
    rng = np.random.default_rng(seed)
    buckets = pd.to_datetime(grid_dates(start, end)["bucket"])
    idx = pd.MultiIndex.from_product([buckets, themes], names=["date", "theme"])
    n = len(idx)
    frame = pd.DataFrame({c: np.abs(rng.normal(10, 2, n)) + 1 for c in FUND_COLUMNS}, index=idx)
    j = np.array([themes.index(t) for t in idx.get_level_values("theme")])
    frame["n_reporting"] = 15 + j
    frame["n_ebitda_pos"] = 10
    frame["ebitda_nonpos_share"] = 0.3
    frame["ev_ebitda_med"] = 8 + rng.normal(size=n)
    frame["ev_sales_med"] = 2 + rng.normal(size=n) * 0.1
    frame["pb_med"] = 1.5 + rng.normal(size=n) * 0.1
    frame["fcf_yield_med"] = 0.05 + rng.normal(size=n) * 0.01
    frame["ev_replacement_med"] = 1.2
    frame = frame.sort_index()
    ss = pd.DataFrame(
        {
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
        },
        index=idx,
    ).sort_index()
    act = pd.DataFrame(
        {"exits_36m": 3.0, "entries_36m": 1.0, "exits_1m": 0.0, "entries_1m": 0.0},
        index=frame.index,
    )
    return FundPanel(frame=frame, same_store=ss, actions=act, built_from={"synthetic": True})


def synthetic_physical(themes: list[str]) -> PhysicalBundle:
    """첫 테마 = 가격 참조(ETF), 둘째 = 물량(수동), 셋째 = 결측(FRED), 나머지 = 선언 없음."""
    me = pd.date_range("2000-01-31", "2016-12-31", freq="ME")
    gld = pd.Series(np.linspace(50, 120, len(me)), index=me)
    vol = pd.Series(np.linspace(100, 130, len(me)), index=me)
    cpi = pd.Series(np.linspace(170, 240, len(me)), index=me)
    refs = {
        themes[0]: PhysicalSeries("GLD", "etf", "price", "ok", gld),
        themes[1]: PhysicalSeries("VOL", "manual", "volume", "ok", vol),
        themes[2]: PhysicalSeries("MISSING", "fred", "volume", "missing", None, "no key"),
    }
    return PhysicalBundle(refs=refs, cpi=PhysicalSeries("CPIAUCSL", "fred", "?", "ok", cpi))


def physical_refs_for(themes: list[str]) -> list[dict[str, str] | None]:
    """`synthetic_physical` 과 짝이 맞는 `physical_ref` 선언."""
    out: list[dict[str, str] | None] = [
        {"source": "etf", "symbol": "GLD", "kind": "price"},
        {"source": "manual", "symbol": "VOL", "kind": "volume"},
        {"source": "fred", "symbol": "MISSING", "kind": "volume"},
    ]
    return (out + [None] * len(themes))[: len(themes)]
