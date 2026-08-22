"""`run_macro` 끝까지 — 임시 MSA_STATE 에 DAG·테마·FRED 캐시·수동 CSV·L1 패널 캐시를 만들어 돌린다.

스토어·ETF 벌크·네트워크 없음 (`allow_store=False`, `allow_etf=False`, `allow_fetch=False`).
확인하는 것은 수치보다 **모양·결측 보고·파일**이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from _l2_helpers import THEMES, daily, monthly, write_dag, write_themes
from msa.cli import app
from msa.l2.runtime import run_macro

ASOF = "2024-07-31"


def _fred_csv(d: Path, symbol: str, s: pd.Series) -> None:
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "value": s.to_numpy()}).to_csv(
        d / f"{symbol}.csv", index=False
    )


def _panel_cache(cache: Path) -> None:
    """L1 패널 캐시 모양의 합성 parquet (ret_ew 만 쓴다)."""
    cache.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2005-01-03", ASOF)
    rng = np.random.default_rng(5)
    frames = []
    for t in THEMES:
        frames.append(
            pd.DataFrame(
                {"date": dates, "theme": t, "ret_ew": rng.normal(0.0003, 0.01, len(dates))}
            )
        )
    f = pd.concat(frames).set_index(["date", "theme"]).sort_index()
    for c in ("ret_cw", "dv", "mcap_sum"):
        f[c] = 0.0
    f.to_parquet(cache / "l1_panel_deadbeef.parquet")
    spy = pd.DataFrame(
        {"close": 100 * np.cumprod(1 + rng.normal(0.0003, 0.008, len(dates))), "dv": 1.0},
        index=dates,
    )
    spy.index.name = "date"
    spy.to_parquet(cache / "l1_spy_deadbeef.parquet")
    (cache / "l1_panel_deadbeef.json").write_text(json.dumps({"fingerprint": "deadbeef"}))


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    st = tmp_path / "state"
    st.mkdir()
    monkeypatch.setenv("MSA_STATE", str(st))
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    write_dag(st)
    write_themes(st)
    fred = st / "physical" / "fred"
    dfii = daily("2010-01-01", ASOF, lambda t: 2.0)
    dfii.loc["2024-02-01":] = 1.4
    _fred_csv(fred, "DFII10", dfii)
    _fred_csv(
        fred, "CPIAUCSL", monthly("2005-01-01", "2024-07-01", lambda t: 100 * 1.03 ** (t / 12))
    )
    # 수동: china_property (available 열 없음 → 기본 +1개월), policy_events
    man = st / "physical" / "manual"
    man.mkdir(parents=True)
    cp = monthly("2019-01-01", "2024-06-01", lambda t: 100 + 3.0 * t)
    pd.DataFrame({"date": cp.index.strftime("%Y-%m-%d"), "value": cp.to_numpy()}).to_csv(
        man / "china_property.csv", index=False
    )
    pd.DataFrame(
        {
            "date": ["2024-03-15"],
            "theme": ["delta"],
            "effect": [1],
            "description": ["보조금 확정"],
            "confirmed": ["Y"],
        }
    ).to_csv(man / "policy_events.csv", index=False)
    _panel_cache(st / "cache")
    return st


def test_run_macro_end_to_end(state: Path) -> None:
    res = run_macro(
        asof=ASOF,
        allow_fetch=False,
        allow_etf=False,
        allow_store=False,
        write=True,
        sign_check=True,
        doc_out=state / "docs" / "sign.md",
    )
    assert res.asof == pd.Timestamp(ASOF)
    snap = res.drivers.snapshot()
    assert snap.loc["real_rate_10y", "state"] == -1
    assert snap.loc["cpi_yoy", "state"] == 1
    assert snap.loc["china_property", "status"] == "ok"
    assert snap.loc["policy_events", "status"] == "ok"
    # 없는 것은 이름으로
    assert set(res.drivers.missing) == {
        "dollar_broad",
        "employment",
        "usd_liquidity",
        "copper_price",
        "gold_price",
        "hyperscaler_capex",
    }
    assert (
        "FRED_API_KEY" in snap.loc["dollar_broad", "note"]
        or "캐시 없음" in snap.loc["dollar_broad", "note"]
    )
    assert "--no-etf" in snap.loc["gold_price", "note"] or "벌크" in snap.loc["gold_price", "note"]
    assert snap.loc["copper_price", "missing_series"] == "PCOPPUSDM,CPER"
    # tailwind: delta = policy(+1) ok, china_property ok → ok 상태
    t = res.tailwind.table
    assert t.loc["delta", "status"] == "ok" and t.loc["delta", "tailwind_raw"] == pytest.approx(1.0)
    assert t.loc["epsilon", "status"] == "unavailable" and t.loc["epsilon", "undercovered"]
    # 검증 결과가 메타에
    assert res.meta["dag_validation"]["unknown_theme_refs"] == ["zeta_unknown"]
    assert "epsilon" in res.meta["dag_validation"]["undercovered"]
    # 4분면: 성장 구성 전부 없음 → 계산 불가, 결측 이름 보고
    assert not res.regime.available
    assert "industrial_production" in res.regime.missing_growth
    # 모순 감사: 규칙 있는 엣지는 dollar 없음 → UNAVAILABLE
    c = res.contradictions.set_index("edge")
    assert c.loc[1, "status"] == "UNAVAILABLE" and c.loc[2, "status"] == "PROSE_ONLY"
    # 부호 실측: real_rate·cpi 쌍은 계산됐다 (합성 패널), 나머지는 이유 포함
    s = res.sign_check.summary
    assert s["n_pairs_available"] == 5  # real_rate×2 + cpi×2 + china_property×1
    assert res.sign_check.ran
    # 파일
    out = res.out_dir
    assert out is not None and out.name == ASOF
    for f in (
        "drivers.csv",
        "driver_measures.csv",
        "driver_states.csv",
        "tailwind.csv",
        "edge_contributions.csv",
        "regime.csv",
        "regime.txt",
        "contradictions.csv",
        "sign_check.csv",
        "sign_check.md",
        "report.txt",
        "meta.json",
    ):
        assert (out / f).exists(), f
    meta = json.loads((out / "meta.json").read_text())
    assert meta["drivers"]["missing"] == res.drivers.missing
    report = (out / "report.txt").read_text()
    assert "결측 드라이버 (6)" in report and "zeta_unknown" in report
    assert (state / "docs" / "sign.md").exists()


def test_run_macro_no_write_no_sign_check(state: Path) -> None:
    res = run_macro(
        asof=ASOF,
        allow_fetch=False,
        allow_etf=False,
        allow_store=False,
        write=False,
        sign_check=False,
    )
    assert res.out_dir is None
    assert not res.sign_check.ran and "--no-sign-check" in res.sign_check.unavailable_reason
    assert not (state / "macro").exists()


def test_cli_macro_runs(state: Path) -> None:
    r = CliRunner().invoke(
        app,
        [
            "macro",
            "--asof",
            ASOF,
            "--no-fetch",
            "--no-etf",
            "--no-store",
            "--no-write",
            "--no-sign-check",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "L2 거시 DAG" in r.output and "결측 드라이버" in r.output


def test_fred_fetch_without_key_fails_loudly(state: Path) -> None:
    r = CliRunner().invoke(app, ["data", "fred-fetch", "--force"])
    assert r.exit_code == 1
    assert "MissingApiKey" in r.output
