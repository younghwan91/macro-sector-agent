"""`cycle_confidence` 캘리브레이션 집계 (`docs/10-validation.md` §4 — 정본).

표본 = 저널의 **청산 항목**(`type: exit`). 각 항목의 `cycle_confidence` 와 사후 판정 `o` 로:

```
o = 1    트리거의 과반이 horizon 안에 충족  AND  무효화 0건
o = 0    무효화 발동  OR  시간 스탑 발동 (트리거 0건)
o = 0.5  트리거 일부 충족, horizon 내 미결 → 다음 평가로 이월 (Brier N 에 넣지 않는다)
```

Brier = (1/N) Σ (c − o)². 구간 [0.5,0.6) [0.6,0.7) [0.7,0.8) [0.8,1.0] 별 적중률.
**기울기** = (구간 중앙값 c, 구간 적중률) 점을 **구간 표본 수로 가중한 최소자승 직선**의 기울기 —
문서가 고정한 방식이며 여기서 달리 재지 않는다. λ ≈ clip(1 − slope, 0, 1) 는 **실측 근거**일 뿐,
값의 갱신은 문서화된 근거와 함께 사람이 한다 (`docs/07` §7.2).

N < 20 이면 "결론 없음 (N=…)" 을 출력하고 표본은 나열한다. N ≥ 20 이어도 두 구간 이하에 몰려 있으면
기울기를 내지 않는다 (문서: "N=20 이 두 구간에 몰려 있으면 여전히 결론을 내지 않는다").
출력에는 반드시 **조건부 캘리브레이션** 문장이 붙는다 — 편입 표본만 보고 있다는 사실을 빼면 판별기가
실제보다 잘 맞는 것처럼 보인다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from msa.ops.journal import load_entries

MIN_N = 20
BINS: tuple[tuple[float, float], ...] = ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.0 + 1e-9))
CONDITIONAL_CAVEAT = (
    "이 곡선은 편입 표본의 조건부 캘리브레이션이며 전체 판단의 캘리브레이션이 아니다. "
    "게이트가 걸러낸 저확신 판단은 표본에 없다 — 곡선의 왼쪽 끝은 데이터가 아니라 절단면이다 "
    "(docs/10 §4)."
)


@dataclass(frozen=True)
class Sample:
    theme: str
    date: str
    c: float
    provenance: str  # human | referee
    o: float  # 0 | 0.5 | 1
    triggers_met: int
    triggers_total: int
    invalidations_fired: int
    exit_via: str
    path: str

    @property
    def resolved(self) -> bool:
        return self.o in (0.0, 1.0)


def outcome(
    *, triggers_met: int, triggers_total: int, invalidations_fired: int, exit_via: str
) -> float:
    """docs/10 §4 의 o_j 규칙 — 사전 고정, 사후 해석 금지."""
    if invalidations_fired > 0:
        return 0.0
    if exit_via == "time_stop" and triggers_met == 0:
        return 0.0
    if triggers_total > 0 and triggers_met * 2 > triggers_total:
        return 1.0
    if triggers_met == 0 and exit_via in ("tier2", "tier1"):
        # 트리거 0건 + 자본/논지 스탑 — 무효화는 없었으나 논지는 검증되지 않았다 → 미결
        return 0.5
    return 0.5


def samples_from_journal(jdir: Path) -> list[Sample]:
    out: list[Sample] = []
    for e in load_entries(jdir, "exit"):
        try:
            c = float(e["cycle_confidence"])
            tm, tt, inv = (
                int(e["triggers_met"]),
                int(e["triggers_total"]),
                int(e["invalidations_fired"]),
            )
        except (KeyError, TypeError, ValueError):
            # 불완전한 항목은 write_record 가 막았어야 한다 — 손으로 쓴 파일이면 건너뛴다
            continue
        out.append(
            Sample(
                theme=str(e.get("theme")),
                date=str(e.get("date")),
                c=c,
                provenance=str(e.get("confidence_provenance", "?")),
                o=outcome(
                    triggers_met=tm,
                    triggers_total=tt,
                    invalidations_fired=inv,
                    exit_via=str(e.get("exit_via")),
                ),
                triggers_met=tm,
                triggers_total=tt,
                invalidations_fired=inv,
                exit_via=str(e.get("exit_via")),
                path=str(e.get("_path")),
            )
        )
    return out


@dataclass(frozen=True)
class BinStat:
    lo: float
    hi: float
    n: int
    hit_rate: float | None
    mean_c: float | None


@dataclass
class Calibration:
    label: str
    n: int
    n_unresolved: int
    brier: float | None
    bins: list[BinStat]
    slope: float | None
    lambda_hint: float | None
    conclusive: bool
    reason: str
    samples: list[Sample]


def _bins(samples: list[Sample]) -> list[BinStat]:
    out: list[BinStat] = []
    for lo, hi in BINS:
        xs = [s for s in samples if lo <= s.c < hi]
        if xs:
            out.append(
                BinStat(
                    lo,
                    min(hi, 1.0),
                    len(xs),
                    float(np.mean([s.o for s in xs])),
                    float(np.mean([s.c for s in xs])),
                )
            )
        else:
            out.append(BinStat(lo, min(hi, 1.0), 0, None, None))
    return out


def weighted_slope(bins: list[BinStat]) -> float | None:
    """(구간 중앙값 c, 적중률) 를 구간 n 으로 가중한 최소자승 기울기. 점이 2개 미만이면 None."""
    pts = [
        ((b.lo + min(b.hi, 1.0)) / 2.0, b.hit_rate, b.n)
        for b in bins
        if b.n > 0 and b.hit_rate is not None
    ]
    if len(pts) < 2:
        return None
    x = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    w = np.array([p[2] for p in pts], dtype=float)
    xm = float(np.sum(w * x) / np.sum(w))
    ym = float(np.sum(w * y) / np.sum(w))
    den = float(np.sum(w * (x - xm) ** 2))
    if den == 0.0:
        return None
    return float(np.sum(w * (x - xm) * (y - ym)) / den)


def calibrate(samples: list[Sample], label: str = "전체") -> Calibration:
    resolved = [s for s in samples if s.resolved]
    unresolved = [s for s in samples if not s.resolved]
    n = len(resolved)
    below = [s for s in resolved if s.c < 0.5]
    bins = _bins(resolved)
    brier = float(np.mean([(s.c - s.o) ** 2 for s in resolved])) if resolved else None
    if n < MIN_N:
        return Calibration(
            label,
            n,
            len(unresolved),
            brier,
            bins,
            None,
            None,
            False,
            f"결론 없음 (N={n} < {MIN_N})",
            samples,
        )
    occupied = sum(1 for b in bins if b.n > 0)
    if occupied <= 2:
        return Calibration(
            label,
            n,
            len(unresolved),
            brier,
            bins,
            None,
            None,
            False,
            f"결론 없음 (N={n} 이지만 표본이 {occupied}개 구간에 몰려 있다)",
            samples,
        )
    slope = weighted_slope(bins)
    lam = None if slope is None else float(np.clip(1.0 - slope, 0.0, 1.0))
    reason = "N ≥ 20 · 3개 이상 구간 — 기울기 산출 (λ 갱신은 사람이 근거와 함께 결정)"
    if below:
        reason += f" · c < 0.5 표본 {len(below)}개는 구간 밖 (C6 미달인데 편입됨 — 점검 필요)"
    return Calibration(label, n, len(unresolved), brier, bins, slope, lam, True, reason, samples)


def render(cals: list[Calibration]) -> str:
    L = ["cycle_confidence 캘리브레이션 (docs/10 §4)", "", CONDITIONAL_CAVEAT, ""]
    for c in cals:
        L += [
            "=" * 78,
            f"[{c.label}]  N(판정 완료)={c.n} · 미결(o=0.5, 이월)={c.n_unresolved}",
            f"  {c.reason}",
        ]
        if c.brier is not None:
            L.append(f"  Brier = {c.brier:.4f}  (N={c.n})")
        L.append("  구간          n   적중률   평균 c")
        for b in c.bins:
            hr = "    —" if b.hit_rate is None else f"{b.hit_rate:5.2f}"
            mc = "   —" if b.mean_c is None else f"{b.mean_c:4.2f}"
            L.append(
                f"  [{b.lo:.1f},{b.hi:.1f}{']' if b.hi >= 1.0 else ')'}  {b.n:4d}   {hr}    {mc}"
            )
        if c.conclusive and c.slope is not None:
            L.append(
                f"  가중 최소자승 기울기 = {c.slope:+.3f}  →  "
                f"λ 실측 근거 ≈ 1 − slope = {c.lambda_hint:.3f} (07 §2.3)"
            )
        if c.samples:
            L.append("  표본:")
            for s in c.samples:
                L.append(
                    f"    {s.date} {s.theme:<24} c={s.c:.2f} ({s.provenance:<7}) o={s.o:<3} "
                    f"트리거 {s.triggers_met}/{s.triggers_total} 무효화 {s.invalidations_fired} "
                    f"via {s.exit_via}"
                )
        L.append("")
    L.append(
        "이 수치로 임계값·가중치·K·C6 을 조정하지 않는다 (CLAUDE.md §1). "
        "허용된 유일한 출력은 λ 의 실측 근거다."
    )
    return "\n".join(L)


def run(jdir: Path) -> tuple[str, list[Calibration]]:
    samples = samples_from_journal(jdir)
    cals = [calibrate(samples, "전체")]
    for prov in ("human", "referee"):
        sub = [s for s in samples if s.provenance == prov]
        cals.append(calibrate(sub, f"산출 주체 = {prov}"))
    return render(cals), cals


def to_json(cals: list[Calibration]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in cals:
        out.append(
            {
                "label": c.label,
                "n": c.n,
                "n_unresolved": c.n_unresolved,
                "brier": c.brier,
                "slope": c.slope,
                "lambda_hint": c.lambda_hint,
                "conclusive": c.conclusive,
                "reason": c.reason,
                "bins": [
                    {"lo": b.lo, "hi": b.hi, "n": b.n, "hit_rate": b.hit_rate, "mean_c": b.mean_c}
                    for b in c.bins
                ],
            }
        )
    return out
