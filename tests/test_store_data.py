"""실제 DuckDB 스토어에 대한 통합 테스트.

`@pytest.mark.data` — CI 에는 스토어가 없으므로 `-m "not data"` 로 제외된다.
여기 적힌 상수는 **M1 실측값**이며, `docs/08` §6.1 이 경고했듯 고정 상수가 아니다.
그래서 등호가 아니라 **하한**으로 쓴다 — 벤더 벌크가 늘어나도 깨지지 않고,
줄어들면(=조용한 절단) 깨진다.
"""

from __future__ import annotations

from datetime import date

import pytest

from msa.data.store import (
    ETF_IN_STORE,
    KNOWN_TABLES,
    SchemaDrift,
    ShortRead,
    Store,
    etf_prices,
)
from msa.data.universe import audit_delisted_included, common_stock

pytestmark = pytest.mark.data


def test_schema_matches_measured_reality(store: Store) -> None:
    cols = set(store.columns("prices"))
    # 문서 §2 는 SEP 의 closeadj / DAILY 의 marketcap 을 말한다. 실제 스토어는 병합돼 있고
    # 이름도 다르다 — 코드가 실제에 맞춰져 있음을 여기서 못박는다.
    assert {"close", "closeunadj", "mcap", "ev"} <= cols
    assert "closeadj" not in cols
    assert "marketcap" not in cols
    assert "daily" not in KNOWN_TABLES

    tcols = set(store.columns("tickers"))
    assert "is_delisted" in tcols  # 문서는 isdelisted 로 적었다
    assert "isdelisted" not in tcols
    assert not {"sicsector", "firstpricedate", "lastpricedate"} & tcols


def test_bulk_scale_no_silent_truncation(store: Store) -> None:
    stats = {s.name: s for s in store.table_stats()}
    px = stats["prices"]
    assert px.rows >= 45_000_000
    assert px.tickers is not None and px.tickers >= 20_000
    assert px.start is not None and px.start <= date(1997, 12, 31)
    assert stats["tickers"].rows >= 43_000
    assert stats["fundamentals"].rows >= 650_000
    assert stats["actions"].rows >= 660_000
    # estimates 는 0행이다 — '비었다' 가 아니라 '적재되지 않았다' 로 보고돼야 한다.
    assert stats["estimates"].rows == 0
    assert stats["estimates"].loaded is False


def test_marketcap_is_dollars_not_millions(store: Store) -> None:
    """`docs/08` §2 의 단위 함정. **환산은 적재 시점에 이미 끝났다.**

    원본 daily.csv 의 `AAPL,2026-08-12,marketcap=4411090.9`(백만 달러)가
    스토어에서는 4.4110909e12(달러)다. 코드가 여기서 다시 10⁶ 을 곱하면
    그때부터 왜곡이 시작된다.
    """
    df = store.prices(["AAPL"], start="2026-08-12", end="2026-08-12", min_rows=1)
    mcap = float(df["mcap"].iloc[0])
    assert mcap == pytest.approx(4_411_090_900_000.0, rel=1e-6)
    assert 1e12 < mcap < 1e13  # 달러라면 조 단위, 백만 달러라면 백만 단위였을 것


def test_close_is_split_adjusted_and_closeunadj_is_not(store: Store) -> None:
    """NVDA 2024-06-10 10:1 분할. `close` 는 조정본, `closeunadj` 가 원가다.

    비율이 정확히 10.0 이 아니라 10.017 인 것이 중요하다 — 배당까지 재투자 조정된
    `closeadj` 라는 뜻이다. 분할만 조정된 값이면 정확히 10.0 이 나왔을 것이다.
    """
    df = store.prices(["NVDA"], start="2024-06-06", end="2024-06-06", min_rows=1)
    row = df.iloc[0]
    assert float(row["close"]) == pytest.approx(120.793, rel=1e-4)
    assert float(row["closeunadj"]) == pytest.approx(1209.98, rel=1e-4)
    ratio = float(row["closeunadj"]) / float(row["close"])
    assert ratio == pytest.approx(10.0, rel=5e-3)
    assert ratio > 10.0


def test_short_read_raises_instead_of_returning_empty(store: Store) -> None:
    with pytest.raises(ShortRead):
        store.prices(["NO_SUCH_TICKER_XYZ"], min_rows=1)


def test_delisted_ticker_history_is_preserved(store: Store) -> None:
    """생존 편향 방지 (`docs/01` §5). 폐지 종목도 자기 이력 구간에 있어야 한다."""
    meta = store.tickers_meta(min_rows=1)
    delisted = meta.loc[meta["is_delisted"] == "Y", "ticker"]
    assert len(delisted) >= 18_000
    df = store.prices(delisted.head(50).tolist(), min_rows=1)
    assert df["ticker"].nunique() >= 25


