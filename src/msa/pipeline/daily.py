"""일간 후보 다이제스트 — `msa run daily` (`docs/09` §1 일간 행).

주인의 요구는 "오늘의 종목을 보고 싶다 — 무슨 먹을거리가 올라오는지 매일 보고, 그중에서
고른다" 이다. **월간이 결정 케이던스라는 사실은 바뀌지 않는다** — 이 명령은 읽기 전용
후보 뷰다: 스캔(캐시 덕에 ~12초) → 상위 K 테마 선정(`select_themes` 재사용) → 테마별 L4
랭킹(`run_picks`, 스냅샷은 쓰지 않는다) → **직전 다이제스트와의 diff**(무엇이 새로 올라왔나)
→ 보유가 있으면 무효화 점검(`run_cadence_check(mode="daily")` — `msa check --daily` 와 같은
경로) → `state/daily/<asof>/digest.json`·`digest.md`·`report.txt`.

새 계산·새 임계값은 없다 (`CLAUDE.md` §1) — `top_k`(기본 8 = `docs/05` §1 의 K)와
`picks_per_theme`(기본 5)뿐이고, **5 는 표시 개수이지 선정 규칙이 아니다.** L4 의 선정은
2026-08-24 부터 **하드 제외 통과 종목 전부 · 테마 내 동일가중**이고, 다이제스트가 싣는
종합·순위·3축·바벨 라벨은 전부 **관찰 지표**다 (`docs/06` §6.1 ·
`journal/2026-08-24-l4-selection-retired.md`). 표시 순서를 K 로 잘라 쓰는 것은 이 명령이 정하는
바가 아니다. LLM 은 부르지 않는다 — 전 단계가 결정론이다 (`CLAUDE.md` §4).

## 2026-08-24 — 다이제스트도 `msa picks` 와 **같은 모양**이다

테마마다 **논지 한 줄 + 무효화 조건 → 적격 종목 전부(판단 재료 표) → 제외와 사유** 순이다.
사용자가 못박은 역할 분담이 그 형태를 정한다: 시스템은 테마를 고르고 명단을 재료와 함께
내놓고, **최종 종목과 진입 시점은 사람이 차트를 보고 정한다.**

- `digest.json` 의 `picks` 는 이제 **적격 전부**다 (옛 판은 `picks_per_theme` 개까지였다).
  자르는 곳은 **표시하는 쪽**이다 — diff 의 "상위 N 신규"(`diff_digests(top_n=…)`)와
  텔레그램(`build_digest_alert`)이고, 텔레그램은 줄인 개수를 본문에 적는다.
- 표의 열은 `l4.picks.TABLE_HEADERS` 를 그대로 쓰고 칸 포맷도 `judgment_cells` 하나를 쓴다 —
  같은 종목이 리포트와 다이제스트에서 다른 숫자로 보이지 않게.
- 유동성·저가 감점이 꺼져 있다는 사실(`axes.disabled_penalty_note`)과 `vcp_base` 의 결함
  (`l4.picks.VCP_DEFECT_NOTE`)이 md·텔레그램 양쪽에 적힌다. **새 임계·새 계산은 없다.**

정직성: L1 점수는 약하고 겨우 검증된 신호다 — 복합 점수의 예측력은 관문에서 0 에
가까웠고 C 블록만 일했다 (`docs/backtest-l1.md` §12 · `docs/02` §7.1). 다이제스트 머리에
그 사실을 적는다. **이것은 후보 목록이지 투자 권유가 아니다** (`CLAUDE.md` §8) — 문구는
`ops/alerts.assert_wording_ok` 의 규약을 따른다.

실패 규약은 월간과 같다: 스캔 실패 = 중단(exit 1), 테마별 picks 실패는 격리·보고,
점검 실패는 보고. `write=False` 면 `state/` 에 아무것도 쓰지 않는다 — 이 파이프라인의
모든 단계가 `write=False` 로 돌 수 있어 샌드박스가 필요 없다. diff 의 기준(직전
다이제스트)은 어느 경우든 실제 `state/daily/` 에서 읽는다 (읽기는 부작용이 아니다).

텔레그램: **`send` 가 이 실행의 모든 발신을 지배한다** — 다이제스트 요약뿐 아니라 보유 점검이
만든 알림(무효화·사다리·TP·시간스탑·Tier-2)까지다. `send=False`(CLI 기본 = `--send` 없음)면
어느 채널로도 나가지 않고 `alerts.json` 만 남는다(`suppressed`). `send=True` + `write=True` 일
때만 "오늘 새로 올라온 것" + 테마 요약을 `AlertKind.DAILY_DIGEST` 로 `deliver` 에 태운다 —
환경변수 둘 다 없으면 "not configured" (기존 규약 그대로). `write=False` 면 보내지 않는다 —
`deliver` 는 `alerts.json` 을 쓰는 계약이라서다 (그 사실을 리포트에 적는다).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from msa import triage as triage_mod
from msa.config import REPO_ROOT, paths, rel
from msa.io import write_snapshot
from msa.l1.scan import asof_note, run_scan, scan_dirs
from msa.l1.scoreboard import BLOCKS
from msa.l4 import axes
from msa.l4.picks import (
    JUDGMENT_COLUMNS,
    TABLE_HEADERS,
    VCP_DEFECT_NOTE,
    PicksResult,
    judgment_cells,
    run_picks,
)
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
from msa.thesis import NO_THESIS_NOTE, all_theses, thesis_head

log = logging.getLogger(__name__)

#: 일간 단계 (순서 = 실행 순서 = 리포트 순서).
#: 단계 이름. `readme` 는 2026-08-25 에 붙었다 — README 의 "오늘의 결론" 블록 갱신.
#: 실패해도 다이제스트를 죽이지 않지만 **단계로 세어 결과를 보고한다** (`CLAUDE.md` §2).
DAILY_STEPS: tuple[str, ...] = (
    "scan",
    "select",
    "picks",
    "diff",
    "check",
    "digest",
    # 판별은 다이제스트 **뒤**에 온다 — 무엇을 판별할지는 순위와 기존 판정이 다 나와야
    # 정해지기 때문이다. 새로 편입 가능이 나오면 판정을 갱신하고 다이제스트를 다시 쓴다.
    "research",
    "audit",
    # 트리아지는 **실사 뒤**다 — J 축이 `evidence_audit` 을 읽으므로, 앞에 두면 오늘
    # 실사한 결과가 오늘 점수에 안 들어간다 (스펙 §5.1.3).
    "triage",
    "readme",
)

#: 다이제스트 머리 한 줄 — 모든 산출물(md·txt·텔레그램)이 같은 사실에서 시작한다.
HONESTY_HEADER = (
    "측정값·후보 목록 — 투자 조언 아님; L1 점수 예측력 약함(docs/02 §7.1); "
    "L4 선정 = 하드 제외 통과 전부·동일가중, 종합·순위·바벨은 관찰 지표(docs/06 §6.1)."
)

#: 텔레그램 본문 상한 (Telegram sendMessage 한도 4096 — 여유를 둔다).
TELEGRAM_MAX_CHARS = 4000

#: 다이제스트에 싣는 종목당 랭킹 열 — **`l4.picks.JUDGMENT_COLUMNS` 전부** + 관찰 지표.
#: 2026-08-24: 판단 재료(시총·ND/EBITDA+basis·런웨이·**52주 고점 대비**·RS·Stage2/50d/VCP)가
#: 여기 없어서 다이제스트가 `msa picks` 보다 적게 보여 주고 있었다. 계산은 이미 다 돼 있었다 —
#: 옮겨 싣기만 한다. 어떤 판정도 이 목록을 읽지 않는다.
PICK_COLUMNS: tuple[str, ...] = (
    "rank",
    "group",
    "barbell_obs",
    "composite",
    "composite_partial",
    "s_pct",
    "t_pct",
    "m_pct",
    "s_partial",
    *JUDGMENT_COLUMNS,
)

#: `PICK_COLUMNS` 중 문자열 · 불리언 열 (나머지는 수치). 형을 여기서 한 번만 정한다.
_PICK_TEXT: frozenset[str] = frozenset(
    {"group", "barbell_obs", "penalties", "red_flags", "name", "nd_basis"}
)
_PICK_BOOL: frozenset[str] = frozenset(
    {"stage2", "above_50d", "vcp_base", "s_partial", "composite_partial"}
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
    cur_themes: list[dict[str, Any]],
    prev: tuple[str, dict[str, Any]] | None,
    *,
    baseline_error: str | None = None,
    top_n: int = 5,
) -> dict[str, Any]:
    """직전 다이제스트와의 변화 — 테마의 진입/이탈/순위 이동 + 테마별 종목의 신규 상위 N ·
    신규 하드 제외 · 신규 통과. 첫 실행이면 `first_run: true` ("기준일 없음, 전부 신규").

    `baseline_error` 는 **직전 기준이 있었는데 읽지 못한 경우**다 (`previous_digest` 가 던진
    사유). 이때는 첫 실행이 아니다 — `first_run: false` · `baseline_broken: <사유>` 로 두고
    diff 를 내지 않는다. "첫 실행 — 전부 신규" 로 둔갑시키면 그날 diff 전체가 거짓이 된다
    (`CLAUDE.md` §2)."""
    if baseline_error is not None:
        return {
            "first_run": False,
            "baseline_broken": baseline_error,
            "prev_asof": None,
            "themes_entered": [],
            "themes_left": [],
            "rank_moves": {},
            "stocks": {},
            "note": f"직전 기준 다이제스트 손상 — 오늘 diff 를 내지 않았다: {baseline_error}",
        }
    if prev is None:
        return {
            "first_run": True,
            "baseline_broken": None,
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
        # `picks` 는 2026-08-24 부터 적격 **전부**다 — "상위 N" 은 여기서 앞 N 개로 정의한다.
        # 옛 다이제스트의 `picks` 는 이미 N 개였으므로 앞 N 개를 취해도 같은 집합이다.
        cur_top = [str(x["ticker"]) for x in t.get("picks", [])[:top_n]]
        prev_top = {str(x["ticker"]) for x in p.get("picks", [])[:top_n]}
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
        "baseline_broken": None,
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


def _pick_rows(ranking: pd.DataFrame) -> list[dict[str, Any]]:
    """적격 종목 **전부**를 관찰 순위 순으로 (2026-08-24). 잘라 담지 않는다 — 이 목록이 명단이다.

    잘라 내는 곳은 표시하는 쪽이다: 텔레그램은 길이 제한이 있어 앞에서 몇 개만 싣고 **몇 개를
    줄였는지 본문에 적는다**(`build_digest_alert`), diff 의 "상위 N 신규" 도 앞 N 개만 본다
    (`diff_digests(top_n=...)`). 그래야 무엇이 잘렸는지가 산출물에 남는다 (`CLAUDE.md` §2).
    """
    rows: list[dict[str, Any]] = []
    for tk, r in ranking.iterrows():
        row: dict[str, Any] = {"ticker": str(tk)}
        for c in PICK_COLUMNS:
            v = r.get(c)
            if c in _PICK_TEXT:
                row[c] = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
            elif c in _PICK_BOOL:
                row[c] = None if v is None or v is pd.NA or pd.isna(v) else bool(v)
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
    asof: str,
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
        # 제외 **사유** — "왜 이 종목이 명단에 없나" 를 다이제스트만 보고도 답할 수 있어야 한다
        # (2026-08-24). 티커만 있던 자리에 사유가 붙었고, 어떤 판정도 바뀌지 않았다.
        "excluded": [],
        "picks_error": err,
        "new_since_prev": False,  # diff 단계가 채운다
    }
    if res is not None:
        rk = res.ranking
        ex = res.excluded
        entry["picks"] = _pick_rows(rk)
        entry["eligible_tickers"] = [str(t) for t in rk.index]
        if len(ex) and "stage" in ex.columns:
            entry["hard_excluded_tickers"] = [
                str(t) for t in ex.index[ex["stage"] == "hard_filter"]
            ]
            entry["excluded"] = [
                {"ticker": str(t), "stage": str(r["stage"]), "reason": str(r["reason"])}
                for t, r in ex.iterrows()
            ]
    # 논지 — picks 가 실패해도 붙는다 (논지는 L3 의 산출이고 L4 실패와 무관하다).
    # asof 는 호출자가 준다: 그 날짜 **이하**의 최신 논지만 찾는다 (PIT 규약).
    head = thesis_head(theme, asof)
    entry["thesis"] = {
        "found": head.found,
        "source": head.source or None,
        "claim": head.claim or None,
        "invalidations": list(head.invalidations),
        # `gate` 와 `portfolio_eligible` 은 다른 값이다 — `passed` 이면서 편입 불가인 경우가
        # 흔하다(확신도 기준선 미달). 둘을 같이 실어야 읽는 쪽이 혼동하지 않는다.
        "gate": head.gate,
        "portfolio_eligible": head.eligible,
        "trusted": head.trusted,
        "cycle_confidence": head.cycle_confidence,
        "lines": head.lines(),
    }
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


def _clip(s: str, n: int) -> str:
    """길이 제한이 있는 채널(텔레그램)용 축약 — 자른 자리에 `…` 를 남긴다."""
    t = " ".join(str(s or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _md_cell(s: str) -> str:
    """마크다운 표 칸 — `|` 만 이스케이프한다 (감점 문자열에 `[`·`]` 가 들어 있어도 그대로 둔다)."""
    return s.replace("|", "\\|")


def roster_table_md(picks: list[dict[str, Any]], new_top: set[str]) -> list[str]:
    """테마의 명단 — `msa picks` 리포트와 **같은 열**(`l4.picks.TABLE_HEADERS`)의 마크다운 표.

    칸 포맷은 `l4.picks.judgment_cells` 하나를 쓴다. 다이제스트가 자기 포맷을 따로 들면 같은
    종목이 두 산출물에서 다른 숫자로 보인다.
    """
    if not picks:
        return ["- 적격 종목 0"]
    heads = [*TABLE_HEADERS, "변화"]
    out = [
        "| " + " | ".join(heads) + " |",
        "|" + "|".join("---" for _ in heads) + "|",
    ]
    for p in picks:
        tk = str(p["ticker"])
        cells = [_md_cell(c) for c in judgment_cells(tk, p)]
        out.append("| " + " | ".join([*cells, "NEW" if tk in new_top else ""]) + " |")
    return out


def excluded_lines_md(ex: list[dict[str, Any]], theme: str = "<theme>") -> list[str]:
    """제외와 사유 — 명단 **아래**에 붙는다. "왜 이 종목이 없나" 를 다이제스트만 보고 답할 수 있게.

    하드 필터 제외는 **한 줄씩 사유와 함께** 적는다 — 런웨이·부채 같은 판단 재료가 거기 있다.

    상장 단계 제외(폐지·가격 없음)는 **수와 사유만** 적고 티커 전문은 `excluded.csv` 로 넘긴다
    (2026-08-25). 예전에는 티커를 한 줄에 전부 나열했는데, `media_streaming` 만 160종목이라
    다이제스트 24KB 중 대부분이 `TWX`·`VIAB` 같은 폐지 티커 문자열이었고 정작 봐야 할
    hard_filter 사유가 그 사이에 묻혔다. **수와 경로를 적으면 절단이 아니다** (`CLAUDE.md` §2 는
    "잘린 것을 표시하라" 이지 "전문을 인라인하라" 가 아니다).
    """
    if not ex:
        return ["", "제외 0"]
    listing = [x for x in ex if x.get("stage") == "listing"]
    rest = [x for x in ex if x.get("stage") != "listing"]
    out = ["", f"제외 {len(ex)} — 왜 이 종목이 위에 없나:"]
    out += [f"- `{x['ticker']}` [{x['stage']}] {x['reason']}" for x in rest]
    if listing:
        why = sorted({str(x["reason"]) for x in listing})
        out.append(
            f"- [listing] {len(listing)}종목 ({' · '.join(why)}) — 티커 전문은 "
            f"`state/picks/<date>/{theme}/excluded.csv`"
        )
    return out


def new_item_lines(diff: dict[str, Any]) -> list[str]:
    """ "오늘 새로 올라온 것" — md 섹션과 텔레그램이 같은 줄을 쓴다. 사실의 나열이다."""
    if diff.get("baseline_broken"):
        return [
            "직전 기준 다이제스트 손상 — 오늘 변화(diff)를 내지 않았다 "
            f"({diff['baseline_broken']}). 첫 실행이 아니다"
        ]
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


def _eligibility_cell(theme: dict[str, Any]) -> str:
    """상위 K 표의 `편입` 열. 순위표만 보고 사는 것을 막는 유일한 열이다."""
    th = theme.get("thesis") or {}
    if not th.get("found"):
        return "판별 안 함"
    conf = th.get("cycle_confidence")
    c = f"{float(conf):g}" if isinstance(conf, int | float) else "?"
    return f"**가능** {c}" if th.get("portfolio_eligible") else f"불가 {c}"


def _conclusion_lines(digest: dict[str, Any]) -> list[str]:
    """다이제스트 머리의 결론. `readme_block._headline` 을 그대로 쓴다 — 같은 사실에서
    두 문서가 갈라지지 않게."""
    from msa.ops.readme_block import _dip_lines, _headline

    verdict, detail = _headline(digest)
    out = [f"> **{verdict}**", ">", f"> {detail}", ""]
    # 결론이 가리키는 종목 표를 **여기에도** 싣는다. 예전에는 README 블록에만 있어서
    # 다이제스트만 읽는 사람에게는 결론이 가리키는 대상이 없었다 (2026-08-26).
    out += _dip_lines(list(digest.get("themes") or []))
    return [*out, ""]


def render_digest_md(digest: dict[str, Any]) -> str:
    """사람용 다이제스트 — 머리에 정직성 한 줄, 상위 K 표, 테마별 상위 N 한 줄씩, 새로 올라온
    것, 보유 점검 요약, "고르면 다음"."""
    diff = digest["diff"]
    themes: list[dict[str, Any]] = digest["themes"]
    L = [
        f"# 일간 후보 다이제스트 · {digest['asof']}",
        "",
        # 결론이 먼저다. **README 와 같은 함수**를 쓴다 — 두 산출물이 다른 결론을 말하는 것을
        # 구조적으로 막는다 (2026-08-25 검토 지적: "결론을 모르겠다").
        *_conclusion_lines(digest),
        HONESTY_HEADER,
        "",
        # 제목의 날짜는 요청한 날짜다 — 데이터가 그보다 이전이면 **바로 여기서** 말한다.
        *([f"> **{asof_note(digest['scan'])}**", ""] if digest["scan"].get("asof_clamped") else []),
        f"스캔 기준일 {digest['scan'].get('asof')} (스토어 {digest['scan'].get('store_end')}) · "
        "기준 다이제스트 "
        + (
            f"손상 — 읽지 못했다 ({diff['baseline_broken']}). 오늘 diff 없음 (첫 실행이 아니다)"
            if diff.get("baseline_broken")
            else (diff.get("prev_asof") or "없음 (첫 실행 — 전부 신규)")
        ),
        "",
        f"## 상위 K={digest['params']['top_k']} 테마",
        "",
        "| 순위 | 테마 | 점수 | pool | **편입** | 플래그 | 변화 |",
        "|---:|---|---:|---:|---|---|---|",
    ]
    for t in themes:
        rank = "지정" if t["source"] == "extra" else ("—" if t["rank"] is None else str(t["rank"]))
        L.append(
            f"| {rank} | {t['theme']} | {_f2(t['score'])} | {_f2(t['pool'])} | "
            f"{_eligibility_cell(t)} | {', '.join(t['flags']) or '—'} | "
            f"{_arrow(t['theme'], diff)} |"
        )
    dem = digest.get("demoted") or []
    if dem:
        who = ", ".join(
            f"{d['theme']}(스코어보드 #{d['rank']})" if d.get("rank") is not None else d["theme"]
            for d in dem
        )
        L += [
            "",
            f"위 표에 없는 테마 {len(dem)} — **소표본이라 뒤로 밀려 상위 K 에서 빠졌다**: {who}. "
            "소표본을 뒤로 미는 것은 선언된 동작이고(구성원이 `min_constituents` 미만이면 중앙값 "
            "통계를 믿을 수 없다), 스코어보드 `rank` 는 순수 점수 순이라 위 표의 순위가 1 부터 "
            "시작하지 않을 수 있다.",
        ]
    n = digest["params"]["picks_per_theme"]
    note = axes.disabled_penalty_note()
    L += [
        "",
        "## 테마별 명단",
        "",
        "테마마다 **논지 한 줄 + 무효화 조건 → 적격 종목 전부 → 제외와 사유** 순이다. "
        "명단이 판단 재료이고, **최종 종목과 진입 시점은 사람이 차트를 보고 정한다.**",
        "",
        "L4 의 선정은 **하드 제외를 통과한 적격 종목 전부 · 테마 내 동일가중**이다 "
        "(`docs/06` §5.1·§6.1 · `docs/15` §5). 표의 어느 열도, 표시 순서도 "
        "**선정에 쓰이지 않는다** — 순서는 관찰 순위다.",
        "",
        f"{VCP_DEFECT_NOTE}",
    ]
    if note:
        L += ["", note]
    L += ["", f"텔레그램 요약은 테마당 상위 {n} 종목만 싣는다 (줄인 수는 그 본문에 적힌다)."]
    for t in themes:
        blocks = t.get("blocks") or {}
        blocks_txt = " ".join(
            f"{b} {_f2(blocks.get(f'{b}_pct'))}" for b in BLOCKS if f"{b}_pct" in blocks
        )
        rank = (
            "지정" if t["source"] == "extra" else ("—" if t["rank"] is None else f"{t['rank']}위")
        )
        th = t.get("thesis") or {}
        # 제목에 편입 여부를 박는다. 괄호 안 다섯 항목 중 넷째로 묻히면 훑는 눈에 안 걸린다.
        if not th.get("found"):
            mark = " — 판별 안 함"
        elif not th.get("trusted", True):
            mark = " — **논지 신뢰 불가** (산출 주체 없음)"
        elif th.get("portfolio_eligible"):
            mark = " — **편입 가능**"
        else:
            mark = " — **편입 불가** (아래 명단은 관찰용)"
        head = f"### ■ {t['theme']}{mark}  (스코어보드 {rank} · {_arrow(t['theme'], diff)})"
        L += ["", head + (f"  {blocks_txt}" if blocks_txt else ""), ""]
        L += th.get("lines") or [f"논지: {NO_THESIS_NOTE}"]
        if t["picks_error"]:
            L += ["", f"- picks 실패: {t['picks_error']}"]
            continue
        new_top = set(diff.get("stocks", {}).get(t["theme"], {}).get("new_in_top", []))
        if diff.get("first_run"):
            new_top = {p["ticker"] for p in t["picks"]}
        n_ok = len(t["eligible_tickers"])
        if th.get("found") and not th.get("portfolio_eligible"):
            L += [
                "",
                f"> ⚠ **이 테마는 편입 불가 판정을 받았다.** 아래 {n_ok}종목은 재무 하드 필터를",
                "> 통과했다는 **사실**일 뿐 후보가 아니다. 사려면 테마가 먼저 통과해야 한다.",
                "",
                f"하드필터 통과 {n_ok} 종목 (선정이 아니다):",
                "",
            ]
        elif not th.get("found"):
            L += [
                "",
                f"> ⚠ **이 테마는 판별을 거치지 않았다.** 아래 {n_ok}종목은 함정 여부가",
                "> 판정되지 않은 테마의 구성원이다 — `msa research` 로 판정을 먼저 받아라.",
                "",
                f"하드필터 통과 {n_ok} 종목 (선정이 아니다):",
                "",
            ]
        else:
            L += ["", f"하드필터 통과 {n_ok} 종목 전부 · 테마 내 동일가중:", ""]
        L += roster_table_md(t["picks"], new_top)
        L += excluded_lines_md(t.get("excluded") or [], t["theme"])
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


#: 플래그 → 사람이 읽는 뜻. 알림에 쓴 플래그만 범례로 붙인다 (`docs/02` §9 · `docs/04` §3).
FLAG_MEANING: tuple[tuple[str, str], ...] = (
    ("SECULAR", "SECULAR = 사양산업일 수 있어 5축 게이트 통과를 입증해야 후보다 (docs/04 §3)"),
    (
        "소표본",
        "소표본 = 생존 구성원이 min_constituents 미만 — 중앙값 통계 신뢰 불가, 상위 K 에서 뒤로",
    ),
    ("풀 미달", "풀 미달 = A·B 자격(≥0.5) 미달 — 순위 없이 관찰 목록 (docs/02 §7.1)"),
    ("short_hist", "short_hist = 자기이력 7년 미만이라 백분위 대신 z-score 를 썼다"),
    (
        "axis1:data_missing",
        "axis1:data_missing = 물량 시계열이 없어 가치함정 축 1 을 계산하지 못했다",
    ),
    ("breadth_lead", "breadth_lead=Nm = 구성원 절반이 200일선을 지수보다 N개월 먼저 넘었다"),
    ("no_etf_proxy", "no_etf_proxy = 대조할 ETF 가 없어 자체지수 검증이 불가하다"),
    ("blocks_missing", "blocks_missing = 그 블록의 지표가 전부 없어 남은 가중치로 재정규화했다"),
)


#: 텔레그램 한 줄에 싣는 판단 재료 (`l4.picks.TABLE_HEADERS` 의 부분집합). 길이 제한이 있어
#: 전부는 못 싣는다 — 무엇을 실을지는 사람이 차트를 열기 전에 보는 순서다 (2026-08-24).
#: 잘린 열은 `digest.md` 의 같은 표에 전부 있고, 알림 본문이 그 경로를 적는다.
ALERT_CELLS: tuple[str, ...] = ("시총", "가격", "ADV20", "ND/EBITDA", "런웨이", "52wH", "RS")


def _alert_pick_line(p: dict[str, Any]) -> str:
    """알림용 종목 한 줄 — 사실만. 칸 포맷은 `judgment_cells` 하나를 쓴다 (리포트·md 와 같은 값)."""
    tk = str(p["ticker"])
    cells = dict(zip(TABLE_HEADERS, judgment_cells(tk, p), strict=True))
    bits = [tk]
    bits += [f"{h} {cells[h]}" for h in ALERT_CELLS if cells.get(h) not in (None, "", "n/a")]
    if cells.get("비고"):
        bits.append(cells["비고"])
    if p.get("new_in_top"):
        bits.append("NEW")
    return " · ".join(bits)


def build_digest_alert(digest: dict[str, Any], asof_d: date, *, picks_per_theme: int = 3) -> Alert:
    """다이제스트 → `AlertKind.DAILY_DIGEST` 알림.

    담는 것: **`HONESTY_HEADER` 와 같은 고지**(파일이 두 번 적는 것을 텔레그램도 적는다 —
    본문이 종합·순위를 나열하므로 알림만 보는 사람이 그것을 선정 규칙으로 읽으면 안 된다) ·
    오늘 새로 올라온 것 · **상위 K 테마 전부**(점수·pool·플래그) · 소표본 강등 ·
    **테마별 종목**(그룹·종합·S/T/M·가격·거래대금·레드플래그) · 쓰인 플래그의 뜻 · 보유 점검 요약.
    본문 ≤ `TELEGRAM_MAX_CHARS`(4000). 넘치면 **종목 → 테마 → 새 항목** 순으로 줄이고
    **줄인 개수를 본문에 적는다** (`CLAUDE.md` §2 조용한 절단 금지). 문구 규약은
    `format_alert` 안의 `assert_wording_ok` 가 강제한다."""
    news = new_item_lines(digest["diff"])
    path = f"state/daily/{digest['asof']}/digest.md"
    all_themes = digest["themes"]

    def theme_blocks(n_themes: int, n_picks: int, *, thesis: int = 2) -> list[dict[str, Any]]:
        """`thesis`: 2 = 논지 + 무효화 조건 1개 · 1 = 논지만 (길이에 밀릴 때). 논지 줄 자체는
        절대 빠지지 않는다 — 명단이 어느 논지 아래 있는지가 이 알림에서 가장 먼저 읽혀야 한다."""
        out = []
        for t in all_themes[:n_themes]:
            head = f"{t['theme']} — 점수 {_f2(t['score'])} · pool {_f2(t['pool'])}"
            if t.get("rank") is not None:
                head += f" · 스코어보드 {int(t['rank'])}위"
            if t.get("flags"):
                head += f" · {', '.join(t['flags'])}"
            picks = [_alert_pick_line(p) for p in (t.get("picks") or [])[:n_picks]]
            n_elig = len(t.get("eligible_tickers") or [])
            th = t.get("thesis") or {}
            out.append(
                {
                    "head": head,
                    "picks": picks,
                    "n_eligible": n_elig,
                    # 논지 한 줄 + 무효화 조건 1개 — 길이 제한 때문에 자른다. 전문은 digest.md
                    "thesis": (
                        (
                            _clip(str(th.get("claim") or ""), 140)
                            if th.get("found")
                            else NO_THESIS_NOTE
                        )
                        if thesis >= 1
                        else ""
                    ),
                    "invalidation": (
                        _clip(str((th.get("invalidations") or [""])[0]), 110) if thesis >= 2 else ""
                    ),
                    "n_invalidations": len(th.get("invalidations") or []),
                    "n_excluded": len(t.get("excluded") or []),
                }
            )
        return out

    def legend_for(blocks: list[dict[str, Any]]) -> list[str]:
        text = " ".join(b["head"] for b in blocks)
        return [meaning for key, meaning in FLAG_MEANING if key in text]

    def make(n_themes: int, n_picks: int, kept_news: int, thesis: int = 2) -> Alert:
        blocks = theme_blocks(n_themes, n_picks, thesis=thesis)
        pc = digest.get("positions_check")
        return Alert(
            AlertKind.DAILY_DIGEST,
            asof_d,
            "-",
            None,
            {
                "asof": digest["asof"],
                "new_items": news[:kept_news],
                "omitted": len(news) - kept_news,
                "themes": blocks,
                "themes_omitted": len(all_themes) - n_themes,
                "picks_per_theme": n_picks,
                # 길이에 밀려 무효화 조건을 뺐으면 그렇다고 적는다 (CLAUDE.md §2)
                "thesis_trimmed": (
                    "" if thesis >= 2 else "길이 제한으로 무효화 조건을 뺐다 — 전문은 아래 경로에"
                ),
                "legend": legend_for(blocks),
                # 무엇을 껐는지 알림에도 적는다 — 조용히 끄지 않는다 (`CLAUDE.md` §2)
                "penalty_note": axes.disabled_penalty_note(),
                "check": pc,
                "demoted": list(digest.get("demoted") or []),
                "honesty": HONESTY_HEADER,
                "path": path,
            },
        )

    def built(n_themes: int, n_picks: int, kept_news: int, thesis: int = 2) -> Alert:
        a = make(n_themes, n_picks, kept_news, thesis)
        a.text = format_alert(a)
        return a

    n_t, n_p, kept, th = len(all_themes), picks_per_theme, len(news), 2
    a = built(n_t, n_p, kept, th)
    # 줄이는 순서: 종목(3개까지) → 무효화 조건 → 종목(1개까지) → 테마 → 새 항목.
    # **논지 한 줄은 마지막까지 남긴다** — 명단이 어느 논지 아래 있는지가 이 알림의 요점이다.
    # 무효화 조건 전문·나머지 종목·제외 사유는 `digest.md` 에 그대로 있고 알림이 그 경로를 적는다.
    # 줄인 사실은 어느 경우든 본문에 남는다 (`CLAUDE.md` §2).
    while len(a.text) > TELEGRAM_MAX_CHARS and n_p > 3:
        n_p -= 1
        a = built(n_t, n_p, kept, th)
    while len(a.text) > TELEGRAM_MAX_CHARS and th > 1:
        th -= 1
        a = built(n_t, n_p, kept, th)
    while len(a.text) > TELEGRAM_MAX_CHARS and n_p > 1:
        n_p -= 1
        a = built(n_t, n_p, kept, th)
    while len(a.text) > TELEGRAM_MAX_CHARS and n_t > 3:
        n_t -= 1
        a = built(n_t, n_p, kept, th)
    while len(a.text) > TELEGRAM_MAX_CHARS and kept > 0:
        kept -= 1
        a = built(n_t, n_p, kept, th)
    return a


# ---------------------------------------------------------------- run_daily


def unjudged_above_best(digest: dict[str, Any]) -> list[str]:
    """**편입 가능한 것보다 순위가 높은데 판별을 안 받은 테마** — 점수 높은 순.

    사용자가 원하는 것은 134개 전수 판별이 아니라 *"최고의 섹터 중 편입 가능한 것"* 이다
    (2026-08-29). 그러려면 **지금 최선의 편입 가능 테마보다 위에 있는 미판별 테마**만
    보면 된다. 그 아래는 봐도 답을 바꾸지 못한다.

    편입 가능이 하나도 없으면 미판별 전부가 후보다 — 비교할 바닥이 없기 때문이다.

    실제로 2026-08-29 에 `life_science_tools`(0.78)가 편입 가능 `shipping_container`(0.77)
    **위에** 있으면서 판별을 안 받은 상태였다. 그것이 편입 가능이면 오늘의 답이 바뀐다.
    """
    themes = digest.get("themes") or []
    judged = {str(j["theme"]): j for j in (digest.get("judged") or [])}
    scored = [
        (float(t.get("score") or 0.0), str(t["theme"]))
        for t in themes
        if t.get("score") is not None
    ]
    best = max(
        (sc for sc, th in scored if judged.get(th, {}).get("portfolio_eligible")),
        default=None,
    )
    out = [
        th
        for sc, th in sorted(scored, reverse=True)
        if th not in judged and (best is None or sc > best)
    ]
    return out


def _research_until_eligible(
    report: RunReport, digest: dict[str, Any], asof_s: str, *, enabled: bool, write: bool
) -> tuple[str, ...]:
    """미판별 테마를 **위에서부터** 판별하고 **편입 가능이 나오면 멈춘다**.

    왜 멈추나: 목적이 "최고의 섹터 중 편입 가능한 것" 하나이기 때문이다. 그것을 찾은 뒤의
    판별은 답을 바꾸지 못하면서 시간만 쓴다 — 한 테마가 4역할 × 웹검색이라 몇 분이다.

    구독 CLI(`--provider claude_code`)로 돈다 — **크레딧 0.** 느린 대신 공짜이고, 하루에
    한둘이면 감당된다. 실패는 다이제스트를 죽이지 않고 단계로 보고한다 (`CLAUDE.md` §2).
    """
    t = _Timer()
    if not enabled:
        report.add(StepResult("research", "skipped", "--no-research", seconds=t.seconds))
        return ()
    # **없는 것과 실패한 것은 다르다.** 구독 CLI 가 안 깔린 환경(CI·합성 테스트)에서
    # 판별을 시도하면 매번 "failed" 가 뜬다 — 그것은 고장이 아니라 전제 미충족이다.
    import shutil

    if shutil.which("claude") is None:
        report.add(
            StepResult(
                "research",
                "skipped",
                "`claude` CLI 가 없다 — 구독 경로로 판별할 수 없다",
                seconds=t.seconds,
            )
        )
        return ()

    todo = unjudged_above_best(digest)
    if not todo:
        report.add(
            StepResult(
                "research",
                "skipped",
                "편입 가능 테마보다 위에 있는 미판별 테마가 없다",
                seconds=t.seconds,
            )
        )
        return ()

    from msa.l3.contracts import assemble_inputs
    from msa.l3.pipeline import run_research
    from msa.l3.providers import make_provider

    p = paths()
    done: list[str] = []
    found: str | None = None
    err: str | None = None
    for theme in todo:
        try:
            inputs = assemble_inputs(theme, state_dir=p.state, asof=asof_s)
            res = run_research(
                inputs,
                make_provider("claude_code", theme_id=theme),
                theses_root=p.theses,
                write=write,
            )
        except Exception as e:  # 판별 실패가 다이제스트를 죽이지 않게
            err = f"{theme}: {_err(e)}"
            break
        done.append(theme)
        if res.gate.portfolio_eligible:
            found = theme
            break

    bit = f"판별 {len(done)}/{len(todo)}"
    if found:
        bit += f" · **{found} 편입 가능 — 여기서 멈췄다**"
    elif done:
        bit += " · 전부 편입 불가"
    if err:
        bit += f" · 중단: {err}"
    report.add(
        StepResult("research", "failed" if err and not done else "ok", bit, seconds=t.seconds)
    )
    return tuple(done)


def _audit_eligible(
    report: RunReport, digest: dict[str, Any], asof_s: str, *, enabled: bool
) -> None:
    """**편입 가능 테마의 근거만** 실사한다 (`l3.evidence_audit`).

    왜 여기서 하나: 사람이 실제로 돈을 걸 후보는 편입 가능 테마뿐이고, 그 판정을 만든
    증거가 원문에 있는지는 **매번 확인해야 하는 것**이지 한 번 해두고 잊을 것이 아니다.
    2026-08-25 실사에서 표본의 20% 가 원문에 없는 수치였다.

    편입 불가 테마는 건너뛴다 — 사지 않을 테마의 URL 수십 개를 매일 받을 이유가 없다.
    실패는 다이제스트를 죽이지 않지만 **단계로 보고한다** (`CLAUDE.md` §2).
    """
    t = _Timer()
    if not enabled:
        report.add(StepResult("audit", "skipped", "--no-audit", seconds=t.seconds))
        return
    ok = [j for j in (digest.get("judged") or []) if j.get("portfolio_eligible")]
    if not ok:
        report.add(StepResult("audit", "skipped", "편입 가능 테마가 없다", seconds=t.seconds))
        return

    from msa.l3.evidence_audit import audit_thesis, http_fetch
    from msa.l3.evidence_triage import run_triage
    from msa.thesis import find_thesis, read_thesis_yaml

    p = paths()
    out: dict[str, Any] = {}
    for j in ok:
        theme = str(j["theme"])
        path = find_thesis(theme, asof_s, p.theses)
        if path is None:
            out[theme] = {"error": "논지를 찾지 못했다"}
            continue
        try:
            res = audit_thesis(read_thesis_yaml(path), http_fetch)
        except Exception as e:  # 네트워크 사고가 다이제스트를 죽이지 않게
            out[theme] = {"error": f"{type(e).__name__}: {e}"}
            continue
        # **어느 것을 먼저 열지**까지 정한다 (`l3.evidence_triage`). 목록만 내면 사람이
        # 13건을 매일 손으로 훑어야 하고, 그러면 아무도 안 본다. 에이전트가 실패하면
        # 기계 순서로 내려가되 그 사실을 적는다 (`CLAUDE.md` §2).
        thesis = read_thesis_yaml(path)
        items, why = run_triage(theme, res.checks, thesis.get("evidence") or [], res.axis_refs)
        out[theme] = {
            "counts": res.counts(),
            "unverified_axes": res.unverified_axes(),
            "checked": len(res.checks),
            "triage": [
                {
                    "evidence_id": x.evidence_id,
                    "verdict": x.verdict,
                    "why": x.why,
                    "look_for": x.look_for,
                    "axes": list(x.axes),
                    "url": next((c.url for c in res.checks if c.evidence_id == x.evidence_id), ""),
                }
                for x in items
            ],
            "triage_fallback": why,
        }
    digest["evidence_audit"] = out
    bad = sum(v.get("counts", {}).get("partial", 0) for v in out.values() if "counts" in v)
    n = sum(v.get("checked", 0) for v in out.values() if "checked" in v)
    first = sum(
        1 for v in out.values() for x in (v.get("triage") or []) if x["verdict"] == "open_first"
    )
    fell_back = [k for k, v in out.items() if v.get("triage_fallback")]
    note = f" · 기계 순서로 내려감 {fell_back}" if fell_back else ""
    report.add(
        StepResult(
            "audit",
            "ok",
            f"{len(out)}테마 · 근거 {n}건 · 못 찾은 숫자 {bad}건 · **먼저 열 것 {first}건**{note}",
            seconds=t.seconds,
        )
    )


#: `triage.csv` 의 앞 열 — 점수와 그 성분. 뒤에는 참고 열이 붙는다.
TRIAGE_LEAD_COLUMNS = (
    "partition", "triage", "ticker", "theme", "j", "c", "r", "from_52w_high",
)

#: **참고 열 — 점수 입력이 아니다.** 사람이 읽으라고 싣는다 (스펙 §5.2·§5.3).
#: `s_pct`·`composite`·`rs_rating` 이 여기 있는 것은 의도다: 실리되 점수에는 안 들어간다.
TRIAGE_REFERENCE_COLUMNS = (
    "price", "adv20_usd", "red_flags", "survival_unjudged",
    "s_pct", "t_pct", "m_pct", "composite", "rs_rating", "from_52w_low",
)


def build_triage_block(digest: dict[str, Any]) -> dict[str, Any]:
    """digest 에 붙일 `triage` 블록. **새 계산은 `msa.triage` 안에만 있다.**"""
    rows = triage_mod.score_digest(digest)
    return {
        "declared": triage_mod.declared_constants(),
        "claim_note": triage_mod.CLAIM_NOTE,
        "rows": [asdict(r) for r in rows],
    }


def render_triage_csv(
    rows: list[dict[str, Any]], picks_by_ticker: dict[str, dict[str, Any]]
) -> str:
    """구획·점수 + 참고 열.

    참고 열이 뒤에 오는 것은 표시가 아니라 **사실의 반영**이다 — 점수는 앞 열만으로
    만들어진다. 계산 불가는 빈 칸이다: 0 으로 쓰면 "가장 낮은 점수" 로 오해된다.
    """
    header = [*TRIAGE_LEAD_COLUMNS, *TRIAGE_REFERENCE_COLUMNS]
    out = [",".join(header)]
    for r in rows:
        src = picks_by_ticker.get(str(r.get("ticker")), {})
        cells: list[str] = []
        for col in header:
            value = r.get(col, src.get(col)) if col in r else src.get(col)
            if value is None:
                cells.append("")
            elif isinstance(value, bool):
                cells.append(str(value))
            elif isinstance(value, float):
                cells.append(f"{value:.6g}")
            else:
                cells.append(str(value).replace(",", " "))
        out.append(",".join(cells))
    return "\n".join(out) + "\n"


def _update_readme(report: RunReport, digest: dict[str, Any], *, readme: Path | None) -> None:
    """README 의 "오늘의 결론" 블록을 다시 쓴다 (2026-08-25 사용자 지시).

    저장소를 열었을 때 가장 먼저 보이는 곳에 오늘 상태가 있어야 한다 — `state/` 를 뒤져야
    알 수 있으면 아무도 안 본다. **실패는 다이제스트를 죽이지 않는다.** 다만 조용히 넘기지도
    않는다: 단계 결과에 사유가 남는다 (`CLAUDE.md` §2). 커밋은 하지 않는다 — 사람이 한다.
    """
    from msa.ops.readme_block import MarkerMissing, render_block, update_readme

    # 기본값이 저장소 README 다 — 그래서 **테스트는 반드시 `readme=` 를 넘겨야 한다.**
    # 안 넘기면 pytest 가 공개 문서를 합성 데이터로 덮는다 (2026-08-25 실제 발생:
    # 스토어가 도달한 적 없는 날짜와 "판별 0개" 라는 거짓이 main 에 커밋됐다).
    path = readme or (REPO_ROOT / "README.md")
    t = _Timer()
    try:
        changed = update_readme(path, render_block(digest))
    except MarkerMissing as e:
        report.add(StepResult("readme", "skipped", str(e), seconds=t.seconds))
    except OSError as e:
        report.add(StepResult("readme", "failed", f"README 갱신 실패 — {e}", seconds=t.seconds))
    else:
        msg = "블록을 다시 썼다" if changed else "내용이 같아 쓰지 않았다"
        report.add(StepResult("readme", "ok", msg, [rel(path)] if changed else [], t.seconds))


def run_daily(
    *,
    asof: str | date | None = None,
    top_k: int = 8,
    extra_themes: Sequence[str] = (),
    picks_per_theme: int = 5,
    write: bool = True,
    send: bool = False,
    audit: bool = True,
    research: bool = True,
    update_readme: bool = True,
    readme: Path | None = None,
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
            "audit": audit,
            "update_readme": update_readme,
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
            f"(스토어 {scan.meta.get('store_end')})"
            + (f" · {asof_note(scan.meta)}" if scan.meta.get("asof_clamped") else ""),
            seconds=t.seconds,
            details={
                "asof": scan.meta.get("asof"),
                "store_end": scan.meta.get("store_end"),
                "asof_requested": scan.meta.get("asof_requested"),
                "asof_clamped": scan.meta.get("asof_clamped"),
            },
        )
    )

    # 2) select — 월간과 같은 규칙 (자격 상위 K + 지정; 풀 미달로 채우지 않는다)
    t = _Timer()
    # **편입 가능 테마는 순위와 무관하게 넣는다** (2026-08-26).
    # 상위 K 만 명단을 뽑으면, 판별을 통과했는데 오늘 순위가 밖인 테마의 종목이 통째로
    # 사라진다. 실제로 `managed_care`(편입 가능 0.75)가 9위라 빠졌고, 그 안에 고점 대비
    # −45%·−24%·−18% 인 종목 셋이 있었는데 결론은 "지금 들어갈 자리는 없다" 였다.
    # 사람이 돈을 걸 후보는 편입 가능 테마이지 순위 상위가 아니다.
    eligible_now = sorted({h.theme for h in all_theses(asof_s) if h.eligible} - set(extra_themes))
    sel = select_themes(sb, top_k=top_k, extra_themes=[*extra_themes, *eligible_now])
    result.selection = sel
    for n in sel.notes:
        report.notes.append(f"select: {n}")
    report.add(
        StepResult(
            "select",
            "ok",
            f"선정 {len(sel.selected)} (자격 {sel.n_eligible}/{sel.n_total}, "
            f"지정 {len(sel.extra)}"
            + (f", 소표본 강등 {len(sel.demoted)}" if sel.demoted else "")
            + ")",
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
        _theme_entry(th, sel, sb, result.picks.get(th), errors.get(th), asof_s)
        for th in sel.selected
    ]

    # 4) diff — 직전 다이제스트는 실제 state/daily/ 에서 읽는다 (no-write 여도)
    t = _Timer()
    baseline_error: str | None = None
    prev: tuple[str, dict[str, Any]] | None = None
    try:
        prev = previous_digest(p.daily, asof_s)
    except RunError as e:
        # 삼키되 "첫 실행" 으로 둔갑시키지 않는다 — 산출물·알림에 손상 사실이 남는다
        baseline_error = str(e)
        report.notes.append(baseline_error)
    diff = diff_digests(themes, prev, baseline_error=baseline_error, top_n=picks_per_theme)
    for te in themes:
        te["new_since_prev"] = bool(diff["first_run"]) or te["theme"] in diff["themes_entered"]
    report.add(
        StepResult(
            "diff",
            "failed" if baseline_error else "ok",
            f"직전 기준 손상 — diff 없음: {baseline_error}"
            if baseline_error
            else "첫 실행 — 기준일 없음, 전부 신규"
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
            chk, info = run_cadence_check(asof_s, mode="daily", write=write, send=send)
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
            # 다이제스트의 날짜 라벨(`asof` 위)은 **요청한 날짜**이고 데이터는 아래
            # `asof` 것이다. 둘이 갈라졌으면 갈라졌다고 적는다 (`CLAUDE.md` §2).
            "asof_requested": scan.meta.get("asof_requested"),
            "asof_clamped": scan.meta.get("asof_clamped"),
        },
        "themes": themes,
        # 판별 결과의 모집단은 **상위 K 가 아니라 판별된 전부**다. 상위 K 로 세면 순위 밖의
        # 편입 가능 테마가 사라져 "통과 0개" 라는 거짓이 나온다 (2026-08-25 실측).
        "judged": [
            {
                "theme": h.theme,
                "portfolio_eligible": h.eligible,
                "trusted": h.trusted,
                "cycle_confidence": h.cycle_confidence,
                "gate": h.gate,
                "source": h.source,
                "in_top_k": h.theme in {t.get("theme") for t in themes},
            }
            for h in all_theses(asof_s)
        ],
        "demoted": [{"theme": th, "rank": rk} for th, rk in sel.demoted],
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

    # 오늘 새로 판별한 것이 있으면 **다이제스트의 판정을 갱신한다.** 안 하면 방금 편입
    # 가능이 된 테마가 오늘 리포트에는 여전히 "판별 안 함" 으로 남는다.
    newly = _research_until_eligible(report, digest, asof_s, enabled=research, write=write)
    if newly:
        digest["judged"] = [
            {
                "theme": h.theme,
                "portfolio_eligible": h.eligible,
                "trusted": h.trusted,
                "cycle_confidence": h.cycle_confidence,
                "gate": h.gate,
                "source": h.source,
                "in_top_k": h.theme in {t.get("theme") for t in digest.get("themes") or []},
            }
            for h in all_theses(asof_s)
        ]
        for entry in digest.get("themes") or []:
            if entry.get("theme") in newly:
                head = thesis_head(str(entry["theme"]), asof_s)
                entry["thesis"] = {
                    "found": head.found,
                    "source": head.source or None,
                    "claim": head.claim or None,
                    "invalidations": list(head.invalidations),
                    "gate": head.gate,
                    "portfolio_eligible": head.eligible,
                    "trusted": head.trusted,
                    "cycle_confidence": head.cycle_confidence,
                    "lines": head.lines(),
                }
        result.digest_md = render_digest_md(digest)
        if write and out_dir is not None:
            write_snapshot(
                out_dir,
                texts={"digest.md": result.digest_md, "report.txt": result.digest_md},
                jsons={"digest.json": digest},
            )

    _audit_eligible(report, digest, asof_s, enabled=audit and write)
    if write and out_dir is not None and digest.get("evidence_audit"):
        write_snapshot(out_dir, jsons={"digest.json": digest})  # 실사 결과를 반영해 다시 쓴다

    # 트리아지 — **실사 뒤에 돈다.** J 축이 `evidence_audit` 을 읽으므로 순서가 규칙의
    # 일부다: 앞에 두면 오늘 실사한 결과가 오늘 점수에 안 들어간다.
    t = _Timer()
    digest["triage"] = build_triage_block(digest)
    picks_by_ticker = {
        str(pk.get("ticker")): pk
        for e in (digest.get("themes") or [])
        for pk in (e.get("picks") or [])
    }
    triage_csv = render_triage_csv(digest["triage"]["rows"], picks_by_ticker)
    result.digest_md = render_digest_md(digest)
    n_ia = sum(
        1
        for r in digest["triage"]["rows"]
        if r["partition"] == triage_mod.PARTITION_IA
    )
    if write and out_dir is not None:
        write_snapshot(
            out_dir,
            texts={
                "digest.md": result.digest_md,
                "report.txt": result.digest_md,
                "triage.csv": triage_csv,
            },
            jsons={"digest.json": digest},
        )
        report.add(
            StepResult(
                "triage",
                "ok",
                f"구획 I-A {n_ia}종목",
                [rel(out_dir / "triage.csv")],
                t.seconds,
            )
        )
    else:
        report.add(
            StepResult(
                "triage", "ok", f"no-write — 구획 I-A {n_ia}종목", seconds=t.seconds
            )
        )

    # README 블록 — 건너뛰어도 **단계로 보고한다.** 단계가 통째로 사라지면 "안 돌았다" 와
    # "돌았는데 할 게 없었다" 를 구분할 수 없다 (`CLAUDE.md` §2).
    if not write:
        report.add(StepResult("readme", "skipped", "no-write — README 를 고치지 않았다"))
    elif not update_readme:
        report.add(StepResult("readme", "skipped", "--no-readme"))
    else:
        _update_readme(report, digest, readme=readme)

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
    "ALERT_CELLS",
    "DAILY_STEPS",
    "HONESTY_HEADER",
    "NO_THESIS_NOTE",
    "PICK_COLUMNS",
    "TELEGRAM_MAX_CHARS",
    "DailyResult",
    "build_digest_alert",
    "diff_digests",
    "excluded_lines_md",
    "new_item_lines",
    "previous_digest",
    "render_digest_md",
    "roster_table_md",
    "run_daily",
]
