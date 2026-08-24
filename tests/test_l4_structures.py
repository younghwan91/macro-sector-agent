"""L4 선정 구조 비교 — `docs/15` §2.2 의 네 규칙과 §4 의 판정식이 코드와 같은가.

합성 데이터, 스토어 없음. `tests/test_l1_structures.py` 와 같은 자리다: 사전 등록 문서를 코드로
옮긴 것이 맞는지만 본다. 성과가 좋은지는 여기서 묻지 않는다 (`CLAUDE.md` §7).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from msa.l1.backtest import (
    BOOT_BLOCK,
    BOOT_N,
    BOOT_SEED,
    GATE_HORIZON,
    HORIZONS,
    PARTITION_ALL,
    PRIMARY_START,
    WINDOWS,
)
from msa.l4 import axes, barbell
from msa.l4.backtest import INDICATORS, MIN_STOCKS_XS, PANEL_COLUMNS, stock_forward
from msa.l4.structures import (
    CANDIDATES,
    N_TRIALS_L4,
    PAIR_NAMES,
    PAIRS,
    PRIMARY_PAIRS,
    SECONDARY_PAIRS,
    K,
    _call,
    count_trials,
    pairwise_theme_month,
    run_structures_frames,
    select_b0,
    select_b1,
    select_b2,
    select_b3,
    theme_month_selection,
    verdict,
)

DATES = pd.date_range("2011-01-31", periods=48, freq="ME")


# ---------------------------------------------------------------- 합성 도구


def _panel(
    theme: str,
    dates: pd.DatetimeIndex,
    tickers: list[str],
    *,
    rng: np.random.Generator,
    n_excl: int = 0,
) -> pd.DataFrame:
    """(date × ticker) 캐시 패널 모양. 앞 `n_excl` 종목은 하드 제외(E1)."""
    rows: list[dict[str, Any]] = []
    for d in dates:
        for j, tk in enumerate(tickers):
            excluded = j < n_excl
            rec: dict[str, Any] = {"date": d, "ticker": tk, "eligible": not excluded}
            for c in axes.HARD_REASON_CODES:
                rec[c] = excluded and c == "E1"
            v = rng.random(4)
            rec["composite"] = np.nan if excluded else float(v[0])
            rec["s_pct"] = np.nan if excluded else float(v[1])
            rec["t_pct"] = np.nan if excluded else float(v[2])
            rec["m_pct"] = np.nan if excluded else float(v[3])
            rec["composite_partial"] = False
            for ind in INDICATORS:
                rec[ind] = np.nan if excluded else float(rng.random())
            rec["tp_marginal_producer"] = np.nan if excluded else float(int(rng.random() < 0.2))
            rows.append(rec)
    df = pd.DataFrame(rows)[list(PANEL_COLUMNS)]
    df["theme"] = theme
    return df


def _close(dates: pd.DatetimeIndex, tickers: list[str], rng: np.random.Generator) -> pd.DataFrame:
    steps = 1.0 + rng.normal(0.005, 0.06, size=(len(dates), len(tickers)))
    return pd.DataFrame(100.0 * np.cumprod(steps, axis=0), index=dates, columns=tickers)


def _forward(close: pd.DataFrame, horizons: tuple[int, ...] = (1, 3, 6, 12)):
    deaths = pd.DataFrame(False, index=close.index, columns=close.columns)
    return stock_forward(close, deaths, horizons, last_complete=pd.Timestamp(close.index[-1]))


# ---------------------------------------------------------------- §2 선언값


def test_declared_constants_match_docs15() -> None:
    """§2.1·§2.2 의 값이 코드 상수와 같다. 후보 목록은 닫혀 있다."""
    assert CANDIDATES == ("B0", "B1", "B2", "B3")  # §2.2 — 정확히 넷
    assert K == 3  # §2.1 — docs/14 §2.4 컷오프 그대로
    assert max(1, K // 2) == 1  # §2.1 각주 — 앵커 1 · 토크 2
    assert barbell.ANCHOR_S_MIN == 0.5  # §2.2 — 코드의 현행 상수
    assert barbell.TORQUE_S_EXCLUDE_LE == 0.25
    assert MIN_STOCKS_XS == 20  # §2.1 → docs/14 §2.2
    assert tuple(HORIZONS) == (3, 6, 12) and GATE_HORIZON == 12  # §2.1
    assert pd.Timestamp("2011-01-31") == PRIMARY_START  # §2.1 주 창
    assert tuple(WINDOWS) == ("primary", "full")
    assert (BOOT_BLOCK, BOOT_N, BOOT_SEED) == (12, 2000, 0)  # §3.1 — 같은 함수·같은 인자
    assert PRIMARY_PAIRS == ("B0-B3", "B1-B3", "B2-B3")  # §4.1
    assert SECONDARY_PAIRS == ("B0-B1", "B0-B2")  # §4.2
    assert (*PRIMARY_PAIRS, *SECONDARY_PAIRS) == PAIR_NAMES
    assert PAIRS[0] == ("B0", "B3")


def test_count_trials_reconciles_docs15_section_4_3() -> None:
    """§4.3 의 산식(66)과 정산(458 + 66 = 524), 그리고 그 위에 더 본 칸을 명시적으로 센다."""
    t = count_trials()
    assert t["levels"] == 4 * 3 * 2 == 24
    assert t["diff_x_minus_b3"] == 3 * 3 * 2 == 18
    assert t["diff_b0_b1"] == 6 and t["diff_b0_b2"] == 6
    assert t["mortality"] == 4 * 2 == 8
    assert t["sensitivity_d1"] == 4
    assert t["docs15_subtotal"] == 66
    assert t["docs14_base"] == N_TRIALS_L4 == 458
    assert t["docs15_declared_total"] == 524
    # 524 는 하한이다 (§4.3) — 더 본 칸은 세어서 더한다
    assert t["added_beyond_docs15"] == t["turnover_added"] + t["level_1m_for_pbo_added"]
    assert t["total"] == 524 + t["added_beyond_docs15"] > 524
    assert t["declared_only"] == 4  # X−B3 셋 + B0−B1 하나


# ---------------------------------------------------------------- §2.2 네 규칙


def test_b0_is_barbell_classify_top_k() -> None:
    """B0 는 `barbell.classify(scored, top=3)` **그대로**다 — 규칙을 다시 쓰지 않았다."""
    rng = np.random.default_rng(3)
    tk = np.array([f"T{i:02d}" for i in range(30)], dtype=object)
    s = rng.random(30)
    t = rng.random(30)
    mp = (rng.random(30) < 0.3).astype(float)
    got = select_b0(tk, s, t, mp)
    want = barbell.classify(
        pd.DataFrame(
            {"s_pct": s, "t_pct": t, "marginal_producer": mp > 0.5},
            index=pd.Index([str(x) for x in tk], name="ticker"),
        ),
        top=K,
    )
    assert got.anchors == want.anchors and got.torques == want.torques
    assert len(got.anchors) <= 1 and got.n <= K  # 앵커 1 · 토크 2


def test_b0_anchor_and_torque_thresholds() -> None:
    """앵커는 `s_pct ≥ 0.5` 이면서 한계생산자 아님, 토크는 `s_pct > 0.25` 이면서 t_pct 비 NaN."""
    tk = np.array(["A", "B", "C", "D", "E"], dtype=object)
    #  t_pct 내림차순: A(.99) C(.95) D(.90) E(.85) B(.50)
    #  A 는 한계생산자라 앵커 불가 · C 는 s_pct 0.10 이라 앵커도 토크도 불가
    #  → 앵커는 s_pct ≥ 0.5 이면서 한계생산자가 아닌 것 중 t_pct 최상위 = D
    #  → 토크는 s_pct > 0.25 이면서 t_pct 비 NaN 인 나머지 중 위에서 둘 = A, E
    s = np.array([0.80, 0.90, 0.10, 0.60, 0.55])
    t = np.array([0.99, 0.50, 0.95, 0.90, 0.85])
    mp = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
    bb = select_b0(tk, s, t, mp)
    assert bb.anchors == ["D"]
    assert bb.torques == ["A", "E"]  # C 는 s_pct ≤ 0.25 로 탈락
    # t_pct 가 NaN 이면 토크가 될 수 없다
    t2 = t.copy()
    t2[0] = np.nan
    assert "A" not in select_b0(tk, s, t2, mp).torques


def test_b0_records_shortfall_when_no_anchor_candidate() -> None:
    """앵커 후보가 없으면 앵커 자리가 비고 그것이 드러난다 (§2.1 — 조용히 채우지 않는다)."""
    tk = np.array(["A", "B", "C", "D"], dtype=object)
    s = np.array([0.30, 0.30, 0.30, 0.30])  # 전부 < ANCHOR_S_MIN
    t = np.array([0.9, 0.8, 0.7, 0.6])
    mp = np.zeros(4)
    bb = select_b0(tk, s, t, mp)
    assert bb.anchors == [] and bb.torques == ["A", "B", "C"]


def test_b1_is_top_k_by_mcap_and_drops_missing() -> None:
    """B1 = 시총 상위 3. `mcap` 결측은 **풀에서 빠진다** — 0 이나 대용값으로 메우지 않는다."""
    tk = np.array(["A", "B", "C", "D", "E"], dtype=object)
    mc = np.array([5.0, np.nan, 9.0, 7.0, 1.0])
    assert select_b1(tk, mc) == ["C", "D", "A"]
    assert select_b1(tk, np.array([np.nan] * 5)) == []
    # 동률은 티커 오름차순 (§2.1)
    assert select_b1(tk, np.array([3.0, 3.0, 3.0, 1.0, 1.0])) == ["A", "B", "C"]


def test_b2_is_top_k_by_t_pct_only() -> None:
    """B2 = `t_pct` 상위 3. `s_pct` 조건도 한계생산자 제외도 **없다** (§2.2)."""
    tk = np.array(["A", "B", "C", "D"], dtype=object)
    t = np.array([0.9, np.nan, 0.8, 0.7])
    assert select_b2(tk, t) == ["A", "C", "D"]
    # B0 와 달리 s_pct 를 보지 않는다: s_pct 가 아무리 낮아도 t_pct 만으로 뽑힌다
    s = np.array([0.01, 0.01, 0.01, 0.01])
    assert select_b0(tk, s, t, np.zeros(4)).torques == []  # s_pct ≤ 0.25 라 토크 0
    assert len(select_b2(tk, t)) == K


def test_b3_is_everything_and_ignores_k() -> None:
    """B3 = 적격 전부. K 를 쓰지 않는다 (§2.2) — 기준선이다 (§2.3)."""
    tk = np.array([f"T{i}" for i in range(25)], dtype=object)
    assert select_b3(tk) == [str(x) for x in tk]
    assert len(select_b3(tk)) == 25 > K


# ---------------------------------------------------------------- §2.1 공통 규약


def test_all_candidates_start_from_the_same_eligible_pool() -> None:
    """하드 제외 뒤 같은 적격 집합에서 출발한다 — 제외된 종목은 어느 후보에도 들어가지 않는다."""
    rng = np.random.default_rng(11)
    tickers = [f"T{i:02d}" for i in range(30)]
    panel = _panel("th", DATES, tickers, rng=rng, n_excl=5)  # T00~T04 가 E1 제외
    close = _close(DATES, tickers, rng)
    fwd = _forward(close)
    mcap = pd.DataFrame(rng.random((len(DATES), len(tickers))) * 1e9, index=DATES, columns=tickers)
    res = theme_month_selection(panel, fwd, mcap)
    assert not res.excess.empty
    # 풀 크기 n 은 후보와 무관하게 같다
    g = res.excess[res.excess["horizon"] == GATE_HORIZON].groupby(["date"])["n"].nunique()
    assert (g == 1).all()
    # B3 는 K 를 무시하고 풀 전체를 담는다 (제외 5개는 절대 안 들어간다)
    b3 = res.excess[(res.excess["candidate"] == "B3") & (res.excess["horizon"] == GATE_HORIZON)]
    assert (b3["n_selected"] == b3["n"]).all()
    assert (b3["n_selected"] <= len(tickers) - 5).all()
    for c in ("B0", "B1", "B2"):
        sub = res.excess[(res.excess["candidate"] == c) & (res.excess["horizon"] == GATE_HORIZON)]
        assert (sub["n_selected"] <= K).all()


def test_below_min_n_theme_months_are_counted_not_dropped_silently() -> None:
    """풀이 `n < 20` 인 테마-월은 값을 만들지 않고 **센다** (§2.1 · `CLAUDE.md` §2)."""
    rng = np.random.default_rng(5)
    tickers = [f"T{i:02d}" for i in range(12)]  # 20 미만
    panel = _panel("th", DATES, tickers, rng=rng)
    fwd = _forward(_close(DATES, tickers, rng))
    mcap = pd.DataFrame(1.0, index=DATES, columns=tickers)
    res = theme_month_selection(panel, fwd, mcap)
    assert res.excess.empty
    assert res.counts["theme_months"] == len(DATES)
    assert res.counts["theme_months_below_min_n"] == len(DATES)


def test_missing_mcap_is_counted_and_shrinks_only_b1() -> None:
    """`asof` 에 mcap 이 없는 종목은 B1 풀에서만 빠지고 **사유별로 센다** (§2.2 · §8.1 U1)."""
    rng = np.random.default_rng(7)
    tickers = [f"T{i:02d}" for i in range(25)]
    panel = _panel("th", DATES, tickers, rng=rng)
    fwd = _forward(_close(DATES, tickers, rng))
    mcap = pd.DataFrame(np.nan, index=DATES, columns=tickers)
    mcap.iloc[:, :2] = 1e9  # 시총이 있는 종목이 2개뿐 → B1 은 K 에 못 미친다
    res = theme_month_selection(panel, fwd, mcap)
    assert res.counts["pool_stock_months_no_mcap"] > 0
    assert res.counts["short_b1_mcap_missing"] > 0
    assert res.counts["B1_theme_months_short_of_k"] > 0
    assert res.counts["B3_theme_months_short_of_k"] == 0
    b1 = res.excess[(res.excess["candidate"] == "B1") & (res.excess["horizon"] == GATE_HORIZON)]
    assert (b1["n_selected"] <= 2).all()


def test_excess_is_against_theme_ew_index() -> None:
    """초과수익 = 후보 EW 수익 − 그 테마-월 EW 지수 수익 (§3.1, docs/14 §2.4 와 같은 정의)."""
    rng = np.random.default_rng(13)
    tickers = [f"T{i:02d}" for i in range(25)]
    panel = _panel("th", DATES, tickers, rng=rng)
    close = _close(DATES, tickers, rng)
    fwd = _forward(close)
    mcap = pd.DataFrame(rng.random((len(DATES), len(tickers))) * 1e9, index=DATES, columns=tickers)
    res = theme_month_selection(panel, fwd, mcap)
    sub = res.excess[res.excess["horizon"] == GATE_HORIZON]
    assert np.allclose(
        sub["excess"].to_numpy(), (sub["ret"] - sub["ret_theme_ew"]).to_numpy(), equal_nan=True
    )
    # B3 = 적격 전부의 EW. 제외 종목이 없으므로 테마 EW 와 같고 초과수익은 0 이다
    b3 = sub[sub["candidate"] == "B3"]
    assert np.allclose(b3["excess"].to_numpy(), 0.0, atol=1e-12)


# ---------------------------------------------------------------- §4 판정식


def test_call_is_one_sided_three_cells() -> None:
    """§4.1·§4.2 의 세 칸 그대로. 양측 검정으로 바꾸지 않고 '0 포함'을 약한 증거로 읽지 않는다."""
    assert _call(0.01, 0.05, "beats_B3", "worse_than_B3") == "beats_B3"
    assert _call(-0.05, -0.01, "beats_B3", "worse_than_B3") == "worse_than_B3"
    assert _call(-0.01, 0.05, "beats_B3", "worse_than_B3") == "indistinguishable"
    assert _call(0.0, 0.05, "beats_B3", "worse_than_B3") == "indistinguishable"  # 하한 0 은 불합격
    assert _call(-0.05, 0.0, "beats_B3", "worse_than_B3") == "indistinguishable"


@pytest.mark.parametrize(
    ("lo", "hi", "want"),
    [
        (0.01, 0.02, "beats_B3"),
        (-0.02, -0.01, "worse_than_B3"),
        (-0.01, 0.02, "indistinguishable"),
    ],
)
def test_verdict_primary_uses_pair_ci_lower_bound(lo: float, hi: float, want: str) -> None:
    """주 판정은 `X − B3` 차의 CI 하한을 본다 — 수준값이 아니다 (§4.1)."""
    pair = pd.DataFrame(
        [
            {
                "window": "primary",
                "horizon": GATE_HORIZON,
                "pair": name,
                "partition": PARTITION_ALL,
                "mean": (lo + hi) / 2,
                "ci_lo": lo,
                "ci_hi": hi,
                "n_months": 120,
                "n_months_dropped": 0,
                "n_eff": 40.0,
            }
            for name in PAIR_NAMES
        ]
    )
    overfit = {"dsr": [], "pbo": [], "trials": count_trials()}
    v = verdict(pd.DataFrame(), pair, overfit)
    assert v["dsr_pbo_in_gate"] is False
    for name in PRIMARY_PAIRS:
        assert v["primary_vs_b3_12m"][name]["call"] == want
    assert v["nobody_beats_b3"] is (want != "beats_B3")
    assert v["n_beating_b3"] == (3 if want == "beats_B3" else 0)


def test_verdict_secondary_names_b0_b1_and_b0_b2() -> None:
    """§4.2 의 두 비교와 그 칸 이름 (하한>0 현행 우위 / 상한<0 대장주 우위 / 0 포함 구분 안 됨)."""

    def row(pair: str, lo: float, hi: float) -> dict[str, Any]:
        return {
            "window": "primary",
            "horizon": GATE_HORIZON,
            "pair": pair,
            "partition": PARTITION_ALL,
            "mean": (lo + hi) / 2,
            "ci_lo": lo,
            "ci_hi": hi,
            "n_months": 100,
            "n_months_dropped": 0,
            "n_eff": 30.0,
        }

    pair = pd.DataFrame([row("B0-B1", -0.04, -0.01), row("B0-B2", -0.01, 0.01)])
    v = verdict(pd.DataFrame(), pair, {"dsr": [], "pbo": [], "trials": count_trials()})
    assert v["secondary_12m"]["B0-B1"]["call"] == "megacap_better"
    assert v["secondary_12m"]["B0-B2"]["call"] == "indistinguishable"


def test_pairwise_is_computed_at_theme_month_level() -> None:
    """차는 테마-월에서 먼저 만든다 — 두 후보가 같은 테마-월에서만 비교된다 (§4.1)."""
    ex = pd.DataFrame(
        [
            {"date": DATES[0], "theme": "a", "candidate": "B0", "horizon": 12, "excess": 0.10},
            {"date": DATES[0], "theme": "a", "candidate": "B3", "horizon": 12, "excess": 0.04},
            {"date": DATES[0], "theme": "b", "candidate": "B0", "horizon": 12, "excess": np.nan},
            {"date": DATES[0], "theme": "b", "candidate": "B3", "horizon": 12, "excess": 0.02},
        ]
    )
    pw = pairwise_theme_month(ex)
    got = pw[(pw["pair"] == "B0-B3") & (pw["theme"] == "a")]["excess"].iloc[0]
    assert got == pytest.approx(0.06)
    # B0 가 비어 있는 테마-월은 차가 NaN 이고 조용히 0 이 되지 않는다
    assert np.isnan(pw[(pw["pair"] == "B0-B3") & (pw["theme"] == "b")]["excess"].iloc[0])


# ---------------------------------------------------------------- 전 구간 통합


def test_run_structures_frames_end_to_end() -> None:
    """3 테마 × 48개월 합성으로 판정까지 돈다 — 값이 아니라 모양과 규약을 본다."""
    rng = np.random.default_rng(2)
    tickers = [f"T{i:02d}" for i in range(28)]
    panels = [_panel(f"th{i}", DATES, tickers, rng=rng, n_excl=3) for i in range(3)]
    panel = pd.concat(panels, ignore_index=True)
    close = _close(DATES, tickers, rng)
    fwd = _forward(close)
    mcap = pd.DataFrame(rng.random((len(DATES), len(tickers))) * 1e9, index=DATES, columns=tickers)
    res = run_structures_frames(panel, fwd, mcap, pbo_max_splits=64)
    assert set(res.level_summary["candidate"]) == set(CANDIDATES)
    assert set(res.pair_summary["pair"]) == set(PAIR_NAMES)
    for name in PRIMARY_PAIRS:
        assert res.verdict["primary_vs_b3_12m"][name]["call"] in (
            "beats_B3",
            "worse_than_B3",
            "indistinguishable",
        )
    assert res.verdict["baseline"] == "B3" and res.verdict["k"] == K
    assert res.overfitting["trials"]["total"] == count_trials()["total"]
    # 제외는 전부 세어져 있다 (`CLAUDE.md` §2)
    t = res.exclusions["totals"]
    assert t["theme_months"] == 3 * len(DATES)
    assert t["eligible_stock_months"] == 3 * len(DATES) * (len(tickers) - 3)
    for c in CANDIDATES:
        assert f"{c}_theme_months_short_of_k" in t and f"{c}_theme_months_empty" in t
    # 부차는 있되 판정에 들어가지 않는다
    assert not res.mortality_summary.empty and not res.turnover_summary.empty
    assert not res.composition.empty
    assert res.meta["limitations"] and res.meta["k"] == K
