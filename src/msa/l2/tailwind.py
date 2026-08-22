"""거시 순풍 점수 (`docs/03-macro-dag.md` §4) + 공통 인자 횡단면 중앙값 차감 (§7).

    tailwind(t) = ind(t) + ( cf(t) − median_themes cf )

    ind(t) = Σ_{개별 엣지 e∈in(t), 가용} w_e · sign_e · state_e  /  W_avail(t)
    cf(t)  = Σ_{공통 인자 엣지 e, 가용}     w_e · sign_e · state_e  /  W_avail(t)
    W_avail(t) = Σ_{가용 엣지 e∈in(t)} w_e          w: strong 3 · moderate 2 · weak 1

## 결정 (문서가 못 박지 않은 것)

1. **분모는 가용 엣지의 가중치 합**이다. 드라이버가 없는 엣지는 분자·분모 모두에서 빠지고 개수로
   보고된다 (`n_edges_missing`, `weight_coverage`). 전체 가중치로 나누면 결측이 "중립(0)" 으로
   둔갑한다 — L1 스코어보드의 가중치 재정규화와 같은 원칙.
2. **공통 인자의 차감 단위는 테마별 정규화 후 기여분**이다. 분자는 전 테마에 같지만 분모(W)가
   테마마다 달라 기여분이 다르다 — 개별 엣지가 가벼운 테마일수록 공통 인자에 더 끌린다.
   그 기여분의 횡단면 중앙값을 빼서 상대 순풍만 남긴다. `tailwind_raw` 에 차감 전 값을 같이 둔다.
3. `policy_events` 는 테마별 판정이다. 이벤트 CSV 의 `effect` 가 **해당 테마에** 유리(+1)/불리(−1)
   이므로, `state := sign × effect` 로 두어 `sign × state = effect` 가 되게 한다 — 규제 리스크
   테마(sign −1)에 '규제 강화' 이벤트는 effect −1 로 기록하면 기여가 −1 이 된다. 판정 창은 직전
   12개월, 확정(`confirmed`) 이벤트만 센다. 유리·불리가 공존하면 0.
4. 하드 규칙 `tailwind < −0.5 → hard_exclude` 는 플래그만 세운다. 실제 후보 제외는 L1·L2 를 합치는
   단계(`final(t)`, M5 이후)의 일이다. 플래그는 **가중치 커버리지 ≥ 0.5** 일 때만 선다 — 엣지 하나만
   관측된 테마를 그 하나로 제외하면 결측이 판정으로 둔갑한다 (0.5 는 "선언 근거의 절반" 이라는
   선언이며 데이터로 정하지 않았다).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from msa.l2.dag import DagValidation, MacroDag, expand_edges
from msa.status import CoverageStatus

HARD_EXCLUDE_BELOW = -0.5
HARD_EXCLUDE_MIN_COVERAGE = 0.5  # 선언: 가중치 절반 이상이 관측돼야 하드 제외가 발동한다
EVENT_WINDOW_MONTHS = 12
TOP_CONTRIB_N = 3  # `top_contrib` 열에 적는 개별 엣지 수 (|기여| 내림차순)

CONTRIB_COLUMNS: tuple[str, ...] = (
    "theme",
    "edge",
    "from",
    "sign",
    "strength",
    "w",
    "state",
    "contrib",
    "status",
    "common_factor",
)
TABLE_COLUMNS: tuple[str, ...] = (
    "tailwind",
    "tailwind_raw",
    "ind_part",
    "cf_part",
    "cf_median",
    "status",
    "hard_exclude",
    "undercovered",
    "n_edges",
    "n_edges_available",
    "n_edges_missing",
    "n_cf_available",
    "weight_coverage",
    "top_contrib",
)


@dataclass
class TailwindResult:
    table: pd.DataFrame  # theme × TABLE_COLUMNS
    contributions: pd.DataFrame  # (theme, edge) 행 — CONTRIB_COLUMNS
    cf_median: float
    n_pairs: int
    n_pairs_available: int

    def ranked(self, n: int = 10, *, ascending: bool = False) -> pd.DataFrame:
        """계산된 테마만, tailwind 순 상위(기본)/하위(`ascending=True`) `n`개."""
        t = self.table.loc[self.table["status"] != CoverageStatus.UNAVAILABLE]
        return t.sort_values("tailwind", ascending=ascending).head(n)


def policy_event_effect(
    events: pd.DataFrame | None,
    theme: str,
    asof: pd.Timestamp,
    *,
    window_months: int = EVENT_WINDOW_MONTHS,
) -> float:
    """직전 `window_months` 의 확정 이벤트로 테마 효과 ∈ {−1, 0, +1}. 목록 없음 → NaN."""
    if events is None:
        return float("nan")
    start = asof - pd.DateOffset(months=window_months)
    sub = events.loc[
        (events["theme"] == theme)
        & events["confirmed"]
        & (events["date"] > start)
        & (events["date"] <= asof)
    ]
    pos = bool((sub["effect"] > 0).any())
    neg = bool((sub["effect"] < 0).any())
    if pos and not neg:
        return 1.0
    if neg and not pos:
        return -1.0
    return 0.0


def _contributions(
    dag: MacroDag,
    theme_ids: list[str],
    state_row: pd.Series,
    asof: pd.Timestamp,
    events: pd.DataFrame | None,
) -> pd.DataFrame:
    """(테마, 엣지) 기여 행. 쌍의 순서는 `expand_edges` 그대로(엣지 순 → 테마 순)."""
    pairs = expand_edges(dag, theme_ids)
    c = pd.DataFrame(
        {
            "theme": [p.theme for p in pairs],
            "edge": [p.edge.index for p in pairs],
            "from": [p.edge.source for p in pairs],
            "sign": [p.edge.sign for p in pairs],
            "strength": [p.edge.strength for p in pairs],
            "w": [p.edge.weight for p in pairs],
            "common_factor": [p.edge.wildcard for p in pairs],
        },
        columns=[k for k in CONTRIB_COLUMNS if k not in ("state", "contrib", "status")],
    )
    is_agent = c["from"].isin(dag.agent_drivers)
    state = c["from"].map(state_row).astype(float)  # 없는 드라이버 → NaN
    # policy_events: 테마별 판정 (결정 3) — 테마당 한 번만 센다
    agent_themes = c.loc[is_agent, "theme"].unique()
    eff = {t: policy_event_effect(events, t, asof) for t in agent_themes}
    state = state.mask(is_agent, c["sign"] * c["theme"].map(eff).astype(float))
    ok = state.notna()
    c["state"] = state
    c["contrib"] = (c["w"] * c["sign"] * state).where(ok)
    c["status"] = np.where(ok, "ok", np.where(is_agent, "missing_events", "missing_driver"))
    c["common_factor"] = c["common_factor"].astype(bool)
    return c[list(CONTRIB_COLUMNS)]


def _top_contrib(ind: pd.DataFrame) -> pd.Series:
    """테마 → 개별 가용 엣지 중 |기여| 상위 `TOP_CONTRIB_N` 개를 `from(sign×state)` 로 `; ` 연결."""
    if ind.empty:
        return pd.Series(dtype=object)
    label = (
        ind["from"]
        + "("
        + ind["sign"].map("{:+d}".format)
        + "×"
        + ind["state"].map("{:+.0f}".format)
        + ")"
    )
    top = (
        ind.assign(_a=ind["contrib"].abs(), _label=label)
        .sort_values(["theme", "_a"], ascending=[True, False], kind="stable")
        .groupby("theme", sort=False)
        .head(TOP_CONTRIB_N)
    )
    return top.groupby("theme")["_label"].agg("; ".join)


def compute_tailwind(
    dag: MacroDag,
    theme_ids: list[str],
    state_row: pd.Series,
    *,
    asof: pd.Timestamp,
    events: pd.DataFrame | None = None,
    validation: DagValidation | None = None,
) -> TailwindResult:
    """`state_row`: driver → state (NaN = 없음). 테마별 표와 (테마, 엣지) 기여 행을 돌려준다."""
    contrib = _contributions(dag, theme_ids, state_row, asof, events)
    avail = contrib["status"] == "ok"
    cf = contrib["common_factor"]
    g = contrib.assign(
        w_ok=contrib["w"].where(avail, 0),
        contrib_ind=contrib["contrib"].where(avail & ~cf, 0.0),
        contrib_cf=contrib["contrib"].where(avail & cf, 0.0),
        n_ind=~cf,
        n_ind_ok=avail & ~cf,
        n_cf_ok=avail & cf,
    ).groupby("theme", sort=False)
    agg = g.agg(
        w_total=("w", "sum"),
        w_avail=("w_ok", "sum"),
        contrib_ind=("contrib_ind", "sum"),
        contrib_cf=("contrib_cf", "sum"),
        n_edges=("n_ind", "sum"),
        n_edges_available=("n_ind_ok", "sum"),
        n_cf_available=("n_cf_ok", "sum"),
    ).reindex(theme_ids)  # 테마 순서를 입력 순서로 — 아래 정렬의 동률 순서가 여기에 달렸다
    w_avail = agg["w_avail"].where(agg["w_avail"] > 0)  # 0 → NaN (가용 엣지 없음 → 계산 불가)
    table = pd.DataFrame(index=pd.Index(theme_ids, name="theme"))
    table["ind_part"] = agg["contrib_ind"] / w_avail
    table["cf_part"] = agg["contrib_cf"] / w_avail
    table["n_edges"] = agg["n_edges"].fillna(0).astype(int)
    table["n_edges_available"] = agg["n_edges_available"].fillna(0).astype(int)
    table["n_edges_missing"] = table["n_edges"] - table["n_edges_available"]
    table["n_cf_available"] = agg["n_cf_available"].fillna(0).astype(int)
    table["weight_coverage"] = agg["w_avail"] / agg["w_total"].where(agg["w_total"] > 0)
    ind = contrib.loc[avail & ~cf]
    table["top_contrib"] = _top_contrib(ind).reindex(theme_ids).fillna("").to_numpy()

    valid = table["cf_part"].notna()
    cf_median = float(table.loc[valid, "cf_part"].median()) if valid.any() else 0.0
    table["cf_median"] = cf_median
    table["tailwind_raw"] = table["ind_part"] + table["cf_part"]
    table["tailwind"] = table["ind_part"] + (table["cf_part"] - cf_median)
    table["status"] = np.where(
        table["tailwind"].isna(),
        CoverageStatus.UNAVAILABLE,
        np.where(table["n_edges_missing"] > 0, CoverageStatus.PARTIAL, CoverageStatus.OK),
    )
    table["hard_exclude"] = (table["tailwind"] < HARD_EXCLUDE_BELOW) & (
        table["weight_coverage"] >= HARD_EXCLUDE_MIN_COVERAGE
    )
    under = validation.undercovered if validation is not None else {}
    table["undercovered"] = [t in under for t in table.index]
    table = table.sort_values("tailwind", ascending=False, na_position="last")
    return TailwindResult(
        table=table[list(TABLE_COLUMNS)],
        contributions=contrib,
        cf_median=cf_median,
        n_pairs=len(contrib),
        n_pairs_available=int(avail.sum()),
    )
