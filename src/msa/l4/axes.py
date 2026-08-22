"""3축 점수와 하드 제외 필터 — `docs/06-stock-selection.md` §2·§3·§4·§6. 순수 함수.

입력은 `features.FeatureSet.frame`(index ticker) 이고 출력은 같은 index 의 점수 표다.
스토어를 모른다 — 그래서 합성 표로 전부 테스트된다.

## 선언값 (`CLAUDE.md` §1 — 데이터에 맞춰 바꾸지 않는다)

문서가 준 것 (그대로):
- 하드 제외: 런웨이 < 4분기 · 순부채/EBITDA > 6× · 만기벽 > 0.5 · 계속기업 의문(**입력 없음**)
- 감점: 순부채/EBITDA > 4× · 이자보상배율 < 1 · 희석 3y > 15%/y · 20일 거래대금 < $2M · 종가 < $2
- 종합: `0.40·S̃ + 0.40·T̃ + 0.20·M̃`

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
- 런웨이 판정 불가 — 현금흐름표가 없어 런웨이가 NaN 이면 **하드 제외** (사유 표기). 하드 필터를
  평가할 수 없는 종목을 통과시키면 필터가 있는 척하는 것이다 — 재무 없음과 같은 처리.
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

# ---- 문서 선언값 (docs/06 §2)
RUNWAY_MIN_Q = 4.0
ND_EBITDA_EXCLUDE = 6.0
ND_EBITDA_PENALTY = 4.0
MATURITY_WALL_EXCLUDE = 0.5
INTEREST_COVERAGE_MIN = 1.0
DILUTION_MAX = 0.15
ADV_MIN_USD = 2_000_000.0
PRICE_MIN = 2.0

# ---- 여기서 선언한 값 (모듈 docstring 표)
RUNWAY_CAP_Q = 8.0
S_WEIGHTS = {"runway": 0.40, "leverage": 0.30, "penalty": 0.30}
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

assert abs(sum(S_WEIGHTS.values()) - 1.0) < 1e-9
assert abs(sum(AXIS_WEIGHTS.values()) - 1.0) < 1e-9

#: 하드 필터 사유 문구 (테스트·`excluded.csv` 가 이 문자열을 본다)
_REASON_NO_SF1 = "재무 없음 (SF1 에 행 0개 — 20-F 해외발행사 등 미수록) — 생존 필터 판정 불가"
_REASON_STALE = "재무 없음 (asof 이전 15개월 내 분기 없음) — 생존 필터 판정 불가"
_REASON_RUNWAY_NA = "런웨이 판정 불가 (현금흐름표 또는 현금 없음) — 하드 필터 미통과"


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


def hard_filters(frame: pd.DataFrame) -> pd.DataFrame:
    """하드 제외 판정. 반환 index ticker: `excluded`(bool), `reason`(str; 복수는 ' · ' 로 연결).

    재무가 없는(신선도 탈락) 종목도 제외한다 — 생존 필터를 **평가할 수 없는** 종목을 통과시키면
    필터가 있는 척하는 것이다. 사유에 그렇게 적는다. `going_concern` 은 입력이 없어 적용하지 못한다.
    """
    _check_columns(frame)
    has_fund = frame["fund_calendardate"].notna()
    runway = _num(frame["cash_runway_q"])
    nd = _num(frame["net_debt_ebitda"])
    wall = _num(frame["maturity_wall_12m"])
    no_sf1 = frame["fund_status"].astype(str) == FundStatus.NONE
    nd_unit = (frame["nd_basis"] == "ebitda").map({True: "EBITDA", False: "시총(EBITDA≤0 대체)"})

    no_fund = _tagged(~has_fund, np.where(no_sf1, _REASON_NO_SF1, _REASON_STALE))
    runway_na = _tagged(has_fund & runway.isna(), _REASON_RUNWAY_NA)
    runway_low = _tagged(
        has_fund & (runway < RUNWAY_MIN_Q),
        runway.map(lambda r: f"런웨이 {r:.2f}분기 < {RUNWAY_MIN_Q:.0f}"),
    )
    nd_high = _tagged(
        has_fund & (nd > ND_EBITDA_EXCLUDE),
        pd.Series(
            [
                f"순부채/{b} {x:.1f}× > {ND_EBITDA_EXCLUDE:.0f}"
                for b, x in zip(nd_unit, nd, strict=True)
            ],
            index=frame.index,
        ),
    )
    wall_high = _tagged(
        has_fund & (wall > MATURITY_WALL_EXCLUDE),
        wall.map(lambda w: f"만기벽(12m 대용) {w:.2f} > {MATURITY_WALL_EXCLUDE}"),
    )
    out = pd.DataFrame(index=frame.index)
    out["reason"] = _join_nonempty([no_fund, runway_na, runway_low, nd_high, wall_high], " · ")
    out["excluded"] = out["reason"].str.len() > 0
    return out


def survival(frame: pd.DataFrame) -> pd.DataFrame:
    """S 원점수와 하위 항목. 열: s_raw, runway_score, leverage_score, penalty_score,
    penalties(str), n_penalties, n_penalty_evaluable, s_inputs_missing(str)."""
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


def timing(frame: pd.DataFrame) -> pd.DataFrame:
    """M 원점수. 열: m_raw, m_n_inputs."""
    idx = frame.index
    comps = pd.DataFrame(index=idx)
    for c in M_BOOLEAN:
        comps[c] = _bool01(frame[c])
    comps["rs_rating"] = _num(frame["rs_rating"]) / 100.0
    for c in M_PCT:
        comps[c] = _pct(frame[c])
    n = comps.notna().sum(axis=1)
    out = pd.DataFrame(index=idx)
    out["m_raw"] = comps.mean(axis=1).where(n >= M_MIN_INPUTS, np.nan)
    out["m_n_inputs"] = n
    return out


def score(frame: pd.DataFrame) -> pd.DataFrame:
    """적격(하드 필터 통과) 표 → 3축 원점수·백분위·종합·순위. 결정론."""
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
        },
        "s_weights": S_WEIGHTS,
        "runway_cap_q": RUNWAY_CAP_Q,
        "t_components": list(T_COMPONENTS),
        "t_min_inputs": T_MIN_INPUTS,
        "m_min_inputs": M_MIN_INPUTS,
        "m_components": [*M_BOOLEAN, "rs_rating", *M_PCT],
        "axis_weights": AXIS_WEIGHTS,
    }
