"""4역할 프롬프트 — 코드가 들고 있는 템플릿 (`docs/05-agent-research.md` §2).

프롬프트를 파일이 아니라 코드에 두는 이유: 역할의 질문 목록은 **고정**이고, 바뀌면 커밋에 남아야
한다.
역할별로 (1) 시스템 프롬프트, (2) 사용자 메시지 조립기, (3) 출력 JSON 스키마가 있다.
출력 스키마는 Anthropic `output_config.format` 에 그대로 실리고, Mock/Fixture 산출도 같은 형태로
검사한다.

증거 번호: 각 역할은 **자기 증거 목록 안의 1..n** 으로 `evidence_ids` 를 쓴다. 파이프라인이 전역
번호로
다시 매긴다. referee 만 전역 번호가 매겨진 통합 목록을 받고 그 번호를 쓴다 — 새 증거를 덧붙일 때는
안내받은 다음 번호부터.

bear 는 `BearInputs` 만 받는다 (`contracts.py`). 이 모듈의 `bear_messages()` 가 `ResearchInputs` 를
받지 않도록 타입으로 막아 둔다.
"""

from __future__ import annotations

import copy
import json
import re
from functools import partial
from typing import Any

from msa.l3.contracts import BearInputs, CaseStudy, ResearchInputs
from msa.l3.gates import DEBT_24M_TO_MCAP_MAX
from msa.l3.providers import CompletionRequest
from msa.thesis import AXES, AXIS_VERDICTS, INVALIDATION_ACTIONS, RELIABILITY

EVIDENCE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "claim": {"type": "string"},
        "source_url": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD. 출처 문서의 날짜"},
        "reliability": {"type": "string", "enum": list(RELIABILITY)},
    },
    "required": ["id", "claim", "source_url", "date", "reliability"],
    "additionalProperties": False,
}

_COMMON_RULES = """\
## 공통 규약 (위반 시 산출물이 거부된다)
- **모든 주장에 증거를 붙인다.** `evidence` 항목은
`id`·`claim`·`source_url`·`date`(YYYY-MM-DD)·`reliability` 를
  전부 갖춘다. 네 기억은 증거가 아니다 — URL 과 날짜를 댈 수 없는 주장은 적지 말고 "찾지 못함"
  이라고 적어라.
- `reliability`: high = 1차 출처(공시·정부 통계·기관 보고서 원문)를 수치까지 대조함 / medium = 2차
출처(업계지·
  애널리스트 요약) / low = 블로그·포럼·출처 불명. **수치는 원문 대조 없이 high 로 등급하지 않는다.**
- 12개월보다 오래된 출처는 그대로 적되 날짜를 속이지 않는다(리포트가 표시한다).
- **종목을 추천하지 않는다.** 개별 기업은 사실(생산량·발표)의 출처로만 언급한다.
목표주가·비중·매수/매도 언급 금지.
- 가격 예측을 하지 않는다. 물리량·시점·정책·원가의 언어로만 쓴다.
- 없는 것은 "없다" 고 산출한다. 매출·대용물로 채워 넣지 않는다.
- 출력은 지정된 JSON 스키마 하나뿐이다. 스키마 밖의 서술은 쓰지 않는다.
"""


