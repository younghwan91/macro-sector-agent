"""테마 버킷 커버리지 감사 — docs/01-theme-universe.md §5

실행:
    uv run --with duckdb --with pyyaml python scripts/audit_themes.py

데이터는 읽기 전용으로만 연다. 산출물은 stdout 표이며,
docs/theme-coverage-audit.md 의 수치는 이 스크립트에서 나온다.

구성원 해석 규칙 (state/themes.yaml 머리말과 동일):
  0. 유니버스 = category LIKE '%Common Stock%' AND NOT LIKE '%Preferred%'
  1. exclude_tickers 가 버킷에서 티커를 뺀다.
  2. include_tickers 가 티커를 배정하며 industry_match 를 덮어쓴다.
  3. 나머지는 industry_match 로 배정한다.
  4. 'Shell Companies' 라벨은 의도적 미배정 — 분모 밖으로 뺀다.
"""

from __future__ import annotations

import collections
import pathlib
import sys

import duckdb
import yaml

DB = "/home/young/data/us_micro.duckdb"
ROOT = pathlib.Path(__file__).resolve().parent.parent
THEMES = ROOT / "state" / "themes.yaml"

# 영업 실체가 없어 사이클이 정의되지 않는 라벨. 미분류 시총 분모에서 뺀다.
EXCLUDED_LABELS = {"Shell Companies"}

UNIVERSE_SQL = """
    select ticker, coalesce(sector, '(null)') as sector,
           coalesce(industry, '(null)') as industry, is_delisted
    from tickers
    where category like '%Common Stock%' and category not like '%Preferred%'
"""
MCAP_SQL = """
    select ticker, mcap from (
        select ticker, mcap,
               row_number() over (partition by ticker order by date desc) rn
        from prices where mcap is not null
    ) where rn = 1
"""


def load_themes():
    spec = yaml.safe_load(THEMES.read_text())
    return spec["themes"]


def assign(themes, universe):
    """티커 → 버킷 id. 중복 소속을 오류 목록으로 함께 돌려준다."""
    by_label: dict[str, str] = {}
    label_dupes: list[tuple[str, str, str]] = []
    for t in themes:
        for label in t["industry_match"]:
            if label in by_label:
                label_dupes.append((label, by_label[label], t["id"]))
            by_label[label] = t["id"]

    includes: dict[str, str] = {}
    include_dupes: list[tuple[str, str, str]] = []
    for t in themes:
        for tk in t["include_tickers"]:
            if tk in includes:
                include_dupes.append((tk, includes[tk], t["id"]))
            includes[tk] = t["id"]

    excludes: dict[str, set[str]] = {
        t["id"]: set(t["exclude_tickers"]) for t in themes
    }

    assigned: dict[str, str] = {}
    for tk, _sector, industry, _dl in universe:
        bucket = includes.get(tk) or by_label.get(industry)
        if bucket is None:
            continue
        if tk in excludes[bucket]:
            continue  # exclude 는 자동 매칭을 되돌린다 (include 는 위에서 우선)
        assigned[tk] = bucket
    return assigned, label_dupes, include_dupes


