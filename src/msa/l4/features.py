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
- 상장 판정 — asof 이전 10거래일(SPY 달력) 안에 가격 행이 있음. 폐지·거래정지는 제외하고
  **수를 보고**.
- `fund_status` — `ok`(15개월 내 분기 있음) / `stale`(분기는 있으나 오래됨) / `none`(SF1 에
  행이 0개 — 실측: SBSW·SQM·BVN 같은 20-F 해외발행사). 둘 다 하드 필터 판정 불가로 제외하되
  사유를 구분한다 — 전자는 데이터 갱신, 후자는 데이터 소스의 문제라 할 일이 다르다.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from msa.data.store import Store, StoreError
from msa.l1.physical import PhysicalSeries, load_etf_series, load_fred_series, load_manual_series
from msa.themes import Membership, Theme
from msa.vendor.redflags import FINANCIAL_SECTORS, AnnualRow, detect_red_flags
from msa.vendor.vcp import build_contractions, compress_pivots, find_pivots

log = logging.getLogger(__name__)

TTM_MAX_SPAN_DAYS = 300  # L1 은 400 — 아래 구현 노트
STALE_MONTHS = 15
LISTED_WINDOW_TD = 10
PRICE_LOOKBACK_DAYS = 430  # 252 거래일 + 여유
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
    """`datekey ≤ asof` · ARQ · 같은 `calendardate` 는 최초 보고분만. ticker·calendardate 오름차순.

    입력 열: ticker, calendardate, datekey, dimension, + 재무 필드.
    """
    need = {"ticker", "calendardate", "datekey"}
    if missing := need - set(fund.columns):
        raise KeyError(f"fundamentals 에 없는 열: {sorted(missing)}")
    q = fund.copy()
    q["calendardate"] = pd.to_datetime(q["calendardate"])
    q["datekey"] = pd.to_datetime(q["datekey"])
    if "dimension" in q.columns:
        q = q.loc[q["dimension"] == "ARQ"]
    q = q.loc[q["datekey"] <= pd.Timestamp(asof)]
    q = q.dropna(subset=["calendardate", "datekey"])
    q = q.sort_values(["ticker", "calendardate", "datekey"])
    q = q.drop_duplicates(["ticker", "calendardate"], keep="first")
    return q.reset_index(drop=True)


def add_ttm(q: pd.DataFrame, fields: tuple[str, ...] = TTM_FIELDS) -> pd.DataFrame:
    """분기 표에 `<field>_ttm` 을 붙인다 — 4개 분기 전부 있고 4번째가 400일 이내일 때만."""
    out = q.copy()
    if "fcf" in out.columns:
        alt = out["ncfo"] + out["capex"] if {"ncfo", "capex"} <= set(out.columns) else np.nan
        out["fcf_q"] = out["fcf"].where(out["fcf"].notna(), alt)
    else:
        out["fcf_q"] = np.nan
    g = out.groupby("ticker", sort=False)
    cd3 = g["calendardate"].shift(3)
    span_ok = cd3 >= out["calendardate"] - pd.Timedelta(days=TTM_MAX_SPAN_DAYS)
    for f in fields:
        if f not in out.columns:
            out[f"{f}_ttm"] = np.nan
            continue
        s = g[f].rolling(4, min_periods=4).sum().reset_index(level=0, drop=True)
        n = g[f].rolling(4, min_periods=1).count().reset_index(level=0, drop=True)
        out[f"{f}_ttm"] = s.where((n == 4) & span_ok)
    return out


