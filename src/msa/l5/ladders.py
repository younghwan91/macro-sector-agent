"""사다리 · 스탑 · TP — `docs/07-portfolio.md` §3·§4·§5 의 산술.

전부 **선언값**이다. 표는 문서의 것이고 여기서는 숫자를 만들지 않는다 (`CLAUDE.md` §1).

| 항목 | 값 | 출처 |
|---|---|---|
| 물타기 3단 (c 구간별) | ≥0.75: 60/25/15 · [0.6,0.75): 50/30/20 · [0.5,0.6): 35/35/30 | §3 |
| 2단·3단 발동가 | 초기가 −13% · −23% ("−12~15%"·"−22~25%" 의 기준점; §4 표의 0.87·0.77) | §3·§4 |
| Tier-2 자본 스탑 | **평단** −35%, 또는 포지션 손실 = 총자본 8% — **둘 중 먼저 오는 쪽** | §4 |
| 손실 기여 | 테마 상한 0.35 × Tier-2 0.35 = 총자본의 12.25% (= 예산 30% 의 40.8%) | §4 |
| 시간 스탑 | 기준일 + `horizon_months[1]` 개월, **AND** 충족 트리거 0건 | §4 |
| TP1 · TP2 · 러너 | 1/3 씩 — P50 또는 +2R · P75 또는 직전 고점 50% 회복 · 트레일 −25%/10주선 | §5 |
| `R` | 초기 진입가 − Tier-2 스탑가 | §5 |

M0.1 에서 정정한 산술을 이 모듈이 재현해야 한다 (테스트가 잰다):
50/30/20 사다리 → 평단 0.9150 (초기가 −8.5%), Tier-2 0.5948 (초기가 **−40.5%**), 손실 기여 12.25%.

> 물타기는 가격이 아니라 **논지 상태**에 조건부다 — 무효화 1건이라도 `fired` 면 추가 매수 금지.
> 이 모듈은 가격 조건을 계산할 뿐이고, 논지 조건은 계획서에 **함께** 찍힌다 (`plan.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from msa.l5.inputs import Pick, ThesisInput

#: 확신도 구간 → 사다리 비율 (1단 / 2단 / 3단). 선언값 (docs/07 §3)
LADDER_HIGH: tuple[float, float, float] = (0.60, 0.25, 0.15)
LADDER_MID: tuple[float, float, float] = (0.50, 0.30, 0.20)
LADDER_LOW: tuple[float, float, float] = (0.35, 0.35, 0.30)
LADDER_C_HIGH = 0.75
LADDER_C_MID = 0.60
LADDER_C_MIN = 0.50  # = C6 최소 확신도

ADD2_DRAWDOWN = 0.13
ADD3_DRAWDOWN = 0.23
TIER2_FROM_AVG = 0.35
TIER2_CAPITAL_LOSS = 0.08
THEME_CAP_FOR_LOSS = 0.35  # C3 테마 상한 — 손실 기여 계산용
TP1_R_MULTIPLE = 2.0
TP2_PEAK_RECOVERY = 0.50
RUNNER_TRAIL = 0.25
RUNNER_MA_WEEKS = 10


class LadderError(ValueError):
    pass


def ladder_fractions(c: float) -> tuple[float, float, float]:
    """확신도 → 사다리 3단 비율. c < 0.5 는 편입 불가이므로 예외."""
    if c >= LADDER_C_HIGH:
        return LADDER_HIGH
    if c >= LADDER_C_MID:
        return LADDER_MID
    if c >= LADDER_C_MIN:
        return LADDER_LOW
    raise LadderError(f"c={c:.2f} < {LADDER_C_MIN} — C6 최소 확신도 미달, 사다리를 만들지 않는다")


@dataclass(frozen=True)
class LadderMath:
    """초기 진입가 = 1.0 으로 정규화한 사다리 산술 (docs/07 §4 표)."""

    fractions: tuple[float, float, float]
    leg_prices: tuple[float, float, float]  # 1.0 · 1−ADD2 · 1−ADD3
    avg_cost: float  # 완납 평단 (초기가 대비 배수)
    avg_vs_initial: float  # 평단/초기가 − 1  (음수)
    tier2_price: float  # 평단 × (1 − 0.35)
    tier2_vs_initial: float  # tier2/초기가 − 1
    loss_contribution_at_theme_cap: float  # 0.35 × 0.35

    def as_dict(self) -> dict[str, object]:
        return {
            "fractions": list(self.fractions),
            "leg_prices": list(self.leg_prices),
            "avg_cost": self.avg_cost,
            "avg_vs_initial": self.avg_vs_initial,
            "tier2_price": self.tier2_price,
            "tier2_vs_initial": self.tier2_vs_initial,
            "loss_contribution_at_theme_cap": self.loss_contribution_at_theme_cap,
        }


def ladder_math(c: float) -> LadderMath:
    f = ladder_fractions(c)
    legs = (1.0, 1.0 - ADD2_DRAWDOWN, 1.0 - ADD3_DRAWDOWN)
    avg = sum(fi * pi for fi, pi in zip(f, legs, strict=True))
    t2 = avg * (1.0 - TIER2_FROM_AVG)
    return LadderMath(
        fractions=f,
        leg_prices=legs,
        avg_cost=avg,
        avg_vs_initial=avg - 1.0,
        tier2_price=t2,
        tier2_vs_initial=t2 - 1.0,
        loss_contribution_at_theme_cap=THEME_CAP_FOR_LOSS * TIER2_FROM_AVG,
    )


def add_months(d: date, months: int) -> date:
    ts = pd.Timestamp(d) + pd.DateOffset(months=months)
    return ts.date()


@dataclass(frozen=True)
class PositionPlan:
    """종목 하나의 매매계획 — 비중·사다리·스탑·TP. 가격은 `entry_price` 가 있을 때만 채워진다."""

    ticker: str
    theme: str
    role: str
    target_weight: float
    c: float
    ladder: LadderMath
    leg_weights: tuple[float, float, float]  # 목표비중 × 비율
    split_first_leg: bool
    entry_price: float | None
    leg_prices: tuple[float | None, float | None, float | None]
    tier1_invalidations: tuple[str, ...]
    tier2_price: float | None
    tier2_vs_initial: float
    tier2_capital_rule_price: float | None  # 포지션 손실 = 총자본 8% 가 되는 가격 (평단 기준)
    tier2_effective_price: float | None  # 둘 중 먼저 오는(높은) 쪽
    tier2_rule: str  # "avg−35%" | "capital 8%"
    time_stop: date
    horizon_months: tuple[int, int]
    r_unit: float | None  # 초기가 − Tier2 유효가
    tp1_price: float | None  # max(P50, entry + 2R) 가 아니라 "또는" — 둘 다 적는다
    tp1_p50_price: float | None
    tp2_r_price: float | None  # 직전 고점 50% 회복가
    tp2_p75_price: float | None
    runner_trail: float
    triggers: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "theme": self.theme,
            "role": self.role,
            "target_weight": self.target_weight,
            "c": self.c,
            "ladder": self.ladder.as_dict(),
            "leg_weights": list(self.leg_weights),
            "split_first_leg": self.split_first_leg,
            "entry_price": self.entry_price,
            "leg_prices": list(self.leg_prices),
            "tier1_invalidations": list(self.tier1_invalidations),
            "tier2_price": self.tier2_price,
            "tier2_vs_initial": self.tier2_vs_initial,
            "tier2_capital_rule_price": self.tier2_capital_rule_price,
            "tier2_effective_price": self.tier2_effective_price,
            "tier2_rule": self.tier2_rule,
            "time_stop": str(self.time_stop),
            "horizon_months": list(self.horizon_months),
            "r_unit": self.r_unit,
            "tp1_price": self.tp1_price,
            "tp1_p50_price": self.tp1_p50_price,
            "tp2_r_price": self.tp2_r_price,
            "tp2_p75_price": self.tp2_p75_price,
            "runner_trail": self.runner_trail,
            "triggers": list(self.triggers),
        }


def build_position_plan(
    pick: Pick, thesis: ThesisInput, *, target_weight: float, asof: date
) -> PositionPlan:
    """비중 하나와 논지 하나로 그 종목의 사다리·스탑·TP 를 만든다."""
    c = thesis.cycle_confidence
    lm = ladder_math(c)
    f = lm.fractions
    leg_w = (target_weight * f[0], target_weight * f[1], target_weight * f[2])
    e = pick.entry_price
    leg_px: tuple[float | None, float | None, float | None]
    t2_px: float | None
    cap_px: float | None
    eff_px: float | None
    rule = "avg−35%"
    r_unit: float | None = None
    tp1_px: float | None = None
    tp2_px: float | None = None
    if e is not None and e > 0:
        leg_px = (e, e * lm.leg_prices[1], e * lm.leg_prices[2])
        avg = e * lm.avg_cost
        t2_px = e * lm.tier2_price
        # 포지션 손실이 총자본 8% 가 되는 평단 대비 손실률 = 0.08 / w (w ≤ 0.15 면 −35% 보다 멀다)
        cap_px = None
        if target_weight > 0:
            loss_frac = TIER2_CAPITAL_LOSS / target_weight
            if loss_frac < 1.0:
                cap_px = avg * (1.0 - loss_frac)
        eff_px = t2_px
        if cap_px is not None and cap_px > t2_px:
            eff_px = cap_px
            rule = "capital 8%"
        r_unit = e - eff_px
        tp1_px = e + TP1_R_MULTIPLE * r_unit
        if pick.prev_cycle_peak_price is not None and pick.prev_cycle_peak_price > e:
            tp2_px = e + TP2_PEAK_RECOVERY * (pick.prev_cycle_peak_price - e)
    else:
        leg_px = (None, None, None)
        t2_px = cap_px = eff_px = None
    return PositionPlan(
        ticker=pick.ticker,
        theme=pick.theme,
        role=pick.role,
        target_weight=target_weight,
        c=c,
        ladder=lm,
        leg_weights=leg_w,
        split_first_leg=pick.split_first_leg,
        entry_price=e,
        leg_prices=leg_px,
        tier1_invalidations=thesis.invalidations,
        tier2_price=t2_px,
        tier2_vs_initial=lm.tier2_vs_initial,
        tier2_capital_rule_price=cap_px,
        tier2_effective_price=eff_px,
        tier2_rule=rule,
        time_stop=add_months(asof, thesis.horizon_months[1]),
        horizon_months=thesis.horizon_months,
        r_unit=r_unit,
        tp1_price=tp1_px,
        tp1_p50_price=pick.tp_p50_price,
        tp2_r_price=tp2_px,
        tp2_p75_price=pick.tp_p75_price,
        runner_trail=RUNNER_TRAIL,
        triggers=thesis.triggers,
    )
