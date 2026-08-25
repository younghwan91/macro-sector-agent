"""스토어의 순수 부분 — WHERE 조립·기대치 가드. DuckDB 없이 돈다."""

from __future__ import annotations

import pandas as pd
import pytest

from msa.data.store import (
    ENTRY_ACTIONS,
    EXIT_ACTIONS,
    MCAP_UNIT_ALREADY_APPLIED,
    ShortRead,
    _guard,
    _ticker_date_where,
)


def test_where_no_filters() -> None:
    assert _ticker_date_where(None, None, None) == ("", [])


def test_where_tickers_uppercased_and_parameterised() -> None:
    """SQL 문자열 보간이 아니라 파라미터 바인딩이어야 한다."""
    where, params = _ticker_date_where(["aapl", "msft"], None, None)
    assert where == "where ticker in (?,?)"
    assert params == ["AAPL", "MSFT"]


def test_where_date_range_and_custom_column() -> None:
    where, params = _ticker_date_where(None, "2020-01-01", "2020-12-31", date_col="datekey")
    assert where == "where datekey >= ? and datekey <= ?"
    assert params == ["2020-01-01", "2020-12-31"]


def test_empty_ticker_list_is_an_error() -> None:
    """`[]` 를 '필터 없음' 으로 읽으면 0행이 조용히 전체가 된다 (또는 그 반대)."""
    with pytest.raises(ValueError, match="필터 없음"):
        _ticker_date_where([], None, None)


def test_guard_raises_below_min_rows() -> None:
    with pytest.raises(ShortRead, match="조용한 절단"):
        _guard(pd.DataFrame({"ticker": []}), "prices", min_rows=1)


def test_guard_passes_at_exactly_min_rows() -> None:
    _guard(pd.DataFrame({"ticker": ["A"]}), "prices", min_rows=1)


def test_guard_raises_when_too_few_distinct_tickers() -> None:
    df = pd.DataFrame({"ticker": ["A", "A", "A"]})
    with pytest.raises(ShortRead, match="종목"):
        _guard(df, "prices", min_rows=1, expect_tickers=2)


def test_guard_warns_but_does_not_raise_on_absent_requested(caplog) -> None:  # type: ignore[no-untyped-def]
    df = pd.DataFrame({"ticker": ["A"]})
    with caplog.at_level("WARNING"):
        _guard(df, "prices", min_rows=1, requested=["A", "ZZZZ"])
    assert "ZZZZ" in caplog.text


def test_mcap_unit_constant_documents_but_is_not_applied() -> None:
    """스토어의 mcap 은 이미 달러다. 이 상수는 '다시 곱하지 마라' 는 기록이다."""
    assert MCAP_UNIT_ALREADY_APPLIED == 1_000_000


def test_action_kind_constants_are_disjoint() -> None:
    assert not set(EXIT_ACTIONS) & set(ENTRY_ACTIONS)
    assert "delisted" in EXIT_ACTIONS
    assert "bankruptcyliquidation" in EXIT_ACTIONS
    assert ENTRY_ACTIONS == ("listed",)


def test_close_series_falls_back_to_bulk_for_store_etfs(monkeypatch: pytest.MonkeyPatch) -> None:
    """ETF 가 `prices` 에 있느냐는 스토어 빌드 방식에 달린 우연이다.

    2026-08-25 벌크 재빌드에서 SPY 가 0행이 되어 L1 패널과 L4 달력이 동시에 멈췄다.
    나머지 ETF 는 이미 벌크에서 읽고 있었으므로 SPY 만 스토어에 의존할 이유가 없다.
    """
    import pandas as pd

    from msa.data import store as S

    called: list[list[str]] = []

    def fake_etf(tickers, **_kw):  # type: ignore[no-untyped-def]
        called.append(list(tickers))
        return pd.DataFrame(
            {
                "ticker": ["SPY", "SPY"],
                "date": ["2026-08-20", "2026-08-21"],
                "close": [600.0, 601.0],
                "closeadj": [600.0, 601.0],
                "volume": [1e6, 1e6],
            }
        )

    monkeypatch.setattr(S, "etf_prices", fake_etf)
    got = S._etf_close_from_bulk("SPY", None, None)
    assert called == [["SPY"]]
    assert list(got["close"]) == [600.0, 601.0]

    # 구간 필터가 먹는다
    win = S._etf_close_from_bulk("SPY", "2026-08-21", None)
    assert list(win["close"]) == [601.0]


def test_bulk_fallback_returns_empty_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """벌크도 없으면 **빈 프레임**이다 — 호출자가 판단한다. 조용히 가짜를 만들지 않는다."""
    from msa.data import store as S

    def boom(*_a, **_kw):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("funds.csv.zip 없음")

    monkeypatch.setattr(S, "etf_prices", boom)
    assert S._etf_close_from_bulk("SPY", None, None).empty