def _fmt_members(inputs: ResearchInputs | BearInputs) -> str:
    if not inputs.members:
        return "(구성원 재무 요약 없음 — 스토어 미연결 또는 생략. 리포트에 표시됨)"
    rows = [
        "| ticker | name | mcap(USD bn) | revenue TTM(USD bn) | capex/D&A | net debt/EBITDA | "
        "EBITDA margin | 유동부채/시총 |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def n(v: float | None, d: int = 2, scale: float = 1.0) -> str:
        return "—" if v is None else f"{v / scale:.{d}f}"

    for m in inputs.members:
        rows.append(
            f"| {m.ticker} | {m.name or '—'} | {n(m.mcap, 2, 1e9)} | {n(m.revenue_ttm, 2, 1e9)} | "
            f"{n(m.capex_to_da)} | {n(m.net_debt_to_ebitda, 1)} | {n(m.ebitda_margin, 2)} | "
            f"{n(m.debt_current_to_mcap, 2)} |"
        )
    return "\n".join(rows)


def _fmt_cases(cases: tuple[CaseStudy, ...]) -> str:
    if not cases:
        return (
            "## 케이스 스터디 few-shot\n(few-shot 없음 — `state/cases/` 가 비어 있다. "
            "M6 산출물이 들어오면 여기 실린다.)"
        )
    parts = ["## 케이스 스터디 few-shot (판정 감각 보정용 — 임계를 여기에 맞추지 않는다)"]
    for c in cases:
        parts.append(f"### {c.case_id}\n{c.text.strip()}")
    return "\n\n".join(parts)


def _fmt_prior(inputs: ResearchInputs) -> str:
    if inputs.prior_thesis is None:
        return "## 이전 thesis\n(없음 — 이 테마의 첫 실행)"
    keep = {
        k: inputs.prior_thesis.get(k)
        for k in (
            "generated_at",
            "claim",
            "mechanism",
            "triggers",
            "invalidations",
            "cycle_confidence",
            "gate_result",
        )
    }
    return (
        f"## 이전 thesis ({inputs.prior_thesis_path})\n"
        "재실행이다. 아래 이전 논지를 읽고, 무엇이 **바뀌었는지** 와 왜 바뀌었는지를 "
        "key_uncertainties 또는 note 에 적어라. "
        "무효화 조건을 피하려고 논지를 슬쩍 옮기는 것은 표류(drift)이며 diff 로 기록된다.\n"
        f"```json\n{json.dumps(keep, ensure_ascii=False, indent=1, default=str)}\n```"
    )


def _fmt_scorecard(inputs: ResearchInputs) -> str:
    return (
        "## L1 테마 스코어카드 (결정론 계층 산출 — 참고용이며 다시 계산하지 않는다)\n```json\n"
        + json.dumps(
            inputs.scorecard.summary_for_prompt(), ensure_ascii=False, indent=1, default=str
        )
        + "\n```"
    )


def _header(inputs: ResearchInputs | BearInputs) -> str:
    return (
        f"# 테마: {inputs.theme_name} (`{inputs.theme_id}`) · 기준일 {inputs.asof}\n"
        f"Sharadar industry 라벨: {', '.join(inputs.industries)}\n"
    )


def _context_blocks(
    inputs: ResearchInputs | BearInputs,
    *,
    members_title: str = "## 구성원 재무 요약 (PIT, 시총 상위)",
    prior: str | None = None,
) -> list[str]:
    """네 역할이 공통으로 받는 사실 자료 — 구성원 재무 (· 이전 thesis) · 케이스 few-shot.
    거시 상태 블록은 없다 — L2 는 2026-08-23 에 제거됐다 (`docs/13` §9)."""
    blocks = [members_title + "\n" + _fmt_members(inputs)]
    if prior is not None:
        blocks.append(prior)
    blocks.append(_fmt_cases(inputs.cases))
    return blocks


def _analyst_request(
    inputs: ResearchInputs,
    *,
    role: str,
    system: str,
    questions: tuple[tuple[str, str], ...],
    schema: dict[str, Any],
    ids_note: str,
) -> CompletionRequest:
    """supply · catalyst 공통 조립 — 스코어카드 포함 컨텍스트 + 고정 질문 목록."""
    q = "\n".join(f"{i + 1}. **{k}** — {desc}" for i, (k, desc) in enumerate(questions))
    user = "\n\n".join(
        [
            _header(inputs),
            _fmt_scorecard(inputs),
            *_context_blocks(inputs),
            f"## 질문 (고정 — {len(questions)}개 전부 답한다. 못 찾으면 not_found=true)\n" + q,
            ids_note,
        ]
    )
    return CompletionRequest(
        role=role,
        system=system,
        messages=[{"role": "user", "content": user}],
        json_schema=schema,
    )


# ---------------------------------------------------------------- supply_analyst

SUPPLY_SYSTEM = (
    "너는 산업 사이클 리서치 팀의 **물리적 수급 분석가**(supply_analyst)다. 테마의 실물 "
    "공급·수요·재고·원가를 "
    "수치와 출처로 수집한다. 강세 증거를 찾는 역할이지만 찾지 못한 것은 찾지 못했다고 쓴다.\n\n"
    + _COMMON_RULES
)

SUPPLY_QUESTIONS = (
    ("capacity_and_closures", "현재 글로벌 생산능력과 가동률. 지난 3년 폐쇄·감산 발표 목록"),
    ("pipeline_3y", "향후 3년 증설 파이프라인 — 프로젝트별 규모·시점·확정도(FID 완료 여부)"),
    ("inventories", "재고 수준 — 거래소 재고, 유통 재고, 역사적 백분위"),
    ("lead_time", "신규 공급의 리드타임 (광산 7~10년, fab 3년, 조선소 2~3년 …)"),
    (
        "cost_curve",
        "원가곡선 — P50/P90 현금원가 추정과 현재 가격의 위치. 한계 생산자의 셧다운 발표 여부",
    ),
    (
        "unit_demand_series",
        "최종 수요의 **실물 소비량 시계열** — 매출이 아니라 물리 단위(톤·온스·MWh·배럴·대수)로 "
        "최소 10년, "
        "연 단위 이상. 출처(기관·보고서명·URL)와 집계 범위(지역·용도)를 명시. 없으면 found=false "
        "로 적는다.",
    ),
)

SUPPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "enum": [k for k, _ in SUPPLY_QUESTIONS]},
                    "summary": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "integer"}},
                    "not_found": {"type": "boolean"},
                },
                "required": ["topic", "summary", "evidence_ids", "not_found"],
                "additionalProperties": False,
            },
        },
        "unit_demand_series": {
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "unit": {"type": "string"},
                "scope": {"type": "string"},
                "source": {"type": "string"},
                "years": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                "evidence_ids": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["found", "unit", "scope", "source", "years", "evidence_ids"],
            "additionalProperties": False,
        },
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
    },
    "required": ["findings", "unit_demand_series", "evidence"],
    "additionalProperties": False,
}


