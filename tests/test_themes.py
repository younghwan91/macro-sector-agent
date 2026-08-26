"""`msa.themes` — 로더 스키마 검증과 구성원 배정 (순수 함수, 데이터 없음)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from msa.config import REPO_ROOT
from msa.themes import (
    BLOCK_WEIGHTS,
    CYCLE_CLASSES,
    ThemeSpecError,
    assign_members,
    load_themes,
)


def _spec(themes: list[dict]) -> dict:
    return {"schema_version": 1, "defaults": {"min_constituents": 5}, "themes": themes}


def _theme(**kw) -> dict:
    base = {
        "id": "gold_miners",
        "name_ko": "금광",
        "parent_sector": "Basic Materials",
        "cycle_class": "commodity_supply",
        "industry_match": ["Gold"],
        "include_tickers": [],
        "exclude_tickers": [],
        "etf_proxy": "GDX",
        "etf_proxy_alt": [],
        "physical_ref": {"source": "etf", "symbol": "GLD", "kind": "price"},
        "correlation_cluster": "precious_metals",
        "min_constituents": 5,
    }
    base.update(kw)
    return base


def _write(tmp_path: Path, spec: dict) -> Path:
    p = tmp_path / "themes.yaml"
    p.write_text(yaml.safe_dump(spec, allow_unicode=True))
    return p


def test_load_real_themes_yaml() -> None:
    ts = load_themes(REPO_ROOT / "state" / "themes.yaml")
    assert len(ts) == 134
    declared = [t for t in ts if t.physical_ref is not None]
    assert len(declared) == 45
    assert all(t.physical_ref.kind in ("price", "volume", "nominal") for t in declared)  # type: ignore[union-attr]
    assert set(t.cycle_class for t in ts) <= set(CYCLE_CLASSES)


def test_physical_ref_requires_kind(tmp_path: Path) -> None:
    p = _write(tmp_path, _spec([_theme(physical_ref={"source": "etf", "symbol": "GLD"})]))
    with pytest.raises(ThemeSpecError, match="kind"):
        load_themes(p)


def test_physical_ref_null_is_allowed(tmp_path: Path) -> None:
    ts = load_themes(_write(tmp_path, _spec([_theme(physical_ref=None)])))
    assert ts.themes[0].physical_ref is None
    assert not ts.themes[0].axis1_declared


def test_duplicate_industry_label_rejected(tmp_path: Path) -> None:
    spec = _spec([_theme(), _theme(id="gold_two")])
    with pytest.raises(ThemeSpecError, match="두 버킷"):
        load_themes(_write(tmp_path, spec))


def test_unknown_cycle_class_rejected(tmp_path: Path) -> None:
    with pytest.raises(ThemeSpecError, match="cycle_class"):
        load_themes(_write(tmp_path, _spec([_theme(cycle_class="momentum")])))


def test_block_weights_sum_to_one() -> None:
    for cc, w in BLOCK_WEIGHTS.items():
        assert abs(sum(w.values()) - 1.0) < 1e-9, cc
        assert set(w) == {"A", "B", "C", "D", "E", "F"}


def test_assign_members_rules(tmp_path: Path) -> None:
    ts = load_themes(
        _write(
            tmp_path,
            _spec(
                [
                    _theme(exclude_tickers=["SBSW"]),
                    _theme(
                        id="pgm_miners",
                        industry_match=["Other Precious Metals & Mining"],
                        include_tickers=["SBSW"],
                        physical_ref=None,
                    ),
                ]
            ),
        )
    )
    meta = pd.DataFrame(
        {
            "ticker": ["NEM", "SBSW", "SHELLCO", "PREF", "ETFX", "DEAD", "CAN1", "NOLBL"],
            "category": [
                "Domestic Common Stock",
                "ADR Common Stock",
                "Domestic Common Stock",
                "Domestic Preferred Stock",
                "ETF",
                "Domestic Common Stock",
                "Canadian Common Stock",
                "Domestic Common Stock",
            ],
            "industry": [
                "Gold",
                "Gold",
                "Shell Companies",
                "Gold",
                "Gold",
                "Gold",
                "Gold",
                None,
            ],
            "is_delisted": ["N", "N", "N", "N", "N", "Y", "N", "N"],
        }
    )
    ms = assign_members(ts, meta)
    by = ms.by_theme()
    assert sorted(by["gold_miners"]) == ["CAN1", "DEAD", "NEM"]  # SBSW 는 exclude → pgm 으로
    assert by["pgm_miners"] == ["SBSW"]
    assert ms.excluded_shell == 1
    assert ms.unassigned == 1  # NOLBL
    assert ms.excluded_non_member_category == {"Domestic Preferred Stock": 1, "ETF": 1}
    counts = ms.counts()
    assert counts.loc["gold_miners", "n_total"] == 3
    assert counts.loc["gold_miners", "n_live"] == 2
    assert counts.loc["gold_miners", "n_delisted"] == 1


def test_etf_candidates_follow_declared_order_and_dedupe() -> None:
    """후보는 **설정에 적힌 순서**다 — 코드가 고르는 것이 아니다 (`CLAUDE.md` §1).

    `etf_proxy_alt` 는 2026-08-27 까지 파싱만 되고 아무 데서도 쓰이지 않았다. 그 사이
    `casinos_gaming` 의 주 프록시 `BJK` 는 상장폐지돼 벌크에 없었고, 대안 `BETZ` 가 설정에
    적혀 있는데도 매 실행 경고만 났다.
    """
    from msa.themes import Theme

    def _t(proxy: str | None, alt: tuple[str, ...]) -> Theme:
        t = object.__new__(Theme)
        object.__setattr__(t, "etf_proxy", proxy)
        object.__setattr__(t, "etf_proxy_alt", alt)
        return t

    assert _t("BJK", ("BETZ",)).etf_candidates == ("BJK", "BETZ")
    assert _t(None, ("BETZ",)).etf_candidates == ("BETZ",)
    assert _t("BETZ", ("BETZ",)).etf_candidates == ("BETZ",), "중복은 뺀다"
    assert _t(None, ()).etf_candidates == ()


def test_retired_proxy_is_not_requested_any_more() -> None:
    """상장폐지된 BJK 를 더는 요청하지 않는다 — 매 실행 경고의 원인이었다.

    2026-08-27 확인: Sharadar 벌크 funds.csv.zip 9,808 종목에 BJK 가 없다.
    """
    from msa.l1.physical import etf_symbols
    from msa.themes import load_themes

    themes = load_themes()
    assert "BJK" not in etf_symbols(themes), "죽은 프록시를 계속 요청하면 안 된다"
    cg = next(t for t in themes if t.id == "casinos_gaming")
    assert cg.etf_proxy == "BETZ", "설정에 이미 대안으로 적혀 있던 값이다"
