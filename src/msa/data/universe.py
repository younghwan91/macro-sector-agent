"""유니버스 필터 — 보통주 선별과 폐지 종목 포함 검증.

**제외한 종목은 세어서 반환한다.** 로그로만 남기고 버리면 `CLAUDE.md` §2 위반이다.
`docs/08` §2 도 "제외한 종목 수를 반드시 로그로 남긴다" 고 못박았지만, 로그는
파이프라인 상류로 올라가지 않는다 — 그래서 여기서는 **반환값**으로 만든다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

import pandas as pd

from msa.data.store import Store

log = logging.getLogger(__name__)


def count_by(values: pd.Series, *, na_label: str = "(category 없음)") -> dict[str, int]:
    """`value_counts()` → `{라벨: 건수}` (키는 str, 값은 int, 결측은 `na_label`).

    "제외한 것은 세어서 돌려준다" 규약(`CLAUDE.md` §2)의 공용 꼴 — `common_stock`·
    `drop_secondary_class`·`assign_members` 가 같은 딕셔너리를 만든다.
    """
    return {str(k): int(v) for k, v in values.fillna(na_label).value_counts().items()}


#: 보통주로 인정하는 `tickers.category` 값.
#:
#: `docs/08` §2 는 `Domestic Common Stock`·`ADR Common Stock` 둘만 적었다. 그러나 실측
#: 분포(43,919행)를 보면 Primary/Secondary Class 변종이 별도 값으로 존재한다 —
#: Domestic Primary 2,176 · Domestic Secondary 1,320 · ADR Primary 265 · ADR Secondary 159.
#: 문서대로 둘만 쓰면 이 3,920 종목이 **조용히 유니버스에서 사라진다.**
#: 그래서 Class 변종까지 포함한다. Secondary Class 는 같은 기업의 다른 의결권 주식이라
#: 테마 시총 집계에서 이중계상이 되므로, 집계 단계에서 `drop_secondary_class()` 로
#: 한 번 더 거른다 — 유니버스에서 빼는 것과 집계에서 빼는 것은 다른 결정이다.
COMMON_STOCK_CATEGORIES: tuple[str, ...] = (
    "Domestic Common Stock",
    "Domestic Common Stock Primary Class",
    "Domestic Common Stock Secondary Class",
    "ADR Common Stock",
    "ADR Common Stock Primary Class",
    "ADR Common Stock Secondary Class",
)

#: 캐나다 상장 보통주. `docs/01` §6-3 이 "순수 해외 상장은 범위 밖" 이라 했으므로
#: 기본 유니버스에서 뺀다. 다만 실측 400종목이 존재한다는 사실은 남겨 둔다.
CANADIAN_COMMON_CATEGORIES: tuple[str, ...] = (
    "Canadian Common Stock",
    "Canadian Common Stock Primary Class",
    "Canadian Common Stock Secondary Class",
)

SECONDARY_CLASS_CATEGORIES: tuple[str, ...] = (
    "Domestic Common Stock Secondary Class",
    "ADR Common Stock Secondary Class",
    "Canadian Common Stock Secondary Class",
)


@dataclass(frozen=True)
class UniverseResult:
    """필터 결과 + **왜 몇 개가 빠졌는지**."""

    frame: pd.DataFrame
    total_in: int
    excluded_by_category: dict[str, int] = field(default_factory=dict)

    @property
    def kept(self) -> int:
        return len(self.frame)

    @property
    def excluded(self) -> int:
        return self.total_in - self.kept

    @property
    def tickers(self) -> list[str]:
        return self.frame["ticker"].tolist()

    def report(self) -> str:
        top = sorted(self.excluded_by_category.items(), key=lambda kv: -kv[1])
        detail = ", ".join(f"{k}={v:,}" for k, v in top[:8]) or "없음"
        return (
            f"유니버스 {self.kept:,} / 입력 {self.total_in:,} "
            f"(제외 {self.excluded:,}) · 제외 내역: {detail}"
        )


def common_stock(
    meta: pd.DataFrame,
    *,
    categories: Sequence[str] = COMMON_STOCK_CATEGORIES,
    include_canadian: bool = False,
) -> UniverseResult:
    """보통주만 남긴다. 순수 함수 — 스토어에 접근하지 않아 데이터 없이 테스트된다.

    워런트·우선주·2종주는 `DAILY` 가 시총을 주지 않아 테마 집계를 오염시킨다
    (`docs/08` §2). 제외된 종목 수는 `UniverseResult.excluded_by_category` 로 돌려준다.
    """
    if "category" not in meta.columns:
        raise KeyError("meta 에 category 컬럼이 없다.")
    if not categories:
        raise ValueError("categories=[] 는 전부 거르라는 뜻이 된다. 필터 없음은 이 함수에 없다.")
    allowed = set(categories)
    if include_canadian:
        allowed |= set(CANADIAN_COMMON_CATEGORIES)
    mask = meta["category"].isin(allowed)
    result = UniverseResult(
        frame=meta.loc[mask].reset_index(drop=True),
        total_in=len(meta),
        excluded_by_category=count_by(meta.loc[~mask, "category"]),
    )
    log.info("common_stock: %s", result.report())
    return result


def drop_secondary_class(universe: UniverseResult) -> UniverseResult:
    """2종주 제외 — 테마 시총 집계에서 같은 기업이 두 번 세어지는 것을 막는다."""
    meta = universe.frame
    mask = ~meta["category"].isin(SECONDARY_CLASS_CATEGORIES)
    merged = dict(universe.excluded_by_category)
    for k, v in count_by(meta.loc[~mask, "category"]).items():
        merged[k] = merged.get(k, 0) + v
    return UniverseResult(
        frame=meta.loc[mask].reset_index(drop=True),
        total_in=universe.total_in,
        excluded_by_category=merged,
    )


@dataclass(frozen=True)
class DelistedCoverage:
    """폐지 종목이 자기이력 구간에 실제로 들어 있는지 (`docs/01` §5 감사 항목)."""

    delisted_total: int
    delisted_with_prices: int
    delisted_missing: list[str]
    excluded_non_equity: dict[str, int]
    window_start: str
    window_end: str

    @property
    def ok(self) -> bool:
        return not self.delisted_missing

    @property
    def coverage(self) -> float:
        return 1.0 if not self.delisted_total else self.delisted_with_prices / self.delisted_total

    def report(self) -> str:
        verdict = "통과" if self.ok else f"실패 — {len(self.delisted_missing)}종목 누락"
        skipped = sum(self.excluded_non_equity.values())
        return (
            f"폐지 종목 포함 감사 [{self.window_start}~{self.window_end}]: "
            f"{self.delisted_with_prices:,}/{self.delisted_total:,} ({self.coverage:.2%}) · "
            f"{verdict} · 검사 대상 밖(펀드류) {skipped:,}"
        )


def audit_delisted_included(
    store: Store,
    start: str,
    end: str,
    *,
    categories: Sequence[str] = COMMON_STOCK_CATEGORIES,
    meta: pd.DataFrame | None = None,
) -> DelistedCoverage:
    """구간 안에 폐지된 종목이 가격 이력에 남아 있는지 확인한다. **전수 검사한다.**

    `meta` 를 주면(이미 읽은 `tickers_meta`) 다시 읽지 않는다. 가격은 행을 끌어오지 않고
    `Store.tickers_with_prices`(`select distinct ticker`)로 존재 여부만 묻는다.

    빠지면 자기이력 백분위가 낙관 방향으로 왜곡된다 — 오늘 살아 있는 은광만으로
    은광의 10년 밸류 백분위를 계산하면 "역사적으로 싸다" 가 자동으로 나온다
    (`docs/01` §5 마지막에서 두 번째 항목).

    **검사 모집단은 보통주로 한정한다.** `prices` 는 주식만 담고 ETF·CEF·ETN·ETD 는
    아예 없기 때문이다 (M1 실측: 폐지된 ETF 1,982종 전부 `prices` 에 0행). 이것을
    한정하지 않으면 감사가 늘 실패하고, 늘 실패하는 관문은 곧 무시된다.
    다만 **몇 개를 검사에서 뺐는지는 `excluded_non_equity` 로 돌려준다** —
    로그로만 남기고 버리지 않는다 (`CLAUDE.md` §2). 이 딕셔너리에는 `prices` 에
    구조적으로 없는 펀드류(ETF·CEF·ETN·ETD·ETMF·MF·UNIT)와, `prices` 에는 있지만
    보통주 모집단이 아닌 것(우선주·캐나다 상장)이 함께 들어간다 — 뺀 이유가 다르므로
    category 별로 세어서 돌려준다.
    """
    acts = store.actions(kinds=["delisted"], start=start, end=end, min_rows=1)
    cands = sorted(acts["ticker"].unique())
    if meta is None:
        meta = store.tickers_meta(min_rows=1)
    cat_of = dict(zip(meta["ticker"], meta["category"].fillna("(category 없음)"), strict=True))
    allowed = set(categories)
    checked = [t for t in cands if cat_of.get(t, "(category 없음)") in allowed]
    excluded: dict[str, int] = {}
    for t in cands:
        c = cat_of.get(t, "(category 없음)")
        if c not in allowed:
            excluded[c] = excluded.get(c, 0) + 1

    have = store.tickers_with_prices(checked, start, end)
    missing = [t for t in checked if t not in have]
    cov = DelistedCoverage(
        delisted_total=len(checked),
        delisted_with_prices=len(checked) - len(missing),
        delisted_missing=missing,
        excluded_non_equity=excluded,
        window_start=start,
        window_end=end,
    )
    log.info("audit_delisted_included: %s", cov.report())
    return cov


@dataclass(frozen=True)
class DuplicateMembership:
    """한 티커가 두 개 이상의 테마 버킷에 속하면 L5 집중도 계산이 오염된다 (`docs/01` §5)."""

    duplicates: dict[str, list[str]]

    @property
    def ok(self) -> bool:
        return not self.duplicates

    def report(self) -> str:
        if self.ok:
            return "중복 소속: 0개 · 통과"
        sample = list(self.duplicates.items())[:5]
        return f"중복 소속: {len(self.duplicates)}개 · 예: {sample}"


def audit_duplicate_membership(buckets: dict[str, Sequence[str]]) -> DuplicateMembership:
    """버킷 → 티커 목록 매핑에서 중복 소속을 찾는다. 순수 함수."""
    owners: dict[str, list[str]] = {}
    for bucket, members in buckets.items():
        for t in members:
            owners.setdefault(t.upper(), []).append(bucket)
    return DuplicateMembership({t: b for t, b in owners.items() if len(b) > 1})
