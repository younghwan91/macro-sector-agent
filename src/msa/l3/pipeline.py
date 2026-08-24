"""`msa research <theme>` 오케스트레이션.

```
inputs ─┬─ supply_analyst ──┐
        ├─ catalyst_analyst ┤   (스코어 포함 컨텍스트)   ← 세 역할은 서로 독립 — 병렬 호출
        └─ bear ────────────┤   (BearInputs — 스코어 숨김, 독립 컨텍스트)
                            ▼
                         referee ──► 축2~5 판정 · claim/mechanism/triggers/invalidations
                            ▼
             gates.apply_gates + cycle_confidence   (기계적)
                            ▼
             schema.validate_thesis  ──► 실패: ThesisRejected (저장 안 함)
                            ▼
  state/theses/<asof>/<theme>.thesis.yaml · <theme>.report.md
  + rejected 면 rejections-pending.yaml 에 행 추가 (대장은 M8)
  + contested.json (라운드 보류 수 · 이월 수)
```

증거 번호: 역할별 1..n → 전역 번호로 재배열(`merge_evidence`). referee 는 전역 번호를 쓴다.
L1 축 1 은 **재판정하지 않는다** — `Axis1Inputs` 를 그대로 thesis 에 옮긴다.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from msa.io import dir_lock, dump_yaml, write_snapshot
from msa.l3.contracts import Axis1Inputs, ResearchInputs
from msa.l3.gates import (
    CONF_BASE,
    AxisVerdicts,
    ConfidenceInputs,
    ConfidenceResult,
    ContestedCount,
    GateResult,
    apply_gates,
    cycle_confidence,
    rejection_row,
)
from msa.l3.providers import CompletionRequest, CostLedger, LLMProvider
from msa.l3.roles import (
    bear_request,
    catalyst_request,
    check_role_output,
    referee_request,
    supply_request,
)
from msa.l3.schema import ThesisRejected, ValidationResult, validate_thesis
from msa.thesis import (
    dump_thesis_yaml,
    gate_status,
    read_thesis_yaml,
    theme_of,
    theses_in,
    thesis_diff,
    thesis_filename,
)

log = logging.getLogger(__name__)

EVIDENCE_ROLE_ORDER = ("supply_analyst", "catalyst_analyst", "bear")


@dataclass
class RoleOutputs:
    supply: dict[str, Any]
    catalyst: dict[str, Any]
    bear: dict[str, Any]
    referee: dict[str, Any]


@dataclass
class ResearchResult:
    theme_id: str
    #: 라운드 식별자 = 쓴 스캔의 날짜. 산출물 디렉터리가 이것으로 묶인다
    #: (`scan`·`research`·`picks` 가 같은 라운드를 공유한다).
    asof: str
    thesis: dict[str, Any]
    validation: ValidationResult
    gate: GateResult
    confidence: ConfidenceResult
    diff: dict[str, Any]
    contested: ContestedCount
    ledger: CostLedger
    report_md: str
    roles: RoleOutputs
    warnings: list[str]
    out_dir: Path | None = None
    thesis_path: Path | None = None
    #: 판정을 내린 날. 증거의 미래 여부는 이것으로 쟀다.
    decision_date: str = ""


# ---------------------------------------------------------------- 증거 병합


def merge_evidence(
    outputs: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[int, int]]]:
    """역할별 로컬 번호 → 전역 번호. 반환: (전역 증거 목록, role → {local_id: global_id})."""
    merged: list[dict[str, Any]] = []
    remap: dict[str, dict[int, int]] = {}
    g = 0
    for role in EVIDENCE_ROLE_ORDER:
        out = outputs.get(role, {})
        remap[role] = {}
        for e in out.get("evidence", []):
            g += 1
            remap[role][int(e["id"])] = g
            merged.append({**e, "id": g, "role": role})
    return merged, remap


def _remap_ids(obj: Any, m: dict[int, int]) -> Any:
    """산출 안의 `evidence_ids` 배열을 전역 번호로 바꾼다 (재귀)."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k == "evidence_ids" and isinstance(v, list):
                out[k] = [m.get(int(x), int(x)) for x in v]
            else:
                out[k] = _remap_ids(v, m)
        return out
    if isinstance(obj, list):
        return [_remap_ids(x, m) for x in obj]
    return obj


