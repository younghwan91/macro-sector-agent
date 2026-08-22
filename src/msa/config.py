"""경로·키 설정. 전부 환경변수로 덮어쓸 수 있다 — 하드코딩된 절대경로는 없다.

| 환경변수 | 기본값 | 무엇 |
|---|---|---|
| `MSA_DUCKDB` | `~/data/us_micro.duckdb` | Sharadar 적재 DuckDB 스토어 (읽기 전용) |
| `MSA_SHARADAR_RAW` | `~/data/sharadar` | 벤더 벌크 CSV 원본 (스토어 검증의 대조군) |
| `MSA_STATE` | `<repo>/state` | 산출물 저장소. **다른 계층이 쓴다 — M1 은 읽지도 쓰지도 않는다** |
| `FRED_API_KEY` | 없음 | FRED 어댑터. 없으면 `msa.data.fred` 가 예외를 던진다 |
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# `src/msa/config.py` → 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return default if raw is None or raw.strip() == "" else Path(raw).expanduser()


@dataclass(frozen=True)
class Paths:
    duckdb: Path
    sharadar_raw: Path
    state: Path


def paths() -> Paths:
    """호출 시점의 환경변수를 읽는다 — 모듈 임포트 시점이 아니다.

    임포트 시점에 고정하면 테스트가 `monkeypatch.setenv` 로 경로를 갈아끼울 수 없다.
    """
    return Paths(
        duckdb=_env_path("MSA_DUCKDB", Path.home() / "data" / "us_micro.duckdb"),
        sharadar_raw=_env_path("MSA_SHARADAR_RAW", Path.home() / "data" / "sharadar"),
        state=_env_path("MSA_STATE", REPO_ROOT / "state"),
    )


class MissingApiKey(RuntimeError):
    """키가 없을 때 조용히 건너뛰는 대신 던진다 (`CLAUDE.md` §2)."""


def fred_api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise MissingApiKey(
            "FRED_API_KEY 가 비어 있다. https://fred.stlouisfed.org/docs/api/api_key.html "
            "에서 무료 키를 받아 환경변수로 넣어라. "
            "키 없이 FRED 단계를 건너뛰면 L2 드라이버가 조용히 빈 채로 진행된다."
        )
    return key
