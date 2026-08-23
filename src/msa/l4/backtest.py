"""L4 종목 선정 백테스트 — `docs/14-l4-backtest-preregistration.md` 의 집행.

**이 모듈은 사전 등록 문서를 해석하지 않는다. 실행한다.** 아래 상수·정의는 전부 `docs/14` 에서
왔고, 그 문서의 절 번호를 옆에 적었다. 결과를 보고 바꾸지 않는다 (`CLAUDE.md` §1). 재는 것은
**스코어의 예측력**이지 전략의 수익률이 아니다 (`CLAUDE.md` §7).

## 기계는 L1 것을 그대로 쓴다 (`docs/14` 머리말)

`spearman`(`_spearman_rows`) · `block_bootstrap_mean`(12개월 블록 · 2000회 · 시드 0) ·
`ar1`/`effective_n` · `mean_pairwise_corr` · `_summarize` · `dsr_of_series` · `pbo_of_spreads` 를
`msa.l1.backtest` 에서 import 한다. 여기서 새로 만든 통계 함수는 없다.

## 설계 (`docs/14` §2 — 실행 전에 고정된 것)

| 항목 | 값 | 출처 |
|---|---|---|
| 격자 | 월말 | §2.4 |
| 주 검정 창 | 2011-01– (`PRIMARY_START`) · 보조 창 전 구간 | §2.4 |
| 호라이즌 | 3·6·12M · **관문 12M** | §2.4 |
| 횡단면 | **테마 내**. 테마-월의 `n < 20` 이면 IC 를 만들지 않고 제외 수로 센다 | §2.2 |
| 월별 IC | 자격 테마들의 **테마 동일가중** 평균 (종목 수 가중이 아니다) | §2.2 |
| 1차 지표 | 주 창 · 12M · `rank_score` 테마 내 rank-IC 평균의 95% 블록 부트스트랩 CI | §2.1 |
| 변형 | `rank_score`(=`composite`) · S̃ · T̃ · M̃ | §6.2 |
| 전진 수익률 | `close`(조정). 폐지 구간은 **마지막 종가에서 동결** | §2.4 · §3.4 |
| 스프레드 | 테마 EW 초과의 상위 3 − 하위 3 | §2.4 |
| 필터 | E1~E5 사유별 `제외군 − 통과군` 초과수익 차 · 사망률 차 | §2.5 |
| 시도 수 | 458 (`count_trials`) | §6.2 |

## 합격 기준 (`docs/14` §4.1 — 여기서 만들지 않는다)

- **Q1**: 주 창 · 12M · `rank_score` IC 의 95% CI **하한 > 0**.
- **Q2**(축) · **Q4**(지표): 관문이 아니다. 표로만.
- **Q3**: E1·E2·E3 각각 `제외군 − 통과군` 12M 초과수익 차의 CI **상한 < 0** → "손실을 막았다".
  E4·E5 는 **판정하지 않는다** — 수치만.
- **DSR·PBO 는 합격 기준에 들어가지 않는다.** 계산해서 반드시 싣는다 (§4.1 · §6).

## 해석상 고정한 것 (문서가 명시하지 않아 실행 전에 여기서 선언한다)

- 테마-월의 `n` 은 **점수와 전진 수익률이 둘 다 있는 짝의 수**다 (L1 `_spearman_rows` 의 `n` 과
  같은 규칙). 자격 판정을 통과한 종목 수(`n_eligible`)는 따로 싣는다.
- **총 구성원이 20 미만인 테마는 격자를 돌지 않는다.** `n ≤ n_listed ≤ n_total` 이므로 그런
  테마는 어느 달에도 `n ≥ 20` 이 될 수 없다 — 임계를 바꾸는 것이 아니라 임계의 논리적 귀결이다.
  건너뛴 테마와 그 구성원 수는 전부 `exclusions.json` 에 적는다 (`CLAUDE.md` §2).
- 테마-월 EW 기준(초과수익의 기준)은 **그 달 상장 구성원 중 전진 수익률이 있는 것 전부**의
  동일가중 평균이다 (제외군 포함) — §2.5 의 "그 테마-월 전체 구성원 동일가중 평균".
- `build_features` 가 스토어 사정으로 던지는 달(SPY 달력 부족 등)은 **사유별로 세어** 보고한다.
- 백분위(S̃·T̃·M̃)와 지표는 `msa picks` 와 **같은 자리**에서 계산된다 — 하드 필터 통과 집합 안에서
  (`axes.score` 가 적격 표를 받는다). 백테스트가 별도 규약을 만들지 않는다.

## 산출물 (`state/backtests/l4/<store_end>/`)

| 파일 | 내용 |
|---|---|
| `ic_summary.csv` | window × horizon × variant × partition 요약 (1차 지표가 여기 한 줄) |
| `ic_timeseries.csv` | 월별 IC 시계열 (테마 동일가중) |
| `ic_theme_month.csv` | 테마-월 단위 IC 원시 (관문 12M) |
| `ic_indicator.csv` | 15개 하위 지표 단독 IC (Q4) |
| `spread.csv` · `spread_summary.csv` | 테마 내 상위 3 − 하위 3 |
| `filters.csv` · `filters_summary.csv` | Q3 — 사유별 초과수익 차 · 사망률 차 (기본 · D1) |
| `effective_sample.json` | §2.3 유효 표본 (리포트 첫 표) |
| `overfitting.json` · `exclusions.json` · `verdict.json` · `meta.json` · `report.txt` | |
"""

from __future__ import annotations

import logging
import math
import os
import sys
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from msa.config import paths
from msa.data.store import Store, StoreError
from msa.fmt import num as _fmt
from msa.io import dump_json, write_snapshot
from msa.l1.backtest import (
    BOOT_BLOCK,
    BOOT_N,
    BOOT_SEED,
    DSR_THRESHOLD,
    GATE_HORIZON,
    HORIZONS,
    MIN_THEMES_XS,
    PARTITION_ALL,
    PBO_BLOCKS,
    PBO_HORIZON,
    PBO_MAX_SPLITS,
    PBO_THRESHOLD,
    PRIMARY_START,
    WINDOWS,
    _plain,
    _spearman_rows,
    _summarize,
    dsr_of_series,
    mean_pairwise_corr,
    pbo_of_spreads,
)
from msa.l4 import axes
from msa.l4.features import FeatureSet, build_features
from msa.themes import CYCLE_CLASSES, Membership, ThemeSet, load_themes, membership_from_store

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 선언 상수 (docs/14 — 불변)

#: 테마 내 횡단면 최소 종목 수 (§2.2). L1 `MIN_THEMES_XS` 와 **같은 규칙에서 나온 같은 숫자**다.
MIN_STOCKS_XS = MIN_THEMES_XS
#: 스프레드 컷오프 — 테마 내 상위 3 − 하위 3 (§2.4, `docs/06` §5 "테마당 2~4 종목").
SPREAD_K = 3
#: 격자 시작 (§2.4 보조 창 "전 구간 1998–"). Sharadar SEP 는 1997-12-31 시작 (`docs/08` §6.2).
GRID_START = pd.Timestamp("1998-01-31")
#: 변형 4종 (§6.2). `rank_score` 는 `axes.score` 의 `composite` 다 (`docs/06` §6 과 같은 물건).
VARIANTS: tuple[str, ...] = ("rank_score", "S", "T", "M")
VARIANT_COLUMN: dict[str, str] = {
    "rank_score": "composite",
    "S": "s_pct",
    "T": "t_pct",
    "M": "m_pct",
}
#: Q4 의 15개 하위 지표 (§1 Q4) — S 3 + T 6 + M 6. 축이 실제로 먹는 값을 그대로 읽는다.
INDICATORS: tuple[str, ...] = (
    *axes.S_COMPONENTS,
    *(f"tp_{c}" for c in axes.T_COMPONENTS),
    *axes.M_COMPONENTS,
)
#: §2.5 · §3.4 D1 의 "사망" — `actions` 의 이 두 종류.
DEATH_ACTIONS: tuple[str, ...] = ("bankruptcyliquidation", "regulatorydelisting")
#: Q3 의 두 눈금 (§2.5).
FILTER_GAUGES: tuple[str, ...] = ("excess", "death")
#: 전진 수익률 기준 (§3.4): `base` = 동결 1차 · `d1` = 파산·규제폐지만 −100% (민감도).
RETURN_BASES: tuple[str, ...] = ("base", "d1")
#: 총 구성원이 이보다 적은 테마는 어느 달에도 `n ≥ MIN_STOCKS_XS` 가 될 수 없다 (임계의 귀결).
MIN_MEMBERS_POSSIBLE = MIN_STOCKS_XS

assert len(INDICATORS) == 15, INDICATORS

#: 리포트·`meta.json` 에 그대로 싣는 한계 (`docs/14` §5 + 실행 중 실측되는 두 가지).
#: 결과를 어느 쪽으로 읽든 이 문장들이 함께 붙어야 한다.
LIMITATIONS: tuple[str, ...] = (
    "L3 확신도가 없다 · 테마 선정이 조건으로 들어가지 않는다 · 바벨과 L5 가 없다 "
    "— 재는 것은 '테마가 주어졌을 때 스코어가 종목 순서를 아는가' 뿐이다 (docs/14 §5).",
    "테마 배정은 오늘의 `tickers.industry` 를 전 구간에 소급한다 (docs/14 §3.5 · §5-8).",
    "`maturity_wall` 은 24m 이 아니라 12m 대용이다 — E3 의 제외군이 설계보다 작다 (§5-7).",
    "재무 **재보고 빈티지**가 스토어에 없으면 '최초 보고분만' 규칙은 무연산이고 정정 최종치가 "
    "원 공시일에 붙어 소급 사용된다 — 실측값은 `meta.json` 의 `pit_vintage` (고칠 수 없다).",
    "`price_beta_hist` 는 테마 physical_ref 와 그 소스 데이터가 있어야 계산된다. 없는 테마에서 "
    "T 축은 6개가 아니라 5개로 돈다 — 몇 테마가 몇 개로 돌았는지는 `exclusions.json` 의 "
    "`indicator_missing` (§5-5 · CLAUDE.md §2).",
    "1998년 이전이 없고 표본이 사실상 하나(1998~2026 미국 시장 단일 경로)다 (§5-9 · §5-10).",
)

