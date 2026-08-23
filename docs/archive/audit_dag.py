#!/usr/bin/env python3
"""거시 인과 DAG 커버리지 감사 (M4) — **L2 제거(2026-08-23) 이전 기록**.

`docs/archive/macro-dag.yaml` 을 대상으로 여전히 돈다 (`uv run --with pyyaml python docs/archive/audit_dag.py`).
`msa.l2` 를 임포트하지 않는 독립 스크립트라 보존한다. 현행 파이프라인의 일부가 아니다.

검사 항목 (docs/11-roadmap.md M4, docs/03-macro-dag.md §3):
  1. 모든 테마가 입력 엣지 >= 2 (공통 인자 엣지는 세지 않는다)
  2. `channel` 이 빈 엣지 0개 — 메커니즘 없는 상관은 엣지가 아니다
  3. `from` 이 드라이버 목록에 있고, `to` 가 테마 id (또는 공통 인자의 "*")
  4. 필수 필드 존재 (from/to/sign/strength/channel/observable)
  5. `common_factor: true` 드라이버 목록 — tailwind 계산에서 횡단면 중앙값 차감 대상
  6. 드라이버별 out-degree, 테마별 in-degree 분포

테마 id 의 정본은 `state/themes.yaml` 이다. 없으면 `docs/01-theme-universe.md` §3
초안에서 파싱한다 (M2 확정 전 상태). 어느 쪽을 썼는지 반드시 출력한다.

조용한 절단 금지 (CLAUDE.md §2): 테마 목록이 비거나 파싱 결과가 0개면 예외를 던진다.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DAG_PATH = ROOT / "docs" / "archive" / "macro-dag.yaml"
THEMES_PATH = ROOT / "state" / "themes.yaml"
THEME_DOC = ROOT / "docs" / "01-theme-universe.md"

REQUIRED_EDGE_FIELDS = ("from", "to", "sign", "strength", "channel", "observable")
VALID_STRENGTH = {"strong", "moderate", "weak"}
STRENGTH_WEIGHT = {"strong": 3, "moderate": 2, "weak": 1}


def load_themes() -> tuple[list[str], str]:
    """테마 id 목록과 그 출처를 돌려준다."""
    if THEMES_PATH.exists():
        doc = yaml.safe_load(THEMES_PATH.read_text(encoding="utf-8"))
        buckets = doc.get("themes") if isinstance(doc, dict) else doc
        ids = [b["id"] for b in buckets]
        if not ids:
            raise RuntimeError(f"{THEMES_PATH} 를 읽었으나 테마가 0개다 — 조용한 절단 의심")
        return ids, f"{THEMES_PATH.name} (정본)"

    # 폴백: docs/01 §3 초안 표/서술에서 스네이크케이스 id 를 긁는다.
    text = THEME_DOC.read_text(encoding="utf-8")
    section = text.split("## 3.", 1)[1].split("\n## 4.", 1)[0]
    ids: list[str] = []
    for match in re.finditer(r"`([a-z][a-z0-9_]{2,})`", section):
        tid = match.group(1)
        if tid in ids:
            continue
        ids.append(tid)
    # §3 안에는 cycle_class 이름도 백틱으로 등장한다 — 제외한다.
    cycle_classes = {
        "commodity_supply", "inventory", "credit_rate", "capex_program",
        "policy_program", "discretionary_demand", "secular_growth", "secular_risk",
        "industry", "notes", "include", "coal_met", "cycle_class",
    }
    ids = [t for t in ids if t not in cycle_classes]
    if not ids:
        raise RuntimeError(f"{THEME_DOC} §3 에서 테마 id 를 하나도 파싱하지 못했다 — 조용한 절단 의심")
    return ids, f"{THEME_DOC.name} §3 초안 (state/themes.yaml 미존재)"


def main() -> int:
    dag = yaml.safe_load(DAG_PATH.read_text(encoding="utf-8"))
    drivers = dag["drivers"]
    edges = dag["edges"]
    driver_ids = [d["id"] for d in drivers]
    themes, theme_source = load_themes()

    failures: list[str] = []
    warnings: list[str] = []

    print("=" * 74)
    print("거시 인과 DAG 감사")
    print("=" * 74)
    print(f"드라이버 {len(drivers)}개 · 엣지 레코드 {len(edges)}개")
    print(f"테마 {len(themes)}개 — 출처: {theme_source}")
    print()

    # --- 드라이버 검사 ---------------------------------------------------
    dup = [d for d, n in Counter(driver_ids).items() if n > 1]
    if dup:
        failures.append(f"드라이버 id 중복: {dup}")
    common_factors = [d["id"] for d in drivers if d.get("common_factor")]
    for d in drivers:
        if "source" not in d or "state_rule" not in d:
            failures.append(f"드라이버 {d['id']}: source 또는 state_rule 누락")
        if "common_factor" not in d:
            warnings.append(f"드라이버 {d['id']}: common_factor 미선언 (false 로 간주)")

    print(f"[공통 인자] {len(common_factors)}개 — tailwind 계산에서 횡단면 중앙값 차감 대상")
    for cid in common_factors:
        print(f"  - {cid}")
    print()

    # --- 엣지 검사 -------------------------------------------------------
    in_degree: Counter[str] = Counter()          # 공통 인자 제외 (하한 판정용)
    in_degree_all: Counter[str] = Counter()      # 공통 인자 포함
    in_weight: Counter[str] = Counter()
    out_degree: Counter[str] = Counter()
    theme_set = set(themes)

    for i, e in enumerate(edges):
        tag = f"엣지[{i}] {e.get('from')} -> {str(e.get('to'))[:40]}"
        for field in REQUIRED_EDGE_FIELDS:
            if field not in e:
                failures.append(f"{tag}: 필수 필드 `{field}` 누락")
        channel = str(e.get("channel", "")).strip()
        if not channel:
            failures.append(f"{tag}: `channel` 이 비었다 — 메커니즘 없는 상관은 엣지가 아니다")
        if e.get("sign") not in (1, -1):
            failures.append(f"{tag}: sign 은 +1 또는 -1 이어야 한다 (현재 {e.get('sign')!r})")
        if e.get("strength") not in VALID_STRENGTH:
            failures.append(f"{tag}: strength 가 {sorted(VALID_STRENGTH)} 밖 ({e.get('strength')!r})")
        src = e.get("from")
        if src not in driver_ids:
            failures.append(f"{tag}: from `{src}` 가 드라이버 목록에 없다")
            continue

        is_common = src in common_factors
        targets = e["to"] if isinstance(e["to"], list) else [e["to"]]
        if targets == ["*"]:
            if not is_common:
                failures.append(f"{tag}: 와일드카드 `*` 는 common_factor 드라이버만 쓸 수 있다")
            out_degree[src] += len(themes)
            for t in themes:
                in_degree_all[t] += 1
            continue
        if is_common:
            failures.append(f"{tag}: common_factor 드라이버가 개별 테마를 지목했다 — `*` 를 쓰거나 common_factor 를 내려라")
        for t in targets:
            if t not in theme_set:
                failures.append(f"{tag}: to `{t}` 가 테마 id 가 아니다")
                continue
            out_degree[src] += 1
            in_degree[t] += 1
            in_degree_all[t] += 1
            in_weight[t] += STRENGTH_WEIGHT[e["strength"]]

    # --- 커버리지 --------------------------------------------------------
    under = sorted(t for t in themes if in_degree[t] < 2)
    total_pairs = sum(in_degree.values())
    counts = sorted(in_degree[t] for t in themes)
    median = counts[len(counts) // 2] if counts else 0

    print(f"[커버리지] 테마-엣지 쌍 {total_pairs}개 (공통 인자 제외) / 하한 {2 * len(themes)}")
    print(f"  in-degree  min={counts[0] if counts else 0}  median={median}  max={counts[-1] if counts else 0}")
    print(f"  입력 엣지 2개 미만 테마: {len(under)}개")
    for t in under:
        print(f"    ! {t} (in-degree={in_degree[t]})")
    if under:
        failures.append(f"입력 엣지 2개 미만 테마 {len(under)}개: {under}")
    print()

    print("[드라이버별 out-degree] (테마-엣지 쌍 기준, `*` 는 전 테마로 전개)")
    for did in driver_ids:
        mark = " [공통]" if did in common_factors else ""
        print(f"  {out_degree[did]:>4}  {did}{mark}")
    print()

    print("[테마별 in-degree 분포] (공통 인자 제외)")
    dist = Counter(in_degree[t] for t in themes)
    for k in sorted(dist):
        print(f"  in-degree {k:>2}: 테마 {dist[k]:>3}개  {'#' * dist[k]}")
    print()

    top = sorted(themes, key=lambda t: (-in_degree[t], t))[:5]
    bottom = sorted(themes, key=lambda t: (in_degree[t], t))[:5]
    print(f"  최다: {', '.join(f'{t}({in_degree[t]})' for t in top)}")
    print(f"  최소: {', '.join(f'{t}({in_degree[t]})' for t in bottom)}")
    print()

    # --- 결과 ------------------------------------------------------------
    if warnings:
        print(f"[경고] {len(warnings)}건")
        for w in warnings:
            print(f"  - {w}")
        print()

    if failures:
        print(f"[실패] {len(failures)}건")
        for f in failures:
            print(f"  ! {f}")
        return 1

    print("[통과] 전 항목 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
