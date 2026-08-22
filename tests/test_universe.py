"""유니버스 필터 — 순수 함수라 데이터 없이 돈다."""

from __future__ import annotations

import pandas as pd
import pytest

from msa.data.universe import (
    COMMON_STOCK_CATEGORIES,
    audit_duplicate_membership,
    common_stock,
    drop_secondary_class,
)


def _meta(categories: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"ticker": [f"T{i}" for i in range(len(categories))], "category": categories}
    )


def test_keeps_common_stock_and_counts_every_exclusion() -> None:
    meta = _meta(
        [
            "Domestic Common Stock",
            "ADR Common Stock",
            "Domestic Preferred Stock",
            "ETF",
            "ETF",
            "CEF",
        ]
    )
    res = common_stock(meta)
    assert res.kept == 2
    assert res.total_in == 6
    # 제외된 4개가 어디로 갔는지 반환값이 답한다 — 로그로만 남기지 않는다.
    assert res.excluded == 4
    assert res.excluded_by_category == {"ETF": 2, "Domestic Preferred Stock": 1, "CEF": 1}
    assert sum(res.excluded_by_category.values()) == res.excluded


def test_class_variants_are_not_silently_dropped() -> None:
    """문서 §2 는 category 2종만 적었다. Class 변종을 빼면 3,920 종목이 조용히 사라진다."""
    meta = _meta(list(COMMON_STOCK_CATEGORIES))
    assert common_stock(meta).kept == len(COMMON_STOCK_CATEGORIES)


def test_canadian_excluded_by_default_but_optional() -> None:
    meta = _meta(["Domestic Common Stock", "Canadian Common Stock"])
    assert common_stock(meta).kept == 1
    assert common_stock(meta, include_canadian=True).kept == 2


def test_null_category_is_labelled_not_dropped_silently() -> None:
    meta = _meta(["Domestic Common Stock"])
    meta.loc[1] = ["TX", None]
    res = common_stock(meta)
    assert res.excluded_by_category == {"(category 없음)": 1}


def test_drop_secondary_class_accumulates_exclusion_counts() -> None:
    meta = _meta(
        [
            "Domestic Common Stock",
            "Domestic Common Stock Secondary Class",
            "ADR Common Stock Secondary Class",
            "ETF",
        ]
    )
    res = drop_secondary_class(common_stock(meta))
    assert res.kept == 1
    assert res.excluded_by_category["ETF"] == 1
    assert res.excluded_by_category["Domestic Common Stock Secondary Class"] == 1
    # total_in 은 원래 입력 기준을 유지한다 — 제외 합계가 맞아야 한다.
    assert res.total_in - res.kept == sum(res.excluded_by_category.values())


def test_empty_category_list_is_an_error_not_a_silent_wipe() -> None:
    with pytest.raises(ValueError, match="필터 없음"):
        common_stock(_meta(["ETF"]), categories=[])


def test_duplicate_membership_detected() -> None:
    audit = audit_duplicate_membership(
        {"silver_miners": ["AG", "PAAS"], "gold_miners": ["NEM", "ag"]}
    )
    assert not audit.ok
    assert audit.duplicates == {"AG": ["silver_miners", "gold_miners"]}


def test_no_duplicate_membership_passes() -> None:
    audit = audit_duplicate_membership({"a": ["X"], "b": ["Y"]})
    assert audit.ok
    assert "통과" in audit.report()
