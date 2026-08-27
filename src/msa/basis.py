"""상수의 **근거** — 값 옆이 아니라 한 곳에 모으고, 테스트가 강제한다.

## 왜 문서가 아니라 코드인가

`CLAUDE.md` §1 은 *"임계값은 도메인 근거에서 오거나, 없으면 그렇다고 적는다"* 를 요구한다.
그동안 그 "적는다" 는 `docs/` 안에 있었고 **코드와 따로 흘렀다** — 2026-08-27 실측: 58개
수치 상수 중 코드에 근거 주석이 붙은 것은 0개였고, 외부 1차 출처가 확인된 것은 `docs/20`
의 7개뿐이었다. 같은 날 `docs/18` §6 이 "ETF 는 손으로 분기 1회" 라고 **사실과 다르게**
적혀 있는 것도 발견됐다. 문서는 드리프트한다.

그래서 근거를 코드에 두고, **테스트가 두 가지를 강제한다:**

1. `FILTER_CONSTANTS` 에 든 상수는 여기 항목이 **반드시** 있어야 한다 (없으면 실패).
2. 여기 적은 값이 실제 상수 값과 **같아야** 한다 (다르면 실패).

(2)가 핵심이다. 값만 바꾸고 근거를 안 고치면 근거가 조용히 거짓말이 된다 — 그때 CI 가
막는다. 근거 없이 값을 바꾸는 것이 이 저장소의 지배적 실패 유형(오버피팅)의 실행 형태다.

## 근거의 세 종류

- `Citation` — **외부 1차 출처**. 인용문과 URL 을 함께 싣는다. 2차 요약이 아니라 원문이다.
- `Derived` — 다른 선언값에서 **산술로** 나온 것. 새 자유도가 아니다.
- `NoBasis` — **근거가 없다.** 숨기지 않고 그렇다고 적는다. `CLAUDE.md` §1 의 후자 절이며,
  이것을 쓰는 것은 규칙 위반이 아니라 **규칙을 지킨 결과**다. 값을 바꿀 이유가 되지도 않는다
  — 근거가 없다고 데이터에 맞춰 옮기면 그것이 §1 이 금지하는 탐색이다.

## 쓰는 법

    msa ops why RUNWAY_MIN_Q     # 값·근거·인용문·URL
    msa ops why --missing        # 근거 없는 필터 상수 목록
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "BASES",
    "FILTER_CONSTANTS",
    "Basis",
    "Citation",
    "Derived",
    "NoBasis",
    "live_value",
    "missing",
    "resolve",
]


@dataclass(frozen=True)
class Citation:
    """외부 1차 출처. `quote` 는 **원문 그대로**, `match` 는 값이 왜 그 값인지."""

    source: str
    url: str
    quote: str
    match: str
    #: 인용문의 값과 우리 값이 **정확히** 같은가. 다르면 왜 다른지 `match` 에 적는다.
    exact: bool = True
    #: **원문에서 이 인용문을 실제로 확인한 날.** 비어 있으면 인용을 적기만 하고 대조하지
    #: 않았다는 뜻이다 — 출처 이름을 아는 것과 그 문장이 거기 있는 것은 다르다.
    #: 2026-08-27 실측: 인용 6건을 자동 대조했더니 PDF 4건이 "못 찾음" 으로 나왔는데,
    #: `pdftotext` 로 손대조하니 원문에 그대로 있었다. **자동 실패가 인용 오류가 아니다.**
    verified: str = ""


@dataclass(frozen=True)
class Derived:
    """다른 선언값에서 산술로 나온 값 — 새 자유도가 아니다."""

    frm: str
    why: str


@dataclass(frozen=True)
class NoBasis:
    """근거가 없다. **찾아봤고 없었다**는 기록이지 미완료 표시가 아니다."""

    note: str
    #: 찾아본 날. 안 찾아본 것과 찾아도 없는 것은 다르다.
    searched: str = ""


Basis = Citation | Derived | NoBasis


@dataclass(frozen=True)
class Entry:
    """근거 한 건 — 어느 상수의, 어떤 값에 대한, 무슨 근거인가."""

    module: str
    value: Any
    basis: Basis
    #: 이 상수가 실제로 무엇을 하는가. "자른다" 와 "표시만 한다" 는 다르다.
    role: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


def live_value(module: str, name: str) -> Any:
    """살아 있는 상수 값 — 레지스트리가 적은 값과 대조하기 위한 것."""
    return getattr(importlib.import_module(module), name)


# ---------------------------------------------------------------------------
# 레지스트리
#
# 값이 바뀌면 테스트가 여기를 고치라고 말한다. 근거를 고치지 않고 값만 바꿀 수 없다.
# ---------------------------------------------------------------------------

_L4 = "msa.l4.axes"
_L5O, _L5R = "msa.l5.optimize", "msa.l5.risk"

BASES: dict[str, Entry] = {
    # ---------------------------------------------------------------- L1
    "POOL_MIN": Entry(
        "msa.l1.scoreboard",
        0.5,
        role="자격 관문 — 미달이면 순위 없음(관찰 목록)",
        basis=NoBasis(
            "0.4·0.5·0.6 을 비교한 칸이 어디에도 없다. 있는 것은 '고를 근거가 없으니 "
            "중앙값' 이라는 설계 원리뿐이고, 그것은 §1 을 어긴 게 아니라 지킨 결과다. "
            "M3.6 구조 검정도 이 값을 검정하지 않았다 (docs/02).",
            searched="2026-08-26",
        ),
    ),
    # ---------------------------------------------------------------- L3
    "CONF_BASE": Entry(
        "msa.l3.gates",
        0.5,
        role="확신도 출발점",
        basis=NoBasis(
            "출처 없음. 그리고 이 값에는 알려진 결함이 있다 — 5축이 전부 적용 불가여도 "
            "확신도가 정확히 0.5 가 되어 편입 최소치(0.50)에 걸친다. 판정의 부재가 "
            "경계값을 만든다 (docs/04 §4).",
            searched="2026-08-27",
        ),
    ),
    "CONF_CAP_ON_DEATH": Entry(
        "msa.l3.gates",
        0.35,
        role="축1 또는 축3 사망 시 확신도 상한 — 편입 불가",
        basis=NoBasis("출처 없음. 조사된 적 없다.", searched=""),
    ),
    "PORTFOLIO_MIN_CONFIDENCE": Entry(
        "msa.l3.gates",
        0.5,
        role="이 아래면 포트폴리오에 넣지 않는다",
        basis=Derived(
            "CONF_BASE",
            "출발점과 같은 값 — 확신도가 오르지 않으면 편입하지 않는다는 "
            "뜻이다. 새 자유도가 아니지만 CONF_BASE 자체에 근거가 없다",
        ),
    ),
    "CAPEX_BELOW1_QTRS": Entry(
        "msa.l3.gates",
        8,
        role="축2 확신도 +0.10 조건 (capex/D&A < 1 연속 분기)",
        basis=NoBasis(
            "출처 없음. 조사된 적 없다 — 자본사이클 문헌에 8분기의 정본이 있는지 확인해야 한다.",
            searched="",
        ),
    ),
    "DEBT_24M_TO_MCAP_MAX": Entry(
        "msa.l3.gates",
        0.5,
        role="축5 터미널 리스크 판정 입력",
        basis=NoBasis("출처 없음. 조사된 적 없다.", searched=""),
    ),
    # ---------------------------------------------------------------- L4 자른다
    "RUNWAY_MIN_Q": Entry(
        _L4,
        4.0,
        role="**자른다** (E1) — 현금 런웨이",
        tags=("hard",),
        basis=Citation(
            "PCAOB AS 2415 ¶.02 (계속기업 판단)",
            "https://pcaobus.org/oversight/standards/auditing-standards/details/AS2415",
            "not to exceed one year beyond the date of the financial statements",
            "12개월 = 4분기. 감사인이 계속기업을 판단하는 지평과 같다",
            verified="2026-08-27",
        ),
    ),
    "ND_EBITDA_EXCLUDE": Entry(
        _L4,
        6.0,
        role="**자른다** (E2) — 순부채/EBITDA. 금융 섹터 미적용",
        tags=("hard",),
        basis=Citation(
            "Interagency Guidance on Leveraged Lending (OCC·Fed·FDIC, 2013)",
            "https://www.federalreserve.gov/supervisionreg/srletters/sr1303a1.pdf",
            "in excess of 6X Total Debt/EBITDA raises concerns",
            "감독기관이 '우려' 라고 부르는 지점과 같은 값",
            verified="2026-08-27",
        ),
    ),
    "MATURITY_WALL_EXCLUDE": Entry(
        _L4,
        0.5,
        role="E3 — **현재 미적용**",
        tags=("hard", "off"),
        basis=NoBasis("1차 출처를 찾지 못했다 (docs/20 조사).", searched="2026-08-26"),
    ),
    # ---------------------------------------------------------------- L4 감점
    "ND_EBITDA_PENALTY": Entry(
        _L4,
        4.0,
        role="감점 — 자르지 않는다",
        basis=Citation(
            "Interagency Guidance on Leveraged Lending (OCC·Fed·FDIC, 2013)",
            "https://www.federalreserve.gov/supervisionreg/srletters/sr1303a1.pdf",
            "exceed 4.0X EBITDA",
            "같은 문서의 leveraged transaction 정의",
            verified="2026-08-27",
        ),
    ),
    "INTEREST_COVERAGE_MIN": Entry(
        _L4,
        1.0,
        role="감점 — 자르지 않는다",
        basis=Citation(
            "BIS Quarterly Review 2018-09, Banerjee & Hofmann, 'The rise of zombie firms'",
            "https://www.bis.org/publ/qtrpdf/r_qt1809g.htm",
            "interest coverage ratio … less than one",
            "좀비 기업 정의의 임계와 정확히 같다",
            verified="2026-08-27",
        ),
    ),
    "DILUTION_MAX": Entry(
        _L4,
        0.15,
        role="감점 — 3년 주식수 증가",
        basis=NoBasis(
            "방향만 있고 임계 출처가 없다. Loughran-Ritter (1995)·Pontiff-Woodgate (2008) 은 "
            "'주식 발행이 많을수록 이후 수익이 낮다' 는 방향을 주지만 15% 라는 컷을 주지 않는다.",
            searched="2026-08-26",
        ),
    ),
    "ADV_MIN_USD": Entry(
        _L4,
        2_000_000.0,
        role="감점 — **현재 꺼짐** (2026-08-24 사용자 지시)",
        tags=("off",),
        basis=NoBasis("출처 없음. 유동성 하한의 정본을 찾지 못했다.", searched="2026-08-26"),
    ),
    "PRICE_MIN": Entry(
        _L4,
        2.0,
        role="감점 — **현재 꺼짐** (2026-08-24 사용자 지시)",
        tags=("off",),
        basis=NoBasis("출처 없음. 조사된 적 없다.", searched=""),
    ),
    "RUNWAY_CAP_Q": Entry(
        _L4,
        8.0,
        role="런웨이 점수의 만점 지점 (S축)",
        basis=Derived(
            "horizon 18M + 조달 6M", "문헌이 아니라 내부 유도다. 그 사실이 docs/20 에 명시돼 있다"
        ),
    ),
    "STREAK_YEARS": Entry(
        "msa.vendor.redflags",
        3,
        role="레드플래그 — 연속 영업적자 / 연속 좀비",
        basis=NoBasis(
            "출처 없음. 조사된 적 없다 — BIS 좀비 정의는 '3년 연속' 을 쓰므로 "
            "zombie_streak 쪽은 인용이 붙을 가능성이 있다. 확인 필요.",
            searched="",
        ),
    ),
    # ---------------------------------------------------------------- L5
    "MDD_BUDGET": Entry(
        _L5O,
        0.30,
        role="포트 최대낙폭 예산",
        basis=NoBasis(
            "출처 없음 — 그러나 **위험선호 선언**이라 문헌이 정해 줄 물건이 아니다. "
            "docs/07 §1: '목표가 아니라 예산이다. 다 쓰지 않으면 손해고 넘기면 파산이다'.",
            searched="2026-08-26",
        ),
    ),
    "MDD_K": Entry(
        _L5O,
        2.2,
        role="σ → 최대낙폭 환산 계수",
        basis=Citation(
            "Magdon-Ismail, Atiya, Pratap, Abu-Mostafa (2004) JAP 41(1), "
            "'On the Maximum Drawdown of a Brownian Motion'",
            "https://www.cs.rpi.edu/~magdon/ps/journal/drawdown_journal.pdf",
            "γ = √(π/8) ≈ 0.6267 is a constant … = 2γσ√T",
            "문헌의 **기대치는 1.2533** 이다. 우리 2.2 는 기대치가 아니라 T=1 의 95분위이며 "
            "그 차이(+76%)가 docs/07 §2.4 에 정정으로 기록돼 있다",
            exact=False,
            verified="2026-08-27",
        ),
    ),
    "CAP_STOCK": Entry(
        _L5O,
        0.15,
        role="종목 상한",
        basis=NoBasis("출처 없음.", searched="2026-08-26"),
    ),
    "CAP_THEME": Entry(
        _L5O,
        0.35,
        role="테마 상한",
        basis=NoBasis(
            "출처 없음. **그리고 순환이 있다** — Tier-2 스탑 −35% 가 이 값에서 역산되는데, "
            "그 둘이 서로를 정당화한다. 어느 쪽에도 외부 근거가 없다 (docs/07 §6.9).",
            searched="2026-08-26",
        ),
    ),
    "CAP_CLASS": Entry(
        _L5O,
        0.55,
        role="사이클 클래스 상한",
        basis=NoBasis("출처 없음.", searched="2026-08-26"),
    ),
    "LIQ_FRACTION_OF_ADV": Entry(
        _L5O,
        0.10,
        role="유동성 제약 — 하루 거래대금 대비",
        basis=Citation(
            "Almgren, Thum, Hauptmann, Li (2005) Risk 18(7), "
            "'Direct estimation of equity market impact'",
            "https://www.cis.upenn.edu/~mkearns/finread/costestim.pdf",
            "Within the range of order sizes considered (up to about 10% of daily volume), "
            "this model can be used to give quantitatively accurate pre-trade cost estimates",
            "값은 같다. 다만 이것은 '안전한 비율' 이 아니라 **임팩트를 예측할 수 있는 마지막 "
            "지점**이다 — 그 위로는 저자들이 자기 모형을 못 믿겠다고 적었다",
            verified="2026-08-27",
        ),
    ),
    "CASH_FLOOR": Entry(
        _L5O,
        0.15,
        role="현금 하한",
        basis=NoBasis("출처 없음.", searched="2026-08-26"),
    ),
    "MIN_CONFIDENCE": Entry(
        _L5O,
        0.50,
        role="C6 — 확신도가 이 아래면 편입하지 않는다",
        basis=Derived(
            "PORTFOLIO_MIN_CONFIDENCE", "L3 의 같은 값을 L5 가 다시 건다. 한 값이 두 곳에 있다"
        ),
    ),
    "COV_LOOKBACK_MONTHS": Entry(
        _L5R,
        60,
        role="공분산 추정 창",
        basis=Citation(
            "Ledoit & Wolf (2004) JPM 30(4) §4, 'Honey, I Shrunk the Sample Covariance Matrix'",
            "https://www.ledoit.net/honey.pdf",
            "we use the last T = 60 monthly returns",
            "정확히 같다",
            verified="2026-08-27",
        ),
    ),
    "SIMILAR_REGIME_DD": Entry(
        _L5R,
        0.50,
        role="'유사 국면' 에피소드의 진입 낙폭 — **케이스가 비어 현재 무해**",
        basis=NoBasis(
            "출처 없음 — docs/21 에 설계 질문으로 등록됨. 이 시스템은 국면을 낙폭이 아니라 "
            "밸류 백분위 하위 10% 로 정의하므로 이 임계는 빌려온 값도 아니다. "
            "**케이스 스터디는 docs/21 §4 가 끝날 때까지 쓰지 않는다.**",
            searched="2026-08-26",
        ),
    ),
    "CASE_DEATH_FACTOR": Entry(
        _L5R,
        0.5,
        role="케이스 스터디 낙폭에 곱하는 계수",
        basis=NoBasis("출처 없음. 조사된 적 없다.", searched=""),
    ),
}


def resolve(name: str) -> Entry | None:
    return BASES.get(name)


def missing() -> tuple[str, ...]:
    """근거 항목이 없는 필터 상수 — 테스트가 이것이 비어 있기를 요구한다."""
    return tuple(sorted(n for n in FILTER_CONSTANTS if n not in BASES))


#: **근거가 필수인 상수** — 종목·테마를 자르거나, 게이트를 쥐거나, 순위를 만드는 것.
#: 데이터 위생 상수(예: `TTM_MAX_SPAN_DAYS`)는 여기 넣지 않는다 — 판정을 만들지 않는다.
#: 이 목록에 이름을 올리는 것이 "이건 근거가 있어야 한다" 는 선언이다.
FILTER_CONSTANTS: tuple[str, ...] = (
    # L1 — 자격 관문
    "POOL_MIN",
    # L3 — 게이트·확신도
    "CONF_BASE",
    "CONF_CAP_ON_DEATH",
    "PORTFOLIO_MIN_CONFIDENCE",
    "CAPEX_BELOW1_QTRS",
    "DEBT_24M_TO_MCAP_MAX",
    # L4 — 하드 제외 (자른다)
    "RUNWAY_MIN_Q",
    "ND_EBITDA_EXCLUDE",
    "MATURITY_WALL_EXCLUDE",
    # L4 — 감점 (자르지 않는다)
    "ND_EBITDA_PENALTY",
    "INTEREST_COVERAGE_MIN",
    "DILUTION_MAX",
    "ADV_MIN_USD",
    "PRICE_MIN",
    "RUNWAY_CAP_Q",
    # L4 — 레드플래그
    "STREAK_YEARS",
    # L5 — 포트폴리오 제약
    "MDD_BUDGET",
    "MDD_K",
    "CAP_STOCK",
    "CAP_THEME",
    "CAP_CLASS",
    "LIQ_FRACTION_OF_ADV",
    "CASH_FLOOR",
    "MIN_CONFIDENCE",
    "COV_LOOKBACK_MONTHS",
    "SIMILAR_REGIME_DD",
    "CASE_DEATH_FACTOR",
)


# ---------------------------------------------------------------------------
# 사람이 읽는 형태
# ---------------------------------------------------------------------------


def render(name: str) -> str:
    """상수 하나의 근거 — `msa ops why <NAME>` 이 그대로 찍는다."""
    e = resolve(name)
    if e is None:
        near = [n for n in FILTER_CONSTANTS if name.upper() in n]
        hint = f" 비슷한 것: {', '.join(near)}" if near else ""
        return f"{name}: 근거 항목이 없다. 필터 상수가 아니거나 아직 등록되지 않았다.{hint}"

    live = live_value(e.module, name)
    L = [f"{name} = {live!r}", f"  어디  {e.module}", f"  역할  {e.role}"]
    b = e.basis
    if isinstance(b, Citation):
        L += [
            f"  근거  인용{'' if b.exact else ' (값이 원문과 다르다 — 아래 대조를 읽어라)'}",
            f"  출처  {b.source}",
            f"  원문  “{b.quote}”",
            f"  대조  {b.match}",
            f"  URL   {b.url}",
        ]
    elif isinstance(b, Derived):
        L += [f"  근거  유도 — {b.frm} 에서", f"  왜    {b.why}"]
    else:
        when = f" (조사일 {b.searched})" if b.searched else " — **아직 조사하지 않았다**"
        L += [f"  근거  없음{when}", f"  기록  {b.note}"]
    return "\n".join(L)


def render_table() -> str:
    """전체 현황 — 무엇이 인용이고 무엇이 근거 없는지 한 화면에."""
    rows, counts = [], {"인용": 0, "유도": 0, "근거없음": 0, "미조사": 0}
    for name in FILTER_CONSTANTS:
        e = BASES[name]
        b = e.basis
        if isinstance(b, Citation):
            kind, note = "인용", b.source[:52]
            counts["인용"] += 1
        elif isinstance(b, Derived):
            kind, note = "유도", f"{b.frm} 에서"
            counts["유도"] += 1
        else:
            searched = bool(b.searched)
            kind = "근거없음" if searched else "미조사"
            note = b.note[:52]
            counts[kind] += 1
        cut = "자른다" if "hard" in e.tags else ("꺼짐" if "off" in e.tags else "")
        rows.append(f"  {name:<26}{live_value(e.module, name)!s:>12}  {kind:<6}{cut:<5}{note}")
    head = " · ".join(f"{k} {v}" for k, v in counts.items() if v)
    return (
        f"필터 상수 {len(FILTER_CONSTANTS)}개 — {head}\n"
        f"  {'상수':<24}{'값':>12}  {'근거':<6}{'':<5}비고\n" + "\n".join(rows)
    )
