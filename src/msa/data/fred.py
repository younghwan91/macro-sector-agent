"""FRED 어댑터 — `docs/08-data-contract.md` §3 의 시리즈 24종.

## 24 의 구성 (`docs/08` §6.3 의 정의)

§3 표의 FRED 직접 시리즈 20 + `usd_liquidity` 파생 3(`WALCL`·`WTREGEN`·`RRPONTSYD`)
+ `DFEDTARU` = 24. 나머지 드라이버(`china_credit_impulse`·`china_property`·
`policy_events`·`gold_price`·`hyperscaler_capex`)는 FRED 밖이라 여기 없다.

## 발표 지연 실측

`measure_release_lag()` 가 각 시리즈의 최신 관측일과 기준일의 차이를 잰다.
이것이 §3 표의 `발표지연` 열을 채울 재료다. **개정 여부는 FRED 본 API 로는 알 수 없다** —
같은 관측일의 값이 시간에 따라 바뀌었는지는 ALFRED(vintage) 가 답한다.
그래서 `measure_revision()` 은 ALFRED `realtime_start`/`realtime_end` 를 쓴다.

## 키 없으면 던진다

`FRED_API_KEY` 가 없으면 `MissingApiKey`. 조용히 건너뛰면 L2 드라이버가 빈 채로
파이프라인이 진행된다 (`CLAUDE.md` §2).

## 네트워크 없이 테스트되는 부분

응답 파싱(`parse_observations`)·지연 계산(`lag_days`)·주기 추론(`infer_frequency`)은
전부 순수 함수다. HTTP 를 타는 것은 `FredClient` 뿐이다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from msa.config import fred_api_key

log = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"

#: `docs/08` §3 의 드라이버 id → FRED 시리즈 id.
#: 값이 튜플인 것은 여러 시리즈를 쓰는 드라이버다 (`employment` 는 2개,
#: `usd_liquidity` 는 파생 3개).
DRIVER_SERIES: dict[str, tuple[str, ...]] = {
    "real_rate_10y": ("DFII10",),
    "term_spread": ("T10Y2Y",),
    "breakeven_10y": ("T10YIE",),
    "dollar_broad": ("DTWEXBGS",),
    "hy_spread": ("BAMLH0A0HYM2",),
    "ig_spread": ("BAMLC0A0CM",),
    "industrial_production": ("INDPRO",),
    "new_orders_mfg": ("AMTMNO",),
    "capex_orders_core": ("NEWORDER",),
    "inventory_sales": ("ISRATIO",),
    "housing_starts": ("HOUST",),
    "employment": ("PAYEMS", "UNRATE"),
    "cpi_yoy": ("CPIAUCSL",),
    "ppi_yoy": ("PPIACO",),
    "oil_wti": ("DCOILWTICO",),
    "nat_gas": ("DHHNGSP",),
    "m2_growth": ("M2SL",),
    "usd_liquidity": ("WALCL", "WTREGEN", "RRPONTSYD"),
    "defense_outlays": ("FDEFX",),
    "copper_price": ("PCOPPUSDM",),
    "fed_policy_path": ("DFEDTARU",),
}

#: 위 매핑을 펼친 목록. `docs/08` §6.3 의 "24종" 이 이것이다.
ALL_SERIES: tuple[str, ...] = tuple(
    dict.fromkeys(s for group in DRIVER_SERIES.values() for s in group)
)

#: `docs/08` §3 이 "M1 에서 실측 확인 필요" 로 표시한 시리즈.
NEEDS_VERIFICATION: tuple[str, ...] = ("FDEFX", "PCOPPUSDM")


class FredError(RuntimeError):
    pass


@dataclass(frozen=True)
class Observation:
    date: date
    value: float | None


@dataclass(frozen=True)
class SeriesMeta:
    """`/series` 응답의 관심 필드."""

    series_id: str
    title: str
    frequency: str
    units: str
    last_updated: str
    observation_end: date


@dataclass(frozen=True)
class LagMeasurement:
    """§3 표의 `발표지연`·`개정` 열을 채울 실측 결과."""

    series_id: str
    as_of: date
    latest_observation: date
    lag_days: int
    frequency: str
    n_observations: int
    revised: bool | None = None
    revision_note: str = ""

    def row(self) -> str:
        rev = "미측정" if self.revised is None else ("있음" if self.revised else "없음")
        return (
            f"{self.series_id:<14} 최신관측 {self.latest_observation} · "
            f"지연 {self.lag_days:>4}일 · 주기 {self.frequency} · "
            f"관측 {self.n_observations:,}개 · 개정 {rev} {self.revision_note}"
        )


# ---------------------------------------------------------------- 순수 함수


def parse_observations(payload: Mapping[str, Any]) -> list[Observation]:
    """`/series/observations` 응답 → `Observation` 목록.

    FRED 는 결측을 `"."` 로 준다. 이것을 0.0 으로 읽으면 국면 판정이 조용히 틀어지므로
    `None` 으로 남긴다. 응답에 `observations` 키가 없으면 던진다 — 빈 목록을 반환하면
    "데이터가 없다" 와 "요청이 틀렸다" 가 구별되지 않는다.
    """
    if "observations" not in payload:
        raise FredError(
            f"FRED 응답에 observations 가 없다. 키: {sorted(payload)} · "
            f"error: {payload.get('error_message', '(없음)')}"
        )
    out: list[Observation] = []
    for row in payload["observations"]:
        raw = row.get("value", ".")
        value = None if raw in (".", "", None) else float(raw)
        out.append(Observation(date=_as_date(row["date"]), value=value))
    return out


def parse_series_meta(payload: Mapping[str, Any]) -> SeriesMeta:
    seriess = payload.get("seriess")
    if not seriess:
        raise FredError(
            f"FRED `/series` 응답이 비었다. error: {payload.get('error_message', '(없음)')}"
        )
    s = seriess[0]
    return SeriesMeta(
        series_id=s["id"],
        title=s["title"],
        frequency=s["frequency_short"],
        units=s["units_short"],
        last_updated=s["last_updated"],
        observation_end=_as_date(s["observation_end"]),
    )


def lag_days(latest_observation: date, as_of: date) -> int:
    """발표 지연 = 기준일 빼기 최신 관측일 (일).

    엄밀히는 "관측 시점과 그 값을 볼 수 있게 된 시점의 차이" 이고, 이 계산은
    **최신 관측이 오늘 이미 발표돼 있다는 가정** 위에 있다. 월간 시리즈에서는
    이 값이 최대 한 주기만큼 과대평가된다 — L2 가 시차를 쓸 때 이 점을 감안해야 한다.
    """
    return (as_of - latest_observation).days


def infer_frequency(observations: Sequence[Observation]) -> str:
    """관측 간격의 중앙값으로 주기를 추정한다. 메타의 `frequency` 와 대조용."""
    if len(observations) < 3:
        return "unknown"
    dates = sorted(o.date for o in observations)
    gaps = sorted((dates[i + 1] - dates[i]).days for i in range(len(dates) - 1))
    med = gaps[len(gaps) // 2]
    if med <= 4:
        return "D"
    if med <= 10:
        return "W"
    if med <= 45:
        return "M"
    if med <= 130:
        return "Q"
    return "A"


def detect_revision(
    original: Sequence[Observation],
    vintage: Sequence[Observation],
    *,
    tolerance: float = 1e-9,
) -> tuple[bool, str]:
    """같은 관측일의 값이 최신본과 과거 빈티지에서 다른지 본다.

    다르면 개정이 있다는 뜻이다. `INDPRO`·`PAYEMS` 가 여기 걸릴 것으로 예상된다
    (`docs/08` §3 각주).
    """
    latest = {o.date: o.value for o in original}
    diffs = 0
    first = ""
    for obs in vintage:
        cur = latest.get(obs.date)
        if cur is None or obs.value is None:
            continue
        if abs(cur - obs.value) > tolerance:
            diffs += 1
            if not first:
                first = f"(예: {obs.date} {obs.value} → {cur})"
    return diffs > 0, (f"{diffs}건 {first}" if diffs else "")


def _as_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


# ---------------------------------------------------------------- HTTP 계층


class FredClient:
    """FRED REST 클라이언트. 키가 없으면 생성 시점에 던진다."""

    def __init__(self, api_key: str | None = None, *, timeout: float = 30.0) -> None:
        self.api_key = api_key if api_key is not None else fred_api_key()
        self._client = httpx.Client(timeout=timeout, base_url=FRED_BASE)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FredClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        params.update(api_key=self.api_key, file_type="json")
        r = self._client.get(path, params=params)
        if r.status_code >= 400:
            raise FredError(f"FRED {path} {r.status_code}: {r.text[:300]}")
        payload: dict[str, Any] = r.json()
        return payload

    def series_meta(self, series_id: str) -> SeriesMeta:
        return parse_series_meta(self._get("/series", series_id=series_id))

    def observations(
        self,
        series_id: str,
        *,
        start: date | str | None = None,
        end: date | str | None = None,
        realtime: tuple[str, str] | None = None,
        min_obs: int = 1,
    ) -> list[Observation]:
        """관측치. `min_obs` 미만이면 던진다 — 조용한 절단 금지 (`CLAUDE.md` §2).

        `realtime` 은 ALFRED 빈티지 조회용 `(realtime_start, realtime_end)` 다.
        지정하면 **그 시점에 보였던 값**을 받는다.
        """
        params: dict[str, Any] = {"series_id": series_id}
        if start is not None:
            params["observation_start"] = str(start)
        if end is not None:
            params["observation_end"] = str(end)
        if realtime is not None:
            params["realtime_start"], params["realtime_end"] = realtime
        obs = parse_observations(self._get("/series/observations", **params))
        if len(obs) < min_obs:
            raise FredError(
                f"{series_id}: 관측 {len(obs)}개 — 최소 {min_obs}개를 기대했다. "
                "시리즈 id 나 기간 조건을 확인해라."
            )
        return obs

    def measure_release_lag(
        self,
        series_id: str,
        *,
        as_of: date | None = None,
        vintage_date: str | None = None,
    ) -> LagMeasurement:
        """§3 표의 `발표지연`·`개정` 열 재료를 한 시리즈에 대해 만든다.

        `vintage_date` 를 주면 그 시점 빈티지를 한 번 더 받아 개정 여부까지 판정한다
        (ALFRED). 주지 않으면 `revised=None` — **모른다는 사실을 값으로 남긴다.**
        """
        today = as_of or date.today()
        meta = self.series_meta(series_id)
        obs = self.observations(series_id, min_obs=1)
        latest = max(o.date for o in obs)
        revised: bool | None = None
        note = ""
        if vintage_date is not None:
            old = self.observations(series_id, realtime=(vintage_date, vintage_date), min_obs=0)
            revised, note = detect_revision(obs, old)
        return LagMeasurement(
            series_id=series_id,
            as_of=today,
            latest_observation=latest,
            lag_days=lag_days(latest, today),
            frequency=meta.frequency or infer_frequency(obs),
            n_observations=len(obs),
            revised=revised,
            revision_note=note,
        )

    def measure_all(
        self,
        series: Iterable[str] = ALL_SERIES,
        *,
        as_of: date | None = None,
        vintage_date: str | None = None,
    ) -> list[LagMeasurement]:
        """전 시리즈 실측. 실패한 시리즈는 **삼키지 않고 예외로 올린다.**

        `docs/08` §3 이 `FDEFX`·`PCOPPUSDM` 을 "실측 확인 필요" 로 남겼는데,
        존재하지 않는 시리즈를 조용히 건너뛰면 그 표가 영원히 안 채워진다.
        """
        out: list[LagMeasurement] = []
        failures: list[str] = []
        for sid in series:
            try:
                out.append(self.measure_release_lag(sid, as_of=as_of, vintage_date=vintage_date))
            except FredError as e:
                failures.append(f"{sid}: {e}")
        if failures:
            raise FredError(
                f"{len(failures)}개 시리즈 실측 실패 — 표의 해당 행은 채워지지 않았다:\n  "
                + "\n  ".join(failures)
            )
        return out
