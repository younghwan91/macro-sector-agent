"""케이던스 스케줄러 — cron 생성 · 1영업일 게이트 · 벤더 RunTracker."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from msa.ops.scheduler import JOBS, cron_lines, first_business_day, is_due, systemd_units
from msa.vendor.scheduler import MAX_LOOKBACK_DAYS, LastRunStore, RunTracker


def test_cron_has_four_cadences_and_installs_nothing(tmp_path: Path) -> None:
    text = cron_lines(tmp_path)
    assert {j.cadence for j in JOBS} == {"monthly", "weekly", "daily", "quarterly"}
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#") and "=" not in ln[:9]]
    assert len(lines) == 4
    # 배선 W4: 월간·주간은 오케스트레이터(`msa run …`)를 부른다 — `msa scan`/`msa check --weekly`
    # 직접 호출에서 바뀌었다. 일간은 그대로 `msa check --daily`.
    assert any(
        ln.startswith("0 7 1-3 * *") and "msa ops due monthly" in ln and "msa run monthly" in ln
        for ln in lines
    )
    assert any(ln.startswith("30 7 * * 1") and "msa run weekly" in ln for ln in lines)
    assert any(ln.startswith("30 18 * * 1-5") and "msa check --daily" in ln for ln in lines)
    assert any(
        ln.startswith("0 8 1-3 1,4,7,10 *")
        and "msa ops calibration" in ln
        and "msa ops rejections-update" in ln
        and "msa macro" not in ln  # L2 제거 — 분기에 모순 감사 없음
        for ln in lines
    )
    assert f"MSA_REPO={tmp_path}" in text
    assert "crontab -e" in text  # 사람이 설치한다
    sd = systemd_units(tmp_path)
    assert "OnCalendar=Mon *-*-* 07:30:00" in sd and sd.count("[Timer]") == 4


@pytest.mark.parametrize(
    ("d", "fbd"),
    [
        (date(2026, 8, 15), date(2026, 8, 3)),  # 8/1 토 → 8/3 월
        (date(2026, 9, 1), date(2026, 9, 1)),  # 9/1 화
        (date(2026, 11, 20), date(2026, 11, 2)),  # 11/1 일 → 11/2
    ],
)
def test_first_business_day(d: date, fbd: date) -> None:
    assert first_business_day(d) == fbd


def test_is_due_gates() -> None:
    assert is_due("monthly", date(2026, 8, 3)) and not is_due("monthly", date(2026, 8, 1))
    assert is_due("quarterly", date(2026, 10, 1)) and not is_due("quarterly", date(2026, 11, 2))
    assert is_due("weekly", date(2026, 8, 24)) and not is_due("weekly", date(2026, 8, 25))
    assert is_due("daily", date(2026, 8, 25)) and not is_due("daily", date(2026, 8, 23))
    with pytest.raises(ValueError, match="cadence"):
        is_due("hourly", date(2026, 8, 25))


def test_run_tracker_marks_only_on_success(tmp_path: Path) -> None:
    tr = RunTracker(LastRunStore(tmp_path / "last.json"), key="check.daily")
    assert tr.lookback_days(date(2026, 8, 25)) == 1

    def boom(days: int) -> int:
        raise RuntimeError("store down")

    assert tr.run_once(boom, date(2026, 8, 25)) is None
    assert tr.consecutive_failures == 1 and tr.lookback_days(date(2026, 8, 25)) == 1
    assert tr.run_once(lambda days: days, date(2026, 8, 25)) == 1
    assert tr.consecutive_failures == 0
    tr.store.set_meta("check.daily", "2026-08-20T18:30:00")
    assert tr.lookback_days(date(2026, 8, 25)) == 6  # 5일 공백 + 1일 겹침
    tr.store.set_meta("check.daily", "2025-01-01T00:00:00")
    assert tr.lookback_days(date(2026, 8, 25)) == MAX_LOOKBACK_DAYS
