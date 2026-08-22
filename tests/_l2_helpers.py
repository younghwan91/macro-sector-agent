"""L2 테스트 공용 — 작은 DAG·테마·가짜 시리즈 스토어 (실데이터 없음)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from msa.l2.dag import StateRule
from msa.l2.drivers import direction_states
from msa.l2.sources import RawSeries

THEMES = ["alpha", "beta", "gamma", "delta", "epsilon"]  # epsilon 은 DAG 에 없다 → undercovered


def small_dag_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "drivers": [
            {
                "id": "real_rate_10y",
                "source": {"provider": "fred", "series": "DFII10"},
                "measure": "change_6m_bp",
                "state_rule": {"favorable_when": "change_6m_bp < -25", "neutral_band": [-25, 25]},
                "common_factor": False,
            },
            {
                "id": "dollar_broad",
                "source": {"provider": "fred", "series": "DTWEXBGS"},
                "measure": "change_6m",
                "state_rule": {
                    "favorable_when": "change_6m < -0.02",
                    "neutral_band": [-0.02, 0.02],
                },
                "common_factor": False,
            },
            {
                "id": "cpi_yoy",
                "source": {"provider": "fred", "series": "CPIAUCSL"},
                "measure": "yoy",
                "state_rule": {"favorable_when": "yoy > 0.025", "neutral_band": [0.015, 0.025]},
                "common_factor": False,
            },
            {
                "id": "employment",
                "source": {"provider": "fred", "series": ["PAYEMS", "UNRATE"]},
                "measure": "composite_z",
                "state_rule": {
                    "favorable_when": "composite_z > 0.25",
                    "neutral_band": [-0.25, 0.25],
                },
                "common_factor": False,
            },
            {
                "id": "usd_liquidity",
                "source": {"provider": "derived", "formula": "WALCL - WTREGEN - RRPONTSYD"},
                "measure": "change_3m",
                "state_rule": {"favorable_when": "change_3m > 0"},
                "common_factor": True,
            },
            {
                "id": "copper_price",
                "source": {
                    "provider": "fred",
                    "series": "PCOPPUSDM",
                    "fallback": {"provider": "etf", "symbol": "CPER"},
                },
                "measure": "change_6m",
                "state_rule": {"favorable_when": "change_6m > 0.05", "neutral_band": [-0.05, 0.05]},
                "common_factor": False,
            },
            {
                "id": "gold_price",
                "source": {"provider": "etf", "symbol": "GLD", "alt": ["IAU"]},
                "measure": "change_6m",
                "state_rule": {"favorable_when": "change_6m > 0.05", "neutral_band": [-0.05, 0.05]},
                "common_factor": False,
            },
            {
                "id": "china_property",
                "source": {"provider": "manual"},
                "measure": "yoy",
                "state_rule": {"favorable_when": "yoy > 0", "neutral_band": [-0.03, 0.03]},
                "common_factor": False,
            },
            {
                "id": "hyperscaler_capex",
                "source": {"provider": "sharadar_derived", "formula": "sum(capex)"},
                "measure": "yoy",
                "state_rule": {"favorable_when": "yoy > 0.10", "neutral_band": [0.0, 0.10]},
                "common_factor": False,
            },
            {
                "id": "policy_events",
                "source": {"provider": "agent"},
                "measure": "event_window",
                "state_rule": {"favorable_when": "직전 12개월 유리 이벤트"},
                "common_factor": False,
            },
        ],
        "edges": [
            {
                "from": "real_rate_10y",
                "to": ["alpha", "beta"],
                "sign": -1,
                "strength": "strong",
                "lag_months": [0, 3],
                "channel": "할인율",
                "observable": "DFII10 6M < -25bp",
            },
            {
                "from": "dollar_broad",
                "to": ["alpha"],
                "sign": -1,
                "strength": "strong",
                "channel": "달러 표시 가격",
                "observable": "DTWEXBGS 6M < -2%",
                "contradicts_when": "달러와 금이 동반 강세",
                "contradicts_rule": {
                    "all_of": [
                        {"driver": "dollar_broad", "state": 1},
                        {"driver": "gold_price", "state": 1},
                    ]
                },
            },
            {
                "from": "dollar_broad",
                "to": ["gamma", "zeta_unknown"],
                "sign": 1,
                "strength": "weak",
                "channel": "소싱 원가",
                "observable": "DTWEXBGS 6M > +2%",
                "contradicts_when": "관세 동반 시 반대",
            },
            {
                "from": "cpi_yoy",
                "to": ["beta", "gamma"],
                "sign": -1,
                "strength": "moderate",
                "channel": "실질 가처분소득",
                "observable": "CPI YoY > 2.5%",
            },
            {
                "from": "usd_liquidity",
                "to": ["*"],
                "sign": 1,
                "strength": "moderate",
                "common_factor_edge": True,
                "channel": "위험 선호",
                "observable": "3M > 0",
            },
            {
                "from": "policy_events",
                "to": ["delta"],
                "sign": 1,
                "strength": "strong",
                "channel": "정책 수요",
                "observable": "이벤트",
            },
            {
                "from": "gold_price",
                "to": ["alpha"],
                "sign": 1,
                "strength": "strong",
                "channel": "금가격 레버리지",
                "observable": "GLD 6M > 5%",
            },
            {
                "from": "china_property",
                "to": ["delta"],
                "sign": 1,
                "strength": "moderate",
                "channel": "착공 면적",
                "observable": "YoY > 0",
            },
            {
                "from": "hyperscaler_capex",
                "to": ["gamma"],
                "sign": 1,
                "strength": "strong",
                "channel": "발주처 capex",
                "observable": "YoY > 10%",
            },
            {
                "from": "copper_price",
                "to": ["alpha"],
                "sign": 1,
                "strength": "moderate",
                "channel": "구리 가격",
                "observable": "6M > 5%",
            },
            {
                "from": "employment",
                "to": ["gamma"],
                "sign": 1,
                "strength": "weak",
                "channel": "임금 소득",
                "observable": "z > 0.25",
            },
        ],
    }


def write_dag(tmp: Path, doc: dict[str, Any] | None = None) -> Path:
    p = tmp / "macro-dag.yaml"
    p.write_text(yaml.safe_dump(doc or small_dag_dict(), allow_unicode=True, sort_keys=False))
    return p


def write_themes(tmp: Path, ids: list[str] = THEMES) -> Path:
    recs = [
        {
            "id": t,
            "name_ko": t,
            "parent_sector": "X",
            "cycle_class": "commodity_supply",
            "industry_match": [f"Ind{i}"],
            "include_tickers": [],
            "exclude_tickers": [],
            "etf_proxy": None,
            "etf_proxy_alt": [],
            "physical_ref": None,
            "correlation_cluster": None,
            "min_constituents": 5,
        }
        for i, t in enumerate(ids)
    ]
    p = tmp / "themes.yaml"
    p.write_text(yaml.safe_dump({"schema_version": 1, "defaults": {}, "themes": recs}))
    return p


def rule_direction(rule: StateRule, value: float) -> int:
    """스칼라 방향 상태 — `drivers.direction_states` 의 밴드 규칙을 값 하나에 적용 (테스트 전용)."""
    return int(direction_states(pd.Series([value]), rule.band_lo, rule.band_hi).iloc[0])


# ---------------------------------------------------------------- 합성 시리즈


def daily(start: str, end: str, fn: Any, seed: int = 0) -> pd.Series:
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    t = np.arange(len(idx))
    return pd.Series(fn(t) + rng.normal(0, 1e-6, len(idx)), index=idx)


def monthly(start: str, end: str, fn: Any) -> pd.Series:
    """FRED 월간 규약 — 관측일은 매월 1일."""
    idx = pd.date_range(start, end, freq="MS")
    t = np.arange(len(idx))
    return pd.Series(fn(t), index=idx, dtype=float)


class FakeStore:
    """`SeriesStore` 와 같은 메서드를 가진 가짜 — 주어진 것만 있고 나머지는 missing."""

    def __init__(
        self,
        fred: dict[str, pd.Series] | None = None,
        etf: dict[str, pd.Series] | None = None,
        manual: dict[str, tuple[pd.Series, pd.Series | None]] | None = None,
        events: pd.DataFrame | None = None,
        capex: pd.Series | None = None,
        units: dict[str, str] | None = None,
    ) -> None:
        self._fred = fred or {}
        self._etf = etf or {}
        self._manual = manual or {}
        self._events = events
        self._capex = capex
        self._units = units or {}
        self.prefetched: list[str] = []

    def fred(self, symbol: str) -> RawSeries:
        if symbol in self._fred:
            return RawSeries(
                symbol,
                f"fred:{symbol}",
                "ok",
                values=self._fred[symbol],
                units=self._units.get(symbol),
            )
        return RawSeries(symbol, f"fred:{symbol}", "missing", note=f"no cache {symbol}")

    def prefetch_etf(self, symbols: Any) -> None:
        self.prefetched = sorted(symbols)

    def etf(self, symbol: str) -> RawSeries:
        if symbol in self._etf:
            return RawSeries(symbol, f"etf:{symbol}", "ok", values=self._etf[symbol])
        return RawSeries(symbol, f"etf:{symbol}", "missing", note="벌크에 없음")

    def manual(self, symbol: str) -> RawSeries:
        if symbol in self._manual:
            v, a = self._manual[symbol]
            return RawSeries(symbol, f"manual:{symbol}", "ok", values=v, available=a)
        return RawSeries(symbol, f"manual:{symbol}", "missing", note=f"파일 없음 {symbol}.csv")

    def manual_events(self, symbol: str = "policy_events") -> tuple[pd.DataFrame | None, str]:
        if self._events is None:
            return None, "파일 없음 policy_events.csv"
        return self._events, f"{len(self._events)}건"

    def sharadar_capex_ttm(self, grid: pd.DatetimeIndex, tickers: Any = None) -> RawSeries:
        if self._capex is None:
            return RawSeries(
                "hyperscaler_capex", "sharadar:capex_ttm", "missing", note="스토어 없음"
            )
        s = self._capex.reindex(grid)
        return RawSeries(
            "hyperscaler_capex",
            "sharadar:capex_ttm",
            "ok",
            values=s,
            available=pd.Series(s.index, index=s.index),
        )