supply_request = partial(
    _analyst_request,
    role="supply_analyst",
    system=SUPPLY_SYSTEM,
    questions=SUPPLY_QUESTIONS,
    schema=SUPPLY_SCHEMA,
    ids_note="증거는 `evidence` 배열에 1 부터 번호를 매겨 넣고 findings 의 `evidence_ids` 로 "
    "가리킨다.",
)


# ---------------------------------------------------------------- catalyst_analyst

CATALYST_SYSTEM = (
    "너는 산업 사이클 리서치 팀의 **정책·촉매 분석가**(catalyst_analyst)다. 향후 12개월의 "
    "정책·규제·예산·무역·"
    "발주 이벤트를 **날짜와 출처**로 수집한다. 시점 증거를 모으는 역할이다.\n\n" + _COMMON_RULES
)

CATALYST_QUESTIONS = (
    ("policy_calendar", "향후 12개월 정책·규제 이벤트 캘린더 (날짜 명시)"),
    ("budgets_subsidies_orders", "확정된 예산·보조금·발주 규모"),
    ("trade_measures", "무역 조치 (관세·수출통제·쿼터) 현황과 예정"),
    ("customer_capex", "수요처의 투자 계획 (발주처 capex 가이던스)"),
)

CATALYST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "calendar": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD 또는 YYYY-Qn"},
                    "event": {"type": "string"},
                    "kind": {"type": "string", "enum": [k for k, _ in CATALYST_QUESTIONS]},
                    "evidence_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["date", "event", "kind", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "enum": [k for k, _ in CATALYST_QUESTIONS]},
                    "summary": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "integer"}},
                    "not_found": {"type": "boolean"},
                },
                "required": ["topic", "summary", "evidence_ids", "not_found"],
                "additionalProperties": False,
            },
        },
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
    },
    "required": ["calendar", "findings", "evidence"],
    "additionalProperties": False,
}


catalyst_request = partial(
    _analyst_request,
    role="catalyst_analyst",
    system=CATALYST_SYSTEM,
    questions=CATALYST_QUESTIONS,
    schema=CATALYST_SCHEMA,
    ids_note="증거는 `evidence` 배열에 1 부터 번호를 매겨 넣고 calendar·findings 의 `evidence_ids` "
    "로 가리킨다.",
)


# ---------------------------------------------------------------- bear

BEAR_SYSTEM = (
    "너는 **논지 파괴 전담**(bear)이다. 성공 조건은 이 테마의 강세 논지를 **죽이는 것**이다. 균형 "
    "잡힌 시각을 "
    "요구하지 않는다 — 균형은 referee 가 잡는다. 네가 온건해지면 판별기 전체가 무력해진다.\n"
    "너는 이 테마가 스코어보드에서 몇 위인지, 어떤 점수를 받았는지 **모른다**. 그 정보는 "
    "의도적으로 주어지지 않았다.\n\n"
    "## 무기 — 가치함정 5축 (docs/04)\n"
    "1. 물량 추세: 이 산업의 **최종 수요량**이 줄고 있다는 증거를 찾아라 (매출이 아니라 물리 "
    "단위)\n"
    "2. 대체 위협: 대체하는 기술·재료·서비스와 그 침투율·비용 교차점·비가역성·규제 강제\n"
    "3. 이번 사이클이 지난 사이클과 다른 이유 (구조 변화)\n"
    "4. 강세론자가 **의도적으로 빼놓는** 사실\n"
    "5. 이미 가격에 반영됐을 가능성 — **이 서사가 언제부터 컨센서스였는가** 를 반드시 답하라\n"
    "6. 터미널 리스크 — 부채 만기, 규제 소멸, 지리적 집중\n\n"
    "`bear_case` 는 네 최강 논지의 **원문**이다. 그대로 보존되어 thesis 에 실린다 — 요약되지 "
    "않는다.\n\n" + _COMMON_RULES
)

BEAR_AXES = (
    "unit_demand",
    "substitution",
    "structural_change",
    "omitted_facts",
    "priced_in",
    "terminal_risk",
)

