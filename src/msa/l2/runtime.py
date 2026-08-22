"""`msa macro` 오케스트레이션.

DAG → 드라이버 상태 → tailwind → 4분면 → 모순 감사 → 부호 실측 → 파일.

산출물 `state/macro/<YYYY-MM-DD>/` (기준일 = 마지막 월말):

| 파일 | 내용 |
|---|---|
| `drivers.csv` | 드라이버별 소스·상태·측정값·방향 상태·우호 플래그·지연·결측 시리즈 |
| `driver_measures.csv` · `driver_states.csv` | 월말 격자 전체 시계열 (date × driver) |
| `tailwind.csv` | 테마 × tailwind(중앙값 차감 후·전)·기여·커버리지·플래그 |
| `edge_contributions.csv` | (테마, 엣지) 기여 행 — 모순 감사·리포트가 인용 |
| `regime.csv` · `regime.txt` | 4분면 축 최근 24개월 · ASCII 차트 |
| `contradictions.csv` | `contradicts_when` 평가 |
| `sign_check.csv` · `sign_check.md` | 엣지 부호 일치율 (쌍 단위 · 엣지 단위 문서) |
| `report.txt` · `meta.json` | 사람이 읽는 요약 · 실행 메타 |

그리고 `state/macro/latest.json` — L3(`msa research`)의 거시 입력 계약
(`msa.l3.contracts.load_macro_state`: `asof` · `regime` · `tailwind{theme: float}`). 기준일이 이미
있는 `latest.json` 보다 **앞서면 덮어쓰지 않는다** — 과거 기준일 재실행이 최신을 지우지 않는다.

없는 것은 **이름으로 적는다**: 결측 드라이버·결측 시리즈·계산 불가 테마·미지 테마 타깃·in-degree
미달 테마. 빈 표를 조용히 내보내지 않는다 (`CLAUDE.md` §2).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from msa.config import paths, rel
from msa.dates import last_month_end
from msa.io import dump_json, write_snapshot
from msa.l2 import audit
from msa.l2.dag import DagValidation, MacroDag, load_dag, validate_dag
from msa.l2.drivers import DriverStates, compute_driver_states
from msa.l2.regime import RegimeResult, compute_regime, render_ascii
from msa.l2.signcheck import (
    SignCheckResult,
    SignCheckUnavailable,
    forward_excess_return,
    load_theme_index_from_cache,
    render_markdown,
    run_sign_check,
)
from msa.l2.sources import SeriesStore
from msa.l2.tailwind import TailwindResult, compute_tailwind
from msa.status import CoverageStatus
from msa.themes import load_themes

log = logging.getLogger(__name__)


@dataclass
class MacroResult:
    asof: pd.Timestamp
    dag: MacroDag
    validation: DagValidation
    drivers: DriverStates
    snapshot: pd.DataFrame  # `drivers.snapshot()` — 리포트·`drivers.csv` 가 같은 표를 쓴다
    tailwind: TailwindResult
    regime: RegimeResult
    regime_text: str  # `render_ascii(regime)`
    contradictions: pd.DataFrame
    sign_check: SignCheckResult
    sign_check_md: str  # `render_markdown(sign_check, meta)`
    meta: dict[str, Any]
    out_dir: Path | None


def run_macro(
    *,
    asof: str | None = None,
    allow_fetch: bool = True,
    allow_etf: bool = True,
    allow_store: bool = True,
    write: bool = True,
    sign_check: bool = True,
    doc_out: Path | None = None,
) -> MacroResult:
    """경로는 전부 `paths()` (`MSA_STATE`) 에서 온다 — 테스트는 환경변수로 갈아끼운다."""
    p = paths()
    asof_ts = last_month_end(pd.Timestamp(asof) if asof else pd.Timestamp.today().normalize())
    theme_ids = load_themes(p.themes_yaml).ids()
    dag = load_dag(p.dag_yaml)
    validation = validate_dag(dag, theme_ids)
    log.info(validation.summary())

    store = SeriesStore(allow_fetch=allow_fetch, allow_etf=allow_etf, allow_store=allow_store)
    ds = compute_driver_states(dag, store, asof_ts)
    log.info(
        "drivers: 가용 %d · 결측 %d (%s)", len(ds.available), len(ds.missing), ", ".join(ds.missing)
    )
    state_row = ds.state_at()
    tw = compute_tailwind(
        dag, theme_ids, state_row, asof=ds.asof, events=ds.events, validation=validation
    )
    rg = compute_regime(ds)
    contra = audit.evaluate_contradictions(dag, state_row)
    sc = _sign_check(dag, theme_ids, ds, p.cache, enabled=sign_check)
    snap = ds.snapshot()
    meta = _meta(ds, snap, validation, tw, rg, contra, sc, dag)
    res = MacroResult(
        asof=ds.asof,
        dag=dag,
        validation=validation,
        drivers=ds,
        snapshot=snap,
        tailwind=tw,
        regime=rg,
        regime_text=render_ascii(rg),
        contradictions=contra,
        sign_check=sc,
        sign_check_md=render_markdown(sc, meta),
        meta=meta,
        out_dir=None,
    )
    if write:
        res.out_dir = _write(res, p.macro)
        _write_latest(res, p.macro_latest)
        log.info("macro: 저장 %s", res.out_dir)
    if doc_out is not None:
        doc_out.parent.mkdir(parents=True, exist_ok=True)
        doc_out.write_text(res.sign_check_md, encoding="utf-8")
        log.info("macro: 부호 실측 문서 → %s", doc_out)
    return res


def _sign_check(
    dag: MacroDag, theme_ids: list[str], ds: DriverStates, cache_dir: Path, *, enabled: bool
) -> SignCheckResult:
    if not enabled:
        return run_sign_check(
            dag, theme_ids, ds.measures, None, unavailable_reason="--no-sign-check"
        )
    try:
        ti = load_theme_index_from_cache(cache_dir)
    except SignCheckUnavailable as e:
        log.warning("sign-check: %s", e)
        return run_sign_check(dag, theme_ids, ds.measures, None, unavailable_reason=str(e))
    fwd = forward_excess_return(ti.index, ti.spy).reindex(ds.grid)
    notes = {r.id: r.note for r in ds.rows if not r.ok}
    res = run_sign_check(dag, theme_ids, ds.measures, fwd, missing_notes=notes)
    res.summary["theme_index"] = ti.meta
    if res.summary["n_pairs_available"] == 0:
        res.unavailable_reason = (
            f"계산된 쌍 0개 — 드라이버 측정값 없음 (결측 드라이버 {len(ds.missing)}개: "
            + ", ".join(ds.missing)
            + ")"
        )
    return res


def _meta(
    ds: DriverStates,
    snap: pd.DataFrame,
    v: DagValidation,
    tw: TailwindResult,
    rg: RegimeResult,
    contra: pd.DataFrame,
    sc: SignCheckResult,
    dag: MacroDag,
) -> dict[str, Any]:
    missing_series = sorted({s for r in ds.rows for s in r.missing_series if s})
    return {
        "asof": str(ds.asof.date()),
        "dag": rel(dag.path) if dag.path is not None else "(none)",
        "dag_schema_version": dag.schema_version,
        "themes": v.n_themes,
        "dag_validation": {
            "schema_ok": v.schema_ok,
            "coverage_ok": v.coverage_ok,
            "n_pairs": v.n_pairs,
            "unknown_theme_refs": sorted({t for ts in v.unknown_theme_refs.values() for t in ts}),
            "undercovered": v.undercovered,
        },
        "drivers": {
            "n": len(ds.rows),
            "available": ds.available,
            "missing": ds.missing,
            "missing_series": missing_series,
            "sources_used": {r.id: r.source_used for r in ds.rows if r.ok},
            "events": ds.events_note,
        },
        "tailwind": {
            "n_pairs": tw.n_pairs,
            "n_pairs_available": tw.n_pairs_available,
            "cf_median": tw.cf_median,
            "status_counts": {k: int(v_) for k, v_ in tw.table["status"].value_counts().items()},
            "hard_exclude": tw.table.index[tw.table["hard_exclude"]].tolist(),
            "undercovered": int(tw.table["undercovered"].sum()),
        },
        "regime": rg.current
        | {"missing_growth": rg.missing_growth, "missing_inflation": rg.missing_inflation},
        "contradictions": audit.summarize(contra),
        "sign_check": sc.summary | {"unavailable_reason": sc.unavailable_reason},
        "favorable_count": int(snap["favorable"].fillna(False).astype(bool).sum()),
    }


def _write(res: MacroResult, root: Path) -> Path:
    """`state/macro/<asof>/` 에 전부 쓴다. 인덱스 없는 세 표(쌍·행 단위)는 따로 적는다."""
    out = root / str(res.asof.date())
    ds, tw = res.drivers, res.tailwind
    write_snapshot(
        out,
        frames={
            "drivers.csv": res.snapshot,
            "driver_measures.csv": ds.measures,
            "driver_states.csv": ds.states,
            "tailwind.csv": tw.table,
            "regime.csv": res.regime.axes,
        },
        texts={
            "regime.txt": res.regime_text,
            "sign_check.md": res.sign_check_md,
            "report.txt": render_report(res),
        },
        jsons={"meta.json": res.meta},
    )
    tw.contributions.to_csv(out / "edge_contributions.csv", index=False)
    res.contradictions.to_csv(out / "contradictions.csv", index=False)
    res.sign_check.pairs.to_csv(out / "sign_check.csv", index=False)
    return out


def _write_latest(res: MacroResult, path: Path) -> None:
    """`state/macro/latest.json` — L3 계약 꼴. 더 최신 기준일의 파일이 있으면 건드리지 않는다."""
    asof = str(res.asof.date())
    if path.exists():
        try:
            prev = str(json.loads(path.read_text(encoding="utf-8")).get("asof") or "")
        except (OSError, ValueError):
            prev = ""
        if prev > asof:
            log.info("macro: latest.json (%s) 이 더 최신이라 유지한다 (이번 %s)", prev, asof)
            return
    tw = res.tailwind.table["tailwind"]
    dump_json(
        path,
        {
            "asof": asof,
            "regime": res.regime.current.get("quadrant"),
            "tailwind": {str(t): (None if pd.isna(v) else float(v)) for t, v in tw.items()},
            "source": rel(res.out_dir) if res.out_dir is not None else None,
        },
    )


def render_report(res: MacroResult) -> str:
    ds, tw, v, snap = res.drivers, res.tailwind, res.validation, res.snapshot
    lines = [
        "=" * 78,
        f"L2 거시 DAG — 기준일 {res.asof.date()} (docs/03-macro-dag.md)",
        "=" * 78,
        v.summary(),
        "",
        f"[드라이버] {len(ds.rows)}개 · 가용 {len(ds.available)} · 결측 {len(ds.missing)}",
        f"{'driver':<24}{'status':<9}{'state':>6}{'fav':>5}  {'value':>10}  source / note",
        "-" * 78,
    ]
    for did, r in snap.iterrows():
        st = "  —" if pd.isna(r["state"]) else f"{r['state']:+.0f}"
        fav = (
            "—"
            if r["favorable"] is None or pd.isna(r["favorable"])
            else ("Y" if r["favorable"] else "N")
        )
        val = "—" if pd.isna(r["value"]) else f"{r['value']:+.4f}"
        src = r["source_used"] if r["status"] == "ok" else f"{r['source_used']} · {r['note']}"
        cf = " [공통]" if r["common_factor"] else ""
        lines.append(f"{str(did) + cf:<24}{r['status']:<9}{st:>6}{fav:>5}  {val:>10}  {src}"[:160])
    if ds.missing:
        lines.append("")
        lines.append(f"결측 드라이버 ({len(ds.missing)}): {', '.join(ds.missing)}")
        ms = res.meta["drivers"]["missing_series"]
        if ms:
            lines.append(f"결측 시리즈 ({len(ms)}): {', '.join(ms)}")
        lines.append(
            "→ FRED_API_KEY 를 넣고 `uv run msa data fred-fetch`, 수동 드라이버는 "
            "state/physical/manual/<id>.csv (docs/03 구현 노트)"
        )
    lines += ["", "[국면 4분면] (docs/03 §5 — 설명 도구)", res.regime_text, ""]
    sc_ = tw.table["status"].value_counts()
    lines += [
        f"[tailwind] 테마 {len(tw.table)} · 쌍 {tw.n_pairs} (가용 {tw.n_pairs_available}) · "
        f"상태 ok {int(sc_.get(CoverageStatus.OK, 0))} / "
        f"partial {int(sc_.get(CoverageStatus.PARTIAL, 0))} / "
        f"unavailable {int(sc_.get(CoverageStatus.UNAVAILABLE, 0))} · "
        f"공통 인자 중앙값 {tw.cf_median:+.3f}",
    ]
    avail = tw.table.loc[tw.table["status"] != CoverageStatus.UNAVAILABLE]
    if avail.empty:
        lines.append("  전 테마 계산 불가 — 가용 드라이버가 어느 엣지에도 닿지 않는다")
    else:
        lines.append(
            f"{'theme':<26}{'tailwind':>9}{'raw':>8}{'edges':>8}{'cov':>6}  flags · top contrib"
        )
        lines.append("-" * 78)
        shown = pd.concat([tw.ranked(10), tw.ranked(10, ascending=True)]).drop_duplicates()
        for t, r in shown.sort_values("tailwind", ascending=False).iterrows():
            flags = (
                ("HARD " if r["hard_exclude"] else "")
                + ("UNDER " if r["undercovered"] else "")
                + ("PART " if r["status"] == CoverageStatus.PARTIAL else "")
            )
            lines.append(
                f"{t!s:<26}{r['tailwind']:>+9.3f}{r['tailwind_raw']:>+8.3f}"
                f"{int(r['n_edges_available']):>4}/{int(r['n_edges']):<3}"
                f"{r['weight_coverage']:>6.0%}  "
                f"{flags}{r['top_contrib']}"[:140]
            )
        hard = tw.table.index[tw.table["hard_exclude"]].tolist()
        lines.append(
            f"하드 규칙 (tailwind < −0.5) 해당 테마 {len(hard)}: "
            + (", ".join(hard) if hard else "없음")
        )
    unav = tw.table.index[tw.table["status"] == CoverageStatus.UNAVAILABLE].tolist()
    if unav:
        lines.append(
            f"계산 불가 테마 {len(unav)}: {', '.join(unav[:20])}{' …' if len(unav) > 20 else ''}"
        )
    c = res.contradictions
    cs = audit.summarize(c)
    lines += [
        "",
        f"[모순 감사 · contradicts_when] 엣지 {len(c)} — FLAGGED {cs['FLAGGED']} · NOT_FLAGGED "
        f"{cs['NOT_FLAGGED']} · UNAVAILABLE {cs['UNAVAILABLE']} · PROSE_ONLY {cs['PROSE_ONLY']}",
    ]
    for _, r in c.loc[c["status"].isin(["FLAGGED", "UNAVAILABLE"])].iterrows():
        lines.append(
            f"  {r['status']:<11} [{r['edge']}] {r['from']} -> {r['to'][:40]} · {r['detail']}"
        )
    s = res.sign_check.summary
    lines += [
        "",
        f"[부호 일치율 실측] 쌍 {s['n_pairs']} · 계산됨 {s['n_pairs_available']}"
        + (
            f" · 36M 평균 {s['mean_agree_36']:.1%} · 60M 평균 {s['mean_agree_60']:.1%}"
            if s.get("mean_agree_36") is not None and s.get("mean_agree_60") is not None
            else ""
        ),
    ]
    if res.sign_check.unavailable_reason:
        lines.append(f"  계산 불가: {res.sign_check.unavailable_reason}")
    lines += [
        "",
        "이 표는 측정값이다. 투자 조언이 아니며 집행은 사람이 한다. "
        "엣지 부호·강도는 데이터로 조정하지 않는다.",
    ]
    return "\n".join(lines)
