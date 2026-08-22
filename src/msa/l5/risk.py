"""리스크 입력 — 공분산 · ENB · 과거 유사 국면 낙폭 · 시나리오 손실 `L_i`.

## 공분산 `Σ` (`docs/07` §2.4 C1-(i)·C2)

문서는 "구성종목 수익률의 공분산(252일, Ledoit-Wolf 축소)" 이라고 적었다. 두 경로를 둔다.

1. **종목 수익률이 있으면** (`<inputs>/returns.csv`, date × ticker) 그것으로 표본 공분산을 만든다.
2. **없으면 테마 EW 지수의 월간 수익률**(L1 캐시 `state/cache/l1_panel_*.parquet`)로 테마 공분산을
   만들고, 종목은 자기 테마 지수에 β=1 로 사상한다: `Σ_stock = B Σ_theme Bᵀ + diag(σ²_idio)`.
   `σ_idio` 는 `picks.csv` 의 `idio_vol_ann` 이며 없으면 0 — 그러면 같은 테마의 종목은 상관 1 로
   들어간다. 스트레스 국면에서는 그것이 오히려 정직한 가정이고, 어느 경로를 썼는지는 진단에 적는다.

**축소: 상수상관(constant-correlation) 타깃, 강도 δ = 0.5 (선언값).**
Ledoit-Wolf(2004) 의 해석적 최적 강도를 쓰지 않는 이유는 둘이다 — sklearn 을 의존성에 넣지
않기로 했고, 표본(60개월)이 짧아 해석적 강도가 1 근방으로 튀는 일이 잦다. δ=0.5 는 "표본과 타깃을
반반 믿는다" 는 선언이며 탐색으로 얻은 값이 아니다 (`CLAUDE.md` §1).

룩백 **60개월** (선언): 사이클 논지의 horizon 6~18개월(`docs/09` §1) 을 서너 번 담는 최소 길이.
연율화는 월간 × 12.

## ENB (`docs/07` §2.4 C2 — 구속 아님, 리포트 지표)

```
Σ = V Λ Vᵀ,  y = Vᵀ w,  p_k = λ_k y_k² / (wᵀ Σ w),  ENB = exp(−Σ p_k log p_k)
```

`p₁·p₂·p₃` (내림차순 상위 3개) 를 함께 돌려준다. **임계는 없다** — `docs/07` §2.4 (b).

## 과거 유사 국면 최대 낙폭 (`L_i` 의 첫째 항) — "유사 국면" 의 선언

> **유사 국면 = 테마 EW 지수가 직전 고점 대비 −50% 에 처음 도달한 시점부터, 지수가 그 고점을
> 회복할 때까지의 구간.** 낙폭 50% 는 L1 이 테마를 스코어보드 상단에 올리는 바로 그 조건이며
> (`CLAUDE.md` §1 의 임계 예시 "낙폭 50%"), 이 포트가 진입하는 국면이 정확히 그 지점이다.
> 각 에피소드에서 재는 것은 **진입 시점(−50% 도달일) 가격 → 그 에피소드 안의 최저가** 의 손실이고,
> 에피소드들 중 **최대값**을 쓴다. 진행 중인 에피소드(아직 고점 미회복)도 포함한다 — 지금까지의
> 손실이 이미 관측값이기 때문이다. 에피소드가 하나도 없으면 이 항은 **없음**이다
> (0 으로 채우지 않는다).

탐색하지 않았다: 임계 −50% 와 "진입 후 추가 낙폭" 이라는 정의는 선언이다.

## 시나리오 손실 `L_i` (`docs/07` §2.4 C1-(ii))

```
L_i = max(과거 유사 국면 최대 낙폭, 케이스 스터디 사망 사례 낙폭 × 0.5)
```

두 항 **모두** 있어야 `L_i` 가 선다. 어느 한 항이라도 없으면 `L_i = None` 이고 사유가 남는다 —
특히 케이스가 없으면 C1-(ii) 는 그 테마를 **계산할 수 없다** (`docs/11` M6). `× 0.5` 에는 근거가
없다 (`docs/07` §2.4) — 그래서 결과는 항상 두 항과 어느 쪽이 구속했는지를 함께 들고 다닌다.
"""

from __future__ import annotations

import glob
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from msa.l5.inputs import CaseTable

log = logging.getLogger(__name__)

