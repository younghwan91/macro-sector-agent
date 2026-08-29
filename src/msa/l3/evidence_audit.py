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

- **표기 차이는 따라간다** (2026-08-26). `만`·`억`·`조` 는 원 단위와 천·백만·십억 표기를
  함께 찾고 (`2,220만 달러` ↔ `$22.2 million`), 꼬리 0 도 맞춘다 (`6.0%` ↔ `6 percent`).
  자리수를 바꾼 후보는 **숫자 경계까지 본다** — `4` 가 `1,400`·`4.7` 안에서 걸리면 넓히려다
  검사를 꺼 버리는 것이다. 실측: 두 테마 46건에서 `partial` 23 → 9, `verified` 13 → 27.
- **반올림·근사는 여전히 남는다.** claim 의 "3,500만 명" 이 원문의 `35.4 million` 과 안 맞는다.
  `partial` 이 곧 날조가 아니다 — **못 찾은 숫자 목록을 보고 사람이 판단한다.**
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
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: 본문에서 찾을 숫자를 뽑는 규칙. 쉼표·소수점은 살린다.
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_YEAR = re.compile(r"^(19|20)\d{2}$")

#: claim 에서 **먼저 지우는** 것 — 날짜다. 날짜의 조각(`08`·`14`)은 claim 의 측정값이 아니고,
#: 증거 날짜는 `R_EVIDENCE_FUTURE`·`W_EVIDENCE_DATE_PLACEHOLDER` 가 따로 본다. 지우지 않으면
#: 실사가 날짜 조각을 "원문에서 못 찾은 숫자" 로 올려 신호를 묽게 만든다.
_DATE_LIKE = re.compile(
    r"\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?"
    r"|\d{4}년\s*\d{1,2}월(?:\s*\d{1,2}일)?"
    r"|\d{1,2}월\s*\d{1,2}일"
)

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
    """비교용 정규화 — 쉼표·공백을 없앤다. `1,180,000` 과 `1180000` 이 같아진다.

    **경계가 사라진다.** `4` 를 찾으면 `1,400` 안에서도 걸린다. 그래서 claim 에 적힌 표기를
    그대로 찾을 때만 쓰고, 자리수를 바꿔 만든 후보는 `_has_number` 로 경계까지 본다.
    """
    return re.sub(r"[,\s ]", "", s)


def _loose(s: str) -> str:
    """숫자 경계를 남긴 본문 — 자릿점만 지우고 나머지 공백은 하나로 접는다."""
    s = re.sub(r"(?<=\d)[,\u00a0\s](?=\d\d\d(?!\d))", "", s)
    return re.sub(r"\s+", " ", s)


def _has_number(body: str, token: str) -> bool:
    """`token` 이 **하나의 수로서** 본문에 있는가.

    앞뒤에 다른 숫자가 붙으면 아니다 — `4` 는 `1400`·`4.7`·`04` 에서 걸리면 안 된다.
    이것이 있어야 한 자리 후보(`400만` → 원문 `4 million` 의 `4`)를 안전하게 쓸 수 있다.
    """
    pat = r"(?<![\d.,])" + re.escape(token) + r"(?![\d.,]*\d)"
    return re.search(pat, body) is not None


#: 한글 수 단위 → 배수. **오탐의 가장 큰 원인이 이것이었다** — claim 이 "순손실 2,220만 달러"
#: 라고 쓰면 영문 원문에는 `$22.2 million` 으로 있어 숫자가 안 맞는다 (2026-08-26 실측).
_KO_SCALE: dict[str, float] = {"만": 1e4, "억": 1e8, "조": 1e12}

#: 원문이 어느 자리수로 적었는지 모르므로 **후보를 만들어 다 찾아본다.**
_EN_SCALE: tuple[float, ...] = (1e3, 1e6, 1e9)


def _fmt_num(x: float) -> str:
    """정수면 정수로, 아니면 꼬리 0 을 뗀다."""
    if abs(x - round(x)) < 1e-9:
        return str(round(x))
    return f"{x:.10f}".rstrip("0").rstrip(".")


