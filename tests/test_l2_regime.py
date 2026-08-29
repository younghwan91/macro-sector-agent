"""P2 매크로 레짐 — `docs/25` 사전 등록의 집행. 합성 dict, 네트워크 없음."""

from __future__ import annotations

from pathlib import Path

import pytest

from msa import triage
from msa.l2 import regime


def _cls(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "verdict": "headwind",
        "mechanism": "정책금리가 높은 채로 유지되어 차환 부담이 크다.",
        "invalidations": ["10년물이 3.5% 아래로 내려가면 이 판정은 무효다"],
        "evidence": [
            {
                "claim": "10년물 4.4%",
                "source_url": "https://fred.stlouisfed.org/series/DGS10",
                "date": "2026-08-27",
                "reliability": "high",
            }
        ],
    }
    d.update(kw)
    return d


def _doc(**classes: object) -> dict[str, object]:
    return {"asof": "2026-08-29", "week": "2026-W35", "classes": dict(classes)}


# ---------------------------------------------------------------- 계수


def test_tilt_is_declared_and_has_exactly_three_values() -> None:
    """`docs/25` §3.4 — 자유도가 8칸 × 3값로 고정되는 것이 L2 와의 결정적 차이다."""
    assert regime.REGIME_TILT == {"tailwind": 1.00, "neutral": 0.85, "headwind": 0.70}
    assert set(regime.VERDICTS) == set(regime.REGIME_TILT)


def test_missing_regime_is_neutral_coefficient_one() -> None:
    """레짐이 없으면 계수 1.0 — 없는 것을 역풍으로 읽지 않는다 (`docs/25` §5)."""
    assert regime.tilt_for(None) == 1.0
    assert regime.tilt_for("") == 1.0


def test_unknown_verdict_is_refused_not_silently_neutral() -> None:
    with pytest.raises(ValueError, match="verdict"):
        regime.tilt_for("bullish")


# ---------------------------------------------------------------- 스키마


def test_evidence_is_required(tmp_path: Path) -> None:
    """출처 없는 주장은 저장되지 않는다 (`CLAUDE.md` §3)."""
    with pytest.raises(regime.RegimeRejected, match="evidence"):
        regime.validate(_doc(credit_rate=_cls(evidence=[])))


def test_invalidations_are_required(tmp_path: Path) -> None:
    """무효화 조건 없는 판정은 저장되지 않는다 (`CLAUDE.md` §5)."""
    with pytest.raises(regime.RegimeRejected, match="invalidations"):
        regime.validate(_doc(credit_rate=_cls(invalidations=[])))


def test_unknown_cycle_class_is_refused() -> None:
    """8칸을 늘리거나 쪼개지 않는다 (`docs/25` §5)."""
    with pytest.raises(regime.RegimeRejected, match="cycle_class"):
        regime.validate(_doc(crypto_winter=_cls()))


def test_evidence_url_must_look_like_a_url() -> None:
    bad = _cls()
    bad["evidence"] = [{"claim": "x", "source_url": "믿어줘", "date": "2026-08-27"}]
    with pytest.raises(regime.RegimeRejected, match="source_url"):
        regime.validate(_doc(credit_rate=bad))


def test_valid_document_passes_and_roundtrips(tmp_path: Path) -> None:
    doc = _doc(credit_rate=_cls(), inventory=_cls(verdict="tailwind"))
    regime.validate(doc)
    p = regime.write(tmp_path, doc)
    assert p.exists()
    got = regime.read(tmp_path, "2026-W35")
    assert got["classes"]["inventory"]["verdict"] == "tailwind"


def test_read_missing_week_is_none(tmp_path: Path) -> None:
    assert regime.read(tmp_path, "1999-W01") is None


# ---------------------------------------------------------------- 테마 → 계수


def test_tilts_by_theme_maps_through_cycle_class() -> None:
    doc = _doc(credit_rate=_cls(verdict="headwind"), inventory=_cls(verdict="tailwind"))
    classes = {"reit_office": "credit_rate", "steel": "inventory", "biotech": "secular_growth"}
    got = regime.tilts_by_theme(doc, classes)
    assert got["reit_office"] == 0.70
    assert got["steel"] == 1.00
    # 판정이 없는 칸은 1.0 — 빠진 것을 역풍으로 읽지 않는다
    assert got["biotech"] == 1.00


