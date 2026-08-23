"""계층 간 배선 — 한 계층의 **파일 산출물**을 다음 계층의 **파일 입력 계약**으로 옮긴다.

| 모듈 | 역할 |
|---|---|
| `assemble` | L4 `state/picks/` + L3 `state/theses/` (또는 사람 논지) → L5 입력 디렉터리 |
| `run` | 케이던스 오케스트레이터 `msa run monthly|weekly|quarterly` — 진입점을 순서대로, 보고 |

계층 패키지(`l4`·`l5`·`l3`)는 서로 임포트하지 않는다는 규약(`msa.l5` 머리말)은 그대로다 —
그 배선을 **이 패키지만** 한다. 여기서 하는 일은 열 이름을 옮기고 빠진 것을 **세어서** 적는
것뿐이며, 새 가중치·임계값을 만들지 않는다 (`CLAUDE.md` §1·§2).
"""

from msa.pipeline.run import (
    MonthlyRunResult,
    RunReport,
    StepResult,
    WeeklyRunResult,
    run_monthly,
    run_quarterly,
    run_weekly,
)

__all__ = [
    "MonthlyRunResult",
    "RunReport",
    "StepResult",
    "WeeklyRunResult",
    "run_monthly",
    "run_quarterly",
    "run_weekly",
]
