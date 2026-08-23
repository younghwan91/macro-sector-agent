"""L3 입력 계약 — 에이전트가 받는 것과 그 출처.

L3 는 다른 계층의 **파일 산출물**만 읽는다. L4·L5 모듈을 임포트하지 않는다 —
계층 간 결합은 파일 스키마로만 한다 (`docs/08-data-contract.md` 의 정신).

| 입력 | 출처 | 없으면 |
|---|---|---|
| 스코어카드 (`ThemeScorecard`) | `state/scans/<date>/` 스캔 산출물 | 예외 — 스캔 없인 안 돈다 |
| 축 1 입력 (`Axis1Inputs`) | 같은 스캔의 `indicators.csv` (L1 계산) | `axis1_available=False` |
| 구성원 재무 요약 (`MemberSummary`) | DuckDB 스토어 — 선택 | 경고 남기고 비운다 (`CLAUDE.md` §2) |
| 이전 thesis | `state/theses/<이전 date>/<theme>.thesis.yaml` | `None` — drift diff 없음 |
| 케이스 스터디 few-shot | `state/cases/*.md` | "few-shot 없음" 을 프롬프트에 적는다 |

**bear 는 `BearInputs` 만 받는다** — L1 스코어·순위·블록 점수·L1 축1 판정이 빠진 부분집합이다
(`docs/05` §6 "에이전트가 항상 강세 논지를 만든다" 대응). 어떤 필드가 빠지는지는 `BearInputs` 자체가
계약이며, 테스트가 bear 프롬프트 본문에 해당 토큰이 없음을 확인한다.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from msa.coerce import opt_bool, opt_float, opt_int, opt_str
from msa.config import paths
from msa.errors import RefusedInput
from msa.l1.scan import scan_dirs
from msa.status import Axis1Status
from msa.thesis import read_thesis_yaml, thesis_filename

log = logging.getLogger(__name__)

#: L1 스코어보드의 블록 열 (`msa.l1.scoreboard.BLOCKS` 와 같은 값 — 여기서는 파일 계약으로만 안다).
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
        return self.axis1_status in (
            Axis1Status.OK_EXTERNAL,
            Axis1Status.OK_FALLBACK,
        ) and self.verdict_post_ss in ("cycle", "warning", "death")

    @property
    def unit_series_source(self) -> str:
        """thesis 스키마의 `unit_series_source` enum 값."""
        if not self.available:
            return "none"
        if self.axis1_status == Axis1Status.OK_EXTERNAL:
            return "physical_series"
        return "revenue_proxy"

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
    capex_to_da: float | None
    capex_to_da_qtrs_below1: float | None
    ebitda_nonpos_share: float | None
    net_debt_ebitda: float | None
    dd_10y: float | None
    months_since_peak: float | None
    breadth_200: float | None
    flags: str
    axis1: Axis1Inputs

    def summary_for_prompt(self) -> dict[str, Any]:
        """supply·catalyst·referee 에게 주는 형태(스코어 포함) — 필드 선언 순서 그대로 전부.
        (프롬프트 JSON 의 키 순서가 곧 필드 순서다 — 필드를 옮기면 프롬프트가 바뀐다.)"""
        return asdict(self)


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
    cases: tuple[CaseStudy, ...]


# ---------------------------------------------------------------- 로더


def latest_scan_dir(scans_root: Path, asof: str | None = None) -> Path:
    """`state/scans/` 아래 `asof` 이하의 최신 스냅샷. 없으면 예외."""
    if not scans_root.exists():
        raise InputsError(f"스캔 디렉터리가 없다: {scans_root} — 먼저 `msa scan` 을 돌려라")
    dirs = [p for _d, p in scan_dirs(scans_root) if (p / "scoreboard.csv").exists()]
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
        axis1_status=opt_str(g(x, "axis1_status")) or Axis1Status.NOT_DECLARED.value,
        unit_source=opt_str(g(x, "unit_source")),
        verdict_pre_ss=opt_str(g(x, "verdict_pre_ss")),
        verdict_post_ss=opt_str(g(x, "verdict_post_ss")),
        unit_cagr_10y=opt_float(g(x, "unit_cagr_10y")),
        unit_cagr_5y=opt_float(g(x, "unit_cagr_5y")),
        unit_cagr_10y_median=opt_float(g(x, "unit_cagr_10y_median")),
        sign_split=opt_bool(g(x, "sign_split")),
        ss_n=opt_int(g(x, "ss_n")),
        ss_coverage=opt_float(g(x, "ss_coverage")),
        ma_flag=opt_bool(g(x, "ma_flag")),
        exit_count=opt_int(g(x, "exit_count")),
    )
    short_hist = any(
        bool(opt_bool(g(x, k)))
        for k in ("short_hist_D", "short_hist_roic", "short_hist_margin", "short_hist_range")
    ) or bool(opt_bool(g(r, "short_hist")))
    return ThemeScorecard(
        theme_id=theme_id,
        scan_date=scan_dir.name,
        rank=opt_int(g(r, "rank")),
        score=opt_float(g(r, "score")),
        cycle_class=opt_str(g(r, "cycle_class")) or "unknown",
        block_scores={b: opt_float(g(r, b)) for b in SCORE_BLOCKS},
        n_live=opt_int(g(r, "n_live")),
        small_sample=bool(opt_bool(g(r, "small_sample"))),
        secular=bool(opt_bool(g(r, "secular"))),
        short_hist=short_hist,
        capex_to_da=opt_float(g(x, "capex_to_da")),
        capex_to_da_qtrs_below1=opt_float(g(x, "capex_to_da_qtrs_below1")),
        ebitda_nonpos_share=opt_float(g(x, "ebitda_nonpos_share")),
        net_debt_ebitda=opt_float(g(x, "net_debt_ebitda")),
        dd_10y=opt_float(g(x, "dd_10y")),
        months_since_peak=opt_float(g(x, "months_since_peak")),
        breadth_200=opt_float(g(x, "breadth_200")),
        flags=opt_str(g(r, "flags")) or "",
        axis1=axis1,
    )


def find_prior_thesis(theses_root: Path, theme_id: str, before: str) -> Path | None:
    """`state/theses/<date>/<theme>.thesis.yaml` 중 `before` 이전의 최신."""
    if not theses_root.exists():
        return None
    cands = sorted(
        p for p in theses_root.glob(f"*/{thesis_filename(theme_id)}") if p.parent.name < before
    )
    return cands[-1] if cands else None


def load_prior_thesis(path: Path | None) -> dict[str, Any] | None:
    """이전 thesis — 최상위가 매핑이 아니면 None (diff 없이 진행, 깨진 YAML 은 그대로 던진다)."""
    if path is None:
        return None
    try:
        return read_thesis_yaml(path)
    except ValueError:
        return None


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
    # 시총: `asof` 이하 최근 non-null (`Store.latest_mcap` = arg_max) — 질의 동안만 뷰로 건다
    px = store.latest_mcap(tickers, asof).reset_index()
    members = pd.DataFrame({"ticker": tickers})
    sql = f"""
    with {
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
    df = store.query(sql, frames={"l3_members": members, "px": px})
    out = [
        MemberSummary(
            ticker=str(r["ticker"]),
            name=opt_str(r["name"]),
            mcap=opt_float(r["mcap"]),
            revenue_ttm=opt_float(r["revenue_ttm"]),
            capex_to_da=opt_float(r["capex_to_da"]),
            net_debt_to_ebitda=opt_float(r["net_debt_to_ebitda"]),
            ebitda_margin=opt_float(r["ebitda_margin"]),
            debt_current_to_mcap=opt_float(r["debt_current_to_mcap"]),
        )
        for _, r in df.iterrows()
    ]
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
    cases_dir: Path | None = None,
    with_store: bool = True,
    top_members: int = 12,
) -> ResearchInputs:
    """CLI 경로의 입력 조립. 스토어가 없으면 **경고를 남기고** 구성원 요약을 비운다 — 리포트에 "
    "표시된다. `state_dir` 아래 하위 경로 이름은 `config.Paths` 의 것이다."""
    from msa.themes import load_themes

    p = dataclasses.replace(paths(), state=state_dir)
    scan_dir = latest_scan_dir(p.scans, asof)
    card = load_scorecard(scan_dir, theme_id)
    themes = load_themes()
    theme = themes.get(theme_id)
    asof_s = asof or scan_dir.name
    warnings: list[str] = []
    members: list[MemberSummary] = []
    if with_store:
        from msa.data.store import Store

        if p.duckdb.exists():
            with Store(p.duckdb) as store:
                members = members_from_store(store, theme_id, themes, asof_s, top_n=top_members)
        else:
            warnings.append(f"DuckDB 스토어 없음({p.duckdb}) — 구성원 재무 요약을 비운 채 진행")
    else:
        warnings.append("구성원 재무 요약 생략(--no-store)")
    prior_path = find_prior_thesis(p.theses, theme_id, asof_s)
    cases = load_case_studies(cases_dir if cases_dir is not None else p.cases_dir)
    if not cases:
        warnings.append("케이스 스터디 few-shot 없음 (state/cases/ 비어 있음 — M6 산출물)")
    return ResearchInputs(
        theme_id=theme_id,
        theme_name=theme.name_ko,
        asof=asof_s,
        industries=tuple(theme.industry_match),
        scorecard=card,
        members=tuple(members),
        prior_thesis=load_prior_thesis(prior_path),
        prior_thesis_path=str(prior_path.relative_to(state_dir)) if prior_path else None,
        cases=cases,
        scan_dir=f"state/scans/{scan_dir.name}",  # 라벨 — 절대경로를 thesis 에 남기지 않는다
        warnings=tuple(warnings),
    )