#: 데이터 스냅샷이 판정일보다 이만큼 넘게 뒤처지면 리포트·thesis 에 경고로 남긴다.
#: 임계가 아니라 **표시**다 — 판정을 막지 않는다. 오래된 가격으로 판단하고 있다는 사실이
#: 보이지 않으면 나중에 원인을 못 찾는다 (CLAUDE.md §2).
DATA_LAG_WARN_DAYS = 7


def _days_between(a: str, b: str) -> int | None:
    """`b - a` 일수. 둘 중 하나라도 못 읽으면 None (조용히 0 으로 만들지 않는다)."""
    from datetime import date as _date

    try:
        return (_date.fromisoformat(b) - _date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 역할 실행


def run_roles(
    inputs: ResearchInputs, provider: LLMProvider, ledger: CostLedger
) -> tuple[RoleOutputs, list[dict[str, Any]]]:
    """supply · catalyst · bear 를 병렬로(서로 독립 컨텍스트), referee 는 그 셋을 받아 마지막에."""

    def call(req: CompletionRequest) -> dict[str, Any]:
        res = provider.complete(req)
        ledger.record(req.role, res)
        obj = res.json()
        check_role_output(req.role, obj)
        return obj

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            "supply_analyst": ex.submit(call, supply_request(inputs)),
            "catalyst_analyst": ex.submit(call, catalyst_request(inputs)),
            "bear": ex.submit(call, bear_request(inputs.bear_view())),  # 스코어 없음
        }
        outputs = {role: f.result() for role, f in futures.items()}
    merged, remap = merge_evidence(outputs)
    supply_g = _remap_ids(outputs["supply_analyst"], remap["supply_analyst"])
    catalyst_g = _remap_ids(outputs["catalyst_analyst"], remap["catalyst_analyst"])
    bear_g = _remap_ids(outputs["bear"], remap["bear"])
    referee = call(
        referee_request(
            inputs,
            supply=supply_g,
            catalyst=catalyst_g,
            bear=bear_g,
            evidence=merged,
            next_evidence_id=len(merged) + 1,
        )
    )
    # referee 추가 증거 — 번호 충돌은 뒤로 민다 (조용히 덮어쓰지 않는다)
    known = {e["id"] for e in merged}
    for e in referee.get("evidence", []):
        eid = int(e["id"])
        if eid in known:
            log.warning(
                "referee 증거 id %d 가 기존 번호와 충돌 — %d 로 재배정", eid, max(known) + 1
            )
            eid = max(known) + 1
        known.add(eid)
        merged.append({**e, "id": eid, "role": "referee"})
    return RoleOutputs(supply=supply_g, catalyst=catalyst_g, bear=bear_g, referee=referee), merged


# ---------------------------------------------------------------- thesis 조립


def _axis_block(ax: dict[str, Any]) -> dict[str, Any]:
    out = {
        "verdict": ax.get("verdict"),
        "evidence_refs": [int(x) for x in ax.get("evidence_refs", [])],
    }
    if ax.get("note"):
        out["note"] = ax["note"]
    for k, v in ax.items():
        if k not in ("verdict", "evidence_refs", "note"):
            out[k] = v
    return out


def _scan_evidence(inputs: ResearchInputs, a1: Axis1Inputs, eid: int) -> dict[str, Any]:
    """가용한 축 1 은 스캔 자체를 증거로 명시한다 — `indicators.csv` 가 출처다."""
    return {
        "id": eid,
        "claim": (
            f"L1 축1 {a1.unit_series_source}: unit_cagr_10y={a1.unit_cagr_10y} · "
            f"median={a1.unit_cagr_10y_median} · "
            f"5y={a1.unit_cagr_5y} · ss_n={a1.ss_n} · ss_coverage={a1.ss_coverage} · "
            f"ma_flag={a1.ma_flag} (unit_source={a1.unit_source})"
        ),
        "source_url": f"{inputs.scan_dir}/indicators.csv",
        "date": inputs.scorecard.scan_date,
        "reliability": "medium",
        "role": "l1_scan",
    }