#: 선언값들 — 탐색하지 않는다 (`CLAUDE.md` §1)
COV_LOOKBACK_MONTHS = 60
SHRINK_DELTA = 0.5
SIMILAR_REGIME_DD = 0.50
CASE_DEATH_FACTOR = 0.5  # 근거 없음 — docs/07 §2.4 가 그렇다고 적는다
MONTHS_PER_YEAR = 12

FArray = NDArray[np.float64]


class RiskInputError(ValueError):
    """리스크 입력을 만들 수 없다."""


# ---------------------------------------------------------------- 테마 지수 (캐시)


def _latest_panel_path(cache_dir: Path) -> Path:
    files = sorted(glob.glob(str(cache_dir / "l1_panel_*.parquet")))
    if not files:
        raise RiskInputError(
            f"L1 패널 캐시가 없다: {cache_dir}/l1_panel_*.parquet — 먼저 `msa scan` 을 돌려라"
        )
    # 여러 지문이 있으면 가장 최근 수정본
    files.sort(key=lambda f: Path(f).stat().st_mtime)
    return Path(files[-1])


def load_theme_ew_returns(cache_dir: Path | str) -> pd.DataFrame:
    """L1 패널 캐시에서 테마 EW **일별** 수익률 (date × theme) 을 읽는다."""
    p = _latest_panel_path(Path(cache_dir))
    frame = pd.read_parquet(p, columns=["ret_ew"])
    wide = frame["ret_ew"].unstack("theme").sort_index()
    wide.index = pd.to_datetime(wide.index)
    log.info("risk: 테마 EW 수익률 %s (%d일 × %d테마)", p.name, *wide.shape)
    return wide


def monthly_returns(daily: pd.DataFrame) -> pd.DataFrame:
    """일별 → 월말 복리 월간 수익률. 한 달 전부 NaN 이면 NaN 으로 남긴다 (0 으로 채우지 않는다)."""
    has = daily.notna().resample("ME").sum() > 0
    comp = (1.0 + daily.fillna(0.0)).resample("ME").prod() - 1.0
    return comp.where(has)


def index_level(daily: pd.Series) -> pd.Series:
    """수익률 누적 지수 (시작 1.0). 첫 관측 전은 NaN."""
    lvl: pd.Series = (1.0 + daily.fillna(0.0)).cumprod()
    mask: pd.Series = daily.notna().cummax()
    return lvl.where(mask)


# ---------------------------------------------------------------- 축소 공분산


def shrink_constant_correlation(sample: FArray, delta: float = SHRINK_DELTA) -> FArray:
    """상수상관 타깃으로 축소: `Σ = (1−δ)·S + δ·F`, F_ij = r̄·σ_i·σ_j (i≠j), F_ii = S_ii."""
    if not 0.0 <= delta <= 1.0:
        raise ValueError(f"delta 는 [0,1]: {delta}")
    s = np.asarray(sample, dtype=np.float64)
    n = s.shape[0]
    if n == 0:
        return s
    sd = np.sqrt(np.clip(np.diag(s), 0.0, None))
    if n == 1:
        return s.copy()
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = s / np.outer(sd, sd)
    corr = np.where(np.isfinite(corr), corr, 0.0)
    off = corr[~np.eye(n, dtype=bool)]
    rbar = float(off.mean()) if off.size else 0.0
    target = rbar * np.outer(sd, sd)
    np.fill_diagonal(target, np.diag(s))
    out = (1.0 - delta) * s + delta * target
    return np.asarray((out + out.T) / 2.0, dtype=np.float64)


@dataclass(frozen=True)
class CovarianceResult:
    """`Σ` (연율) 와 그것이 어디서 왔는지."""

    sigma: FArray  # n × n, annualized
    labels: tuple[str, ...]
    source: str  # "stock_returns" | "theme_ew_monthly"
    lookback_months: int
    n_obs: int
    shrink_delta: float
    window: tuple[str, str]
    notes: tuple[str, ...] = ()


