"""README 히어로 이미지 — "지금 어느 산업이 잊혔나" 를 연도별 상대성과 히트맵 한 장으로.

행 = 테마(`state/themes.yaml` 의 L1 테마 가운데 **평균 시총 비중 상위 18개**, 섹터별로 묶음),
열 = 연도(1999 ~ 스토어 마지막 해, 마지막 해는 YTD), 값 = 그 해 테마 시총가중 지수의 수익률을
같은 해 SPY 수익률로 나눈 상대수익 `(1+r_theme)/(1+r_spy) − 1`.

데이터는 L1 스캔이 남긴 **테마 패널 캐시**(`state/cache/l1_panel_<지문>.parquet`, `msa.l1.panel`)다 —
`ret_cw`(전일 시총 가중 일별 수익률)·`mcap_sum`·SPY 종가. 스토어(Sharadar DuckDB, 읽기 전용)를
직접 읽지 않는다. 테마 선택 규칙(평균 시총 비중 상위 N)은 성과와 무관한 선언이며, 어떤 테마가
"잊혔는지" 는 그림이 아니라 L1 스캔(`msa scan`)이 판정한다. 이 그림은 측정값의 역사일 뿐
추천·매수 신호가 아니다 (`CLAUDE.md` §7·§8).

실행 (레포 루트):
    uv run --with matplotlib python scripts/make_hero.py            # 패널 캐시 → CSV + PNG 2장
    uv run --with matplotlib python scripts/make_hero.py --from-csv # 저장된 CSV 만으로 PNG 재생성

산출: docs/images/hero-light.png · hero-dark.png · hero-data.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hero_style import caption, render_both  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "images"
CSV = OUT_DIR / "hero-data.csv"

N_THEMES = 18  # 평균 시총 비중 상위 N — 선언값. 성과를 보고 고르지 않는다.
FIRST_YEAR = 1999  # 패널의 ret_cw 가 1998-12 에 시작하므로 첫 온전한 해
MIN_DAY_SHARE = 0.8  # 한 해의 수익률 일수가 SPY 거래일의 이 비율 미만이면 NaN (마지막 해 YTD 는 예외)
CLIP = 0.40  # 색 스케일 양 극 (±40%). 그 밖은 포화 — 범례에 적는다
GENERATED = "2026-10-19"

#: 테마 id → 그림 라벨(영어). 없는 id 는 id 를 그대로 다듬어 쓴다.
LABELS = {
    "banks_large": "Large banks",
    "banks_regional": "Regional banks",
    "asset_managers_exchanges": "Asset managers & exchanges",
    "insurance_diversified": "Diversified insurance",
    "pharma_large": "Large pharma",
    "medtech_devices": "Medical devices",
    "biotech_clinical": "Clinical-stage biotech",
    "telecom_carriers": "Telecom carriers",
    "internet_platform": "Internet platforms",
    "media_streaming": "Media & streaming",
    "intl_majors": "Integrated oil majors",
    "oil_gas_ep": "Oil & gas E&P",
    "semi_devices": "Semiconductors",
    "software_infra": "Infrastructure software",
    "software_vertical": "Vertical software",
    "networking_optical": "Networking & optical",
    "consumer_electronics": "Consumer electronics",
    "it_services": "IT services",
    "datacenter_hw": "Datacenter hardware",
    "defense": "Defense",
    "food_beverage": "Food & beverage",
    "household_products": "Household products",
    "retail_discount": "Discount retail",
    "utility_regulated": "Regulated utilities",
    "ecommerce": "E-commerce",
    "auto_oem": "Auto OEMs",
}

SECTOR_SHORT = {
    "Financial Services": "Financials",
    "Communication Services": "Comm. services",
    "Consumer Defensive": "Cons. defensive",
    "Consumer Cyclical": "Cons. cyclical",
    "Basic Materials": "Materials",
    "Real Estate": "Real estate",
}


def _label(theme: str) -> str:
    return LABELS.get(theme, theme.replace("_", " ").capitalize())


# ── 데이터 ──────────────────────────────────────────────────────────────────


def build_from_panel() -> tuple[pd.DataFrame, dict[str, str]]:
    """패널 캐시(최신 지문) → 긴 형식 표. 레포 패키지(`msa`)가 필요하다 — `uv run` 으로 돈다."""
    import yaml

    from msa.l1.panel import load_cached_panel

    panel = load_cached_panel()
    meta = panel.built_from
    ret = panel.wide("ret_cw")
    mcap = panel.wide("mcap_sum")
    spy = panel.spy["close"].astype(float)
    spy.index = pd.to_datetime(spy.index)
    ret.index = pd.to_datetime(ret.index)
    mcap.index = pd.to_datetime(mcap.index)

    themes = yaml.safe_load((ROOT / "state" / "themes.yaml").read_text())["themes"]
    sector = {t["id"]: t["parent_sector"] for t in themes}

    # 행 선택: 전 기간 평균 시총 비중 상위 N (성과와 무관한 규칙)
    share = mcap.div(mcap.sum(axis=1), axis=0).mean().sort_values(ascending=False)
    chosen = list(share.index[:N_THEMES])

    # 연도별 복리 수익률. SPY 는 연말 종가 기준
    years = ret.index.year
    theme_y = (1.0 + ret[chosen]).groupby(years).prod() - 1.0
    n_days = ret[chosen].notna().groupby(years).sum()
    spy_eoy = spy.groupby(spy.index.year).last()
    spy_y = spy_eoy / spy_eoy.shift(1) - 1.0
    spy_days = spy.groupby(spy.index.year).size()

    last_year = int(ret.index.max().year)
    rows = []
    for y in range(FIRST_YEAR, last_year + 1):
        if y not in spy_y.index or pd.isna(spy_y[y]):
            continue
        for th in chosen:
            n = int(n_days.loc[y, th]) if y in n_days.index else 0
            full = n >= MIN_DAY_SHARE * int(spy_days.get(y, 0))
            if y == last_year or full:
                rel = (1.0 + float(theme_y.loc[y, th])) / (1.0 + float(spy_y[y])) - 1.0
                tr = float(theme_y.loc[y, th])
            else:
                rel, tr = np.nan, np.nan
            rows.append(
                {
                    "theme": th,
                    "label": _label(th),
                    "sector": sector[th],
                    "mcap_share_mean": round(float(share[th]), 5),
                    "year": y,
                    "theme_return": tr,
                    "spy_return": float(spy_y[y]),
                    "rel_return": rel,
                    "n_days": n,
                }
            )
    df = pd.DataFrame(rows)
    info = {
        "store_end": str(meta.get("store_end", "")),
        "fingerprint": str(meta.get("fingerprint", "")),
        "last_date": str(ret.index.max().date()),
    }
    return df, info


def save_csv(df: pd.DataFrame, info: dict[str, str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    header = (
        f"# source=L1 theme panel cache (Sharadar store, read-only) fingerprint={info['fingerprint']} "
        f"store_end={info['store_end']} last_date={info['last_date']} generated={GENERATED}\n"
    )
    with CSV.open("w", encoding="utf-8") as f:
        f.write(header)
        df.to_csv(f, index=False, float_format="%.6f")


def load_csv() -> tuple[pd.DataFrame, dict[str, str]]:
    head = CSV.read_text(encoding="utf-8").splitlines()[0]
    info = dict(kv.split("=", 1) for kv in head.lstrip("# ").split(" ") if "=" in kv)
    df = pd.read_csv(CSV, comment="#")
    return df, info


# ── 그림 ────────────────────────────────────────────────────────────────────


def make_draw(df: pd.DataFrame, info: dict[str, str]):
    from matplotlib.colors import LinearSegmentedColormap, Normalize

    # 행 순서: 섹터(총 시총 비중 내림차순) → 테마(비중 내림차순). 섹터 사이는 약간 띄운다.
    tshare = df.groupby("theme")["mcap_share_mean"].first()
    tsector = df.groupby("theme")["sector"].first()
    sec_order = tshare.groupby(tsector).sum().sort_values(ascending=False).index.tolist()
    order: list[str] = []
    groups: list[tuple[str, int, int]] = []  # (sector, start_row, end_row)
    for s in sec_order:
        ids = tshare[tsector == s].sort_values(ascending=False).index.tolist()
        groups.append((s, len(order), len(order) + len(ids)))
        order.extend(ids)

    years = sorted(df["year"].unique())
    last_year = int(years[-1])
    mat = df.pivot(index="theme", columns="year", values="rel_return").loc[order, years]
    labels = [_label(t) for t in order]

    gap = 0.45
    # pcolormesh 는 연속 격자를 쓰므로 섹터 간격은 NaN 행(높이 gap)으로 넣는다
    ys: list[float] = [0.0]
    rows_data: list[np.ndarray] = []
    row_centers: list[float] = []
    cur = 0.0
    for gi, (s, a, b) in enumerate(groups):
        if gi > 0:
            rows_data.append(np.full(len(years), np.nan))
            cur += gap
            ys.append(cur)
        for r in range(a, b):
            rows_data.append(mat.iloc[r].to_numpy(dtype=float))
            row_centers.append(cur + 0.5)
            cur += 1.0
            ys.append(cur)
    data = np.vstack(rows_data)
    total_h = cur
    x_edges = np.arange(len(years) + 1, dtype=float)

    def draw(fig, ax, p):
        cmap = LinearSegmentedColormap.from_list("rel", [p["amber"], p["grid"], p["blue"]])
        cmap.set_bad(p["surface"])
        norm = Normalize(vmin=-CLIP, vmax=CLIP, clip=True)
        mesh = ax.pcolormesh(
            x_edges,
            np.array(ys),
            np.ma.masked_invalid(data),
            cmap=cmap,
            norm=norm,
            edgecolors=p["surface"],
            linewidth=0.72,  # 2px @ 200dpi
            shading="flat",
        )
        ax.set_ylim(total_h, 0)
        ax.set_xlim(0, len(years))
        ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.tick_params(length=0, pad=4)

        ax.set_yticks(row_centers)
        ax.set_yticklabels(labels, fontsize=10.5, color=p["ink"])
        xt = [str(y) if y != last_year else f"{y}\nYTD" for y in years]
        ax.set_xticks(x_edges[:-1] + 0.5)
        ax.set_xticklabels(xt, fontsize=9, color=p["ink2"])
        ax.xaxis.set_ticks_position("top")
        ax.xaxis.set_label_position("top")

        # 섹터 라벨 — 오른쪽, 그룹 중앙
        for s, a, b in groups:
            yc = (row_centers[a] + row_centers[b - 1]) / 2
            ax.text(
                len(years) + 0.35,
                yc,
                SECTOR_SHORT.get(s, s),
                fontsize=9,
                color=p["ink3"],
                va="center",
                ha="left",
                clip_on=False,
            )

        # 컬러바 — 아래 가로
        cb = fig.colorbar(
            mesh,
            ax=ax,
            orientation="horizontal",
            fraction=0.035,
            pad=0.04,
            aspect=45,
            shrink=0.42,
            anchor=(0.0, 1.0),
        )
        cb.outline.set_visible(False)
        cb.set_ticks([-CLIP, -CLIP / 2, 0, CLIP / 2, CLIP])
        cb.set_ticklabels([f"{int(t * 100):+d}%" if t else "0" for t in cb.get_ticks()])
        cb.ax.tick_params(labelsize=9, colors=p["ink2"], length=0)
        cb.set_label(
            "Theme return relative to SPY in the year, (1+r)/(1+r_spy) − 1  (colour saturates beyond ±40%)",
            fontsize=9,
            color=p["ink2"],
            loc="left",
        )

        fig.suptitle(
            "Which industry has been forgotten? Relative performance vs. the market, by year",
            x=0.0,
            y=1.02,
            ha="left",
            fontsize=15,
            fontweight="bold",
            color=p["ink"],
        )
        fig.text(
            0.0,
            0.985,
            "Cap-weighted US industry themes — blue: beat SPY that year, amber: lagged. "
            f"Rows: the {len(order)} largest themes by average market-cap share, grouped by sector.",
            ha="left",
            va="top",
            fontsize=10.5,
            color=p["ink2"],
        )
        caption(
            fig,
            f"Source: Sharadar daily prices via the repo's L1 theme panel (local read-only store, "
            f"data through {info['store_end']}) · {years[0]}–{last_year} ({last_year} to "
            f"{info['last_date']}) · SPY = market · not investment advice · generated {GENERATED}",
            p,
        )
        fig.subplots_adjust(left=0.0, right=1.0, top=0.9, bottom=0.08)

    return draw


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--from-csv", action="store_true", help="패널 캐시 대신 docs/images/hero-data.csv 를 읽는다")
    args = ap.parse_args()
    if args.from_csv:
        df, info = load_csv()
    else:
        df, info = build_from_panel()
        save_csv(df, info)
        print(f"wrote {CSV} ({len(df)} rows, {df['theme'].nunique()} themes, {df['year'].nunique()} years)")
    paths = render_both(make_draw(df, info), out_dir=str(OUT_DIR), name="hero", figsize=(12, 6.6))
    for pth in paths:
        print(f"wrote {pth}")


if __name__ == "__main__":
    main()
