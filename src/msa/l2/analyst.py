"""매크로 분석가 — `cycle_class` 8칸에 3값 판정을 붙이는 역할 프롬프트와 실행.

L3 의 provider 추상을 **그대로 재사용한다** (`msa.l3.providers`). 새 프로바이더를 만들지
않는다 — 오프라인은 `mock`·`fixture`, 실제는 `anthropic`·`claude_code` 로 같다.

## 이 역할이 하지 않는 것

- **종목을 말하지 않는다.** `CLAUDE.md` §4 가 금지한다. 스키마에 종목 칸이 없다.
- **점수를 말하지 않는다.** 판정은 3값뿐이고 계수는 코드가 붙인다 (`docs/25` §3.4).
- **어떤 거시 변수를 볼지 코드가 정하지 않는다.** 분석가가 증거와 함께 가져오고, 무엇을
  봤는지는 산출물의 `evidence` 에 남는다. 코드가 변수를 고르면 그것이 L2 를 죽인 자유도
  폭발이다 (`docs/25` §5).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from msa.l2.regime import CYCLE_CLASSES, VERDICTS
from msa.l3 import roles as _roles
from msa.l3.providers import CompletionRequest, LLMProvider

#: 각 칸이 무엇에 걸린 테마 묶음인지 — 프롬프트에 그대로 싣는다. 분석가가 `credit_rate` 를
#: 자기 식으로 해석하면 8칸의 뜻이 매주 바뀐다.
CLASS_MEANING: dict[str, str] = {
    "capex_program": "설비투자 프로그램에 걸린 산업 — 발주·수주잔량·프로젝트 FID 가 드라이버",
    "commodity_supply": "원자재 공급 사이클 — 광산·정제·감산·재고가 드라이버",
    "credit_rate": "금리·신용 사이클 — 조달비용·차환·스프레드가 드라이버",
    "discretionary_demand": "가계 재량 지출 — 실질소득·고용·소비심리가 드라이버",
    "inventory": "재고 사이클 — 채널 재고·출하/재고 비율이 드라이버",
    "policy_program": "정책·예산 집행 — 법안·보조금·조달 일정이 드라이버",
    "secular_growth": "구조적 성장 — 거시에 **덜** 걸린다. 판정이 대개 neutral 인 것이 정상이다",
    "secular_risk": "구조적 쇠퇴 위험 — 거시 순풍이 와도 되돌리지 못하는 쪽",
}

SYSTEM = (
    "너는 산업 사이클 리서치 팀의 **매크로 스트래티지스트**다. 하는 일은 하나다 — "
    f"아래 {len(CYCLE_CLASSES)}개 테마 유형 각각에 대해 **향후 3~6개월** 의 거시 환경이 "
    "순풍(tailwind)인지 중립(neutral)인지 역풍(headwind)인지 판정한다.\n\n"
    "## 절대 규칙\n"
    "1. **종목을 말하지 마라.** 티커도 회사명도 쓰지 않는다. 이 판정은 유형 단위다.\n"
    "2. **출처 없는 주장은 저장되지 않는다.** 판정마다 `evidence` 에 URL 과 날짜를 단다. "
    "네 기억은 증거가 아니다.\n"
    "3. **무효화 조건 없는 판정은 저장되지 않는다.** `invalidations` 에 '무엇이 관측되면 "
    "이 판정이 틀린 것인가' 를 **관측 가능한 형태**로 적는다. '상황이 나빠지면' 은 무효화 "
    "조건이 아니다.\n"
    "4. **수익률을 말하지 마라.** '얼마나 오를 것' 이라고 쓰지 않는다. 이 판정은 사람이 "
    "차트를 **어느 순서로 열지** 를 미는 데만 쓰인다.\n"
    "5. 모르면 `neutral` 이다. 억지로 방향을 내지 마라 — 8칸이 전부 중립이어도 그것이 "
    "정직한 판정이면 맞는 답이다.\n\n"
    "## 어떤 변수를 볼지는 네가 정한다\n"
    "금리·물가·고용·달러·유가·신용스프레드·재정·무역 — 무엇을 봤는지는 `evidence` 에 "
    "남는다. 코드가 변수 목록을 주지 않는 것이 의도다."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "classes": {
            "type": "object",
            "properties": {
                name: {
                    "type": "object",
                    "properties": {
                        "verdict": {"type": "string", "enum": list(VERDICTS)},
                        "mechanism": {
                            "type": "string",
                            "description": "왜 그렇게 보는가 — 한 문단. 종목명 금지",
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
                                    "reliability": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                    },
                                },
                                "required": ["claim", "source_url", "date"],
                            },
                        },
                    },
                    "required": ["verdict", "mechanism", "invalidations", "evidence"],
                }
                for name in CYCLE_CLASSES
            },
            "required": list(CYCLE_CLASSES),
        }
    },
    "required": ["classes"],
}


def build_request(week: str, asof: str) -> CompletionRequest:
    """주간 판정 요청 하나. 8칸을 한 번에 묻는다 — 칸마다 부르면 8배 비싸고, 칸 사이의
    일관성(같은 금리 전망이 두 칸에서 다르게 쓰이는 것)을 아무도 못 본다."""
    rows = "\n".join(f"- **{k}** — {v}" for k, v in sorted(CLASS_MEANING.items()))
    user = (
        f"## 기준\n주 {week} · 기준일 {asof}. 판정 지평은 **향후 3~6개월** 이다.\n\n"
        f"## 판정할 {len(CYCLE_CLASSES)}칸 (전부 답한다)\n{rows}\n\n"
        "## 산출\n위 스키마의 JSON 하나. 칸을 빠뜨리면 거부된다."
    )
    return CompletionRequest(
        role="macro_strategist",
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        json_schema=SCHEMA,
    )


#: 프롬프트가 **반드시 담아야 하는** 금지 문구. 종목을 물으면 유명세 편향이 들어온다
#: (`CLAUDE.md` §4).
#:
#: 초안은 반대로 짰다 — "프롬프트에 '티커' 라는 낱말이 없어야 한다" 는 토큰 검사였다.
#: **틀렸다.** 프롬프트는 정당하게 *"티커도 회사명도 쓰지 않는다"* 라고 금지하고 있고,
#: 토큰 검사는 그 금지문 자체를 위반으로 센다. L3 의 같은 기법(`L1_SCORE_FIELDS`)은
#: **입력이 새는 것**을 막는 것이라 성질이 다르다.
#:
#: 실제 보증은 프롬프트 문구가 아니라 **출력 스키마**에 있다 — `SCHEMA` 에 종목을 담을
#: 칸이 없으므로 모델이 종목을 내려 해도 담을 곳이 없다. 아래는 그 위의 보조 확인이다.
REQUIRED_PROHIBITIONS: tuple[str, ...] = (
    "종목을 말하지 마라",
    "수익률을 말하지 마라",
)


def run(provider: LLMProvider, *, week: str, asof: str) -> dict[str, Any]:
    """분석가를 한 번 부르고 레짐 문서 모양으로 돌려준다. **검증은 호출자가** 한다
    (`regime.write` 가 저장 전에 부른다) — 여기서 삼키면 실패가 조용해진다."""
    result = provider.complete(build_request(week, asof))
    obj = result.json()
    out: dict[str, Any] = {"asof": asof, "week": week, "classes": obj.get("classes") or {}}
    if obj.get("synthetic"):
        # 합성 표시는 프로바이더가 낸 그대로 보존한다 — 지우면 실제 판정과 구분되지 않는다.
        out["synthetic"] = True
    return out


def theme_classes(themes: Iterable[Any]) -> dict[str, str]:
    """테마 → `cycle_class`. `msa.themes.load_themes()` 의 `ThemeSet` 을 그대로 받는다.

    `ThemeSet` 은 `__iter__` 만 있고 `Sequence` 가 아니다 — 그래서 `Iterable` 로 받는다.
    """
    return {t.id: t.cycle_class for t in themes}


def summarize(doc: Mapping[str, Any] | None) -> str:
    """리포트 한 줄. 문서가 없으면 그렇다고 적는다 — 없는 것을 중립이라 말하지 않는다."""
    if not doc:
        return "매크로 레짐 없음 — R 계수 전부 1.0 (판정을 안 돌렸다는 뜻이지 중립이 아니다)"
    classes = doc.get("classes") or {}
    counts: dict[str, int] = {v: 0 for v in VERDICTS}
    for body in classes.values():
        v = (body or {}).get("verdict")
        if v in counts:
            counts[v] += 1
    parts = " · ".join(f"{k} {counts[k]}" for k in VERDICTS)
    return f"매크로 레짐 {doc.get('week')} — {parts} (읽는 순서만 민다)"


#: `--dry-run`(MockProvider) 용 결정론 응답. **합성이라는 것이 mechanism 에 적혀 있다.**
MOCK_OUTPUT: dict[str, Any] = {
    "synthetic": True,
    "classes": {
        name: {
            "verdict": "neutral",
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
        for name in CYCLE_CLASSES
    }
}

_roles.register_mock_output("macro_strategist", MOCK_OUTPUT)