def theme_covariance(
    monthly: pd.DataFrame,
    themes: Sequence[str],
    *,
    asof: pd.Timestamp | None = None,
    lookback_months: int = COV_LOOKBACK_MONTHS,
    shrink_delta: float = SHRINK_DELTA,
) -> CovarianceResult:
    """테마 EW 월간 수익률에서 연율 축소 공분산. 룩백 안에 관측이 절반 미만인 테마는 예외 —
    조용히 0 분산으로 들어가는 것보다 낫다."""
    missing = [t for t in themes if t not in monthly.columns]
    if missing:
        raise RiskInputError(f"테마 수익률에 없는 테마: {missing}")
    m = monthly[list(themes)]
    if asof is not None:
        m = m.loc[: pd.Timestamp(asof)]
    m = m.tail(lookback_months)
    if len(m) < 12:
        raise RiskInputError(f"월간 관측 {len(m)}개 — 12개 미만으로는 공분산을 만들지 않는다")
    thin = [t for t in themes if m[t].notna().sum() < len(m) / 2]
    if thin:
        raise RiskInputError(f"룩백 {len(m)}개월 중 관측이 절반 미만인 테마: {thin}")
    sample = np.asarray(m.cov(min_periods=6).to_numpy(), dtype=np.float64)
    if not np.all(np.isfinite(sample)):
        raise RiskInputError("표본 공분산에 NaN — 테마 쌍의 겹치는 관측이 부족하다")
    sigma = shrink_constant_correlation(sample, shrink_delta) * MONTHS_PER_YEAR
    return CovarianceResult(
        sigma=sigma,
        labels=tuple(themes),
        source="theme_ew_monthly",
        lookback_months=lookback_months,
        n_obs=len(m),
        shrink_delta=shrink_delta,
        window=(str(m.index[0].date()), str(m.index[-1].date())),
    )


def stock_covariance_from_returns(
    returns: pd.DataFrame,
    tickers: Sequence[str],
    *,
    asof: pd.Timestamp | None = None,
    lookback_rows: int = 252,
    periods_per_year: int = 252,
    shrink_delta: float = SHRINK_DELTA,
) -> CovarianceResult:
    """종목 수익률(date × ticker) 에서 연율 축소 공분산 — `returns.csv` 경로."""
    missing = [t for t in tickers if t not in returns.columns]
    if missing:
        raise RiskInputError(f"returns 에 없는 티커: {missing}")
    r = returns[list(tickers)]
    if asof is not None:
        r = r.loc[: pd.Timestamp(asof)]
    r = r.tail(lookback_rows)
    if len(r) < 60:
        raise RiskInputError(f"종목 수익률 관측 {len(r)}행 — 60 미만으로는 공분산을 만들지 않는다")
    thin = [t for t in tickers if r[t].notna().sum() < len(r) / 2]
    if thin:
        raise RiskInputError(f"룩백 안 관측이 절반 미만인 티커: {thin}")
    sample = np.asarray(r.cov(min_periods=30).to_numpy(), dtype=np.float64)
    if not np.all(np.isfinite(sample)):
        raise RiskInputError("표본 공분산에 NaN — 종목 쌍의 겹치는 관측이 부족하다")
    sigma = shrink_constant_correlation(sample, shrink_delta) * periods_per_year
    return CovarianceResult(
        sigma=sigma,
        labels=tuple(tickers),
        source="stock_returns",
        lookback_months=lookback_rows,
        n_obs=len(r),
        shrink_delta=shrink_delta,
        window=(str(r.index[0].date()), str(r.index[-1].date())),
        notes=("룩백 단위는 행(일)이다",),
    )


def map_theme_cov_to_stocks(
    theme_cov: CovarianceResult,
    stock_themes: Sequence[str],
    idio_vol_ann: Sequence[float | None],
    labels: Sequence[str],
) -> CovarianceResult:
    """`Σ_stock = B Σ_theme Bᵀ + diag(σ²_idio)`, B = 종목→테마 지시행렬 (β=1)."""
    idx = {t: i for i, t in enumerate(theme_cov.labels)}
    n = len(stock_themes)
    b = np.zeros((n, len(theme_cov.labels)), dtype=np.float64)
    for i, t in enumerate(stock_themes):
        if t not in idx:
            raise RiskInputError(f"테마 공분산에 없는 테마: {t}")
        b[i, idx[t]] = 1.0
    idio = np.array([(v or 0.0) ** 2 for v in idio_vol_ann], dtype=np.float64)
    sigma = b @ theme_cov.sigma @ b.T + np.diag(idio)
    n_idio = int(sum(1 for v in idio_vol_ann if v))
    return CovarianceResult(
        sigma=np.asarray((sigma + sigma.T) / 2.0, dtype=np.float64),
        labels=tuple(labels),
        source=theme_cov.source,
        lookback_months=theme_cov.lookback_months,
        n_obs=theme_cov.n_obs,
        shrink_delta=theme_cov.shrink_delta,
        window=theme_cov.window,
        notes=(
            *theme_cov.notes,
            f"종목은 자기 테마 지수에 β=1 로 사상 · 고유분산 지정 {n_idio}/{n} 종목",
        ),
    )