def main() -> int:
    con = duckdb.connect(DB, read_only=True)
    universe = con.execute(UNIVERSE_SQL).fetchall()
    mcap = dict(con.execute(MCAP_SQL).fetchall())

    themes = load_themes()
    assigned, label_dupes, include_dupes = assign(themes, universe)

    live = {tk for tk, _s, _i, dl in universe if dl == "N"}
    label_of = {tk: ind for tk, _s, ind, _dl in universe}

    def live_mcap(tk):
        return mcap.get(tk, 0.0) if tk in live else 0.0

    denom = sum(
        live_mcap(tk)
        for tk, _s, ind, _dl in universe
        if ind not in EXCLUDED_LABELS
    )
    covered = sum(
        live_mcap(tk)
        for tk in assigned
        if label_of[tk] not in EXCLUDED_LABELS
    )
    unclassified = denom - covered

    print("=" * 78)
    print("1. 미분류 시총 비율 (기준 < 5%)")
    print("=" * 78)
    print(f"  유니버스 종목 수        : {len(universe):,}")
    print(f"  배정된 종목 수          : {len(assigned):,}")
    print(f"  분모 시총 (생존, Shell 제외): {denom/1e6:,.0f} M USD")
    print(f"  미분류 시총             : {unclassified/1e6:,.0f} M USD")
    print(f"  미분류 비율             : {unclassified/denom*100:.3f}%   "
          f"→ {'PASS' if unclassified/denom < 0.05 else 'FAIL'}")

    shell_mcap = sum(
        live_mcap(tk) for tk, _s, ind, _dl in universe if ind in EXCLUDED_LABELS
    )
    shell_n = sum(1 for _t, _s, ind, _d in universe if ind in EXCLUDED_LABELS)
    print(f"  [분모 밖] Shell Companies: {shell_n:,}종목 / {shell_mcap/1e6:,.0f} M USD")

    unmatched = collections.Counter()
    unmatched_mcap = collections.Counter()
    for tk, _s, ind, _dl in universe:
        if tk not in assigned and ind not in EXCLUDED_LABELS:
            unmatched[ind] += 1
            unmatched_mcap[ind] += live_mcap(tk)
    if unmatched:
        print("\n  어느 버킷에도 안 들어간 industry 라벨:")
        for ind, n in unmatched.most_common():
            print(f"    {ind:<44} n={n:<6} mcap={unmatched_mcap[ind]/1e6:,.0f} M")

    print()
    print("=" * 78)
    print("2. 중복 소속 티커 (기준 0개)")
    print("=" * 78)
    print(f"  industry 라벨 중복 배정 : {len(label_dupes)}건")
    for label, a, b in label_dupes:
        print(f"    {label}: {a} vs {b}")
    print(f"  include_tickers 중복    : {len(include_dupes)}건")
    for tk, a, b in include_dupes:
        print(f"    {tk}: {a} vs {b}")
    total_dupes = len(label_dupes) + len(include_dupes)
    print(f"  → {'PASS' if total_dupes == 0 else 'FAIL'}")

    members = collections.defaultdict(list)
    for tk, bid in assigned.items():
        members[bid].append(tk)

    print()
    print("=" * 78)
    print("3. min_constituents 미달 버킷 (생존 종목 기준)")
    print("=" * 78)
    short = []
    for t in themes:
        n_live = sum(1 for tk in members[t["id"]] if tk in live)
        if n_live < t["min_constituents"]:
            short.append((t["id"], n_live, t["min_constituents"]))
    for bid, n, need in sorted(short, key=lambda r: r[1]):
        print(f"    {bid:<28} 생존 {n}종목 (기준 {need})")
    print(f"  미달 {len(short)}개 / 전체 {len(themes)}개")

    print()
    print("=" * 78)
    print("4. 폐지 종목 포함 여부 (자기이력 구간에 반드시 포함)")
    print("=" * 78)
    n_delisted = sum(1 for tk in assigned if tk not in live)
    print(f"  배정된 폐지 종목        : {n_delisted:,} / 전체 배정 {len(assigned):,}")
    nodel = [t["id"] for t in themes
             if not any(tk not in live for tk in members[t["id"]])]
    print(f"  폐지 구성원이 0인 버킷  : {len(nodel)}개")
    for bid in nodel:
        print(f"    {bid}")

    print()
    print("=" * 78)
    print("5. 버킷별 구성원 수 · 시총")
    print("=" * 78)
    print(f"  {'id':<28}{'cycle_class':<22}{'n':>6}{'live':>6}"
          f"{'mcap(M)':>14}  ax1")
    rows = []
    for t in themes:
        ms = members[t["id"]]
        rows.append((
            t["id"], t["cycle_class"], len(ms),
            sum(1 for tk in ms if tk in live),
            sum(live_mcap(tk) for tk in ms),
            "Y" if t["physical_ref"] else "-",
        ))
    for r in sorted(rows, key=lambda r: -r[4]):
        print(f"  {r[0]:<28}{r[1]:<22}{r[2]:>6}{r[3]:>6}{r[4]/1e6:>14,.0f}   {r[5]}")

    print()
    print("=" * 78)
    print("6. 요약")
    print("=" * 78)
    ax1 = sum(1 for t in themes if t["physical_ref"])
    print(f"  확정 버킷 수            : {len(themes)}")
    print(f"  축 1 적용 가능 (physical_ref 있음): {ax1}"
          f"  / 불가: {len(themes) - ax1}")
    cc = collections.Counter(t["cycle_class"] for t in themes)
    for k, v in cc.most_common():
        print(f"    {k:<24}{v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
