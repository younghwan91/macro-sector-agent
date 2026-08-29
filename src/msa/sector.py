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
        return Result("not_a_trap", False, "판별 결과 편입 불가 — 가치 함정 혐의를 못 벗었다")
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

    names = [str(t.get("theme")) for t in (digest.get("themes") or [])]
    ledger = _refuted_counts(names)

    rows: list[Row] = []
    for entry in digest.get("themes") or []:
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
        f"({best.depth}/{len(GATES)} 관문). 가장 많이 막은 곳은 **{g.title}** "
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
