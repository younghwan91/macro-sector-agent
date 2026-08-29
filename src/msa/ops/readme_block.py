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

from msa.dates import last_possible_us_session

BEGIN = "<!-- MSA:LATEST -->"
END = "<!-- /MSA:LATEST -->"

#: 블록에 싣는 테마 수. 전체는 `state/daily/<date>/digest.md` 에 있다.
TOP_N = 8

#: **"지금 볼 만한 자리"의 기준** — 52주 고점 대비 이만큼 아래.
#:
#: 시스템 판정(게이트·확신도·명단·비중)은 이 값과 무관하다. **그러나 사람이 읽는 결론은
#: 이 값 하나가 정한다** — "차트를 볼 것 N종목" 이 될지 "지금 들어갈 자리는 없다" 가 될지,
#: 어느 종목이 이름으로 불릴지. 사람이 실제로 행동하는 유일한 출력이 여기 걸려 있으므로
#: **검토 대상에서 빼지 마라.**
#:
#: 근거: **없다 — 선언값이다.** 도메인 문헌에서 온 값이 아니고 데이터에 맞춰 고르지도
#: 않았다(스윕 없음). 바꾸려면 근거를 적고 바꿔라. 결론 문장에도 선언값임을 표기한다.
PULLBACK_MARK = -0.15


class MarkerMissing(RuntimeError):
    """README 에 마커가 없다 — 어디에 쓸지 사람이 정해야 한다."""


