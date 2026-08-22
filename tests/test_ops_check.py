"""`msa check` 로직 — 합성 가격으로 스탑·사다리·시간스탑·TP·무효화."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from conftest import make_thesis
from msa.ops.alerts import AlertKind
from msa.ops.check import DictPriceSource, check_position, run_check
from msa.ops.state_files import LadderStep, Position, PositionsFile, TpLevel, save_positions


def _series(closes: list[float], end: date) -> pd.Series:
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=len(closes))
    return pd.Series(closes, index=idx, dtype=float)


def _pos(**over: object) -> Position:
    kw: dict[str, object] = {
        "ticker": "CCJ",
        "theme": "uranium",
        "role": "anchor",
        "target_weight": 0.16,
        "opened_at": date(2026, 9, 1),
        "entry_price": 50.0,
        "ladder": [
            LadderStep(1, 0.5, 0.0, 50.0, date(2026, 9, 1), 50.0),
            LadderStep(2, 0.3, 0.13, 43.5),
            LadderStep(3, 0.2, 0.23, 38.5),
        ],
        "tier2_stop_price": 32.5,  # 평단 50 × 0.65
        "time_stop_date": date(2028, 3, 1),
        "horizon_months": (6, 18),
        "thesis_snapshot": "journal/2026-09-01-uranium-entry.thesis.yaml",
        "journal_entry": "journal/2026-09-01-uranium-entry.md",
        "tp": [
            TpLevel("tp1", 1 / 3, "P50 또는 +2R", price=85.0),
            TpLevel("tp2", 1 / 3, "P75 또는 고점 50%"),
            TpLevel("runner", 1 / 3, "트레일 −25% / 10주선"),
        ],
    }
    kw.update(over)
    return Position(**kw)  # type: ignore[arg-type]


ASOF = date(2026, 12, 15)


def _prices(ccj: list[float], ura: list[float]) -> DictPriceSource:
    return DictPriceSource({"CCJ": _series(ccj, ASOF), "URA": _series(ura, ASOF)})


def test_manual_conditions_listed_and_machine_ones_evaluated() -> None:
    pc = check_position(_pos(), make_thesis(), {}, _prices([50.0] * 60, [30.0] * 60), ASOF)
    by = {c.observable: c for c in pc.conditions}
    assert by["Cameco 가이던스 상향"].status == "manual"
    assert (
        by["URA 종가 > 40 (5일 연속)"].status == "pending"
        and by["URA 종가 > 40 (5일 연속)"].machine
    )
    assert by["URA 종가 < 20 (3일 연속)"].status == "pending"
    assert pc.manual_count == 3 and pc.triggers_met == 0 and pc.invalidations_fired == 0
    assert pc.alerts == []


def test_ladder_step2_needs_price_and_thesis_together() -> None:
    # 가격만 충족 (−13.2%), 트리거 0 → 알림 없음
    pc = check_position(_pos(), make_thesis(), {}, _prices([43.4] * 60, [30.0] * 60), ASOF)
    l2 = next(ls for ls in pc.ladder if ls.step == 2)
    assert l2.price_met and not l2.thesis_met and not l2.both
    assert not any(a.kind is AlertKind.LADDER_STEP_MET for a in pc.alerts)
    # 트리거 1개가 기계로 충족 (URA > 40 5일) → 둘 다 충족 → 알림
    pc = check_position(_pos(), make_thesis(), {}, _prices([43.4] * 60, [41.0] * 60), ASOF)
    l2 = next(ls for ls in pc.ladder if ls.step == 2)
    assert pc.triggers_met == 1 and l2.both
    al = [a for a in pc.alerts if a.kind is AlertKind.LADDER_STEP_MET]
    assert len(al) == 1 and "사다리 2단 조건 충족" in al[0].text and "트리거 1/3" in al[0].text
    # 3단은 2단 체결 전이면 논지 조건 미충족
    l3 = next(ls for ls in pc.ladder if ls.step == 3)
    assert not l3.thesis_met


def test_ladder_blocked_when_invalidation_fired_and_alert_emitted() -> None:
    # URA < 20 3일 → 무효화 발동. 가격 −13% 여도 사다리 논지 조건 실패
    pc = check_position(_pos(), make_thesis(), {}, _prices([43.0] * 60, [19.0] * 60), ASOF)
    assert pc.invalidations_fired == 1
    assert not any(ls.both for ls in pc.ladder)
    inv = [a for a in pc.alerts if a.kind is AlertKind.INVALIDATION_FIRED]
    assert len(inv) == 1 and "무효화 발동" in inv[0].text and "exit" in inv[0].text


def test_prior_fired_status_is_kept_and_not_realerted() -> None:
    prior = {("invalidation", "URA 종가 < 20 (3일 연속)"): "fired"}
    pc = check_position(_pos(), make_thesis(), prior, _prices([50.0] * 60, [30.0] * 60), ASOF)
    assert pc.invalidations_fired == 1
    assert not any(a.kind is AlertKind.INVALIDATION_FIRED for a in pc.alerts)


def test_tier2_stop_hit_and_breakeven_after_tp1() -> None:
    pc = check_position(_pos(), make_thesis(), {}, _prices([32.0] * 60, [30.0] * 60), ASOF)
    assert pc.tier2_hit and any(a.kind is AlertKind.TIER2_STOP_HIT for a in pc.alerts)
    # TP1 체결 후 → 스탑이 본전(평단)으로 올라간다
    pos = _pos()
    pos.tp[0].filled_price = 85.0
    pos.tp[0].filled_date = date(2026, 11, 1)
    pc = check_position(pos, make_thesis(), {}, _prices([49.0] * 60, [30.0] * 60), ASOF)
    assert pc.tier2_basis == "breakeven" and pc.tier2_stop_price == 50.0 and pc.tier2_hit


def test_tier2_consistency_warning_when_stop_not_avg_minus_35() -> None:
    pc = check_position(
        _pos(tier2_stop_price=40.0), make_thesis(), {}, _prices([50.0] * 60, [30.0] * 60), ASOF
    )
    assert any("평단 −35%" in p for p in pc.problems)


def test_time_stop_warning_30_days_before_only_when_no_trigger_met() -> None:
    pos = _pos(time_stop_date=date(2027, 1, 10))  # D+26
    pc = check_position(pos, make_thesis(), {}, _prices([50.0] * 60, [30.0] * 60), ASOF)
    assert pc.time_stop_warning and any(a.kind is AlertKind.TIME_STOP_WARNING for a in pc.alerts)
    # 트리거가 하나라도 충족되면 시간 스탑 비적용
    pc = check_position(pos, make_thesis(), {}, _prices([50.0] * 60, [41.0] * 60), ASOF)
    assert not pc.time_stop_warning
    # 경과 + 트리거 0 → due
    pc = check_position(
        _pos(time_stop_date=date(2026, 12, 1)),
        make_thesis(),
        {},
        _prices([50.0] * 60, [30.0] * 60),
        ASOF,
    )
    assert pc.time_stop_due


def test_tp_price_level_and_runner_trailing() -> None:
    pc = check_position(_pos(), make_thesis(), {}, _prices([86.0] * 60, [30.0] * 60), ASOF)
    tp1 = next(t for t in pc.tp if t.level == "tp1")
    assert tp1.met and any(a.kind is AlertKind.TP_MET for a in pc.alerts)
    tp2 = next(t for t in pc.tp if t.level == "tp2")
    assert not tp2.machine  # 밸류 백분위 → manual
    # 러너: TP2 체결 후 고점 대비 −25% 이탈
    pos = _pos()
    for t in pos.tp[:2]:
        t.filled_price, t.filled_date = 90.0, date(2026, 11, 1)
    closes = list(np.linspace(50, 100, 40)) + [74.0] * 20  # 고점 100 → 74 (−26%)
    pc = check_position(pos, make_thesis(), {}, _prices(closes, [30.0] * 60), ASOF)
    runner = next(t for t in pc.tp if t.level == "runner")
    assert runner.met and "고점" in runner.detail


def test_missing_prices_is_reported_not_silent() -> None:
    pc = check_position(_pos(), make_thesis(), {}, DictPriceSource({}), ASOF)
    assert pc.close is None and any("가격이 없다" in p for p in pc.problems)
    assert not pc.tier2_hit


def test_run_check_writes_report_alerts_and_journal_draft(tmp_path: Path) -> None:
    repo = tmp_path
    jdir = repo / "journal"
    jdir.mkdir()
    (jdir / "2026-09-01-uranium-entry.thesis.yaml").write_text(yaml.safe_dump(make_thesis()))
    ppath = repo / "state" / "positions.yaml"
    save_positions(ppath, PositionsFile(ASOF, [_pos(), _pos(ticker="UEC", role="torque")]))
    rep = run_check(
        asof=ASOF,
        mode="daily",
        prices=DictPriceSource(
            {
                "CCJ": _series([43.0] * 60, ASOF),
                "UEC": _series([43.0] * 60, ASOF),
                "URA": _series([41.0] * 60, ASOF),
            }
        ),
        positions_path=ppath,
        journal_dir=jdir,
        repo_root=repo,
        out_root=repo / "state" / "checks",
    )
    assert rep.out_dir is not None
    assert (rep.out_dir / "report.txt").exists()
    text = (rep.out_dir / "report.txt").read_text()
    assert "주문은 내지 않으며" in text and "CCJ" in text and "UEC" in text
    draft = yaml.safe_load((rep.out_dir / "journal-draft-uranium.yaml").read_text())
    assert draft["type"] == "check" and len(draft["trigger_status"]) == 3
    assert len(rep.alerts) == 2  # 두 종목 모두 사다리 2단 충족


def test_run_check_reports_missing_snapshot(tmp_path: Path) -> None:
    ppath = tmp_path / "positions.yaml"
    save_positions(ppath, PositionsFile(ASOF, [_pos()]))
    rep = run_check(
        asof=ASOF,
        mode="weekly",
        prices=_prices([50.0] * 60, [30.0] * 60),
        positions_path=ppath,
        journal_dir=tmp_path / "journal",
        repo_root=tmp_path,
        out_root=None,
    )
    assert rep.positions == [] and any("스냅샷 없음" in p for p in rep.problems)
