"""증거 실사 — `claim` 의 숫자가 **그 문서에 실제로 있는지** 확인한다.

스키마 검사는 형식만 본다: URL 이 URL 처럼 생겼는가, 날짜가 미래인가, 출처가 비었는가.
그것을 전부 통과하면서도 **원문에 없는 수치**를 적을 수 있다. 2026-08-25 실사에서 표본 74건
중 약 16건(20%)이 그랬다 — 2년 전 기사를 최근 것으로 이름만 바꾸거나, UNCTAD 보고서에 없는
숫자를 그 URL 로 인용하거나, "109개 카운티" 를 "225개" 로 적은 것들이다.

**이 모듈이 하는 일은 하나다:** claim 에서 숫자를 뽑아 문서 본문에서 찾는다. 하나라도 못
찾으면 `partial`, 전부 찾으면 `verified`, 문서를 못 읽으면 `unreachable` 이다.

## 판정 규칙 (임계를 만들지 않는다)

`verified` 는 **뽑은 숫자를 전부 찾았을 때만** 난다. "70% 이상 일치" 같은 비율을 두지
않는다 — 그런 값은 근거 없이 고른 임계이고 (`CLAUDE.md` §1), 무엇보다 **틀린 숫자 하나가
판정을 만든다.** 못 찾은 숫자는 목록으로 남겨 사람이 판단한다.

## 이 검사가 못 하는 것

- **단위 변환을 못 따라간다 — 오탐의 가장 큰 원인이다.** claim 이 한국어로 "순손실
  2,220만 달러" 라고 쓰면 영문 원문에는 `$22.2 million` 으로 있다. 숫자로는 안 맞는다.
  `partial` 이 나왔다고 곧바로 날조가 아니다 — **못 찾은 숫자 목록을 보고 사람이 판단한다.**
- **문맥은 못 본다.** 숫자가 문서에 있어도 claim 이 말하는 뜻과 다를 수 있다 (예: 원문의
  "109 fewer counties" 를 "225개 철수" 로 적었는데 문서 어딘가에 225 가 있는 경우).
- **403·페이월은 `unreachable` 이다.** 실사에서 cms.gov·SEC·Commonwealth Fund 가 전부
  봇 차단이었다. **`unreachable` 은 "맞다" 도 "틀리다" 도 아니다** — 사람이 열어야 한다.
- **PDF 는 본문을 읽지 않는다.** `unsupported` 로 남긴다.

그래서 이 모듈은 사람의 실사를 **대체하지 않고 좁힌다** — 23건 중 어느 것을 먼저 열어야
하는지 알려준다.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: 본문에서 찾을 숫자를 뽑는 규칙. 쉼표·소수점은 살린다.
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_YEAR = re.compile(r"^(19|20)\d{2}$")

#: claim 에서 **먼저 지우는** 것 — 날짜다. 날짜의 조각(`08`·`14`)은 claim 의 측정값이 아니고,
#: 증거 날짜는 `R_EVIDENCE_FUTURE`·`W_EVIDENCE_DATE_PLACEHOLDER` 가 따로 본다. 지우지 않으면
#: 실사가 날짜 조각을 "원문에서 못 찾은 숫자" 로 올려 신호를 묽게 만든다.
_DATE_LIKE = re.compile(r"\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?|\d{1,2}월\s*\d{1,2}일")

#: 이 확장자는 본문 추출을 시도하지 않는다.
_BINARY_SUFFIXES = (".pdf", ".xlsx", ".xls", ".zip", ".doc", ".docx")

#: 한 증거에서 검사할 최대 숫자 수. 긴 claim 이 수십 개를 내면 그중 대부분은 서술용이라
#: 신호가 묽어진다. **판정이 아니라 표시 상한이다** — 잘린 수는 결과에 적는다.
MAX_NUMBERS = 12

VERIFIED = "verified"
PARTIAL = "partial"
UNREACHABLE = "unreachable"
UNSUPPORTED = "unsupported"
NO_NUMBERS = "no_numbers"


@dataclass(frozen=True)
class EvidenceCheck:
    """증거 한 건의 실사 결과."""

    evidence_id: int
    status: str
    url: str
    wanted: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    truncated: int = 0
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status == VERIFIED

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.evidence_id, "status": self.status, "url": self.url}
        if self.wanted:
            d["checked_numbers"] = list(self.wanted)
        if self.missing:
            d["missing_numbers"] = list(self.missing)
        if self.truncated:
            d["numbers_not_checked"] = self.truncated
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class AuditResult:
    """한 논지의 실사 — **판정을 만든 증거만** 본다."""

    checks: tuple[EvidenceCheck, ...] = ()
    axis_refs: Mapping[str, tuple[int, ...]] = field(default_factory=dict)

    def by_id(self) -> dict[int, EvidenceCheck]:
        return {c.evidence_id: c for c in self.checks}

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.checks:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    def unverified_axes(self) -> list[str]:
        """근거 중 **확인된 것이 하나도 없는** 축. 그 판정은 확인되지 않은 것 위에 서 있다."""
        by = self.by_id()
        out = []
        for axis, refs in self.axis_refs.items():
            checked = [by[r] for r in refs if r in by]
            if checked and not any(c.ok for c in checked):
                out.append(axis)
        return sorted(out)


def numbers_in(text: str, *, limit: int = MAX_NUMBERS) -> tuple[tuple[str, ...], int]:
    """claim 에서 확인 가능한 숫자를 뽑는다. 반환 (숫자들, 잘린 수).

    빼는 것: 날짜와 그 조각 · 연도 · 한 자리 수. 전부 "어느 문서에나 있거나, claim 의
    측정값이 아닌" 것들이라 남겨 두면 결과가 잡음으로 덮인다.
    """
    seen: list[str] = []
    for m in _NUM.finditer(_DATE_LIKE.sub(" ", text or "")):
        raw = m.group(0).rstrip(".,")
        bare = raw.replace(",", "")
        if _YEAR.match(bare) or len(bare.replace(".", "")) < 2:
            continue
        if raw not in seen:
            seen.append(raw)
    return tuple(seen[:limit]), max(0, len(seen) - limit)


def _norm(s: str) -> str:
    """비교용 정규화 — 쉼표·공백을 없앤다. `1,180,000` 과 `1180000` 이 같아진다."""
    return re.sub(r"[,\s ]", "", s)


def strip_html(raw: str) -> str:
    """태그를 걷어낸 본문. 외부 의존을 쓰지 않는다 — 숫자만 찾으면 되므로 충분하다."""
    body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return html.unescape(body)


def check_one(item: Mapping[str, Any], fetch: Callable[[str], str | None]) -> EvidenceCheck:
    """증거 한 건 — claim 의 숫자가 문서에 있는가."""
    eid = int(item.get("id", -1))
    url = str(item.get("source_url", ""))
    claim = str(item.get("claim", ""))
    wanted, cut = numbers_in(claim)

    if not url.startswith("http"):
        return EvidenceCheck(
            eid, UNSUPPORTED, url, wanted, truncated=cut, note="HTTP URL 이 아니다"
        )
    if url.lower().split("?")[0].endswith(_BINARY_SUFFIXES):
        return EvidenceCheck(
            eid, UNSUPPORTED, url, wanted, truncated=cut, note="본문을 읽지 않는 형식"
        )
    if not wanted:
        return EvidenceCheck(
            eid, NO_NUMBERS, url, truncated=cut, note="claim 에 확인할 숫자가 없다"
        )

    raw = fetch(url)
    if raw is None:
        return EvidenceCheck(
            eid,
            UNREACHABLE,
            url,
            wanted,
            truncated=cut,
            note="문서를 못 읽었다 (403·페이월·네트워크) — 맞다는 뜻도 틀리다는 뜻도 아니다",
        )
    body = _norm(strip_html(raw))
    missing = tuple(w for w in wanted if _norm(w) not in body)
    status = VERIFIED if not missing else PARTIAL
    return EvidenceCheck(eid, status, url, wanted, missing, cut)


def audit_thesis(
    thesis: Mapping[str, Any],
    fetch: Callable[[str], str | None],
    *,
    only_axis_refs: bool = True,
) -> AuditResult:
    """논지 하나를 실사한다. 기본은 **판정을 만든 증거만** — 나머지는 서술 재료다."""
    axes = thesis.get("value_trap_axes") or {}
    axis_refs: dict[str, tuple[int, ...]] = {}
    for name, block in axes.items():
        if isinstance(block, Mapping):
            refs = block.get("evidence_refs") or []
            axis_refs[str(name)] = tuple(int(r) for r in refs)
    wanted_ids: set[int] | None = None
    if only_axis_refs:
        wanted_ids = {r for refs in axis_refs.values() for r in refs}

    ev: Sequence[Mapping[str, Any]] = thesis.get("evidence") or []
    checks = [
        check_one(e, fetch) for e in ev if wanted_ids is None or int(e.get("id", -1)) in wanted_ids
    ]
    return AuditResult(tuple(checks), axis_refs)


# ---------------------------------------------------------------- 네트워크

#: 브라우저처럼 보이는 헤더. 많은 사이트가 기본 UA 를 막는다 — 그것을 "틀린 증거" 로
#: 오판하지 않으려고 붙인다. 그래도 막히면 `unreachable` 이고, 그건 사람이 열어야 한다.
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

#: 한 문서에서 읽어들이는 최대 바이트. 숫자를 찾는 데 본문 앞부분이면 대개 충분하고,
#: 상한이 없으면 큰 문서 하나가 실사 전체를 붙잡는다. 잘렸는지는 결과에 남지 않으므로
#: **넉넉히** 둔다 (일반 기사·공시 본문은 이보다 훨씬 작다).
MAX_BYTES = 4_000_000
FETCH_TIMEOUT_S = 15

#: 동시에 받는 문서 수. 서로 다른 호스트라 한 사이트를 두드리는 것이 아니다.
MAX_WORKERS = 8


def http_fetch(url: str, *, timeout_s: int = FETCH_TIMEOUT_S) -> str | None:
    """문서 본문. 실패하면 `None` — **예외를 삼켜 빈 문자열로 만들지 않는다.**

    빈 문자열을 돌려주면 "본문에 그 숫자가 없다" 와 "문서를 못 읽었다" 가 같아진다.
    전자는 증거가 틀렸다는 뜻이고 후자는 아무 말도 못 한 것이다 (`CLAUDE.md` §2).
    """
    import httpx

    try:
        with httpx.Client(follow_redirects=True, timeout=timeout_s) as c:
            r = c.get(url, headers={"User-Agent": _UA, "Accept": "text/html,*/*"})
        if r.status_code != 200:
            log.info("실사: %s → HTTP %s", url[:70], r.status_code)
            return None
        return r.text[:MAX_BYTES]
    except Exception as e:  # 네트워크·TLS·인코딩 — 사유를 남기고 못 읽었다고 한다
        log.info("실사: %s → %s", url[:70], type(e).__name__)
        return None


def render_audit(theme: str, res: AuditResult) -> str:
    """사람이 읽는 실사 보고. **먼저 무엇을 열어야 하는지**가 위에 온다."""
    counts = res.counts()
    n = len(res.checks)
    lines = [
        f"■ 증거 실사 · {theme}",
        "=" * 78,
        f"판정을 만든 증거 {n}건 — " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items())),
        "",
    ]
    bad = [c for c in res.checks if c.status == PARTIAL]
    if bad:
        lines += ["**원문에서 못 찾은 숫자가 있다 — 먼저 열어라**", ""]
        for c in sorted(bad, key=lambda x: -len(x.missing)):
            lines.append(
                f"  [{c.evidence_id}] 못 찾음 {len(c.missing)}/{len(c.wanted)}: "
                f"{', '.join(c.missing[:6])}"
            )
            lines.append(f"       {c.url[:100]}")
        lines.append("")
    unread = [c for c in res.checks if c.status in (UNREACHABLE, UNSUPPORTED)]
    if unread:
        lines += [
            f"**읽지 못한 문서 {len(unread)}건 — 맞다는 뜻도 틀리다는 뜻도 아니다**",
            "",
        ]
        lines += [f"  [{c.evidence_id}] {c.status} — {c.url[:90]}" for c in unread]
        lines.append("")
    ua = res.unverified_axes()
    if ua:
        lines += [
            "**확인된 근거가 하나도 없는 축**: " + ", ".join(ua),
            "  그 축의 판정은 확인되지 않은 것 위에 서 있다. 판정을 바꾸지는 않는다 —"
            " 무엇을 믿고 있는지 적을 뿐이다.",
            "",
        ]
    if not bad and not unread and not ua:
        lines.append("모든 근거의 숫자를 원문에서 찾았다.")
    lines += [
        "",
        "이 검사는 **숫자가 문서에 있는지**만 본다. 두 가지를 못 한다:",
        "  · 단위 변환 — 한국어 '2,220만 달러' 는 영문 원문에 `$22.2 million` 이라 안 맞는다.",
        "    `partial` 이 곧 날조라는 뜻이 아니다. 못 찾은 숫자를 보고 사람이 판단한다.",
        "  · 문맥 — 숫자가 있어도 claim 이 말하는 뜻과 다를 수 있다.",
        "판정을 만든 축의 근거는 결국 사람이 원문을 읽어야 한다. 이 표는 **어느 것을 먼저**",
        "열지 정해 줄 뿐이다.",
    ]
    return "\n".join(lines)
