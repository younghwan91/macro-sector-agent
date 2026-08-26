"""파일 입출력 공용 — YAML 매핑 로드, dataclass → 평문 변환, JSON/YAML 덤프, 스냅샷 쓰기.

`ops/state_files.py`·`ops/journal.py`·`ops/check.py` 가 각자 들고 있던 `_plain` 과, 계층마다
반복되던 `json.dumps(..., ensure_ascii=False, indent=1, default=str)` + UTF-8 `write_text` 를
한 곳에 모았다. **직렬화 규약(들여쓰기 1·비ASCII 그대로·`default=str`)은 바꾸지 않았다** —
`msa ops reproduce` 가 보관본과 재생성본을 바이트로 대조한다.

`dir_lock` 은 **프로세스 간** 잠금이다 — 같은 라운드 디렉터리에 여러 `msa` 프로세스가
동시에 쓰는 경우(테마별 병렬 실행)를 위해 있다.
"""

from __future__ import annotations

import fcntl
import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def load_yaml_mapping(
    path: Path | str,
    *,
    required_keys: Iterable[str] = (),
    err: type[Exception] = ValueError,
) -> dict[str, Any]:
    """YAML 파일 → dict. 파일이 없거나 최상위가 매핑이 아니거나 `required_keys` 가 빠지면 `err`.

    `err` 에 계층의 예외 클래스(`ThemeSpecError`·`DagError`·…)를 넘긴다 — 메시지 문구는
    기존 로더들과 같은 꼴(`"{path}: 최상위에 {key} 키가 없다"`)을 유지한다.
    """
    p = Path(path)
    if not p.exists():
        raise err(f"파일이 없다: {p}")
    spec = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(spec, Mapping):
        raise err(f"{p}: 최상위가 매핑이 아니다")
    for k in required_keys:
        if k not in spec:
            raise err(f"{p}: 최상위에 {k} 키가 없다")
    return dict(spec)


def to_plain(obj: Any, *, drop: frozenset[str] = frozenset()) -> Any:
    """dataclass → yaml/json 친화 평문 (date 는 ISO 문자열, tuple 은 list, Enum 은 값).

    `drop` 에 든 키는 **어느 깊이의 dict 에서든** 뺀다 (`ops/check.py` 가 `alerts` 를 빼던 규약).
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        return to_plain(asdict(obj), drop=drop)
    if isinstance(obj, dict):
        return {k: to_plain(v, drop=drop) for k, v in obj.items() if k not in drop}
    if isinstance(obj, list | tuple):
        return [to_plain(v, drop=drop) for v in obj]
    if isinstance(obj, Enum):
        return str(obj) if isinstance(obj, str) else obj.value
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def dump_json(path: Path | str, obj: Any) -> Path:
    """`json.dumps(obj, ensure_ascii=False, indent=1, default=str)` 를 UTF-8 로 쓴다."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return p


def yaml_text(obj: Any) -> str:
    """`yaml.safe_dump(to_plain(obj), allow_unicode=True, sort_keys=False,
    default_flow_style=False)` — `ops/state_files._dump`·`ops/journal._yaml` 과 같은 옵션."""
    return yaml.safe_dump(
        to_plain(obj), allow_unicode=True, sort_keys=False, default_flow_style=False
    )


def dump_yaml(path: Path | str, obj: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml_text(obj), encoding="utf-8")
    return p


def write_snapshot(
    out_dir: Path | str,
    *,
    frames: Mapping[str, pd.DataFrame] | None = None,
    texts: Mapping[str, str] | None = None,
    jsons: Mapping[str, Any] | None = None,
) -> Path:
    """`out_dir` 를 만들고 프레임(csv)·텍스트·JSON 을 파일명대로 쓴다.

    키는 **확장자를 포함한 파일명**이다 (`"scoreboard.csv"`, `"report.txt"`, `"meta.json"`).
    프레임은 `DataFrame.to_csv(path)` 기본값(인덱스 포함)으로 쓴다 — 기존 계층들과 같다.
    """
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    for name, df in (frames or {}).items():
        df.to_csv(d / name)
    for name, text in (texts or {}).items():
        (d / name).write_text(text, encoding="utf-8")
    for name, obj in (jsons or {}).items():
        dump_json(d / name, obj)
    return d


@contextmanager
def dir_lock(directory: Path | str, name: str = ".lock") -> Iterator[None]:
    """디렉터리 단위 프로세스 간 잠금 (`fcntl.flock`).

    누적 파일(읽고→고쳐→쓰기)을 여러 프로세스가 동시에 갱신할 때 쓴다. 잠금이 없으면
    늦게 쓴 쪽이 먼저 쓴 쪽의 행을 지운다 — 그리고 **아무 오류도 나지 않는다**. 조용히
    사라지는 기록이야말로 `CLAUDE.md` §2 가 금지하는 것이다.

    잠금 파일은 남겨둔다 (지우면 잠금을 든 다른 프로세스와 경합한다).
    """
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    lock_path = d / name
    with lock_path.open("a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def code_fingerprint(*modules: str) -> str:
    """모듈 소스의 짧은 해시 — **캐시 키에 코드 버전을 넣기 위한 것.**

    캐시 키가 (테마, 날짜) 뿐이면 특성·축 코드를 고쳐도 예전 parquet 이 그대로 재사용된다.
    DSR·PBO 판정이 그 숫자 위에 서 있으므로, 조용히 낡은 패널을 읽는 것이 여기서 가장 나쁜
    실패다 (2026-08-26 코드 리뷰). 소스가 한 글자라도 바뀌면 키가 바뀌어 다시 만든다.

    파일을 못 읽으면 **예외를 삼키지 않는다** — 지문을 못 만들었는데 만든 척하면 캐시가
    다시 조용해진다 (`CLAUDE.md` §2).
    """
    import hashlib
    import importlib.util

    h = hashlib.sha256()
    for name in sorted(modules):
        spec = importlib.util.find_spec(name)
        origin = spec.origin if spec else None
        if origin is None:
            raise OSError(f"코드 지문: 모듈 {name!r} 의 소스를 찾지 못했다")
        h.update(Path(origin).read_bytes())
    return h.hexdigest()[:12]
