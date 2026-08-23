"""L5 계획 → `positions-proposal.yaml` (W2 배선) — 합성 테스트.

- 계획 → `Position` 필드 사상 (사다리·Tier-2·시간스탑·TP·status=proposed)
- YAML 왕복 (`load_positions`) · `msa check` 가 제안 행을 점검하지 않고 목록만 적는다
- `state/positions.yaml` 은 절대 쓰지 않는다 · entry_price 없으면 거부
- `run_portfolio(emit_positions=True)` 훅 · CLI `--emit-positions` 옵션
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from _synth_ops import make_position, series
from msa.cli import app
from msa.l5 import ladders
from msa.l5.inputs import Pick, load_inputs
from msa.l5.ladders import build_position_plan
from msa.l5.positions import (
    PROPOSAL_MD,
    PROPOSAL_YAML,
    ProposalError,
    emit_positions_proposal,
    position_from_plan,
    proposal_from_portfolio,
    write_positions_proposal,
)
from msa.l5.run import PortfolioResult, build_portfolio, run_portfolio
from msa.ops.check import DictPriceSource, run_check
from msa.ops.state_files import StateFileError, load_positions, save_positions
from msa.themes import load_themes
from test_l5_portfolio import ASOF, REPO, _synthetic_daily_ew, _thesis, _write_inputs

# ---------------------------------------------------------------- 도우미


def _toy_result(*plans: ladders.PositionPlan, asof: date = ASOF) -> PortfolioResult:
    """솔버 없이 `PositionPlan` 만 든 최소 `PortfolioResult` — 제안 변환만 본다."""
    return PortfolioResult(
        asof=asof,
        inputs_dir="toy",
        theme_rows=(),
        positions=tuple(plans),
        solution=None,
        cov=None,
        enb=None,
        lam=0.3,
        mu_method="(a) 균등",
        mdd_budget=0.30,
        k=2.2,
        anchor_share=None,
        warnings=(),
        axis1_universe=(0, 0),
    )


def _plan(
    ticker: str = "CCJ",
    role: str = "anchor",
    *,
    c: float = 0.72,
    w: float = 0.16,
    entry: float | None = 100.0,
    **pick_over: object,
) -> ladders.PositionPlan:
    pick = Pick(theme="uranium", ticker=ticker, role=role, entry_price=entry, **pick_over)  # type: ignore[arg-type]
    return build_position_plan(pick, _thesis("uranium", c), target_weight=w, asof=ASOF)


# ---------------------------------------------------------------- 사상


def test_position_from_plan_maps_declared_values() -> None:
    """사다리 비율·발동가·Tier-2·시간스탑·TP 가 L5 선언값 그대로 옮겨지고 status 는 proposed."""
    pp = _plan(prev_cycle_peak_price=300.0, tp_p50_price=150.0)
    pos = position_from_plan(pp, asof=ASOF)
    assert pos.status == "proposed" and pos.opened_at == ASOF
    assert pos.ticker == "CCJ" and pos.theme == "uranium" and pos.role == "anchor"
    assert pos.target_weight == pytest.approx(0.16) and pos.entry_price == 100.0
    # 사다리: c=0.72 → 50/30/20 · 발동 0/−13%/−23% · 가격 100/87/77 · 체결 없음
    assert [s.step for s in pos.ladder] == [1, 2, 3]
    assert [s.weight for s in pos.ladder] == pytest.approx(list(ladders.LADDER_MID))
    assert [s.trigger_pct for s in pos.ladder] == pytest.approx(
        [0.0, ladders.ADD2_DRAWDOWN, ladders.ADD3_DRAWDOWN]
    )
    assert [s.trigger_price for s in pos.ladder] == pytest.approx([100.0, 87.0, 77.0])
    assert not any(s.filled for s in pos.ladder)
    # Tier-2: 1단만 체결된 시점의 평단(=진입가) −35% — check.py 의 대조 규칙과 일치
    assert pos.tier2_stop_price == pytest.approx(65.0) and pos.tier2_basis == "avg_minus_35"
    # 완납 시 값(초기가 −40.5%)은 note 에 남는다
    assert "완납 시 Tier-2 = 59.48" in pos.note and "-40.5%" in pos.note
    # 시간 스탑 = asof + 18M
    assert pos.time_stop_date == date(2028, 2, 22) and pos.horizon_months == (6, 18)
    # TP: +2R=181.05 vs P50=150 → "또는" 이므로 먼저 오는 150 · TP2 고점 50% 회복 = 200
    tp = {t.level: t for t in pos.tp}
    assert tp["tp1"].price == pytest.approx(150.0) and "+2R = 181.05" in tp["tp1"].condition
    assert tp["tp2"].price == pytest.approx(200.0)
    assert tp["runner"].price is None and "10주선" in tp["runner"].condition
    assert all(t.fraction == pytest.approx(1 / 3) for t in pos.tp)
    assert pos.runner_trail_pct == ladders.RUNNER_TRAIL
    assert pos.runner_ma_weeks == ladders.RUNNER_MA_WEEKS
    # 저널 링크는 모른다 → None + note 가 채울 것을 적는다 · Tier-1 문구도 옮긴다
    assert pos.thesis_snapshot is None and pos.journal_entry is None
    assert "thesis_snapshot, journal_entry" in pos.note
    assert "카자흐 쿼터" in pos.note


def test_tp2_manual_when_no_inputs_and_role_mapping() -> None:
    """P75·직전 고점 둘 다 없으면 TP2 는 가격 없음(manual). royalty→anchor · etf→torque."""
    pos = position_from_plan(_plan("FNV", "royalty"), asof=ASOF)
    assert pos.role == "anchor" and "원 role royalty → anchor" in pos.note
    assert {t.level: t.price for t in pos.tp}["tp2"] is None
    etf = position_from_plan(_plan("URA", "etf", w=0.10), asof=ASOF)
    assert etf.role == "torque" and "원 role etf → torque" in etf.note
    plain = position_from_plan(_plan("UEC", "torque", w=0.10), asof=ASOF)
    assert "원 role" not in plain.note


def test_missing_entry_price_is_refused_not_defaulted() -> None:
    with pytest.raises(ProposalError, match="entry_price"):
        position_from_plan(_plan(entry=None), asof=ASOF)
    res = _toy_result(_plan("CCJ"), _plan("UEC", "torque", entry=None, w=0.1))
    with pytest.raises(ProposalError, match=r"\['UEC'\]"):
        proposal_from_portfolio(res)


def test_proposal_skips_zero_weight_and_links_journal() -> None:
    res = _toy_result(_plan("CCJ"), _plan("UEC", "torque", w=0.0))
    pf = proposal_from_portfolio(
        res,
        thesis_snapshots={"uranium": Path("journal/2026-08-22-uranium-entry.thesis.yaml")},
        journal_entries={"uranium": "journal/2026-08-22-uranium-entry.md"},
    )
    assert pf.asof == ASOF and [p.ticker for p in pf.positions] == ["CCJ"]
    p = pf.positions[0]
    assert p.thesis_snapshot == "journal/2026-08-22-uranium-entry.thesis.yaml"
    assert p.journal_entry == "journal/2026-08-22-uranium-entry.md"
    assert "채울 것" not in p.note and "1단 체결" in p.note


# ---------------------------------------------------------------- 파일 · 왕복 · check


def test_write_roundtrip_and_never_touches_positions_yaml(tmp_path: Path) -> None:
    state = tmp_path / "state"
    real = state / "positions.yaml"
    save_positions(real, load_positions(real))  # 빈 실제 파일
    before = real.read_text(encoding="utf-8")
    out = state / "portfolio" / str(ASOF)
    pf = proposal_from_portfolio(_toy_result(_plan("CCJ"), _plan("UEC", "torque", w=0.1)))
    path = write_positions_proposal(pf, out)
    assert path == out / PROPOSAL_YAML and (out / PROPOSAL_MD).exists()
    # 같은 모양 — load_positions 로 읽히고 proposed 로 돌아온다
    back = load_positions(path)
    assert [p.status for p in back.positions] == ["proposed", "proposed"]
    assert back.open_positions() == [] and len(back.proposed_positions()) == 2
    b = back.positions[0]
    assert b.ticker == "CCJ" and b.thesis_snapshot is None and b.journal_entry is None
    assert [s.trigger_price for s in b.ladder] == pytest.approx([100.0, 87.0, 77.0])
    assert b.tier2_stop_price == pytest.approx(65.0) and b.time_stop_date == date(2028, 2, 22)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert set(raw) == {"asof", "positions"} and raw["positions"][0]["status"] == "proposed"
    # 실제 포지션 파일은 그대로
    assert real.read_text(encoding="utf-8") == before
    # 체크리스트는 승격 절차와 §8 문구를 담는다
    md = (out / PROPOSAL_MD).read_text(encoding="utf-8")
    for must in ("status: proposed", "open", "thesis_snapshot", "msa journal new", "CLAUDE.md §8"):
        assert must in md, must
    # positions.yaml 이 있는 디렉터리에는 쓰지 않는다 (구조적 방어)
    with pytest.raises(ProposalError, match=r"positions\.yaml"):
        write_positions_proposal(pf, state)


def test_open_row_without_journal_links_is_refused() -> None:
    """`proposed` 만 저널 링크를 비울 수 있다 — open 은 그대로 거부."""
    raw = {
        "ticker": "CCJ",
        "theme": "uranium",
        "role": "anchor",
        "target_weight": 0.1,
        "opened_at": "2026-09-01",
        "entry_price": 50.0,
        "ladder": [{"step": 1, "weight": 1.0, "trigger_pct": 0.0}],
        "tier2_stop_price": 32.5,
        "time_stop_date": "2028-03-01",
        "horizon_months": [6, 18],
        "status": "open",
    }
    from msa.ops.state_files import position_from_dict

    with pytest.raises(StateFileError, match="thesis_snapshot"):
        position_from_dict(raw)
    ok = position_from_dict({**raw, "status": "proposed"})
    assert ok.status == "proposed" and ok.thesis_snapshot is None


def test_check_lists_proposed_rows_as_unchecked(tmp_path: Path) -> None:
    """제안 파일을 `msa check` 에 주면 — 로드되고, 제안 행은 점검 없이 '미체결 제안' 으로만."""
    out = tmp_path / "state" / "portfolio" / str(ASOF)
    pf = proposal_from_portfolio(_toy_result(_plan("CCJ")))
    path = write_positions_proposal(pf, out)
    rep = run_check(
        asof=ASOF,
        mode="weekly",
        prices=DictPriceSource({"CCJ": series([40.0] * 60, ASOF)}),  # 스탑 아래 가격이어도
        positions_path=path,
        journal_dir=tmp_path / "journal",
        repo_root=tmp_path,
        out_root=tmp_path / "state" / "checks",
    )
    assert rep.positions == [] and rep.alerts == [] and rep.problems == []
    assert rep.unchecked == ["CCJ (uranium)"]
    text = rep.render()
    assert "미체결 제안 1건" in text and "점검하지 않았다" in text and "CCJ" in text
    assert (rep.out_dir / "report.txt").read_text(encoding="utf-8") == text  # type: ignore[union-attr]


def test_check_mixed_file_checks_open_and_lists_proposed(tmp_path: Path) -> None:
    """사람이 제안 행을 positions.yaml 에 합쳐 두고 아직 승격하지 않은 상태."""
    from conftest import make_thesis
    from msa.io import yaml_text
    from msa.ops.state_files import PositionsFile

    jdir = tmp_path / "journal"
    jdir.mkdir()
    (jdir / "2026-09-01-uranium-entry.thesis.yaml").write_text(yaml_text(make_thesis()))
    prop = position_from_plan(_plan("UEC", "torque", w=0.1), asof=ASOF)
    ppath = tmp_path / "state" / "positions.yaml"
    save_positions(ppath, PositionsFile(date(2026, 12, 15), [make_position(), prop]))
    rep = run_check(
        asof=date(2026, 12, 15),
        mode="weekly",
        prices=DictPriceSource(
            {
                "CCJ": series([50.0] * 60),
                "URA": series([30.0] * 60),
                "UEC": series([1.0] * 60),
            }
        ),
        positions_path=ppath,
        journal_dir=jdir,
        repo_root=tmp_path,
        out_root=None,
    )
    assert [pc.ticker for pc in rep.positions] == ["CCJ"]
    assert rep.unchecked == ["UEC (uranium)"]
    assert not any(a.ticker == "UEC" for a in rep.alerts)  # 가격 1.0 이어도 스탑 알림 없음


# ---------------------------------------------------------------- 훅 · CLI


@pytest.fixture(scope="module")
def daily_ew() -> pd.DataFrame:
    return _synthetic_daily_ew(["uranium", "grid_equipment", "coal"])


def test_emit_from_real_build_portfolio(tmp_path: Path, daily_ew: pd.DataFrame) -> None:
    """end-to-end 결과(가중치 > 0 인 4종목)에서 제안 4행 — 비중·가격이 계획과 같다."""
    _write_inputs(tmp_path)
    inputs = load_inputs(tmp_path, cases_path=None)
    res = build_portfolio(
        inputs,
        asof=ASOF,
        themes=load_themes(REPO / "state" / "themes.yaml"),
        daily_ew=daily_ew,
        inputs_dir=str(tmp_path),
    )
    assert res.solution is not None
    out = tmp_path / "out"
    path = emit_positions_proposal(res, out)
    back = load_positions(path)
    by = {p.ticker: p for p in back.positions}
    assert set(by) == {"CCJ", "UEC", "PWR", "GEV"}
    plans = {p.ticker: p for p in res.positions}
    for t, pos in by.items():
        assert pos.target_weight == pytest.approx(plans[t].target_weight)
        assert pos.entry_price == plans[t].entry_price
        assert pos.time_stop_date == plans[t].time_stop
        assert pos.status == "proposed"


def test_run_portfolio_emit_hook(
    tmp_path: Path, daily_ew: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    import msa.l5.run as run_mod

    monkeypatch.setattr(run_mod, "load_theme_ew_returns", lambda *_a, **_k: daily_ew)
    inputs = tmp_path / "inputs"
    _write_inputs(inputs)
    state = tmp_path / "state"
    res = run_portfolio(
        asof=str(ASOF),
        inputs_dir=inputs,
        cases_path=tmp_path / "nope.yaml",
        state_dir=state,
        emit_positions=True,
    )
    assert res.out_dir == state / "portfolio" / str(ASOF)
    assert (res.out_dir / PROPOSAL_YAML).exists() and (res.out_dir / PROPOSAL_MD).exists()
    assert not (state / "positions.yaml").exists()  # 실제 포지션 파일은 만들지도 않는다
    # write=False 와는 양립 불가 — 조용히 무시하지 않는다
    with pytest.raises(ValueError, match="emit_positions"):
        run_portfolio(
            asof=str(ASOF),
            inputs_dir=inputs,
            cases_path=tmp_path / "nope.yaml",
            state_dir=state,
            write=False,
            emit_positions=True,
        )
    # 기본(emit 없음)은 제안을 쓰지 않는다
    res2 = run_portfolio(
        asof="2026-08-23", inputs_dir=inputs, cases_path=tmp_path / "nope.yaml", state_dir=state
    )
    assert res2.out_dir is not None and not (res2.out_dir / PROPOSAL_YAML).exists()


def test_cli_emit_positions_option() -> None:
    r = CliRunner().invoke(app, ["portfolio", "--help"])
    assert r.exit_code == 0 and "--emit-positions" in r.output
    r = CliRunner().invoke(
        app, ["portfolio", "--inputs", "/nonexistent", "--no-write", "--emit-positions"]
    )
    assert r.exit_code != 0 and "--no-write" in r.output


def test_replace_keeps_proposal_pure() -> None:
    """`PortfolioResult` 는 frozen — 제안 생성이 결과를 바꾸지 않는다."""
    res = _toy_result(_plan("CCJ"))
    before = res.positions
    proposal_from_portfolio(res)
    assert res.positions is before and replace(res).positions == before
