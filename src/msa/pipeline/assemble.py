"""L4 `state/picks/` + L3 `state/theses/` → L5 입력 묶음 (`msa portfolio-inputs`).

L5 는 L4·L3 를 임포트하지 않고 **파일 계약**(`src/msa/l5/inputs.py` 머리말)으로만 받는다. 이 모듈이
그 파일을 만든다 — `state/picks/<date≤asof>/<theme>/ranking.csv` 와
`state/theses/<date≤asof>/<theme>.thesis.yaml` (또는 사람이 쓴 논지 디렉터리)을 찾아
`<out>/picks.csv` · `<out>/theses/<theme>.yaml` · `<out>/assemble_report.json` · `<out>/report.txt`
를 쓴다. 그 디렉터리를 `msa portfolio --inputs <out>` 이 그대로 읽는다.

## `picks.csv` — `ranking.csv` 에서 무엇을 옮기는가

| L5 열 | L4 원천 | 비고 |
|---|---|---|
| `theme` | 디렉터리 이름 | |
| `ticker` | `ranking.csv` index | |
| `role` | `group` (`ELIGIBLE`→`eligible`; 옛 `ANCHOR`→`anchor` · `TORQUE`→`torque`) | 아래 |
| `entry_price` | `price` | asof 이하 마지막 비조정 종가 (`features.ENTRY_PRICE_FEATURE`) |
| `adv20_usd` | `adv20_usd` | C4 유동성 |
| `rank_score` | `composite` | 0.40·S̃ + 0.40·T̃ + 0.20·M̃ — **관찰 지표. 선정에 쓰이지 않는다** |
| `notes` | `rank`·`group`·`barbell_obs`·3축 백분위·플래그·`composite_partial`·결측 | 표기용 |

### `role` — 2026-08-24 개정

L4 의 선정은 **하드 제외 통과 종목 전부 · 테마 내 동일가중**이 됐다 (`docs/15` §5 의 사전 등록된
조치 · `journal/2026-08-24-l4-selection-retired.md`). 그래서 `ranking.csv` 의 `group` 은 전 행이
`ELIGIBLE`(`l4.picks.SELECTION_GROUP`)이고, `role` 도 전 행이 `eligible` 이다 — **행을 가르는
값이 아니다.** 옛 스냅샷의 `ANCHOR`/`TORQUE` 는 그대로 읽힌다 (그때는 그 값이 선정이었다).

따라 나오는 것 둘, 여기 적어 둔다:

- `by_role` 계수와 L5 의 `anchor_share` 진단은 오늘 산출물에서 각각 `eligible` 한 칸과 0 이 된다.
  L4 가 더 이상 앵커를 지정하지 않기 때문이지 앵커를 0% 로 정한 것이 아니다. "옛 규칙이라면
  무엇이 앵커였을까" 는 `ranking.csv` 의 `barbell_obs` 열에 관찰로 남아 있다.
- **테마당 몇 종목까지 실제로 들 것인가(K)는 정해져 있지 않다.** `top_per_theme` 은 사람이 주는
  상한이고 L4 의 규칙이 아니다 — K 를 규칙으로 만들려면 새 사전 등록이 필요하다 (`docs/06` §6.2).

**쓰지 않는 열과 이유는 `OMITTED_COLUMNS`** 에 있고 리포트에 매번 찍힌다 — L4 가 내지 않는 값을
여기서 만들어 넣지 않는다 (`idio_vol_ann`·`tp_*`·`prev_cycle_peak_price`·`min_weight`·
`split_first_leg`). `docs/06` §5 의 옵션 그룹(로열티·미드스트림·ETF)은 L4 가 태깅하지 않으므로
(§8.4) 매핑이 없다 — 모르는 `group` 값은 제외하고 센다.

## `theses/<theme>.yaml` — thesis 객체에서 무엇을 옮기는가

`thesis_input_from_l3` 가 `docs/specs/thesis.schema.yaml` 객체에서 `parse_thesis` 가 읽는 부분집합만
꺼낸다: `theme_id` · `horizon_months` · `cycle_confidence` · **`cycle_confidence_source`**
(호출자는 **위치로** 안다 — L3 산출은 `referee`, 사람 논지는 `human`. yaml 이 주체를 적어 두면
그것이 이기고, 그중에서도 기계가 쓴 `cycle_confidence_by` 가 손기재 `confidence_provenance`·
`cycle_confidence_source` 보다 앞선다 — `_declared_source`) · `invalidations` · `triggers` ·
`gate_result{status, portfolio_eligible, rule, path}` · `value_trap_axes.unit_demand{verdict,
axis1_available, unit_series_source}`. 게이트 편입 불가(`contested`·`rejected`·`portfolio_eligible:
false`)인 테마는 **묶음에서 빠지고 사유가 남는다.**

제외·건너뜀은 전부 **수와 사유**로 보고한다 (`CLAUDE.md` §2). 한 테마도 남지 않으면 예외다.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from msa.config import paths, rel
from msa.dates import parse_date
from msa.errors import RefusedInput
from msa.io import write_snapshot
from msa.l1.scan import scan_dirs
from msa.l4.features import ENTRY_PRICE_FEATURE, LIQUIDITY_FEATURE
from msa.l4.picks import read_ranking
from msa.l5.inputs import (
    PICK_ROLES,
    InputError,
    ThesisInput,
    load_picks,
    load_theses,
    parse_thesis,
)
from msa.thesis import (
    CONFIDENCE_PROVENANCE,
    dump_thesis_yaml,
    read_thesis_yaml,
    thesis_filename,
)

log = logging.getLogger(__name__)


class AssembleError(RefusedInput, ValueError):
    """배선 입력이 없거나 계약을 어긴다 — 빈 묶음을 만들지 않고 던진다 (`CLAUDE.md` §2)."""


#: L4 바벨 라벨 → L5 role (`docs/06` §5). 옵션 그룹(royalty·midstream·etf)은 L4 가 태깅하지 않는다
#: (`docs/06` §8.4) — 매핑이 없고, 모르는 라벨은 제외하고 센다.
#: `ranking.csv` 의 `group` → L5 `role`. `ELIGIBLE` 이 2026-08-24 이후의 값이고, `ANCHOR`/
#: `TORQUE` 는 그 이전 스냅샷을 계속 읽기 위해 남는다 (머리말 "`role` — 2026-08-24 개정").
ROLE_BY_GROUP: Mapping[str, str] = {
    "ELIGIBLE": "eligible",
    "ANCHOR": "anchor",
    "TORQUE": "torque",
}
assert set(ROLE_BY_GROUP.values()) <= set(PICK_ROLES)

#: `picks.csv` 에 쓰는 열 (순서 = 파일 순서). 전부 `load_picks` 계약 안이다.
PICKS_COLUMNS: tuple[str, ...] = (
    "theme",
    "ticker",
    "role",
    "entry_price",
    "adv20_usd",
    "rank_score",
    "notes",
)

#: 계약에는 있으나 **쓰지 않는** 열과 이유. L4 가 내지 않는 값을 만들어 넣지 않는다.
OMITTED_COLUMNS: dict[str, str] = {
    "idio_vol_ann": (
        "L4 특성 표(features.FEATURE_COLUMNS)에 종목 고유 변동성이 없다 — L5 는 0 으로 두고 "
        "같은 테마 종목을 상관 1 로 본다 (docs/07 구현 노트 4)"
    ),
    "min_weight": "하한 비중은 L4 산출이 아니다 — 필요하면 사람이 picks.csv 에 넣는다 (기본 0)",
    "split_first_leg": (
        "docs/07 §3 'M 축이 낮으면 25%+25% 분할' 의 컷이 문서에 없다 — 컷을 만들지 않는다 "
        "(CLAUDE.md §1). M̃ 는 notes 에 적혀 있어 사람이 정할 수 있다"
    ),
    "tp_p50_price": "테마 밸류 백분위 P50 회복가 — L4 가 아직 내지 않는다 (docs/07 구현 노트 8)",
    "tp_p75_price": "테마 밸류 백분위 P75 회복가 — L4 가 아직 내지 않는다 (docs/07 구현 노트 8)",
    "prev_cycle_peak_price": "직전 사이클 고점가 — L4 특성 표에 없다",
}

#: `ranking.csv` 에서 없으면 안 되는 열. 나머지 내보내기 열은 없으면 빈 값 + 리포트 표기.
_RANKING_REQUIRED: tuple[str, ...] = ("group", "rank", "composite")
_RANKING_VALUE_COLS: tuple[str, ...] = (ENTRY_PRICE_FEATURE, LIQUIDITY_FEATURE)

#: thesis 객체에서 `picks` 묶음으로 옮기는 트리거/무효화 항목의 키 (`parse_thesis._observables`
#: 가 읽는 `observable`·`source` + 상태·기한·행동).
_OBS_KEYS: tuple[str, ...] = ("observable", "source", "by", "action", "status")


# ---------------------------------------------------------------- picks


@dataclass(frozen=True)
class PicksAssembly:
    """`picks_csv_from_rankings` 의 결과 — 계약 프레임 + 제외 장부."""

    frame: pd.DataFrame  # PICKS_COLUMNS
    excluded: pd.DataFrame  # theme · ticker · reason
    counts: dict[str, int]  # 제외 사유 → 건수
    themes_without_picks: tuple[str, ...]  # 한 행도 남지 않은 테마
    missing_inputs: dict[str, tuple[str, ...]]  # 테마 → ranking.csv 에 없던 내보내기 열
    columns_omitted: Mapping[str, str] = field(default_factory=lambda: dict(OMITTED_COLUMNS))

    @property
    def n_included(self) -> int:
        return len(self.frame)


def _cell(row: pd.Series, key: str) -> Any:
    """행의 값 — 열이 없거나 NaN/None 이면 None."""
    if key not in row.index:
        return None
    v = row[key]
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
        return None
    return v


def _fnum(v: Any, digits: int = 2) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "n/a"
    return "n/a" if pd.isna(f) else f"{f:.{digits}f}"


def _pick_notes(row: pd.Series, group: str) -> str:
    """표기용 `notes` — L4 선정 라벨 + 관찰 지표(순위·바벨·3축 백분위)와 플래그.

    값만 옮기고 판단은 넣지 않는다. 등수·종합·바벨 라벨이 **선정에 쓰이지 않는다**는 사실을
    문구가 직접 말한다 (2026-08-24 · 머리말).
    """
    parts = [f"L4 {group}"]
    if group == "ELIGIBLE":
        parts.append("적격 전부·동일가중 (아래는 관찰 지표 — 선정 무관)")
    obs = _cell(row, "barbell_obs")
    parts += [
        f"관찰 #{int(row['rank'])}" + (f" 바벨 {obs}" if obs else ""),
        f"종합 {_fnum(row['composite'])}",
        f"S̃ {_fnum(_cell(row, 's_pct'))} T̃ {_fnum(_cell(row, 't_pct'))} "
        f"M̃ {_fnum(_cell(row, 'm_pct'))}",
    ]
    pen = _cell(row, "penalties")
    if pen:
        parts.append(f"감점[{pen}]")
    rf = _cell(row, "red_flags")
    if rf:
        parts.append(f"레드플래그[{rf}]")
    cp = _cell(row, "composite_partial")
    if cp is not None and str(cp).lower() == "true":
        parts.append("종합 부분(축 결측)")
    for axis, key in (("S", "s_inputs_missing"), ("T", "t_inputs_missing")):
        m = _cell(row, key)
        if m:
            parts.append(f"{axis} 입력 없음: {m}")
    return " · ".join(parts).replace("\n", " ")


def _optional_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def picks_csv_from_rankings(
    theme_to_ranking: Mapping[str, pd.DataFrame | Path | str],
    *,
    top_per_theme: int | None = None,
) -> PicksAssembly:
    """테마별 `ranking.csv`(프레임 또는 경로) → `load_picks` 계약 프레임.

    - `role` 은 `group` 라벨에서만 온다 (`ROLE_BY_GROUP`). 라벨이 비었거나(순위만 있음) 모르는
      값이면 **제외하고 센다.**
    - `top_per_theme` 을 주면 role 이 있는 행을 `rank` 순으로 그만큼만 남기고 나머지를 센다.
      **이것은 사람이 주는 상한이지 L4 의 선정 규칙이 아니다** (기본 None = 적격 종목 전부).
      자르는 순서로 쓰는 `rank` 는 관찰 지표이고, 그것을 규칙으로 승격하려면 새 사전 등록이
      필요하다 (`docs/06` §6.2 · 머리말 "`role` — 2026-08-24 개정").
    - 한 티커는 한 테마에만 — 먼저 온 테마(dict 순서)가 갖고 뒤는 제외하고 센다 (`load_picks` 규칙).
    - `entry_price`·`adv20_usd` 는 `ranking.csv` 에 해당 열이 없으면 빈 값이고 그 사실이
      `missing_inputs` 에 남는다. 나머지 계약 열은 `OMITTED_COLUMNS` 의 이유로 쓰지 않는다.
    """
    if top_per_theme is not None and top_per_theme < 1:
        raise AssembleError("top_per_theme 은 1 이상이어야 한다")
    rows: list[dict[str, Any]] = []
    ex_rows: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    empty: list[str] = []
    missing_inputs: dict[str, tuple[str, ...]] = {}
    for theme, src in theme_to_ranking.items():
        rk = src if isinstance(src, pd.DataFrame) else read_ranking(src)
        miss_req = [c for c in _RANKING_REQUIRED if c not in rk.columns]
        if miss_req and len(rk):
            raise AssembleError(f"{theme}: ranking 에 열이 없다 {miss_req} — L4 산출물이 아니다")
        miss_val = tuple(c for c in _RANKING_VALUE_COLS if c not in rk.columns)
        if miss_val:
            missing_inputs[theme] = miss_val
        n_before = len(rows)
        kept = 0
        order = rk.sort_values("rank", kind="mergesort") if len(rk) else rk
        for tk, row in order.iterrows():
            ticker = str(tk).strip().upper()
            group = str(_cell(row, "group") or "").strip().upper()
            role = ROLE_BY_GROUP.get(group)
            if not group:
                ex_rows.append(
                    {"theme": theme, "ticker": ticker, "reason": "선정 라벨 없음 (group 비어 있음)"}
                )
                continue
            if role is None:
                ex_rows.append(
                    {"theme": theme, "ticker": ticker, "reason": f"group 매핑 없음: {group}"}
                )
                continue
            if top_per_theme is not None and kept >= top_per_theme:
                ex_rows.append(
                    {
                        "theme": theme,
                        "ticker": ticker,
                        "reason": f"top_per_theme={top_per_theme} 초과",
                    }
                )
                continue
            if ticker in seen:
                ex_rows.append(
                    {
                        "theme": theme,
                        "ticker": ticker,
                        "reason": f"티커 중복 — 이미 {seen[ticker]} 에 배정",
                    }
                )
                continue
            seen[ticker] = theme
            kept += 1
            rows.append(
                {
                    "theme": theme,
                    "ticker": ticker,
                    "role": role,
                    "entry_price": _optional_float(_cell(row, ENTRY_PRICE_FEATURE)),
                    "adv20_usd": _optional_float(_cell(row, LIQUIDITY_FEATURE)),
                    "rank_score": _optional_float(_cell(row, "composite")),
                    "notes": _pick_notes(row, group),
                }
            )
        if len(rows) == n_before:
            empty.append(theme)
    frame = pd.DataFrame(rows, columns=list(PICKS_COLUMNS))
    excluded = pd.DataFrame(ex_rows, columns=["theme", "ticker", "reason"])
    counts = dict(sorted(Counter(r["reason"] for r in ex_rows).items()))
    return PicksAssembly(
        frame=frame,
        excluded=excluded,
        counts=counts,
        themes_without_picks=tuple(empty),
        missing_inputs=missing_inputs,
    )


# ---------------------------------------------------------------- thesis


def _obs_items(raw: Any) -> list[Any]:
    """트리거/무효화 목록 — 매핑은 `_OBS_KEYS` 부분집합으로, 문자열은 그대로. 목록이 아니면 빈 목록
    (검증은 `parse_thesis` 가 한다 — 여기서 조용히 고치지 않는다)."""
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        return []
    out: list[Any] = []
    for item in raw:
        if isinstance(item, Mapping):
            out.append({k: item[k] for k in _OBS_KEYS if k in item})
        else:
            out.append(item)
    return out


#: `cycle_confidence_by` 를 enum 으로 읽는 규칙 — 값은 자유 서술이고(L3 는
#: `"referee-pipeline (04 §4 기계 적용; 09 §2 — 산출 주체 표기)"` 를 쓴다) 첫 낱말이 주체다.
_BY_TOKEN = re.compile(r"[A-Za-z_]+")


def _declared_source(thesis: Mapping[str, Any]) -> str | None:
    """yaml 이 적어 둔 확신도 산출 주체.

    **`cycle_confidence_by` 가 먼저다.** 이 키는 `l3/pipeline.build_thesis` 가 `c` 를 실제로
    계산한 코드 자리에서 쓰는 **기계 기록**이고, `confidence_provenance`·`cycle_confidence_source`
    는 사람이 손으로 적는 자기선언이다. 예전 목록에는 기계 키가 아예 없어서, 기계가 산출한 논지의
    출처는 무시되고 손기재 자기선언만 채택됐다 — `docs/10` §4 캘리브레이션이 사람 판단을 referee
    실적으로 집계하는 경로다. 순서만 바로잡았고 "파일이 위치보다 잘 안다" 는 기존 의도는 그대로다
    (`docs/09` §2 · `docs/11` M6).

    `cycle_confidence_by` 의 값에서 enum 을 읽지 못하면 조용히 넘기지 않고 예외로 알린다
    (`CLAUDE.md` §2).
    """
    by = thesis.get("cycle_confidence_by")
    if by is not None:
        m = _BY_TOKEN.search(str(by))
        token = m.group(0).lower() if m else ""
        if token not in CONFIDENCE_PROVENANCE:
            raise AssembleError(
                f"cycle_confidence_by {str(by)[:60]!r} 에서 산출 주체를 읽지 못했다 — "
                f"첫 낱말이 {CONFIDENCE_PROVENANCE} 중 하나여야 한다"
            )
        return token
    for k in ("confidence_provenance", "cycle_confidence_source"):
        v = thesis.get(k)
        if v is not None:
            return str(v)
    return None


def thesis_input_from_l3(
    thesis: Mapping[str, Any], *, confidence_source: str, source_path: str = ""
) -> dict[str, Any]:
    """thesis 객체(`docs/specs/thesis.schema.yaml`) → `parse_thesis` 가 읽는 부분집합.

    `confidence_source` 는 호출자가 **위치로** 아는 값 — L3 `msa research` 산출(`state/theses/`)이면
    `referee`, 사람 논지 디렉터리면 `human`. yaml 이 스스로 `confidence_provenance`(저널 용어) 또는
    `cycle_confidence_source` 를 선언했으면 **그 선언이 이긴다** — 파일이 어디 있든 누가 `c` 를
    만들었는지는 파일이 더 잘 안다 (`docs/09` §2 · `docs/11` M6). 선언값이 enum 밖이면 거부.
    나머지 필드(evidence·bear_case·…)는 옮기지 않는다 — 전문은 `state/theses/`·저널에 있다.
    """
    if confidence_source not in CONFIDENCE_PROVENANCE:
        raise AssembleError(
            f"confidence_source 허용값 {CONFIDENCE_PROVENANCE}: {confidence_source!r}"
        )
    declared = _declared_source(thesis)
    if declared is not None:
        if declared not in CONFIDENCE_PROVENANCE:
            raise AssembleError(
                f"{source_path or '<thesis>'}: yaml 이 선언한 확신도 주체 {declared!r} 는 "
                f"허용값 {CONFIDENCE_PROVENANCE} 밖이다"
            )
        confidence_source = declared
    theme = thesis.get("theme_id") or thesis.get("theme")
    if not theme or not isinstance(theme, str):
        raise AssembleError(f"{source_path or '<thesis>'}: theme_id 가 없다")
    out: dict[str, Any] = {"theme_id": theme}
    for k in ("generated_at", "supersedes", "claim"):
        if thesis.get(k) is not None:
            out[k] = str(thesis[k])
    hz = thesis.get("horizon_months")
    out["horizon_months"] = list(hz) if isinstance(hz, Sequence) and not isinstance(hz, str) else hz
    out["cycle_confidence"] = thesis.get("cycle_confidence")
    out["cycle_confidence_source"] = confidence_source
    if thesis.get("cycle_confidence_by") is not None:
        out["cycle_confidence_by"] = str(thesis["cycle_confidence_by"])
    out["triggers"] = _obs_items(thesis.get("triggers"))
    out["invalidations"] = _obs_items(thesis.get("invalidations"))
    gate = thesis.get("gate_result")
    if isinstance(gate, Mapping):
        out["gate_result"] = {
            k: gate[k] for k in ("status", "portfolio_eligible", "rule", "path") if k in gate
        }
    axes = thesis.get("value_trap_axes")
    if isinstance(axes, Mapping) and isinstance(axes.get("unit_demand"), Mapping):
        ud = axes["unit_demand"]
        out["value_trap_axes"] = {
            "unit_demand": {
                k: ud[k] for k in ("verdict", "axis1_available", "unit_series_source") if k in ud
            }
        }
    if source_path:
        out["assembled_from"] = source_path
    return out


# ---------------------------------------------------------------- 묶음


@dataclass(frozen=True)
class AssembleResult:
    """`assemble_inputs` 의 결과. `out_dir` 가 `msa portfolio --inputs` 의 인자다."""

    asof: str
    out_dir: Path | None
    picks: PicksAssembly
    theses: dict[str, dict[str, Any]]  # 포함된 테마 → L5 yaml 부분집합
    parsed: dict[str, ThesisInput]  # 포함된 테마 → 검증된 ThesisInput
    report: dict[str, Any]
    report_text: str

    @property
    def themes_included(self) -> list[str]:
        return list(self.report["themes_included"])

    @property
    def themes_skipped(self) -> dict[str, str]:
        return dict(self.report["themes_skipped"])


def _date_dirs_le(root: Path, asof: str) -> list[Path]:
    """`root/<YYYY-MM-DD>/` 중 `asof` 이하를 **최신 → 과거** 순으로."""
    return [p for d, p in reversed(scan_dirs(root)) if d.isoformat() <= asof]


def _find_latest(root: Path, asof: str, relpath: str) -> Path | None:
    """`root/<date≤asof>/<relpath>` 가 있는 최신 날짜의 그 파일."""
    for d in _date_dirs_le(root, asof):
        f = d / relpath
        if f.exists():
            return f
    return None


def _find_human_thesis(human_dir: Path, theme: str) -> Path | None:
    for name in (f"{theme}.yaml", f"{theme}.yml", thesis_filename(theme)):
        f = human_dir / name
        if f.exists():
            return f
    return None


def _asof_str(asof: str | date) -> str:
    s = asof.isoformat() if isinstance(asof, date) else str(asof)
    try:
        parse_date(s)
    except ValueError as e:
        raise AssembleError(f"asof={asof!r}: YYYY-MM-DD 가 아니다") from e
    return s


def assemble_inputs(
    *,
    asof: str | date,
    themes: Sequence[str],
    picks_root: Path | str | None = None,
    theses_root: Path | str | None = None,
    out_dir: Path | str | None = None,
    human_theses_dir: Path | str | None = None,
    top_per_theme: int | None = None,
    write: bool = True,
) -> AssembleResult:
    """테마 목록 → `<out>/picks.csv` · `<out>/theses/<theme>.yaml` · 리포트.

    테마별로 (1) 논지 — `human_theses_dir/<theme>.yaml` 이 있으면 그것(`human`), 없으면
    `theses_root/<date≤asof>/<theme>.thesis.yaml` 의 최신(`referee`) — 을 찾아 L5 부분집합으로
    옮기고 `parse_thesis` 로 검증한다. 계약 위반·게이트 편입 불가·논지 없음이면 테마를 **건너뛰고
    사유를 남긴다.** (2) `picks_root/<date≤asof>/<theme>/ranking.csv` 의 최신을 읽어
    `picks_csv_from_rankings` 로 모은다. 바벨 라벨이 하나도 없는 테마도 건너뛴다. 남는 테마가 0 이면
    예외.

    쓰고 나서 `load_picks`·`load_theses` 로 **자기 산출물을 다시 읽어** 계약을 확인한다.
    기본 경로: `Paths.picks` · `Paths.theses` · `Paths.portfolio_inputs/<asof>/`.
    """
    p = paths()
    asof_s = _asof_str(asof)
    proot = Path(picks_root) if picks_root is not None else p.picks
    troot = Path(theses_root) if theses_root is not None else p.theses
    hdir = Path(human_theses_dir) if human_theses_dir is not None else None
    if hdir is not None and not hdir.is_dir():
        raise AssembleError(f"사람 논지 디렉터리가 없다: {hdir}")
    out = Path(out_dir) if out_dir is not None else p.portfolio_inputs / asof_s

    wanted: list[str] = []
    for t in themes:
        t = str(t).strip()
        if t and t not in wanted:
            wanted.append(t)
    if not wanted:
        raise AssembleError("테마가 0개다 — --themes a,b,c")

    skipped: dict[str, str] = {}
    sources: dict[str, dict[str, Any]] = {}
    yamls: dict[str, dict[str, Any]] = {}
    parsed: dict[str, ThesisInput] = {}
    rankings: dict[str, pd.DataFrame] = {}
    for theme in wanted:
        # --- thesis
        tpath: Path | None = None
        csrc = "referee"
        if hdir is not None:
            tpath = _find_human_thesis(hdir, theme)
            if tpath is not None:
                csrc = "human"
        if tpath is None:
            tpath = _find_latest(troot, asof_s, thesis_filename(theme))
        if tpath is None:
            where = f"{troot}/<≤{asof_s}>/{thesis_filename(theme)}"
            if hdir is not None:
                where += f" · {hdir}/{theme}.yaml"
            skipped[theme] = f"thesis 없음 ({where})"
            continue
        try:
            raw = read_thesis_yaml(tpath)
            mapped = thesis_input_from_l3(raw, confidence_source=csrc, source_path=rel(tpath))
            ti = parse_thesis(mapped, where=rel(tpath))
        except (ValueError, InputError, AssembleError) as e:
            skipped[theme] = f"thesis 계약 위반: {e}"
            continue
        if not ti.portfolio_eligible:
            skipped[theme] = (
                f"gate 편입 불가 (status={ti.gate_status}, portfolio_eligible=False) — {rel(tpath)}"
            )
            continue
        # --- picks
        rpath = _find_latest(proot, asof_s, f"{theme}/ranking.csv")
        if rpath is None:
            skipped[theme] = (
                f"picks 없음 ({proot}/<≤{asof_s}>/{theme}/ranking.csv — `msa picks {theme}`)"
            )
            continue
        try:
            rk = read_ranking(rpath)
        except ValueError as e:
            skipped[theme] = f"ranking.csv 계약 위반: {e}"
            continue
        rankings[theme] = rk
        yamls[theme] = mapped
        parsed[theme] = ti
        sources[theme] = {
            "thesis": rel(tpath),
            "thesis_date": None if hdir is not None and tpath.parent == hdir else tpath.parent.name,
            "confidence_source": mapped["cycle_confidence_source"],
            "confidence_source_by": "yaml 선언" if _declared_source(raw) else f"위치({csrc})",
            "cycle_confidence": ti.cycle_confidence,
            "gate_status": ti.gate_status,
            "picks": rel(rpath),
            "picks_date": rpath.parent.parent.name,
            "ranking_rows": len(rk),
        }

    pa = picks_csv_from_rankings(rankings, top_per_theme=top_per_theme)
    for theme in pa.themes_without_picks:
        skipped[theme] = (
            "picks 0건 — ranking.csv 에 선정 라벨(group=ELIGIBLE; 옛 ANCHOR/TORQUE)이 없다"
        )
        yamls.pop(theme, None)
        parsed.pop(theme, None)
    included = [t for t in wanted if t in yamls]
    if not included:
        lines = "\n".join(f"  {t}: {r}" for t, r in skipped.items())
        raise AssembleError(f"asof {asof_s}: 묶을 테마가 0개다 — 전부 건너뜀:\n{lines}")

    report: dict[str, Any] = {
        "asof": asof_s,
        "themes_requested": wanted,
        "themes_included": included,
        "themes_skipped": skipped,
        "sources": {t: sources[t] for t in included},
        "picks": {
            "included": pa.n_included,
            "by_role": dict(sorted(Counter(pa.frame["role"]).items())),
            "excluded": pa.counts,
            "excluded_rows": pa.excluded.to_dict(orient="records"),
            "missing_inputs": {t: list(v) for t, v in pa.missing_inputs.items()},
            "top_per_theme": top_per_theme,
        },
        "columns": {"written": list(PICKS_COLUMNS), "omitted": dict(OMITTED_COLUMNS)},
        "roots": {
            "picks": str(proot),
            "theses": str(troot),
            "human_theses": str(hdir) if hdir is not None else None,
        },
        "out_dir": str(out) if write else None,
        "next": f"msa portfolio --inputs {out}",
    }
    text = render_report(report)

    final_out: Path | None = None
    if write:
        out.mkdir(parents=True, exist_ok=True)
        pa.frame.to_csv(out / "picks.csv", index=False)
        for t in included:
            dump_thesis_yaml(out / "theses" / f"{t}.yaml", yamls[t])
        write_snapshot(out, texts={"report.txt": text}, jsons={"assemble_report.json": report})
        # 자기 산출물 재검증 — 계약을 어겼으면 여기서 터진다
        load_picks(out / "picks.csv")
        load_theses(out / "theses")
        final_out = out
        log.info("portfolio-inputs: 저장 %s (테마 %d · 종목 %d)", out, len(included), pa.n_included)
    return AssembleResult(
        asof=asof_s,
        out_dir=final_out,
        picks=pa,
        theses={t: yamls[t] for t in included},
        parsed={t: parsed[t] for t in included},
        report=report,
        report_text=text,
    )


# ---------------------------------------------------------------- 리포트


def render_report(r: Mapping[str, Any]) -> str:
    """사람이 읽는 묶음 리포트 — 포함·건너뜀·제외를 전부 찍는다."""
    pk = r["picks"]
    L: list[str] = [
        f"L5 입력 묶음 — asof {r['asof']}  (L4 picks + L3/사람 thesis → picks.csv · theses/)",
        "=" * 78,
        f"테마 요청 {len(r['themes_requested'])} → 포함 {len(r['themes_included'])} "
        f"[{', '.join(r['themes_included']) or '—'}] · 건너뜀 {len(r['themes_skipped'])}",
        "",
    ]
    if r["themes_skipped"]:
        L.append("건너뛴 테마 (전부 표기 — CLAUDE.md §2)")
        for t, why in r["themes_skipped"].items():
            L.append(f"  {t}: {why}")
        L.append("")
    L.append("원천")
    for t, s in r["sources"].items():
        L.append(
            f"  {t}: thesis {s['thesis']} (c={s['cycle_confidence']}, "
            f"주체 {s['confidence_source']}, gate {s['gate_status'] or 'n/a'}) · "
            f"picks {s['picks']} ({s['ranking_rows']}행, {s['picks_date']})"
        )
    L.append("")
    roles = " · ".join(f"{k} {v}" for k, v in pk["by_role"].items()) or "—"
    L.append(
        f"종목 {pk['included']}  ({roles})"
        + (f"   top_per_theme={pk['top_per_theme']}" if pk.get("top_per_theme") else "")
    )
    if pk["excluded"]:
        L.append("제외 (수·사유)")
        for why, n in pk["excluded"].items():
            L.append(f"  {n:>3}  {why}")
        for row in pk["excluded_rows"]:
            L.append(f"       {row['theme']}/{row['ticker']}: {row['reason']}")
    if pk["missing_inputs"]:
        L.append("ranking.csv 에 없던 열 (빈 값으로 쓰고 L5 가 '미적용' 으로 표기)")
        for t, cols in pk["missing_inputs"].items():
            L.append(f"  {t}: {', '.join(cols)}")
    L.append("")
    L.append(f"쓴 열: {', '.join(r['columns']['written'])}")
    L.append("쓰지 않은 열 (L4 가 내지 않는다 — 만들어 넣지 않았다)")
    for c, why in r["columns"]["omitted"].items():
        L.append(f"  {c}: {why}")
    L.append("")
    if r.get("out_dir"):
        L.append(f"다음: {r['next']}")
    L.append("이 묶음은 측정값의 이동이다. 주문은 내지 않는다 (CLAUDE.md §8).")
    return "\n".join(L)
