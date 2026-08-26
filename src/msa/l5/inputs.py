"""L5 입력 계약 — L4 종목 후보 · L3/사람 논지 · 케이스 스터디 표.

세 입력이 전부 **파일**이다. L4(`msa picks`)·L3(`msa research`)가 무엇을 내든 이 파일 형식으로
떨어뜨리면 L5 는 그대로 돈다 — 두 계층이 동시에 만들어지는 동안 결합을 파일 하나로 제한한다.

## 1. `picks.csv` — 테마별 종목 후보 (L4 `docs/06` §5~§7 바벨 구성)

| 열 | 필수 | 뜻 |
|---|---|---|
| `theme` | ✓ | `state/themes.yaml` 의 id |
| `ticker` | ✓ | 종목 |
| `role` | ✓ | `eligible` (2026-08-24 이후 L4 의 유일한 값) · `anchor` · `torque` ·
|  |  | `royalty` · `midstream` · `etf` |
| `entry_price` | | 계획 기준가 (사다리·스탑·TP 가격). 없으면 가격은 `—` 로 남고 비율만 적는다 |
| `adv20_usd` | | 20일 평균 달러 거래대금 — C4 유동성. 없으면 C4 를 적용하지 못했다고 **표기**한다 |
| `rank_score` | | L4 종합 점수 — **표기용.** L5 의 어느 모듈도 읽지 않고 L4 선정에도 안 쓰인다 |
| `idio_vol_ann` | | 종목 고유 변동성(연). 공분산을 테마 지수에서 사상할 때 대각에 더한다 (§risk) |
| `min_weight` | | 하한 비중 (기본 0). 하한이 있어야만 infeasible 이 생긴다 (`optimize`) |
| `split_first_leg` | | L4 의 M 축이 낮아 1단을 25%+25% 로 나눈다 (`docs/07` §3). `true/false` |
| `tp_p50_price` · `tp_p75_price` | | 밸류 P50·P75 회복가 (TP1·TP2). 없으면 R 배수·고점 회복만 |
| `prev_cycle_peak_price` | | 직전 사이클 고점가 (TP2 의 "고점 50% 회복") |
| `notes` | | 표기용 |

## 2. `theses/<theme_id>.yaml` — 테마 논지와 확신도

`docs/specs/thesis.schema.yaml` 의 부분집합을 읽는다. 여기서 **반드시** 있어야 하는 것:

- `cycle_confidence` ∈ [0,1] — `docs/04` §4 규칙으로 산출한 값
- `cycle_confidence_source` ∈ {`human`, `referee`} — **누가 산출했는가.** M6 구간은 사람이다
  (`docs/11-roadmap.md` "M6 구간에 `c` 를 누가 만드는가"). 스키마에는 없는 필드지만 저널
  진입 항목이 요구하는 것과 같은 정보이며(`docs/09` §2), 계획서에 출처로 찍힌다
- `invalidations` ≥ 1건 — 비면 거부 (`CLAUDE.md` §5). Tier-1 스탑의 근거다
- `horizon_months: [lo, hi]` — 시간 스탑 = 기준일 + hi 개월

선택: `triggers` · `gate_result.portfolio_eligible` (false 면 편입 불가로 제외하고
그 사실을 적는다) · `value_trap_axes.unit_demand.axis1_available`. 그 밖의 필드
(`key_uncertainties` · `generated_at` · …) 는 읽지 않는다 — 전문은 저널에 있다.

## 3. `cases.yaml` — 케이스 스터디 표 (`L_i` 의 사망 사례 낙폭 출처)

`state/cases/cases.yaml` (예시: `docs/specs/cases.example.yaml`). 행 하나가 사례 하나:

```yaml
cases:
  - id: thermal_coal_2012
    name_ko: 석탄(연료탄) 2012-2016
    type: death                      # cycle | death
    theme_ids: [coal]                # 이 사례가 적용되는 테마 id (0개 이상)
    clusters: [fossil]               # 또는 correlation_cluster 로 넓게 (0개 이상)
    drawdown_peak_to_trough: 0.90    # 고점→저점 낙폭 (양수 비율). 모르면 null
    peak_date: 2011-04               # YYYY-MM 또는 YYYY-MM-DD
    trough_date: 2016-01
    verified: false                  # true 가 아니면 L_i 에 쓰지 않는다
    sources: []                      # [{url, title, date}] — 비어 있으면 verified 일 수 없다
    notes: ""
```

`L_i` 에 쓰이는 행의 조건은 **`type: death` · `verified: true` · `sources` ≥ 1 · 낙폭 not null**
전부다. 출처 없는 낙폭은 저장될 수는 있어도 **예산 제약의 숫자가 되지 않는다** (`CLAUDE.md` §3).
테마 매칭은 `theme_ids` 우선, 없으면 `clusters` 로 넓힌다. 여러 행이 맞으면 **낙폭이 가장 큰 행**
(보수적) 을 쓰고 그 id 를 출처로 적는다.
"""

