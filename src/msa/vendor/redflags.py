"""재무제표 레드플래그 — `fin-checkup` 에서 벤더링 (`docs/06-stock-selection.md` §2 생존 축).

출처: https://github.com/younghwan91/fin-checkup
파일: src/fin_checkup/metrics/redflags.py (+ `models.Financials.capital_impairment_rate`,
      `metrics/sector.py` 의 `Sector.FINANCIAL` 예외)
커밋: df47aeecf9c1680e9989ae88cb493c68688ea08b
복사: 2026-08-23 (M5).

## 원본과 다른 점 — 입력을 Sharadar SF1 로 바꿨다

원본은 DART 연간 `Financials`(pydantic) 목록을 받는다. 여기서는 같은 판정 논리를
**연간 단위 재무 행(`AnnualRow`) 목록**에 적용하며, 그 행은 호출자가 Sharadar ARQ 분기를
TTM 으로 묶어 만든다 (`msa.l4.features`). 판정 규칙(자본잠식 · 3년 연속 영업손실 ·
흑자인데 영업현금 유출 · 3년 연속 이자보상배율 1 미만)은 원본 그대로다. 원본의
"관리종목 지정 요건" 문구는 한국 거래소 규정이라 뺐다 — 미국 상장사에 그 규정은 없다.
여기서 플래그는 **사실의 관측**이며 상장폐지 판정이 아니다.

컬럼 매핑 (원본 → Sharadar SF1):
- `total_equity` → `equity` (최신 분기 스냅샷)
- `capital_stock` (자본금) → **없음** → `partial_capital_impairment` 는 **계산 불가**
  (`NOT_COMPUTABLE`)
- `operating_income` → `opinc` TTM (분기 4개 합) · `net_income` → `netinc` TTM ·
  `operating_cash_flow` → `ncfo` TTM · `interest_expense` → `intexp` TTM
- `bsns_year` → TTM 종료 `calendardate` 의 연도 라벨 (회계연도가 아니라 직전 12개월 창)
- `Sector.FINANCIAL` → Sharadar `sector == 'Financial Services'` (이자보상배율 판정 생략,
  원본과 같은 이유)

계산할 수 없는 플래그는 **조용히 빠지지 않는다** — `NOT_COMPUTABLE` 에 이름과 이유가 있고,
L4 리포트가 그것을 그대로 적는다 (`CLAUDE.md` §2).
"""

from __future__ import annotations

from dataclasses import dataclass

#: 원본에 있으나 Sharadar 입력이 없어 계산하지 못하는 플래그 → 이유.
NOT_COMPUTABLE: dict[str, str] = {
    "partial_capital_impairment": (
        "자본잠식률 = (자본금 − 자기자본)/자본금 인데 SF1 에 자본금(capital_stock) 필드가 없다"
    ),
}

#: 여기서 계산하는 플래그 키 (리포트 열 순서).
COMPUTABLE: tuple[str, ...] = (
    "full_capital_impairment",
    "consecutive_operating_loss",
    "profit_without_cash",
    "zombie_streak",
)

#: Sharadar `tickers.sector` 중 이자보상배율 판정을 적용하지 않는 값.
FINANCIAL_SECTORS: frozenset[str] = frozenset({"Financial Services"})

STREAK_YEARS = 3


@dataclass(frozen=True)
class AnnualRow:
    """연간(직전 12개월) 단위 입력. `None` 은 "없음" 이며 0 으로 채우지 않는다 (원본 규약)."""

    year: int
    total_equity: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    operating_cash_flow: float | None = None
    interest_expense: float | None = None


@dataclass(frozen=True)
class RedFlag:
    key: str
    label: str
    #: 관측된 사실. 해석이나 권유를 담지 않는다.
    detail: str


def detect_red_flags(history: list[AnnualRow], *, financial: bool = False) -> list[RedFlag]:
    """연도 오름차순 재무 이력에서 위험 신호를 찾는다. 원본 `detect_red_flags` 와 같은 규칙.

    `financial=True` 면 이자보상배율 기반 판정을 적용하지 않는다 — 이자비용이 차입 원가가
    아니라 영업의 원가여서 1 미만이 정상이다.
    """
    if not history:
        return []
    ordered = sorted(history, key=lambda f: f.year)
    latest = ordered[-1]
    flags: list[RedFlag] = []

    # 자본잠식 (완전). 부분 잠식은 자본금이 없어 계산 불가 — NOT_COMPUTABLE.
    if latest.total_equity is not None and latest.total_equity <= 0:
        flags.append(
            RedFlag(
                "full_capital_impairment",
                "완전자본잠식",
                f"{latest.year}년 자기자본이 {latest.total_equity:,.0f} 으로 0 이하다.",
            )
        )

    # 연속 영업손실
    streak = _trailing_loss_streak(ordered)
    if streak >= STREAK_YEARS:
        flags.append(
            RedFlag(
                "consecutive_operating_loss",
                f"{streak}년 연속 영업손실",
                f"{ordered[-streak].year}~{latest.year}년 영업이익이 연속 음수다.",
            )
        )

    # 흑자인데 영업현금흐름 유출
    if (
        latest.net_income is not None
        and latest.net_income > 0
        and latest.operating_cash_flow is not None
        and latest.operating_cash_flow < 0
    ):
        flags.append(
            RedFlag(
                "profit_without_cash",
                "흑자인데 영업현금 유출",
                f"{latest.year}년 당기순이익은 {latest.net_income:,.0f} 이지만 "
                f"영업활동현금흐름은 {latest.operating_cash_flow:,.0f} 이다.",
            )
        )

    # 이자보상배율 1 미만 연속
    zombie = 0 if financial else _trailing_zombie_streak(ordered)
    if zombie >= STREAK_YEARS:
        flags.append(
            RedFlag(
                "zombie_streak",
                f"{zombie}년 연속 이자보상배율 1 미만",
                f"{ordered[-zombie].year}~{latest.year}년 영업이익이 이자비용에 미치지 못했다.",
            )
        )

    return flags


def _trailing_loss_streak(ordered: list[AnnualRow]) -> int:
    streak = 0
    for fin in reversed(ordered):
        if fin.operating_income is not None and fin.operating_income < 0:
            streak += 1
        else:
            break
    return streak


def _trailing_zombie_streak(ordered: list[AnnualRow]) -> int:
    streak = 0
    for fin in reversed(ordered):
        op, interest = fin.operating_income, fin.interest_expense
        if op is None or interest is None or interest == 0:
            break
        if op / interest < 1:
            streak += 1
        else:
            break
    return streak