BEAR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bear_case": {"type": "string", "description": "최강 논지 원문. 요약 금지"},
        "attacks": {
            "type": "object",
            "properties": {
                k: {
                    "type": "object",
                    "properties": {
                        "argument": {"type": "string"},
                        "evidence_ids": {"type": "array", "items": {"type": "integer"}},
                        "strength": {
                            "type": "string",
                            "enum": ["strong", "moderate", "weak", "none_found"],
                        },
                    },
                    "required": ["argument", "evidence_ids", "strength"],
                    "additionalProperties": False,
                }
                for k in BEAR_AXES
            },
            "required": list(BEAR_AXES),
            "additionalProperties": False,
        },
        "consensus_since": {
            "type": "string",
            "description": "강세 서사가 컨센서스가 된 시점과 근거. 모르면 '불명'",
        },
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
    },
    "required": ["bear_case", "attacks", "consensus_since", "evidence"],
    "additionalProperties": False,
}


def bear_request(inputs: BearInputs) -> CompletionRequest:
    """bear 는 `BearInputs` 만 받는다 — `ResearchInputs` 를 넘기면 타입 오류다."""
    user = "\n\n".join(
        [
            _header(inputs),
            f"cycle_class (테마 정의의 선언값, 점수 아님): {inputs.cycle_class}",
            *_context_blocks(
                inputs, members_title="## 구성원 재무 요약 (PIT, 시총 상위 — 사실 자료)"
            ),
            "## 과제\n6개 공격축 전부에 대해 argument·evidence_ids·strength 를 채운다. 증거를 못 "
            "찾은 축은 strength=none_found 로 "
            "정직하게 적는다 (없는 증거를 만들지 않는다). 마지막에 `bear_case` 로 최강 논지를 "
            "원문으로 쓴다.",
            "증거는 `evidence` 배열에 1 부터 번호를 매겨 넣는다.",
        ]
    )
    return CompletionRequest(
        role="bear",
        system=BEAR_SYSTEM,
        messages=[{"role": "user", "content": user}],
        json_schema=BEAR_SCHEMA,
    )


# ---------------------------------------------------------------- referee

REFEREE_SYSTEM = (
    "너는 **referee** 다. 강세 측(supply·catalyst)과 bear 의 증거를 **축별로 대조**하고, 축 "
    "2·3·4·5 의 판정을 내리고, "
    "반증 가능한 논지(claim·mechanism·triggers·invalidations)를 쓴다.\n\n"
    "## 네가 하지 않는 것\n"
    "- **축 1(물량 추세)은 네가 판정하지 않는다.** L1 이 계산한 "
    "`verdict_post_ss`·`axis1_contested` 를 그대로 받는다. "
    "네 몫은 `axis1_contested=true` 일 때 **물량 감소가 산업 축소인가 수요 소멸인가** 를 서술로 "
    "판정하는 것(referee_ruling)이고, "
    "그 판정에는 evidence 번호가 붙어야 한다. 증거 없이 서술하면 게이트는 기각으로 닫힌다.\n"
    "- `cycle_confidence` 와 게이트 판정은 네가 계산하지 않는다. 코드가 docs/04 §3·§4 규칙을 "
    "기계적으로 적용한다. "
    "규칙 밖의 조정이 필요하면 값을 움직이는 대신 `key_uncertainties` 에 서술한다.\n"
    "- 종목을 고르지 않는다. claim 에 종목명을 쓰지 않는다.\n\n"
    "## 축 판정 기준 (docs/04 §2)\n"
    "- capital_cycle: capex/D&A<1 8분기+ · exit_count · asset_growth. 단독 판별 불가 — "
    "cycle/warning 만 내고 death 는 내지 않는다.\n"
    "- substitution: 침투율 <10% 이고 비용 우위 없음 → cycle / 10~35% 또는 비용 교차점 도달 → "
    "warning / >35% 또는 비용 역전 완료 또는 규제 강제 → death.\n"
    "- cost_curve: 가격 < P90 현금원가 + 셧다운 발표 관측 → cycle 이고 strong_cycle=true / 가격 < "
    "P75 → cycle / 원가곡선 상단 여유 → warning(무관). "
    "death 는 내지 않는다 (이 축은 '반등한다' 만 말한다).\n"
    f"- terminal_risk: 24M 만기부채/시총 > {DEBT_24M_TO_MCAP_MAX}, 자산 재활용성, 단일 규제 "
    "소멸, 지리 집중. 심각하면 "
    "severe=true (death), 주의면 warning.\n"
    "- 증거를 댈 수 없는 축은 not_applicable 로 닫고 note 에 그 사실을 적는다. low 등급 "
    "증거만으로는 판정할 수 없다 (medium 이상 1개 필요).\n\n"
    "## 논지 작성 규약\n"
    "- claim: 한 문장, 400자 이내, **반증 가능**. 기한과 관측치가 들어간다.\n"
    "- mechanism: 인과 경로. '역사적으로 함께 움직였다' 류의 상관 서술 금지. 공급·수요·정책의 "
    "언어로.\n"
    "- triggers: 관측 가능 + 출처 + 기한(by). '심리 개선' 은 트리거가 아니다.\n"
    "- invalidations: 관측되면 논지가 죽는 조건 + 출처 + action(exit|halve|freeze_ladder). 비면 "
    "저장되지 않는다.\n"
    "- horizon_months: [최소, 최대] 개월.\n"
    "- bear 의 논지를 요약하지 않는다 — 코드가 원문을 싣는다. 너는 반박 가능한 것과 불가능한 것을 "
    "가른다.\n\n" + _COMMON_RULES
)

