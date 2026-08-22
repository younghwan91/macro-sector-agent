"""`Store` 의 일반 질의 표면(`query`·`temp_tables`·`latest_mcap`·`store_end`·…)과 ETF 헬퍼.

순수 부분은 DuckDB 없이 돈다. `@pytest.mark.data` 는 실제 스토어에서 **옛 구현과 같은 답**인지
본다 — `latest_mcap` 의 `arg_max` 는 `row_number() … = 1` 과, `tickers_with_prices` 는 `prices()`
전체 행과.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from msa.data.store import (
    ETF_COLUMNS,
    PRICE_COLUMNS,
    SchemaDrift,
    Store,
    _in_clause,
    empty_etf_frame,
    etf_prices,
    etf_prices_or_empty,
    etf_series,
)

# ---------------------------------------------------------------- 순수


def test_in_clause_builds_placeholders() -> None:
    assert _in_clause("ticker", ["A", "B", "C"]) == ("ticker in (?,?,?)", ["A", "B", "C"])


def test_empty_etf_frame_and_series_helper() -> None:
    e = empty_etf_frame()
    assert list(e.columns) == list(ETF_COLUMNS) and e.empty
    df = pd.DataFrame(
        {
            "ticker": ["GLD", "GLD", "GDX"],
            "date": [pd.Timestamp("2024-01-03").date(), pd.Timestamp("2024-01-02").date(), None],
            "close": [1.0, 2.0, 3.0],
            "closeadj": [1.5, 2.5, float("nan")],
            "volume": [1.0, 1.0, 1.0],
        }
    )
    s = etf_series(df, "gld")
    assert s is not None and s.index.is_monotonic_increasing and s.tolist() == [2.5, 1.5]
    assert etf_series(df, "GDX") is not None and etf_series(df, "GDX").empty  # type: ignore[union-attr]
    assert etf_series(df, "URA") is None


def test_etf_prices_or_empty_returns_empty_frame_when_bulk_missing(tmp_path: Path) -> None:
    df = etf_prices_or_empty(["GLD"], raw_dir=tmp_path, cache_dir=tmp_path / "c")
    assert list(df.columns) == list(ETF_COLUMNS) and df.empty


def _make_funds_zip(path: Path) -> None:
    rows = [
        ["ticker", "date", "lastupdated", "open", "close", "closeadj", "volume"],
        ["GLD", "2024-01-03", "x", "1", "10.5", "10.1", "100"],
        ["GLD", "2024-01-02", "x", "1", "10.0", "9.9", "200"],
        ["XYZ", "2024-01-02", "x", "1", "1", "1", "1"],
        ["GDX", "2024-01-02", "x", "1", "", "abc", "5"],
    ]
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    (path / "raw").mkdir(parents=True)
    with zipfile.ZipFile(path / "raw" / "funds.csv.zip", "w") as zf:
        zf.writestr("funds.csv", buf.getvalue())


def test_etf_prices_pyarrow_scan_shape_and_side_cache(tmp_path: Path) -> None:
    _make_funds_zip(tmp_path)
    cdir = tmp_path / "cache"
    df = etf_prices(["gld", "GDX"], min_rows=1, raw_dir=tmp_path, cache_dir=cdir)
    assert list(df.columns) == list(ETF_COLUMNS)
    assert df["ticker"].tolist() == ["GDX", "GLD", "GLD"]  # ticker, date 오름차순
    assert [str(d) for d in df["date"]] == ["2024-01-02", "2024-01-02", "2024-01-03"]
    assert pd.isna(df.loc[0, "close"]) and pd.isna(df.loc[0, "closeadj"])  # 빈칸·문자 → NaN
    assert df["volume"].tolist() == [5.0, 200.0, 100.0]
    cached = list(cdir.glob("etf_*.parquet"))
    assert len(cached) == 1
    # 두 번째 호출은 캐시 — 같은 프레임
    df2 = etf_prices(["GDX", "GLD"], min_rows=1, raw_dir=tmp_path, cache_dir=cdir)
    pd.testing.assert_frame_equal(df, df2)
    # 다른 티커 집합은 다른 캐시 파일
    etf_prices(["GLD"], min_rows=1, raw_dir=tmp_path, cache_dir=cdir)
    assert len(list(cdir.glob("etf_*.parquet"))) == 2
    # 없는 티커만 요청 — 빈 프레임, min_rows=0 이면 통과
    assert etf_prices(["NOPE"], min_rows=0, raw_dir=tmp_path, cache_dir=cdir).empty


def test_etf_prices_header_drift_is_refused(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    with zipfile.ZipFile(tmp_path / "raw" / "funds.csv.zip", "w") as zf:
        zf.writestr("funds.csv", "ticker,date,close\nGLD,2024-01-02,1\n")
    with pytest.raises(SchemaDrift, match="closeadj"):
        etf_prices(["GLD"], min_rows=0, raw_dir=tmp_path, cache_dir=tmp_path / "c")


# ---------------------------------------------------------------- 실제 스토어


@pytest.mark.data
def test_store_end_and_columns_cache(store: Store) -> None:
    se = store.store_end()
    assert se is not None and str(se) >= "2026-01-01"
    assert store.columns("prices") == list(PRICE_COLUMNS) or set(PRICE_COLUMNS) <= set(
        store.columns("prices")
    )
    assert store.columns("prices") is not store._columns["prices"]  # 복사본을 돌려준다


@pytest.mark.data
def test_latest_mcap_equals_row_number_version(store: Store) -> None:
    tickers = ["AAPL", "MSFT", "NVDA", "GDX", "ZZZZNOPE"]
    new = store.latest_mcap(tickers)
    old = store.query(
        "select ticker, mcap from (select ticker, mcap, row_number() over "
        "(partition by ticker order by date desc) rn from prices "
        "where mcap is not null and ticker in (?,?,?,?,?)) where rn = 1 order by ticker",
        tickers,
    )
    assert new.index.tolist() == old["ticker"].tolist()
    assert new.to_numpy().tolist() == old["mcap"].tolist()
    assert "ZZZZNOPE" not in new.index and "GDX" not in new.index  # ETF 는 prices 에 없다
    # asof 컷
    asof = store.latest_mcap(["AAPL"], asof="2020-12-31")
    assert asof.loc["AAPL"] < new.loc["AAPL"]


@pytest.mark.data
def test_tickers_with_prices_equals_full_price_pull(store: Store) -> None:
    tickers = ["AAPL", "ENRN", "LEHMQ", "ZZZZNOPE"]
    have = store.tickers_with_prices(tickers, "2010-01-01", "2026-12-31")
    px = store.prices(tickers, "2010-01-01", "2026-12-31", min_rows=0)
    assert have == set(px["ticker"].unique())
    assert store.tickers_with_prices([], None, None) == set()


@pytest.mark.data
def test_close_series_and_prices_projection(store: Store) -> None:
    s = store.close_series("AAPL", "2024-01-01", "2024-01-31")
    assert s.name == "AAPL" and isinstance(s.index, pd.DatetimeIndex) and len(s) >= 15
    df = store.prices(
        ["AAPL"], "2024-01-01", "2024-01-31", min_rows=1, columns=["ticker", "date", "close"]
    )
    assert list(df.columns) == ["ticker", "date", "close"]
    assert df["close"].tolist() == s.tolist()
    with pytest.raises(SchemaDrift):
        store.prices(["AAPL"], min_rows=0, columns=["ticker", "nope"])


@pytest.mark.data
def test_query_with_frames_registers_and_unregisters(store: Store) -> None:
    m = pd.DataFrame({"ticker": ["AAPL", "MSFT"]})
    df = store.query(
        "select count(distinct ticker) as n from prices join m using (ticker)", frames={"m": m}
    )
    assert int(df["n"].iloc[0]) == 2
    with pytest.raises(Exception):  # noqa: B017 — 뷰가 해제됐다는 것만 본다
        store.query("select * from m")


@pytest.mark.data
def test_etf_prices_new_scan_matches_csv_reader_oracle(tmp_path: Path) -> None:
    """pyarrow 배치 스캔 == 옛 `csv.reader` 한 줄씩 스캔 (같은 zip, 같은 티커)."""
    from msa.config import paths

    base = paths().sharadar_raw
    zip_path = next(
        (p for p in (base / "raw" / "funds.csv.zip", base / "funds.csv.zip") if p.exists()), None
    )
    if zip_path is None:
        pytest.skip("funds.csv.zip 없음")
    want = {"GLD", "SIL"}
    new = etf_prices(sorted(want), min_rows=1, cache_dir=tmp_path)
    rows = []
    with (
        zipfile.ZipFile(zip_path) as zf,
        zf.open(next(n for n in zf.namelist() if n.endswith(".csv"))) as raw,
    ):
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
        header = next(reader)
        idx = {c: i for i, c in enumerate(header)}
        cols = [idx[c] for c in ETF_COLUMNS]
        for row in reader:
            if row and row[0] in want:
                rows.append(tuple(row[i] for i in cols))
    old = pd.DataFrame(rows, columns=list(ETF_COLUMNS))
    old["date"] = pd.to_datetime(old["date"]).dt.date
    for c in ("close", "closeadj", "volume"):
        old[c] = pd.to_numeric(old[c], errors="coerce")
    old = old.sort_values(["ticker", "date"], ignore_index=True)
    pd.testing.assert_frame_equal(new, old)
