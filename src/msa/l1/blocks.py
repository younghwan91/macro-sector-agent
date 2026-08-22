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
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from msa.l1.fundamentals import FundPanel
from msa.l1.panel import ThemePanel
from msa.l1.physical import PhysicalBundle
from msa.themes import ThemeSet
from msa.vendor.taa_signals import momentum_13612w
from msa.vendor.vcp import build_contractions, compress_pivots, find_pivots

log = logging.getLogger(__name__)

D10Y = 2520
D5Y = 1260
M10Y = 120
OWN_HIST_MIN = 84  # 7년
OWN_HIST_Z_MIN = 36

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


@dataclass(frozen=True)
class Indicators:
    monthly: pd.DataFrame  # index (date, theme)
    meta: dict[str, Any] = field(default_factory=dict)

    def wide(self, column: str) -> pd.DataFrame:
        return self.monthly[column].unstack("theme").sort_index()

    def bucket_for(self, date: pd.Timestamp) -> pd.Timestamp:
        """`date` 가 속한 달의 버킷(월말 라벨)이 있으면 그것, 없으면 `date` 이전 마지막 월말.

        오늘의 스캔(8/14)은 8월 부분 버킷(라벨 8/31, 데이터 8/14 까지)을 쓴다. 백테스트는 월말을
        정확히 넘기므로 같은 함수가 그 월말을 돌려준다."""
        date = pd.Timestamp(date)
        idx = self.monthly.index.get_level_values("date").unique().sort_values()
        label = date + pd.offsets.MonthEnd(0)
        if label in idx:
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
    zpct = z.apply(lambda col: col.map(lambda v: _phi(v) if pd.notna(v) else np.nan))
    short = (cnt < min_periods) & (cnt >= z_min) & m.notna()
    out = pct.where(~short, zpct)
    return out, short


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _months_since_max(a: np.ndarray) -> float:
    if np.isnan(a).all():
        return np.nan
    return float(len(a) - 1 - int(np.nanargmax(a)))


def vcp_index_score(close: pd.Series, *, left: int = 5, right: int = 5, max_cons: int = 4) -> float:
    """지수 레벨 VCP 점수 ∈ [0,1]. 수축 2개 미만이면 0."""
    c = close.dropna()
    if len(c) < 60:
        return np.nan
    piv = compress_pivots(find_pivots(c, left=left, right=right))
    cons = build_contractions(piv, ref_level=float(c.max()), tol=0.10, max_drop_from_ref=1.0)
    cons = [x for x in cons if x["depth"] > 0.0][
        -max_cons:
    ]  # 평탄 구간의 0 폭 "수축" 은 수축이 아니다
    if len(cons) < 2:
        return 0.0
    depths = [x["depth"] for x in cons]
    steps = len(depths) - 1
    shrinking = sum(1 for i in range(1, len(depths)) if depths[i] < depths[i - 1])
    return shrinking / steps


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
    out = np.full(br.shape, np.nan)
    for j in range(br.shape[1]):
        for i in range(br.shape[0]):
            r = rf[i, j]
            if np.isnan(r):
                continue
            s = sb[int(r), j]
            out[i, j] = 0.0 if np.isnan(s) else min(float(r - s), float(cap))
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


def _cagr(ratio: pd.Series | pd.DataFrame | float, years: float) -> Any:
    return np.sign(ratio) * np.abs(ratio) ** (1.0 / years) - 1.0 if years > 0 else np.nan


