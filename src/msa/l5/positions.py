"""L5 매매계획 → `positions.yaml` **제안** (`msa portfolio --emit-positions`).

`PortfolioResult.positions` (`ladders.PositionPlan`) 를 `msa check` 가 읽는 모양
(`ops.state_files.Position`) 으로 옮겨 `state/portfolio/<asof>/positions-proposal.yaml` 에 쓴다.
사람이 체결한 뒤 행을 `state/positions.yaml` 로 **직접 옮기고** `status: open` 으로 올린다 —
이 모듈은 `state/positions.yaml` 을 **절대 쓰지 않는다** (`CLAUDE.md` §6·§8: 주문도, 체결 반영도
사람의 일이다. 기계는 제안만 남긴다).

계획 → 포지션 필드 사상 (값은 전부 L5 가 이미 선언한 것 — 여기서 숫자를 새로 만들지 않는다):

| `Position` | 출처 (`PositionPlan` · `ladders` 상수) |
|---|---|
| `ticker`·`theme`·`target_weight` | 그대로. 비중 0 인 종목은 행을 만들지 않는다 |
| `role` | `anchor`/`royalty`/`midstream` → `anchor`, 그 외(`torque`·`etf`) → `torque` |
|  | (`Pick.is_anchor` 와 같은 묶음 — 원 role 은 `note` 에 적는다) |
| `opened_at` | `asof` (1단 진입 기준일) |
| `entry_price` | `entry_price` (= `picks.csv`). **없으면 거부** — 기본값을 넣지 않는다 |
| `ladder[]` | `weight` ← `ladder.fractions` · `trigger_pct` ← `(0, ADD2, ADD3)` · |
|  | `trigger_price` ← `leg_prices`. 체결 필드는 전부 비움 |
| `tier2_stop_price` | **두 규칙 중 먼저 오는 쪽** (`ladders.tier2_rules`) 을 1단만 체결된 |
|  | 시점에서 평가한 값 — 평단 = 진입가, 포지션 비중 = 목표비중 × 1단 비율. |
|  | 대개 평단 −35% 이고, 1단 비중이 0.2286 을 넘을 때만 자본 8% 규칙이 앞선다. |
|  | 완납 시 값(§4 표)은 `note` 에 남고 사다리가 채워질 때 사람이 갱신한다 |
| `tier2_basis` | 적용된 규칙 — `avg_minus_35` 또는 `capital_8pct` (`msa check` 가 같은 |
|  | 함수로 대조하므로 라벨과 가격이 어긋나지 않는다) |
| `time_stop_date`·`horizon_months` | `time_stop`·`horizon_months` (asof + 상한 개월, 07 §4) |
| `tp[]` | TP1 `min(+2R, P50)` · TP2 `min(P75, 고점 50% 회복)` · 러너(가격 없음) — |
|  | "또는" 조건이라 먼저 오는(낮은) 가격이 기계 조건. 둘 다 없으면 manual |
| `runner_trail_pct`·`runner_ma_weeks` | `RUNNER_TRAIL`·`RUNNER_MA_WEEKS` |
| `thesis_snapshot`·`journal_entry` | 호출자가 준 테마별 경로, 없으면 `None` — |
|  | `open` 으로 올릴 때 사람이 채운다 (`msa journal new` 진입 항목) |
| `status` | `proposed` |

Tier-1(논지 스탑)은 가격이 아니다 — thesis 스냅샷의 `invalidations` 를 `msa check` 가 읽는다.
제안 행은 스냅샷이 없으므로 `note` 에 무효화 문구만 옮겨 적어 사람이 대조하게 한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from msa.errors import RefusedInput
from msa.io import dump_yaml
from msa.l5.ladders import (
    ADD2_DRAWDOWN,
    ADD3_DRAWDOWN,
    RUNNER_MA_WEEKS,
    RUNNER_TRAIL,
    TIER2_RULE_AVG,
    TIER2_RULE_CAPITAL,
    PositionPlan,
    tier2_rules,
)
from msa.ops.state_files import LadderStep, Position, PositionsFile, Role, Tier2Basis, TpLevel

if TYPE_CHECKING:
    from msa.l5.run import PortfolioResult

PROPOSAL_YAML = "positions-proposal.yaml"
PROPOSAL_MD = "positions-proposal.md"
#: TP 3단 물량 — `docs/07` §5 "1/3 씩" (`state_files._tp_from` 의 기본값과 같다).
TP_FRACTION = 1.0 / 3.0
#: Tier-2 규칙 이름 → `positions.yaml` 의 `tier2_basis` 값. 라벨이 실제 적용 규칙을 가리킨다.
_BASIS: dict[str, Tier2Basis] = {
    TIER2_RULE_AVG: "avg_minus_35",
    TIER2_RULE_CAPITAL: "capital_8pct",
}
#: `PositionPlan.role` → `Position.role` (anchor | torque). `Pick.is_anchor` 와 같은 묶음이다.
_ANCHOR_ROLES: frozenset[str] = frozenset({"anchor", "royalty", "midstream"})


class ProposalError(RefusedInput, ValueError):
    """제안을 만들 수 없다 — 조용히 기본값을 넣지 않는다 (`CLAUDE.md` §2)."""


def _role(plan_role: str) -> Role:
    return "anchor" if plan_role in _ANCHOR_ROLES else "torque"


def _min_price(*xs: float | None) -> float | None:
    vals = [x for x in xs if x is not None]
    return min(vals) if vals else None


def _tp_levels(p: PositionPlan) -> list[TpLevel]:
    """07 §5 의 세 단계. 가격 조건은 "또는" 이므로 먼저 오는(낮은) 쪽을 기계 조건으로 둔다."""
    tp1_cond = f"밸류 P50 회복 또는 +2R (+2R = {p.tp1_price:.2f}" if p.tp1_price is not None else ""
    if p.tp1_p50_price is not None:
        tp1_cond += f", P50 = {p.tp1_p50_price:.2f}"
    tp1_cond = (tp1_cond + ")") if tp1_cond else "밸류 P50 회복 또는 +2R"
    tp2_parts = []
    if p.tp2_p75_price is not None:
        tp2_parts.append(f"P75 = {p.tp2_p75_price:.2f}")
    if p.tp2_r_price is not None:
        tp2_parts.append(f"고점 50% 회복 = {p.tp2_r_price:.2f}")
    tp2_cond = "P75 또는 직전 고점 50% 회복" + (f" ({', '.join(tp2_parts)})" if tp2_parts else "")
    return [
        TpLevel("tp1", TP_FRACTION, tp1_cond, price=_min_price(p.tp1_price, p.tp1_p50_price)),
        TpLevel("tp2", TP_FRACTION, tp2_cond, price=_min_price(p.tp2_p75_price, p.tp2_r_price)),
        TpLevel(
            "runner",
            TP_FRACTION,
            f"{RUNNER_MA_WEEKS}주선 이탈 또는 고점 −{RUNNER_TRAIL:.0%}",
        ),
    ]


def _note(p: PositionPlan, *, has_snapshot: bool, has_journal: bool) -> str:
    """사람이 `open` 으로 올리기 전에 채워야 할 것과, 계획서의 맥락(완납 Tier-2·원 role·Tier-1)."""
    todo: list[str] = []
    if not has_snapshot:
        todo.append("thesis_snapshot")
    if not has_journal:
        todo.append("journal_entry")
    parts = [
        "L5 제안(미체결). 집행은 사람이 한다 (CLAUDE.md §8).",
        (
            f"open 으로 올리기 전에 채울 것: {', '.join(todo)} (msa journal new 진입 항목 → 경로)"
            if todo
            else "open 으로 올리기 전에 1단 체결(filled_*) 을 적는다"
        ),
    ]
    if p.tier2_effective_price is not None:
        parts.append(
            f"완납 시 Tier-2 = {p.tier2_effective_price:.2f} "
            f"(초기가 {p.tier2_effective_vs_initial:+.1%}, 규칙 {p.tier2_rule}) — 사다리가 "
            "채워질 때마다 tier2_stop_price 를 두 규칙(평단 −35% · 포지션 손실 = 총자본 8%) 중 "
            "먼저 오는 쪽으로 갱신한다"
        )
    if _role(p.role) != p.role:
        parts.append(
            f"원 role {p.role} → {_role(p.role)} 로 사상 (positions 스키마는 anchor|torque)"
        )
    if p.split_first_leg:
        parts.append("1단은 25%+25% 분할 (M 축 낮음)")
    if p.tier1_invalidations:
        parts.append("Tier-1 무효화: " + " / ".join(p.tier1_invalidations))
    return " · ".join(parts)


def position_from_plan(
    p: PositionPlan,
    *,
    asof: date,
    thesis_snapshot: str | None = None,
    journal_entry: str | None = None,
) -> Position:
    """계획 한 건 → `status: proposed` 포지션 한 건. `entry_price` 가 없으면 거부."""
    e = p.entry_price
    if e is None or e <= 0:
        raise ProposalError(
            f"{p.ticker}: entry_price 가 없다 — picks.csv 에 entry_price 를 채우고 다시 돌려라. "
            "사다리·Tier-2·TP 가격 전부가 이 값에서 나오므로 기본값을 넣지 않는다"
        )
    f = p.ladder.fractions
    leg1_rules = tier2_rules(e, p.target_weight * f[0])
    ladder = [
        LadderStep(step=1, weight=f[0], trigger_pct=0.0, trigger_price=e),
        LadderStep(step=2, weight=f[1], trigger_pct=ADD2_DRAWDOWN, trigger_price=p.leg_prices[1]),
        LadderStep(step=3, weight=f[2], trigger_pct=ADD3_DRAWDOWN, trigger_price=p.leg_prices[2]),
    ]
    return Position(
        ticker=p.ticker,
        theme=p.theme,
        role=_role(p.role),
        target_weight=p.target_weight,
        opened_at=asof,
        entry_price=e,
        ladder=ladder,
        # 1단만 체결된 시점의 평단 = 진입가, 그 시점 포지션 비중 = 목표비중 × 1단 비율.
        # 두 규칙 중 **먼저 오는 쪽**을 그대로 옮긴다 (docs/07 §4) — `msa check` 는 같은 함수로
        # 대조한다. 자본 8% 규칙이 이기면 basis 가 `capital_8pct` 로 나가고, 사람이 오지목되지
        # 않는다.
        tier2_stop_price=leg1_rules.effective,
        tier2_basis=_BASIS[leg1_rules.rule],
        time_stop_date=p.time_stop,
        horizon_months=p.horizon_months,
        tp=_tp_levels(p),
        runner_trail_pct=RUNNER_TRAIL,
        runner_ma_weeks=RUNNER_MA_WEEKS,
        thesis_snapshot=thesis_snapshot,
        journal_entry=journal_entry,
        status="proposed",
        note=_note(p, has_snapshot=bool(thesis_snapshot), has_journal=bool(journal_entry)),
    )


def proposal_from_portfolio(
    result: PortfolioResult,
    *,
    asof: date | None = None,
    thesis_snapshots: Mapping[str, Path | str] | None = None,
    journal_entries: Mapping[str, Path | str] | None = None,
) -> PositionsFile:
    """비중 > 0 인 종목마다 `proposed` 행 하나. 한 종목이라도 `entry_price` 가 없으면 전체를
    거부한다 — 절반짜리 제안은 사람이 합칠 수 없다.

    `thesis_snapshots`·`journal_entries` 는 테마 → 저널 경로(상대). 모르면 None 으로 남고
    `note` 가 채울 것을 적는다.
    """
    d = asof or result.asof
    snaps = {k: str(v) for k, v in (thesis_snapshots or {}).items()}
    entries = {k: str(v) for k, v in (journal_entries or {}).items()}
    plans = [p for p in result.positions if p.target_weight > 0]
    missing = [p.ticker for p in plans if p.entry_price is None or p.entry_price <= 0]
    if missing:
        raise ProposalError(
            f"entry_price 없는 종목 {missing} — picks.csv 에 채우고 다시 돌려라 "
            "(positions 제안은 가격 없이 만들지 않는다)"
        )
    rows = [
        position_from_plan(
            p, asof=d, thesis_snapshot=snaps.get(p.theme), journal_entry=entries.get(p.theme)
        )
        for p in plans
    ]
    return PositionsFile(asof=d, positions=rows)


def _checklist(pf: PositionsFile, yaml_name: str) -> str:
    L = [
        f"# positions 제안 · {pf.asof} — 미체결 · 집행은 사람이 (CLAUDE.md §8)",
        "",
        f"`{yaml_name}` 은 `state/positions.yaml` 과 **같은 모양**이다. 이 파일은 제안이고, "
        "`state/positions.yaml` 은 사람이 체결을 반영해서 쓴다 — 기계는 그 파일을 건드리지 않는다.",
        "",
        "## 행",
        "",
        "| ticker | theme | role | 목표 | 진입가 | 2단 | 3단 | Tier-2 | 시간스탑 | TP1 | TP2 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in pf.positions:
        by = {s.step: s for s in p.ladder}
        tp = {t.level: t for t in p.tp}

        def px(x: float | None) -> str:
            return "—" if x is None else f"{x:.2f}"

        L.append(
            f"| {p.ticker} | {p.theme} | {p.role} | {p.target_weight:.1%} | {p.entry_price:.2f} "
            f"| {px(by[2].trigger_price)} | {px(by[3].trigger_price)} | {p.tier2_stop_price:.2f} "
            f"| {p.time_stop_date} | {px(tp['tp1'].price)} | {px(tp['tp2'].price)} |"
        )
    L += [
        "",
        "## 체결 전 확인할 것",
        "",
        "- [ ] 계획서(`plan.md`)의 경고란을 읽었다 — 완화 단계·C4 미적용·L_i 불가·축 1 불가",
        "- [ ] 각 행의 `note` 에 적힌 Tier-1 무효화가 thesis 와 같다 "
        "(논지가 죽으면 가격 무관 전량 청산)",
        "- [ ] `entry_price` 가 실제 체결 가능한 가격대다 (picks.csv 의 값 = 계획 기준가)",
        "- [ ] 2·3단은 **가격 AND 무효화 0건 AND 트리거 충족** 일 때만 — "
        "가격만 보고 물타지 않는다 (07 §3)",
        "- [ ] 시간 스탑 날짜를 달력에 적었다 (가장 자주 무시되고 가장 중요하다, 07 §4)",
        "",
        "## open 으로 올리는 절차 (사람)",
        "",
        "1. 진입 저널 항목을 만든다: `msa journal template entry` → 채움 → "
        "`msa journal new --from entry.yaml` "
        "(thesis 전문 포함 → `.thesis.yaml` 스냅샷이 옆에 생긴다)",
        "2. 이 파일의 행을 `state/positions.yaml` 의 `positions:` 아래에 **복사**한다 "
        "(덮어쓰기 아님)",
        "3. 복사한 행에서 `thesis_snapshot` · `journal_entry` 를 1 의 경로로 채운다 "
        "(비어 있으면 `open` 은 로드가 거부된다)",
        "4. 1단 체결을 적는다: `ladder[0].filled_date / filled_price / filled_shares`. "
        "체결가가 진입가와 다르면 `entry_price` 와 `tier2_stop_price`(평단 −35%) 도 고친다",
        "5. `status: proposed` → `open`. `note` 의 '채울 것' 문구는 지워도 된다",
        "6. `msa check --weekly` 로 로드·점검이 되는지 본다",
        "",
        "제안 행을 그대로 두면 `msa check` 는 '미체결 제안 — 점검하지 않았다' 로만 적는다.",
    ]
    return "\n".join(L) + "\n"


def write_positions_proposal(pf: PositionsFile, out_dir: Path | str) -> Path:
    """`<out_dir>/positions-proposal.yaml` (+ `.md` 체크리스트). `state/positions.yaml` 은 쓰지
    않는다."""
    d = Path(out_dir)
    if d.name == "state" or (d / "positions.yaml").exists():
        # 제안은 스냅샷 디렉터리(state/portfolio/<date>/)에만 둔다 — 실제 포지션 파일 옆에 두면
        # 사람이 헷갈려 덮어쓴다. 구조적으로 막는다.
        raise ProposalError(f"{d}: positions.yaml 이 있는 디렉터리에는 제안을 쓰지 않는다")
    path = dump_yaml(d / PROPOSAL_YAML, {"asof": pf.asof, "positions": pf.positions})
    (d / PROPOSAL_MD).write_text(_checklist(pf, PROPOSAL_YAML), encoding="utf-8")
    return path


def emit_positions_proposal(
    result: PortfolioResult,
    out_dir: Path | str,
    *,
    thesis_snapshots: Mapping[str, Path | str] | None = None,
    journal_entries: Mapping[str, Path | str] | None = None,
) -> Path:
    """`run_portfolio(..., emit_positions=True)` 의 훅 — 제안 생성 + 쓰기."""
    pf = proposal_from_portfolio(
        result, thesis_snapshots=thesis_snapshots, journal_entries=journal_entries
    )
    return write_positions_proposal(pf, out_dir)