def _unit_demand_axis(
    inputs: ResearchInputs,
    ud_in: dict[str, Any],
    evidence: list[dict[str, Any]],
    ev_ids: set[int],
) -> dict[str, Any]:
    """축 1 블록 — L1 값 그대로. 증거: referee 가 가리킨 것 + (가용하면) 스캔 증거를 덧붙인다
    (`evidence`·`ev_ids` 를 제자리에서 늘린다)."""
    a1 = inputs.scorecard.axis1
    refs = [int(x) for x in ud_in.get("evidence_refs", [])]
    if a1.available:
        scan_ev_id = max(ev_ids, default=0) + 1
        evidence.append(_scan_evidence(inputs, a1, scan_ev_id))
        ev_ids.add(scan_ev_id)
        refs.append(scan_ev_id)
    unit_demand: dict[str, Any] = {
        "verdict": a1.verdict,
        "evidence_refs": refs,
        "axis1_available": a1.available,
        "unit_series_source": a1.unit_series_source,
    }
    if ud_in.get("note"):
        unit_demand["note"] = ud_in["note"]
    if a1.available:
        unit_demand.update(
            {
                "verdict_pre_ss": a1.verdict_pre_ss,
                "verdict_post_ss": a1.verdict_post_ss,
                "axis1_contested": a1.contested,
                "ss_n": a1.ss_n,
                "ss_coverage": a1.ss_coverage,
                "ma_flag": a1.ma_flag,
                "unit_cagr_10y": a1.unit_cagr_10y,
                "unit_cagr_10y_median": a1.unit_cagr_10y_median,
                "unit_cagr_5y": a1.unit_cagr_5y,
                "sign_split": a1.sign_split,
            }
        )
    else:
        unit_demand["axis1_status"] = a1.axis1_status
    return unit_demand


def _judge(
    inputs: ResearchInputs, axes_in: dict[str, Any], ev_ids: set[int]
) -> tuple[AxisVerdicts, ConfidenceResult, GateResult]:
    """referee 축 판정 + L1 축1 → 확신도(04 §4) → 게이트(04 §3). 전부 기계적."""
    a1 = inputs.scorecard.axis1
    card = inputs.scorecard
    cc = axes_in["cost_curve"]
    tr = axes_in["terminal_risk"]
    verdicts = AxisVerdicts(
        unit_demand=a1.verdict,
        capital_cycle=str(axes_in["capital_cycle"]["verdict"]),
        substitution=str(axes_in["substitution"]["verdict"]),
        cost_curve=str(cc["verdict"]),
        terminal_risk=str(tr["verdict"]),
    )
    conf = cycle_confidence(
        ConfidenceInputs(
            verdicts=verdicts,
            capex_to_da_qtrs_below1=card.capex_to_da_qtrs_below1,
            axis4_strong_cycle=bool(cc.get("strong_cycle", False)),
            axis5_severe=bool(tr.get("severe", False)),
            small_sample=card.small_sample,
            short_hist=card.short_hist,
        )
    )
    ruling = axes_in["unit_demand"].get("referee_ruling")
    ruling_refs = tuple(int(x) for x in axes_in["unit_demand"].get("referee_evidence_refs", []))
    gate = apply_gates(
        verdicts,
        a1,
        confidence=conf.value,
        referee_ruling=str(ruling) if ruling else None,
        referee_evidence_refs=ruling_refs,
        referee_refs_valid=all(x in ev_ids for x in ruling_refs),
        secular_risk=card.cycle_class == "secular_risk",
        debt_24m_over_half=bool(tr.get("debt_maturity_24m_over_half", False)),
    )
    return verdicts, conf, gate


