"""배선 W1 — L4 `ranking.csv` + L3 thesis → L5 입력 묶음 (`msa.pipeline.assemble`).

합성 표로 역할 매핑·제외 장부·논지 매핑(`cycle_confidence_source`)·게이트 편입 불가 제외·
계약 왕복(`load_picks`/`load_theses`/`load_inputs` → `build_portfolio`)을 검사한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from conftest import make_thesis
from msa.config import paths
from msa.l5.inputs import InputError, load_inputs, load_picks, load_theses, parse_thesis
from msa.pipeline.assemble import (
    OMITTED_COLUMNS,
    PICKS_COLUMNS,
    AssembleError,
    assemble_inputs,
    picks_csv_from_rankings,
    thesis_input_from_l3,
)
from msa.thesis import dump_thesis_yaml, thesis_filename

ASOF = "2026-08-22"

# ---------------------------------------------------------------- 도우미


def _ranking(rows: list[tuple[str, str, float, float, float]], **extra: Any) -> pd.DataFrame:
    """(ticker, group, composite, price, adv20) → L4 `ranking.csv` 꼴 (index ticker, rank 순)."""
    df = pd.DataFrame(
        [
            {
                "group": g,
                "rank": i + 1,
                "composite": c,
                "composite_partial": False,
                "s_pct": 0.5,
                "t_pct": 0.6,
                "m_pct": 0.4,
                "price": px,
                "adv20_usd": adv,
                "penalties": "",
                "red_flags": "",
                "s_inputs_missing": "",
                "t_inputs_missing": "",
                **extra,
            }
            for i, (_t, g, c, px, adv) in enumerate(rows)
        ],
        index=pd.Index([r[0] for r in rows]),
    )
    return df


def _write_ranking(root: Path, day: str, theme: str, df: pd.DataFrame) -> Path:
    d = root / day / theme
    d.mkdir(parents=True, exist_ok=True)
    df.to_csv(d / "ranking.csv")  # L4 write_snapshot 과 같이 index 포함
    return d / "ranking.csv"


def _write_thesis(root: Path, day: str, thesis: dict[str, Any]) -> Path:
    return dump_thesis_yaml(root / day / thesis_filename(thesis["theme_id"]), thesis)


def _state(tmp_path: Path) -> tuple[Path, Path, Path]:
    picks = tmp_path / "picks"
    theses = tmp_path / "theses"
    out = tmp_path / "portfolio_inputs"
    return picks, theses, out


# ---------------------------------------------------------------- picks 매핑


def test_role_mapping_and_exclusions_are_counted() -> None:
    rk_u = _ranking(
        [
            ("CCJ", "ANCHOR", 0.8, 50.0, 3e8),
            ("UEC", "TORQUE", 0.7, 6.0, 5e7),
            ("URG", "", 0.5, 1.0, 1e6),  # 순위만 — 바벨 미배정
            ("FNV", "ROYALTY", 0.4, 100.0, 1e8),  # L4 가 내지 않는 라벨 — 매핑 없음
        ]
    )
    rk_g = _ranking([("CCJ", "ANCHOR", 0.9, 50.0, 3e8), ("PWR", "TORQUE", 0.6, 200.0, 4e8)])
    pa = picks_csv_from_rankings({"uranium": rk_u, "grid_equipment": rk_g})
    f = pa.frame
    assert list(f.columns) == list(PICKS_COLUMNS)
    assert f["ticker"].tolist() == ["CCJ", "UEC", "PWR"]
    assert f["role"].tolist() == ["anchor", "torque", "torque"]
    assert f["theme"].tolist() == ["uranium", "uranium", "grid_equipment"]
    assert f.loc[0, "entry_price"] == 50.0 and f.loc[0, "adv20_usd"] == 3e8
    assert f.loc[0, "rank_score"] == 0.8
    assert "L4 #1 ANCHOR" in f.loc[0, "notes"]
    # 제외는 수와 사유로
    assert pa.counts == {
        "group 매핑 없음: ROYALTY": 1,
        "바벨 미배정 (group 비어 있음)": 1,
        "티커 중복 — 이미 uranium 에 배정": 1,
    }
    assert set(pa.excluded["ticker"]) == {"URG", "FNV", "CCJ"}
    assert pa.themes_without_picks == ()
    assert set(pa.columns_omitted) == set(OMITTED_COLUMNS)
    # 계약 밖 열은 쓰지 않았다
    assert not {"idio_vol_ann", "split_first_leg", "tp_p50_price"} & set(f.columns)


def test_top_per_theme_and_empty_theme() -> None:
    rk = _ranking(
        [
            ("A", "ANCHOR", 0.9, 10.0, 1e7),
            ("B", "ANCHOR", 0.8, 10.0, 1e7),
            ("C", "TORQUE", 0.7, 10.0, 1e7),
        ]
    )
    only_ranked = _ranking([("Z", "", 0.3, 1.0, 1e6)])
    pa = picks_csv_from_rankings({"t1": rk, "t2": only_ranked}, top_per_theme=2)
    assert pa.frame["ticker"].tolist() == ["A", "B"]
    assert pa.counts["top_per_theme=2 초과"] == 1
    assert pa.themes_without_picks == ("t2",)
    with pytest.raises(AssembleError):
        picks_csv_from_rankings({"t1": rk}, top_per_theme=0)


def test_missing_value_columns_are_reported_not_invented() -> None:
    rk = _ranking([("A", "ANCHOR", 0.9, 10.0, 1e7)]).drop(columns=["price", "adv20_usd"])
    pa = picks_csv_from_rankings({"t1": rk})
    assert pa.missing_inputs == {"t1": ("price", "adv20_usd")}
    assert pd.isna(pa.frame.loc[0, "entry_price"]) and pd.isna(pa.frame.loc[0, "adv20_usd"])


def test_non_l4_frame_is_refused() -> None:
    with pytest.raises(AssembleError, match="L4 산출물이 아니다"):
        picks_csv_from_rankings({"t1": pd.DataFrame({"x": [1]}, index=["A"])})


def test_picks_frame_round_trips_through_load_picks(tmp_path: Path) -> None:
    rk = _ranking([("CCJ", "ANCHOR", 0.8, 50.0, 3e8), ("UEC", "TORQUE", 0.7, 6.0, 5e7)])
    pa = picks_csv_from_rankings({"uranium": rk})
    p = tmp_path / "picks.csv"
    pa.frame.to_csv(p, index=False)
    picks = load_picks(p)
    assert [x.ticker for x in picks] == ["CCJ", "UEC"]
    assert picks[0].role == "anchor" and picks[0].is_anchor
    assert picks[0].entry_price == 50.0 and picks[0].adv20_usd == 3e8
    assert picks[0].rank_score == 0.8 and picks[0].idio_vol_ann is None
    assert picks[0].split_first_leg is False and picks[0].min_weight == 0.0


def test_read_ranking_path_input(tmp_path: Path) -> None:
    rk = _ranking([("CCJ", "ANCHOR", 0.8, 50.0, 3e8)])
    path = _write_ranking(tmp_path, "2026-08-14", "uranium", rk)
    pa = picks_csv_from_rankings({"uranium": path})
    assert pa.frame["ticker"].tolist() == ["CCJ"]


# ---------------------------------------------------------------- thesis 매핑


def test_thesis_input_from_l3_round_trips_through_parse_thesis() -> None:
    t = make_thesis()
    t["inputs"] = {"macro_tailwind": 0.41}
    t["cycle_confidence_by"] = "referee-pipeline (04 §4 기계 적용)"
    m = thesis_input_from_l3(t, confidence_source="referee", source_path="state/x.yaml")
    assert m["cycle_confidence_source"] == "referee"
    assert m["tailwind"] == 0.41
    assert m["gate_result"] == {
        "status": "passed",
        "portfolio_eligible": True,
        "rule": t["gate_result"]["rule"],
    }
    assert m["value_trap_axes"] == {
        "unit_demand": {
            "verdict": "cycle",
            "axis1_available": True,
            "unit_series_source": "physical_series",
        }
    }
    assert "evidence" not in m and "bear_case" not in m
    assert m["assembled_from"] == "state/x.yaml"
    # 트리거/무효화 항목은 부분집합 — `check` 같은 운영 키는 옮기지 않는다
    assert all("check" not in x for x in m["triggers"])
    ti = parse_thesis(m, where="t")
    assert ti.theme == "uranium" and ti.confidence_source == "referee"
    assert ti.cycle_confidence == 0.72 and ti.horizon_months == (6, 18)
    assert len(ti.invalidations) == 2 and len(ti.triggers) == 3
    assert ti.tailwind == 0.41 and ti.portfolio_eligible and ti.axis1_available is True


def test_thesis_input_declared_provenance_wins() -> None:
    t = make_thesis(confidence_provenance="human")
    assert thesis_input_from_l3(t, confidence_source="human")["cycle_confidence_source"] == "human"
    # 위치로는 referee 라도 yaml 의 선언이 이긴다
    assert (
        thesis_input_from_l3(t, confidence_source="referee")["cycle_confidence_source"] == "human"
    )
    t2 = make_thesis(cycle_confidence_source="referee")
    assert (
        thesis_input_from_l3(t2, confidence_source="human")["cycle_confidence_source"] == "referee"
    )
    with pytest.raises(AssembleError, match="허용값"):
        thesis_input_from_l3(make_thesis(), confidence_source="llm")
    with pytest.raises(AssembleError, match="허용값"):
        thesis_input_from_l3(make_thesis(confidence_provenance="llm"), confidence_source="human")
    with pytest.raises(AssembleError, match="theme_id"):
        thesis_input_from_l3({"cycle_confidence": 0.5}, confidence_source="human")


def test_thesis_input_keeps_contract_violations_for_parse_thesis() -> None:
    """빈 무효화는 고치지 않고 넘긴다 — 거부는 `parse_thesis` 의 일이다 (CLAUDE.md §5)."""
    m = thesis_input_from_l3(make_thesis(invalidations=[]), confidence_source="referee")
    with pytest.raises(InputError, match="invalidations"):
        parse_thesis(m)


def test_thesis_input_gate_ineligible_propagates() -> None:
    t = make_thesis(gate_result={"status": "contested", "portfolio_eligible": False})
    ti = parse_thesis(thesis_input_from_l3(t, confidence_source="referee"))
    assert ti.portfolio_eligible is False and ti.gate_status == "contested"


# ---------------------------------------------------------------- 묶음 (assemble_inputs)


def _seed_state(tmp_path: Path) -> tuple[Path, Path, Path]:
    """uranium: thesis + picks(최신 ≤ asof 는 08-14, 08-25 는 미래) · coal: 게이트 기각 ·
    grid_equipment: thesis 없음 · lithium: thesis 만 있고 picks 없음."""
    picks, theses, out = _state(tmp_path)
    _write_ranking(picks, "2026-08-10", "uranium", _ranking([("OLD", "ANCHOR", 0.5, 1.0, 1e7)]))
    _write_ranking(
        picks,
        "2026-08-14",
        "uranium",
        _ranking(
            [
                ("CCJ", "ANCHOR", 0.8, 50.0, 3e8),
                ("UEC", "TORQUE", 0.7, 6.0, 5e7),
                ("URG", "", 0.5, 1.0, 1e6),
            ]
        ),
    )
    _write_ranking(picks, "2026-08-25", "uranium", _ranking([("FUT", "ANCHOR", 0.9, 1.0, 1e7)]))
    _write_ranking(picks, "2026-08-14", "coal", _ranking([("BTU", "TORQUE", 0.6, 20.0, 8e7)]))
    _write_ranking(
        picks, "2026-08-14", "grid_equipment", _ranking([("PWR", "ANCHOR", 0.6, 200.0, 4e8)])
    )
    _write_thesis(theses, "2026-08-12", make_thesis(theme_id="uranium"))
    _write_thesis(
        theses,
        "2026-08-12",
        make_thesis(
            theme_id="coal",
            gate_result={"status": "rejected", "portfolio_eligible": False, "path": "hard_gate"},
        ),
    )
    _write_thesis(theses, "2026-08-12", make_thesis(theme_id="lithium"))
    return picks, theses, out


def test_assemble_inputs_writes_contract_and_reports_skips(tmp_path: Path) -> None:
    picks, theses, out = _seed_state(tmp_path)
    res = assemble_inputs(
        asof=ASOF,
        themes=["uranium", "coal", "grid_equipment", "lithium", "uranium"],
        picks_root=picks,
        theses_root=theses,
        out_dir=out,
    )
    assert res.out_dir == out
    assert res.themes_included == ["uranium"]
    sk = res.themes_skipped
    assert set(sk) == {"coal", "grid_equipment", "lithium"}
    assert sk["coal"].startswith("gate 편입 불가 (status=rejected")
    assert sk["grid_equipment"].startswith("thesis 없음")
    assert sk["lithium"].startswith("picks 없음")
    # 최신 ≤ asof 스냅샷 (08-14) — 08-10 도 08-25 도 아니다
    assert res.report["sources"]["uranium"]["picks_date"] == "2026-08-14"
    assert res.report["sources"]["uranium"]["thesis_date"] == "2026-08-12"
    assert res.report["sources"]["uranium"]["confidence_source"] == "referee"
    assert res.picks.counts == {"바벨 미배정 (group 비어 있음)": 1}
    # 파일 계약 — L5 로더가 그대로 읽는다
    pk = load_picks(out / "picks.csv")
    assert [p.ticker for p in pk] == ["CCJ", "UEC"]
    th = load_theses(out / "theses")
    assert set(th) == {"uranium"} and th["uranium"].confidence_source == "referee"
    inputs = load_inputs(out, cases_path=None)
    assert inputs.themes() == ["uranium"]
    # 리포트 파일과 텍스트
    assert (out / "assemble_report.json").exists()
    txt = (out / "report.txt").read_text(encoding="utf-8")
    for needle in ("건너뛴 테마", "coal", "gate 편입 불가", "쓰지 않은 열", "idio_vol_ann"):
        assert needle in txt
    assert "msa portfolio --inputs" in txt


def test_assemble_inputs_no_write_returns_frames_only(tmp_path: Path) -> None:
    picks, theses, out = _seed_state(tmp_path)
    res = assemble_inputs(
        asof=date(2026, 8, 22),
        themes=["uranium"],
        picks_root=picks,
        theses_root=theses,
        out_dir=out,
        write=False,
    )
    assert res.out_dir is None and not out.exists()
    assert res.picks.frame["ticker"].tolist() == ["CCJ", "UEC"]
    assert res.theses["uranium"]["cycle_confidence_source"] == "referee"


def test_assemble_inputs_all_skipped_raises(tmp_path: Path) -> None:
    picks, theses, out = _seed_state(tmp_path)
    with pytest.raises(AssembleError, match="묶을 테마가 0개") as ei:
        assemble_inputs(
            asof=ASOF,
            themes=["coal", "grid_equipment"],
            picks_root=picks,
            theses_root=theses,
            out_dir=out,
        )
    assert "coal" in str(ei.value) and "grid_equipment" in str(ei.value)
    assert not out.exists()
    with pytest.raises(AssembleError, match="테마가 0개"):
        assemble_inputs(asof=ASOF, themes=[], picks_root=picks, theses_root=theses, out_dir=out)
    with pytest.raises(AssembleError, match="YYYY-MM-DD"):
        assemble_inputs(
            asof="08/22/2026",
            themes=["uranium"],
            picks_root=picks,
            theses_root=theses,
            out_dir=out,
        )


def test_assemble_inputs_human_theses_dir(tmp_path: Path) -> None:
    picks, theses, out = _seed_state(tmp_path)
    hdir = tmp_path / "human"
    hdir.mkdir()
    # grid_equipment: L3 thesis 없음 → 사람 논지로 채운다 (부분집합만 써도 된다)
    (hdir / "grid_equipment.yaml").write_text(
        yaml.safe_dump(
            {
                "theme_id": "grid_equipment",
                "cycle_confidence": 0.66,
                "horizon_months": [6, 18],
                "invalidations": [{"observable": "변압기 리드타임 < 12개월", "source": "IEA"}],
                "triggers": ["수주잔고 YoY +20%"],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    # uranium: 사람 논지가 L3 산출보다 우선 — 그리고 yaml 스스로 human 을 선언
    dump_thesis_yaml(
        hdir / "uranium.yaml",
        make_thesis(theme_id="uranium", cycle_confidence=0.55, confidence_provenance="human"),
    )
    res = assemble_inputs(
        asof=ASOF,
        themes=["uranium", "grid_equipment"],
        picks_root=picks,
        theses_root=theses,
        out_dir=out,
        human_theses_dir=hdir,
    )
    assert res.themes_included == ["uranium", "grid_equipment"]
    src = res.report["sources"]
    assert src["uranium"]["confidence_source"] == "human" and src["uranium"]["thesis_date"] is None
    assert src["grid_equipment"]["confidence_source"] == "human"
    th = load_theses(out / "theses")
    assert th["uranium"].cycle_confidence == 0.55 and th["uranium"].confidence_source == "human"
    assert th["grid_equipment"].confidence_source == "human"
    with pytest.raises(AssembleError, match="디렉터리가 없다"):
        assemble_inputs(
            asof=ASOF,
            themes=["uranium"],
            picks_root=picks,
            theses_root=theses,
            out_dir=out,
            human_theses_dir=tmp_path / "nope",
        )


def test_assemble_inputs_yaml_declared_provenance_is_honoured(tmp_path: Path) -> None:
    """`state/theses/` 에 있어도 yaml 이 `confidence_provenance: human` 이면 human 으로 찍히고,
    사람 디렉터리에 있어도 referee 를 선언하면 referee 다 — 위치가 선언을 덮어쓰지 않는다."""
    picks, theses, out = _seed_state(tmp_path)
    _write_thesis(
        theses, "2026-08-15", make_thesis(theme_id="uranium", confidence_provenance="human")
    )
    res = assemble_inputs(
        asof=ASOF, themes=["uranium"], picks_root=picks, theses_root=theses, out_dir=out
    )
    src = res.report["sources"]["uranium"]
    assert src["confidence_source"] == "human" and src["confidence_source_by"] == "yaml 선언"
    assert load_theses(out / "theses")["uranium"].confidence_source == "human"
    hdir = tmp_path / "human"
    hdir.mkdir()
    dump_thesis_yaml(
        hdir / "uranium.yaml", make_thesis(theme_id="uranium", confidence_provenance="referee")
    )
    res = assemble_inputs(
        asof=ASOF,
        themes=["uranium"],
        picks_root=picks,
        theses_root=theses,
        out_dir=out,
        human_theses_dir=hdir,
    )
    assert res.report["sources"]["uranium"]["confidence_source"] == "referee"
    # 선언 없는 사람 디렉터리 파일은 위치로 human
    dump_thesis_yaml(hdir / "uranium.yaml", make_thesis(theme_id="uranium"))
    res = assemble_inputs(
        asof=ASOF,
        themes=["uranium"],
        picks_root=picks,
        theses_root=theses,
        out_dir=out,
        human_theses_dir=hdir,
    )
    src = res.report["sources"]["uranium"]
    assert src["confidence_source"] == "human" and src["confidence_source_by"] == "위치(human)"


def test_assemble_inputs_broken_thesis_is_skipped_with_reason(tmp_path: Path) -> None:
    picks, theses, out = _seed_state(tmp_path)
    _write_thesis(theses, "2026-08-16", make_thesis(theme_id="uranium", invalidations=[]))
    with pytest.raises(AssembleError) as ei:
        assemble_inputs(
            asof=ASOF, themes=["uranium"], picks_root=picks, theses_root=theses, out_dir=out
        )
    assert "thesis 계약 위반" in str(ei.value) and "invalidations" in str(ei.value)


def _synthetic_daily_ew(themes: list[str]) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2019-01-01", "2026-08-20")
    return pd.DataFrame({t: rng.normal(0.0003, 0.012, len(idx)) for t in themes}, index=idx)


def test_assembled_dir_feeds_build_portfolio(tmp_path: Path) -> None:
    """`msa portfolio --inputs <out>` 경로 — 묶음 디렉터리를 L5 가 그대로 소비한다."""
    from msa.l5.run import build_portfolio
    from msa.themes import load_themes

    picks, theses, out = _seed_state(tmp_path)
    assemble_inputs(
        asof=ASOF, themes=["uranium"], picks_root=picks, theses_root=theses, out_dir=out
    )
    inputs = load_inputs(out, cases_path=None)
    themes = load_themes(paths().themes_yaml)
    res = build_portfolio(
        inputs,
        asof=date(2026, 8, 22),
        themes=themes,
        daily_ew=_synthetic_daily_ew(["uranium"]),
        inputs_dir=str(out),
    )
    assert res.solution is not None and set(res.solution.weights) == {"CCJ", "UEC"}


# ---------------------------------------------------------------- CLI


def test_cli_portfolio_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from msa.cli import app

    _seed_state(tmp_path)
    # MSA_STATE 를 tmp 로 — picks/theses/portfolio_inputs 전부 그 아래
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    runner = CliRunner()
    r = runner.invoke(app, ["portfolio-inputs", "--help"])
    assert r.exit_code == 0
    for opt in ("--asof", "--themes", "--human-theses", "--top", "--no-write"):
        assert opt in r.stdout
    r = runner.invoke(
        app, ["portfolio-inputs", "--asof", ASOF, "--themes", "uranium,coal,grid_equipment"]
    )
    assert r.exit_code == 0, r.output
    assert "포함 1 [uranium]" in r.stdout and "coal" in r.stdout
    out = tmp_path / "portfolio_inputs" / ASOF
    assert (out / "picks.csv").exists() and (out / "theses" / "uranium.yaml").exists()
    assert f"저장: {out}" in r.stdout
    # 전부 건너뜀 → 입력 거부 종료 코드 1, 사유가 stderr 에
    r = runner.invoke(app, ["portfolio-inputs", "--asof", ASOF, "--themes", "coal", "--no-write"])
    assert r.exit_code == 1
    assert "gate 편입 불가" in r.output


# ---------------------------------------------------------------- 실데이터 스모크


@pytest.mark.data
def test_assemble_from_real_picks_run(tmp_path: Path) -> None:
    """`msa picks rare_earth --asof 2026-08-14` 실산출 → 합성 thesis → 묶음 → `load_inputs`."""
    from msa.l4.picks import run_picks

    picks, theses, out = _state(tmp_path)
    res = run_picks(
        "rare_earth", asof="2026-08-14", out_root=picks, with_physical=False, allow_fetch=False
    )
    assert res.out_dir is not None and res.barbell.n >= 1
    _write_thesis(theses, "2026-08-14", make_thesis(theme_id="rare_earth"))
    ar = assemble_inputs(
        asof="2026-08-14",
        themes=["rare_earth"],
        picks_root=picks,
        theses_root=theses,
        out_dir=out,
    )
    assert ar.themes_included == ["rare_earth"]
    assert ar.picks.n_included == res.barbell.n
    assert set(ar.picks.frame["ticker"]) == set(res.barbell.anchors + res.barbell.torques)
    # 순위만 있는 행은 전부 '바벨 미배정' 으로 세어진다
    assert (
        ar.picks.counts.get("바벨 미배정 (group 비어 있음)", 0) == len(res.ranking) - res.barbell.n
    )
    inputs = load_inputs(out, cases_path=None)
    assert all(p.entry_price and p.adv20_usd for p in inputs.picks)
