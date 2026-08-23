"""합성 데이터로 패널 → 지표 → 스코어보드를 끝까지 돌린다 (스토어 없음).

목적은 수치의 정확성이 아니라 **모양·결측·가중치 재정규화·플래그**가 설계대로 나오는지다.
벡터화한 `scoreboard_history` 는 월말별 `build_scoreboard` 루프(`_ref_scoreboard_history`)와
비트 단위로 같아야 한다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from _synth_l1 import (
    physical_refs_for,
    pipeline_panel,
    synthetic_fund,
    synthetic_physical,
    theme_record,
    write_panel_cache,
    write_themes,
)
from msa.data.store import StoreError
from msa.l1.blocks import BLOCK_INDICATORS, Indicators, compute_indicators
from msa.l1.fundamentals import FundPanel, grid_dates
from msa.l1.panel import PANEL_COLUMNS, ThemePanel, load_cached_panel
from msa.l1.scan import scan_dirs
from msa.l1.scoreboard import (
    BLOCKS,
    SCORED,
    TIMING_BLOCKS,
    build_scoreboard,
    render_flags,
    scoreboard_history,
)
from msa.themes import BLOCK_WEIGHTS, ThemeSet

THEMES = ["alpha", "beta", "gamma", "delta"]
CLASSES = ["commodity_supply", "secular_growth", "credit_rate", "commodity_supply"]


@pytest.fixture(scope="module")
def themes(tmp_path_factory: pytest.TempPathFactory) -> ThemeSet:
    refs = physical_refs_for(THEMES)
    recs = [
        theme_record(tid, cc, i, etf_proxy="GDX" if i == 0 else None, physical_ref=refs[i])
        for i, (tid, cc) in enumerate(zip(THEMES, CLASSES, strict=True))
    ]
    return write_themes(tmp_path_factory.mktemp("themes"), recs)


@pytest.fixture(scope="module")
def panel() -> ThemePanel:
    return pipeline_panel(THEMES)


@pytest.fixture(scope="module")
def fund() -> FundPanel:
    return synthetic_fund(THEMES)


@pytest.fixture(scope="module")
def ind(panel: ThemePanel, fund: FundPanel, themes: ThemeSet) -> Indicators:
    return compute_indicators(panel, fund, synthetic_physical(THEMES), themes, compute_vcp=True)


@pytest.fixture(scope="module")
def ind_novcp(panel: ThemePanel, fund: FundPanel, themes: ThemeSet) -> Indicators:
    return compute_indicators(panel, fund, synthetic_physical(THEMES), themes, compute_vcp=False)


def test_panel_index_level_and_wide(panel: ThemePanel) -> None:
    P = panel.index_level("ew")
    assert list(P.columns) == sorted(THEMES)
    assert (P.iloc[-1] > 0).all()
    assert set(PANEL_COLUMNS) <= set(panel.frame.columns)
    # wide() 는 한 번 unstack 한 것을 잘라 준다 — 열별 unstack 과 같다
    for c in ("ret_ew", "n_listed"):
        pd.testing.assert_frame_equal(
            panel.wide(c), panel.frame[c].unstack("theme").sort_index(), check_exact=True
        )
    assert panel.index_level("ew") is panel.index_level("ew")  # 가중 방식별 1회 계산
    with pytest.raises(KeyError):
        panel.wide("nope")


def test_panel_cache_roundtrip(panel: ThemePanel, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    with pytest.raises(StoreError):
        load_cached_panel(cache)
    write_panel_cache(panel, cache, fingerprint="aaaa000000000000")
    loaded = load_cached_panel(cache, "aaaa000000000000")
    pd.testing.assert_frame_equal(loaded.frame, panel.frame)
    pd.testing.assert_frame_equal(loaded.spy, panel.spy, check_freq=False)
    assert loaded.built_from["fingerprint"] == "aaaa000000000000"
    # 지문을 안 주면 가장 최근 것
    write_panel_cache(panel, cache, fingerprint="bbbb000000000000")
    assert load_cached_panel(cache).built_from["fingerprint"] == "bbbb000000000000"
    # 불완전한 캐시(메타 없음)는 거부
    (cache / "l1_panel_bbbb000000000000.json").unlink()
    with pytest.raises(StoreError):
        load_cached_panel(cache, "bbbb000000000000")


def test_fund_wide_selects_from_three_tables(fund: FundPanel) -> None:
    pd.testing.assert_frame_equal(
        fund.wide("ss10_n"), fund.same_store["ss10_n"].unstack("theme").sort_index()
    )
    pd.testing.assert_frame_equal(
        fund.wide("exits_36m"), fund.actions["exits_36m"].unstack("theme").sort_index()
    )
    with pytest.raises(KeyError):
        fund.wide("nope")


def test_grid_dates_adds_partial_month() -> None:
    g = grid_dates("2020-01-31", "2020-03-15")
    assert list(map(str, g["me"])) == ["2020-01-31", "2020-02-29", "2020-03-15"]
    assert list(map(str, g["bucket"])) == ["2020-01-31", "2020-02-29", "2020-03-31"]
    g2 = grid_dates("2020-01-31", "2020-03-31")
    assert len(g2) == 3 and str(g2["me"].iloc[-1]) == "2020-03-31"


def test_pipeline_shapes_flags_and_weights(themes: ThemeSet, ind: Indicators) -> None:
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
    assert t.columns[0] == "rank"
    # 2026-08-23 S2 채택: 순위는 자격(pool ≥ 0.5) 테마만 — 자격 수만큼 1..n, 나머지 NaN
    n_elig = int(t["eligible"].sum())
    assert list(t["rank"].dropna().astype(int)) == list(range(1, n_elig + 1))
    assert t.loc[~t["eligible"], "score"].isna().all()
    assert t.loc[t["eligible"], "score"].between(0, 1).all()
    assert t["score_s0"].between(0, 1).all()
    for b in BLOCKS:
        assert t[f"{b}_pct"].between(0, 1).all()
    # 집계 재현 (블록 전부 있을 때): pool = mean(A,B) · score = Σ_{C,E,F} w·pct / Σw ·
    # score_s0 = 6블록
    for _tid, r in t.iterrows():
        w = BLOCK_WEIGHTS[r["cycle_class"]]
        if not r["blocks_missing"]:
            assert r["pool"] == pytest.approx((r["A_pct"] + r["B_pct"]) / 2)
            assert r["score_s0"] == pytest.approx(sum(w[b] * r[f"{b}_pct"] for b in BLOCKS))
            if r["eligible"]:
                num = sum(w[b] * r[f"{b}_pct"] for b in TIMING_BLOCKS)
                den = sum(w[b] for b in TIMING_BLOCKS)
                assert r["score"] == pytest.approx(num / den)
            else:
                assert "풀 미달" in r["flags"]
    assert t.loc["alpha", "small_sample"]
    assert "소표본" in t.loc["alpha", "flags"]
    assert t.loc["beta", "secular"] and "SECULAR" in t.loc["beta", "flags"]
    assert "axis1:ok_fallback" in t.loc["alpha", "flags"]
    assert "axis1:data_missing" in t.loc["gamma", "flags"]
    assert "no_etf_proxy" in t.loc["beta", "flags"]
    # flags 는 구조화 열에서 다시 만들 수 있는 표시 전용 파생값
    assert (t.apply(render_flags, axis=1) == t["flags"]).all()
    # top_k 는 소표본을 뒤로
    assert sb.top_k(1).index[0] != "alpha"
    # 점수에 들어간 지표 백분위 표
    assert set(sb.indicator_pct.columns) <= {i for v in SCORED.values() for i in v}
    # 렌더
    txt = sb.render()
    assert "테마 스코어보드" in txt and "alpha" in txt


def test_missing_block_renormalizes_weights(themes: ThemeSet, ind_novcp: Indicators) -> None:
    # F 블록 지표를 전부 지우면 F 없이 재정규화돼야 한다
    m = ind_novcp.monthly.copy()
    for c in SCORED["F"]:
        m[c] = np.nan
    sb = build_scoreboard(Indicators(monthly=m), themes, pd.Timestamp("2016-12-30"))
    t = sb.table
    assert (t["blocks_missing"] == "F").all()
    for _tid, r in t.iterrows():
        w = BLOCK_WEIGHTS[r["cycle_class"]]
        num = sum(w[b] * r[f"{b}_pct"] for b in BLOCKS if b != "F")
        den = sum(w[b] for b in BLOCKS if b != "F")
        assert r["score_s0"] == pytest.approx(num / den)
        if r["eligible"]:
            num_t = sum(w[b] * r[f"{b}_pct"] for b in TIMING_BLOCKS if b != "F")
            den_t = sum(w[b] for b in TIMING_BLOCKS if b != "F")
            assert r["score"] == pytest.approx(num_t / den_t)
    assert "blocks_missing=F" in t["flags"].iloc[0]


def _ref_scoreboard_history(ind: Indicators, themes: ThemeSet) -> pd.DataFrame:
    """구 구현 — 월말마다 `build_scoreboard` 를 불러 쌓는다."""
    frames = []
    for d in ind.dates:
        sb = build_scoreboard(ind, themes, d)
        t = sb.table[
            [
                "score",
                "score_s0",
                "pool",
                "eligible",
                "cycle_class",
                *BLOCKS,
                *[f"{b}_pct" for b in BLOCKS],
            ]
        ].copy()
        t["date"] = d
        frames.append(t.reset_index())
    return pd.concat(frames, ignore_index=True).set_index(["date", "theme"]).sort_index()


def test_scoreboard_history_matches_per_month_loop(themes: ThemeSet, ind_novcp: Indicators) -> None:
    sub = Indicators(monthly=ind_novcp.monthly.loc["2016-01-31":])  # 월말 12개면 충분하다
    hist = scoreboard_history(sub, themes)
    assert hist.index.names == ["date", "theme"]
    assert len(hist) == sub.dates.nunique() * len(THEMES)
    assert {"score", "cycle_class", *BLOCKS} <= set(hist.columns)
    pd.testing.assert_frame_equal(hist, _ref_scoreboard_history(sub, themes), check_exact=True)


def test_scoreboard_history_exact_with_ties_and_nans(
    themes: ThemeSet, ind_novcp: Indicators
) -> None:
    """동률·결측이 섞여도 루프와 비트 단위로 같다 (합산 순서가 같아야 동률이 같은 쪽으로 깨진다)."""
    m = ind_novcp.monthly.loc["2016-01-31":].copy()
    # C 블록 지표(9개) 일부를 결측·동률로 만든다
    m.loc[(slice(None), "alpha"), "mom_13612w"] = np.nan
    m.loc[(slice(None), "beta"), "rs_slope"] = m.loc[(slice(None), "gamma"), "rs_slope"].to_numpy()
    m.loc["2016-06-30", "breadth_lead"] = 0.0
    sub = Indicators(monthly=m)
    pd.testing.assert_frame_equal(
        scoreboard_history(sub, themes), _ref_scoreboard_history(sub, themes), check_exact=True
    )


def test_scan_dirs_lists_dated_snapshots(tmp_path: Path) -> None:
    assert scan_dirs(tmp_path / "none") == []
    for name in ("2026-08-14", "2026-07-31", "latest", "2026-13-99"):
        (tmp_path / name).mkdir()
    (tmp_path / "2026-01-01.txt").write_text("x")
    got = scan_dirs(tmp_path)
    assert [str(d) for d, _ in got] == ["2026-07-31", "2026-08-14"]
    assert got[-1][1] == tmp_path / "2026-08-14"
