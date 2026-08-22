"""기각 대장 — 12·24M 갱신 · 세 질문 집계 (합성 지수)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from msa.ops.rejections import (
    forward_return,
    question_c,
    summarize,
    theme_index_from_returns,
    update_returns,
)
from msa.ops.state_files import Rejection, load_rejections, save_rejections


def _index(end: str = "2028-12-31") -> pd.DataFrame:
    idx = pd.bdate_range("2025-01-01", end)
    rng = np.random.default_rng(0)
    ret = pd.DataFrame(
        {
            "winner": 0.0008 + 0.01 * rng.standard_normal(len(idx)),
            "loser": -0.0008 + 0.01 * rng.standard_normal(len(idx)),
            "flat": 0.0 * rng.standard_normal(len(idx)),
        },
        index=idx,
    )
    return theme_index_from_returns(ret)


def _rej(theme: str, when: date, path: str = "hard_gate", **over: object) -> Rejection:
    kw: dict[str, object] = {
        "theme": theme,
        "rejected_at": when,
        "path": path,
        "reason": "r",
        "cycle_confidence": None,
        "scoreboard_rank": 3,
        "journal": f"journal/{when}-{theme}-reject.md",
        "scan": f"state/scans/{when}/",
    }
    kw.update(over)
    return Rejection(**kw)  # type: ignore[arg-type]


def test_forward_return_and_update_only_elapsed_horizons() -> None:
    idx = _index()
    assert forward_return(idx, "flat", date(2026, 1, 5), 12) == pytest.approx(0.0)
    assert forward_return(idx, "nope", date(2026, 1, 5), 12) is None
    assert forward_return(idx, "winner", date(2028, 6, 1), 12) is None  # 끝점 없음
    rows = [_rej("winner", date(2026, 3, 2)), _rej("loser", date(2027, 9, 1))]
    out = update_returns(rows, idx, asof=date(2027, 6, 30))
    assert out[0].r_12m is not None and out[0].r_24m is None  # 24M 미도래
    assert out[1].r_12m is None  # 12M 미도래
    out2 = update_returns(out, idx, asof=date(2028, 12, 31))
    assert out2[0].r_24m is not None and out2[1].r_12m is not None
    assert out2[0].r_12m == out[0].r_12m  # 이미 채운 값은 그대로


def test_summarize_writes_three_questions_and_respects_immutability(tmp_path: Path) -> None:
    idx = _index()
    jdir = tmp_path / "journal"
    jdir.mkdir()
    scans = tmp_path / "state" / "scans"
    for d in ("2026-03-02", "2026-09-01"):
        sd = scans / d
        sd.mkdir(parents=True)
        pd.DataFrame(
            {"rank": [1, 2, 9, 10, 11]},
            index=pd.Index(["winner", "flat", "loser", "flat", "winner"], name="theme"),
        ).to_csv(sd / "scoreboard.csv")
    axis1 = pd.DataFrame(
        {"verdict_post_ss": ["death", "cycle"], "unit_cagr_10y": [-0.05, 0.01]},
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2027-09-30"), "loser"), (pd.Timestamp("2027-09-30"), "winner")],
            names=["date", "theme"],
        ),
    )
    rows = [
        _rej("loser", date(2026, 3, 2), "hard_gate", axis_verdicts={"unit_demand": "death"}),
        _rej("loser", date(2026, 9, 1), "secular_risk", axis_verdicts={"unit_demand": "death"}),
        _rej("flat", date(2026, 3, 2), "rank_cutoff", scoreboard_rank=9),
    ]
    s = summarize(rows, index=idx, axis1=axis1, jdir=jdir, scans_dir=scans, asof=date(2028, 3, 1))
    assert "내부 감사 기록" in s.text
    assert "### (a)" in s.text and "### (b)" in s.text and "### (c)" in s.text
    assert "hard_gate" in s.text and s.n_filled_12m == 3 and s.n_filled_24m == 0
    assert "verdict_post_ss=death" in s.text  # (b) 사후 축1
    assert "2026-03-02: 상위 2 · 9~15위 3" in s.text  # (c) 순위 스냅샷
    assert "임계값·가중치·K·C6 을 조정하지 않는다" in s.text
    # 파일로 저장 → 불변 규칙 통과 (null → 값)
    p = tmp_path / "state" / "rejections.yaml"
    save_rejections(p, rows)
    save_rejections(p, s.updated_rows)
    assert load_rejections(p)[0].r_12m is not None


def test_question_c_without_scans_dir_says_so(tmp_path: Path) -> None:
    lines = question_c(tmp_path / "none", _index(), date(2028, 1, 1))
    assert any("없음" in ln for ln in lines)