# ---------------------------------------------------------------- ENB


@dataclass(frozen=True)
class ENBResult:
    enb: float
    p_top3: tuple[float, float, float]
    n_factors: int
    port_var: float

    def as_dict(self) -> dict[str, float | int | list[float]]:
        return {
            "enb": self.enb,
            "p_top3": list(self.p_top3),
            "n_factors": self.n_factors,
            "port_var": self.port_var,
        }


def effective_number_of_bets(sigma: FArray, w: FArray) -> ENBResult:
    """분산 엔트로피 ENB 와 상위 3 고유팩터 리스크 기여. `wᵀΣw = 0` 이면 ENB=0 (포지션 없음)."""
    s = np.asarray(sigma, dtype=np.float64)
    ww = np.asarray(w, dtype=np.float64)
    var = float(ww @ s @ ww)
    if var <= 1e-16:
        return ENBResult(enb=0.0, p_top3=(0.0, 0.0, 0.0), n_factors=0, port_var=0.0)
    lam, vec = np.linalg.eigh(s)
    lam = np.clip(lam, 0.0, None)
    y = vec.T @ ww
    p = lam * y**2 / var
    p = np.clip(p, 0.0, None)
    p = p / p.sum()
    nz = p[p > 1e-12]
    ent = float(-(nz * np.log(nz)).sum())
    top = [*sorted(p.tolist(), reverse=True), 0.0, 0.0, 0.0]
    return ENBResult(
        enb=float(np.exp(ent)),
        p_top3=(float(top[0]), float(top[1]), float(top[2])),
        n_factors=int((lam > 1e-12).sum()),
        port_var=var,
    )


# ---------------------------------------------------------------- 과거 유사 국면 낙폭


@dataclass(frozen=True)
class RegimeEpisode:
    entry_date: str  # −50% 최초 도달일
    trough_date: str
    loss_from_entry: float  # 1 − min/entry  (양수 비율)
    ongoing: bool


@dataclass(frozen=True)
class HistoricalDrawdown:
    theme: str
    threshold: float
    max_loss: float | None  # 에피소드가 없으면 None
    episodes: tuple[RegimeEpisode, ...]
    history: tuple[str, str] | None

    def as_dict(self) -> dict[str, object]:
        return {
            "threshold": self.threshold,
            "max_loss": self.max_loss,
            "n_episodes": len(self.episodes),
            "episodes": [e.__dict__ for e in self.episodes],
            "history": list(self.history) if self.history else None,
        }


def similar_regime_drawdown(
    level: pd.Series, *, theme: str = "", threshold: float = SIMILAR_REGIME_DD
) -> HistoricalDrawdown:
    """테마 지수 수준 시계열에서 "유사 국면" 에피소드를 찾고 진입 후 최대 추가 손실을 잰다.

    에피소드 = 누적고점 대비 `−threshold` 최초 도달 → 고점 회복(낙폭 0) 직전까지.
    """
    s = level.dropna()
    if s.empty:
        return HistoricalDrawdown(theme, threshold, None, (), None)
    px = s.to_numpy(dtype=np.float64)
    dates = s.index
    peak = np.maximum.accumulate(px)
    dd = px / peak - 1.0
    episodes: list[RegimeEpisode] = []
    i = 0
    n = len(px)
    while i < n:
        if dd[i] <= -threshold:
            entry = px[i]
            j = i
            trough = entry
            trough_j = i
            while j < n and dd[j] < 0.0:
                if px[j] < trough:
                    trough = px[j]
                    trough_j = j
                j += 1
            ongoing = j >= n
            episodes.append(
                RegimeEpisode(
                    entry_date=str(pd.Timestamp(dates[i]).date()),
                    trough_date=str(pd.Timestamp(dates[trough_j]).date()),
                    loss_from_entry=float(1.0 - trough / entry),
                    ongoing=ongoing,
                )
            )
            i = j
        else:
            i += 1
    mx = max((e.loss_from_entry for e in episodes), default=None)
    return HistoricalDrawdown(
        theme=theme,
        threshold=threshold,
        max_loss=mx,
        episodes=tuple(episodes),
        history=(str(pd.Timestamp(dates[0]).date()), str(pd.Timestamp(dates[-1]).date())),
    )


