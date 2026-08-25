"""README 의 "오늘의 결론" 블록을 최신 산출물로 다시 쓴다.

`msa run daily` 가 매번 호출한다 (2026-08-25 사용자 지시: "최신 결론은 매일 리드미에
업데이트해"). 저장소를 열었을 때 **가장 먼저 보이는 곳에 오늘 상태가 있어야** 한다 —
`state/` 를 뒤져야 알 수 있으면 아무도 안 본다.

## 규약

- 블록은 `README.md` 안의 마커 사이만 바꾼다. 마커 밖은 건드리지 않는다.
- 마커가 없으면 **README 를 고치지 않고 실패를 보고한다** — 조용히 붙이지 않는다
  (`CLAUDE.md` §2). 사람이 위치를 정한다.
- **성과 수치를 쓰지 않는다** (`CLAUDE.md` §7). 여기 들어가는 것은 측정값과 판정뿐이다:
  스캔 날짜·스토어 최신도·테마 순위·게이트 판정·명단 크기. 수익률·승률은 없다.
- 커밋하지 않는다. 파일만 쓰고 `git` 은 사람이 한다.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import date
from pathlib import Path
from typing import Any

BEGIN = "<!-- MSA:LATEST -->"
END = "<!-- /MSA:LATEST -->"

#: 블록에 싣는 테마 수. 전체는 `state/daily/<date>/digest.md` 에 있다.
TOP_N = 8

#: **"지금 볼 만한 자리"의 기준** — 52주 고점 대비 이만큼 아래.
#:
#: 이것은 선정 임계가 **아니다.** 아무것도 거르지 않고 순위도 바꾸지 않는다. 명단을 읽는
#: 사람이 "고점 근처인 것과 눌린 것"을 구분하도록 **줄 하나를 더 쓰는** 표시일 뿐이다.
#: 값 −15% 는 흔한 얕은 조정(−5~−10%)과 의미 있는 눌림을 가르는 자리로 골랐고, 선정에
#: 쓰이지 않으므로 `CLAUDE.md` §1 의 대상이 아니다 — 이 값을 바꿔도 어떤 판정도 안 바뀐다.
PULLBACK_MARK = -0.15


class MarkerMissing(RuntimeError):
    """README 에 마커가 없다 — 어디에 쓸지 사람이 정해야 한다."""


def _fmt_money(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(x) >= div:
            return f"${x / div:.1f}{unit}"
    return f"${x:,.0f}"


def _verdict_rows(themes: list[dict[str, Any]]) -> list[str]:
    rows = []
    for t in themes[:TOP_N]:
        th = t.get("thesis") or {}
        if not th.get("found"):
            verdict = "**판별 안 함**"
        else:
            conf = th.get("cycle_confidence")
            conf_s = f"{float(conf):g}" if isinstance(conf, int | float) else "?"
            # 게이트 status 가 아니라 **편입 여부**를 쓴다 — 둘은 다르다.
            mark = "**편입 가능**" if th.get("portfolio_eligible") else "편입 불가"
            verdict = f"{mark} · {conf_s}"
        n_pick = len(t.get("eligible_tickers") or [])
        flags = t.get("flags") or ""
        score = t.get("score")
        score_s = f"{float(score):.2f}" if isinstance(score, int | float) else "—"
        rows.append(
            f"| {t.get('rank', '—')} | `{t.get('theme', '?')}` | {score_s} "
            f"| {verdict} | {n_pick or '—'} | {flags or '—'} |"
        )
    return rows


def _eligible(themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """**판별을 통과한** 테마만. `게이트 passed` 로 거르면 안 된다 — 확신도 미달로 통과
    상태이면서 편입 불가인 경우가 흔하다 (2026-08-25 실측: 4테마 중 3테마)."""
    return [t for t in themes if (t.get("thesis") or {}).get("portfolio_eligible")]


def _pullbacks(themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """편입 가능 테마의 명단 중 **눌려 있는** 종목 (고점 대비 `PULLBACK_MARK` 아래)."""
    out: list[dict[str, Any]] = []
    for t in _eligible(themes):
        for pick in t.get("picks") or []:
            h = pick.get("from_52w_high")
            if isinstance(h, int | float) and h <= PULLBACK_MARK:
                out.append({**pick, "theme": t.get("theme")})
    return sorted(out, key=lambda x: x.get("from_52w_high", 0.0))


def _headline(themes: list[dict[str, Any]]) -> tuple[str, str]:
    """한 줄 결론 + 근거. 표를 읽기 전에 **무엇을 할지**가 먼저 나와야 한다.

    세는 대상은 **판별을 통과한 테마의 종목뿐**이다. 게이트 `passed` 로 세면 안 된다 —
    조항에 안 걸려도 확신도가 기준선 미달이면 `passed` 이면서 편입 불가다. 그것까지 세면
    "차트 볼 것 37종목" 같은 줄이 나오는데 대부분이 가치 함정 판정을 받은 테마의 구성원이다.
    이 시스템이 막으려는 사고가 바로 그것이다 (2026-08-25 실측: 4테마 중 3테마가 그 상태).
    """
    ok = _eligible(themes)
    judged = [t for t in themes if (t.get("thesis") or {}).get("found")]
    n_pick = sum(len(t.get("eligible_tickers") or []) for t in ok)

    if not ok:
        why = (
            f"판별한 것 {len(judged)}개 모두 편입 불가"
            if judged
            else "아직 아무 테마도 판별하지 않았다"
        )
        return (
            "오늘 살 것은 없다 — 판별을 통과한 테마가 0개",
            f"상위 {len(themes)}개 중 {why}. 스코어보드 순위는 '오래 잊혀졌다' 는 뜻이지 "
            "후보라는 뜻이 아니다 — 판정을 받으려면 `msa research <theme>`.",
        )

    ok_names = " · ".join(f"`{t.get('theme')}`" for t in ok)
    if not n_pick:
        return (
            f"통과한 테마는 {len(ok)}개인데 명단이 비었다",
            f"{ok_names} — 하드 제외를 통과한 종목이 0개다. `msa picks` 결과를 확인하라.",
        )

    dips = _pullbacks(themes)
    if not dips:
        return (
            "지금 들어갈 자리는 없다",
            f"통과 테마 {ok_names} 의 명단 {n_pick}종목이 "
            f"**전부 52주 고점 −{abs(PULLBACK_MARK):.0%} 이내**다. 이 시스템은 잊혀진 바닥을 "
            "찾는데 나온 것은 이미 회복된 자리다. 관찰만 하고 눌릴 때 다시 본다.",
        )

    names = " · ".join(f"`{d['ticker']}` {d['from_52w_high']:+.0%}" for d in dips[:5])
    more = f" 외 {len(dips) - 5}종목" if len(dips) > 5 else ""
    return (
        f"차트를 볼 것은 {len(dips)}종목 — 통과 테마 {ok_names} 의 명단 {n_pick} 중",
        f"고점 대비 −{abs(PULLBACK_MARK):.0%} 아래로 눌린 것: {names}{more}. "
        "나머지는 고점 근처라 지금 자리가 아니다. **판정은 사람이 차트로 한다** — "
        "시스템이 한 말은 '이 테마는 함정이 아니고 이 종목들은 재무가 버틴다' 까지다.",
    )


def render_block(digest: dict[str, Any], *, today: date | None = None) -> str:
    """`digest.json` → README 블록 텍스트 (마커 포함)."""
    scan = digest.get("scan") or {}
    asof = str(scan.get("asof") or digest.get("asof") or "?")
    store_end = str(scan.get("store_end") or "?")
    now = (today or date.today()).isoformat()
    themes = list(digest.get("themes") or [])

    lag = "—"
    with suppress(ValueError):
        lag = f"{(date.fromisoformat(now) - date.fromisoformat(store_end)).days}일 전"

    verdict, detail = _headline(themes)
    out = [
        BEGIN,
        "",
        f"## 오늘의 결론 · {now}",
        "",
        f"> **{verdict}**",
        ">",
        f"> {detail}",
        "",
        f"<sub>`msa run daily` 가 자동으로 다시 쓴다. 스캔 기준일 **{asof}** · "
        f"가격 스토어 마지막 날 **{store_end}** ({lag}). "
        "성과 수치는 없다 — 측정값과 판정뿐이다 (`CLAUDE.md` §7).</sub>",
        "",
        "| # | 테마 | 점수 | 판별 | 명단 | 플래그 |",
        "|---:|---|---:|---|---:|---|",
    ]
    out += _verdict_rows(themes) or ["| — | (테마 없음) | — | — | — | — |"]
    out += [
        "",
        f"<sub>상위 {min(TOP_N, len(themes))}개만 싣는다. 전문·제외 사유·판단 재료 열은 "
        f"`state/daily/{asof}/digest.md`. **순위가 높다 = 오래 잊혀졌다** 이지 "
        "사라는 뜻이 아니다 — 판별(`msa research`)을 거치지 않은 테마는 후보가 아니다.</sub>",
        "",
        END,
    ]
    return "\n".join(out)


def update_readme(readme: Path | str, block: str) -> bool:
    """마커 사이를 `block` 으로 교체. 내용이 같으면 쓰지 않고 False."""
    p = Path(readme)
    text = p.read_text(encoding="utf-8")
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 or j < 0 or j < i:
        raise MarkerMissing(
            f"{p} 에 {BEGIN} … {END} 마커가 없다 — 어디에 쓸지 정해지지 않았다. "
            "조용히 덧붙이지 않는다 (CLAUDE.md §2)."
        )
    new = text[:i] + block + text[j + len(END) :]
    if new == text:
        return False
    p.write_text(new, encoding="utf-8")
    return True
