"""일간 후보 다이제스트 — `msa run daily` (`docs/09` §1 일간 행).

주인의 요구는 "오늘의 종목을 보고 싶다 — 무슨 먹을거리가 올라오는지 매일 보고, 그중에서
고른다" 이다. **월간이 결정 케이던스라는 사실은 바뀌지 않는다** — 이 명령은 읽기 전용
후보 뷰다: 스캔(캐시 덕에 ~12초) → 상위 K 테마 선정(`select_themes` 재사용) → 테마별 L4
랭킹(`run_picks`, 스냅샷은 쓰지 않는다) → **직전 다이제스트와의 diff**(무엇이 새로 올라왔나)
→ 보유가 있으면 무효화 점검(`run_cadence_check(mode="daily")` — `msa check --daily` 와 같은
경로) → `state/daily/<asof>/digest.json`·`digest.md`·`report.txt`.

새 계산·새 임계값은 없다 (`CLAUDE.md` §1) — `top_k`(기본 8 = `docs/05` §1 의 K)와
`picks_per_theme`(기본 5)뿐이고, **5 는 표시 개수이지 선정 규칙이 아니다**(랭킹 전체는
`msa picks <theme>` 산출물에 있다). LLM 은 부르지 않는다 — 전 단계가 결정론이다
(`CLAUDE.md` §4: 종목은 결정론 계층이 고른다).

정직성: L1 점수는 약하고 겨우 검증된 신호다 — 복합 점수의 예측력은 관문에서 0 에
가까웠고 C 블록만 일했다 (`docs/backtest-l1.md` §12 · `docs/02` §7.1). 다이제스트 머리에
그 사실을 적는다. **이것은 후보 목록이지 투자 권유가 아니다** (`CLAUDE.md` §8) — 문구는
`ops/alerts.assert_wording_ok` 의 규약을 따른다.

실패 규약은 월간과 같다: 스캔 실패 = 중단(exit 1), 테마별 picks 실패는 격리·보고,
점검 실패는 보고. `write=False` 면 `state/` 에 아무것도 쓰지 않는다 — 이 파이프라인의
모든 단계가 `write=False` 로 돌 수 있어 샌드박스가 필요 없다. diff 의 기준(직전
다이제스트)은 어느 경우든 실제 `state/daily/` 에서 읽는다 (읽기는 부작용이 아니다).

텔레그램(`send=True` + `write=True`): "오늘 새로 올라온 것" + 상위 3테마 한 줄씩을
`AlertKind.DAILY_DIGEST` 로 기존 `deliver` 에 태운다 — 환경변수 둘 다 없으면
"not configured" (기존 규약 그대로). `write=False` 면 보내지 않는다 — `deliver` 는
`alerts.json` 을 쓰는 계약이라서다 (그 사실을 리포트에 적는다).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from msa.config import paths, rel
from msa.fmt import ratio
from msa.io import write_snapshot
from msa.l1.scan import run_scan, scan_dirs
from msa.l1.scoreboard import BLOCKS
from msa.l4.picks import PicksResult, run_picks
from msa.ops.alerts import Alert, AlertKind, deliver, format_alert
from msa.ops.check import CheckReport
from msa.pipeline.run import (
    RunError,
    RunReport,
    StepResult,
    ThemeSelection,
    _asof_str,
    _err,
    _skip_rest,
    _Timer,
    run_cadence_check,
    select_themes,
)

log = logging.getLogger(__name__)

#: 일간 단계 (순서 = 실행 순서 = 리포트 순서).
DAILY_STEPS: tuple[str, ...] = ("scan", "select", "picks", "diff", "check", "digest")

#: 다이제스트 머리 한 줄 — 모든 산출물(md·txt·텔레그램)이 같은 사실에서 시작한다.
HONESTY_HEADER = "측정값·후보 목록 — 투자 조언 아님; L1 점수 예측력 약함(docs/02 §7.1)."

#: 텔레그램 본문 상한 (Telegram sendMessage 한도 4096 — 여유를 둔다).
TELEGRAM_MAX_CHARS = 4000

#: 다이제스트에 싣는 종목당 랭킹 열 (`l4/picks.RANKING_EXPORT_COLUMNS` 의 부분집합 + rank).
PICK_COLUMNS: tuple[str, ...] = (
    "rank",
    "group",
    "composite",
    "s_pct",
    "t_pct",
    "m_pct",
    "price",
    "adv20_usd",
    "penalties",
    "red_flags",
)


# ---------------------------------------------------------------- 결과


@dataclass
class DailyResult:
    """`run_daily` 의 결과 — 단계 장부(`report`) + 다이제스트(기계 `digest` · 사람 `digest_md`)."""

    report: RunReport
    digest: dict[str, Any] = field(default_factory=dict)
    digest_md: str = ""
    out_dir: Path | None = None
    scan: Any = None
    selection: ThemeSelection | None = None
    picks: dict[str, PicksResult] = field(default_factory=dict)
    check: CheckReport | None = None
    telegram: str | None = None  # DeliveryStatus 문자열 · None = 보내지 않음

    @property
    def exit_code(self) -> int:
        return self.report.exit_code


# ---------------------------------------------------------------- 직전 다이제스트 · diff


def previous_digest(daily_root: Path, asof_s: str) -> tuple[str, dict[str, Any]] | None:
    """`state/daily/<date < asof>/digest.json` 의 최신 → (날짜, 내용). 없으면 None (첫 실행)."""
    import json

    for d, p in reversed(scan_dirs(daily_root)):
        f = p / "digest.json"
        if d.isoformat() < asof_s and f.exists():
            try:
                return d.isoformat(), json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:  # 깨진 기준은 건너뛰지 않고 그 사실이 남게 던진다
                raise RunError(f"직전 다이제스트를 읽을 수 없다 ({f}): {e}") from e
    return None


def _theme_names(themes: list[dict[str, Any]], *, scoreboard_only: bool) -> list[str]:
    return [
        str(t["theme"]) for t in themes if not scoreboard_only or t.get("source") == "scoreboard"
    ]


def diff_digests(
    cur_themes: list[dict[str, Any]], prev: tuple[str, dict[str, Any]] | None
) -> dict[str, Any]:
    """직전 다이제스트와의 변화 — 테마의 진입/이탈/순위 이동 + 테마별 종목의 신규 상위 N ·
    신규 하드 제외 · 신규 통과. 첫 실행이면 `first_run: true` ("기준일 없음, 전부 신규")."""
    if prev is None:
        return {
            "first_run": True,
            "prev_asof": None,
            "themes_entered": _theme_names(cur_themes, scoreboard_only=True),
            "themes_left": [],
            "rank_moves": {},
            "stocks": {},
            "note": "기준일 없음, 전부 신규",
        }
    prev_asof, prev_digest = prev
    prev_themes: list[dict[str, Any]] = list(prev_digest.get("themes", []))
    prev_by_name = {str(t["theme"]): t for t in prev_themes}

    cur_sb = _theme_names(cur_themes, scoreboard_only=True)
    prev_sb = set(_theme_names(prev_themes, scoreboard_only=True))
    entered = [t for t in cur_sb if t not in prev_sb]
    left = sorted(prev_sb - set(cur_sb))

    rank_moves: dict[str, int] = {}
    for t in cur_themes:
        name = str(t["theme"])
        p = prev_by_name.get(name)
        if p is None or t.get("rank") is None or p.get("rank") is None:
            continue
        delta = int(p["rank"]) - int(t["rank"])  # +N = N 계단 상승
        if delta:
            rank_moves[name] = delta

    stocks: dict[str, dict[str, list[str]]] = {}
    for t in cur_themes:
        name = str(t["theme"])
        p = prev_by_name.get(name)
        if p is None:
            continue  # 테마 자체가 신규 — themes_entered 가 말한다
        cur_top = [str(x["ticker"]) for x in t.get("picks", [])]
        prev_top = {str(x["ticker"]) for x in p.get("picks", [])}
        cur_elig = set(map(str, t.get("eligible_tickers", [])))
        prev_elig = set(map(str, p.get("eligible_tickers", [])))
        cur_hard = set(map(str, t.get("hard_excluded_tickers", [])))
        prev_hard = set(map(str, p.get("hard_excluded_tickers", [])))
        row = {
            "new_in_top": [x for x in cur_top if x not in prev_top],
            "newly_hard_excluded": sorted(cur_hard - prev_hard),
            "newly_passing": sorted(cur_elig - prev_elig),
        }
        if any(row.values()):
            stocks[name] = row
    return {
        "first_run": False,
        "prev_asof": prev_asof,
        "themes_entered": entered,
        "themes_left": left,
        "rank_moves": rank_moves,
        "stocks": stocks,
    }


# ---------------------------------------------------------------- 테마 항목 구성


def _num(v: Any) -> float | None:
    x = pd.to_numeric(v, errors="coerce")
    return None if pd.isna(x) else float(x)


def _sb_row(sb: pd.DataFrame, theme: str) -> pd.Series | None:
    if theme not in sb.index:
        return None
    got = sb.loc[theme]
    return got.iloc[0] if isinstance(got, pd.DataFrame) else got


def _pick_rows(ranking: pd.DataFrame, n: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tk, r in ranking.head(n).iterrows():
        row: dict[str, Any] = {"ticker": str(tk)}
        for c in PICK_COLUMNS:
            v = r.get(c)
            if c in ("group", "penalties", "red_flags"):
                row[c] = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
            elif c == "rank":
                row[c] = None if v is None or pd.isna(v) else int(v)
            else:
                row[c] = _num(v)
        rows.append(row)
    return rows


def _theme_entry(
    theme: str,
    sel: ThemeSelection,
    sb: pd.DataFrame,
    res: PicksResult | None,
    err: str | None,
    picks_per_theme: int,
) -> dict[str, Any]:
    row = _sb_row(sb, theme)
    entry: dict[str, Any] = {
        "theme": theme,
        "source": "extra" if theme in sel.extra else "scoreboard",
        "rank": sel.ranks.get(theme),
        "score": None if row is None else _num(row.get("score")),
        "pool": None if row is None else _num(row.get("pool")),
        "flags": list(sel.flags.get(theme, ())),
        "blocks": {}
        if row is None
        else {f"{b}_pct": _num(row.get(f"{b}_pct")) for b in BLOCKS if f"{b}_pct" in row.index},
        "picks": [],
        "eligible_tickers": [],
        "hard_excluded_tickers": [],
        "picks_error": err,
        "new_since_prev": False,  # diff 단계가 채운다
    }
    if res is not None:
        rk = res.ranking
        ex = res.excluded
        entry["picks"] = _pick_rows(rk, picks_per_theme)
        entry["eligible_tickers"] = [str(t) for t in rk.index]
        if len(ex) and "stage" in ex.columns:
            entry["hard_excluded_tickers"] = [
                str(t) for t in ex.index[ex["stage"] == "hard_filter"]
            ]
    return entry


# ---------------------------------------------------------------- 렌더링 (digest.md)


def _arrow(theme: str, diff: dict[str, Any]) -> str:
    if theme in diff.get("themes_entered", []):
        return "NEW"
    d = diff.get("rank_moves", {}).get(theme)
    if d is None:
        return "="
    return f"▲{d}" if d > 0 else f"▼{-d}"


def _f2(v: Any) -> str:
    return "—" if v is None else f"{float(v):.2f}"


def _pick_line(p: dict[str, Any], new_top: set[str]) -> str:
    adv = p.get("adv20_usd")
    adv_txt = "—" if adv is None else f"${ratio(adv / 1e6)}M"
    price = p.get("price")
    price_txt = "—" if price is None else f"${price:,.2f}"
    tail = []
    if p.get("penalties"):
        tail.append(f"감점[{p['penalties']}]")
    if p.get("red_flags"):
        tail.append(f"레드플래그[{p['red_flags']}]")
    if p["ticker"] in new_top:
        tail.append("NEW")
    return (
        f"- {p['ticker']:<6} {p.get('group') or '—':<7} 종합 {_f2(p.get('composite'))}  "
        f"S {_f2(p.get('s_pct'))} / T {_f2(p.get('t_pct'))} / M {_f2(p.get('m_pct'))}  "
        f"{price_txt} · ADV {adv_txt}" + (("  " + " · ".join(tail)) if tail else "")
    )


def new_item_lines(diff: dict[str, Any]) -> list[str]:
    """ "오늘 새로 올라온 것" — md 섹션과 텔레그램이 같은 줄을 쓴다. 사실의 나열이다."""
    if diff.get("first_run"):
        return ["기준일 없음, 전부 신규 (첫 다이제스트)"]
    L: list[str] = []
    for t in diff.get("themes_entered", []):
        L.append(f"테마 상위 K 진입: {t}")
    for t in diff.get("themes_left", []):
        L.append(f"테마 상위 K 이탈: {t}")
    for t, d in diff.get("rank_moves", {}).items():
        L.append(f"순위 이동: {t} {'▲' if d > 0 else '▼'}{abs(d)}")
    for t, row in diff.get("stocks", {}).items():
        if row.get("new_in_top"):
            L.append(f"{t}: 상위 N 신규 {', '.join(row['new_in_top'])}")
        if row.get("newly_passing"):
            L.append(f"{t}: 하드 필터 신규 통과 {', '.join(row['newly_passing'])}")
        if row.get("newly_hard_excluded"):
            L.append(f"{t}: 신규 하드 제외 {', '.join(row['newly_hard_excluded'])}")
    return L


def render_digest_md(digest: dict[str, Any]) -> str:
    """사람용 다이제스트 — 머리에 정직성 한 줄, 상위 K 표, 테마별 상위 N 한 줄씩, 새로 올라온
    것, 보유 점검 요약, "고르면 다음"."""
    diff = digest["diff"]
    themes: list[dict[str, Any]] = digest["themes"]
    L = [
        f"# 일간 후보 다이제스트 · {digest['asof']}",
        "",
        HONESTY_HEADER,
        "",
        f"스캔 기준일 {digest['scan'].get('asof')} (스토어 {digest['scan'].get('store_end')}) · "
        f"기준 다이제스트 {diff.get('prev_asof') or '없음 (첫 실행 — 전부 신규)'}",
        "",
        f"## 상위 K={digest['params']['top_k']} 테마",
        "",
        "| 순위 | 테마 | 점수 | pool | 플래그 | 변화 |",
        "|---:|---|---:|---:|---|---|",
    ]
    for t in themes:
        rank = "지정" if t["source"] == "extra" else ("—" if t["rank"] is None else str(t["rank"]))
        L.append(
            f"| {rank} | {t['theme']} | {_f2(t['score'])} | {_f2(t['pool'])} | "
            f"{', '.join(t['flags']) or '—'} | {_arrow(t['theme'], diff)} |"
        )
    n = digest["params"]["picks_per_theme"]
    L += [
        "",
        f"## 테마별 후보 상위 {n}",
        "",
        f"{n} 은 표시 개수이지 선정 규칙이 아니다 — 랭킹 전체는 `msa picks <theme>`.",
    ]
    for t in themes:
        blocks = t.get("blocks") or {}
        blocks_txt = " ".join(
            f"{b} {_f2(blocks.get(f'{b}_pct'))}" for b in BLOCKS if f"{b}_pct" in blocks
        )
        L += ["", f"### {t['theme']}" + (f"  ({blocks_txt})" if blocks_txt else "")]
        if t["picks_error"]:
            L.append(f"- picks 실패: {t['picks_error']}")
            continue
        if not t["picks"]:
            L.append("- 적격 종목 0")
            continue
        new_top = set(diff.get("stocks", {}).get(t["theme"], {}).get("new_in_top", []))
        if diff.get("first_run"):
            new_top = {p["ticker"] for p in t["picks"]}
        L += [_pick_line(p, new_top) for p in t["picks"]]
        n_elig = len(t["eligible_tickers"])
        if n_elig > len(t["picks"]):
            L.append(f"  (적격 {n_elig} 중 {len(t['picks'])} 표시 — 나머지는 `msa picks`)")
    L += ["", "## 오늘 새로 올라온 것", ""]
    news = new_item_lines(diff)
    L += [f"- {x}" for x in news] or ["- (없음)"]
    pc = digest.get("positions_check")
    if pc is not None:
        L += [
            "",
            "## 보유 점검",
            "",
            f"- 포지션 {pc['positions']} · 알림 {pc['alerts']} · 문제 {len(pc['problems'])} · "
            f"미체결 제안 {pc['unchecked']}"
            + (f" · 텔레그램 {pc['telegram']}" if pc.get("telegram") else ""),
        ]
        L += [f"- 문제: {x}" for x in pc["problems"]]
    L += [
        "",
        "## 고르면 다음",
        "",
        "- 테마를 골랐다면 `msa research <theme>` 또는 사람 논지(<dir>/<theme>.yaml) → "
        "`msa journal new --from` (무효화 조건 없는 논지는 저장되지 않는다, CLAUDE.md §5). "
        "결정 케이던스는 월간 그대로다 (`msa run monthly`).",
        "",
        HONESTY_HEADER + " 집행은 사람이 한다 (CLAUDE.md §8).",
        "",
    ]
    return "\n".join(L)


# ---------------------------------------------------------------- 텔레그램


def build_digest_alert(digest: dict[str, Any], asof_d: date) -> Alert:
    """다이제스트 → `AlertKind.DAILY_DIGEST` 알림. "오늘 새로 올라온 것" + 상위 3테마 한 줄씩,
    본문 ≤ `TELEGRAM_MAX_CHARS`(4000) 자 — 넘치면 새 항목을 줄이고 **자른 개수를 적는다**
    (`CLAUDE.md` §2 조용한 절단 금지). 문구 규약은 `format_alert` 안의 `assert_wording_ok` 가
    강제한다."""
    news = new_item_lines(digest["diff"])
    top3 = [
        f"{t['theme']} — 점수 {_f2(t['score'])} · pool {_f2(t['pool'])}"
        + (f" · {', '.join(t['flags'])}" if t["flags"] else "")
        for t in digest["themes"][:3]
    ]
    path = f"state/daily/{digest['asof']}/digest.md"

    def make(kept: int) -> Alert:
        return Alert(
            AlertKind.DAILY_DIGEST,
            asof_d,
            "-",
            None,
            {
                "asof": digest["asof"],
                "new_items": news[:kept],
                "omitted": len(news) - kept,
                "top3": top3,
                "path": path,
            },
        )

    kept = len(news)
    a = make(kept)
    a.text = format_alert(a)
    while len(a.text) > TELEGRAM_MAX_CHARS and kept > 0:
        kept -= 1
        a = make(kept)
        a.text = format_alert(a)
    return a


# ---------------------------------------------------------------- run_daily


def run_daily(
    *,
    asof: str | date | None = None,
    top_k: int = 8,
    extra_themes: Sequence[str] = (),
    picks_per_theme: int = 5,
    write: bool = True,
    send: bool = False,
) -> DailyResult:
    """일간 후보 다이제스트 한 번 (모듈 머리말 참조). 스캔 실패만 exit 1 — 나머지는 격리·보고."""
    if top_k < 0:
        raise RunError(f"top_k 는 0 이상: {top_k}")
    if picks_per_theme < 1:
        raise RunError(f"picks_per_theme 는 1 이상: {picks_per_theme}")
    asof_s = _asof_str(asof)
    p = paths()
    report = RunReport(
        cadence="daily",
        asof=asof_s,
        started_at=datetime.now().isoformat(timespec="seconds"),
        write=write,
        state_root=str(p.state),
        params={
            "top_k": top_k,
            "extra_themes": [str(t) for t in extra_themes],
            "picks_per_theme": picks_per_theme,
            "send": send,
        },
    )
    result = DailyResult(report=report)

    # 1) scan — 경성. 실패면 중단 (부분 데이터로 후보를 내지 않는다, CLAUDE.md §2)
    t = _Timer()
    try:
        scan = run_scan(asof=asof_s, write=False)
    except Exception as e:
        log.exception("run daily: scan 실패 — 중단")
        report.add(StepResult("scan", "failed", _err(e), seconds=t.seconds))
        report.stopped = True
        report.stopped_reason = f"scan 실패 — {_err(e)}"
        _skip_rest(report, DAILY_STEPS, "scan 실패로 중단")
        return result
    result.scan = scan
    sb = scan.scoreboard.table
    report.add(
        StepResult(
            "scan",
            "ok",
            f"테마 {len(sb)} · 스캔 기준일 {scan.meta.get('asof')} "
            f"(스토어 {scan.meta.get('store_end')})",
            seconds=t.seconds,
        )
    )

    # 2) select — 월간과 같은 규칙 (자격 상위 K + 지정; 풀 미달로 채우지 않는다)
    t = _Timer()
    sel = select_themes(sb, top_k=top_k, extra_themes=extra_themes)
    result.selection = sel
    report.add(
        StepResult(
            "select",
            "ok",
            f"선정 {len(sel.selected)} (자격 {sel.n_eligible}/{sel.n_total}, "
            f"지정 {len(sel.extra)})",
            seconds=t.seconds,
        )
    )

    # 3) picks — 테마별 격리. 다이제스트용이라 스냅샷은 쓰지 않는다 (write=False)
    t = _Timer()
    errors: dict[str, str] = {}
    for th in sel.selected:
        try:
            result.picks[th] = run_picks(th, asof=asof_s, write=False)
        except Exception as e:
            log.warning("run daily: picks %s 실패 — %s", th, _err(e))
            errors[th] = _err(e)
    report.add(
        StepResult(
            "picks",
            "ok" if result.picks or not sel.selected else "failed",
            f"테마 {len(result.picks)}/{len(sel.selected)} 랭킹"
            + (" · 실패 " + "; ".join(f"{k} ({v})" for k, v in errors.items()) if errors else ""),
            seconds=t.seconds,
            details={"failed": errors},
        )
    )
    themes = [
        _theme_entry(th, sel, sb, result.picks.get(th), errors.get(th), picks_per_theme)
        for th in sel.selected
    ]

    # 4) diff — 직전 다이제스트는 실제 state/daily/ 에서 읽는다 (no-write 여도)
    t = _Timer()
    try:
        prev = previous_digest(p.daily, asof_s)
    except RunError as e:
        report.notes.append(str(e))
        prev = None
    diff = diff_digests(themes, prev)
    for te in themes:
        te["new_since_prev"] = bool(diff["first_run"]) or te["theme"] in diff["themes_entered"]
    report.add(
        StepResult(
            "diff",
            "ok",
            "첫 실행 — 기준일 없음, 전부 신규"
            if diff["first_run"]
            else f"기준 {diff['prev_asof']} · 새 항목 {len(new_item_lines(diff))}",
            seconds=t.seconds,
        )
    )

    # 5) check — 보유가 있을 때만 (msa check --daily 와 같은 경로 재사용)
    pc: dict[str, Any] | None = None
    if p.positions.exists():
        t = _Timer()
        try:
            chk, info = run_cadence_check(asof_s, mode="daily", write=write)
        except Exception as e:
            log.warning("run daily: check 실패 — %s", _err(e))
            report.add(StepResult("check", "failed", _err(e), seconds=t.seconds))
        else:
            result.check = chk
            pc = {
                "positions": len(chk.positions),
                "alerts": len(chk.alerts),
                "problems": list(chk.problems),
                "unchecked": len(chk.unchecked),
                "telegram": info.get("telegram"),
            }
            report.add(
                StepResult(
                    "check",
                    "ok",
                    f"포지션 {pc['positions']} · 알림 {pc['alerts']} · 문제 {len(chk.problems)}",
                    [rel(chk.out_dir)] if chk.out_dir else [],
                    t.seconds,
                )
            )
            for pr in chk.problems:
                report.human_todo.append(f"check 문제: {pr}")
    else:
        report.add(StepResult("check", "skipped", "state/positions.yaml 없음 — 보유 없음"))

    # 6) digest — json(기계) + md(사람) + report.txt(= md)
    t = _Timer()
    digest: dict[str, Any] = {
        "asof": asof_s,
        "generated_at": report.started_at,
        "params": dict(report.params),
        "scan": {
            "asof": scan.meta.get("asof"),
            "store_end": scan.meta.get("store_end"),
            "bucket": scan.meta.get("bucket"),
        },
        "themes": themes,
        "diff": diff,
        "positions_check": pc,
        "note": HONESTY_HEADER,
    }
    result.digest = digest
    result.digest_md = render_digest_md(digest)
    out_dir: Path | None = None
    if write:
        out_dir = write_snapshot(
            p.daily / asof_s,
            texts={"digest.md": result.digest_md, "report.txt": result.digest_md},
            jsons={"digest.json": digest},
        )
        result.out_dir = out_dir
        report.out_dir = str(out_dir)
        outs = [rel(out_dir / "digest.md"), rel(out_dir / "digest.json")]
        report.add(StepResult("digest", "ok", "", outs, t.seconds))
    else:
        report.add(StepResult("digest", "ok", "no-write — 파일을 쓰지 않았다", seconds=t.seconds))

    # 7) 텔레그램 (선택) — deliver 는 alerts.json 을 쓰는 계약이라 write=False 면 보내지 않는다
    if send:
        if out_dir is None:
            report.notes.append("--send 는 no-write 와 함께 쓸 수 없다 — 보내지 않았다")
        else:
            alert = build_digest_alert(digest, date.fromisoformat(asof_s))
            dres = deliver([alert], out_dir, use_env=True)
            result.telegram = str(dres.status)
            report.notes.append(f"텔레그램: {dres.status}")
    return result


__all__ = [
    "DAILY_STEPS",
    "HONESTY_HEADER",
    "PICK_COLUMNS",
    "TELEGRAM_MAX_CHARS",
    "DailyResult",
    "build_digest_alert",
    "diff_digests",
    "new_item_lines",
    "previous_digest",
    "render_digest_md",
    "run_daily",
]
