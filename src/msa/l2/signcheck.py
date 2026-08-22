"""엣지 부호 일치율 실측 (`docs/10-validation.md` §2.1 "L2 엣지 부호", `docs/03` §6 1~3항).

**세는 것이지 고치는 것이 아니다** (roadmap M4). 결과는 `docs/macro-dag-sign-check.md` 로 나가고
엣지는 그대로 둔다.

## 무엇을 상관하는가 (결정)

- x = 드라이버의 **측정값 시계열** (`drivers.py` 의 transform — 대부분 변화율이므로 §6 의
  "Δdriver" 에 해당. 발표 지연을 반영한 as-of 값)
- y = 테마 EW 지수의 **전방 12개월 초과수익**:  P(t+12)/P(t) − 1 − (SPY(t+12)/SPY(t) − 1)
  전방을 쓰는 이유: 엣지가 `lag_months` 로 **선행**을 선언했기 때문이다 — 동시 상관은 그 주장을
  재지 않는다. 12개월은 선언된 lag 창(0~36개월, 대부분 ≤12) 을 덮는 가장 짧은 단일 지평이다.
- 창: 36·60개월 롤링 Pearson 상관 (전 구간 상관도 같이). 월별 전방수익이 겹쳐 자기상관이 크므로
  **유의성 검정이 아니다** — 부호 일치 비율과 개수만 센다.

## 플래그 (§6, 최신 창 기준)

| 플래그 | 조건 |
|---|---|
| `CONTRADICTED` | 상관 부호가 선언과 반대이고 \\|corr\\| > 0.3 |
| `NO_SIGNAL` | \\|corr\\| < 0.1 |
| `CONSISTENT` | 나머지 |
| `UNAVAILABLE` | 드라이버 또는 테마 지수가 없어 창을 만들 수 없음 |

테마 지수는 L1 패널 캐시(`state/cache/l1_panel_*.parquet` 의 `ret_ew` 누적)에서 읽는다 —
`msa scan` 이 한 번 돌았어야 한다. 없으면 전부 `UNAVAILABLE` 이고 그 이유를 적는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from msa.data.store import StoreError
from msa.l1.panel import load_cached_panel
from msa.l2.dag import MacroDag, expand_edges

log = logging.getLogger(__name__)

WINDOWS: tuple[int, ...] = (36, 60)
HORIZON = 12
CONTRADICT_ABS = 0.3
NO_SIGNAL_ABS = 0.1


class SignCheckUnavailable(RuntimeError):
    pass


@dataclass
class ThemeIndexMonthly:
    index: pd.DataFrame  # 월말 × 테마 (EW 지수 수준)
    spy: pd.Series  # 월말 SPY 종가
    meta: dict[str, Any] = field(default_factory=dict)


def load_theme_index_from_cache(cache_dir: Path) -> ThemeIndexMonthly:
    """L1 패널 캐시(`msa.l1.panel.load_cached_panel`) → 월말 EW 지수.

    캐시가 없으면 `SignCheckUnavailable`."""
    try:
        panel = load_cached_panel(cache_dir)
    except StoreError as e:
        raise SignCheckUnavailable(f"{e} — `msa scan` 을 먼저 돌려라") from e
    built = dict(panel.built_from)
    fp = str(built.get("fingerprint", ""))
    meta: dict[str, Any] = {"panel": f"l1_panel_{fp}.parquet", "fingerprint": fp, **built}
    level = panel.index_level("ew")
    spy = panel.spy["close"].sort_index()
    return ThemeIndexMonthly(
        index=level.resample("ME").last(), spy=spy.resample("ME").last(), meta=meta
    )


def forward_excess_return(
    idx: pd.DataFrame, spy: pd.Series, horizon: int = HORIZON
) -> pd.DataFrame:
    """P(t+h)/P(t) − 1 − (SPY(t+h)/SPY(t) − 1), t 기준 행. 마지막 h 개월은 NaN."""
    fwd = idx.shift(-horizon) / idx - 1.0
    spy_m = spy.reindex(idx.index)
    fwd_spy = spy_m.shift(-horizon) / spy_m - 1.0
    return fwd.sub(fwd_spy, axis=0)


#: 창을 만들 수 없을 때의 결과 꼴 (`n_obs` 는 호출자가 채운다).
_EMPTY: dict[str, Any] = {
    "n_windows": 0,
    "agree_share": float("nan"),
    "latest_corr": float("nan"),
    "n_obs": 0,
}
MIN_FULL_CORR_OBS = 24  # 전 구간 상관을 적는 최소 관측 수


def _paired(x: pd.Series, y: pd.Series) -> pd.DataFrame:
    """둘 다 있는 시점만 — 한 쌍에 한 번 만들어 창·전 구간 상관에 같이 쓴다."""
    return pd.concat([x, y], axis=1, keys=["x", "y"]).dropna()


def _agreement(both: pd.DataFrame, window: int, sign: int) -> dict[str, Any]:
    if len(both) < window:
        return _EMPTY | {"n_obs": len(both)}
    rc = both["x"].rolling(window, min_periods=window).corr(both["y"]).dropna()
    rc = rc[np.isfinite(rc)]
    if rc.empty:
        return _EMPTY | {"n_obs": len(both)}
    return {
        "n_windows": len(rc),
        "agree_share": float((np.sign(rc) == sign).mean()),
        "latest_corr": float(rc.iloc[-1]),
        "n_obs": len(both),
    }


def rolling_sign_agreement(x: pd.Series, y: pd.Series, window: int, sign: int) -> dict[str, Any]:
    """`window` 개월 롤링 상관의 부호가 `sign` 과 같은 창의 비율·최신 상관·창 수."""
    return _agreement(_paired(x, y), window, sign)


def flag_for(corr: float, sign: int) -> str:
    if not np.isfinite(corr):
        return "UNAVAILABLE"
    if abs(corr) < NO_SIGNAL_ABS:
        return "NO_SIGNAL"
    if np.sign(corr) == -sign and abs(corr) > CONTRADICT_ABS:
        return "CONTRADICTED"
    return "CONSISTENT"


@dataclass
class SignCheckResult:
    pairs: pd.DataFrame  # (edge, theme) 행
    per_edge: pd.DataFrame
    summary: dict[str, Any]
    unavailable_reason: str = ""

    @property
    def ran(self) -> bool:
        return not self.unavailable_reason


def run_sign_check(
    dag: MacroDag,
    theme_ids: list[str],
    measures: pd.DataFrame,
    fwd_excess: pd.DataFrame | None,
    *,
    windows: tuple[int, ...] = WINDOWS,
    unavailable_reason: str = "",
    missing_notes: dict[str, str] | None = None,
) -> SignCheckResult:
    """(엣지, 테마) 쌍마다 창별 부호 일치율. `fwd_excess=None` 이면 전부 UNAVAILABLE.

    `missing_notes` (driver → 결측 이유) 를 주면 "측정값 없음" 대신 그 이유를 적는다.
    """
    notes = missing_notes or {}
    pairs = [p for p in expand_edges(dag, theme_ids) if not p.edge.wildcard]
    agent_drivers = dag.agent_drivers
    # 드라이버별로 한 번: 측정값 시리즈와 "없음" 사유 (쌍 451개가 같은 26개 드라이버를 본다)
    driver_reason: dict[str, str] = {}
    for drv in {p.edge.source for p in pairs}:
        if drv in agent_drivers:
            driver_reason[drv] = "policy_events 는 시계열이 아니다"
        elif drv not in measures.columns or measures[drv].notna().sum() == 0:
            driver_reason[drv] = f"드라이버 {drv} 측정값 없음" + (
                f" — {notes[drv]}" if drv in notes else ""
            )
    recs: list[dict[str, Any]] = []
    for p in pairs:
        e = p.edge
        rec: dict[str, Any] = {
            "edge": e.index,
            "from": e.source,
            "theme": p.theme,
            "sign": e.sign,
            "strength": e.strength,
            "lag_months": "" if e.lag_months is None else f"{e.lag_months[0]}-{e.lag_months[1]}",
        }
        reason = driver_reason.get(e.source, "")
        if not reason and (fwd_excess is None or p.theme not in fwd_excess.columns):
            reason = unavailable_reason or f"테마 {p.theme} 지수 없음"
        rec["reason"] = reason
        both: pd.DataFrame | None = None
        if not reason:
            assert fwd_excess is not None
            both = _paired(measures[e.source], fwd_excess[p.theme])
        for w in windows:
            r = _EMPTY if both is None else _agreement(both, w, e.sign)
            rec[f"n_windows_{w}"] = r["n_windows"]
            rec[f"agree_{w}"] = r["agree_share"]
            rec[f"latest_corr_{w}"] = r["latest_corr"]
            rec[f"flag_{w}"] = flag_for(r["latest_corr"], e.sign)
        if both is not None and len(both) >= MIN_FULL_CORR_OBS:
            rec["full_corr"] = float(both["x"].corr(both["y"]))
        else:
            rec["full_corr"] = float("nan")
        rec["n_obs"] = 0 if both is None else len(both)
        recs.append(rec)
    cols = ["edge", "from", "theme", "sign", "strength", "lag_months", "n_obs", "full_corr"]
    for w in windows:
        cols += [f"n_windows_{w}", f"agree_{w}", f"latest_corr_{w}", f"flag_{w}"]
    cols.append("reason")
    pairs_df = pd.DataFrame(recs, columns=cols)
    per_edge = _aggregate(pairs_df, windows)
    avail = pairs_df["reason"] == ""
    summary: dict[str, Any] = {
        "n_pairs": len(pairs_df),
        "n_pairs_available": int(avail.sum()),
        "n_edges": int(pairs_df["edge"].nunique()),
        "n_edges_available": int(pairs_df.loc[avail, "edge"].nunique()),
    }
    for w in windows:
        sub = pairs_df.loc[avail & pairs_df[f"agree_{w}"].notna()]
        summary[f"mean_agree_{w}"] = float(sub[f"agree_{w}"].mean()) if len(sub) else None
        summary[f"flags_{w}"] = {
            f: int((pairs_df[f"flag_{w}"] == f).sum())
            for f in ("CONSISTENT", "NO_SIGNAL", "CONTRADICTED", "UNAVAILABLE")
        }
    return SignCheckResult(
        pairs=pairs_df, per_edge=per_edge, summary=summary, unavailable_reason=unavailable_reason
    )


_EDGE_FLAGS = ("CONTRADICTED", "NO_SIGNAL", "CONSISTENT")


def _aggregate(pairs: pd.DataFrame, windows: tuple[int, ...]) -> pd.DataFrame:
    """엣지별 집계 — 테마 수·계산된 수·창별 평균 일치율·창 수·플래그별 테마 수."""
    if pairs.empty:
        return pd.DataFrame()
    flags = {f"{f.lower()}_{w}": pairs[f"flag_{w}"] == f for w in windows for f in _EDGE_FLAGS}
    g = pairs.assign(available=pairs["reason"] == "", **flags).groupby(
        ["edge", "from", "sign", "strength"], sort=True
    )
    spec: dict[str, tuple[str, str]] = {
        "n_themes": ("theme", "size"),
        "n_available": ("available", "sum"),
    }
    for w in windows:
        spec[f"agree_{w}"] = (f"agree_{w}", "mean")
        spec[f"n_windows_{w}"] = (f"n_windows_{w}", "sum")
        for f in _EDGE_FLAGS:
            spec[f"{f.lower()}_{w}"] = (f"{f.lower()}_{w}", "sum")
    return g.agg(**spec).reset_index()


def _fetch_howto(*, with_scan: bool) -> list[str]:
    """문서의 "키가 생기면" 절차 — 계산 불가 절에는 `msa scan`(테마 지수) 한 줄이 더 들어간다."""
    return [
        "```bash",
        "export FRED_API_KEY=...",
        "uv run msa data fred-fetch          # DRIVER_SERIES + physical_ref + CPIAUCSL 캐시",
        *(["uv run msa scan                     # L1 패널 캐시 (테마 지수)"] if with_scan else []),
        "uv run msa macro --doc-out docs/macro-dag-sign-check.md",
        "```",
    ]


def render_markdown(res: SignCheckResult, meta: dict[str, Any]) -> str:
    s = res.summary
    lines = [
        "# L2 엣지 부호 일치율 실측 (`docs/10-validation.md` §2.1 · `docs/03` §6)",
        "",
        f"생성: `msa macro` · 기준일 {meta.get('asof', '?')} · "
        f"DAG {meta.get('dag', 'state/macro-dag.yaml')}",
        "",
        "**세는 것이지 고치는 것이 아니다.** 이 표를 보고 `sign` 이나 `strength` 를 바꾸지 않는다 "
        "(`CLAUDE.md` §1). 불일치 엣지는 `docs/03` §6 의 절차"
        "(사람 검토 → 서술 수정 → 커밋 근거)를 거친다.",
        "",
        "## 방법",
        "",
        "- x = 드라이버 측정값(발표 지연 반영 as-of transform), "
        "y = 테마 EW 지수의 **전방 12개월 초과수익**(vs SPY)",
        "- 36·60개월 롤링 Pearson 상관의 **부호가 선언 `sign` 과 같은 창의 비율**. "
        "전방수익이 겹쳐 자기상관이 크므로 검정이 아니다",
        "- 플래그는 최신 창 기준: `CONTRADICTED` (반대 부호 & |corr|>0.3) · "
        "`NO_SIGNAL` (|corr|<0.1) · `CONSISTENT` · `UNAVAILABLE`",
        "- 테마 지수: L1 패널 캐시 (`state/cache/l1_panel_*`), "
        "드라이버: `state/physical/fred/*.csv` (최신 개정치 — ALFRED 빈티지 아님)",
        "",
        "## 요약",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 테마-엣지 쌍 (공통 인자 제외) | {s['n_pairs']} |",
        f"| 계산된 쌍 | {s['n_pairs_available']} |",
        f"| 엣지 | {s['n_edges']} (계산된 엣지 {s['n_edges_available']}) |",
    ]
    for w in WINDOWS:
        m = s.get(f"mean_agree_{w}")
        fl = s.get(f"flags_{w}", {})
        lines.append(
            f"| {w}개월 창 평균 일치율 | {'—' if m is None else f'{m:.1%}'} · 플래그 "
            + " / ".join(f"{k} {v}" for k, v in fl.items())
            + " |"
        )
    lines.append("")
    n_unav = s["n_pairs"] - s["n_pairs_available"]
    if res.ran and 0 < s["n_pairs_available"] < s["n_pairs"]:
        miss_drivers = sorted(
            set(res.pairs.loc[res.pairs["reason"] != "", "from"]) if not res.pairs.empty else []
        )
        lines += [
            f"## 실행 결과: **부분 실행** — {s['n_pairs_available']}/{s['n_pairs']} 쌍만 계산",
            "",
            f"{n_unav}쌍은 드라이버 측정값이 없어 계산하지 못했다 (드라이버 {len(miss_drivers)}개: "
            + ", ".join(f"`{d}`" for d in miss_drivers)
            + "). 아래 요약·엣지 표의 평균은 **계산된 쌍만의 값**이며 DAG 전체를 대표하지 않는다. "
            "FRED 기반 드라이버는 `FRED_API_KEY` 가 설정되면 채워진다:",
            "",
            *_fetch_howto(with_scan=False),
            "",
            "수동 드라이버(`china_*`)는 `state/physical/manual/<id>.csv`, `policy_events` 는 "
            "시계열이 아니라 이 검정의 대상이 아니다.",
            "",
        ]
    if not res.ran or s["n_pairs_available"] == 0:
        lines += [
            "## 실행 결과: **계산 불가**",
            "",
            f"이유: {res.unavailable_reason or '계산된 쌍이 0개'}",
            "",
            "현재 머신에 `FRED_API_KEY` 가 없고 `state/physical/fred/` 캐시도 없어 "
            "FRED 기반 드라이버의 측정값이 "
            "없다. 이 문서는 **실측이 아니라 실측 불가의 기록**이다. 키가 생기면:",
            "",
            *_fetch_howto(with_scan=True),
            "",
        ]
    lines += ["## 드라이버별 가용성", ""]
    if not res.pairs.empty:
        by = res.pairs.groupby("from").agg(
            n=("theme", "size"),
            avail=("reason", lambda s: int((s == "").sum())),
            reason=("reason", lambda s: next((r for r in s if r), "")),
        )
        lines += ["| 드라이버 | 쌍 | 계산됨 | 이유 |", "|---|---|---|---|"]
        for drv, brow in by.iterrows():
            lines.append(f"| `{drv}` | {brow['n']} | {brow['avail']} | {brow['reason']} |")
        lines.append("")
    lines += ["## 엣지별", ""]
    if res.per_edge.empty:
        lines.append("(쌍 없음)")
    else:
        hdr = "| 엣지 | from | sign | 강도 | 테마 | 계산됨 |"
        sep = "|---|---|---|---|---|---|"
        for w in WINDOWS:
            hdr += f" 일치율 {w}M | 창수 | C/N/K {w}M |"
            sep += "---|---|---|"
        lines += [hdr, sep]
        for _, r in res.per_edge.iterrows():
            row = (
                f"| {int(r['edge'])} | `{r['from']}` | {int(r['sign']):+d} | {r['strength']} | "
                f"{int(r['n_themes'])} | {int(r['n_available'])} |"
            )
            for w in WINDOWS:
                a = r[f"agree_{w}"]
                row += (
                    f" {'—' if pd.isna(a) else f'{a:.0%}'} | {int(r[f'n_windows_{w}'])} | "
                    f"{int(r[f'contradicted_{w}'])}/{int(r[f'no_signal_{w}'])}/"
                    f"{int(r[f'consistent_{w}'])} |"
                )
            lines.append(row)
        lines.append("")
        lines.append("C/N/K = 최신 창 기준 CONTRADICTED / NO_SIGNAL / CONSISTENT 인 테마 수.")
    lines += [
        "",
        "## 해석 규칙",
        "",
        "- 일치율이 낮은 엣지를 **고치지 않는다.** `docs/03` §6 의 세 조치"
        "(엣지 서술 수정 · 국면 조건 추가 · 유지)는 사람이 근거를 적고 커밋한다.",
        "- 표본은 사이클 2~3바퀴다. 60개월 창의 개수가 한 자릿수인 엣지는 "
        "어느 쪽으로도 말할 수 없다.",
        "- 드라이버 캐시가 최신 개정치라 `INDPRO`·`PAYEMS`(개정 큼) 엣지의 과거 상관은 "
        "실시간 판단과 다를 수 있다 (`docs/08` §4).",
    ]
    return "\n".join(lines) + "\n"