from __future__ import annotations

import csv
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from msa import coerce
from msa.errors import RefusedInput
from msa.io import load_yaml_mapping
from msa.thesis import CONFIDENCE_PROVENANCE, read_thesis_yaml

log = logging.getLogger(__name__)

#: `eligible` — L4 가 2026-08-24 부터 내는 값. "하드 제외를 통과했다" 뿐이고 행을 가르지 않는다
#: (선정 = 적격 전부 · 테마 내 동일가중; `pipeline.assemble` 머리말 · `l4.picks.SELECTION_GROUP`).
#: 나머지 다섯은 옛 산출물과 사람이 손으로 쓰는 `picks.csv` 를 위해 그대로 남는다.
PICK_ROLES: tuple[str, ...] = ("eligible", "anchor", "torque", "royalty", "midstream", "etf")
#: 확신도를 누가 만들었는가 — L3 스키마의 enum 과 같은 값 (`msa.thesis`).
CONFIDENCE_SOURCES: tuple[str, ...] = CONFIDENCE_PROVENANCE
CASE_TYPES: tuple[str, ...] = ("cycle", "death")

PICKS_REQUIRED_COLUMNS: tuple[str, ...] = ("theme", "ticker", "role")
#: 선택 실수 열 — `Pick` 의 `float | None` 필드와 이름이 같다 (dict 로 바로 넘긴다).
_FLOAT_COLS: tuple[str, ...] = (
    "entry_price",
    "adv20_usd",
    "rank_score",
    "idio_vol_ann",
    "tp_p50_price",
    "tp_p75_price",
    "prev_cycle_peak_price",
)
PICKS_OPTIONAL_COLUMNS: tuple[str, ...] = (*_FLOAT_COLS, "min_weight", "split_first_leg", "notes")


#: 익절가가 진입가보다 낮으면 **손실 구간에서 매도 신호가 난다.** `positions._min_price` 가
#: `+2R` 과 이 값 중 낮은 쪽을 TP1 로 쓰고, `ops/check` 는 `close >= t.price` 로 도달을
#: 판정하므로 첫 점검에서 바로 `TP_MET` 이 뜬다 — 사람에게 손실 상태로 1/3 을 팔라고 한다
#: (2026-08-26 코드 리뷰). 값을 손보지 않고 **거부한다** (`CLAUDE.md` §2).
_TP_PRICE_COLS: tuple[str, ...] = ("tp_p50_price", "tp_p75_price")


def _check_tp_above_entry(floats: Mapping[str, float | None], *, where: str) -> None:
    entry = floats.get("entry_price")
    if entry is None or entry <= 0:
        return
    for c in _TP_PRICE_COLS:
        v = floats.get(c)
        if v is not None and v <= entry:
            raise InputError(
                f"{where}: {c}={v:g} 가 entry_price={entry:g} 이하다 — 익절가가 진입가보다 "
                "낮으면 첫 점검에서 손실 상태로 TP 도달 신호가 난다. 값을 고치거나 비워라."
            )


class InputError(RefusedInput, ValueError):
    """입력 파일이 계약을 어긴다. 조용히 건너뛰지 않고 던진다 (`CLAUDE.md` §2)."""


# ---------------------------------------------------------------- picks