# ---------------------------------------------------------------- 시나리오 손실 L_i


@dataclass(frozen=True)
class ScenarioLoss:
    """테마 하나의 `L_i` 와 그 두 항. 계획서는 `value` 하나만 찍지 않는다 (`docs/07` §2.4)."""

    theme: str
    hist_term: float | None  # 과거 유사 국면 최대 낙폭
    case_raw: float | None  # 사망 사례 낙폭 (× 0.5 전)
    case_factor: float
    case_term: float | None  # case_raw × factor
    case_id: str | None
    value: float | None  # max(hist, case_term) — 둘 다 있을 때만
    binding: str | None  # "hist" | "case" | None
    reasons: tuple[str, ...] = field(default_factory=tuple)  # 못 만든 이유 · 버린 케이스 사유

    @property
    def computable(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "theme": self.theme,
            "hist_term": self.hist_term,
            "case_raw": self.case_raw,
            "case_factor": self.case_factor,
            "case_term": self.case_term,
            "case_id": self.case_id,
            "value": self.value,
            "binding": self.binding,
            "reasons": list(self.reasons),
        }


def scenario_loss(
    theme: str,
    *,
    cluster: str | None,
    hist: HistoricalDrawdown | None,
    cases: CaseTable,
    case_factor: float = CASE_DEATH_FACTOR,
) -> ScenarioLoss:
    """`L_i = max(과거 유사 국면 최대 낙폭, 사망 사례 낙폭 × 0.5)`. 한 항이라도 없으면 None."""
    reasons: list[str] = []
    hist_term: float | None = None
    if hist is None or hist.history is None:
        reasons.append("과거 유사 국면: 테마 지수 이력 없음")
    elif hist.max_loss is None:
        reasons.append(
            f"과거 유사 국면: 이력 {hist.history[0]}~{hist.history[1]} 에 "
            f"−{hist.threshold:.0%} 에피소드 없음"
        )
    else:
        hist_term = hist.max_loss

    case_raw: float | None = None
    case_id: str | None = None
    if not cases.exists:
        reasons.append(
            "케이스 스터디 표 없음 (state/cases/cases.yaml) — 사망 사례 낙폭을 만들 수 없다"
        )
    else:
        matched = cases.for_theme(theme, cluster)
        usable = [c for c in matched if c.usable_for_loss]
        for c in matched:
            r = c.unusable_reason()
            if r:
                reasons.append(f"케이스 제외 — {r}")
        if not matched:
            reasons.append(f"케이스 스터디: 테마 {theme} (클러스터 {cluster}) 에 해당하는 행 없음")
        elif not usable:
            reasons.append(
                "케이스 스터디: 해당 행은 있으나 L_i 에 쓸 수 있는 사망·검증·출처 행이 없음"
            )
        else:
            best = max(usable, key=lambda c: c.drawdown_peak_to_trough or 0.0)
            case_raw = best.drawdown_peak_to_trough
            case_id = best.id
    case_term = None if case_raw is None else case_raw * case_factor

    value: float | None = None
    binding: str | None = None
    if hist_term is not None and case_term is not None:
        if hist_term >= case_term:
            value, binding = hist_term, "hist"
        else:
            value, binding = case_term, "case"
    return ScenarioLoss(
        theme=theme,
        hist_term=hist_term,
        case_raw=case_raw,
        case_factor=case_factor,
        case_term=case_term,
        case_id=case_id,
        value=value,
        binding=binding,
        reasons=tuple(reasons),
    )


def scenario_losses_for_themes(
    themes: Sequence[str],
    *,
    clusters: Mapping[str, str | None],
    daily_ew: pd.DataFrame | None,
    cases: CaseTable,
    asof: pd.Timestamp | None = None,
) -> dict[str, ScenarioLoss]:
    """테마 목록 전부에 대해 `L_i` 를 만든다. 지수 이력이 없는 테마도 **항목은 남긴다** (사유)."""
    out: dict[str, ScenarioLoss] = {}
    for t in themes:
        hist: HistoricalDrawdown | None = None
        if daily_ew is not None and t in daily_ew.columns:
            ser = daily_ew[t]
            if asof is not None:
                ser = ser.loc[: pd.Timestamp(asof)]
            hist = similar_regime_drawdown(index_level(ser), theme=t)
        out[t] = scenario_loss(t, cluster=clusters.get(t), hist=hist, cases=cases)
    return out
