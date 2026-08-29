"""P3 종목 분석가 — 기업 분석가 자리. 설계 §9.2.

## `CLAUDE.md` §4 와 충돌하지 않게 짓는 것이 이 자리의 전부다

> LLM 에게 종목을 물으면 훈련 데이터의 유명세 편향이 들어온다.

그래서 규칙이 셋이고, 셋 다 테스트가 강제한다:

1. **후보는 코드가 정한다.** `candidates()` 가 구획 I-A 의 트리아지 상위 N 을 고른다.
   LLM 은 명단을 **만들지 않고 받는다.** 프롬프트에 티커가 들어가는 것은 그래서 위반이
   아니다 — 고르라는 것이 아니라 **이것을 보라**는 것이다.
2. **질문은 하나뿐이다.** *"이 회사의 재무가 무너지고 있는가"* — `bear` 의 종목판이다.
   "살 만한가" · "얼마나 오를까" 를 묻지 않는다. 스키마에 그 답을 담을 칸이 없다.
3. **산출은 판정이 아니라 재료다.** 증거 배열 + 무효화 조건. 점수에는 `J_ticker` 성분으로
   들어가고, 노트가 없는 종목은 `J = J_theme` 이 되어 **오늘의 식이 특수해**가 된다.

## 온디맨드다 — 매일 돌지 않는다

구획 I-A 에 **새로** 들어온 종목만 부른다. 매일 전부 부르면 크레딧이 매일 들고, 같은 종목의
판정이 매일 흔들려 사람이 무엇을 믿을지 모르게 된다 (P2 와 같은 이유, `docs/25` §4.3).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from msa.errors import Rejected
from msa.l3 import roles as _roles
from msa.l3.providers import CompletionRequest, LLMProvider

#: 재무 판정 3값. `bear` 의 종목판이라 **부정 쪽이 기본**이다 — 모르면 `unknown` 이지
#: `intact` 가 아니다.
VERDICTS = ("intact", "strained", "breaking")

#: 판정 → J_ticker 성분. **선언값이고 근거가 없다** (설계 §9.2).
#: `msa.basis` 에 `NoBasis` 로 등록돼 있다. 아무것도 자르지 않는다 — 순서만 민다.
NOTE_TRUST = {"intact": 1.00, "strained": 0.60, "breaking": 0.20}

_URL = re.compile(r"^https?://\S+$")


class NoteRejected(Rejected, ValueError):
    """종목 노트가 계약을 어겼다 — 저장하지 않는다."""


@dataclass(frozen=True)
class Candidate:
    ticker: str
    theme: str
    triage: float


def candidates(
    triage_rows: Iterable[Mapping[str, Any]], *, partition: str, top_n: int
) -> list[Candidate]:
    """**코드가 고른다.** 구획 안에서 triage 상위 N.

    `top_n` 은 **표시·호출 개수**이지 선정 규칙이 아니다 — L4 의 선정은 여전히 "하드 제외
    통과 전부" 이고 (`journal/2026-08-24-l4-selection-retired.md`), 여기서 자르는 것은
    *누구에게 분석가를 붙일 것인가* 뿐이다.
    """
    rows = [
        r
        for r in triage_rows
        if r.get("partition") == partition and r.get("triage") is not None
    ]
    rows.sort(key=lambda r: (-float(r["triage"]), str(r.get("ticker"))))
    return [
        Candidate(str(r["ticker"]), str(r.get("theme") or ""), float(r["triage"]))
        for r in rows[: max(top_n, 0)]
    ]


SYSTEM = (
    "너는 리서치 팀의 **기업 분석가**다. 하는 일은 하나다 — 주어진 회사의 "
    "**재무가 무너지고 있는가**를 판정한다.\n\n"
    "## 절대 규칙\n"
    "1. **살 만한지 묻지 않았다.** 목표가·투자의견·기대수익을 쓰지 마라. 그 답을 담을 칸이 "
    "스키마에 없다.\n"
    "2. **너는 이 종목을 고르지 않았다.** 명단은 코드가 정했다. 네 일은 그 명단에 있는 "
    "회사의 재무를 **깨려고** 시도하는 것이다.\n"
    "3. **출처 없는 주장은 저장되지 않는다.** 판정마다 `evidence` 에 URL 과 날짜를 단다. "
    "네 기억은 증거가 아니다.\n"
    "4. **무효화 조건 없는 판정은 저장되지 않는다.** '무엇이 관측되면 이 판정이 틀린 "
    "것인가' 를 관측 가능한 형태로 적는다.\n"
    "5. **모르면 `strained` 가 아니라 근거를 못 찾았다고 적어라.** 억지로 방향을 내면 "
    "그 판정이 사람의 읽는 순서를 잘못 민다.\n\n"
    "## 판정 3값\n"
    "- `intact` — 재무가 버틴다. 유동성·차환·현금흐름에 임박한 문제가 없다.\n"
    "- `strained` — 압박이 있다. 견딜 수도 있지만 사람이 재무제표를 열어야 한다.\n"
    "- `breaking` — 무너지는 중이다. 차환 실패·계속기업 의문·현금 소진이 임박했다."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "mechanism": {
            "type": "string",
            "description": "재무가 무너지는(또는 버티는) 경로. 목표가·투자의견 금지",
        },
        "invalidations": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
            "description": "무엇이 관측되면 이 판정이 틀린 것인가 (관측 가능하게)",
        },
        "evidence": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "source_url": {"type": "string"},
                    "date": {"type": "string"},
                    "reliability": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["claim", "source_url", "date"],
            },
        },
    },
    "required": ["verdict", "mechanism", "invalidations", "evidence"],
}

#: 프롬프트가 **반드시 담아야 하는** 금지 문구 (P2 와 같은 기법 — 토큰 부재 검사가 아니라
#: 금지문 존재 검사다. 이유는 `msa.l2.analyst.REQUIRED_PROHIBITIONS` 주석에 있다).
REQUIRED_PROHIBITIONS: tuple[str, ...] = (
    "살 만한지 묻지 않았다",
    "너는 이 종목을 고르지 않았다",
)

#: 프롬프트에 실어 주는 재무 열 — 사람이 리포트에서 보는 것과 **같은 것**이다. 분석가가
#: 다른 숫자를 보고 다른 말을 하면 사람이 대조할 수 없다.
CONTEXT_COLUMNS: tuple[str, ...] = (
    "price",
    "mcap",
    "adv20_usd",
    "net_debt_ebitda",
    "cash_runway_q",
    "from_52w_high",
    "red_flags",
    "survival_unjudged",
)


def build_request(cand: Candidate, pick: Mapping[str, Any], asof: str) -> CompletionRequest:
    """한 종목에 대한 요청 하나."""
    rows = "\n".join(
        f"- `{c}` = {pick.get(c)!r}" for c in CONTEXT_COLUMNS if pick.get(c) is not None
    )
    user = (
        f"## 대상\n`{cand.ticker}` · 테마 `{cand.theme}` · 기준일 {asof}\n\n"
        f"## 코드가 이미 계산한 재무 (같은 숫자를 보라)\n{rows or '- (없음)'}\n\n"
        "## 질문 (하나뿐이다)\n"
        "이 회사의 **재무가 무너지고 있는가?** 차환 일정·현금 소진 속도·계약/규제 충격·"
        "감사의견을 원문 출처로 확인해 판정하라.\n\n"
        "## 산출\n위 스키마의 JSON 하나."
    )
    return CompletionRequest(
        role="stock_analyst",
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        json_schema=SCHEMA,
    )


def validate(note: Mapping[str, Any]) -> None:
    """노트 검증 — L3 계약을 그대로 승계한다 (`CLAUDE.md` §3·§5)."""
    if not str(note.get("ticker") or "").strip():
        raise NoteRejected("ticker 가 비었다")
    if note.get("verdict") not in VERDICTS:
        raise NoteRejected(f"verdict 는 {VERDICTS} 중 하나여야 한다: {note.get('verdict')!r}")
    if not str(note.get("mechanism") or "").strip():
        raise NoteRejected("mechanism 이 비었다")
    if not list(note.get("invalidations") or []):
        raise NoteRejected(
            "invalidations 가 비었다 — 무효화 조건 없는 판정은 판정이 아니다 (CLAUDE.md §5)"
        )
    ev = list(note.get("evidence") or [])
    if not ev:
        raise NoteRejected("evidence 가 비었다 — LLM 의 기억은 증거가 아니다 (CLAUDE.md §3)")
    for i, e in enumerate(ev):
        if not _URL.match(str((e or {}).get("source_url") or "")):
            raise NoteRejected(f"evidence[{i}] 의 source_url 이 URL 이 아니다")
        if not str((e or {}).get("claim") or "").strip():
            raise NoteRejected(f"evidence[{i}] 의 claim 이 비었다")


def path_for(root: Path, ticker: str) -> Path:
    return Path(root) / f"{ticker}.yaml"


def write(root: Path, note: Mapping[str, Any]) -> Path:
    """검증 후 저장. 같은 종목을 다시 분석하면 **덮어쓴다** — 재무는 분기마다 바뀌고,
    옛 판정을 남겨 두면 어느 것이 오늘의 판정인지 모른다. 이력은 `journal/` 이 진다."""
    validate(note)
    p = path_for(root, str(note["ticker"]))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(dict(note), allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def read(root: Path, ticker: str) -> dict[str, Any] | None:
    p = path_for(root, ticker)
    if not p.exists():
        return None
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    return dict(raw) if isinstance(raw, Mapping) else None


def load_all(root: Path, tickers: Iterable[str]) -> dict[str, float]:
    """티커 → `J_ticker` 성분. 노트가 없는 종목은 **키가 없다** — 0 이 아니다.

    없음을 0 으로 채우면 분석가를 안 부른 종목이 "재무가 무너지는 종목" 과 같은 값을
    받는다 (`CLAUDE.md` §2).
    """
    out: dict[str, float] = {}
    for t in tickers:
        note = read(root, t)
        if not note or note.get("verdict") not in NOTE_TRUST:
            continue
        if note.get("synthetic"):
            # **합성 응답(--dry-run)은 점수에 들어가지 않는다.** 경로 검증용으로 쓴 값이
            # 실제 읽는 순서를 조용히 바꾸면 --dry-run 이 dry 가 아니게 된다.
            # 건너뛴 사실은 `skipped_synthetic()` 이 든다.
            continue
        out[str(t)] = NOTE_TRUST[str(note["verdict"])]
    return out


def skipped_synthetic(root: Path, tickers: Iterable[str]) -> list[str]:
    """점수에서 제외된 **합성 노트**의 티커. 조용히 버리지 않는다 (`CLAUDE.md` §2)."""
    out: list[str] = []
    for t in tickers:
        note = read(root, t)
        if note and note.get("synthetic"):
            out.append(str(t))
    return sorted(set(out))


def run(
    provider: LLMProvider,
    cand: Candidate,
    pick: Mapping[str, Any],
    asof: str,
) -> dict[str, Any]:
    """분석가를 한 번 부르고 노트 모양으로 돌려준다. 검증은 호출자(`write`)가 한다."""
    obj = provider.complete(build_request(cand, pick, asof)).json()
    return {
        "ticker": cand.ticker,
        "theme": cand.theme,
        "asof": asof,
        # 합성 표시는 **프로바이더가 낸 그대로 보존한다** — 여기서 지우면 mock 산출이
        # 실제 판정과 구분되지 않는다.
        **({"synthetic": True} if obj.get("synthetic") else {}),
        "verdict": obj.get("verdict"),
        "mechanism": obj.get("mechanism"),
        "invalidations": list(obj.get("invalidations") or []),
        "evidence": list(obj.get("evidence") or []),
    }


def summarize(notes: Sequence[Mapping[str, Any]]) -> str:
    if not notes:
        return "종목 노트 없음 — J 는 테마 성분만으로 계산된다 (분석가를 안 불렀다는 뜻이다)"
    counts = {v: sum(1 for n in notes if n.get("verdict") == v) for v in VERDICTS}
    return "종목 노트 " + " · ".join(f"{k} {counts[k]}" for k in VERDICTS)


def declared_constants() -> dict[str, Any]:
    return {
        "note_trust": dict(NOTE_TRUST),
        "verdicts": list(VERDICTS),
        "candidate_rule": "구획 I-A 의 triage 상위 N — **코드가 고른다** (CLAUDE.md §4)",
        "question": "재무가 무너지고 있는가 — 살 만한가를 묻지 않는다",
        "cadence": "온디맨드 — 구획 I-A 에 새로 들어온 종목만",
    }


#: `--dry-run`(MockProvider) 용 결정론 응답. **합성이라는 것이 mechanism 에 적혀 있다** —
#: 실수로 저장돼도 사람이 실제 판정과 구분할 수 있어야 한다.
MOCK_OUTPUT: dict[str, Any] = {
    "synthetic": True,
    "verdict": "strained",
    "mechanism": "합성 응답(--dry-run) — 실제 판정이 아니다. 경로 검증용이다.",
    "invalidations": ["합성 응답이므로 무효화 조건도 합성이다"],
    "evidence": [
        {
            "claim": "합성 증거 — 실제 출처가 아니다",
            "source_url": "https://example.invalid/mock",
            "date": "2026-01-01",
            "reliability": "low",
        }
    ],
}

_roles.register_mock_output("stock_analyst", MOCK_OUTPUT)