#: referee 가 내는 축 판정 — `contested` 는 L1(축1)만 낸다 (`docs/05` §2).
REFEREE_VERDICTS: tuple[str, ...] = tuple(v for v in AXIS_VERDICTS if v != "contested")

_AXIS_OUT = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(REFEREE_VERDICTS)},
        "evidence_refs": {"type": "array", "items": {"type": "integer"}},
        "note": {"type": "string"},
    },
    "required": ["verdict", "evidence_refs", "note"],
    "additionalProperties": False,
}


def _axis_out(extra: dict[str, Any]) -> dict[str, Any]:
    o: dict[str, Any] = copy.deepcopy(_AXIS_OUT)
    o["properties"].update(extra)
    o["required"] = list(o["properties"].keys())
    return o


REFEREE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim": {"type": "string"},
        "mechanism": {"type": "string"},
        # 구조화 출력은 minItems 를 0/1 만 지원한다 (API 400). 길이 2 는 프롬프트로
        # 지시하고 `l3/schema.py` R_HORIZON 이 검증한다 — 미달이면 저장을 거부한다.
        "horizon_months": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "triggers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "observable": {"type": "string"},
                    "source": {"type": "string"},
                    "by": {"type": "string"},
                },
                "required": ["observable", "source", "by"],
                "additionalProperties": False,
            },
        },
        "invalidations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "observable": {"type": "string"},
                    "source": {"type": "string"},
                    "action": {"type": "string", "enum": list(INVALIDATION_ACTIONS)},
                },
                "required": ["observable", "source", "action"],
                "additionalProperties": False,
            },
        },
        "key_uncertainties": {"type": "array", "items": {"type": "string"}},
        "axes": {
            "type": "object",
            "properties": {
                "unit_demand": {
                    "type": "object",
                    "properties": {
                        "note": {"type": "string"},
                        "evidence_refs": {"type": "array", "items": {"type": "integer"}},
                        "referee_ruling": {"type": ["string", "null"]},
                        "referee_evidence_refs": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": [
                        "note",
                        "evidence_refs",
                        "referee_ruling",
                        "referee_evidence_refs",
                    ],
                    "additionalProperties": False,
                },
                "capital_cycle": _AXIS_OUT,
                "substitution": _AXIS_OUT,
                "cost_curve": _axis_out({"strong_cycle": {"type": "boolean"}}),
                "terminal_risk": _axis_out(
                    {
                        "severe": {"type": "boolean"},
                        "debt_maturity_24m_over_half": {"type": "boolean"},
                    }
                ),
            },
            "required": list(AXES),
            "additionalProperties": False,
        },
        "bear_rebuttal": {
            "type": "string",
            "description": "bear 논지 중 반박 가능한 것과 불가능한 것",
        },
        "evidence": {
            "type": "array",
            "items": EVIDENCE_ITEM_SCHEMA,
            "description": "referee 가 추가한 증거 (안내받은 번호부터)",
        },
    },
    "required": [
        "claim",
        "mechanism",
        "horizon_months",
        "triggers",
        "invalidations",
        "key_uncertainties",
        "axes",
        "bear_rebuttal",
        "evidence",
    ],
    "additionalProperties": False,
}


