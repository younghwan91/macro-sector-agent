"""`state/macro-dag.yaml` 적재·검증 — `scripts/audit_dag.py` 의 검사를 런타임으로 옮긴 것.

두 층의 검사를 구분한다. **둘 다 보고하되 막는 것은 앞쪽뿐이다.**

| 층 | 내용 | 실패 시 |
|---|---|---|
| 스키마 | 필수 필드 · `channel` · `sign` · `strength` · `from` · 와일드카드 | `DagError` — 중단 |
| 커버리지 | `to` 가 테마인가 · in-degree ≥ 2 (공통 인자 제외) | 돌되 미지 타깃은 세어서 제외 |

커버리지 실패를 예외로 올리지 않는 이유: DAG 는 109개 초안 기준으로 선언됐고 테마는 M2 에서
134개로 확정됐다. 그 괴리는 사람이 엣지를 추가해 고치는 일이지 런타임이 숨기거나 멈출 일이
아니다 — 리포트 맨 위에 개수와 이름이 찍힌다.

`state_rule.favorable_when` 은 `"<measure> <op> <threshold>"` 한 줄로 파싱한다.
파싱이 안 되는 규칙(`policy_events` 의 서술형)은 `rule=None` 으로 남고, 그 드라이버는
`drivers.py` 가 따로 다룬다.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from msa.config import paths
from msa.errors import RefusedInput

REQUIRED_EDGE_FIELDS: tuple[str, ...] = ("from", "to", "sign", "strength", "channel", "observable")
STRENGTH_WEIGHT: dict[str, int] = {"strong": 3, "moderate": 2, "weak": 1}
MIN_IN_DEGREE = 2  # docs/11 M4 — 공통 인자 제외

_RULE_RE = re.compile(r"^\s*([a-z_0-9]+)\s*(<=|>=|<|>)\s*(-?[0-9]*\.?[0-9]+)\s*$")


class DagError(RefusedInput, ValueError):
    """스키마 수준 실패 — 전부 모아서 한 번에 던진다."""


@dataclass(frozen=True)
class StateRule:
    """`favorable_when` + `neutral_band` 를 파싱한 것.

    `band_lo/band_hi` 가 **방향 상태**의 경계다 (측정값 > band_hi → +1, < band_lo → −1).
    `op/threshold` 는 '우호' 판정(표시용). `neutral_band` 가 없으면 밴드 = [threshold, threshold].
    """

    measure: str
    op: str
    threshold: float
    band_lo: float
    band_hi: float
    raw: str

    def favorable(self, value: float) -> bool:
        if self.op == "<":
            return value < self.threshold
        if self.op == "<=":
            return value <= self.threshold
        if self.op == ">":
            return value > self.threshold
        return value >= self.threshold

    def direction(self, value: float) -> int:
        if value > self.band_hi:
            return 1
        if value < self.band_lo:
            return -1
        return 0


@dataclass(frozen=True)
class Driver:
    id: str
    provider: str  # fred | derived | etf | manual | sharadar_derived | agent
    series: tuple[str, ...]  # FRED 시리즈 id 들 (provider=fred/derived)
    symbol: str | None  # ETF 심볼 (provider=etf)
    formula: str | None
    measure: str
    rule: StateRule | None
    common_factor: bool
    fallback: Mapping[str, Any] | None
    note: str
    raw: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True)
class Edge:
    index: int
    source: str
    targets: tuple[str, ...]  # ("*",) 이면 전 테마
    sign: int
    strength: str
    lag_months: tuple[int, int] | None
    channel: str
    observable: str
    evidence: str
    contradicts_when: str
    contradicts_rule: Mapping[str, Any] | None
    common_factor_edge: bool

    @property
    def weight(self) -> int:
        return STRENGTH_WEIGHT[self.strength]

    @property
    def wildcard(self) -> bool:
        return self.targets == ("*",)

    def label(self) -> str:
        to = (
            "*"
            if self.wildcard
            else ",".join(self.targets[:3]) + ("…" if len(self.targets) > 3 else "")
        )
        return f"[{self.index}] {self.source} -> {to}"


@dataclass(frozen=True)
class EdgeTarget:
    """(엣지, 테마) 한 쌍 — tailwind 합산의 단위."""

    edge: Edge
    theme: str


@dataclass(frozen=True)
class MacroDag:
    drivers: tuple[Driver, ...]
    edges: tuple[Edge, ...]
    schema_version: int
    path: Path | None

    def driver(self, driver_id: str) -> Driver:
        for d in self.drivers:
            if d.id == driver_id:
                return d
        raise KeyError(f"드라이버 없음: {driver_id}")

    @property
    def driver_ids(self) -> list[str]:
        return [d.id for d in self.drivers]

    @property
    def common_factors(self) -> list[str]:
        return [d.id for d in self.drivers if d.common_factor]


@dataclass
class DagValidation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unknown_theme_refs: dict[int, list[str]] = field(default_factory=dict)  # edge idx → themes
    undercovered: dict[str, int] = field(default_factory=dict)  # theme → in-degree
    in_degree: dict[str, int] = field(default_factory=dict)  # 공통 인자 제외
    out_degree: dict[str, int] = field(default_factory=dict)
    n_pairs: int = 0
    n_themes: int = 0

    @property
    def schema_ok(self) -> bool:
        return not self.errors

    @property
    def coverage_ok(self) -> bool:
        return not self.unknown_theme_refs and not self.undercovered

    def summary(self) -> str:
        unk = sorted({t for ts in self.unknown_theme_refs.values() for t in ts})
        lines = [
            f"DAG 검증: 스키마 {'통과' if self.schema_ok else f'실패 {len(self.errors)}건'} · "
            f"테마 {self.n_themes} · 테마-엣지 쌍 {self.n_pairs} (공통 인자 제외, 하한 "
            f"{MIN_IN_DEGREE * self.n_themes})",
        ]
        if unk:
            lines.append(
                f"  ! themes.yaml 에 없는 to 테마 {len(unk)}개 (해당 쌍 제외): {', '.join(unk)}"
            )
        if self.undercovered:
            lines.append(
                f"  ! 입력 엣지 {MIN_IN_DEGREE}개 미만 테마 {len(self.undercovered)}개 "
                f"(tailwind 에 undercovered 플래그): "
                + ", ".join(f"{t}({n})" for t, n in sorted(self.undercovered.items()))
            )
        for e in self.errors:
            lines.append(f"  ! {e}")
        return "\n".join(lines)


# ---------------------------------------------------------------- 파싱


def parse_state_rule(raw: Mapping[str, Any] | None, measure: str) -> StateRule | None:
    if not raw:
        return None
    fav = str(raw.get("favorable_when", "")).strip()
    m = _RULE_RE.match(fav)
    if m is None:
        return None
    name, op, thr = m.group(1), m.group(2), float(m.group(3))
    band = raw.get("neutral_band")
    if band is None:
        lo = hi = thr
    else:
        if not (isinstance(band, list) and len(band) == 2):
            raise DagError(f"neutral_band 는 [lo, hi] 여야 한다: {band!r}")
        lo, hi = float(band[0]), float(band[1])
        if lo > hi:
            raise DagError(f"neutral_band lo > hi: {band!r}")
    if name != measure:
        raise DagError(f"favorable_when 의 측정값 `{name}` 이 measure `{measure}` 와 다르다")
    return StateRule(measure=name, op=op, threshold=thr, band_lo=lo, band_hi=hi, raw=fav)


def _parse_driver(raw: Mapping[str, Any], errors: list[str]) -> Driver | None:
    did = str(raw.get("id", "")).strip()
    if not did:
        errors.append(f"드라이버 id 누락: {dict(raw)!r}"[:120])
        return None
    src = raw.get("source")
    if not isinstance(src, Mapping) or "provider" not in src:
        errors.append(f"드라이버 {did}: source.provider 누락")
        return None
    if "state_rule" not in raw:
        errors.append(f"드라이버 {did}: state_rule 누락")
    measure = str(raw.get("measure", "")).strip()
    if not measure:
        errors.append(f"드라이버 {did}: measure 누락")
    series_raw = src.get("series")
    if series_raw is None:
        series: tuple[str, ...] = ()
    elif isinstance(series_raw, str):
        series = (series_raw,)
    else:
        series = tuple(str(s) for s in series_raw)
    try:
        rule = parse_state_rule(raw.get("state_rule"), measure)
    except DagError as e:
        errors.append(f"드라이버 {did}: {e}")
        rule = None
    fb = src.get("fallback")
    return Driver(
        id=did,
        provider=str(src["provider"]),
        series=series,
        symbol=str(src["symbol"]) if "symbol" in src else None,
        formula=str(src["formula"]) if "formula" in src else None,
        measure=measure,
        rule=rule,
        common_factor=bool(raw.get("common_factor", False)),
        fallback=fb if isinstance(fb, Mapping) else None,
        note=" ".join(str(src.get("note", raw.get("note", ""))).split()),
        raw=raw,
    )


def _parse_edge(i: int, raw: Mapping[str, Any], errors: list[str]) -> Edge | None:
    tag = f"엣지[{i}] {raw.get('from')} -> {str(raw.get('to'))[:40]}"
    ok = True
    for f in REQUIRED_EDGE_FIELDS:
        if f not in raw:
            errors.append(f"{tag}: 필수 필드 `{f}` 누락")
            ok = False
    channel = " ".join(str(raw.get("channel", "")).split())
    if not channel:
        errors.append(f"{tag}: `channel` 이 비었다 — 메커니즘 없는 상관은 엣지가 아니다")
        ok = False
    if raw.get("sign") not in (1, -1):
        errors.append(f"{tag}: sign 은 +1 또는 -1 이어야 한다 (현재 {raw.get('sign')!r})")
        ok = False
    if raw.get("strength") not in STRENGTH_WEIGHT:
        errors.append(f"{tag}: strength 가 {sorted(STRENGTH_WEIGHT)} 밖 ({raw.get('strength')!r})")
        ok = False
    if not ok:
        return None
    to = raw["to"]
    targets = tuple(str(t) for t in (to if isinstance(to, list) else [to]))
    lag = raw.get("lag_months")
    lag_t: tuple[int, int] | None = None
    if lag is not None:
        if not (isinstance(lag, list) and len(lag) == 2):
            errors.append(f"{tag}: lag_months 는 [min, max] 여야 한다 ({lag!r})")
        else:
            lag_t = (int(lag[0]), int(lag[1]))
    rule = raw.get("contradicts_rule")
    if rule is not None and not isinstance(rule, Mapping):
        errors.append(f"{tag}: contradicts_rule 은 매핑이어야 한다 ({rule!r})")
        rule = None
    return Edge(
        index=i,
        source=str(raw["from"]),
        targets=targets,
        sign=int(raw["sign"]),
        strength=str(raw["strength"]),
        lag_months=lag_t,
        channel=channel,
        observable=" ".join(str(raw.get("observable", "")).split()),
        evidence=" ".join(str(raw.get("evidence", "")).split()),
        contradicts_when=" ".join(str(raw.get("contradicts_when", "")).split()),
        contradicts_rule=rule,
        common_factor_edge=bool(raw.get("common_factor_edge", False)),
    )


def dag_path() -> Path:
    return paths().dag_yaml


def load_dag(path: Path | str | None = None) -> MacroDag:
    """YAML → `MacroDag`. 스키마 실패는 전부 모아 `DagError` 하나로 던진다."""
    p = Path(path) if path is not None else dag_path()
    if not p.exists():
        raise DagError(f"DAG 파일이 없다: {p}")
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(doc, Mapping) or "drivers" not in doc or "edges" not in doc:
        raise DagError(f"{p}: 최상위에 drivers·edges 가 있어야 한다")
    errors: list[str] = []
    drivers = [d for d in (_parse_driver(r, errors) for r in doc["drivers"]) if d is not None]
    ids = [d.id for d in drivers]
    dup = sorted(d for d, n in Counter(ids).items() if n > 1)
    if dup:
        errors.append(f"드라이버 id 중복: {dup}")
    if not drivers:
        errors.append("드라이버가 0개다")
    edges = [e for e in (_parse_edge(i, r, errors) for i, r in enumerate(doc["edges"])) if e]
    if not edges:
        errors.append("엣지가 0개다")
    cf = {d.id for d in drivers if d.common_factor}
    for e in edges:
        if e.source not in ids:
            errors.append(f"{e.label()}: from `{e.source}` 가 드라이버 목록에 없다")
            continue
        if e.wildcard and e.source not in cf:
            errors.append(f"{e.label()}: 와일드카드 `*` 는 common_factor 드라이버만 쓸 수 있다")
        if not e.wildcard and e.source in cf:
            errors.append(
                f"{e.label()}: common_factor 드라이버가 개별 테마를 지목했다 — "
                "`*` 를 쓰거나 common_factor 를 내려라"
            )
    if errors:
        raise DagError(f"{p}: 스키마 검증 실패 {len(errors)}건\n  " + "\n  ".join(errors))
    return MacroDag(
        drivers=tuple(drivers),
        edges=tuple(edges),
        schema_version=int(doc.get("schema_version", 1)),
        path=p,
    )


# ---------------------------------------------------------------- 커버리지


def validate_dag(dag: MacroDag, theme_ids: Iterable[str]) -> DagValidation:
    """커버리지 검사 — `audit_dag.py` 의 3·6번 항목. 예외를 던지지 않고 결과를 돌려준다."""
    themes = list(dict.fromkeys(theme_ids))
    if not themes:
        raise DagError("테마 목록이 비었다 — 조용한 절단 의심")
    theme_set = set(themes)
    v = DagValidation(n_themes=len(themes))
    in_deg: Counter[str] = Counter({t: 0 for t in themes})
    out_deg: Counter[str] = Counter({d: 0 for d in dag.driver_ids})
    for e in dag.edges:
        if e.wildcard:
            out_deg[e.source] += len(themes)
            continue
        for t in e.targets:
            if t not in theme_set:
                v.unknown_theme_refs.setdefault(e.index, []).append(t)
                continue
            in_deg[t] += 1
            out_deg[e.source] += 1
    v.in_degree = dict(in_deg)
    v.out_degree = dict(out_deg)
    v.n_pairs = sum(in_deg.values())
    v.undercovered = {t: n for t, n in in_deg.items() if n < MIN_IN_DEGREE}
    for d in dag.drivers:
        if "common_factor" not in d.raw:
            v.warnings.append(f"드라이버 {d.id}: common_factor 미선언 (false 로 간주)")
    return v


def expand_edges(dag: MacroDag, theme_ids: Iterable[str]) -> list[EdgeTarget]:
    """(엣지, 테마) 쌍으로 전개. 미지 테마는 건너뛴다 — **개수는 `validate_dag` 가 센다.**"""
    themes = list(dict.fromkeys(theme_ids))
    theme_set = set(themes)
    out: list[EdgeTarget] = []
    for e in dag.edges:
        if e.wildcard:
            out.extend(EdgeTarget(e, t) for t in themes)
            continue
        out.extend(EdgeTarget(e, t) for t in e.targets if t in theme_set)
    return out
