"""L3 — 실제 스토어가 필요한 부분 (`@pytest.mark.data`)."""

from __future__ import annotations

import pytest

from msa.l3.contracts import members_from_store
from msa.themes import load_themes


@pytest.mark.data
def test_members_from_store_uranium(store) -> None:  # type: ignore[no-untyped-def]
    themes = load_themes()
    rows = members_from_store(store, "uranium", themes, "2026-08-14", top_n=5)
    assert 1 <= len(rows) <= 5
    assert rows[0].mcap is not None and rows[0].mcap > 0
    assert all(r.ticker for r in rows)
    # 시총 내림차순
    m = [r.mcap for r in rows if r.mcap is not None]
    assert m == sorted(m, reverse=True)
