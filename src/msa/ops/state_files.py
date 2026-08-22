"""`state/positions.yaml` · `watchlist.yaml` · `rejections.yaml` — 타입 있는 로드/저장.

스키마는 `docs/09-operations.md` §4 (+ "구현 노트 (M8)"). 세 파일의 성격이 다르다:

| 파일 | 누가 쓰나 | 수정 규칙 |
|---|---|---|
| `positions.yaml` | L5 매매계획 → 사람이 체결 반영 · `msa check` 는 **읽기만** | 자유 |
| `watchlist.yaml` | L3/L4 (contested · 범위 밖) · 사람 | 자유 |
| `rejections.yaml` | 스캔이 행 추가 · 분기 감사가 `r_12m`/`r_24m` 채움 | **기각 시점 필드 불변** |

`rejections.yaml` 은 저장 시 이전 파일과 대조해 위반이면 예외를 던진다.

`rejections.yaml` 의 불변성은 "행 추가는 자유, 기존 행의 `path`~`scan` 은 수정 불가,
`r_12m`·`r_24m` 은 null → 값 한 번만" 이다. 값이 들어간 뒤 다시 바꾸는 것도 거부한다 —
사후 수익률을 고쳐 쓰는 순간 대장이 감사 기록이 아니게 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml

from msa.errors import Immutable, RefusedInput
from msa.io import to_plain
from msa.ops.thesis import REJECTION_PATHS

Role = Literal["anchor", "torque"]
PositionStatus = Literal["open", "closed"]


class StateFileError(RefusedInput, ValueError):
    """스키마 위반 — 조용히 넘어가지 않는다 (`CLAUDE.md` §2)."""


class ImmutableRowChanged(Immutable, StateFileError):
    """`rejections.yaml` 의 기각 시점 필드를 바꾸려 했다."""


def _d(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def _req(d: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in d or d[key] is None:
        raise StateFileError(f"{ctx}: 필수 필드 없음 `{key}`")
    return d[key]


# ---------------------------------------------------------------------------
# positions.yaml
# ---------------------------------------------------------------------------


@dataclass
class LadderStep:
    """사다리 한 단. `trigger_pct` 는 초기 진입가 대비 하락률(양수, 예 0.13). 1단은 0."""

    step: int
    weight: float  # 목표 비중 대비 배분 (예 0.50)
    trigger_pct: float
    trigger_price: float | None = None  # 초기가 × (1 − trigger_pct). 1단은 진입가
    filled_date: date | None = None
    filled_price: float | None = None
    filled_shares: float | None = None

    @property
    def filled(self) -> bool:
        return self.filled_price is not None


@dataclass
class TpLevel:
    """익절 단계 (docs/07 §5). `price` 가 있으면 기계가 가격 조건을 본다.

    `condition` 은 사람이 읽는 문구 (예 "밸류 P50 회복 또는 +2R"). 밸류 백분위 조건은 가격이
    아니므로 `manual` 로 분류된다 — 가격 조건(+2R · 직전 고점 50%)만 `price` 로 환산해 둔다.
    """

    level: Literal["tp1", "tp2", "runner"]
    fraction: float  # 물량 (1/3)
    condition: str
    price: float | None = None
    filled_date: date | None = None
    filled_price: float | None = None

    @property
    def filled(self) -> bool:
        return self.filled_price is not None


@dataclass
class Position:
    """보유 포지션 1건 = 종목 1개. 같은 테마의 종목이 여럿이면 행이 여럿이다.

    `msa check` 가 쓰는 필드 (docs/09 §4 구현 노트 M8):
      ticker · theme · role · target_weight · opened_at · entry_price · ladder[] ·
      tier2_stop_price · tier2_basis · time_stop_date · horizon_months · tp[] ·
      runner_trail_pct · thesis_snapshot · journal_entry · status
    """

    ticker: str
    theme: str
    role: Role
    target_weight: float
    opened_at: date
    entry_price: float  # 1단 진입가 (사다리·Tier-2 '초기가 대비 %' 의 기준)
    ladder: list[LadderStep]
    tier2_stop_price: float  # 평단 −35% 를 가격으로 (TP1 후 본전으로 상향)
    time_stop_date: date  # opened_at + horizon 상한 개월
    horizon_months: tuple[int, int]
    thesis_snapshot: str  # journal/....thesis.yaml (상대 경로)
    journal_entry: str  # journal/....md
    tier2_basis: Literal["avg_minus_35", "breakeven"] = "avg_minus_35"
    tp: list[TpLevel] = field(default_factory=list)
    runner_trail_pct: float = 0.25
    runner_ma_weeks: int = 10
    status: PositionStatus = "open"
    closed_at: date | None = None
    note: str = ""

    @property
    def avg_price(self) -> float | None:
        """체결된 사다리 단의 비중 가중 평단. 체결이 없으면 None."""
        fills = [(s.weight, s.filled_price) for s in self.ladder if s.filled_price is not None]
        if not fills:
            return None
        w = sum(f[0] for f in fills)
        return sum(a * b for a, b in fills) / w if w > 0 else None

    @property
    def tp1_filled(self) -> bool:
        return any(t.level == "tp1" and t.filled for t in self.tp)


def _ladder_from(d: dict[str, Any], ctx: str) -> LadderStep:
    return LadderStep(
        step=int(_req(d, "step", ctx)),
        weight=float(_req(d, "weight", ctx)),
        trigger_pct=float(_req(d, "trigger_pct", ctx)),
        trigger_price=None if d.get("trigger_price") is None else float(d["trigger_price"]),
        filled_date=_d(d.get("filled_date")),
        filled_price=None if d.get("filled_price") is None else float(d["filled_price"]),
        filled_shares=None if d.get("filled_shares") is None else float(d["filled_shares"]),
    )


def _tp_from(d: dict[str, Any], ctx: str) -> TpLevel:
    lvl = _req(d, "level", ctx)
    if lvl not in ("tp1", "tp2", "runner"):
        raise StateFileError(f"{ctx}: tp.level 값 불가 {lvl!r}")
    return TpLevel(
        level=lvl,
        fraction=float(d.get("fraction", 1 / 3)),
        condition=str(_req(d, "condition", ctx)),
        price=None if d.get("price") is None else float(d["price"]),
        filled_date=_d(d.get("filled_date")),
        filled_price=None if d.get("filled_price") is None else float(d["filled_price"]),
    )


def position_from_dict(d: dict[str, Any]) -> Position:
    ctx = f"positions[{d.get('ticker', '?')}]"
    role = _req(d, "role", ctx)
    if role not in ("anchor", "torque"):
        raise StateFileError(f"{ctx}: role 값 불가 {role!r}")
    hz = _req(d, "horizon_months", ctx)
    if not (isinstance(hz, list | tuple) and len(hz) == 2):
        raise StateFileError(f"{ctx}: horizon_months 는 [하한, 상한] 이어야 한다")
    ladder = [_ladder_from(x, ctx) for x in _req(d, "ladder", ctx)]
    if not ladder:
        raise StateFileError(f"{ctx}: ladder 가 비어 있다")
    basis = d.get("tier2_basis", "avg_minus_35")
    if basis not in ("avg_minus_35", "breakeven"):
        raise StateFileError(f"{ctx}: tier2_basis 값 불가 {basis!r}")
    status = d.get("status", "open")
    if status not in ("open", "closed"):
        raise StateFileError(f"{ctx}: status 값 불가 {status!r}")
    return Position(
        ticker=str(_req(d, "ticker", ctx)).upper(),
        theme=str(_req(d, "theme", ctx)),
        role=role,
        target_weight=float(_req(d, "target_weight", ctx)),
        opened_at=_d(_req(d, "opened_at", ctx)) or date.min,
        entry_price=float(_req(d, "entry_price", ctx)),
        ladder=ladder,
        tier2_stop_price=float(_req(d, "tier2_stop_price", ctx)),
        tier2_basis=basis,
        time_stop_date=_d(_req(d, "time_stop_date", ctx)) or date.min,
        horizon_months=(int(hz[0]), int(hz[1])),
        tp=[_tp_from(x, ctx) for x in d.get("tp", []) or []],
        runner_trail_pct=float(d.get("runner_trail_pct", 0.25)),
        runner_ma_weeks=int(d.get("runner_ma_weeks", 10)),
        thesis_snapshot=str(_req(d, "thesis_snapshot", ctx)),
        journal_entry=str(_req(d, "journal_entry", ctx)),
        status=status,
        closed_at=_d(d.get("closed_at")),
        note=str(d.get("note", "")),
    )


@dataclass
class PositionsFile:
    asof: date
    positions: list[Position]

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "open"]


_plain = to_plain  # dataclass → yaml 친화 dict (date 는 ISO 문자열, tuple 은 list)


def _dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(_plain(obj), allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_positions(path: Path) -> PositionsFile:
    """없으면 빈 파일로 취급한다 — 포지션이 없는 것은 결측이 아니라 사실이다."""
    raw = _load_yaml(path)
    if raw is None:
        return PositionsFile(asof=date.today(), positions=[])
    if not isinstance(raw, dict) or "positions" not in raw:
        raise StateFileError(f"{path}: 최상위에 `asof` 와 `positions` 가 있어야 한다")
    return PositionsFile(
        asof=_d(raw.get("asof")) or date.today(),
        positions=[position_from_dict(x) for x in raw["positions"] or []],
    )


def save_positions(path: Path, pf: PositionsFile) -> None:
    _dump({"asof": pf.asof, "positions": pf.positions}, path)


# ---------------------------------------------------------------------------
# watchlist.yaml
# ---------------------------------------------------------------------------

WatchReason = Literal["contested", "axis1_unavailable", "awaiting_condition", "human"]


@dataclass
class WatchItem:
    """편입 전 관찰 테마 + 대기 조건 (docs/09 §4). contested 는 여기만 올라간다 (04 §3.1)."""

    theme: str
    added_at: date
    reason: WatchReason
    waiting_condition: str  # 무엇이 관측되면 재검토하는가 — 비면 관찰이 아니라 방치다
    scan: str  # state/scans/<date>/
    thesis_snapshot: str | None = None
    journal: str | None = None
    scoreboard_rank: int | None = None
    note: str = ""


def watch_from_dict(d: dict[str, Any]) -> WatchItem:
    ctx = f"watchlist[{d.get('theme', '?')}]"
    reason = _req(d, "reason", ctx)
    if reason not in ("contested", "axis1_unavailable", "awaiting_condition", "human"):
        raise StateFileError(f"{ctx}: reason 값 불가 {reason!r}")
    cond = str(_req(d, "waiting_condition", ctx)).strip()
    if not cond:
        raise StateFileError(f"{ctx}: waiting_condition 이 비어 있다")
    return WatchItem(
        theme=str(_req(d, "theme", ctx)),
        added_at=_d(_req(d, "added_at", ctx)) or date.min,
        reason=reason,
        waiting_condition=cond,
        scan=str(_req(d, "scan", ctx)),
        thesis_snapshot=d.get("thesis_snapshot"),
        journal=d.get("journal"),
        scoreboard_rank=None if d.get("scoreboard_rank") is None else int(d["scoreboard_rank"]),
        note=str(d.get("note", "")),
    )


def load_watchlist(path: Path) -> list[WatchItem]:
    raw = _load_yaml(path)
    if raw is None:
        return []
    items = raw["watchlist"] if isinstance(raw, dict) else raw
    return [watch_from_dict(x) for x in items or []]


def save_watchlist(path: Path, items: list[WatchItem]) -> None:
    _dump({"watchlist": items}, path)


# ---------------------------------------------------------------------------
# rejections.yaml — 기각 대장
# ---------------------------------------------------------------------------

#: 기각 시점 필드 — 한 번 쓰면 바꾸지 않는다 (docs/09 §4 "path 이하 scan 까지" + 식별자).
IMMUTABLE_FIELDS: tuple[str, ...] = (
    "theme",
    "rejected_at",
    "path",
    "reason",
    "cycle_confidence",
    "scoreboard_rank",
    "journal",
    "scan",
)
FILLABLE_FIELDS: tuple[str, ...] = ("r_12m", "r_24m")


@dataclass
class Rejection:
    theme: str
    rejected_at: date
    path: str  # REJECTION_PATHS
    reason: str
    cycle_confidence: float | None
    scoreboard_rank: int | None
    journal: str
    scan: str
    r_12m: float | None = None
    r_24m: float | None = None
    #: 축별 판정 스냅샷 — (a)(b) 집계용. 선택이지만 있으면 불변 필드로 취급한다.
    axis_verdicts: dict[str, str] | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.theme, self.rejected_at.isoformat())


def rejection_from_dict(d: dict[str, Any]) -> Rejection:
    ctx = f"rejections[{d.get('theme', '?')}@{d.get('rejected_at', '?')}]"
    path = _req(d, "path", ctx)
    if path not in REJECTION_PATHS:
        raise StateFileError(f"{ctx}: path 값 불가 {path!r} (허용 {REJECTION_PATHS})")
    if "cycle_confidence" not in d:
        raise StateFileError(f"{ctx}: cycle_confidence 는 값 또는 null 로 반드시 적는다")
    c = d["cycle_confidence"]
    return Rejection(
        theme=str(_req(d, "theme", ctx)),
        rejected_at=_d(_req(d, "rejected_at", ctx)) or date.min,
        path=path,
        reason=str(_req(d, "reason", ctx)),
        cycle_confidence=None if c is None else float(c),
        scoreboard_rank=None if d.get("scoreboard_rank") is None else int(d["scoreboard_rank"]),
        journal=str(_req(d, "journal", ctx)),
        scan=str(_req(d, "scan", ctx)),
        r_12m=None if d.get("r_12m") is None else float(d["r_12m"]),
        r_24m=None if d.get("r_24m") is None else float(d["r_24m"]),
        axis_verdicts=d.get("axis_verdicts"),
    )


def load_rejections(path: Path) -> list[Rejection]:
    raw = _load_yaml(path)
    if raw is None:
        return []
    rows = raw["rejections"] if isinstance(raw, dict) else raw
    return [rejection_from_dict(x) for x in rows or []]


def _immutable_view(r: Rejection) -> dict[str, Any]:
    v = {k: _plain(getattr(r, k)) for k in IMMUTABLE_FIELDS}
    v["axis_verdicts"] = r.axis_verdicts
    return v


def check_rejections_append_only(previous: list[Rejection], new: list[Rejection]) -> None:
    """`previous` 의 모든 행이 `new` 에 있고 불변 필드가 같고, 채워진 r_* 가 바뀌지 않았는가."""
    by_key = {r.key: r for r in new}
    for old in previous:
        cur = by_key.get(old.key)
        if cur is None:
            raise ImmutableRowChanged(f"기각 대장 행 삭제 불가: {old.key}")
        if _immutable_view(old) != _immutable_view(cur):
            raise ImmutableRowChanged(
                f"기각 대장 행 {old.key} 의 기각 시점 필드가 바뀌었다 — "
                f"{_immutable_view(old)} → {_immutable_view(cur)}"
            )
        for f in FILLABLE_FIELDS:
            ov, nv = getattr(old, f), getattr(cur, f)
            if ov is not None and nv != ov:
                raise ImmutableRowChanged(
                    f"기각 대장 행 {old.key} 의 {f} 는 이미 {ov} 로 채워졌다 → {nv} 로 바꿀 수 없다"
                )
    keys = [r.key for r in new]
    if len(keys) != len(set(keys)):
        raise StateFileError("기각 대장에 (theme, rejected_at) 중복 행이 있다")


def save_rejections(path: Path, rows: list[Rejection]) -> None:
    """이전 파일과 대조해 불변 규칙을 확인한 뒤에만 쓴다."""
    previous = load_rejections(path)
    check_rejections_append_only(previous, rows)
    for r in rows:
        if r.path not in REJECTION_PATHS:
            raise StateFileError(f"path 값 불가 {r.path!r}")
    _dump({"rejections": rows}, path)
