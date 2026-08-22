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

`load_ref(ref)` 가 한 `PhysicalRef` 를 `PhysicalSeries` 로 바꾸는 단일 진입점이다 — L1 의
`load_physical` 과 L4 의 `load_reference_series` 가 같은 함수를 쓴다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd

from msa.config import paths
from msa.data.store import StoreError, etf_prices, etf_series
from msa.dates import to_month_end
from msa.status import Axis1Status, SeriesStatus
from msa.themes import PhysicalRef, Theme, ThemeSet

log = logging.getLogger(__name__)

CPI_SERIES = "CPIAUCSL"


@dataclass(frozen=True)
class PhysicalSeries:
    symbol: str
    source: str
    kind: str = "?"  # 로더는 모른다 — `load_ref` 가 `PhysicalRef.kind` 로 채운다
    status: str = SeriesStatus.MISSING.value  # ok | missing
    series: pd.Series | None = None  # 월말 인덱스
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status == SeriesStatus.OK and self.series is not None


def _physical_dir() -> Path:
    return paths().physical


def read_date_value_csv(path: Path) -> pd.Series:
    """`date,value` CSV → 값 시리즈 (`DatetimeIndex`, 결측 제거, 오름차순). 컬럼명은 대소문자 무관.

    컬럼이 없거나 값이 전부 결측이면 `StoreError` — 빈 시리즈를 돌려주지 않는다 (`CLAUDE.md` §2).
    FRED 캐시·수동 CSV 가 같은 꼴이라 L1·L2 가 함께 쓴다.
    """
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


#: 이전 이름 — L2·L4 가 옮겨 갈 때까지 남겨 둔다. `to_month_end` 도 `msa.dates` 의 것을 재노출한다.
_read_csv_series = read_date_value_csv


def fred_cache_path(symbol: str) -> Path:
    """`state/physical/fred/<SYMBOL>.csv` — L1(실물 참조·CPI)과 L2(드라이버)가 같은 캐시를 쓴다."""
    return paths().fred_cache / f"{symbol}.csv"


def read_fred_cache(symbol: str) -> pd.Series | None:
    """캐시된 FRED 시리즈를 **원래 주기 그대로** 읽는다. 캐시가 없으면 `None`."""
    cache = fred_cache_path(symbol)
    if not cache.exists():
        return None
    return _read_csv_series(cache)


def write_fred_cache(symbol: str, series: pd.Series, meta: Mapping[str, Any] | None = None) -> Path:
    """시리즈를 `state/physical/fred/<SYMBOL>.csv` (`date,value`) 로 쓰고, `meta` 가 있으면 옆에
    `<SYMBOL>.meta.json` 을 남긴다 (`fetched_at`·`n_obs` 는 여기서 붙인다)."""
    cache = fred_cache_path(symbol)
    cache.parent.mkdir(parents=True, exist_ok=True)
    s = series.dropna().sort_index()
    dates = pd.DatetimeIndex(s.index).strftime("%Y-%m-%d")
    pd.DataFrame({"date": dates, "value": s.to_numpy()}).to_csv(cache, index=False)
    if meta is not None:
        meta_d: dict[str, Any] = dict(meta)
        meta_d["fetched_at"] = pd.Timestamp.now().isoformat(timespec="seconds")
        meta_d["n_obs"] = len(s)
        cache.with_suffix(".meta.json").write_text(json.dumps(meta_d, ensure_ascii=False, indent=1))
    return cache


def fetch_fred_to_cache(symbol: str, *, min_obs: int = 12) -> pd.Series:
    """FRED 에서 받아 캐시에 쓴다. 키가 없거나 실패하면 **예외를 그대로 올린다.**

    값 옆에 `<SYMBOL>.meta.json`(단위·주기·제목·받은 시각)을 남긴다 — 파생 드라이버
    (`usd_liquidity`)의 단위 환산이 선언과 맞는지 L2 가 대조할 재료다.
    """
    from msa.data.fred import FredClient

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
    cache = write_fred_cache(symbol, s, meta_d)
    log.info("fred: %s 관측 %d개 캐시 → %s", symbol, len(s), cache)
    return s


def _ok(symbol: str, source: str, s: pd.Series, note: str) -> PhysicalSeries:
    return PhysicalSeries(
        symbol, source, status=SeriesStatus.OK.value, series=to_month_end(s), note=note
    )


def _missing(symbol: str, source: str, note: str) -> PhysicalSeries:
    return PhysicalSeries(symbol, source, status=SeriesStatus.MISSING.value, note=note)


def load_fred_series(symbol: str, *, allow_fetch: bool = True) -> PhysicalSeries:
    cache = fred_cache_path(symbol)
    cached = read_fred_cache(symbol)
    if cached is not None:
        return _ok(symbol, "fred", cached, f"cache {cache.name}")
    if not allow_fetch:
        return _missing(symbol, "fred", f"캐시 없음 {cache}")
    try:
        s = fetch_fred_to_cache(symbol)
    except Exception as e:  # MissingApiKey · FredError · 네트워크
        return _missing(symbol, "fred", f"{type(e).__name__}: {e}")
    return _ok(symbol, "fred", s, "fetched+cached")


