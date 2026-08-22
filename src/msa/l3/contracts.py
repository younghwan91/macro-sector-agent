"""L3 입력 계약 — 에이전트가 받는 것과 그 출처.

L3 는 다른 계층의 **파일 산출물**만 읽는다. L2·L4·L5 모듈을 임포트하지 않는다 —
계층 간 결합은 파일 스키마로만 한다 (`docs/08-data-contract.md` 의 정신).

| 입력 | 출처 | 없으면 |
|---|---|---|
| 스코어카드 (`ThemeScorecard`) | `state/scans/<date>/` 스캔 산출물 | 예외 — 스캔 없인 안 돈다 |
| 축 1 입력 (`Axis1Inputs`) | 같은 스캔의 `indicators.csv` (L1 계산) | `axis1_available=False` |
| 구성원 재무 요약 (`MemberSummary`) | DuckDB 스토어 — 선택 | 경고 남기고 비운다 (`CLAUDE.md` §2) |
| 거시 상태 (`MacroState`) | JSON 선택 (L2 계약 `state/macro/latest.json`) | `tailwind=None` |
| 이전 thesis | `state/theses/<이전 date>/<theme>.thesis.yaml` | `None` — drift diff 없음 |
| 케이스 스터디 few-shot | `state/cases/*.md` | "few-shot 없음" 을 프롬프트에 적는다 |

**bear 는 `BearInputs` 만 받는다** — L1 스코어·순위·블록 점수·L1 축1 판정이 빠진 부분집합이다
(`docs/05` §6 "에이전트가 항상 강세 논지를 만든다" 대응). 어떤 필드가 빠지는지는 `BearInputs` 자체가
계약이며, 테스트가 bear 프롬프트 본문에 해당 토큰이 없음을 확인한다.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from msa.errors import RefusedInput

log = logging.getLogger(__name__)

SCORE_BLOCKS = ("A", "B", "C", "D", "E", "F")

#: bear 프롬프트에 **나타나면 안 되는** 입력 키. `ThemeScorecard` 중 L1 판단에 해당하는 것들.
#: 테스트(`tests/test_l3_pipeline.py`)가 bear 프롬프트 본문에서 이 토큰을 전수 검사한다.
L1_SCORE_FIELDS: tuple[str, ...] = (
    "score",
    "rank",
    "A_pct",
    "B_pct",
    "C_pct",
    "D_pct",
    "E_pct",
    "F_pct",
    "block_scores",
    "verdict_post_ss",
    "verdict_pre_ss",
    "axis1_contested",
    "flags",
    "breadth_lead",
)


class InputsError(RefusedInput, RuntimeError):
    """입력이 없거나 모자랄 때 던진다 — 빈 값으로 진행하지 않는다 (`CLAUDE.md` §2)."""


@dataclass(frozen=True)
class Axis1Inputs:
    """축 1 — L1 이 계산한 값. **L3 는 이것을 다시 판정하지 않는다** (`docs/05` §2 referee 계약).

    `axis1_status` 는 L1 의 표기 그대로: `ok_external`(실물 시계열) · `ok_fallback`(매출/가격지수
    프록시)
    · `data_missing` · `not_declared`.
    """

    axis1_status: str
    unit_source: str | None
    verdict_pre_ss: str | None
    verdict_post_ss: str | None
    unit_cagr_10y: float | None
    unit_cagr_5y: float | None
    unit_cagr_10y_median: float | None
    sign_split: bool | None
    ss_n: int | None
    ss_coverage: float | None
    ma_flag: bool | None
    exit_count: int | None  # 축 2 — referee 가 contested 판정 때 함께 받는다 (`docs/04` §3.1)

    @property
    def available(self) -> bool:
        return self.axis1_status.startswith("ok") and self.verdict_post_ss in (
            "cycle",
            "warning",
            "death",
        )

    @property
    def unit_series_source(self) -> str:
        """thesis 스키마의 `unit_series_source` enum 값."""
        if not self.available:
            return "none"
        return "physical_series" if self.axis1_status == "ok_external" else "revenue_proxy"

    @property
    def contested(self) -> bool:
        """`docs/04` §3 첫 분기 — 보정 전후 판정이 다르거나 부호가 갈리면 true. 가용하지 않으면 "
        "false."""
        if not self.available:
            return False
        return bool(self.verdict_pre_ss != self.verdict_post_ss) or bool(self.sign_split)

    @property
    def verdict(self) -> str:
        """thesis 의 `value_trap_axes.unit_demand.verdict` — contested 가 판정에 우선한다."""
        if not self.available:
            return "not_applicable"
        if self.contested:
            return "contested"
        assert self.verdict_post_ss is not None
        return self.verdict_post_ss


