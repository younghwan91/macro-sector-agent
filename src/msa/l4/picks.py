"""`msa picks <theme>` 오케스트레이션 — 특성 → 하드 필터 → 3축 → 바벨 → 파일.

산출물 `state/picks/<asof>/<theme>/`:

| 파일 | 내용 |
|---|---|
| `ranking.csv` | 적격 종목 전부의 순위·3축·종합·바벨 라벨·특성 원값 |
| `excluded.csv` | 제외된 **모든** 종목과 사유 (폐지·재무 없음·하드 필터) |
| `report.txt` | 사람이 읽는 리포트 — `docs/06` §7 형식. S 하위 항목을 접지 않는다 |
| `meta.json` | asof·스토어 최종일·유니버스 계수·없는 입력·선언 상수·테마 통계 |

제외는 **수와 사유**로 보고한다 (`CLAUDE.md` §2). 에이전트 thesis 는 아직 입력으로 받지 않는다
(M7) — 받게 되면 `주의:` 줄의 재료가 된다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from msa.config import paths
from msa.data.store import Store, StoreError
from msa.fmt import ratio
from msa.io import write_snapshot
from msa.l4 import axes
from msa.l4.barbell import DEFAULT_TOP, Barbell, classify
from msa.l4.features import (
    ENTRY_PRICE_FEATURE,
    INPUTS_UNUSED,
    LIQUIDITY_FEATURE,
    FeatureSet,
    build_features,
)
from msa.themes import load_themes, membership_from_store

log = logging.getLogger(__name__)


#: `ranking.csv` 에서 L5 입력으로 옮겨 가는 열 (`msa.pipeline.assemble`). 바벨 라벨 · 순위 ·
#: 종합 · 3축 백분위 · 기준가 · 유동성 · 표기용 플래그. 이 밖의 열은 리포트 전용이다.
RANKING_EXPORT_COLUMNS: tuple[str, ...] = (
    "group",
    "rank",
    "composite",
    "composite_partial",
    "s_pct",
    "t_pct",
    "m_pct",
    ENTRY_PRICE_FEATURE,
    LIQUIDITY_FEATURE,
    "penalties",
    "red_flags",
    "s_inputs_missing",
    "t_inputs_missing",
)


def read_ranking(path: Path | str) -> pd.DataFrame:
    """저장된 `ranking.csv` → index ticker 프레임 (`write_snapshot` 의 역). 필수 열이 빠지면 예외 —
    다른 스냅샷 형식을 조용히 읽지 않는다 (`CLAUDE.md` §2)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"ranking.csv 가 없다: {p}")
    df = pd.read_csv(p, index_col=0)
    df.index = df.index.astype(str)
    missing = [c for c in ("group", "rank", "composite") if c not in df.columns]
    if missing:
        raise ValueError(f"{p}: ranking.csv 에 열이 없다 {missing} — L4 산출물이 아니다")
    return df


@dataclass(frozen=True)
class PicksResult:
    theme: str
    asof: pd.Timestamp
    ranking: pd.DataFrame  # index ticker — 적격 종목, rank 순
    excluded: pd.DataFrame  # index ticker — reason, stage
    barbell: Barbell
    features: FeatureSet
    meta: dict[str, Any]
    report: str
    out_dir: Path | None


def rank_theme(
    fs: FeatureSet, *, top: int = DEFAULT_TOP
) -> tuple[pd.DataFrame, pd.DataFrame, Barbell]:
    """특성 표 → (ranking, excluded, barbell). 순수 함수 — 합성 FeatureSet 으로 테스트된다."""
    uni = fs.universe
    ex_rows: list[dict[str, Any]] = []
    for tk in uni.index[~uni["listed"]]:
        why = (
            "폐지" if str(uni.loc[tk, "is_delisted"]) == "Y" else "asof 이전 10거래일 내 가격 없음"
        )
        ex_rows.append({"ticker": str(tk), "stage": "listing", "reason": why})
    hf = (
        axes.hard_filters(fs.frame)
        if len(fs.frame)
        else pd.DataFrame(columns=["reason", "excluded"])
    )
    for tk in hf.index[hf["excluded"].astype(bool)]:
        ex_rows.append(
            {"ticker": str(tk), "stage": "hard_filter", "reason": str(hf.loc[tk, "reason"])}
        )
    excluded = pd.DataFrame(ex_rows, columns=["ticker", "stage", "reason"]).set_index("ticker")
    eligible = fs.frame.loc[~fs.frame.index.isin(excluded.index)] if len(fs.frame) else fs.frame
    if eligible.empty:
        ranking = pd.DataFrame()
        return ranking, excluded, Barbell([], [])
    sc = axes.score(eligible)
    bb = classify(sc.join(eligible[["marginal_producer"]]), top=top)
    ranking = sc.join(eligible, how="left")
    ranking.insert(0, "group", [bb.label(str(t)) for t in ranking.index])
    return ranking, excluded, bb