def referee_request(
    inputs: ResearchInputs,
    *,
    supply: dict[str, Any],
    catalyst: dict[str, Any],
    bear: dict[str, Any],
    evidence: list[dict[str, Any]],
    next_evidence_id: int,
) -> CompletionRequest:
    a1 = inputs.scorecard.axis1
    axis1_block = {
        "axis1_status": a1.axis1_status,
        "axis1_available": a1.available,
        "unit_series_source": a1.unit_series_source,
        "verdict_pre_ss": a1.verdict_pre_ss,
        "verdict_post_ss": a1.verdict_post_ss,
        "axis1_contested": a1.contested,
        "unit_cagr_10y": a1.unit_cagr_10y,
        "unit_cagr_10y_median": a1.unit_cagr_10y_median,
        "unit_cagr_5y": a1.unit_cagr_5y,
        "sign_split": a1.sign_split,
        "ss_n": a1.ss_n,
        "ss_coverage": a1.ss_coverage,
        "ma_flag": a1.ma_flag,
        "exit_count (축2)": a1.exit_count,
    }
    contested_note = (
        "**axis1_contested=true** — 보정 전후 판정이 다르거나 합산/중앙값 부호가 갈린다. 위 "
        "입력(ss_n·ss_coverage·ma_flag·exit_count)을 "
        "함께 보고 `axes.unit_demand.referee_ruling` 에 '산업 축소인가 수요 소멸인가' 를 서술하고 "
        "`referee_evidence_refs` 를 붙여라. "
        "증거 없이 서술하면 코드가 기각으로 닫는다."
        if a1.contested
        else "axis1_contested=false — referee_ruling 은 null 로 둔다."
    )
    user = "\n\n".join(
        [
            _header(inputs),
            _fmt_scorecard(inputs),
            "## 축 1 입력 (L1 계산 — 다시 판정하지 않는다)\n```json\n"
            + json.dumps(axis1_block, ensure_ascii=False, indent=1)
            + "\n```\n"
            + contested_note,
            *_context_blocks(inputs, prior=_fmt_prior(inputs)),
            "## supply_analyst 산출\n```json\n"
            + json.dumps(
                {k: v for k, v in supply.items() if k != "evidence"}, ensure_ascii=False, indent=1
            )
            + "\n```",
            "## catalyst_analyst 산출\n```json\n"
            + json.dumps(
                {k: v for k, v in catalyst.items() if k != "evidence"}, ensure_ascii=False, indent=1
            )
            + "\n```",
            "## bear 산출 (독립 컨텍스트에서 생성됨 — L1 스코어를 보지 않았다)\n```json\n"
            + json.dumps(
                {k: v for k, v in bear.items() if k != "evidence"}, ensure_ascii=False, indent=1
            )
            + "\n```",
            "## 통합 증거 목록 (전역 번호 — evidence_refs 는 이 번호를 쓴다)\n```json\n"
            + json.dumps(evidence, ensure_ascii=False, indent=1)
            + "\n```\n"
            f"새 증거를 덧붙이려면 id {next_evidence_id} 부터 번호를 매겨 `evidence` 에 넣는다.",
        ]
    )
    return CompletionRequest(
        role="referee",
        system=REFEREE_SYSTEM,
        messages=[{"role": "user", "content": user}],
        json_schema=REFEREE_SCHEMA,
    )


ROLE_SCHEMAS: dict[str, dict[str, Any]] = {
    "supply_analyst": SUPPLY_SCHEMA,
    "catalyst_analyst": CATALYST_SCHEMA,
    "bear": BEAR_SCHEMA,
    "referee": REFEREE_SCHEMA,
}


class RoleOutputError(ValueError):
    """역할 산출이 그 역할의 스키마 required 키를 갖추지 못했다."""


def check_role_output(role: str, obj: dict[str, Any]) -> None:
    """얕은 검사 — required 키 존재 + evidence 항목 필드. 깊은 검증은 thesis 단계(`schema.py`)가 "
    "한다."""
    schema = ROLE_SCHEMAS[role]
    missing = [k for k in schema["required"] if k not in obj]
    if missing:
        raise RoleOutputError(f"{role}: 산출에 필수 키가 없다: {missing}")
    ev = obj.get("evidence")
    if not isinstance(ev, list):
        raise RoleOutputError(f"{role}: evidence 가 배열이 아니다")
    for i, e in enumerate(ev):
        miss = [k for k in EVIDENCE_ITEM_SCHEMA["required"] if k not in e]
        if miss:
            raise RoleOutputError(f"{role}: evidence[{i}] 필드 누락 {miss}")


# ---------------------------------------------------------------- Mock 기본 산출
#
# `MockProvider` 의 역할별 결정론적 산출 — 스키마를 만족하며 게이트를 통과하는 '정상' 경로.
# 문자열 안의 `{theme}`·`{asof}`·`{year}` 는 요청 프롬프트에서 읽어 채운다 (`default_mock_output`).
# 내용은 합성이며 사실이 아니다 (URL 은 example.org).


def _mock_ev(role: str, i: int, claim: str, rel: str = "medium") -> dict[str, Any]:
    return {
        "id": i,
        "claim": claim,
        "source_url": f"https://example.org/{role}/{i}",
        "date": "{asof}",
        "reliability": rel,
    }