def _fmt_money(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= div:
            return f"${x / div:.1f}{unit}"
    return f"${x:,.2f}" if abs(x) < 100 else f"${x:,.0f}"


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
        # 0 과 "모름" 은 다르다. picks 가 안 돌았으면 `—`, 돌았는데 0 이면 `0`.
        n_pick: Any = len(t.get("eligible_tickers") or [])
        if t.get("picks_error") or t.get("picks") is None:
            n_pick = "—"
        raw_flags = t.get("flags") or ""
        flags = ", ".join(str(x) for x in raw_flags) if isinstance(raw_flags, list) else raw_flags
        score = t.get("score")
        score_s = f"{float(score):.2f}" if isinstance(score, int | float) else "—"
        rows.append(
            f"| {t.get('rank', '—')} | `{t.get('theme', '?')}` | {score_s} "
            f"| {verdict} | {n_pick} | {flags or '—'} |"
        )
    return rows


def _eligible(themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """상위 K 안에서 **편입 가능**한 테마. `게이트 passed` 로 거르면 안 된다 — 확신도 미달로
    통과 상태이면서 편입 불가인 경우가 흔하다 (2026-08-25 실측: 상위 4테마 중 4테마)."""
    return [t for t in themes if (t.get("thesis") or {}).get("portfolio_eligible")]


def _judged_eligible(digest: dict[str, Any]) -> list[dict[str, Any]]:
    """**판별된 테마 전부** 중 편입 가능한 것 (상위 K 밖 포함).

    결론을 상위 K 로 세면 순위 밖의 통과 테마가 사라진다 — 2026-08-25 실측에서 통과 2개가
    5위 밖이라 "판별을 통과한 테마가 0개" 라는 거짓 결론이 나왔다. L1 순위와 L3 판별은
    다른 축이다.
    """
    return [j for j in (digest.get("judged") or []) if j.get("portfolio_eligible")]


def _triage_order(digest: dict[str, Any]) -> dict[str, float]:
    """티커 → triage. 블록이 없으면 **빈 dict** — 그러면 기존 낙폭 순서를 그대로 쓴다.

    계산 불가(`triage: null`)는 넣지 않는다. 넣으면 0 으로 읽혀 맨 뒤로 밀리는데,
    "모른다" 와 "가장 낮다" 는 다른 말이다 (`CLAUDE.md` §2).
    """
    rows = (digest.get("triage") or {}).get("rows") or []
    return {
        str(r["ticker"]): float(r["triage"])
        for r in rows
        if r.get("triage") is not None
    }


def _pullbacks(
    themes: list[dict[str, Any]], order: dict[str, float] | None = None
) -> list[dict[str, Any]]:
    """편입 가능 테마의 명단 중 **눌려 있는** 종목 (고점 대비 `PULLBACK_MARK` 아래).

    `order`(트리아지)가 주어지면 그 내림차순이 곧 읽는 순서다. 없으면 낙폭 깊은 순 —
    **없는 것을 있다고 말하지 않는다.**
    """
    out: list[dict[str, Any]] = []
    for t in _eligible(themes):
        for pick in t.get("picks") or []:
            h = pick.get("from_52w_high")
            if isinstance(h, int | float) and h <= PULLBACK_MARK:
                out.append({**pick, "theme": t.get("theme")})
    if order:
        return sorted(out, key=lambda x: -order.get(str(x.get("ticker")), -1.0))
    return sorted(out, key=lambda x: x.get("from_52w_high", 0.0))


def _resolved_ids(digest: dict[str, Any]) -> dict[str, set[int]]:
    """테마 → 대장에서 **이미 처리한** 증거 id.

    `digest["triage"]["resolutions"]` 는 건수만 들고 있어 id 를 모른다. 대장 파일을 직접
    읽는다 — 없으면 빈 dict 이고 아무것도 안 빠진다.
    """
    from msa.config import paths
    from msa.ops import resolutions as res

    out: dict[str, set[int]] = {}
    try:
        root = paths().evidence_resolutions
        for th in (digest.get("evidence_audit") or {}):
            ids = {e.evidence_id for e in res.effective(root, str(th))}
            if ids:
                out[str(th)] = ids
    except Exception:  # 대장 사고가 리포트를 죽이지 않게 — 다만 아무것도 빼지 않는다
        return {}
    return out


def _audit_line(digest: dict[str, Any]) -> str:
    """증거 실사 요약 한 조각. 결론 안에 넣는다 — 파일에만 있으면 아무도 안 본다."""
    audit = digest.get("evidence_audit") or {}
    if not audit:
        return ""
    partial = sum(v.get("counts", {}).get("partial", 0) for v in audit.values() if "counts" in v)
    unread = sum(
        v.get("counts", {}).get("unreachable", 0) + v.get("counts", {}).get("unsupported", 0)
        for v in audit.values()
        if "counts" in v
    )
    total = sum(v.get("checked", 0) for v in audit.values() if "checked" in v)
    if not total:
        return ""
    axes = sorted({a for v in audit.values() for a in (v.get("unverified_axes") or [])})
    # **먼저 열 것을 이름으로 짚는다.** 숫자만 적으면 "13건 이상" 이 겁만 주고 사람이
    # 무엇을 할지 모른다 (2026-08-29). 분류는 `l3.evidence_triage` 가 한다.
    # **테마별로 묶는다.** 증거 id 는 테마마다 따로라 `[1]` 이 두 테마에 다 있을 수 있다.
    # 섞어서 나열하면 어느 문서를 열어야 하는지 알 수 없다 (2026-08-29).
    # **이미 대장에서 처리한 것은 빼고 짚는다.** 2026-08-29 실측: 사람이 [1]·[8]·[10]·[17]
    # 을 원문 대조까지 끝냈는데 리포트는 여전히 그 넷을 "먼저 열 것" 으로 내밀었다.
    # 처리한 일을 다시 시키면 목록 전체가 신뢰를 잃는다.
    done = _resolved_ids(digest)
    by_theme: list[tuple[str, list[int]]] = []
    resolved_n = 0
    for th, v in sorted(audit.items()):
        raw = [
            int(x["evidence_id"])
            for x in (v.get("triage") or [])
            if x.get("verdict") == "open_first"
        ]
        ids = [i for i in raw if i not in done.get(th, set())]
        resolved_n += len(raw) - len(ids)
        if ids:
            by_theme.append((th, sorted(ids)))
    first = [i for _, ids in by_theme for i in ids]
    fell_back = any(v.get("triage_fallback") for v in audit.values())
    bit = (
        f" ⚠ **판정을 만든 근거 {total}건 중 {partial}건은 원문에서 못 찾은 숫자가 있고 "
        f"{unread}건은 문서를 읽지 못했다.**"
    )
    if first:
        src = " (기계 순서 — 분류 실패)" if fell_back else ""
        parts = [f"`{th}` {' · '.join(f'[{i}]' for i in ids)}" for th, ids in by_theme]
        cmds = " · ".join(f"`msa ops audit-evidence {th}`" for th, _ in by_theme)
        bit += (
            f" 그중 **먼저 열 것 {len(first)}건**{src} — {' / '.join(parts)}. "
            f"URL 과 무엇을 찾을지는 {cmds} 가 적어 준다."
        )
    else:
        bit += (
            " 먼저 열 것으로 분류된 것은 없다 — 전부 반올림·곁가지다 "
            "(`msa ops audit-evidence <theme>` 로 전문)."
        )
    if resolved_n:
        bit += f" (사람이 원문 대조를 끝낸 {resolved_n}건은 목록에서 뺐다.)"
    if axes:
        bit += f" 확인된 근거가 하나도 없는 축: {', '.join(axes)}."
    return bit


def _concentration_line(digest: dict[str, Any]) -> str:
    """P4 의 집중 경고를 **결론 문장 안으로** 끌어올린다.

    경고가 구획 표 아래에만 있으면 결론만 읽는 사람은 못 본다. 2026-08-29 실측에서
    구획 I-A 의 3종목이 전부 한 테마·한 군집이었는데, 그 사실이 결론에는 없고 표
    아래에만 있었다 — **명단의 가장 중요한 사실이 가장 안 읽히는 자리에 있었다.**
    """
    parts = (digest.get("risk") or {}).get("partitions") or {}
    warns = [
        w["text"]
        for p in ("I-A", "I-B")
        for w in (parts.get(p) or {}).get("warnings") or []
        if w.get("kind") in ("theme_concentration", "cluster_concentration")
    ]
    if not warns:
        return ""
    head = str(warns[0]).split(" — ")[0].strip()
    return f" ⚠ **{head} — 사실상 한 베팅이다.**"


def _headline(digest: dict[str, Any]) -> tuple[str, str]:
    """한 줄 결론 + 근거. 표를 읽기 전에 **무엇을 할지**가 먼저 나와야 한다.

    두 가지를 틀리기 쉽고 둘 다 실제로 틀렸었다 (2026-08-25):

    1. 게이트 `passed` 로 세면 **편입 불가 테마의 종목**이 "차트 볼 것" 에 들어온다.
       → `portfolio_eligible` 로 센다.
    2. 상위 K 로 세면 **순위 밖의 편입 가능 테마**가 사라져 "통과 0개" 라는 거짓이 된다.
       → 판별된 전부(`digest["judged"]`)를 모집단으로 쓴다.
    """
    themes = list(digest.get("themes") or [])
    judged = list(digest.get("judged") or [])
    ok_all = _judged_eligible(digest)
    ok_top = _eligible(themes)
    outside = [j for j in ok_all if not j.get("in_top_k")]

    if not ok_all:
        why = (
            f"판별한 {len(judged)}개 모두 편입 불가"
            if judged
            else "아직 아무 테마도 판별하지 않았다"
        )
        return (
            "오늘 편입 가능 판정을 받은 테마가 없다",
            f"{why}. 스코어보드 순위는 '오래 잊혀졌다' 는 뜻이지 후보라는 뜻이 아니다 — "
            "판정을 받으려면 `msa research <theme>`.",
        )

    names_all = " · ".join(f"`{j['theme']}`" for j in ok_all)
    # 전부 밖이면 이름을 두 번 쓰지 않는다 — 헤드라인이 이미 "상위 K 밖" 이라고 말한다.
    tail = ""
    if outside and len(outside) < len(ok_all):
        tail = (
            f" (이 중 {' · '.join('`' + j['theme'] + '`' for j in outside)} 는 "
            "오늘 상위 K 밖이라 아래 표에 없다)"
        )

    # 눌린 종목은 상위 K 안에서만 셀 수 있다 — 명단(picks)이 다이제스트에 실린 것만이라서.
    dips = _pullbacks(themes)
    n_pick = sum(len(t.get("eligible_tickers") or []) for t in ok_top)
    if not ok_top:
        return (
            f"편입 가능 테마 {len(ok_all)}개 — 전부 오늘 상위 K 밖이다",
            f"{names_all}. 아래 표(상위 K)에는 없다 — 스코어보드 순위와 판별은 다른 축이다. "
            "명단은 `msa picks <theme>` 또는 `state/picks/<date>/<theme>/` 에서 본다.",
        )
    if not n_pick:
        return (
            f"편입 가능 테마는 {len(ok_all)}개인데 명단이 비었다",
            f"{names_all} — 하드 필터를 통과한 종목이 0개다. `msa picks` 결과를 확인하라.",
        )
    if not dips:
        return (
            "지금 들어갈 자리는 없다",
            f"편입 가능 {names_all}{tail} 의 명단 {n_pick}종목이 **전부 52주 고점 "
            f"−{abs(PULLBACK_MARK):.0%}(선언값) 이내**다. 이 시스템은 잊혀진 바닥을 찾는데 "
            f"나온 것은 이미 회복된 자리다. 관찰만 하고 눌릴 때 다시 본다.{_audit_line(digest)}",
        )

    audit = _audit_line(digest)
    flagged = sum(1 for d in dips if d.get("red_flags") or d.get("penalties"))
    warn = f" 그중 **레드플래그·감점이 붙은 것 {flagged}종목**." if flagged else ""
    names_top = " · ".join(f"`{t.get('theme')}`" for t in ok_top)
    # **종목 이름을 결론 문장에 직접 넣는다.** 예전에는 "아래 표 밑의 목록을 보라" 고만 했는데
    # 그 목록은 README 블록에만 있고 digest.md 에는 없어, 다이제스트만 읽는 사람에게는
    # 결론이 가리키는 대상이 어디에도 없었다 (2026-08-26).
    named = " · ".join(
        f"{'⚠' if (d.get('red_flags') or d.get('penalties')) else ''}`{d['ticker']}` "
        f"{d['from_52w_high']:+.0%}"
        for d in sorted(dips, key=lambda x: (str(x.get("theme")), str(x.get("ticker"))))[:8]
    )
    more = f" 외 {len(dips) - 8}종목" if len(dips) > 8 else ""
    return (
        f"차트 확인 대상 {len(dips)}종목 — 편입 가능 {names_top} 의 명단 {n_pick} 중{tail}",
        f"**{named}**{more}."
        f"{warn} 나머지는 52주 고점 −{abs(PULLBACK_MARK):.0%}(선언값) 이내라 지금 자리가 "
        f"아니다.{_concentration_line(digest)}{audit} **판정은 사람이 차트로 한다** — "
        "시스템이 한 말은 '이 테마는 함정이 아니고 이 종목들은 재무가 버틴다' 까지다. "
        "⚠ 는 레드플래그·감점이 붙은 종목이다.",
    )


def _dip_lines(
    themes: list[dict[str, Any]], order: dict[str, float] | None = None
) -> list[str]:
    """눌린 종목 표.

    **이전 판은 테마·티커 순이었고 그 이유가 옳았다**: 낙폭 순 정렬은 "더 눌린 것이 더
    볼 만하다" 는 근거 없는 주장이 되고, 낙폭만 적으면 유동성 없는 껍데기가 맨 위에 온다.

    2026-08-29 에 바뀐 것은 **정렬 근거가 생겼다는 것**이지 그 판단이 틀렸다는 것이 아니다.
    `order`(트리아지)는 낙폭 하나가 아니라 판정 신뢰도(J)·재무 명료도(C)·열람 시급성(R)을
    함께 본다 — 그래서 레드플래그가 붙은 종목은 더 눌렸어도 뒤로 간다. **그래도 이것은
    읽는 순서이지 수익률 순서가 아니다.**

    `order` 가 없으면 옛 규칙 그대로 테마·티커 순이다 — 없는 것을 있다고 말하지 않는다.
    거래대금과 레드플래그를 같이 싣는 것은 어느 경우든 그대로다.
    """
    if order:
        dips = _pullbacks(themes, order=order)
        order_note = "순서 = triage(읽는 순서) — 수익률 순서가 아니다"
        bar_note = "막대는 크기만 — 부호는 숫자가 든다. 순서는 triage 이지 낙폭 순이 아니다."
    else:
        dips = sorted(
            _pullbacks(themes), key=lambda d: (str(d.get("theme")), str(d.get("ticker")))
        )
        order_note = "순서 = 테마·티커 순, 볼 만한 순서가 아니다"
        bar_note = "막대는 크기만 — 부호는 숫자가 든다. 순서는 테마·티커 순이지 우선순위가 아니다."
    if not dips:
        return []
    from msa.ops.charts import block

    out = ["", f"**눌린 종목** ({order_note})", ""]
    # 그래프는 숫자를 대신하지 않고 옆에 붙는다 — 낙폭 크기 차이가 표만 봐서는 안 잡힌다.
    out += block(
        "52주 고점 대비",
        [(str(d.get("ticker")), float(d.get("from_52w_high", 0.0))) for d in dips],
        note=bar_note,
    )
    out += ["| 종목 | 테마 | 52wH | 가격 | ADV20 | 비고 |", "|---|---|---:|---:|---:|---|"]
    for d in dips:
        mark = "⚠ " if (d.get("red_flags") or d.get("penalties")) else ""
        note = str(d.get("red_flags") or d.get("penalties") or "—")
        out.append(
            f"| {mark}`{d.get('ticker')}` | `{d.get('theme')}` | "
            f"{d.get('from_52w_high', float('nan')):+.0%} | "
            f"{_fmt_money(d.get('price'))} | {_fmt_money(d.get('adv20_usd'))} | {note} |"
        )
    return out


def render_block(digest: dict[str, Any], *, today: date | None = None) -> str:
    """`digest.json` → README 블록 텍스트 (마커 포함)."""
    scan = digest.get("scan") or {}
    # 스캔 기준일과 **다이제스트가 저장된 디렉터리**는 다르다. 스토어가 뒤처지면
    # 스캔 asof(가격이 끊긴 날) < 실행일이고, 다이제스트는 실행일 디렉터리에 저장된다.
    # 링크에 스캔 asof 를 쓰면 스토어가 밀린 평시에 항상 깨진 경로가 된다 (2026-08-25).
    asof = str(scan.get("asof") or digest.get("asof") or "?")
    round_dir = str(digest.get("asof") or asof)
    store_end = str(scan.get("store_end") or "?")
    now = (today or date.today()).isoformat()
    themes = list(digest.get("themes") or [])

    # **KST 달력 날짜에서 미 거래일을 빼면 안 된다.** KST 는 동부보다 13~14시간 앞서고
    # 벤더는 세션 다음날 낮에 데이터를 올린다. 그래서 스토어가 최신일 때도 달력으로는
    # 이틀 차이가 나고, 그것을 "2일 낡음" 이라고 적으면 멀쩡한 데이터를 낡았다고 말한다.
    # 2026-08-29 실측: 스토어 08-27 = 그 시점에 **존재 가능한 마지막 세션**이었는데
    # 문구는 "2일 낡음" 이었다. 나도 그 문구에 두 번 속아 크론을 옮길 뻔했다.
    #
    # 기준은 달력이 아니라 `last_possible_us_session()` 이다 (`docs/18`).
    lag = "—"
    behind = False
    with suppress(ValueError):
        newest = last_possible_us_session()
        se = date.fromisoformat(store_end)
        behind = se < newest
        gap = (newest - se).days
        lag = "최신" if not behind else f"거래일 {gap}일 뒤처짐"

    verdict, detail = _headline(digest)
    assert "**" not in verdict, "결론 줄은 렌더러가 굵게 만든다 — 안에서 다시 굵게 하지 않는다"
    out = [
        BEGIN,
        "",
        f"## 오늘의 결론 · {now}",
        "",
        f"> **{verdict}**",
        ">",
        f"> {detail}",
    ]
    if behind:
        out += [
            ">",
            f"> ⚠ **가격 스토어가 {store_end} 에서 멈춰 있다 — 마지막 거래일보다 뒤처졌다.** "
            "적재를 확인해라. 52주 고점 대비도 그 날짜 값이다.",
        ]
    out += [
        "",
        f"<sub>`msa run daily` 가 자동으로 다시 쓴다. 스캔 기준일 **{asof}** · "
        f"가격 스토어 마지막 날 **{store_end}** ({lag} — 미 거래일 기준이다. "
        f"KST 달력 날짜와 다른 것은 정상이다). "
        "성과 수치는 없다 — 측정값과 판정뿐이다 (`CLAUDE.md` §7).</sub>",
        "",
        "| # | 테마 | 점수 | 판별 | 명단 | 플래그 |",
        "|---:|---|---:|---|---:|---|",
    ]
    out += _verdict_rows(themes) or ["| — | (테마 없음) | — | — | — | — |"]
    out += _dip_lines(themes, _triage_order(digest))
    out += [
        "",
        f"<sub>상위 {min(TOP_N, len(themes))}개만 싣는다. 전문·제외 사유·판단 재료 열은 "
        f"`state/daily/{round_dir}/digest.md`. **순위가 높다 = 오래 잊혀졌다** 이지 "
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
