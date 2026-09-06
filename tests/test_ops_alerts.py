"""알림 — 6종(+Tier2) 문구 규약 · 배달."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

from msa.ops.alerts import (
    SIX_KINDS,
    Alert,
    AlertKind,
    WordingViolation,
    assert_wording_ok,
    deliver,
    format_alert,
)
from msa.vendor.telegram import TelegramConfig, telegram_config

D = date(2026, 12, 15)


def _all_alerts() -> list[Alert]:
    return [
        Alert(
            AlertKind.DAILY_DIGEST,
            D,
            "-",
            None,
            {
                "asof": "2026-12-15",
                "new_items": ["uranium: 상위 N 신규 CCJ, UEC", "copper: 신규 하드 제외 XYZ"],
                "omitted": 3,
                "top3": ["uranium — 점수 0.91 · pool 0.88", "copper — 점수 0.85 · pool 0.80"],
                "path": "state/daily/2026-12-15/digest.md",
            },
        ),
        Alert(
            AlertKind.MONTHLY_REPORT,
            D,
            "-",
            None,
            {
                "asof": "2026-12-01",
                "path": "state/scans/2026-12-01/report.txt",
                "n_themes": 134,
                "top_k": 8,
            },
        ),
        Alert(
            AlertKind.MONTHLY_SUMMARY,
            D,
            "-",
            None,
            {
                "asof": "2026-12-01",
                "top5": ["uranium", "copper", "gold", "shipping", "grid"],
                "plan_changes": ["uranium 28% → 24%"],
            },
        ),
        Alert(
            AlertKind.INVALIDATION_FIRED,
            D,
            "uranium",
            "CCJ",
            {
                "observable": "URA < 20",
                "source": "가격",
                "action": "exit",
                "detail": "3일 연속 19.0",
            },
        ),
        Alert(
            AlertKind.LADDER_STEP_MET,
            D,
            "uranium",
            "CCJ",
            {
                "step": 2,
                "move_from_entry": -0.132,
                "trigger_pct_neg": -0.13,
                "close": 43.4,
                "invalidations_fired": 0,
                "triggers_met": 1,
                "triggers_total": 3,
            },
        ),
        Alert(
            AlertKind.TIME_STOP_WARNING,
            D,
            "uranium",
            "CCJ",
            {
                "days_left": 26,
                "time_stop_date": "2027-01-10",
                "triggers_met": 0,
                "triggers_total": 3,
            },
        ),
        Alert(
            AlertKind.TP_MET,
            D,
            "uranium",
            "CCJ",
            {"level": "tp1", "condition": "+2R", "detail": "86 ≥ 85", "close": 86.0},
        ),
        Alert(
            AlertKind.TIER2_STOP_HIT,
            D,
            "uranium",
            "CCJ",
            {
                "close": 32.0,
                "stop_price": 32.5,
                "basis": "avg_minus_35",
                "move_from_avg": -0.36,
                "move_from_entry": -0.36,
            },
        ),
    ]


def test_six_kinds_plus_tier2_all_format_and_pass_wording_rule() -> None:
    assert len(SIX_KINDS) == 6 and len(AlertKind) == 8
    kinds = {a.kind for a in _all_alerts()}
    assert kinds == set(AlertKind)
    for a in _all_alerts():
        text = format_alert(a)
        assert_wording_ok(text)
        assert "투자 조언이 아니다" in text


def test_ladder_message_is_the_documented_fact_format() -> None:
    a = next(x for x in _all_alerts() if x.kind is AlertKind.LADDER_STEP_MET)
    t = format_alert(a)
    assert "사다리 2단 조건 충족" in t and "-13.2%" in t and "무효화 0건" in t and "트리거 1/3" in t


@pytest.mark.parametrize(
    "bad",
    [
        "CCJ 사세요",
        "지금 매수하세요",
        "CCJ 매수 추천",
        "비중 확대 권장",
        "You should buy CCJ now",
        "SELL everything",
        "CCJ 를 사라.",
    ],
)
def test_forbidden_wording_raises(bad: str) -> None:
    with pytest.raises(WordingViolation):
        assert_wording_ok(bad)


def test_neutral_wording_passes() -> None:
    assert_wording_ok("CCJ 사다리 2단 조건 충족: 가격 −13.2%, 무효화 0건, 트리거 1/3 충족")
    assert_wording_ok("사다리 추가 매수 금지 조건 (무효화 1건)")


def test_deliver_send_false_is_suppressed_and_never_touches_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`send=False` — 설정이 **있어도** 보내지 않는다. 파일은 쓰고 상태는 not_configured 가
    아니라 suppressed (안 보낸 이유를 뭉개지 않는다, CLAUDE.md §2)."""

    class Boom:
        def send_many_sync(self, chat_id: str, texts: Sequence[str]) -> list[bool]:
            raise AssertionError("send=False 인데 채널을 건드렸다")

    monkeypatch.setenv("MSA_TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("MSA_TELEGRAM_CHAT_ID", "42")
    res = deliver(_all_alerts()[:2], tmp_path, notifier=Boom(), send=False)
    assert res.status == "suppressed" and res.sent == 0 and res.failed == 0
    assert len(json.loads((tmp_path / "alerts.json").read_text())) == 2


def test_deliver_not_configured_still_writes_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MSA_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("MSA_TELEGRAM_CHAT_ID", raising=False)
    assert telegram_config() is None
    res = deliver(_all_alerts()[:2], tmp_path)
    assert res.status == "not_configured" and res.sent == 0
    data = json.loads((tmp_path / "alerts.json").read_text())
    assert len(data) == 2 and data[0]["kind"] == "daily_digest" and data[0]["text"]
    # 토큰만 있고 chat_id 없음 → 여전히 not configured
    monkeypatch.setenv("MSA_TELEGRAM_TOKEN", "x")
    assert telegram_config() is None
    monkeypatch.setenv("MSA_TELEGRAM_CHAT_ID", "1")
    assert telegram_config() == TelegramConfig("x", "1")


def test_deliver_sends_when_configured(tmp_path: Path) -> None:
    class Fake:
        def __init__(self, fail_every: int = 0) -> None:
            self.sent: list[tuple[str, str]] = []
            self.batches = 0
            self.fail_every = fail_every

        def send_many_sync(self, chat_id: str, texts: Sequence[str]) -> list[bool]:
            self.batches += 1
            oks: list[bool] = []
            for t in texts:
                self.sent.append((chat_id, t))
                oks.append(not (self.fail_every and len(self.sent) % self.fail_every == 0))
            return oks

    fake = Fake()
    res = deliver(_all_alerts(), tmp_path, cfg=TelegramConfig("t", "42"), notifier=fake)
    assert res.status == "sent" and res.sent == 8 and all(c == "42" for c, _ in fake.sent)
    assert fake.batches == 1  # 한 루프로 전부
    assert deliver([], tmp_path).status == "nothing_to_send"
    partial = Fake(fail_every=3)
    res = deliver(_all_alerts(), tmp_path, cfg=TelegramConfig("t", "42"), notifier=partial)
    assert res.status == "partial" and (res.sent, res.failed) == (6, 2)
    assert (
        deliver(_all_alerts()[:1], tmp_path, cfg=TelegramConfig("t", "42"), notifier=Fake(1)).status
        == "failed"
    )


def test_time_stop_alert_says_elapsed_not_days_before(tmp_path: Path) -> None:
    """`check.py` 는 예고(D+n)와 경과(D−n)를 같은 종류로 낸다 — 문구가 갈라져야 한다."""

    def txt(days_left: int) -> str:
        return format_alert(
            Alert(
                AlertKind.TIME_STOP_WARNING,
                D,
                "uranium",
                "CCJ",
                {
                    "days_left": days_left,
                    "time_stop_date": "2026-12-03",
                    "triggers_met": 0,
                    "triggers_total": 3,
                },
            )
        )

    assert "[시간 스탑 21일 전]" in txt(21)
    assert "[시간 스탑 12일 경과]" in txt(-12)
    assert "0일 경과" in txt(0)
    assert "-12일 전" not in txt(-12)


def test_alerts_json_is_written_even_when_wording_check_fires(tmp_path: Path) -> None:
    """docstring 의 계약 — 파일은 어느 경우든 쓴다. 검사는 저장 뒤에 돈다."""
    bad = Alert(AlertKind.TP_MET, D, "uranium", "CCJ", {"level": "tp1"})
    bad.text = "[TP 조건 충족] CCJ — 지금 매수 추천"
    with pytest.raises(WordingViolation):
        deliver([bad], tmp_path)
    saved = json.loads((tmp_path / "alerts.json").read_text(encoding="utf-8"))
    assert len(saved) == 1 and saved[0]["ticker"] == "CCJ"


def test_agent_prose_is_not_scanned_but_code_template_still_is() -> None:
    """L3 원문이 '추천' 을 서술로 담았다고 다이제스트 전체가 죽지 않는다 (CLAUDE.md §2)."""
    facts = {
        "asof": "2026-12-15",
        "new_items": [],
        "themes": [
            {
                "head": "uranium — 점수 0.91 · pool 0.88",
                "picks": ["CCJ · 가격 55.1"],
                "thesis": "업계 추천 관행이 바뀌면서 수요가 늘고 있다",
                "invalidation": "",
                "n_invalidations": 0,
                "n_eligible": 1,
                "n_excluded": 0,
            }
        ],
        "picks_per_theme": 1,
        "path": "state/daily/2026-12-15/digest.md",
    }
    a = Alert(AlertKind.DAILY_DIGEST, D, "-", None, facts)
    text = format_alert(a)
    assert "업계 추천 관행" in text  # 원문은 그대로 실린다 — 지우지 않는다

    facts["themes"][0]["head"] = "uranium — 매수 추천"  # type: ignore[index]
    with pytest.raises(WordingViolation):
        format_alert(Alert(AlertKind.DAILY_DIGEST, D, "-", None, facts))