def build_thesis(
    inputs: ResearchInputs,
    roles: RoleOutputs,
    evidence: list[dict[str, Any]],
    *,
    generated_at: str,
) -> tuple[dict[str, Any], GateResult, ConfidenceResult]:
    """referee 산출 + L1 축1 + 게이트/확신도 → thesis dict. 검증은 호출자가 한다."""
    ref = roles.referee
    a1 = inputs.scorecard.axis1
    card = inputs.scorecard
    axes_in = ref["axes"]
    ev_ids = {int(e["id"]) for e in evidence}

    unit_demand = _unit_demand_axis(inputs, axes_in["unit_demand"], evidence, ev_ids)
    _, conf, gate = _judge(inputs, axes_in, ev_ids)

    key_unc = [str(x) for x in ref.get("key_uncertainties", [])]
    if not a1.available and not any("axis1_available" in x for x in key_unc):
        key_unc.append(
            f"axis1_available = false (axis1_status={a1.axis1_status}) — 축 1 을 쓸 수 없어 판별 "
            f"중심이 축 3(LLM) 으로 넘어간다 (04 축1 적용 범위)"
        )
    for n in conf.notes:
        if n not in key_unc:
            key_unc.append(n)

    thesis: dict[str, Any] = {
        "theme_id": inputs.theme_id,
        "generated_at": generated_at,
        "supersedes": inputs.prior_thesis_path,
        "horizon_months": [int(x) for x in ref["horizon_months"]],
        "claim": str(ref["claim"]).strip(),
        "mechanism": str(ref["mechanism"]).strip(),
        "triggers": [{**t, "status": "pending"} for t in ref["triggers"]],
        "invalidations": [{**t, "status": "pending"} for t in ref["invalidations"]],
        "key_uncertainties": key_unc,
        "bear_case": str(roles.bear["bear_case"]),  # 원문 그대로 — 요약하지 않는다
        "bear_rebuttal": str(ref.get("bear_rebuttal", "")),
        "consensus_since": str(roles.bear.get("consensus_since", "")),
        "value_trap_axes": {
            "unit_demand": unit_demand,
            "capital_cycle": _axis_block(axes_in["capital_cycle"]),
            "substitution": _axis_block(axes_in["substitution"]),
            "cost_curve": _axis_block(axes_in["cost_curve"]),
            "terminal_risk": _axis_block(axes_in["terminal_risk"]),
        },
        "gate_result": gate.as_dict(),
        "cycle_confidence": conf.value,
        "cycle_confidence_terms": {
            "base": CONF_BASE,
            **conf.terms,
            **({"cap": conf.cap} if conf.cap is not None else {}),
        },
        "cycle_confidence_by": "referee-pipeline (04 §4 기계 적용; 09 §2 — 산출 주체 표기)",
        "evidence": [dict(e) for e in evidence],
        "inputs": {
            "scan_dir": inputs.scan_dir,
            # 두 날짜를 모두 남긴다 — 하나로 합치면 어느 쪽 기준인지 다시 알 수 없다
            "data_asof": inputs.asof,
            "decision_date": generated_at,
            "data_lag_days": _days_between(inputs.asof, generated_at),
            "scoreboard_rank": card.rank,
            "cycle_class": card.cycle_class,
            "members_summarized": len(inputs.members),
            "few_shot_cases": [c.case_id for c in inputs.cases],
            "warnings": list(inputs.warnings),
        },
    }
    return thesis, gate, conf


# ---------------------------------------------------------------- contested 집계


def _round_status(round_dir: Path) -> dict[str, str]:
    """한 라운드 디렉터리의 테마 → `gate_result.status` (문자열화). 깨진 파일은 빼고 로그로."""
    out: dict[str, str] = {}
    for p in theses_in(round_dir):
        try:
            obj = read_thesis_yaml(p)
        except Exception:  # 집계는 한 파일 때문에 멈추지 않는다
            log.warning("contested 집계: %s 를 읽지 못함", p)
            continue
        out[theme_of(p)] = str(gate_status(obj))
    return out


def count_contested(
    theses_root: Path, asof: str, current_theme: str, current_status: str
) -> ContestedCount:
    """이번 라운드(`asof` 디렉터리)의 contested 수 + 직전 라운드에서 넘어온 미해소 건수."""
    cc = ContestedCount()
    round_status = _round_status(theses_root / asof)
    round_status[current_theme] = current_status
    cc.round_themes = sorted(t for t, s in round_status.items() if s == "contested")
    cc.round_contested = len(cc.round_themes)
    prev_dirs = (
        sorted(p for p in theses_root.glob("*") if p.is_dir() and p.name < asof)
        if theses_root.exists()
        else []
    )
    if prev_dirs:
        prev_status = _round_status(prev_dirs[-1])
        cc.carried_over_themes = sorted(
            t
            for t, s in prev_status.items()
            if s == "contested" and round_status.get(t) in (None, "contested")
        )
        cc.carried_over = len(cc.carried_over_themes)
    return cc


# ---------------------------------------------------------------- 리포트


