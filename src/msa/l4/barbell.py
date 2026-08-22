"""앵커/토크 바벨 분류 — `docs/06-stock-selection.md` §5·§6. 순수 함수.

문서 규칙 (그대로):
- 앵커: `S̃` 상위에서 `T̃` 가 가장 높은 것
- 토크: `T̃` 상위에서 `S̃` 하위 25% 를 뺀 것
- 테마당 2~4 종목. 앵커 0% 를 금지하지 않되 **비율을 보이게** 한다

문서가 비워 둔 것 — 선언:
- "S̃ 상위" = `s_pct ≥ 0.5` (상위 절반). 문서가 컷을 주지 않았다. 중앙값은 표본 크기에 무관하게
  정의된다.
- 앵커 추가 조건 — `marginal_producer` 가 True 가 아닐 것. §5 "저비용 생산자" — 한계생산자는
  정의상 저비용이 아니다.
- 종목 수 배분 — `n_anchor = max(1, top // 2)`, 나머지 토크. 앵커 후보가 모자라면 토크로 채우고
  비율에 드러난다. §5 비중 55~70% / 30~45% 를 **수**로 옮기면 절반 전후. 비중 자체는 L5 가 정한다.
- 토크의 `S̃` 하위 25% = `s_pct ≤ 0.25` 제외. 문서 그대로.
- 토크는 `T̃` 가 계산된 종목만 — T̃ 가 NaN 인 종목은 "T̃ 상위" 일 수 없다. 앵커는 S 가 1차
  기준이라 T̃ NaN 을 맨 뒤로 보낼 뿐 배제하지 않는다. 후보가 모자라면 토크 자리는 비고
  비율에 드러난다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

ANCHOR_S_MIN = 0.5
TORQUE_S_EXCLUDE_LE = 0.25
DEFAULT_TOP = 4


@dataclass(frozen=True)
class Barbell:
    anchors: list[str]
    torques: list[str]

    @property
    def n(self) -> int:
        return len(self.anchors) + len(self.torques)

    @property
    def anchor_share(self) -> float:
        return len(self.anchors) / self.n if self.n else math.nan

    def label(self, ticker: str) -> str:
        if ticker in self.anchors:
            return "ANCHOR"
        if ticker in self.torques:
            return "TORQUE"
        return ""


def classify(scored: pd.DataFrame, top: int = DEFAULT_TOP) -> Barbell:
    """`axes.score()` 출력(index ticker; s_pct·t_pct·marginal_producer 필요)에서 앵커/토크를
    고른다."""
    if top < 1:
        raise ValueError("top 은 1 이상이어야 한다")
    df = scored.copy()
    if df.empty:
        return Barbell([], [])
    mp = (
        df["marginal_producer"].astype("boolean")
        if "marginal_producer" in df
        else pd.Series(pd.NA, index=df.index, dtype="boolean")
    )
    not_marginal = ~(mp.fillna(False).astype(bool))
    t_order = df.sort_values(["t_pct", "s_pct"], ascending=[False, False], kind="mergesort")
    # 동률·NaN 결정론: t_pct NaN 은 맨 뒤, 그 다음 티커 오름차순
    t_order = t_order.assign(_tk=t_order.index.astype(str)).sort_values(
        ["t_pct", "s_pct", "_tk"],
        ascending=[False, False, True],
        na_position="last",
        kind="mergesort",
    )
    n_anchor = max(1, top // 2)
    anchor_pool = t_order.loc[
        (t_order["s_pct"] >= ANCHOR_S_MIN) & not_marginal.reindex(t_order.index)
    ]
    anchors = [str(t) for t in anchor_pool.index[:n_anchor]]
    torque_pool = t_order.loc[
        (t_order["s_pct"] > TORQUE_S_EXCLUDE_LE)
        & t_order["t_pct"].notna()
        & ~t_order.index.isin(anchors)
    ]
    torques = [str(t) for t in torque_pool.index[: top - len(anchors)]]
    return Barbell(anchors=anchors, torques=torques)
