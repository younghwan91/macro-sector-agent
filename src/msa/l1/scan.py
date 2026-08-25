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

캐시(`state/cache/`)는 지문으로 관리한다 (`msa.l1.cache.FingerprintCache`). 패널은 `panel.py` 가,
재무 패널·지표는 여기서 같은 지문(`구성원 + 스토어 최종일`)으로 저장한다. `--force` 면 전부 다시
만든다. 지표 캐시는 실물 참조 상태(`physical_status`)와 `vcp_computed` 가 같을 때만 유효하다.

`prepare_inputs()` 가 스토어 → 패널 → 재무 → 실물 → 지표까지를 한 번에 준비한다 — `msa scan` 과
`msa backtest l1` 이 같은 함수를 쓴다 (백테스트는 미분류 시총 관문을 생략한다).

커버리지 감사 중 **미분류 시총 비율**은 `scripts/audit_themes.py` 와 같은 정의로 여기서도 계산하며,
5% 를 넘으면 스캔을 진행하지 않는다 (`CLAUDE.md` §2, `docs/01` §5).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from msa.config import paths
from msa.data.store import Store, StoreError, etf_prices_or_empty
from msa.dates import parse_date
from msa.io import write_snapshot
from msa.l1.blocks import (
    BLOCK_INDICATORS,
    FLAG_OUTPUTS,
    TEXT_OUTPUTS,
    Indicators,
    compute_indicators,
)
from msa.l1.cache import FingerprintCache
from msa.l1.fundamentals import FundPanel, build_fund_panel
from msa.l1.panel import ThemePanel, build_panel
from msa.l1.physical import PhysicalBundle, etf_symbols, load_physical
from msa.l1.scoreboard import Scoreboard, build_scoreboard
from msa.status import Axis1Status
from msa.themes import Membership, ThemeSet, load_themes, membership_from_store

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


@dataclass(frozen=True)
class ScanInputs:
    """`prepare_inputs` 의 산출 — 스토어를 닫은 뒤에도 스캔·백테스트가 필요로 하는 전부."""

    themes: ThemeSet
    membership: Membership
    panel: ThemePanel
    fund: FundPanel
    physical: PhysicalBundle
    etf: pd.DataFrame  # `etf_prices` 프레임 (못 읽었으면 빈 프레임)
    indicators: Indicators
    unclassified_mcap: dict[str, float] | None  # 관문을 건너뛰었으면 None

    @property
    def fingerprint(self) -> str:
        return str(self.panel.built_from["fingerprint"])

    @property
    def store_end(self) -> str:
        return str(self.panel.built_from["store_end"])

    def info(self) -> dict[str, Any]:
        """메타에 싣는 공통 항목."""
        return {
            "fingerprint": self.fingerprint,
            "store_end": self.store_end,
            "panel": self.panel.built_from,
            "fund": self.fund.built_from,
        }


