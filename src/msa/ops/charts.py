"""리포트용 막대 그래프 — 유니코드 문자로 그린다.

**왜 이미지도 Mermaid 도 아닌가.** 같은 문장이 세 곳에 나간다: 마크다운(`digest.md`·README),
터미널(`report.txt`), 텔레그램. Mermaid 는 GitHub 에서만 그려지고 터미널에서는 소스가 그대로
보인다. 이미지는 파일이 하나 더 생기고 텔레그램·터미널에서 안 보인다. 유니코드 막대는
**세 곳에서 같게 보이고** 산출물이 늘지 않는다.

숫자를 대체하지 않는다 — 숫자 옆에 붙는다. 그래프만 남기면 정확한 값을 잃는다.
"""

from __future__ import annotations

from collections.abc import Sequence

#: 막대 한 칸. 8분의 1 단위로 채워 짧은 값도 길이 차이가 보인다.
_EIGHTHS = "▏▎▍▌▋▊▉█"

#: 기본 막대 폭(칸). 마크다운 표 안에서도 줄바꿈되지 않는 길이다.
WIDTH = 24


def bar(value: float, *, vmax: float, width: int = WIDTH) -> str:
    """`0..vmax` → 막대. `vmax` 가 0 이거나 값이 음수면 빈 막대."""
    if vmax <= 0 or value <= 0:
        return ""
    filled = min(1.0, value / vmax) * width
    full = int(filled)
    rest = filled - full
    out = "█" * full
    if rest > 0 and full < width:
        out += _EIGHTHS[min(len(_EIGHTHS) - 1, int(rest * len(_EIGHTHS)))]
    return out


def hbar_rows(
    rows: Sequence[tuple[str, float]],
    *,
    width: int = WIDTH,
    fmt: str = "{:+.0%}",
    label_width: int = 6,
) -> list[str]:
    """`(라벨, 값)` → `라벨  값  막대` 줄들. **값의 절댓값**으로 막대를 그린다.

    낙폭처럼 음수가 의미를 갖는 값을 그대로 쓰면 막대가 안 나온다. 부호는 숫자가 들고,
    막대는 크기만 보여 준다 — 그래서 라벨·숫자·막대가 서로를 대체하지 않는다.
    """
    if not rows:
        return []
    vmax = max(abs(v) for _, v in rows) or 1.0
    return [
        f"{label:<{label_width}} {fmt.format(v):>7}  {bar(abs(v), vmax=vmax, width=width)}"
        for label, v in rows
    ]


def block(
    title: str, rows: Sequence[tuple[str, float]], *, note: str = "", **kw: object
) -> list[str]:
    """제목 + 코드블록 막대. 마크다운·터미널 둘 다에서 같게 보인다."""
    lines = hbar_rows(rows, **kw)  # type: ignore[arg-type]
    if not lines:
        return []
    out = [f"**{title}**", "", "```"]
    out += lines
    out += ["```"]
    if note:
        out += ["", f"<sub>{note}</sub>"]
    return [*out, ""]
