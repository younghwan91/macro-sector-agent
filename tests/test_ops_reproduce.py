"""스캔 스냅샷 재현 — 저장 파일만으로 report.txt 를 다시 만든다."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from msa.l1.scan import render_report
from msa.l1.scoreboard import Scoreboard
from msa.ops.reproduce import reproduce


def _snapshot(d: Path) -> None:
    themes = ["uranium", "copper", "gold"]
    table = pd.DataFrame(
        {
            "rank": [1.0, 2.0, 3.0],
            "cycle_class": ["commodity_supply"] * 3,
            "score": [0.81, 0.66, 0.52],
            **{f"{b}_pct": [0.9, 0.6, 0.3] for b in "ABCDEF"},
            "flags": ["", "[SECULAR]", ""],
            "small_sample": [False, False, True],
        },
        index=pd.Index(themes, name="theme"),
    )
    ipct = pd.DataFrame({"dd_10y": [0.9, 0.5, 0.1]}, index=pd.Index(themes, name="theme"))
    cov = pd.DataFrame({"n_live": [10, 8, 3]}, index=pd.Index(themes, name="theme"))
    meta = {
        "asof": "2026-08-14",
        "bucket": "2026-08-31",
        "membership": "3 themes",
        "unclassified_mcap": {"share": 0.012, "denominator_musd": 1000.0},
        "panel": {"n_capped_total": 5},
        "small_sample_buckets": ["gold"],
        "etf_proxy": {"corr_gt_0.85_share": 0.5, "with_proxy": 2, "corr_missing": 0},
        "physical": {"declared": 2, "data_ok": 1, "data_missing": 1, "cpi": "ok"},
        "ebitda_nonpos_share_median": 0.2,
        "indicators": {"unavailable_indicators": [], "unavailable_reason": "-"},
    }
    sb = Scoreboard(date=pd.Timestamp(meta["bucket"]), table=table, indicator_pct=ipct, meta={})
    d.mkdir(parents=True)
    table.to_csv(d / "scoreboard.csv")
    ipct.to_csv(d / "indicator_pct.csv")
    cov.to_csv(d / "coverage.csv")
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
    (d / "report.txt").write_text(render_report(sb, cov, meta), encoding="utf-8")


def test_reproduce_from_snapshot_is_identical(tmp_path: Path) -> None:
    d = tmp_path / "scans" / "2026-08-14"
    _snapshot(d)
    r = reproduce(d)
    assert r.identical and "uranium" in r.rendered and "투자 조언이 아니며" in r.rendered
    # 보관본이 손대어졌으면 다르다고 말한다
    (d / "report.txt").write_text(r.stored + "\n편집\n", encoding="utf-8")
    r2 = reproduce(d)
    assert not r2.identical and r2.diff_lines()


def test_reproduce_refuses_incomplete_snapshot(tmp_path: Path) -> None:
    d = tmp_path / "scans" / "2026-08-14"
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{}")
    with pytest.raises(FileNotFoundError, match="누락"):
        reproduce(d)
