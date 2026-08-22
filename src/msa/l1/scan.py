"""`msa scan` 오케스트레이션 — 데이터 → 패널 → 지표 → 스코어보드 → 파일.

출력은 `state/scans/<YYYY-MM-DD>/` 아래에 남는다 (`docs/09-operations.md` 스냅샷 보존):

| 파일 | 내용 |
|---|---|
| `scoreboard.csv` | 순위·점수·블록 점수·플래그 |
| `indicators.csv` | 그 월말의 전 지표 원값 (테마 × 지표) |
| `indicator_pct.csv` | 점수에 들어간 지표의 횡단면 백분위 |
| `coverage.csv` | 테마별 구성원 수(전체·생존·폐지)·ETF 프록시 상관·축 1 상태 |
| `report.txt` | 사람이 읽는 요약 (스코어보드 + 제외·결측 보고) |
| `meta.json` | 스토어 최종일·지문·위생 상수·결측 지표·적자 제외 비율 |

캐시(`state/cache/`)는 지문으로 관리한다. 패널은 `panel.py` 가, 재무 패널·지표는 여기서 같은 지문
(`구성원 + 스토어 최종일`)으로 저장한다. `--force` 면 전부 다시 만든다.

커버리지 감사 중 **미분류 시총 비율**은 `scripts/audit_themes.py` 와 같은 정의로 여기서도 계산하며,
5% 를 넘으면 스캔을 진행하지 않는다 (`CLAUDE.md` §2, `docs/01` §5).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from msa.config import paths
from msa.data.store import Store, StoreError, etf_prices
from msa.l1.blocks import (
    BLOCK_INDICATORS,
    FLAG_OUTPUTS,
    TEXT_OUTPUTS,
    Indicators,
    compute_indicators,
)
from msa.l1.fundamentals import FundPanel, build_fund_panel
from msa.l1.panel import ThemePanel, build_panel
from msa.l1.physical import load_physical
from msa.l1.scoreboard import Scoreboard, build_scoreboard
from msa.themes import Membership, ThemeSet, assign_members, load_themes

log = logging.getLogger(__name__)

UNCLASSIFIED_MCAP_MAX = 0.05
ETF_CORR_MIN = 0.85


@dataclass(frozen=True)
class ScanResult:
    scoreboard: Scoreboard
    indicators: Indicators
    coverage: pd.DataFrame
    meta: dict[str, Any]
    out_dir: Path | None


def unclassified_mcap_share(
    store: Store, membership: Membership, meta: pd.DataFrame
) -> dict[str, float]:
    """생존 종목 최신 시총 기준 미분류 비율 (Shell 제외). `audit_themes.py` §1 과 같은 정의."""
    con = store._con
    mcap = con.execute(
        "select ticker, mcap from (select ticker, mcap, row_number() over "
        "(partition by ticker order by date desc) rn from prices where mcap is not null) "
        "where rn = 1"
    ).fetch_df()
    mcap_of: dict[str, float] = dict(zip(mcap["ticker"], mcap["mcap"], strict=True))
    from msa.themes import EXCLUDED_LABELS, MEMBER_CATEGORIES

    uni = meta.loc[meta["category"].isin(MEMBER_CATEGORIES)].copy()
    uni["live"] = uni["is_delisted"].fillna("N") != "Y"
    uni["shell"] = uni["industry"].fillna("(null)").isin(EXCLUDED_LABELS)
    uni["mcap"] = uni["ticker"].str.upper().map(mcap_of).fillna(0.0).where(uni["live"], 0.0)
    assigned = set(membership.frame["ticker"])
    denom = float(uni.loc[~uni["shell"], "mcap"].sum())
    covered = float(uni.loc[~uni["shell"] & uni["ticker"].str.upper().isin(assigned), "mcap"].sum())
    share = (denom - covered) / denom if denom > 0 else float("nan")
    return {
        "denominator_musd": denom / 1e6,
        "unclassified_musd": (denom - covered) / 1e6,
        "share": share,
    }


def etf_proxy_corr(
    panel: ThemePanel, themes: ThemeSet, etf: pd.DataFrame, asof: pd.Timestamp
) -> pd.Series:
    """ETF 프록시 vs 자체 EW 지수의 최근 12M 일별 수익률 상관 (`docs/01` §5). 프록시 없으면 NaN."""
    ret = panel.wide("ret_ew")
    start = asof - pd.DateOffset(months=12)
    out: dict[str, float] = {}
    if etf.empty:
        return pd.Series({t.id: np.nan for t in themes})
    e = etf.copy()
    e["date"] = pd.to_datetime(e["date"])
    px = e.pivot_table(index="date", columns="ticker", values="closeadj").sort_index()
    eret = px.pct_change(fill_method=None)
    for t in themes:
        if t.etf_proxy is None or t.etf_proxy not in eret.columns or t.id not in ret.columns:
            out[t.id] = np.nan
            continue
        a = ret[t.id].loc[start:asof]
        b = eret[t.etf_proxy].reindex(a.index)
        both = pd.concat([a, b], axis=1).dropna()
        out[t.id] = float(both.iloc[:, 0].corr(both.iloc[:, 1])) if len(both) >= 120 else np.nan
    return pd.Series(out)


def _cache_paths(fp: str, cache_dir: Path) -> dict[str, Path]:
    return {
        "fund": cache_dir / f"l1_fund_{fp}.parquet",
        "ss": cache_dir / f"l1_fund_ss_{fp}.parquet",
        "acts": cache_dir / f"l1_fund_actions_{fp}.parquet",
        "fund_meta": cache_dir / f"l1_fund_{fp}.json",
        "ind": cache_dir / f"l1_indicators_{fp}.parquet",
        "ind_meta": cache_dir / f"l1_indicators_{fp}.json",
    }


def load_or_build_fund(
    store: Store, membership: Membership, fp: str, cache_dir: Path, *, force: bool
) -> FundPanel:
    cp = _cache_paths(fp, cache_dir)
    if not force and all(cp[k].exists() for k in ("fund", "ss", "acts", "fund_meta")):
        log.info("fund: 캐시 사용 %s", cp["fund"].name)
        return FundPanel(
            frame=pd.read_parquet(cp["fund"]),
            same_store=pd.read_parquet(cp["ss"]),
            actions=pd.read_parquet(cp["acts"]),
            built_from=json.loads(cp["fund_meta"].read_text()),
        )
    fund = build_fund_panel(store, membership)
    fund.frame.to_parquet(cp["fund"])
    fund.same_store.to_parquet(cp["ss"])
    fund.actions.to_parquet(cp["acts"])
    cp["fund_meta"].write_text(json.dumps(fund.built_from, ensure_ascii=False, indent=1))
    return fund


def run_scan(
    *,
    asof: str | None = None,
    themes_path: Path | None = None,
    out_root: Path | None = None,
    force: bool = False,
    write: bool = True,
    allow_fetch: bool = True,
    compute_vcp: bool = True,
) -> ScanResult:
    p = paths()
    cache_dir = p.state / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    themes = load_themes(themes_path)
    with Store(p.duckdb) as store:
        meta = store.tickers_meta(min_rows=10_000)
        membership = assign_members(themes, meta)
        if len(membership.frame) == 0:
            raise StoreError("배정된 구성원이 0개다.")
        uncls = unclassified_mcap_share(store, membership, meta)
        if not (uncls["share"] < UNCLASSIFIED_MCAP_MAX):
            raise StoreError(
                f"미분류 시총 비율 {uncls['share']:.2%} ≥ {UNCLASSIFIED_MCAP_MAX:.0%} — "
                "스캔을 진행하지 않는다 "
                "(docs/01 §5). themes.yaml 의 industry_match 를 점검해라."
            )
        panel = build_panel(store, membership, cache_dir=cache_dir, force=force)
        fp = panel.built_from["fingerprint"]
        fund = load_or_build_fund(store, membership, fp, cache_dir, force=force)
        counts = membership.counts()

    # ETF: 프록시 + 실물 참조를 한 번에
    etf_syms = sorted(
        {t.etf_proxy for t in themes if t.etf_proxy}
        | {
            t.physical_ref.symbol
            for t in themes
            if t.physical_ref and t.physical_ref.source == "etf"
        }
    )
    try:
        etf = etf_prices(etf_syms, min_rows=0)
    except StoreError as e:
        log.warning("ETF 벌크를 읽지 못했다 — 프록시 상관·ETF 실물 참조 없이 진행: %s", e)
        etf = pd.DataFrame(columns=["ticker", "date", "close", "closeadj", "volume"])
    physical = load_physical(
        themes, allow_fetch=allow_fetch, etf_prefetched=etf if not etf.empty else None
    )

    cp = _cache_paths(fp, cache_dir)
    phys_sig = {k: v.status for k, v in physical.refs.items()} | {"_cpi": physical.cpi.status}
    ind: Indicators | None = None
    if not force and cp["ind"].exists() and cp["ind_meta"].exists():
        im = json.loads(cp["ind_meta"].read_text())
        if im.get("physical_status") == phys_sig and im.get("vcp_computed") == compute_vcp:
            log.info("indicators: 캐시 사용 %s", cp["ind"].name)
            ind = Indicators(monthly=pd.read_parquet(cp["ind"]), meta=im)
    if ind is None:
        log.info("indicators: 계산 시작 (vcp=%s)", compute_vcp)
        ind = compute_indicators(panel, fund, physical, themes, compute_vcp=compute_vcp)
        ind.meta["physical_status"] = phys_sig
        ind.monthly.to_parquet(cp["ind"])
        cp["ind_meta"].write_text(json.dumps(ind.meta, ensure_ascii=False, indent=1, default=str))

    store_end = pd.Timestamp(panel.built_from["store_end"])
    asof_ts = min(pd.Timestamp(asof), store_end) if asof else store_end
    sb = build_scoreboard(ind, themes, asof_ts, n_live=counts["n_live"])
    data_date = min(asof_ts, store_end)  # 버킷 라벨(월말)이 아니라 실제 데이터 기준일

    corr = etf_proxy_corr(panel, themes, etf, sb.date)
    cov = counts.reindex(themes.ids()).copy()
    cov["etf_proxy"] = [t.etf_proxy for t in themes]
    cov["etf_corr_12m"] = corr.reindex(cov.index)
    cov["etf_corr_ok"] = cov["etf_corr_12m"] > ETF_CORR_MIN
    st = physical.status_table(themes)
    cov["axis1_declared"] = st["status"].ne("not_declared")
    cov["axis1_data"] = st["status"]
    cov["physical_ref"] = (st["source"].fillna("") + ":" + st["symbol"].fillna("")).str.strip(":")
    cov["min_constituents"] = [t.min_constituents for t in themes]
    cov["small_sample"] = cov["n_live"] < cov["min_constituents"]

    with_proxy = cov["etf_proxy"].notna()
    corr_ok_share = (
        float(cov.loc[with_proxy, "etf_corr_ok"].mean()) if with_proxy.any() else float("nan")
    )
    scan_meta: dict[str, Any] = {
        "asof": str(data_date.date()),
        "bucket": str(sb.date.date()),
        "store_end": panel.built_from["store_end"],
        "fingerprint": fp,
        "themes": len(themes),
        "membership": membership.report(),
        "unclassified_mcap": uncls,
        "panel": panel.built_from,
        "fund": fund.built_from,
        "indicators": {k: v for k, v in ind.meta.items() if k != "physical_status"},
        "physical": {
            "declared": int(cov["axis1_declared"].sum()),
            "data_ok": int(st["status"].str.startswith("ok").sum()) if len(st) else 0,
            "data_missing": int((st["status"] == "data_missing").sum())
            + int((st["status"] == "missing").sum()),
            "cpi": physical.cpi.status,
        },
        "etf_proxy": {
            "with_proxy": int(with_proxy.sum()),
            "corr_gt_0.85_share": corr_ok_share,
            "corr_missing": int((with_proxy & cov["etf_corr_12m"].isna()).sum()),
        },
        "small_sample_buckets": cov.index[cov["small_sample"]].tolist(),
        "ebitda_nonpos_share_median": float(sb.table["ebitda_nonpos_share"].median()),
    }

    out_dir: Path | None = None
    if write:
        root = out_root if out_root is not None else p.state / "scans"
        out_dir = root / str(data_date.date())
        out_dir.mkdir(parents=True, exist_ok=True)
        sb.table.to_csv(out_dir / "scoreboard.csv")
        row = ind.at(sb.date)
        ordered = [i for b in BLOCK_INDICATORS.values() for i in b if i in row.columns]
        ordered += [c for c in (*TEXT_OUTPUTS, *FLAG_OUTPUTS) if c in row.columns]
        row[ordered].to_csv(out_dir / "indicators.csv")
        sb.indicator_pct.to_csv(out_dir / "indicator_pct.csv")
        cov.to_csv(out_dir / "coverage.csv")
        (out_dir / "meta.json").write_text(
            json.dumps(scan_meta, ensure_ascii=False, indent=1, default=str)
        )
        (out_dir / "report.txt").write_text(render_report(sb, cov, scan_meta), encoding="utf-8")
        log.info("scan: 저장 %s", out_dir)
    return ScanResult(scoreboard=sb, indicators=ind, coverage=cov, meta=scan_meta, out_dir=out_dir)


def render_report(sb: Scoreboard, cov: pd.DataFrame, meta: dict[str, Any]) -> str:
    lines = [
        sb.render().replace(str(sb.date.date()), f"{meta['asof']} (버킷 {meta['bucket']})", 1),
        "",
        "=" * 78,
        "커버리지·결측 보고 (CLAUDE.md §2 — 제외는 보고한다)",
        "=" * 78,
    ]
    lines.append(f"구성원: {meta['membership']}")
    u = meta["unclassified_mcap"]
    lines.append(
        f"미분류 시총 비율: {u['share']:.3%} (기준 < 5%) · 분모 {u['denominator_musd']:,.0f} M USD"
    )
    pm = meta["panel"]
    lines.append(
        f"패널: 수익률 상·하한 적용 종목-일 {pm['n_capped_total']:,} · "
        "$1 미만 제외는 n_listed−n_ret 로 표기"
    )
    lines.append(
        f"소표본 버킷 ({len(meta['small_sample_buckets'])}): "
        + ", ".join(meta["small_sample_buckets"])
    )
    e = meta["etf_proxy"]
    lines.append(
        f"ETF 프록시 상관 > 0.85 비율: {e['corr_gt_0.85_share']:.1%} "
        f"(프록시 보유 {e['with_proxy']} · 상관 계산 불가 {e['corr_missing']})"
    )
    ph = meta["physical"]
    lines.append(
        f"축 1 (physical_ref): 선언 {ph['declared']} · 데이터 있음 {ph['data_ok']} · "
        f"데이터 없음 {ph['data_missing']} · CPI {ph['cpi']}"
    )
    lines.append(
        f"적자(EBITDA≤0) 제외 비율 중앙값 (ev_ebitda_med): {meta['ebitda_nonpos_share_median']:.1%}"
    )
    if ph["cpi"] != "ok":
        lines.append(
            "CPI 없음 → dd_real 과 nominal 참조의 실질화는 계산되지 않았다 "
            "(FRED_API_KEY 또는 state/physical/fred/CPIAUCSL.csv)"
        )
    ind = meta["indicators"]
    lines.append(
        f"계산하지 않은 지표: {ind.get('unavailable_indicators')} — {ind.get('unavailable_reason')}"
    )
    lines.append("")
    lines.append(
        "블록 프로필 읽는 법 (docs/02 §8): A↑B↑C↓ 아직 바닥 · A↑B↑C↑E↑ 진입 구간 · "
        "A↓C↑F↑E↓ 이미 진행됨"
    )
    lines.append("이 표는 측정값이다. 투자 조언이 아니며 집행은 사람이 한다.")
    return "\n".join(lines)
