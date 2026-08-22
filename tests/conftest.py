from __future__ import annotations

import pytest

from msa.config import paths


@pytest.fixture(scope="session")
def store():
    """실제 DuckDB 스토어. 없으면 스킵한다 — `@pytest.mark.data` 테스트에서만 쓴다."""
    from msa.data.store import Store

    p = paths().duckdb
    if not p.exists():
        pytest.skip(f"DuckDB 스토어 없음: {p}")
    with Store(p) as s:
        yield s
