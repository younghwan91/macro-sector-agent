"""L4 실데이터 스모크 — 실제 스토어 (`pytest -m data`)."""

from __future__ import annotations

import pandas as pd
import pytest

from msa.l4.features import build_features
from msa.l4.picks import rank_theme
from msa.themes import assign_members, load_themes

pytestmark = pytest.mark.data


def test_picks_rare_earth_smoke(store) -> None:  # type: ignore[no-untyped-def]
    themes = load_themes()
    ms = assign_members(themes, store.tickers_meta(min_rows=10_000))
    fs = build_features(store, themes.get("rare_earth"), ms, "2026-08-14", with_physical=False)
    assert fs.n_members >= 10
    assert 0 < fs.n_listed <= fs.n_members
    assert "MP" in fs.frame.index
    mp = fs.frame.loc["MP"]
    assert pd.notna(mp["cash_runway_q"]) and pd.notna(mp["rs_rating"])
    # PIT: 최신 분기 공시일이 asof 를 넘지 않는다
    assert (pd.to_datetime(fs.frame["fund_datekey"].dropna()) <= pd.Timestamp("2026-08-14")).all()
    ranking, excluded, bb = rank_theme(fs)
    assert len(ranking) + len(excluded) == fs.n_members
    assert "MP" in ranking.index
    assert bb.n <= 4
