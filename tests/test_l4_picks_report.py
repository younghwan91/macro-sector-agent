"""명단의 **표시** — 판단 재료 열 순서 · 명단 표 · 제외 · 논지 머리.

2026-08-24 에 붙은 것들이다. 전부 표시이고 어떤 판정도 하지 않는다 — 그래서 순수 함수로
테스트된다 (스토어도 FeatureSet 도 필요 없다).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from msa.l4 import picks
from msa.thesis import NO_THESIS_NOTE, dump_thesis_yaml, thesis_head


def _row(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "group": picks.SELECTION_GROUP,
        "barbell_obs": "",
        "rank": 1,
        "composite": 0.5,
        "name": "TEST CO",
        "mcap": 1.23e9,
        "price": 15.05,
        "adv20_usd": 850_100.0,
        "net_debt_ebitda": 3.1,
        "nd_basis": "ebitda",
        "cash_runway_q": 8.0,
        "from_52w_high": -0.34,
        "from_52w_low": 0.29,
        "rs_rating": 45.0,
        "stage2": True,
        "above_50d": False,
        "vcp_base": None,
        "penalties": "",
        "red_flags": "",
        "s_partial": False,
        "composite_partial": False,
    }
    base.update(kw)
    return base


def _ranking(**rows: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(list(rows.values()), index=pd.Index(list(rows), name="ticker"))


def test_judgment_columns_come_first_and_nothing_is_dropped() -> None:
    """판단 재료가 앞으로 온다. **열은 하나도 버리지 않는다** — 순서만 바뀐다."""
    df = _ranking(AAA=_row()).assign(t_pct=0.3, s_inputs_missing="")
    out = picks.order_ranking_columns(df)
    assert set(out.columns) == set(df.columns)
    cols = list(out.columns)
    assert cols[:3] == ["group", "barbell_obs", "rank"]
    assert cols[3 : 3 + len(picks.JUDGMENT_COLUMNS)] == list(picks.JUDGMENT_COLUMNS)
    # 손익비 판단의 핵심 열이 명단 앞에 있다 (2026-08-24 사용자 지시)
    assert "from_52w_high" in picks.JUDGMENT_COLUMNS
    # 유동성 감점은 껐지만 열은 남는다 — 감점만 껐지 정보를 뺀 것이 아니다
    assert "adv20_usd" in picks.JUDGMENT_COLUMNS


def test_judgment_table_shows_the_material_a_person_reads_first() -> None:
    df = _ranking(
        WLKP=_row(mcap=1.2e9, net_debt_ebitda=3.1, cash_runway_q=8.0, from_52w_high=-0.34),
        GURE=_row(
            rank=2,
            mcap=3e8,
            net_debt_ebitda=0.4,
            nd_basis="mcap",
            cash_runway_q=float("inf"),
            from_52w_high=-0.51,
            rs_rating=31.0,
            penalties="dilution_gt15",
            red_flags="zombie_streak",
            stage2=False,
            vcp_base=True,
        ),
    )
    lines = picks.judgment_table(df)
    head, body = lines[0], "\n".join(lines[2:])
    for h in ("종목", "시총", "ADV20", "ND/EBITDA", "런웨이", "52wH", "RS", "비고"):
        assert h in head, h
    assert "$1.2B" in body and "-34%" in body and "8.0Q" in body
    # basis 가 칸 안에 있다 — EBITDA 공간과 시총 공간을 같은 축으로 읽으면 안 된다
    assert "3.1x" in body and "0.4x(시총)" in body
    assert "∞" in body  # FCF ≥ 0 런웨이
    assert "감점[dilution_gt15]" in body and "레드플래그[zombie_streak]" in body
    # vcp_base 는 결함 표시가 붙은 이름으로만 나온다
    assert "VCP*" in body and picks.VCP_DEFECT_NOTE.startswith("VCP*")


def test_excluded_lines_name_every_stock_and_its_reason() -> None:
    ex = pd.DataFrame(
        {"stage": ["hard_filter", "listing"], "reason": ["런웨이 1.1분기 < 4", "폐지"]},
        index=pd.Index(["ASIX", "ZY"], name="ticker"),
    )
    out = "\n".join(picks.excluded_lines(ex))
    assert "제외 2" in out and "hard_filter 1" in out and "listing 1"
    assert "ASIX" in out and "런웨이 1.1분기 < 4" in out
    assert "ZY" in out and "폐지" in out
    assert picks.excluded_lines(pd.DataFrame()) == ["  제외 0"]


def test_thesis_head_reads_claim_and_invalidations(tmp_path: Path) -> None:
    root = tmp_path / "theses"
    dump_thesis_yaml(
        root / "2026-08-10" / "commodity_chem.thesis.yaml",
        {
            "theme_id": "commodity_chem",
            "claim": "공급 순증 14.6Mt vs 유럽 감축 505kt",
            "horizon_months": [24, 60],
            "cycle_confidence": 0.7,
            "gate_result": {"status": "passed"},
            "invalidations": [{"observable": "중국 신증설 상향"}, {"observable": "수요 0% 이하"}],
        },
    )
    h = thesis_head("commodity_chem", "2026-08-14", root)
    assert h.found
    txt = "\n".join(h.lines())
    assert "공급 순증 14.6Mt" in txt
    assert "무효화 조건:" in txt and "중국 신증설 상향" in txt and "수요 0% 이하" in txt
    assert "지평 24~60개월" in txt and "확신도 0.7" in txt and "게이트 passed" in txt


def test_thesis_head_is_pit_and_says_so_when_missing(tmp_path: Path) -> None:
    """asof **이후**에 쓰인 논지는 찾지 않는다. 없으면 없다고 적는다 — 빈 줄을 두지 않는다."""
    root = tmp_path / "theses"
    dump_thesis_yaml(
        root / "2026-08-23" / "t.thesis.yaml",
        {"theme_id": "t", "claim": "미래의 논지", "invalidations": [{"observable": "x"}]},
    )
    later = thesis_head("t", "2026-08-14", root)
    assert not later.found
    assert later.lines() == [f"논지: {NO_THESIS_NOTE}"]
    assert thesis_head("t", "2026-08-23", root).found


@pytest.mark.parametrize(
    ("value", "want"),
    [(1.23e9, "$1.2B"), (4.2e6, "$4.2M"), (850_100.0, "$850.1K"), (None, "n/a")],
)
def test_usd_compact(value: Any, want: str) -> None:
    assert picks._usd_compact(value) == want
