"""테마 버킷 정의 (`state/themes.yaml`) 로더와 구성원 배정.

배정 규칙은 `state/themes.yaml` 머리말과 `scripts/audit_themes.py` 가 쓰는 것과 **하나**다.
감사 스크립트와 스캐너가 다른 규칙으로 구성원을 세면 감사가 통과한 유니버스와 스캔이 도는
유니버스가 달라진다 — 그래서 규칙을 여기 한 곳에 두고 둘 다 이 모듈을 쓴다.

  0. 유니버스 = 보통주 (`msa.data.universe.COMMON_STOCK_CATEGORIES` + 캐나다 보통주).
     감사 스크립트의 `category LIKE '%Common Stock%' AND NOT LIKE '%Preferred%'` 와 같다.
  1. `exclude_tickers` 가 버킷에서 티커를 뺀다.
  2. `include_tickers` 가 티커를 배정하며 `industry_match` 를 덮어쓴다.
  3. 나머지는 `industry_match` 로 배정한다 (라벨 → 버킷은 1:1).
  4. `Shell Companies` 라벨은 어느 버킷에도 배정하지 않는다.

## `physical_ref.kind`

`docs/01-theme-universe.md` §2 의 `physical_ref` 는 `{source, symbol}` 만 적었다. 그러나
축 1 의 `unit_series` 계산은 참조가 **가격**인지 **실물 물량**인지에 따라 갈린다
(`docs/04-value-trap.md` 축 1: 1순위 실물 소비량 → 그대로 쓴다 / 폴백 가격지수 → 동일 구성원
매출을 그것으로 나눈다). M3 에서 이 구분이 없으면 `ALTSALES`(자동차 판매 대수)를 가격으로
나누는 식의 오류가 조용히 들어간다. 그래서 `kind ∈ {price, volume, nominal}` 을 요구한다 —
`nominal` 은 달러 표시 매출(예: 소매판매)로, CPI 로 실질화해 물량으로 쓴다.
`kind` 가 없는 `physical_ref` 는 **로드 시점에 거부한다.** 추정하지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from msa.config import paths
from msa.data.universe import CANADIAN_COMMON_CATEGORIES, COMMON_STOCK_CATEGORIES

log = logging.getLogger(__name__)

#: 영업 실체가 없어 사이클이 정의되지 않는 industry 라벨. 어느 버킷에도 넣지 않는다.
EXCLUDED_LABELS: frozenset[str] = frozenset({"Shell Companies"})

#: `02-cycle-state.md` §7 의 8개 클래스. 이 밖의 값은 로드 시점에 거부한다.
CYCLE_CLASSES: tuple[str, ...] = (
    "commodity_supply",
    "inventory",
    "credit_rate",
    "capex_program",
    "policy_program",
    "discretionary_demand",
    "secular_growth",
    "secular_risk",
)

PHYSICAL_SOURCES: tuple[str, ...] = ("etf", "fred", "manual")
PHYSICAL_KINDS: tuple[str, ...] = ("price", "volume", "nominal")

#: 테마 구성원이 될 수 있는 category. 감사 스크립트의 LIKE 조건과 같은 집합이다.
MEMBER_CATEGORIES: tuple[str, ...] = COMMON_STOCK_CATEGORIES + CANADIAN_COMMON_CATEGORIES


class ThemeSpecError(ValueError):
    """`state/themes.yaml` 이 스키마를 어긴다."""


@dataclass(frozen=True)
class PhysicalRef:
    source: str  # etf | fred | manual
    symbol: str
    kind: str  # price | volume | nominal
    verify: bool = False


@dataclass(frozen=True)
class Theme:
    id: str
    name_ko: str
    parent_sector: str
    cycle_class: str
    industry_match: tuple[str, ...]
    include_tickers: tuple[str, ...]
    exclude_tickers: tuple[str, ...]
    etf_proxy: str | None
    etf_proxy_alt: tuple[str, ...]
    physical_ref: PhysicalRef | None
    correlation_cluster: str | None
    min_constituents: int
    notes: str = ""

    @property
    def axis1_declared(self) -> bool:
        """`physical_ref` 가 있다 = 축 1 을 쓸 수 있다는 **선언**이다 (데이터 가용성과 별개)."""
        return self.physical_ref is not None


@dataclass(frozen=True)
class ThemeSet:
    themes: tuple[Theme, ...]
    schema_version: int
    defaults: Mapping[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.themes)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.themes)

    def by_id(self) -> dict[str, Theme]:
        return {t.id: t for t in self.themes}

    def ids(self) -> list[str]:
        return [t.id for t in self.themes]

    def get(self, theme_id: str) -> Theme:
        try:
            return self.by_id()[theme_id]
        except KeyError:
            raise KeyError(f"모르는 테마 id: {theme_id!r}") from None


def _parse_physical_ref(raw: Any, theme_id: str) -> PhysicalRef | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ThemeSpecError(
            f"{theme_id}: physical_ref 는 객체 {{source, symbol, kind}} 또는 null 이어야 한다: "
            f"{raw!r}"
        )
    src = raw.get("source")
    sym = raw.get("symbol")
    kind = raw.get("kind")
    if src not in PHYSICAL_SOURCES:
        raise ThemeSpecError(f"{theme_id}: physical_ref.source 허용값 {PHYSICAL_SOURCES}: {src!r}")
    if not sym or not isinstance(sym, str):
        raise ThemeSpecError(f"{theme_id}: physical_ref.symbol 이 비었다")
    if kind not in PHYSICAL_KINDS:
        raise ThemeSpecError(
            f"{theme_id}: physical_ref.kind 는 {PHYSICAL_KINDS} 중 하나여야 한다: {kind!r}. "
            "추정하지 않는다 — 가격을 물량으로 쓰면 축 1 이 조용히 틀린다."
        )
    return PhysicalRef(source=src, symbol=sym, kind=kind, verify=bool(raw.get("verify", False)))


def _parse_theme(raw: Mapping[str, Any], defaults: Mapping[str, Any]) -> Theme:
    tid = raw.get("id")
    if not tid or not isinstance(tid, str):
        raise ThemeSpecError(f"id 가 없는 테마 레코드: {raw!r}")
    cc = raw.get("cycle_class")
    if cc not in CYCLE_CLASSES:
        raise ThemeSpecError(f"{tid}: cycle_class 허용값 {CYCLE_CLASSES}: {cc!r}")
    im = raw.get("industry_match") or []
    inc = raw.get("include_tickers") or []
    exc = raw.get("exclude_tickers") or []
    if not im and not inc:
        raise ThemeSpecError(f"{tid}: industry_match 와 include_tickers 가 둘 다 비었다")
    minc = raw.get("min_constituents", defaults.get("min_constituents", 5))
    return Theme(
        id=tid,
        name_ko=str(raw.get("name_ko", tid)),
        parent_sector=str(raw.get("parent_sector", "")),
        cycle_class=cc,
        industry_match=tuple(str(x) for x in im),
        include_tickers=tuple(str(x).upper() for x in inc),
        exclude_tickers=tuple(str(x).upper() for x in exc),
        etf_proxy=(str(raw["etf_proxy"]).upper() if raw.get("etf_proxy") else None),
        etf_proxy_alt=tuple(str(x).upper() for x in (raw.get("etf_proxy_alt") or [])),
        physical_ref=_parse_physical_ref(raw.get("physical_ref"), tid),
        correlation_cluster=(
            str(raw["correlation_cluster"]) if raw.get("correlation_cluster") else None
        ),
        min_constituents=int(minc),
        notes=str(raw.get("notes", "") or ""),
    )


def load_themes(path: Path | str | None = None) -> ThemeSet:
    """`state/themes.yaml` 을 읽고 스키마를 검증한다.

    검증 실패는 예외다 — 잘못된 정의로 스캔이 도는 것보다 낫다.
    """
    p = Path(path) if path is not None else paths().state / "themes.yaml"
    if not p.exists():
        raise ThemeSpecError(f"테마 정의 파일이 없다: {p}")
    spec = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(spec, Mapping) or "themes" not in spec:
        raise ThemeSpecError(f"{p}: 최상위에 themes 키가 없다")
    defaults = spec.get("defaults") or {}
    themes = tuple(_parse_theme(t, defaults) for t in spec["themes"])

    ids = [t.id for t in themes]
    dup_ids = sorted({i for i in ids if ids.count(i) > 1})
    if dup_ids:
        raise ThemeSpecError(f"중복 테마 id: {dup_ids}")
    # industry 라벨은 정확히 한 버킷에만
    label_owner: dict[str, str] = {}
    for t in themes:
        for label in t.industry_match:
            if label in label_owner:
                raise ThemeSpecError(
                    f"industry 라벨 {label!r} 이 두 버킷에 있다: {label_owner[label]} / {t.id}"
                )
            label_owner[label] = t.id
    inc_owner: dict[str, str] = {}
    for t in themes:
        for tk in t.include_tickers:
            if tk in inc_owner:
                raise ThemeSpecError(
                    f"include_tickers {tk} 가 두 버킷에 있다: {inc_owner[tk]} / {t.id}"
                )
            inc_owner[tk] = t.id
    return ThemeSet(
        themes=themes, schema_version=int(spec.get("schema_version", 1)), defaults=defaults
    )


# ---------------------------------------------------------------- 구성원 배정


@dataclass(frozen=True)
class Membership:
    """티커 → 테마 배정 결과. **몇 개가 왜 빠졌는지**를 함께 돌려준다 (`CLAUDE.md` §2)."""

    frame: pd.DataFrame  # columns: ticker, theme, industry, is_delisted, category
    total_universe: int
    unassigned: int
    excluded_shell: int
    excluded_non_member_category: dict[str, int]

    def members(self, theme_id: str) -> list[str]:
        return self.frame.loc[self.frame["theme"] == theme_id, "ticker"].tolist()

    def by_theme(self) -> dict[str, list[str]]:
        return {str(k): v["ticker"].tolist() for k, v in self.frame.groupby("theme", sort=True)}

    def counts(self) -> pd.DataFrame:
        g = self.frame.groupby("theme")
        out = pd.DataFrame(
            {
                "n_total": g.size(),
                "n_live": g["is_delisted"].apply(lambda s: int((s != "Y").sum())),
            }
        )
        out["n_delisted"] = out["n_total"] - out["n_live"]
        return out

    def report(self) -> str:
        return (
            f"유니버스 {self.total_universe:,} → 배정 {len(self.frame):,} · "
            f"미배정 {self.unassigned:,} · Shell 제외 {self.excluded_shell:,} · "
            f"구성원 불가 category {sum(self.excluded_non_member_category.values()):,}"
        )


def assign_members(
    themes: ThemeSet | Iterable[Theme],
    meta: pd.DataFrame,
    *,
    member_categories: Sequence[str] = MEMBER_CATEGORIES,
) -> Membership:
    """`tickers` 메타(ticker, category, industry, is_delisted)에 배정 규칙을 적용한다. 순수 함수."""
    need = {"ticker", "category", "industry"}
    missing = need - set(meta.columns)
    if missing:
        raise KeyError(f"meta 에 없는 컬럼: {sorted(missing)}")
    tl = list(themes)
    by_label = {label: t.id for t in tl for label in t.industry_match}
    includes = {tk: t.id for t in tl for tk in t.include_tickers}
    excludes = {t.id: set(t.exclude_tickers) for t in tl}

    df = meta.copy()
    df["ticker"] = df["ticker"].str.upper()
    if "is_delisted" not in df.columns:
        df["is_delisted"] = "N"
    cat_ok = df["category"].isin(set(member_categories))
    excluded_cat = {
        str(k): int(v)
        for k, v in df.loc[~cat_ok, "category"].fillna("(category 없음)").value_counts().items()
    }
    uni = df.loc[cat_ok].copy()
    total_universe = len(uni)

    ind = uni["industry"].fillna("(null)")
    is_shell = ind.isin(EXCLUDED_LABELS)
    theme_by_inc = uni["ticker"].map(includes)
    theme_by_label = ind.map(by_label)
    theme = theme_by_inc.where(theme_by_inc.notna(), theme_by_label)
    # Shell 라벨은 include 로 명시하지 않는 한 배정하지 않는다
    theme = theme.where(~(is_shell & theme_by_inc.isna()), other=pd.NA)
    uni["theme"] = theme
    # exclude 는 자동 매칭을 되돌린다 (include 가 위에서 우선)
    excl_mask = pd.Series(False, index=uni.index)
    for tid, exs in excludes.items():
        if exs:
            excl_mask |= (uni["theme"] == tid) & uni["ticker"].isin(exs) & theme_by_inc.isna()
    uni.loc[excl_mask, "theme"] = pd.NA

    assigned = uni.loc[
        uni["theme"].notna(), ["ticker", "theme", "industry", "is_delisted", "category"]
    ]
    assigned = assigned.reset_index(drop=True)
    ms = Membership(
        frame=assigned,
        total_universe=total_universe,
        unassigned=int(
            total_universe - len(assigned) - int((is_shell & theme_by_inc.isna()).sum())
        ),
        excluded_shell=int((is_shell & theme_by_inc.isna()).sum()),
        excluded_non_member_category=excluded_cat,
    )
    log.info("assign_members: %s", ms.report())
    return ms


#: `02-cycle-state.md` §7 — cycle_class 별 블록 가중치. **선언값이다. 데이터에 맞춰 바꾸지 않는다.**
BLOCK_WEIGHTS: dict[str, dict[str, float]] = {
    "commodity_supply": {"A": 0.15, "B": 0.15, "C": 0.20, "D": 0.10, "E": 0.30, "F": 0.10},
    "inventory": {"A": 0.10, "B": 0.15, "C": 0.25, "D": 0.10, "E": 0.15, "F": 0.25},
    "credit_rate": {"A": 0.15, "B": 0.15, "C": 0.25, "D": 0.25, "E": 0.05, "F": 0.15},
    "capex_program": {"A": 0.05, "B": 0.10, "C": 0.25, "D": 0.10, "E": 0.15, "F": 0.35},
    "policy_program": {"A": 0.15, "B": 0.20, "C": 0.30, "D": 0.10, "E": 0.10, "F": 0.15},
    "discretionary_demand": {"A": 0.15, "B": 0.15, "C": 0.25, "D": 0.20, "E": 0.05, "F": 0.20},
    "secular_growth": {"A": 0.05, "B": 0.15, "C": 0.25, "D": 0.30, "E": 0.05, "F": 0.20},
    "secular_risk": {"A": 0.05, "B": 0.15, "C": 0.25, "D": 0.15, "E": 0.20, "F": 0.20},
}

for _cc, _w in BLOCK_WEIGHTS.items():
    assert abs(sum(_w.values()) - 1.0) < 1e-9, (_cc, sum(_w.values()))
assert set(BLOCK_WEIGHTS) == set(CYCLE_CLASSES)