def test_tilts_by_theme_without_document_is_all_one() -> None:
    classes = {"reit_office": "credit_rate"}
    assert regime.tilts_by_theme(None, classes) == {"reit_office": 1.0}


# ---------------------------------------------------------------- 트리아지 결합


def _pick(**kw: object) -> dict[str, object]:
    d: dict[str, object] = {
        "ticker": "AAA",
        "from_52w_high": -0.40,
        "stage2": True,
        "above_50d": True,
        "red_flags": "",
        "survival_unjudged": None,
    }
    d.update(kw)
    return d


def _digest(tilt: float | None) -> dict[str, object]:
    d: dict[str, object] = {
        "themes": [{"theme": "t1", "picks": [_pick(), _pick(ticker="BBB", from_52w_high=-0.05)]}],
        "judged": [
            {"theme": "t1", "portfolio_eligible": True, "trusted": True, "gate": "passed"}
        ],
        "evidence_audit": {
            "t1": {"counts": {"verified": 20}, "checked": 20, "unverified_axes": []}
        },
    }
    if tilt is not None:
        d["regime_tilts"] = {"t1": tilt}
    return d


def test_headwind_lowers_r_but_not_j_or_c() -> None:
    """레짐은 R 에만 곱한다 — J·C 는 못 건드린다 (`docs/25` §3.3)."""
    base = triage.score_digest(_digest(None))[0]
    hw = triage.score_digest(_digest(0.70))[0]
    assert hw.j == base.j
    assert hw.c == base.c
    assert hw.r == pytest.approx(base.r * 0.70)
    assert hw.triage < base.triage


def test_headwind_cannot_move_a_stock_between_partitions() -> None:
    """구획은 판별과 낙폭이 정한다 — 매크로는 둘 다에 발언권이 없다 (`docs/25` §3.3)."""
    base = {r.ticker: r.partition for r in triage.score_digest(_digest(None))}
    hw = {r.ticker: r.partition for r in triage.score_digest(_digest(0.70))}
    assert base == hw
    assert base["AAA"] == triage.PARTITION_IA
    assert base["BBB"] == triage.PARTITION_IB


def test_tailwind_is_the_identity() -> None:
    base = triage.score_digest(_digest(None))[0]
    tw = triage.score_digest(_digest(1.00))[0]
    assert tw.triage == pytest.approx(base.triage)


def test_declared_constants_carry_the_tilt() -> None:
    d = triage.declared_constants()
    assert d["regime_tilt"] == regime.REGIME_TILT
    assert "docs/25" in d["regime_tilt_source"]


def test_cycle_classes_are_the_same_object_as_themes() -> None:
    """**같은 값이 두 곳에 살면 한쪽만 고쳐도 아무도 모른다.**

    `is` 를 쓰는 것이 요점이다 — `msa.basis` 의 같은 이름 테스트와 같은 규약이다.
    """
    from msa import themes

    assert regime.CYCLE_CLASSES is themes.CYCLE_CLASSES


def test_every_theme_in_themes_yaml_has_a_known_cycle_class() -> None:
    """정본(`state/themes.yaml`)의 모든 테마가 8칸 안에 있다 — 레짐이 빠뜨리는 테마가 없다."""
    from msa.themes import load_themes

    got = {t.cycle_class for t in load_themes()}
    assert got <= set(regime.CYCLE_CLASSES)
    assert len(got) == 8, f"8칸 전부가 실제로 쓰이고 있어야 한다: {sorted(got)}"


# ---------------------------------------------------------------- 분석가 역할


def test_analyst_prompt_asks_all_eight_classes() -> None:
    from msa.l2 import analyst

    req = analyst.build_request("2026-W35", "2026-08-29")
    text = req.as_text()
    for name in regime.CYCLE_CLASSES:
        assert name in text, f"{name} 칸을 안 물었다"
    assert set(analyst.SCHEMA["properties"]["classes"]["required"]) == set(regime.CYCLE_CLASSES)