def run_picks(
    theme_id: str,
    *,
    asof: str | None = None,
    top: int = DEFAULT_TOP,
    write: bool = True,
    themes_path: Path | None = None,
    out_root: Path | None = None,
    allow_fetch: bool = True,
    with_physical: bool = True,
) -> PicksResult:
    p = paths()
    themes = load_themes(themes_path)
    theme = themes.get(theme_id)
    with Store(p.duckdb) as store:
        membership = membership_from_store(store, themes)
        if not membership.members(theme_id):
            raise StoreError(f"{theme_id}: 배정된 구성원이 0개다")
        fs = build_features(
            store, theme, membership, asof, allow_fetch=allow_fetch, with_physical=with_physical
        )
    ranking, excluded, bb = rank_theme(fs, top=top)

    n_hard = int((excluded["stage"] == "hard_filter").sum()) if len(excluded) else 0
    n_listing = int((excluded["stage"] == "listing").sum()) if len(excluded) else 0
    picks_meta: dict[str, Any] = {
        "theme": theme_id,
        "name_ko": theme.name_ko,
        "asof": str(fs.asof.date()),
        "store_end": str(fs.store_end.date()),
        "top": top,
        "universe": {
            "members": fs.n_members,
            "listed": fs.n_listed,
            "excluded_listing": n_listing,
            "excluded_hard_filter": n_hard,
            "eligible": len(ranking),
            "min_constituents": theme.min_constituents,
            "below_min_constituents": bool(len(ranking) < theme.min_constituents),
            "etf_fallback": theme.etf_proxy,
        },
        "barbell": {
            "anchors": bb.anchors,
            "torques": bb.torques,
            "anchor_count_share": bb.anchor_share,
            "weight_band_doc": "앵커 55~70% / 토크 30~45% (docs/06 §5; 비중은 L5)",
        },
        "inputs_unavailable": fs.inputs_unavailable,
        "inputs_unused": INPUTS_UNUSED,
        "inputs_missing_per_stock": _inputs_missing(ranking),
        "theme_stats": fs.theme_stats,
        "declared": axes.declared_constants(),
        "pit": "datekey ≤ asof, first-reported per calendardate (features.py)",
    }
    report = render_report(fs, ranking, excluded, bb, picks_meta, theme_name=theme.name_ko)

    out_dir: Path | None = None
    if write:
        root = out_root if out_root is not None else p.picks
        out_dir = write_snapshot(
            root / str(fs.asof.date()) / theme_id,
            frames={"ranking.csv": ranking, "excluded.csv": excluded},
            texts={"report.txt": report},
            jsons={"meta.json": picks_meta},
        )
        log.info("picks: 저장 %s", out_dir)
    return PicksResult(theme_id, fs.asof, ranking, excluded, bb, fs, picks_meta, report, out_dir)


def _txt(r: pd.Series, key: str) -> str:
    """행의 문자열 셀 — 없음·None·NaN·빈 문자열은 전부 `""`."""
    return str(r.get(key, "") or "")


def _inputs_missing(ranking: pd.DataFrame) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if ranking.empty:
        return out
    for tk, r in ranking.iterrows():
        d = {
            axis: _txt(r, key)
            for axis, key in (("S", "s_inputs_missing"), ("T", "t_inputs_missing"))
            if _txt(r, key)
        }
        if d:
            out[str(tk)] = d
    return out


# ---------------------------------------------------------------- 리포트


