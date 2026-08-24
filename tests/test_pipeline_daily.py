"""일간 후보 다이제스트 (`msa.pipeline.daily`, `msa run daily`).

각 계층 진입점을 가짜로 갈아끼우고(스토어 불필요) 다이제스트 구성·diff·첫 실행·no-write·
문구 규약·CLI 등록을 검사한다. 진짜 캐시 스모크 1건은 `@pytest.mark.data`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date as _d
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from msa.config import paths
from msa.ops.alerts import assert_wording_ok
from msa.ops.check import CheckReport
from msa.pipeline import daily as D

ASOF1 = "2026-08-21"
ASOF2 = "2026-08-22"


# ---------------------------------------------------------------- 합성 입력


def _sb(rows: list[tuple[str, float, bool]], small: set[str] | None = None) -> pd.DataFrame:
    """(theme, score, eligible) → S2 스코어보드 꼴 (pool·블록 백분위 포함).

    `small` 에 든 테마는 소표본이다."""
    small = small or set()
    df = pd.DataFrame(
        [
            {
                "cycle_class": "commodity_supply",
                "score": sc,
                "pool": 0.5 if np.isnan(sc) else sc - 0.05,
                "eligible": el,
                "small_sample": _t in small,
                "secular": False,
                "flags": "",
                **{f"{b}_pct": 0.5 for b in "ABCDEF"},
            }
            for _t, sc, el in rows
        ],
        index=pd.Index([r[0] for r in rows], name="theme"),
    )
    df = df.sort_values("score", ascending=False, na_position="last")
    df.insert(0, "rank", np.where(df["score"].notna(), np.arange(1, len(df) + 1), np.nan))
    return df


def _ranking(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rank": range(1, len(tickers) + 1),
            "group": ["anchor" if i < 2 else "torque" for i in range(len(tickers))],
            "composite": [0.9 - 0.1 * i for i in range(len(tickers))],
            "s_pct": 0.6,
            "t_pct": 0.5,
            "m_pct": 0.7,
            "price": 12.34,
            "adv20_usd": 3.2e6,
            "penalties": ["p1" if i == 0 else "" for i in range(len(tickers))],
            "red_flags": "",
        },
        index=pd.Index(tickers, name="ticker"),
    )


def _excluded(hard: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"stage": ["hard_filter"] * len(hard), "reason": ["runway<4q"] * len(hard)},
        index=pd.Index(hard, name="ticker"),
    )


@dataclass
class _Scan:
    scoreboard: Any
    meta: dict[str, Any]
    out_dir: Path | None = None


@dataclass
class _SBox:
    table: pd.DataFrame


@dataclass
class _Picks:
    ranking: pd.DataFrame
    excluded: pd.DataFrame


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """MSA_STATE 를 임시로 돌리고 scan·picks·check 진입점을 가짜로 바꾼다. `data` 를 바꾸면
    다음 호출부터 반영된다 — 이틀치 diff 테스트용."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("MSA_STATE", str(state))
    data: dict[str, Any] = {
        "sb": [("t_a", 0.9, True), ("t_b", 0.8, True), ("t_c", 0.7, True)],
        "asof": ASOF1,
        "rank": {"t_a": ["AAA", "BBB", "CCC"], "t_b": ["DDD", "EEE"], "t_c": ["FFF"]},
        "hard": {"t_a": ["XXX"], "t_b": [], "t_c": []},
        "boom": {},  # theme → Exception
        "small": set(),  # 소표본 테마
    }
    calls: dict[str, list[Any]] = {"scan": [], "picks": [], "check": []}

    def scan(**kw: Any) -> _Scan:
        calls["scan"].append(kw)
        return _Scan(
            _SBox(_sb(data["sb"], data.get("small"))),
            {"asof": data["asof"], "store_end": data["asof"], "bucket": "x"},
        )

    def picks(theme: str, **kw: Any) -> _Picks:
        calls["picks"].append((theme, kw))
        if theme in data["boom"]:
            raise data["boom"][theme]
        return _Picks(_ranking(data["rank"][theme]), _excluded(data["hard"].get(theme, [])))

    def check(asof_s: str, **kw: Any) -> tuple[CheckReport, dict[str, Any]]:
        calls["check"].append((asof_s, kw))
        rep = CheckReport(
            asof=_d.fromisoformat(asof_s),
            mode="daily",
            positions=[],
            alerts=[],
            out_dir=None,
            problems=["CCJ: thesis 스냅샷 없음"],
        )
        return rep, {"telegram": "not_configured", "lookback_days": 1}

    monkeypatch.setattr(D, "run_scan", scan)
    monkeypatch.setattr(D, "run_picks", picks)
    monkeypatch.setattr(D, "run_cadence_check", check)
    return {"state": state, "calls": calls, "data": data}