#: 테마별 특성 패널의 열 (parquet 캐시 스키마).
PANEL_COLUMNS: tuple[str, ...] = (
    "date",
    "ticker",
    "eligible",
    *axes.HARD_REASON_CODES,
    "composite",
    "s_pct",
    "t_pct",
    "m_pct",
    "composite_partial",
    *INDICATORS,
)
#: 테마-월 계수 (제외 집계의 원재료 — `CLAUDE.md` §2).
COUNT_COLUMNS: tuple[str, ...] = (
    "date",
    "n_members",
    "n_listed",
    "n_delisted",
    "n_no_recent_price",
    "n_eligible",
    *(f"n_{c}" for c in axes.HARD_REASON_CODES),
    "n_excluded_any",
    "n_composite_partial",
    "n_s_na",
    "n_t_na",
    "n_m_na",
    "error",
)


def count_trials() -> dict[str, int]:
    """DSR 시도 수 — `docs/14` §6.2 의 식을 **그대로**.

        per_window = V×H×(2 + C) + V×1 + F×H + E×H×2
        total      = W × per_window + 민감도 D1 (E×H×W×2)

    선언만 세면 1 이다 (Q1 하나). 둘 다 적는다. 458 은 **하한**이며, 리포트가 이보다 많은 칸을
    들여다보면 그 수만큼 늘린다 (§6.2).
    """
    v, h, w = len(VARIANTS), len(HORIZONS), len(WINDOWS)
    c, f, e = len(CYCLE_CLASSES), len(INDICATORS), len(axes.HARD_REASON_CODES)
    per_window = v * h * (2 + c) + v * 1 + f * h + e * h * 2
    d1 = e * h * w * 2
    return {
        "variants": v,
        "horizons": h,
        "windows": w,
        "classes": c,
        "indicators": f,
        "filter_reasons": e,
        "filter_gauges": 2,
        "metrics_on_all_partition": 2,
        "monthly_spread_horizons": 1,
        "per_window": per_window,
        "windows_total": w * per_window,
        "sensitivity_d1": d1,
        "declared_only": 1,
        "total": w * per_window + d1,
    }


# ---------------------------------------------------------------- 테마별 특성 패널 (비싼 부분)


