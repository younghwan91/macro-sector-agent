"""`msa check` 로직 — 합성 가격으로 스탑·사다리·시간스탑·TP·무효화."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from _synth_ops import ASOF
from _synth_ops import make_position as _pos
from _synth_ops import series as _series
from conftest import make_thesis
from msa.data.store import ShortRead
from msa.ops.alerts import AlertKind
from msa.ops.check import DictPriceSource, StorePriceSource, check_position, run_check
from msa.ops.state_files import PositionsFile, save_positions


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
    assert any("유효 Tier-2" in p and "avg−35%" in p for p in pc.problems)


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


class _FakeStore:
    """`Store.prices` 의 모양만 흉내낸다 — 질의 횟수와 요청 열을 기록한다."""

    def __init__(self, data: dict[str, pd.Series]) -> None:
        self.data = data
        self.calls: list[tuple[list[str], list[str] | None]] = []

    def prices(
        self,
        tickers: list[str],
        start: date,
        end: date,
        *,
        min_rows: int,
        expect_tickers: int | None = None,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        self.calls.append((list(tickers), None if columns is None else list(columns)))
        frames = [
            pd.DataFrame({"ticker": t, "date": s.index, "close": s.to_numpy()})
            for t in tickers
            if (s := self.data.get(t)) is not None
        ]
        if not frames:
            raise ShortRead("0 rows")
        return pd.concat(frames, ignore_index=True)


def test_store_price_source_prefetch_is_one_query_and_memoized() -> None:
    store = _FakeStore({"CCJ": _series([50.0] * 5, ASOF), "URA": _series([30.0] * 5, ASOF)})
    src = StorePriceSource(store)  # type: ignore[arg-type]
    src.prefetch(["ccj", "URA", "NOPE"], ASOF)
    assert len(store.calls) == 1 and store.calls[0] == (
        ["CCJ", "NOPE", "URA"],
        ["ticker", "date", "close"],
    )
    assert src.closes("CCJ", ASOF).iloc[-1] == 50.0 and src.closes("ura", ASOF).name == "URA"
    assert src.closes("NOPE", ASOF).empty
    assert len(store.calls) == 1  # 메모에서 — 재질의 없음
    # 선적재 밖(다른 end) 은 종목별로 읽는다 · 없는 종목은 빈 시리즈 (예외 아님)
    other = date(2026, 12, 1)
    assert src.closes("CCJ", other).iloc[-1] == 50.0 and len(store.calls) == 2
    assert src.closes("GONE", other).empty and len(store.calls) == 3


def test_run_check_prefetches_position_and_dsl_tickers(tmp_path: Path) -> None:
    jdir = tmp_path / "journal"
    jdir.mkdir()
    (jdir / "2026-09-01-uranium-entry.thesis.yaml").write_text(yaml.safe_dump(make_thesis()))
    ppath = tmp_path / "positions.yaml"
    save_positions(ppath, PositionsFile(ASOF, [_pos()]))
    store = _FakeStore({"CCJ": _series([50.0] * 60, ASOF), "URA": _series([30.0] * 60, ASOF)})
    rep = run_check(
        asof=ASOF,
        mode="weekly",
        prices=StorePriceSource(store),  # type: ignore[arg-type]
        positions_path=ppath,
        journal_dir=jdir,
        repo_root=tmp_path,
        out_root=None,
    )
    assert [c[0] for c in store.calls] == [["CCJ", "URA"]]  # 포지션 + DSL 티커를 한 질의로
    assert rep.positions[0].close == 50.0


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


def test_time_stop_on_the_exact_date_is_due_not_a_warning() -> None:
    """기한 당일은 **경과**다 (2026-08-26 코드 리뷰).

    `docs/07` §4 는 "horizon_months 상한 경과" 라고 적는다 — `time_stop_date` 그날이 상한에
    닿은 날이다. 예전에는 `0 <= days_left` 가 예고를 먼저 잡아 리포트가 `D+0 예고` 라고
    적었다. 알림 발생 자체는 양쪽 다 같았고 문구만 달랐다.
    """
    pc = check_position(
        _pos(time_stop_date=ASOF),  # 오늘이 기한
        make_thesis(),
        {},
        _prices([50.0] * 60, [30.0] * 60),
        ASOF,
    )
    assert pc.time_stop_due, "당일은 경과다"
    assert not pc.time_stop_warning, "예고가 아니다"

    # 하루 남았으면 여전히 예고다
    pc = check_position(
        _pos(time_stop_date=date(2026, 12, 16)),
        make_thesis(),
        {},
        _prices([50.0] * 60, [30.0] * 60),
        ASOF,
    )
    assert pc.time_stop_warning and not pc.time_stop_due