def _alternates(raw: str, unit: str) -> list[str]:
    """`2,220` + `만` → 원문이 쓸 법한 표기 후보 (`22200000` · `22200` · `22.2`).

    **찾는 쪽만 넓힌다** — claim 이 틀렸는데 맞다고 하지는 않는다. 후보 중 하나라도 본문에
    있으면 그 숫자는 원문에 있는 것으로 본다.
    """
    scale = _KO_SCALE.get(unit)
    if scale is None:
        return []
    try:
        base = float(raw.replace(",", "")) * scale
    except ValueError:
        return []
    out: list[str] = []
    for v in [base] + [base / d for d in _EN_SCALE]:
        # 1 미만은 뺀다 — `0.0222` 로 적는 원문은 없고, 반올림하면 `0` 이 되어 아무 문서에나
        # 있는 값이 된다. **넓히려다 검사를 꺼 버리면 안 된다.**
        if abs(v) < 1.0:
            continue
        for t in (_fmt_num(v), _fmt_num(round(v, 1))):
            if t not in out:
                out.append(t)
    return out


def _plain(raw: str) -> str:
    """꼬리 0 을 뗀 표기 — claim 의 `6.0` 은 원문에 `6 percent` 로 있다 (2026-08-26 실측).

    자리수를 바꾸지 않으므로 `_has_number` 의 경계 검사만으로 안전하다.
    """
    try:
        return _fmt_num(float(raw.replace(",", "")))
    except ValueError:
        return raw


#: 영문 낱말 숫자 → 값. **작은 표만 둔다** — `twelve`·`eleven` 이 실측 오탐의 절반이었고
#: (2026-08-29, 해체 척수), 임의의 복합 수사 파서는 새 자유도라 유지비가 크다.
#: 맨 단위 낱말(`hundred`·`million`)은 **값으로 두지 않는다** — `five hundred ships` 가
#: claim 의 `100` 을 통과시키면 넓히려다 검사를 꺼 버리는 것이다.
_WORD_NUM: dict[str, tuple[str, ...]] = {
    "0": ("zero",),
    "1": ("one",),
    "2": ("two",),
    "3": ("three",),
    "4": ("four",),
    "5": ("five",),
    "6": ("six",),
    "7": ("seven",),
    "8": ("eight",),
    "9": ("nine",),
    "10": ("ten",),
    "11": ("eleven",),
    "12": ("twelve",),
    "13": ("thirteen",),
    "14": ("fourteen",),
    "15": ("fifteen",),
    "16": ("sixteen",),
    "17": ("seventeen",),
    "18": ("eighteen",),
    "19": ("nineteen",),
    "20": ("twenty",),
    "30": ("thirty",),
    "40": ("forty",),
    "50": ("fifty",),
    "60": ("sixty",),
    "70": ("seventy",),
    "80": ("eighty",),
    "90": ("ninety",),
    "100": ("one hundred",),
    "1000": ("one thousand",),
    "1000000": ("one million",),
    "1000000000": ("one billion",),
}


def _word_forms(token: str) -> tuple[str, ...]:
    """`12` → `("twelve",)`. 표에 없으면 빈 튜플 — 복합 수사(`twenty-one`)는 다루지 않는다."""
    return _WORD_NUM.get(token, ())


def _has_word(body: str, word: str) -> bool:
    """`word` 가 **하나의 낱말로서** 본문에 있는가.

    단어 경계를 강제한다 — `one` 이 `money`·`phone`, `ten` 이 `tenant` 안에서 걸리면
    검사가 꺼진다. `one hundred` 처럼 사이에 공백이 있는 것도 그대로 본다 (`_loose` 가
    본문 공백을 하나로 접어 둔다).
    """
    pat = r"(?<![A-Za-z])" + word.replace(" ", r"\s+") + r"(?![A-Za-z])"
    return re.search(pat, body, re.I) is not None


#: 본문의 영문 축약 단위 → 배수. **한 글자 약어는 붙여 쓴 것만** 본다 (`1.8M`) —
#: `40 M` 은 미터일 수도 있어 띄어 쓴 것까지 받으면 엉뚱한 수를 만든다.
_EN_UNIT_SCALE: dict[str, float] = {
    "k": 1e3,
    "m": 1e6,
    "bn": 1e9,
    "tn": 1e12,
    "thousand": 1e3,
    "million": 1e6,
    "billion": 1e9,
    "trillion": 1e12,
}

