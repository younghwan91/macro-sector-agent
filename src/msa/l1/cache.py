"""L1 지문 캐시 경로 — 패널·재무·지표 parquet 과 메타 JSON 의 **파일 이름을 한 곳에** 둔다.

지문(`panel._fingerprint` = 구성원 배정 + 스토어 최종일 + 위생 상수)이 같으면 세 계층의 캐시를
전부 같은 접미어로 찾는다. 이름 규칙은 바꾸지 않았다 (`state/cache/l1_<종류>_<지문>.parquet`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from msa.config import paths
from msa.io import dump_json


@dataclass(frozen=True)
class FingerprintCache:
    """한 지문의 캐시 파일 묶음. `panel`·`fund`·`indicators` 가 각자 자기 파일만 읽고 쓴다."""

    cache_dir: Path
    fingerprint: str

    @classmethod
    def at(cls, fingerprint: str, cache_dir: Path | None = None) -> FingerprintCache:
        cdir = cache_dir if cache_dir is not None else paths().cache
        cdir.mkdir(parents=True, exist_ok=True)
        return cls(cache_dir=cdir, fingerprint=fingerprint)

    def _p(self, stem: str, ext: str = "parquet") -> Path:
        return self.cache_dir / f"l1_{stem}_{self.fingerprint}.{ext}"

    # ---- 패널
    @property
    def panel(self) -> Path:
        return self._p("panel")

    @property
    def spy(self) -> Path:
        return self._p("spy")

    @property
    def panel_meta(self) -> Path:
        return self._p("panel", "json")

    # ---- 재무
    @property
    def fund(self) -> Path:
        return self._p("fund")

    @property
    def fund_ss(self) -> Path:
        return self._p("fund_ss")

    @property
    def fund_actions(self) -> Path:
        return self._p("fund_actions")

    @property
    def fund_meta(self) -> Path:
        return self._p("fund", "json")

    # ---- 지표
    @property
    def indicators(self) -> Path:
        return self._p("indicators")

    @property
    def indicators_meta(self) -> Path:
        return self._p("indicators", "json")

    # ---- 공용
    def has(self, *files: Path) -> bool:
        return all(f.exists() for f in files)

    @staticmethod
    def read_meta(path: Path) -> dict[str, Any]:
        out: dict[str, Any] = json.loads(path.read_text())
        return out

    @staticmethod
    def write_meta(path: Path, meta: dict[str, Any]) -> None:
        dump_json(path, meta)

    @staticmethod
    def read_frame(path: Path) -> pd.DataFrame:
        return pd.read_parquet(path)


def newest_fingerprint(cache_dir: Path, stem: str = "panel") -> str | None:
    """`l1_<stem>_<지문>.parquet` 중 수정시각이 가장 최근인 것의 지문. 없으면 None."""
    cands = sorted(cache_dir.glob(f"l1_{stem}_*.parquet"), key=lambda p: p.stat().st_mtime)
    if not cands:
        return None
    return cands[-1].stem.removeprefix(f"l1_{stem}_")