def unclassified_mcap_share(
    store: Store, membership: Membership, meta: pd.DataFrame
) -> dict[str, float]:
    """생존 종목 최신 시총 기준 미분류 비율 (Shell 제외). `audit_themes.py` §1 과 같은 정의.

    **시총 결측은 0 으로 덮인다** (`fillna(0.0)`). 그 종목이 미분류면 분자에 기여하지 못하므로
    관문은 **통과 쪽으로만** 틀린다. 동작은 그대로 두고 — 분모에서 뺄지 0 으로 둘지는 선언이
    없어 새 결정이 된다 (`CLAUDE.md` §1) — 대신 몇 종목이 덮였는지 **센다**
    (`docs/08` §7 "제외된 종목 수를 매번 리포트한다", `CLAUDE.md` §2). 2026-08-24.
    """
    mcap = store.latest_mcap()
    mcap_of: dict[str, float] = dict(zip(mcap.index, mcap.to_numpy(), strict=True))
    from msa.themes import EXCLUDED_LABELS, MEMBER_CATEGORIES

    uni = meta.loc[meta["category"].isin(MEMBER_CATEGORIES)].copy()
    uni["live"] = uni["is_delisted"].fillna("N") != "Y"
    uni["shell"] = uni["industry"].fillna("(null)").isin(EXCLUDED_LABELS)
    raw_mcap = uni["ticker"].str.upper().map(mcap_of)
    uni["mcap"] = raw_mcap.fillna(0.0).where(uni["live"], 0.0)
    assigned = set(membership.frame["ticker"])
    uni["assigned"] = uni["ticker"].str.upper().isin(assigned)
    denom = float(uni.loc[~uni["shell"], "mcap"].sum())
    covered = float(uni.loc[~uni["shell"] & uni["assigned"], "mcap"].sum())
    share = (denom - covered) / denom if denom > 0 else float("nan")
    # 분모 모집단(생존·비Shell) 안에서 시총이 없어 0 으로 덮인 종목
    pop = ~uni["shell"] & uni["live"]
    missing = pop & raw_mcap.isna()
    return {
        "denominator_musd": denom / 1e6,
        "unclassified_musd": (denom - covered) / 1e6,
        "share": share,
        "n_universe": int(pop.sum()),
        "n_missing_mcap": int(missing.sum()),
        "n_missing_mcap_assigned": int((missing & uni["assigned"]).sum()),
        "n_missing_mcap_unassigned": int((missing & ~uni["assigned"]).sum()),
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


def load_or_build_fund(
    store: Store,
    membership: Membership,
    fc: FingerprintCache,
    *,
    force: bool,
    end: str | None = None,
) -> FundPanel:
    """재무 패널 — 캐시가 있으면 읽고, 없으면 만들어 저장한다. `end` 는 스토어 최종일(패널 메타)."""
    if not force and fc.has(fc.fund, fc.fund_ss, fc.fund_actions, fc.fund_meta):
        log.info("fund: 캐시 사용 %s", fc.fund.name)
        return FundPanel(
            frame=fc.read_frame(fc.fund),
            same_store=fc.read_frame(fc.fund_ss),
            actions=fc.read_frame(fc.fund_actions),
            built_from=fc.read_meta(fc.fund_meta),
        )
    fund = build_fund_panel(store, membership, end=end)
    fund.frame.to_parquet(fc.fund)
    fund.same_store.to_parquet(fc.fund_ss)
    fund.actions.to_parquet(fc.fund_actions)
    fc.write_meta(fc.fund_meta, fund.built_from)
    return fund


def load_or_build_indicators(
    panel: ThemePanel,
    fund: FundPanel,
    physical: PhysicalBundle,
    themes: ThemeSet,
    fc: FingerprintCache,
    *,
    force: bool,
    compute_vcp: bool,
) -> Indicators:
    """지표 — 캐시가 있고 실물 참조 상태·`vcp_computed` 가 같으면 읽고, 아니면 계산해 저장한다."""
    phys_sig = physical.status_signature()
    if not force and fc.has(fc.indicators, fc.indicators_meta):
        im = fc.read_meta(fc.indicators_meta)
        if im.get("physical_status") == phys_sig and im.get("vcp_computed") == compute_vcp:
            log.info("indicators: 캐시 사용 %s", fc.indicators.name)
            return Indicators(monthly=fc.read_frame(fc.indicators), meta=im)
    log.info("indicators: 계산 시작 (vcp=%s)", compute_vcp)
    ind = compute_indicators(panel, fund, physical, themes, compute_vcp=compute_vcp)
    ind.meta["physical_status"] = phys_sig
    ind.monthly.to_parquet(fc.indicators)
    fc.write_meta(fc.indicators_meta, ind.meta)
    return ind


def prepare_inputs(
    *,
    force: bool = False,
    compute_vcp: bool = True,
    allow_fetch: bool = True,
    themes_path: Path | None = None,
    coverage_gate: bool = True,
) -> ScanInputs:
    """스토어 → 구성원 → 패널 → 재무 → ETF·실물 → 지표. 캐시는 지문으로 찾는다.

    `coverage_gate=True` 면 미분류 시총 비율이 `UNCLASSIFIED_MCAP_MAX` 이상일 때 `StoreError`
    (스캔 경로, `CLAUDE.md` §2). 백테스트는 `False` 로 부른다.
    """
    p = paths()
    themes = load_themes(themes_path)
    uncls: dict[str, float] | None = None
    with Store(p.duckdb) as store:
        membership = membership_from_store(store, themes)
        if len(membership.frame) == 0:
            raise StoreError("배정된 구성원이 0개다.")
        if coverage_gate:
            uncls = unclassified_mcap_share(store, membership, membership.meta)
            if not (uncls["share"] < UNCLASSIFIED_MCAP_MAX):
                raise StoreError(
                    f"미분류 시총 비율 {uncls['share']:.2%} ≥ {UNCLASSIFIED_MCAP_MAX:.0%} — "
                    "스캔을 진행하지 않는다 "
                    "(docs/01 §5). themes.yaml 의 industry_match 를 점검해라."
                )
        panel = build_panel(store, membership, cache_dir=p.cache, force=force)
        fc = FingerprintCache.at(str(panel.built_from["fingerprint"]), p.cache)
        fund = load_or_build_fund(
            store, membership, fc, force=force, end=str(panel.built_from["store_end"])
        )

    # ETF: 프록시 + 실물 참조를 한 번에
    etf = etf_prices_or_empty(etf_symbols(themes))
    physical = load_physical(
        themes, allow_fetch=allow_fetch, etf_prefetched=etf if not etf.empty else None
    )
    ind = load_or_build_indicators(
        panel, fund, physical, themes, fc, force=force, compute_vcp=compute_vcp
    )
    return ScanInputs(
        themes=themes,
        membership=membership,
        panel=panel,
        fund=fund,
        physical=physical,
        etf=etf,
        indicators=ind,
        unclassified_mcap=uncls,
    )


def _axis1_counts(scoreboard: pd.DataFrame, cpi_status: str) -> dict[str, Any]:
    """축 1 상태 집계 — **스코어보드의 `axis1_status` 하나만 센다.**

    "데이터 있음" 은 "판정할 수 있는 데이터가 있음" 이어야 한다. 시리즈를 읽었는지가 아니라
    `_unit_block` 이 실제로 무엇을 낼 수 있었는지가 기준이다.
    """
    col = scoreboard.get("axis1_status")
    if col is None:
        return {"declared": 0, "data_ok": 0, "data_missing": 0, "cpi": cpi_status}
    vc = col.value_counts()
    ok = int(vc.get(Axis1Status.OK_EXTERNAL.value, 0) + vc.get(Axis1Status.OK_FALLBACK.value, 0))
    missing = int(vc.get(Axis1Status.DATA_MISSING.value, 0))
    return {
        "declared": ok + missing,
        "data_ok": ok,
        "data_missing": missing,
        "cpi": cpi_status,
    }


def clamp_asof(asof: str | None, store_end: pd.Timestamp) -> tuple[pd.Timestamp, bool]:
    """요청 `asof` 를 스토어 최종일 이하로 내린다 — **내렸으면 말한다** (`CLAUDE.md` §2).

    스토어보다 앞선 asof 는 흔하다: `msa run daily` 는 `--asof` 가 없으면 **오늘 날짜**를 쓰고,
    스토어는 마지막 적재일(주말·미수집일이면 며칠 전)에서 끝난다. 미래 가격은 존재하지 않으므로
    마지막 완결 데이터로 계산하는 것 말고 할 수 있는 일이 없다. 그러나 그렇게 하면
    **산출물의 날짜 라벨(`state/daily/<오늘>/`, 다이제스트 제목)과 계산의 데이터 기준일이
    갈라진다** — 조용히 내리면 08-24 데이터로 만든 표를 08-26 것으로 읽게 된다.

    돌려주는 두 번째 값 `clamped` 는 그 사실을 상위 계층(스캔 메타·단계 노트·다이제스트 머리)이
    그대로 싣기 위한 것이다. 임계값이 아니라 보고 규약이므로 §1 과 무관하다.
    """
    if asof is None:
        return store_end, False
    req = pd.Timestamp(asof)
    if req <= store_end:
        return req, False
    log.warning(
        "scan: 요청 asof %s 가 스토어 최종일 %s 보다 앞선다 — %s 데이터로 계산한다 "
        "(미래 가격은 없다; 산출물의 날짜 라벨과 데이터 기준일이 다르다)",
        req.date(),
        store_end.date(),
        store_end.date(),
    )
    return store_end, True


def asof_note(meta: Mapping[str, Any]) -> str:
    """스캔 메타 → "asof 를 내렸다" 한 줄. 안 내렸으면 빈 문자열.

    단계 노트·다이제스트·월간 리포트가 **같은 문구**를 쓴다 — 같은 사실을 세 곳에서 따로
    쓰면 반드시 갈라진다 (`scan.py` 의 축 1 주석과 같은 이유).
    """
    if not meta.get("asof_clamped"):
        return ""
    return (
        f"요청 asof {meta['asof_requested']} 는 스토어 최종일 {meta['store_end']} 보다 앞선다 "
        f"— {meta['asof']} 데이터로 계산했다"
    )


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
    inp = prepare_inputs(
        force=force, compute_vcp=compute_vcp, allow_fetch=allow_fetch, themes_path=themes_path
    )
    themes, panel, ind, physical, etf = inp.themes, inp.panel, inp.indicators, inp.physical, inp.etf
    assert inp.unclassified_mcap is not None
    counts = inp.membership.counts()

    store_end = pd.Timestamp(inp.store_end)
    asof_ts, asof_clamped = clamp_asof(asof, store_end)
    sb = build_scoreboard(ind, themes, asof_ts, n_live=counts["n_live"])
    data_date = min(asof_ts, store_end)  # 버킷 라벨(월말)이 아니라 실제 데이터 기준일

    corr = etf_proxy_corr(panel, themes, etf, sb.date)
    cov = counts.reindex(themes.ids()).copy()
    cov["etf_proxy"] = [t.etf_proxy for t in themes]
    cov["etf_corr_12m"] = corr.reindex(cov.index)
    cov["etf_corr_ok"] = cov["etf_corr_12m"] > ETF_CORR_MIN
    st = physical.status_table(themes)
    cov["axis1_declared"] = st["status"].ne(Axis1Status.NOT_DECLARED.value)
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
        # 요청받은 날짜와 실제로 쓴 날짜를 **둘 다** 남긴다 — 같으면 같고, 다르면 다르다는
        # 사실 자체가 산출물에 남아야 한다 (`clamp_asof` 주석 · `CLAUDE.md` §2).
        "asof_requested": str(pd.Timestamp(asof).date()) if asof else str(store_end.date()),
        "asof_clamped": asof_clamped,
        "bucket": str(sb.date.date()),
        "store_end": inp.store_end,
        "fingerprint": inp.fingerprint,
        "themes": len(themes),
        "membership": inp.membership.report(),
        "unclassified_mcap": inp.unclassified_mcap,
        "panel": panel.built_from,
        "fund": inp.fund.built_from,
        "indicators": {k: v for k, v in ind.meta.items() if k != "physical_status"},
        # 축 1 상태는 **스코어보드가 단일 출처다.** 예전에는 `physical.status_table`(시리즈를
        # 읽었는가)로 세고 스코어보드는 `_unit_block`(판정을 낼 수 있는가)으로 채워, 10년을
        # 못 채우는 시리즈가 머리줄에서는 "데이터 있음" 이고 표에서는 `data_missing` 이었다
        # (2026-08-25). 같은 사실을 두 곳에서 세면 반드시 갈라진다.
        "physical": _axis1_counts(sb.table, physical.cpi.status),
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
        root = out_root if out_root is not None else paths().scans
        row = ind.at(sb.date)
        ordered = [i for b in BLOCK_INDICATORS.values() for i in b if i in row.columns]
        ordered += [c for c in (*TEXT_OUTPUTS, *FLAG_OUTPUTS) if c in row.columns]
        out_dir = write_snapshot(
            root / str(data_date.date()),
            frames={
                "scoreboard.csv": sb.table,
                "indicators.csv": row[ordered],
                "indicator_pct.csv": sb.indicator_pct,
                "coverage.csv": cov,
            },
            jsons={"meta.json": scan_meta},
            texts={"report.txt": render_report(sb, cov, scan_meta)},
        )
        log.info("scan: 저장 %s", out_dir)
    return ScanResult(scoreboard=sb, indicators=ind, coverage=cov, meta=scan_meta, out_dir=out_dir)


def scan_dirs(root: Path | None = None) -> list[tuple[date, Path]]:
    """`state/scans/<YYYY-MM-DD>/` 스냅샷 디렉터리를 (날짜, 경로) 로 날짜 오름차순. 이름이 날짜가
    아닌 것은 건너뛴다. 루트가 없으면 빈 목록 — L3·ops 가 최신/이하 스냅샷을 고를 때 쓴다."""
    base = root if root is not None else paths().scans
    if not base.exists():
        return []
    out: list[tuple[date, Path]] = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        try:
            out.append((parse_date(d.name), d))
        except ValueError:
            continue
    return sorted(out)


def render_report(sb: Scoreboard, cov: pd.DataFrame, meta: dict[str, Any]) -> str:
    lines = [
        sb.render().replace(str(sb.date.date()), f"{meta['asof']} (버킷 {meta['bucket']})", 1),
        "",
        "=" * 78,
        "커버리지·결측 보고 (CLAUDE.md §2 — 제외는 보고한다)",
        "=" * 78,
    ]
    if meta.get("asof_clamped"):
        lines.append(
            f"asof: 요청 {meta['asof_requested']} 은 스토어 최종일 {meta['store_end']} 보다 "
            f"앞선다 — {meta['asof']} 데이터로 계산했다 (미래 가격은 없다)"
        )
    lines.append(f"구성원: {meta['membership']}")
    u = meta["unclassified_mcap"]
    lines.append(
        f"미분류 시총 비율: {u['share']:.3%} (기준 < 5%) · 분모 {u['denominator_musd']:,.0f} M USD"
    )
    if "n_missing_mcap" in u:  # 2026-08-24 이전 스냅샷에는 없다 (`msa ops reproduce`)
        lines.append(
            f"  시총 결측 → 0 으로 덮인 종목: {u['n_missing_mcap']:,}/{u['n_universe']:,} "
            f"(미배정 {u['n_missing_mcap_unassigned']:,} · 배정 {u['n_missing_mcap_assigned']:,}) "
            "— 미배정분은 위 비율을 낮추는 쪽으로만 작용한다 (관문이 통과 쪽으로 틀린다)"
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