def load_manual_series(symbol: str) -> PhysicalSeries:
    path = paths().manual_dir / f"{symbol}.csv"
    if not path.exists():
        return _missing(symbol, "manual", f"파일 없음 {path}")
    return _ok(symbol, "manual", _read_csv_series(path), path.name)


def load_etf_series(
    symbols: list[str], *, prefetched: pd.DataFrame | None = None
) -> dict[str, PhysicalSeries]:
    """벌크 zip 을 한 번만 훑어 여러 ETF 를 받는다 (`etf_prices` 는 통과 1회 ≈ 12초).

    `prefetched` 를 주면 (이미 받은 `etf_prices` 프레임) 다시 훑지 않는다. 벌크를 못 읽으면
    전부 `missing` 이되 **이유를 `note` 에 남긴다** — `etf_prices_or_empty` 는 이유를 버리므로
    여기서는 쓰지 않는다.
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
            return {s: _missing(s, "etf", str(e)) for s in symbols}
    for sym in symbols:
        s = etf_series(df, sym)
        out[sym] = (
            _missing(sym, "etf", "벌크에 없음") if s is None else _ok(sym, "etf", s, f"{len(s)}행")
        )
    return out


def etf_symbols(themes: Iterable[Theme], *, include_proxy: bool = True) -> list[str]:
    """테마들이 필요로 하는 ETF 심볼 — `physical_ref.source == "etf"` 의 참조 (+ `etf_proxy`).
    정렬된 중복 없는 목록. 벌크 zip 을 **한 번에** 읽으려고 스캔·백테스트·실물 로더가 같이 쓴다."""
    syms: set[str] = set()
    for t in themes:
        if t.physical_ref is not None and t.physical_ref.source == "etf":
            syms.add(t.physical_ref.symbol)
        if include_proxy and t.etf_proxy:
            syms.add(t.etf_proxy)
    return sorted(syms)


def load_ref(
    ref: PhysicalRef,
    *,
    allow_fetch: bool = True,
    etf_prefetched: pd.DataFrame | None = None,
    memo: dict[str, PhysicalSeries] | None = None,
) -> PhysicalSeries:
    """한 `physical_ref` → `PhysicalSeries` (`kind` 는 선언값으로 채운다).

    `etf_prefetched` 는 `etf_prices` 프레임 (없으면 벌크를 읽는다). `memo` 는 호출자 소유의
    `"<source>:<symbol>" → 로드 결과` 캐시 — 같은 심볼을 여러 테마가 가리킬 때 한 번만 읽고,
    `load_physical` 은 ETF 를 한 번에 받아 미리 채워 넘긴다.
    """
    key = f"{ref.source}:{ref.symbol}"
    if memo is not None and key in memo:
        return replace(memo[key], kind=ref.kind)
    if ref.source == "etf":
        base = load_etf_series([ref.symbol], prefetched=etf_prefetched)[ref.symbol]
    elif ref.source == "fred":
        base = load_fred_series(ref.symbol, allow_fetch=allow_fetch)
    else:
        base = load_manual_series(ref.symbol)
    if memo is not None:
        memo[key] = base
    return replace(base, kind=ref.kind)


@dataclass(frozen=True)
class PhysicalBundle:
    refs: dict[str, PhysicalSeries]  # theme id → series
    cpi: PhysicalSeries

    def status_signature(self) -> dict[str, str]:
        """테마별 상태 + CPI — 지표 캐시의 유효성 열쇠 (`scan`·`backtest` 가 메타에 적는다)."""
        return {k: v.status for k, v in self.refs.items()} | {"_cpi": self.cpi.status}

    def status_table(self, themes: ThemeSet) -> pd.DataFrame:
        rows = []
        for t in themes:
            if t.physical_ref is None:
                rows.append((t.id, None, None, None, str(Axis1Status.NOT_DECLARED), ""))
                continue
            ps = self.refs.get(t.id)
            rows.append(
                (
                    t.id,
                    t.physical_ref.source,
                    t.physical_ref.symbol,
                    t.physical_ref.kind,
                    ps.status if ps else str(SeriesStatus.MISSING),
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
    etf_syms = etf_symbols(themes, include_proxy=False)
    memo = {
        f"etf:{s}": ps for s, ps in load_etf_series(etf_syms, prefetched=etf_prefetched).items()
    }
    refs: dict[str, PhysicalSeries] = {}
    for t in themes:
        if t.physical_ref is None:
            continue
        refs[t.id] = load_ref(t.physical_ref, allow_fetch=allow_fetch, memo=memo)
    cpi = load_fred_series(CPI_SERIES, allow_fetch=allow_fetch)
    n_ok = sum(1 for p in refs.values() if p.status == SeriesStatus.OK)
    log.info(
        "physical: 선언 %d · 데이터 있음 %d · 없음 %d · CPI %s",
        len(refs),
        n_ok,
        len(refs) - n_ok,
        cpi.status,
    )
    return PhysicalBundle(refs=refs, cpi=cpi)
