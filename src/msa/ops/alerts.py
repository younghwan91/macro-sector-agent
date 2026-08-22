"""알림 — 종류 · 문구 규약 · 배달 (`docs/09-operations.md` §3).

문구 규약 (`fin-checkup` 승계): **측정값과 사실만 전달하고 투자 권유를 하지 않는다.**
"CCJ 사세요" 가 아니라 "CCJ 사다리 2단 조건 충족: 가격 −13.2%, 무효화 0건, 트리거 1/3 충족".
`FORBIDDEN_WORDING` 이 그 규약의 기계적 하한이고 `assert_wording_ok()` 가 모든 문구를 통과시킨다 —
테스트가 이를 강제한다. 문구 규약을 통과했다고 권유가 아닌 것은 아니지만, 통과 못 하면
확실히 권유다.

배달: 텔레그램은 `MSA_TELEGRAM_TOKEN` · `MSA_TELEGRAM_CHAT_ID` 가 **둘 다** 있을 때만 보낸다.
없으면 "not configured" 로 보고한다. 어느 경우든 `state/checks/<date>/alerts.json` 에 남는다 —
텔레그램은 배달 수단이고 기록은 파일이다.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from msa.vendor.telegram import TelegramConfig, TelegramNotifier, telegram_config


class AlertKind(StrEnum):
    """docs/09 §3 표의 6행 + Tier-2 자본 스탑 (docs/07 §4 — 점검이 평가하므로 알림도 필요하다)."""

    MONTHLY_REPORT = "monthly_report"  # 마크다운 리포트 생성 — 경로·요약 (월간)
    MONTHLY_SUMMARY = "monthly_summary"  # 상위 5테마 + 계획 변경분 (월간)
    INVALIDATION_FIRED = "invalidation_fired"  # 즉시
    LADDER_STEP_MET = "ladder_step_met"  # 가격 + 논지 조건 동시 충족 (일간)
    TIME_STOP_WARNING = "time_stop_warning"  # 30일 전 예고
    TP_MET = "tp_met"  # TP 조건 충족 (일간)
    TIER2_STOP_HIT = "tier2_stop_hit"  # 07 §4 자본 스탑 (09 §3 표 밖 — 추가)


#: 6종 (09 §3) — 로드맵 체크박스가 세는 단위. TIER2 는 07 §4 에서 온 추가분이다.
SIX_KINDS: tuple[AlertKind, ...] = (
    AlertKind.MONTHLY_REPORT,
    AlertKind.MONTHLY_SUMMARY,
    AlertKind.INVALIDATION_FIRED,
    AlertKind.LADDER_STEP_MET,
    AlertKind.TIME_STOP_WARNING,
    AlertKind.TP_MET,
)

#: 권유 문구 — 하나라도 걸리면 보내지 않는다 (테스트가 모든 템플릿을 이 목록에 통과시킨다).
FORBIDDEN_WORDING: tuple[str, ...] = (
    r"사세요",
    r"파세요",
    r"사라[\s.!]|사라$",
    r"팔아라",
    r"매수\s*하(세요|십시오|라|자)",
    r"매도\s*하(세요|십시오|라|자)",
    r"매수\s*추천",
    r"매도\s*추천",
    r"추천",
    r"권유",
    r"권장",
    r"강력\s*매수",
    r"비중\s*확대\s*(하세요|권)",
    r"\bbuy\b",
    r"\bsell\b",
    r"should\s+(buy|sell|add)",
)
_FORBIDDEN = tuple(re.compile(p, re.I) for p in FORBIDDEN_WORDING)

FOOTER = "측정값과 사실의 전달이며 투자 조언이 아니다. 집행 여부는 사람이 정한다."


class WordingViolation(ValueError):
    """알림 문구에 권유 표현이 들어 있다."""


def assert_wording_ok(text: str) -> None:
    hits = [p.pattern for p in _FORBIDDEN if p.search(text)]
    if hits:
        raise WordingViolation(f"권유 표현: {hits} — 문구: {text[:120]!r}")


@dataclass
class Alert:
    kind: AlertKind
    date: date
    theme: str
    ticker: str | None
    facts: dict[str, Any] = field(default_factory=dict)
    text: str = ""  # format_alert 가 채운다

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = str(self.kind)
        d["date"] = self.date.isoformat()
        return d


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1%}"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_alert(a: Alert) -> str:
    """사실만. 종류별 템플릿은 측정값의 나열이다 — 동사가 없다."""
    f = a.facts
    who = f"{a.ticker} ({a.theme})" if a.ticker else a.theme
    if a.kind is AlertKind.INVALIDATION_FIRED:
        head = f"[무효화 발동] {who}"
        body = (
            f"조건: {f.get('observable')}\n"
            f"출처: {f.get('source')} · 규정 조치: {f.get('action')} (07 §4 Tier-1)\n"
            f"관측: {f.get('detail', '')}"
        )
    elif a.kind is AlertKind.LADDER_STEP_MET:
        head = f"[사다리 {f.get('step')}단 조건 충족] {who}"
        body = (
            f"가격: 초기가 대비 {_pct(f.get('move_from_entry'))} "
            f"(기준 {_pct(f.get('trigger_pct_neg'))})"
            f" · 종가 {f.get('close')}\n"
            f"논지: 무효화 {f.get('invalidations_fired')}건 · "
            f"트리거 {f.get('triggers_met')}/{f.get('triggers_total')} 충족"
        )
    elif a.kind is AlertKind.TIME_STOP_WARNING:
        head = f"[시간 스탑 {f.get('days_left')}일 전] {who}"
        body = (
            f"시간 스탑일 {f.get('time_stop_date')} · 충족 트리거 {f.get('triggers_met')}/"
            f"{f.get('triggers_total')}\n"
            f"규정: horizon 상한 경과 AND 트리거 0건 → 전량 청산 (07 §4)"
        )
    elif a.kind is AlertKind.TP_MET:
        head = f"[TP 조건 충족 · {str(f.get('level', '')).upper()}] {who}"
        body = f"조건: {f.get('condition')}\n관측: {f.get('detail', '')} · 종가 {f.get('close')}"
    elif a.kind is AlertKind.TIER2_STOP_HIT:
        head = f"[Tier-2 자본 스탑 도달] {who}"
        body = (
            f"종가 {f.get('close')} ≤ 스탑 {f.get('stop_price')} ({f.get('basis')})\n"
            f"평단 대비 {_pct(f.get('move_from_avg'))} · "
            f"초기가 대비 {_pct(f.get('move_from_entry'))}\n"
            "규정: 전량 청산 (07 §4)"
        )
    elif a.kind is AlertKind.MONTHLY_REPORT:
        head = f"[월간 리포트] {f.get('asof')}"
        body = (
            f"경로: {f.get('path')}\n테마 {f.get('n_themes')}개 · 상위 {f.get('top_k')} 검토 대상"
        )
    elif a.kind is AlertKind.MONTHLY_SUMMARY:
        head = f"[월간 요약] {f.get('asof')}"
        tops = f.get("top5") or []
        lines = [f"  {i + 1}. {t}" for i, t in enumerate(tops)]
        changes = f.get("plan_changes") or []
        body = "상위 5테마:\n" + "\n".join(lines)
        body += "\n계획 변경분:\n" + (
            "\n".join(f"  - {c}" for c in changes) if changes else "  (없음)"
        )
    else:  # pragma: no cover — enum 이 막는다
        raise ValueError(a.kind)
    text = f"{head}\n{body}\n— {FOOTER}"
    assert_wording_ok(text)
    return text


@dataclass(frozen=True)
class DeliveryResult:
    json_path: Path
    status: str  # sent | not_configured | partial | failed | nothing_to_send
    sent: int
    failed: int


def deliver(
    alerts: list[Alert],
    out_dir: Path,
    *,
    cfg: TelegramConfig | None = None,
    use_env: bool = True,
    notifier: TelegramNotifier | None = None,
) -> DeliveryResult:
    """항상 `alerts.json` 을 쓴다. 텔레그램은 설정이 둘 다 있을 때만."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in alerts:
        if not a.text:
            a.text = format_alert(a)
        assert_wording_ok(a.text)
    path = out_dir / "alerts.json"
    path.write_text(
        json.dumps([a.to_json() for a in alerts], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if not alerts:
        return DeliveryResult(path, "nothing_to_send", 0, 0)
    if cfg is None and use_env:
        cfg = telegram_config()
    if cfg is None:
        return DeliveryResult(path, "not_configured", 0, 0)
    n = notifier or TelegramNotifier(cfg.token)
    sent = failed = 0
    for a in alerts:
        ok = n.send_sync(cfg.chat_id, _esc(a.text))
        sent += int(ok)
        failed += int(not ok)
    status = "sent" if failed == 0 else ("partial" if sent else "failed")
    return DeliveryResult(path, status, sent, failed)