# ---------------------------------------------------------------- 구성 · 첫 실행


def test_daily_first_run_writes_digest_and_marks_everything_new(env: dict[str, Any]) -> None:
    res = D.run_daily(asof=ASOF1, top_k=2, picks_per_theme=2)
    assert res.exit_code == 0
    assert [s.name for s in res.report.steps] == list(D.DAILY_STEPS)
    assert res.report.statuses() == {
        "scan": "ok",
        "select": "ok",
        "picks": "ok",
        "diff": "ok",
        "check": "skipped",  # positions.yaml 없음
        "digest": "ok",
    }
    out = env["state"] / "daily" / ASOF1
    assert res.out_dir == out
    dj = json.loads((out / "digest.json").read_text(encoding="utf-8"))
    md = (out / "digest.md").read_text(encoding="utf-8")
    assert (out / "report.txt").read_text(encoding="utf-8") == md
    # 머리의 정직성 한 줄 + 후보 목록 선언
    assert D.HONESTY_HEADER in md and "docs/02 §7.1" in md
    # top_k=2 → t_a, t_b 만 (t_c 는 자격이어도 K 밖)
    assert [t["theme"] for t in dj["themes"]] == ["t_a", "t_b"]
    assert all(t["new_since_prev"] for t in dj["themes"])
    assert dj["diff"]["first_run"] and dj["diff"]["prev_asof"] is None
    assert "기준일 없음, 전부 신규" in md
    # per_theme=2 는 표시 개수 — eligible 전체(3)는 diff 용으로 남는다
    ta = dj["themes"][0]
    assert [x["ticker"] for x in ta["picks"]] == ["AAA", "BBB"]
    assert ta["eligible_tickers"] == ["AAA", "BBB", "CCC"]
    assert ta["hard_excluded_tickers"] == ["XXX"]
    assert ta["blocks"]["A_pct"] == 0.5
    # 종목 한 줄: group·종합·S/T/M·가격·ADV·감점
    assert "AAA" in md and "종합 0.90" in md and "$12.34" in md and "ADV $3.2M" in md
    assert "감점[p1]" in md
    # 고르면 다음
    assert "msa research" in md and "msa journal new --from" in md and "msa run monthly" in md


def test_daily_diff_against_previous_digest(env: dict[str, Any]) -> None:
    D.run_daily(asof=ASOF1, top_k=2, picks_per_theme=2)
    data = env["data"]
    # 다음 날: t_c 가 t_b 를 제치고 2위(t_b 는 K 밖으로), t_a 상위에 NEW 진입 + 신규 통과/하드 제외
    data["sb"] = [("t_a", 0.9, True), ("t_c", 0.85, True), ("t_b", 0.8, True)]
    data["rank"]["t_a"] = ["NEW1", "AAA", "BBB", "CCC"]  # NEW1 이 1위로 등장
    data["hard"]["t_a"] = ["XXX", "CCC2"]  # CCC2 신규 하드 제외
    res = D.run_daily(asof=ASOF2, top_k=2, picks_per_theme=2)
    diff = res.digest["diff"]
    assert not diff["first_run"] and diff["prev_asof"] == ASOF1
    assert diff["themes_entered"] == ["t_c"] and diff["themes_left"] == ["t_b"]
    assert diff["rank_moves"] == {}  # t_a 1위 유지; t_c 는 신규라 이동이 아니다
    st = diff["stocks"]["t_a"]
    assert st["new_in_top"] == ["NEW1"]
    assert st["newly_passing"] == ["NEW1"]
    assert st["newly_hard_excluded"] == ["CCC2"]
    md = res.digest_md
    assert "테마 상위 K 진입: t_c" in md and "테마 상위 K 이탈: t_b" in md
    assert "상위 N 신규 NEW1" in md and "신규 하드 제외 CCC2" in md
    # 표의 변화 열: t_c 는 NEW
    assert "| t_c |" in md and "NEW" in md
    # 테마 자체가 신규인 t_c 는 new_since_prev
    by = {t["theme"]: t for t in res.digest["themes"]}
    assert by["t_c"]["new_since_prev"] and not by["t_a"]["new_since_prev"]