@dataclass(frozen=True)
class Pick:
    """L4 가 넘기는 종목 후보 하나. `picks.csv` 의 한 행."""

    theme: str
    ticker: str
    role: str
    entry_price: float | None = None
    adv20_usd: float | None = None
    rank_score: float | None = None
    idio_vol_ann: float | None = None
    min_weight: float = 0.0
    split_first_leg: bool = False
    tp_p50_price: float | None = None
    tp_p75_price: float | None = None
    prev_cycle_peak_price: float | None = None
    notes: str = ""

    @property
    def is_anchor(self) -> bool:
        """앵커 성격 — `docs/06` §5 의 앵커 · 로열티 · 미드스트림.

        `eligible` 은 앵커가 아니다 — L4 가 더 이상 앵커를 **지정하지 않기** 때문이지 앵커
        비중을 0 으로 정한 것이 아니다 (`pipeline.assemble` 머리말 "`role` — 2026-08-24 개정").
        """
        return self.role in ("anchor", "royalty", "midstream")

    @property
    def barbell_labeled(self) -> bool:
        """이 행이 **바벨 라벨을 갖고 있는가** — `is_anchor` 가 False 인 두 가지를 가른다.

        `role='torque'` 는 "앵커가 아니다" 라는 **판정**이고, `role='eligible'` 은 L4 가
        판정을 **하지 않았다**는 뜻이다 (2026-08-24 개정). 앵커:토크 비율은 후자에서
        의미가 없으므로 계획서가 0:100 이라고 단언하면 안 된다 (`run.anchor_share`).
        """
        return self.role != "eligible"


def _opt_float(raw: str | None, *, field_name: str, where: str) -> float | None:
    """빈 값·NA 토큰은 None, 숫자가 아니면 예외 (`msa.coerce` 는 "모르면 None" — 여기서 거른다)."""
    if coerce.opt_str(raw) is None or str(raw).strip().lower() in coerce.NA_TOKENS:
        return None
    v = coerce.opt_float(raw)
    if v is None:
        raise InputError(f"{where}: {field_name}={raw!r} 는 숫자가 아니다")
    return v


def _opt_bool(raw: str | None, *, field_name: str, where: str) -> bool:
    """빈 값은 False, true/false 꼴이 아니면 예외."""
    v = coerce.opt_bool(raw)
    if v is None:
        if raw is None:
            return False
        raise InputError(f"{where}: {field_name}={raw!r} 는 true/false 여야 한다")
    return v


def load_picks(path: Path | str) -> list[Pick]:
    """`picks.csv` 를 읽고 계약을 검증한다. 중복 티커·모르는 role 은 예외."""
    p = Path(path)
    if not p.exists():
        raise InputError(f"picks 파일이 없다: {p}")
    with p.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        cols = tuple(reader.fieldnames or ())
        missing = [c for c in PICKS_REQUIRED_COLUMNS if c not in cols]
        if missing:
            raise InputError(f"{p}: 필수 열 누락 {missing} (있는 열: {list(cols)})")
        unknown = [c for c in cols if c not in PICKS_REQUIRED_COLUMNS + PICKS_OPTIONAL_COLUMNS]
        if unknown:
            raise InputError(f"{p}: 모르는 열 {unknown} — 계약 밖의 열은 조용히 버리지 않는다")
        picks: list[Pick] = []
        seen: set[str] = set()
        for i, row in enumerate(reader, start=2):
            where = f"{p.name}:{i}"
            theme = (row.get("theme") or "").strip()
            ticker = (row.get("ticker") or "").strip().upper()
            role = (row.get("role") or "").strip().lower()
            if not theme or not ticker:
                raise InputError(f"{where}: theme/ticker 가 비었다")
            if role not in PICK_ROLES:
                raise InputError(f"{where}: role={role!r} 허용값 {PICK_ROLES}")
            if ticker in seen:
                raise InputError(f"{where}: 티커 중복 {ticker} — 한 종목은 한 테마에만 배정된다")
            seen.add(ticker)
            mw = _opt_float(row.get("min_weight"), field_name="min_weight", where=where) or 0.0
            if mw < 0 or mw > 1:
                raise InputError(f"{where}: min_weight={mw} 는 [0,1] 이어야 한다")
            floats = {c: _opt_float(row.get(c), field_name=c, where=where) for c in _FLOAT_COLS}
            _check_tp_above_entry(floats, where=where)
            picks.append(
                Pick(
                    theme=theme,
                    ticker=ticker,
                    role=role,
                    min_weight=mw,
                    split_first_leg=_opt_bool(
                        row.get("split_first_leg"), field_name="split_first_leg", where=where
                    ),
                    notes=(row.get("notes") or "").strip(),
                    **floats,
                )
            )
    if not picks:
        raise InputError(f"{p}: 후보 종목이 0개다")
    return picks


# ---------------------------------------------------------------- theses