def latest_rows(qt: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """ticker 별 최신 분기(신선도 15개월 이내). index ticker."""
    last = qt.groupby("ticker", sort=False).tail(1).set_index("ticker")
    fresh = last["calendardate"] >= pd.Timestamp(asof) - pd.DateOffset(months=STALE_MONTHS)
    return last.loc[fresh]


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


def dilution_3y(qt: pd.DataFrame, latest: pd.DataFrame) -> pd.DataFrame:
    """주식수 3년 CAGR. 36개월(±60일) 전 행을 날짜로 찾는다.

    열: shares, shares_3y_ago, dilution_3y."""
    rows: dict[str, dict[str, float]] = {}
    for tk, cur in latest.iterrows():
        tq = qt.loc[qt["ticker"] == tk]
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


def regression_features(qt: pd.DataFrame, latest: pd.DataFrame) -> pd.DataFrame:
    """12분기 QoQ ΔEBITDA_ttm ~ Δrevenue_ttm 회귀 기울기(`incremental_margin`)와 `opleverage`."""
    rows: dict[str, dict[str, float]] = {}
    for tk, cur in latest.iterrows():
        tq = qt.loc[qt["ticker"] == tk, ["calendardate", "revenue_ttm", "ebitda_ttm"]].tail(
            REG_QUARTERS + 1
        )
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


def annual_rows_for(qt: pd.DataFrame, ticker: str, latest_cd: pd.Timestamp) -> list[AnnualRow]:
    """레드플래그 입력 — TTM 을 12개월 간격(±60일)으로 최대 4개 뽑아 '연도' 행으로 만든다."""
    tq = qt.loc[qt["ticker"] == ticker]
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
        g = qt.groupby("ticker")["fcf_q"]
        n_q = g.apply(lambda s: float(s.tail(4).notna().sum()))
        mean_q = g.apply(lambda s: float(s.tail(4).mean()) if s.tail(4).notna().any() else np.nan)
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
    eb_pos = latest["ebitda_ttm"] > 0
    f["net_debt_ebitda"] = (nd / latest["ebitda_ttm"]).where(eb_pos, nd / f["mcap"])
    f["nd_basis"] = pd.Series(np.where(eb_pos, "ebitda", "mcap"), index=f.index)
    f.loc[f["net_debt_ebitda"].isna(), "nd_basis"] = "n/a"
    f["maturity_wall_12m"] = latest["debtc"] / f["mcap"]
    ic = latest["ebit_ttm"] / latest["intexp_ttm"]
    f["interest_coverage"] = ic.where(latest["intexp_ttm"] > 0, np.nan)

    f = f.join(dilution_3y(qt, latest))

    # 레드플래그 (벤더링)
    flags: dict[str, str] = {}
    nflags: dict[str, int] = {}
    for tk in f.index:
        sec = str(sectors.get(tk, "")) if sectors is not None else ""
        rows = annual_rows_for(qt, str(tk), latest.loc[tk, "calendardate"])
        fl = detect_red_flags(rows, financial=sec in FINANCIAL_SECTORS)
        flags[str(tk)] = ";".join(x.key for x in fl)
        nflags[str(tk)] = len(fl)
    f["red_flags"] = pd.Series(flags)
    f["n_red_flags"] = pd.Series(nflags)

    # T
    margin = (latest["ebitda_ttm"] / latest["revenue_ttm"]).where(latest["revenue_ttm"] > 0)
    f["ebitda_margin"] = margin
    f["margin_headroom"] = p75 - margin
    f = f.join(regression_features(qt, latest))
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
        return pd.Series(np.nan, index=pd.Index([], dtype=object)), info
    t0 = pd.Timestamp(s.idxmin())
    after = s.loc[t0:]
    t1 = pd.Timestamp(after.idxmax())
    months = (t1.year - t0.year) * 12 + (t1.month - t0.month)
    info.update({"trough": str(t0.date()), "peak": str(t1.date()), "months": int(months)})
    if months < BETA_MIN_UPTURN_MONTHS:
        info["reason"] = f"상승 국면 {months}개월 — {BETA_MIN_UPTURN_MONTHS}개월 미만"
        return pd.Series(np.nan, index=pd.Index([], dtype=object)), info
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
    if ref.source == "etf":
        base = load_etf_series([ref.symbol])[ref.symbol]
    elif ref.source == "fred":
        base = load_fred_series(ref.symbol, allow_fetch=allow_fetch)
    else:
        base = load_manual_series(ref.symbol)
    return PhysicalSeries(base.symbol, base.source, ref.kind, base.status, base.series, base.note)


# ---------------------------------------------------------------- 가격 특성 (순수 함수)


def price_features(px: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """종목별 가격 특성. `px` 열: ticker, date, close(조정), closeunadj, volume, mcap.

    반환 index ticker: price, mcap, last_price_date, adv20_usd, stage2, vcp_base, from_52w_low,
    from_52w_high, above_50d, rvol_expansion, sma200_up_1m, rs_raw.
    """
    p = px.copy()
    p["date"] = pd.to_datetime(p["date"])
    p = p.loc[p["date"] <= pd.Timestamp(asof)].sort_values(["ticker", "date"])
    rows: dict[str, dict[str, Any]] = {}
    for tk, g in p.groupby("ticker", sort=True):
        rs = rs_raw(g["close"].astype(float).reset_index(drop=True))  # 253행 필요 — 자르기 전
        g = g.tail(252)
        c = g["close"].astype(float).reset_index(drop=True)
        cu = g["closeunadj"].astype(float).reset_index(drop=True)
        v = g["volume"].astype(float).reset_index(drop=True)
        n = len(c)
        last_mcap = g["mcap"].dropna()
        r: dict[str, Any] = {
            "price": float(cu.iloc[-1]) if n else np.nan,
            "mcap": float(last_mcap.iloc[-1]) if len(last_mcap) else np.nan,
            "last_price_date": g["date"].iloc[-1].date() if n else None,
            "adv20_usd": float((cu * v).tail(20).mean()) if n >= 5 else np.nan,
        }
        sma50 = c.tail(50).mean() if n >= 50 else np.nan
        sma150 = c.tail(150).mean() if n >= 150 else np.nan
        sma200 = c.tail(200).mean() if n >= 200 else np.nan
        sma200_prev = c.iloc[:-21].tail(200).mean() if n >= 221 else np.nan
        lo = c.min() if n >= 120 else np.nan
        hi = c.max() if n >= 120 else np.nan
        last = float(c.iloc[-1]) if n else np.nan
        r["from_52w_low"] = last / lo - 1 if n >= 120 else np.nan
        r["from_52w_high"] = last / hi - 1 if n >= 120 else np.nan
        r["above_50d"] = bool(last > sma50) if n >= 50 else None
        r["sma200_up_1m"] = bool(sma200 > sma200_prev) if n >= 221 else None
        r["stage2"] = (
            bool(
                last > sma150 > sma200
                and sma200 > sma200_prev
                and r["from_52w_low"] >= 0.30
                and r["from_52w_high"] >= -0.25
            )
            if n >= 221
            else None
        )
        r["rvol_expansion"] = (
            float(v.tail(20).mean() / v.tail(50).mean())
            if n >= 50 and v.tail(50).mean() > 0
            else np.nan
        )
        r["vcp_base"] = vcp_base(c, v) if n >= 60 else None
        r["rs_raw"] = rs
        rows[str(tk)] = r
    return pd.DataFrame.from_dict(rows, orient="index")


def rs_raw(c: pd.Series) -> float:
    """IBD 식 가중 수익률 — 252거래일 이력이 없으면 NaN."""
    n = len(c)
    if n < 253:
        return float("nan")
    last = float(c.iloc[-1])
    return float(sum(w * (last / float(c.iloc[-1 - k]) - 1) for k, w in RS_WEIGHTS))


def vcp_base(
    close: pd.Series, volume: pd.Series, *, left: int = 5, right: int = 5, max_cons: int = 4
) -> bool:
    """VCP 베이스: 수축 ≥ 2 · 수축폭 단조 감소 · 거래량 dry-up (10일 < 50일)."""
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
    return bool(shrinking and dry)


def rs_rating_from_universe(universe_rs_raw: pd.Series) -> pd.Series:
    """전체 유니버스 `rs_raw` → 1~99 백분위."""
    s = universe_rs_raw.dropna()
    pct = s.rank(pct=True, method="average")
    return (pct * 98 + 1).round().clip(1, 99)


# ---------------------------------------------------------------- 스토어 연결


def _trading_dates(store: Store, asof: pd.Timestamp) -> pd.DatetimeIndex:
    spy = store.prices(
        ["SPY"],
        start=(asof - pd.Timedelta(days=PRICE_LOOKBACK_DAYS)).date(),
        end=asof.date(),
        min_rows=200,
    )
    return pd.DatetimeIndex(pd.to_datetime(spy["date"])).sort_values()


def universe_rs(store: Store, trading_dates: pd.DatetimeIndex) -> pd.Series:
    """전체 유니버스의 RS 원값 — 5개 거래일 슬라이스만 읽는다 (45M 행 전체 스캔 아님)."""
    if len(trading_dates) < 253:
        raise StoreError(f"거래일 달력이 {len(trading_dates)}일 — RS(252일) 에 부족하다")
    d0 = trading_dates[-1]
    dates = [d0] + [trading_dates[-1 - k] for k, _ in RS_WEIGHTS]
    sql = (
        "select ticker, date, close from prices where date in (" + ",".join("?" * len(dates)) + ")"
    )
    df = store._df(sql, [d.date() for d in dates])
    if df.empty:
        raise StoreError("RS 유니버스 슬라이스가 0행이다")
    df["date"] = pd.to_datetime(df["date"])
    w = df.pivot_table(index="ticker", columns="date", values="close")
    w = w.dropna(subset=[d0])
    rs = pd.Series(0.0, index=w.index)
    for (_k, wt), dk in zip(RS_WEIGHTS, dates[1:], strict=True):
        rs = rs + wt * (w[d0] / w[dk] - 1)
    return rs.dropna()


def build_features(
    store: Store,
    theme: Theme,
    membership: Membership,
    asof: pd.Timestamp | str | None = None,
    *,
    allow_fetch: bool = True,
    with_physical: bool = True,
) -> FeatureSet:
    """스토어에서 테마 구성원의 특성 표를 만든다. `asof` 기본 = 스토어 최종일."""
    row = store._con.execute("select max(date) from prices").fetchone()
    store_end = pd.Timestamp(row[0]) if row and row[0] else pd.Timestamp.today().normalize()
    asof_ts = min(pd.Timestamp(asof), store_end) if asof else store_end
    members = membership.members(theme.id)
    if not members:
        raise StoreError(f"{theme.id}: 구성원이 0개다")
    mf = membership.frame.set_index("ticker").reindex(members)
    meta = store.tickers_meta(min_rows=10_000).set_index("ticker")
    names = meta["name"].reindex(members)
    sectors = meta["sector"].reindex(members)

    td = _trading_dates(store, asof_ts)
    cutoff = td[-LISTED_WINDOW_TD] if len(td) >= LISTED_WINDOW_TD else td[0]
    px = store.prices(
        members,
        start=(asof_ts - pd.Timedelta(days=PRICE_LOOKBACK_DAYS)).date(),
        end=asof_ts.date(),
        min_rows=0,
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

    # RS — 전체 유니버스 백분위
    rs_u = universe_rs(store, td)
    rs_rating = rs_rating_from_universe(rs_u)
    stats["rs_universe_n"] = len(rs_u)

    # 재무 — PIT
    fund = store.fundamentals(
        listed, fields=list(FUND_FIELDS), end=asof_ts.date(), min_rows=0, date_column="datekey"
    )
    qt = (
        add_ttm(pit_quarterly(fund, asof_ts))
        if not fund.empty
        else pd.DataFrame(columns=["ticker", "calendardate", "datekey", *FUND_FIELDS])
    )
    mcap = pf["mcap"].reindex(listed) if not pf.empty else pd.Series(np.nan, index=listed)
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

    frame = pd.DataFrame(index=pd.Index(listed, name="ticker"))
    frame["name"] = names.reindex(listed)
    for col in (
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
    ):
        frame[col] = pf[col].reindex(listed) if not pf.empty else np.nan
    frame["rs_rating"] = rs_rating.reindex(listed)
    if not ff.empty:
        for col in ff.columns:
            if col == "mcap":
                continue
            frame[col] = ff[col].reindex(listed)
    frame["price_beta_hist"] = beta
    covered = set(qt["ticker"].unique()) if len(qt) else set()
    frame["fund_status"] = [
        "ok" if (not ff.empty and t in ff.index) else ("stale" if t in covered else "none")
        for t in listed
    ]
    for col in FEATURE_COLUMNS:
        if col not in frame.columns:
            frame[col] = np.nan
    frame = frame[list(FEATURE_COLUMNS)]
    return FeatureSet(theme.id, asof_ts, store_end, frame, universe, stats, inputs_unavailable)