@dataclass(frozen=True)
class ThemeScorecard:
    """`state/scans/<date>/` 의 한 테마 행. 점수는 참고 정보이며 agent 가 다시 계산하지 않는다."""

    theme_id: str
    scan_date: str
    rank: int | None
    score: float | None
    cycle_class: str
    block_scores: dict[str, float | None]
    n_live: int | None
    small_sample: bool
    secular: bool
    short_hist: bool
    capex_to_da_qtrs_below1: float | None
    capex_to_da: float | None
    ebitda_nonpos_share: float | None
    net_debt_ebitda: float | None
    dd_10y: float | None
    months_since_peak: float | None
    breadth_200: float | None
    flags: str
    axis1: Axis1Inputs

    def summary_for_prompt(self) -> dict[str, Any]:
        """supply·catalyst·referee 에게 주는 형태(스코어 포함)."""
        d: dict[str, Any] = {
            "theme_id": self.theme_id,
            "scan_date": self.scan_date,
            "rank": self.rank,
            "score": self.score,
            "cycle_class": self.cycle_class,
            "block_scores": self.block_scores,
            "n_live": self.n_live,
            "small_sample": self.small_sample,
            "secular": self.secular,
            "short_hist": self.short_hist,
            "capex_to_da": self.capex_to_da,
            "capex_to_da_qtrs_below1": self.capex_to_da_qtrs_below1,
            "ebitda_nonpos_share": self.ebitda_nonpos_share,
            "net_debt_ebitda": self.net_debt_ebitda,
            "dd_10y": self.dd_10y,
            "months_since_peak": self.months_since_peak,
            "breadth_200": self.breadth_200,
            "flags": self.flags,
            "axis1": asdict(self.axis1),
        }
        return d


@dataclass(frozen=True)
class MemberSummary:
    """구성원 PIT 재무 요약 한 줄 (시총 상위). 숫자는 달러·배수. 없는 값은 None 으로 남긴다."""

    ticker: str
    name: str | None
    mcap: float | None
    revenue_ttm: float | None
    capex_to_da: float | None
    net_debt_to_ebitda: float | None
    ebitda_margin: float | None
    debt_current_to_mcap: float | None  # 유동부채(12M 내) / 시총 — 축 5 "24M 만기" 의 보수적 프록시


@dataclass(frozen=True)
class MacroState:
    """L2 산출물 계약 (선택). 파일이 없으면 `None` 으로 전달된다."""

    asof: str | None
    regime: str | None
    tailwind: float | None  # 이 테마의 순풍 점수 [-1, 1]. 0.3 초과면 확신도 +0.10 (`docs/04` §4)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseStudy:
    case_id: str
    text: str


@dataclass(frozen=True)
class ResearchInputs:
    """supply · catalyst · referee 가 받는 전체 입력."""

    theme_id: str
    theme_name: str
    asof: str
    industries: tuple[str, ...]
    scorecard: ThemeScorecard
    members: tuple[MemberSummary, ...]
    macro: MacroState | None
    prior_thesis: dict[str, Any] | None
    prior_thesis_path: str | None
    cases: tuple[CaseStudy, ...]
    scan_dir: str
    warnings: tuple[str, ...] = ()

    @property
    def member_tickers(self) -> tuple[str, ...]:
        return tuple(m.ticker for m in self.members)

    def bear_view(self) -> BearInputs:
        return BearInputs(
            theme_id=self.theme_id,
            theme_name=self.theme_name,
            asof=self.asof,
            industries=self.industries,
            cycle_class=self.scorecard.cycle_class,
            members=self.members,
            macro=self.macro,
            cases=self.cases,
        )