@dataclass(frozen=True)
class ThesisInput:
    """L5 가 논지 객체에서 쓰는 부분. 전문은 저널에 있다 (`docs/09` §2)."""

    theme: str
    cycle_confidence: float
    confidence_source: str  # human | referee
    horizon_months: tuple[int, int]
    invalidations: tuple[str, ...]
    triggers: tuple[str, ...] = ()
    portfolio_eligible: bool = True
    gate_status: str | None = None
    axis1_available: bool | None = None
    source_path: str = ""


#: 무효화 조치 → 계획서에 찍는 말. 조치를 버리면 **전부 전량 청산으로 읽힌다** —
#: 2026-08-25 실측: 11건 중 9건이 청산이 아닌 조치인데 계획서는 11건을 Tier-1(즉시 전량
#: 청산)로 나열하고 있었다. `docs/specs/thesis.schema.yaml` 의 정의를 그대로 옮긴다.
ACTION_TEXT: dict[str, str] = {
    "exit": "전량 청산",
    "halve": "절반 축소",
    "freeze_ladder": "사다리 동결(물타기 중단·보유 유지)",
}


def _observables(
    raw: Any, *, field_name: str, where: str, with_action: bool = False
) -> tuple[str, ...]:
    """관측 조건 문자열. `with_action` 이면 **조치를 앞에 붙인다.**

    조치가 빠지면 `freeze_ladder`(물타기만 중단)와 `exit`(전량 청산)이 같은 줄로 보인다.
    계획서를 그대로 집행하면 보유해야 할 것을 파는 일이 생긴다.
    """
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise InputError(f"{where}: {field_name} 는 목록이어야 한다")
    out: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            obs = item.get("observable")
            if not obs:
                raise InputError(f"{where}: {field_name} 항목에 observable 이 없다: {item!r}")
            src = item.get("source")
            body = f"{obs} [{src}]" if src else str(obs)
            if with_action:
                act = str(item.get("action") or "")
                # 모르는 조치를 조용히 청산으로 만들지 않는다 — 있는 그대로 적는다.
                label = ACTION_TEXT.get(act, f"조치 미상({act})" if act else "조치 미기재")
                body = f"[{label}] {body}"
            out.append(body)
        else:
            out.append(str(item))
    return tuple(out)


def parse_thesis(raw: Mapping[str, Any], *, where: str = "<thesis>") -> ThesisInput:
    """thesis 객체(dict)에서 L5 가 쓰는 필드를 꺼내고 검증한다."""
    theme = raw.get("theme_id") or raw.get("theme")
    if not theme or not isinstance(theme, str):
        raise InputError(f"{where}: theme_id 가 없다")
    c = raw.get("cycle_confidence")
    if not isinstance(c, int | float) or isinstance(c, bool):
        raise InputError(f"{where}: cycle_confidence 가 숫자가 아니다: {c!r}")
    if not 0.0 <= float(c) <= 1.0:
        raise InputError(f"{where}: cycle_confidence={c} 는 [0,1] 이어야 한다")
    src = raw.get("cycle_confidence_source")
    if src not in CONFIDENCE_SOURCES:
        raise InputError(
            f"{where}: cycle_confidence_source 허용값 {CONFIDENCE_SOURCES}: {src!r} — "
            "누가 c 를 만들었는지 없는 논지는 캘리브레이션 표본이 될 수 없다 (docs/11 M6)"
        )
    inv = _observables(
        raw.get("invalidations"), field_name="invalidations", where=where, with_action=True
    )
    if not inv:
        raise InputError(
            f"{where}: invalidations 가 비었다 — 무효화 조건 없는 논지는 저장할 수 없다 "
            "(CLAUDE.md §5). Tier-1 스탑을 만들 수 없다."
        )
    hz = raw.get("horizon_months")
    if (
        not isinstance(hz, Sequence)
        or isinstance(hz, str)
        or len(hz) != 2
        or not all(isinstance(x, int) and not isinstance(x, bool) for x in hz)
    ):
        raise InputError(f"{where}: horizon_months 는 [lo, hi] 정수 둘이어야 한다: {hz!r}")
    lo, hi = int(hz[0]), int(hz[1])
    if lo <= 0 or hi < lo:
        raise InputError(f"{where}: horizon_months=[{lo},{hi}] 가 올바르지 않다")
    gate = raw.get("gate_result") or {}
    eligible = True
    gate_status: str | None = None
    if isinstance(gate, Mapping):
        gate_status = gate.get("status")
        pe = gate.get("portfolio_eligible")
        if pe is not None:
            eligible = bool(pe)
        if gate_status in ("contested", "rejected"):
            eligible = False
    axes = raw.get("value_trap_axes") or {}
    axis1: bool | None = None
    if isinstance(axes, Mapping):
        ud = axes.get("unit_demand")
        if isinstance(ud, Mapping) and "axis1_available" in ud:
            axis1 = bool(ud["axis1_available"])
    return ThesisInput(
        theme=theme,
        cycle_confidence=float(c),
        confidence_source=str(src),
        horizon_months=(lo, hi),
        invalidations=inv,
        triggers=_observables(raw.get("triggers"), field_name="triggers", where=where),
        portfolio_eligible=eligible,
        gate_status=str(gate_status) if gate_status else None,
        axis1_available=axis1,
        source_path=where,
    )


