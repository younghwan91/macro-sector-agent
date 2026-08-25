"""3축 점수와 하드 제외 필터 — `docs/06-stock-selection.md` §2·§3·§4·§6. 순수 함수.

입력은 `features.FeatureSet.frame`(index ticker) 이고 출력은 같은 index 의 점수 표다.
스토어를 모른다 — 그래서 합성 표로 전부 테스트된다.

## 2026-08-24 — 이 모듈의 두 절반은 지위가 다르다

- **`hard_filters` / `hard_filter_flags` 는 선정한다.** 하드 제외(E1~E6)는 그대로다. 임계도
  그대로다 — `docs/14` §4.2 가 미리 정한 대로, 하드 제외의 근거는 수익률이 아니라 `docs/06` §2
  의 도메인 서술이다.
- **`score`(3축 백분위 · `composite` · `rank`)는 선정하지 않는다.** 관찰 지표다. 선정은
  "하드 제외를 통과한 종목 전부 · 동일가중" 이고 그 판정은 위 두 함수가 이미 끝낸다
  (`picks.rank_theme` · `journal/2026-08-24-l4-selection-retired.md`).

`AXIS_WEIGHTS`(0.40/0.40/0.20) · `S_WEIGHTS` · `T_MIN_INPUTS` · `RUNWAY_CAP_Q` 는 **하나도
옮기지 않았다** (`docs/14` §4.3 · `docs/15` §5.1). 축 정의도 그대로다. 바꾼 것은 이 숫자들이
어디에 쓰이는지에 대한 **표시**이지 숫자가 아니다. 덧붙여, `AXIS_WEIGHTS` 는 2026-08-23 이전에도
선정에 쓰인 적이 없다 (`journal/2026-08-23-l4-rank-score-unwired.md`).

## 선언값 (`CLAUDE.md` §1 — 데이터에 맞춰 바꾸지 않는다)

문서가 준 것 (그대로):
- 하드 제외: 런웨이 < 4분기 · 순부채/EBITDA > 6× · 만기벽 > 0.5 · 계속기업 의문(**입력 없음**)
- 감점: 순부채/EBITDA > 4× · 이자보상배율 < 1 · 희석 3y > 15%/y · 20일 거래대금 < $2M · 종가 < $2
- 종합: `0.40·S̃ + 0.40·T̃ + 0.20·M̃`

**2026-08-24 — 뒤의 둘(`adv_lt_2m`·`price_lt_2`)은 꺼져 있다.** 사용자 지시다("유동성 걱정하지
말고 일단 풀어놔"). 스위치는 `PENALTY_ENABLED` 이고 **임계값은 하나도 지우지 않았다** — 규칙이
다시 주어지면 `True` 로 되돌리는 것이 되살리는 전부다. 꺼진 항목은 평가되지 않아 분자·분모
양쪽에서 빠지고(없는 것을 통과로 세지 않는다), 그 사실은 `declared_constants()` → `meta.json` 과
리포트·다이제스트 머리에 매번 적힌다. `adv20_usd`·`price` **열은 그대로 실린다** — 판단
재료이지 감점 재료만이 아니다.

문서가 비워 둔 것 — 여기서 선언한다 (근거는 `docs/06` §8 구현 노트와 같다):

- S 원점수 = `0.40·runway_score + 0.30·leverage_score + 0.30·penalty_score`. 런웨이는 문서가
  "1차 사망 원인" 이라 부른 항목 → 최대. 레버리지는 두 번째 하드 항목. 나머지 감점 5종 +
  레드플래그 4종은 등가의 보조 신호.
- `runway_score = clip(runway_q / 8, 0, 1)` (FCF ≥ 0 → 1). 논지 horizon 6~18개월(`docs/05`
  `horizon_months`) 의 상한 + 자금조달 6개월 = 8분기. 그 너머의 런웨이는 논지 창 안의 생존을
  더 늘리지 않는다.
- `leverage_score = 1 − clip(ND/EBITDA / 6, 0, 1)` (순현금 → 1). 하드 제외 임계 6× 를 0 점으로
  두는 선형 감점.
- `penalty_score = 1 − (발동 감점 수 / 평가 가능한 감점 수)`. 감점 항목끼리 우열 근거가 없어
  등가. 입력이 없는 항목은 분모에서 뺀다 (없는 것을 통과로 세지 않는다).
- T 원점수 = 가용 구성 요소의 테마 내 백분위 평균 (불리언은 0/1) — `margin_headroom`·
  `opleverage`·`fixed_cost_ratio`·`price_beta_hist`·`equity_leverage`·`marginal_producer`, 전부
  높을수록 토크 ↑. 문서가 순서를 주지 않았다. `price_beta_hist` 가 "가장 직접적" 이지만 "표본
  1~2 사이클" 이라 가중하지 않는다.
- M 원점수 = `stage2`·`rs_rating/100`·`vcp_base`·`above_50d`·pct(`from_52w_low`)·
  pct(`rvol_expansion`) 의 가용 평균. 문서 §4 의 6개 지표 등가. M 은 종합 가중 0.20 으로 이미 낮다.
- 축 최소 입력 — T·M 모두 6개 중 **3개 이상** 있어야 계산, 아니면 NaN. 소수 구성 요소의 평균은
  그 축이 아니라 다른 것을 잰다 (예: `above_50d` 하나로 M=1.0). 절반은 표본 크기에 무관한 기준.
- **계산된 하드 항목의 판정 불가는 하드 제외** (사유 표기) — 런웨이(E4) · 순부채/EBITDA(E6).
  하드 필터를 평가할 수 없는 종목을 통과시키면 필터가 있는 척하는 것이다 — 재무 없음(E5)과
  같은 처리. **2026-08-24: 이 문장은 원래 셋 다를 가리켰는데 코드는 런웨이(E4)에만
  적용하고 있었다.** `nd` 가 NaN 이면 `nd > 6` 이 `False` 라 조용히 통과했다. E6 은 그 누락을
  메운 것이고 **임계는 하나도 옮기지 않았다** — 결측 처리만 바꿨다. E4 와 같이 **데이터 절단**
  이며 알파 주장이 아니다 (`docs/14` §1 Q3 · §4.1 — 판정하지 않는다).
- **만기벽은 예외다 — 그 필터는 이 스토어에서 선언대로 계산된 적이 없다** (2026-08-24 재개정).
  `docs/06` §2 가 선언한 필터는 `maturity_wall_24m`(24개월 만기부채/시총)이고, SF1 에 만기
  스케줄이 없어 **어느 종목에도 계산되지 않는다** (`features.py` 머리말). E3 가 보는
  `maturity_wall_12m = debtc/mcap` 은 **선언된 적 없는 대용치**이고, `debtc` 가 있는 종목에서만
  기회적으로 발동해 왔다. 대용치가 없다고 제외하면 **선언되지 않은 강제**를 만드는 것이다 —
  `going_concern` 이 "선언됐으나 미구현" 으로 **보고**되고 그 부재로 아무도 자르지 않는 것과
  같은 취급을 한다. 하루 존재했던 E7(만기벽 판정 불가 = 하드 제외)은 그래서 **철회했다.**
  대신 `unapplied_filter_flags` 가 **E3 를 적용하지 못한 종목 수**를 세어 산출물에 싣는다
  (`CLAUDE.md` §2 — 필터가 있는 척하지 않으려면 이 수가 보여야 한다).
  E6 과의 비대칭은 데이터의 성격 차이다: `net_debt_ebitda` 는 EBITDA≤0 이면 순부채/시총으로
  **대체 계산되므로** NaN 은 "재무가 아예 없다" 는 뜻(E5 와 같은 층위)이지 업종 회계 구조가
  아니다. `debtc` 결측은 위험이 아니라 회계 구조다 — 실측 REIT 100.0% · 은행 99.7% ·
  보험 98.2% vs 원유 E&P 0.1% · 금 0.0% (`docs/06` §2.1).
- 축 결측 시 종합 — 가용 축 가중치를 재정규화하고 `composite_partial=True` 표시. 빈 축을 0 으로
  두면 순위가 결측에 지배된다; 표시 없이 재정규화하면 조용한 절단.
- 순위 동률 — 종합 ↓ → S̃ ↓ → 티커 ↑. 결정론 — 같은 입력이면 같은 순위.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from msa.l1.scoreboard import xs_pct
from msa.l4.features import FEATURE_COLUMNS
from msa.status import FundStatus
from msa.vendor.redflags import FINANCIAL_SECTORS

# ---- 문서 선언값 (docs/06 §2)
RUNWAY_MIN_Q = 4.0
ND_EBITDA_EXCLUDE = 6.0
ND_EBITDA_PENALTY = 4.0
MATURITY_WALL_EXCLUDE = 0.5
INTEREST_COVERAGE_MIN = 1.0
DILUTION_MAX = 0.15
ADV_MIN_USD = 2_000_000.0
PRICE_MIN = 2.0

# ---- 여기서 선언한 값 (모듈 docstring 표). 값은 2026-08-24 개정에서 하나도 바뀌지 않았다.
RUNWAY_CAP_Q = 8.0
S_WEIGHTS = {"runway": 0.40, "leverage": 0.30, "penalty": 0.30}
#: 종합 점수 `composite` 의 축 가중치 — **선정에 쓰이지 않는다** (관찰 지표). 값을 바꿔도
#: `msa picks` 가 내놓는 종목 집합은 같다. 그래서 옮기지도 않는다 (`CLAUDE.md` §1).
AXIS_WEIGHTS = {"S": 0.40, "T": 0.40, "M": 0.20}
T_MIN_INPUTS = 3
M_MIN_INPUTS = 3
T_COMPONENTS: tuple[str, ...] = (
    "margin_headroom",
    "opleverage",
    "fixed_cost_ratio",
    "price_beta_hist",
    "equity_leverage",
    "marginal_producer",
)
T_BOOLEAN = ("marginal_producer",)
M_BOOLEAN = ("stage2", "vcp_base", "above_50d")
M_PCT = ("from_52w_low", "rvol_expansion")
#: M 축이 평균하는 6개 — `timing_components` 의 열 순서다 (합산 순서를 바꾸지 않는다).
M_COMPONENTS: tuple[str, ...] = (*M_BOOLEAN, "rs_rating", *M_PCT)
#: S 원점수의 3개 하위 항목 (`survival` 이 내놓는 열 이름). `docs/14` §1 Q4 의 "S 3개".
S_COMPONENTS: tuple[str, ...] = ("runway_score", "leverage_score", "penalty_score")
#: 레드플래그 감점 4종 — `features.red_flags` 문자열(`;` 구분)에 키가 들어 있으면 발동.
RED_FLAG_KEYS: tuple[str, ...] = (
    "full_capital_impairment",
    "consecutive_operating_loss",
    "profit_without_cash",
    "zombie_streak",
)
PENALTY_ITEMS: tuple[str, ...] = (
    "nd_ebitda_gt4",
    "interest_coverage_lt1",
    "dilution_gt15",
    "adv_lt_2m",
    "price_lt_2",
    *(f"rf_{k}" for k in RED_FLAG_KEYS),
)

#: 감점 항목의 **적용 여부** — 2026-08-24 사용자 지시로 유동성(`adv_lt_2m`)·저가(`price_lt_2`)
#: 둘을 껐다 ("유동성 걱정하지말고 일단 풀어놔. 필터링 규칙은 내가 나중에 도움요청할게").
#:
#: - **끈 항목은 평가하지 않는다** — `penalty_score` 의 분자에서도 **분모에서도** 빠진다.
#:   `s_inputs_missing` 과 같은 규칙이다: 없는 것을 통과로 세지 않는다. 끄기 전후로 남은
#:   항목의 상대 비중은 그대로다.
#: - **임계값은 지우지 않았다** (`ADV_MIN_USD` = $2M · `PRICE_MIN` = $2). 되살리는 법은
#:   여기 값을 `True` 로 되돌리는 것 하나뿐이고, 그러면 옛 판정이 그대로 돌아온다.
#: - `adv20_usd` · `price` **열은 계속 산출물에 실린다** — 판단 재료다. 감점만 껐다.
#: - 하드 제외(E1~E7)는 이 스위치와 무관하다 — 유동성은 애초에 하드 항목이 아니었다.
#: - 이 사실은 조용히 두지 않는다: `declared_constants()` → `meta.json`, 리포트·다이제스트
#:   머리, 텔레그램 본문에 매번 적힌다 (`CLAUDE.md` §2).
PENALTY_ENABLED: dict[str, bool] = {
    "nd_ebitda_gt4": True,
    "interest_coverage_lt1": True,
    "dilution_gt15": True,
    "adv_lt_2m": False,  # 2026-08-24 사용자 지시 — 유동성 감점 미적용
    "price_lt_2": False,  # 2026-08-24 사용자 지시 — 저가 감점 미적용
    **{f"rf_{k}": True for k in RED_FLAG_KEYS},
}
assert set(PENALTY_ENABLED) == set(PENALTY_ITEMS)

#: 지금 꺼져 있는 감점 (표시용 — 리포트·다이제스트가 이 목록을 읽어 "무엇을 껐는지" 를 적는다).
DISABLED_PENALTIES: tuple[str, ...] = tuple(k for k in PENALTY_ITEMS if not PENALTY_ENABLED[k])

#: 꺼진 감점을 사람 문장으로 — 산출물 머리에 그대로 박힌다. 전부 켜져 있으면 빈 문자열.
_DISABLED_LABELS: dict[str, str] = {
    "adv_lt_2m": f"유동성(20일 거래대금 < ${ADV_MIN_USD / 1e6:.0f}M)",
    "price_lt_2": f"저가(종가 < ${PRICE_MIN:.0f})",
}


def disabled_penalty_note() -> str:
    """ "무엇을 껐고 왜인가" 한 줄. 켜진 것만 있으면 빈 문자열 (조용히 끄지 않는다)."""
    if not DISABLED_PENALTIES:
        return ""
    who = " · ".join(_DISABLED_LABELS.get(k, k) for k in DISABLED_PENALTIES)
    return (
        f"감점 미적용: {who} — 2026-08-24 사용자 지시로 껐다. "
        "임계는 지우지 않았고(axes.PENALTY_ENABLED) 열은 아래 명단에 그대로 실린다"
    )


assert abs(sum(S_WEIGHTS.values()) - 1.0) < 1e-9
assert abs(sum(AXIS_WEIGHTS.values()) - 1.0) < 1e-9

#: 하드 필터 사유 문구 (테스트·`excluded.csv` 가 이 문자열을 본다)
_REASON_NO_SF1 = "재무 없음 (SF1 에 행 0개 — 20-F 해외발행사 등 미수록) — 생존 필터 판정 불가"
_REASON_STALE = "재무 없음 (asof 이전 15개월 내 분기 없음) — 생존 필터 판정 불가"
_REASON_RUNWAY_NA = "런웨이 판정 불가 (현금흐름표 또는 현금 없음) — 하드 필터 미통과"
_REASON_ND_NA = "순부채/EBITDA 판정 불가 (부채·현금 또는 EBITDA·시총 없음) — 하드 필터 미통과"

#: 하드 제외 **사유 코드** — `docs/14` §1 Q3 의 E1~E5 + 2026-08-24 에 메운 E6.
#: E1~E3 이 알파 주장, E4~E6 은 데이터 사정(판정 불가). 한 종목이 여러 사유에 동시에 걸릴 수
#: 있다 (코드별로 따로 센다).
#: **E7(만기벽 판정 불가)은 2026-08-24 같은 날 철회됐다** — 모듈 docstring 의 만기벽 항목.
#: 코드를 남겨 두면 `hard_filters` 의 마스크·`backtest.filters` 의 "제외군 − 통과군" 대조·
#: `count_trials` 의 E 가 전부 "제외한다" 를 전제하므로, 제외하지 않기로 한 사유를 코드로
#: 남기는 것은 세 곳에 거짓말을 심는 것이다. 그래서 마스크에서만 빼지 않고 **코드 자체를
#: 뺐고**, 그 자리는 아래 `FILTER_UNAPPLIED_*`(제외가 아니라 미적용 계수)가 받는다.
HARD_REASON_CODES: tuple[str, ...] = ("E1", "E2", "E3", "E4", "E5", "E6")
HARD_REASON_LABELS: dict[str, str] = {
    "E1": f"cash_runway_q < {RUNWAY_MIN_Q:.0f}",
    "E2": f"net_debt_ebitda > {ND_EBITDA_EXCLUDE:.0f}x",
    "E3": f"maturity_wall_12m > {MATURITY_WALL_EXCLUDE}",
    "E4": "런웨이 판정 불가 (현금흐름표 없음)",
    "E5": "fund_status ∈ {none, stale}",
    "E6": "순부채/EBITDA 판정 불가 (입력 없음)",
}
#: 알파 주장인 사유 — `docs/14` §4.1 이 합격 판정을 거는 것은 이 셋뿐이다.
HARD_REASON_ALPHA: tuple[str, ...] = ("E1", "E2", "E3")
#: 데이터 절단인 사유 — `docs/14` §4.1 이 "판정하지 않는다. 수치만 적는다" 로 못박은 부류.
#: E6 은 E4 와 같은 등급이다 (2026-08-24 신설 · 모듈 docstring).
HARD_REASON_DATA: tuple[str, ...] = ("E4", "E5", "E6")

#: **미적용 계수** — 제외 사유가 아니다. 입력이 없어 그 하드 필터를 **걸지 못한** 종목을 센다.
#: 제외하지 않으므로 `hard_filters` 도 `HARD_REASON_CODES` 도 이것을 모른다. `docs/14` §6.2 의
#: 시도 수에도 들어가지 않는다 — 어떤 칸도 들여다보지 않고 세기만 한다.
#: 지금 원소는 하나(E3)다. `going_concern` 은 아예 열이 없어(입력 자체가 없다) 여기가 아니라
#: `features.INPUTS_UNAVAILABLE` 이 보고한다 — 이쪽은 "열은 있는데 값이 없다" 를 센다.
#: **이 업종에는 이 비율이 정의되지 않는다** — 제외가 아니라 **미적용**으로 센다 (2026-08-26).
#:
#: `net_debt_ebitda`(E2)·`maturity_wall_12m`(E3)은 둘 다 대차대조표 부채를 분모/분자로 쓴다.
#: **은행·브로커·보험에서 부채는 위험이 아니라 영업 그 자체**다 — 예금·차입이 곧 사업 자산의
#: 재원이고, 그 비율은 제조업에서 뜻하는 것을 뜻하지 않는다. 근거가 된 문헌(2013 Interagency
#: Guidance on Leveraged Lending)도 **대출을 받는 기업**의 레버리지를 다루지 대출을 **하는**
#: 기관을 다루지 않는다.
#:
#: 이 저장소는 같은 원칙을 이미 선언했다 — `vendor/redflags.FINANCIAL_SECTORS` 가 이자보상배율
#: 판정을 금융업에서 뺀다. **새 임계가 아니라 그 원칙의 확장이다** (`CLAUDE.md` §1 은 값을
#: 데이터에 맞춰 옮기는 것을 금지하지, 정의되지 않는 곳에 적용하지 않는 것을 금지하지 않는다).
#:
#: 실측(2026-08-26, 2023-08 단면·24개월): E2 단독 제외군의 사망률은 **1.8%** 로 통과군 2.7%
#: 보다 **낮았고** 중앙수익률은 +20.1% 로 더 높았다. 그 단독군의 절반 이상이 은행·자산운용·
#: 모기지REIT 였다. `docs/backtest-l4.md` §5 의 "+6.7%p" 는 E1·E3 와 겹친 114종목이 만든 것이다.
FILTER_UNAPPLIED_SECTORS: dict[str, frozenset[str]] = {
    "E2": FINANCIAL_SECTORS,
    "E3": FINANCIAL_SECTORS,
}

FILTER_UNAPPLIED_CODES: tuple[str, ...] = ("E2", "E3")
FILTER_UNAPPLIED_COLUMN: dict[str, str] = {
    "E2": "net_debt_ebitda",
    "E3": "maturity_wall_12m",
}
FILTER_UNAPPLIED_LABELS: dict[str, str] = {
    "E2": (
        "순부채/EBITDA 미적용 (금융업 — 부채가 위험이 아니라 영업이다). "
        "제외하지 않는다: 근거 문헌(2013 Interagency Guidance)은 대출을 받는 기업을 다루지 "
        "대출을 하는 기관을 다루지 않는다 (docs/06 §2.1.2)"
    ),
    "E3": (
        "만기벽 미적용 (maturity_wall_12m 입력 없음 — SF1 의 debtc 결측). "
        "제외하지 않는다: 선언된 필터는 maturity_wall_24m 이고 이 스토어에서 "
        "누구에게도 계산되지 않는다 (docs/06 §2.1 재개정)"
    ),
}


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _pct(s: pd.Series) -> pd.Series:
    """테마 내 횡단면 백분위 (0,1]. NaN 은 NaN 으로 남는다 (`l1.scoreboard.xs_pct` 와 같은 규칙)."""
    return xs_pct(_num(s), +1)


def _bool01(s: pd.Series) -> pd.Series:
    """True/False/NA(None·NaN·pd.NA) → 1.0/0.0/NaN."""
    return s.astype("boolean").astype("float")


def _check_columns(frame: pd.DataFrame) -> None:
    """입력은 `features.FEATURE_COLUMNS` 전부를 가진 특성 표다 — 없는 열을 메우지 않는다."""
    missing = set(FEATURE_COLUMNS) - set(frame.columns)
    assert not missing, f"특성 표에 없는 열: {sorted(missing)}"


def _join_nonempty(parts: list[pd.Series], sep: str) -> pd.Series:
    """행마다 빈 문자열이 아닌 조각을 `sep` 로 잇는다 (벡터화된 `sep.join(x for x in row if x)`)."""
    out = parts[0].copy()
    for part in parts[1:]:
        out = out + np.where((out != "") & (part != ""), sep, "") + part
    return out


def _tagged(mask: pd.Series, text: Any) -> pd.Series:
    """`mask` 인 행만 `text`, 나머지는 빈 문자열."""
    return pd.Series(np.where(mask.fillna(False).astype(bool), text, ""), index=mask.index)


def _sector_mask(frame: pd.DataFrame, code: str) -> pd.Series:
    """그 사유가 **적용되지 않는 업종**인가. `sector` 열이 없으면 전부 False (예전 산출물 호환)."""
    sectors = FILTER_UNAPPLIED_SECTORS.get(code)
    if not sectors or "sector" not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame["sector"].astype(str).isin(sectors)


def hard_filter_flags(frame: pd.DataFrame) -> pd.DataFrame:
    """사유 **코드별** 하드 제외 불리언 (index ticker · 열 `HARD_REASON_CODES`).

    `hard_filters` 의 문구가 붙는 마스크와 **같은 마스크**다 (그 함수가 이것을 쓴다). 백테스트가
    사유별로 제외군을 나눠 재기 위해 필요하다 (`docs/14` §1 Q3 · §2.5). 판정값은 바뀌지 않는다.
    """
    _check_columns(frame)
    has_fund = frame["fund_calendardate"].notna()
    runway = _num(frame["cash_runway_q"])
    nd = _num(frame["net_debt_ebitda"])
    wall = _num(frame["maturity_wall_12m"])
    out = pd.DataFrame(index=frame.index)
    out["E1"] = (has_fund & (runway < RUNWAY_MIN_Q)).fillna(False).astype(bool)
    # 금융업에서는 부채 비율이 정의되지 않는다 — 제외하지 않고 `unapplied_filter_flags` 가 센다.
    fin = _sector_mask(frame, "E2")
    out["E2"] = (has_fund & ~fin & (nd > ND_EBITDA_EXCLUDE)).fillna(False).astype(bool)
    out["E3"] = (
        (has_fund & ~_sector_mask(frame, "E3") & (wall > MATURITY_WALL_EXCLUDE))
        .fillna(False)
        .astype(bool)
    )
    out["E4"] = (has_fund & runway.isna()).fillna(False).astype(bool)
    out["E5"] = (~has_fund).fillna(False).astype(bool)
    # E6 — E2 의 판정 불가. `nd > 6` 은 NaN 에서 False 라 조용히 통과했다 (2026-08-24).
    # E4 와 같은 처리이고 임계는 옮기지 않았다.
    # E3 의 짝(하루 존재했던 E7)은 없다 — `wall` 결측은 제외가 아니라 **미적용**으로 센다
    # (`unapplied_filter_flags`). 근거는 모듈 docstring 의 만기벽 항목.
    out["E6"] = (has_fund & ~fin & nd.isna()).fillna(False).astype(bool)
    return out[list(HARD_REASON_CODES)]


def unapplied_filter_flags(frame: pd.DataFrame) -> pd.DataFrame:
    """**필터를 걸지 못한** 종목의 불리언 (index ticker · 열 `FILTER_UNAPPLIED_CODES`).

    제외 마스크가 아니다 — 여기 True 인 종목도 다른 사유가 없으면 적격이다. 세는 이유는 하나,
    "그 종목에는 그 필터가 적용되지 않았다" 를 산출물이 말할 수 있어야 하기 때문이다
    (`CLAUDE.md` §2). 재무 자체가 없는 종목(E5)은 이미 제외되므로 세지 않는다 — 미적용을
    말하려면 먼저 평가 대상이어야 한다.
    """
    _check_columns(frame)
    has_fund = frame["fund_calendardate"].notna()
    out = pd.DataFrame(index=frame.index)
    for code in FILTER_UNAPPLIED_CODES:
        col = _num(frame[FILTER_UNAPPLIED_COLUMN[code]])
        # 미적용의 사유는 둘이다 — 입력이 없거나(결측), 그 업종에 정의되지 않거나.
        out[code] = (has_fund & (col.isna() | _sector_mask(frame, code))).fillna(False).astype(bool)
    return out[list(FILTER_UNAPPLIED_CODES)]


def hard_filters(frame: pd.DataFrame) -> pd.DataFrame:
    """하드 제외 판정. 반환 index ticker: `excluded`(bool), `reason`(str; 복수는 ' · ' 로 연결).

    재무가 없는(신선도 탈락) 종목도 제외한다 — 생존 필터를 **평가할 수 없는** 종목을 통과시키면
    필터가 있는 척하는 것이다. 사유에 그렇게 적는다. **계산되는 하드 항목에 같은 규칙이 걸린다**
    — 런웨이(E4) · 순부채/EBITDA(E6) (2026-08-24). `going_concern` 은 입력이 없어 적용하지
    못한다. **만기벽도 같은 부류다** — 선언된 `maturity_wall_24m` 은 이 스토어에서 아무에게도
    계산되지 않고, 대용치 `maturity_wall_12m` 이 없다고 제외하지 않는다 (2026-08-24 재개정 ·
    모듈 docstring). 미적용 수는 `unapplied_filter_flags` 가 센다.
    """
    _check_columns(frame)
    flags = hard_filter_flags(frame)
    runway = _num(frame["cash_runway_q"])
    nd = _num(frame["net_debt_ebitda"])
    wall = _num(frame["maturity_wall_12m"])
    no_sf1 = frame["fund_status"].astype(str) == FundStatus.NONE
    nd_unit = (frame["nd_basis"] == "ebitda").map({True: "EBITDA", False: "시총(EBITDA≤0 대체)"})

    no_fund = _tagged(flags["E5"], np.where(no_sf1, _REASON_NO_SF1, _REASON_STALE))
    runway_na = _tagged(flags["E4"], _REASON_RUNWAY_NA)
    nd_na = _tagged(flags["E6"], _REASON_ND_NA)
    runway_low = _tagged(
        flags["E1"],
        runway.map(lambda r: f"런웨이 {r:.2f}분기 < {RUNWAY_MIN_Q:.0f}"),
    )
    nd_high = _tagged(
        flags["E2"],
        pd.Series(
            [
                f"순부채/{b} {x:.1f}× > {ND_EBITDA_EXCLUDE:.0f}"
                for b, x in zip(nd_unit, nd, strict=True)
            ],
            index=frame.index,
        ),
    )
    wall_high = _tagged(
        flags["E3"],
        wall.map(lambda w: f"만기벽(12m 대용) {w:.2f} > {MATURITY_WALL_EXCLUDE}"),
    )
    out = pd.DataFrame(index=frame.index)
    out["reason"] = _join_nonempty(
        [no_fund, runway_na, runway_low, nd_na, nd_high, wall_high], " · "
    )
    out["excluded"] = out["reason"].str.len() > 0
    return out


def survival(frame: pd.DataFrame) -> pd.DataFrame:
    """S 원점수와 하위 항목. 열: s_raw, runway_score, leverage_score, penalty_score,
    penalties(str), n_penalties, n_penalty_evaluable, s_inputs_missing(str), s_partial(bool).

    **`s_raw` 는 가용 하위 항목 가중치를 재정규화한 값이다** — T·M 이 `T_MIN_INPUTS` 미만에서
    NaN 이 되는 것과 달리 S 는 하나만 있어도 값이 나온다. 그래서 `leverage_score` 가 NaN 인
    종목의 `s_raw` 는 순현금 기업과 **동률 최상위(1.00)** 가 될 수 있다 — 모름이 최상으로 보인다.
    `s_inputs_missing` 문자열만으로는 표·정렬에서 그 사실이 보이지 않아 2026-08-24 에
    `s_partial` 불리언을 붙였다 (`composite_partial` 과 같은 형식·같은 이유: 표시 없는
    재정규화는 조용한 절단이다).

    **재정규화 규칙 자체는 바꾸지 않았다** — 그것은 이 모듈 docstring 이 선언한 값이고,
    "모름을 어떤 점수로 둘 것인가" 는 새 선언이 필요하다 (`CLAUDE.md` §1). 열린 질문으로
    남긴다 (`docs/06` §8.4).
    """
    idx = frame.index
    runway = _num(frame["cash_runway_q"])
    runway_score = (runway / RUNWAY_CAP_Q).clip(0, 1)
    runway_score = runway_score.where(~np.isinf(runway), 1.0)
    nd = _num(frame["net_debt_ebitda"])
    leverage_score = (1 - (nd / ND_EBITDA_EXCLUDE).clip(0, 1)).where(nd.notna(), np.nan)

    ic = _num(frame["interest_coverage"])
    dil = _num(frame["dilution_3y"])
    adv = _num(frame["adv20_usd"])
    price = _num(frame["price"])
    flags = frame["red_flags"].fillna("").astype(str)
    has_fund = frame["fund_calendardate"].notna()

    checks: dict[str, tuple[pd.Series, pd.Series]] = {
        # name: (evaluable, triggered)
        "nd_ebitda_gt4": (nd.notna(), nd > ND_EBITDA_PENALTY),
        "interest_coverage_lt1": (ic.notna(), ic < INTEREST_COVERAGE_MIN),
        "dilution_gt15": (dil.notna(), dil > DILUTION_MAX),
        "adv_lt_2m": (adv.notna(), adv < ADV_MIN_USD),
        "price_lt_2": (price.notna(), price < PRICE_MIN),
    }
    for key in RED_FLAG_KEYS:
        checks[f"rf_{key}"] = (has_fund, flags.str.contains(key, regex=False))
    # 꺼진 감점은 **평가하지 않는다** — 분자에서도 분모에서도 빠진다 (`PENALTY_ENABLED`).
    # `adv`·`price` 는 위에서 계속 읽히고 특성 표에도 남는다 — 판정만 안 하는 것이다.
    checks = {k: v for k, v in checks.items() if PENALTY_ENABLED.get(k, True)}
    n_eval = pd.Series(0, index=idx, dtype=int)
    n_trig = pd.Series(0, index=idx, dtype=int)
    triggered: list[pd.Series] = []
    for name, (ev, tr) in checks.items():
        ev = ev.fillna(False).astype(bool)
        tr = (tr.fillna(False).astype(bool)) & ev
        n_eval = n_eval + ev.astype(int)
        n_trig = n_trig + tr.astype(int)
        triggered.append(_tagged(tr, name))
    penalty_score = (1 - n_trig / n_eval.replace(0, np.nan)).astype(float)

    parts = pd.DataFrame(
        {"runway": runway_score, "leverage": leverage_score, "penalty": penalty_score}
    )
    w = pd.Series(S_WEIGHTS)
    avail = parts.notna()
    wsum = avail.mul(w, axis=1).sum(axis=1)
    s_raw = parts.fillna(0).mul(w, axis=1).sum(axis=1) / wsum.replace(0, np.nan)

    out = pd.DataFrame(index=idx)
    out["s_raw"] = s_raw
    out["runway_score"] = runway_score
    out["leverage_score"] = leverage_score
    out["penalty_score"] = penalty_score
    out["penalties"] = _join_nonempty(triggered, ";")
    out["n_penalties"] = n_trig
    out["n_penalty_evaluable"] = n_eval
    out["s_inputs_missing"] = _join_nonempty([_tagged(~avail[c], c) for c in parts.columns], ",")
    #: 하위 항목이 하나라도 없으면 True — `s_raw` 가 재정규화된 값이라는 표시 (2026-08-24).
    out["s_partial"] = ~avail.all(axis=1)
    return out


def torque(frame: pd.DataFrame) -> pd.DataFrame:
    """T 원점수 = 가용 구성 요소 백분위(불리언 0/1) 평균.

    열: t_raw, t_n_inputs, t_inputs_missing, tp_<comp>."""
    idx = frame.index
    comps = pd.DataFrame(index=idx)
    for c in T_COMPONENTS:
        comps[c] = _bool01(frame[c]) if c in T_BOOLEAN else _pct(frame[c])
    n = comps.notna().sum(axis=1)
    t_raw = comps.mean(axis=1).where(n >= T_MIN_INPUTS, np.nan)
    out = pd.DataFrame(index=idx)
    out["t_raw"] = t_raw
    out["t_n_inputs"] = n
    out["t_inputs_missing"] = _join_nonempty([_tagged(comps[c].isna(), c) for c in comps], ",")
    for c in T_COMPONENTS:
        out[f"tp_{c}"] = comps[c]
    return out


def timing_components(frame: pd.DataFrame) -> pd.DataFrame:
    """M 축이 평균하는 6개 구성 요소 (index ticker · 열 `M_COMPONENTS`).

    `torque` 가 `tp_<comp>` 로 이미 내놓는 것의 M 판이다 — 백테스트의 지표 단독 IC(`docs/14` §1 Q4)
    가 축이 실제로 먹는 값을 읽어야 하기 때문에 함수로 뺐다. `timing` 이 이것을 그대로 평균한다.
    """
    comps = pd.DataFrame(index=frame.index)
    for c in M_BOOLEAN:
        comps[c] = _bool01(frame[c])
    comps["rs_rating"] = _num(frame["rs_rating"]) / 100.0
    for c in M_PCT:
        comps[c] = _pct(frame[c])
    return comps[list(M_COMPONENTS)]


def timing(frame: pd.DataFrame) -> pd.DataFrame:
    """M 원점수. 열: m_raw, m_n_inputs, m_inputs_missing.

    `m_inputs_missing` 은 `torque` 의 `t_inputs_missing` · `survival` 의 `s_inputs_missing` 과
    **같은 형식**이다 (쉼표로 이은 결측 구성 요소 이름). 2026-08-24 에 추가했다 — M 만 없어서
    "왜 이 종목의 M 이 NaN 인가" 를 산출물에서 답할 수 없었다. `m_n_inputs` 는 그 전부터
    계산되고 있었으나 아무 로직도 읽지 않는 **관찰용**이고, 그 지위는 그대로다.
    """
    comps = timing_components(frame)
    n = comps.notna().sum(axis=1)
    out = pd.DataFrame(index=frame.index)
    out["m_raw"] = comps.mean(axis=1).where(n >= M_MIN_INPUTS, np.nan)
    out["m_n_inputs"] = n
    out["m_inputs_missing"] = _join_nonempty([_tagged(comps[c].isna(), c) for c in comps], ",")
    return out


def score(frame: pd.DataFrame) -> pd.DataFrame:
    """적격(하드 필터 통과) 표 → 3축 원점수·백분위·종합·순위. 결정론.

    **관찰 지표다 — `composite` 도 `rank` 도 무엇을 사는지를 정하지 않는다** (2026-08-24,
    모듈 docstring). 선정은 이 함수가 불리기 전에 `hard_filters` 가 끝냈고, 남은 종목은
    전부 동일가중이다. `rank` 는 리포트·다이제스트의 표시 순서이고, 그 순서를 사람이 잘라
    쓰기로 한다면 그것은 새 사전 등록이 필요한 별개 결정이다 (`docs/06` §6.2).
    """
    _check_columns(frame)
    s = survival(frame)
    t = torque(frame)
    m = timing(frame)
    out = pd.concat([s, t, m], axis=1)
    out["s_pct"] = _pct(out["s_raw"])
    out["t_pct"] = _pct(out["t_raw"])
    out["m_pct"] = _pct(out["m_raw"])
    axes = out[["s_pct", "t_pct", "m_pct"]].rename(
        columns={"s_pct": "S", "t_pct": "T", "m_pct": "M"}
    )
    w = pd.Series(AXIS_WEIGHTS)
    avail = axes.notna()
    wsum = avail.mul(w, axis=1).sum(axis=1)
    out["composite"] = axes.fillna(0).mul(w, axis=1).sum(axis=1) / wsum.replace(0, np.nan)
    out["composite_partial"] = ~avail.all(axis=1)
    # 순위: 종합 ↓ → S̃ ↓ → 티커 ↑. NaN 은 맨 뒤 — 결정론
    out = (
        out.assign(_tk=out.index.astype(str))
        .sort_values(
            ["composite", "s_pct", "_tk"], ascending=[False, False, True], na_position="last"
        )
        .drop(columns="_tk")
    )
    out["rank"] = np.arange(1, len(out) + 1)
    return out


def declared_constants() -> dict[str, Any]:
    """meta.json 에 싣는 선언값 — 무엇을 어떤 값으로 돌렸는지 산출물에 남긴다."""
    return {
        "hard": {
            "runway_min_q": RUNWAY_MIN_Q,
            "nd_ebitda_exclude": ND_EBITDA_EXCLUDE,
            "maturity_wall_exclude": MATURITY_WALL_EXCLUDE,
            "going_concern": "input unavailable",
        },
        "penalty": {
            "nd_ebitda_penalty": ND_EBITDA_PENALTY,
            "interest_coverage_min": INTEREST_COVERAGE_MIN,
            "dilution_max": DILUTION_MAX,
            "adv_min_usd": ADV_MIN_USD,
            "price_min": PRICE_MIN,
            "red_flags": [k for k in PENALTY_ITEMS if k.startswith("rf_")],
            "enabled": dict(PENALTY_ENABLED),
            "disabled": list(DISABLED_PENALTIES),
            "disabled_note": disabled_penalty_note() or "없음 — 선언된 감점 전부를 적용했다",
        },
        "s_weights": S_WEIGHTS,
        "runway_cap_q": RUNWAY_CAP_Q,
        "t_components": list(T_COMPONENTS),
        "t_min_inputs": T_MIN_INPUTS,
        "m_min_inputs": M_MIN_INPUTS,
        "m_components": [*M_BOOLEAN, "rs_rating", *M_PCT],
        "axis_weights": AXIS_WEIGHTS,
        "axis_weights_role": "관찰 지표(composite) 전용 — 선정에 쓰이지 않는다 (2026-08-24)",
        "selection_rule": "하드 제외 통과 전부 · 테마 내 동일가중",
    }