# ---------------------------------------------------------------- 본체


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
    Pcw = panel.index_level("cw")
    ret = panel.wide("ret_ew")
    dv = panel.wide("dv")
    n_listed = panel.wide("n_listed").astype(float)
    spy = panel.spy.reindex(P.index).ffill()
    S = spy["close"]
    dv_spy = spy["dv"]
    theme_cols = list(P.columns)

    if month_ends is None:
        month_ends = pd.DatetimeIndex(P.resample("ME").last().index)
    me = month_ends

    def m_last(df: pd.DataFrame) -> pd.DataFrame:
        return df.resample("ME").last().reindex(me)

    out: dict[str, pd.DataFrame] = {}
    flags: dict[str, pd.DataFrame] = {}

    # ---------------- A 망각
    out["dd_10y"] = m_last(P / P.rolling(D10Y, min_periods=252).max() - 1.0)
    Pm = m_last(P)
    cpi_ok = physical.cpi.status == "ok" and physical.cpi.series is not None
    if cpi_ok:
        cpi = physical.cpi.series.reindex(Pm.index).ffill()  # type: ignore[union-attr]
        Preal = Pm.div(cpi, axis=0)
        out["dd_real"] = Preal / Preal.rolling(M10Y, min_periods=12).max() - 1.0
    else:
        out["dd_real"] = pd.DataFrame(np.nan, index=Pm.index, columns=theme_cols)
    flags["cpi_missing"] = pd.DataFrame(not cpi_ok, index=Pm.index, columns=theme_cols)
    out["months_since_peak"] = Pm.rolling(M10Y, min_periods=12).apply(_months_since_max, raw=True)
    rel_dv = dv.div(dv_spy, axis=0).replace([np.inf, -np.inf], np.nan)
    out["liquidity_decay"] = m_last(
        rel_dv.rolling(63, min_periods=40).median() / rel_dv.rolling(D5Y, min_periods=630).median()
    )
    nl_m = m_last(n_listed)
    out["count_decay"] = nl_m / nl_m.shift(60) - 1.0

    # ---------------- B 베이스
    out["rv_ratio"] = m_last(
        ret.rolling(63, min_periods=40).std() / ret.rolling(252, min_periods=160).std()
    )
    hi = P.rolling(126, min_periods=80).max()
    lo = P.rolling(126, min_periods=80).min()
    rng = (hi - lo) / ((hi + lo) / 2.0)
    rng_pct = rng.rolling(D5Y, min_periods=630).rank(pct=True)
    out["range_compression"] = m_last(rng_pct)
    rng_cnt = rng.rolling(D5Y, min_periods=1).count()
    flags["short_hist_range"] = m_last((rng_cnt < 630) & rng.notna()).fillna(False).astype(bool)
    logP = P.apply(np.log)
    out["decline_angle"] = m_last(rolling_slope(logP, 126) - rolling_slope(logP, 504))
    out["volume_dryup"] = m_last(
        dv.rolling(21, min_periods=15).median() / dv.rolling(252, min_periods=160).median()
    )
    if compute_vcp:
        vcp = pd.DataFrame(np.nan, index=me, columns=theme_cols)
        pos = P.index.searchsorted(me, side="right")
        for j, col in enumerate(theme_cols):
            s = P[col]
            for i, end in enumerate(pos):
                if end < 60:
                    continue
                window = s.iloc[max(0, end - 252) : end]
                vcp.iat[i, j] = vcp_index_score(window)
        out["vcp_index"] = vcp
    else:
        out["vcp_index"] = pd.DataFrame(np.nan, index=me, columns=theme_cols)

    # ---------------- C 턴
    out["mom_13612w"] = momentum_13612w(Pm)
    sma200 = P.rolling(200, min_periods=200).mean()
    out["above_200"] = m_last((sma200 < P).where(sma200.notna()).astype(float))
    out["sma200_slope"] = m_last((sma200 - sma200.shift(21)).apply(np.sign))
    rs = P.div(S, axis=0)
    out["rs_slope"] = m_last(rolling_slope(rs.apply(np.log), 63))
    out["rs_trough_bounce"] = m_last(rs / rs.rolling(252, min_periods=160).min() - 1.0)
    n_sma = panel.wide("n_sma200").astype(float)
    n_ab = panel.wide("n_above200").astype(float)
    b200 = n_ab / n_sma.replace(0.0, np.nan)
    out["breadth_200"] = m_last(b200)
    nh = panel.wide("n_nh6m").astype(float)
    nl = panel.wide("n_nl6m").astype(float)
    out["breadth_nh6m"] = m_last(nh / n_listed.replace(0.0, np.nan))
    out["breadth_nhnl"] = m_last(
        ((nh - nl) / n_listed.replace(0.0, np.nan)).rolling(21, min_periods=15).sum()
    )
    out["breadth_lead"] = breadth_lead_months(out["breadth_200"], out["above_200"] > 0.5)
    ewcw = P / Pcw
    out["ew_vs_cw"] = m_last(ewcw / ewcw.shift(63) - 1.0)

    # ---------------- D 밸류
    fw = {
        c: fund.wide(c).reindex(index=me, columns=theme_cols)
        for c in (
            "ev_ebitda_med",
            "ev_sales_med",
            "pb_med",
            "fcf_yield_med",
            "ev_replacement_med",
            "ebitda_nonpos_share",
            "n_reporting",
        )
    }
    short_D = pd.DataFrame(False, index=me, columns=theme_cols)
    for c in ("ev_ebitda_med", "ev_sales_med", "pb_med", "fcf_yield_med", "ev_replacement_med"):
        out[c] = fw[c]
        pct, short = own_history_pct(fw[c])
        out[c.replace("_med", "_pct")] = pct
        short_D |= short
    out["ebitda_nonpos_share"] = fw["ebitda_nonpos_share"]
    flags["short_hist_D"] = short_D

    # ---------------- E 자본 사이클
    g = {
        c: fund.wide(c).reindex(index=me, columns=theme_cols)
        for c in (
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
    }
    ratio_ttm = g["capex_ttm_sum"] / g["da_ttm_sum"].replace(0.0, np.nan)
    out["capex_to_da_ttm"] = ratio_ttm
    out["capex_to_da"] = ratio_ttm.rolling(36, min_periods=24).mean()
    below = (ratio_ttm < 1.0) & ratio_ttm.notna()
    run = below.astype(float)
    # 연속 True 길이: 누적합에서 False 지점 값 빼기
    cs = run.cumsum()
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
    ex36 = fund.wide("exits_36m").reindex(index=me, columns=theme_cols)
    en36 = fund.wide("entries_36m").reindex(index=me, columns=theme_cols)
    out["exit_count"] = ex36
    out["entry_count"] = en36
    base36 = nl_m.shift(36).replace(0.0, np.nan)
    out["exit_rate_3y"] = ex36 / base36
    out["entry_rate_3y"] = en36 / base36

    # ---------------- F 펀더멘털
    rev_yoy = g["revenue_ss"] / g["revenue_prev_ss"].replace(0.0, np.nan) - 1.0
    out["rev_yoy"] = rev_yoy
    out["rev_yoy_d2"] = (rev_yoy - rev_yoy.shift(3)) - (rev_yoy.shift(3) - rev_yoy.shift(6))
    margin = g["ebitda_ttm_sum"] / g["revenue_ttm_sum"].where(g["revenue_ttm_sum"] > 0)
    out["ebitda_margin"] = margin
    out["ebitda_margin_pct"], flags["short_hist_margin"] = own_history_pct(margin)
    out["ebitda_margin_d4"] = margin - margin.shift(12)
    out["surprise_dir"] = pd.DataFrame(np.nan, index=me, columns=theme_cols)
    out["guidance_rev"] = pd.DataFrame(np.nan, index=me, columns=theme_cols)

    unit = _unit_block(fund, physical, themes, me, theme_cols, g, cpi_ok)
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
        "n_themes": len(theme_cols),
        "cpi": physical.cpi.status,
        "vcp_computed": compute_vcp,
        "unavailable_indicators": ["surprise_dir", "guidance_rev"],
        "unavailable_reason": "estimates 테이블 0행 (docs/08 실측)",
    }
    return Indicators(monthly=long, meta=meta)


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
    ss = {
        c: fund.wide(c).reindex(index=me, columns=theme_cols)
        for c in (
            "ss10_rev_t1",
            "ss10_rev_t0",
            "ss10_ratio_med",
            "ss10_n",
            "ss10_coverage",
            "ss10_ma_n",
            "ss5_rev_t1",
            "ss5_rev_t0",
            "ss5_ratio_med",
            "ss5_n",
            "ss5_coverage",
            "ss5_ma_n",
        )
        if c in set(fund.same_store.columns)
    }
    rev_tot = g["revenue_ttm_sum"]
    cpi_full = physical.cpi.series.dropna().resample("ME").last() if cpi_ok else None  # type: ignore[union-attr]

    for t in themes:
        col = t.id
        if col not in theme_cols:
            continue
        if t.physical_ref is None:
            txt["axis1_status"][col] = "not_declared"
            txt["unit_source"][col] = None
            continue
        ps = physical.refs.get(col)
        if ps is None or ps.status != "ok" or ps.series is None:
            txt["axis1_status"][col] = "data_missing"
            txt["unit_source"][col] = f"{t.physical_ref.source}:{t.physical_ref.symbol}"
            continue
        ref_full = ps.series.dropna()
        # 참조의 전 이력에서 CAGR 을 만든 뒤 me 로 맞춘다
        ref_full = ref_full.resample("ME").last().ffill()
        kind = t.physical_ref.kind
        txt["unit_source"][col] = f"{t.physical_ref.source}:{t.physical_ref.symbol}:{kind}"
        if kind in ("volume", "nominal"):
            if kind == "volume":
                u = ref_full
            elif cpi_full is not None:
                u = ref_full / cpi_full.reindex(ref_full.index).ffill()
            else:
                txt["axis1_status"][col] = "data_missing"  # CPI 없이 nominal 은 실질화 불가
                continue
            c10 = _cagr(u / u.shift(M10Y), 10.0).reindex(me)
            c5 = _cagr(u / u.shift(60), 5.0).reindex(me)
            num["unit_cagr_10y"][col] = c10
            num["unit_cagr_5y"][col] = c5
            # 외부 시리즈 — 동일 구성원 개념이 없다. pre==post.
            v = [axis1_verdict(a, b) for a, b in zip(c10, c5, strict=True)]
            txt["verdict_post_ss"][col] = v
            txt["verdict_pre_ss"][col] = v
            num["axis1_contested"][col] = 0.0
            txt["axis1_status"][col] = "ok_external"
            continue
        # kind == price — 폴백: 동일 구성원 매출 / 가격지수
        if not ss:
            txt["axis1_status"][col] = "data_missing"
            continue
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
        post = pd.Series([axis1_verdict(a, b) for a, b in zip(c10, c5, strict=True)], index=me)
        pre = pd.Series([axis1_verdict(a, b) for a, b in zip(pre10, pre5, strict=True)], index=me)
        txt["verdict_post_ss"][col] = post
        txt["verdict_pre_ss"][col] = pre
        contested = ((post != pre) & (post != "n/a") & (pre != "n/a")) | split
        num["axis1_contested"][col] = contested.astype(float)
        txt["axis1_status"][col] = "ok_fallback"
    return {"numeric": num, "text": txt}