def test_tickers_meta_does_not_filter_by_default(store: Store) -> None:
    """기본값으로 조용히 거르지 않는다 — 우선주도 ETF 메타도 그대로 나온다."""
    meta = store.tickers_meta(min_rows=40_000)
    cats = set(meta["category"].dropna())
    assert {"Domestic Preferred Stock", "ETF", "Institutional Investor"} <= cats
    only = store.tickers_meta(["Domestic Common Stock"], min_rows=10_000)
    assert set(only["category"]) == {"Domestic Common Stock"}
    assert len(only) < len(meta)


def test_common_stock_universe_size_and_exclusion_accounting(store: Store) -> None:
    res = common_stock(store.tickers_meta(min_rows=40_000))
    assert res.kept >= 19_000
    assert res.excluded == res.total_in - res.kept
    assert sum(res.excluded_by_category.values()) == res.excluded
    # Institutional Investor 13,230 이 tickers 안에 섞여 있다 — is_delisted NULL 30% 의 정체.
    assert res.excluded_by_category["Institutional Investor"] >= 13_000


def test_fundamentals_averages_are_all_null_as_documented(store: Store) -> None:
    """`docs/08` §2 의 "ARQ 에서 전부 null" 은 실측에서 그대로 확인됐다."""
    rates = store.null_rates("fundamentals", ["assetsavg", "equityavg", "invcapavg"])
    assert all(r == 1.0 for r in rates.values())


def test_fundamentals_only_arq_dimension(store: Store) -> None:
    df = store.fundamentals(["AAPL"], fields=["revenue", "capex"], min_rows=20)
    assert set(df["dimension"]) == {"ARQ"}
    assert {"datekey", "calendardate"} <= set(df.columns)
    assert df["datekey"].is_monotonic_increasing


def test_fundamentals_unknown_field_raises(store: Store) -> None:
    """`roic`·`pb` 는 문서가 SF1 필드로 적었지만 스토어에 없다 — 조용히 빠지면 안 된다."""
    with pytest.raises(SchemaDrift, match="roic"):
        store.fundamentals(["AAPL"], fields=["roic"], min_rows=0)


def test_short_interest_is_entirely_unloaded(store: Store) -> None:
    """컬럼은 있고 값은 100% null. 있는 줄 알고 쓰면 L4 토크 축이 조용히 빈다."""
    assert store.null_rates("prices", ["short_interest"])["short_interest"] == 1.0


def test_actions_kinds_present_for_capital_cycle(store: Store) -> None:
    from msa.data.store import ENTRY_ACTIONS, EXIT_ACTIONS

    df = store.actions(kinds=list(EXIT_ACTIONS + ENTRY_ACTIONS), min_rows=40_000)
    got = set(df["action"])
    assert set(ENTRY_ACTIONS) <= got
    assert {"delisted", "bankruptcyliquidation", "acquisitionby"} <= got


def test_delisted_coverage_audit_over_common_stock(store: Store) -> None:
    cov = audit_delisted_included(store, "2010-01-01", "2026-08-14")
    assert cov.delisted_total >= 6_000
    assert cov.coverage >= 0.999
    # 펀드류는 prices 에 구조적으로 없다. 뺀 개수는 반환값에 남는다.
    assert cov.excluded_non_equity["ETF"] >= 1_900
    # 남은 누락은 TFSA(비상장 BDC) 뿐이어야 한다 — 늘어나면 실제 회귀다.
    assert cov.delisted_missing == ["TFSA"]


def test_only_spy_etf_lives_in_the_store(store: Store) -> None:
    """`docs/08` §6.2 의 "SPY 외 ETF 가 있는지" 에 대한 답: 없다."""
    assert ETF_IN_STORE == ("SPY",)
    store.prices(["SPY"], min_rows=7_000)
    for t in ("GDX", "SIL", "REMX", "URA", "LIT"):
        with pytest.raises(ShortRead):
            store.prices([t], min_rows=1)


def test_theme_etf_proxies_come_from_bulk_funds_zip() -> None:
    """`docs/01` 의 ETF 프록시는 벌크 funds.csv.zip 에 있다. zip 1회 통과 — 약 12초."""
    df = etf_prices(["GDX", "SIL", "REMX", "URA", "LIT", "COPX"], min_rows=20_000)
    assert set(df["ticker"]) == {"GDX", "SIL", "REMX", "URA", "LIT", "COPX"}
    # docs/01 §1: URA·REMX·SIL·LIT 는 2010년 상장이라 사이클 한 바퀴가 안 담긴다.
    assert df.loc[df["ticker"] == "URA", "date"].min() >= date(2010, 1, 1)
    assert df.loc[df["ticker"] == "GDX", "date"].min() <= date(2006, 12, 31)
    assert df["close"].notna().all()
