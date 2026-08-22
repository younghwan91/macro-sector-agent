"""국면 4분면 (`docs/03-macro-dag.md` §5) — 설명 도구. **분면으로 테마를 고르지 않는다.**

축 (docs/03 §5 그대로):
- 성장축 = z(`industrial_production` yoy 2계차) · z(`new_orders_mfg` 6M) · −z(`inventory_sales` 6M)
  · `employment` composite_z (이미 z 라 다시 표준화하지 않는다) 의 평균
- 인플레축 = z(`cpi_yoy`) · z(`breakeven_10y` 6M bp) · z(`ppi_yoy`) · z(`oil_wti` 6M) 의 평균
- 신용 3차원 = `hy_spread` 방향 상태. +1(확대) 이면 `credit_stress` — 문서는 "전체 스코어에 곱셈
  페널티" 라고만 적었다. **여기서는 플래그와 선언 계수(`CREDIT_PENALTY = 0.5`)만 낸다.** 적용 대상은
  L1+L2 를 합치는 `final(t)` 이고 그 단계는 아직 없다. 0.5 의 근거: 신용 확대 국면에서 거시 순풍의
  신뢰도를 절반으로 깎는다는 선언이지 추정치가 아니다 — 데이터로 정하지 않았다.

z 창은 `drivers.Z_WINDOW`(120개월·최소 60) 와 같다. 축은 구성 드라이버 **2개 이상**이 있어야
계산하고
몇 개로 계산했는지(`n_growth`·`n_inflation`)를 매 행에 적는다. 결측 드라이버는 이름으로 보고한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from msa.l2.drivers import DriverStates, rolling_z

GROWTH_COMPONENTS: tuple[tuple[str, float, bool], ...] = (
    # (driver, 부호, z 표준화 여부)
    ("industrial_production", +1.0, True),
    ("new_orders_mfg", +1.0, True),
    ("inventory_sales", -1.0, True),
    ("employment", +1.0, False),
)
INFLATION_COMPONENTS: tuple[tuple[str, float, bool], ...] = (
    ("cpi_yoy", +1.0, True),
    ("breakeven_10y", +1.0, True),
    ("ppi_yoy", +1.0, True),
    ("oil_wti", +1.0, True),
)
CREDIT_DRIVER = "hy_spread"
CREDIT_PENALTY = 0.5
MIN_COMPONENTS = 2
QUADRANTS = {
    (1, 1): "과열(리플레)",
    (1, -1): "골디락스",
    (-1, 1): "스태그플레이션",
    (-1, -1): "디플레 침체",
}


@dataclass
class RegimeResult:
    axes: (
        pd.DataFrame
    )  # date × growth_z, inflation_z, n_growth, n_inflation, quadrant, credit_state, credit_stress
    current: dict[str, Any]
    missing_growth: list[str]
    missing_inflation: list[str]
    credit_available: bool

    @property
    def available(self) -> bool:
        return bool(self.current.get("quadrant") not in (None, "unavailable"))


def _axis(
    measures: pd.DataFrame, comps: tuple[tuple[str, float, bool], ...]
) -> tuple[pd.Series, pd.Series, list[str]]:
    parts: list[pd.Series] = []
    missing: list[str] = []
    for name, sgn, do_z in comps:
        if name not in measures.columns or measures[name].notna().sum() == 0:
            missing.append(name)
            continue
        s = measures[name]
        parts.append(sgn * (rolling_z(s) if do_z else s))
    if not parts:
        nan = pd.Series(np.nan, index=measures.index, dtype=float)
        return nan, pd.Series(0, index=measures.index, dtype=int), missing
    m = pd.concat(parts, axis=1)
    n = m.notna().sum(axis=1)
    axis = m.mean(axis=1).where(n >= MIN_COMPONENTS)
    return axis, n, missing


def classify(growth: float, inflation: float) -> str:
    if not (np.isfinite(growth) and np.isfinite(inflation)):
        return "unavailable"
    return QUADRANTS[(1 if growth >= 0 else -1, 1 if inflation >= 0 else -1)]


def compute_regime(ds: DriverStates, *, months: int = 24) -> RegimeResult:
    g, ng, miss_g = _axis(ds.measures, GROWTH_COMPONENTS)
    i, ni, miss_i = _axis(ds.measures, INFLATION_COMPONENTS)
    credit = (
        ds.states[CREDIT_DRIVER]
        if CREDIT_DRIVER in ds.states.columns
        else pd.Series(np.nan, index=ds.grid, dtype=float)
    )
    axes = pd.DataFrame(
        {
            "growth_z": g,
            "inflation_z": i,
            "n_growth": ng,
            "n_inflation": ni,
            "credit_state": credit,
        },
        index=ds.grid,
    )
    axes["quadrant"] = [
        classify(a, b) for a, b in zip(axes["growth_z"], axes["inflation_z"], strict=True)
    ]
    axes["credit_stress"] = axes["credit_state"] == 1.0
    tail = axes.loc[: ds.asof].tail(months)
    last = tail.iloc[-1] if len(tail) else None
    current: dict[str, Any] = {
        "asof": str(ds.asof.date()),
        "growth_z": None if last is None else _f(last["growth_z"]),
        "inflation_z": None if last is None else _f(last["inflation_z"]),
        "n_growth": 0 if last is None else int(last["n_growth"]),
        "n_inflation": 0 if last is None else int(last["n_inflation"]),
        "quadrant": "unavailable" if last is None else str(last["quadrant"]),
        "credit_state": None if last is None else _f(last["credit_state"]),
        "credit_stress": bool(last is not None and last["credit_stress"]),
        "credit_penalty": CREDIT_PENALTY,
    }
    return RegimeResult(
        axes=tail,
        current=current,
        missing_growth=miss_g,
        missing_inflation=miss_i,
        credit_available=bool(credit.notna().any()),
    )


def _f(v: Any) -> float | None:
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v)


def render_ascii(res: RegimeResult, *, width: int = 61, height: int = 21, lim: float = 3.0) -> str:
    """성장(가로) × 인플레(세로) 산점 — 최근 24개월 궤적.

    `·` 13~24개월 전 · `o` 최근 12개월 · `@` 최신.
    """
    lines: list[str] = []
    if not res.available:
        lines.append("국면 4분면: 계산 불가")
        if res.missing_growth:
            lines.append(f"  성장축 결측 드라이버: {', '.join(res.missing_growth)}")
        if res.missing_inflation:
            lines.append(f"  인플레축 결측 드라이버: {', '.join(res.missing_inflation)}")
        if not res.credit_available:
            lines.append(f"  신용축 결측: {CREDIT_DRIVER}")
        return "\n".join(lines)
    cx, cy = width // 2, height // 2
    canvas = [[" "] * width for _ in range(height)]
    for r in range(height):
        canvas[r][cx] = "│"
    for c in range(width):
        canvas[cy][c] = "─"
    canvas[cy][cx] = "┼"
    pts = res.axes.dropna(subset=["growth_z", "inflation_z"])
    n = len(pts)
    for k, (_, row) in enumerate(pts.iterrows()):
        x = round(cx + float(row["growth_z"]) / lim * cx)
        y = round(cy - float(row["inflation_z"]) / lim * cy)
        x = min(max(x, 0), width - 1)
        y = min(max(y, 0), height - 1)
        mark = "@" if k == n - 1 else ("o" if k >= n - 12 else "·")
        canvas[y][x] = mark
    lines.append(f"{'인플레 ↑':^{width}}")
    lines.append(f"{'스태그플레이션':<{cx}}{'':1}{'과열(리플레)':>{cx}}")
    for r in range(height):
        lines.append("".join(canvas[r]))
    lines.append(f"{'디플레 침체':<{cx}}{'':1}{'골디락스':>{cx}}")
    lines.append(f"{'인플레 ↓':^{width}}")
    lines.append(f"성장 ← {'':{width - 16}} → 성장   (축 범위 ±{lim:.0f}σ)")
    cur = res.current
    lines.append(
        f"최신 {cur['asof']}: 성장 z={cur['growth_z']:+.2f} ({cur['n_growth']}/4) · "
        f"인플레 z={cur['inflation_z']:+.2f} ({cur['n_inflation']}/4) → {cur['quadrant']}"
    )
    if res.credit_available:
        lines.append(
            f"신용 3차원 hy_spread 상태 {cur['credit_state']:+.0f} → "
            + (
                "신용 스트레스 (페널티 계수 " + f"{CREDIT_PENALTY} 선언)"
                if cur["credit_stress"]
                else "정상"
            )
        )
    else:
        lines.append(f"신용 3차원: {CREDIT_DRIVER} 없음")
    miss = res.missing_growth + res.missing_inflation
    if miss:
        lines.append(f"결측 구성 드라이버 (축은 ≥{MIN_COMPONENTS}개로 계산): {', '.join(miss)}")
    lines.append("4분면은 설명 도구다 — 테마 선택은 §4 엣지 기반 tailwind 로 한다.")
    return "\n".join(lines)