#: 붙여 쓴 한 글자 약어(`4.3k`)와 띄어 쓸 수 있는 낱말 단위(`0.6 million`).
_ABBREV_UNIT = re.compile(r"(\d+(?:\.\d+)?)(k|m|bn|tn)(?![A-Za-z])", re.I)
_WORD_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(thousand|million|billion|trillion)(?![A-Za-z])", re.I)


def _expanded_units(body: str) -> str:
    """본문의 `4.3k`·`0.6 million` 을 편 수(`4300`·`600000`)로 옮긴 **덧붙임 문자열**.

    원문이 어느 표기를 쓸지 모르므로 claim 쪽에서 후보를 만들었는데(`_alternates`),
    소수 + 단위 조합(`0.6 million`)은 그것만으로는 못 만난다 — `60만` 의 후보는
    `600000`·`600` 인데 본문에는 `0.6` 만 있기 때문이다. 그래서 **본문 쪽도 편다.**

    확장한 값은 공백으로 갈라 뒤에 붙인다 — `_has_number` 의 경계 검사가 그대로 산다.
    자리수를 바꾸지 않고 **적힌 그대로의 값**만 만든다.
    """
    out: list[str] = []
    for pat in (_ABBREV_UNIT, _WORD_UNIT):
        for m in pat.finditer(body):
            scale = _EN_UNIT_SCALE.get(m.group(2).lower())
            if scale is None:
                continue
            try:
                v = float(m.group(1)) * scale
            except ValueError:
                continue
            t = _fmt_num(v)
            if t not in out:
                out.append(t)
    return " ".join(out)


def _units_for(text: str, wanted: Sequence[str]) -> dict[str, str]:
    """숫자 바로 뒤에 붙은 한글 수 단위 (`2,220만` → `{"2,220": "만"}`). 없으면 빈 문자열."""
    out: dict[str, str] = {}
    for w in wanted:
        m = re.search(re.escape(w) + r"\s*([만억조])", text or "")
        out[w] = m.group(1) if m else ""
    return out


def _found(loose: str, w: str, unit: str) -> bool:
    """claim 의 숫자 `w` 하나가 본문에 있는가 — 표기 후보를 전부 본다.

    후보는 세 갈래다: claim 에 적힌 표기 그대로 · 자리수를 옮긴 것(`_alternates`) ·
    영문 낱말(`twelve`). 어느 갈래든 **경계를 본다** — 숫자는 숫자 경계, 낱말은 단어 경계.
    """
    cands = [_norm(w), _plain(w), *_alternates(w, unit)]
    if any(_has_number(loose, c) for c in cands):
        return True
    return any(_has_word(loose, word) for c in cands for word in _word_forms(c))


def strip_html(raw: str) -> str:
    """태그를 걷어낸 본문. 외부 의존을 쓰지 않는다 — 숫자만 찾으면 되므로 충분하다."""
    body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return html.unescape(body)


def _early_verdict(eid: int, url: str, wanted: tuple[str, ...], cut: int) -> EvidenceCheck | None:
    """문서를 **받기 전에** 판정이 나는 경우. 받아야 하면 `None`.

    `check_one` 과 `fetch_urls` 가 같은 규칙을 봐야 한다 — 규칙이 두 벌이면 미리 받는 목록과
    실제로 받는 목록이 어긋난다.
    """
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
    return None


def fetch_urls(items: Iterable[Mapping[str, Any]]) -> set[str]:
    """실제로 받아야 하는 URL 집합 — 중복은 하나다 (같은 KFF 페이지를 두 근거가 인용한다)."""
    out: set[str] = set()
    for item in items:
        url = str(item.get("source_url", ""))
        wanted, cut = numbers_in(str(item.get("claim", "")))
        if _early_verdict(int(item.get("id", -1)), url, wanted, cut) is None:
            out.add(url)
    return out


