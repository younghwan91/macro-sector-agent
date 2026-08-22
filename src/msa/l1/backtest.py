"""L1 백테스트 — 관문 0 (`docs/10-validation.md` §2, `docs/11-roadmap.md` M3.5).

재는 것은 **스코어의 예측력**이지 전략의 수익률이 아니다 (`CLAUDE.md` §7). 산출물은
rank-IC · 분위 스프레드 · 신뢰구간 · 시도 수를 명시한 DSR · PBO · 브레드스 선행 개월 수이며,
CAGR·Sharpe 같은 전략 성과는 만들지 않는다.

**이 모듈은 튜닝 루프가 아니다.** 결과가 어떻게 나오든 가중치·방향·임계를 바꾸지 않는다
(`CLAUDE.md` §1, `docs/10` §2.3·§2.4). 아래 상수는 전부 **결과를 보기 전에 선언**한 값이고
그 근거를 옆에 적었다. 바꾸려면 근거를 문서와 커밋에 남긴다.

## 설계 (결과를 보기 전에 고정)

- **테마 지수** — EW (`panel.index_level("ew")`), 월말 종가. 스코어보드가 쓰는 지수와 동일.
  시총가중은 대형주 한둘이 지배한다.
- **초과수익 기준** — SPY 총수익 (`panel.spy.close`). 시장 공통 요인을 빼야 횡단면 순서
  정보만 남는다.
- **호라이즌** — 3·6·12M (`HORIZONS`). `docs/10` §2.1. 사이클 논지의 horizon 6~18개월
  (`docs/09` §1)을 덮는다.
- **관문 호라이즌** — 12M (`GATE_HORIZON`). 위 horizon 의 중앙. 3·6M 은 보조로 보고한다.
- **주 검정 창** — 2011-01 이후 (`PRIMARY_START`). `docs/10` §2.2 walk-forward — 1998~2010 은
  지표 이력 확보 구간이지 가중치 추정 구간이 아니다. **보조 창** = 전 구간. 둘 다 보고한다.
- **횡단면 최소 테마 수** — 20 (`MIN_THEMES_XS`). Spearman 의 표준오차 ≈ 1/√(n−1) 이 0.23 을
  넘는 달은 한 달치 IC 로 뜻이 없다.
- **클래스 내 최소 테마 수** — 5 (`MIN_THEMES_CLASS`). 그 이하면 순위상관이 정의는 되나 ±1
  사이를 튄다. n 을 함께 보고한다.
- **상위 K** — 8 (`TOP_K`). 실제 운영 컷오프 (`docs/05` §1). 하위도 같은 8.
- **소표본 처리** — 양끝 모두 제외. `Scoreboard.top_k` 가 소표본을 상위에서 뒤로 보내는 것과
  대칭. 과거 `n_live` 가 없으므로 그 월말 `n_listed < min_constituents` 로 판정한다.
- **부트스트랩** — 12개월 이동블록 · 2000회 · 시드 0 (`docs/10` §2.2). 월별 IC 의 자기상관
  (중첩 호라이즌)을 살린 채 재표집한다.
- **PBO** — S=16 블록, 월별 스프레드, 열 = 스코어 변형 7 (`docs/10` §2.2
  "`portfolio-research` 의 선례"). 전수 조합 C(16,8)=12,870.
- **DSR 시도 수** — `count_trials()` 의 규칙. 이 리포트가 들여다본 칸을 전부 센다.
- **통과 판정** — 주 창 · 12M · 복합 IC 의 95% CI 가 0 을 넘어 양수 (`docs/10` §2.3 "전체 IC 가
  0 과 구분되는가"). 블록·클래스 분해는 진단이지 관문이 아니다.

## look-ahead 규약

월말 `t` 의 스코어는 `t` 까지의 데이터로 만들어졌다 (`blocks.py`). 전진 수익률은
`P[t+h]/P[t] − 1` 로 **`t` 이후의 가격만** 쓴다. 부분 월(스토어 최종일이 월말 전)은 전진
수익률의 끝점으로 쓰지 않는다 —
3M 이라 적어 놓고 2.5M 을 재는 것은 조용한 절단이다 (`CLAUDE.md` §2). 제외한 건수는 전부 센다.

## 산출물 (`state/backtests/l1/<asof>/`)

| 파일 | 내용 |
|---|---|
| `ic_timeseries.csv` | (date, window 무관) × variant × horizon × partition → ic, n |
| `ic_summary.csv` | window × horizon × variant × partition → 평균 IC · CI · AR1 · N_eff … |
| `ic_indicator.csv` | 지표 단독 IC 요약 (전체 파티션) |
| `spread.csv` / `spread_summary.csv` | 상위 8 − 하위 8 월별 스프레드와 요약 |
| `breadth_lead.csv` / `breadth_lead_summary.csv` | 테마-에피소드별 선행 개월 수와 분포 |
| `overfitting.json` | 시도 수 계산 · DSR · PBO 입출력 |
| `exclusions.json` | 제외 건수 전부 |
| `report.txt` | 사람이 읽는 요약 |

## 구현 노트 (값에 영향 없음)

2026-08-23 리팩터: 월별 rank-IC 는 (월말 × 테마) 행렬에서 유효 테마 수가 같은 행끼리 묶어 한 번에
계산한다 — 행마다 `_spearman_np` 를 부른 것과 **비트 단위로 같다** (밀집 배열의 합산 순서가 같다).
부트스트랩 재표집 인덱스는 `(n, L, n_boot, seed)` 별로 한 번만 뽑는다 (같은 난수열). 실제 캐시와
합성 데이터로 구 구현과 대조했다 (`tests/test_l1_backtest.py` 의 `_ref_*`).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from msa.dates import to_month_end
from msa.fmt import num as _fmt
from msa.io import dump_json
from msa.l1.blocks import Indicators
from msa.l1.panel import ThemePanel
from msa.l1.scoreboard import BLOCKS, ORIENTATION, SCORED, scoreboard_history
from msa.themes import CYCLE_CLASSES, ThemeSet
from msa.vendor.overfitting import (
    PBOResult,
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 선언 상수 (머리말 표 참조)

HORIZONS: tuple[int, ...] = (3, 6, 12)
PBO_HORIZON = 1
GATE_HORIZON = 12
PRIMARY_START = pd.Timestamp("2011-01-31")
MIN_THEMES_XS = 20
MIN_THEMES_CLASS = 5
TOP_K = 8
BOOT_BLOCK = 12
BOOT_N = 2000
BOOT_SEED = 0
PBO_BLOCKS = 16
PBO_MAX_SPLITS = 12870  # C(16, 8) — 전수
DSR_THRESHOLD = 0.95
PBO_THRESHOLD = 0.5
BREADTH_LAG_SEARCH = (
    12  # 지수 전환 뒤 브레드스 전환을 찾는 개월 수 (blocks.breadth_lead 의 상한과 같다)
)

#: 스코어 변형 — 복합(선언 가중치) + 블록 단독 6. 이것이 DSR 시도 수와 PBO "전략" 의 단위다.
VARIANTS: tuple[str, ...] = ("score", *BLOCKS)
WINDOWS: tuple[str, ...] = ("primary", "full")
PARTITION_ALL = "all"
SCORED_INDICATORS: tuple[str, ...] = tuple(i for b in BLOCKS for i in SCORED[b])


def count_trials(n_indicators: int = len(SCORED_INDICATORS)) -> dict[str, int]:
    """DSR 시도 수 — `docs/10` §2.2 의 규칙을 숫자로.

    선언된 복합 스코어 하나만 봤다면 1 이다. 그러나 이 리포트는 블록 단독(+6)·호라이즌(×3)·
    `cycle_class` 파티션(+8)·두 창(×2)·지표 단독 IC 를 **전부 들여다본다.** 들여다본 칸은 시도다 —
    "세지 않은 시도는 없는 시도가 아니다". 같은 칸을 IC 와 스프레드 두 눈금으로 보면 둘 다 센다.

        total = windows × [ variants × horizons × (2 + classes)   # IC·스프레드(전체)+IC(클래스)
                          + variants × 1                        # 1M 월별 스프레드 (DSR·PBO)
                          + indicators × horizons ]             # 지표 단독 IC
    """
    variants = len(VARIANTS)
    horizons = len(HORIZONS)
    classes = len(CYCLE_CLASSES)
    windows = len(WINDOWS)
    per_window = variants * horizons * (2 + classes) + variants * 1 + n_indicators * horizons
    return {
        "variants": variants,
        "horizons": horizons,
        "classes": classes,
        "windows": windows,
        "indicators": n_indicators,
        "metrics_on_all_partition": 2,
        "monthly_spread_horizons": 1,
        "per_window": per_window,
        "declared_only": 1,
        "total": windows * per_window,
    }


# ---------------------------------------------------------------- 전진 수익률


@dataclass(frozen=True)
class Forward:
    """월말 전진 초과수익. `excess[h]` 는 date × theme,
    값은 `P[t+h]/P[t] − 1 − (S[t+h]/S[t] − 1)`."""

    excess: dict[int, pd.DataFrame]
    last_complete: pd.Timestamp
    exclusions: dict[str, Any]


def forward_excess(panel: ThemePanel, horizons: tuple[int, ...]) -> Forward:
    """월말 EW 지수의 h 개월 전진 수익률과 SPY 대비 초과수익.

    - 월말 라벨은 `Indicators.bucket_for` 와 같은 `resample("ME").last()` 라벨이다.
    - 끝점 `t+h` 가 **완결된 월**이어야 한다 (라벨 ≤ 패널 최종일). 아니면 NaN 으로 두고 센다.
    - 구간 `(t, t+h]` 의 모든 달에 그 테마의 수익률 관측(`n_ret ≥ 1`)이 있어야 한다. 구성원이
      전부 없는 달은 지수가 정체해 전진 수익률이 0 으로 보이므로 NaN 으로 두고 센다.
    """
    P = panel.index_level("ew")
    Pm = to_month_end(P)
    me = pd.DatetimeIndex(Pm.index)
    last_day = pd.Timestamp(P.index.max())
    complete = me[me <= last_day]
    if len(complete) == 0:
        raise ValueError("완결된 월이 하나도 없다")
    last_complete = pd.Timestamp(complete[-1])
    spy = to_month_end(panel.spy["close"].reindex(P.index).ffill()).reindex(me)
    active = panel.wide("n_ret").resample("ME").max().reindex(me).fillna(0) >= 1

    excess: dict[int, pd.DataFrame] = {}
    excl: dict[str, Any] = {"last_complete_month": str(last_complete.date())}
    for h in horizons:
        fwd = Pm.shift(-h) / Pm - 1.0
        fs = spy.shift(-h) / spy - 1.0
        end_ok = pd.Series(me + pd.offsets.MonthEnd(h) <= last_complete, index=me)
        # (t, t+h] 전부 활성: active 를 h 개월 앞으로 당겨 rolling min
        act_fwd = active.astype(float)[::-1].rolling(h, min_periods=h).min()[::-1].shift(-1)
        act_ok = act_fwd.fillna(0.0) >= 1.0
        raw_ok = fwd.notna()
        n_raw = int(raw_ok.to_numpy().sum())
        n_end_bad = int((raw_ok & ~end_ok.to_numpy()[:, None]).to_numpy().sum())
        keep = raw_ok & end_ok.to_numpy()[:, None]
        n_act_bad = int((keep & ~act_ok).to_numpy().sum())
        keep = keep & act_ok
        fwd = fwd.where(keep)
        fs = fs.where(end_ok)
        excess[h] = fwd.sub(fs, axis=0)
        excl[f"h{h}"] = {
            "theme_months_raw": n_raw,
            "dropped_incomplete_endpoint": n_end_bad,
            "dropped_inactive_window": n_act_bad,
            "kept": int(keep.to_numpy().sum()),
            # 어느 테마도 전진 수익률이 없는 월말 (표본 끝 h 개월 + 미완결 월) — IC·스프레드 행 없음
            "months_without_any_forward": int((~keep).all(axis=1).sum()),
        }
    return Forward(excess=excess, last_complete=last_complete, exclusions=excl)


def small_sample_history(panel: ThemePanel, themes: ThemeSet) -> pd.DataFrame:
    """월말 `n_listed < min_constituents` (date × theme, bool). 과거 `n_live` 의 대용이다."""
    nl = to_month_end(panel.wide("n_listed"))
    by_id = themes.by_id()
    minc = pd.Series({t: by_id[t].min_constituents for t in nl.columns if t in by_id})
    nl = nl[minc.index]
    return nl.lt(minc, axis=1) | nl.isna()


# ---------------------------------------------------------------- 횡단면 통계


def _spearman_np(x: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    """짝으로 값이 있는 항목만 써서 Spearman ρ 와 n. n < 3 이면 (NaN, n). 동률은 평균 순위."""
    m = ~(np.isnan(x) | np.isnan(y))
    n = int(m.sum())
    if n < 3:
        return float("nan"), n
    a = rankdata(x[m], method="average")
    b = rankdata(y[m], method="average")
    a = a - a.mean()
    b = b - b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if den == 0.0:
        return float("nan"), n
    return float((a * b).sum() / den), n


def spearman(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    """`_spearman_np` 의 Series 판 — 인덱스 이름으로 짝을 맞춘다."""
    both = pd.concat([x, y], axis=1)
    return _spearman_np(
        both.iloc[:, 0].to_numpy(dtype=float), both.iloc[:, 1].to_numpy(dtype=float)
    )


def _spearman_rows(X: np.ndarray, Y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """행별 Spearman ρ 와 n — 행마다 `_spearman_np` 를 부른 것과 **비트 단위로 같은** 값.

    유효(둘 다 값 있음) 항목을 열 순서대로 앞에 모은 뒤, 유효 개수 n 이 같은 행끼리 (r × n) 밀집
    배열로 한 번에 계산한다. 밀집 행의 `mean`·`sum` 은 1차원 배열과 같은 합산 순서를 쓴다.
    """
    m = ~(np.isnan(X) | np.isnan(Y))
    n = m.sum(axis=1)
    ic = np.full(X.shape[0], np.nan)
    if X.shape[0] == 0 or X.shape[1] == 0:
        return ic, n
    order = np.argsort(~m, axis=1, kind="stable")
    Xs = np.take_along_axis(X, order, axis=1)
    Ys = np.take_along_axis(Y, order, axis=1)
    for k in np.unique(n):
        if k < 3:
            continue
        rows = np.flatnonzero(n == k)
        a = rankdata(np.ascontiguousarray(Xs[rows, :k]), method="average", axis=1)
        b = rankdata(np.ascontiguousarray(Ys[rows, :k]), method="average", axis=1)
        a = a - a.mean(axis=1, keepdims=True)
        b = b - b.mean(axis=1, keepdims=True)
        den = np.sqrt((a * a).sum(axis=1) * (b * b).sum(axis=1))
        with np.errstate(invalid="ignore", divide="ignore"):
            val = (a * b).sum(axis=1) / den
        val[den == 0.0] = np.nan
        ic[rows] = val
    return ic, n


def _score_matrices(
    scores: pd.DataFrame, variants: tuple[str, ...]
) -> tuple[dict[str, np.ndarray], list[str], pd.DatetimeIndex]:
    """`scoreboard_history` 긴 표 → 변형별 (월말 × 테마) 행렬, 테마 목록, 월말 인덱스."""
    wide = {v: scores[v].unstack("theme").sort_index() for v in variants}
    themes = list(wide[variants[0]].columns)
    dates = pd.DatetimeIndex(wide[variants[0]].index)
    X = {v: wide[v].reindex(index=dates, columns=themes).to_numpy(dtype=float) for v in variants}
    return X, themes, dates


def rank_ic_series(
    scores: pd.DataFrame,
    fwd: Forward,
    classes: pd.Series,
    *,
    variants: tuple[str, ...] = VARIANTS,
    horizons: Sequence[int] | None = None,
    min_n: int = MIN_THEMES_XS,
    min_n_class: int = MIN_THEMES_CLASS,
) -> pd.DataFrame:
    """월별 횡단면 rank-IC (긴 표). 열: date, variant, horizon, partition, ic, n.

    `scores` 는 `scoreboard_history` 의 긴 표(index (date, theme)). `partition` 은 `all` 또는
    `cycle_class`. n 이 문턱 미만인 (date, partition) 은 행을 만들되 ic=NaN 으로 남긴다 — 빠진 달을
    세기 위해서다. `horizons` 를 주면 `fwd.excess` 중 그 호라이즌만 쓴다.
    """
    X, themes, dates = _score_matrices(scores, variants)
    col_of = {t: j for j, t in enumerate(themes)}
    cls_idx = {
        c: np.array([col_of[t] for t in classes.index[classes == c] if t in col_of], dtype=int)
        for c in CYCLE_CLASSES
    }
    chunks: list[pd.DataFrame] = []
    for h in horizons if horizons is not None else tuple(fwd.excess):
        Y = fwd.excess[h].reindex(index=dates, columns=themes).to_numpy(dtype=float)
        live = ~np.isnan(Y).all(axis=1)  # 어느 테마도 전진 수익률이 없는 달은 행을 만들지 않는다
        d_live = dates[live]
        Yl = Y[live]
        for v in variants:
            Xl = X[v][live]
            parts: list[tuple[str, np.ndarray, np.ndarray, int]] = [(PARTITION_ALL, Xl, Yl, min_n)]
            for c, idx in cls_idx.items():
                parts.append((c, Xl[:, idx], Yl[:, idx], min_n_class))
            for p, xs, ys, thr in parts:
                ic, n = _spearman_rows(xs, ys)
                chunks.append(
                    pd.DataFrame(
                        {
                            "date": d_live,
                            "variant": v,
                            "horizon": h,
                            "partition": p,
                            "ic": np.where(n >= thr, ic, np.nan),
                            "n": n.astype(int),
                        }
                    )
                )
    out = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    if out.empty:
        raise ValueError("IC 를 계산할 (월말, 호라이즌) 쌍이 하나도 없다")
    return out.sort_values(["horizon", "date"], kind="stable").reset_index(drop=True)


def indicator_ic_series(
    ind: Indicators,
    fwd: Forward,
    *,
    indicators: tuple[str, ...] = SCORED_INDICATORS,
    horizons: Sequence[int] | None = None,
    min_n: int = MIN_THEMES_XS,
) -> pd.DataFrame:
    """지표 단독 rank-IC (방향 `ORIENTATION` 반영, 전체 파티션만).

    열: date, indicator, horizon, ic, n."""
    chunks: list[pd.DataFrame] = []
    hs = tuple(horizons) if horizons is not None else tuple(fwd.excess)
    for i in indicators:
        if i not in ind.monthly.columns:
            continue
        w = ind.wide(i).astype(float) * ORIENTATION[i]
        for h in hs:
            ex = fwd.excess[h]
            dates = w.index.intersection(ex.index)
            themes = w.columns.intersection(ex.columns)
            X = w.reindex(index=dates, columns=themes).to_numpy(dtype=float)
            Y = ex.reindex(index=dates, columns=themes).to_numpy(dtype=float)
            ic, n = _spearman_rows(X, Y)
            chunks.append(
                pd.DataFrame(
                    {
                        "date": dates,
                        "indicator": i,
                        "horizon": h,
                        "ic": np.where(n >= min_n, ic, np.nan),
                        "n": n.astype(int),
                    }
                )
            )
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def spread_series(
    scores: pd.DataFrame,
    fwd: Forward,
    small: pd.DataFrame,
    *,
    variants: tuple[str, ...] = VARIANTS,
    k: int = TOP_K,
    min_n: int = MIN_THEMES_XS,
) -> pd.DataFrame:
    """상위 K − 하위 K 동일가중 전진 초과수익 스프레드 (긴 표).

    열: date, variant, horizon, spread, ret_top, ret_bot, n_universe, n_small_excluded.
    소표본 버킷은 양끝에서 제외한다 (머리말). 우주(스코어·전진수익 모두 있고 소표본 아님)가
    `min_n` 미만이면 spread=NaN 으로 남기고 센다.
    """
    rows: list[dict[str, Any]] = []
    X, themes, dates = _score_matrices(scores, variants)
    # 소표본: 표시가 없으면(테마·날짜가 표에 없으면) True 로 본다 — 모르는 것은 제외한다
    S = small.reindex(index=dates, columns=themes).fillna(True).to_numpy(dtype=bool)
    for h, ex in fwd.excess.items():
        Y = ex.reindex(index=dates, columns=themes).to_numpy(dtype=float)
        for i, d in enumerate(dates):
            y = Y[i]
            if np.isnan(y).all():
                continue
            for v in variants:
                x = X[v][i]
                both = ~(np.isnan(x) | np.isnan(y))
                n_small = int((both & S[i]).sum())
                use = both & ~S[i]
                n_u = int(use.sum())
                if n_u >= min_n:
                    order = np.argsort(-x[use], kind="stable")
                    yy = y[use][order]
                    top = float(yy[:k].mean())
                    bot = float(yy[-k:].mean())
                    spread = top - bot
                else:
                    top = bot = spread = float("nan")
                rows.append(
                    {
                        "date": d,
                        "variant": v,
                        "horizon": h,
                        "spread": spread,
                        "ret_top": top,
                        "ret_bot": bot,
                        "n_universe": n_u,
                        "n_small_excluded": n_small,
                    }
                )
    out = pd.DataFrame(rows)
    return out.sort_values(["horizon", "date"], kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------- 유효 표본·신뢰구간


def ar1(x: pd.Series) -> float:
    s = x.dropna()
    if len(s) < 3:
        return float("nan")
    a = s.to_numpy(dtype=float)
    return float(np.corrcoef(a[:-1], a[1:])[0, 1]) if a.std() > 0 else float("nan")


def effective_n(n: int, rho: float) -> float:
    """AR(1) 자기상관 ρ 를 가진 길이 n 시계열의 유효 관측 수 ≈ n(1−ρ)/(1+ρ). 최소 1."""
    if n <= 0 or math.isnan(rho):
        return float("nan")
    r = max(min(rho, 0.999), -0.999)
    return max(1.0, n * (1.0 - r) / (1.0 + r))


@cache
def _boot_index(n: int, block: int, n_boot: int, seed: int) -> np.ndarray:
    """이동블록 재표집 인덱스 (n_boot × n). 같은 (n, L, n_boot, seed) 면 같은 난수열이다."""
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[:, :n]
    idx.setflags(write=False)
    return idx


def block_bootstrap_mean(
    x: pd.Series,
    *,
    block: int = BOOT_BLOCK,
    n_boot: int = BOOT_N,
    seed: int = BOOT_SEED,
    alpha: float = 0.05,
) -> dict[str, float]:
    """이동블록 부트스트랩으로 평균의 신뢰구간. 반환: mean, ci_lo, ci_hi, se_boot, n, n_boot.

    길이 L 블록의 시작점을 균등 추출해 이어 붙이고 원 길이로 자른다. n < 2L 이면 블록을 n//2
    로 줄이고 그 사실을 `block_used` 로 적는다. NaN 은 제거하고 센다 (시계열 순서는 유지).
    """
    s = x.dropna().to_numpy(dtype=float)
    n = len(s)
    out: dict[str, float] = {
        "mean": float(s.mean()) if n else float("nan"),
        "n": float(n),
        "n_boot": float(n_boot),
    }
    if n < 4:
        out.update(ci_lo=float("nan"), ci_hi=float("nan"), se_boot=float("nan"), block_used=0.0)
        return out
    L = block if n >= 2 * block else max(1, n // 2)
    means = s[_boot_index(n, L, n_boot, seed)].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    out.update(ci_lo=float(lo), ci_hi=float(hi), se_boot=float(means.std(ddof=1)), block_used=L)
    return out


def avg_cross_corr(
    panel: ThemePanel, start: pd.Timestamp | None, *, min_months: int = 60
) -> dict[str, float]:
    """테마 간 월별 수익률의 평균 쌍별 상관과 유효 테마 수 n/(1+(n−1)ρ̄).

    원수익률(`raw`)과 SPY 초과수익(`excess`) 둘 다 낸다 — IC 가 쓰는 것은 후자다. 원수익률의
    ρ̄ 는 시장 공통 요인이 지배해 유효 테마 수가 1/ρ̄ 근방으로 무너진다; 초과수익의 ρ̄ 가 횡단면
    순위 정보의 유효 폭에 가깝다.
    """
    P = to_month_end(panel.index_level("ew"))
    r = P.pct_change(fill_method=None)
    spy = to_month_end(panel.spy["close"]).reindex(r.index).pct_change(fill_method=None)
    out: dict[str, float] = {}
    for name, rr in (("raw", r), ("excess", r.sub(spy, axis=0))):
        x = rr.loc[start:] if start is not None else rr
        x = x.loc[:, x.notna().sum() >= min_months]
        n = x.shape[1]
        if n < 2:
            out.update({f"n_themes_{name}": float(n), f"avg_corr_{name}": float("nan")})
            out[f"n_eff_themes_{name}"] = float("nan")
            continue
        c = x.corr(min_periods=min_months).to_numpy()
        vals = c[np.triu_indices(n, 1)]
        vals = vals[~np.isnan(vals)]
        rho = float(vals.mean()) if len(vals) else float("nan")
        neff = n / (1.0 + (n - 1) * rho) if not math.isnan(rho) else float("nan")
        out[f"n_themes_{name}"] = float(n)
        out[f"avg_corr_{name}"] = rho
        out[f"n_eff_themes_{name}"] = float(neff)
    return out


def _summarize_series(x: pd.Series, *, label: dict[str, Any]) -> dict[str, Any]:
    s = x.dropna()
    bs = block_bootstrap_mean(s)
    rho = ar1(s)
    n = len(s)
    sd = float(s.std(ddof=1)) if n > 1 else float("nan")
    mean = float(s.mean()) if n else float("nan")
    neff = effective_n(n, rho)
    rec: dict[str, Any] = dict(label)
    rec.update(
        n_months=n,
        mean=mean,
        median=float(s.median()) if n else float("nan"),
        sd=sd,
        t_naive=mean / sd * math.sqrt(n) if n > 1 and sd > 0 else float("nan"),
        ar1=rho,
        n_eff=neff,
        t_eff=mean / sd * math.sqrt(neff)
        if n > 1 and sd > 0 and not math.isnan(neff)
        else float("nan"),
        ci_lo=bs["ci_lo"],
        ci_hi=bs["ci_hi"],
        se_boot=bs["se_boot"],
        share_pos=float((s > 0).mean()) if n else float("nan"),
        first=str(s.index.min().date()) if n else None,
        last=str(s.index.max().date()) if n else None,
    )
    return rec


def _window_slice(df: pd.DataFrame, window: str) -> pd.DataFrame:
    if window == "primary":
        return df[df["date"] >= PRIMARY_START]
    return df


def _summarize(
    df: pd.DataFrame,
    keys: Sequence[str],
    value: str,
    extra: Callable[[pd.DataFrame, dict[str, Any]], None] | None = None,
) -> pd.DataFrame:
    """window × `keys` 별 시계열 요약 (`_summarize_series`) + `n_months_dropped` (+ `extra`).

    `keys` 에는 `horizon` 이 있어야 하며 int 로 실린다. `extra(g, rec)` 는 그룹 프레임을 보고
    요약에 열을 더한다 (IC: 평균 테마 수, 스프레드: 평균 우주 크기).
    """
    rows = []
    if df.empty:
        return pd.DataFrame()
    for w in WINDOWS:
        sub = _window_slice(df, w)
        for key, g in sub.groupby(list(keys), sort=False):
            s = g.set_index("date")[value].sort_index()
            kv = dict(zip(keys, key, strict=True))
            # 열 순서 규약: window · horizon · 나머지 키 (CSV 헤더가 이 순서다)
            label: dict[str, Any] = {"window": w, "horizon": int(cast(int, kv.pop("horizon")))}
            label.update(kv)
            rec = _summarize_series(s, label=label)
            rec["n_months_dropped"] = int(s.isna().sum())
            if extra is not None:
                extra(g, rec)
            rows.append(rec)
    return pd.DataFrame(rows)


def _ic_extra(g: pd.DataFrame, rec: dict[str, Any]) -> None:
    rec["mean_n_themes"] = (
        float(g.loc[g["ic"].notna(), "n"].mean()) if rec["n_months"] else float("nan")
    )


def _spread_extra(g: pd.DataFrame, rec: dict[str, Any]) -> None:
    rec["mean_n_universe"] = float(g["n_universe"].mean())
    rec["mean_n_small_excluded"] = float(g["n_small_excluded"].mean())


def summarize_ic(ic: pd.DataFrame) -> pd.DataFrame:
    """window × horizon × variant × partition 요약. `n_months_dropped` 는 문턱 미만으로 빠진 달."""
    return _summarize(ic, ("variant", "horizon", "partition"), "ic", _ic_extra)


def summarize_indicator_ic(iic: pd.DataFrame) -> pd.DataFrame:
    return _summarize(iic, ("indicator", "horizon"), "ic")


def summarize_spread(sp: pd.DataFrame) -> pd.DataFrame:
    return _summarize(sp, ("variant", "horizon"), "spread", _spread_extra)


# ---------------------------------------------------------------- 브레드스 선행성


def breadth_lead_episodes(
    ind: Indicators, classes: pd.Series, *, lag_search: int = BREADTH_LAG_SEARCH
) -> pd.DataFrame:
    """지수 SMA200 상향 전환 에피소드마다 브레드스(`breadth_200 ≥ 0.5`)가 몇 개월 먼저 돌았는가.

    에피소드 = `above_200` 이 0 → 1 로 바뀐 월말 (둘 다 관측). 그 시점에 브레드스 런이 활성이면
    `lead = 전환월 − 런 시작월` (≥ 0, **상한 없음** — `blocks.breadth_lead` 는 12 로 자른다),
    활성이 아니면 이후 `lag_search` 개월 안의 첫 브레드스 전환까지를 음수로, 그것도 없으면
    `lead = NaN`, `kind = none`.
    반환 열: theme, cycle_class, date, lead, kind ∈ {lead, same, lag, none}.
    """
    ab = ind.wide("above_200")
    br = ind.wide("breadth_200")
    rows: list[dict[str, Any]] = []
    for t in ab.columns:
        a = ab[t]
        b = br[t]
        up = (a == 1.0) & (a.shift(1) == 0.0)
        bs = (b >= 0.5) & b.notna()
        run_start = pd.Series(
            np.where(bs & ~bs.shift(1, fill_value=False), np.arange(len(bs)), np.nan),
            index=bs.index,
        ).ffill()
        for i in np.flatnonzero(up.to_numpy()).tolist():
            lead = float("nan")
            kind = "none"
            if pd.isna(b.iloc[i]):
                pass
            elif bool(bs.iloc[i]):
                lead = float(i - run_start.iloc[i])
                kind = "same" if lead == 0 else "lead"
            else:
                hit = np.flatnonzero(bs.iloc[i + 1 : i + 1 + lag_search].to_numpy())
                if len(hit):
                    lead = -float(hit[0] + 1)
                    kind = "lag"
            rows.append(
                {
                    "theme": t,
                    "cycle_class": classes.get(t),
                    "date": a.index[i],
                    "lead": lead,
                    "kind": kind,
                }
            )
    return pd.DataFrame(rows, columns=["theme", "cycle_class", "date", "lead", "kind"])


def breadth_cross_precision(ind: Indicators, *, search: int = BREADTH_LAG_SEARCH) -> dict[str, Any]:
    """반대 방향 — 브레드스 상향 전환 뒤 `search` 개월 안에 지수가 돌았는가 (또는 이미 위였는가)."""
    ab = ind.wide("above_200")
    br = ind.wide("breadth_200")
    n = followed = already = 0
    for t in br.columns:
        b = br[t]
        a = ab[t]
        bs = (b >= 0.5) & b.notna()
        cross = bs & ~bs.shift(1, fill_value=False) & b.shift(1).notna()
        for i in np.flatnonzero(cross.to_numpy()):
            if pd.isna(a.iloc[i]):
                continue
            n += 1
            if a.iloc[i] == 1.0:
                already += 1
                continue
            fut = a.iloc[i + 1 : i + 1 + search]
            if (fut == 1.0).any():
                followed += 1
    return {
        "n_breadth_crosses": n,
        "index_already_above": already,
        "index_follows_within_search": followed,
        "neither": n - already - followed,
        "share_followed_given_not_above": followed / (n - already)
        if n - already > 0
        else float("nan"),
        "search_months": search,
    }


def summarize_breadth_lead(ep: pd.DataFrame) -> pd.DataFrame:
    """에피소드 분포 — 전체와 `cycle_class` 별. lead 는 kind ∈ {lead, same, lag} 만
    (none 은 NaN)."""
    rows = []
    groups: list[tuple[str, pd.DataFrame]] = [("all", ep)]
    groups += [(str(c), g) for c, g in ep.groupby("cycle_class")]
    for name, g in groups:
        x = g["lead"].dropna()
        pos = x[x > 0]
        rec: dict[str, Any] = {
            "group": name,
            "n_episodes": len(g),
            "n_lead": int((g["kind"] == "lead").sum()),
            "n_same": int((g["kind"] == "same").sum()),
            "n_lag": int((g["kind"] == "lag").sum()),
            "n_none": int((g["kind"] == "none").sum()),
            "share_lead_gt0": float((g["kind"] == "lead").mean()) if len(g) else float("nan"),
            "share_lead_ge0": float(g["kind"].isin(["lead", "same"]).mean())
            if len(g)
            else float("nan"),
            "median_lead_all": float(x.median()) if len(x) else float("nan"),
            "mean_lead_all": float(x.mean()) if len(x) else float("nan"),
            "median_lead_given_lead": float(pos.median()) if len(pos) else float("nan"),
            "p25_lead_given_lead": float(pos.quantile(0.25)) if len(pos) else float("nan"),
            "p75_lead_given_lead": float(pos.quantile(0.75)) if len(pos) else float("nan"),
            "share_lead_gt12_given_lead": float((pos > 12).mean()) if len(pos) else float("nan"),
        }
        rows.append(rec)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 과최적화 정산


def dsr_of_series(x: pd.Series, n_trials: int, *, horizon: int) -> dict[str, float]:
    """IC·스프레드 시계열의 DSR — 중첩 그대로(낙관)와 h 개월 간격 비중첩 서브샘플(offset 0)."""
    s = x.dropna()
    overlap = deflated_sharpe_ratio(s, n_trials)
    sub = s.iloc[::horizon] if horizon > 1 else s
    nonov = deflated_sharpe_ratio(sub, n_trials) if len(sub) >= 10 else float("nan")
    return {
        "dsr_overlapping": float(overlap),
        "dsr_nonoverlapping": float(nonov),
        "n": len(s),
        "n_nonoverlapping": len(sub),
    }


def pbo_of_spreads(
    sp: pd.DataFrame, *, window: str, horizon: int, max_splits: int = PBO_MAX_SPLITS
) -> dict[str, Any]:
    """열 = 스코어 변형 7 의 월별 스프레드 → CSCV PBO (S=16, 기본 전수 조합)."""
    sub = _window_slice(sp[sp["horizon"] == horizon], window)
    mat = sub.pivot(index="date", columns="variant", values="spread")[list(VARIANTS)].sort_index()
    mat = mat.dropna(how="any")
    rec: dict[str, Any] = {
        "window": window,
        "horizon": horizon,
        "n_months": len(mat),
        "strategies": list(VARIANTS),
    }
    if len(mat) < PBO_BLOCKS * 2:
        rec.update(pbo=float("nan"), note=f"관측 {len(mat)} < {PBO_BLOCKS * 2}")
        return rec
    res: PBOResult = probability_of_backtest_overfitting(
        mat, n_blocks=PBO_BLOCKS, max_splits=max_splits
    )
    rec.update(
        pbo=float(res.pbo),
        n_splits=int(res.n_splits),
        logit_mean=float(np.mean(res.logits)),
        oos_sr_of_is_best_mean=float(np.mean(res.oos_sharpe_of_is_best)),
        is_overfit=bool(res.is_overfit),
    )
    return rec


def overfitting_summary(
    ic: pd.DataFrame,
    sp: pd.DataFrame,
    trials: dict[str, int],
    *,
    pbo_max_splits: int = PBO_MAX_SPLITS,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "trials": trials,
        "dsr_threshold": DSR_THRESHOLD,
        "pbo_threshold": PBO_THRESHOLD,
        "dsr": [],
        "pbo": [],
    }
    n_all = trials["total"]
    for w in WINDOWS:
        ic_w = _window_slice(ic[ic["partition"] == PARTITION_ALL], w)
        sp_w = _window_slice(sp, w)
        # (series 이름, 긴 표, 값 열, 호라이즌) — IC 는 3·6·12M, 스프레드는 1M(PBO)까지
        spec: tuple[tuple[str, pd.DataFrame, tuple[int, ...]], ...] = (
            ("ic", ic_w, HORIZONS),
            ("spread", sp_w, (PBO_HORIZON, *HORIZONS)),
        )
        for v in VARIANTS:
            for series, frame, hs in spec:
                for h in hs:
                    s = (
                        frame[(frame["variant"] == v) & (frame["horizon"] == h)]
                        .set_index("date")[series]
                        .sort_index()
                    )
                    rec: dict[str, Any] = {
                        "window": w,
                        "variant": v,
                        "horizon": h,
                        "series": series,
                    }
                    if v == "score":
                        rec["dsr_n1"] = dsr_of_series(s, 1, horizon=h)
                    rec["dsr_n_total"] = dsr_of_series(s, n_all, horizon=h)
                    out["dsr"].append(rec)
        for h in (PBO_HORIZON, *HORIZONS):
            out["pbo"].append(pbo_of_spreads(sp, window=w, horizon=h, max_splits=pbo_max_splits))
    return out


# ---------------------------------------------------------------- 판정


def _cell(summ: pd.DataFrame, variant: str) -> pd.DataFrame:
    """관문 칸 — 주 창 · 관문 호라이즌 · 전체 파티션 · `variant`."""
    return summ[
        (summ["window"] == "primary")
        & (summ["horizon"] == GATE_HORIZON)
        & (summ["variant"] == variant)
        & (summ["partition"] == PARTITION_ALL)
    ]


def verdict(ic_summary: pd.DataFrame, overfit: dict[str, Any]) -> dict[str, Any]:
    """`docs/10` §2.3 — 주 창·12M·복합 IC 의 CI 가 0 을 넘는가. 나머지는 진단 줄로 덧붙인다."""
    g = _cell(ic_summary, "score")
    if g.empty:
        return {"gate": "undetermined", "reason": "관문 셀이 비어 있다"}
    r = g.iloc[0]
    ci_excludes_zero_pos = bool(r["ci_lo"] > 0)
    ci_excludes_zero_neg = bool(r["ci_hi"] < 0)
    dsr_rows = [
        d
        for d in overfit["dsr"]
        if d["window"] == "primary"
        and d["variant"] == "score"
        and d["horizon"] == GATE_HORIZON
        and d["series"] == "ic"
    ]
    pbo_rows = [
        p for p in overfit["pbo"] if p["window"] == "primary" and p["horizon"] == GATE_HORIZON
    ]
    dsr_n1 = dsr_rows[0]["dsr_n1"]["dsr_nonoverlapping"] if dsr_rows else float("nan")
    dsr_nt = dsr_rows[0]["dsr_n_total"]["dsr_nonoverlapping"] if dsr_rows else float("nan")
    pbo = pbo_rows[0].get("pbo", float("nan")) if pbo_rows else float("nan")
    gate = "pass" if ci_excludes_zero_pos else "fail"
    blocks = {}
    for b in BLOCKS:
        gb = _cell(ic_summary, b)
        if not gb.empty:
            rb = gb.iloc[0]
            blocks[b] = {
                "mean_ic": float(rb["mean"]),
                "ci": [float(rb["ci_lo"]), float(rb["ci_hi"])],
                "works": "yes"
                if rb["ci_lo"] > 0
                else ("negative" if rb["ci_hi"] < 0 else "indistinguishable_from_0"),
            }
    return {
        "gate": gate,
        "rule": "주 창(2011–) · 12M · 복합 score 의 rank-IC 평균 95% 블록부트스트랩 CI 하한 > 0",
        "window": "primary",
        "horizon": GATE_HORIZON,
        "mean_ic": float(r["mean"]),
        "ci": [float(r["ci_lo"]), float(r["ci_hi"])],
        "n_months": int(r["n_months"]),
        "n_eff": float(r["n_eff"]),
        "ci_excludes_zero_positive": ci_excludes_zero_pos,
        "ci_excludes_zero_negative": ci_excludes_zero_neg,
        "dsr_declared_n1_nonoverlapping": dsr_n1,
        "dsr_all_trials_nonoverlapping": dsr_nt,
        "dsr_all_trials_ge_threshold": bool(dsr_nt >= DSR_THRESHOLD)
        if not math.isnan(dsr_nt)
        else None,
        "pbo_primary_12m": pbo,
        "pbo_le_threshold": bool(pbo <= PBO_THRESHOLD)
        if not (isinstance(pbo, float) and math.isnan(pbo))
        else None,
        "blocks_12m_primary": blocks,
    }


# ---------------------------------------------------------------- 오케스트레이션


@dataclass(frozen=True)
class BacktestResult:
    ic: pd.DataFrame
    ic_summary: pd.DataFrame
    indicator_ic_summary: pd.DataFrame
    spread: pd.DataFrame
    spread_summary: pd.DataFrame
    breadth_lead: pd.DataFrame
    breadth_lead_summary: pd.DataFrame
    overfitting: dict[str, Any]
    verdict: dict[str, Any]
    meta: dict[str, Any]
    out_dir: Path | None = None
    indicator_ic: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_backtest_frames(
    panel: ThemePanel,
    ind: Indicators,
    themes: ThemeSet,
    *,
    scores: pd.DataFrame | None = None,
    with_indicator_ic: bool = True,
    pbo_max_splits: int = PBO_MAX_SPLITS,
) -> BacktestResult:
    """이미 로드된 패널·지표로 백테스트 전체를 돈다 (스토어 불필요 — 테스트와 `run_backtest`
    공용)."""
    by_id = themes.by_id()
    if scores is None:
        log.info("backtest: 전 월말 스코어보드 계산")
        scores = scoreboard_history(ind, themes)
    classes = pd.Series(
        {
            t: by_id[t].cycle_class
            for t in scores.index.get_level_values("theme").unique()
            if t in by_id
        }
    )
    log.info("backtest: 전진 수익률")
    fwd = forward_excess(panel, (PBO_HORIZON, *HORIZONS))
    small = small_sample_history(panel, themes)
    log.info("backtest: rank-IC")
    ic = rank_ic_series(scores, fwd, classes, horizons=HORIZONS)
    iic = indicator_ic_series(ind, fwd, horizons=HORIZONS) if with_indicator_ic else pd.DataFrame()
    log.info("backtest: 스프레드")
    sp = spread_series(scores, fwd, small)
    log.info("backtest: 요약·부트스트랩")
    ic_sum = summarize_ic(ic)
    iic_sum = summarize_indicator_ic(iic)
    sp_sum = summarize_spread(sp)
    ep = breadth_lead_episodes(ind, classes)
    ep_sum = summarize_breadth_lead(ep)
    prec = breadth_cross_precision(ind)
    trials = count_trials(len([i for i in SCORED_INDICATORS if i in ind.monthly.columns]))
    log.info("backtest: DSR·PBO (시도 수 %d)", trials["total"])
    overfit = overfitting_summary(ic, sp, trials, pbo_max_splits=pbo_max_splits)
    overfit["breadth_cross_precision"] = prec
    ver = verdict(ic_sum, overfit)
    xs_primary = avg_cross_corr(panel, PRIMARY_START)
    xs_full = avg_cross_corr(panel, None)
    n_scored_months = scores["score"].groupby(level="date").count()
    meta: dict[str, Any] = {
        "horizons": list(HORIZONS),
        "pbo_horizon": PBO_HORIZON,
        "gate_horizon": GATE_HORIZON,
        "primary_start": str(PRIMARY_START.date()),
        "top_k": TOP_K,
        "min_themes_xs": MIN_THEMES_XS,
        "min_themes_class": MIN_THEMES_CLASS,
        "bootstrap": {"block": BOOT_BLOCK, "n": BOOT_N, "seed": BOOT_SEED},
        "pbo": {"blocks": PBO_BLOCKS, "max_splits": pbo_max_splits},
        "score_months": {
            "first": str(n_scored_months.index.min().date()),
            "last": str(n_scored_months.index.max().date()),
            "n": len(n_scored_months),
        },
        "months_with_lt_min_themes_scored": int((n_scored_months < MIN_THEMES_XS).sum()),
        "cross_corr": {"primary": xs_primary, "full": xs_full},
        "forward_exclusions": fwd.exclusions,
        "classes": {c: int((classes == c).sum()) for c in CYCLE_CLASSES},
        "n_themes": int(classes.shape[0]),
    }
    return BacktestResult(
        ic=ic,
        ic_summary=ic_sum,
        indicator_ic=iic,
        indicator_ic_summary=iic_sum,
        spread=sp,
        spread_summary=sp_sum,
        breadth_lead=ep,
        breadth_lead_summary=ep_sum,
        overfitting=overfit,
        verdict=ver,
        meta=meta,
    )


def load_inputs(
    *, force: bool = False, compute_vcp: bool = True
) -> tuple[ThemePanel, Indicators, ThemeSet, dict[str, Any]]:
    """`msa scan` 과 같은 경로(`scan.prepare_inputs`)로 패널·지표를 (캐시에서) 가져온다.

    FRED 는 받지 않고(`allow_fetch=False`) 미분류 시총 관문은 건너뛴다 — 백테스트는 스캔이 아니다.
    """
    from msa.l1.scan import prepare_inputs

    inp = prepare_inputs(
        force=force, compute_vcp=compute_vcp, allow_fetch=False, coverage_gate=False
    )
    return inp.panel, inp.indicators, inp.themes, inp.info()


def run_backtest(
    *, out_root: Path | None = None, write: bool = True, force: bool = False
) -> BacktestResult:
    from msa.config import paths

    panel, ind, themes, info = load_inputs(force=force)
    res = run_backtest_frames(panel, ind, themes)
    res.meta.update(info)
    out_dir: Path | None = None
    if write:
        root = out_root if out_root is not None else paths().backtests_l1
        out_dir = root / str(info["store_end"])
        write_outputs(res, out_dir)
    return replace(res, out_dir=out_dir)


def write_outputs(res: BacktestResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    res.ic.to_csv(out_dir / "ic_timeseries.csv", index=False)
    res.ic_summary.to_csv(out_dir / "ic_summary.csv", index=False)
    if not res.indicator_ic.empty:
        res.indicator_ic.to_csv(out_dir / "ic_indicator_timeseries.csv", index=False)
        res.indicator_ic_summary.to_csv(out_dir / "ic_indicator.csv", index=False)
    res.spread.to_csv(out_dir / "spread.csv", index=False)
    res.spread_summary.to_csv(out_dir / "spread_summary.csv", index=False)
    res.breadth_lead.to_csv(out_dir / "breadth_lead.csv", index=False)
    res.breadth_lead_summary.to_csv(out_dir / "breadth_lead_summary.csv", index=False)
    exclusions = {
        "forward": res.meta["forward_exclusions"],
        "months_with_lt_min_themes_scored": res.meta["months_with_lt_min_themes_scored"],
        "ic_months_dropped": res.ic_summary[
            ["window", "horizon", "variant", "partition", "n_months", "n_months_dropped"]
        ].to_dict(orient="records"),
        "spread_months_dropped": res.spread_summary[
            [
                "window",
                "horizon",
                "variant",
                "n_months",
                "n_months_dropped",
                "mean_n_small_excluded",
            ]
        ].to_dict(orient="records"),
    }
    for name, obj in (
        ("overfitting.json", res.overfitting),
        ("verdict.json", res.verdict),
        ("exclusions.json", exclusions),
        ("meta.json", res.meta),
    ):
        dump_json(out_dir / name, _plain(obj))
    (out_dir / "report.txt").write_text(render_report(res), encoding="utf-8")
    log.info("backtest: 저장 %s", out_dir)


def _plain(o: Any) -> Any:
    """numpy 스칼라·배열·Timestamp → JSON 평문 (`dump_json` 의 `default=str` 에 앞서 변환한다)."""
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_plain(v) for v in o]
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, pd.Timestamp):
        return str(o.date())
    if isinstance(o, np.ndarray):
        return o.tolist()
    return o


def _pct(x: Any, w: int = 6, p: int = 0) -> str:
    """고정폭 백분율 (기호 없음, `%` 없음) — `msa.fmt.num` 에 ×100 만 얹은 것."""
    return _fmt(float(x) * 100.0 if x is not None and pd.notna(x) else float("nan"), w, p)


def _sorted(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(
        ["window", "horizon", "variant"],
        key=lambda c: c.map(_order) if c.name in ("window", "variant") else c,
    )


def _ic_table(res: BacktestResult) -> list[str]:
    hdr = (
        f"{'window':<8}{'h':>3} {'variant':<8}{'N':>5}{'N_eff':>7}{'mean':>8}{'ci_lo':>8}"
        f"{'ci_hi':>8}{'t_eff':>7}{'AR1':>6}{'pos%':>6}{'drop':>5}"
    )
    out = ["[1] 횡단면 rank-IC 요약 (partition=all)", hdr]
    s = res.ic_summary[res.ic_summary["partition"] == PARTITION_ALL]
    for _, r in _sorted(s).iterrows():
        out.append(
            f"{r['window']:<8}{int(r['horizon']):>3} {r['variant']:<8}{int(r['n_months']):>5}"
            f"{_fmt(r['n_eff'], 7, 1)}{_fmt(r['mean'], 8, 4)}{_fmt(r['ci_lo'], 8, 4)}"
            f"{_fmt(r['ci_hi'], 8, 4)}{_fmt(r['t_eff'], 7, 2)}{_fmt(r['ar1'], 6, 2)}"
            f"{_pct(r['share_pos'])}{int(r['n_months_dropped']):>5}"
        )
    return out


def _class_table(res: BacktestResult) -> list[str]:
    out = [
        "[2] cycle_class 별 블록 단독 IC (주 창 · 12M · 평균 IC [CI] · 평균 n)"
        " — `02` §7 가중치 표의 주장 대조"
    ]
    sc = res.ic_summary[
        (res.ic_summary["window"] == "primary")
        & (res.ic_summary["horizon"] == GATE_HORIZON)
        & (res.ic_summary["partition"] != PARTITION_ALL)
    ]
    out.append(f"{'class':<22}{'n̄':>5} " + " ".join(f"{v:>20}" for v in VARIANTS))
    for c in CYCLE_CLASSES:
        g = sc[sc["partition"] == c].set_index("variant")
        if g.empty:
            continue
        nbar = g["mean_n_themes"].iloc[0]
        cells = []
        for vv in VARIANTS:
            if vv in g.index:
                r = g.loc[vv]
                cell = f"{_fmt(r['mean'], 6, 3)}[{_fmt(r['ci_lo'], 6, 3)},{_fmt(r['ci_hi'], 6, 3)}]"
                cells.append(cell.replace(" ", ""))
            else:
                cells.append("—")
        out.append(f"{c:<22}{_fmt(nbar, 5, 1)} " + " ".join(f"{x:>20}" for x in cells))
    return out


def _spread_table(res: BacktestResult) -> list[str]:
    hdr = (
        f"{'window':<8}{'h':>3} {'variant':<8}{'N':>5}{'mean':>9}{'ci_lo':>9}{'ci_hi':>9}"
        f"{'hit%':>6}{'AR1':>6}{'ū':>6}{'small':>6}"
    )
    out = ["[3] 상위 8 − 하위 8 스프레드 (전진 초과수익 차, 소표본 양끝 제외)", hdr]
    for _, r in _sorted(res.spread_summary).iterrows():
        out.append(
            f"{r['window']:<8}{int(r['horizon']):>3} {r['variant']:<8}{int(r['n_months']):>5}"
            f"{_fmt(r['mean'], 9, 4)}{_fmt(r['ci_lo'], 9, 4)}{_fmt(r['ci_hi'], 9, 4)}"
            f"{_pct(r['share_pos'])}{_fmt(r['ar1'], 6, 2)}{_fmt(r['mean_n_universe'], 6, 1)}"
            f"{_fmt(r['mean_n_small_excluded'], 6, 1)}"
        )
    return out


def _breadth_lines(res: BacktestResult) -> list[str]:
    out = [
        "[4] breadth_lead 실측 — 지수 SMA200 상향 전환 에피소드에서 브레드스가 먼저 돈 개월 수"
        " (상한 없음)"
    ]
    for _, r in res.breadth_lead_summary.iterrows():
        out.append(
            f"  {r['group']:<22} 에피소드 {int(r['n_episodes']):>4}"
            f" · lead>0 {_pct(r['share_lead_gt0'], 5, 1)}%"
            f" · same {int(r['n_same']):>3} · lag {int(r['n_lag']):>3} · none {int(r['n_none']):>3}"
            f" · lead 중앙값(전체) {_fmt(r['median_lead_all'], 5, 1)}"
            f" · lead>0 일 때 중앙값 {_fmt(r['median_lead_given_lead'], 5, 1)}"
            f" [p25 {_fmt(r['p25_lead_given_lead'], 4, 1)},"
            f" p75 {_fmt(r['p75_lead_given_lead'], 4, 1)}]"
            f" · >12M {_pct(r['share_lead_gt12_given_lead'], 4)}%"
        )
    bp = res.overfitting.get("breadth_cross_precision", {})
    if bp:
        out.append(
            f"  반대 방향: 브레드스 상향 전환 {bp['n_breadth_crosses']}건 중 지수가 이미 위"
            f" {bp['index_already_above']} · {bp['search_months']}M 안에 지수 전환"
            f" {bp['index_follows_within_search']} · 둘 다 아님 {bp['neither']}"
            f" (지수가 아직 아래일 때 추종률 {_pct(bp['share_followed_given_not_above'], 5, 1)}%)"
        )
    return out


def _overfit_lines(res: BacktestResult) -> list[str]:
    t = res.overfitting["trials"]
    out = ["[6] 과최적화 정산"]
    out.append(
        f"  시도 수: 선언 1 · 이 리포트가 본 칸 {t['total']} = 창 {t['windows']}"
        f" × [변형 {t['variants']}"
        f" × 호라이즌 {t['horizons']} × (2 + 클래스 {t['classes']}) + 변형 {t['variants']} × 1M"
        f" + 지표 {t['indicators']} × {t['horizons']}]"
    )
    out.append(
        f"  {'window':<8}{'variant':<8}{'series':<7}{'h':>3}{'DSR N=1':>9}{'DSR N=all':>10}"
        f"{'N':>5}{'N_nonov':>8}"
    )
    for d in res.overfitting["dsr"]:
        n1 = d["dsr_n1"]["dsr_nonoverlapping"] if "dsr_n1" in d else float("nan")
        dt = d["dsr_n_total"]
        out.append(
            f"  {d['window']:<8}{d['variant']:<8}{d['series']:<7}{d['horizon']:>3}{_fmt(n1, 9, 3)}"
            f"{_fmt(dt['dsr_nonoverlapping'], 10, 3)}{dt['n']:>5}{dt['n_nonoverlapping']:>8}"
        )
    out.append("  (DSR 은 비중첩 서브샘플 값. 중첩 그대로의 값은 overfitting.json)")
    for p in res.overfitting["pbo"]:
        out.append(
            f"  PBO {p['window']:<8} h={p['horizon']:>2} N={p['n_months']:>4} → "
            f"{_fmt(p.get('pbo', float('nan')), 6, 3)} {p.get('note', '')}"
        )
    return out


def render_report(res: BacktestResult) -> str:
    m = res.meta
    v = res.verdict
    sm = m["score_months"]
    L: list[str] = []
    L.append("L1 백테스트 (관문 0) — 스코어 예측력. 전략 수익률이 아니다 (CLAUDE.md §7).")
    L.append(
        f"스토어 최종일 {m.get('store_end', '?')} · 지문 {m.get('fingerprint', '?')}"
        f" · 테마 {m['n_themes']}"
        f" · 스코어 월 {sm['first']}~{sm['last']} ({sm['n']}개월)"
    )
    L.append(
        f"주 창 {m['primary_start']}– (1998~2010 은 지표 이력 확보 구간) · 호라이즌 {m['horizons']}"
        f" · 관문 {m['gate_horizon']}M · K={m['top_k']}"
    )
    L.append("")
    L.append("=" * 100)
    L.append(f"판정: {v.get('gate', '?').upper()} — {v.get('rule', '')}")
    if "mean_ic" in v:
        n_all = res.overfitting["trials"]["total"]
        L.append(
            f"  복합 IC 평균 {v['mean_ic']:+.4f}  95% CI [{v['ci'][0]:+.4f}, {v['ci'][1]:+.4f}]"
            f"  N={v['n_months']}  N_eff={v['n_eff']:.1f}"
        )
        L.append(
            f"  DSR(N=1 선언, 비중첩) {_fmt(v['dsr_declared_n1_nonoverlapping'])}"
            f" · DSR(N={n_all} 전 시도, 비중첩) {_fmt(v['dsr_all_trials_nonoverlapping'])}"
            f" (기준 {DSR_THRESHOLD})"
        )
        L.append(
            f"  PBO(주 창·12M·S=16, 전략=복합+블록 6) {_fmt(v['pbo_primary_12m'])}"
            f" (기준 ≤ {PBO_THRESHOLD})"
        )
        blk = ", ".join(
            f"{b}: {d['mean_ic']:+.3f} [{d['ci'][0]:+.3f},{d['ci'][1]:+.3f}] {d['works']}"
            for b, d in v["blocks_12m_primary"].items()
        )
        L.append("  블록 단독 (주 창·12M): " + blk)
    L.append("=" * 100)
    L.append("")
    L += _ic_table(res)
    L.append("")
    L += _class_table(res)
    L.append("")
    L += _spread_table(res)
    L.append("")
    L += _breadth_lines(res)
    L.append("")
    L.append("[5] 유효 표본")
    for w in WINDOWS:
        xc = m["cross_corr"][w]
        L.append(
            f"  {w:<8} 테마 간 월별 수익률 평균 상관 — 원수익률 {_fmt(xc['avg_corr_raw'], 6, 3)}"
            f" (테마 {int(xc['n_themes_raw'])} → 유효 {_fmt(xc['n_eff_themes_raw'], 5, 1)})"
            f" · SPY 초과 {_fmt(xc['avg_corr_excess'], 6, 3)}"
            f" (→ 유효 {_fmt(xc['n_eff_themes_excess'], 5, 1)})"
        )
    L.append("  월별 IC 의 AR1·N_eff 는 [1] 표. 신뢰구간은 12개월 이동블록 부트스트랩 2000회.")
    L.append("")
    L += _overfit_lines(res)
    L.append("")
    L.append("[7] 제외 (CLAUDE.md §2)")
    L.append(f"  스코어 테마 수 < {MIN_THEMES_XS} 인 달: {m['months_with_lt_min_themes_scored']}")
    for k, val in m["forward_exclusions"].items():
        if k.startswith("h"):
            L.append(
                f"  전진 {k}: 원 {val['theme_months_raw']} · 미완결 끝점 제외"
                f" {val['dropped_incomplete_endpoint']} · 비활성 구간 제외"
                f" {val['dropped_inactive_window']} · 유지 {val['kept']}"
                f" · 전진 수익률이 전무한 월말 {val['months_without_any_forward']}"
            )
    L.append(f"  마지막 완결 월 {m['forward_exclusions']['last_complete_month']}")
    L.append("")
    L.append(
        "이 수치로 가중치를 옮기지 않는다 (CLAUDE.md §1, docs/10 §2.4)."
        " 판정 문서: docs/backtest-l1.md"
    )
    return "\n".join(L)


_ORDER = {**{w: i for i, w in enumerate(WINDOWS)}, **{v: i for i, v in enumerate(VARIANTS)}}


def _order(x: Any) -> int:
    return _ORDER.get(x, 99)
