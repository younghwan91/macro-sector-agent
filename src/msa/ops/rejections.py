"""기각 대장 갱신 + 사전 고정 세 질문 (`docs/10-validation.md` §5, `docs/09` §4).

- `update_returns()` — `r_12m` · `r_24m` 를 **테마 EW 지수**(스코어보드가 쓰는 것과 같은
  `ret_ew` 누적, `state/cache/l1_panel_*.parquet` 읽기 전용)로 채운다. horizon 이 아직 안 지난
  행은 null 로 둔다.
  사후에 종목을 고르지 않는다.
- 세 질문 (바꾸지 않는다):
  (a) 하드 게이트 기각 테마의 12·24M 분포 vs 편입(통과) 테마의 분포
  (b) `secular_risk` 기각분의 **사후 물량 추세** — 지표 캐시의 축 1 판정
      (`verdict_post_ss`·`unit_cagr_10y`)을 기각 12개월 뒤 시점에서 다시 읽는다
  (c) 상위 K=8 vs 9~15위 — `state/scans/<date>/scoreboard.csv` 순위 스냅샷으로 전 스캔에 대해

산출물 `state/rejections-summary.md` 는 **내부 감사 기록**이다 — 리포트·README·알림에 싣지 않는다.
이 수치로 임계값·가중치·K·C6 을 조정하지 않는다 (`CLAUDE.md` §1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from msa.ops.journal import load_entries
from msa.ops.state_files import Rejection

log = logging.getLogger(__name__)

TOP_K = 8
BELOW_K_RANGE = (9, 15)


# ---------------------------------------------------------------------------
# 테마 지수 (읽기 전용 캐시)
# ---------------------------------------------------------------------------


def _newest(cache_dir: Path, pattern: str) -> Path | None:
    files = sorted(cache_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def load_theme_index(cache_dir: Path) -> pd.DataFrame:
    """date × theme EW 누적 지수 (시작 1.0). 패널 캐시가 없으면 예외 — 조용히 빈 표를 내지 않는다.

    스코어보드와 같은 지수다 (`ThemePanel.index_level("ew")` 와 동일 계산).
    """
    f = _newest(cache_dir, "l1_panel_*.parquet")
    if f is None:
        raise FileNotFoundError(
            f"{cache_dir} 에 l1_panel_*.parquet 이 없다 — `msa scan` 을 먼저 돌려라"
        )
    frame = pd.read_parquet(f)
    r = frame["ret_ew"].unstack("theme").sort_index()
    return (1.0 + r.fillna(0.0)).cumprod().where(r.notna().cummax())


def load_axis1_monthly(cache_dir: Path) -> pd.DataFrame | None:
    """지표 캐시의 축 1 열 (date × theme 멀티인덱스). 없으면 None — (b) 는 '측정 불가' 로 적는다."""
    f = _newest(cache_dir, "l1_indicators_*.parquet")
    if f is None:
        return None
    ind = pd.read_parquet(f)
    cols = [
        c
        for c in ("verdict_post_ss", "unit_cagr_10y", "unit_cagr_10y_median", "axis1_status")
        if c in ind.columns
    ]
    return ind[cols] if cols else None


def forward_return(index: pd.DataFrame, theme: str, t0: date, months: int) -> float | None:
    """t0 이후 첫 거래일 → t0+months 이후 첫 거래일 수익률. 끝점이 아직 없으면 None."""
    if theme not in index.columns:
        return None
    s = index[theme].dropna()
    if s.empty:
        return None
    start = s.loc[pd.Timestamp(t0) :]
    if start.empty:
        return None
    t1 = pd.Timestamp(t0) + pd.DateOffset(months=months)
    end = s.loc[t1:]
    if end.empty:
        return None
    a, b = float(start.iloc[0]), float(end.iloc[0])
    return b / a - 1.0 if a > 0 else None


def update_returns(rows: list[Rejection], index: pd.DataFrame, asof: date) -> list[Rejection]:
    """채워지지 않은 r_12m/r_24m 만 채운다. 이미 있는 값은 건드리지 않는다 (불변 규칙)."""
    out: list[Rejection] = []
    for r in rows:
        r12, r24 = r.r_12m, r.r_24m
        if r12 is None and pd.Timestamp(r.rejected_at) + pd.DateOffset(months=12) <= pd.Timestamp(
            asof
        ):
            r12 = forward_return(index, r.theme, r.rejected_at, 12)
        if r24 is None and pd.Timestamp(r.rejected_at) + pd.DateOffset(months=24) <= pd.Timestamp(
            asof
        ):
            r24 = forward_return(index, r.theme, r.rejected_at, 24)
        out.append(replace(r, r_12m=r12, r_24m=r24))
    return out


# ---------------------------------------------------------------------------
# 세 질문
# ---------------------------------------------------------------------------


def _dist(xs: list[float]) -> str:
    if not xs:
        return "n=0"
    a = np.array(xs)
    return (
        f"n={len(a)} 중앙값 {np.median(a):+.1%} 평균 {a.mean():+.1%} "
        f"최소 {a.min():+.1%} 최대 {a.max():+.1%}"
    )


def passed_themes(jdir: Path) -> list[tuple[str, date]]:
    """편입(통과) 표본 = 저널 진입 항목 (theme, date)."""
    out: list[tuple[str, date]] = []
    for e in load_entries(jdir, "entry"):
        try:
            out.append((str(e["theme"]), date.fromisoformat(str(e["date"]))))
        except (KeyError, ValueError):
            continue
    return out


def question_a(
    rows: list[Rejection], passed: list[tuple[str, date]], index: pd.DataFrame, asof: date
) -> list[str]:
    L = ["### (a) 하드 게이트가 실제로 구분했는가", ""]
    rej = [r for r in rows if r.path == "hard_gate"]
    for months, attr in ((12, "r_12m"), (24, "r_24m")):
        rx = [getattr(r, attr) for r in rej if getattr(r, attr) is not None]
        px = [
            v
            for t, d in passed
            if (v := forward_return(index, t, d, months)) is not None
            and pd.Timestamp(d) + pd.DateOffset(months=months) <= pd.Timestamp(asof)
        ]
        L.append(f"- {months}M  기각(hard_gate): {_dist(rx)}")
        L.append(f"- {months}M  통과(편입):      {_dist(px)}")
        if rx and px:
            ov = "겹침" if (max(rx) >= min(px) and max(px) >= min(rx)) else "분리"
            L.append(
                f"  - 두 분포 범위: {ov}. 겹치면 게이트는 필터가 아니라 노이즈다 — 사실만 적는다"
            )
    if not rej:
        L.append("- hard_gate 행 없음")
    return L


def question_b(rows: list[Rejection], axis1: pd.DataFrame | None) -> list[str]:
    L = ["### (b) secular_risk 게이트가 물량 소멸 테마를 골랐는가 (사후 축 1 실측)", ""]
    rej = [r for r in rows if r.path == "secular_risk"]
    if not rej:
        return [*L, "- secular_risk 행 없음"]
    if axis1 is None:
        return [*L, "- 측정 불가 — 지표 캐시(l1_indicators_*.parquet)에 축 1 열이 없다"]
    for r in rej:
        at_rej = (r.axis_verdicts or {}).get("unit_demand", "?")
        t1 = pd.Timestamp(r.rejected_at) + pd.DateOffset(months=12)
        try:
            sub = axis1.xs(r.theme, level="theme")
        except KeyError:
            L.append(f"- {r.theme} @{r.rejected_at}: 기각 시 축1={at_rej} · 사후: 지표 없음")
            continue
        later = sub.loc[t1:]
        if later.empty:
            L.append(
                f"- {r.theme} @{r.rejected_at}: 기각 시 축1={at_rej} · "
                "사후 12M 시점 데이터 아직 없음"
            )
            continue
        row = later.iloc[0]
        v = row.get("verdict_post_ss", None)
        cagr = row.get("unit_cagr_10y", None)
        cagr_s = "n/a" if cagr is None or pd.isna(cagr) else f"{float(cagr):+.1%}"
        L.append(
            f"- {r.theme} @{r.rejected_at}: 기각 시 축1={at_rej} · "
            f"12M 후 verdict_post_ss={v} unit_cagr_10y={cagr_s} · "
            f"r_12m={'n/a' if r.r_12m is None else f'{r.r_12m:+.1%}'}"
        )
    return L


def question_c(scans_dir: Path, index: pd.DataFrame, asof: date) -> list[str]:
    L = [
        f"### (c) 상위 K={TOP_K} 컷오프에 근거가 있는가 — "
        f"{BELOW_K_RANGE[0]}~{BELOW_K_RANGE[1]}위 vs 상위 {TOP_K}",
        "",
    ]
    if not scans_dir.exists():
        return [*L, f"- {scans_dir} 없음"]
    rows_out: list[str] = []
    agg: dict[int, dict[str, list[float]]] = {
        12: {"top": [], "below": []},
        24: {"top": [], "below": []},
    }
    for d in sorted(scans_dir.iterdir()):
        sb = d / "scoreboard.csv"
        if not sb.exists():
            continue
        try:
            t0 = date.fromisoformat(d.name)
        except ValueError:
            continue
        tab = pd.read_csv(sb, index_col=0)
        if "rank" not in tab.columns:
            continue
        ranked = tab["rank"].dropna().astype(int)
        top = ranked[ranked <= TOP_K].index.tolist()
        below = ranked[(ranked >= BELOW_K_RANGE[0]) & (ranked <= BELOW_K_RANGE[1])].index.tolist()
        parts = [f"- {t0}: 상위 {len(top)} · 9~15위 {len(below)}"]
        for m in (12, 24):
            if pd.Timestamp(t0) + pd.DateOffset(months=m) > pd.Timestamp(asof):
                parts.append(f"{m}M 미도래")
                continue
            tr = [v for t in top if (v := forward_return(index, str(t), t0, m)) is not None]
            br = [v for t in below if (v := forward_return(index, str(t), t0, m)) is not None]
            agg[m]["top"] += tr
            agg[m]["below"] += br
            parts.append(f"{m}M 상위 {_dist(tr)} | 9~15위 {_dist(br)}")
        rows_out.append(" · ".join(parts))
    if not rows_out:
        return [*L, "- 스캔 스냅샷 없음"]
    L += rows_out
    L.append("")
    for m in (12, 24):
        L.append(f"- 합산 {m}M: 상위 {_dist(agg[m]['top'])} | 9~15위 {_dist(agg[m]['below'])}")
    L.append(
        "- 9~15위가 더 나았다면 문제는 K 가 아니라 스코어의 순서다 — 컷오프를 옮기지 않는다 "
        "(docs/10 §5)"
    )
    return L


@dataclass
class RejectionSummary:
    text: str
    updated_rows: list[Rejection]
    n_filled_12m: int
    n_filled_24m: int


def summarize(
    rows: list[Rejection],
    *,
    index: pd.DataFrame,
    axis1: pd.DataFrame | None,
    jdir: Path,
    scans_dir: Path,
    asof: date,
) -> RejectionSummary:
    updated = update_returns(rows, index, asof)
    f12 = sum(
        1 for a, b in zip(rows, updated, strict=True) if a.r_12m is None and b.r_12m is not None
    )
    f24 = sum(
        1 for a, b in zip(rows, updated, strict=True) if a.r_24m is None and b.r_24m is not None
    )
    by_path: dict[str, int] = {}
    for r in updated:
        by_path[r.path] = by_path.get(r.path, 0) + 1
    L = [
        f"# 기각 대장 집계 · {asof}",
        "",
        "> **내부 감사 기록이다.** 리포트·README·알림에 싣지 않는다. "
        "실현 손익이 아니며 성과 주장이 아니다.",
        "> 이 수치로 임계값·가중치·K·C6 을 조정하지 않는다 (CLAUDE.md §1, docs/10 §5 경계).",
        "",
        f"- 행 {len(updated)}개 · 경로별 {by_path}",
        f"- 이번 갱신으로 채운 r_12m {f12}개 · r_24m {f24}개",
        "- 테마 지수: 버킷 구성종목 동일가중 (`ret_ew` 누적) · "
        f"마지막 거래일 {index.index.max().date() if len(index) else 'n/a'}",
        "",
        "## 행",
        "",
        "| theme | rejected_at | path | rank | c | r_12m | r_24m |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in updated:
        L.append(
            f"| {r.theme} | {r.rejected_at} | {r.path} | {r.scoreboard_rank} | "
            f"{'null' if r.cycle_confidence is None else r.cycle_confidence} | "
            f"{'null' if r.r_12m is None else f'{r.r_12m:+.1%}'} | "
            f"{'null' if r.r_24m is None else f'{r.r_24m:+.1%}'} |"
        )
    L += ["", "## 사전 고정 세 질문", ""]
    L += question_a(updated, passed_themes(jdir), index, asof)
    L.append("")
    L += question_b(updated, axis1)
    L.append("")
    L += question_c(scans_dir, index, asof)
    L.append("")
    return RejectionSummary("\n".join(L) + "\n", updated, f12, f24)


def theme_index_from_returns(ret: pd.DataFrame) -> pd.DataFrame:
    """테스트·합성용: date × theme 일별 수익률 → 누적 지수."""
    return (1.0 + ret.fillna(0.0)).cumprod().where(ret.notna().cummax())


def as_dict(rows: list[Rejection]) -> list[dict[str, Any]]:
    from dataclasses import asdict

    return [asdict(r) for r in rows]
