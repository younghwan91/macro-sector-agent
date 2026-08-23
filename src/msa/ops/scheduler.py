"""케이던스 → crontab / systemd 타이머 텍스트 (`docs/09-operations.md` §1).

| 주기 | cron | 명령 |
|---|---|---|
| 월간 (1영업일) | `1-3일 07:00` + `msa ops due monthly` | `msa run monthly` |
| 주간 (월요일) | `월 07:30` | `msa run weekly` (스캔 + `check --weekly`) |
| 일간 (평일) | `평일 18:30` | `msa run daily --send` (다이제스트 + `check --daily` 내장) |
| 분기 (1·4·7·10월 1영업일) | `1-3일 08:00` + `due quarterly` | calibration · rejections |

월간(`msa run monthly`, 배선 W4)은 스캔→상위 K→L3→적재→L4→L5 를 잇고 **제안·초안**에서 끝난다
(`docs/09` §1 "기계 vs 사람"). 키가 없으면 기본 `--provider none` 으로 L3 를 부르지 않고 사람
논지/직전 thesis 만 찾는다; `ANTHROPIC_API_KEY` 가 있으면 cron 행에 `--provider anthropic` 을
사람이 붙인다 — 비용이 드는 호출을 기본값으로 두지 않는다. (분기의 `msa macro` 모순 감사는
2026-08-23 L2 제거와 함께 없어졌다 — `docs/13` §9.)

cron 은 "1영업일" 을 표현하지 못하므로 1~3일에 매일 깨우고 `msa ops due <cadence>` 가 그날이
그 달의 첫 평일일 때만 0 을 돌려준다 (미국 공휴일은 보지 않는다 — 공휴일이 1일이면 하루 늦게 돈다.
이 한계를 숨기지 않고 여기 적는다). **아무것도 설치하지 않는다** — 출력을 사람이 `crontab -e` 에
붙인다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from msa.config import REPO_ROOT

CADENCES = ("monthly", "weekly", "daily", "quarterly")


@dataclass(frozen=True)
class Job:
    cadence: str
    when: str  # cron 5필드
    on_calendar: str  # systemd OnCalendar — `when` 과 같은 시각
    commands: tuple[str, ...]
    gate: str | None  # `msa ops due <cadence>` 로 거를지
    note: str

    def command_chain(self, runner: str) -> str:
        """`runner msa …` 를 `&&` 로 잇고, 게이트가 있으면 `msa ops due <gate>` 를 앞에 둔다."""
        chain = " && ".join(f"{runner} {c}" for c in self.commands)
        if self.gate:
            chain = f"{runner} msa ops due {self.gate} && {chain}"
        return chain


JOBS: tuple[Job, ...] = (
    Job(
        "monthly",
        "0 7 1-3 * *",
        "*-*-01..03 07:00:00",
        ("msa run monthly",),
        "monthly",
        "L0 적재 → L1 전수 스캔 → 상위 K L3 → L4 → L5 (제안·초안까지) → 사람 검토 "
        "30~60분. ANTHROPIC_API_KEY 가 있으면 `--provider anthropic` 을 붙인다 "
        "(기본 none = L3 미호출)",
    ),
    Job(
        "weekly",
        "30 7 * * 1",
        "Mon *-*-* 07:30:00",
        ("msa run weekly",),
        None,
        "L1 스캔 갱신 + 보유 포지션 트리거·무효화 점검 — 사람 5~10분",
    ),
    Job(
        "daily",
        "30 18 * * 1-5",
        "Mon..Fri *-*-* 18:30:00",
        ("msa run daily --send",),
        None,
        "후보 다이제스트 + 무효화·사다리·TP·시간스탑 확인 (check 내장) — 알림·요약 시에만 본다",
    ),
    Job(
        "quarterly",
        "0 8 1-3 1,4,7,10 *",
        "*-01,04,07,10-01..03 08:00:00",
        ("msa ops calibration", "msa ops rejections-update"),
        "quarterly",
        "캘리브레이션 · 기각 대장 12·24M 갱신",
    ),
)


def first_business_day(d: date) -> date:
    """그 달의 첫 평일 (월~금). 공휴일 미고려 — 모듈 docstring 참조."""
    x = d.replace(day=1)
    while x.weekday() >= 5:
        x += timedelta(days=1)
    return x


def is_due(cadence: str, today: date) -> bool:
    if cadence == "monthly":
        return today == first_business_day(today)
    if cadence == "quarterly":
        return today.month in (1, 4, 7, 10) and today == first_business_day(today)
    if cadence == "weekly":
        return today.weekday() == 0
    if cadence == "daily":
        return today.weekday() < 5
    raise ValueError(f"cadence ∈ {CADENCES}: {cadence!r}")


def cron_lines(
    repo: Path | None = None, runner: str = "uv run", log_dir: str = "state/logs"
) -> str:
    root = repo or REPO_ROOT
    L = [
        "# macro-sector-agent 케이던스 (docs/09 §1) — `msa ops schedule --print-cron` 이 만들었다.",
        "# 설치는 사람이 한다: crontab -e 에 붙여 넣는다.",
        "# 텔레그램은 MSA_TELEGRAM_TOKEN / MSA_TELEGRAM_CHAT_ID 가 둘 다 있을 때만 보낸다.",
        f"MSA_REPO={root}",
        "# MSA_TELEGRAM_TOKEN=...",
        "# MSA_TELEGRAM_CHAT_ID=...",
        "",
    ]
    for j in JOBS:
        L.append(f"# {j.cadence}: {j.note}")
        L.append(
            f'{j.when} cd "$MSA_REPO" && mkdir -p {log_dir} && {j.command_chain(runner)} '
            f">> {log_dir}/{j.cadence}.log 2>&1"
        )
        L.append("")
    return "\n".join(L)


def systemd_units(repo: Path | None = None, runner: str = "uv run") -> str:
    """systemd 타이머 텍스트 (cron 대신 쓸 때). OnCalendar 로 1~3일 + due 게이트는 동일."""
    root = repo or REPO_ROOT
    out: list[str] = [
        "# systemd --user 타이머. 각 블록을 "
        "~/.config/systemd/user/msa-<cadence>.{service,timer} 로 "
        "저장한다.",
        "",
    ]
    for j in JOBS:
        out += [
            f"# --- msa-{j.cadence}.service",
            "[Unit]",
            f"Description=msa {j.cadence} — {j.note}",
            "",
            "[Service]",
            "Type=oneshot",
            f"WorkingDirectory={root}",
            f"ExecStart=/bin/sh -lc '{j.command_chain(runner)}'",
            "",
            f"# --- msa-{j.cadence}.timer",
            "[Unit]",
            f"Description=msa {j.cadence} timer",
            "",
            "[Timer]",
            f"OnCalendar={j.on_calendar}",
            "Persistent=true",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    return "\n".join(out)
