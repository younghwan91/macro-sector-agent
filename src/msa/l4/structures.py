"""L4 선정 구조 비교 — `docs/15-l4-selection-structure-preregistration.md` 의 집행.

**이 모듈은 사전 등록 문서를 해석하지 않는다. 실행한다.** 후보·상수·지표·합격 기준은 전부
`docs/15` 에서 왔고 그 절 번호를 옆에 적었다. 결과를 보고 바꾸지 않는다 (`CLAUDE.md` §1).
재는 것은 **선정 규칙의 예측력**(테마 EW 지수 초과)이지 전략의 수익률이 아니다 (`CLAUDE.md` §7).

## 기계는 새로 만들지 않는다 (`docs/15` §7)

특성 패널(`backtest.theme_panel` 의 parquet 캐시) · 전진 수익률(`backtest.stock_forward`) ·
테마 동일가중 집계(`backtest.theme_equal_weight`) · 요약(`l1.backtest._summarize`, 12개월 블록
부트스트랩 2000회 · 시드 0) · `dsr_of_series` · CSCV PBO 를 그대로 쓴다. `build_features` 는 다시
부르지 않는다 — 후보 넷은 캐시된 패널에서 재구성된다.

## 후보 넷 (`docs/15` §2.2 — 목록은 닫혀 있다)

- **B0 현행** — `barbell.classify(scored, top=3)` **그대로**. K=3 이므로 앵커 1 · 토크 2.
  상수는 코드의 현행값 `ANCHOR_S_MIN = 0.5` · `TORQUE_S_EXCLUDE_LE = 0.25` 그대로 쓴다.
- **B1 대장주** — 시총 상위 3. 시총은 **PIT** 다: `prices.mcap` 의 `asof` 이하 마지막 non-null.
  `Store.latest_mcap()` 은 PIT 가 아니므로 이 경로에서 쓰지 않는다 (§2.2).
- **B2 토크 단독** — `t_pct` 상위 3 (NaN 제외). `s_pct` 조건도 한계생산자 제외도 없다 (§2.2).
- **B3 동일가중 전체** — 적격 전부. K 미사용. **주 판정의 기준선**이다 (§2.3).

네 후보 전부 **하드 제외(E1~E5) 를 먼저 적용한 뒤** 같은 적격 집합에서 출발한다 (§2.1).
하드 필터는 이 문서의 비교 대상이 아니다 — `docs/14` Q3 이 따로 판정한다.

## 1차 지표와 판정 (`docs/15` §3.1 · §4)

- **1차 지표**: 주 창(2011-01–) · 12M · 후보 포트폴리오의 테마 EW 지수 초과수익. 월별로 테마
  동일가중 평균 → 하나의 시계열 → 95% 12개월 블록 부트스트랩 CI.
- **주 판정** (§4.1): X ∈ {B0, B1, B2} 에 대해 `X − B3` 차의 CI **하한 > 0** 이면 "B3 를 이겼다".
  0 포함이면 "구분되지 않는다", 상한 < 0 이면 "B3 보다 나빴다". **부호는 한쪽만 본다.**
- **부 판정** (§4.2): `B0 − B1` · `B0 − B2` 를 같은 방식으로.
- **DSR·PBO 는 합격 기준에 들어가지 않는다** (§4.3). 계산해서 반드시 싣는다.

## 해석상 고정한 것 (문서가 명시하지 않아 실행 전에 여기서 선언한다)

- **선정 풀** = 그 테마-월의 `eligible` 중 **그 호라이즌의 전진 수익률이 있는** 종목. 네 후보가
  같은 풀에서 출발한다 (§2.1 "네 후보 전부 같은 적격 집합에서"). 전진 수익률이 없는 종목을
  뽑아 두고 조용히 빼면 보유 종목 수가 말없이 줄어든다 (`CLAUDE.md` §2). `backtest.py` 의
  스프레드가 `pair = ~(isnan(S) | isnan(Xex))` 로 하는 것과 같은 자리다.
- **`n ≥ 20`** (§2.1 → `docs/14` §2.2) 은 **그 풀의 크기**로 센다. 미달 테마-월은 값을 만들지 않고
  사유별로 센다.
- 테마 EW 기준은 `backtest.theme_month_metrics` 와 **같은 정의** — 그 달 상장 구성원 중 전진
  수익률이 있는 것 **전부**(제외군 포함)의 동일가중 평균 (`docs/14` §2.5).
- `marginal_producer` 는 캐시 패널의 `tp_marginal_producer`(0/1, NaN=판정 불가)를 쓴다.
  `axes._bool01` 이 만든 그 열이 `barbell.classify` 가 보는 `marginal_producer` 와 같은 값이다.
- **회전율**(§6 #4 · §8.1 U5): 관문 호라이즌 선정 집합으로
  `1 − |S_t ∩ S_{t-1}| / max(|S_t|, |S_{t-1}|)`, 테마별로 격자에서 이웃한 달 사이에서만.
  **판정에 들어가지 않고 시도 수에 계상한다** (U5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from msa.config import paths
from msa.data.store import Store, StoreError
from msa.fmt import num as _fmt
from msa.io import dump_json, write_snapshot
from msa.l1.backtest import (
    BOOT_BLOCK,
    BOOT_N,
    BOOT_SEED,
    DSR_THRESHOLD,
    GATE_HORIZON,
    HORIZONS,
    PARTITION_ALL,
    PBO_BLOCKS,
    PBO_HORIZON,
    PBO_MAX_SPLITS,
    PBO_THRESHOLD,
    PRIMARY_START,
    WINDOWS,
    _plain,
    _summarize,
    _window_slice,
    dsr_of_series,
)
from msa.l4 import barbell
from msa.l4.backtest import (
    GRID_START,
    MIN_MEMBERS_POSSIBLE,
    MIN_STOCKS_XS,
    StockForward,
    _matrices,
    collect_panels,
    death_months,
    default_jobs,
    month_grid,
    monthly_close,
    prewarm_rs_cache,
    stock_forward,
    theme_equal_weight,
)
from msa.themes import load_themes, membership_from_store
from msa.vendor.overfitting import PBOResult, probability_of_backtest_overfitting

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 선언 (docs/15 §2 — 불변)

#: 후보 넷. **목록은 닫혀 있다** (§2). 실행 후에 추가하지 않는다.
CANDIDATES: tuple[str, ...] = ("B0", "B1", "B2", "B3")
#: K = 3 — `docs/14` §2.4 스프레드 컷오프 그대로. 새로 고른 값이 아니다 (§2.1).
K = 3
#: 후보 설명 (리포트·`meta.json` 에 그대로 실린다).
CANDIDATE_LABELS: dict[str, str] = {
    "B0": f"현행 바벨 — barbell.classify(top={K}) → 앵커 1 · 토크 2",
    "B1": f"대장주 — PIT 시총 상위 {K}",
    "B2": f"토크 단독 — t_pct 상위 {K} (s_pct 조건 없음)",
    "B3": "동일가중 전체 — 적격 전부 (선정을 하지 않는 것 · 기준선)",
}
#: 판정하는 차 (§4.1 주 판정 셋 · §4.2 부 판정 둘). 이 목록도 닫혀 있다.
PAIRS: tuple[tuple[str, str], ...] = (
    ("B0", "B3"),
    ("B1", "B3"),
    ("B2", "B3"),
    ("B0", "B1"),
    ("B0", "B2"),
)
PAIR_NAMES: tuple[str, ...] = tuple(f"{a}-{b}" for a, b in PAIRS)
PRIMARY_PAIRS: tuple[str, ...] = ("B0-B3", "B1-B3", "B2-B3")
SECONDARY_PAIRS: tuple[str, ...] = ("B0-B1", "B0-B2")
#: `docs/14` §6.2 의 정산값. §15 §4.3 이 "여기에 더한다" 고 못박았다.
N_TRIALS_L4 = 458

#: 후보가 K 에 못 미친 사유 (§2.1 · `CLAUDE.md` §2 — 조용히 버리지 않는다).
SHORTFALL_REASONS: tuple[str, ...] = (
    "b0_no_anchor_candidate",
    "b0_torque_pool_short",
    "b1_mcap_missing",
    "b2_t_pct_nan",
)

#: 결과를 어느 쪽으로 읽든 함께 붙어야 하는 문장 (`docs/15` §6).
LIMITATIONS: tuple[str, ...] = (
    "docs/14 §5 의 열 한 가지가 전부 그대로 걸린다 — L3 확신도 없음 · 테마 선정이 조건이 "
    "아님 · L5(비중·사다리·스탑·비용) 없음 · 표본이 사실상 하나 (§6).",
    "바벨의 '물타기 여력'은 경로 의존이라 12개월 초과수익 하나로는 원리적으로 보이지 않는다 "
    "(§6 #2). B0 가 져도 바벨 설계의 반증이 아니고, 이겨도 물타기 여력이 확인된 것은 아니다.",
    "비중이 없다 — 전부 동일가중이므로 B0 는 바벨의 절반(무엇을 고르는가)만 재고 나머지 "
    "절반(얼마씩 사는가)은 재지 않는다 (§6 #3).",
    "거래비용이 없다. 후보 간 회전율 차이가 결과에 반영되지 않는다 — 회전율 자체는 부차로 "
    "적는다 (§6 #4).",
    "B1 은 '대장주'의 한 가지 조작적 정의(시총 상위 3)일 뿐이다. B1 이 져도 '대장주가 안 "
    "된다'가 아니라 **'시총 상위 3 은 안 됐다'** 이다 (§6 #7).",
    "docs/06 §1 의 '우량주가 가장 덜 오른다'를 직접 검정하지 않는다 — 우량주 ≠ 시총 상위 "
    "(§6 #8).",
    "표본이 사실상 하나라 '틀렸다'를 말할 힘은 있어도 '맞았다'를 말할 힘이 애초에 약하다. "
    "B3 를 이기지 못한 것은 상대적으로 강한 진술이고, 이긴 것은 약한 진술이다 (§6 #6).",
)


def count_trials() -> dict[str, int]:
    """DSR 시도 수 — `docs/15` §4.3 의 식을 **그대로**, 그 위에 실제로 들여다본 칸을 더한다.

        수준 눈금    B×H×W = 4×3×2 = 24
        차 X−B3      3×H×W = 3×3×2 = 18
        차 B0−B1     1×H×W = 1×3×2 =  6
        차 B0−B2     1×H×W = 1×3×2 =  6
        사망률       B×W   = 4×2   =  8
        민감도 D1    주 창·12M·수준 4후보 =  4
        ────────────────────────────────────
        §15 시도 = 66 → 정산 = 458 (docs/14 §6.2) + 66 = 524

    **524 는 하한이다** (§4.3 "리포트가 이보다 많은 칸을 들여다보면 그 수만큼 늘린다").
    이 구현이 더 들여다보는 칸이 둘 있고, 세지 않은 시도는 없는 시도가 아니므로
    (`docs/10` §2.2) 여기에 더한다:

    - **회전율** B×W = 8 — §8.1 U5 가 "정의는 구현 시 적고 시도 수에 계상한다" 고 했다.
    - **1M 수준** B×W = 8 — §4.3 의 PBO 항이 "열 = 4 후보의 1M 월별 초과수익" 을 요구하는데
      위 산식에 그 칸이 없다. 요구된 입력이므로 만들고, 만든 만큼 센다.

    선언만 세면 **4** 다 — 주 창·12M 의 `X − B3` 셋과 `B0 − B1` 하나 (§4.3). 둘 다 적는다.
    """
    b, h, w = len(CANDIDATES), len(HORIZONS), len(WINDOWS)
    levels = b * h * w
    diff_b3 = len(PRIMARY_PAIRS) * h * w
    diff_b0b1 = h * w
    diff_b0b2 = h * w
    mortality = b * w
    sens_d1 = b
    doc = levels + diff_b3 + diff_b0b1 + diff_b0b2 + mortality + sens_d1
    turnover = b * w
    level_1m = b * w
    return {
        "candidates": b,
        "horizons": h,
        "windows": w,
        "levels": levels,
        "diff_x_minus_b3": diff_b3,
        "diff_b0_b1": diff_b0b1,
        "diff_b0_b2": diff_b0b2,
        "mortality": mortality,
        "sensitivity_d1": sens_d1,
        "docs15_subtotal": doc,
        "docs14_base": N_TRIALS_L4,
        "docs15_declared_total": N_TRIALS_L4 + doc,
        "turnover_added": turnover,
        "level_1m_for_pbo_added": level_1m,
        "added_beyond_docs15": turnover + level_1m,
        "declared_only": 4,
        "total": N_TRIALS_L4 + doc + turnover + level_1m,
    }


# ---------------------------------------------------------------- PIT 시총 (§2.2 — B1 만 쓴다)


def monthly_mcap(
    store: Store, tickers: list[str], dates: pd.DatetimeIndex
) -> pd.DataFrame:
    """월말 **PIT** 시총 (date × ticker, 달러) — `asof` 이하 마지막 non-null (`docs/15` §2.2).

    달마다 그 달의 마지막 non-null `prices.mcap` 을 집고, 격자에 맞춘 뒤 **앞으로 채운다**(ffill).
    ffill 이 곧 "`asof` 이하 마지막 non-null" 이다. `Store.latest_mcap()` 은 스토어 전체에서 가장
    최근 값을 집으므로 **PIT 가 아니고 이 경로에서 쓰지 않는다.**
    """
    sql = (
        "select p.ticker as ticker, last_day(p.date) as m, arg_max(p.mcap, p.date) as mcap "
        "from prices p join tk on p.ticker = tk.ticker "
        "where p.mcap is not null group by 1, 2"
    )
    cols = sorted(set(tickers))
    tk = pd.DataFrame({"ticker": pd.Series(cols, dtype="object")})
    df = store.query(sql, frames={"tk": tk}, min_rows=1, what="monthly_mcap")
    df["m"] = pd.to_datetime(df["m"])
    out = df.pivot(index="m", columns="ticker", values="mcap").sort_index()
    out.index = pd.DatetimeIndex(out.index)
    idx = out.index.union(pd.DatetimeIndex(dates)).sort_values()
    return out.reindex(index=idx).ffill().reindex(index=dates).reindex(columns=cols)


# ---------------------------------------------------------------- 후보 넷 (§2.2)


def _order_desc(values: np.ndarray, tickers: np.ndarray) -> np.ndarray:
    """값 내림차순 → 티커 오름차순 (§2.1 동률 처리). NaN 은 넣기 전에 걸러 낸다."""
    return np.lexsort((tickers, -values))


def select_b0(
    tickers: np.ndarray, s_pct: np.ndarray, t_pct: np.ndarray, marginal: np.ndarray
) -> barbell.Barbell:
    """B0 — `barbell.classify(scored, top=K)` **그대로**. 규칙의 정본은 `barbell.py` 이고
    여기서 다시 쓰지 않는다 (§2.2)."""
    scored = pd.DataFrame(
        {
            "s_pct": np.asarray(s_pct, dtype=float),
            "t_pct": np.asarray(t_pct, dtype=float),
            "marginal_producer": pd.array(
                [pd.NA if np.isnan(x) else bool(x > 0.5) for x in marginal], dtype="boolean"
            ),
        },
        index=pd.Index([str(x) for x in tickers], name="ticker"),
    )
    return barbell.classify(scored, top=K)


def select_b1(tickers: np.ndarray, mcap: np.ndarray) -> list[str]:
    """B1 — PIT 시총 상위 K. `mcap` 이 없는 종목은 **풀에서 빠지고 사유별로 센다** (§2.2).
    결측을 0 이나 대용값으로 메우지 않는다."""
    ok = ~np.isnan(mcap)
    tk, v = np.asarray(tickers)[ok], np.asarray(mcap, dtype=float)[ok]
    return [str(x) for x in tk[_order_desc(v, tk.astype(str))][:K]]


def select_b2(tickers: np.ndarray, t_pct: np.ndarray) -> list[str]:
    """B2 — `t_pct` 상위 K (NaN 제외). `s_pct` 조건도 한계생산자 제외도 없다 (§2.2)."""
    ok = ~np.isnan(t_pct)
    tk, v = np.asarray(tickers)[ok], np.asarray(t_pct, dtype=float)[ok]
    return [str(x) for x in tk[_order_desc(v, tk.astype(str))][:K]]


def select_b3(tickers: np.ndarray) -> list[str]:
    """B3 — 적격 전부. K 를 쓰지 않는다 (§2.2). **주 판정의 기준선**이다 (§2.3)."""
    return [str(x) for x in np.asarray(tickers)]


# ---------------------------------------------------------------- 테마-월 집계


@dataclass(frozen=True)
class ThemeMonthSelection:
    excess: pd.DataFrame  # date, theme, candidate, horizon, excess, ret, n_selected, n
    mortality: pd.DataFrame  # date, theme, candidate, horizon, death_rate, n
    composition: pd.DataFrame  # date, theme, n_anchor, n_torque, anchor_share, n_empty_slots
    turnover: pd.DataFrame  # date, theme, candidate, turnover
    counts: dict[str, Any]


def _zero_counts() -> dict[str, Any]:
    z: dict[str, Any] = {
        "theme_months": 0,
        "theme_months_below_min_n": 0,
        "eligible_stock_months": 0,
        "eligible_stock_months_no_forward": 0,
        "pool_stock_months_no_mcap": 0,
        "pool_stock_months_t_pct_nan": 0,
    }
    z.update({f"short_{r}": 0 for r in SHORTFALL_REASONS})
    z.update({f"{c}_theme_months_short_of_k": 0 for c in CANDIDATES})
    z.update({f"{c}_theme_months_empty": 0 for c in CANDIDATES})
    return z


def theme_month_selection(
    panel: pd.DataFrame,
    fwd: StockForward,
    mcap: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (PBO_HORIZON, *HORIZONS),
    min_n: int = MIN_STOCKS_XS,
) -> ThemeMonthSelection:
    """테마 하나의 캐시 패널 → 후보 넷의 테마-월 초과수익 · 사망률 · B0 구성 · 회전율.

    풀 = `eligible` ∧ 그 호라이즌의 전진 수익률 있음 (모듈 docstring 의 선언). `n < min_n` 인
    테마-월은 값을 만들지 않고 센다 (`CLAUDE.md` §2).
    """
    empty = pd.DataFrame()
    if panel.empty:
        return ThemeMonthSelection(empty, empty, empty, empty, _zero_counts())
    theme = str(panel["theme"].iloc[0])
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
    M = _matrices(panel, dates, ["eligible", "s_pct", "t_pct", "tp_marginal_producer"])
    tickers = np.array([str(x) for x in M.pop("__tickers__")], dtype=object)
    elig = np.nan_to_num(M["eligible"], nan=0.0) > 0.5
    listed = ~np.isnan(M["eligible"])
    S, T, MP = M["s_pct"], M["t_pct"], M["tp_marginal_producer"]
    MC = mcap.reindex(index=dates, columns=list(tickers)).to_numpy(dtype=float)
    pos = {str(x): j for j, x in enumerate(tickers)}

    cnt = _zero_counts()
    ex_rows: list[dict[str, Any]] = []
    mo_rows: list[dict[str, Any]] = []
    comp_rows: list[dict[str, Any]] = []
    tv_rows: list[dict[str, Any]] = []

    for h in horizons:
        Y = fwd.raw[h].reindex(index=dates, columns=list(tickers)).to_numpy(dtype=float)
        D = fwd.death[h].reindex(index=dates, columns=list(tickers)).to_numpy(dtype=float)
        base = np.where(listed, Y, np.nan)
        n_base = np.sum(~np.isnan(base), axis=1)
        with np.errstate(invalid="ignore"):
            ew = np.where(n_base > 0, np.nansum(base, axis=1) / np.maximum(n_base, 1), np.nan)
        pool_ok = elig & ~np.isnan(Y)
        gate = h == GATE_HORIZON
        prev: dict[str, set[str]] = {}
        prev_i = -99
        for i, d in enumerate(dates):
            ok = pool_ok[i]
            n_pool = int(ok.sum())
            if gate:
                cnt["theme_months"] += 1
                cnt["eligible_stock_months"] += int(elig[i].sum())
                cnt["eligible_stock_months_no_forward"] += int((elig[i] & ~ok).sum())
                cnt["pool_stock_months_no_mcap"] += int((ok & np.isnan(MC[i])).sum())
                cnt["pool_stock_months_t_pct_nan"] += int((ok & np.isnan(T[i])).sum())
            if n_pool < min_n:
                if gate:
                    cnt["theme_months_below_min_n"] += 1
                continue
            tk = tickers[ok]
            bb = select_b0(tk, S[i][ok], T[i][ok], MP[i][ok])
            sel: dict[str, list[str]] = {
                "B0": [*bb.anchors, *bb.torques],
                "B1": select_b1(tk, MC[i][ok]),
                "B2": select_b2(tk, T[i][ok]),
                "B3": select_b3(tk),
            }
            if gate:
                if not bb.anchors:
                    cnt["short_b0_no_anchor_candidate"] += 1
                if len(bb.torques) < K - len(bb.anchors):
                    cnt["short_b0_torque_pool_short"] += 1
                if int((~np.isnan(MC[i][ok])).sum()) < K:
                    cnt["short_b1_mcap_missing"] += 1
                if int((~np.isnan(T[i][ok])).sum()) < K:
                    cnt["short_b2_t_pct_nan"] += 1
                comp_rows.append(
                    {
                        "date": d,
                        "theme": theme,
                        "n_anchor": len(bb.anchors),
                        "n_torque": len(bb.torques),
                        "n_selected": bb.n,
                        "anchor_share": bb.anchor_share,
                        "n_empty_slots": K - bb.n,
                    }
                )
                for c in CANDIDATES:
                    target = n_pool if c == "B3" else K
                    if len(sel[c]) < target:
                        cnt[f"{c}_theme_months_short_of_k"] += 1
                    if not sel[c]:
                        cnt[f"{c}_theme_months_empty"] += 1
                    now = set(sel[c])
                    if i == prev_i + 1 and c in prev:
                        den = max(len(now), len(prev[c]))
                        tv_rows.append(
                            {
                                "date": d,
                                "theme": theme,
                                "candidate": c,
                                "turnover": 1.0 - len(now & prev[c]) / den
                                if den
                                else float("nan"),
                            }
                        )
                    prev[c] = now
                prev_i = i
            for c in CANDIDATES:
                idx = [pos[x] for x in sel[c]]
                ret = float(np.mean(Y[i][idx])) if idx else float("nan")
                ex_rows.append(
                    {
                        "date": d,
                        "theme": theme,
                        "candidate": c,
                        "horizon": h,
                        "excess": ret - float(ew[i]) if idx else float("nan"),
                        "ret": ret,
                        "ret_theme_ew": float(ew[i]),
                        "n_selected": len(idx),
                        "n": n_pool,
                    }
                )
                if gate and idx:
                    dr = D[i][idx]
                    mo_rows.append(
                        {
                            "date": d,
                            "theme": theme,
                            "candidate": c,
                            "horizon": h,
                            "death_rate": float(np.nanmean(dr))
                            if bool(np.any(~np.isnan(dr)))
                            else float("nan"),
                            "n": len(idx),
                        }
                    )
    return ThemeMonthSelection(
        excess=pd.DataFrame(ex_rows),
        mortality=pd.DataFrame(mo_rows),
        composition=pd.DataFrame(comp_rows),
        turnover=pd.DataFrame(tv_rows),
        counts=cnt,
    )


# ---------------------------------------------------------------- 차 (§4.1 · §4.2)


def pairwise_theme_month(excess: pd.DataFrame) -> pd.DataFrame:
    """테마-월 단위 `X − Y` (§4.1 · §4.2).

    **차를 테마-월에서 먼저 만들고** 그 뒤에 테마 동일가중 평균한다 — 두 후보가 같은 테마-월에서만
    비교되도록 짝을 맞춘 것이다. 한쪽이 비어 있는 테마-월(예: B0 가 0개)은 차가 NaN 이 되고,
    `_summarize` 의 `n_months_dropped` 로 드러난다.
    """
    if excess.empty:
        return pd.DataFrame()
    wide = excess.pivot_table(
        index=["date", "theme", "horizon"], columns="candidate", values="excess", aggfunc="first"
    )
    rows: list[pd.DataFrame] = []
    for a, b in PAIRS:
        if a not in wide.columns or b not in wide.columns:
            continue
        d = (wide[a] - wide[b]).rename("excess").reset_index()
        d["pair"] = f"{a}-{b}"
        rows.append(d)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out["n"] = np.nan
    return out


# ---------------------------------------------------------------- 과최적화 정산 (§4.3)


def _pbo(
    level_monthly: pd.DataFrame, *, window: str, horizon: int, max_splits: int
) -> dict[str, Any]:
    """CSCV PBO — 열("전략") = **4 후보의 초과수익** (§4.3). S=16, 전수 조합 C(16,8)=12,870."""
    rec: dict[str, Any] = {
        "window": window,
        "horizon": horizon,
        "strategies": list(CANDIDATES),
        "n_months": 0,
    }
    if level_monthly.empty:
        rec.update(pbo=float("nan"), note="시계열 없음")
        return rec
    sub = _window_slice(level_monthly[level_monthly["horizon"] == horizon], window)
    if sub.empty:
        rec.update(pbo=float("nan"), note="시계열 없음")
        return rec
    mat = sub.pivot(index="date", columns="candidate", values="excess")
    missing = [c for c in CANDIDATES if c not in mat.columns]
    if missing:
        rec.update(pbo=float("nan"), note=f"후보 결측 {missing}")
        return rec
    mat = mat[list(CANDIDATES)].sort_index().dropna(how="any")
    rec["n_months"] = len(mat)
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
    level_monthly: pd.DataFrame,
    pair_monthly: pd.DataFrame,
    trials: dict[str, int],
    *,
    pbo_max_splits: int = PBO_MAX_SPLITS,
) -> dict[str, Any]:
    """DSR(선언 4 · 전 시도) · PBO. **합격 기준이 아니다** (§4.3) — 계산해서 반드시 싣는다."""
    out: dict[str, Any] = {
        "trials": trials,
        "dsr_threshold": DSR_THRESHOLD,
        "pbo_threshold": PBO_THRESHOLD,
        "dsr": [],
        "pbo": [],
        "note": (
            "DSR·PBO 는 합격 기준에 들어가지 않는다 (docs/15 §4.3). 합격은 '0 과 구분된다' 이지 "
            "'N 번 본 중 우연이 아니다' 가 아니다. 12M 의 비중첩 관측 수가 얇아 전 시도 수를 "
            "이길 수 없을 가능성이 높고, 그것이 이 검정의 구조적 한계다 — 그래서 관문에 넣지 "
            "않았고 넣지 않은 대신 반드시 적는다. PBO 는 열이 4개뿐이라 분해능이 낮고, "
            "**낮게 나오는 것은 '후보 간 순위가 시간상 안정적'이라는 뜻이지 '선정이 좋다'는 "
            "뜻이 아니다** (docs/backtest-l1.md §7 · docs/14 §6.3 과 같은 주의)."
        ),
    }
    n_all, n_dec = trials["total"], trials["declared_only"]
    lv = (
        level_monthly[level_monthly["partition"] == PARTITION_ALL]
        if not level_monthly.empty
        else level_monthly
    )
    pr = (
        pair_monthly[pair_monthly["partition"] == PARTITION_ALL]
        if not pair_monthly.empty
        else pair_monthly
    )
    for w in WINDOWS:
        for series, frame, key, names in (
            ("level", lv, "candidate", CANDIDATES),
            ("diff", pr, "pair", PAIR_NAMES),
        ):
            if frame.empty:
                continue
            fw = _window_slice(frame, w)
            for name in names:
                for h in (PBO_HORIZON, *HORIZONS):
                    s = (
                        fw[(fw[key] == name) & (fw["horizon"] == h)]
                        .set_index("date")["excess"]
                        .sort_index()
                    )
                    if s.dropna().empty:
                        continue
                    out["dsr"].append(
                        {
                            "window": w,
                            "series": series,
                            "name": name,
                            "horizon": h,
                            "dsr_declared_n4": dsr_of_series(s, n_dec, horizon=h),
                            "dsr_n_total": dsr_of_series(s, n_all, horizon=h),
                        }
                    )
        for h in (PBO_HORIZON, GATE_HORIZON):
            out["pbo"].append(_pbo(lv, window=w, horizon=h, max_splits=pbo_max_splits))
    return out


# ---------------------------------------------------------------- 판정 (§4.1 · §4.2)


def _call(lo: float, hi: float, better: str, worse: str) -> str:
    """§4 의 세 칸. **부호는 한쪽만 본다** — 양측 검정으로 바꾸지 않는다 (§4.1 · §4.2).
    "0 포함"을 "약한 증거"로 읽지 않는다."""
    if lo > 0:
        return better
    if hi < 0:
        return worse
    return "indistinguishable"


def _cell(summ: pd.DataFrame, **where: Any) -> pd.Series | None:
    """요약 표에서 정확히 한 칸. 없으면 None (그 칸을 재지 않았다는 뜻)."""
    if summ.empty or any(k not in summ.columns for k in where):
        return None
    m = pd.Series(True, index=summ.index)
    for k, v in where.items():
        m &= summ[k] == v
    sub = summ[m]
    return None if sub.empty else sub.iloc[0]


def verdict(
    level_summary: pd.DataFrame, pair_summary: pd.DataFrame, overfit: dict[str, Any]
) -> dict[str, Any]:
    """`docs/15` §4.1 · §4.2 의 표를 그대로 코드로. 기준선은 B3 이고 관문은 차의 CI 하한이다."""
    out: dict[str, Any] = {
        "preregistration": "docs/15-l4-selection-structure-preregistration.md",
        "k": K,
        "baseline": "B3",
        "rule_primary": (
            "각 후보 X ∈ {B0,B1,B2} 에 대해 주 창(2011-01–) · 12M 의 `X − B3` 초과수익 차의 "
            "95% 12개월 블록 부트스트랩 CI 하한 > 0 이면 'X 가 B3 를 이겼다'. 0 을 포함하면 "
            "'구분되지 않는다', 상한 < 0 이면 'B3 보다 나빴다'. 부호는 한쪽만 본다 (§4.1)"
        ),
        "rule_secondary": (
            "같은 창·호라이즌에서 `B0 − B1` (하한>0 현행 우위 / 상한<0 대장주 우위 / 0 포함 "
            "구분 안 됨) 과 `B0 − B2` (S̃ 조건이 값을 했는가) 를 판정한다 (§4.2)"
        ),
        "dsr_pbo_in_gate": False,
    }
    levels: dict[str, Any] = {}
    for c in CANDIDATES:
        r = _cell(
            level_summary,
            window="primary",
            horizon=GATE_HORIZON,
            candidate=c,
            partition=PARTITION_ALL,
        )
        if r is not None:
            levels[c] = {
                "label": CANDIDATE_LABELS[c],
                "mean_excess": float(r["mean"]),
                "ci": [float(r["ci_lo"]), float(r["ci_hi"])],
                "n_months": int(r["n_months"]),
                "n_eff": float(r["n_eff"]),
            }
    out["levels_12m_primary"] = levels

    primary: dict[str, Any] = {}
    for name in PRIMARY_PAIRS:
        r = _cell(
            pair_summary,
            window="primary",
            horizon=GATE_HORIZON,
            pair=name,
            partition=PARTITION_ALL,
        )
        if r is None:
            primary[name] = {"call": "undetermined", "reason": "관문 셀이 비어 있다"}
            continue
        lo, hi = float(r["ci_lo"]), float(r["ci_hi"])
        primary[name] = {
            "mean": float(r["mean"]),
            "ci": [lo, hi],
            "n_months": int(r["n_months"]),
            "n_months_dropped": int(r["n_months_dropped"]),
            "n_eff": float(r["n_eff"]),
            "call": _call(lo, hi, "beats_B3", "worse_than_B3"),
        }
    out["primary_vs_b3_12m"] = primary
    beat = [k for k, v in primary.items() if v.get("call") == "beats_B3"]
    out["beating_b3"] = beat
    out["n_beating_b3"] = len(beat)
    out["nobody_beats_b3"] = bool(primary) and not beat

    sec: dict[str, Any] = {}
    for name, better, worse in (
        ("B0-B1", "current_better_than_megacap", "megacap_better"),
        ("B0-B2", "s_condition_added_value", "s_condition_hurt"),
    ):
        r = _cell(
            pair_summary,
            window="primary",
            horizon=GATE_HORIZON,
            pair=name,
            partition=PARTITION_ALL,
        )
        if r is None:
            sec[name] = {"call": "undetermined"}
            continue
        lo, hi = float(r["ci_lo"]), float(r["ci_hi"])
        sec[name] = {
            "mean": float(r["mean"]),
            "ci": [lo, hi],
            "n_months": int(r["n_months"]),
            "call": _call(lo, hi, better, worse),
        }
    out["secondary_12m"] = sec

    dsr = [
        d
        for d in overfit["dsr"]
        if d["window"] == "primary"
        and d["series"] == "diff"
        and d["name"] == "B0-B3"
        and d["horizon"] == GATE_HORIZON
    ]
    pbo = [p for p in overfit["pbo"] if p["window"] == "primary" and p["horizon"] == PBO_HORIZON]
    out["reported_not_gated"] = {
        "dsr_declared_n4_nonoverlapping_B0_B3": dsr[0]["dsr_declared_n4"]["dsr_nonoverlapping"]
        if dsr
        else float("nan"),
        "dsr_all_trials_nonoverlapping_B0_B3": dsr[0]["dsr_n_total"]["dsr_nonoverlapping"]
        if dsr
        else float("nan"),
        "n_trials": overfit["trials"]["total"],
        "pbo_primary_1m": pbo[0].get("pbo", float("nan")) if pbo else float("nan"),
    }
    out["actions_docs15_section5"] = {
        "B0_only_beats_B3": "현행 유지 + rank_score·composite·rank 와 M 축 제거 (§5)",
        "B1_better_than_B0": "선정 규칙 시총 상위로 교체 **검토** — 자동 채택이 아니다 (§5)",
        "nobody_beats_B3": "L4 의 선정 규칙을 버린다 — 하드 제외만 남기고 테마 내 동일가중 (§5)",
        "B2_indistinguishable_from_B0": "S̃ 조건이 값을 하지 않았음을 기록. 임계 불변 (§5)",
        "multiple_beat_B3": "더 단순한 쪽 우선 (B3 < B1 < B2 < B0). 초과수익이 큰 쪽이 아니다 (§5)",
    }
    return out


# ---------------------------------------------------------------- 오케스트레이션


@dataclass(frozen=True)
class L4StructureResult:
    theme_month: pd.DataFrame
    level_monthly: pd.DataFrame
    level_summary: pd.DataFrame
    pair_monthly: pd.DataFrame
    pair_summary: pd.DataFrame
    mortality_summary: pd.DataFrame
    turnover_summary: pd.DataFrame
    composition: pd.DataFrame
    overfitting: dict[str, Any]
    verdict: dict[str, Any]
    exclusions: dict[str, Any]
    meta: dict[str, Any]
    out_dir: Path | None = None


def run_structures_frames(
    panel: pd.DataFrame,
    fwd: StockForward,
    mcap: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = HORIZONS,
    pbo_max_splits: int = PBO_MAX_SPLITS,
) -> L4StructureResult:
    """이미 만들어진 패널·전진 수익률·PIT 시총으로 §2~§4 를 돈다 (스토어 불필요 — 테스트 공용)."""
    hs = (PBO_HORIZON, *horizons)
    ex_parts: list[pd.DataFrame] = []
    mo_parts: list[pd.DataFrame] = []
    cp_parts: list[pd.DataFrame] = []
    tv_parts: list[pd.DataFrame] = []
    totals = _zero_counts()
    by_theme: list[dict[str, Any]] = []
    themes = sorted(panel["theme"].unique()) if not panel.empty else []
    for i, t in enumerate(themes, 1):
        r = theme_month_selection(panel[panel["theme"] == t], fwd, mcap, horizons=hs)
        for lst, fr in (
            (ex_parts, r.excess),
            (mo_parts, r.mortality),
            (cp_parts, r.composition),
            (tv_parts, r.turnover),
        ):
            if not fr.empty:
                lst.append(fr)
        for k, v in r.counts.items():
            totals[k] = totals[k] + v
        by_theme.append({"theme": t, **r.counts})
        log.info("l4-structures: 집계 %d/%d 테마 (%s)", i, len(themes), t)

    def cat(parts: list[pd.DataFrame]) -> pd.DataFrame:
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    ex_tm, mo_tm, cp_tm, tv_tm = cat(ex_parts), cat(mo_parts), cat(cp_parts), cat(tv_parts)
    pair_tm = pairwise_theme_month(ex_tm)

    lv_monthly = theme_equal_weight(ex_tm, ("candidate", "horizon"), "excess")
    pr_monthly = theme_equal_weight(pair_tm, ("pair", "horizon"), "excess")
    mo_monthly = theme_equal_weight(mo_tm, ("candidate", "horizon"), "death_rate")
    tv_tm2 = tv_tm.assign(horizon=GATE_HORIZON) if not tv_tm.empty else tv_tm
    tv_monthly = theme_equal_weight(tv_tm2, ("candidate", "horizon"), "turnover")

    lv_sum = _summarize(lv_monthly, ("candidate", "horizon", "partition"), "excess", _extra)
    pr_sum = _summarize(pr_monthly, ("pair", "horizon", "partition"), "excess", _extra)
    mo_sum = _summarize(mo_monthly, ("candidate", "horizon", "partition"), "death_rate", _extra)
    tv_sum = _summarize(tv_monthly, ("candidate", "horizon", "partition"), "turnover", _extra)

    trials = count_trials()
    overfit = overfitting_summary(lv_monthly, pr_monthly, trials, pbo_max_splits=pbo_max_splits)
    ver = verdict(lv_sum, pr_sum, overfit)
    excl = {
        "totals": totals,
        "by_theme": by_theme,
        "forward": fwd.exclusions,
        "shortfall_reasons": list(SHORTFALL_REASONS),
        "note": (
            "후보가 K 에 못 미치거나 0개인 테마-월을 사유별로 센다 (docs/15 §2.1 · CLAUDE.md §2). "
            "`pool_stock_months_no_mcap` 이 docs/15 §8.1 U1 이 묻는 수다 — 커버리지가 낮으면 "
            "'B1 은 그 표본에서 정의되지 않았다'가 결과이며 대용값으로 메우지 않는다."
        ),
    }
    meta: dict[str, Any] = {
        "preregistration": "docs/15-l4-selection-structure-preregistration.md",
        "candidates": list(CANDIDATES),
        "candidate_labels": dict(CANDIDATE_LABELS),
        "pairs": list(PAIR_NAMES),
        "k": K,
        "horizons": list(horizons),
        "gate_horizon": GATE_HORIZON,
        "pbo_horizon": PBO_HORIZON,
        "primary_start": str(PRIMARY_START.date()),
        "min_stocks_xs": MIN_STOCKS_XS,
        "bootstrap": {"block": BOOT_BLOCK, "n": BOOT_N, "seed": BOOT_SEED},
        "pbo": {"blocks": PBO_BLOCKS, "max_splits": pbo_max_splits},
        "barbell": {
            "anchor_s_min": barbell.ANCHOR_S_MIN,
            "torque_s_exclude_le": barbell.TORQUE_S_EXCLUDE_LE,
            "n_anchor": max(1, K // 2),
        },
        "mcap_pit": "prices.mcap 의 asof 이하 마지막 non-null (Store.latest_mcap 은 쓰지 않는다)",
        "turnover_definition": (
            "관문 호라이즌 선정 집합 · 격자에서 이웃한 달 사이 "
            "1 − |S_t ∩ S_{t-1}| / max(|S_t|, |S_{t-1}|) (docs/15 §8.1 U5)"
        ),
        "n_themes_measured": len(themes),
        "limitations": list(LIMITATIONS),
    }
    return L4StructureResult(
        theme_month=ex_tm[ex_tm["horizon"] == GATE_HORIZON].reset_index(drop=True)
        if not ex_tm.empty
        else ex_tm,
        level_monthly=lv_monthly,
        level_summary=lv_sum,
        pair_monthly=pr_monthly,
        pair_summary=pr_sum,
        mortality_summary=mo_sum,
        turnover_summary=tv_sum,
        composition=cp_tm,
        overfitting=overfit,
        verdict=ver,
        exclusions=excl,
        meta=meta,
    )


def _extra(g: pd.DataFrame, rec: dict[str, Any]) -> None:
    rec["mean_n_themes"] = float(g["n_themes"].mean()) if len(g) else float("nan")
    rec["mean_n_stocks"] = float(g["n_mean"].mean()) if len(g) else float("nan")


# ---------------------------------------------------------------- 리포트


def _pct(x: Any, w: int = 7, p: int = 2) -> str:
    return _fmt(float(x) * 100.0 if x is not None and pd.notna(x) else float("nan"), w, p)


def render_report(res: L4StructureResult) -> str:
    m, v = res.meta, res.verdict
    L: list[str] = []
    L.append("L4 선정 구조 비교 — docs/15 사전 등록의 집행.")
    L.append(
        "재는 것은 선정 규칙의 예측력(테마 EW 지수 초과)이지 전략의 수익률이 아니다 "
        "(CLAUDE.md §7 · docs/14 리포트와 같은 문구 규약)."
    )
    L.append(
        f"스토어 최종일 {m.get('store_end', '?')} · 테마 {m['n_themes_measured']}"
        f" · 격자 {m.get('grid_first', '?')}~{m.get('grid_last', '?')}"
        f" ({m.get('n_months', '?')}개월) · 주 창 {m['primary_start']}–"
        f" · 관문 {m['gate_horizon']}M · K={m['k']} · n≥{m['min_stocks_xs']}"
    )
    if m.get("smoke"):
        L.append("!! 스모크 실행이다 — 테마·격자를 줄였다. 판정이 아니다 (docs/15 §4).")
    L.append("")
    L.append("=" * 100)
    L.append(f"주 판정 (docs/15 §4.1): {v['rule_primary']}")
    for name in PRIMARY_PAIRS:
        r = v["primary_vs_b3_12m"].get(name, {})
        if "mean" not in r:
            L.append(f"  {name:<7} —  ({r.get('call', '?')})")
            continue
        L.append(
            f"  {name:<7} {_pct(r['mean'], 8, 2)}%p  95% CI"
            f" [{_pct(r['ci'][0], 7, 2)}, {_pct(r['ci'][1], 7, 2)}]%p"
            f"  N={r['n_months']}  N_eff={r['n_eff']:.1f}"
            f"  → **{r['call']}**"
        )
    if m.get("smoke"):
        L.append("  ⇒ 스모크라 §5 의 조치를 읽지 않는다. 판정은 전체 실행에서만 나온다.")
    elif v.get("nobody_beats_b3"):
        L.append("  ⇒ 아무도 B3 를 이기지 못했다. §5: L4 의 선정 규칙을 버린다 (조치는 사람이).")
    elif v.get("n_beating_b3", 0) == 1 and v["beating_b3"] == ["B0-B3"]:
        L.append("  ⇒ B0 만 B3 를 이겼다. §5: 현행 유지 + rank_score·M 축 제거 (조치는 사람이).")
    elif v.get("n_beating_b3", 0) > 1:
        L.append("  ⇒ 여럿이 B3 를 이겼다. §5: 더 단순한 쪽 우선 (B3 < B1 < B2 < B0).")
    L.append("")
    L.append(f"부 판정 (docs/15 §4.2): {v['rule_secondary']}")
    for name in SECONDARY_PAIRS:
        r = v["secondary_12m"].get(name, {})
        if "mean" not in r:
            L.append(f"  {name:<7} —  ({r.get('call', '?')})")
            continue
        L.append(
            f"  {name:<7} {_pct(r['mean'], 8, 2)}%p  95% CI"
            f" [{_pct(r['ci'][0], 7, 2)}, {_pct(r['ci'][1], 7, 2)}]%p"
            f"  N={r['n_months']}  → **{r['call']}**"
        )
    rn = v.get("reported_not_gated", {})
    L.append("")
    L.append(
        f"  (합격 기준 밖) B0−B3 DSR(N=4 선언, 비중첩)"
        f" {_fmt(rn.get('dsr_declared_n4_nonoverlapping_B0_B3'))}"
        f" · DSR(N={rn.get('n_trials')} 전 시도)"
        f" {_fmt(rn.get('dsr_all_trials_nonoverlapping_B0_B3'))}"
        f" · PBO(1M) {_fmt(rn.get('pbo_primary_1m'))}"
    )
    L.append("  합격은 '0 과 구분된다' 이지 'N 번 본 중 우연이 아니다' 가 아니다 (docs/15 §4.3).")
    L.append("=" * 100)
    L.append("")
    L += _level_table(res)
    L.append("")
    L += _pair_table(res)
    L.append("")
    L += _secondary_table(res)
    L.append("")
    L += _overfit_lines(res)
    L.append("")
    L += _exclusion_lines(res)
    L.append("")
    L += _limitation_lines(res)
    L.append("")
    L.append(
        "이 표로 후보를 추가하거나 K·ANCHOR_S_MIN·TORQUE_S_EXCLUDE_LE·축 가중치를 옮기지 않는다 "
        "(CLAUDE.md §1, docs/15 §5.1). 합격해도 자동 채택이 아니다 — 사람이 읽고 정한다."
    )
    return "\n".join(L)


def _level_table(res: L4StructureResult) -> list[str]:
    out = [
        "[1] 후보별 테마 EW 지수 초과수익 (수준) — 판정은 [2] 의 차로 한다",
        f"{'window':<8}{'h':>3} {'cand':<5}{'N':>5}{'N_eff':>7}{'mean%p':>9}{'ci_lo':>9}"
        f"{'ci_hi':>9}{'pos%':>7}{'AR1':>6}{'테마':>6}{'종목':>7}",
    ]
    s = res.level_summary
    if s.empty:
        return [*out, "  —"]
    s = s[s["partition"] == PARTITION_ALL]
    for _, r in _sorted(s, "candidate").iterrows():
        out.append(
            f"{r['window']:<8}{int(r['horizon']):>3} {r['candidate']:<5}{int(r['n_months']):>5}"
            f"{_fmt(r['n_eff'], 7, 1)}{_pct(r['mean'], 9, 2)}{_pct(r['ci_lo'], 9, 2)}"
            f"{_pct(r['ci_hi'], 9, 2)}{_pct(r['share_pos'], 7, 1)}{_fmt(r['ar1'], 6, 2)}"
            f"{_fmt(r['mean_n_themes'], 6, 1)}{_fmt(r['mean_n_stocks'], 7, 1)}"
        )
    for c in CANDIDATES:
        out.append(f"  {c} = {CANDIDATE_LABELS[c]}")
    return out


def _pair_table(res: L4StructureResult) -> list[str]:
    out = [
        "[2] 차 (X − Y) — 테마-월에서 차를 만들고 테마 동일가중 평균. **여기가 판정이다**",
        f"{'window':<8}{'h':>3} {'pair':<8}{'N':>5}{'drop':>5}{'N_eff':>7}{'mean%p':>9}"
        f"{'ci_lo':>9}{'ci_hi':>9}{'pos%':>7}{'AR1':>6}",
    ]
    s = res.pair_summary
    if s.empty:
        return [*out, "  —"]
    s = s[s["partition"] == PARTITION_ALL]
    for _, r in _sorted(s, "pair").iterrows():
        out.append(
            f"{r['window']:<8}{int(r['horizon']):>3} {r['pair']:<8}{int(r['n_months']):>5}"
            f"{int(r['n_months_dropped']):>5}{_fmt(r['n_eff'], 7, 1)}{_pct(r['mean'], 9, 2)}"
            f"{_pct(r['ci_lo'], 9, 2)}{_pct(r['ci_hi'], 9, 2)}"
            f"{_pct(r['share_pos'], 7, 1)}{_fmt(r['ar1'], 6, 2)}"
        )
    out.append("  주 창 · 12M 행이 판정이다. 나머지 창·호라이즌은 부차이며 판정에 들어가지 않는다.")
    return out


def _secondary_table(res: L4StructureResult) -> list[str]:
    out = ["[3] 부차 — 사망률 · 회전율 · B0 앵커/토크 구성 (판정에 들어가지 않는다, docs/15 §3.3)"]
    mo = res.mortality_summary
    if not mo.empty:
        mo = mo[(mo["partition"] == PARTITION_ALL) & (mo["horizon"] == GATE_HORIZON)]
        out.append("  12개월 내 사망률 (파산·규제폐지, docs/14 §2.5 정의)")
        for _, r in mo.sort_values(["window", "candidate"]).iterrows():
            out.append(
                f"    {r['window']:<8}{r['candidate']:<5}{_pct(r['mean'], 8, 3)}%"
                f"  [{_pct(r['ci_lo'], 7, 3)}, {_pct(r['ci_hi'], 7, 3)}]  N={int(r['n_months'])}"
            )
    tv = res.turnover_summary
    if not tv.empty:
        tv = tv[tv["partition"] == PARTITION_ALL]
        out.append(f"  회전율 ({res.meta['turnover_definition']})")
        for _, r in tv.sort_values(["window", "candidate"]).iterrows():
            out.append(
                f"    {r['window']:<8}{r['candidate']:<5}{_pct(r['mean'], 8, 2)}%"
                f"  N={int(r['n_months'])}"
            )
    cp = res.composition
    if not cp.empty:
        out.append(
            f"  B0 구성 (테마-월 {len(cp):,}): 앵커 평균 {cp['n_anchor'].mean():.2f}"
            f" · 토크 평균 {cp['n_torque'].mean():.2f}"
            f" · 앵커 비율 평균 {_pct(cp['anchor_share'].mean(), 6, 1)}%"
            f" · K 미달 {int((cp['n_selected'] < K).sum()):,}"
            f" · 빈자리 합계 {int(cp['n_empty_slots'].sum()):,}"
        )
        out.append(
            "  docs/06 §5 '비율을 보이게 한다' 의 소급판이다 — 기술통계이지 판정이 아니다."
        )
    return out


def _overfit_lines(res: L4StructureResult) -> list[str]:
    t = res.overfitting["trials"]
    out = ["[4] 과최적화 정산 (docs/15 §4.3) — **합격 기준에 들어가지 않는다**"]
    out.append(
        f"  시도 수 정산: docs/14 의 {t['docs14_base']} + §15 {t['docs15_subtotal']}"
        f" (= 수준 {t['levels']} + X−B3 {t['diff_x_minus_b3']} + B0−B1 {t['diff_b0_b1']}"
        f" + B0−B2 {t['diff_b0_b2']} + 사망률 {t['mortality']} + D1 {t['sensitivity_d1']})"
        f" = {t['docs15_declared_total']}"
    )
    out.append(
        f"  + 이 구현이 더 본 칸 {t['added_beyond_docs15']}"
        f" (회전율 {t['turnover_added']} — §8.1 U5 가 계상하라고 했다;"
        f" 1M 수준 {t['level_1m_for_pbo_added']} — §4.3 의 PBO 가 요구하는 입력인데 산식에 없다)"
        f" = **{t['total']}**. 524 는 하한이고 세지 않은 시도는 없는 시도가 아니다 (docs/10 §2.2)."
    )
    out.append(f"  선언만 세면 {t['declared_only']} (X−B3 셋 + B0−B1 하나). 둘 다 적는다.")
    out.append(
        f"  {'window':<8}{'series':<6}{'name':<8}{'h':>3}{'DSR N=4':>9}"
        f"{'DSR N=all':>10}{'N':>5}{'N_nonov':>8}"
    )
    for d in res.overfitting["dsr"]:
        if d["window"] != "primary" or d["horizon"] != GATE_HORIZON:
            continue
        out.append(
            f"  {d['window']:<8}{d['series']:<6}{d['name']:<8}{d['horizon']:>3}"
            f"{_fmt(d['dsr_declared_n4']['dsr_nonoverlapping'], 9, 3)}"
            f"{_fmt(d['dsr_n_total']['dsr_nonoverlapping'], 10, 3)}"
            f"{d['dsr_n_total']['n']:>5}{d['dsr_n_total']['n_nonoverlapping']:>8}"
        )
    out.append("  (전 창·호라이즌 DSR 은 overfitting.json)")
    for p in res.overfitting["pbo"]:
        out.append(
            f"  PBO {p['window']:<8} h={p['horizon']:>2} N={p['n_months']:>4} → "
            f"{_fmt(p.get('pbo', float('nan')), 6, 3)} {p.get('note', '')}"
        )
    out.append(f"  {res.overfitting['note']}")
    return out


def _exclusion_lines(res: L4StructureResult) -> list[str]:
    t = res.exclusions.get("totals", {})
    out = ["[5] 제외 (CLAUDE.md §2 · docs/15 §2.1) — 전문은 exclusions.json"]
    if t:
        out.append(
            f"  테마-월 {t['theme_months']:,} 중 n < {MIN_STOCKS_XS} 로 뺀 것"
            f" {t['theme_months_below_min_n']:,}"
            f" (남은 것 {t['theme_months'] - t['theme_months_below_min_n']:,})"
        )
        out.append(
            f"  적격 종목-월 {t['eligible_stock_months']:,}"
            f" · 그중 전진 수익률 없어 풀에서 빠진 것 {t['eligible_stock_months_no_forward']:,}"
        )
        out.append(
            f"  풀 종목-월 중 PIT 시총 결측 {t['pool_stock_months_no_mcap']:,}"
            f" (B1 만 영향 · docs/15 §8.1 U1)"
            f" · t_pct NaN {t['pool_stock_months_t_pct_nan']:,} (B2 만 영향)"
        )
        out.append(
            "  후보별 K 미달 테마-월: "
            + " · ".join(f"{c} {t[f'{c}_theme_months_short_of_k']:,}" for c in CANDIDATES)
        )
        out.append(
            "  후보별 0개 테마-월: "
            + " · ".join(f"{c} {t[f'{c}_theme_months_empty']:,}" for c in CANDIDATES)
        )
        out.append(
            "  사유별: " + " · ".join(f"{r} {t[f'short_{r}']:,}" for r in SHORTFALL_REASONS)
        )
    for k, val in res.exclusions.get("forward", {}).items():
        if k.startswith("h"):
            out.append(
                f"  전진 {k}: 가격 있는 종목-월 {val['stock_months_with_price']:,}"
                f" · 미완결 끝점 제외 {val['dropped_incomplete_endpoint']:,}"
                f" · 동결 적용 {val['frozen_last_price']:,}"
                f" · 유지 {val['kept']:,}"
            )
    return out


def _limitation_lines(res: L4StructureResult) -> list[str]:
    out = ["[6] 이 검정이 못 재는 것 (docs/15 §6) — 결과를 운용 성과로 옮겨 적지 않는다"]
    for line in res.meta.get("limitations", []):
        out.append(f"  - {line}")
    return out


_ORDER = {
    **{w: i for i, w in enumerate(WINDOWS)},
    **{c: i for i, c in enumerate(CANDIDATES)},
    **{p: i for i, p in enumerate(PAIR_NAMES)},
}


def _sorted(df: pd.DataFrame, key: str) -> pd.DataFrame:
    return df.sort_values(
        ["window", "horizon", key],
        key=lambda c: c.map(lambda x: _ORDER.get(x, 99)) if c.name in ("window", key) else c,
    )


# ---------------------------------------------------------------- 실행


def run_structures(
    *,
    out_root: Path | None = None,
    cache_root: Path | None = None,
    write: bool = True,
    force: bool = False,
    jobs: int | None = None,
    themes_filter: list[str] | None = None,
    max_months: int | None = None,
    progress: bool = True,
) -> L4StructureResult:
    """`msa backtest l4-structures` — `docs/14` 실행이 남긴 특성 패널 캐시를 재사용해 §2~§4 를 돈다.

    캐시는 `state/backtests/l4/<store_end>/cache/` (§7 "같은 캐시를 재사용한다"). 캐시가 있으면
    `build_features` 는 한 번도 불리지 않는다. `themes_filter`·`max_months` 는 **스모크 전용**이며
    주면 산출물이 `-smoke` 로 갈리고 판정에 `smoke` 표시가 붙는다.
    """
    p = paths()
    store = Store(p.duckdb)
    themes = load_themes()
    ms = membership_from_store(store, themes)
    se = store.store_end()
    store_end = pd.Timestamp(se) if se else pd.Timestamp.today().normalize()
    last_complete = (
        (store_end + pd.offsets.MonthEnd(0))
        if store_end.is_month_end
        else (store_end - pd.offsets.MonthEnd(1))
    )
    dates = month_grid(GRID_START, last_complete)
    n_total = {str(k): int(v) for k, v in ms.counts()["n_total"].astype(int).items()}
    all_ids = [t for t in themes.ids() if t in n_total]
    skipped = [(t, n_total[t]) for t in all_ids if n_total[t] < MIN_MEMBERS_POSSIBLE]
    ids = [t for t in all_ids if n_total[t] >= MIN_MEMBERS_POSSIBLE]
    smoke = themes_filter is not None or max_months is not None
    if themes_filter:
        ids = [t for t in ids if t in set(themes_filter)]
        if not ids:
            raise StoreError(f"--themes 로 남은 테마가 0개다: {themes_filter}")
    if max_months:
        dates = dates[-max_months:]
    tag = f"{store_end.date()}-smoke" if smoke else str(store_end.date())
    # 캐시는 **docs/14 실행의 것을 그대로 재사용한다** — 여기서 새 캐시 트리를 만들지 않는다
    cache_dir = (cache_root or p.backtests_l4) / str(store_end.date()) / "cache"
    if force and cache_dir.exists():
        for f in cache_dir.glob("*.parquet"):
            f.unlink()
    cache_dir.mkdir(parents=True, exist_ok=True)
    n_cached = len(list(cache_dir.glob("*.panel.parquet")))
    log.info(
        "l4-structures: 테마 %d (구성원 <%d 로 건너뜀 %d) × 월말 %d (%s~%s) · 캐시 패널 %d",
        len(ids),
        MIN_MEMBERS_POSSIBLE,
        len(skipped),
        len(dates),
        dates[0].date(),
        dates[-1].date(),
        n_cached,
    )
    n_rs = prewarm_rs_cache(store, list(dates), progress=progress) if n_cached < len(ids) else 0
    panel, counts = collect_panels(
        ids,
        list(dates),
        db_path=p.duckdb,
        state_dir=p.state,
        cache_dir=cache_dir,
        jobs=jobs if jobs is not None else default_jobs(),
        progress=progress,
    )
    tickers = sorted(set(panel["ticker"])) if not panel.empty else []
    if not tickers:
        raise StoreError("패널이 비었다 — 특성 표를 만든 테마-월이 하나도 없다")
    grid = pd.DatetimeIndex(sorted(pd.to_datetime(panel["date"]).unique()))
    close = monthly_close(store, tickers).reindex(index=grid).reindex(columns=tickers)
    deaths = death_months(store, tickers, grid)
    fwd = stock_forward(close, deaths, (PBO_HORIZON, *HORIZONS), last_complete=grid[-1])
    mcap = monthly_mcap(store, tickers, grid)
    res = run_structures_frames(panel, fwd, mcap)
    res.meta.update(
        store_end=str(store_end.date()),
        grid_first=str(grid[0].date()),
        grid_last=str(grid[-1].date()),
        n_months=len(grid),
        cache_dir=str(cache_dir),
        cached_panels_found=n_cached,
        rs_cache_months=n_rs,
        jobs=jobs if jobs is not None else default_jobs(),
        smoke=smoke,
        themes_skipped=skipped,
        n_themes_total=len(all_ids),
    )
    res.exclusions["theme_month_counts_from_features"] = {
        "theme_months_with_error": int((counts["error"].fillna("") != "").sum())
        if not counts.empty
        else 0
    }
    if smoke:
        res.verdict["smoke"] = True
        for r in res.verdict.get("primary_vs_b3_12m", {}).values():
            r["call"] = "smoke (판정 아님 — 표본을 줄였다)"
    store.close()
    if write:
        root = out_root if out_root is not None else p.backtests_l4_structures
        out_dir = write_outputs(res, root / tag)
        return replace(res, out_dir=out_dir)
    return res


def write_outputs(res: L4StructureResult, out_dir: Path) -> Path:
    d = write_snapshot(
        out_dir,
        frames={},
        texts={"report.txt": render_report(res)},
        jsons={
            "verdict.json": _plain(res.verdict),
            "overfitting.json": _plain(res.overfitting),
            "exclusions.json": _plain(res.exclusions),
            "meta.json": _plain(res.meta),
        },
    )
    for name, df in (
        ("spread_summary.csv", res.level_summary),
        ("spread_timeseries.csv", res.level_monthly),
        ("pairwise.csv", res.pair_summary),
        ("pairwise_timeseries.csv", res.pair_monthly),
        ("theme_month.csv", res.theme_month),
        ("mortality_summary.csv", res.mortality_summary),
        ("turnover_summary.csv", res.turnover_summary),
        ("b0_composition.csv", res.composition),
    ):
        df.to_csv(d / name, index=False)
    dump_json(d / "trials.json", _plain(count_trials()))
    log.info("l4-structures: 저장 %s", d)
    return d
