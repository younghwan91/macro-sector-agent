"""드라이버 상태 — 원시 시계열 → 발표 지연 반영 → 측정값(transform) → 방향 상태.

## 상태의 정의 (결정 — docs/03 §2·§4 와 YAML 부호 규약을 함께 만족시키는 유일한 읽기)

`state/macro-dag.yaml` 의 엣지 `sign` 은 **"드라이버 값 상승 → 테마 우호(+1)/역풍(−1)"** 이고
`favorable_when` 의 방향과 독립이라고 선언돼 있다. 따라서 `sign × state` 가 뜻을 가지려면
`state` 는 **값의 방향**이어야 한다:

    state = +1  측정값 > neutral_band 상한        (드라이버가 "올랐다")
            −1  측정값 < neutral_band 하한        (드라이버가 "내렸다")
             0  밴드 안                            (중립)
            NaN 계산 불가 (시리즈 없음·이력 부족)   → 엣지 제외, 개수 보고

`favorable_when` 은 **표시용 '우호' 플래그**로만 쓴다 (리포트의 `favorable` 열). 점수에는 들어가지
않는다. 예: `real_rate_10y` 가 6개월 −40bp 면 state = −1, favorable = True; 엣지
`real_rate_10y → gold_miners (sign −1)` 의 기여는 (−1)×(−1) = +1 — 실질금리 하락이 금광 순풍.

## 측정값(measure) 정의 — 월말 격자 위에서

| measure | 정의 | 쓰는 드라이버 |
|---|---|---|
| `level` | 값 그대로 | china_credit_impulse |
| `yoy` | x_t / x_{t−12} − 1 | m2_growth · cpi_yoy · ppi_yoy · china_property · defense 등 |
| `yoy_second_derivative` | y = yoy; y_t − 2·y_{t−3} + y_{t−6} (3개월 보폭 2계 차분) | INDPRO |
| `change_6m` · `change_3m` | x_t / x_{t−k} − 1 | dollar_broad · new_orders_mfg · … |
| `change_6m_bp` · `change_3m_bp` | (x_t − x_{t−k}) × 100 — 원 시리즈가 % | real_rate_10y 등 |
| `composite_z` | ( z(PAYEMS 월간 증가분 3개월 평균) − z(UNRATE 6개월 변화) ) / 2 | employment |
| `event_window` | 테마별 — `tailwind.py` 가 이벤트 목록으로 판정 | policy_events |

z-score 는 **후행 120개월 창 · 최소 60개월** (L1 의 `M10Y` 자기이력 창과 같은 길이 — 한 사이클을
덮는 길이이며, 36개월이면 단일 국면에 오염된다). 2계 차분의 3개월 보폭은 월간 1계 차분의 잡음이
INDPRO 개정폭보다 커서 월 보폭으로는 부호가 매달 뒤집히기 때문이다.
둘 다 **선언이며 탐색하지 않았다.**

## 발표 지연 (publication lag) — `PUB_LAG`

`docs/08` §3 의 `발표지연` 열은 M1 에서 **실측되지 못했다** (키 없음). 아래 표는 발표 일정에서 온
선언값이며, 키가 생기면 `msa data fred-lag` 실측으로 **대체**한다 (성과를 보고 고치는 것이 아니다).
월말 격자의 시점 T 에서 쓰는 값은 **T 까지 발표된 관측**뿐이다:

- 일간·주간 시리즈: 관측일 + `days` ≤ T
- 월간 시리즈: 관측월 말일 + `months` 개월 ≤ T  (예: CPI 7월치는 8월 중순 발표 → 8/31 격자부터)
- 분기 시리즈: 분기 말일 + `months` 개월 ≤ T  (FRED 분기 관측일은 분기 **시작일**이다)

이용 가능 시점 이후 `MAX_STALE_DAYS` 를 넘게 새 관측이 없으면 NaN —
죽은 시리즈를 앞으로 끌지 않는다.

## PIT 한계 (정직하게)

FRED 캐시는 **최신 개정치**다. ALFRED 빈티지를 쓰지 않으므로 `INDPRO`·`PAYEMS` 같은 개정 큰
시리즈는 과거 시점의 상태가 당시 판단과 다를 수 있다 (`docs/08` §4 "권장"). 오늘의 상태 판정에는
영향이 없고, `signcheck.py` 의 과거 상관에는 영향이 있다 — 그 문서에 적는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from pandas.tseries.offsets import MonthEnd

from msa.l2.dag import Driver, MacroDag
from msa.l2.sources import RawSeries, SeriesStore

log = logging.getLogger(__name__)

Z_WINDOW = 120
Z_MIN = 60
GRID_START = "1990-01-31"


@dataclass(frozen=True)
class PubLag:
    freq: str  # D | W | M | Q
    months: int = 0
    days: int = 0
    reason: str = ""

    def describe(self) -> str:
        if self.freq in ("D", "W"):
            return f"{self.freq} +{self.days}d"
        return f"{self.freq} +{self.months}m"


#: FRED 시리즈별 선언 발표 지연. **없는 시리즈를 쓰면 예외** — 지연을 모르는 채 쓰지 않는다.
PUB_LAG: dict[str, PubLag] = {
    # 일간 시장 시리즈 — 당일 발표
    "DFII10": PubLag("D", days=0, reason="일간 시장 수익률, 당일"),
    "T10Y2Y": PubLag("D", days=0, reason="일간, 당일"),
    "T10YIE": PubLag("D", days=0, reason="일간, 당일"),
    "DFEDTARU": PubLag("D", days=0, reason="정책금리 상단, 당일"),
    "BAMLH0A0HYM2": PubLag("D", days=0, reason="ICE BofA OAS, 당일"),
    "BAMLC0A0CM": PubLag("D", days=0, reason="ICE BofA OAS, 당일"),
    "DCOILWTICO": PubLag("D", days=0, reason="EIA 일간 현물, 당일"),
    "DHHNGSP": PubLag("D", days=0, reason="EIA 일간 현물, 당일"),
    "DTWEXBGS": PubLag("D", days=7, reason="연준 H.10 — 다음 주 월요일 발표"),
    "RRPONTSYD": PubLag("D", days=0, reason="뉴욕연준 일간, 당일"),
    # 주간
    "WALCL": PubLag("W", days=7, reason="H.4.1 수요일 기준 목요일 발표 — 보수적으로 1주"),
    "WTREGEN": PubLag("W", days=7, reason="H.4.1 과 동일"),
    # 월간 — 관측월 말일 + N 개월
    "CPIAUCSL": PubLag("M", months=1, reason="BLS 다음 달 중순"),
    "PPIACO": PubLag("M", months=1, reason="BLS 다음 달 중순"),
    "INDPRO": PubLag("M", months=1, reason="연준 G.17 다음 달 중순 (개정 큼)"),
    "HOUST": PubLag("M", months=1, reason="센서스 다음 달 중하순"),
    "PAYEMS": PubLag("M", months=1, reason="BLS 다음 달 첫 금요일 (개정 큼)"),
    "UNRATE": PubLag("M", months=1, reason="BLS 다음 달 첫 금요일"),
    "M2SL": PubLag("M", months=1, reason="연준 H.6 다음 달 넷째 주"),
    "NEWORDER": PubLag("M", months=1, reason="내구재 선행 보고서 다음 달 넷째 주"),
    "AMTMNO": PubLag("M", months=2, reason="제조업 전체 M3 본보고서는 다다음 달 초"),
    "ISRATIO": PubLag("M", months=2, reason="사업 재고/판매 약 6주 후 — 다다음 달 중순"),
    "PCOPPUSDM": PubLag("M", months=1, reason="IMF 월평균 — 다음 달. 실측 필요 (docs/08 §3)"),
    # 분기
    "FDEFX": PubLag("Q", months=1, reason="NIPA — 분기 말 + 1개월(GDP 속보). 실측 필요"),
}

#: provider 별 기본 지연 (FRED 밖). 수동 CSV 에 `available` 열이 있으면 그것이 우선한다.
DEFAULT_LAG: dict[str, PubLag] = {
    "etf": PubLag("D", days=0, reason="시장 가격, 당일"),
    "manual": PubLag("M", months=1, reason="월간 수동 갱신 — 다음 달 발표로 가정"),
}

MAX_STALE_DAYS: dict[str, int] = {"D": 45, "W": 45, "M": 120, "Q": 220}

#: `usd_liquidity` 단위 환산 (FRED 단위 문자열의 핵심어로 대조). RRP 는 십억 → 백만.
LIQUIDITY_UNITS: dict[str, tuple[str, float]] = {
    "WALCL": ("Millions", 1.0),
    "WTREGEN": ("Millions", 1.0),
    "RRPONTSYD": ("Billions", 1000.0),
}


# ---------------------------------------------------------------- 시점 정렬


def month_end_grid(asof: pd.Timestamp, start: str = GRID_START) -> pd.DatetimeIndex:
    return pd.date_range(start, asof, freq="ME")


def last_month_end(asof: pd.Timestamp) -> pd.Timestamp:
    """`asof` 이하의 마지막 월말. 8/23 이면 7/31 — 그 달이 끝나야 월말 값이 있다."""
    me = asof + MonthEnd(0)
    return me if me == asof else asof - MonthEnd(1)


def availability_dates(index: pd.DatetimeIndex, lag: PubLag) -> pd.DatetimeIndex:
    """관측일 → 그 값을 볼 수 있는 첫 시점."""
    if lag.freq in ("D", "W"):
        return index + pd.Timedelta(days=lag.days)
    if lag.freq == "M":
        return pd.DatetimeIndex(index + MonthEnd(0) + MonthEnd(lag.months))
    if lag.freq == "Q":
        return pd.DatetimeIndex(index + MonthEnd(0) + MonthEnd(2) + MonthEnd(lag.months))
    raise ValueError(f"알 수 없는 주기: {lag.freq}")


def asof_on_grid(
    values: pd.Series,
    available: pd.Series | pd.DatetimeIndex,
    grid: pd.DatetimeIndex,
    *,
    max_stale_days: int,
) -> pd.Series:
    """격자의 각 T 에 대해 `available ≤ T` 인 **마지막으로 발표된** 관측값을 놓는다."""
    avail = pd.DatetimeIndex(
        available.to_numpy() if isinstance(available, pd.Series) else available
    )
    rows = pd.DataFrame({"avail": avail, "value": values.to_numpy()}).dropna()
    rows = rows.sort_values("avail").drop_duplicates("avail", keep="last")
    if rows.empty:
        return pd.Series(np.nan, index=grid, dtype=float)
    left = pd.DataFrame({"t": grid})
    m = pd.merge_asof(left, rows, left_on="t", right_on="avail", direction="backward")
    stale = (m["t"] - m["avail"]).dt.days > max_stale_days
    return pd.Series(m["value"].where(~stale).to_numpy(), index=grid, dtype=float)


def raw_to_grid(raw: RawSeries, lag: PubLag, grid: pd.DatetimeIndex) -> pd.Series:
    assert raw.values is not None
    vals = raw.values
    if raw.available is not None:
        avail: pd.Series | pd.DatetimeIndex = pd.Series(
            pd.to_datetime(raw.available.reindex(vals.index).to_numpy()), index=vals.index
        )
    else:
        avail = availability_dates(pd.DatetimeIndex(vals.index), lag)
    return asof_on_grid(vals, avail, grid, max_stale_days=MAX_STALE_DAYS[lag.freq])


# ---------------------------------------------------------------- 측정값


def rolling_z(s: pd.Series, window: int = Z_WINDOW, min_periods: int = Z_MIN) -> pd.Series:
    mu = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std()
    return (s - mu) / sd.replace(0.0, np.nan)


def measure_from_series(measure: str, s: pd.Series) -> pd.Series:
    """단일 시리즈 측정값. 모르는 measure 는 던진다 — 조용히 level 로 떨어지지 않는다."""
    if measure == "level":
        return s.astype(float)
    if measure == "yoy":
        return s / s.shift(12) - 1.0
    if measure == "yoy_second_derivative":
        y = s / s.shift(12) - 1.0
        return y - 2.0 * y.shift(3) + y.shift(6)
    if measure == "change_6m":
        return s / s.shift(6) - 1.0
    if measure == "change_3m":
        return s / s.shift(3) - 1.0
    if measure == "change_6m_bp":
        return (s - s.shift(6)) * 100.0
    if measure == "change_3m_bp":
        return (s - s.shift(3)) * 100.0
    raise ValueError(f"알 수 없는 measure: {measure}")


def employment_composite_z(payems: pd.Series, unrate: pd.Series) -> pd.Series:
    """YAML: "PAYEMS 3개월 평균 증가분과 UNRATE 6개월 변화의 z-score 평균" — 실업률은 부호 반전."""
    a = payems.diff().rolling(3, min_periods=3).mean()
    b = unrate - unrate.shift(6)
    return (rolling_z(a) - rolling_z(b)) / 2.0


def usd_liquidity_level(walcl: pd.Series, wtregen: pd.Series, rrp: pd.Series) -> pd.Series:
    """WALCL − WTREGEN − RRPONTSYD (백만 달러). RRP 는 십억 단위라 ×1000."""
    return walcl - wtregen - rrp * LIQUIDITY_UNITS["RRPONTSYD"][1]


def direction_states(measure: pd.Series, band_lo: float, band_hi: float) -> pd.Series:
    out = pd.Series(np.nan, index=measure.index, dtype=float)
    out[measure > band_hi] = 1.0
    out[measure < band_lo] = -1.0
    out[(measure >= band_lo) & (measure <= band_hi)] = 0.0
    return out


# ---------------------------------------------------------------- 결과 컨테이너


@dataclass
class DriverState:
    id: str
    provider: str
    source_used: str
    status: str  # ok | missing
    measure_name: str
    measure_value: float = float("nan")
    state: float = float("nan")
    favorable: bool | None = None
    obs_date: pd.Timestamp | None = None  # 측정값에 쓰인 마지막 관측의 시점 (격자 기준)
    lag: str = ""
    note: str = ""
    missing_series: list[str] = field(default_factory=list)
    common_factor: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class DriverStates:
    asof: pd.Timestamp
    grid: pd.DatetimeIndex
    measures: pd.DataFrame  # grid × driver (NaN = 없음)
    states: pd.DataFrame  # grid × driver ∈ {−1, 0, 1, NaN}
    rows: list[DriverState]
    events: pd.DataFrame | None = None  # policy_events (date, theme, effect, confirmed)
    events_note: str = ""

    def state_at(self, when: pd.Timestamp | None = None) -> pd.Series:
        t = self.asof if when is None else when
        row = self.states.loc[t] if t in self.states.index else self.states.iloc[-1]
        assert isinstance(row, pd.Series)
        return row

    @property
    def missing(self) -> list[str]:
        return [r.id for r in self.rows if not r.ok]

    @property
    def available(self) -> list[str]:
        return [r.id for r in self.rows if r.ok]

    def snapshot(self) -> pd.DataFrame:
        recs: list[dict[str, Any]] = []
        for r in self.rows:
            recs.append(
                {
                    "driver": r.id,
                    "provider": r.provider,
                    "source_used": r.source_used,
                    "status": r.status,
                    "measure": r.measure_name,
                    "value": r.measure_value,
                    "state": r.state,
                    "favorable": r.favorable,
                    "obs_date": None if r.obs_date is None else str(r.obs_date.date()),
                    "lag": r.lag,
                    "common_factor": r.common_factor,
                    "missing_series": ",".join(r.missing_series),
                    "note": r.note,
                }
            )
        return pd.DataFrame(recs).set_index("driver")


# ---------------------------------------------------------------- 계산


def _lag_for_fred(symbol: str) -> PubLag:
    try:
        return PUB_LAG[symbol]
    except KeyError as e:
        raise ValueError(
            f"FRED {symbol} 의 발표 지연이 PUB_LAG 에 선언돼 있지 않다 — "
            "지연을 모르는 채 쓰지 않는다"
        ) from e


def _units_ok(raw: RawSeries, symbol: str) -> str | None:
    """usd_liquidity 구성 시리즈의 단위 대조. 메타가 없으면 대조 불가 → None(통과, 메모 남김)."""
    want = LIQUIDITY_UNITS.get(symbol)
    if want is None or raw.units is None:
        return None
    if want[0].lower() not in raw.units.lower():
        return f"{symbol} 단위 `{raw.units}` 가 선언 `{want[0]}` 과 다르다 — 환산 불가"
    return None


def _finish(
    d: Driver,
    measure: pd.Series,
    grid_series: pd.Series | None,
    source_used: str,
    lag: str,
    note: str,
    asof: pd.Timestamp,
) -> tuple[DriverState, pd.Series, pd.Series]:
    rule = d.rule
    if rule is None:
        states = pd.Series(np.nan, index=measure.index, dtype=float)
    else:
        states = direction_states(measure, rule.band_lo, rule.band_hi)
    v = float(measure.loc[asof]) if asof in measure.index else float("nan")
    st = DriverState(
        id=d.id,
        provider=d.provider,
        source_used=source_used,
        status="ok" if np.isfinite(v) else "missing",
        measure_name=d.measure,
        measure_value=v,
        state=float(states.loc[asof]) if np.isfinite(v) and rule is not None else float("nan"),
        favorable=(rule.favorable(v) if (rule is not None and np.isfinite(v)) else None),
        obs_date=(
            pd.Timestamp(grid_series.loc[:asof].last_valid_index())  # type: ignore[arg-type]
            if grid_series is not None and grid_series.loc[:asof].last_valid_index() is not None
            else None
        ),
        lag=lag,
        note=note,
        common_factor=d.common_factor,
    )
    if not st.ok and not note:
        st.note = "이력 부족 — 측정값 계산 불가"
    return st, measure, states


def _missing(d: Driver, source_used: str, note: str, missing: list[str]) -> DriverState:
    return DriverState(
        id=d.id,
        provider=d.provider,
        source_used=source_used,
        status="missing",
        measure_name=d.measure,
        note=note,
        missing_series=missing,
        common_factor=d.common_factor,
    )


def compute_driver_states(
    dag: MacroDag,
    store: SeriesStore,
    asof: pd.Timestamp,
    *,
    start: str = GRID_START,
) -> DriverStates:
    """전 드라이버의 측정값·상태 시계열과 `asof` 스냅샷. 없는 것은 이름을 적어 `missing`."""
    asof = last_month_end(pd.Timestamp(asof))
    grid = month_end_grid(asof, start)
    nan = pd.Series(np.nan, index=grid, dtype=float)
    measures: dict[str, pd.Series] = {}
    states: dict[str, pd.Series] = {}
    rows: list[DriverState] = []
    events: pd.DataFrame | None = None
    events_note = ""

    # 1) ETF 심볼을 먼저 모아 벌크를 한 번만 읽는다 — FRED 폴백은 FRED 가 없을 때만.
    etf_syms: set[str] = set()
    fred_raw: dict[str, RawSeries] = {}
    for d in dag.drivers:
        if d.provider == "etf" and d.symbol:
            etf_syms.add(d.symbol)
            etf_syms.update(str(a) for a in (d.raw.get("source", {}).get("alt") or []))
        if d.provider == "fred" and d.fallback and d.fallback.get("provider") == "etf":
            sym = d.series[0]
            fred_raw[sym] = store.fred(sym)
            if not fred_raw[sym].ok:
                etf_syms.add(str(d.fallback["symbol"]))
    if etf_syms:
        store.prefetch_etf(etf_syms)

    # 2) 드라이버별 계산
    for d in dag.drivers:
        measures[d.id] = nan
        states[d.id] = nan
        try:
            if d.provider == "fred":
                rows.append(_fred_driver(d, store, fred_raw, grid, asof, measures, states))
            elif d.provider == "derived":
                rows.append(_derived_driver(d, store, grid, asof, measures, states))
            elif d.provider == "etf":
                rows.append(_etf_driver(d, store, grid, asof, measures, states))
            elif d.provider == "manual":
                rows.append(_manual_driver(d, store, grid, asof, measures, states))
            elif d.provider == "sharadar_derived":
                rows.append(_sharadar_driver(d, store, grid, asof, measures, states))
            elif d.provider == "agent":
                events, events_note = store.manual_events()
                note = events_note if events is not None else f"이벤트 목록 없음 — {events_note}"
                st = _missing(d, "manual:policy_events.csv", note, [])
                st.status = "ok" if events is not None else "missing"
                st.note = note + " · 테마별 판정은 tailwind 단계"
                rows.append(st)
            else:
                rows.append(_missing(d, d.provider, f"알 수 없는 provider `{d.provider}`", []))
        except ValueError as e:
            rows.append(_missing(d, d.provider, f"{type(e).__name__}: {e}", []))
    return DriverStates(
        asof=asof,
        grid=grid,
        measures=pd.DataFrame(measures, index=grid),
        states=pd.DataFrame(states, index=grid),
        rows=rows,
        events=events,
        events_note=events_note,
    )


def _store_result(
    d: Driver,
    res: tuple[DriverState, pd.Series, pd.Series],
    measures: dict[str, pd.Series],
    states: dict[str, pd.Series],
) -> DriverState:
    st, m, s = res
    measures[d.id] = m
    states[d.id] = s
    return st


def _fred_driver(
    d: Driver,
    store: SeriesStore,
    fred_raw: dict[str, RawSeries],
    grid: pd.DatetimeIndex,
    asof: pd.Timestamp,
    measures: dict[str, pd.Series],
    states: dict[str, pd.Series],
) -> DriverState:
    raws = {sym: fred_raw.get(sym) or store.fred(sym) for sym in d.series}
    missing = [sym for sym, r in raws.items() if not r.ok]
    if missing:
        # 폴백 (copper_price → CPER)
        if d.fallback and d.fallback.get("provider") == "etf":
            fb_sym = str(d.fallback["symbol"])
            fb = store.etf(fb_sym)
            if fb.ok:
                g = raw_to_grid(fb, DEFAULT_LAG["etf"], grid)
                m = measure_from_series(d.measure, g)
                st = _finish(
                    d,
                    m,
                    g,
                    f"etf:{fb_sym} (fallback)",
                    DEFAULT_LAG["etf"].describe(),
                    f"FRED {missing} 없음 → ETF {fb_sym} 폴백 · {fb.note}",
                    asof,
                )
                st[0].missing_series = missing
                return _store_result(d, st, measures, states)
            note = (
                f"FRED {missing} 없음 ({raws[missing[0]].note}) · 폴백 {fb_sym} 도 없음 ({fb.note})"
            )
            return _missing(d, f"fred:{'+'.join(d.series)}", note, [*missing, fb_sym])
        note = " · ".join(f"{sym}: {raws[sym].note}" for sym in missing)
        return _missing(d, f"fred:{'+'.join(d.series)}", note, missing)
    lags = {sym: _lag_for_fred(sym) for sym in d.series}
    grids = {sym: raw_to_grid(r, lags[sym], grid) for sym, r in raws.items()}
    lag_desc = ", ".join(f"{sym} {lags[sym].describe()}" for sym in d.series)
    if d.measure == "composite_z":
        if set(d.series) != {"PAYEMS", "UNRATE"}:
            raise ValueError(f"{d.id}: composite_z 는 PAYEMS+UNRATE 를 기대한다 ({d.series})")
        m = employment_composite_z(grids["PAYEMS"], grids["UNRATE"])
        g = grids["PAYEMS"]
    else:
        if len(d.series) != 1:
            raise ValueError(f"{d.id}: measure {d.measure} 는 시리즈 1개를 기대한다 ({d.series})")
        g = grids[d.series[0]]
        m = measure_from_series(d.measure, g)
    res = _finish(d, m, g, f"fred:{'+'.join(d.series)}", lag_desc, raws[d.series[0]].note, asof)
    return _store_result(d, res, measures, states)


def _derived_driver(
    d: Driver,
    store: SeriesStore,
    grid: pd.DatetimeIndex,
    asof: pd.Timestamp,
    measures: dict[str, pd.Series],
    states: dict[str, pd.Series],
) -> DriverState:
    if d.id != "usd_liquidity":
        raise ValueError(f"{d.id}: 알 수 없는 파생 드라이버 (formula={d.formula})")
    syms = ("WALCL", "WTREGEN", "RRPONTSYD")
    raws = {s: store.fred(s) for s in syms}
    missing = [s for s in syms if not raws[s].ok]
    if missing:
        note = " · ".join(f"{s}: {raws[s].note}" for s in missing)
        return _missing(d, f"derived:{'-'.join(syms)}", note, missing)
    unit_problems = [p for p in (_units_ok(raws[s], s) for s in syms) if p]
    if unit_problems:
        return _missing(d, f"derived:{'-'.join(syms)}", " · ".join(unit_problems), [])
    grids = {s: raw_to_grid(raws[s], _lag_for_fred(s), grid) for s in syms}
    lvl = usd_liquidity_level(grids["WALCL"], grids["WTREGEN"], grids["RRPONTSYD"])
    m = measure_from_series(d.measure, lvl)
    units_note = "단위 메타 대조: " + (
        "완료" if all(raws[s].units for s in syms) else "메타 없음(환산 선언값 사용)"
    )
    res = _finish(
        d,
        m,
        lvl,
        f"derived:{'-'.join(syms)}",
        ", ".join(f"{s} {_lag_for_fred(s).describe()}" for s in syms),
        units_note,
        asof,
    )
    return _store_result(d, res, measures, states)


def _etf_driver(
    d: Driver,
    store: SeriesStore,
    grid: pd.DatetimeIndex,
    asof: pd.Timestamp,
    measures: dict[str, pd.Series],
    states: dict[str, pd.Series],
) -> DriverState:
    cands = [d.symbol or ""] + [str(a) for a in (d.raw.get("source", {}).get("alt") or [])]
    tried: list[str] = []
    for sym in [c for c in cands if c]:
        raw = store.etf(sym)
        if raw.ok:
            g = raw_to_grid(raw, DEFAULT_LAG["etf"], grid)
            m = measure_from_series(d.measure, g)
            res = _finish(
                d,
                m,
                g,
                f"etf:{sym}",
                DEFAULT_LAG["etf"].describe(),
                raw.note + (f" (대체: {tried} 없음)" if tried else ""),
                asof,
            )
            return _store_result(d, res, measures, states)
        tried.append(f"{sym}: {raw.note}")
    return _missing(d, f"etf:{d.symbol}", " · ".join(tried), [c for c in cands if c])


def _manual_driver(
    d: Driver,
    store: SeriesStore,
    grid: pd.DatetimeIndex,
    asof: pd.Timestamp,
    measures: dict[str, pd.Series],
    states: dict[str, pd.Series],
) -> DriverState:
    raw = store.manual(d.id)
    if not raw.ok:
        return _missing(d, raw.source, raw.note, [d.id])
    lag = DEFAULT_LAG["manual"]
    g = raw_to_grid(raw, lag, grid)
    m = measure_from_series(d.measure, g)
    lag_desc = "available 열" if raw.available is not None else lag.describe()
    res = _finish(d, m, g, raw.source, lag_desc, raw.note, asof)
    return _store_result(d, res, measures, states)


def _sharadar_driver(
    d: Driver,
    store: SeriesStore,
    grid: pd.DatetimeIndex,
    asof: pd.Timestamp,
    measures: dict[str, pd.Series],
    states: dict[str, pd.Series],
) -> DriverState:
    raw = store.sharadar_capex_ttm(grid)
    if not raw.ok:
        return _missing(d, raw.source, raw.note, ["SF1 capex"])
    assert raw.values is not None
    g = raw.values.reindex(grid)
    m = measure_from_series(d.measure, g)
    res = _finish(d, m, g, raw.source, "datekey as-of (PIT)", raw.note, asof)
    return _store_result(d, res, measures, states)