@dataclass(frozen=True)
class BearInputs:
    """bear 전용 — **L1 스코어·순위·블록·축1 판정이 없다.** 이 클래스가 곧 격리 계약이다."""

    theme_id: str
    theme_name: str
    asof: str
    industries: tuple[str, ...]
    cycle_class: str
    members: tuple[MemberSummary, ...]
    macro: MacroState | None
    cases: tuple[CaseStudy, ...]


# ---------------------------------------------------------------- 로더


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _i(v: Any) -> int | None:
    x = _f(v)
    return None if x is None else int(x)


def _b(v: Any) -> bool | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "1.0", "yes"):
            return True
        if s in ("false", "0", "0.0", "no", ""):
            return False
        return None
    return bool(v)


def _s(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return s or None


def latest_scan_dir(scans_root: Path, asof: str | None = None) -> Path:
    """`state/scans/` 아래 `asof` 이하의 최신 스냅샷. 없으면 예외."""
    if not scans_root.exists():
        raise InputsError(f"스캔 디렉터리가 없다: {scans_root} — 먼저 `msa scan` 을 돌려라")
    dirs = sorted(p for p in scans_root.iterdir() if p.is_dir() and (p / "scoreboard.csv").exists())
    if asof:
        dirs = [d for d in dirs if d.name <= asof]
    if not dirs:
        raise InputsError(f"{scans_root} 에 사용할 스캔이 없다 (asof={asof})")
    return dirs[-1]


def load_scorecard(scan_dir: Path, theme_id: str) -> ThemeScorecard:
    sb = pd.read_csv(scan_dir / "scoreboard.csv", index_col=0)
    ind = pd.read_csv(scan_dir / "indicators.csv", index_col=0)
    if theme_id not in sb.index:
        raise InputsError(f"테마 `{theme_id}` 가 {scan_dir.name} 스코어보드에 없다")
    if theme_id not in ind.index:
        raise InputsError(f"테마 `{theme_id}` 가 {scan_dir.name} indicators.csv 에 없다")
    r: Any = sb.loc[theme_id]
    x: Any = ind.loc[theme_id]

    def g(row: Any, k: str) -> Any:
        return row[k] if k in row.index else None

    axis1 = Axis1Inputs(
        axis1_status=_s(g(x, "axis1_status")) or "not_declared",
        unit_source=_s(g(x, "unit_source")),
        verdict_pre_ss=_s(g(x, "verdict_pre_ss")),
        verdict_post_ss=_s(g(x, "verdict_post_ss")),
        unit_cagr_10y=_f(g(x, "unit_cagr_10y")),
        unit_cagr_5y=_f(g(x, "unit_cagr_5y")),
        unit_cagr_10y_median=_f(g(x, "unit_cagr_10y_median")),
        sign_split=_b(g(x, "sign_split")),
        ss_n=_i(g(x, "ss_n")),
        ss_coverage=_f(g(x, "ss_coverage")),
        ma_flag=_b(g(x, "ma_flag")),
        exit_count=_i(g(x, "exit_count")),
    )
    short_hist = any(
        bool(_b(g(x, k)))
        for k in ("short_hist_D", "short_hist_roic", "short_hist_margin", "short_hist_range")
    ) or bool(_b(g(r, "short_hist")))
    return ThemeScorecard(
        theme_id=theme_id,
        scan_date=scan_dir.name,
        rank=_i(g(r, "rank")),
        score=_f(g(r, "score")),
        cycle_class=_s(g(r, "cycle_class")) or "unknown",
        block_scores={b: _f(g(r, b)) for b in SCORE_BLOCKS},
        n_live=_i(g(r, "n_live")),
        small_sample=bool(_b(g(r, "small_sample"))),
        secular=bool(_b(g(r, "secular"))),
        short_hist=short_hist,
        capex_to_da_qtrs_below1=_f(g(x, "capex_to_da_qtrs_below1")),
        capex_to_da=_f(g(x, "capex_to_da")),
        ebitda_nonpos_share=_f(g(x, "ebitda_nonpos_share")),
        net_debt_ebitda=_f(g(x, "net_debt_ebitda")),
        dd_10y=_f(g(x, "dd_10y")),
        months_since_peak=_f(g(x, "months_since_peak")),
        breadth_200=_f(g(x, "breadth_200")),
        flags=_s(g(r, "flags")) or "",
        axis1=axis1,
    )


def load_macro_state(path: Path | None, theme_id: str) -> MacroState | None:
    """L2 산출물 JSON. 형식(관용): "
    "`{"asof":..., "regime":..., "tailwind": {theme_id: float} | float}`."""
    if path is None or not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    tw_raw = raw.get("tailwind")
    tailwind = _f(tw_raw.get(theme_id)) if isinstance(tw_raw, dict) else _f(tw_raw)
    return MacroState(
        asof=_s(raw.get("asof")), regime=_s(raw.get("regime")), tailwind=tailwind, raw=raw
    )


def find_prior_thesis(theses_root: Path, theme_id: str, before: str) -> Path | None:
    """`state/theses/<date>/<theme>.thesis.yaml` 중 `before` 이전의 최신."""
    if not theses_root.exists():
        return None
    cands = sorted(
        p for p in theses_root.glob(f"*/{theme_id}.thesis.yaml") if p.parent.name < before
    )
    return cands[-1] if cands else None


def load_prior_thesis(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    return obj if isinstance(obj, dict) else None


def load_case_studies(cases_dir: Path | None) -> tuple[CaseStudy, ...]:
    """`state/cases/*.md` — M6 가 작성하는 6건. 없으면 빈 튜플 (프롬프트에 "few-shot 없음")."""
    if cases_dir is None or not cases_dir.exists():
        return ()
    out = []
    for p in sorted(cases_dir.glob("*.md")):
        out.append(CaseStudy(case_id=p.stem, text=p.read_text(encoding="utf-8")))
    return tuple(out)


def members_from_store(
    store: Any, theme_id: str, themes: Any, asof: str, top_n: int = 12
) -> list[MemberSummary]:
    """DuckDB 스토어에서 구성원 재무 요약 (시총 상위 `top_n`). PIT = `datekey ≤ asof` 최신 분기.

    `msa.l1.fundamentals` 의 TTM 규칙(4분기 전부·400일 이내)을 따른다. `store` 는
    `msa.data.store.Store`,
    `themes` 는 `msa.themes.ThemeSet` — 타입을 `Any` 로 둔 것은 이 모듈이 스토어 없이도 임포트되게
    하려는 것.
    """
    from msa.data.pit import L3_TTM_FIELDS, first_reported_quarterly_sql, ttm_window_sql
    from msa.themes import membership_from_store

    membership = membership_from_store(store, themes)
    tickers = membership.members(theme_id)
    if not tickers:
        raise InputsError(f"테마 `{theme_id}` 의 구성원이 0명이다")
    store.execute(
        "create or replace temp table l3_members as select * from (values "
        + ",".join(f"('{t}')" for t in tickers)
        + ") t(ticker)"
    )
    sql = f"""
    with px as (
        select ticker, mcap from (
            select ticker, mcap, row_number() over (partition by ticker order by date desc) rn
            from prices
            where date <= '{asof}' and mcap is not null
              and ticker in (select ticker from l3_members)
        ) where rn = 1
    ),
    {
        first_reported_quarterly_sql(
            "f.ticker, f.calendardate, f.datekey, f.revenue, f.capex, f.depamor, f.ebitda, "
            "f.debt, f.debtc, f.cashneq",
            where_extra=(
                f" and f.datekey <= '{asof}' and f.ticker in (select ticker from l3_members)"
            ),
        )
    },
    ttm as (
        select *,
{ttm_window_sql(L3_TTM_FIELDS)},
            lag(calendardate, 3) over (partition by ticker order by calendardate) as cd_3back,
            row_number() over (partition by ticker order by calendardate desc) as rn_last
        from q
        window w4 as (partition by ticker order by calendardate
                      rows between 3 preceding and current row)
    ),
    last as (select * from ttm
             where rn_last = 1 and calendardate >= date '{asof}' - interval 15 month)
    select l.ticker, t.name, p.mcap,
        case when n_rev4 = 4 and cd_3back >= calendardate - interval 400 day
             then revenue_ttm end as revenue_ttm,
        case when n_capex4 = 4 and n_da4 = 4 and da_ttm > 0
             then capex_ttm / da_ttm end as capex_to_da,
        case when n_ebitda4 = 4 and ebitda_ttm > 0
             then (coalesce(debt,0) - coalesce(cashneq,0)) / ebitda_ttm end as net_debt_to_ebitda,
        case when n_ebitda4 = 4 and n_rev4 = 4 and revenue_ttm > 0
             then ebitda_ttm / revenue_ttm end as ebitda_margin,
        case when p.mcap > 0 then coalesce(debtc, 0) / p.mcap end as debt_current_to_mcap
    from last l left join px p using (ticker) left join tickers t using (ticker)
    order by p.mcap desc nulls last
    limit {int(top_n)}
    """
    df = store.query(sql)
    out: list[MemberSummary] = []
    for _, r in df.iterrows():
        out.append(
            MemberSummary(
                ticker=str(r["ticker"]),
                name=_s(r["name"]),
                mcap=_f(r["mcap"]),
                revenue_ttm=_f(r["revenue_ttm"]),
                capex_to_da=_f(r["capex_to_da"]),
                net_debt_to_ebitda=_f(r["net_debt_to_ebitda"]),
                ebitda_margin=_f(r["ebitda_margin"]),
                debt_current_to_mcap=_f(r["debt_current_to_mcap"]),
            )
        )
    if not out:
        log.warning(
            "테마 %s: 재무 요약 0행 (asof=%s) — 구성원 %d명 중 PIT 분기 없음",
            theme_id,
            asof,
            len(tickers),
        )
    return out


def assemble_inputs(
    theme_id: str,
    *,
    state_dir: Path,
    asof: str | None = None,
    macro_path: Path | None = None,
    cases_dir: Path | None = None,
    with_store: bool = True,
    top_members: int = 12,
) -> ResearchInputs:
    """CLI 경로의 입력 조립. 스토어가 없으면 **경고를 남기고** 구성원 요약을 비운다 — 리포트에 "
    "표시된다."""
    from msa.themes import load_themes

    scan_dir = latest_scan_dir(state_dir / "scans", asof)
    card = load_scorecard(scan_dir, theme_id)
    themes = load_themes()
    theme = themes.get(theme_id)
    asof_s = asof or scan_dir.name
    warnings: list[str] = []
    members: list[MemberSummary] = []
    if with_store:
        from msa.config import paths
        from msa.data.store import Store

        db = paths().duckdb
        if db.exists():
            with Store(db) as store:
                members = members_from_store(store, theme_id, themes, asof_s, top_n=top_members)
        else:
            warnings.append(f"DuckDB 스토어 없음({db}) — 구성원 재무 요약을 비운 채 진행")
    else:
        warnings.append("구성원 재무 요약 생략(--no-store)")
    if macro_path is None:
        cand = state_dir / "macro" / "latest.json"
        macro_path = cand if cand.exists() else None
    macro = load_macro_state(macro_path, theme_id)
    if macro is None:
        warnings.append("거시 상태(L2) 없음 — 확신도의 순풍 항(+0.10) 미적용")
    theses_root = state_dir / "theses"
    prior_path = find_prior_thesis(theses_root, theme_id, asof_s)
    cases = load_case_studies(cases_dir if cases_dir is not None else state_dir / "cases")
    if not cases:
        warnings.append("케이스 스터디 few-shot 없음 (state/cases/ 비어 있음 — M6 산출물)")
    return ResearchInputs(
        theme_id=theme_id,
        theme_name=theme.name_ko,
        asof=asof_s,
        industries=tuple(theme.industry_match),
        scorecard=card,
        members=tuple(members),
        macro=macro,
        prior_thesis=load_prior_thesis(prior_path),
        prior_thesis_path=str(prior_path.relative_to(state_dir)) if prior_path else None,
        cases=cases,
        scan_dir=f"state/scans/{scan_dir.name}",  # 라벨 — 절대경로를 thesis 에 남기지 않는다
        warnings=tuple(warnings),
    )


def today() -> str:
    return date.today().isoformat()