def render_report(
    inputs: ResearchInputs,
    thesis: dict[str, Any],
    gate: GateResult,
    conf: ConfidenceResult,
    val: ValidationResult,
    diff: dict[str, Any],
    cc: ContestedCount,
    ledger: CostLedger,
    provider_name: str,
) -> str:
    L: list[str] = []
    a1 = inputs.scorecard.axis1
    L.append(f"# L3 리서치 — {inputs.theme_name} (`{inputs.theme_id}`) · {thesis['generated_at']}")
    L.append("")
    L.append(
        f"provider: **{provider_name}** · 스캔: `{inputs.scan_dir}` · 순위 {inputs.scorecard.rank} "
        f"· cycle_class {inputs.scorecard.cycle_class}"
    )
    if provider_name in ("mock", "fixture"):
        L.append("> **합성/녹화 산출물** — 실제 리서치가 아니다. 실행 경로 검증용.")
    L.append("")
    L.append(
        f"## 게이트: **{gate.status}** · 포트 편입 {'가능' if gate.portfolio_eligible else '불가'} "
        f"· cycle_confidence **{conf.value}**"
    )
    L.append(f"- 규칙: {gate.rule}")
    L.append(f"- 사유: {gate.reason}")
    if gate.path:
        L.append(
            f"- 기각 경로: `{gate.path}` → `rejections-pending.yaml` 에 행 추가 (대장 적재는 M8)"
        )
    for n in gate.notes:
        L.append(f"- {n}")
    if gate.status == "contested":
        L.append(
            f"- referee_ruling: {gate.referee_ruling} (근거 {list(gate.referee_evidence_refs)})"
        )
    L.append("")
    L.append("### 확신도 산출 (04 §4 기계 적용 — 자유 조정 없음)")
    L.append(f"| 항 | 값 |\n|---|---|\n| base | {CONF_BASE} |")
    for k, v in conf.terms.items():
        L.append(f"| {k} | {v:+.2f} |")
    L.append(f"| 합 (클립 전) | {conf.raw} |")
    if conf.cap is not None:
        L.append(f"| 상한 | {conf.cap} |")
    L.append(f"| **cycle_confidence** | **{conf.value}** |")
    for n in conf.notes:
        L.append(f"- {n}")
    L.append("")
    L.append("### 5축 판정")
    L.append("| 축 | 판정 | 증거 | 비고 |\n|---|---|---|---|")
    for a, ax in thesis["value_trap_axes"].items():
        L.append(
            f"| {a} | **{ax['verdict']}** | {ax.get('evidence_refs')} | "
            f"{str(ax.get('note', ''))[:120]} |"
        )
    L.append("")
    L.append("### 축 1 (L1 계산 — 재판정 안 함)")
    L.append(
        f"- axis1_status `{a1.axis1_status}` · available {a1.available} · source "
        f"{a1.unit_series_source} · **axis1_contested {a1.contested}**"
    )
    L.append(
        f"- pre_ss {a1.verdict_pre_ss} / post_ss {a1.verdict_post_ss} · cagr10 {a1.unit_cagr_10y} "
        f"· median {a1.unit_cagr_10y_median} · cagr5 {a1.unit_cagr_5y} · sign_split {a1.sign_split}"
    )
    L.append(
        f"- ss_n {a1.ss_n} · ss_coverage {a1.ss_coverage} · ma_flag {a1.ma_flag} · exit_count "
        f"{a1.exit_count}"
    )
    L.append("")
    L.append("## 논지")
    L.append(f"**claim**: {thesis['claim']}\n")
    L.append(f"**mechanism**: {thesis['mechanism']}\n")
    L.append(f"**horizon_months**: {thesis['horizon_months']}\n")
    L.append("**triggers**")
    for t in thesis["triggers"]:
        L.append(f"- {t['observable']} — {t['source']} · by {t['by']}")
    L.append("\n**invalidations**")
    for t in thesis["invalidations"]:
        L.append(f"- {t['observable']} — {t['source']} · action `{t['action']}`")
    L.append("\n**key_uncertainties**")
    for k in thesis["key_uncertainties"]:
        L.append(f"- {k}")
    L.append("")
    L.append("## bear_case (원문 보존 — 요약하지 않음)")
    L.append("> " + str(thesis["bear_case"]).replace("\n", "\n> "))
    L.append(f"\n컨센서스 시점(bear): {thesis.get('consensus_since', '')}")
    L.append(f"\nreferee 의 반박 정리: {thesis.get('bear_rebuttal', '')}")
    L.append("")
    L.append("## 증거")
    L.append("| id | role | reliability | date | claim | url |\n|---|---|---|---|---|---|")
    stale = {
        w.split("]")[0].split("[")[-1] for w in val.warnings if w.startswith("W_EVIDENCE_STALE")
    }
    for e in thesis["evidence"]:
        flag = " ⚠12M+" if str(e["id"]) in stale else ""
        L.append(
            f"| {e['id']}{flag} | {e.get('role', '')} | {e['reliability']} | {e['date']} | "
            f"{str(e['claim'])[:90]} | {e['source_url']} |"
        )
    L.append("")
    L.append("## 검증")
    L.append(f"- errors: {len(val.errors)} · warnings: {len(val.warnings)}")
    for w in val.warnings:
        L.append(f"  - ⚠ {w}")
    L.append("")
    L.append("## 재실행 diff (논지 표류 추적)")
    if not diff.get("has_prior"):
        L.append("- 이전 thesis 없음 — 첫 실행")
    else:
        L.append(f"- 이전: {thesis.get('supersedes')} ({diff.get('prior_generated_at')})")
        L.append(f"- 바뀐 필드: {diff.get('changed')} · 유지: {diff.get('unchanged')}")
        for f in diff.get("changed", []):
            L.append(f"  - {f}: {json.dumps(diff.get(f), ensure_ascii=False, default=str)[:400]}")
        if diff.get("drift_suspect"):
            L.append(f"- **{diff['drift_suspect']}**")
    L.append("")
    L.append("## contested 집계 (05 §6 — 보류가 쌓이는 것이 보이게)")
    L.append(f"- 이번 라운드 contested: {cc.round_contested} {cc.round_themes}")
    L.append(f"- 직전 라운드에서 넘어온 미해소: {cc.carried_over} {cc.carried_over_themes}")
    L.append("")
    L.append("## 비용 (05 §5 — 역할당 검색 예산 15)")
    L.append(
        "| role | model | calls | in_tok | out_tok | searches / budget |\n|---|---|---|---|---|---|"
    )
    for r in ledger.rows():
        L.append(
            f"| {r['role']} | {r['model']} | {r['calls']} | {r['input_tokens']} | "
            f"{r['output_tokens']} | {r['search_queries']} / {r['search_budget']} |"
        )
    usd = ledger.estimated_usd()
    L.append(
        f"- 추정 비용: {'—' if usd is None else f'${usd:.3f}'} (가격표 기준 추정, 캐시 미반영)"
    )
    L.append("")
    if inputs.warnings:
        L.append("## 입력 경고 (CLAUDE.md §2 — 빈 입력은 보고한다)")
        for w in inputs.warnings:
            L.append(f"- {w}")
        L.append("")
    L.append(
        "이 문서는 측정값과 명시된 가정이다. 투자 조언이 아니며 집행은 사람이 한다. 종목은 L4 가 "
        "고른다."
    )
    return "\n".join(L)