def load_theses(dir_path: Path | str) -> dict[str, ThesisInput]:
    """`theses/*.yaml` 전부를 읽는다. 같은 테마가 둘이면 예외."""
    d = Path(dir_path)
    if not d.is_dir():
        raise InputError(f"theses 디렉터리가 없다: {d}")
    out: dict[str, ThesisInput] = {}
    files = sorted(list(d.glob("*.yaml")) + list(d.glob("*.yml")))
    if not files:
        raise InputError(f"{d}: thesis 파일이 0개다")
    for f in files:
        try:
            raw = read_thesis_yaml(f)
        except ValueError as e:
            raise InputError(str(e)) from None
        t = parse_thesis(raw, where=str(f))
        if t.theme in out:
            raise InputError(
                f"{f}: 테마 {t.theme} 의 thesis 가 둘이다 ({out[t.theme].source_path})"
            )
        out[t.theme] = t
    return out


# ---------------------------------------------------------------- cases


@dataclass(frozen=True)
class CaseSource:
    url: str
    title: str = ""
    date: str = ""


@dataclass(frozen=True)
class Case:
    """케이스 스터디 한 건 (`docs/04` §5). `L_i` 의 사망 사례 낙폭이 여기서 나온다."""

    id: str
    name_ko: str
    type: str  # cycle | death
    theme_ids: tuple[str, ...]
    clusters: tuple[str, ...]
    drawdown_peak_to_trough: float | None
    peak_date: str
    trough_date: str
    verified: bool
    sources: tuple[CaseSource, ...]
    notes: str = ""

    @property
    def usable_for_loss(self) -> bool:
        """`L_i` 에 쓸 수 있는가 — 사망·검증됨·출처 ≥1·낙폭 있음 (`unusable_reason` 이 없음)."""
        return self.unusable_reason() is None

    def unusable_reason(self) -> str | None:
        if self.type != "death":
            return f"{self.id}: type={self.type} (사망 사례만 L_i 에 쓴다)"
        if self.drawdown_peak_to_trough is None:
            return f"{self.id}: 낙폭 null"
        if not self.sources:
            return f"{self.id}: sources 비어 있음 — 출처 없는 낙폭은 예산 숫자가 되지 않는다"
        if not self.verified:
            return f"{self.id}: verified=false"
        return None

    def matches(self, theme_id: str, cluster: str | None) -> bool:
        if theme_id in self.theme_ids:
            return True
        return cluster is not None and cluster in self.clusters


@dataclass(frozen=True)
class CaseTable:
    cases: tuple[Case, ...]
    path: str
    exists: bool = True

    def __len__(self) -> int:
        return len(self.cases)

    def for_theme(self, theme_id: str, cluster: str | None) -> list[Case]:
        return [c for c in self.cases if c.matches(theme_id, cluster)]