def month_grid(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """월말 격자 (§2.4). 끝점은 마지막 **완결** 월말이다 — 부분 월은 쓰지 않는다."""
    return pd.date_range(start, pd.Timestamp(end), freq="ME")


def month_panel(fs: FeatureSet) -> tuple[pd.DataFrame, dict[str, Any]]:
    """한 테마-월의 특성 표 → (종목별 패널 행, 계수). `msa picks` 와 같은 순서로 부른다.

    상장 판정(`FeatureSet.universe.listed`) → 하드 필터(`axes.hard_filter_flags`) → 적격 표에
    `axes.score`. 백분위·종합은 **적격 집합 안에서** 계산된다 — `picks.rank_theme` 과 같은 자리다.
    """
    uni = fs.universe
    listed = uni["listed"].astype(bool)
    is_del = uni["is_delisted"].astype(str).eq("Y")
    counts: dict[str, Any] = {
        "date": fs.asof,
        "n_members": len(uni),
        "n_listed": int(listed.sum()),
        "n_delisted": int((~listed & is_del).sum()),
        "n_no_recent_price": int((~listed & ~is_del).sum()),
        "error": "",
    }
    frame = fs.frame
    rows = pd.DataFrame(index=frame.index)
    if frame.empty:
        counts.update(
            n_eligible=0,
            n_excluded_any=0,
            n_composite_partial=0,
            n_s_na=0,
            n_t_na=0,
            n_m_na=0,
            **{f"n_{c}": 0 for c in axes.HARD_REASON_CODES},
        )
        return pd.DataFrame(columns=list(PANEL_COLUMNS)), counts

    flags = axes.hard_filter_flags(frame)
    excluded = flags.any(axis=1)
    rows["eligible"] = ~excluded
    for code in axes.HARD_REASON_CODES:
        rows[code] = flags[code].to_numpy()
    for col in ("composite", "s_pct", "t_pct", "m_pct", *INDICATORS):
        rows[col] = np.nan
    rows["composite_partial"] = False

    elig = frame.loc[~excluded]
    if len(elig):
        sc = axes.score(elig).reindex(elig.index)
        mc = axes.timing_components(elig)
        for col in ("composite", "s_pct", "t_pct", "m_pct"):
            rows.loc[elig.index, col] = sc[col].to_numpy(dtype=float)
        rows.loc[elig.index, "composite_partial"] = sc["composite_partial"].to_numpy(dtype=bool)
        for ind in INDICATORS:
            src = mc[ind] if ind in mc.columns else sc[ind]
            rows.loc[elig.index, ind] = pd.to_numeric(src, errors="coerce").to_numpy(dtype=float)

    counts.update(
        n_eligible=int((~excluded).sum()),
        n_excluded_any=int(excluded.sum()),
        n_composite_partial=int(rows["composite_partial"].sum()),
        n_s_na=int(rows.loc[rows["eligible"], "s_pct"].isna().sum()),
        n_t_na=int(rows.loc[rows["eligible"], "t_pct"].isna().sum()),
        n_m_na=int(rows.loc[rows["eligible"], "m_pct"].isna().sum()),
        **{f"n_{c}": int(flags[c].sum()) for c in axes.HARD_REASON_CODES},
    )
    rows = rows.reset_index().rename(columns={"index": "ticker"})
    rows.insert(0, "date", fs.asof)
    return rows[list(PANEL_COLUMNS)], counts


def theme_panel(
    store: Store,
    themes: ThemeSet,
    membership: Membership,
    theme_id: str,
    dates: Sequence[pd.Timestamp],
    *,
    cache_dir: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """한 테마의 전 월말 특성 패널 (긴 표) 과 월별 계수. parquet 으로 캐시한다.

    `build_features` 가 던지는 달은 **행을 만들지 않고 `error` 로 센다** — 조용히 버리지 않는다
    (`CLAUDE.md` §2). 캐시 키는 (테마, 격자 첫·마지막 달, 달 수) 이고 파일 이름에 그대로 들어간다.
    """
    tag = f"{theme_id}__{dates[0].date()}__{dates[-1].date()}__{len(dates)}"
    p_panel = cache_dir / f"{tag}.panel.parquet" if cache_dir else None
    p_counts = cache_dir / f"{tag}.counts.parquet" if cache_dir else None
    if p_panel is not None and p_counts is not None and p_panel.exists() and p_counts.exists():
        return pd.read_parquet(p_panel), pd.read_parquet(p_counts)

    theme = themes.get(theme_id)
    panels: list[pd.DataFrame] = []
    counts: list[dict[str, Any]] = []
    for d in dates:
        try:
            fs = build_features(store, theme, membership, asof=d, allow_fetch=False)
        except (StoreError, ValueError, KeyError) as e:  # 사유를 적어 센다
            counts.append({"date": d, "error": f"{type(e).__name__}: {e}"})
            continue
        rows, cnt = month_panel(fs)
        if len(rows):
            panels.append(rows)
        counts.append(cnt)
    panel = (
        pd.concat(panels, ignore_index=True)
        if panels
        else pd.DataFrame(columns=list(PANEL_COLUMNS))
    )
    cf = pd.DataFrame(counts).reindex(columns=list(COUNT_COLUMNS))
    cf["error"] = cf["error"].fillna("")
    panel["theme"] = theme_id
    cf["theme"] = theme_id
    if p_panel is not None and p_counts is not None:
        _write_parquet_atomic(panel, p_panel)
        _write_parquet_atomic(cf, p_counts)
    return panel, cf


def _write_parquet_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


# ---- 병렬 실행 (테마 단위) — 워커마다 DuckDB 연결을 따로 연다 (스레드 공유 금지)

_W: dict[str, Any] = {}


def _worker_init(db_path: str, themes_path: str | None, state_dir: str) -> None:
    os.environ["MSA_STATE"] = state_dir
    store = Store(db_path)
    themes = load_themes(themes_path) if themes_path else load_themes()
    _W["store"] = store
    _W["themes"] = themes
    _W["membership"] = membership_from_store(store, themes)


def _worker_theme(
    args: tuple[str, list[pd.Timestamp], str | None],
) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    theme_id, dates, cache = args
    panel, counts = theme_panel(
        _W["store"],
        _W["themes"],
        _W["membership"],
        theme_id,
        dates,
        cache_dir=Path(cache) if cache else None,
    )
    return theme_id, panel, counts


def prewarm_rs_cache(store: Store, dates: Sequence[pd.Timestamp], *, progress: bool = True) -> int:
    """월말마다 `universe_rs` 를 미리 만들어 둔다 (`state/cache/rs_universe_<asof>_<end>.parquet`).

    RS 는 **전체 유니버스 백분위**라 테마와 무관하다 (`docs/14` §3.5). 테마별 워커가 각자 만들면
    같은 asof 를 14번 계산한다 — 값은 같지만 시간이 14배다. 부모가 한 번 만들어 두면 워커는 읽기만
    한다. 달력이 부족한 이른 달(SPY 200거래일 미만)은 여기서 못 만들고, 그 달은 워커가 사유와 함께
    센다 (`counts.error`). 반환값은 **만든 달 수**다.
    """
    from msa.l4.features import _trading_dates, universe_rs_cached

    se = store.store_end()
    store_end = pd.Timestamp(se) if se else pd.Timestamp.today().normalize()
    made = 0
    for i, d in enumerate(dates, 1):
        try:
            td = _trading_dates(store, pd.Timestamp(d))
            universe_rs_cached(store, td, asof=pd.Timestamp(d), store_end=store_end)
            made += 1
        except (StoreError, ValueError, KeyError) as e:
            log.info("l4-backtest: RS 캐시 건너뜀 %s — %s", pd.Timestamp(d).date(), e)
        if progress and i % 12 == 0:
            print(
                f"[l4-backtest] RS 유니버스 캐시 {i}/{len(dates)} 월 (만든 것 {made})",
                file=sys.stderr,
                flush=True,
            )
    return made


def default_jobs() -> int:
    """`--jobs` 기본 = min(14, cpu−2). 스토어 I/O 가 병목이라 코어를 다 쓰지 않는다."""
    return max(1, min(14, (os.cpu_count() or 2) - 2))


def collect_panels(
    theme_ids: Sequence[str],
    dates: Sequence[pd.Timestamp],
    *,
    db_path: Path,
    state_dir: Path,
    themes_path: Path | None = None,
    cache_dir: Path | None = None,
    jobs: int = 1,
    progress: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """테마 목록 × 월말 격자 → (전 테마 패널, 전 테마 계수). 테마 단위로 병렬."""
    panels: list[pd.DataFrame] = []
    counts: list[pd.DataFrame] = []
    total = len(theme_ids)
    done = 0

    def note(theme_id: str, panel: pd.DataFrame) -> None:
        nonlocal done
        done += 1
        if progress:
            print(
                f"[l4-backtest] {done}/{total} 테마 · {theme_id} "
                f"({len(panel):,} 종목-월) · 남은 {total - done}",
                file=sys.stderr,
                flush=True,
            )

    args = [(t, list(dates), str(cache_dir) if cache_dir else None) for t in theme_ids]
    if jobs <= 1:
        _worker_init(str(db_path), str(themes_path) if themes_path else None, str(state_dir))
        for a in args:
            tid, panel, cf = _worker_theme(a)
            panels.append(panel)
            counts.append(cf)
            note(tid, panel)
    else:
        with ProcessPoolExecutor(
            max_workers=jobs,
            initializer=_worker_init,
            initargs=(
                str(db_path),
                str(themes_path) if themes_path else None,
                str(state_dir),
            ),
        ) as pool:
            for tid, panel, cf in pool.map(_worker_theme, args):
                panels.append(panel)
                counts.append(cf)
                note(tid, panel)
    panel_all = (
        pd.concat(panels, ignore_index=True)
        if panels
        else pd.DataFrame(columns=[*PANEL_COLUMNS, "theme"])
    )
    counts_all = (
        pd.concat(counts, ignore_index=True)
        if counts
        else pd.DataFrame(columns=[*COUNT_COLUMNS, "theme"])
    )
    return panel_all, counts_all


# ---------------------------------------------------------------- 전진 수익률 (§3.4)


@dataclass(frozen=True)
class StockForward:
    """월말 종목 전진 수익률 (date × ticker). `raw[h]` 는 §3.4 의 동결 규칙을 적용한 총수익."""

    raw: dict[int, pd.DataFrame]
    raw_d1: dict[int, pd.DataFrame]
    death: dict[int, pd.DataFrame]
    valid: dict[int, pd.DataFrame]
    last_complete: pd.Timestamp
    exclusions: dict[str, Any]


def monthly_close(store: Store, tickers: Sequence[str]) -> pd.DataFrame:
    """월말 조정 종가 (date × ticker). 그 달 **마지막 거래일**의 `close` 다 (§3.1 표: 전진 수익률은
    조정 종가). 스토어에서 한 번만 집계한다."""
    sql = (
        "select p.ticker as ticker, last_day(p.date) as m, arg_max(p.close, p.date) as close "
        "from prices p join tk on p.ticker = tk.ticker "
        "where p.close is not null group by 1, 2"
    )
    tk = pd.DataFrame({"ticker": pd.Series(sorted(set(tickers)), dtype="object")})
    df = store.query(sql, frames={"tk": tk}, min_rows=1, what="monthly_close")
    df["m"] = pd.to_datetime(df["m"])
    out = df.pivot(index="m", columns="ticker", values="close").sort_index()
    out.index = pd.DatetimeIndex(out.index)
    return out


def death_months(store: Store, tickers: Sequence[str], index: pd.DatetimeIndex) -> pd.DataFrame:
    """사망(파산·규제폐지) 이 일어난 달 (date × ticker, bool) — §2.5 · §3.4 D1."""
    act = store.actions(kinds=list(DEATH_ACTIONS), min_rows=0)
    out = pd.DataFrame(False, index=index, columns=pd.Index(sorted(set(tickers)), name="ticker"))
    if act.empty:
        return out
    act = act[act["ticker"].isin(out.columns)].copy()
    act["m"] = pd.to_datetime(act["date"]) + pd.offsets.MonthEnd(0)
    act = act[act["m"].isin(out.index)]
    for m, tks in act.groupby("m")["ticker"]:
        out.loc[m, sorted(set(tks))] = True
    return out


def stock_forward(
    close: pd.DataFrame,
    deaths: pd.DataFrame,
    horizons: Sequence[int],
    *,
    last_complete: pd.Timestamp,
) -> StockForward:
    """§3.4 의 네 줄을 그대로.

    - `(t, t+h]` 에 가격이 계속 있으면 `close[t+h]/close[t] − 1`.
    - 가격이 끊기면 **마지막 종가에서 동결** (`ffill`) — `close[last]/close[t] − 1`.
    - `t` 에 가격이 없으면 그 종목은 그 월 랭킹에 없다 (분모가 NaN → 결과도 NaN).
    - `t+h` 가 스토어 최종 완결 월을 넘으면 **NaN 으로 두고 센다**.

    민감도 **D1** (§3.4): `(t, t+h]` 안에 파산·규제폐지가 있으면 수익률을 −100% 로 둔다.
    """
    filled = close.ffill()
    raw: dict[int, pd.DataFrame] = {}
    raw_d1: dict[int, pd.DataFrame] = {}
    death: dict[int, pd.DataFrame] = {}
    valid: dict[int, pd.DataFrame] = {}
    excl: dict[str, Any] = {"last_complete_month": str(pd.Timestamp(last_complete).date())}
    idx = pd.DatetimeIndex(close.index)
    dcum = deaths.reindex(index=idx, columns=close.columns).fillna(False).astype(int).cumsum()
    for h in horizons:
        end_ok = pd.Series(idx + pd.offsets.MonthEnd(h) <= last_complete, index=idx)
        end_mask = pd.DataFrame(
            np.repeat(end_ok.to_numpy()[:, None], close.shape[1], axis=1),
            index=idx,
            columns=close.columns,
        )
        exact = close.shift(-h)
        frozen = filled.shift(-h)
        r = (frozen / close - 1.0).where(end_mask)
        start_ok = close.notna()
        r = r.where(start_ok)
        din = (dcum.shift(-h) - dcum) > 0
        din = din.where(end_mask & start_ok)
        raw[h] = r
        death[h] = din
        valid[h] = r.notna()
        raw_d1[h] = r.mask(din.fillna(False).astype(bool) & r.notna(), -1.0)
        n_start = int(start_ok.to_numpy().sum())
        excl[f"h{h}"] = {
            "stock_months_with_price": n_start,
            "dropped_incomplete_endpoint": int((start_ok & ~end_mask).to_numpy().sum()),
            "frozen_last_price": int(
                (start_ok & end_mask & exact.isna() & frozen.notna()).to_numpy().sum()
            ),
            "no_forward_price_at_all": int((start_ok & end_mask & frozen.isna()).to_numpy().sum()),
            "kept": int(r.notna().to_numpy().sum()),
            "d1_set_to_minus_100": int(
                (din.fillna(False).astype(bool) & r.notna()).to_numpy().sum()
            ),
        }
    return StockForward(
        raw=raw,
        raw_d1=raw_d1,
        death=death,
        valid=valid,
        last_complete=pd.Timestamp(last_complete),
        exclusions=excl,
    )


# ---------------------------------------------------------------- 테마-월 집계


@dataclass(frozen=True)
class ThemeMonthFrames:
    ic: pd.DataFrame  # date, theme, variant, horizon, ic, n, n_eligible
    indicator_ic: pd.DataFrame  # date, theme, indicator, horizon, ic, n
    spread: pd.DataFrame  # date, theme, variant, horizon, spread, ret_top, ret_bot, n
    filters: pd.DataFrame  # date, theme, reason, horizon, gauge, basis, diff, n_excl, n_pass


def _matrices(
    panel: pd.DataFrame, dates: pd.DatetimeIndex, columns: Sequence[str]
) -> dict[str, np.ndarray]:
    """긴 표 → 열별 (date × ticker) 밀집 배열. 티커 순서는 `panel` 의 등장 순서.

    (date, ticker) 는 유일하다 — 한 테마-월에 같은 종목이 두 번 오지 않는다. 그래서 `unstack`
    한 번으로 전 열을 한꺼번에 편다 (열마다 `pivot_table` 을 부르는 것과 같은 값이다).
    """
    tickers = list(dict.fromkeys(panel["ticker"]))
    wide = panel.set_index(["date", "ticker"])[list(columns)].unstack("ticker")
    out: dict[str, np.ndarray] = {}
    for c in columns:
        sub = cast(pd.DataFrame, wide[c])
        out[c] = sub.reindex(index=dates, columns=tickers).to_numpy(dtype=float)
    out["__tickers__"] = np.array(tickers, dtype=object)
    return out


def _group_mean(A: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """행별로 `mask` 이면서 값이 있는 항목의 (평균, 개수). 개수 0 이면 평균 NaN."""
    use = mask & ~np.isnan(A)
    n = use.sum(axis=1)
    tot = np.where(use, A, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, tot / np.maximum(n, 1), np.nan)
    return mean, n


def theme_month_metrics(
    panel: pd.DataFrame,
    fwd: StockForward,
    *,
    horizons: Sequence[int] = HORIZONS,
    min_n: int = MIN_STOCKS_XS,
    k: int = SPREAD_K,
) -> ThemeMonthFrames:
    """테마 하나의 패널 → 테마-월 단위 IC · 지표 IC · 스프레드 · 필터 차 (긴 표 4개).

    `n < min_n` 인 테마-월은 값을 NaN 으로 두되 **행은 만든다** — 빠진 달을 세기 위해서다
    (L1 `rank_ic_series` 와 같은 규약).
    """
    empty = pd.DataFrame()
    if panel.empty:
        return ThemeMonthFrames(empty, empty, empty, empty)
    theme = str(panel["theme"].iloc[0])
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
    num_cols = ["eligible", *axes.HARD_REASON_CODES, *VARIANT_COLUMN.values(), *INDICATORS]
    M = _matrices(panel, dates, num_cols)
    tickers = list(M.pop("__tickers__"))
    elig = np.nan_to_num(M["eligible"], nan=0.0) > 0.5
    excl_flags = {c: np.nan_to_num(M[c], nan=0.0) > 0.5 for c in axes.HARD_REASON_CODES}
    listed = ~np.isnan(M["eligible"])  # 패널에 행이 있다 = 그 달 상장 판정을 통과했다

    ic_rows: list[pd.DataFrame] = []
    iic_rows: list[pd.DataFrame] = []
    sp_rows: list[dict[str, Any]] = []
    fl_rows: list[pd.DataFrame] = []
    n_elig = elig.sum(axis=1)

    for h in horizons:
        Yb = fwd.raw[h].reindex(index=dates, columns=tickers).to_numpy(dtype=float)
        Yd = fwd.raw_d1[h].reindex(index=dates, columns=tickers).to_numpy(dtype=float)
        D = fwd.death[h].reindex(index=dates, columns=tickers).to_numpy(dtype=float)
        Ye = np.where(elig, Yb, np.nan)
        # 테마-월 EW 기준 — 그 달 상장 구성원 중 전진 수익률이 있는 것 **전부** (§2.5)
        base = np.where(listed, Yb, np.nan)
        n_base = np.sum(~np.isnan(base), axis=1)
        ew = np.where(n_base > 0, np.nansum(base, axis=1) / np.maximum(n_base, 1), np.nan)
        for v in VARIANTS:
            X = np.where(elig, M[VARIANT_COLUMN[v]], np.nan)
            ic, n = _spearman_rows(X, Ye)
            ic_rows.append(
                pd.DataFrame(
                    {
                        "date": dates,
                        "theme": theme,
                        "variant": v,
                        "horizon": h,
                        "ic": np.where(n >= min_n, ic, np.nan),
                        "n": n.astype(int),
                        "n_eligible": n_elig.astype(int),
                    }
                )
            )
        for ind in INDICATORS:
            X = np.where(elig, M[ind], np.nan)
            ic, n = _spearman_rows(X, Ye)
            iic_rows.append(
                pd.DataFrame(
                    {
                        "date": dates,
                        "theme": theme,
                        "indicator": ind,
                        "horizon": h,
                        "ic": np.where(n >= min_n, ic, np.nan),
                        "n": n.astype(int),
                    }
                )
            )
        # 스프레드 — 테마 EW 초과의 상위 k − 하위 k (§2.4)
        Xex = Ye - ew[:, None]
        for v in VARIANTS:
            S = np.where(elig, M[VARIANT_COLUMN[v]], np.nan)
            for i in range(len(dates)):
                pair = ~(np.isnan(S[i]) | np.isnan(Xex[i]))
                n_pair = int(pair.sum())
                top = bot = spread = float("nan")
                if n_pair >= min_n:
                    order = np.argsort(-S[i][pair], kind="stable")
                    yy = Xex[i][pair][order]
                    top = float(yy[:k].mean())
                    bot = float(yy[-k:].mean())
                    spread = top - bot
                sp_rows.append(
                    {
                        "date": dates[i],
                        "theme": theme,
                        "variant": v,
                        "horizon": h,
                        "spread": spread,
                        "ret_top": top,
                        "ret_bot": bot,
                        "n": n_pair,
                    }
                )
        # Q3 — 사유별 제외군 − 통과군 (§2.5). 초과수익 차 · 사망률 차 · 기본/D1
        n_pass_all = elig.sum(axis=1)
        gauge_specs: list[tuple[str, str, np.ndarray]] = [
            ("excess", "base", np.where(listed, Yb, np.nan) - ew[:, None]),
            ("excess", "d1", np.where(listed, Yd, np.nan) - ew[:, None]),
            # 사망률은 수익률 규약과 무관하다 — 기본 기준으로 한 번만 잰다
            ("death", "base", np.where(listed, D, np.nan)),
        ]
        for gauge, basis, A in gauge_specs:
            m_pass, n_pass = _group_mean(A, elig)
            for code in axes.HARD_REASON_CODES:
                m_ex, n_ex = _group_mean(A, excl_flags[code] & listed)
                ok = (n_pass_all >= min_n) & (n_ex >= 1) & (n_pass >= 1)
                fl_rows.append(
                    pd.DataFrame(
                        {
                            "date": dates,
                            "theme": theme,
                            "reason": code,
                            "horizon": h,
                            "gauge": gauge,
                            "basis": basis,
                            "diff": np.where(ok, m_ex - m_pass, np.nan),
                            "n_excluded": n_ex.astype(int),
                            "n_passing": n_pass.astype(int),
                        }
                    )
                )
    return ThemeMonthFrames(
        ic=pd.concat(ic_rows, ignore_index=True) if ic_rows else empty,
        indicator_ic=pd.concat(iic_rows, ignore_index=True) if iic_rows else empty,
        spread=pd.DataFrame(sp_rows),
        filters=pd.concat(fl_rows, ignore_index=True) if fl_rows else empty,
    )


# ---------------------------------------------------------------- 월별 시계열 (테마 동일가중)


def theme_equal_weight(
    df: pd.DataFrame, keys: Sequence[str], value: str, *, partition: pd.Series | None = None
) -> pd.DataFrame:
    """테마-월 단위 표 → **테마 동일가중** 월별 시계열 (§2.2). 종목 수 가중이 아니다.

    `partition` 이 있으면 (theme → 파티션 이름) 으로 나눠 파티션별 시계열도 만든다.
    반환 열: date, `keys`…, partition, `value`, n_themes, n_mean.
    """
    if df.empty:
        return pd.DataFrame()
    d = df.dropna(subset=[value]).copy()
    n_col = "n" if "n" in d.columns else None
    parts: list[pd.DataFrame] = []

    def agg(x: pd.DataFrame, name: str) -> pd.DataFrame:
        g = x.groupby(["date", *keys], sort=False)
        out = g[value].mean().rename(value).reset_index()
        out["n_themes"] = g[value].size().to_numpy()
        out["n_mean"] = g[n_col].mean().to_numpy() if n_col else np.nan
        out["partition"] = name
        return out

    parts.append(agg(d, PARTITION_ALL))
    if partition is not None:
        cls = d["theme"].map(partition)
        for c in CYCLE_CLASSES:
            sub = d[cls == c]
            if not sub.empty:
                parts.append(agg(sub, c))
    return pd.concat(parts, ignore_index=True)


def _ic_extra(g: pd.DataFrame, rec: dict[str, Any]) -> None:
    rec["mean_n_themes"] = float(g["n_themes"].mean()) if len(g) else float("nan")
    rec["mean_n_stocks"] = float(g["n_mean"].mean()) if len(g) else float("nan")


# ---------------------------------------------------------------- 유효 표본 (§2.3)


def effective_sample(
    ic_theme_month: pd.DataFrame,
    close: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    horizon: int = GATE_HORIZON,
    variant: str = "rank_score",
    min_months: int = 60,
) -> dict[str, Any]:
    """§2.3 — 테마 간 IC 상관 · 테마 내 종목 수익률 평균 상관과 유효 종목 수. 리포트 첫 표.

    (AR1 → N_eff 는 `ic_summary` 의 열이다 — 여기서 다시 만들지 않는다.)
    """
    out: dict[str, Any] = {"min_months": min_months, "horizon": horizon, "variant": variant}
    sub = ic_theme_month[
        (ic_theme_month["horizon"] == horizon) & (ic_theme_month["variant"] == variant)
    ]
    for w, start in (("primary", PRIMARY_START), ("full", None)):
        s = sub if start is None else sub[sub["date"] >= start]
        mat = s.pivot_table(index="date", columns="theme", values="ic", aggfunc="first")
        n, rho, neff = mean_pairwise_corr(mat, min_months=min_months)
        out[f"theme_ic_corr_{w}"] = {"n_themes": n, "avg_corr": rho, "n_eff_themes": neff}

    rets = close.pct_change(fill_method=None)
    rows: list[dict[str, Any]] = []
    if not panel.empty:
        by_theme = panel.groupby("theme")["ticker"].agg(lambda s: sorted(set(s)))
        for theme, tks in by_theme.items():
            cols = [t for t in tks if t in rets.columns]
            if len(cols) < 2:
                continue
            x = rets.loc[PRIMARY_START:, cols]
            n, rho, neff = mean_pairwise_corr(x, min_months=min_months)
            if n >= 2 and not math.isnan(rho):
                rows.append({"theme": theme, "n_stocks": n, "avg_corr": rho, "n_eff_stocks": neff})
    wt = pd.DataFrame(rows)
    out["within_theme_stock_corr_primary"] = {
        "n_themes_measured": len(wt),
        "median_avg_corr": float(wt["avg_corr"].median()) if len(wt) else float("nan"),
        "mean_avg_corr": float(wt["avg_corr"].mean()) if len(wt) else float("nan"),
        "median_n_stocks": float(wt["n_stocks"].median()) if len(wt) else float("nan"),
        "median_n_eff_stocks": float(wt["n_eff_stocks"].median()) if len(wt) else float("nan"),
    }
    out["within_theme_stock_corr_by_theme"] = wt.to_dict(orient="records")
    return out


# ---------------------------------------------------------------- 과최적화 정산 (§6)


def overfitting_summary(
    ic_monthly: pd.DataFrame,
    spread_monthly: pd.DataFrame,
    trials: dict[str, int],
    *,
    pbo_max_splits: int = PBO_MAX_SPLITS,
) -> dict[str, Any]:
    """DSR(선언 1 · 전 시도) · PBO(CSCV, 열 = 4 변형 1M 스프레드). 합격 기준이 아니다 (§4.1)."""
    out: dict[str, Any] = {
        "trials": trials,
        "dsr_threshold": DSR_THRESHOLD,
        "pbo_threshold": PBO_THRESHOLD,
        "dsr": [],
        "pbo": [],
        "note": (
            "DSR·PBO 는 합격 기준에 들어가지 않는다 (docs/14 §4.1). 합격은 '0 과 구분된다' 이지 "
            "'N 번 본 중 우연이 아니다' 가 아니다. PBO 는 열이 4개뿐이라 L1(7개)보다 CSCV 의 "
            "분해능이 낮고, 우리는 4 변형 중에서 고르지 않았다 — rank_score 는 선언됐다 (§6.3)."
        ),
    }
    n_all = trials["total"]
    ic_all = ic_monthly[ic_monthly["partition"] == PARTITION_ALL]
    for w in WINDOWS:
        icw = ic_all if w == "full" else ic_all[ic_all["date"] >= PRIMARY_START]
        spw = (
            spread_monthly
            if w == "full"
            else spread_monthly[spread_monthly["date"] >= PRIMARY_START]
        )
        for v in VARIANTS:
            for series, frame, hs in (
                ("ic", icw, tuple(HORIZONS)),
                ("spread", spw, (PBO_HORIZON, *HORIZONS)),
            ):
                for h in hs:
                    col = "ic" if series == "ic" else "spread"
                    s = (
                        frame[(frame["variant"] == v) & (frame["horizon"] == h)]
                        .set_index("date")[col]
                        .sort_index()
                    )
                    rec: dict[str, Any] = {
                        "window": w,
                        "variant": v,
                        "horizon": h,
                        "series": series,
                    }
                    if v == "rank_score":
                        rec["dsr_n1"] = dsr_of_series(s, 1, horizon=h)
                    rec["dsr_n_total"] = dsr_of_series(s, n_all, horizon=h)
                    out["dsr"].append(rec)
        for h in (PBO_HORIZON, *HORIZONS):
            out["pbo"].append(
                pbo_of_spreads(
                    spread_monthly,
                    window=w,
                    horizon=h,
                    max_splits=pbo_max_splits,
                    variants=VARIANTS,
                )
            )
    return out


# ---------------------------------------------------------------- 판정 (§4.1)


def _cell(summ: pd.DataFrame, **where: Any) -> pd.Series | None:
    """요약 표에서 정확히 한 칸. 열이 없거나 행이 없으면 None (그 칸을 재지 않았다는 뜻)."""
    if summ.empty or any(k not in summ.columns for k in where):
        return None
    m = pd.Series(True, index=summ.index)
    for k, v in where.items():
        m &= summ[k] == v
    sub = summ[m]
    return None if sub.empty else sub.iloc[0]


def _works(lo: float, hi: float) -> str:
    if lo > 0:
        return "works"
    if hi < 0:
        return "negative"
    return "indistinguishable_from_0"


def verdict(
    ic_summary: pd.DataFrame, filters_summary: pd.DataFrame, overfit: dict[str, Any]
) -> dict[str, Any]:
    """`docs/14` §4.1 의 표를 그대로 코드로. Q1 만 관문이고 Q2·Q4 는 진단, Q3 는 자기 기준."""
    out: dict[str, Any] = {
        "rule_q1": (
            "주 창(2011-01–) · 12M · rank_score 의 테마 내 rank-IC 평균 "
            "95% 12개월 블록 부트스트랩 CI 하한 > 0"
        ),
        "rule_q3": (
            "E1·E2·E3 각각 제외군 − 통과군 12M 초과수익 차의 95% CI 상한 < 0 → '손실을 막았다'. "
            "0 을 포함하면 '알파가 아니라 표본 절단'. E4·E5 는 판정하지 않는다"
        ),
        "dsr_pbo_in_gate": False,
    }
    r = _cell(
        ic_summary,
        window="primary",
        horizon=GATE_HORIZON,
        variant="rank_score",
        partition=PARTITION_ALL,
    )
    if r is None:
        out["q1"] = {"gate": "undetermined", "reason": "관문 셀이 비어 있다"}
    else:
        out["q1"] = {
            "gate": "pass" if bool(r["ci_lo"] > 0) else "fail",
            "mean_ic": float(r["mean"]),
            "ci": [float(r["ci_lo"]), float(r["ci_hi"])],
            "n_months": int(r["n_months"]),
            "n_months_dropped": int(r["n_months_dropped"]),
            "n_eff": float(r["n_eff"]),
            "mean_n_themes": float(r.get("mean_n_themes", float("nan"))),
            "mean_n_stocks": float(r.get("mean_n_stocks", float("nan"))),
            "ci_excludes_zero_negative": bool(r["ci_hi"] < 0),
        }
    axes_out: dict[str, Any] = {}
    for v in VARIANTS[1:]:
        rv = _cell(
            ic_summary,
            window="primary",
            horizon=GATE_HORIZON,
            variant=v,
            partition=PARTITION_ALL,
        )
        if rv is not None:
            axes_out[v] = {
                "mean_ic": float(rv["mean"]),
                "ci": [float(rv["ci_lo"]), float(rv["ci_hi"])],
                "works": _works(float(rv["ci_lo"]), float(rv["ci_hi"])),
            }
    out["q2_axes_12m_primary"] = axes_out
    out["q2_note"] = "진단이지 관문이 아니다. 결과가 어떻게 나오든 가중치는 움직이지 않는다 (§4.2)"

    q3: dict[str, Any] = {}
    for code in axes.HARD_REASON_CODES:
        rec: dict[str, Any] = {"label": axes.HARD_REASON_LABELS[code]}
        ex = _cell(
            filters_summary,
            window="primary",
            horizon=GATE_HORIZON,
            reason=code,
            gauge="excess",
            basis="base",
        )
        if ex is not None:
            lo, hi = float(ex["ci_lo"]), float(ex["ci_hi"])
            rec["excess_diff"] = {"mean": float(ex["mean"]), "ci": [lo, hi]}
            rec["verdict"] = (
                "not_judged (데이터 절단 — docs/14 §4.1)"
                if code not in axes.HARD_REASON_ALPHA
                else ("blocked_losses" if hi < 0 else "sample_truncation_not_alpha")
            )
        d1 = _cell(
            filters_summary,
            window="primary",
            horizon=GATE_HORIZON,
            reason=code,
            gauge="excess",
            basis="d1",
        )
        if d1 is not None:
            rec["excess_diff_d1"] = {
                "mean": float(d1["mean"]),
                "ci": [float(d1["ci_lo"]), float(d1["ci_hi"])],
            }
        dt = _cell(
            filters_summary,
            window="primary",
            horizon=GATE_HORIZON,
            reason=code,
            gauge="death",
            basis="base",
        )
        if dt is not None:
            lo, hi = float(dt["ci_lo"]), float(dt["ci_hi"])
            rec["death_diff"] = {"mean": float(dt["mean"]), "ci": [lo, hi]}
            rec["mechanism_confirmed"] = bool(lo > 0)
        q3[code] = rec
    out["q3_filters_12m_primary"] = q3

    dsr_rows = [
        d
        for d in overfit["dsr"]
        if d["window"] == "primary"
        and d["variant"] == "rank_score"
        and d["horizon"] == GATE_HORIZON
        and d["series"] == "ic"
    ]
    pbo_rows = [
        p for p in overfit["pbo"] if p["window"] == "primary" and p["horizon"] == GATE_HORIZON
    ]
    out["reported_not_gated"] = {
        "dsr_declared_n1_nonoverlapping": dsr_rows[0]["dsr_n1"]["dsr_nonoverlapping"]
        if dsr_rows
        else float("nan"),
        "dsr_all_trials_nonoverlapping": dsr_rows[0]["dsr_n_total"]["dsr_nonoverlapping"]
        if dsr_rows
        else float("nan"),
        "n_trials": overfit["trials"]["total"],
        "pbo_primary_12m": pbo_rows[0].get("pbo", float("nan")) if pbo_rows else float("nan"),
    }
    return out


# ---------------------------------------------------------------- 오케스트레이션


@dataclass(frozen=True)
class L4BacktestResult:
    ic_theme_month: pd.DataFrame
    ic_monthly: pd.DataFrame
    ic_summary: pd.DataFrame
    indicator_ic_monthly: pd.DataFrame
    indicator_ic_summary: pd.DataFrame
    spread_monthly: pd.DataFrame
    spread_summary: pd.DataFrame
    filters_monthly: pd.DataFrame
    filters_summary: pd.DataFrame
    effective_sample: dict[str, Any]
    overfitting: dict[str, Any]
    verdict: dict[str, Any]
    exclusions: dict[str, Any]
    meta: dict[str, Any]
    counts: pd.DataFrame = field(default_factory=pd.DataFrame)
    out_dir: Path | None = None


def run_backtest_frames(
    panel: pd.DataFrame,
    counts: pd.DataFrame,
    fwd: StockForward,
    close: pd.DataFrame,
    classes: pd.Series,
    *,
    horizons: Sequence[int] = HORIZONS,
    pbo_max_splits: int = PBO_MAX_SPLITS,
) -> L4BacktestResult:
    """이미 만들어진 패널·전진 수익률로 검정 전체를 돈다 (스토어 불필요 — 테스트와 공용)."""
    hs = (PBO_HORIZON, *horizons)
    ic_parts: list[pd.DataFrame] = []
    iic_parts: list[pd.DataFrame] = []
    sp_parts: list[pd.DataFrame] = []
    fl_parts: list[pd.DataFrame] = []
    themes = sorted(panel["theme"].unique()) if not panel.empty else []
    for i, t in enumerate(themes, 1):
        sub = panel[panel["theme"] == t]
        # 1M 은 **스프레드에만** 쓴다 (PBO 입력, §6.3). IC·지표·필터는 3·6·12M 뿐이다 —
        # 시도 수(§6.2)가 세는 칸이 그것이고, 세지 않은 칸을 들여다보지 않는다.
        f = theme_month_metrics(sub, fwd, horizons=hs)
        keep = set(horizons)
        for lst, frame in (
            (ic_parts, f.ic[f.ic["horizon"].isin(keep)] if not f.ic.empty else f.ic),
            (
                iic_parts,
                f.indicator_ic[f.indicator_ic["horizon"].isin(keep)]
                if not f.indicator_ic.empty
                else f.indicator_ic,
            ),
            (sp_parts, f.spread),
            (
                fl_parts,
                f.filters[f.filters["horizon"].isin(keep)] if not f.filters.empty else f.filters,
            ),
        ):
            if not frame.empty:
                lst.append(frame)
        log.info("l4-backtest: 집계 %d/%d 테마 (%s)", i, len(themes), t)

    def cat(parts: list[pd.DataFrame]) -> pd.DataFrame:
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    ic_tm, iic_tm, sp_tm, fl_tm = cat(ic_parts), cat(iic_parts), cat(sp_parts), cat(fl_parts)

    ic_monthly = theme_equal_weight(ic_tm, ("variant", "horizon"), "ic", partition=classes)
    iic_monthly = theme_equal_weight(iic_tm, ("indicator", "horizon"), "ic")
    sp_monthly = theme_equal_weight(sp_tm, ("variant", "horizon"), "spread")
    fl_monthly = theme_equal_weight(fl_tm, ("reason", "horizon", "gauge", "basis"), "diff")

    ic_sum = _summarize(ic_monthly, ("variant", "horizon", "partition"), "ic", _ic_extra)
    iic_sum = _summarize(iic_monthly, ("indicator", "horizon"), "ic", _ic_extra)
    sp_sum = _summarize(sp_monthly, ("variant", "horizon"), "spread", _ic_extra)
    fl_sum = _summarize(fl_monthly, ("reason", "horizon", "gauge", "basis"), "diff", _ic_extra)
    trials = count_trials()
    overfit = overfitting_summary(ic_monthly, sp_monthly, trials, pbo_max_splits=pbo_max_splits)
    ver = verdict(ic_sum, fl_sum, overfit)
    eff = effective_sample(ic_tm, close, panel)
    excl = exclusions_summary(counts, ic_tm, fwd, panel)
    meta: dict[str, Any] = {
        "preregistration": "docs/14-l4-backtest-preregistration.md",
        "horizons": list(horizons),
        "gate_horizon": GATE_HORIZON,
        "pbo_horizon": PBO_HORIZON,
        "primary_start": str(PRIMARY_START.date()),
        "min_stocks_xs": MIN_STOCKS_XS,
        "spread_k": SPREAD_K,
        "variants": list(VARIANTS),
        "indicators": list(INDICATORS),
        "bootstrap": {"block": BOOT_BLOCK, "n": BOOT_N, "seed": BOOT_SEED},
        "pbo": {"blocks": PBO_BLOCKS, "max_splits": pbo_max_splits},
        "declared_constants": axes.declared_constants(),
        "n_themes_measured": len(themes),
        "spread_horizons": list(hs),
        "limitations": list(LIMITATIONS),
    }
    return L4BacktestResult(
        ic_theme_month=ic_tm[ic_tm["horizon"] == GATE_HORIZON].reset_index(drop=True),
        ic_monthly=ic_monthly,
        ic_summary=ic_sum,
        indicator_ic_monthly=iic_monthly,
        indicator_ic_summary=iic_sum,
        spread_monthly=sp_monthly,
        spread_summary=sp_sum,
        filters_monthly=fl_monthly,
        filters_summary=fl_sum,
        effective_sample=eff,
        overfitting=overfit,
        verdict=ver,
        exclusions=excl,
        meta=meta,
        counts=counts,
    )


def _hist(s: pd.Series) -> dict[int, int]:
    """값(입력 개수)별 종목-월 수 — JSON 에 그대로 실린다."""
    return {int(str(k)): int(v) for k, v in s.value_counts().sort_index().items()}


def indicator_missing(panel: pd.DataFrame) -> dict[str, Any]:
    """§6.4 마지막 항목 — 적격 종목-월에서 지표별 결측률과 T·M 축의 실제 입력 수.

    `price_beta_hist` 는 테마 `physical_ref` 와 그 소스 데이터가 있어야 계산된다. 없으면 T 축이
    6개가 아니라 5개로 돌고, `T_MIN_INPUTS = 3` 이라 그대로 통과한다 — **통과했다는 사실이
    입력이 다 있었다는 뜻이 아니다.** 몇 테마가 몇 개로 돌았는지를 세어 적는다 (`CLAUDE.md` §2).
    """
    if panel.empty:
        return {}
    elig = panel[panel["eligible"].astype(bool)]
    if elig.empty:
        return {}
    n = len(elig)
    rates = {c: float(elig[c].isna().mean()) for c in INDICATORS}
    t_cols = [f"tp_{c}" for c in axes.T_COMPONENTS]
    m_cols = list(axes.M_COMPONENTS)
    t_n = elig[t_cols].notna().sum(axis=1)
    m_n = elig[m_cols].notna().sum(axis=1)
    by_theme = (
        elig.assign(_t=t_n, _m=m_n)
        .groupby("theme")
        .agg(
            stock_months=("_t", "size"),
            mean_t_inputs=("_t", "mean"),
            mean_m_inputs=("_m", "mean"),
            beta_missing_share=(f"tp_{axes.T_COMPONENTS[3]}", lambda s: float(s.isna().mean())),
        )
        .reset_index()
    )
    return {
        "eligible_stock_months": int(n),
        "missing_rate_by_indicator": rates,
        "t_inputs_hist": _hist(t_n),
        "m_inputs_hist": _hist(m_n),
        "themes_with_price_beta_hist_fully_missing": int(
            (by_theme["beta_missing_share"] >= 1.0).sum()
        ),
        "themes_measured": len(by_theme),
        "by_theme": by_theme.to_dict(orient="records"),
    }


def pit_vintage_check(store: Store) -> dict[str, Any]:
    """재무 **재보고 빈티지**가 스토어에 있는가 — `pit.py` 의 "최초 보고분만" 이 실효인지 실측.

    `(ticker, calendardate)` 당 `datekey` 가 전부 1개면 정정 이력이 없다는 뜻이고, 그렇다면
    **정정 최종치가 원 공시일에 붙어 소급 사용된다.** 고칠 수 없는 데이터 한계이므로 세어서 적는다.
    """
    sql = (
        "select count(*) as groups, sum(case when n > 1 then 1 else 0 end) as with_revision "
        "from (select ticker, calendardate, count(distinct datekey) as n from fundamentals "
        "where dimension = 'ARQ' and calendardate is not null group by 1, 2)"
    )
    df = store.query(sql, min_rows=1, what="pit_vintage_check")
    groups = int(df["groups"].iloc[0])
    rev = int(df["with_revision"].iloc[0] or 0)
    return {
        "ticker_calendardate_groups": groups,
        "groups_with_multiple_datekeys": rev,
        "has_restatement_vintage": rev > 0,
        "limitation": (
            "재보고 빈티지가 없으면 `pit_quarterly` 의 '최초 보고분만' 규칙은 무연산이고, "
            "정정 최종치가 원 공시일(datekey)에 붙어 소급 사용된다. 고칠 수 없는 데이터 한계다"
        )
        if rev == 0
        else "재보고 빈티지가 있다 — 최초 보고분만 쓰는 규칙이 실제로 작동한다",
    }


def exclusions_summary(
    counts: pd.DataFrame, ic_tm: pd.DataFrame, fwd: StockForward, panel: pd.DataFrame | None = None
) -> dict[str, Any]:
    """§6.4 — 제외를 전부 센다. **하나라도 조용히 빠지면 조용한 절단이다** (`CLAUDE.md` §2)."""
    out: dict[str, Any] = {"forward": fwd.exclusions}
    if panel is not None:
        out["indicator_missing"] = indicator_missing(panel)
    if not counts.empty:
        c = counts.copy()
        c["date"] = pd.to_datetime(c["date"])
        c["year"] = c["date"].dt.year
        num = [x for x in COUNT_COLUMNS if x.startswith("n_")]
        out["stock_months"] = {k: int(c[k].fillna(0).sum()) for k in num}
        out["theme_months_with_error"] = int((c["error"].fillna("") != "").sum())
        errs = c.loc[c["error"].fillna("") != "", "error"]
        out["errors_by_kind"] = {
            str(k): int(v) for k, v in errs.str.split(":").str[0].value_counts().items()
        }
        out["by_year"] = (
            c.groupby("year")[["n_members", "n_listed", "n_eligible"]]
            .sum()
            .astype(int)
            .reset_index()
            .to_dict(orient="records")
        )
    if not ic_tm.empty:
        g = ic_tm[(ic_tm["variant"] == "rank_score") & (ic_tm["horizon"] == GATE_HORIZON)].copy()
        g["date"] = pd.to_datetime(g["date"])
        g["below_min"] = g["ic"].isna()
        out["theme_months"] = {
            "total": len(g),
            "with_ic": int((~g["below_min"]).sum()),
            "dropped_n_lt_min": int(g["below_min"].sum()),
            "min_stocks_xs": MIN_STOCKS_XS,
        }
        out["theme_months_dropped_by_theme"] = (
            g.groupby("theme")["below_min"]
            .agg(["size", "sum"])
            .astype(int)
            .reset_index()
            .rename(columns={"size": "theme_months", "sum": "dropped"})
            .to_dict(orient="records")
        )
        out["theme_months_dropped_by_year"] = (
            g.assign(year=g["date"].dt.year)
            .groupby("year")["below_min"]
            .agg(["size", "sum"])
            .astype(int)
            .reset_index()
            .rename(columns={"size": "theme_months", "sum": "dropped"})
            .to_dict(orient="records")
        )
    return out


# ---------------------------------------------------------------- 리포트


def _pct(x: Any, w: int = 6, p: int = 1) -> str:
    return _fmt(float(x) * 100.0 if x is not None and pd.notna(x) else float("nan"), w, p)


def render_report(res: L4BacktestResult) -> str:
    m = res.meta
    v = res.verdict
    L: list[str] = []
    L.append("L4 종목 선정 백테스트 — docs/14 사전 등록의 집행.")
    L.append("재는 것은 스코어의 예측력이지 전략의 수익률이 아니다 (CLAUDE.md §7).")
    L.append(
        f"스토어 최종일 {m.get('store_end', '?')} · 테마 {m['n_themes_measured']}"
        f" · 격자 {m.get('grid_first', '?')}~{m.get('grid_last', '?')}"
        f" ({m.get('n_months', '?')}개월)"
        f" · 주 창 {m['primary_start']}– · 관문 {m['gate_horizon']}M · n≥{m['min_stocks_xs']}"
    )
    if m.get("smoke"):
        L.append(
            "!! 스모크 실행이다 — 테마·격자를 줄였다. 판정이 아니다 (docs/14 §4 의 관문이 아님)."
        )
    L.append("")
    L.append("=" * 100)
    q1 = v.get("q1", {})
    L.append(f"Q1 판정: {str(q1.get('gate', '?')).upper()} — {v['rule_q1']}")
    if "mean_ic" in q1:
        L.append(
            f"  rank_score IC 평균 {q1['mean_ic']:+.4f}  95% CI"
            f" [{q1['ci'][0]:+.4f}, {q1['ci'][1]:+.4f}]"
            f"  N={q1['n_months']}  N_eff={q1['n_eff']:.1f}"
            f"  빠진달 {q1['n_months_dropped']}  평균 테마 {q1['mean_n_themes']:.1f}"
            f"  평균 종목 {q1['mean_n_stocks']:.1f}"
        )
    rn = v.get("reported_not_gated", {})
    L.append(
        f"  (합격 기준 밖) DSR(N=1 선언, 비중첩) {_fmt(rn.get('dsr_declared_n1_nonoverlapping'))}"
        f" · DSR(N={rn.get('n_trials')} 전 시도) {_fmt(rn.get('dsr_all_trials_nonoverlapping'))}"
        f" · PBO {_fmt(rn.get('pbo_primary_12m'))}"
    )
    L.append("  합격은 '0 과 구분된다' 이지 'N 번 본 중 우연이 아니다' 가 아니다 (docs/14 §4.1).")
    L.append("=" * 100)
    L.append("")
    L += _effective_table(res)
    L.append("")
    L += _ic_table(res)
    L.append("")
    L += _class_table(res)
    L.append("")
    L += _spread_table(res)
    L.append("")
    L += _filter_table(res)
    L.append("")
    L += _indicator_table(res)
    L.append("")
    L += _overfit_lines(res)
    L.append("")
    L += _exclusion_lines(res)
    L.append("")
    L += _limitation_lines(res)
    L.append("")
    L.append("이 수치로 축 가중치·하드 임계를 옮기지 않는다 (CLAUDE.md §1, docs/14 §4.2·§4.3).")
    return "\n".join(L)


def _limitation_lines(res: L4BacktestResult) -> list[str]:
    """[9] 한계 — 결과를 읽는 사람이 반드시 함께 읽어야 하는 것 (docs/14 §5)."""
    out = ["[9] 이 검정이 못 재는 것 (docs/14 §5) — 결과를 운용 성과로 옮겨 적지 않는다"]
    v = res.meta.get("pit_vintage")
    if v:
        out.append(
            "  재무 재보고 빈티지: (ticker, calendardate) "
            f"{v['ticker_calendardate_groups']:,} 조 중 datekey 가 2개 이상인 것 "
            f"{v['groups_with_multiple_datekeys']:,} → {v['limitation']}"
        )
    im = res.exclusions.get("indicator_missing") or {}
    if im:
        hist = im.get("t_inputs_hist", {})
        out.append(
            f"  T 축 입력 수 분포 (적격 종목-월 {im['eligible_stock_months']:,}): "
            + " · ".join(f"{k}개 {n:,}" for k, n in sorted(hist.items()))
        )
        out.append(
            "  price_beta_hist 가 전 구간 결측인 테마 "
            f"{im['themes_with_price_beta_hist_fully_missing']}/{im['themes_measured']}"
            " · 지표별 결측률은 exclusions.json"
        )
    for line in res.meta.get("limitations", []):
        out.append(f"  - {line}")
    return out


def _effective_table(res: L4BacktestResult) -> list[str]:
    e = res.effective_sample
    out = ["[1] 유효 표본 (docs/14 §2.3) — 명목 n 이 유효 n 이 아니다"]
    for w in WINDOWS:
        d = e.get(f"theme_ic_corr_{w}", {})
        out.append(
            f"  {w:<8} 테마 간 월별 IC 평균 상관 {_fmt(d.get('avg_corr'), 7, 3)}"
            f" (테마 {d.get('n_themes', '?')} → 유효 {_fmt(d.get('n_eff_themes'), 6, 1)})"
        )
    s = e.get("within_theme_stock_corr_primary", {})
    out.append(
        f"  primary  테마 내 종목 월수익률 평균 상관 중앙값 {_fmt(s.get('median_avg_corr'), 7, 3)}"
        f" (테마 {s.get('n_themes_measured')}개"
        f" · 종목 중앙값 {_fmt(s.get('median_n_stocks'), 6, 1)}"
        f" → 유효 종목 중앙값 {_fmt(s.get('median_n_eff_stocks'), 6, 1)})"
    )
    out.append("  월별 IC 의 AR1·N_eff 는 [2] 표. CI 는 12개월 이동블록 부트스트랩 2000회·시드 0.")
    return out


def _ic_table(res: L4BacktestResult) -> list[str]:
    hdr = (
        f"{'window':<8}{'h':>3} {'variant':<11}{'N':>5}{'N_eff':>7}{'mean':>8}{'ci_lo':>8}"
        f"{'ci_hi':>8}{'t_eff':>7}{'AR1':>6}{'pos%':>6}{'drop':>5}{'테마':>6}{'종목':>7}"
    )
    out = ["[2] 테마 내 rank-IC (테마 동일가중 월별 시계열)", hdr]
    s = res.ic_summary[res.ic_summary["partition"] == PARTITION_ALL]
    for _, r in _sorted(s).iterrows():
        out.append(
            f"{r['window']:<8}{int(r['horizon']):>3} {r['variant']:<11}{int(r['n_months']):>5}"
            f"{_fmt(r['n_eff'], 7, 1)}{_fmt(r['mean'], 8, 4)}{_fmt(r['ci_lo'], 8, 4)}"
            f"{_fmt(r['ci_hi'], 8, 4)}{_fmt(r['t_eff'], 7, 2)}{_fmt(r['ar1'], 6, 2)}"
            f"{_pct(r['share_pos'])}{int(r['n_months_dropped']):>5}"
            f"{_fmt(r['mean_n_themes'], 6, 1)}{_fmt(r['mean_n_stocks'], 7, 1)}"
        )
    return out


def _class_table(res: L4BacktestResult) -> list[str]:
    out = ["[3] cycle_class 별 IC (주 창 · 12M · 평균 [CI]) — 진단, 관문 아님"]
    sc = res.ic_summary[
        (res.ic_summary["window"] == "primary")
        & (res.ic_summary["horizon"] == GATE_HORIZON)
        & (res.ic_summary["partition"] != PARTITION_ALL)
    ]
    out.append(f"{'class':<22}{'테마':>5} " + " ".join(f"{v:>20}" for v in VARIANTS))
    for c in CYCLE_CLASSES:
        g = sc[sc["partition"] == c].set_index("variant")
        if g.empty:
            continue
        cells = []
        for vv in VARIANTS:
            if vv in g.index:
                r = g.loc[vv]
                cells.append(
                    (
                        f"{_fmt(r['mean'], 6, 3)}"
                        f"[{_fmt(r['ci_lo'], 6, 3)},{_fmt(r['ci_hi'], 6, 3)}]"
                    ).replace(" ", "")
                )
            else:
                cells.append("—")
        nbar = g["mean_n_themes"].iloc[0]
        out.append(f"{c:<22}{_fmt(nbar, 5, 1)} " + " ".join(f"{x:>20}" for x in cells))
    return out


def _spread_table(res: L4BacktestResult) -> list[str]:
    hdr = (
        f"{'window':<8}{'h':>3} {'variant':<11}{'N':>5}{'mean':>9}{'ci_lo':>9}{'ci_hi':>9}"
        f"{'hit%':>6}{'AR1':>6}{'테마':>6}"
    )
    out = [
        f"[4] 테마 내 상위 {SPREAD_K} − 하위 {SPREAD_K} (테마 EW 초과수익 차) — 부차 지표",
        hdr,
    ]
    for _, r in _sorted(res.spread_summary).iterrows():
        out.append(
            f"{r['window']:<8}{int(r['horizon']):>3} {r['variant']:<11}{int(r['n_months']):>5}"
            f"{_fmt(r['mean'], 9, 4)}{_fmt(r['ci_lo'], 9, 4)}{_fmt(r['ci_hi'], 9, 4)}"
            f"{_pct(r['share_pos'])}{_fmt(r['ar1'], 6, 2)}{_fmt(r['mean_n_themes'], 6, 1)}"
        )
    return out


def _filter_table(res: L4BacktestResult) -> list[str]:
    out = [
        "[5] Q3 하드 필터 — 제외군 − 통과군 (주 창 · 12M). "
        "E1~E3 만 판정한다; E4·E5 는 수치만 (docs/14 §4.1)",
        f"{'사유':<4}{'설명':<34}{'초과수익차':>11}{'ci_lo':>9}{'ci_hi':>9}"
        f"{'D1차':>9}{'사망률차':>10}{'ci_lo':>9}{'ci_hi':>9}  판정",
    ]
    q3 = res.verdict.get("q3_filters_12m_primary", {})
    for code in axes.HARD_REASON_CODES:
        r = q3.get(code, {})
        ex = r.get("excess_diff", {})
        d1 = r.get("excess_diff_d1", {})
        dt = r.get("death_diff", {})
        exc = ex.get("ci", [float("nan")] * 2)
        dtc = dt.get("ci", [float("nan")] * 2)
        out.append(
            f"{code:<4}{axes.HARD_REASON_LABELS[code]:<34}"
            f"{_fmt(ex.get('mean'), 11, 4)}{_fmt(exc[0], 9, 4)}{_fmt(exc[1], 9, 4)}"
            f"{_fmt(d1.get('mean'), 9, 4)}"
            f"{_fmt(dt.get('mean'), 10, 4)}{_fmt(dtc[0], 9, 4)}{_fmt(dtc[1], 9, 4)}"
            f"  {r.get('verdict', '—')}"
            + (" · 메커니즘 확인" if r.get("mechanism_confirmed") else "")
        )
    out.append(
        "  나쁘지 않다면 그 필터는 알파가 아니라 그냥 표본 절단이다 (docs/14 §1 Q3). "
        "판정이 어떻게 나오든 임계는 옮기지 않는다 (§4.2)."
    )
    return out


def _indicator_table(res: L4BacktestResult) -> list[str]:
    out = ["[6] 하위 지표 단독 IC (Q4 · 주 창 · 12M) — 판정 없음, 표로만"]
    s = res.indicator_ic_summary
    s = s[(s["window"] == "primary") & (s["horizon"] == GATE_HORIZON)]
    for ind in INDICATORS:
        g = s[s["indicator"] == ind]
        if g.empty:
            out.append(f"  {ind:<24} —")
            continue
        r = g.iloc[0]
        out.append(
            f"  {ind:<24}{_fmt(r['mean'], 8, 4)}"
            f" [{_fmt(r['ci_lo'], 7, 4)},{_fmt(r['ci_hi'], 7, 4)}]"
            f"  N={int(r['n_months']):>4}  테마 {_fmt(r['mean_n_themes'], 5, 1)}"
        )
    return out


def _overfit_lines(res: L4BacktestResult) -> list[str]:
    t = res.overfitting["trials"]
    out = ["[7] 과최적화 정산 (docs/14 §6) — **합격 기준에 들어가지 않는다**"]
    out.append(
        f"  시도 수: 선언 {t['declared_only']} · 이 리포트가 본 칸 {t['total']}"
        f" = 창 {t['windows']} × [변형 {t['variants']}×호라이즌 {t['horizons']}×(2+클래스"
        f" {t['classes']}) + 변형 {t['variants']}×1M + 지표 {t['indicators']}×{t['horizons']}"
        f" + 사유 {t['filter_reasons']}×{t['horizons']}×2] + D1 {t['sensitivity_d1']}"
    )
    out.append(
        f"  {'window':<8}{'variant':<11}{'series':<7}{'h':>3}{'DSR N=1':>9}"
        f"{'DSR N=all':>10}{'N':>5}{'N_nonov':>8}"
    )
    for d in res.overfitting["dsr"]:
        n1 = d["dsr_n1"]["dsr_nonoverlapping"] if "dsr_n1" in d else float("nan")
        dt = d["dsr_n_total"]
        out.append(
            f"  {d['window']:<8}{d['variant']:<11}{d['series']:<7}{d['horizon']:>3}"
            f"{_fmt(n1, 9, 3)}{_fmt(dt['dsr_nonoverlapping'], 10, 3)}"
            f"{dt['n']:>5}{dt['n_nonoverlapping']:>8}"
        )
    for p in res.overfitting["pbo"]:
        out.append(
            f"  PBO {p['window']:<8} h={p['horizon']:>2} N={p['n_months']:>4} → "
            f"{_fmt(p.get('pbo', float('nan')), 6, 3)} {p.get('note', '')}"
        )
    out.append(f"  {res.overfitting['note']}")
    return out


def _exclusion_lines(res: L4BacktestResult) -> list[str]:
    e = res.exclusions
    out = ["[8] 제외 (CLAUDE.md §2 · docs/14 §6.4) — 전문은 exclusions.json"]
    tm = e.get("theme_months", {})
    if tm:
        out.append(
            f"  테마-월 {tm['total']:,} 중 IC 를 만든 것 {tm['with_ic']:,}"
            f" · n < {tm['min_stocks_xs']} 로 뺀 것 {tm['dropped_n_lt_min']:,}"
        )
    sm = e.get("stock_months", {})
    if sm:
        out.append(
            f"  종목-월: 구성원 {sm.get('n_members', 0):,} · 상장 {sm.get('n_listed', 0):,}"
            f" · 폐지 {sm.get('n_delisted', 0):,}"
            f" · 10거래일 내 가격 없음 {sm.get('n_no_recent_price', 0):,}"
            f" · 적격 {sm.get('n_eligible', 0):,}"
        )
        out.append(
            "  하드 제외 사유별: "
            + " · ".join(f"{c} {sm.get(f'n_{c}', 0):,}" for c in axes.HARD_REASON_CODES)
        )
        out.append(
            f"  축 결측: composite_partial {sm.get('n_composite_partial', 0):,}"
            f" · S NaN {sm.get('n_s_na', 0):,} · T NaN {sm.get('n_t_na', 0):,}"
            f" · M NaN {sm.get('n_m_na', 0):,}"
        )
    if e.get("theme_months_with_error"):
        out.append(
            f"  특성 생성 실패 테마-월 {e['theme_months_with_error']:,}"
            f" (사유 {e.get('errors_by_kind', {})})"
        )
    for k, val in e.get("forward", {}).items():
        if k.startswith("h"):
            out.append(
                f"  전진 {k}: 가격 있는 종목-월 {val['stock_months_with_price']:,}"
                f" · 미완결 끝점 제외 {val['dropped_incomplete_endpoint']:,}"
                f" · 동결 적용 {val['frozen_last_price']:,}"
                f" · 끝점 가격 전무 {val['no_forward_price_at_all']:,}"
                f" · 유지 {val['kept']:,} · D1 −100% {val['d1_set_to_minus_100']:,}"
            )
    skipped = res.meta.get("themes_skipped", [])
    if skipped:
        out.append(
            f"  총 구성원 < {MIN_MEMBERS_POSSIBLE} 라 격자를 돌지 않은 테마 {len(skipped)}개:"
            f" {', '.join(f'{s[0]}({s[1]})' for s in skipped)}"
        )
    return out


_ORDER = {**{w: i for i, w in enumerate(WINDOWS)}, **{v: i for i, v in enumerate(VARIANTS)}}


def _order(x: Any) -> int:
    return _ORDER.get(x, 99)


def _sorted(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(
        ["window", "horizon", "variant"],
        key=lambda c: c.map(_order) if c.name in ("window", "variant") else c,
    )


# ---------------------------------------------------------------- 실행


def run_backtest(
    *,
    out_root: Path | None = None,
    write: bool = True,
    force: bool = False,
    jobs: int | None = None,
    themes_filter: Sequence[str] | None = None,
    max_months: int | None = None,
    progress: bool = True,
) -> L4BacktestResult:
    """`msa backtest l4` — 스토어에서 전부 만들어 `state/backtests/l4/<store_end>/` 에 쓴다.

    `themes_filter`·`max_months` 는 **스모크 전용**이다. 주면 산출물이 `-smoke` 로 갈리고
    판정에 `smoke` 표시가 붙는다 — 줄인 표본으로 관문을 통과시키지 않기 위해서다.
    """
    p = paths()
    store = Store(p.duckdb)
    themes = load_themes()
    ms = membership_from_store(store, themes)
    se = store.store_end()
    store_end = pd.Timestamp(se) if se else pd.Timestamp.today().normalize()
    # 부분 월은 격자의 끝점이 아니다 (L1 과 같다)
    last_complete = (
        (store_end + pd.offsets.MonthEnd(0))
        if store_end.is_month_end
        else (store_end - pd.offsets.MonthEnd(1))
    )
    dates = month_grid(GRID_START, last_complete)
    n_total: dict[str, int] = {
        str(k): int(v) for k, v in ms.counts()["n_total"].astype(int).items()
    }
    all_ids = [t for t in themes.ids() if t in n_total]
    skipped = [(t, n_total[t]) for t in all_ids if n_total[t] < MIN_MEMBERS_POSSIBLE]
    ids = [t for t in all_ids if n_total[t] >= MIN_MEMBERS_POSSIBLE]
    smoke = themes_filter is not None or max_months is not None
    if themes_filter:
        ids = [t for t in ids if t in set(themes_filter)]
        if not ids:
            raise StoreError(f"--themes 로 남은 테마가 0개다: {list(themes_filter)}")
    if max_months:
        dates = dates[-max_months:]
    tag = f"{store_end.date()}-smoke" if smoke else str(store_end.date())
    root = out_root if out_root is not None else p.backtests_l4
    out_dir = root / tag
    cache_dir = out_dir / "cache"
    if force and cache_dir.exists():
        for f in cache_dir.glob("*.parquet"):
            f.unlink()
    cache_dir.mkdir(parents=True, exist_ok=True)

    log.info(
        "l4-backtest: 테마 %d (구성원 <%d 로 건너뜀 %d) × 월말 %d (%s~%s) · jobs=%s",
        len(ids),
        MIN_MEMBERS_POSSIBLE,
        len(skipped),
        len(dates),
        dates[0].date(),
        dates[-1].date(),
        jobs,
    )
    # RS 는 테마와 무관한 전체 유니버스 값이라 부모가 먼저 캐시한다 (워커가 14번 만들지 않게)
    n_rs = prewarm_rs_cache(store, list(dates), progress=progress)
    log.info("l4-backtest: RS 유니버스 캐시 %d/%d 월", n_rs, len(dates))
    panel, counts = collect_panels(
        ids,
        list(dates),
        db_path=p.duckdb,
        state_dir=p.state,
        cache_dir=cache_dir,
        jobs=jobs if jobs is not None else default_jobs(),
        progress=progress,
    )
    tickers = sorted(set(panel["ticker"])) if not panel.empty else []
    if not tickers:
        raise StoreError("패널이 비었다 — 특성 표를 만든 테마-월이 하나도 없다")
    close = monthly_close(store, tickers).reindex(index=dates).reindex(columns=tickers)
    deaths = death_months(store, tickers, dates)
    fwd = stock_forward(close, deaths, (PBO_HORIZON, *HORIZONS), last_complete=dates[-1])
    by_id = themes.by_id()
    classes = pd.Series({t: by_id[t].cycle_class for t in ids})
    res = run_backtest_frames(panel, counts, fwd, close, classes)
    res.meta.update(pit_vintage=pit_vintage_check(store))
    res.meta.update(
        rs_cache_months=n_rs,
        store_end=str(store_end.date()),
        grid_first=str(dates[0].date()),
        grid_last=str(dates[-1].date()),
        n_months=len(dates),
        jobs=jobs if jobs is not None else default_jobs(),
        smoke=smoke,
        themes_skipped=skipped,
        n_themes_total=len(all_ids),
    )
    if smoke:
        res.verdict["smoke"] = True
        res.verdict["q1"]["gate"] = "smoke (판정 아님 — 표본을 줄였다)"
    store.close()
    if write:
        write_outputs(res, out_dir)
        return replace(res, out_dir=out_dir)
    return res


def write_outputs(res: L4BacktestResult, out_dir: Path) -> Path:
    d = write_snapshot(
        out_dir,
        frames={},
        texts={"report.txt": render_report(res)},
        jsons={
            "verdict.json": _plain(res.verdict),
            "overfitting.json": _plain(res.overfitting),
            "exclusions.json": _plain(res.exclusions),
            "effective_sample.json": _plain(res.effective_sample),
            "meta.json": _plain(res.meta),
        },
    )
    for name, df in (
        ("ic_summary.csv", res.ic_summary),
        ("ic_timeseries.csv", res.ic_monthly),
        ("ic_theme_month.csv", res.ic_theme_month),
        ("ic_indicator.csv", res.indicator_ic_summary),
        ("ic_indicator_timeseries.csv", res.indicator_ic_monthly),
        ("spread.csv", res.spread_monthly),
        ("spread_summary.csv", res.spread_summary),
        ("filters.csv", res.filters_monthly),
        ("filters_summary.csv", res.filters_summary),
        ("theme_month_counts.csv", res.counts),
    ):
        df.to_csv(d / name, index=False)
    dump_json(d / "trials.json", _plain(count_trials()))
    log.info("l4-backtest: 저장 %s", d)
    return d


def theme_ids_with_enough_members(ms: Membership, ids: Iterable[str]) -> list[str]:
    """총 구성원이 `MIN_MEMBERS_POSSIBLE` 이상인 테마만 (임계의 논리적 귀결 — §2.2)."""
    c = {str(k): int(v) for k, v in ms.counts()["n_total"].astype(int).items()}
    return [t for t in ids if c.get(t, 0) >= MIN_MEMBERS_POSSIBLE]