# ---------------------------------------------------------------- 저장


def write_outputs(
    theses_root: Path, inputs: ResearchInputs, res: ResearchResult
) -> tuple[Path, Path]:
    """`state/theses/<asof>/` 에 thesis · 리포트 · contested 집계, 기각이면
    `rejections-pending.yaml` 행(테마당 한 줄 — 같은 테마 재실행은 덮어쓴다). 반환 (out_dir,
    thesis_path)."""
    out_dir = theses_root / res.asof
    tp = dump_thesis_yaml(out_dir / thesis_filename(res.theme_id), res.thesis)
    cc = res.contested
    # 라운드 디렉터리는 테마마다 프로세스가 따로 붙을 수 있다 (`msa research` 를 여러 테마로
    # 동시에 돌리는 경우). `rejections-pending.yaml` 은 읽고→고쳐→쓰기라 잠금이 없으면
    # 늦게 끝난 테마가 먼저 끝난 테마의 기각 행을 지운다. `contested.json` 은 라운드 집계라
    # 마지막에 쓴 프로세스의 관점이 남는다 — 찢어지지는 않지만 최신이 아닐 수 있다.
    with dir_lock(out_dir):
        _write_round_files(out_dir, inputs, res, cc)
    return out_dir, tp


def _write_round_files(out_dir: Path, inputs: ResearchInputs, res: ResearchResult, cc: Any) -> None:
    write_snapshot(
        out_dir,
        texts={f"{res.theme_id}.report.md": res.report_md},
        jsons={
            "contested.json": {
                "asof": res.asof,
                "round_contested": cc.round_contested,
                "round_themes": cc.round_themes,
                "carried_over": cc.carried_over,
                "carried_over_themes": cc.carried_over_themes,
            }
        },
    )
    if res.gate.status == "rejected":
        rp = out_dir / "rejections-pending.yaml"
        rows: list[dict[str, Any]] = []
        if rp.exists():
            loaded = yaml.safe_load(rp.read_text(encoding="utf-8")) or []
            rows = [r for r in loaded if r.get("theme") != res.theme_id]
        rows.append(
            rejection_row(
                theme_id=res.theme_id,
                rejected_at=res.decision_date or res.asof,
                gate=res.gate,
                cycle_confidence=res.confidence.value,
                scoreboard_rank=inputs.scorecard.rank,
                scan_dir=inputs.scan_dir,
            )
        )
        dump_yaml(rp, rows)


