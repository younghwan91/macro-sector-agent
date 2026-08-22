""" "마지막 성공 시점부터" 를 기억하는 실행기 — `fin-checkup` 에서 벤더링 (`docs/08` §5).

출처: https://github.com/younghwan91/fin-checkup
파일: src/fin_checkup/alerts/scheduler.py
커밋: df47aeecf9c1680e9989ae88cb493c68688ea08b
복사: 2026-08-23 (M8).

원본은 DART 공시 폴링 워커를 asyncio 루프로 돌리는 `AlertScheduler` 였다. 이 저장소의 케이던스는
cron 이 돌리므로(`msa.ops.scheduler`) 루프는 가져오지 않고, **놓친 구간이 없게 하는 부분**만 남겼다:

- `lookback_days()` — 마지막 성공 기록부터 며칠치를 다시 봐야 하는가 (원본 그대로. 기록이 없으면
  하루치, 최대 `MAX_LOOKBACK_DAYS`, `OVERLAP_DAYS` 만큼 겹침).
- `run_once()` — 작업을 한 번 돌리고 **성공했을 때만** 시각을 기록한다. 실패한 구간을 성공으로
  표시하면 그 사이의 무효화 발동이 영영 사라진다.

원본의 `Cache.get_meta/set_meta` 대신 JSON 파일 하나(`state/checks/last_run.json`)를 쓴다.
`msa check --daily` 가 이 기록을 읽어, 프로세스가 며칠 죽어 있었으면 그 구간의 가격을 소급해 본다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

LAST_POLL_KEY = "alerts.last_poll"
#: 마지막 성공 기록이 없거나 너무 오래됐을 때 거슬러 올라갈 최대 일수.
MAX_LOOKBACK_DAYS = 30
#: 늦게 반영되는 경우를 대비해 겹쳐서 조회한다. 중복은 호출자가 막는다.
OVERLAP_DAYS = 1

T = TypeVar("T")


class LastRunStore:
    """`Cache.get_meta/set_meta` 의 JSON 파일 대체물."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("[scheduler] %s 를 읽을 수 없다 — 빈 기록으로 취급", self.path)
            return {}
        return d if isinstance(d, dict) else {}

    def get_meta(self, key: str) -> str | None:
        v = self._load().get(key)
        return None if v is None else str(v)

    def set_meta(self, key: str, value: str) -> None:
        d = self._load()
        d[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


class RunTracker:
    def __init__(self, store: LastRunStore, key: str = LAST_POLL_KEY) -> None:
        self.store = store
        self.key = key
        self.consecutive_failures = 0

    # ------------------------------------------------------------------
    # 놓친 구간 계산
    # ------------------------------------------------------------------

    def lookback_days(self, now: date | None = None) -> int:
        """마지막 성공 시점부터 며칠치를 조회해야 하는지.

        기록이 없으면 하루치만 본다. 처음 켠 워커가 한 달치 공시를 한꺼번에
        쏟아내면 그건 알림이 아니라 스팸이다.
        """
        today = now or date.today()
        last = self.store.get_meta(self.key)
        if not last:
            return 1
        try:
            last_date = datetime.fromisoformat(last).date()
        except ValueError:
            logger.warning("[scheduler] 마지막 폴링 시각을 읽을 수 없다: %r", last)
            return 1

        gap = (today - last_date).days + OVERLAP_DAYS
        return max(1, min(gap, MAX_LOOKBACK_DAYS))

    def mark_polled(self, when: datetime | None = None) -> None:
        self.store.set_meta(self.key, (when or datetime.now()).isoformat())

    # ------------------------------------------------------------------
    # 한 번 실행
    # ------------------------------------------------------------------

    def run_once(self, job: Callable[[int], T], now: date | None = None) -> T | None:
        """한 주기를 실행한다. 실패하면 None 을 반환하고 기록은 갱신하지 않는다."""
        days = self.lookback_days(now)
        try:
            result = job(days)
        except Exception:
            self.consecutive_failures += 1
            logger.exception(
                "[scheduler] 실행 실패 (연속 %d회) — 마지막 성공 시점을 유지해 "
                "다음 실행에서 이 구간을 다시 본다",
                self.consecutive_failures,
            )
            return None

        # 성공했을 때만 갱신한다. 실패한 구간을 성공으로 표시하면 그 사이 사건이 영영 사라진다.
        self.mark_polled()
        self.consecutive_failures = 0
        logger.info("[scheduler] %d일치 확인 완료", days)
        return result
