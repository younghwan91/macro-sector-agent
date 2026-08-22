"""스코어보드 — 지표 → 블록 점수 → `cycle_class` 가중합 → 순위·플래그.

`docs/02-cycle-state.md` §7·§8·§9. **방향과 가중치는 전부 선언값이다.**

## 방향 (높을수록 "사이클 저점에서 돌아서는 중" 쪽)

`ORIENTATION[indicator] = +1` 이면 값이 클수록, `−1` 이면 작을수록 블록 점수가 올라간다.
`SCORED[block]` 은 블록 점수에 **들어가는** 지표만 모은 것이다 — 문서가 점수 구성원을
명시한 블록(A·E)은 그 목록을, 나머지는 블록의 전 지표를 쓴다. 점수에 안 들어가는 지표도
리포트에는 그대로 실린다 (사이클 위치는 프로필 모양으로 읽는다, §8).

블록별 점수 구성 (문서 근거):

- **A** — `dd_10y`(−) · `months_since_peak`(+) · `liquidity_decay`(−). §A "세 지표의 정규화 평균".
- **B** — 5개 전부: `vcp_index`(+) `rv_ratio`(−) `range_compression`(−) `decline_angle`(+)
  `volume_dryup`(−).
- **C** — `mom_13612w` `rs_slope` `rs_trough_bounce` `breadth_200` `breadth_nh6m` `breadth_nhnl`
  `breadth_lead` `ew_vs_cw` (전부 +), `above_200`(+).
- **D** — 자기이력 백분위 5종: `ev_ebitda_pct` `ev_sales_pct` `pb_pct` `ev_replacement_pct`(−)
  `fcf_yield_pct`(+). §D "저평가 방향 백분위의 평균".
- **E** — `capex_to_da`(−) `asset_growth`(−) `exit_rate_3y`(+) `entry_rate_3y`(−). §E "점수 =
  capex_to_da 낮음 + asset_growth 음수 + exit_count 높음 + entry_count 낮음". 건수 대신 비율을
  쓰는 이유는 `blocks.py` 머리말.
- **F** — `rev_yoy_d2`(+) `ebitda_margin_d4`(+) `unit_cagr_5y`(+, 있을 때만). 서프라이즈·리비전은
  데이터 없음.

## 정규화
1. 지표별 **횡단면 백분위** (그 월말에 값이 있는 테마 사이의 rank/N, 방향 반영).
2. 블록 점수 = 들어간 지표 백분위의 평균. 지표가 하나도 없으면 블록 NaN.
3. 블록 점수를 다시 횡단면 백분위로 (§7 "각 블록을 0~1 로 정규화(pct 기반, 버킷 간 횡단면)").
4. `score = Σ w_class[block] × block_pct`. 블록이 빠지면 남은 가중치로 재정규화하고
   `blocks_missing` 플래그.

## 플래그 (§9)
- `n<min` 소표본: 생존 구성원 < `min_constituents`. 스코어는 계산하되 상위 K 선정에서 감점 —
  감점의 크기를 문서가 정하지 않았으므로 **순위에서는 빼지 않고 플래그만 단다.** 상위 K 선정은
  `top_k()` 가 소표본을 뒤로 보낸다 (점수는 건드리지 않는다).
- `SECULAR`: `secular_*` 클래스 — 게이트(`04`) 필요.
- `short_hist`: 자기이력 7년 미만 (z-score 대체).
- `breadth_lead=Nm`, `axis1:<status>`, `no_etf_proxy`, `blocks_missing=[..]`. `cpi_missing` 은
  전 테마 공통이라 행 플래그가 아니라 리포트 머리에 한 번 적는다 (표 열에는 남는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from msa.l1.blocks import Indicators
from msa.themes import BLOCK_WEIGHTS, ThemeSet

BLOCKS = ("A", "B", "C", "D", "E", "F")

ORIENTATION: dict[str, int] = {
    # A
    "dd_10y": -1,
    "dd_real": -1,
    "months_since_peak": +1,
    "liquidity_decay": -1,
    "count_decay": -1,
    # B
    "vcp_index": +1,
    "rv_ratio": -1,
    "range_compression": -1,
    "decline_angle": +1,
    "volume_dryup": -1,
    # C
    "mom_13612w": +1,
    "above_200": +1,
    "sma200_slope": +1,
    "rs_slope": +1,
    "rs_trough_bounce": +1,
    "breadth_200": +1,
    "breadth_nh6m": +1,
    "breadth_nhnl": +1,
    "breadth_lead": +1,
    "ew_vs_cw": +1,
    # D
    "ev_ebitda_pct": -1,
    "ev_sales_pct": -1,
    "pb_pct": -1,
    "fcf_yield_pct": +1,
    "ev_replacement_pct": -1,
    # E
    "capex_to_da": -1,
    "capex_to_da_qtrs_below1": +1,
    "asset_growth": -1,
    "roic_pct": -1,
    "roic_d2": +1,
    "share_change": +1,
    "net_debt_ebitda_trend": +1,
    "exit_rate_3y": +1,
    "entry_rate_3y": -1,
    # F
    "rev_yoy_d2": +1,
    "ebitda_margin_d4": +1,
    "unit_cagr_5y": +1,
    "unit_cagr_10y": +1,
}

SCORED: dict[str, tuple[str, ...]] = {
    "A": ("dd_10y", "months_since_peak", "liquidity_decay"),
    "B": ("vcp_index", "rv_ratio", "range_compression", "decline_angle", "volume_dryup"),
    "C": (
        "mom_13612w",
        "above_200",
        "rs_slope",
        "rs_trough_bounce",
        "breadth_200",
        "breadth_nh6m",
        "breadth_nhnl",
        "breadth_lead",
        "ew_vs_cw",
    ),
    "D": ("ev_ebitda_pct", "ev_sales_pct", "pb_pct", "fcf_yield_pct", "ev_replacement_pct"),
    "E": ("capex_to_da", "asset_growth", "exit_rate_3y", "entry_rate_3y"),
    "F": ("rev_yoy_d2", "ebitda_margin_d4", "unit_cagr_5y"),
}

for _b, _inds in SCORED.items():
    for _i in _inds:
        assert _i in ORIENTATION, (_b, _i)


def xs_pct(values: pd.Series, orientation: int) -> pd.Series:
    """횡단면 백분위 ∈ (0,1]. 값이 있는 테마 사이에서만. 동률은 평균 순위."""
    v = values.astype(float)
    if orientation < 0:
        v = -v
    n = v.notna().sum()
    if n == 0:
        return pd.Series(np.nan, index=values.index)
    return v.rank(method="average", pct=True)


@dataclass(frozen=True)
class Scoreboard:
    date: pd.Timestamp
    table: (
        pd.DataFrame
    )  # index theme; columns rank, score, A..F, A_pct..F_pct, flags, class, n_live ...
    indicator_pct: pd.DataFrame  # theme × scored indicator 백분위
    meta: dict[str, Any] = field(default_factory=dict)

    def top_k(self, k: int = 8) -> pd.DataFrame:
        """상위 K — 소표본 버킷은 뒤로 보낸다 (점수는 그대로)."""
        t = self.table.copy()
        t["_penal"] = t["small_sample"].astype(int)
        t = t.sort_values(["_penal", "score"], ascending=[True, False])
        return t.drop(columns="_penal").head(k)

    def render(self, top: int | None = None) -> str:
        t = self.table if top is None else self.table.head(top)
        lines = [
            f"테마 스코어보드 · {self.date.date()} · {len(self.table)} buckets",
            "",
            f"{'rank':>4}  {'theme':<26}{'class':<22}{'score':>6}  "
            + "  ".join(f"{b:>4}" for b in BLOCKS)
            + "   flags",
        ]
        for tid, r in t.iterrows():
            blocks = "  ".join(
                "   ." if pd.isna(r[f"{b}_pct"]) else f"{r[f'{b}_pct']:4.2f}" for b in BLOCKS
            )
            score = "  nan" if pd.isna(r["score"]) else f"{r['score']:5.2f}"
            rank = int(r["rank"]) if pd.notna(r["rank"]) else "—"
            lines.append(
                f"{rank:>4}  {tid:<26}{r['cycle_class']:<22}{score:>6}  {blocks}   {r['flags']}"
            )
        return "\n".join(lines)


def build_scoreboard(
    ind: Indicators, themes: ThemeSet, date: pd.Timestamp, *, n_live: pd.Series | None = None
) -> Scoreboard:
    """한 월말의 스코어보드."""
    actual_date = ind.bucket_for(pd.Timestamp(date))
    row = ind.monthly.xs(actual_date, level="date")
    by_id = themes.by_id()
    tids = [t for t in row.index if t in by_id]
    row = row.loc[tids]

    pct_cols: dict[str, pd.Series] = {}
    block_scores: dict[str, pd.Series] = {}
    n_ind: dict[str, pd.Series] = {}
    for b, inds in SCORED.items():
        parts = []
        for i in inds:
            if i not in row.columns:
                continue
            p = xs_pct(row[i], ORIENTATION[i])
            pct_cols[i] = p
            parts.append(p)
        if parts:
            mat = pd.concat(parts, axis=1)
            block_scores[b] = mat.mean(axis=1, skipna=True)
            n_ind[b] = mat.notna().sum(axis=1)
        else:
            block_scores[b] = pd.Series(np.nan, index=row.index)
            n_ind[b] = pd.Series(0, index=row.index)
    block_pct = {b: xs_pct(s, +1) for b, s in block_scores.items()}

    cls = pd.Series({t: by_id[t].cycle_class for t in tids})
    W = pd.DataFrame({b: cls.map(lambda c, b=b: BLOCK_WEIGHTS[c][b]) for b in BLOCKS})
    BP = pd.DataFrame(block_pct)[list(BLOCKS)]
    avail = BP.notna()
    w_eff = W.where(avail)
    w_sum = w_eff.sum(axis=1)
    score = (BP.fillna(0.0) * W).sum(axis=1) / w_sum.replace(0.0, np.nan)

    tab = pd.DataFrame(index=pd.Index(tids, name="theme"))
    tab["cycle_class"] = cls
    tab["score"] = score
    for b in BLOCKS:
        tab[b] = block_scores[b]
        tab[f"{b}_pct"] = BP[b]
        tab[f"{b}_n_ind"] = n_ind[b]
    tab["blocks_missing"] = [",".join(b for b in BLOCKS if not avail.loc[t, b]) for t in tids]
    if n_live is not None:
        tab["n_live"] = n_live.reindex(tids)
    else:
        tab["n_live"] = np.nan
    tab["min_constituents"] = [by_id[t].min_constituents for t in tids]
    tab["small_sample"] = tab["n_live"].notna() & (tab["n_live"] < tab["min_constituents"])
    tab["secular"] = cls.str.startswith("secular")
    tab["breadth_lead"] = row.get("breadth_lead", np.nan)
    tab["axis1_status"] = row.get("axis1_status", None)
    tab["verdict_post_ss"] = row.get("verdict_post_ss", None)
    tab["axis1_contested"] = row.get("axis1_contested", np.nan)
    tab["ebitda_nonpos_share"] = row.get("ebitda_nonpos_share", np.nan)
    short = pd.Series(False, index=tab.index)
    for c in ("short_hist_D", "short_hist_roic", "short_hist_margin", "short_hist_range"):
        if c in row:
            short |= row[c].fillna(False).astype(bool)
    tab["short_hist"] = short
    tab["no_etf_proxy"] = [by_id[t].etf_proxy is None for t in tids]
    tab["cpi_missing"] = (
        row["cpi_missing"].fillna(False).astype(bool) if "cpi_missing" in row else False
    )
    tab["flags"] = [_flags(tab.loc[t]) for t in tids]
    tab = tab.sort_values("score", ascending=False, na_position="last")
    tab["rank"] = np.where(tab["score"].notna(), np.arange(1, len(tab) + 1), np.nan)
    cols = ["rank"] + [c for c in tab.columns if c != "rank"]
    tab = tab[cols]
    meta = {
        "date": str(pd.Timestamp(actual_date).date()),
        "requested": str(pd.Timestamp(date).date()),
        "n": len(tab),
    }
    return Scoreboard(
        date=pd.Timestamp(actual_date), table=tab, indicator_pct=pd.DataFrame(pct_cols), meta=meta
    )


def _flags(r: pd.Series) -> str:
    f: list[str] = []
    if r["small_sample"]:
        f.append(f"n={int(r['n_live'])} 소표본")
    if r["secular"]:
        f.append("SECULAR — 게이트 필요")
    if pd.notna(r["breadth_lead"]) and r["breadth_lead"] > 0:
        f.append(f"breadth_lead={int(r['breadth_lead'])}m")
    st = r["axis1_status"]
    if isinstance(st, str) and st != "not_declared":
        v = r["verdict_post_ss"]
        f.append(f"axis1:{st}" + (f"/{v}" if isinstance(v, str) and st.startswith("ok") else ""))
        if r["axis1_contested"] == 1.0:
            f.append("axis1_contested")
    if r["short_hist"]:
        f.append("short_hist")
    if r["blocks_missing"]:
        f.append(f"blocks_missing={r['blocks_missing']}")
    if r["no_etf_proxy"]:
        f.append("no_etf_proxy")
    return "[" + "; ".join(f) + "]" if f else ""


def scoreboard_history(ind: Indicators, themes: ThemeSet) -> pd.DataFrame:
    """전 월말의 스코어보드를 쌓은 긴 표 — M3.5 백테스트 입력.

    열: score, A..F, A_pct..F_pct, cycle_class.
    """
    dates = ind.monthly.index.get_level_values("date").unique().sort_values()
    frames = []
    for d in dates:
        sb = build_scoreboard(ind, themes, d)
        t = sb.table[["score", "cycle_class", *BLOCKS, *[f"{b}_pct" for b in BLOCKS]]].copy()
        t["date"] = d
        frames.append(t.reset_index())
    out = pd.concat(frames, ignore_index=True).set_index(["date", "theme"]).sort_index()
    return out