def test_daily_rank_moves_are_reported(env: dict[str, Any]) -> None:
    D.run_daily(asof=ASOF1, top_k=3, picks_per_theme=2)
    env["data"]["sb"] = [("t_b", 0.9, True), ("t_a", 0.8, True), ("t_c", 0.7, True)]
    res = D.run_daily(asof=ASOF2, top_k=3, picks_per_theme=2)
    assert res.digest["diff"]["rank_moves"] == {"t_a": -1, "t_b": 1}
    assert "순위 이동: t_b ▲1" in res.digest_md and "순위 이동: t_a ▼1" in res.digest_md


def test_daily_no_write_leaves_state_untouched(env: dict[str, Any]) -> None:
    before = {x.name for x in env["state"].iterdir()}
    res = D.run_daily(asof=ASOF1, top_k=2, write=False)
    after = {x.name for x in env["state"].iterdir()}
    assert after == before and res.out_dir is None
    assert res.digest["themes"] and res.digest_md  # 산출물은 객체로 돌아온다
    assert res.report.step("digest").status == "ok"  # type: ignore[union-attr]
    assert "no-write" in res.report.step("digest").reason  # type: ignore[union-attr]


def test_daily_picks_failure_is_isolated(env: dict[str, Any]) -> None:
    env["data"]["boom"]["t_a"] = RuntimeError("store down for t_a")
    res = D.run_daily(asof=ASOF1, top_k=2, picks_per_theme=2)
    assert res.exit_code == 0
    by = {t["theme"]: t for t in res.digest["themes"]}
    assert "store down for t_a" in (by["t_a"]["picks_error"] or "")
    assert by["t_a"]["picks"] == [] and by["t_b"]["picks"]
    assert "picks 실패" in res.digest_md
    assert "t_a" in res.report.step("picks").reason  # type: ignore[union-attr]


