"""섹터 관문 체인 — 모든 계층을 하나로 꿰어 **"오늘 어느 섹터인가"** 를 낸다.

## 왜 점수가 아니라 관문인가

여섯 계층이 각자 판정을 내는데 그것이 리포트 여기저기 흩어져 있었다. 사람이 여섯 곳을
읽고 머릿속에서 합쳐야 했다. 이 모듈이 그 합치기를 대신한다.

**그런데 가중 합산은 하지 않는다.** 여섯을 하나의 수로 만드는 순간 그것은 `docs/15` 가
죽인 종합 점수의 재발이고, 가중치는 어디서도 검정되지 않는다 (`CLAUDE.md` §1). 대신
**순서 있는 관문 체인**이다:

| # | 관문 | 묻는 것 | 판정을 내는 계층 |
|---|---|---|---|
| 1 | `forgotten` | 오래 잊혀졌나 | L1 (`pool ≥ POOL_MIN`) |
| 2 | `not_a_trap` | 가치 함정이 아닌가 | L3 판별 |
| 3 | `evidence` | 그 판별을 믿을 수 있나 | 실사 + 처리 대장 |
| 4 | `balance` | **수요/공급이 벌어지나** | L3.5 수급 조사 |
| 5 | `macro` | 거시 역풍이 아닌가 | L2′ 레짐 |
| 6 | `entry` | 지금 눌린 종목이 있나 | 트리아지 구획 I-A |

**순서가 규칙의 일부다** — 판별을 통과하지 않은 테마의 수급을 묻는 것은 낭비다. 그러나
막힌 뒤에도 **나머지 관문을 계속 본다**: "무엇을 더 해야 통과하나" 가 이 체인의 산출이기
때문이다.

## 새 상수를 만들지 않는다

여섯 관문의 임계는 전부 **다른 모듈이 이미 선언한 것을 import** 한다 —
`POOL_MIN`(L1) · `REGIME_TILT`(L2′) · `PARTITION_IA`(트리아지) · 대장의 `refuted`.
이 모듈은 판정을 **읽기만** 한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from msa.l1.scoreboard import POOL_MIN
from msa.l2.regime import REGIME_TILT
from msa.l35.balance import BALANCE_VERDICTS
from msa.triage import PARTITION_IA

#: 수급 관문을 통과시키는 판정. **`tightening` 하나뿐이다** — `balanced` 는 "벌어지지
#: 않는다" 이고, 그것은 이 체인이 찾는 것이 아니다.
BALANCE_PASS = "tightening"

#: "무엇이 바뀌면" 에 싣는 최대 항목 수. **표시 상한이지 판정이 아니다** — 전문은 수급
#: 조사 보고서(`state/balance/<theme>.report.md`)에 있고, 투자 메모에는 읽을 만큼만 싣는다.
WHAT_CHANGES_MAX = 4

assert BALANCE_PASS in BALANCE_VERDICTS


@dataclass(frozen=True)
class Gate:
    key: str
    title: str
    question: str


#: 관문 여섯. **순서가 규칙의 일부다.**
GATES: tuple[Gate, ...] = (
    Gate("forgotten", "① 잊혀졌나", "오래 소외됐나 (L1 자격)"),
    Gate("not_a_trap", "② 함정이 아닌가", "가치 함정 판별을 통과했나 (L3)"),
    Gate("evidence", "③ 믿을 수 있나", "그 판별의 근거가 원문 대조를 통과했나"),
    Gate("balance", "④ 수요/공급이 벌어지나", "실물 수요 증가율이 공급을 앞지르나 (L3.5)"),
    Gate("macro", "⑤ 거시 역풍이 아닌가", "레짐이 headwind 는 아닌가 (L2′)"),
    Gate("entry", "⑥ 지금 자리인가", "구획 I-A 에 종목이 있나"),
)

_BY_KEY = {g.key: g for g in GATES}


@dataclass(frozen=True)
class Result:
    """관문 하나의 결과. **수를 담지 않는다** — 통과 여부와 사유뿐이다."""

    key: str
    passed: bool
    why: str


@dataclass(frozen=True)
class Row:
    """테마 하나의 체인 결과."""

    theme: str
    gates: tuple[Result, ...]

    def gate(self, key: str) -> Result:
        for r in self.gates:
            if r.key == key:
                return r
        raise KeyError(key)

    @property
    def cleared(self) -> bool:
        return all(r.passed for r in self.gates)

    @property
    def blocked_at(self) -> str | None:
        """**처음** 막힌 관문. 순서가 규칙이므로 첫 번째가 진짜 원인이다."""
        for r in self.gates:
            if not r.passed:
                return r.key
        return None

    @property
    def depth(self) -> int:
        """몇 번째 관문까지 갔나 — 정렬에 쓴다. 점수가 아니다."""
        for i, r in enumerate(self.gates):
            if not r.passed:
                return i
        return len(self.gates)


def _forgotten(theme: Mapping[str, Any]) -> Result:
    pool = theme.get("pool")
    if pool is None:
        return Result("forgotten", False, "자격(pool)을 계산하지 못했다")
    ok = float(pool) >= POOL_MIN
    return Result(
        "forgotten",
        ok,
        f"pool {float(pool):.2f} {'≥' if ok else '<'} {POOL_MIN} (L1 자격)",
    )


def _not_a_trap(judged: Mapping[str, Any] | None) -> Result:
    if judged is None:
        return Result("not_a_trap", False, "판별을 받은 적이 없다 — `msa research` 가 먼저다")
    if not judged.get("trusted"):
        return Result("not_a_trap", False, "판별했으나 논지를 신뢰하지 못한다 (trusted=false)")
    if not judged.get("portfolio_eligible"):
        # **왜 편입 불가인지가 다르다.** 확신도 미달과 "축이 적용 불가라 판정 자체가 없다" 는
        # 다른 사실이고, 뭉뚱그리면 리포트가 거짓을 적는다 — 2026-08-29 실측:
        # `insurance_brokers` 는 확신도 0.6 으로 편입선을 넘었는데 "확신도 미달" 로 표시됐다.
        rule = str(judged.get("gate_rule") or "")
        if "적용 불가" in rule:
            return Result(
                "not_a_trap",
                False,
                "**판별의 중심 질문에 답한 축이 없다** — 5축 중 여럿이 적용 불가라 "
                "확신도가 판정이 아니라 판정의 부재에서 왔다 (`docs/04` §2). "
                f"확신도 {judged.get('cycle_confidence')}",
            )
        conf = judged.get("cycle_confidence")
        tail = f" (확신도 {conf})" if conf is not None else ""
        return Result(
            "not_a_trap", False, f"판별 결과 편입 불가 — 가치 함정 혐의를 못 벗었다{tail}"
        )
    return Result("not_a_trap", True, "판별 통과 · 편입 가능")


def _evidence(theme: str, audit: Mapping[str, Any] | None, refuted: int, resolved: bool) -> Result:
    if audit is None:
        return Result("evidence", False, "증거 실사를 안 돌렸다 — 통과가 아니라 미확인이다")
    if refuted:
        return Result("evidence", False, f"사람이 원문 대조에서 **반박**한 근거 {refuted}건")
    axes = list(audit.get("unverified_axes") or [])
    if axes:
        return Result("evidence", False, f"확인된 근거가 없는 축: {', '.join(axes)}")
    counts = audit.get("counts") or {}
    checked = int(audit.get("checked") or 0)
    partial = int(counts.get("partial", 0))
    unread = int(counts.get("unreachable", 0)) + int(counts.get("unsupported", 0))
    if (partial or unread) and not resolved:
        return Result(
            "evidence",
            False,
            f"미처리 근거 {partial + unread}건 (못 찾은 숫자 {partial} · 못 읽음 {unread}) "
            "— `msa ops audit-evidence` 로 열고 대장에 적어라",
        )
    verified = int(counts.get("verified", 0))
    return Result("evidence", True, f"근거 {verified}/{checked} 확인 · 반박 0건")


def _balance(theme: str, block: Mapping[str, Any] | None) -> Result:
    verdicts = (block or {}).get("verdicts") or {}
    v = verdicts.get(theme)
    if not v:
        return Result(
            "balance",
            False,
            "수급 조사가 없다 — 안 했다는 뜻이지 수급이 중립이라는 뜻이 아니다. "
            f"`msa balance {theme}`",
        )
    if v != BALANCE_PASS:
        return Result("balance", False, f"수급 **{v}** — 벌어지지 않는다")
    return Result("balance", True, f"수급 **{v}** — 수요가 공급을 앞지른다")


def _macro(theme: str, regime: Mapping[str, Any] | None) -> Result:
    tilts = (regime or {}).get("tilts") or {}
    t = tilts.get(theme)
    if t is None:
        return Result("macro", True, "레짐 계수 없음 (순풍이거나 판정 없음) — 막지 않는다")
    if float(t) <= REGIME_TILT["headwind"]:
        return Result("macro", False, "거시 **역풍** — 이 유형은 지금 순풍이 아니다")
    return Result("macro", True, f"거시 계수 {float(t):.2f} — 역풍은 아니다")


def _entry(theme: str, rows: Sequence[Mapping[str, Any]]) -> Result:
    mine = [r for r in rows if r.get("theme") == theme]
    ia = [r for r in mine if r.get("partition") == PARTITION_IA]
    if ia:
        names = " · ".join(f"`{r.get('ticker')}`" for r in ia[:4])
        return Result("entry", True, f"구획 I-A {len(ia)}종목 — {names}")
    if mine:
        return Result(
            "entry", False, f"명단 {len(mine)}종목이 전부 고점권(I-B) — 지금 자리가 아니다"
        )
    return Result("entry", False, "명단에 종목이 없다")


def _refuted_counts(themes: Sequence[str]) -> dict[str, tuple[int, bool]]:
    """테마 → (반박 건수, 대장에 기록이 있나). 대장을 못 읽으면 전부 (0, False)."""
    try:
        from msa.config import paths
        from msa.ops import resolutions as res

        root = paths().evidence_resolutions
        out: dict[str, tuple[int, bool]] = {}
        for t in themes:
            entries = res.effective(root, t)
            out[t] = (sum(1 for e in entries if e.verdict == "refuted"), bool(entries))
        return out
    except Exception:
        return {t: (0, False) for t in themes}


def evaluate(digest: Mapping[str, Any]) -> list[Row]:
    """digest → 테마별 관문 체인. **더 멀리 간 테마가 위**로 정렬된다."""
    judged = {str(j["theme"]): j for j in (digest.get("judged") or [])}
    audits = digest.get("evidence_audit") or {}
    tri_rows = (digest.get("triage") or {}).get("rows") or []
    regime = digest.get("regime") or {}
    bal = digest.get("balance") or {}

    # **수급 조사를 돌린 테마는 상위 K 밖이어도 체인에 들어온다.**
    # 2026-08-29 실측: `silver_miners` 조사(tightening)를 돌렸는데 상위 K 밖이라 관문표에
    # 아예 없었다. 리포트가 그 조사는 보여주면서 관문에는 없으니, 읽는 사람이 "왜 실버는
    # 없나" 를 알 수 없었다. 실제 답은 ① 에서 떨어진다는 것이고 **그 답이 보여야 한다.**
    entries: list[Mapping[str, Any]] = list(digest.get("themes") or [])
    inside = {str(t.get("theme")) for t in entries}
    scan_all = digest.get("scan_all") or {}
    for theme in sorted(set(bal.get("surveyed") or []) - inside):
        # 스캔 밖이라 pool 을 모를 수 있다 — 모르면 모른다고 적힌다 (`_forgotten`).
        extra = dict(scan_all.get(theme) or {})
        extra["theme"] = theme
        entries.append(extra)

    names = [str(t.get("theme")) for t in entries]
    ledger = _refuted_counts(names)

    rows: list[Row] = []
    for entry in entries:
        theme = str(entry.get("theme"))
        refuted, has_ledger = ledger.get(theme, (0, False))
        rows.append(
            Row(
                theme,
                (
                    _forgotten(entry),
                    _not_a_trap(judged.get(theme)),
                    _evidence(theme, audits.get(theme), refuted, has_ledger),
                    _balance(theme, bal),
                    _macro(theme, regime),
                    _entry(theme, tri_rows),
                ),
            )
        )
    rows.sort(key=lambda r: (-r.depth, r.theme))
    return rows


def cleared(rows: Sequence[Row]) -> list[Row]:
    return [r for r in rows if r.cleared]


def headline(rows: Sequence[Row]) -> str:
    """한 줄 결론. **통과가 0개인 것도 정직한 답이다.**"""
    ok = cleared(rows)
    if ok:
        names = " · ".join(f"`{r.theme}`" for r in ok)
        return (
            f"**여섯 관문을 전부 통과한 섹터: {names}** — 잊혀졌고 · 함정이 아니고 · "
            "근거가 확인됐고 · 수급이 벌어지고 · 거시 역풍이 아니고 · 지금 눌려 있다"
        )
    if not rows:
        return "평가할 테마가 없다"
    best = rows[0]
    counts: dict[str, int] = {}
    for r in rows:
        k = r.blocked_at
        if k:
            counts[k] = counts.get(k, 0) + 1
    worst = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[0]
    g = _BY_KEY[worst[0]]
    return (
        f"**여섯 관문을 다 통과한 섹터는 없다.** 가장 멀리 간 것은 `{best.theme}` "
        f"({_BY_KEY[best.blocked_at].title if best.blocked_at else ''} 관문에서 막혔다). "
        f"가장 많이 막은 곳은 **{g.title}** "
        f"({worst[1]}개 테마) — {g.question}"
    )


def render_md(rows: Sequence[Row], *, limit: int = 8) -> list[str]:
    """구획별 표가 아니라 **체인 표**다 — 각 테마가 어디서 막혔는지 한눈에."""
    if not rows:
        return []
    out = [
        "",
        "## 오늘의 섹터 — 관문 체인",
        "",
        headline(rows),
        "",
        "**이것은 점수가 아니라 관문이다.** 여섯을 가중 합산하지 않는다 — 합치는 순간 "
        "`docs/15` 가 죽인 종합 점수가 된다. 각 칸은 그 계층이 이미 내린 판정이다.",
        "",
        "| 테마 | " + " | ".join(g.title for g in GATES) + " | 막힌 곳 |",
        "|---|" + "---|" * (len(GATES) + 1),
    ]
    for r in rows[:limit]:
        cells = " | ".join("✅" if r.gate(g.key).passed else "❌" for g in GATES)
        blocked = _BY_KEY[r.blocked_at].title if r.blocked_at else "**통과**"
        out.append(f"| `{r.theme}` | {cells} | {blocked} |")
    out.append("")

    # 상위 테마의 사유를 풀어서 — 표만 있으면 왜 막혔는지 모른다
    for r in rows[: min(limit, 3)]:
        out += [f"**`{r.theme}`**", ""]
        for g in GATES:
            res = r.gate(g.key)
            out.append(f"- {'✅' if res.passed else '❌'} {g.title} — {res.why}")
        out.append("")
    return out


def declared_constants() -> dict[str, Any]:
    return {
        "gates": [g.key for g in GATES],
        "pool_min": POOL_MIN,
        "balance_pass": BALANCE_PASS,
        "headwind_tilt": REGIME_TILT["headwind"],
        "entry_partition": PARTITION_IA,
        "claim": (
            "관문 체인이다 — **새 가중치를 만들지 않는다.** 여섯을 하나의 수로 합치면 "
            "docs/15 가 죽인 종합 점수의 재발이다. 각 관문의 임계는 다른 모듈이 이미 "
            "선언한 것을 import 한다"
        ),
    }

# ---------------------------------------------------------------- 다음 행동


@dataclass(frozen=True)
class Action:
    """실행 가능한 다음 한 걸음. **기다리는 것은 여기 들어오지 않는다.**"""

    theme: str
    command: str
    why: str


def _action_for(row: Row) -> Action | None:
    """막힌 관문 → 실행할 명령. **못 할 일은 None** 이다.

    할 일 목록에 못 할 일을 넣으면 목록 전체가 죽는다 — 사람이 두 번 보고 안 본다.
    """
    key = row.blocked_at
    if key is None:
        return None
    why = row.gate(key).why
    if key == "not_a_trap":
        if "판별을 받은 적이 없다" in why:
            return Action(row.theme, f"msa research {row.theme}", "판별을 안 받았다")
        return None  # 편입 불가 판정은 답이지 할 일이 아니다
    if key == "evidence":
        if "반박" in why:
            # 반박된 근거는 더 읽는다고 안 풀린다 — 논지 자체를 다시 세워야 한다
            return Action(
                row.theme,
                f"msa research {row.theme}",
                "근거가 반박됐다 — 더 읽어서 풀리지 않는다. 판별을 다시 받아야 한다",
            )
        if "실사를 안 돌렸다" in why:
            return Action(row.theme, "msa run daily", "증거 실사를 안 돌렸다")
        if "미처리 근거" in why:
            return Action(
                row.theme,
                f"msa ops audit-evidence {row.theme}",
                "미처리 근거가 남았다 — 원문을 열고 대장에 적는다",
            )
        return None
    if key == "balance":
        if "수급 조사가 없다" in why:
            return Action(
                row.theme, f"msa balance {row.theme}", "수급 조사가 없다 — 회전을 돌린다"
            )
        return None  # loosening·balanced 는 답이다
    # forgotten · macro · entry 는 기다리는 것이지 실행할 명령이 없다
    return None


def next_actions(rows: Sequence[Row]) -> list[Action]:
    """**할 수 있는 것만.** 더 멀리 간 테마의 할 일이 먼저 온다 (통과에 가장 가깝다)."""
    out: list[Action] = []
    seen: set[str] = set()
    for r in rows:  # `evaluate` 가 이미 depth 내림차순으로 준다
        a = _action_for(r)
        if a is not None and a.command not in seen:
            seen.add(a.command)
            out.append(a)
    return out


def what_would_change(rows: Sequence[Row]) -> dict[str, list[str]]:
    """테마 → **무엇이 바뀌면 이 판정이 뒤집히나.**

    수급 조사가 이미 `invalidations`(판정이 틀렸다는 관측)와 `what_would_close_it`(격차가
    메워지는 경로)를 들고 있다. 다시 묻지 않고 그대로 싣는다 — 좋은 투자 메모의 핵심이
    "무엇이 바뀌면 마음이 바뀌나" 이고, 그 답을 이미 갖고 있으면서 안 싣는 것이 낭비다.
    """
    out: dict[str, list[str]] = {}
    try:
        from msa.config import paths
        from msa.l35 import balance as balance_mod
    except Exception:
        return {}
    root = paths().balance
    for r in rows:
        try:
            doc = balance_mod.read(root, r.theme)
        except Exception:
            continue
        if not doc:
            continue
        bal = doc.get("balance") or {}
        # `invalidations` 가 먼저다 — "이 판정이 틀렸다는 관측" 이 곧 재진입 트리거이고,
        # `what_would_close_it`("격차가 메워지는 경로")보다 투자자에게 직접적이다.
        items = [str(x) for x in (bal.get("invalidations") or [])]
        items += [str(x) for x in (bal.get("what_would_close_it") or [])]
        # 두 목록은 자주 겹친다 (2026-08-29 실측: 수에즈 항로가 양쪽에 있었다).
        # 앞 40자가 같으면 같은 말로 본다 — 문장 전체 비교로는 안 잡힌다.
        seen: set[str] = set()
        uniq: list[str] = []
        for x in items:
            key = x[:40]
            if key in seen:
                continue
            seen.add(key)
            uniq.append(x)
        if uniq:
            out[r.theme] = uniq[:WHAT_CHANGES_MAX]
    return out


# ---------------------------------------------------------------- 투자 판단


def _label(r: Result) -> str:
    return f"{_BY_KEY[r.key].title.split(' ', 1)[1]} — {r.why}"


def _blocking_reasons(row: Row) -> list[str]:
    """이 테마가 막힌 **모든** 사유. 첫 번째만 적으면 나머지가 안 보인다."""
    return [_label(r) for r in row.gates if not r.passed]


def _passing_reasons(row: Row) -> list[str]:
    return [_label(r) for r in row.gates if r.passed]


def _reached_passes(row: Row) -> list[str]:
    """**막히기 전에** 통과한 관문. 체인이므로 이것만이 진짜 통과다."""
    return [_label(r) for r in row.gates[: row.depth]]


def _unreached(row: Row) -> list[str]:
    """막힌 뒤의 관문 — **통과가 아니라 미도달**이다.

    2026-08-31 리포트 검토: 이 구분이 없으면 "2/6 관문" 옆에 ✅ 가 넷 서서 독자가 둘 중
    하나를 거짓으로 읽는다. 값은 계산돼 있으므로 버리지 않고 **참고로 내린다** — 무엇을
    더 풀어야 하는지가 이 체인의 산출이기 때문이다 (모듈 머리말).
    """
    return [_label(r) for r in row.gates[row.depth + 1 :] if r.passed]


def _stop_line(row: Row) -> str:
    """`{테마} — {막힌 관문}에서 막혔다` — 분수를 쓰지 않는다.

    `depth` 는 통과 **개수**가 아니라 멈춘 **자리**다. 분수로 적으면 개수로 읽힌다.
    """
    blocked = row.blocked_at
    if blocked is None:
        return f"**`{row.theme}`** — 여섯 관문 전부 통과"
    title = _BY_KEY[blocked].title
    if row.depth == 0:
        return f"**`{row.theme}`** — 첫 관문 {title} 에서 막혔다"
    return f"**`{row.theme}`** — {title} 관문에서 막혔다 (앞의 {row.depth}개는 통과)"


def verdict_md(rows: Sequence[Row], *, limit: int = 3) -> list[str]:
    """**투자 판단** — 리포트의 첫 절. 관문이 결론이고 나머지는 그 근거다.

    투자자가 읽는 문서다. 그러나 이 저장소가 쓸 수 있는 것은 **측정값과 명시된 가정**뿐이고
    기대수익·승률은 쓰지 않는다 (`CLAUDE.md` §7·§8). 좋은 투자 메모가 원래 그렇다 —
    무엇을 아는지, 무엇을 모르는지, **무엇이 바뀌면 마음이 바뀌는지**를 적는다.
    """
    if not rows:
        return []
    ok = cleared(rows)
    out = ["", "## 투자 판단", ""]

    if ok:
        names = " · ".join(f"`{r.theme}`" for r in ok)
        out += [
            f"> **오늘의 섹터: {names}**",
            ">",
            "> 여섯 관문을 전부 통과했다 — 오래 잊혀졌고, 가치 함정이 아니고, 그 판별의 근거가 "
            "원문 대조를 통과했고, 실물 수요가 공급을 앞지르고, 거시 역풍이 아니고, "
            "지금 눌려 있다.",
            "",
        ]
        for r in ok:
            out += [f"**`{r.theme}` — 통과 근거**", ""]
            out += [f"- {x}" for x in _passing_reasons(r)]
            out.append("")
    else:
        best = rows[0]
        out += [
            "> **신규 편입 없음.** 여섯 관문을 모두 통과한 섹터가 오늘은 없다.",
            ">",
            f"> 가장 가까웠던 것은 **`{best.theme}`** — "
            f"{_BY_KEY[best.blocked_at].title if best.blocked_at else ''} 관문에서 막혔다. "
            "아래가 그 테마가 어디까지 갔고 무엇에 막혔는지다.",
            "",
        ]
        # **판별을 통과한 테마만 길게 편다.** ② 에서 막힌 것은 아직 후보가 아니고,
        # 그 아래 관문의 ❌ 를 나열하면 할 일처럼 보여 소음이 된다.
        detailed = [r for r in rows if r.depth >= 2][:limit]
        for r in detailed:
            out += [_stop_line(r), ""]
            # **답이 '안 산다' 이므로 왜 안 사는지가 먼저다.** 통과 항목을 앞에 놓으면
            # 투자자가 세 줄을 읽고 "좋아 보인다" 고 오해한다 (2026-08-29 검토).
            for x in _blocking_reasons(r):
                out.append(f"- ❌ {x}")
            for x in _reached_passes(r):
                out.append(f"- ✅ {x}")
            for x in _unreached(r):
                # 체인상 도달하지 못한 칸 — 값은 있으나 통과라고 부르지 않는다
                out.append(f"- ◻ (미도달) {x}")
            out.append("")
        rest = [r for r in rows if r not in detailed]
        if rest:
            # **판정을 받고 떨어진 것과 아직 안 받은 것은 다른 사실이다.** 뭉뚱그리면
            # 투자자가 "돌리면 될 수도" 라고 읽는다 — 앞은 이미 답이 나온 것이다.
            judged_out = [
                r for r in rest if "판별을 받은 적이 없다" not in r.gate("not_a_trap").why
            ]
            unjudged = [r for r in rest if r not in judged_out]
            if judged_out:
                names = " · ".join(f"`{r.theme}`" for r in judged_out)
                # 사유가 둘이다 — 뭉뚱그리면 거짓이 된다
                no_axis = [r for r in judged_out if "답한 축이 없다" in r.gate("not_a_trap").why]
                low_conf = [r for r in judged_out if r not in no_axis]
                if low_conf:
                    n2 = " · ".join(f"`{r.theme}`" for r in low_conf)
                    out += [
                        f"**확신도 미달 {len(low_conf)}개** — {n2}. "
                        "가치 함정 혐의를 못 벗었다.",
                        "",
                    ]
                if no_axis:
                    n3 = " · ".join(f"`{r.theme}`" for r in no_axis)
                    out += [
                        f"**판정 자체가 없는 {len(no_axis)}개** — {n3}. "
                        "5축 중 여럿이 적용 불가라 확신도가 판정의 부재에서 왔다 "
                        "(`docs/04` §2 — 적용 불가는 통과가 아니다).",
                        "",
                    ]
            if unjudged:
                names = " · ".join(f"`{r.theme}`" for r in unjudged)
                out += [
                    f"**아직 판별을 안 받은 {len(unjudged)}개** — {names}. "
                    "후보가 아니라 미지수다.",
                    "",
                ]

    changes = what_would_change(rows)
    named = [r.theme for r in (ok or rows[:limit]) if r.theme in changes]
    if named:
        out += [
            "**재진입 트리거 — 무엇이 바뀌면 이 판단이 뒤집히나**",
            "",
            "<sub>수급 조사의 무효화 조건에서 그대로 가져왔다 "
            "(`state/balance/<theme>.report.md` 에 전문). 이 목록은 예측이 아니라 "
            "**관측 대상**이다.</sub>",
            "",
        ]
        for t in named:
            out.append(f"- `{t}`")
            out += [f"  - {x}" for x in changes[t]]
        out.append("")

    acts = next_actions(rows)
    out += ["**오늘 할 일**", ""]
    if acts:
        out += [f"- `{a.command}` — {a.why}" for a in acts]
    else:
        out.append(
            "- **할 일이 없다.** 막힌 관문은 전부 시간이 푸는 것들이다 (판정이 답으로 나왔거나, "
            "가격이 내려오기를 기다린다). 무리해서 관문을 느슨하게 하지 않는다."
        )
    out += [
        "",
        "<sub>**이 판단은 기대수익을 말하지 않는다.** 이 저장소는 전략 수익률을 낼 근거가 "
        "없다 (`CLAUDE.md` §7). 여기 있는 것은 측정값과 명시된 가정이며, 집행은 사람이 한다 "
        "(§8). 관문은 가중 합산이 아니라 순서 있는 체인이고, 각 칸은 그 계층이 이미 내린 "
        "판정을 그대로 옮긴 것이다.</sub>",
        "",
    ]
    return out

def searchable_classes(regime_doc: Mapping[str, Any] | None) -> set[str]:
    """관문 ⑤ 를 통과할 수 있는 `cycle_class` 집합 — **탐색 공간을 손으로 세지 않게.**

    2026-08-29 실측: 다음에 판별할 테마를 고르려고 탐색 공간을 손으로 셌는데 **순풍 3종만
    세고 `secular_growth`(중립)를 빼먹어 9개 테마를 놓쳤다.** 관문 ⑤(`_macro`)는
    `headwind` 만 막는데, 사람이 "순풍" 과 "막지 않음" 을 헷갈린 것이다.

    같은 판정을 두 곳에서 내리지 않도록 이 함수가 `_macro` 와 **같은 규칙**을 쓴다.
    """
    from msa.l2.regime import CYCLE_CLASSES

    classes = (regime_doc or {}).get("classes") or {}
    if not classes:
        return set(CYCLE_CLASSES)  # 레짐 문서가 아예 없으면 아무것도 막지 않는다
    out: set[str] = set()
    for name in CYCLE_CLASSES:
        body = classes.get(name)
        if not body:
            # **판정이 없는 칸을 순풍으로 읽지 않는다.** `_macro` 는 계수가 없으면
            # 막지 않지만, 탐색 공간을 짤 때 "모르는 칸" 을 후보에 넣으면 판별을 돌린 뒤
            # ⑤ 에서 걸리는 일이 생긴다. 여기서는 **아는 것만** 센다 (`CLAUDE.md` §2).
            continue
        if REGIME_TILT.get(str(body.get("verdict")), 1.0) > REGIME_TILT["headwind"]:
            out.add(str(name))
    return out