def _yn(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
        return "n/a"
    return "예" if bool(v) else "아니오"


def _signed_pct(x: Any, unit: str = "%") -> str:
    """비율 → 부호 있는 정수 백분율 (`+12%`·`-3pp`·`+20%/y`). 결측은 `n/a`."""
    return "n/a" if x is None or pd.isna(x) else f"{float(x) * 100:+.0f}{unit}"


def _stock_block(tk: str, r: pd.Series, theme: str, group: str) -> list[str]:
    f = ratio
    head = (
        f"{tk} · {theme} · {group or '—'}   #{int(r['rank'])}  종합 {f(r['composite'], digits=2)}"
    )
    if r.get("name") is not None and str(r.get("name")) != "nan":
        head += f"   ({r['name']})"
    nd_basis = r.get("nd_basis", "n/a")
    nd_txt = (
        f"ND/EBITDA {f(r['net_debt_ebitda'])}×"
        if nd_basis == "ebitda"
        else f"ND/시총 {f(r['net_debt_ebitda'])}×(적자 대체)"
        if nd_basis == "mcap"
        else "ND/EBITDA n/a"
    )
    dil_txt = _signed_pct(r.get("dilution_3y"), "%/y")
    rb = r.get("runway_basis_q")
    rb_txt = "" if rb is None or pd.isna(rb) or float(rb) == 4 else f"({int(rb)}Q 기준)"
    adv_m = f(pd.to_numeric(r["adv20_usd"], errors="coerce") / 1e6)
    lines = [
        head,
        f"  S {f(r['s_pct'], digits=2)}  runway {f(r['cash_runway_q'])}q{rb_txt} · {nd_txt} · "
        f"만기벽(12m) {f(r['maturity_wall_12m'], digits=2)} · 희석 3y {dil_txt} · "
        f"이자보상 {f(r['interest_coverage'])} · ADV ${adv_m}M · "
        f"가격 ${f(r['price'], digits=2)}",
    ]
    pen = _txt(r, "penalties")
    rf = _txt(r, "red_flags")
    lines.append(
        f"      감점 {int(r.get('n_penalties', 0))}/{int(r.get('n_penalty_evaluable', 0))}"
        + (f" [{pen}]" if pen else "")
        + (f" · 레드플래그 [{rf}]" if rf else "")
    )
    mh_txt = _signed_pct(r.get("margin_headroom"), "pp")
    lines.append(
        f"  T {f(r['t_pct'], digits=2)}  마진여지 P75까지 {mh_txt} · "
        f"opleverage {f(r['opleverage'])}× (증분마진 {f(r['incremental_margin'], digits=2)}) · "
        f"고정비율 {f(r['fixed_cost_ratio'], digits=2)} · "
        f"가격탄력 {f(r['price_beta_hist'], digits=2)} · "
        f"EV/시총 {f(r['equity_leverage'], digits=2)} · "
        f"한계생산자 {_yn(r.get('marginal_producer'))}  [입력 {int(r.get('t_n_inputs', 0))}/6]"
    )
    lines.append(
        f"  M {f(r['m_pct'], digits=2)}  Stage2 {_yn(r.get('stage2'))} · "
        f"RS {f(r['rs_rating'], digits=0)} · VCP 베이스 {_yn(r.get('vcp_base'))} · "
        f"52wL {_signed_pct(r.get('from_52w_low'))} · 50일선 위 {_yn(r.get('above_50d'))} · "
        f"RVOL {f(r['rvol_expansion'], digits=2)}"
    )
    lines.append(
        "  하드필터: 통과"
        + ("  (종합 부분 — 축 결측)" if bool(r.get("composite_partial", False)) else "")
    )
    notes = [
        f"{axis} 입력 없음: {_txt(r, key)}"
        for axis, key in (("S", "s_inputs_missing"), ("T", "t_inputs_missing"))
        if _txt(r, key)
    ]
    if notes:
        lines.append("  주의: " + " · ".join(notes))
    return lines


def render_report(
    fs: FeatureSet,
    ranking: pd.DataFrame,
    excluded: pd.DataFrame,
    bb: Barbell,
    meta: dict[str, Any],
    *,
    theme_name: str = "",
) -> str:
    u = meta["universe"]
    anchor_share_txt = ratio(bb.anchor_share * 100 if bb.n else float("nan"), "%", 0)
    L: list[str] = [
        f"L4 종목 선정 — {fs.theme} ({theme_name})  asof {meta['asof']} "
        f"(스토어 {meta['store_end']})",
        "=" * 78,
        f"구성원 {u['members']} → 상장 {u['listed']} (폐지/가격없음 {u['excluded_listing']}) → "
        f"하드 제외 {u['excluded_hard_filter']} → 적격 {u['eligible']}"
        + (
            f"   ※ min_constituents {u['min_constituents']} 미달 — ETF 대체 {u['etf_fallback']}"
            if u["below_min_constituents"]
            else ""
        ),
        "",
        f"바벨: 앵커 {len(bb.anchors)} [{', '.join(bb.anchors) or '—'}] · 토크 {len(bb.torques)} "
        f"[{', '.join(bb.torques) or '—'}] · 앵커 수 비중 {anchor_share_txt}"
        f"  (비중 밴드 {meta['barbell']['weight_band_doc']})",
        "",
    ]
    if len(excluded):
        L.append("제외 (전부 표기 — CLAUDE.md §2)")
        for tk, r in excluded.iterrows():
            L.append(f"  {tk:<8} [{r['stage']}] {r['reason']}")
        L.append("")
    L.append("없는 입력 (계산하지 않았다 — 빈 값이 아니라 '없다')")
    for k, v in fs.inputs_unavailable.items():
        L.append(f"  {k}: {v}")
    ts = fs.theme_stats
    L.append(
        f"테마 통계: 마진 자기이력 {ts.get('margin_hist_quarters', 0)}분기 · P75 마진 "
        f"{ratio(ts.get('theme_margin_p75', float('nan')), digits=3)} · 횡단면 P25 마진 "
        f"{ratio(ts.get('theme_margin_p25_xs', float('nan')), digits=3)} "
        f"(n={ts.get('theme_margin_n_xs', 0)}) · "
        f"RS 유니버스 {ts.get('rs_universe_n', 0)} · 가격탄력 {ts.get('price_beta_hist', {})}"
    )
    L.append("")
    L.append(
        "순위 (하드 필터 통과분 전부 · 종합 = 0.40·S̃ + 0.40·T̃ + 0.20·M̃ · 틸데 = 테마 내 백분위)"
    )
    L.append("-" * 78)
    if ranking.empty:
        L.append("  적격 종목 없음")
    for tk, r in ranking.iterrows():
        L.extend(_stock_block(str(tk), r, fs.theme, str(r["group"])))
        L.append("")
    L.append(
        "이 표는 측정값이다. 투자 조언이 아니며 집행은 사람이 한다. "
        "성과 수치는 없다 (CLAUDE.md §7·§8)."
    )
    return "\n".join(L)
