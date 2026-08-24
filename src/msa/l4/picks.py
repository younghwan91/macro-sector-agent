"""`msa picks <theme>` 오케스트레이션 — 특성 → 하드 필터 → (3축·바벨은 관찰) → 파일.

## 선정 규칙 (2026-08-24 개정)

**하드 제외를 통과한 적격 종목 전부. 테마 내 동일가중. 그것이 전부다.**

동일가중은 "가중치를 정한 것" 이 아니라 **정하지 않은 것**이다 — 적격 종목 사이를 갈라 놓을
근거가 이 경로에서 확인되지 않았으므로(`docs/15` §4 — B0·B1·B2 중 아무도 B3 를 이기지 못했다)
가르지 않는다. 새 가중치를 만든 것이 아니다 (`CLAUDE.md` §1).

`rank_score`(`composite`) · `rank` · `group` · 3축 백분위(`s_pct`·`t_pct`·`m_pct`) ·
바벨 라벨(`barbell_obs`)은 **관찰 지표**로 계속 계산·수록되지만 **무엇을 사는지를 정하지
않는다.** 근거·경위는 `journal/2026-08-24-l4-selection-retired.md`, 판정은 `docs/backtest-l4.md`
와 `docs/15` §4.

산출물 `state/picks/<asof>/<theme>/`:

| 파일 | 내용 |
|---|---|
| `ranking.csv` | 적격 종목 **전부**(= 선정 결과) + 관찰 지표(순위·3축·종합·바벨 라벨)·특성 원값 |
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


#: 선정 라벨 — `ranking.csv` 의 `group` 열이 적격 종목 **전원**에게 갖는 값 (2026-08-24).
#: 옛 값 `ANCHOR`/`TORQUE` 는 "바벨의 어느 통에 뽑혔나" 였고, 그 선정이 폐기됐으므로 이 열은
#: 이제 남은 유일한 편입 근거인 **"하드 제외를 통과했다"** 만 담는다. 값이 한 종류인 것이
#: 동일가중의 표현이다 — 행을 가르는 열이 없다. 열을 지우지 않는 이유는 하위 호환
#: (`pipeline.assemble._RANKING_REQUIRED` · `l5.inputs` 의 `role`)이고, 옛 스냅샷의
#: `ANCHOR`/`TORQUE` 도 계속 읽힌다 (`assemble.ROLE_BY_GROUP`).
SELECTION_GROUP = "ELIGIBLE"

#: `ranking.csv` 에서 L5 입력으로 옮겨 가는 열 (`msa.pipeline.assemble`). 선정 라벨 · 관찰용
#: 바벨 라벨 · 관찰용 순위·종합·3축 백분위 · 기준가 · 유동성 · 표기용 플래그.
#: 이 밖의 열은 리포트 전용이다. **`rank`·`composite`·`*_pct`·`barbell_obs` 는 표기용이고
#: 선정에 쓰이지 않는다** (모듈 docstring).
#: 2026-08-24 추가 — `nd_basis`(그 종목의 `net_debt_ebitda` 가 EBITDA 공간인지 시총 공간인지) ·
#: `s_partial`(S 하위 항목 결측으로 `s_raw` 가 재정규화됐다) · `m_inputs_missing`(S·T 와 같은 형식).
#: 셋 다 **표시**이고 어떤 판정도 바꾸지 않는다.
RANKING_EXPORT_COLUMNS: tuple[str, ...] = (
    "group",
    "barbell_obs",
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
    "nd_basis",
    "s_partial",
    "s_inputs_missing",
    "t_inputs_missing",
    "m_inputs_missing",
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
    """특성 표 → (ranking, excluded, barbell). 순수 함수 — 합성 FeatureSet 으로 테스트된다.

    **선정은 하드 제외를 통과한 적격 종목 전부다** (2026-08-24 · 모듈 docstring). `ranking` 의
    모든 행이 선정이고 서로 동일가중이며, `group` 은 전원 `SELECTION_GROUP` 이다.

    `top` 은 **관찰용 바벨 라벨(`barbell_obs`)의 개수**일 뿐 선정 개수가 아니다. 반환되는
    `ranking` 의 행 수는 `top` 과 무관하다.
    """
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
    # 바벨은 관찰 — 이 라벨은 ranking 의 행을 하나도 걸러 내지 않는다 (2026-08-24)
    bb = classify(sc.join(eligible[["marginal_producer"]]), top=top)
    ranking = sc.join(eligible, how="left")
    ranking.insert(0, "group", SELECTION_GROUP)
    ranking.insert(1, "barbell_obs", [bb.label(str(t)) for t in ranking.index])
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
    """테마 하나의 L4 산출물. **선정 = 적격 종목 전부 · 동일가중** (`rank_theme`).

    `top` 은 관찰용 바벨 라벨의 개수일 뿐 선정 개수가 아니다 — 무엇이 산출물에 남는지를 바꾸지
    않는다.
    """
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
    unapplied = _unapplied_filters(fs, ranking)
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
            # `docs/06` §5 는 min_constituents 미달 시 ETF 대체를 규정하지만 **L4·L5 경로에
            # 구현이 없다** (`etf_proxy` 는 L1 검증용). 2026-08-24 까지 리포트가 대체를 한 것처럼
            # 적고 있었다 — 문구를 고치고 `docs/06` §8.4 에 미구현으로 올렸다.
            "etf_fallback_declared": theme.etf_proxy,
            "etf_fallback_implemented": False,
            "etf_fallback_note": (
                "docs/06 §5 가 규정하나 미구현 (docs/06 §8.4). etf_proxy 는 L1 검증용이고 "
                "L4/L5 경로에서 읽히지 않는다 — 미달이어도 대체하지 않는다"
            ),
        },
        "selection": {
            "rule": "하드 제외 통과 종목 전부 · 테마 내 동일가중 (docs/06 §5.1·§6.1 · docs/15 §5)",
            "n_selected": len(ranking),
            "group_label": SELECTION_GROUP,
            "retired": (
                "바벨 선정(앵커/토크 2~4 종목)과 종합 점수 랭킹은 2026-08-24 에 선정 경로에서 "
                "빠졌다 — journal/2026-08-24-l4-selection-retired.md"
            ),
            "observation_only": [
                "rank",
                "composite",
                "s_pct",
                "t_pct",
                "m_pct",
                "barbell_obs",
            ],
            "open_question": (
                "운용 가능한 K(테마당 몇 종목까지 실제로 들 것인가)는 정하지 않았다 — "
                "새 사전 등록이 필요하다 (docs/06 §6.2)"
            ),
        },
        "barbell_observation": {
            "anchors": bb.anchors,
            "torques": bb.torques,
            "anchor_count_share": bb.anchor_share,
            "top": top,
            "note": "관찰용 — 선정에 쓰이지 않는다. 비중 밴드도 마찬가지",
            "weight_band_doc": "앵커 55~70% / 토크 30~45% (docs/06 §5, 2026-08-24 이전 판)",
        },
        # 입력이 없어 **걸지 못한** 하드 필터의 종목 수 — 제외가 아니다 (2026-08-24 재개정).
        # 이 수가 보이지 않으면 리포트가 "만기벽 필터가 있다" 고 말하면서 실제로는 그 필터가
        # 걸리지 않은 종목을 적격으로 내놓는다 (`CLAUDE.md` §2 · `docs/06` §2.1).
        "filters_unapplied": unapplied,
        "inputs_unavailable": fs.inputs_unavailable,
        "inputs_unused": INPUTS_UNUSED,
        "inputs_missing_per_stock": _inputs_missing(ranking),
        # `net_debt_ebitda` 는 EBITDA>0 이면 순부채/EBITDA, EBITDA≤0 이면 순부채/시총이다
        # (`docs/06` §2 가 선언한 대체). **하드 제외 임계 6× 는 basis 와 무관하게 같은 값**이라
        # 시총 공간에서는 사실상 발동하지 않는다 — 어느 종목이 어느 공간에서 평가됐는지를
        # 산출물에 남긴다 (`docs/06` §8.2 · `docs/backtest-l4.md` §10 #12).
        "nd_basis_counts": _nd_basis_counts(ranking),
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


def _unapplied_filters(fs: FeatureSet, ranking: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """하드 필터별 **미적용** 계수 (`axes.FILTER_UNAPPLIED_CODES`).

    `n_evaluated` 는 재무가 있어 하드 필터를 실제로 돌린 종목 수, `n_unapplied` 는 그중 입력이
    없어 그 필터를 걸지 못한 수, `n_unapplied_eligible` 는 그러고도 적격으로 남은 수다.
    셋째가 이 저장소가 실제로 신경 쓰는 수다 — 리포트에 나오는 종목 중 그 필터를 통과한 것이
    아니라 **평가받지 않은** 것이 몇인가.
    """
    out: dict[str, dict[str, Any]] = {}
    if not len(fs.frame):
        return out
    flags = axes.unapplied_filter_flags(fs.frame)
    evaluated = fs.frame["fund_calendardate"].notna()
    for code in axes.FILTER_UNAPPLIED_CODES:
        f = flags[code]
        elig = f.loc[f.index.isin(ranking.index)] if len(ranking) else f.iloc[:0]
        out[code] = {
            "filter": axes.HARD_REASON_LABELS[code],
            "column": axes.FILTER_UNAPPLIED_COLUMN[code],
            "n_evaluated": int(evaluated.sum()),
            "n_unapplied": int(f.sum()),
            "n_unapplied_eligible": int(elig.sum()),
            "note": axes.FILTER_UNAPPLIED_LABELS[code],
        }
    return out


def _nd_basis_counts(ranking: pd.DataFrame) -> dict[str, int]:
    """적격 종목의 `nd_basis` 분포 — `ebitda`(순부채/EBITDA) · `mcap`(EBITDA≤0 대체) · `n/a`."""
    if ranking.empty or "nd_basis" not in ranking.columns:
        return {}
    return {str(k): int(v) for k, v in ranking["nd_basis"].astype(str).value_counts().items()}


def _inputs_missing(ranking: pd.DataFrame) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if ranking.empty:
        return out
    for tk, r in ranking.iterrows():
        d = {
            axis: _txt(r, key)
            for axis, key in (
                ("S", "s_inputs_missing"),
                ("T", "t_inputs_missing"),
                ("M", "m_inputs_missing"),
            )
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
    """종목 한 블록. `group` 은 선정 라벨(전원 동일), 머리의 등수·종합·바벨은 관찰 지표다."""
    f = ratio
    bb_obs = _txt(r, "barbell_obs")
    head = (
        f"{tk} · {theme} · {group or '—'}   [관찰 #{int(r['rank'])} · "
        f"종합 {f(r['composite'], digits=2)}"
        + (f" · 바벨 {bb_obs}" if bb_obs else "")
        + "]"
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
        # S 하위 항목이 빠지면 `s_raw` 는 남은 항목만으로 재정규화된다 — 모름이 최상으로
        # 보일 수 있어 그 사실을 여기 적는다 (2026-08-24 · `axes.survival` docstring)
        + (" · S 부분(하위 항목 결측 — 재정규화)" if bool(r.get("s_partial", False)) else "")
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
        for axis, key in (
            ("S", "s_inputs_missing"),
            ("T", "t_inputs_missing"),
            ("M", "m_inputs_missing"),
        )
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
    obs = meta.get("barbell_observation", {})
    L: list[str] = [
        f"L4 종목 선정 — {fs.theme} ({theme_name})  asof {meta['asof']} "
        f"(스토어 {meta['store_end']})",
        "=" * 78,
        f"구성원 {u['members']} → 상장 {u['listed']} (폐지/가격없음 {u['excluded_listing']}) → "
        f"하드 제외 {u['excluded_hard_filter']} → 적격 {u['eligible']}"
        + (
            f"   ※ min_constituents {u['min_constituents']} 미달 — "
            f"docs/06 §5 는 ETF 대체({u['etf_fallback_declared'] or 'ETF 미선언'})를 규정하나 "
            "**미구현**이다 (docs/06 §8.4). 이 실행은 대체하지 않았다"
            if u["below_min_constituents"]
            else ""
        ),
        "",
        f"선정: 적격 {u['eligible']} 종목 **전부** · 테마 내 동일가중 (라벨 {SELECTION_GROUP})",
        "  동일가중은 가중치를 정한 것이 아니라 정하지 않은 것이다 — 적격 종목 사이를 가를 근거가",
        "  이 경로에서 확인되지 않았다 (docs/15 §4·§5 · docs/06 §5.1·§6.1). 비중은 L5 가 정한다.",
        "  운용 가능한 K 는 정해져 있지 않다 — 새 사전 등록이 필요하다 (docs/06 §6.2).",
        "",
        f"바벨 (관찰용 · 선정에 쓰이지 않는다): 앵커 {len(bb.anchors)} "
        f"[{', '.join(bb.anchors) or '—'}] · 토크 {len(bb.torques)} "
        f"[{', '.join(bb.torques) or '—'}] · 앵커 수 비중 {anchor_share_txt}",
        f"  옛 규칙이라면 무엇을 골랐을까 — {obs.get('weight_band_doc', '')}",
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
    # 걸지 못한 하드 필터 — 제외가 아니라 **미적용**이다 (2026-08-24 재개정 · docs/06 §2.1).
    # 이 줄이 없으면 리포트가 만기벽 필터를 걸었다고 읽힌다 (CLAUDE.md §2).
    ua = meta.get("filters_unapplied", {})
    if ua:
        L.append("걸지 못한 하드 필터 (제외가 아니다 — 그 종목엔 이 필터가 적용되지 않았다)")
        for code, d in ua.items():
            L.append(
                f"  {code} {d['filter']}: 평가 대상 {d['n_evaluated']} 중 "
                f"입력 없음 {d['n_unapplied']} (그중 적격으로 남은 것 "
                f"{d['n_unapplied_eligible']}) — {d['column']} 결측"
            )
        L.append(
            "  선언된 필터는 maturity_wall_24m 이고 SF1 에 만기 스케줄이 없어 **누구에게도** "
            "계산되지 않는다."
        )
        L.append(
            "  E3 는 대용치 maturity_wall_12m(debtc/시총) 이 있는 종목에서만 걸린다 — "
            "없다고 제외하지 않는다 (docs/06 §2.1)."
        )
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
        "적격 종목 — 아래 전부가 선정이고 서로 동일가중이다 (순서는 표기 편의)."
    )
    L.append(
        "  관찰 지표 (선정에 쓰이지 않는다): #순위 · 종합 = 0.40·S̃ + 0.40·T̃ + 0.20·M̃ · "
        "바벨 라벨 · 틸데 = 테마 내 백분위"
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
