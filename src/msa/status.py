"""계층 간에 문자열로 오가는 상태값의 단일 정의.

값은 **기존 문자열 그대로**다 — 저장된 CSV/JSON(`axis1_status`·`status` 열)과 `docs/` 의 표기가
이 문자열을 쓴다. `StrEnum` 이라 `== "ok"` 비교·`str()`·JSON 직렬화가 전부 평문과 같다.
새 값을 만들 때는 여기 추가하고, 문자열 리터럴을 다른 모듈에 두지 않는다.
"""

from __future__ import annotations

from enum import StrEnum


class SeriesStatus(StrEnum):
    """외부 시계열(실물 참조·FRED·ETF·수동 CSV) 로드 결과 (`l1/physical`·`l2/sources`)."""

    OK = "ok"
    MISSING = "missing"


class Axis1Status(StrEnum):
    """축 1(단위 수요) 계산 경로 (`l1/blocks`·`l1/physical.status_table`·`l3/contracts`)."""

    OK_EXTERNAL = "ok_external"  # 실물 참조 시계열 그대로
    OK_FALLBACK = "ok_fallback"  # 동일 구성원 매출 / 가격지수 폴백
    DATA_MISSING = "data_missing"  # 선언은 있으나 데이터가 없다
    NOT_DECLARED = "not_declared"  # themes.yaml 에 physical_ref 없음

    @property
    def is_ok(self) -> bool:
        return self in (Axis1Status.OK_EXTERNAL, Axis1Status.OK_FALLBACK)


class FundStatus(StrEnum):
    """종목별 재무 가용성 (`l4/features`·`l4/axes`)."""

    OK = "ok"
    STALE = "stale"
    NONE = "none"


class CoverageStatus(StrEnum):
    """L2 tailwind 표의 테마별 엣지 커버리지 (`l2/tailwind`)."""

    OK = "ok"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class DeliveryStatus(StrEnum):
    """알림 배달 결과 (`ops/alerts.deliver`)."""

    SENT = "sent"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"
    NOTHING_TO_SEND = "nothing_to_send"
