"""실물·가격 참조 시계열(`physical_ref`) 과 CPI 로더.

세 소스를 같은 형태(월말 `pd.Series`)로 돌려준다.

| source | 어디서 | 없으면 |
|---|---|---|
| `etf` | 벌크 `funds.csv.zip` (`msa.data.store.etf_prices`) | 벌크에 없으면 `missing` |
| `fred` | `state/physical/fred/<SYMBOL>.csv` 캐시. 없고 키가 있으면 받아서 캐시 | `missing` |
| `manual` | `state/physical/manual/<SYMBOL>.csv` (`date,value`) — 사람이 갱신 | `missing` |

**없는 것은 없다고 돌려준다.** `PhysicalSeries.status ∈ {ok, missing}` 이며 스코어보드는 이 값을
`axis1_data` 플래그로 그대로 내보낸다. 데이터가 없는 테마를 "축 1 없음" 으로 조용히 넘기지 않고,
"선언은 있으나 데이터가 없다" 로 구분해 적는다 — 그 둘은 다른 할 일이다
(전자는 `themes.yaml` 결정, 후자는 데이터 수집).

CPI(`CPIAUCSL`)는 `dd_real`(A 블록)과 `nominal` 종류 참조의 실질화에 쓴다. FRED 경로와 같다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from msa.config import paths
from msa.data.store import StoreError, etf_prices
from msa.themes import PhysicalRef, ThemeSet

log = logging.getLogger(__name__)

CPI_SERIES = "CPIAUCSL"


@dataclass(frozen=True)
class PhysicalSeries:
    symbol: str
    source: str
    kind: str
    status: str  # ok | missing
    series: pd.Series | None  # 월말 인덱스
    note: str = ""


def _physical_dir() -> Path:
    return paths().state / "physical"


def _read_csv_series(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    if "date" not in cols or "value" not in cols:
        raise StoreError(f"{path}: 컬럼은 date,value 여야 한다. 있는 것: {list(df.columns)}")
    s = pd.Series(
        pd.to_numeric(df[cols["value"]], errors="coerce").to_numpy(),
        index=pd.to_datetime(df[cols["date"]]),
    ).dropna()
    s = s.sort_index()
    if s.empty:
        raise StoreError(f"{path}: 값이 전부 결측이다")
    return s


def to_month_end(s: pd.Series) -> pd.Series:
    """임의 주기 → 월말 마지막 관측. 월 안에 관측이 없으면 NaN 으로 남긴다 (앞으로 채우지
    않는다)."""
    return s.resample("ME").last()


def fred_cache_path(symbol: str) -> Path:
    """`state/physical/fred/<SYMBOL>.csv` — L1(실물 참조·CPI)과 L2(드라이버)가 같은 캐시를 쓴다."""
    return _physical_dir() / "fred" / f"{symbol}.csv"


def read_fred_cache(symbol: str) -> pd.Series | None:
    """캐시된 FRED 시리즈를 **원래 주기 그대로** 읽는다. 캐시가 없으면 `None`."""
    cache = fred_cache_path(symbol)
    if not cache.exists():
        return None
    return _read_csv_series(cache)


def fetch_fred_to_cache(symbol: str, *, min_obs: int = 12) -> pd.Series:
    """FRED 에서 받아 캐시에 쓴다. 키가 없거나 실패하면 **예외를 그대로 올린다.**

    값 옆에 `<SYMBOL>.meta.json`(단위·주기·제목·받은 시각)을 남긴다 — 파생 드라이버
    (`usd_liquidity`)의 단위 환산이 선언과 맞는지 L2 가 대조할 재료다.
    """
    from msa.data.fred import FredClient

    cache = fred_cache_path(symbol)
    with FredClient() as c:
        obs = c.observations(symbol, min_obs=min_obs)
        try:
            meta = c.series_meta(symbol)
            meta_d: dict[str, object] = {
                "series_id": meta.series_id,
                "title": meta.title,
                "frequency": meta.frequency,
                "units": meta.units,
                "last_updated": meta.last_updated,
            }
        except Exception as e:  # 메타 실패는 값 캐시를 막지 않는다 — 그러나 기록한다
            meta_d = {"series_id": symbol, "meta_error": f"{type(e).__name__}: {e}"}
    s = pd.Series({pd.Timestamp(o.date): o.value for o in obs}).dropna().sort_index()
    cache.parent.mkdir(parents=True, exist_ok=True)
    dates = pd.DatetimeIndex(s.index).strftime("%Y-%m-%d")
    pd.DataFrame({"date": dates, "value": s.to_numpy()}).to_csv(cache, index=False)
    meta_d["fetched_at"] = pd.Timestamp.now().isoformat(timespec="seconds")
    meta_d["n_obs"] = len(s)
    cache.with_suffix(".meta.json").write_text(json.dumps(meta_d, ensure_ascii=False, indent=1))
    log.info("fred: %s 관측 %d개 캐시 → %s", symbol, len(s), cache)
    return s


def load_fred_series(symbol: str, *, allow_fetch: bool = True) -> PhysicalSeries:
    cache = fred_cache_path(symbol)
    cached = read_fred_cache(symbol)
    if cached is not None:
        return PhysicalSeries(
            symbol, "fred", "?", "ok", to_month_end(cached), f"cache {cache.name}"
        )
    if not allow_fetch:
        return PhysicalSeries(symbol, "fred", "?", "missing", None, f"캐시 없음 {cache}")
    try:
        s = fetch_fred_to_cache(symbol)
    except Exception as e:  # MissingApiKey · FredError · 네트워크
        return PhysicalSeries(symbol, "fred", "?", "missing", None, f"{type(e).__name__}: {e}")
    return PhysicalSeries(symbol, "fred", "?", "ok", to_month_end(s), "fetched+cached")


def load_manual_series(symbol: str) -> PhysicalSeries:
    path = _physical_dir() / "manual" / f"{symbol}.csv"
    if not path.exists():
        return PhysicalSeries(symbol, "manual", "?", "missing", None, f"파일 없음 {path}")
    return PhysicalSeries(
        symbol, "manual", "?", "ok", to_month_end(_read_csv_series(path)), path.name
    )


def load_etf_series(
    symbols: list[str], *, prefetched: pd.DataFrame | None = None
) -> dict[str, PhysicalSeries]:
    """벌크 zip 을 한 번만 훑어 여러 ETF 를 받는다 (`etf_prices` 는 통과 1회 ≈ 12초).

    `prefetched` 를 주면 (이미 받은 `etf_prices` 프레임) 다시 훑지 않는다.
    """
    out: dict[str, PhysicalSeries] = {}
    if not symbols:
        return out
    if prefetched is not None:
        df = prefetched
    else:
        try:
            df = etf_prices(symbols, min_rows=0)
        except StoreError as e:
            return {s: PhysicalSeries(s, "etf", "?", "missing", None, str(e)) for s in symbols}
    for sym in symbols:
        sub = df.loc[df["ticker"] == sym.upper()]
        if sub.empty:
            out[sym] = PhysicalSeries(sym, "etf", "?", "missing", None, "벌크에 없음")
            continue
        s = pd.Series(sub["closeadj"].to_numpy(), index=pd.to_datetime(sub["date"])).dropna()
        out[sym] = PhysicalSeries(sym, "etf", "?", "ok", to_month_end(s), f"{len(s)}행")
    return out


@dataclass(frozen=True)
class PhysicalBundle:
    refs: dict[str, PhysicalSeries]  # theme id → series
    cpi: PhysicalSeries

    def status_table(self, themes: ThemeSet) -> pd.DataFrame:
        rows = []
        for t in themes:
            if t.physical_ref is None:
                rows.append((t.id, None, None, None, "not_declared", ""))
                continue
            ps = self.refs.get(t.id)
            rows.append(
                (
                    t.id,
                    t.physical_ref.source,
                    t.physical_ref.symbol,
                    t.physical_ref.kind,
                    ps.status if ps else "missing",
                    ps.note if ps else "",
                )
            )
        return pd.DataFrame(
            rows, columns=["theme", "source", "symbol", "kind", "status", "note"]
        ).set_index("theme")


def load_physical(
    themes: ThemeSet, *, allow_fetch: bool = True, etf_prefetched: pd.DataFrame | None = None
) -> PhysicalBundle:
    """전 테마의 `physical_ref` 와 CPI 를 로드한다. 못 받은 것은 `missing` 으로 남는다."""
    etf_syms = sorted(
        {t.physical_ref.symbol for t in themes if t.physical_ref and t.physical_ref.source == "etf"}
    )
    etf = load_etf_series(etf_syms, prefetched=etf_prefetched)
    refs: dict[str, PhysicalSeries] = {}
    fred_cache: dict[str, PhysicalSeries] = {}
    for t in themes:
        ref: PhysicalRef | None = t.physical_ref
        if ref is None:
            continue
        if ref.source == "etf":
            base = etf[ref.symbol]
        elif ref.source == "fred":
            if ref.symbol not in fred_cache:
                fred_cache[ref.symbol] = load_fred_series(ref.symbol, allow_fetch=allow_fetch)
            base = fred_cache[ref.symbol]
        else:
            base = load_manual_series(ref.symbol)
        refs[t.id] = PhysicalSeries(
            base.symbol, base.source, ref.kind, base.status, base.series, base.note
        )
    cpi = load_fred_series(CPI_SERIES, allow_fetch=allow_fetch)
    n_ok = sum(1 for p in refs.values() if p.status == "ok")
    log.info(
        "physical: 선언 %d · 데이터 있음 %d · 없음 %d · CPI %s",
        len(refs),
        n_ok,
        len(refs) - n_ok,
        cpi.status,
    )
    return PhysicalBundle(refs=refs, cpi=cpi)
