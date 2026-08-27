"""SOCP — `docs/07-portfolio.md` §2 의 정식화를 그대로 푼다 (`cvxpy`, 기본 솔버 CLARABEL).

```
max_w  Σ_i c̃_{t(i)} · μ_i · w_i                       (μ 방식 (a) 균등: μ_i = 1)
 s.t.  C1-(i)  k·‖Σ^{1/2} w‖₂ ≤ B          k = 2.2, B = 0.30      (2차 원뿔)
       C1-(ii) Σ_{i: L_i 있음} w_i·L_i ≤ B                        (선형 · 부분합)
       C3      w_i ≤ 0.15 · Σ_{i∈t} w_i ≤ 0.35 · Σ_{i∈class} w_i ≤ 0.55
       C4      w_i · Capital ≤ 0.10 · ADV20_i                    (자본·ADV 둘 다 있을 때)
       C5      Σ w_i ≤ 1 − 0.15
       C6      c_{t(i)} ≥ 0.50 인 테마만 변수에 남긴다            (풀기 전 필터)
       w_i ≥ min_weight_i ≥ 0                                     (하한 — 선택)
       (선택) 클러스터 상한 Σ_{i∈cluster} w_i ≤ cap             (사용자가 요구했을 때만)
```

**C1 의 "보수적인 쪽"** — 두 제약을 **동시에** 건다. 둘 다 걸면 자동으로 더 타이트한 쪽이 구속하고,
풀고 난 뒤 어느 쪽이 경계에 붙었는지(`mdd_binding`) 를 잰다. (ii) 에 `L_i` 가 없는 종목은 합에서
빠진다 — 그 사실은 `scenario_missing` 으로 돌려주고 계획서가 경고로 찍는다. 조용히 0 으로 넣지
않는다.

**확신도 압축** (`docs/07` §2.3 (2)): `c̃_t = c̄ + (1−λ)(c_t − c̄)`, `c̄` = 편입 후보(C6 통과) 테마의
평균, **λ = 0.3 선언값.** 평균 보존·분산 축소이므로 선형성이 유지된다.

**infeasible 완화 순서 — C3 → C1 고정** (`docs/09` §5). 하한(`min_weight`·`min_gross`) 이 없으면
`w = 0` 이 항상 feasible 이므로 infeasible 은 하한이 있을 때만 생긴다.
- 0단: 전부 건다.
- 1단: C3 를 **내린다** (세 상한 전부). 진단에 `relaxed: ["C3"]`.
- 2단: C1 예산을 0.35 → 0.40 → 0.45 → 0.50 으로 올린다 (5%p 씩, 선언). 그래도 안 되면 예외 —
  MDD 는 마지막까지 지키고, 0.50 을 넘는 예산은 이 저장소의 전제(30% 감내)와 양립하지 않는다.
ENB 는 구속이 아니므로 완화 대상이 아니다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from functools import cached_property
from typing import Any

import cvxpy as cp
import numpy as np
from numpy.typing import NDArray

from msa.l3.gates import PORTFOLIO_MIN_CONFIDENCE

log = logging.getLogger(__name__)

FArray = NDArray[np.float64]

#: 선언값 — 근거는 docs/07 §2. 탐색으로 바꾸지 않는다 (CLAUDE.md §1)
MDD_BUDGET = 0.30
MDD_K = 2.2
CAP_STOCK = 0.15
CAP_THEME = 0.35
CAP_CLASS = 0.55
LIQ_FRACTION_OF_ADV = 0.10
CASH_FLOOR = 0.15
#: **`l3.gates.PORTFOLIO_MIN_CONFIDENCE` 를 그대로 쓴다.** C6 은 L3 가 세운 편입선을 L5 가
#: 다시 거는 것이지 새 값이 아니다. 두 곳에 두면 한쪽만 옮겨도 조용히 갈라진다 (2026-08-28).
MIN_CONFIDENCE = PORTFOLIO_MIN_CONFIDENCE
LAMBDA_COMPRESS = 0.30
MU_METHOD = "(a) 균등"
#: 2단 완화에서 순서대로 시도하는 예산. 0.50 을 넘기지 않는다.
RELAX_BUDGETS: tuple[float, ...] = (0.35, 0.40, 0.45, 0.50)
SOLVER_PREFERENCE: tuple[str, ...] = ("CLARABEL", "SCS", "ECOS")


class OptimizeError(RuntimeError):
    """풀 수 없다 (완화를 다 써도 infeasible, 또는 솔버 실패)."""


def compress_confidence(c: Mapping[str, float], lam: float = LAMBDA_COMPRESS) -> dict[str, float]:
    """`c̃_t = c̄ + (1−λ)(c_t − c̄)`. 빈 입력이면 빈 출력."""
    if not 0.0 <= lam <= 1.0:
        raise ValueError(f"λ 는 [0,1]: {lam}")
    if not c:
        return {}
    cbar = float(sum(c.values()) / len(c))
    return {t: cbar + (1.0 - lam) * (v - cbar) for t, v in c.items()}


@dataclass(frozen=True)
class Problem:
    """종목 단위로 정렬된 최적화 입력. 길이는 전부 n.

    `loss_vec`/`has_loss`/`sigma_half` 는 한 번 계산해 완화 시도마다 다시 쓴다 (`cached_property`).
    """

    tickers: tuple[str, ...]
    themes: tuple[str, ...]
    classes: tuple[str, ...]
    clusters: tuple[str | None, ...]
    coef: tuple[float, ...]  # c̃_{t(i)} · μ_i
    sigma: FArray  # n × n 연율 공분산
    scenario_loss: tuple[float | None, ...]  # L_i (None = 없음)
    adv20_usd: tuple[float | None, ...]
    min_weight: tuple[float, ...]
    capital_usd: float | None = None
    min_gross: float = 0.0
    cluster_caps: Mapping[str, float] = field(default_factory=dict)
    mdd_budget: float = MDD_BUDGET
    k: float = MDD_K

    def __post_init__(self) -> None:
        n = len(self.tickers)
        for name in ("themes", "classes", "clusters", "coef", "scenario_loss", "adv20_usd"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"Problem.{name} 길이 {len(getattr(self, name))} ≠ n={n}")
        if len(self.min_weight) != n:
            raise ValueError("Problem.min_weight 길이 불일치")
        if self.sigma.shape != (n, n):
            raise ValueError(f"sigma 는 {n}×{n} 이어야 한다: {self.sigma.shape}")
        if n == 0:
            raise ValueError("변수가 0개다 — C6 을 통과한 후보가 없다")

    @property
    def n(self) -> int:
        return len(self.tickers)

    @cached_property
    def has_loss(self) -> NDArray[np.bool_]:
        """`L_i` 가 있는 종목 (C1-(ii) 부분합에 들어가는 것)."""
        return np.array([v is not None for v in self.scenario_loss], dtype=bool)

    @cached_property
    def loss_vec(self) -> FArray:
        """`L_i` (없으면 0 — 합에서 빠지는 것은 `has_loss` 가 말한다)."""
        return np.array([v if v is not None else 0.0 for v in self.scenario_loss], dtype=np.float64)

    @cached_property
    def sigma_half(self) -> FArray:
        return _sigma_half(self.sigma)


@dataclass(frozen=True)
class Solution:
    weights: dict[str, float]
    status: str
    solver: str
    stage: int  # 0 = 완화 없음, 1 = C3 완화, 2 = C1 예산 완화
    relaxed: tuple[str, ...]
    budget_used: float  # 실제 쓰인 MDD 예산 (완화 후)
    mdd_vol: float  # k·σ_p
    mdd_scenario: float | None  # Σ w_i L_i (부분합; L_i 전무면 None)
    mdd_binding: str  # "vol" | "scenario" | "both" | "none"
    scenario_missing: tuple[str, ...]  # L_i 없어 (ii) 합에서 빠진 종목
    c4_applied: bool
    c4_skipped: tuple[str, ...]  # ADV 없어 C4 못 건 종목
    gross: float
    cash: float
    theme_weights: dict[str, float]
    class_weights: dict[str, float]
    cluster_weights: dict[str, float]
    objective: float
    binding_caps: tuple[str, ...]  # 경계에 붙은 C3/C4/C5/클러스터 상한
    #: 종목별 허용 구간 `(하한, 상한)` — 하한은 `min_weight`, 상한은 C3 종목 상한과
    #: C4 유동성 상한 중 **작은 쪽**. 해를 나중에 손보는 쪽(`l5.run`)이 제약을 다시
    #: 유도하지 않게 여기서 준다 — 유도가 두 벌이면 한쪽만 갱신돼도 조용히 어긋난다.
    bounds: dict[str, tuple[float, float]]

    def as_dict(self) -> dict[str, object]:
        """진단용 — `weights` 는 빼고 전부 (비중은 weights.csv·positions 가 들고 있다)."""
        return {k: v for k, v in asdict(self).items() if k != "weights"}


def _sigma_half(sigma: FArray) -> FArray:
    """대칭 PSD 제곱근 — `‖Σ^{1/2} w‖₂ = σ_p`."""
    s = np.asarray((sigma + sigma.T) / 2.0, dtype=np.float64)
    lam, vec = np.linalg.eigh(s)
    lam = np.clip(lam, 0.0, None)
    return np.asarray(vec @ np.diag(np.sqrt(lam)) @ vec.T, dtype=np.float64)


def _pick_solver() -> str:
    installed = set(cp.installed_solvers())
    for s in SOLVER_PREFERENCE:
        if s in installed:
            return s
    raise OptimizeError(f"쓸 수 있는 원뿔 솔버가 없다. 설치됨: {sorted(installed)}")


def _groups(keys: Sequence[str | None]) -> dict[str, list[int]]:
    g: dict[str, list[int]] = {}
    for i, k in enumerate(keys):
        if k is None:
            continue
        g.setdefault(k, []).append(i)
    return g


@dataclass(frozen=True)
class _Built:
    """한 번 만든 cvxpy 문제 — `budget` 만 파라미터라 완화 2단의 예산 변경에 다시 만들지 않는다."""

    prob: cp.Problem
    w: cp.Variable
    budget: cp.Parameter
    named: dict[str, Any]


def _build(p: Problem, *, with_c3: bool) -> _Built:
    """제약을 전부 세운다. `named` 는 경계 판정(슬랙)에 쓰는 제약들이다."""
    n = p.n
    w = cp.Variable(n, nonneg=True)
    budget = cp.Parameter(nonneg=True)
    cons: list[Any] = []
    named: dict[str, Any] = {}

    def add(name: str | None, c: Any) -> None:
        cons.append(c)
        if name is not None:
            named[name] = c

    # C5 현금 하한
    add("C5", cp.sum(w) <= 1.0 - CASH_FLOOR)
    if p.min_gross > 0:
        add(None, cp.sum(w) >= p.min_gross)
    # 하한
    mw = np.asarray(p.min_weight, dtype=np.float64)
    if (mw > 0).any():
        add(None, w >= mw)
    # C1-(i)
    add("C1-i", p.k * cp.norm(p.sigma_half @ w, 2) <= budget)
    # C1-(ii) 부분합
    if p.has_loss.any():
        add("C1-ii", p.loss_vec @ w <= budget)
    # C3
    if with_c3:
        for i, tk in enumerate(p.tickers):
            add(f"C3-stock:{tk}", w[i] <= CAP_STOCK)
        for t, idx in _groups(p.themes).items():
            add(f"C3-theme:{t}", cp.sum(w[idx]) <= CAP_THEME)
        for k_, idx in _groups(p.classes).items():
            add(f"C3-class:{k_}", cp.sum(w[idx]) <= CAP_CLASS)
    # C4
    if p.capital_usd is not None and p.capital_usd > 0:
        for i, adv in enumerate(p.adv20_usd):
            if adv is not None and adv > 0:
                add(f"C4:{p.tickers[i]}", w[i] <= LIQ_FRACTION_OF_ADV * adv / p.capital_usd)
    # 클러스터 상한 (선택)
    cl = _groups(p.clusters)
    for name, cap in p.cluster_caps.items():
        if name not in cl:
            raise OptimizeError(
                f"클러스터 상한 {name!r}: 후보에 그 클러스터가 없다 (있는 것: {sorted(cl)})"
            )
        add(f"cluster:{name}", cp.sum(w[cl[name]]) <= cap)

    coef = np.asarray(p.coef, dtype=np.float64)
    return _Built(cp.Problem(cp.Maximize(coef @ w), cons), w, budget, named)


def _try_solve(
    built: _Built, *, budget: float, solver: str
) -> tuple[str, FArray | None, dict[str, float]]:
    """한 번 푼다. (status, w, 제약 슬랙) 을 돌려준다."""
    built.budget.value = budget
    try:
        built.prob.solve(solver=solver)
    except cp.error.SolverError as e:  # pragma: no cover - 솔버 내부 실패
        raise OptimizeError(f"{solver} 실패: {e}") from e
    status = str(built.prob.status)
    if status not in ("optimal", "optimal_inaccurate"):
        return status, None, {}
    wv = np.asarray(built.w.value, dtype=np.float64).reshape(-1)
    wv = np.where(wv < 1e-9, 0.0, wv)
    slacks: dict[str, float] = {}
    for k_, c in built.named.items():
        sl = getattr(c, "expr", None)
        # cvxpy 의 Inequality: expr = lhs − rhs ≤ 0. 값이 0 근방이면 경계.
        val = getattr(sl, "value", None) if sl is not None else None
        if val is not None:
            slacks[k_] = float(-np.asarray(val).reshape(-1)[0])
    return status, wv, slacks


def solve(p: Problem, *, relax: bool = True) -> Solution:
    """풀고, 필요하면 C3 → C1 순으로 완화한다."""
    solver = _pick_solver()
    attempts: list[tuple[int, bool, float, tuple[str, ...]]] = [(0, True, p.mdd_budget, ())]
    if relax:
        attempts.append((1, False, p.mdd_budget, ("C3",)))
        attempts.extend((2, False, b, ("C3", f"C1 예산 {b:.2f}")) for b in RELAX_BUDGETS)
    last_status = ""
    built: dict[bool, _Built] = {}  # C3 포함/제외 두 문제만 있다 — 예산은 파라미터
    for stage, with_c3, budget, relaxed in attempts:
        if with_c3 not in built:
            built[with_c3] = _build(p, with_c3=with_c3)
        status, w, slacks = _try_solve(built[with_c3], budget=budget, solver=solver)
        last_status = status
        if w is None:
            log.warning("optimize: stage %d (C3=%s, B=%.2f) → %s", stage, with_c3, budget, status)
            continue
        return _finish(p, w, status, solver, stage, relaxed, budget, slacks)
    raise OptimizeError(
        f"완화를 전부 써도 infeasible (마지막 상태 {last_status}). 하한(min_weight·min_gross)이 "
        "C5·C4 와 양립하지 않는다 — 입력을 고쳐라. MDD 예산은 0.50 너머로 올리지 않는다."
    )


def _finish(
    p: Problem,
    w: FArray,
    status: str,
    solver: str,
    stage: int,
    relaxed: tuple[str, ...],
    budget: float,
    slacks: Mapping[str, float],
) -> Solution:
    sigma_p = float(np.sqrt(max(float(w @ p.sigma @ w), 0.0)))
    mdd_vol = p.k * sigma_p
    has_l = p.has_loss
    mdd_sc: float | None = None
    if has_l.any():
        mdd_sc = float(sum(w[i] * (p.scenario_loss[i] or 0.0) for i in range(p.n) if has_l[i]))
    tol = 1e-4
    vol_b = mdd_vol >= budget - tol
    sc_b = mdd_sc is not None and mdd_sc >= budget - tol
    binding = "both" if vol_b and sc_b else "vol" if vol_b else "scenario" if sc_b else "none"

    def group_sums(keys: Sequence[str | None]) -> dict[str, float]:
        return {k: float(sum(float(w[i]) for i in idx)) for k, idx in _groups(keys).items()}

    c4_applied = p.capital_usd is not None and p.capital_usd > 0
    c4_skipped = tuple(
        p.tickers[i] for i in range(p.n) if c4_applied and not (p.adv20_usd[i] or 0) > 0
    )
    binding_caps = tuple(
        k
        for k, s in slacks.items()
        if k.startswith(("C3", "C4", "C5", "cluster")) and abs(s) <= tol
    )
    gross = float(w.sum())
    mw = np.asarray(p.min_weight, dtype=np.float64)
    bounds: dict[str, tuple[float, float]] = {}
    for i, tk in enumerate(p.tickers):
        hi = CAP_STOCK
        adv = p.adv20_usd[i]
        if c4_applied and adv is not None and adv > 0 and p.capital_usd:
            hi = min(hi, LIQ_FRACTION_OF_ADV * adv / p.capital_usd)
        bounds[tk] = (float(mw[i]), float(hi))
    return Solution(
        weights={p.tickers[i]: float(w[i]) for i in range(p.n)},
        status=status,
        solver=solver,
        stage=stage,
        relaxed=relaxed,
        budget_used=budget,
        mdd_vol=mdd_vol,
        mdd_scenario=mdd_sc,
        mdd_binding=binding,
        scenario_missing=tuple(p.tickers[i] for i in range(p.n) if not has_l[i]),
        c4_applied=c4_applied,
        c4_skipped=c4_skipped,
        gross=gross,
        cash=1.0 - gross,
        theme_weights=group_sums(p.themes),
        class_weights=group_sums(p.classes),
        cluster_weights=group_sums(p.clusters),
        objective=float(np.asarray(p.coef) @ w),
        binding_caps=binding_caps,
        bounds=bounds,
    )