# ---------------------------------------------------------------- 진입점


def run_research(
    inputs: ResearchInputs,
    provider: LLMProvider,
    *,
    theses_root: Path,
    write: bool = True,
    generated_at: str | None = None,
) -> ResearchResult:
    """전체 파이프라인. 스키마 미달이면 `ThesisRejected` — 저장하지 않는다. 게이트 기각은 "
    "저장한다."""
    ledger = CostLedger()
    # 판정일과 데이터 스냅샷일은 다른 물건이다 (2026-08-25). `asof` 는 가격·재무가 끊긴 날이고,
    # 판정은 오늘 내린다. 증거가 "미래" 인지는 **판정일**로 재야 한다 — 스냅샷일로 재면
    # 스토어가 뒤처진 만큼 실재하는 문서가 미래로 오판된다 (6테마 중 6테마에서 발생).
    gen = generated_at or inputs.decision_date or inputs.asof
    if gen < inputs.asof:
        raise ValueError(
            f"판정일 {gen} 이 데이터 스냅샷일 {inputs.asof} 보다 앞선다 — "
            "존재하지 않는 데이터로 판정할 수 없다"
        )
    lag = _days_between(inputs.asof, gen)
    stale_note: list[str] = []
    if lag is not None and lag > DATA_LAG_WARN_DAYS:
        # §2 — 오래된 가격으로 판단하고 있다는 사실이 보이지 않으면 나중에 원인을 못 찾는다.
        stale_note.append(
            f"가격·재무 스냅샷이 판정일보다 {lag}일 뒤처져 있다 "
            f"({inputs.asof} → {gen}, 경고 기준 {DATA_LAG_WARN_DAYS}일). "
            "증거는 판정일 기준으로 검증되지만 스코어카드는 스냅샷 시점 값이다"
        )
    roles, evidence = run_roles(inputs, provider, ledger)
    thesis, gate, conf = build_thesis(inputs, roles, evidence, generated_at=gen)
    val = validate_thesis(
        thesis,
        asof=gen,
        member_tickers=inputs.member_tickers,
        member_names=tuple(m.name for m in inputs.members if m.name),
        bear_case_original=str(roles.bear["bear_case"]),
    )
    if not val.ok:
        raise ThesisRejected(val)
    diff = thesis_diff(inputs.prior_thesis, thesis)
    cc = count_contested(theses_root, inputs.asof, inputs.theme_id, gate.status)
    report = render_report(
        inputs,
        thesis,
        gate,
        conf,
        val,
        diff,
        cc,
        ledger,
        getattr(provider, "name", type(provider).__name__),
    )
    res = ResearchResult(
        theme_id=inputs.theme_id,
        asof=inputs.asof,
        decision_date=gen,
        thesis=thesis,
        validation=val,
        gate=gate,
        confidence=conf,
        diff=diff,
        contested=cc,
        ledger=ledger,
        report_md=report,
        roles=roles,
        warnings=stale_note + list(inputs.warnings) + list(val.warnings),
    )
    if write:
        res.out_dir, res.thesis_path = write_outputs(theses_root, inputs, res)
    return res
