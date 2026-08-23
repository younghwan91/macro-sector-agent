"""경로·키 설정. 전부 환경변수로 덮어쓸 수 있다 — 하드코딩된 절대경로는 없다.

| 환경변수 | 기본값 | 무엇 |
|---|---|---|
| `MSA_DUCKDB` | `~/data/us_micro.duckdb` | Sharadar 적재 DuckDB 스토어 (읽기 전용) |
| `MSA_SHARADAR_RAW` | `~/data/sharadar` | 벤더 벌크 CSV 원본 (스토어 검증의 대조군) |
| `MSA_STATE` | `<repo>/state` | 산출물 저장소. **다른 계층이 쓴다 — M1 은 읽지도 쓰지도 않는다** |
| `FRED_API_KEY` | 없음 | FRED 어댑터(L1 축 1 실물 참조·CPI). 없으면 `msa.data.fred` 가 던진다 |

`state/` 아래의 하위 경로는 전부 `Paths` 의 속성이다 (`paths().scans`·`paths().themes_yaml`·…).
계층 모듈이 `p.state / "scans"` 를 각자 만들면 디렉터리 이름이 한 곳에서 바뀔 때 조용히
갈라진다 — 이름은 여기 한 번만 적는다. 값(디렉터리·파일 이름)은 바꾸지 않았다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from msa.errors import MsaError

# `src/msa/config.py` → 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[2]

#: 결정 저널 디렉터리 이름 (`<repo>/journal`, `CLAUDE.md` §6).
JOURNAL_DIRNAME = "journal"


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return default if raw is None or raw.strip() == "" else Path(raw).expanduser()


@dataclass(frozen=True)
class Paths:
    duckdb: Path
    sharadar_raw: Path
    state: Path

    # ---- state/ 아래 디렉터리 (산출물 루트) — `<date>/` 는 호출자가 붙인다

    @property
    def cache(self) -> Path:
        """L1 패널·재무·지표 parquet 과 ETF 벌크 사이드 캐시 (`state/cache/`)."""
        return self.state / "cache"

    @property
    def scans(self) -> Path:
        return self.state / "scans"

    @property
    def theses(self) -> Path:
        return self.state / "theses"

    @property
    def picks(self) -> Path:
        return self.state / "picks"

    @property
    def portfolio(self) -> Path:
        return self.state / "portfolio"

    @property
    def portfolio_inputs(self) -> Path:
        """L4·L3 → L5 입력 묶음 (`state/portfolio_inputs/<asof>/`, `msa portfolio-inputs`)."""
        return self.state / "portfolio_inputs"

    @property
    def checks(self) -> Path:
        return self.state / "checks"

    @property
    def runs(self) -> Path:
        """케이던스 실행 리포트 (`state/runs/<asof>/monthly-report.md`·`weekly-report.md`·
        `run.json`, `msa run monthly|weekly`)."""
        return self.state / "runs"

    @property
    def backtests_l1(self) -> Path:
        return self.state / "backtests" / "l1"

    @property
    def calibration(self) -> Path:
        return self.state / "calibration"

    @property
    def physical(self) -> Path:
        return self.state / "physical"

    @property
    def fred_cache(self) -> Path:
        """`state/physical/fred/<SYMBOL>.csv` — L1 실물 참조(축 1)·CPI 캐시."""
        return self.physical / "fred"

    @property
    def manual_dir(self) -> Path:
        """`state/physical/manual/<SYMBOL>.csv` — 사람이 갱신하는 수동 시계열."""
        return self.physical / "manual"

    @property
    def cases_dir(self) -> Path:
        """케이스 스터디 디렉터리 (`state/cases/`) — L3 입력·L5 `cases.yaml` 의 위치."""
        return self.state / "cases"

    @property
    def cases(self) -> Path:
        """L5 케이스 스터디 표 (`state/cases/cases.yaml`)."""
        return self.cases_dir / "cases.yaml"

    # ---- state/ 아래 파일

    @property
    def themes_yaml(self) -> Path:
        return self.state / "themes.yaml"

    @property
    def positions(self) -> Path:
        return self.state / "positions.yaml"

    @property
    def watchlist(self) -> Path:
        return self.state / "watchlist.yaml"

    @property
    def rejections(self) -> Path:
        return self.state / "rejections.yaml"

    @property
    def rejections_summary(self) -> Path:
        return self.state / "rejections-summary.md"

    # ---- 저장소 루트 아래

    @property
    def journal(self) -> Path:
        """결정 저널 (`<repo>/journal/`). `state/` 가 아니라 저장소 루트다 — 커밋되는 기록이다."""
        return REPO_ROOT / JOURNAL_DIRNAME


def paths() -> Paths:
    """호출 시점의 환경변수를 읽는다 — 모듈 임포트 시점이 아니다.

    임포트 시점에 고정하면 테스트가 `monkeypatch.setenv` 로 경로를 갈아끼울 수 없다.
    """
    return Paths(
        duckdb=_env_path("MSA_DUCKDB", Path.home() / "data" / "us_micro.duckdb"),
        sharadar_raw=_env_path("MSA_SHARADAR_RAW", Path.home() / "data" / "sharadar"),
        state=_env_path("MSA_STATE", REPO_ROOT / "state"),
    )


def rel(path: Path | str) -> str:
    """리포트용 짧은 경로 — 저장소 루트 기준 상대 경로, 밖이면 절대 경로.

    산출물(thesis·리포트)에 절대 경로를 남기지 않기 위한 것이다.
    """
    p = Path(path)
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


class MissingApiKey(MsaError, RuntimeError):
    """키가 없을 때 조용히 건너뛰는 대신 던진다 (`CLAUDE.md` §2)."""


def fred_api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise MissingApiKey(
            "FRED_API_KEY 가 비어 있다. https://fred.stlouisfed.org/docs/api/api_key.html "
            "에서 무료 키를 받아 환경변수로 넣어라. "
            "키가 없으면 L1 축 1 의 FRED 실물 참조·CPI 는 data_missing 으로 남는다."
        )
    return key
