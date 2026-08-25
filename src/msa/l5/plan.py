"""매매계획서 렌더러 — `docs/07-portfolio.md` §6 형식.

문서의 예시 블록을 따르되, 거기 없고 M6 완료 기준이 요구하는 것을 덧붙인다:
확신도 압축 λ · ENB 와 `p₁·p₂·p₃`(눈금 없음) · MDD 두 방식의 사용률과 어느 쪽이 구속했는지 ·
`L_i` 의 두 항과 구속 항(또는 못 만든 사유) · `c` 의 산출 주체(사람/referee) · 축 1 적용 가능 여부 ·
완화 단계. 성과 수치(기대수익·승률)는 어디에도 없다 (`CLAUDE.md` §7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from msa import fmt
from msa.l5.ladders import RUNNER_MA_WEEKS, TIER2_RULE_CAPITAL, PositionPlan
from msa.l5.risk import ScenarioLoss

if TYPE_CHECKING:
    from msa.l5.run import PortfolioResult, ThemeRow

RULE = "─" * 78


def _pct(x: float | None, nd: int = 1) -> str:
    """비율 → `12.3%` (부호 없음), 없으면 `—`."""
    return fmt.pct(x, sign=False, na="—", nd=nd)


def _px(x: float | None) -> str:
    return "$—" if x is None else f"${x:,.2f}"


def _src_label(s: str) -> str:
    return {"human": "사람", "referee": "referee"}.get(s, s)


def _loss_line(sl: ScenarioLoss) -> str:
    if sl.computable:
        assert sl.hist_term is not None and sl.case_raw is not None and sl.case_term is not None
        which = "과거 국면이 구속" if sl.binding == "hist" else "사망 사례 × 0.5 가 구속"
        return (
            f"  L = {sl.value:.2f}  (과거 유사 국면 {sl.hist_term:.2f} / 사망 사례 "
            f"{sl.case_raw:.2f} × {sl.case_factor} = {sl.case_term:.2f} [{sl.case_id}] → {which})"
        )
    parts: list[str] = []
    parts.append("과거 유사 국면 " + ("—" if sl.hist_term is None else f"{sl.hist_term:.2f}"))
    parts.append(
        "사망 사례 "
        + (
            "—"
            if sl.case_term is None
            else f"{sl.case_raw:.2f} × {sl.case_factor} = {sl.case_term:.2f} [{sl.case_id}]"
        )
    )
    return (
        "  L = 계산 불가  ("
        + " / ".join(parts)
        + ") → C1-(ii) 에서 빠짐 — "
        + "; ".join(sl.reasons)
    )


def _tier2_budget_text(res: PortfolioResult) -> str:
    """`docs/07` §4 의 예산 역산 — 진단에만 있던 것을 계획서에도 싣는다.

    Tier-2 −35% 가 **탐색값이 아니라 예산에서 역산한 값**이라는 사실이 계획서에서 읽혀야 한다.
    """
    b = res.extra.get("tier2_budget")
    if not isinstance(b, dict):
        return "—"
    return (
        f"테마 상한 {float(b['theme_cap']):.0%} × Tier2 {float(b['tier2_from_avg']):.0%} = "
        f"총자본 {float(b['loss_contribution']) * 100:.2f}% = MDD 예산 "
        f"{float(b['mdd_budget']):.0%} 의 {float(b['share_of_budget']) * 100:.1f}% (docs/07 §4)"
    )


def _c4_text(res: PortfolioResult) -> str:
    """C4 유동성 — **걸렸는지 아닌지**를 계획서 본문에 적는다 (`docs/07` §2.4 C4).

    자본(`--capital`) 이 없으면 `w·Capital ≤ 0.10·ADV20` 은 식을 세울 수 없어 **한 번도 걸리지
    않는다.** 문서가 "핵심 제약" 이라 부른 것이 무효인 채로 계획서가 나가면 안 되므로, 경고란
    뿐 아니라 머리에도 그 사실을 적는다. 여기서 자본 기본값을 **정하지 않는다** (`CLAUDE.md` §1).
    """
    cap = res.extra.get("capital_usd")
    if not isinstance(cap, int | float):
        return "미적용 — 자본(--capital) 미지정 → w·Capital ≤ 10%·ADV20 을 걸지 않았다"
    skipped = res.solution.c4_skipped if res.solution is not None else ()
    txt = f"적용 — 자본 ${float(cap):,.0f} · w·Capital ≤ 10%·ADV20"
    if skipped:
        txt += f" (ADV 없어 제외한 종목 {list(skipped)})"
    return txt


def _tier2_text(p: PositionPlan) -> str:
    """Tier-2 한 줄 — **적용된 규칙**의 가격과 하락률을 짝으로 찍는다 (`docs/07` §4).

    두 규칙 중 먼저 오는 쪽이 유효 스탑이므로, 진 규칙은 뒤에 참고로만 남긴다.
    가격과 % 가 서로 다른 규칙을 가리키는 일이 없어야 한다 — 스탑은 틀리면 안 되는 자리다.
    """
    eff_pct = f"초기가 −{abs(p.tier2_effective_vs_initial) * 100:.1f}%"
    if p.tier2_rule == TIER2_RULE_CAPITAL:
        other = (
            f"평단 −35% 는 {_px(p.tier2_price)} = 초기가 "
            f"−{abs(p.tier2_vs_initial) * 100:.1f}% 로 더 멀다"
        )
        return f"{_px(p.tier2_effective_price)} (자본 8% 규칙이 먼저 = {eff_pct}; {other})"
    return f"{_px(p.tier2_effective_price)} (평단 −35% = {eff_pct})"


def _position_block(p: PositionPlan) -> list[str]:
    role = {
        "eligible": "적격",
        "anchor": "앵커",
        "torque": "토크",
        "royalty": "로열티",
        "midstream": "미드스트림",
        "etf": "ETF",
    }.get(p.role, p.role)
    f = p.ladder.fractions
    lw = p.leg_weights
    lines = [
        f"  {p.ticker:<6} {role:<5} 목표 {_pct(p.target_weight)}   사다리 "
        f"{_pct(lw[0])} / {_pct(lw[1])} / {_pct(lw[2])}  ({f[0]:.0%}/{f[1]:.0%}/{f[2]:.0%}"
        + (", 1단 25+25 분할" if p.split_first_leg else "")
        + ")"
    ]
    lines.append(
        f"         진입 {_px(p.entry_price)}   2단 {_px(p.leg_prices[1])}"
        f"(−{(1 - p.ladder.leg_prices[1]) * 100:.0f}%)   3단 {_px(p.leg_prices[2])}"
        f"(−{(1 - p.ladder.leg_prices[2]) * 100:.0f}%)"
        "   — 2·3단은 무효화 0건 AND 트리거 충족 시에만"
        "\n           **1단은 트리거를 요구하지 않는다** (docs/07 §3 — 잊혀진 테마에 먼저"
        " 들어가는 설계). 논지의 '진입 조건' 이 아직 관측되지 않았다고 적혀 있으면 1단도"
        " 보류할지는 **사람이 정한다** (docs/19)."
    )
    # 무효화마다 **조치가 다르다.** 한 줄에 이어 붙이면 전부 전량 청산으로 읽힌다
    # (2026-08-25: 11건 중 9건이 청산이 아닌 조치였다).
    if p.tier1_invalidations:
        lines.append("         Tier1  무효화 조건 — 조치는 조건마다 다르다:")
        lines += [f"           · {x}" for x in p.tier1_invalidations]
    else:
        lines.append("         Tier1  (없음 — 불가)")
    lines.append(
        f"         Tier2  {_tier2_text(p)}   시간스탑  {p.time_stop} "
        f"(horizon {p.horizon_months[1]}M, 트리거 0건일 때)"
    )
    tp1 = f"TP1 {_px(p.tp1_price)} (+2R)"
    if p.tp1_p50_price is not None:
        tp1 += f" 또는 {_px(p.tp1_p50_price)} (P50)"
    tp2 = "TP2 "
    if p.tp2_p75_price is not None:
        tp2 += f"{_px(p.tp2_p75_price)} (P75)"
    if p.tp2_r_price is not None:
        tp2 += (
            " 또는 " if p.tp2_p75_price is not None else ""
        ) + f"{_px(p.tp2_r_price)} (고점 50% 회복)"
    if p.tp2_p75_price is None and p.tp2_r_price is None:
        tp2 += "$— (P75·직전 고점 입력 없음)"
    lines.append(f"         {tp1}  {tp2}  러너 트레일 {p.runner_trail:.0%} / {RUNNER_MA_WEEKS}주선")
    if p.triggers:
        lines.append(f"         트리거  {' / '.join(p.triggers)}")
    return lines


def _theme_header(r: ThemeRow) -> str:
    ct = "" if r.c_tilde is None else f", c̃={r.c_tilde:.2f}"
    ax = "축1 가능" if r.axis1_declared else "축1 불가"
    if r.axis1_available is False and r.axis1_declared:
        ax += "(thesis: false)"
    head = f"{r.theme}  (c={r.c:.2f} [{_src_label(r.c_source)}]{ct}, {ax})"
    if not r.eligible:
        return f"{head:<60} 제외 — {r.excluded_reason}"
    return f"{head:<60} 테마 {_pct(r.weight)}"


def render_plan(res: PortfolioResult) -> str:
    s = res.solution
    out: list[str] = []
    out.append(RULE)
    out.append(f"포트폴리오 계획 · {res.asof} · 자본 대비")
    if s is not None:
        used = max(s.mdd_vol, s.mdd_scenario or 0.0)
        enb_s = (
            f"ENB: {res.enb.enb:.1f}  (p₁ {res.enb.p_top3[0]:.2f} · p₂ {res.enb.p_top3[1]:.2f} · "
            f"p₃ {res.enb.p_top3[2]:.2f})"
            if res.enb
            else "ENB: —"
        )
        out.append(f"  MDD 예산 사용률: {_pct(used)} / {_pct(s.budget_used, 0)}      {enb_s}")
        sc = "—" if s.mdd_scenario is None else _pct(s.mdd_scenario)
        bind = {
            "vol": "변동성(i) 구속",
            "scenario": "시나리오(ii) 구속",
            "both": "둘 다 경계",
            "none": "둘 다 여유 (다른 상한이 구속)",
        }[s.mdd_binding]
        out.append(
            f"  MDD 방식: 변동성 k·σ_p = {_pct(s.mdd_vol)} (k={res.k}) · 시나리오 Σw·L = {sc}"
            f"  → {bind}"
        )
        leg1 = sum(p.leg_weights[0] for p in res.positions)
        # 라벨 부재와 배분 결정은 다르다 — L4 가 role 을 안 붙이면 비율을 단언하지 않는다.
        anc = (
            "라벨 없음 (L4 미지정)"
            if res.anchor_share is None
            else f"{res.anchor_share * 100:.0f} : {(1 - res.anchor_share) * 100:.0f}"
        )
        out.append(
            f"  앵커 : 토크 = {anc:<16}        현금 {_pct(s.cash, 0)}  "
            f"(총투자 {_pct(s.gross, 0)}, 1단 실투입 {_pct(leg1, 0)})"
        )
        out.append(f"  C4 유동성: {_c4_text(res)}")
        out.append(f"  Tier-2 예산 역산: {_tier2_budget_text(res)}")
        out.append(f"  μ 방식: {res.mu_method:<16}        확신도 압축 λ = {res.lam}")
        relax = "없음" if not s.relaxed else ", ".join(s.relaxed)
        out.append(f"  솔버: {s.solver} ({s.status}) · 완화: {relax}")
    else:
        out.append("  포트폴리오 없음 — 편입 가능한 후보가 0개")
        out.append(f"  μ 방식: {res.mu_method:<16}        확신도 압축 λ = {res.lam}")
    if res.cov is not None:
        out.append(
            f"  Σ: {res.cov.source} · 룩백 {res.cov.lookback_months} · "
            f"상수상관 축소 δ={res.cov.shrink_delta} · "
            f"{res.cov.window[0]}~{res.cov.window[1]}"
        )
    out.append(RULE)
    for r in res.theme_rows:
        out.append(_theme_header(r))
        out.append(_loss_line(r.scenario))
        if r.eligible:
            for p in res.positions:
                if p.theme == r.theme:
                    out.extend(_position_block(p))
        out.append(RULE)
    # 축 1 목록
    a_yes = [r.theme for r in res.theme_rows if r.axis1_declared]
    a_no = [r.theme for r in res.theme_rows if not r.axis1_declared]
    out.append(
        "축 1 (물량 추세) 적용 가능 여부 — physical_ref 기준 "
        "(docs/04 축 1 · docs/11 '첫 실전 사용 시점')"
    )
    out.append(f"  가능 ({len(a_yes)}): {', '.join(a_yes) if a_yes else '없음'}")
    out.append(
        f"  불가 ({len(a_no)}): {', '.join(a_no) if a_no else '없음'}"
        "  → 축 3 으로 무게 이전, M6 운영 범위 밖"
    )
    out.append(
        f"  (유니버스 전체: {res.axis1_universe[0]} / {res.axis1_universe[1]} 테마가 "
        "physical_ref 보유)"
    )
    out.append(RULE)
    out.append("확신도 출처 (c 를 누가 만들었는가 — docs/11 M6)")
    for r in res.theme_rows:
        out.append(f"  {r.theme:<24} c={r.c:.2f}  {_src_label(r.c_source)}")
    out.append(RULE)
    out.append("경고")
    if res.warnings:
        out.extend(f"  · {w}" for w in res.warnings)
    else:
        out.append("  · 없음")
    if res.enb is not None:
        out.append(
            f"  · ENB {res.enb.enb:.2f} · p₁ {res.enb.p_top3[0]:.2f} — 눈금 없음: "
            "한 팩터가 리스크의 "
            f"{res.enb.p_top3[0] * 100:.0f}% 를 진다는 뜻 그대로 읽는다 (docs/07 §2.4 (b))"
        )
    if s is not None:
        for t, w in sorted(s.class_weights.items(), key=lambda kv: -kv[1]):
            out.append(f"  · cycle_class {t} 합계 {_pct(w)} (상한 55%)")
        caps = res.extra.get("cluster_caps")
        caps_map = caps if isinstance(caps, dict) else {}
        for cl, w in sorted(s.cluster_weights.items(), key=lambda kv: -kv[1]):
            cap = f" (요청 상한 {_pct(float(caps_map[cl]))})" if cl in caps_map else ""
            out.append(f"  · 클러스터 {cl} 합계 {_pct(w)}{cap}")
    out.append("  · 이 문서는 측정값과 명시된 가정이다. 주문은 사람이 낸다 (CLAUDE.md §8)")
    out.append(RULE)
    return "\n".join(out) + "\n"
