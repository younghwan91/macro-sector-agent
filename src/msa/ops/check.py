"""`msa check` — 보유 포지션의 트리거·무효화·스탑·사다리·TP 점검 (`docs/09` §1·§3, `docs/07` §3~§5).

입력은 `state/positions.yaml` (`state_files.Position`) 과 각 포지션의 thesis 스냅샷(저널)이다.
출력은 `state/checks/<date>/report.txt` · `alerts.json` · 테마별 점검 저널 초안
(`journal-draft-<theme>.yaml`). **주문은 내지 않는다** (`CLAUDE.md` §8) — 이 모듈은 조건이
충족됐다는 사실을 측정해 적을 뿐이다.

무엇을 기계가 보고 무엇을 사람이 보는가:

| 항목 | 기계 | 사람 (`manual`) |
|---|---|---|
| 트리거·무효화 | `check:` 블록이 있는 항목 (가격 DSL, 아래) | `check:` 없는 항목 — 전부 목록으로 |
| Tier-2 자본 스탑 | 종가 ≤ 스탑가 (TP1 후엔 본전) | — |
| 사다리 n단 | 가격(초기가 대비 −x%) **AND** 논지(무효화 0건 · 트리거 ≥1) | 논지의 `manual` 해석 |
| 시간 스탑 | 30일 전 예고 · 경과 여부 · 충족 트리거 0건 여부 | — |
| TP | `price` 가 있는 단계(+2R · 직전 고점 50%) · 러너 트레일/10주선 | 밸류 백분위(P50·P75) 조건 |

가격 DSL (`thesis.triggers[*].check` / `invalidations[*].check`):

```yaml
check: {kind: price_below, ticker: URA, level: 70, days: 63}   # 종가 < level 이 days 거래일 연속
check: {kind: price_above, ticker: CCJ, level: 60, days: 1}
check: {kind: drawdown_from_high, ticker: CCJ, pct: 0.30, lookback_days: 252}  # 고점 대비 −30% 이상
```

그 외(`kind: manual` 또는 `check` 없음)는 전부 `manual` 이다. "심리 개선" 같은 것은 트리거가
아니므로 DSL 이 없다는 것 자체가 신호다 — 리포트가 manual 비율을 센다.

상태의 출처: 트리거/무효화의 **현재 상태**는 가장 최근 점검 저널 항목(front matter 의 `after`)에서,
없으면 thesis 스냅샷의 `status` 에서 온다. 기계가 이번 점검에서 새로 판정한 것은 리포트와 저널
초안에 "변화" 로 표시되고, 사람이 저널 항목을 추가해 확정한다 — 기계는 저널을 쓰지 않는다.

사다리 3단의 "트리거 진행 중" 은 **충족 ≥1 AND 2단 체결 완료** 로 읽는다 (07 §3 표의 2단 조건을
상속).
이 해석은 선언이다 — 데이터로 고른 것이 아니다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import yaml

from msa.ops.alerts import Alert, AlertKind, format_alert
from msa.ops.journal import load_entries, load_snapshot
from msa.ops.state_files import Position, PositionsFile, load_positions

log = logging.getLogger(__name__)

TIME_STOP_WARN_DAYS = 30
TIER2_PCT = 0.35

# ---------------------------------------------------------------------------
# 가격 소스 계약 — Store 든 합성이든 같은 모양
# ---------------------------------------------------------------------------


class PriceSource(Protocol):
    def closes(self, ticker: str, end: date) -> pd.Series:
        """`end` 까지의 조정 종가 (index: Timestamp 오름차순). 없으면 빈 Series."""
        ...


class DictPriceSource:
    """테스트·오프라인용: {ticker: Series}."""

    def __init__(self, data: dict[str, pd.Series]) -> None:
        self.data = {k.upper(): v.sort_index() for k, v in data.items()}

    def closes(self, ticker: str, end: date) -> pd.Series:
        s = self.data.get(ticker.upper())
        if s is None:
            return pd.Series(dtype=float)
        return s.loc[: pd.Timestamp(end)]


class StorePriceSource:
    """DuckDB 스토어 (`msa.data.store.Store`) 래퍼. 폐지 종목도 읽힌다."""

    def __init__(self, store: Any, lookback_days: int = 400) -> None:
        self.store = store
        self.lookback_days = lookback_days

    def closes(self, ticker: str, end: date) -> pd.Series:
        from msa.data.store import StoreError

        start = end - timedelta(days=self.lookback_days)
        try:
            df = self.store.prices([ticker.upper()], start, end, min_rows=1)
        except StoreError:
            return pd.Series(dtype=float)
        s: pd.Series = df.set_index(pd.to_datetime(df["date"]))["close"].astype(float)
        s = s.sort_index()
        s.name = ticker.upper()
        return s


# ---------------------------------------------------------------------------
# 조건 평가
# ---------------------------------------------------------------------------


@dataclass
class ConditionStatus:
    kind: str  # trigger | invalidation
    observable: str
    source: str
    action: str | None  # invalidation 만
    prior: str  # 이전 상태 (저널/스냅샷)
    status: str  # pending | met | missed | fired | manual
    machine: bool
    detail: str = ""

    @property
    def changed(self) -> bool:
        return self.machine and self.status != self.prior and self.status != "manual"


def _eval_check(check: dict[str, Any], prices: PriceSource, asof: date) -> tuple[bool | None, str]:
    """DSL 평가 → (충족 여부 | None=평가 불가, 설명)."""
    kind = str(check.get("kind", "manual"))
    if kind == "manual":
        return None, "manual"
    ticker = str(check.get("ticker", ""))
    s = prices.closes(ticker, asof)
    if s.empty:
        return None, f"{ticker} 가격 없음 — 평가 불가"
    if kind in ("price_below", "price_above"):
        level = float(check["level"])
        days = int(check.get("days", 1))
        tail = s.tail(days)
        if len(tail) < days:
            return None, f"{ticker} 이력 {len(tail)}일 < {days}일 — 평가 불가"
        ok = bool((tail < level).all()) if kind == "price_below" else bool((tail > level).all())
        op = "<" if kind == "price_below" else ">"
        return (
            ok,
            f"{ticker} 최근 {days}일 종가 {op} {level}: {'충족' if ok else '미충족'} "
            f"(최종 {tail.iloc[-1]:.2f})",
        )
    if kind == "drawdown_from_high":
        pct = float(check["pct"])
        lb = int(check.get("lookback_days", 252))
        w = s.tail(lb)
        hi = float(w.max())
        dd = float(w.iloc[-1]) / hi - 1.0 if hi > 0 else 0.0
        ok = dd <= -pct
        return (
            ok,
            f"{ticker} {lb}일 고점 대비 {dd:+.1%} (기준 −{pct:.0%}): {'충족' if ok else '미충족'}",
        )
    return None, f"알 수 없는 check.kind={kind!r} — manual 로 취급"


def _prior_statuses(jdir: Path, theme: str) -> dict[tuple[str, str], str]:
    """가장 최근 점검 저널 항목의 after 값. (kind, observable) → status."""
    checks = [e for e in load_entries(jdir, "check") if e.get("theme") == theme]
    if not checks:
        return {}
    last = checks[-1]
    out: dict[tuple[str, str], str] = {}
    for x in last.get("trigger_status") or []:
        out[("trigger", str(x.get("observable")))] = str(x.get("after"))
    for x in last.get("invalidation_status") or []:
        out[("invalidation", str(x.get("observable")))] = str(x.get("after"))
    return out


def evaluate_conditions(
    thesis: dict[str, Any],
    prior: dict[tuple[str, str], str],
    prices: PriceSource,
    asof: date,
) -> list[ConditionStatus]:
    out: list[ConditionStatus] = []
    for kind, key, fired_word in (
        ("trigger", "triggers", "met"),
        ("invalidation", "invalidations", "fired"),
    ):
        for item in thesis.get(key) or []:
            obs = str(item.get("observable"))
            p = prior.get((kind, obs), str(item.get("status", "pending")))
            check = item.get("check")
            if p in ("met", "missed", "fired"):
                # 이미 확정된 상태는 되돌리지 않는다 (사람이 저널에 적은 판정)
                out.append(
                    ConditionStatus(
                        kind,
                        obs,
                        str(item.get("source", "")),
                        item.get("action"),
                        p,
                        p,
                        False,
                        "확정 상태 유지",
                    )
                )
                continue
            if not isinstance(check, dict) or check.get("kind", "manual") == "manual":
                out.append(
                    ConditionStatus(
                        kind,
                        obs,
                        str(item.get("source", "")),
                        item.get("action"),
                        p,
                        "manual",
                        False,
                        "기계 판정 불가 — 사람이 본다",
                    )
                )
                continue
            ok, detail = _eval_check(check, prices, asof)
            if ok is None:
                out.append(
                    ConditionStatus(
                        kind,
                        obs,
                        str(item.get("source", "")),
                        item.get("action"),
                        p,
                        "manual",
                        False,
                        detail,
                    )
                )
                continue
            status = fired_word if ok else "pending"
            if kind == "trigger" and not ok and item.get("by"):
                # 기한 경과 + 미충족 → missed. `by` 는 "2026-Q4" 같은 자유 문자열이라
                # ISO 날짜일 때만 본다
                try:
                    if date.fromisoformat(str(item["by"])) < asof:
                        status = "missed"
                except ValueError:
                    pass
            out.append(
                ConditionStatus(
                    kind,
                    obs,
                    str(item.get("source", "")),
                    item.get("action"),
                    p,
                    status,
                    True,
                    detail,
                )
            )
    return out


# ---------------------------------------------------------------------------
# 포지션 점검
# ---------------------------------------------------------------------------


@dataclass
class LadderStatus:
    step: int
    filled: bool
    trigger_price: float
    price_met: bool
    thesis_met: bool
    detail: str

    @property
    def both(self) -> bool:
        return self.price_met and self.thesis_met and not self.filled


@dataclass
class TpStatus:
    level: str
    filled: bool
    machine: bool
    met: bool
    detail: str


@dataclass
class PositionCheck:
    ticker: str
    theme: str
    asof: date
    close: float | None
    entry_price: float
    avg_price: float | None
    move_from_entry: float | None
    move_from_avg: float | None
    conditions: list[ConditionStatus]
    triggers_met: int
    triggers_total: int
    invalidations_fired: int
    manual_count: int
    ladder: list[LadderStatus]
    tier2_stop_price: float
    tier2_basis: str
    tier2_hit: bool
    tier2_expected_from_avg: float | None  # 평단 −35% 계산값 (대조용)
    time_stop_date: date
    days_to_time_stop: int
    time_stop_warning: bool
    time_stop_due: bool
    tp: list[TpStatus]
    alerts: list[Alert] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _sma(s: pd.Series, n: int) -> float | None:
    if len(s) < n:
        return None
    return float(s.tail(n).mean())


def check_position(
    pos: Position,
    thesis: dict[str, Any],
    prior: dict[tuple[str, str], str],
    prices: PriceSource,
    asof: date,
) -> PositionCheck:
    s = prices.closes(pos.ticker, asof)
    close = float(s.iloc[-1]) if not s.empty else None
    problems: list[str] = []
    if close is None:
        problems.append(f"{pos.ticker}: {asof} 까지의 가격이 없다 — 가격 기반 판정 전부 불가")
    conds = evaluate_conditions(thesis, prior, prices, asof)
    trig = [c for c in conds if c.kind == "trigger"]
    inv = [c for c in conds if c.kind == "invalidation"]
    t_met = sum(1 for c in trig if c.status == "met")
    i_fired = sum(1 for c in inv if c.status == "fired")
    manual = sum(1 for c in conds if c.status == "manual")

    avg = pos.avg_price
    mv_entry = None if close is None else close / pos.entry_price - 1.0
    mv_avg = None if (close is None or avg is None) else close / avg - 1.0

    # 사다리
    ladder: list[LadderStatus] = []
    step2_filled = any(st.step == 2 and st.filled for st in pos.ladder)
    for st in sorted(pos.ladder, key=lambda x: x.step):
        tp_price = (
            st.trigger_price
            if st.trigger_price is not None
            else pos.entry_price * (1 - st.trigger_pct)
        )
        price_met = close is not None and st.step > 1 and close <= tp_price
        if st.step == 2:
            thesis_met = i_fired == 0 and t_met >= 1
            why = f"무효화 {i_fired}건 · 트리거 {t_met}/{len(trig)}"
        elif st.step == 3:
            thesis_met = i_fired == 0 and t_met >= 1 and step2_filled
            why = f"무효화 {i_fired}건 · 트리거 {t_met}/{len(trig)} · 2단 체결 {step2_filled}"
        else:
            thesis_met = True
            why = "1단 (진입)"
        ladder.append(LadderStatus(st.step, st.filled, float(tp_price), price_met, thesis_met, why))

    # Tier-2
    basis = pos.tier2_basis
    stop = pos.tier2_stop_price
    if pos.tp1_filled and avg is not None:
        basis, stop = "breakeven", avg  # 07 §5 전환 규칙
    expected = None if avg is None else avg * (1 - TIER2_PCT)
    if expected is not None and basis == "avg_minus_35" and abs(stop / expected - 1) > 0.01:
        problems.append(
            f"{pos.ticker}: tier2_stop_price {stop:.2f} 가 평단 −35% 계산값 {expected:.2f} 와 "
            "1% 이상 다르다 — "
            "positions.yaml 갱신 누락인지 확인"
        )
    tier2_hit = close is not None and close <= stop

    # 시간 스탑
    days_left = (pos.time_stop_date - asof).days
    ts_warn = 0 <= days_left <= TIME_STOP_WARN_DAYS and t_met == 0
    ts_due = days_left < 0 and t_met == 0

    # TP
    tps: list[TpStatus] = []
    tp2_filled = any(t.level == "tp2" and t.filled for t in pos.tp)
    for t in pos.tp:
        if t.level == "runner":
            if not tp2_filled:
                tps.append(
                    TpStatus(t.level, t.filled, True, False, "TP2 체결 전 — 러너 트레일 비활성")
                )
                continue
            since = s.loc[pd.Timestamp(pos.opened_at) :] if not s.empty else s
            peak = float(since.max()) if not since.empty else None
            ma = _sma(s, pos.runner_ma_weeks * 5)
            trail_hit = (
                close is not None
                and peak is not None
                and close <= peak * (1 - pos.runner_trail_pct)
            )
            ma_hit = close is not None and ma is not None and close < ma
            dd = None if (close is None or not peak) else close / peak - 1
            det = (
                f"고점 {peak if peak is None else round(peak, 2)} 대비 {_fmt_pct(dd)} "
                f"(기준 −{pos.runner_trail_pct:.0%}) · "
                f"{pos.runner_ma_weeks}주선 {ma if ma is None else round(ma, 2)}"
            )
            tps.append(TpStatus(t.level, t.filled, True, bool(trail_hit or ma_hit), det))
        elif t.price is not None:
            met = close is not None and close >= t.price
            tps.append(
                TpStatus(
                    t.level, t.filled, True, met, f"종가 {close} vs {t.price:.2f} — {t.condition}"
                )
            )
        else:
            tps.append(TpStatus(t.level, t.filled, False, False, f"manual — {t.condition}"))

    pc = PositionCheck(
        ticker=pos.ticker,
        theme=pos.theme,
        asof=asof,
        close=close,
        entry_price=pos.entry_price,
        avg_price=avg,
        move_from_entry=mv_entry,
        move_from_avg=mv_avg,
        conditions=conds,
        triggers_met=t_met,
        triggers_total=len(trig),
        invalidations_fired=i_fired,
        manual_count=manual,
        ladder=ladder,
        tier2_stop_price=stop,
        tier2_basis=basis,
        tier2_hit=tier2_hit,
        tier2_expected_from_avg=expected,
        time_stop_date=pos.time_stop_date,
        days_to_time_stop=days_left,
        time_stop_warning=ts_warn,
        time_stop_due=ts_due,
        tp=tps,
        problems=problems,
    )
    pc.alerts = _alerts_for(pc, pos)
    return pc


def _fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1%}"


def _alerts_for(pc: PositionCheck, pos: Position) -> list[Alert]:
    out: list[Alert] = []
    for c in pc.conditions:
        if c.kind == "invalidation" and c.status == "fired" and (c.changed or c.prior != "fired"):
            out.append(
                Alert(
                    AlertKind.INVALIDATION_FIRED,
                    pc.asof,
                    pc.theme,
                    pc.ticker,
                    {
                        "observable": c.observable,
                        "source": c.source,
                        "action": c.action,
                        "detail": c.detail,
                    },
                )
            )
    for ls in pc.ladder:
        if ls.both:
            out.append(
                Alert(
                    AlertKind.LADDER_STEP_MET,
                    pc.asof,
                    pc.theme,
                    pc.ticker,
                    {
                        "step": ls.step,
                        "move_from_entry": pc.move_from_entry,
                        "trigger_pct_neg": ls.trigger_price / pc.entry_price - 1.0,
                        "close": pc.close,
                        "invalidations_fired": pc.invalidations_fired,
                        "triggers_met": pc.triggers_met,
                        "triggers_total": pc.triggers_total,
                    },
                )
            )
    if pc.time_stop_warning or pc.time_stop_due:
        out.append(
            Alert(
                AlertKind.TIME_STOP_WARNING,
                pc.asof,
                pc.theme,
                pc.ticker,
                {
                    "days_left": pc.days_to_time_stop,
                    "time_stop_date": pc.time_stop_date.isoformat(),
                    "triggers_met": pc.triggers_met,
                    "triggers_total": pc.triggers_total,
                },
            )
        )
    for t in pc.tp:
        if t.met and not t.filled:
            out.append(
                Alert(
                    AlertKind.TP_MET,
                    pc.asof,
                    pc.theme,
                    pc.ticker,
                    {
                        "level": t.level,
                        "condition": t.detail,
                        "detail": t.detail,
                        "close": pc.close,
                    },
                )
            )
    if pc.tier2_hit:
        out.append(
            Alert(
                AlertKind.TIER2_STOP_HIT,
                pc.asof,
                pc.theme,
                pc.ticker,
                {
                    "close": pc.close,
                    "stop_price": round(pc.tier2_stop_price, 4),
                    "basis": pc.tier2_basis,
                    "move_from_avg": pc.move_from_avg,
                    "move_from_entry": pc.move_from_entry,
                },
            )
        )
    for a in out:
        a.text = format_alert(a)
    return out


# ---------------------------------------------------------------------------
# 전체 실행 + 산출물
# ---------------------------------------------------------------------------


@dataclass
class CheckReport:
    asof: date
    mode: str  # daily | weekly
    positions: list[PositionCheck]
    alerts: list[Alert]
    out_dir: Path | None
    problems: list[str]

    def render(self) -> str:
        L = [
            f"포지션 점검 · {self.asof} · {self.mode} · 포지션 {len(self.positions)}개 · "
            f"알림 {len(self.alerts)}건",
            "",
        ]
        if not self.positions:
            L.append("보유 포지션 없음 (state/positions.yaml)")
        for p in self.positions:
            L += [
                "=" * 78,
                f"{p.ticker} ({p.theme})  종가 {p.close}  초기가 {p.entry_price:.2f} "
                f"({_fmt_pct(p.move_from_entry)})  "
                f"평단 {'—' if p.avg_price is None else f'{p.avg_price:.2f}'} "
                f"({_fmt_pct(p.move_from_avg)})",
                f"  트리거 {p.triggers_met}/{p.triggers_total} 충족 · "
                f"무효화 {p.invalidations_fired}건 발동 · manual {p.manual_count}건",
            ]
            for c in p.conditions:
                mark = " ◀ 변화" if c.changed else ""
                L.append(
                    f"    [{c.kind[:4]}] {c.status:<8} {'기계' if c.machine else '사람'}  "
                    f"{c.observable}  — {c.detail}{mark}"
                )
            L.append(
                f"  Tier-2 스탑 {p.tier2_stop_price:.2f} ({p.tier2_basis}) · "
                f"{'도달' if p.tier2_hit else '미도달'}"
            )
            for ls in p.ladder:
                L.append(
                    f"  사다리 {ls.step}단 {'체결' if ls.filled else '대기'}  "
                    f"기준가 {ls.trigger_price:.2f}  "
                    f"가격 {'충족' if ls.price_met else '미충족'} · "
                    f"논지 {'충족' if ls.thesis_met else '미충족'} ({ls.detail})"
                    f"{'  ◀ 둘 다 충족' if ls.both else ''}"
                )
            ts = "예고" if p.time_stop_warning else ("경과" if p.time_stop_due else "—")
            L.append(f"  시간 스탑 {p.time_stop_date} (D{p.days_to_time_stop:+d}) {ts}")
            for t in p.tp:
                L.append(
                    f"  {t.level.upper():<6} "
                    f"{'체결' if t.filled else ('충족' if t.met else '미충족')} "
                    f"{'기계' if t.machine else '사람'}  {t.detail}"
                )
            for pr in p.problems:
                L.append(f"  ! {pr}")
        if self.alerts:
            L += ["", "=" * 78, "알림"]
            for a in self.alerts:
                L += ["", a.text]
        if self.problems:
            L += ["", "문제"] + [f"  ! {x}" for x in self.problems]
        L += ["", "이 리포트는 측정값이다. 주문은 내지 않으며 집행은 사람이 한다 (CLAUDE.md §8)."]
        return "\n".join(L)


def _journal_draft(
    theme: str, checks: list[PositionCheck], asof: date, mode: str, report_path: str
) -> dict[str, Any]:
    """테마 단위 점검 저널 초안 — 사람이 확인해 `msa journal new --from` 으로 넣는다."""
    seen: dict[tuple[str, str], ConditionStatus] = {}
    for pc in checks:
        for c in pc.conditions:
            seen.setdefault((c.kind, c.observable), c)
    return {
        "type": "check",
        "date": asof.isoformat(),
        "theme": theme,
        "cadence": mode,
        "check_report": report_path,
        "trigger_status": [
            {
                "observable": c.observable,
                "before": c.prior,
                "after": (c.status if c.status != "manual" else c.prior),
            }
            for (k, _), c in seen.items()
            if k == "trigger"
        ],
        "invalidation_status": [
            {
                "observable": c.observable,
                "before": c.prior,
                "after": (c.status if c.status != "manual" else c.prior),
            }
            for (k, _), c in seen.items()
            if k == "invalidation"
        ],
        "thesis": None,
        "notes": "기계 초안 — manual 항목은 사람이 판정해 after 를 고친 뒤 저장한다",
        "links": [],
    }


def run_check(
    *,
    asof: date,
    mode: str,
    prices: PriceSource,
    positions_path: Path,
    journal_dir: Path,
    repo_root: Path,
    out_root: Path | None,
    positions: PositionsFile | None = None,
) -> CheckReport:
    pf = positions if positions is not None else load_positions(positions_path)
    problems: list[str] = []
    checks: list[PositionCheck] = []
    for pos in pf.open_positions():
        snap = repo_root / pos.thesis_snapshot
        if not snap.exists():
            problems.append(
                f"{pos.ticker}: thesis 스냅샷 없음 {pos.thesis_snapshot} — "
                "이 포지션은 점검하지 않았다"
            )
            continue
        thesis = load_snapshot(snap)
        prior = _prior_statuses(journal_dir, pos.theme)
        checks.append(check_position(pos, thesis, prior, prices, asof))
    alerts = [a for pc in checks for a in pc.alerts]
    out_dir = None
    report = CheckReport(
        asof=asof, mode=mode, positions=checks, alerts=alerts, out_dir=None, problems=problems
    )
    if out_root is not None:
        out_dir = out_root / asof.isoformat()
        out_dir.mkdir(parents=True, exist_ok=True)
        report.out_dir = out_dir
        (out_dir / "report.txt").write_text(report.render(), encoding="utf-8")
        (out_dir / "positions.json").write_text(
            json.dumps(
                [_plain(asdict(pc)) for pc in checks], ensure_ascii=False, indent=1, default=str
            ),
            encoding="utf-8",
        )
        rel_report = (
            str((out_dir / "report.txt").relative_to(repo_root))
            if out_dir.is_relative_to(repo_root)
            else str(out_dir / "report.txt")
        )
        for theme in sorted({pc.theme for pc in checks}):
            draft = _journal_draft(
                theme, [pc for pc in checks if pc.theme == theme], asof, mode, rel_report
            )
            (out_dir / f"journal-draft-{theme}.yaml").write_text(
                yaml.safe_dump(draft, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
    return report


def _plain(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items() if k != "alerts"}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, AlertKind):
        return str(obj)
    return obj
