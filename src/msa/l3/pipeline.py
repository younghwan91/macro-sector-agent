"""`msa research <theme>` 오케스트레이션.

```
inputs ─┬─ supply_analyst ──┐
        ├─ catalyst_analyst ┤   (스코어 포함 컨텍스트)
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from msa.l3.contracts import ResearchInputs
from msa.l3.gates import (
    AxisVerdicts,
    ConfidenceInputs,
    ConfidenceResult,
    ContestedCount,
    GateResult,
    apply_gates,
    cycle_confidence,
    rejection_row,
)
from msa.l3.providers import (
    CompletionRequest,
    CostLedger,
    LLMProvider,
    SearchBudget,
)
from msa.l3.roles import (
    bear_request,
    catalyst_request,
    check_role_output,
    referee_request,
    supply_request,
)
from msa.l3.schema import ThesisRejected, ValidationResult, validate_thesis

log = logging.getLogger(__name__)

EVIDENCE_ROLE_ORDER = ("supply_analyst", "catalyst_analyst", "bear")


@dataclass
class RoleOutputs:
    supply: dict[str, Any]
    catalyst: dict[str, Any]
    bear: dict[str, Any]
    referee: dict[str, Any]
    requests: dict[str, CompletionRequest] = field(default_factory=dict)


@dataclass
class ResearchResult:
    theme_id: str
    asof: str
    thesis: dict[str, Any]
    validation: ValidationResult
    gate: GateResult
    confidence: ConfidenceResult
    diff: dict[str, Any]
    contested: ContestedCount
    ledger: CostLedger
    report_md: str
    out_dir: Path | None
    thesis_path: Path | None
    roles: RoleOutputs
    warnings: list[str]


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


# ---------------------------------------------------------------- 역할 실행


def run_roles(
    inputs: ResearchInputs,
    provider: LLMProvider,
    ledger: CostLedger,
    *,
    budget: SearchBudget | None = None,
) -> tuple[RoleOutputs, list[dict[str, Any]]]:
    reqs: dict[str, CompletionRequest] = {}

    def call(req: CompletionRequest) -> dict[str, Any]:
        reqs[req.role] = req
        res = provider.complete(req)
        ledger.record(req.role, res)
        if budget is not None and res.usage.search_queries:
            budget.charge(req.role, res.usage.search_queries)
        obj = res.json()
        check_role_output(req.role, obj)
        return obj

    supply = call(supply_request(inputs))
    catalyst = call(catalyst_request(inputs))
    bear = call(bear_request(inputs.bear_view()))  # 독립 컨텍스트 — 스코어 없음
    merged, remap = merge_evidence(
        {"supply_analyst": supply, "catalyst_analyst": catalyst, "bear": bear}
    )
    supply_g = _remap_ids(supply, remap["supply_analyst"])
    catalyst_g = _remap_ids(catalyst, remap["catalyst_analyst"])
    bear_g = _remap_ids(bear, remap["bear"])
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
    return RoleOutputs(
        supply=supply_g, catalyst=catalyst_g, bear=bear_g, referee=referee, requests=reqs
    ), merged


# ---------------------------------------------------------------- thesis 조립


def _axis_block(ax: dict[str, Any], extra_drop: tuple[str, ...] = ()) -> dict[str, Any]:
    out = {
        "verdict": ax.get("verdict"),
        "evidence_refs": [int(x) for x in ax.get("evidence_refs", [])],
    }
    if ax.get("note"):
        out["note"] = ax["note"]
    for k, v in ax.items():
        if k not in ("verdict", "evidence_refs", "note", *extra_drop):
            out[k] = v
    return out


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
    axes_in = ref["axes"]
    ev_ids = {int(e["id"]) for e in evidence}

    # 축 1 — L1 값 그대로. 증거: referee 가 가리킨 것 + (가용하면) 스캔 자체를 증거로 명시
    ud_refs = [int(x) for x in axes_in["unit_demand"].get("evidence_refs", [])]
    if a1.available:
        scan_ev_id = max(ev_ids, default=0) + 1
        evidence.append(
            {
                "id": scan_ev_id,
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
        )
        ev_ids.add(scan_ev_id)
        ud_refs.append(scan_ev_id)
    unit_demand: dict[str, Any] = {
        "verdict": a1.verdict,
        "evidence_refs": ud_refs,
        "axis1_available": a1.available,
        "unit_series_source": a1.unit_series_source,
    }
    if axes_in["unit_demand"].get("note"):
        unit_demand["note"] = axes_in["unit_demand"]["note"]
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

    cc = axes_in["cost_curve"]
    tr = axes_in["terminal_risk"]
    verdicts = AxisVerdicts(
        unit_demand=a1.verdict,
        capital_cycle=str(axes_in["capital_cycle"]["verdict"]),
        substitution=str(axes_in["substitution"]["verdict"]),
        cost_curve=str(cc["verdict"]),
        terminal_risk=str(tr["verdict"]),
    )
    card = inputs.scorecard
    conf = cycle_confidence(
        ConfidenceInputs(
            verdicts=verdicts,
            capex_to_da_qtrs_below1=card.capex_to_da_qtrs_below1,
            axis4_strong_cycle=bool(cc.get("strong_cycle", False)),
            axis5_severe=bool(tr.get("severe", False)),
            tailwind=inputs.macro.tailwind if inputs.macro else None,
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
            "cost_curve": _axis_block(cc),
            "terminal_risk": _axis_block(tr),
        },
        "gate_result": gate.as_dict(),
        "cycle_confidence": conf.value,
        "cycle_confidence_terms": {
            "base": 0.5,
            **conf.terms,
            **({"cap": conf.cap} if conf.cap is not None else {}),
        },
        "cycle_confidence_by": "referee-pipeline (04 §4 기계 적용; 09 §2 — 산출 주체 표기)",
        "evidence": [{k: v for k, v in e.items()} for e in evidence],
        "inputs": {
            "scan_dir": inputs.scan_dir,
            "scoreboard_rank": card.rank,
            "cycle_class": card.cycle_class,
            "members_summarized": len(inputs.members),
            "macro_tailwind": inputs.macro.tailwind if inputs.macro else None,
            "few_shot_cases": [c.case_id for c in inputs.cases],
            "warnings": list(inputs.warnings),
        },
    }
    return thesis, gate, conf


# ---------------------------------------------------------------- 표류 diff


DIFF_FIELDS = (
    "claim",
    "mechanism",
    "horizon_months",
    "triggers",
    "invalidations",
    "cycle_confidence",
    "bear_case",
)


def thesis_diff(prior: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """이전 thesis 와의 필드별 차이 — 논지 표류 추적 (`docs/05` §6, `docs/09` §2)."""
    if prior is None:
        return {"has_prior": False}
    out: dict[str, Any] = {
        "has_prior": True,
        "prior_generated_at": str(prior.get("generated_at")),
        "changed": [],
        "unchanged": [],
    }
    for f in DIFF_FIELDS:
        a, b = prior.get(f), current.get(f)
        if f in ("triggers", "invalidations"):
            a = [_obs(x) for x in (a or [])]
            b = [_obs(x) for x in (b or [])]
            added = [x for x in b if x not in a]
            removed = [x for x in a if x not in b]
            if added or removed:
                out["changed"].append(f)
                out[f] = {"added": added, "removed": removed}
            else:
                out["unchanged"].append(f)
        elif a != b:
            out["changed"].append(f)
            out[f] = {"before": a, "after": b}
        else:
            out["unchanged"].append(f)
    pa = (prior.get("gate_result") or {}).get("axis_verdicts") or {}
    ca = (current.get("gate_result") or {}).get("axis_verdicts") or {}
    ax_changed = {
        k: {"before": pa.get(k), "after": ca.get(k)} for k in ca if pa.get(k) != ca.get(k)
    }
    if ax_changed:
        out["changed"].append("axis_verdicts")
        out["axis_verdicts"] = ax_changed
    ps = (prior.get("gate_result") or {}).get("status")
    cs = (current.get("gate_result") or {}).get("status")
    if ps != cs:
        out["changed"].append("gate_status")
        out["gate_status"] = {"before": ps, "after": cs}
    # 무효화 회피 의심: 이전 무효화 조건이 사라졌는데 논지는 유지
    inv = out.get("invalidations", {})
    if isinstance(inv, dict) and inv.get("removed") and "claim" not in out["changed"]:
        out["drift_suspect"] = (
            "이전 invalidations 가 제거됐는데 claim 은 그대로 — 무효화 회피 의심 (05 §6)"
        )
    return out


def _obs(x: Any) -> str:
    return str(x.get("observable", x)) if isinstance(x, dict) else str(x)


# ---------------------------------------------------------------- contested 집계


def count_contested(
    theses_root: Path, asof: str, current_theme: str, current_status: str
) -> ContestedCount:
    """이번 라운드(`asof` 디렉터리)의 contested 수 + 직전 라운드에서 넘어온 미해소 건수."""
    cc = ContestedCount()
    this_dir = theses_root / asof
    round_status: dict[str, str] = {}
    if this_dir.exists():
        for p in this_dir.glob("*.thesis.yaml"):
            t = p.name[: -len(".thesis.yaml")]
            try:
                obj = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                round_status[t] = str((obj.get("gate_result") or {}).get("status"))
            except Exception:  # 깨진 파일은 집계에서 빼되 로그로 남긴다
                log.warning("contested 집계: %s 를 읽지 못함", p)
    round_status[current_theme] = current_status
    cc.round_themes = sorted(t for t, s in round_status.items() if s == "contested")
    cc.round_contested = len(cc.round_themes)
    prev_dirs = (
        sorted(p for p in theses_root.glob("*") if p.is_dir() and p.name < asof)
        if theses_root.exists()
        else []
    )
    if prev_dirs:
        prev = prev_dirs[-1]
        for p in prev.glob("*.thesis.yaml"):
            t = p.name[: -len(".thesis.yaml")]
            try:
                obj = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if str(
                (obj.get("gate_result") or {}).get("status")
            ) == "contested" and round_status.get(t) in (None, "contested"):
                cc.carried_over_themes.append(t)
        cc.carried_over_themes.sort()
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
    L.append("| 항 | 값 |\n|---|---|\n| base | 0.5 |")
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
    theses_root: Path,
    asof: str,
    theme_id: str,
    thesis: dict[str, Any],
    report: str,
    gate: GateResult,
    conf: ConfidenceResult,
    cc: ContestedCount,
    scan_dir: str,
    rank: int | None,
) -> tuple[Path, Path]:
    out_dir = theses_root / asof
    out_dir.mkdir(parents=True, exist_ok=True)
    tp = out_dir / f"{theme_id}.thesis.yaml"
    tp.write_text(
        yaml.safe_dump(thesis, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8"
    )
    (out_dir / f"{theme_id}.report.md").write_text(report, encoding="utf-8")
    if gate.status == "rejected":
        rp = out_dir / "rejections-pending.yaml"
        rows: list[dict[str, Any]] = []
        if rp.exists():
            loaded = yaml.safe_load(rp.read_text(encoding="utf-8")) or []
            rows = [r for r in loaded if r.get("theme") != theme_id]
        rows.append(
            rejection_row(
                theme_id=theme_id,
                rejected_at=asof,
                gate=gate,
                cycle_confidence=conf.value,
                scoreboard_rank=rank,
                scan_dir=scan_dir,
            )
        )
        rp.write_text(yaml.safe_dump(rows, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (out_dir / "contested.json").write_text(
        json.dumps(
            {
                "asof": asof,
                "round_contested": cc.round_contested,
                "round_themes": cc.round_themes,
                "carried_over": cc.carried_over,
                "carried_over_themes": cc.carried_over_themes,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return out_dir, tp


# ---------------------------------------------------------------- 진입점


def run_research(
    inputs: ResearchInputs,
    provider: LLMProvider,
    *,
    theses_root: Path,
    write: bool = True,
    generated_at: str | None = None,
    budget: SearchBudget | None = None,
) -> ResearchResult:
    """전체 파이프라인. 스키마 미달이면 `ThesisRejected` — 저장하지 않는다. 게이트 기각은 "
    "저장한다."""
    ledger = CostLedger()
    roles, evidence = run_roles(inputs, provider, ledger, budget=budget)
    gen = generated_at or inputs.asof
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
    cc = count_contested(theses_root, gen, inputs.theme_id, gate.status)
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
    out_dir: Path | None = None
    tp: Path | None = None
    if write:
        out_dir, tp = write_outputs(
            theses_root,
            gen,
            inputs.theme_id,
            thesis,
            report,
            gate,
            conf,
            cc,
            inputs.scan_dir,
            inputs.scorecard.rank,
        )
    return ResearchResult(
        theme_id=inputs.theme_id,
        asof=gen,
        thesis=thesis,
        validation=val,
        gate=gate,
        confidence=conf,
        diff=diff,
        contested=cc,
        ledger=ledger,
        report_md=report,
        out_dir=out_dir,
        thesis_path=tp,
        roles=roles,
        warnings=list(inputs.warnings) + list(val.warnings),
    )
