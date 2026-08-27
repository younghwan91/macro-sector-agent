"""M3.6 · 설계 질문 1 의 사전 등록 검정 — A(망각)를 가산 항이 아니라 **후보 집합의 조건**으로 두는
두 대안 구조(S1·S2)를 관문 0 과 같은 규칙으로 잰다 (`docs/12-design-question-a-block.md` §4).

**이 모듈은 선언값을 바꾸지 않는다.** `scoreboard.py` 의 S0(현행)은 그대로이고, 여기서는 같은 블록
백분위(`A_pct..F_pct`)와 같은 클래스 가중치로 **집계 방식만 다른** 두 점수를 만들어 백테스트 기계
(`backtest.py`)에 넣는다. 후보·임계·합격 기준은 `docs/12` §4.1–4.2 에 실행 전에 고정된 것이며,
결과를 보고 옮기지 않는다.

| 후보 | 정의 (docs/12 §4.1 그대로) |
|---|---|
| S0 | 현행 `score` (`scoreboard_history`) |
| S1 | 후보 집합 `G(t) = {dd_10y ≤ −0.50 AND months_since_peak ≥ 12}`.
|    | 점수 = `Σ_{b∈B..F} w_class[b]·pct_b` 를 가중치 재정규화. G 밖 = NaN(순위 없음) |
| S2 | 풀 점수 `P = mean(pct_A, pct_B)`, 타이밍 점수 `T = Σ_{b∈C,E,F} w_class[b]·pct_b` 재정규화.
|    | 자격 `P ≥ 0.5`. 점수 = T, 자격 미달 = NaN |

해석상 고정한 것(문서가 명시하지 않아 여기서 선언하고 결과와 무관하게 둔다):
- `pct_b` 는 **전 우주 횡단면 백분위**(S0 과 같은 값)다. G/자격 집합 안에서 다시 백분위를 매기지
  않는다 — 문서가 "G 밖의 테마는 순위 없음" 이라고만 했고, 재백분위는 또 하나의 선택이기 때문.
- S2 의 `P` 는 A·B 중 하나가 결측이면 남은 하나(nanmean)다. 둘 다 결측이면 자격 없음.
- 재정규화는 S0 과 같은 규칙(`_weighted_score`): 결측 블록의 가중치를 남은 블록에 비례 배분.
- 횡단면 최소 20 은 **후보 집합 안의 테마 수**로 센다 (S1 은 G(t) 가 20 미만인 달이 빠지고, 빠진
  달 수를 보고한다 — `ic` 긴 표의 `n` 과 `n_months_dropped`).
- 시도 수: 608 + 후보 2 × 창 2 × 호라이즌 3 × (IC + 스프레드 2) = **632** (`docs/12` §4.2).

M3.7 (2026-08-24) — **테마 선정 점수를 `C 단독` 으로 바꿀지**의 사전 등록 검정을 같은 모듈에 더한다
(`docs/17-l1-score-structure-preregistration.md`). 후보를 둘 더하고, 위의 형식을 그대로 따른다.

| 후보 | 정의 (docs/17 §2 그대로) |
|---|---|
| S3 | S2 와 **같은 자격**(`pool = mean(A_pct,B_pct) ≥ 0.5`). 점수 = `C_pct` (가중치 없음 — |
|    | 블록이 하나뿐이라 재정규화가 무의미하다) |
| S2ʹ (코드 `S2p`) | S2 와 같은 자격. 점수 = `Σ_{C,E} w·pct` 재정규화 (F 만 뺀 것) |

M3.7 의 1차 지표는 IC 가 아니라 **짝지은 스프레드 차**다: 주 창·12M·상위 8 − 하위 8 초과수익
스프레드의 월별 차 `X − S2` 를 `summarize_spread`(= 같은 12개월 블록 부트스트랩 2000회 시드 0)에
넣고 95% CI 하한 > 0 이면 "S2 를 이겼다". 새 통계 함수는 만들지 않았다 — 차 시계열을 같은 긴 표
형식으로 만들어 같은 요약 함수에 넣는다.

시도 수: 632 + 후보 2 × 창 2 × 호라이즌 3 × (IC + 스프레드 2) + 차 2 × 창 2 × 호라이즌 3
= 632 + 24 + 12 = **668** (`docs/17` §6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from msa.l1.backtest import (
    GATE_HORIZON,
    HORIZONS,
    PARTITION_ALL,
    PBO_HORIZON,
    WINDOWS,
    Forward,
    _window_slice,
    count_trials,
    dsr_of_series,
    forward_excess,
    pbo_of_spreads,
    rank_ic_series,
    small_sample_history,
    spread_series,
    summarize_ic,
    summarize_spread,
)
from msa.l1.blocks import Indicators
from msa.l1.panel import ThemePanel
from msa.l1.scoreboard import BLOCKS, POOL_MIN, _weighted_score, _weights, scoreboard_history
from msa.themes import ThemeSet

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 선언 (docs/12 §4.1 — 불변)

S1_DD_MAX = -0.50  # dd_10y ≤ −50%  (docs/02 §A "사용자 기준선 −50%")
S1_MONTHS_MIN = 12  # months_since_peak ≥ 12 (docs/02 §A "6개월=패닉 … 48개월=망각" 의 하한)
#: **`scoreboard.POOL_MIN` 을 그대로 쓴다 — 같은 값을 두 곳에 두지 않는다.**
#: S2 구조 검정의 자격 컷은 정의상 실제 스코어보드의 자격 컷과 같아야 한다. 따로 두면
#: 한쪽만 바꿔도 아무도 모르고, 그때 검정은 실제로 안 쓰는 규칙을 재게 된다 (2026-08-28).
S2_POOL_MIN = POOL_MIN
S1_BLOCKS: tuple[str, ...] = ("B", "C", "D", "E", "F")
S2_POOL_BLOCKS: tuple[str, ...] = ("A", "B")
S2_TIMING_BLOCKS: tuple[str, ...] = ("C", "E", "F")

# --- M3.7 (docs/17 §2) — 자격은 S2 와 같고 점수만 다르다. 값은 전부 이미 선언된 것에서 온다.
S3_BLOCK = "C"  # 점수 = C_pct 그대로. 가중치 없음 (블록 하나에 재정규화는 항등)
S2P_TIMING_BLOCKS: tuple[str, ...] = ("C", "E")  # S2 에서 F 만 뺀 것

STRUCTURES: tuple[str, ...] = ("S0", "S1", "S2", "S3", "S2p")
CANDIDATES: tuple[str, ...] = ("S1", "S2")
#: M3.7 후보 — 짝지은 스프레드 차의 기준은 항상 현행 S2 다 (docs/17 §4).
CANDIDATES_M37: tuple[str, ...] = ("S3", "S2p")
DIFF_BASE = "S2"
DIFF_PAIRS: tuple[tuple[str, str], ...] = tuple((c, DIFF_BASE) for c in CANDIDATES_M37)
#: PBO 의 "전략" 집합 — 이 검정이 고르는 세 구조 (S1 은 자격이 달라 짝이 맞지 않아 뺀다).
PBO_VARIANTS: tuple[str, ...] = ("S2", "S3", "S2p")

N_TRIALS_ADDED = len(CANDIDATES) * len(WINDOWS) * len(HORIZONS) * 2  # = 24 (docs/12 §4.2)
N_TRIALS_ADDED_M37 = len(CANDIDATES_M37) * len(WINDOWS) * len(HORIZONS) * 2 + len(DIFF_PAIRS) * len(
    WINDOWS
) * len(HORIZONS)  # = 24 + 12 = 36 (docs/17 §6)


def structure_scores(
    ind: Indicators, themes: ThemeSet, scores: pd.DataFrame | None = None
) -> pd.DataFrame:
    """(date, theme) 긴 표: `S0`·`S1`·`S2`·`S3`·`S2p` 점수, `S1_eligible`·`S2_eligible`, `S2_pool`.

    `scores` 는 `scoreboard_history(ind, themes)` (없으면 계산). 블록 백분위 `*_pct` 와 클래스는
    거기서 그대로 가져온다 — S0 과 같은 입력이다. `S3`·`S2p` 는 `S2` 와 **자격이 같고** 점수만
    다르다 (docs/17 §2) — 그래서 세 후보의 유효 월·우주가 정확히 같고 스프레드를 짝지을 수 있다.
    """
    sb = scoreboard_history(ind, themes) if scores is None else scores
    BP = sb[[f"{b}_pct" for b in BLOCKS]].copy()
    BP.columns = list(BLOCKS)
    W = _weights(sb["cycle_class"])

    # --- S1: 절대 게이트 + A 를 뺀 재정규화 가중합
    m = ind.monthly.reindex(sb.index)
    g = (m["dd_10y"] <= S1_DD_MAX) & (m["months_since_peak"] >= S1_MONTHS_MIN)
    g = g.fillna(False).astype(bool)
    BP1 = BP[list(S1_BLOCKS)]
    W1 = W[list(S1_BLOCKS)]
    s1, _ = _weighted_score(BP1, W1)
    s1 = s1.where(g)

    # --- S2: 풀 점수 자격 + 타이밍 점수
    pool = BP[list(S2_POOL_BLOCKS)].mean(axis=1, skipna=True)  # 둘 다 NaN 이면 NaN
    elig2 = (pool >= S2_POOL_MIN).fillna(False).astype(bool)
    s2, _ = _weighted_score(BP[list(S2_TIMING_BLOCKS)], W[list(S2_TIMING_BLOCKS)])
    s2 = s2.where(elig2)

    # --- M3.7: 같은 자격, 점수만 다르다 (docs/17 §2)
    s3 = BP[S3_BLOCK].where(elig2)  # C_pct 그대로 — 가중치·재정규화 없음
    s2p, _ = _weighted_score(BP[list(S2P_TIMING_BLOCKS)], W[list(S2P_TIMING_BLOCKS)])
    s2p = s2p.where(elig2)

    out = pd.DataFrame(
        {
            "S0": sb["score_s0"] if "score_s0" in sb.columns else sb["score"],
            "S1": s1,
            "S2": s2,
            "S3": s3,
            "S2p": s2p,
            "S1_eligible": g,
            "S2_eligible": elig2,
            "S2_pool": pool,
            "cycle_class": sb["cycle_class"],
        },
        index=sb.index,
    )
    out.index.names = ["date", "theme"]
    return out.sort_index()


@dataclass(frozen=True)
class StructureResult:
    scores: pd.DataFrame
    ic: pd.DataFrame
    ic_summary: pd.DataFrame
    spread: pd.DataFrame
    spread_summary: pd.DataFrame
    eligibility: pd.DataFrame  # 월말별 G(t)·자격 집합 크기
    dsr: list[dict[str, Any]]
    verdicts: dict[str, Any]
    spread_diff: pd.DataFrame = field(default_factory=pd.DataFrame)  # M3.7 짝지은 차 (긴 표)
    spread_diff_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    pbo: list[dict[str, Any]] = field(default_factory=list)  # M3.7 CSCV (판정 아님)
    verdicts_m37: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


def _eligibility_table(sc: pd.DataFrame) -> pd.DataFrame:
    g = sc.groupby(level="date")
    tab = pd.DataFrame(
        {
            "n_scored_S0": g["S0"].count(),
            "n_S1": g["S1_eligible"].sum().astype(int),
            "n_S2": g["S2_eligible"].sum().astype(int),
        }
    )
    tab.index.name = "date"
    return tab


def spread_diff_series(sp: pd.DataFrame) -> pd.DataFrame:
    """M3.7 1차 지표 — 후보 − S2 의 **같은 달 짝지은** 스프레드 차 (긴 표).

    `spread_series` 가 낸 긴 표를 (date, horizon) × variant 로 펴서 뺀다. 열 이름·형식은 원 표와
    같게 두므로 `summarize_spread` 가 그대로 먹는다 — **새 통계 함수는 없다**(docs/17 §3). 세 후보는
    자격이 같아 같은 달에 같은 우주를 보므로(`structure_scores`) 차는 순위 규칙만의 차다.
    어느 한쪽이 NaN 인 달은 차도 NaN 이고 요약에서 `n_months_dropped` 로 센다.
    """
    if sp.empty:
        return sp
    wide = sp.pivot_table(index=["date", "horizon"], columns="variant", values="spread")
    uni = sp.pivot_table(index=["date", "horizon"], columns="variant", values="n_universe")
    sml = sp.pivot_table(index=["date", "horizon"], columns="variant", values="n_small_excluded")
    out: list[pd.DataFrame] = []
    for a, b in DIFF_PAIRS:
        d = (wide[a] - wide[b]).rename("spread").reset_index()
        d["variant"] = f"{a}-{b}"
        d["ret_top"] = float("nan")
        d["ret_bot"] = float("nan")
        d["n_universe"] = uni[a].to_numpy()
        d["n_small_excluded"] = sml[a].to_numpy()
        out.append(d)
    return (
        pd.concat(out, ignore_index=True)
        .sort_values(["horizon", "date"], kind="stable")
        .reset_index(drop=True)
    )


def _diff_verdict(row: pd.Series) -> str:
    """docs/17 §4 — 한쪽만 본다: 하한 > 0 이면 이겼다, 상한 < 0 이면 졌다, 나머지는 구분 안 됨."""
    lo, hi = float(row["ci_lo"]), float(row["ci_hi"])
    if np.isnan(lo) or np.isnan(hi):
        return "undetermined"
    if lo > 0:
        return "beats_S2"
    if hi < 0:
        return "worse_than_S2"
    return "indistinguishable"


def run_structure_backtest(
    panel: ThemePanel,
    ind: Indicators,
    themes: ThemeSet,
    *,
    scores: pd.DataFrame | None = None,
    fwd: Forward | None = None,
    n_trials_base: int | None = None,
) -> StructureResult:
    """S0·S1·S2·S3·S2ʹ 를 관문 0 과 같은 기계로 잰다.

    판정 둘이 **서로 다른 눈금**으로 붙어 있고 섞지 않는다.
    - M3.6 (`docs/12` §4.2): 주 창·12M·후보 rank-IC 의 95% CI 하한 > 0 → 후보별 pass/fail.
    - M3.7 (`docs/17` §4): 주 창·12M·**짝지은 스프레드 차** `X − S2` 의 95% CI 하한 > 0 → S2 를
      이겼다. 0 을 포함하면 구분되지 않는다, 상한 < 0 이면 S2 보다 나빴다.
    """
    sc = structure_scores(ind, themes, scores)
    by_id = themes.by_id()
    classes = pd.Series(
        {t: by_id[t].cycle_class for t in sc.index.get_level_values("theme").unique() if t in by_id}
    )
    if fwd is None:
        fwd = forward_excess(panel, (PBO_HORIZON, *HORIZONS))
    small = small_sample_history(panel, themes)
    log.info("structures: rank-IC (%s)", "·".join(STRUCTURES))
    ic = rank_ic_series(sc, fwd, classes, variants=STRUCTURES, horizons=HORIZONS)
    log.info("structures: 스프레드")
    sp = spread_series(sc, fwd, small, variants=STRUCTURES)
    ic_sum = summarize_ic(ic)
    sp_sum = summarize_spread(sp)
    log.info("structures: 짝지은 스프레드 차 (M3.7)")
    spd = spread_diff_series(sp)
    spd_sum = summarize_spread(spd)
    elig = _eligibility_table(sc)

    base = count_trials()["total"] if n_trials_base is None else n_trials_base
    n_total = base + N_TRIALS_ADDED + N_TRIALS_ADDED_M37
    dsr: list[dict[str, Any]] = []
    for w in WINDOWS:
        ic_w = _window_slice(ic[ic["partition"] == PARTITION_ALL], w)
        sp_w = _window_slice(sp, w)
        spd_w = _window_slice(spd, w) if not spd.empty else spd
        for v in [f"{a}-{b}" for a, b in DIFF_PAIRS]:
            for h in HORIZONS:
                sd = (
                    spd_w[(spd_w["variant"] == v) & (spd_w["horizon"] == h)]
                    .set_index("date")["spread"]
                    .sort_index()
                )
                dsr.append(
                    {
                        "window": w,
                        "variant": v,
                        "horizon": h,
                        "series": "spread_diff",
                        "dsr_n_total": dsr_of_series(sd, n_total, horizon=h),
                        "n_trials": n_total,
                    }
                )
        for v in STRUCTURES:
            for series, frame, hs in (("ic", ic_w, HORIZONS), ("spread", sp_w, HORIZONS)):
                for h in hs:
                    s = (
                        frame[(frame["variant"] == v) & (frame["horizon"] == h)]
                        .set_index("date")[series]
                        .sort_index()
                    )
                    dsr.append(
                        {
                            "window": w,
                            "variant": v,
                            "horizon": h,
                            "series": series,
                            "dsr_n_total": dsr_of_series(s, n_total, horizon=h),
                            "n_trials": n_total,
                        }
                    )

    verdicts: dict[str, Any] = {
        "rule": (
            "주 창(2011–) · 12M · 후보 점수의 rank-IC 평균 95% 블록부트스트랩 CI 하한 > 0 "
            "(docs/12 §4.2)"
        ),
        "n_trials": n_total,
        "n_trials_base": base,
        "n_trials_added": N_TRIALS_ADDED,
        "n_trials_added_m37": N_TRIALS_ADDED_M37,
    }
    for v in STRUCTURES:
        cell = ic_sum[
            (ic_sum["window"] == "primary")
            & (ic_sum["horizon"] == GATE_HORIZON)
            & (ic_sum["variant"] == v)
            & (ic_sum["partition"] == PARTITION_ALL)
        ]
        if cell.empty:
            verdicts[v] = {"gate": "undetermined"}
            continue
        r = cell.iloc[0]
        d = [
            x
            for x in dsr
            if x["window"] == "primary"
            and x["variant"] == v
            and x["horizon"] == GATE_HORIZON
            and x["series"] == "ic"
        ]
        spc = sp_sum[
            (sp_sum["window"] == "primary")
            & (sp_sum["horizon"] == GATE_HORIZON)
            & (sp_sum["variant"] == v)
        ]
        verdicts[v] = {
            "gate": "pass" if bool(r["ci_lo"] > 0) else "fail",
            "mean_ic": float(r["mean"]),
            "ci": [float(r["ci_lo"]), float(r["ci_hi"])],
            "n_months": int(r["n_months"]),
            "n_months_dropped": int(r["n_months_dropped"]),
            "n_eff": float(r["n_eff"]),
            "mean_n_themes": float(r.get("mean_n_themes", float("nan"))),
            "dsr_nonoverlapping_n_total": d[0]["dsr_n_total"]["dsr_nonoverlapping"] if d else None,
            "spread_12m": {
                "mean": float(spc.iloc[0]["mean"]),
                "ci": [float(spc.iloc[0]["ci_lo"]), float(spc.iloc[0]["ci_hi"])],
                "n_months": int(spc.iloc[0]["n_months"]),
            }
            if not spc.empty
            else None,
        }
    # ---------------------------------------------------------------- M3.7 판정 (docs/17 §4)
    log.info("structures: PBO (M3.7 후보 %s)", "·".join(PBO_VARIANTS))
    pbo = [
        pbo_of_spreads(sp, window=w, horizon=h, variants=PBO_VARIANTS)
        for w in WINDOWS
        for h in (PBO_HORIZON, *HORIZONS)
    ]
    verdicts_m37: dict[str, Any] = {
        "rule": (
            "주 창(2011–) · 12M · 짝지은 스프레드 차(후보 − S2)의 평균에 대한 95% 12개월 "
            "블록부트스트랩 CI 하한 > 0 이면 'S2 를 이겼다' (docs/17 §4). DSR·PBO 는 싣되 "
            "합격 기준에 넣지 않는다"
        ),
        "base": DIFF_BASE,
        "n_trials": n_total,
        "n_trials_base": base,
        "n_trials_added_m36": N_TRIALS_ADDED,
        "n_trials_added_m37": N_TRIALS_ADDED_M37,
    }
    for a, b in DIFF_PAIRS:
        name = f"{a}-{b}"
        cell = spd_sum[
            (spd_sum["window"] == "primary")
            & (spd_sum["horizon"] == GATE_HORIZON)
            & (spd_sum["variant"] == name)
        ]
        if cell.empty:
            verdicts_m37[name] = {"verdict": "undetermined"}
            continue
        r = cell.iloc[0]
        d = [
            x
            for x in dsr
            if x["window"] == "primary"
            and x["variant"] == name
            and x["horizon"] == GATE_HORIZON
            and x["series"] == "spread_diff"
        ]
        verdicts_m37[name] = {
            "verdict": _diff_verdict(r),
            "mean": float(r["mean"]),
            "ci": [float(r["ci_lo"]), float(r["ci_hi"])],
            "n_months": int(r["n_months"]),
            "n_months_dropped": int(r["n_months_dropped"]),
            "n_eff": float(r["n_eff"]),
            "share_pos": float(r["share_pos"]),
            "dsr_nonoverlapping_n_total": d[0]["dsr_n_total"]["dsr_nonoverlapping"] if d else None,
            "dsr_overlapping_n_total": d[0]["dsr_n_total"]["dsr_overlapping"] if d else None,
        }
    verdicts_m37["pbo_primary_12m"] = next(
        (x.get("pbo") for x in pbo if x["window"] == "primary" and x["horizon"] == GATE_HORIZON),
        None,
    )

    meta = {
        "candidates": list(CANDIDATES),
        "candidates_m37": list(CANDIDATES_M37),
        "s1": {
            "dd_10y_max": S1_DD_MAX,
            "months_since_peak_min": S1_MONTHS_MIN,
            "blocks": list(S1_BLOCKS),
        },
        "s2": {
            "pool_blocks": list(S2_POOL_BLOCKS),
            "pool_min": S2_POOL_MIN,
            "timing_blocks": list(S2_TIMING_BLOCKS),
        },
        "s3": {"block": S3_BLOCK, "weighting": "없음 — C_pct 그대로", "eligibility": "S2 와 동일"},
        "s2p": {
            "pool_blocks": list(S2_POOL_BLOCKS),
            "pool_min": S2_POOL_MIN,
            "timing_blocks": list(S2P_TIMING_BLOCKS),
            "eligibility": "S2 와 동일",
        },
        "pbo_variants": list(PBO_VARIANTS),
        "pct_basis": "전 우주 횡단면 백분위 (S0 과 동일; 후보 집합 안 재백분위 없음)",
        "eligibility": {
            "S1_months_lt_20": int((elig["n_S1"] < 20).sum()),
            "S2_months_lt_20": int((elig["n_S2"] < 20).sum()),
            "S1_mean_n": float(elig["n_S1"].mean()),
            "S2_mean_n": float(elig["n_S2"].mean()),
            "months": len(elig),
        },
    }
    return StructureResult(
        scores=sc,
        ic=ic,
        ic_summary=ic_sum,
        spread=sp,
        spread_summary=sp_sum,
        eligibility=elig,
        dsr=dsr,
        verdicts=verdicts,
        spread_diff=spd,
        spread_diff_summary=spd_sum,
        pbo=pbo,
        verdicts_m37=verdicts_m37,
        meta=meta,
    )


def render_structure_report(res: StructureResult) -> str:
    v = res.verdicts
    L = [
        "M3.6 · 설계 질문 1 — A(망각) 집계 구조 검정 (docs/12 §4, 사전 등록)",
        f"규칙: {v['rule']}",
        f"시도 수: {v['n_trials']} (= {v['n_trials_base']} + {v['n_trials_added']}"
        f" + {v['n_trials_added_m37']}) — M3.7 이 붙으면서 DSR 정산의 분모가 같이 늘었다",
        "",
        f"{'후보':<4} {'판정':<5} {'IC(12M,주창)':>14} {'95% CI':>22} {'N':>4} {'N_eff':>6} "
        f"{'빠진달':>6} {'평균n':>6} {f'DSR({v["n_trials"]})':>9} {'spread12M':>10}",
    ]
    for s in STRUCTURES:
        r = v.get(s, {})
        if r.get("gate") in (None, "undetermined"):
            L.append(f"{s:<4} {'?':<5}")
            continue
        sp = r.get("spread_12m") or {}
        dsr = r.get("dsr_nonoverlapping_n_total")
        L.append(
            f"{s:<4} {r['gate'].upper():<5} {r['mean_ic']:>+14.4f} "
            f"[{r['ci'][0]:+.4f}, {r['ci'][1]:+.4f}] {r['n_months']:>4} {r['n_eff']:>6.1f} "
            f"{r['n_months_dropped']:>6} {r['mean_n_themes']:>6.1f} "
            f"{(dsr if dsr is not None and not np.isnan(dsr) else float('nan')):>9.3f} "
            f"{(sp.get('mean', float('nan')) * 100):>+9.1f}%p"
        )
    m = res.meta["eligibility"]
    L += [
        "",
        f"후보 집합 크기: S1 평균 {m['S1_mean_n']:.1f} 테마/월 "
        f"(20 미만 {m['S1_months_lt_20']}/{m['months']} 달) · "
        f"S2 평균 {m['S2_mean_n']:.1f} (20 미만 {m['S2_months_lt_20']} 달)",
        f"백분위 기준: {res.meta['pct_basis']}",
        "",
        "전 창·호라이즌 IC 요약 (partition=all):",
    ]
    sub = res.ic_summary[res.ic_summary["partition"] == PARTITION_ALL]
    for w in WINDOWS:
        for h in HORIZONS:
            row = []
            for s in STRUCTURES:
                c = sub[(sub["window"] == w) & (sub["horizon"] == h) & (sub["variant"] == s)]
                if c.empty:
                    row.append(f"{s}: —")
                else:
                    rr = c.iloc[0]
                    row.append(f"{s}: {rr['mean']:+.3f} [{rr['ci_lo']:+.3f},{rr['ci_hi']:+.3f}]")
            L.append(f"  {w:<8} {h:>2}M  " + " · ".join(row))
    L += _m37_lines(res)
    L += [
        "",
        "이 표로 가중치·임계·후보를 옮기지 않는다 (CLAUDE.md §1, docs/12 §4.4, docs/17 §7). "
        "합격은 '한 경로에서 어긋나지 않았다' 이지 '맞았다' 가 아니다.",
    ]
    return "\n".join(L)


_VERDICT_KO = {
    "beats_S2": "S2 를 이겼다",
    "worse_than_S2": "S2 보다 나빴다",
    "indistinguishable": "구분되지 않는다",
    "undetermined": "판정 불가",
}


def _m37_lines(res: StructureResult) -> list[str]:
    """M3.7 — 짝지은 스프레드 차 판정 표 (docs/17 §4)."""
    v = res.verdicts_m37
    if not v:
        return []
    L = [
        "",
        "─" * 96,
        "M3.7 · 테마 선정 점수를 C 단독으로 바꿀지 (docs/17, 사전 등록)",
        f"규칙: {v['rule']}",
        f"시도 수: {v['n_trials']} (= {v['n_trials_base']} + {v['n_trials_added_m36']}"
        f" + {v['n_trials_added_m37']})",
        "",
        f"{'차':<9} {'판정':<14} {'평균(12M,주창)':>15} {'95% CI':>22} {'N':>4} {'N_eff':>6} "
        f"{'>0 비율':>7} {'DSR비중첩':>9}",
    ]
    for a, b in DIFF_PAIRS:
        r = v.get(f"{a}-{b}", {})
        if r.get("verdict") in (None, "undetermined"):
            L.append(f"{a + '−' + b:<9} {'판정 불가':<14}")
            continue
        dsr = r.get("dsr_nonoverlapping_n_total")
        dsr_s = f"{dsr:>9.3f}" if isinstance(dsr, float) and not np.isnan(dsr) else f"{'—':>9}"
        L.append(
            f"{a + '−' + b:<9} {_VERDICT_KO[r['verdict']]:<14} {r['mean'] * 100:>+14.2f}%p "
            f"[{r['ci'][0] * 100:+.2f}, {r['ci'][1] * 100:+.2f}]%p {r['n_months']:>4} "
            f"{r['n_eff']:>6.1f} {r['share_pos']:>7.0%} {dsr_s}"
        )
    L += ["", "부차 (판정 아님) — 창·호라이즌별 차 평균 [95% CI], %p:"]
    sd = res.spread_diff_summary
    for w in WINDOWS:
        for h in HORIZONS:
            row = []
            for a, b in DIFF_PAIRS:
                c = sd[(sd["window"] == w) & (sd["horizon"] == h) & (sd["variant"] == f"{a}-{b}")]
                if c.empty:
                    row.append(f"{a}−{b}: —")
                else:
                    rr = c.iloc[0]
                    row.append(
                        f"{a}−{b}: {rr['mean'] * 100:+.2f} "
                        f"[{rr['ci_lo'] * 100:+.2f},{rr['ci_hi'] * 100:+.2f}]"
                    )
            L.append(f"  {w:<8} {h:>2}M  " + " · ".join(row))
    L += ["", "후보 자체의 스프레드 (참고) — 주 창, %p:"]
    sp = res.spread_summary
    for h in HORIZONS:
        row = []
        for x in PBO_VARIANTS:
            c = sp[(sp["window"] == "primary") & (sp["horizon"] == h) & (sp["variant"] == x)]
            if not c.empty:
                rr = c.iloc[0]
                row.append(
                    f"{x}: {rr['mean'] * 100:+.2f} [{rr['ci_lo'] * 100:+.2f},"
                    f"{rr['ci_hi'] * 100:+.2f}]"
                )
        L.append(f"  {h:>2}M  " + " · ".join(row))
    pbo_lines = " · ".join(
        f"{x['window']}/{x['horizon']}M {x.get('pbo', float('nan')):.3f}(n={x['n_months']})"
        for x in res.pbo
    )
    L += [
        "",
        f"PBO (CSCV S=16, 전략 = {'·'.join(PBO_VARIANTS)}): {pbo_lines}",
        "  — 합격 기준에 넣지 않는다 (docs/17 §4). 전략이 셋뿐이라 PBO 의 분해능도 셋뿐이다.",
    ]
    return L


def run_structures(
    *, out_root: Path | None = None, write: bool = True, force: bool = False
) -> StructureResult:
    """`msa backtest l1-structures` — 캐시에서 입력을 받아 S0·S1·S2 를 재고
    `state/backtests/l1/<store_end>/` 에 `structures_*` 파일로 쓴다 (관문 0 산출물 옆)."""
    from msa.config import paths
    from msa.io import dump_json, write_snapshot
    from msa.l1.backtest import load_inputs

    panel, ind, themes, info = load_inputs(force=force)
    res = run_structure_backtest(panel, ind, themes)
    res.meta.update({"inputs": info})
    if write:
        root = out_root if out_root is not None else paths().backtests_l1
        out_dir = root / str(info["store_end"])
        write_snapshot(
            out_dir,
            frames={
                "structures_ic_summary.csv": res.ic_summary,
                "structures_spread_summary.csv": res.spread_summary,
                "structures_spread_diff_summary.csv": res.spread_diff_summary,
                "structures_spread_diff_timeseries.csv": res.spread_diff,
                "structures_eligibility.csv": res.eligibility,
                "structures_ic_timeseries.csv": res.ic,
            },
            texts={"structures_report.txt": render_structure_report(res)},
            jsons={
                "structures_verdict.json": res.verdicts,
                "structures_verdict_m37.json": res.verdicts_m37,
                "structures_dsr.json": {"dsr": res.dsr, "pbo": res.pbo, "meta": res.meta},
            },
        )
        dump_json(out_dir / "structures_meta.json", res.meta)
        log.info("structures: 저장 %s", out_dir)
    return res
