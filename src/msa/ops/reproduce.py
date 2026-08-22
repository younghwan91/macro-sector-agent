"""`msa ops reproduce <scan-date>` — 저장된 `state/scans/<date>/` 에서 리포트를 다시 만든다.

재계산하지 않는다. `scoreboard.csv` · `indicator_pct.csv` · `coverage.csv` · `meta.json` 만으로
`msa.l1.scan.render_report` 를 다시 호출하고, 저장된 `report.txt` 와 같은지 대조한다.
"몇 달 뒤 '그때 왜 이 테마가 3위였나' 를 답할 수 없으면 캘리브레이션이 불가능하다" (`docs/09` §4) —
이 명령이 그 답을 스냅샷만으로 낼 수 있음을 증명한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED = ("scoreboard.csv", "indicator_pct.csv", "coverage.csv", "meta.json", "report.txt")


@dataclass(frozen=True)
class Reproduction:
    scan_dir: Path
    rendered: str
    stored: str
    identical: bool
    missing: tuple[str, ...]

    def diff_lines(self) -> list[str]:
        import difflib

        return list(
            difflib.unified_diff(
                self.stored.splitlines(),
                self.rendered.splitlines(),
                "stored report.txt",
                "re-rendered",
                lineterm="",
                n=1,
            )
        )


def reproduce(scan_dir: Path) -> Reproduction:
    missing = tuple(f for f in REQUIRED if not (scan_dir / f).exists())
    if missing:
        raise FileNotFoundError(
            f"{scan_dir}: 스냅샷 파일 누락 {missing} — 재현 불가 (조용히 건너뛰지 않는다)"
        )
    from msa.l1.scan import render_report
    from msa.l1.scoreboard import Scoreboard

    meta = json.loads((scan_dir / "meta.json").read_text(encoding="utf-8"))
    table = pd.read_csv(scan_dir / "scoreboard.csv", index_col=0)
    if "flags" in table.columns:
        # CSV 왕복에서 빈 flags 가 NaN 이 된다 — 저장 시점의 "" 로 되돌린다
        table["flags"] = table["flags"].fillna("").astype(str)
    ipct = pd.read_csv(scan_dir / "indicator_pct.csv", index_col=0)
    cov = pd.read_csv(scan_dir / "coverage.csv", index_col=0)
    if "bucket" not in meta:
        # M3 초기 스냅샷(2026-07-31)은 bucket 키가 없다 — asof 로 대신하고, 그 결과 헤더가 달라지면
        # identical=False 로 드러난다 (조용히 맞추지 않는다)
        meta = {**meta, "bucket": meta["asof"]}
    sb = Scoreboard(date=pd.Timestamp(meta["bucket"]), table=table, indicator_pct=ipct, meta={})
    rendered = render_report(sb, cov, meta)
    stored = (scan_dir / "report.txt").read_text(encoding="utf-8")
    return Reproduction(scan_dir, rendered, stored, rendered == stored, missing)