MOCK_OUTPUTS: dict[str, dict[str, Any]] = {
    "supply_analyst": {
        "findings": [
            {
                "topic": "capacity_and_closures",
                "summary": "{theme}: 지난 3년 감산 발표 3건(합성).",
                "evidence_ids": [1],
                "not_found": False,
            },
            {
                "topic": "pipeline_3y",
                "summary": "FID 완료 증설 1건, 규모 소폭(합성).",
                "evidence_ids": [2],
                "not_found": False,
            },
            {
                "topic": "inventories",
                "summary": "거래소 재고 10년 백분위 15%(합성).",
                "evidence_ids": [3],
                "not_found": False,
            },
            {
                "topic": "lead_time",
                "summary": "신규 공급 리드타임 5~7년(합성).",
                "evidence_ids": [1],
                "not_found": False,
            },
            {
                "topic": "cost_curve",
                "summary": "현재 가격이 P90 현금원가 아래, 셧다운 발표 2건(합성).",
                "evidence_ids": [4],
                "not_found": False,
            },
            {
                "topic": "unit_demand_series",
                "summary": "기관 통계의 실물 소비량 10년 시계열 확보(합성).",
                "evidence_ids": [5],
                "not_found": False,
            },
        ],
        "unit_demand_series": {
            "found": True,
            "unit": "kt",
            "scope": "global",
            "source": "합성 기관 통계",
            "years": [[2016 + k, 100 + 2 * k] for k in range(10)],
            "evidence_ids": [5],
        },
        "evidence": [
            _mock_ev("supply_analyst", 1, "감산 발표 3건 (합성)", "high"),
            _mock_ev("supply_analyst", 2, "FID 완료 증설 1건 (합성)"),
            _mock_ev("supply_analyst", 3, "거래소 재고 백분위 15% (합성)"),
            _mock_ev("supply_analyst", 4, "P90 현금원가 대비 가격 −12%, 셧다운 2건 (합성)", "high"),
            _mock_ev("supply_analyst", 5, "실물 소비량 10년 시계열 (합성)", "high"),
        ],
    },
    "catalyst_analyst": {
        "calendar": [
            {
                "date": "2027-03-31",
                "event": "보조금 집행 개시 (합성)",
                "kind": "policy_calendar",
                "evidence_ids": [1],
            }
        ],
        "findings": [
            {
                "topic": "policy_calendar",
                "summary": "12개월 내 정책 이벤트 2건(합성).",
                "evidence_ids": [1],
                "not_found": False,
            },
            {
                "topic": "budgets_subsidies_orders",
                "summary": "확정 예산 규모 (합성).",
                "evidence_ids": [2],
                "not_found": False,
            },
            {
                "topic": "trade_measures",
                "summary": "관세 현황 (합성).",
                "evidence_ids": [2],
                "not_found": False,
            },
            {
                "topic": "customer_capex",
                "summary": "수요처 capex 가이던스 상향 (합성).",
                "evidence_ids": [3],
                "not_found": False,
            },
        ],
        "evidence": [
            _mock_ev("catalyst_analyst", 1, "정책 캘린더 (합성)"),
            _mock_ev("catalyst_analyst", 2, "예산·관세 (합성)", "high"),
            _mock_ev("catalyst_analyst", 3, "수요처 capex 가이던스 (합성)"),
        ],
    },
    "bear": {
        "bear_case": (
            "{theme} 강세 서사는 이미 2년째 컨센서스이며, 대체재 침투율이 8%에서 가속 중이고, "
            "구성원 상위 기업의 "
            "유동부채 비중이 높아 사이클 회복 전에 희석이 일어날 수 있다. (합성 bear_case — "
            "원문 보존 테스트용)"
        ),
        "attacks": {
            "unit_demand": {
                "argument": "최종 수요량 감소 증거를 찾지 못함 (합성).",
                "evidence_ids": [],
                "strength": "none_found",
            },
            "substitution": {
                "argument": "대체재 침투율 8%, 비용 교차점 미도달 (합성).",
                "evidence_ids": [1],
                "strength": "moderate",
            },
            "structural_change": {
                "argument": "구조 변화 근거 약함 (합성).",
                "evidence_ids": [],
                "strength": "weak",
            },
            "omitted_facts": {
                "argument": "강세론이 재고 회계 변경을 빼놓음 (합성).",
                "evidence_ids": [2],
                "strength": "moderate",
            },
            "priced_in": {
                "argument": "서사는 2024년부터 컨센서스 (합성).",
                "evidence_ids": [2],
                "strength": "moderate",
            },
            "terminal_risk": {
                "argument": "유동부채/시총 일부 기업 높음 (합성).",
                "evidence_ids": [],
                "strength": "weak",
            },
        },
        "consensus_since": "2024년 하반기 (합성)",
        "evidence": [
            _mock_ev("bear", 1, "대체재 침투율 8% (합성)"),
            _mock_ev("bear", 2, "컨센서스 시점·재고 회계 (합성)", "low"),
        ],
    },
    "referee": {
        "claim": (
            "{theme} 의 공급 축소와 재고 소진으로 {year}년 말까지 실물 가격이 P90 원가 "
            "위로 회복되고 구성원 EBITDA 마진이 확대된다 (합성)."
        ),
        "mechanism": (
            "저가격 국면의 투자 중단으로 신규 공급이 수년간 불가능하고, 실물 수요량은 완만히 "
            "증가하므로 재고가 소진되면 가격이 한계원가 위로 복귀한다 (합성 인과 서술)."
        ),
        "horizon_months": [6, 18],
        "triggers": [
            {
                "observable": "주요 생산자 생산 가이던스 하향 발표",
                "source": "분기 실적 공시",
                "by": "2027-Q1",
            },
            {
                "observable": "breadth_200 > 0.6 지속 3개월",
                "source": "L1 스캐너",
                "by": "2027-Q2",
            },
        ],
        "invalidations": [
            {
                "observable": "확정 증설 파이프라인 규모가 수요의 10% 이상 추가 발표",
                "source": "기업 공시",
                "action": "exit",
            },
            {
                "observable": "실물 가격이 P90 원가 아래 6개월 지속",
                "source": "기관 가격 통계",
                "action": "halve",
            },
        ],
        "key_uncertainties": ["합성 데이터 — 실제 출처 없음", "대체재 침투 속도"],
        "axes": {
            "unit_demand": {
                "note": "L1 판정 수용 (합성)",
                "evidence_refs": [5],
                "referee_ruling": None,
                "referee_evidence_refs": [],
            },
            "capital_cycle": {
                "verdict": "cycle",
                "evidence_refs": [1, 2],
                "note": "capex/D&A<1, 감산 (합성)",
            },
            "substitution": {
                "verdict": "cycle",
                "evidence_refs": [9],
                "note": "침투율 8% <10%, 비용 우위 없음 (합성)",
            },
            "cost_curve": {
                "verdict": "cycle",
                "evidence_refs": [4],
                "note": "가격<P90, 셧다운 관측 (합성)",
                "strong_cycle": True,
            },
            "terminal_risk": {
                "verdict": "warning",
                "evidence_refs": [8],
                "note": "일부 유동부채 (합성)",
                "severe": False,
                "debt_maturity_24m_over_half": False,
            },
        },
        "bear_rebuttal": "priced_in 은 반박 불가, substitution 은 침투율 수치로 반박 (합성).",
        "evidence": [],
    },
}