def test_daily_scan_failure_stops_with_exit_1(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(**kw: Any) -> Any:
        raise RuntimeError("커버리지 감사 실패")

    monkeypatch.setattr(D, "run_scan", boom)
    res = D.run_daily(asof=ASOF1)
    assert res.exit_code == 1 and res.report.stopped
    assert res.report.step("scan").status == "failed"  # type: ignore[union-attr]
    assert not (env["state"] / "daily").exists()
    assert env["calls"]["picks"] == []


def test_daily_check_runs_only_when_positions_exist(env: dict[str, Any]) -> None:
    paths().positions.write_text("positions: []", encoding="utf-8")
    res = D.run_daily(asof=ASOF1, top_k=2)
    # --send 없이 돌았으므로 점검 알림도 발신 금지로 내려간다 (발신은 --send 가 지배한다)
    assert env["calls"]["check"] == [(ASOF1, {"mode": "daily", "write": True, "send": False})]
    assert res.report.statuses()["check"] == "ok"
    pc = res.digest["positions_check"]
    assert pc["positions"] == 0 and pc["problems"] == ["CCJ: thesis 스냅샷 없음"]
    assert "보유 점검" in res.digest_md and "thesis 스냅샷 없음" in res.digest_md
    assert any("check 문제" in x for x in res.report.human_todo)


def test_daily_check_failure_reported_not_fatal(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    paths().positions.write_text("positions: []", encoding="utf-8")

    def boom(a: str, **k: Any) -> Any:
        raise RuntimeError("positions.yaml 깨짐")

    monkeypatch.setattr(D, "run_cadence_check", boom)
    res = D.run_daily(asof=ASOF1, top_k=2)
    assert res.exit_code == 0 and res.report.statuses()["check"] == "failed"
    assert res.digest["positions_check"] is None


# ---------------------------------------------------------------- 텔레그램 · 문구 규약


def test_daily_send_without_env_is_not_configured(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MSA_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("MSA_TELEGRAM_CHAT_ID", raising=False)
    res = D.run_daily(asof=ASOF1, top_k=2, send=True)
    assert res.telegram == "not_configured"
    assert (env["state"] / "daily" / ASOF1 / "alerts.json").exists()  # 기록은 파일이다


def test_daily_send_requires_write(env: dict[str, Any]) -> None:
    res = D.run_daily(asof=ASOF1, top_k=2, send=True, write=False)
    assert res.telegram is None
    assert any("--send" in n and "no-write" in n for n in res.report.notes)


def test_digest_alert_passes_wording_rule_and_caps_length(env: dict[str, Any]) -> None:
    D.run_daily(asof=ASOF1, top_k=2, picks_per_theme=2)
    env["data"]["rank"]["t_a"] = [f"T{i:03d}" for i in range(300)]  # 새 항목 폭탄
    res = D.run_daily(asof=ASOF2, top_k=2, picks_per_theme=2)
    a = D.build_digest_alert(res.digest, _d.fromisoformat(ASOF2))
    assert_wording_ok(a.text)
    assert len(a.text) <= D.TELEGRAM_MAX_CHARS
    assert "[일간 후보 다이제스트]" in a.text and "후보 테마" in a.text
    # 테마·종목·플래그 뜻이 다 실린다 (사람이 알림만 보고 판단할 수 있어야 한다)
    assert "종합" in a.text and "전문:" in a.text
    assert "투자 조언이 아니다" in a.text and "docs/02 §7.1" in a.text
    if "… 외 " in a.text:  # 잘랐다면 자른 개수를 적는다 — 조용한 절단 금지
        assert "건" in a.text or "개" in a.text
    # 파일과 같은 L4 폐기 고지가 알림에도 있다 (7번)
    assert D.HONESTY_HEADER in a.text


def test_daily_broken_baseline_is_not_reported_as_first_run(env: dict[str, Any]) -> None:
    """깨진 직전 다이제스트는 "첫 실행" 이 아니다 — 산출물·알림에 손상 사실이 남는다 (4번)."""
    D.run_daily(asof=ASOF1, top_k=2, picks_per_theme=2)
    (paths().daily / ASOF1 / "digest.json").write_text("{ 깨짐", encoding="utf-8")
    res = D.run_daily(asof=ASOF2, top_k=2, picks_per_theme=2)
    diff = res.digest["diff"]
    assert not diff["first_run"] and diff["baseline_broken"]
    assert diff["themes_entered"] == [] and diff["rank_moves"] == {}
    assert not any(t["new_since_prev"] for t in res.digest["themes"])
    md = res.digest_md
    assert "첫 실행 — 전부 신규" not in md and "기준일 없음, 전부 신규" not in md
    assert "손상" in md and "직전 기준" in D.new_item_lines(diff)[0]
    step = res.report.step("diff")
    assert step is not None and step.status == "failed" and "손상" in step.reason
    a = D.build_digest_alert(res.digest, _d.fromisoformat(ASOF2))
    assert "손상" in a.text
    assert res.exit_code == 0  # 후보 뷰 자체는 낸다


def test_daily_small_sample_demotion_is_named_in_digest_and_alert(env: dict[str, Any]) -> None:
    """스코어보드 1위가 소표본으로 빠지면 그 사실이 파일·알림에 남는다 (5번)."""
    env["data"]["sb"] = [("t_a", 0.9, True), ("t_b", 0.8, True), ("t_c", 0.7, True)]
    env["data"]["small"] = {"t_a"}
    res = D.run_daily(asof=ASOF1, top_k=2, picks_per_theme=2)
    assert res.digest["demoted"] == [{"theme": "t_a", "rank": 1}]
    assert [t["theme"] for t in res.digest["themes"]] == ["t_b", "t_c"]
    assert "소표본이라 뒤로 밀려" in res.digest_md and "t_a" in res.digest_md
    a = D.build_digest_alert(res.digest, _d.fromisoformat(ASOF1))
    assert "소표본이라 뒤로 밀려 상위 K 에서 빠진 테마" in a.text and "t_a" in a.text


def test_daily_without_send_delivers_nothing_at_all(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--send` 없이는 다이제스트도 보유 점검 알림도 나가지 않는다 (1번)."""
    monkeypatch.setenv("MSA_TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("MSA_TELEGRAM_CHAT_ID", "42")
    paths().positions.write_text("positions: []", encoding="utf-8")
    res = D.run_daily(asof=ASOF1, top_k=2)
    assert res.telegram is None  # 다이제스트를 만들지도 않았다
    assert env["calls"]["check"][0][1]["send"] is False
    assert not (env["state"] / "daily" / ASOF1 / "alerts.json").exists()


def test_run_daily_rejects_bad_args(env: dict[str, Any]) -> None:
    from msa.pipeline.run import RunError

    with pytest.raises(RunError):
        D.run_daily(asof=ASOF1, top_k=-1)
    with pytest.raises(RunError):
        D.run_daily(asof=ASOF1, picks_per_theme=0)
    with pytest.raises(RunError):
        D.run_daily(asof="2026/08/21")


# ---------------------------------------------------------------- CLI


def test_cli_run_daily_registered_and_passes_options(monkeypatch: pytest.MonkeyPatch) -> None:
    import msa.pipeline.daily as daily_mod
    from msa.cli import app
    from msa.pipeline.run import RunReport

    seen: dict[str, Any] = {}

    def fake(**kw: Any) -> D.DailyResult:
        seen.update(kw)
        rep = RunReport(
            cadence="daily", asof=ASOF1, started_at="t", write=kw["write"], state_root="s"
        )
        return D.DailyResult(report=rep, digest={}, digest_md="(다이제스트)")

    monkeypatch.setattr(daily_mod, "run_daily", fake)
    r = CliRunner().invoke(
        app,
        [
            "run",
            "daily",
            "--asof",
            ASOF1,
            "--top-k",
            "3",
            "--themes",
            "t_x,t_y",
            "--per-theme",
            "2",
            "--no-write",
            "--send",
        ],
    )
    assert r.exit_code == 0, r.output
    assert seen == {
        "asof": ASOF1,
        "top_k": 3,
        "extra_themes": ["t_x", "t_y"],
        "picks_per_theme": 2,
        "write": False,
        "send": True,
    }
    assert "(다이제스트)" in r.output


# ---------------------------------------------------------------- 진짜 캐시 스모크


@pytest.mark.data
def test_daily_smoke_on_real_cache() -> None:
    """진짜 캐시로 no-write 다이제스트 — state/ 에 아무것도 쓰지 않는다."""
    p = paths()
    if not p.duckdb.exists() or not p.cache.exists():
        pytest.skip("스토어/캐시 없음")
    before = {x.name for x in p.state.iterdir()}
    res = D.run_daily(top_k=2, picks_per_theme=3, write=False)
    after = {x.name for x in p.state.iterdir()}
    assert after == before, f"write=False 인데 state/ 가 바뀌었다: {after - before}"
    assert res.exit_code == 0
    assert D.HONESTY_HEADER in res.digest_md
    for name in D.DAILY_STEPS:
        step = res.report.step(name)
        assert step is not None and (step.status == "ok" or step.reason), name
    assert len(res.digest["themes"]) <= 2
    for t in res.digest["themes"]:
        assert len(t["picks"]) <= 3