def test_analyst_output_schema_has_nowhere_to_put_a_stock() -> None:
    """**진짜 보증은 스키마에 있다** — 모델이 종목을 내려 해도 담을 칸이 없다.

    초안 테스트는 "프롬프트에 '티커' 라는 낱말이 없어야 한다" 였는데 틀렸다: 프롬프트는
    정당하게 *"티커도 회사명도 쓰지 않는다"* 라고 금지하고 있고, 토큰 검사는 그 금지문을
    위반으로 센다.
    """
    from msa.l2 import analyst

    one = analyst.SCHEMA["properties"]["classes"]["properties"]["credit_rate"]
    assert set(one["properties"]) == {"verdict", "mechanism", "invalidations", "evidence"}
    assert one["properties"]["verdict"]["enum"] == list(regime.VERDICTS)
    # 자유 문자열은 mechanism 하나뿐이고 그것도 required 로 종목 금지를 명시한다
    assert "종목명 금지" in one["properties"]["mechanism"]["description"]


def test_analyst_prompt_carries_the_prohibitions() -> None:
    """스키마 위의 보조 확인 — 금지문이 프롬프트에서 사라지면 알아야 한다."""
    from msa.l2 import analyst

    text = analyst.build_request("2026-W35", "2026-08-29").as_text()
    for phrase in analyst.REQUIRED_PROHIBITIONS:
        assert phrase in text, f"프롬프트에서 금지문이 사라졌다: {phrase!r}"


def test_analyst_schema_requires_evidence_and_invalidations() -> None:
    from msa.l2 import analyst

    one = analyst.SCHEMA["properties"]["classes"]["properties"]["credit_rate"]
    assert set(one["required"]) == {"verdict", "mechanism", "invalidations", "evidence"}
    assert one["properties"]["evidence"]["minItems"] == 1
    assert one["properties"]["invalidations"]["minItems"] == 1


def test_summarize_says_missing_is_not_neutral() -> None:
    from msa.l2 import analyst

    assert "중립이 아니다" in analyst.summarize(None)
    got = analyst.summarize(_doc(credit_rate=_cls(), inventory=_cls(verdict="tailwind")))
    assert "headwind 1" in got and "tailwind 1" in got


def test_run_returns_document_shape_and_validates() -> None:
    from msa.l2 import analyst

    class _P:
        def complete(self, req: object) -> object:
            class _R:
                @staticmethod
                def json() -> dict[str, object]:
                    return {"classes": {name: _cls() for name in regime.CYCLE_CLASSES}}

            return _R()

    doc = analyst.run(_P(), week="2026-W35", asof="2026-08-29")
    regime.validate(doc)
    assert set(doc["classes"]) == set(regime.CYCLE_CLASSES)


def test_daily_regime_block_survives_missing_themes_file(tmp_path: Path, monkeypatch) -> None:
    """레짐은 선택 사항이다 — 못 읽어도 다이제스트는 나가되 **왜인지 적는다** (`CLAUDE.md` §2)."""
    from msa.pipeline import daily as D

    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    block = D._regime_block({"themes": [{"theme": "t1"}]})
    assert block["tilts"] == {}
    assert "R 계수 전부 1.0" in block["note"]


def test_daily_regime_block_omits_neutral_ones(tmp_path: Path, monkeypatch) -> None:
    """계수 1.0 은 싣지 않는다 — 무엇이 실제로 밀렸는지가 보여야 한다."""
    from msa.pipeline import daily as D
    from msa.themes import load_themes

    import shutil

    from msa.config import paths

    real = paths().themes_yaml
    monkeypatch.setenv("MSA_STATE", str(tmp_path))
    (tmp_path / "regime").mkdir(parents=True)
    shutil.copy(real, tmp_path / "themes.yaml")  # MSA_STATE 는 themes.yaml 위치도 옮긴다
    themes = list(load_themes())
    hw_cls = themes[0].cycle_class
    doc = {
        "asof": "2026-08-29",
        "week": "2026-W35",
        "classes": {hw_cls: _cls(verdict="headwind")},
    }
    regime.write(tmp_path / "regime", doc)
    picked = [t.id for t in themes if t.cycle_class == hw_cls][:1]
    other = [t.id for t in themes if t.cycle_class != hw_cls][:1]
    block = D._regime_block({"themes": [{"theme": picked[0]}, {"theme": other[0]}]})
    assert block["tilts"] == {picked[0]: 0.70}
    assert block["week"] == "2026-W35"