def _parse_case(raw: Mapping[str, Any], where: str) -> Case:
    cid = raw.get("id")
    if not cid or not isinstance(cid, str):
        raise InputError(f"{where}: id 없는 케이스 행: {raw!r}")
    ctype = raw.get("type")
    if ctype not in CASE_TYPES:
        raise InputError(f"{where}: {cid}: type 허용값 {CASE_TYPES}: {ctype!r}")
    dd = raw.get("drawdown_peak_to_trough")
    ddv: float | None
    if dd is None:
        ddv = None
    elif isinstance(dd, int | float) and not isinstance(dd, bool):
        ddv = float(dd)
        if not 0.0 < ddv <= 1.0:
            raise InputError(f"{where}: {cid}: 낙폭은 (0,1] 의 양수 비율이어야 한다: {dd!r}")
    else:
        raise InputError(f"{where}: {cid}: drawdown_peak_to_trough={dd!r} 는 숫자/null 이어야 한다")
    srcs_raw = raw.get("sources") or []
    if not isinstance(srcs_raw, Sequence) or isinstance(srcs_raw, str):
        raise InputError(f"{where}: {cid}: sources 는 목록이어야 한다")
    srcs: list[CaseSource] = []
    for s in srcs_raw:
        if isinstance(s, Mapping):
            url = s.get("url")
            if not url:
                raise InputError(f"{where}: {cid}: source 에 url 이 없다: {s!r}")
            srcs.append(
                CaseSource(url=str(url), title=str(s.get("title", "")), date=str(s.get("date", "")))
            )
        else:
            srcs.append(CaseSource(url=str(s)))
    verified = bool(raw.get("verified", False))
    if verified and not srcs:
        raise InputError(f"{where}: {cid}: verified=true 인데 sources 가 비었다 (CLAUDE.md §3)")
    return Case(
        id=cid,
        name_ko=str(raw.get("name_ko", cid)),
        type=str(ctype),
        theme_ids=tuple(str(x) for x in (raw.get("theme_ids") or [])),
        clusters=tuple(str(x) for x in (raw.get("clusters") or [])),
        drawdown_peak_to_trough=ddv,
        peak_date=str(raw.get("peak_date", "") or ""),
        trough_date=str(raw.get("trough_date", "") or ""),
        verified=verified,
        sources=tuple(srcs),
        notes=str(raw.get("notes", "") or ""),
    )


def load_cases(path: Path | str | None) -> CaseTable:
    """`cases.yaml` 을 읽는다. **파일이 없으면 빈 표**를 돌려주되 `exists=False` 로 표시한다 —
    그 사실은 진단·계획서에 찍힌다 (케이스 없음 → `L_i` 형성 불가, `docs/11` M6)."""
    if path is None:
        return CaseTable(cases=(), path="", exists=False)
    p = Path(path)
    if not p.exists():
        log.warning(
            "cases: 파일 없음 %s — 모든 테마의 사망 사례 낙폭이 비어 C1-(ii) 를 못 만든다", p
        )
        return CaseTable(cases=(), path=str(p), exists=False)
    rows = load_yaml_mapping(p, required_keys=("cases",), err=InputError)["cases"] or []
    cases = tuple(_parse_case(r, str(p)) for r in rows)
    dups = sorted(i for i, n in Counter(c.id for c in cases).items() if n > 1)
    if dups:
        raise InputError(f"{p}: 중복 케이스 id {dups}")
    return CaseTable(cases=cases, path=str(p), exists=True)


# ---------------------------------------------------------------- bundle


@dataclass(frozen=True)
class PortfolioInputs:
    """L5 한 번 실행에 들어가는 입력 묶음."""

    picks: tuple[Pick, ...]
    theses: Mapping[str, ThesisInput]
    cases: CaseTable
    capital_usd: float | None = None
    cluster_caps: Mapping[str, float] = field(default_factory=dict)

    def themes(self) -> list[str]:
        return sorted({p.theme for p in self.picks})


def load_inputs(
    inputs_dir: Path | str,
    *,
    cases_path: Path | str | None,
    capital_usd: float | None = None,
    cluster_caps: Mapping[str, float] | None = None,
) -> PortfolioInputs:
    """`<inputs>/picks.csv` + `<inputs>/theses/` + 케이스 표. thesis 없는 테마의 후보는 예외다 —
    `c` 없이는 목적함수도 C6 도 사다리도 없다 (`docs/11` M6)."""
    d = Path(inputs_dir)
    picks = load_picks(d / "picks.csv")
    theses = load_theses(d / "theses")
    missing = sorted({p.theme for p in picks} - set(theses))
    if missing:
        raise InputError(
            f"thesis 가 없는 테마의 후보가 있다: {missing} — cycle_confidence 없이는 편입 판정을 "
            "내릴 수 없다. theses/<theme>.yaml 을 넣거나 picks 에서 빼라."
        )
    return PortfolioInputs(
        picks=tuple(picks),
        theses=theses,
        cases=load_cases(cases_path),
        capital_usd=capital_usd,
        cluster_caps=dict(cluster_caps or {}),
    )