def _fill(obj: Any, vars_: dict[str, str]) -> Any:
    """문자열 안의 `{theme}` 류 자리표시자를 채운다 (재귀). 다른 중괄호는 건드리지 않는다."""
    if isinstance(obj, str):
        for k, v in vars_.items():
            obj = obj.replace(k, v)
        return obj
    if isinstance(obj, dict):
        return {k: _fill(v, vars_) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill(x, vars_) for x in obj]
    return obj


def _extract(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None


def register_mock_output(role: str, output: dict[str, Any]) -> None:
    """L3 밖의 역할(P2 매크로 · P3 종목 분석가)이 자기 mock 응답을 등록하는 자리.

    `MockProvider` 를 `--dry-run` 으로 돌릴 때 쓰인다. **L3 가 L2·L4 를 임포트하지 않게**
    하려고 등록 방향을 뒤집었다 — 계층 간 결합은 파일 스키마로만 한다는 `docs/08` 의
    정신과 같다.
    """
    if role in MOCK_OUTPUTS:
        raise ValueError(f"이미 등록된 역할: {role}")
    MOCK_OUTPUTS[role] = output


def default_mock_output(request: CompletionRequest) -> dict[str, Any]:
    """`MOCK_OUTPUTS[role]` 의 사본에 테마 이름·기준일을 채운다 — 프롬프트에서 읽는다."""
    if request.role not in MOCK_OUTPUTS:
        raise ValueError(
            f"알 수 없는 역할: {request.role} — L3 밖의 역할이면 "
            "`roles.register_mock_output` 으로 등록한다"
        )
    text = request.as_text()
    asof = _extract(text, r"기준일 (\d{4}-\d{2}-\d{2})") or "2026-01-01"
    theme = _extract(text, r"# 테마: (.+?) \(`") or "테마"
    out: dict[str, Any] = _fill(
        copy.deepcopy(MOCK_OUTPUTS[request.role]),
        {"{theme}": theme, "{asof}": asof, "{year}": asof[:4]},
    )
    return out
