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
from typing import Any

import numpy as np
import pandas as pd

from msa.l2.dag import DagValidation, EdgeTarget, MacroDag, expand_edges

HARD_EXCLUDE_BELOW = -0.5
HARD_EXCLUDE_MIN_COVERAGE = 0.5  # 선언: 가중치 절반 이상이 관측돼야 하드 제외가 발동한다
EVENT_WINDOW_MONTHS = 12


@dataclass
class TailwindResult:
    table: pd.DataFrame  # theme × 열
    contributions: pd.DataFrame  # (theme, edge) 행
    cf_median: float
    n_pairs: int
    n_pairs_available: int

    def top(self, n: int = 10) -> pd.DataFrame:
        t = self.table.loc[self.table["status"] != "unavailable"]
        return t.sort_values("tailwind", ascending=False).head(n)

    def bottom(self, n: int = 10) -> pd.DataFrame:
        t = self.table.loc[self.table["status"] != "unavailable"]
        return t.sort_values("tailwind", ascending=True).head(n)


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
    pairs: list[EdgeTarget] = expand_edges(dag, theme_ids)
    agent_drivers = {d.id for d in dag.drivers if d.provider == "agent"}
    recs: list[dict[str, Any]] = []
    for p in pairs:
        e = p.edge
        if e.source in agent_drivers:
            eff = policy_event_effect(events, p.theme, asof)
            state = float("nan") if np.isnan(eff) else e.sign * eff
            status = "missing_events" if np.isnan(eff) else "ok"
        else:
            state = float(state_row.get(e.source, np.nan))
            status = "ok" if np.isfinite(state) else "missing_driver"
        contrib_v = e.weight * e.sign * state if status == "ok" else float("nan")
        recs.append(
            {
                "theme": p.theme,
                "edge": e.index,
                "from": e.source,
                "sign": e.sign,
                "strength": e.strength,
                "w": e.weight,
                "state": state,
                "contrib": contrib_v,
                "status": status,
                "common_factor": e.wildcard,
            }
        )
    contrib = pd.DataFrame(
        recs,
        columns=[
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
        ],
    )
    rows: list[dict[str, Any]] = []
    for theme in theme_ids:
        c = contrib.loc[contrib["theme"] == theme]
        avail = c.loc[c["status"] == "ok"]
        w_total = float(c["w"].sum())
        w_avail = float(avail["w"].sum())
        ind = avail.loc[~avail["common_factor"]]
        cf = avail.loc[avail["common_factor"]]
        if w_avail > 0:
            ind_part = float(ind["contrib"].sum()) / w_avail
            cf_part = float(cf["contrib"].sum()) / w_avail
        else:
            ind_part = cf_part = float("nan")
        n_ind = int((~c["common_factor"]).sum())
        n_ind_avail = int((~ind["common_factor"]).sum())
        top = ind.reindex(ind["contrib"].abs().sort_values(ascending=False).index).head(3)
        rows.append(
            {
                "theme": theme,
                "ind_part": ind_part,
                "cf_part": cf_part,
                "n_edges": n_ind,
                "n_edges_available": n_ind_avail,
                "n_edges_missing": n_ind - n_ind_avail,
                "n_cf_available": len(cf),
                "weight_coverage": (w_avail / w_total) if w_total > 0 else float("nan"),
                "top_contrib": "; ".join(
                    f"{r['from']}({r['sign']:+d}×{r['state']:+.0f})" for _, r in top.iterrows()
                ),
            }
        )
    table = pd.DataFrame(rows).set_index("theme")
    valid = table["cf_part"].notna()
    cf_median = float(table.loc[valid, "cf_part"].median()) if valid.any() else 0.0
    table["cf_median"] = cf_median
    table["tailwind_raw"] = table["ind_part"] + table["cf_part"]
    table["tailwind"] = table["ind_part"] + (table["cf_part"] - cf_median)
    table["status"] = np.where(
        table["tailwind"].isna(),
        "unavailable",
        np.where(table["n_edges_missing"] > 0, "partial", "ok"),
    )
    table["hard_exclude"] = (table["tailwind"] < HARD_EXCLUDE_BELOW) & (
        table["weight_coverage"] >= HARD_EXCLUDE_MIN_COVERAGE
    )
    under = validation.undercovered if validation is not None else {}
    table["undercovered"] = [t in under for t in table.index]
    table = table.sort_values("tailwind", ascending=False, na_position="last")
    cols = [
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
    ]
    return TailwindResult(
        table=table[cols],
        contributions=contrib,
        cf_median=cf_median,
        n_pairs=len(contrib),
        n_pairs_available=int((contrib["status"] == "ok").sum()),
    )
