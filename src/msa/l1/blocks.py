"""6블록 지표 계산 — `docs/02-cycle-state.md` §A~§F.

입력은 테마 패널(일별)·재무 패널(월말)·실물 참조이고, 출력은 **월말 × 테마 × 지표** 긴 표다.
일별로 계산되는 지표는 일별로 만든 뒤 월말 값을 뽑는다 (월말 이전 마지막 거래일).
여기서는 **지표 값만** 만든다 — 방향(높을수록 좋은가)과 블록 점수·가중합은 `scoreboard.py` 가
맡는다. 그래야 백테스트(M3.5)가 같은 지표 표를 받아 블록별 IC 를 따로 잴 수 있다.

## 문서에 없던 구현 결정 (선언이며, 데이터에 맞춰 고르지 않았다)

- **기울기** — `log(P)` 의 OLS 기울기 (일당). 스케일 불변. `rs_slope` 도 `log(P/S)` 로 —
  문서는 "(P/S) 비율의 기울기" 라 했으나 비율 수준이 테마마다 달라 비교 불가.
- **브레드스 분모** — `n_listed` (그 날 가격 행이 있는 구성원). `n_nh6m` 은 126일 이력이 있는
  종목만 세므로 약간 과소 — 분모에 이력 조건을 넣지 않은 것은 표본이 작은 버킷에서 분모가
  0 이 되는 것을 피하기 위함.
- **`breadth_lead`** — 지수가 SMA200 위로 돌아선 시점(없으면 오늘) 기준으로, 그때 활성이던
  `breadth_200 ≥ 0.5` 구간의 시작까지의 개월 수. 12개월 상한. "지수보다 먼저 돌았는가" 를
  월 단위로 셈. 상한은 한 사이클을 넘는 리드가 의미 없기 때문.
- **`vcp_index`** — 최근 252일 창 · 피벗 좌우 5일 · 수축 2~4개 · 점수 = 수축폭이 직전보다
  줄어든 단계 수 / (수축 수 − 1). `momentum` 의 pass/fail 을 지수 레벨의 **정도**로 바꾼 것.
  돌파·거래량 조건은 안 쓴다 (§B 의 목적은 소진의 정도).
- **`exit_rate_3y`·`entry_rate_3y`** — 3년 누적 건수 / 3년 전 상장 구성원 수. 건수 그대로
  횡단면 백분위를 매기면 큰 버킷이 항상 위다. 비율이 "참여자가 얼마나 줄었는가" 다.
- **`roic`** — Σebit_ttm × (1 − t_eff) / Σinvcap, `t_eff = clip(Σtaxexp/Σ(netinc+taxexp), 0, 0.4)`,
  분모 ≤ 0 이면 0.21. `invcapavg` 가 전부 null 이라 기말 `invcap` 사용 (`docs/08` 실측).
  0.21 은 현행 미국 법인세율.
- **`capex_to_da`** — 월별 TTM 비율의 36개월 이동평균 (최소 24개월). "12분기 이동평균" 의
  월말 표현.
- **`capex_to_da_qtrs_below1`** — 평활 전 TTM 비율이 1.0 미만으로 연속된 개월 수 / 3.
  문서의 "< 1.0 이 지속된 분기 수".
- **자기이력 백분위** — 120개월 창 · 최소 84개월. 36~83개월이면 z-score → 정규 CDF 로
  대체하고 `*_short_hist` 표시. `docs/02` §9 "이력 < 7년이면 z-score".
- **축 1 판정 공백** — `unit_cagr_10y < −2%` 인데 `unit_cagr_5y ≥ unit_cagr_10y` (감소
  **감속**) 는 표의 어느 칸에도 없다 → `warning`. 사이클도 사망도 단정하지 않는 쪽이 보수적.
- **`surprise_dir`·`guidance_rev`** — 계산하지 않고 `NaN`. `estimates` 테이블이 0행
  (`docs/08` 실측). 빈 값이 아니라 "없다" 로 리포트에 표기.

## 구현 노트 (값에 영향 없음)

`months_since_peak`·`breadth_lead`·`vcp_index`·자기이력 z→Φ 는 2026-08-23 에 벡터화했다.
수학은 그대로이며 실제 캐시로 구 구현과 대조해 같음을 확인했다 (`tests/test_l1_blocks.py` 의
`_ref_*` 가 구 구현이다). Φ 만 `math.erf` → `scipy.special.ndtr` 로 바뀌어 마지막 비트(≤ 1 ulp)가
다를 수 있다 — 순위·판정에는 영향이 없다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, cast

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from scipy.special import ndtr

from msa.dates import month_end_label, to_month_end
from msa.l1.fundamentals import FundPanel
from msa.l1.panel import ThemePanel
from msa.l1.physical import PhysicalBundle
from msa.status import Axis1Status, SeriesStatus
from msa.themes import ThemeSet
from msa.vendor.taa_signals import momentum_13612w
from msa.vendor.vcp import Pivot, build_contractions, compress_pivots, find_pivots

log = logging.getLogger(__name__)

D10Y = 2520
D5Y = 1260
M10Y = 120
OWN_HIST_MIN = 84  # 7년
OWN_HIST_Z_MIN = 36
VCP_WINDOW = 252
VCP_MIN_OBS = 60
VCP_PIVOT = 5  # 피벗 좌우 일수
VCP_MAX_CONS = 4

#: 블록별 지표 목록 — 리포트 열 순서이자 "어느 블록의 지표인가" 의 정본.
BLOCK_INDICATORS: dict[str, tuple[str, ...]] = {
    "A": ("dd_10y", "dd_real", "months_since_peak", "liquidity_decay", "count_decay"),
    "B": ("vcp_index", "rv_ratio", "range_compression", "decline_angle", "volume_dryup"),
    "C": (
        "mom_13612w",
        "above_200",
        "sma200_slope",
        "rs_slope",
        "rs_trough_bounce",
        "breadth_200",
        "breadth_nh6m",
        "breadth_nhnl",
        "breadth_lead",
        "ew_vs_cw",
    ),
    "D": (
        "ev_ebitda_med",
        "ev_sales_med",
        "pb_med",
        "fcf_yield_med",
        "ev_replacement_med",
        "ev_ebitda_pct",
        "ev_sales_pct",
        "pb_pct",
        "fcf_yield_pct",
        "ev_replacement_pct",
        "ebitda_nonpos_share",
    ),
    "E": (
        "capex_to_da",
        "capex_to_da_ttm",
        "capex_to_da_qtrs_below1",
        "asset_growth",
        "roic",
        "roic_pct",
        "roic_d2",
        "share_change",
        "net_debt_ebitda",
        "net_debt_ebitda_trend",
        "exit_count",
        "entry_count",
        "exit_rate_3y",
        "entry_rate_3y",
    ),
    "F": (
        "rev_yoy",
        "rev_yoy_d2",
        "ebitda_margin",
        "ebitda_margin_pct",
        "ebitda_margin_d4",
        "surprise_dir",
        "guidance_rev",
        "unit_cagr_10y",
        "unit_cagr_5y",
        "unit_cagr_10y_median",
        "sign_split",
        "ss_n",
        "ss_coverage",
        "ma_flag",
        "axis1_contested",
    ),
}

#: 수치가 아닌(문자열) 출력 — 긴 표에 같이 실리지만 백분위 대상이 아니다.
TEXT_OUTPUTS = ("verdict_post_ss", "verdict_pre_ss", "unit_source", "axis1_status")
#: 표본·이력 플래그 (bool)
FLAG_OUTPUTS = (
    "short_hist_D",
    "short_hist_roic",
    "short_hist_margin",
    "short_hist_range",
    "cpi_missing",
)

#: 재무 패널에서 E·F 블록이 읽는 합계 열.
_FUND_SUM_COLS = (
    "capex_ttm_sum",
    "da_ttm_sum",
    "assets_ss",
    "assets_prev_ss",
    "ebit_ttm_sum",
    "taxexp_ttm_sum",
    "netinc_ttm_sum",
    "invcap_sum",
    "shares_ss",
    "shares_prev3y_ss",
    "debt_sum",
    "cash_sum",
    "ebitda_ttm_sum",
    "revenue_ttm_sum",
    "revenue_ss",
    "revenue_prev_ss",
    "ebitda_ss",
    "ebitda_prev_ss",
    "revenue_for_ebitda_ss",
    "revenue_prev_for_ebitda_ss",
)
#: D 블록의 밸류 중앙값 (자기이력 백분위 대상).
_VALUE_MED_COLS = ("ev_ebitda_med", "ev_sales_med", "pb_med", "fcf_yield_med", "ev_replacement_med")
#: 동일 구성원 열 (축 1 폴백).
_SS_COLS = tuple(
    f"ss{y}_{c}"
    for y in (10, 5)
    for c in ("rev_t1", "rev_t0", "ratio_med", "n", "coverage", "ma_n")
)


@dataclass(frozen=True)
class Indicators:
    monthly: pd.DataFrame  # index (date, theme)
    meta: dict[str, Any] = field(default_factory=dict)

    def wide(self, column: str) -> pd.DataFrame:
        return self.monthly[column].unstack("theme").sort_index()

    @cached_property
    def dates(self) -> pd.DatetimeIndex:
        """월말 라벨(버킷) 오름차순 — `bucket_for` 가 매번 다시 만들지 않게 한 번만."""
        return pd.DatetimeIndex(self.monthly.index.get_level_values("date").unique().sort_values())

    def bucket_for(self, date: pd.Timestamp) -> pd.Timestamp:
        """`date` **이하의 마지막 완결 월말** 버킷. 단 부분 버킷은 스토어 끝일 때만 허용한다.

        오늘의 스캔(8/14)은 8월 부분 버킷(라벨 8/31, 데이터 8/14 까지)을 쓴다 — 미래가 아직
        존재하지 않으므로 미래 참조가 아니다. 백테스트는 월말을 정확히 넘기므로 같은 함수가
        그 월말을 돌려준다.

        **2026-08-24 수정.** 예전에는 `date` 가 속한 달의 라벨이 있으면 무조건 돌려줬다.
        과거 `--asof` (예 2020-07-03) 로도 2020-07-31 버킷 — **최대 4주 미래** — 이 나왔고,
        그 스냅샷이 잘못 라벨된 채 L3·L4 로 흘러갔다. CLI 도움말(`msa scan --asof`)이 선언한
        "그 이전 마지막 월말" 과 어긋난 쪽이 코드였다.

        선택지는 둘이었다 — (a) 언제나 마지막 **완결** 월말, (b) 부분 버킷은 스토어 끝
        (= 지표 격자의 마지막 라벨) 일 때만. **(b) 를 택한다.** (a) 는 CLI 도움말에는
        맞지만 이 함수 자신의 선언("오늘의 스캔은 부분 버킷을 쓴다") 과 오늘의 스캔 동작을
        깨뜨린다. (b) 는 두 선언을 동시에 만족한다: 과거 asof 는 도움말대로 완결 월말만,
        오늘의 스캔(asof = store_end)은 예전 그대로.

        부분 버킷은 격자의 **마지막** 라벨뿐이다 (격자는 `to_month_end(P)` 의 resample 라벨이라
        스토어 최종일이 속한 달까지만 있다). 그래서 "마지막 라벨" 이 곧 "스토어 끝" 이다.
        """
        date = pd.Timestamp(date)
        idx = self.dates
        label = month_end_label(date)
        if label in idx and (label == date or label == idx[-1]):
            return pd.Timestamp(label)
        cand = idx[idx <= date]
        if len(cand) == 0:
            raise KeyError(f"{date.date()} 이전 월말이 없다 (시작 {idx[0].date()})")
        return pd.Timestamp(cand[-1])

    def at(self, date: pd.Timestamp) -> pd.DataFrame:
        """그 월(버킷)의 테마 × 지표 표. `bucket_for` 참조."""
        out = self.monthly.xs(self.bucket_for(date), level="date")
        assert isinstance(out, pd.DataFrame)
        return out


# ---------------------------------------------------------------- 수학 헬퍼


def rolling_slope(y: pd.DataFrame, window: int, min_periods: int | None = None) -> pd.DataFrame:
    """열별 OLS 기울기 (x = 0..window−1). 누적합으로 완전 벡터화. NaN 은 구간 안에서 무시하지 않는다
    (구간에 NaN 이 있으면 NaN) — 지수는 연속이므로 실제로 문제되지 않는다."""
    mp = window if min_periods is None else min_periods
    n = window
    k = np.arange(n, dtype=float)
    sk = k.sum()
    skk = (k * k).sum()
    denom = n * skk - sk * sk
    # Σ_j j·y_{t-n+1+j} = Σ_i i·y_i − (t−n+1)·Σ_i y_i  (i = 전역 행 번호)
    i = np.arange(len(y), dtype=float)
    yi = y.mul(i, axis=0)
    s_y = y.rolling(n, min_periods=mp).sum()
    s_iy = yi.rolling(n, min_periods=mp).sum()
    t0 = pd.Series(i - (n - 1), index=y.index)
    s_jy = s_iy.sub(s_y.mul(t0, axis=0))
    slope: pd.DataFrame = (n * s_jy - sk * s_y) / denom
    return slope


def own_history_pct(
    m: pd.DataFrame,
    window: int = M10Y,
    min_periods: int = OWN_HIST_MIN,
    z_min: int = OWN_HIST_Z_MIN,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """자기이력 백분위 (월별). 이력이 `min_periods` 미만이고 `z_min` 이상이면 z-score → Φ 로 대체.
    반환: (pct, short_hist_flag)."""
    pct = m.rolling(window, min_periods=min_periods).rank(pct=True)
    cnt = m.rolling(window, min_periods=1).count()
    mu = m.rolling(window, min_periods=z_min).mean()
    sd = m.rolling(window, min_periods=z_min).std()
    z = (m - mu) / sd.replace(0.0, np.nan)
    zpct = pd.DataFrame(ndtr(z.to_numpy(dtype=float)), index=z.index, columns=z.columns)
    short = (cnt < min_periods) & (cnt >= z_min) & m.notna()
    out = pct.where(~short, zpct)
    return out, short


def months_since_peak(pm: pd.DataFrame, window: int = M10Y, min_periods: int = 12) -> pd.DataFrame:
    """월별. 최근 `window` 개월 창 안의 최고점(**최초 도달**)으로부터 지난 개월 수.
    관측이 `min_periods` 미만이면 NaN. (`rolling(window).apply(len−1−nanargmax)` 와 같다.)"""
    a = pm.to_numpy(dtype=float)
    if a.shape[0] == 0:
        return pd.DataFrame(a, index=pm.index, columns=pm.columns)
    pad = np.full((window - 1, a.shape[1]), np.nan)
    win = sliding_window_view(np.vstack([pad, a]), window, axis=0)  # (T, K, window)
    cnt = (~np.isnan(win)).sum(axis=2)
    am = np.where(np.isnan(win), -np.inf, win).argmax(axis=2)  # 첫 번째 최댓값
    out = (window - 1 - am).astype(float)
    out[cnt < min_periods] = np.nan
    return pd.DataFrame(out, index=pm.index, columns=pm.columns)


def _vcp_score(piv: list[Pivot], ref_level: float, max_cons: int) -> float:
    """피벗 목록 → VCP 점수 ∈ [0,1]. 수축 2개 미만이면 0."""
    cons = build_contractions(
        compress_pivots(piv), ref_level=ref_level, tol=0.10, max_drop_from_ref=1.0
    )
    # 평탄 구간의 0 폭 "수축" 은 수축이 아니다
    cons = [x for x in cons if x["depth"] > 0.0][-max_cons:]
    if len(cons) < 2:
        return 0.0
    depths = [x["depth"] for x in cons]
    steps = len(depths) - 1
    shrinking = sum(1 for i in range(1, len(depths)) if depths[i] < depths[i - 1])
    return shrinking / steps


def vcp_index_score(
    close: pd.Series, *, left: int = VCP_PIVOT, right: int = VCP_PIVOT, max_cons: int = VCP_MAX_CONS
) -> float:
    """지수 레벨 VCP 점수 ∈ [0,1]. 수축 2개 미만이면 0. 관측 60 미만이면 NaN."""
    c = close.dropna()
    if len(c) < VCP_MIN_OBS:
        return np.nan
    return _vcp_score(find_pivots(c, left=left, right=right), float(c.max()), max_cons)


def _pivots_all(c: pd.Series, left: int, right: int) -> tuple[np.ndarray, list[Pivot]]:
    """전 구간 피벗 (`find_pivots` 와 같은 목록 — 같은 시점은 H 가 L 앞). 위치 배열을 함께 돌려준다.

    임의 창 `[lo, hi)` 의 피벗은 이 목록에서 위치가 `[lo+left, hi−right)` 인 것과 **정확히 같다** —
    피벗 조건이 좌우 `left`·`right` 일만 보기 때문이다."""
    vals = c.to_numpy(dtype=float)
    n = len(vals)
    span = left + right + 1
    if n < span:
        return np.empty(0, dtype=int), []
    w = sliding_window_view(vals, span)
    centre = vals[left : n - right]
    is_h = centre == w.max(axis=1)
    is_l = centre == w.min(axis=1)
    idx = c.index
    ks: list[int] = []
    piv: list[Pivot] = []
    for k in (np.flatnonzero(is_h | is_l) + left).tolist():
        if is_h[k - left]:
            ks.append(k)
            piv.append((idx[k], "H", float(vals[k])))
        if is_l[k - left]:
            ks.append(k)
            piv.append((idx[k], "L", float(vals[k])))
    return np.asarray(ks, dtype=int), piv


def vcp_index_matrix(
    P: pd.DataFrame,
    me: pd.DatetimeIndex,
    *,
    window: int = VCP_WINDOW,
    left: int = VCP_PIVOT,
    right: int = VCP_PIVOT,
    max_cons: int = VCP_MAX_CONS,
) -> pd.DataFrame:
    """월말 × 테마 `vcp_index` — 각 월말에서 직전 `window` 일 창의 `vcp_index_score`.

    피벗은 테마별로 전 구간에서 한 번만 찾고 창마다 잘라 쓴다 (결과는 창마다 `find_pivots` 를
    다시 부르는 것과 같다). 창 안 관측 60 미만이면 NaN."""
    out = np.full((len(me), P.shape[1]), np.nan)
    ends = P.index.searchsorted(me, side="right")
    for j, col in enumerate(P.columns):
        s = P[col]
        valid = np.flatnonzero(s.notna().to_numpy())
        c = s.iloc[valid]
        ks, piv = _pivots_all(c, left, right)
        vals = c.to_numpy(dtype=float)
        for i, end in enumerate(ends):
            lo = int(np.searchsorted(valid, max(0, int(end) - window)))
            hi = int(np.searchsorted(valid, int(end)))
            if hi - lo < VCP_MIN_OBS:
                continue
            a, b = np.searchsorted(ks, [lo + left, hi - right])
            out[i, j] = _vcp_score(piv[a:b], float(vals[lo:hi].max()), max_cons)
    return pd.DataFrame(out, index=me, columns=P.columns)


def breadth_lead_months(breadth: pd.DataFrame, above: pd.DataFrame, cap: int = 12) -> pd.DataFrame:
    """월별. `breadth ≥ 0.5` 구간의 시작과 지수 전환 시점의 차이 (개월)."""
    br = (breadth >= 0.5) & breadth.notna()
    ab = above.fillna(False).astype(bool)
    pos = pd.DataFrame(
        np.tile(np.arange(len(br))[:, None], (1, br.shape[1])), index=br.index, columns=br.columns
    ).astype(float)
    # br 런 시작: 직전이 False 이고 지금 True 인 위치 → ffill (False 구간에서는 NaN)
    start_br = pos.where(br & ~br.shift(1, fill_value=False)).ffill().where(br)
    start_ab = pos.where(ab & ~ab.shift(1, fill_value=False)).ffill().where(ab)
    # 기준 시점: 지수가 위면 그 전환 시점, 아니면 지금
    ref = start_ab.where(ab, pos)
    # 기준 시점에 활성이던 br 런의 시작 — ref 위치의 start_br 값
    sb = start_br.to_numpy(dtype=float)
    rf = ref.to_numpy(dtype=float)
    has_ref = ~np.isnan(rf)
    r_idx = np.where(has_ref, rf, 0.0).astype(int)
    s = np.take_along_axis(sb, r_idx, axis=0) if sb.size else sb
    val = np.where(np.isnan(s), 0.0, np.minimum(rf - s, float(cap)))
    out = np.where(has_ref, val, np.nan)
    return pd.DataFrame(out, index=br.index, columns=br.columns)


def axis1_verdict(cagr10: float, cagr5: float) -> str:
    """`docs/04-value-trap.md` 축 1 판정표. 임계는 불변."""
    if pd.isna(cagr10) or pd.isna(cagr5):
        return "n/a"
    if cagr10 >= 0:
        return "cycle"
    if cagr10 >= -0.02:
        return "warning"
    if cagr5 < cagr10:
        return "death"
    return "warning"  # 감소 감속 — 표의 공백, 보수적으로 경고


def _verdicts(cagr10: pd.Series, cagr5: pd.Series) -> pd.Series:
    """`axis1_verdict` 의 벡터판 (같은 표, 같은 순서의 조건)."""
    c10 = cagr10.to_numpy(dtype=float)
    c5 = cagr5.to_numpy(dtype=float)
    out = np.select(
        [np.isnan(c10) | np.isnan(c5), c10 >= 0, c10 >= -0.02, c5 < c10],
        ["n/a", "cycle", "warning", "death"],
        default="warning",
    )
    return pd.Series(out.tolist(), index=cagr10.index)  # 구 구현의 `pd.Series([...])` 와 같은 dtype


def _cagr(ratio: pd.Series | pd.DataFrame | float, years: float) -> Any:
    return np.sign(ratio) * np.abs(ratio) ** (1.0 / years) - 1.0 if years > 0 else np.nan


# ---------------------------------------------------------------- 본체


@dataclass(frozen=True)
class _Ctx:
    """블록 함수들이 공유하는 재료 — 일별 행렬과 월말 격자."""

    P: pd.DataFrame  # EW 지수 (일별)
    Pcw: pd.DataFrame  # CW 지수 (일별)
    Pm: pd.DataFrame  # EW 지수 월말
    ret: pd.DataFrame
    dv: pd.DataFrame
    n_listed: pd.DataFrame
    nl_m: pd.DataFrame  # n_listed 월말
    S: pd.Series  # SPY close (P.index 에 맞춤)
    dv_spy: pd.Series
    me: pd.DatetimeIndex
    theme_cols: list[str]
    cpi_ok: bool
    cpi: pd.Series | None  # 월말 CPI (원 주기 그대로, dropna 전)

    def m_last(self, df: pd.DataFrame) -> pd.DataFrame:
        return to_month_end(df).reindex(self.me)

    def nan(self) -> pd.DataFrame:
        return pd.DataFrame(np.nan, index=self.me, columns=self.theme_cols)


def compute_indicators(
    panel: ThemePanel,
    fund: FundPanel,
    physical: PhysicalBundle,
    themes: ThemeSet,
    *,
    month_ends: pd.DatetimeIndex | None = None,
    compute_vcp: bool = True,
) -> Indicators:
    P = panel.index_level("ew")
    spy = panel.spy.reindex(P.index).ffill()
    n_listed = panel.wide("n_listed").astype(float)
    me = month_ends if month_ends is not None else pd.DatetimeIndex(to_month_end(P).index)
    cpi_ok = physical.cpi.status == SeriesStatus.OK and physical.cpi.series is not None
    ctx = _Ctx(
        P=P,
        Pcw=panel.index_level("cw"),
        Pm=to_month_end(P).reindex(me),
        ret=panel.wide("ret_ew"),
        dv=panel.wide("dv"),
        n_listed=n_listed,
        nl_m=to_month_end(n_listed).reindex(me),
        S=spy["close"],
        dv_spy=spy["dv"],
        me=me,
        theme_cols=list(P.columns),
        cpi_ok=cpi_ok,
        cpi=physical.cpi.series if cpi_ok else None,
    )

    def fund_w(c: str) -> pd.DataFrame:
        return fund.wide(c).reindex(index=me, columns=ctx.theme_cols)

    g = {c: fund_w(c) for c in _FUND_SUM_COLS}

    out: dict[str, pd.DataFrame] = {}
    flags: dict[str, pd.DataFrame] = {}
    _block_a(ctx, out, flags)
    _block_b(ctx, panel, out, flags, compute_vcp=compute_vcp)
    _block_c(ctx, panel, out)
    _block_d(ctx, fund_w, out, flags)
    _block_e(ctx, g, fund_w, out, flags)
    _block_f(ctx, g, out, flags)
    unit = _unit_block(fund, physical, themes, me, ctx.theme_cols, g, cpi_ok)
    out.update(unit["numeric"])

    # ---------------- 조립
    long = pd.concat({k: v.stack(future_stack=True) for k, v in out.items()}, axis=1)
    long.index.names = ["date", "theme"]
    for k, v in flags.items():
        long[k] = v.stack(future_stack=True).reindex(long.index).fillna(False).astype(bool)
    for k, v in unit["text"].items():
        long[k] = v.stack(future_stack=True).reindex(long.index)
    long = long.sort_index()
    meta = {
        "month_ends": [str(d.date()) for d in (me[0], me[-1])],
        "n_themes": len(ctx.theme_cols),
        "cpi": physical.cpi.status,
        "vcp_computed": compute_vcp,
        "unavailable_indicators": ["surprise_dir", "guidance_rev"],
        "unavailable_reason": "estimates 테이블 0행 (docs/08 실측)",
    }
    return Indicators(monthly=long, meta=meta)


def _block_a(ctx: _Ctx, out: dict[str, pd.DataFrame], flags: dict[str, pd.DataFrame]) -> None:
    """A 망각 — dd_10y · dd_real · months_since_peak · liquidity_decay · count_decay."""
    P, Pm = ctx.P, ctx.Pm
    out["dd_10y"] = ctx.m_last(P / P.rolling(D10Y, min_periods=252).max() - 1.0)
    if ctx.cpi is not None:
        cpi = ctx.cpi.reindex(Pm.index).ffill()
        Preal = Pm.div(cpi, axis=0)
        out["dd_real"] = Preal / Preal.rolling(M10Y, min_periods=12).max() - 1.0
    else:
        out["dd_real"] = ctx.nan()
    flags["cpi_missing"] = pd.DataFrame(not ctx.cpi_ok, index=Pm.index, columns=ctx.theme_cols)
    out["months_since_peak"] = months_since_peak(Pm, M10Y, 12)
    rel_dv = ctx.dv.div(ctx.dv_spy, axis=0).replace([np.inf, -np.inf], np.nan)
    out["liquidity_decay"] = ctx.m_last(
        rel_dv.rolling(63, min_periods=40).median() / rel_dv.rolling(D5Y, min_periods=630).median()
    )
    out["count_decay"] = ctx.nl_m / ctx.nl_m.shift(60) - 1.0


def _block_b(
    ctx: _Ctx,
    panel: ThemePanel,
    out: dict[str, pd.DataFrame],
    flags: dict[str, pd.DataFrame],
    *,
    compute_vcp: bool,
) -> None:
    """B 베이스 — rv_ratio · range_compression · decline_angle · volume_dryup · vcp_index."""
    P, ret, dv = ctx.P, ctx.ret, ctx.dv
    out["rv_ratio"] = ctx.m_last(
        ret.rolling(63, min_periods=40).std() / ret.rolling(252, min_periods=160).std()
    )
    hi = P.rolling(126, min_periods=80).max()
    lo = P.rolling(126, min_periods=80).min()
    rng = (hi - lo) / ((hi + lo) / 2.0)
    out["range_compression"] = ctx.m_last(rng.rolling(D5Y, min_periods=630).rank(pct=True))
    rng_cnt = rng.rolling(D5Y, min_periods=1).count()
    flags["short_hist_range"] = ctx.m_last((rng_cnt < 630) & rng.notna()).fillna(False).astype(bool)
    logP = cast(pd.DataFrame, np.log(P))
    out["decline_angle"] = ctx.m_last(rolling_slope(logP, 126) - rolling_slope(logP, 504))
    out["volume_dryup"] = ctx.m_last(
        dv.rolling(21, min_periods=15).median() / dv.rolling(252, min_periods=160).median()
    )
    out["vcp_index"] = vcp_index_matrix(P, ctx.me) if compute_vcp else ctx.nan()


def _block_c(ctx: _Ctx, panel: ThemePanel, out: dict[str, pd.DataFrame]) -> None:
    """C 턴 — 모멘텀 · SMA200 · 상대강도 · 브레드스 3종 · breadth_lead · ew_vs_cw."""
    P, S = ctx.P, ctx.S
    out["mom_13612w"] = momentum_13612w(ctx.Pm)
    sma200 = P.rolling(200, min_periods=200).mean()
    out["above_200"] = ctx.m_last((sma200 < P).where(sma200.notna()).astype(float))
    out["sma200_slope"] = ctx.m_last(cast(pd.DataFrame, np.sign(sma200 - sma200.shift(21))))
    rs = P.div(S, axis=0)
    out["rs_slope"] = ctx.m_last(rolling_slope(cast(pd.DataFrame, np.log(rs)), 63))
    out["rs_trough_bounce"] = ctx.m_last(rs / rs.rolling(252, min_periods=160).min() - 1.0)
    n_sma = panel.wide("n_sma200").astype(float)
    n_ab = panel.wide("n_above200").astype(float)
    out["breadth_200"] = ctx.m_last(n_ab / n_sma.replace(0.0, np.nan))
    nh = panel.wide("n_nh6m").astype(float)
    nl = panel.wide("n_nl6m").astype(float)
    denom = ctx.n_listed.replace(0.0, np.nan)
    out["breadth_nh6m"] = ctx.m_last(nh / denom)
    out["breadth_nhnl"] = ctx.m_last(((nh - nl) / denom).rolling(21, min_periods=15).sum())
    out["breadth_lead"] = breadth_lead_months(out["breadth_200"], out["above_200"] > 0.5)
    ewcw = P / ctx.Pcw
    out["ew_vs_cw"] = ctx.m_last(ewcw / ewcw.shift(63) - 1.0)


def _block_d(
    ctx: _Ctx,
    fund_w: Callable[[str], pd.DataFrame],
    out: dict[str, pd.DataFrame],
    flags: dict[str, pd.DataFrame],
) -> None:
    """D 밸류 — 중앙값 5종과 그 자기이력 백분위 · 적자 제외 비율."""
    short_D = pd.DataFrame(False, index=ctx.me, columns=ctx.theme_cols)
    for c in _VALUE_MED_COLS:
        out[c] = fund_w(c)
        pct, short = own_history_pct(out[c])
        out[c.replace("_med", "_pct")] = pct
        short_D |= short
    out["ebitda_nonpos_share"] = fund_w("ebitda_nonpos_share")
    flags["short_hist_D"] = short_D


def _block_e(
    ctx: _Ctx,
    g: dict[str, pd.DataFrame],
    fund_w: Callable[[str], pd.DataFrame],
    out: dict[str, pd.DataFrame],
    flags: dict[str, pd.DataFrame],
) -> None:
    """E 자본 사이클 — capex/D&A · 자산성장 · ROIC · 주식수 · 순부채 · 진입/퇴출."""
    ratio_ttm = g["capex_ttm_sum"] / g["da_ttm_sum"].replace(0.0, np.nan)
    out["capex_to_da_ttm"] = ratio_ttm
    out["capex_to_da"] = ratio_ttm.rolling(36, min_periods=24).mean()
    below = (ratio_ttm < 1.0) & ratio_ttm.notna()
    # 연속 True 길이: 누적합에서 False 지점 값 빼기
    cs = below.astype(float).cumsum()
    reset = cs.where(~below).ffill().fillna(0.0)
    out["capex_to_da_qtrs_below1"] = ((cs - reset) / 3.0).where(ratio_ttm.notna())
    out["asset_growth"] = g["assets_ss"] / g["assets_prev_ss"].replace(0.0, np.nan) - 1.0
    pretax = g["netinc_ttm_sum"] + g["taxexp_ttm_sum"]
    t_eff = (g["taxexp_ttm_sum"] / pretax.where(pretax > 0)).clip(0.0, 0.4).fillna(0.21)
    roic = g["ebit_ttm_sum"] * (1.0 - t_eff) / g["invcap_sum"].where(g["invcap_sum"] > 0)
    out["roic"] = roic
    out["roic_pct"], flags["short_hist_roic"] = own_history_pct(roic)
    out["roic_d2"] = (roic - roic.shift(3)) - (roic.shift(3) - roic.shift(6))
    out["share_change"] = g["shares_ss"] / g["shares_prev3y_ss"].replace(0.0, np.nan) - 1.0
    nde = (g["debt_sum"] - g["cash_sum"]) / g["ebitda_ttm_sum"].where(g["ebitda_ttm_sum"] > 0)
    out["net_debt_ebitda"] = nde
    out["net_debt_ebitda_trend"] = -(nde - nde.shift(12))
    ex36 = fund_w("exits_36m")
    en36 = fund_w("entries_36m")
    out["exit_count"] = ex36
    out["entry_count"] = en36
    base36 = ctx.nl_m.shift(36).replace(0.0, np.nan)
    out["exit_rate_3y"] = ex36 / base36
    out["entry_rate_3y"] = en36 / base36


def _block_f(
    ctx: _Ctx,
    g: dict[str, pd.DataFrame],
    out: dict[str, pd.DataFrame],
    flags: dict[str, pd.DataFrame],
) -> None:
    """F 펀더멘털 — 매출 성장과 가속 · 마진과 자기이력 · (없는) 서프라이즈·리비전."""
    rev_yoy = g["revenue_ss"] / g["revenue_prev_ss"].replace(0.0, np.nan) - 1.0
    out["rev_yoy"] = rev_yoy
    out["rev_yoy_d2"] = (rev_yoy - rev_yoy.shift(3)) - (rev_yoy.shift(3) - rev_yoy.shift(6))
    margin = g["ebitda_ttm_sum"] / g["revenue_ttm_sum"].where(g["revenue_ttm_sum"] > 0)
    out["ebitda_margin"] = margin
    out["ebitda_margin_pct"], flags["short_hist_margin"] = own_history_pct(margin)
    out["ebitda_margin_d4"] = margin - margin.shift(12)
    out["surprise_dir"] = ctx.nan()
    out["guidance_rev"] = ctx.nan()


def _unit_block(
    fund: FundPanel,
    physical: PhysicalBundle,
    themes: ThemeSet,
    me: pd.DatetimeIndex,
    theme_cols: list[str],
    g: dict[str, pd.DataFrame],
    cpi_ok: bool,
) -> dict[str, dict[str, pd.DataFrame]]:
    """축 1 `unit_series` 계열 — 테마별로 참조 종류에 따라 갈린다 (`docs/04` 축 1)."""

    def nan() -> pd.DataFrame:
        return pd.DataFrame(np.nan, index=me, columns=theme_cols)

    num = {
        k: nan()
        for k in (
            "unit_cagr_10y",
            "unit_cagr_5y",
            "unit_cagr_10y_median",
            "sign_split",
            "ss_n",
            "ss_coverage",
            "ma_flag",
            "axis1_contested",
        )
    }
    txt = {k: pd.DataFrame(None, index=me, columns=theme_cols, dtype=object) for k in TEXT_OUTPUTS}
    have = set(fund.same_store.columns)
    ss = {c: fund.wide(c).reindex(index=me, columns=theme_cols) for c in _SS_COLS if c in have}
    rev_tot = g["revenue_ttm_sum"]
    cpi_full = to_month_end(physical.cpi.series.dropna()) if cpi_ok else None  # type: ignore[union-attr]
    status = txt["axis1_status"]
    unit_source = txt["unit_source"]

    for t in themes:
        col = t.id
        if col not in theme_cols:
            continue
        ref = t.physical_ref
        if ref is None:
            status[col] = Axis1Status.NOT_DECLARED.value
            unit_source[col] = None
            continue
        ps = physical.refs.get(col)
        ok = ps is not None and ps.ok
        unit_source[col] = f"{ref.source}:{ref.symbol}" + (f":{ref.kind}" if ok else "")
        if ref.kind == "nominal" and cpi_full is None:
            ok = False  # CPI 없이 nominal 은 실질화 불가
        if ref.kind == "price" and not ss:
            ok = False  # 동일 구성원 매출 없이는 가격지수 폴백 불가
        if not ok:
            status[col] = Axis1Status.DATA_MISSING.value
            continue
        assert ps is not None and ps.series is not None
        # 참조의 전 이력에서 CAGR 을 만든 뒤 me 로 맞춘다
        ref_full = to_month_end(ps.series.dropna()).ffill()
        if ref.kind in ("volume", "nominal"):
            if ref.kind == "volume":
                u = ref_full
            else:
                assert cpi_full is not None
                u = ref_full / cpi_full.reindex(ref_full.index).ffill()
            c10 = _cagr(u / u.shift(M10Y), 10.0).reindex(me)
            c5 = _cagr(u / u.shift(60), 5.0).reindex(me)
            num["unit_cagr_10y"][col] = c10
            num["unit_cagr_5y"][col] = c5
            # 외부 시리즈 — 동일 구성원 개념이 없다. pre==post.
            v = _verdicts(c10, c5)
            txt["verdict_post_ss"][col] = v
            txt["verdict_pre_ss"][col] = v
            num["axis1_contested"][col] = 0.0
            status[col] = Axis1Status.OK_EXTERNAL.value
            continue
        # kind == price — 폴백: 동일 구성원 매출 / 가격지수
        pr10 = (ref_full / ref_full.shift(M10Y)).reindex(me)
        pr5 = (ref_full / ref_full.shift(60)).reindex(me)
        r10 = (ss["ss10_rev_t1"][col] / ss["ss10_rev_t0"][col]) / pr10
        r5 = (ss["ss5_rev_t1"][col] / ss["ss5_rev_t0"][col]) / pr5
        c10 = _cagr(r10, 10.0)
        c5 = _cagr(r5, 5.0)
        c10m = _cagr(ss["ss10_ratio_med"][col] / pr10, 10.0)
        pre10 = _cagr((rev_tot[col] / rev_tot[col].shift(M10Y)) / pr10, 10.0)
        pre5 = _cagr((rev_tot[col] / rev_tot[col].shift(60)) / pr5, 5.0)
        num["unit_cagr_10y"][col] = c10
        num["unit_cagr_5y"][col] = c5
        num["unit_cagr_10y_median"][col] = c10m
        split = (np.sign(c10) != np.sign(c10m)) & c10.notna() & c10m.notna()
        num["sign_split"][col] = split.astype(float)
        num["ss_n"][col] = ss["ss10_n"][col]
        num["ss_coverage"][col] = ss["ss10_coverage"][col]
        num["ma_flag"][col] = (
            (ss["ss10_ma_n"][col].fillna(0) > 0).astype(float).where(ss["ss10_n"][col].notna())
        )
        post = _verdicts(c10, c5)
        pre = _verdicts(pre10, pre5)
        txt["verdict_post_ss"][col] = post
        txt["verdict_pre_ss"][col] = pre
        contested = ((post != pre) & (post != "n/a") & (pre != "n/a")) | split
        num["axis1_contested"][col] = contested.astype(float)
        status[col] = Axis1Status.OK_FALLBACK.value
    return {"numeric": num, "text": txt}
