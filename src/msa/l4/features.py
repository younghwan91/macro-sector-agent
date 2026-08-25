"""종목 레벨 특성 — `docs/06-stock-selection.md` §2~§4 의 원재료.

테마 구성원(`Membership.members`) 각각에 대해 S(생존)·T(토크)·M(타이밍) 축이 읽을 값을 만든다.
**값만 만든다** — 임계·감점·백분위·가중합은 `axes.py` 가 맡는다 (L1 의 `blocks` / `scoreboard`
분리와 같은 이유: 백테스트가 같은 특성 표를 받아 축별 IC 를 따로 잴 수 있어야 한다).

## PIT — 전부 `datekey` 기준, 최초 보고분

`CLAUDE.md` PIT 규약 표는 자기이력 백분위·자본사이클 시계열은 PIT 필요, 오늘의 스냅샷(런웨이·
부채비율)은 불필요라 한다. 여기서는 L1 `fundamentals.py` 와 같은 이유로 **더 엄격한 쪽(PIT)으로
통일**한다 — `datekey ≤ asof` 인 행만 쓰고, 같은 `calendardate` 가 여러 `datekey` 로 다시 보고된
경우 최초 보고분만 쓴다. 한 모듈 안에서 두 규칙을 섞지 않는다. 가격은 개정되지 않으므로 PIT
구분이 없다. **이 모듈은 백테스트·오늘의 스캔 두 경로에서 같은 함수로 호출된다** — 호출자가
`asof` 만 다르게 준다.

## 스토어에 없는 입력 (`docs/08-data-contract.md` §2.1 실측)

- `going_concern` (감사의견) — **없음**. 에이전트/SEC 파싱 영역. 계산하지 않고
  `INPUTS_UNAVAILABLE` 에 적는다. 하드 제외 적용 불가.
- `maturity_wall_24m` — **없음**. SF1 은 유동부채(`debtc`, 12개월 내)만 있다.
  `maturity_wall_12m = debtc / mcap` 을 **대용**으로 계산. 12개월 벽 ⊂ 24개월 벽이므로 0.5 초과
  제외는 건전하고(오제외 없음) 놓치는 쪽만 있다.
- `price_beta_hist` 의 상품가 — 테마 `physical_ref` 가 있고 데이터가 있을 때만. 없으면 NaN + 사유.
- `short_interest` (100% null) · 컨센서스(`estimates` 0행) · `insiders`·`institutions` (있음) —
  docs/06 이 요구하지 않으므로 쓰지 않는다. `INPUTS_UNUSED` 에 기록만 한다.

## 구현 노트 — 문서가 계산식을 비워 둔 곳 (선언이며, 데이터에 맞춰 고르지 않았다)

- `cash_runway_q` 의 "분기 FCF" — TTM FCF / 4 (4개 분기 미만이면 있는 분기 평균,
  `runway_basis_q` 에 개수). `fcf` 가 null 이면 `ncfo + capex`(capex 음수) 로 대체. 현금흐름표가
  아예 없으면(반기 보고 해외 발행사) 런웨이 NaN → **하드 필터 판정 불가로 제외**
  (`axes.hard_filters`). 근거: 광업 capex 는 분기 단위로 덩어리져 단일 분기 FCF 는 4분기 하드
  제외를 한 분기 착시로 발동시킨다. 판정 불가를 통과로 두면 생존 축의 1차 항목이 비는 종목이
  상위에 온다.
- TTM — 직전 4분기 합, 4개 전부 있고 4번째가 **300일 이내**. L1 은 400일인데, 4개 분기말의 정상
  간격은 273일이고 한 분기가 빠지면 365일이라 400일은 **한 분기 결측을 통과시킨다** (5분기 중
  4개 합 = TTM 아님). 테마 합산에서는 희석되지만 종목 런웨이에서는 25% 오차다 → 300일.
  결측 분기를 0 으로 더하지 않는다.
- 최신 분기 신선도 — `calendardate ≥ asof − 15개월` (L1 `STALE_MONTHS`). 그보다 오래되면
  "재무 없음" 으로 취급.
- `dilution_3y` — 최신 `sharesbas` 대비 36개월(±60일) 전 행의 CAGR. 행 위치(lag 12)가 아니라
  날짜로 찾는다 — 결측 분기가 있으면 위치 lag 는 기간이 틀어진다.
- `opleverage` — 12분기 QoQ ΔEBITDA_ttm 을 Δ매출_ttm 에 회귀한 기울기 `incremental_margin`
  ÷ max(abs(현재 마진), 0.05). 문서의 "ΔEBITDA% / Δ매출%" 는 EBITDA≈0 에서 발산한다. 분모
  마진을 5pp 로 바닥 처리하면 순위가 분모 잡음에 지배되지 않는다. 최소 8쌍.
- `fixed_cost_ratio` — (매출_ttm − `cor`_ttm) / 매출_ttm. 문서의 "(매출 − 변동비 추정)/매출" 에서
  변동비 = 매출원가(COGS) 로 둔 회계 분해.
- `margin_headroom` 의 "섹터 자기이력 P75" — 테마 구성원 Σebitda_ttm/Σrevenue_ttm 의 분기
  시계열(최근 40분기, 분기당 구성원 ≥ 2) 의 P75. 시계열 < 12분기면 NaN. "섹터" = 테마. 최초
  보고분으로 만든 시계열이라 PIT 와 합치.
- `marginal_producer` — 현재 EBITDA 마진이 테마 **상장** 구성원(매출 > 0) 의 하위 25%. 문서
  그대로. 횡단면이라 PIT 불필요. 매출 있는 구성원이 4개 미만이면 NA — 사분위는 관측 4개
  미만에서 정의되지 않는다.
- `price_beta_hist` — 참조가격의 최근 10년 저점 → 그 후 고점(≥ 12개월 떨어진) 구간에서
  (EBITDA_ttm 변화 / 저점 시 매출_ttm) ÷ log(P_고점/P_저점). "EBITDA 의 %변화" 는 적자에서
  정의되지 않아 매출로 정규화(마진 pp / 가격 100%). 표본 1 사이클.
- `rs_rating` — 0.4·r3m + 0.2·r6m + 0.2·r9m + 0.2·r12m 의 전체 유니버스 백분위 (1~99).
  IBD 공표 방식(최근 분기 2배 가중).
- `rvol_expansion` — 20일 평균 거래량 / 50일 평균 거래량. 1 초과 = 최근 거래량 확장.
- `vcp_base` — 최근 252일 · 피벗 좌우 5일 · 마지막 수축 ≤ 4개 중 2개 이상이고 수축폭이 단조
  감소, 10일 평균 거래량 < 50일 평균 (dry-up). L1 `vcp_index_score` 와 같은 피벗 파라미터.
  **결함이 있다 — 폭락 중에도 True 가 나온다** (`docs/06` §4·§8.2 · `test_l4_features.py`
  `test_vcp_base_characterization_*`). 고치려면 새 임계가 필요해 고치지 않았다. M 축은 어떤
  결정에도 쓰이지 않으므로 실피해는 0 이다 (`docs/06` §6.1).
- **관찰용 열 — 아무 로직도 읽지 않는다**: `from_52w_high` · `sma200_up_1m` · `m_n_inputs`.
  `from_52w_high`·`sma200_up_1m` 은 `stage2` 안에서 **다시 계산**되어 쓰이고, 열 자체는 리포트·
  진단용이다. 지우지 않는 이유는 `vcp_base` 결함의 재현·진단에 이 열들이 필요하기 때문이다
  (`from_52w_high` 는 "지금 고점 대비 어디인가" 를 이미 담고 있다).
- 상장 판정 — asof 이전 10거래일(SPY 달력) 안에 가격 행이 있음. 폐지·거래정지는 제외하고
  **수를 보고**.
- `fund_status` — `ok`(15개월 내 분기 있음) / `stale`(분기는 있으나 오래됨) / `none`(SF1 에
  행이 0개 — 실측: SBSW·SQM·BVN 같은 20-F 해외발행사). 둘 다 하드 필터 판정 불가로 제외하되
  사유를 구분한다 — 전자는 데이터 갱신, 후자는 데이터 소스의 문제라 할 일이 다르다.
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

from msa.config import paths
from msa.data import pit
from msa.data.store import Store, StoreError
from msa.dates import months_between
from msa.l1.physical import PhysicalSeries, load_ref
from msa.l1.scoreboard import xs_pct
from msa.status import FundStatus
from msa.themes import MEMBER_META_MIN_ROWS, Membership, Theme
from msa.vendor.redflags import FINANCIAL_SECTORS, AnnualRow, detect_red_flags
from msa.vendor.vcp import build_contractions, compress_pivots, find_pivots

log = logging.getLogger(__name__)

TTM_MAX_SPAN_DAYS = 300  # L1 은 400 — 아래 구현 노트
STALE_MONTHS = 15
LISTED_WINDOW_TD = 10
PRICE_LOOKBACK_DAYS = 430  # 252 거래일 + 여유
#: 재무 질의 하한 — 가장 긴 창(마진 자기이력 40분기 + TTM 3분기 + 참조가 10년 저점 ±95일)을 덮는다.
#: `datekey ≥ calendardate` 이므로 11년은 위 창의 어느 행도 자르지 않는다. `fund_status` 의
#: "없음/오래됨" 판정은 이 하한과 무관하게 별도 distinct 질의로 센다 (`_sf1_covered`).
FUND_LOOKBACK_YEARS = 11
MARGIN_HIST_QUARTERS = 40
MARGIN_HIST_MIN_QUARTERS = 12
MARGIN_HIST_MIN_MEMBERS = 2
MARGINAL_MIN_N = 4  # 사분위는 관측 4개 미만에서 정의되지 않는다
REG_QUARTERS = 12
REG_MIN_PAIRS = 8
OPLEV_MARGIN_FLOOR = 0.05
DILUTION_TOL_DAYS = 60
BETA_LOOKBACK_YEARS = 10
BETA_MIN_UPTURN_MONTHS = 12
RS_WEIGHTS: tuple[tuple[int, float], ...] = ((63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2))

FUND_FIELDS = (
    "revenue",
    "ebitda",
    "ebit",
    "opinc",
    "netinc",
    "ncfo",
    "fcf",
    "capex",
    "intexp",
    "cor",
    "cashneq",
    "debt",
    "debtc",
    "equity",
    "sharesbas",
)
TTM_FIELDS = ("revenue", "ebitda", "ebit", "opinc", "netinc", "ncfo", "fcf_q", "intexp", "cor")

#: 문서가 요구하지만 스토어에 없는 입력 → 사유. 리포트와 meta.json 에 그대로 실린다.
INPUTS_UNAVAILABLE: dict[str, str] = {
    "going_concern": (
        "감사의견은 스토어에 없다 (에이전트/SEC 파싱 영역). 하드 제외를 적용하지 못했다"
    ),
    "maturity_wall_24m": (
        "SF1 에 24개월 만기 스케줄이 없다. 유동부채 debtc(12개월 내)/시총 을 대용으로 썼다 — "
        "0.5 초과 제외는 건전하나(12m ⊂ 24m) 13~24개월 벽은 놓친다"
    ),
    "partial_capital_impairment": "레드플래그 — SF1 에 자본금(capital_stock) 이 없다",
}

#: 스토어에 있으나 docs/06 이 요구하지 않아 쓰지 않는 것 (기록).
INPUTS_UNUSED: dict[str, str] = {
    "short_interest": "prices.short_interest 는 100% null (docs/08 §2.1 #11)",
    "estimates": "0행 — 컨센서스 없음 (docs/08 §2.1 #12)",
    "insiders": "insider_net_shares 있음 — docs/06 이 요구하지 않아 미사용",
    "institutions": "inst_holders/inst_shares 있음 — docs/06 이 요구하지 않아 미사용",
}

#: 특성 표의 열 (리포트·CSV 순서의 정본).
FEATURE_COLUMNS: tuple[str, ...] = (
    "name",
    "price",
    "mcap",
    "last_price_date",
    "fund_calendardate",
    "fund_datekey",
    "fund_status",
    # S
    "cash",
    "fcf_ttm",
    "runway_basis_q",
    "cash_runway_q",
    "net_debt",
    "ebitda_ttm",
    "net_debt_ebitda",
    "nd_basis",
    "debtc",
    "maturity_wall_12m",
    "ebit_ttm",
    "intexp_ttm",
    "interest_coverage",
    "shares",
    "shares_3y_ago",
    "dilution_3y",
    "adv20_usd",
    "red_flags",
    "sector",
    "n_red_flags",
    # T
    "revenue_ttm",
    "ebitda_margin",
    "margin_headroom",
    "incremental_margin",
    "opleverage",
    "reg_pairs",
    "fixed_cost_ratio",
    "price_beta_hist",
    "equity_leverage",
    "marginal_producer",
    # M
    "stage2",
    "rs_rating",
    "vcp_base",
    "from_52w_low",
    "from_52w_high",
    "above_50d",
    "rvol_expansion",
    "sma200_up_1m",
)

#: L5 입력(`picks.csv`)으로 내보낼 때 읽는 특성 이름 — `msa.pipeline.assemble` 이 쓴다.
#: `price` = asof 이하 마지막 **비조정** 종가(`closeunadj`; 계획 기준가), `adv20_usd` = 20일 평균
#: 달러 거래대금(C4 유동성) — **조정** 종가 × 조정 거래량이다. 종목 고유 변동성·밸류 회복가·
#: 직전 고점가는 이 표에 **없다**.
ENTRY_PRICE_FEATURE = "price"
LIQUIDITY_FEATURE = "adv20_usd"

#: `price_features` 가 만들고 특성 표로 그대로 옮기는 열.
PRICE_FEATURE_COLUMNS: tuple[str, ...] = (
    "price",
    "mcap",
    "last_price_date",
    "adv20_usd",
    "stage2",
    "vcp_base",
    "from_52w_low",
    "from_52w_high",
    "above_50d",
    "rvol_expansion",
    "sma200_up_1m",
)

#: ticker → 그 ticker 의 분기 행 (`qt` 의 부분 프레임, 원래 순서). `_by_ticker` 로 한 번 만든다.
ByTicker = Mapping[str, pd.DataFrame]


@dataclass(frozen=True)
class FeatureSet:
    """테마 한 개의 종목 특성. `frame` 은 **상장** 구성원만, `universe` 는 전 구성원."""

    theme: str
    asof: pd.Timestamp
    store_end: pd.Timestamp
    frame: pd.DataFrame  # index ticker — FEATURE_COLUMNS
    universe: pd.DataFrame  # index ticker — is_delisted, listed, last_price_date, name
    theme_stats: dict[str, Any] = field(default_factory=dict)
    inputs_unavailable: dict[str, str] = field(default_factory=dict)

    @property
    def n_members(self) -> int:
        return len(self.universe)

    @property
    def n_listed(self) -> int:
        return int(self.universe["listed"].sum())


# ---------------------------------------------------------------- PIT 재무 (순수 함수)


def pit_quarterly(fund: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """`datekey ≤ asof` · ARQ · 같은 `calendardate` 는 최초 보고분만 (`msa.data.pit`)."""
    return pit.pit_quarterly(fund, asof)


def add_ttm(q: pd.DataFrame, fields: tuple[str, ...] = TTM_FIELDS) -> pd.DataFrame:
    """분기 표에 `<field>_ttm` 을 붙인다 — 4개 분기 전부 있고 4번째가 300일 이내일 때만.

    `fcf_q` 는 `fcf` 가 결측이면 `ncfo + capex` 로 대체한 분기 FCF 다 (L4 고유) — 그 뒤의 TTM 은
    `msa.data.pit.add_ttm(span_days=TTM_MAX_SPAN_DAYS)` 다.
    """
    out = q.copy()
    if "fcf" in out.columns:
        alt = out["ncfo"] + out["capex"] if {"ncfo", "capex"} <= set(out.columns) else np.nan
        out["fcf_q"] = out["fcf"].where(out["fcf"].notna(), alt)
    else:
        out["fcf_q"] = np.nan
    return pit.add_ttm(out, fields, span_days=TTM_MAX_SPAN_DAYS)


def latest_rows(qt: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """ticker 별 최신 분기(신선도 15개월 이내). index ticker."""
    return pit.latest_fresh_rows(qt, asof, stale_months=STALE_MONTHS)


def _by_ticker(qt: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """ticker → 분기 부분 프레임. 종목별 도우미들이 전체 표를 매번 마스킹하지 않게 한 번 만든다."""
    return {str(k): g for k, g in qt.groupby("ticker", sort=False)}


def _row_near(tq: pd.DataFrame, target: pd.Timestamp, tol_days: int) -> pd.Series | None:
    d = (tq["calendardate"] - target).abs()
    if d.empty:
        return None
    i = d.idxmin()
    if d.loc[i] > pd.Timedelta(days=tol_days):
        return None
    row = tq.loc[i]
    assert isinstance(row, pd.Series)
    return row


def dilution_3y(
    qt: pd.DataFrame, latest: pd.DataFrame, *, by_tk: ByTicker | None = None
) -> pd.DataFrame:
    """주식수 3년 CAGR. 36개월(±60일) 전 행을 날짜로 찾는다.

    열: shares, shares_3y_ago, dilution_3y."""
    by_tk = _by_ticker(qt) if by_tk is None else by_tk
    rows: dict[str, dict[str, float]] = {}
    for tk, cur in latest.iterrows():
        tq = by_tk[str(tk)]
        prev = _row_near(tq, cur["calendardate"] - pd.DateOffset(months=36), DILUTION_TOL_DAYS)
        s1 = float(cur["sharesbas"]) if pd.notna(cur.get("sharesbas")) else np.nan
        s0 = (
            float(prev["sharesbas"])
            if prev is not None and pd.notna(prev.get("sharesbas"))
            else np.nan
        )
        cagr = (s1 / s0) ** (1 / 3) - 1 if (s0 and s0 > 0 and s1 > 0) else np.nan
        rows[str(tk)] = {"shares": s1, "shares_3y_ago": s0, "dilution_3y": cagr}
    return pd.DataFrame.from_dict(rows, orient="index")


def regression_features(
    qt: pd.DataFrame, latest: pd.DataFrame, *, by_tk: ByTicker | None = None
) -> pd.DataFrame:
    """12분기 QoQ ΔEBITDA_ttm ~ Δrevenue_ttm 회귀 기울기(`incremental_margin`)와 `opleverage`."""
    by_tk = _by_ticker(qt) if by_tk is None else by_tk
    rows: dict[str, dict[str, float]] = {}
    for tk, cur in latest.iterrows():
        tq = by_tk[str(tk)][["calendardate", "revenue_ttm", "ebitda_ttm"]].tail(REG_QUARTERS + 1)
        d = tq[["revenue_ttm", "ebitda_ttm"]].diff().dropna()
        b = np.nan
        if len(d) >= REG_MIN_PAIRS:
            x = d["revenue_ttm"].to_numpy(dtype=float)
            y = d["ebitda_ttm"].to_numpy(dtype=float)
            vx = float(np.var(x))
            # 완전 선형(차분이 상수)이면 분산이 부동소수 잡음뿐 — 기울기를 만들지 않는다
            if vx > 1e-10 * float(np.mean(np.abs(x))) ** 2 and vx > 0:
                b = float(np.cov(x, y, bias=True)[0, 1] / vx)
        rev = cur.get("revenue_ttm")
        eb = cur.get("ebitda_ttm")
        margin = float(eb) / float(rev) if pd.notna(rev) and pd.notna(eb) and rev > 0 else np.nan
        oplev = b / max(abs(margin), OPLEV_MARGIN_FLOOR) if not math.isnan(b) else np.nan
        if math.isnan(margin) and not math.isnan(b):
            oplev = b / OPLEV_MARGIN_FLOOR
        rows[str(tk)] = {"incremental_margin": b, "opleverage": oplev, "reg_pairs": float(len(d))}
    return pd.DataFrame.from_dict(rows, orient="index")


def theme_margin_history(qt: pd.DataFrame, asof: pd.Timestamp) -> pd.Series:
    """테마 Σebitda_ttm / Σrevenue_ttm 분기 시계열 (최근 40분기, 분기당 구성원 ≥ 2)."""
    ok = qt.loc[(qt["revenue_ttm"] > 0) & qt["ebitda_ttm"].notna()]
    ok = ok.loc[
        ok["calendardate"] > pd.Timestamp(asof) - pd.DateOffset(months=3 * MARGIN_HIST_QUARTERS)
    ]
    if ok.empty:
        return pd.Series(dtype=float)
    g = ok.groupby("calendardate")
    agg = pd.DataFrame({"e": g["ebitda_ttm"].sum(), "r": g["revenue_ttm"].sum(), "n": g.size()})
    agg = agg.loc[agg["n"] >= MARGIN_HIST_MIN_MEMBERS]
    s: pd.Series = (agg["e"] / agg["r"]).sort_index()
    return s


def annual_rows_for(
    qt: pd.DataFrame, ticker: str, latest_cd: pd.Timestamp, *, by_tk: ByTicker | None = None
) -> list[AnnualRow]:
    """레드플래그 입력 — TTM 을 12개월 간격(±60일)으로 최대 4개 뽑아 '연도' 행으로 만든다."""
    tq = by_tk[ticker] if by_tk is not None else qt.loc[qt["ticker"] == ticker]
    out: list[AnnualRow] = []
    for k in range(3, -1, -1):
        r = _row_near(tq, latest_cd - pd.DateOffset(months=12 * k), DILUTION_TOL_DAYS)
        if r is None:
            continue

        def _v(col: str, r: pd.Series = r) -> float | None:
            v = r.get(col)
            return None if v is None or pd.isna(v) else float(v)

        out.append(
            AnnualRow(
                year=int(r["calendardate"].year),
                total_equity=_v("equity"),
                operating_income=_v("opinc_ttm"),
                net_income=_v("netinc_ttm"),
                operating_cash_flow=_v("ncfo_ttm"),
                interest_expense=_v("intexp_ttm"),
            )
        )
    return out


def fundamental_features(
    qt: pd.DataFrame,
    asof: pd.Timestamp,
    mcap: pd.Series,
    *,
    sectors: pd.Series | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """S·T 축의 재무 특성. `qt` 는 `add_ttm(pit_quarterly(...))`. `mcap` 은 ticker → 달러 시총.

    반환: (index ticker 표, 테마 통계 dict). 최신 분기가 없는(신선도 탈락) 종목은 표에 **없다** —
    호출자(`picks`)가 "재무 없음" 으로 제외 사유를 적는다.
    """
    latest = latest_rows(qt, asof)
    by_tk = _by_ticker(qt)
    stats: dict[str, Any] = {}
    hist = theme_margin_history(qt, asof)
    stats["margin_hist_quarters"] = len(hist)
    p75 = float(hist.quantile(0.75)) if len(hist) >= MARGIN_HIST_MIN_QUARTERS else np.nan
    stats["theme_margin_p75"] = p75
    if latest.empty:
        return pd.DataFrame(columns=list(FEATURE_COLUMNS)), stats

    f = pd.DataFrame(index=latest.index)
    f["fund_calendardate"] = latest["calendardate"].dt.date
    f["fund_datekey"] = latest["datekey"].dt.date
    f["mcap"] = mcap.reindex(f.index)
    f["cash"] = latest["cashneq"]
    f["revenue_ttm"] = latest["revenue_ttm"]
    f["ebitda_ttm"] = latest["ebitda_ttm"]
    f["ebit_ttm"] = latest["ebit_ttm"]
    f["intexp_ttm"] = latest["intexp_ttm"]
    f["debtc"] = latest["debtc"]

    # 런웨이 — TTM FCF / 4, 4분기 미만이면 있는 분기 평균
    fcf_ttm = latest["fcf_q_ttm"].copy()
    basis = pd.Series(4.0, index=f.index).where(fcf_ttm.notna(), np.nan)
    if fcf_ttm.isna().any():
        g4 = qt.groupby("ticker", sort=False).tail(4).groupby("ticker", sort=False)["fcf_q"]
        n_q = g4.count().astype(float)
        mean_q = g4.mean()
        fill = fcf_ttm.isna()
        fcf_ttm.loc[fill] = (mean_q.reindex(f.index) * 4).loc[fill]
        basis.loc[fill] = n_q.reindex(f.index).loc[fill].where(lambda s: s > 0, np.nan)
    f["fcf_ttm"] = fcf_ttm
    f["runway_basis_q"] = basis
    burn_q = (-fcf_ttm / 4).clip(lower=0)
    runway = pd.Series(np.inf, index=f.index)
    runway = runway.where(burn_q <= 0, f["cash"] / burn_q)
    runway = runway.where(f["cash"].notna() & fcf_ttm.notna(), np.nan)
    f["cash_runway_q"] = runway

    # 순부채 / EBITDA (EBITDA ≤ 0 이면 순부채 / 시총)
    nd = latest["debt"] - latest["cashneq"]
    f["net_debt"] = nd
    # **적자와 결측을 구분한다.** `ebitda_ttm > 0` 은 NaN 에서도 False 라, 예전에는 EBITDA 가
    # 아예 없는 종목이 "적자" 와 같은 경로로 들어가 리포트에 "적자 대체" 로 찍혔다.
    # 2026-08-25 실측: GSL·CMRE 는 최신 분기 `ebitda` 가 NULL 일 뿐 **크게 흑자**다
    # (GSL 직전 3분기 EBITDA 130~139M · TTM EBIT 420M). 사람이 표를 보고 흑자 기업을
    # 적자로 판단할 수 있었다. 판정은 세 경우 모두 같다(시총 기준) — 바뀌는 것은 **표시**다.
    eb = latest["ebitda_ttm"]
    eb_pos = eb > 0
    eb_missing = eb.isna()
    f["net_debt_ebitda"] = (nd / eb).where(eb_pos, nd / f["mcap"])
    f["nd_basis"] = pd.Series(
        np.where(eb_pos, "ebitda", np.where(eb_missing, "mcap_missing", "mcap_nonpos")),
        index=f.index,
    )
    f.loc[f["net_debt_ebitda"].isna(), "nd_basis"] = "n/a"
    f["maturity_wall_12m"] = latest["debtc"] / f["mcap"]
    ic = latest["ebit_ttm"] / latest["intexp_ttm"]
    f["interest_coverage"] = ic.where(latest["intexp_ttm"] > 0, np.nan)

    f = f.join(dilution_3y(qt, latest, by_tk=by_tk))

    # 레드플래그 (벤더링)
    flags: dict[str, str] = {}
    nflags: dict[str, int] = {}
    for tk in f.index:
        sec = str(sectors.get(tk, "")) if sectors is not None else ""
        rows = annual_rows_for(qt, str(tk), latest.loc[tk, "calendardate"], by_tk=by_tk)
        fl = detect_red_flags(rows, financial=sec in FINANCIAL_SECTORS)
        flags[str(tk)] = ";".join(x.key for x in fl)
        nflags[str(tk)] = len(fl)
    f["red_flags"] = pd.Series(flags)
    f["n_red_flags"] = pd.Series(nflags)
    # 섹터를 특성 표에 남긴다 — 지금까지 레드플래그 계산에만 쓰고 버렸다. 하드 필터가
    # "이 업종에는 이 비율이 정의되지 않는다" 를 판단하려면 여기까지 와야 한다
    # (`axes.FILTER_UNAPPLIED_SECTORS`, 2026-08-26).
    f["sector"] = (
        pd.Series({str(tk): str(sectors.get(tk, "")) for tk in f.index})
        if sectors is not None
        else pd.Series("", index=f.index)
    )

    # T
    margin = (latest["ebitda_ttm"] / latest["revenue_ttm"]).where(latest["revenue_ttm"] > 0)
    f["ebitda_margin"] = margin
    f["margin_headroom"] = p75 - margin
    f = f.join(regression_features(qt, latest, by_tk=by_tk))
    f["fixed_cost_ratio"] = (
        (latest["revenue_ttm"] - latest["cor_ttm"]) / latest["revenue_ttm"]
    ).where(latest["revenue_ttm"] > 0)
    f["equity_leverage"] = ((nd + f["mcap"]) / f["mcap"]).where(f["mcap"] > 0)
    xs = margin.dropna()
    p25 = float(xs.quantile(0.25)) if len(xs) >= MARGINAL_MIN_N else np.nan
    stats["theme_margin_p25_xs"] = p25
    stats["theme_margin_n_xs"] = len(xs)
    mp = pd.Series(pd.NA, index=f.index, dtype="boolean")
    if not math.isnan(p25):
        mp = pd.Series(margin <= p25, index=f.index, dtype="boolean").where(margin.notna(), pd.NA)
    f["marginal_producer"] = mp
    return f, stats


# ---------------------------------------------------------------- 상품가 탄력성


def price_beta_hist(
    qt: pd.DataFrame, ref: pd.Series, asof: pd.Timestamp
) -> tuple[pd.Series, dict[str, Any]]:
    """직전 상승 국면(10년 저점 → 그 후 고점)에서의 EBITDA 변화(매출 정규화) / log 가격 변화."""
    s = ref.dropna().sort_index()
    s = s.loc[
        (s.index > pd.Timestamp(asof) - pd.DateOffset(years=BETA_LOOKBACK_YEARS))
        & (s.index <= asof)
    ]
    info: dict[str, Any] = {"status": "n/a"}
    if len(s) < 24:
        info["reason"] = f"참조 시계열 {len(s)}개월 — 24개월 미만"
        return pd.Series(dtype=float), info
    t0 = pd.Timestamp(s.idxmin())
    after = s.loc[t0:]
    t1 = pd.Timestamp(after.idxmax())
    months = months_between(t0, t1)
    info.update({"trough": str(t0.date()), "peak": str(t1.date()), "months": int(months)})
    if months < BETA_MIN_UPTURN_MONTHS:
        info["reason"] = f"상승 국면 {months}개월 — {BETA_MIN_UPTURN_MONTHS}개월 미만"
        return pd.Series(dtype=float), info
    dlogp = math.log(float(s.loc[t1]) / float(s.loc[t0]))
    out: dict[str, float] = {}
    for tk, tq in qt.groupby("ticker"):
        r0 = _row_near(tq, pd.Timestamp(t0), 95)
        r1 = _row_near(tq, pd.Timestamp(t1), 95)
        if r0 is None or r1 is None:
            out[str(tk)] = np.nan
            continue
        e0, e1, rev0 = r0.get("ebitda_ttm"), r1.get("ebitda_ttm"), r0.get("revenue_ttm")
        if pd.isna(e0) or pd.isna(e1) or pd.isna(rev0) or rev0 <= 0 or dlogp <= 0:
            out[str(tk)] = np.nan
            continue
        out[str(tk)] = float((e1 - e0) / rev0 / dlogp)
    info["status"] = "ok"
    return pd.Series(out, dtype=float), info


def load_reference_series(theme: Theme, *, allow_fetch: bool) -> PhysicalSeries | None:
    """테마 `physical_ref` 를 월말 시계열로. 없으면 None.

    `kind` 가 price 가 아니어도 쓰되 기록한다."""
    ref = theme.physical_ref
    if ref is None:
        return None
    return load_ref(ref, allow_fetch=allow_fetch)


# ---------------------------------------------------------------- 가격 특성 (순수 함수)


def _nanmean(seg: np.ndarray) -> float:
    """`pd.Series(seg).mean()` 과 같은 산술 — NaN 을 0 으로 치환한 numpy 합 / 유효 개수.

    groupby·rolling·reduceat 의 합은 누적 순서가 달라 마지막 비트가 어긋난다 (테스트가 잰다).
    pandas `nanmean` 이 (bottleneck 없이) 하는 계산을 그대로 적었다 — 비어 있으면 NaN.
    """
    m = np.isnan(seg)
    cnt = seg.size - int(m.sum())
    if cnt == 0:
        return float("nan")
    return float(np.where(m, 0.0, seg).sum() / cnt)


def _nan_minmax(seg: np.ndarray) -> tuple[float, float]:
    ok = seg[~np.isnan(seg)]
    return (float(ok.min()), float(ok.max())) if ok.size else (np.nan, np.nan)


def price_features(px: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """종목별 가격 특성. `px` 열: ticker, date, close(조정), closeunadj, volume, mcap.

    반환 index ticker(오름차순): `PRICE_FEATURE_COLUMNS`. 종목별 루프는 numpy 슬라이스만 만진다
    (프레임 마스킹·Series 생성 없음) — 값은 종목별 `Series.tail(k).mean()` 과 비트 단위로 같다.
    """
    p = px.assign(date=pd.to_datetime(px["date"]))
    p = p.loc[p["date"] <= pd.Timestamp(asof)].sort_values(["ticker", "date"])
    t = p.groupby("ticker", sort=True).tail(252)
    tk = t["ticker"].to_numpy()
    c_all = t["close"].to_numpy(dtype=float)
    cu_all = t["closeunadj"].to_numpy(dtype=float)
    v_all = t["volume"].to_numpy(dtype=float)
    mc_all = t["mcap"].to_numpy(dtype=float)
    dates = t["date"].to_numpy()
    bounds = np.flatnonzero(np.r_[True, tk[1:] != tk[:-1], True]) if len(tk) else np.array([0])
    cols: dict[str, list[Any]] = {k: [] for k in PRICE_FEATURE_COLUMNS}
    tickers: list[str] = []
    for a, b in pairwise(bounds):
        n = int(b - a)
        c, cu, v = c_all[a:b], cu_all[a:b], v_all[a:b]
        tickers.append(str(tk[a]))
        mc = mc_all[a:b]
        mc = mc[~np.isnan(mc)]
        cols["price"].append(float(cu[-1]))
        cols["mcap"].append(float(mc[-1]) if mc.size else np.nan)
        cols["last_price_date"].append(pd.Timestamp(dates[b - 1]).date())
        # `volume` 은 소급 분할조정 값이므로 조정 종가 `c` 와 곱해야 한다. 비조정 `cu` 와
        # 곱하면 asof 이후의 분할 계수만큼 틀리고, 그것은 미래를 보는 것이다 (2026-08-23).
        cols["adv20_usd"].append(_nanmean((c * v)[-20:]) if n >= 5 else np.nan)
        sma50 = _nanmean(c[-50:]) if n >= 50 else np.nan
        sma150 = _nanmean(c[-150:]) if n >= 150 else np.nan
        sma200 = _nanmean(c[-200:]) if n >= 200 else np.nan
        sma200_prev = _nanmean(c[-221:-21]) if n >= 221 else np.nan
        lo, hi = _nan_minmax(c) if n >= 120 else (np.nan, np.nan)
        last = float(c[-1])
        from_low = last / lo - 1 if n >= 120 else np.nan
        from_high = last / hi - 1 if n >= 120 else np.nan
        cols["from_52w_low"].append(from_low)
        cols["from_52w_high"].append(from_high)
        cols["above_50d"].append(bool(last > sma50) if n >= 50 else None)
        cols["sma200_up_1m"].append(bool(sma200 > sma200_prev) if n >= 221 else None)
        cols["stage2"].append(
            bool(
                last > sma150 > sma200
                and sma200 > sma200_prev
                and from_low >= 0.30
                and from_high >= -0.25
            )
            if n >= 221
            else None
        )
        v50 = _nanmean(v[-50:]) if n >= 50 else np.nan
        cols["rvol_expansion"].append(
            float(_nanmean(v[-20:]) / v50) if n >= 50 and v50 > 0 else np.nan
        )
        # 창 길이는 문서 선언 그대로 252 거래일이다 (`docs/06` §8.2 "252일 창"). 2026-08-24
        # 이전 코드는 `n >= 60` 이라 60봉만 있어도 계산했다 — 60봉은 252일 창이 아니고, 그
        # 숫자는 어느 문서에도 선언된 적이 없다. 새 값을 정한 것이 아니라 **선언된 값으로
        # 되돌린 것**이다 (`CLAUDE.md` §1).
        cols["vcp_base"].append(vcp_base(pd.Series(c), pd.Series(v)) if n >= 252 else None)
    out = pd.DataFrame(index=pd.Index(tickers))
    for k in ("price", "mcap", "adv20_usd", "from_52w_low", "from_52w_high", "rvol_expansion"):
        out[k] = np.asarray(cols[k], dtype=float)
    for k in ("last_price_date", "above_50d", "sma200_up_1m", "stage2", "vcp_base"):
        out[k] = pd.Series(cols[k], index=out.index, dtype=object)
    return out[list(PRICE_FEATURE_COLUMNS)]


def vcp_base(
    close: pd.Series, volume: pd.Series, *, left: int = 5, right: int = 5, max_cons: int = 4
) -> bool:
    """VCP 베이스: 수축 ≥ 2 · 수축폭 단조 감소 · 거래량 dry-up · **현재가가 베이스 안**.

    ## 2026-08-25 — 치명적 오탐을 고쳤다 (`docs/06` §4·§8.2)

    이전 판은 수축 베이스(20% → 12% → 6%) 뒤에 40봉 −40% 붕괴를 이어 붙여도 **5개 시드 전부
    True** 를 냈다. 원인은 `build_contractions(ref_level=c.max(), tol=0.10)` 이 고점 −10% 아래
    피벗 쌍을 버리는 것이었다 — 폭락 구간이 수축으로 세어지지 않고 붕괴 전의 예쁜 수축만 남는다.

    **고친 방법은 새 임계가 아니다.** 마지막 수축의 저점(`trough`)은 이 함수가 이미 계산한다.
    종가가 그 아래로 내려갔으면 **가격이 베이스에서 이탈한 것**이고, 이탈한 베이스는 정의상
    베이스가 아니다. 발명한 값이 없으므로 `CLAUDE.md` §1 에 걸리지 않는다 — 임계를 고른 것이
    아니라 선언된 개념("수축 베이스")을 그대로 구현한 것이다.

    ## 남은 한계 (표시는 유지한다)

    - **최신성 요구가 없다**: 베이스 뒤 120봉을 횡보해도, 저점을 지키는 한 True 다. 최신성
      창은 새 임계라 넣지 않았다. 다만 이탈 조건 덕분에 위험한 쪽(폭락)은 더는 통과하지 못한다.
    - **dry-up 이 임계 없는 순부등호**다 — 10일 평균이 50일 평균보다 1%만 낮아도 통과한다.

    그래서 `picks.VCP_DEFECT_NOTE` 는 계속 붙는다. M 축은 여전히 관찰 지표이고 선정에
    쓰이지 않는다 (`docs/06` §6.1).
    """
    c = close.dropna()
    piv = compress_pivots(find_pivots(c, left=left, right=right))
    cons = build_contractions(piv, ref_level=float(c.max()), tol=0.10, max_drop_from_ref=1.0)
    cons = [x for x in cons if x["depth"] > 0.0][-max_cons:]
    if len(cons) < 2:
        return False
    depths = [x["depth"] for x in cons]
    shrinking = all(depths[i] < depths[i - 1] for i in range(1, len(depths)))
    v50 = float(volume.tail(50).mean())
    dry = bool(v50 > 0 and float(volume.tail(10).mean()) < v50)
    # 마지막 수축의 저점을 잃었으면 베이스에서 이탈한 것이다 — 이탈한 베이스는 베이스가 아니다.
    # 새 임계가 아니라 위에서 이미 구한 `trough` 와의 비교다.
    in_base = float(c.iloc[-1]) >= float(cons[-1]["trough"])
    return bool(shrinking and dry and in_base)


def rs_rating_from_universe(universe_rs_raw: pd.Series) -> pd.Series:
    """전체 유니버스 RS 원값 → 1~99 백분위 (동률 평균 순위)."""
    return (xs_pct(universe_rs_raw.dropna(), +1) * 98 + 1).round().clip(1, 99)


# ---------------------------------------------------------------- 스토어 연결


def _trading_dates(store: Store, asof: pd.Timestamp) -> pd.DatetimeIndex:
    """SPY 달력 — asof 이전 430일 창. 200일 미만이면 달력이 아니다 (조용히 진행하지 않는다)."""
    spy = store.close_series(
        "SPY", start=(asof - pd.Timedelta(days=PRICE_LOOKBACK_DAYS)).date(), end=asof.date()
    )
    if len(spy) < 200:
        raise StoreError(f"SPY 달력 {len(spy)}일 — 최소 200일을 기대했다 (`CLAUDE.md` §2)")
    return pd.DatetimeIndex(spy.index)


def universe_rs(store: Store, trading_dates: pd.DatetimeIndex) -> pd.Series:
    """전체 유니버스의 RS 원값 — 5개 거래일 슬라이스만 읽는다 (45M 행 전체 스캔 아님)."""
    if len(trading_dates) < 253:
        raise StoreError(f"거래일 달력이 {len(trading_dates)}일 — RS(252일) 에 부족하다")
    d0 = trading_dates[-1]
    dates = [d0] + [trading_dates[-1 - k] for k, _ in RS_WEIGHTS]
    sql = (
        "select ticker, date, close from prices where date in (" + ",".join("?" * len(dates)) + ")"
    )
    df = store.query(sql, [d.date() for d in dates])
    if df.empty:
        raise StoreError("RS 유니버스 슬라이스가 0행이다")
    df["date"] = pd.to_datetime(df["date"])
    w = df.pivot_table(index="ticker", columns="date", values="close")
    w = w.dropna(subset=[d0])
    rs = pd.Series(0.0, index=w.index)
    for (_k, wt), dk in zip(RS_WEIGHTS, dates[1:], strict=True):
        rs = rs + wt * (w[d0] / w[dk] - 1)
    return rs.dropna()


def universe_rs_cached(
    store: Store, trading_dates: pd.DatetimeIndex, *, asof: pd.Timestamp, store_end: pd.Timestamp
) -> pd.Series:
    """`universe_rs` 를 `state/cache/rs_universe_<asof>_<store_end>.parquet` 에 메모한다.

    같은 asof 로 여러 테마를 돌릴 때 유니버스 슬라이스를 테마마다 다시 읽지 않기 위한 것이다.
    키는 (asof, 스토어 최종일) — 스토어가 갱신되면 최종일이 바뀌어 캐시가 비껴간다.
    쓰기는 임시 파일 + `os.replace` 다. 백테스트가 테마별 프로세스로 병렬로 도는데 같은 asof 를
    여러 워커가 동시에 만나므로, 직접 쓰면 반쯤 쓰인 parquet 을 다른 워커가 읽을 수 있다.
    """
    path = paths().cache / f"rs_universe_{asof.date()}_{store_end.date()}.parquet"
    if path.exists():
        return pd.read_parquet(path)["rs"]
    rs = universe_rs(store, trading_dates)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    rs.rename("rs").to_frame().to_parquet(tmp)
    os.replace(tmp, path)
    return rs


def _sf1_covered(store: Store, tickers: list[str], asof: pd.Timestamp) -> set[str]:
    """asof 까지 SF1(ARQ) 행이 하나라도 있는 종목 — `pit_quarterly` 의 필터와 같은 조건.

    재무 질의를 `FUND_LOOKBACK_YEARS` 로 자르기 때문에 "행 0개(none)" 와 "오래됨(stale)" 의 구분은
    하한 없는 이 질의로 센다.
    """
    sql = (
        "select distinct ticker from fundamentals where dimension = 'ARQ' and datekey <= ? "
        "and calendardate is not null and ticker in (" + ",".join("?" * len(tickers)) + ")"
    )
    df = store.query(sql, [asof.date(), *tickers])
    return set(df["ticker"].astype(str))


def build_features(
    store: Store,
    theme: Theme,
    membership: Membership,
    asof: pd.Timestamp | str | None = None,
    *,
    allow_fetch: bool = True,
    with_physical: bool = True,
) -> FeatureSet:
    """스토어에서 테마 구성원의 특성 표를 만든다. `asof` 기본 = 스토어 최종일.

    티커 메타는 `membership.meta`(배정에 쓴 것) 를 다시 쓴다 — 비어 있을 때만 스토어를 읽는다.
    """
    se = store.store_end()
    store_end = pd.Timestamp(se) if se else pd.Timestamp.today().normalize()
    asof_ts = min(pd.Timestamp(asof), store_end) if asof else store_end
    members = membership.members(theme.id)
    if not members:
        raise StoreError(f"{theme.id}: 구성원이 0개다")
    mf = membership.frame.set_index("ticker").reindex(members)
    meta_src = (
        membership.meta
        if len(membership.meta)
        else store.tickers_meta(min_rows=MEMBER_META_MIN_ROWS)
    )
    meta = meta_src.set_index("ticker")
    names = meta["name"].reindex(members)
    sectors = meta["sector"].reindex(members)

    td = _trading_dates(store, asof_ts)
    cutoff = td[-LISTED_WINDOW_TD] if len(td) >= LISTED_WINDOW_TD else td[0]
    px = store.prices(
        members,
        start=(asof_ts - pd.Timedelta(days=PRICE_LOOKBACK_DAYS)).date(),
        end=asof_ts.date(),
        min_rows=0,
        columns=["ticker", "date", "close", "closeunadj", "volume", "mcap"],
    )
    pf = price_features(px, asof_ts) if not px.empty else pd.DataFrame()
    universe = pd.DataFrame(index=pd.Index(members, name="ticker"))
    universe["name"] = names
    universe["is_delisted"] = mf["is_delisted"].reindex(members).fillna("N")
    universe["last_price_date"] = pf["last_price_date"].reindex(members) if not pf.empty else None
    lp = pd.to_datetime(universe["last_price_date"])
    universe["listed"] = lp.notna() & (lp >= cutoff)
    listed = universe.index[universe["listed"]].tolist()
    log.info(
        "%s: 구성원 %d · 상장 %d · 폐지/가격없음 %d (기준 %s)",
        theme.id,
        len(members),
        len(listed),
        len(members) - len(listed),
        cutoff.date(),
    )
    inputs_unavailable = dict(INPUTS_UNAVAILABLE)
    stats: dict[str, Any] = {"listed_cutoff": str(cutoff.date())}
    if not listed:
        frame = pd.DataFrame(columns=list(FEATURE_COLUMNS))
        return FeatureSet(theme.id, asof_ts, store_end, frame, universe, stats, inputs_unavailable)
    # 상장 종목이 있으면 가격 표도 비어 있지 않다 (상장 판정이 가격 행에서 나온다)

    # RS — 전체 유니버스 백분위 (asof·스토어 최종일 키로 메모)
    rs_u = universe_rs_cached(store, td, asof=asof_ts, store_end=store_end)
    rs_rating = rs_rating_from_universe(rs_u)
    stats["rs_universe_n"] = len(rs_u)

    # 재무 — PIT. 하한 11년(`FUND_LOOKBACK_YEARS`) · "행 0개" 판정은 하한 없는 distinct 질의
    fund = store.fundamentals(
        listed,
        fields=list(FUND_FIELDS),
        start=(asof_ts - pd.DateOffset(years=FUND_LOOKBACK_YEARS)).date(),
        end=asof_ts.date(),
        min_rows=0,
        date_column="datekey",
    )
    qt = (
        add_ttm(pit_quarterly(fund, asof_ts))
        if not fund.empty
        else pd.DataFrame(columns=["ticker", "calendardate", "datekey", *FUND_FIELDS])
    )
    covered = _sf1_covered(store, listed, asof_ts)
    mcap = pf["mcap"].reindex(listed)
    ff, fstats = (
        fundamental_features(qt, asof_ts, mcap, sectors=sectors)
        if len(qt)
        else (pd.DataFrame(), {})
    )
    stats.update(fstats)

    # 상품가 탄력성
    beta_info: dict[str, Any] = {"status": "n/a"}
    beta = pd.Series(np.nan, index=pd.Index(listed))
    if with_physical and len(qt):
        ref = load_reference_series(theme, allow_fetch=allow_fetch)
        if ref is None:
            beta_info = {"status": "not_declared", "reason": "themes.yaml 에 physical_ref 없음"}
        elif ref.status != "ok" or ref.series is None:
            beta_info = {"status": "missing", "reason": f"{ref.source}:{ref.symbol} — {ref.note}"}
        else:
            b, beta_info = price_beta_hist(qt, ref.series, asof_ts)
            beta_info["ref"] = f"{ref.source}:{ref.symbol} ({ref.kind})"
            beta = b.reindex(listed)
    elif not with_physical:
        beta_info = {"status": "skipped", "reason": "--no-physical"}
    if beta_info.get("status") != "ok":
        inputs_unavailable["price_beta_hist"] = str(beta_info.get("reason", beta_info["status"]))
    stats["price_beta_hist"] = beta_info

    frame = pd.DataFrame({"name": names.reindex(listed)}, index=pd.Index(listed, name="ticker"))
    frame = frame.join(pf[list(PRICE_FEATURE_COLUMNS)])
    frame["rs_rating"] = rs_rating.reindex(listed)
    if not ff.empty:
        frame = frame.join(ff.drop(columns="mcap"))
    frame["price_beta_hist"] = beta
    ok = set(ff.index) if not ff.empty else set()
    frame["fund_status"] = [
        FundStatus.OK if t in ok else FundStatus.STALE if t in covered else FundStatus.NONE
        for t in listed
    ]
    frame = frame.reindex(columns=list(FEATURE_COLUMNS))
    return FeatureSet(theme.id, asof_ts, store_end, frame, universe, stats, inputs_unavailable)