def check_one(item: Mapping[str, Any], fetch: Callable[[str], str | None]) -> EvidenceCheck:
    """증거 한 건 — claim 의 숫자가 문서에 있는가."""
    eid = int(item.get("id", -1))
    url = str(item.get("source_url", ""))
    claim = str(item.get("claim", ""))
    wanted, cut = numbers_in(claim)

    early = _early_verdict(eid, url, wanted, cut)
    if early is not None:
        return early

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
    body = _loose(strip_html(raw))
    # 본문의 `4.3k`·`0.6 million` 을 편 값을 뒤에 덧붙인다 — 숫자로 찾는 쪽만 넓어진다.
    loose = body + " " + _expanded_units(body)
    units = _units_for(claim, wanted)
    missing = tuple(w for w in wanted if not _found(loose, w, units.get(w, "")))
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
    todo = [e for e in ev if wanted_ids is None or int(e.get("id", -1)) in wanted_ids]
    cached = prefetch(todo, fetch)
    checks = [check_one(e, lambda u: cached[u]) for e in todo]
    return AuditResult(tuple(checks), axis_refs)


def prefetch(
    items: Sequence[Mapping[str, Any]], fetch: Callable[[str], str | None]
) -> dict[str, str | None]:
    """받아야 할 문서를 **동시에** 받아 URL → 본문으로 돌려준다.

    서로 다른 호스트라 한 사이트를 두드리는 것이 아니다. 같은 URL 은 한 번만 받는다 —
    한 페이지를 두 근거가 인용하는 일이 실제로 있다 (KFF MA 등록 현황).

    실패는 그대로 `None` 으로 남긴다. **여기서 삼켜 빈 문자열로 만들지 않는다** — 그러면
    "본문에 그 숫자가 없다" 와 "문서를 못 읽었다" 가 같아진다 (`CLAUDE.md` §2).
    """
    urls = sorted(fetch_urls(items))
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(urls))) as ex:
        return dict(zip(urls, ex.map(fetch, urls), strict=True))


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

#: **일시적 차단은 다시 시도한다.** 2026-08-29 실측: Commonwealth Fund 가 실사에서 403 을
#: 냈는데 같은 헤더로 나중에 다시 열자 200 이었다 — 헤더 문제가 아니라 순간적인 차단이었다.
#: 한 번 시도하고 `unreachable` 로 굳히면 **읽을 수 있는 문서를 "사람이 열어야 한다" 로
#: 잘못 미룬다.** 그 오판이 실제로 판정 하나를 며칠 묶어 뒀다.
RETRY_STATUSES = (403, 429, 500, 502, 503, 504)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_S = 2.0

#: 동시에 받는 문서 수. 서로 다른 호스트라 한 사이트를 두드리는 것이 아니다.
MAX_WORKERS = 8


def http_fetch(url: str, *, timeout_s: int = FETCH_TIMEOUT_S) -> str | None:
    """문서 본문. 실패하면 `None` — **예외를 삼켜 빈 문자열로 만들지 않는다.**

    빈 문자열을 돌려주면 "본문에 그 숫자가 없다" 와 "문서를 못 읽었다" 가 같아진다.
    전자는 증거가 틀렸다는 뜻이고 후자는 아무 말도 못 한 것이다 (`CLAUDE.md` §2).
    """
    import time

    import httpx

    headers = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    last = ""
    for attempt in range(RETRY_ATTEMPTS):
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout_s) as c:
                r = c.get(url, headers=headers)
            if r.status_code == 200:
                return r.text[:MAX_BYTES]
            last = f"HTTP {r.status_code}"
            if r.status_code not in RETRY_STATUSES:
                break
        except Exception as e:  # 네트워크·TLS·인코딩
            last = type(e).__name__
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_BACKOFF_S * (attempt + 1))
    log.info("실사: %s → %s (%d회 시도)", url[:70], last, RETRY_ATTEMPTS)
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
        "이 검사는 **숫자가 문서에 있는지**만 본다. 못 하는 것:",
        "  · 반올림·근사 — '3,500만 명' 은 원문의 `35.4 million` 과 숫자로는 안 맞는다.",
        "    `partial` 이 곧 날조라는 뜻이 아니다. 못 찾은 숫자를 보고 사람이 판단한다.",
        "  · 문맥 — 숫자가 있어도 claim 이 말하는 뜻과 다를 수 있다.",
        "  (단위 표기 차이 '2,220만 달러' ↔ `$22.2 million` 은 처리한다.)",
        "판정을 만든 축의 근거는 결국 사람이 원문을 읽어야 한다. 이 표는 **어느 것을 먼저**",
        "열지 정해 줄 뿐이다.",
    ]
    return "\n".join(lines)
