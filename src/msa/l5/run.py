"""L5 조립 — 입력 → 리스크 → SOCP → 사다리 → 매매계획서 → `state/portfolio/<date>/`.

산출물:
- `weights.csv` — ticker · theme · role · target_weight · 사다리 3단 비중 · Tier-2 · 시간 스탑
- `plan.md` — `docs/07` §6 형식의 매매계획서 (코드 블록)
- `diagnostics.json` — 솔버·상태·완화 · λ·c·c̃·출처 · C1 두 방식과 구속 · `L_i` 두 항과 사유 ·
  ENB·p₁₂₃ · 공분산 출처 · 축 1 가능 목록 · 경고 전부
- `positions-proposal.{yaml,md}` (선택, `emit_positions=True` / `--emit-positions`) —
  `state/positions.yaml` 모양의 **미체결 제안** + 승격 체크리스트 (`l5/positions.py`)

**자동 주문은 없다** (`CLAUDE.md` §8). 이 모듈은 파일을 쓴다. 주문은 사람이 낸다.
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from msa import __version__
from msa.config import paths
from msa.dates import asof_or_today
from msa.io import write_snapshot
from msa.l5.inputs import Pick, PortfolioInputs, ThesisInput, load_inputs
from msa.l5.ladders import (
    THEME_CAP_FOR_LOSS,
    TIER2_FROM_AVG,
    PositionPlan,
    build_position_plan,
)
from msa.l5.optimize import (
    LAMBDA_COMPRESS,
    MDD_BUDGET,
    MDD_K,
    MIN_CONFIDENCE,
    MU_METHOD,
    Problem,
    Solution,
    compress_confidence,
    solve,
)
from msa.l5.risk import (
    CovarianceResult,
    ENBResult,
    ScenarioLoss,
    effective_number_of_bets,
    filled_gap_days,
    load_theme_ew_returns,
    map_theme_cov_to_stocks,
    monthly_returns,
    scenario_losses_for_themes,
    stock_covariance_from_returns,
    theme_covariance,
)
from msa.themes import Theme, ThemeSet, load_themes

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThemeRow:
    """계획서의 테마 블록 머리 — 확신도와 출처, 축 1, L_i."""

    theme: str
    name_ko: str
    cycle_class: str
    cluster: str | None
    c: float
    c_tilde: float | None  # C6 탈락이면 None
    c_source: str
    axis1_declared: bool  # themes.yaml physical_ref 보유
    axis1_available: bool | None  # thesis 가 적은 값 (없으면 None)
    eligible: bool
    excluded_reason: str | None
    weight: float
    scenario: ScenarioLoss


@dataclass(frozen=True)
class PortfolioResult:
    asof: date
    inputs_dir: str
    theme_rows: tuple[ThemeRow, ...]
    positions: tuple[PositionPlan, ...]
    solution: Solution | None
    cov: CovarianceResult | None
    enb: ENBResult | None
    lam: float
    mu_method: str
    mdd_budget: float
    k: float
    anchor_share: float | None  # 앵커 비중 / 총투자
    warnings: tuple[str, ...]
    axis1_universe: tuple[int, int]  # (physical_ref 보유 테마 수, 전체 테마 수)
    out_dir: Path | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def diagnostics(self) -> dict[str, object]:
        return {
            "version": __version__,
            "asof": str(self.asof),
            "inputs_dir": self.inputs_dir,
            "declared": {
                "lambda_compress": self.lam,
                "mu_method": self.mu_method,
                "mdd_budget": self.mdd_budget,
                "k": self.k,
                "min_confidence": MIN_CONFIDENCE,
            },
            "solution": self.solution.as_dict() if self.solution else None,
            "covariance": (
                {
                    "source": self.cov.source,
                    "lookback": self.cov.lookback_months,
                    "n_obs": self.cov.n_obs,
                    "shrink": f"constant-correlation δ={self.cov.shrink_delta}",
                    "window": list(self.cov.window),
                    "notes": list(self.cov.notes),
                }
                if self.cov
                else None
            ),
            "enb": self.enb.as_dict() if self.enb else None,
            "anchor_share": self.anchor_share,
            "axis1_universe": {
                "declared": self.axis1_universe[0],
                "total": self.axis1_universe[1],
            },
            "themes": [
                {
                    "theme": r.theme,
                    "name_ko": r.name_ko,
                    "cycle_class": r.cycle_class,
                    "cluster": r.cluster,
                    "c": r.c,
                    "c_tilde": r.c_tilde,
                    "c_source": r.c_source,
                    "axis1_declared": r.axis1_declared,
                    "axis1_available": r.axis1_available,
                    "eligible": r.eligible,
                    "excluded_reason": r.excluded_reason,
                    "weight": r.weight,
                    "scenario_loss": r.scenario.as_dict(),
                }
                for r in self.theme_rows
            ],
            "positions": [p.as_dict() for p in self.positions],
            "warnings": list(self.warnings),
            **dict(self.extra),
        }


def _eligibility(t: ThesisInput) -> tuple[bool, str | None]:
    if not t.portfolio_eligible:
        return False, f"gate_result: portfolio_eligible=false (status={t.gate_status})"
    if t.cycle_confidence < MIN_CONFIDENCE:
        return False, f"C6 최소 확신도 미달 (c={t.cycle_confidence:.2f} < {MIN_CONFIDENCE})"
    return True, None


def _eligibility_and_c_tilde(
    inputs: PortfolioInputs, cand_themes: Sequence[str], warnings: list[str]
) -> tuple[dict[str, str | None], dict[str, float]]:
    """C6·게이트 → (테마별 제외 사유; None 이면 편입 후보) 와 편입 후보의 압축 확신도 `c̃`."""
    excl_reason: dict[str, str | None] = {}
    for t in cand_themes:
        _ok, why = _eligibility(inputs.theses[t])
        excl_reason[t] = why
        if why is not None:
            warnings.append(f"{t}: 편입 제외 — {why}")
    elig = [t for t in cand_themes if excl_reason[t] is None]
    c_raw = {t: inputs.theses[t].cycle_confidence for t in elig}
    return excl_reason, compress_confidence(c_raw, LAMBDA_COMPRESS)


def _covariance(
    picks: Sequence[Pick],
    elig_themes: Sequence[str],
    *,
    daily_ew: pd.DataFrame | None,
    stock_returns: pd.DataFrame | None,
    ts_asof: pd.Timestamp,
    warnings: list[str],
) -> CovarianceResult:
    """종목 수익률이 있으면 그것으로, 없으면 테마 EW 지수 사상(β=1) 으로 `Σ`."""
    tickers = [p.ticker for p in picks]
    if stock_returns is not None:
        return stock_covariance_from_returns(stock_returns, tickers, asof=ts_asof)
    if daily_ew is None:
        raise ValueError("테마 EW 수익률도 종목 수익률도 없다 — 공분산을 만들 수 없다")
    tcov = theme_covariance(monthly_returns(daily_ew), elig_themes, asof=ts_asof)
    cov = map_theme_cov_to_stocks(
        tcov, [p.theme for p in picks], [p.idio_vol_ann for p in picks], tickers
    )
    # 부분 결측도 경고한다 — 한 종목이라도 있으면 넘어가면, 나머지는 σ_idio=0(테마 내 상관 1)
    # 으로 들어가는데 그 사실이 계획서에 안 뜬다 (`CLAUDE.md` §2 "센 것만 말한다").
    no_idio = [p.ticker for p in picks if not p.idio_vol_ann]
    if no_idio:
        scope = "전 종목" if len(no_idio) == len(picks) else f"{len(no_idio)}/{len(picks)}종목"
        warnings.append(
            f"공분산: 종목 수익률 없음 → 테마 EW 지수 사상(β=1) · 고유분산 0 인 것이 {scope} "
            f"{no_idio} — 그 종목들은 같은 테마 안에서 상관 1 로 들어간다 "
            "(ENB 가 테마 수를 넘지 않는다)"
        )
    return cov


def _solve_and_report(
    inputs: PortfolioInputs,
    picks: Sequence[Pick],
    *,
    by_id: Mapping[str, Theme],
    c_tilde: Mapping[str, float],
    losses: Mapping[str, ScenarioLoss],
    cov: CovarianceResult,
    warnings: list[str],
) -> tuple[Solution, ENBResult]:
    """SOCP 를 풀고 완화·상태·C4·C1·경계 상한을 경고로 적는다. ENB 도 여기서."""
    stock_themes = [p.theme for p in picks]
    prob = Problem(
        tickers=tuple(p.ticker for p in picks),
        themes=tuple(stock_themes),
        classes=tuple(by_id[t].cycle_class for t in stock_themes),
        clusters=tuple(by_id[t].correlation_cluster for t in stock_themes),
        coef=tuple(c_tilde[t] * 1.0 for t in stock_themes),  # μ=1
        sigma=cov.sigma,
        scenario_loss=tuple(losses[t].value for t in stock_themes),
        adv20_usd=tuple(p.adv20_usd for p in picks),
        min_weight=tuple(p.min_weight for p in picks),
        capital_usd=inputs.capital_usd,
        cluster_caps=inputs.cluster_caps,
    )
    solution = solve(prob)
    if solution.stage > 0:
        warnings.append(
            f"infeasible → 완화 {solution.stage}단: {', '.join(solution.relaxed)} "
            "(순서 C3 → C1 고정, docs/09 §5)"
        )
    if solution.status != "optimal":
        warnings.append(f"솔버 상태 {solution.status} — 해의 정밀도를 의심하라")
    if inputs.capital_usd is None:
        warnings.append(
            "C4 유동성 미적용 — 자본(--capital) 미지정 → `w·Capital ≤ 10%·ADV20` 을 한 번도 "
            "걸지 않았다. docs/07 §2.4 가 핵심 제약으로 세운 것이 이 산출물에는 없다 — "
            "비중이 하루 거래대금을 넘을 수 있다"
        )
    elif solution.c4_skipped:
        warnings.append(f"C4 유동성: ADV 없어 적용 못 한 종목 {list(solution.c4_skipped)}")
    wv = np.array([solution.weights[p.ticker] for p in picks], dtype=np.float64)
    enb = effective_number_of_bets(cov.sigma, wv)
    if solution.mdd_scenario is None:
        warnings.append("C1: 시나리오 기반(ii) 계산 불가 — 변동성 기반(i) 만 구속")
    if solution.binding_caps:
        warnings.append(f"경계에 붙은 상한: {list(solution.binding_caps)}")
    return solution, enb


def _theme_rows(
    inputs: PortfolioInputs,
    cand_themes: Sequence[str],
    picks: Sequence[Pick],
    *,
    by_id: Mapping[str, Theme],
    c_tilde: Mapping[str, float],
    excl_reason: Mapping[str, str | None],
    losses: Mapping[str, ScenarioLoss],
    weights: Mapping[str, float],
    warnings: list[str],
) -> tuple[ThemeRow, ...]:
    """계획서의 테마 블록 머리 — 편입 여부와 무관하게 전 후보 테마. 축 1 경고도 여기서."""
    rows: list[ThemeRow] = []
    for t in cand_themes:
        th = by_id[t]
        ti = inputs.theses[t]
        rows.append(
            ThemeRow(
                theme=t,
                name_ko=th.name_ko,
                cycle_class=th.cycle_class,
                cluster=th.correlation_cluster,
                c=ti.cycle_confidence,
                c_tilde=c_tilde.get(t),
                c_source=ti.confidence_source,
                axis1_declared=th.axis1_declared,
                axis1_available=ti.axis1_available,
                eligible=excl_reason[t] is None,
                excluded_reason=excl_reason[t],
                weight=sum(weights.get(p.ticker, 0.0) for p in picks if p.theme == t),
                scenario=losses[t],
            )
        )
    for r in rows:
        if r.eligible and not r.axis1_declared:
            warnings.append(
                f"{r.theme}: 축 1 적용 불가 (physical_ref 없음) — M6 운영 범위 밖이다 "
                "(docs/11 '첫 실전 사용 시점'). 판정은 축 3 쪽으로 넘어가 있다"
            )
        if r.eligible and r.axis1_declared and r.axis1_available is False:
            warnings.append(
                f"{r.theme}: physical_ref 는 있으나 thesis 가 axis1_available=false 로 적었다"
            )
    return tuple(rows)


def build_portfolio(
    inputs: PortfolioInputs,
    *,
    asof: date,
    themes: ThemeSet,
    daily_ew: pd.DataFrame | None,
    stock_returns: pd.DataFrame | None = None,
    inputs_dir: str = "",
) -> PortfolioResult:
    """순수 조립 함수 — 파일을 쓰지 않는다. 테스트는 여기를 부른다."""
    warnings: list[str] = []
    by_id = themes.by_id()
    cand_themes = inputs.themes()
    unknown = [t for t in cand_themes if t not in by_id]
    if unknown:
        raise ValueError(f"themes.yaml 에 없는 테마: {unknown}")

    # --- C6 · 게이트 · 확신도 압축 (편입 후보 평균 기준)
    excl_reason, c_tilde = _eligibility_and_c_tilde(inputs, cand_themes, warnings)
    elig_themes = [t for t in cand_themes if excl_reason[t] is None]

    # --- L_i (전 후보 테마에 대해 — 제외된 테마도 표기는 한다)
    clusters = {t: by_id[t].correlation_cluster for t in cand_themes}
    ts_asof = pd.Timestamp(asof)
    # 월간 복리·누적 지수가 **수익률 0 으로 메운 일수** — 동작은 그대로 두고 센다 (risk 머리말).
    gaps: dict[str, int] = {}
    if daily_ew is not None:
        cols = [t for t in cand_themes if t in daily_ew.columns]
        gaps = {k: v for k, v in filled_gap_days(daily_ew[cols]).items() if v > 0}
        if gaps:
            top = ", ".join(f"{k} {v}일" for k, v in sorted(gaps.items(), key=lambda kv: -kv[1]))
            warnings.append(
                f"테마 EW 수익률에 결측일이 있다 — 수익률 0 으로 메우고 계산했다 ({top}). "
                "이 지수가 L_i 의 '과거 유사 국면' 낙폭과 월간 공분산을 만든다 — "
                "메운 날은 무변동으로 들어가 변동성·낙폭을 낮춘다"
            )
    losses = scenario_losses_for_themes(
        cand_themes, clusters=clusters, daily_ew=daily_ew, cases=inputs.cases, asof=ts_asof
    )
    for t in elig_themes:
        if not losses[t].computable:
            warnings.append(
                f"{t}: L_i 형성 불가 → C1-(ii) 에서 빠짐 — " + " / ".join(losses[t].reasons)
            )
    if not inputs.cases.exists:
        warnings.append(
            "케이스 스터디 표가 없다 (state/cases/cases.yaml) — C1-(ii) 시나리오 제약이 한 테마도 "
            "계산되지 않았다. MDD 예산은 변동성 한 축으로만 지켜진다 (docs/11 '순서' 3)."
        )

    # --- 공분산 · SOCP · ENB
    picks = [p for p in inputs.picks if excl_reason[p.theme] is None]
    solution: Solution | None = None
    cov: CovarianceResult | None = None
    enb: ENBResult | None = None
    weights: dict[str, float] = {}
    if picks:
        cov = _covariance(
            picks,
            elig_themes,
            daily_ew=daily_ew,
            stock_returns=stock_returns,
            ts_asof=ts_asof,
            warnings=warnings,
        )
        solution, enb = _solve_and_report(
            inputs, picks, by_id=by_id, c_tilde=c_tilde, losses=losses, cov=cov, warnings=warnings
        )
        weights = solution.weights
    else:
        warnings.append("편입 가능한 후보가 0개 — 포트폴리오를 만들지 않았다")

    # --- 사다리·스탑·TP
    positions = tuple(
        build_position_plan(
            p, inputs.theses[p.theme], target_weight=weights.get(p.ticker, 0.0), asof=asof
        )
        for p in picks
    )
    gross = sum(weights.values())
    # 앵커 비중은 **라벨이 있을 때만** 낸다. L4 가 `eligible` 만 내는 오늘, 라벨이 하나도 없으면
    # 0.0 은 "앵커에 0 을 배분했다" 가 아니라 "L4 가 라벨을 안 붙였다" 다 — 계획서가 그 둘을
    # 섞어 `앵커 : 토크 = 0 : 100` 으로 단언하면 바벨 붕괴로 읽힌다.
    held = [p for p in picks if weights.get(p.ticker, 0.0) > 0]
    anchor_labeled = any(p.barbell_labeled for p in held)
    anchor_share: float | None = None
    if gross > 0 and anchor_labeled:
        anchor_share = sum(weights.get(p.ticker, 0.0) for p in picks if p.is_anchor) / gross
    if gross > 0 and not anchor_labeled:
        warnings.append(
            "앵커:토크 비율 없음 — L4 가 바벨 라벨을 붙이지 않는다 (role 이 전부 `eligible`, "
            "docs/06 §8.4). 앵커 비중을 0 으로 **정한** 것이 아니라 **재지 못한** 것이다"
        )

    # --- 테마 행
    rows = _theme_rows(
        inputs,
        cand_themes,
        picks,
        by_id=by_id,
        c_tilde=c_tilde,
        excl_reason=excl_reason,
        losses=losses,
        weights=weights,
        warnings=warnings,
    )
    n_axis1 = sum(1 for th in themes if th.axis1_declared)
    return PortfolioResult(
        asof=asof,
        inputs_dir=inputs_dir,
        theme_rows=rows,
        positions=positions,
        solution=solution,
        cov=cov,
        enb=enb,
        lam=LAMBDA_COMPRESS,
        mu_method=MU_METHOD,
        mdd_budget=MDD_BUDGET,
        k=MDD_K,
        anchor_share=anchor_share,
        warnings=tuple(warnings),
        axis1_universe=(n_axis1, len(themes)),
        extra={
            "cluster_caps": dict(inputs.cluster_caps),
            "capital_usd": inputs.capital_usd,
            "c4_applied": inputs.capital_usd is not None,
            "anchor_labeled": anchor_labeled,
            "filled_gap_days": gaps,
            "tier2_budget": {
                "theme_cap": THEME_CAP_FOR_LOSS,
                "tier2_from_avg": TIER2_FROM_AVG,
                "loss_contribution": THEME_CAP_FOR_LOSS * TIER2_FROM_AVG,
                "mdd_budget": MDD_BUDGET,
                "share_of_budget": THEME_CAP_FOR_LOSS * TIER2_FROM_AVG / MDD_BUDGET,
            },
        },
    )


# ---------------------------------------------------------------- 파일 I/O


def write_outputs(res: PortfolioResult, out_dir: Path) -> PortfolioResult:
    from msa.l5.plan import render_plan

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "weights.csv").open("w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(
            [
                "ticker",
                "theme",
                "role",
                "target_weight",
                "leg1_weight",
                "leg2_weight",
                "leg3_weight",
                "entry_price",
                "leg2_price",
                "leg3_price",
                # Tier-2 는 **유효 스탑** 한 짝으로 쓴다 — 가격·하락률·규칙이 같은 규칙을
                # 가리킨다 (`docs/07` §4 "둘 중 먼저 오는 쪽"). 진 규칙은 diagnostics 에 있다.
                "tier2_price",
                "tier2_vs_initial",
                "tier2_rule",
                "time_stop",
            ]
        )
        for p in res.positions:
            wr.writerow(
                [
                    p.ticker,
                    p.theme,
                    p.role,
                    f"{p.target_weight:.6f}",
                    f"{p.leg_weights[0]:.6f}",
                    f"{p.leg_weights[1]:.6f}",
                    f"{p.leg_weights[2]:.6f}",
                    "" if p.entry_price is None else f"{p.entry_price:.4f}",
                    "" if p.leg_prices[1] is None else f"{p.leg_prices[1]:.4f}",
                    "" if p.leg_prices[2] is None else f"{p.leg_prices[2]:.4f}",
                    "" if p.tier2_effective_price is None else f"{p.tier2_effective_price:.4f}",
                    f"{p.tier2_effective_vs_initial:.4f}",
                    p.tier2_rule,
                    str(p.time_stop),
                ]
            )
    write_snapshot(
        out_dir, texts={"plan.md": render_plan(res)}, jsons={"diagnostics.json": res.diagnostics()}
    )
    return replace(res, out_dir=out_dir)


def run_portfolio(
    *,
    asof: str | None,
    inputs_dir: Path | str,
    cases_path: Path | str | None = None,
    capital_usd: float | None = None,
    cluster_caps: Mapping[str, float] | None = None,
    write: bool = True,
    cache_dir: Path | str | None = None,
    themes_path: Path | str | None = None,
    state_dir: Path | str | None = None,
    emit_positions: bool = False,
) -> PortfolioResult:
    """CLI 진입점. 캐시의 테마 EW 수익률을 읽고, `<inputs>/returns.csv` 가 있으면 종목 공분산에
    쓴다. `emit_positions` 면 산출 디렉터리에 `positions-proposal.yaml` 도 남긴다 (`write` 일 때만 —
    `state/positions.yaml` 은 건드리지 않는다). 제안 행의 `thesis_snapshot` 은 묶음이 적어 둔
    `<inputs>/assemble_report.json` 의 `sources[테마].thesis` 로 채운다 — 기계가 아는 값을 사람
    몫으로 넘기지 않는다. `journal_entry` 는 진입 저널 항목이라 사람 몫으로 남는다."""
    p = paths()
    out_root = replace(p, state=Path(state_dir)).portfolio if state_dir is not None else p.portfolio
    d = Path(inputs_dir)
    cases = Path(cases_path) if cases_path is not None else p.cases
    inputs = load_inputs(d, cases_path=cases, capital_usd=capital_usd, cluster_caps=cluster_caps)
    themes = load_themes(themes_path)
    cdir = Path(cache_dir) if cache_dir is not None else p.cache
    daily = load_theme_ew_returns(cdir, inputs.themes())
    returns: pd.DataFrame | None = None
    rp = d / "returns.csv"
    if rp.exists():
        returns = pd.read_csv(rp, index_col=0, parse_dates=True).sort_index()
        returns.columns = [str(c).upper() for c in returns.columns]
    res = build_portfolio(
        inputs,
        asof=asof_or_today(asof),
        themes=themes,
        daily_ew=daily,
        stock_returns=returns,
        inputs_dir=str(d),
    )
    if write:
        res = write_outputs(res, out_root / str(res.asof))
        if emit_positions:
            from msa.l5.positions import emit_positions_proposal

            assert res.out_dir is not None
            emit_positions_proposal(res, res.out_dir, thesis_snapshots=_thesis_paths(d))
    elif emit_positions:
        raise ValueError(
            "emit_positions 는 write=True 일 때만 — 제안은 파일로만 낸다 (--no-write 와 양립 불가)"
        )
    return res


def _thesis_paths(inputs_dir: Path) -> dict[str, str]:
    """`<inputs>/assemble_report.json` 의 `sources[<theme>].thesis` → 테마별 thesis 경로.

    묶음(`pipeline/assemble`)은 어느 thesis 로 이 입력을 만들었는지 이미 안다 — 제안 행의
    `thesis_snapshot` 을 "사람이 채울 것" 으로 남기지 않고 그 값을 넣는다. 파일이 없거나 모양이
    다르면 빈 dict 를 돌려준다(옛 묶음·수동 입력) — 그때는 종전대로 사람이 채운다.
    """
    f = Path(inputs_dir) / "assemble_report.json"
    if not f.exists():
        return {}
    try:
        rep = json.loads(f.read_text(encoding="utf-8"))
        src = rep.get("sources") or {}
    except (OSError, ValueError) as e:
        log.warning("l5: %s 를 읽지 못해 thesis_snapshot 을 채우지 못했다 — %s", f, e)
        return {}
    out: dict[str, str] = {}
    for theme, meta in src.items():
        path = (meta or {}).get("thesis") if isinstance(meta, dict) else None
        if path:
            out[str(theme)] = str(path)
    return out


def cluster_caps_from_args(raw: Sequence[str]) -> dict[str, float]:
    """`--cluster-cap precious_metals=0.35` 형식을 파싱한다."""
    out: dict[str, float] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"--cluster-cap 형식은 name=cap: {item!r}")
        name, cap = item.split("=", 1)
        v = float(cap)
        if not 0.0 < v <= 1.0:
            raise ValueError(f"--cluster-cap {name}: 상한은 (0,1]: {v}")
        out[name.strip()] = v
    return out
