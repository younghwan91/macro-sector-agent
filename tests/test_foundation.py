"""공용 기반 모듈 — `msa.dates`·`msa.io`·`msa.coerce`·`msa.fmt`·`msa.status`·`msa.errors`·`Paths`.

전부 순수 함수라 데이터 없이 돈다. 값·규약은 이전 계층별 구현과 같아야 한다 — 여기 적힌
기대값은 옮기기 전 구현(`l1/fundamentals.month_ends`·`l2/drivers.last_month_end`·
`ops/state_files._plain`·`l3/contracts._f` …)이 돌려주던 것이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

import pandas as pd
import pytest

from msa import coerce, dates, fmt
from msa.config import REPO_ROOT, MissingApiKey, paths, rel
from msa.errors import Immutable, MsaError, ProviderError, RefusedInput, Rejected
from msa.io import dump_json, dump_yaml, load_yaml_mapping, to_plain, write_snapshot, yaml_text
from msa.status import Axis1Status, CoverageStatus, DeliveryStatus, FundStatus, SeriesStatus

# ---------------------------------------------------------------- dates


def test_month_ends_matches_pandas_me_grid() -> None:
    idx = dates.month_ends("2024-01-15", "2024-04-10")
    assert list(idx.strftime("%Y-%m-%d")) == ["2024-01-31", "2024-02-29", "2024-03-31"]
    assert dates.month_ends("2024-01-31", "2024-01-31").tolist() == [pd.Timestamp("2024-01-31")]


def test_month_end_label_and_last_month_end() -> None:
    assert dates.month_end_label("2026-08-23") == pd.Timestamp("2026-08-31")
    assert dates.month_end_label("2026-08-31") == pd.Timestamp("2026-08-31")
    # l2/drivers.last_month_end 규약: 8/23 → 7/31, 월말이면 그대로
    assert dates.last_month_end(pd.Timestamp("2026-08-23")) == pd.Timestamp("2026-07-31")
    assert dates.last_month_end(pd.Timestamp("2026-08-31")) == pd.Timestamp("2026-08-31")


def test_to_month_end_keeps_gaps_as_nan_for_series_and_frame() -> None:
    s = pd.Series([1.0, 2.0, 5.0], index=pd.to_datetime(["2024-01-02", "2024-01-30", "2024-03-05"]))
    m = dates.to_month_end(s)
    assert list(m.index.strftime("%Y-%m-%d")) == ["2024-01-31", "2024-02-29", "2024-03-31"]
    assert m.iloc[0] == 2.0 and pd.isna(m.iloc[1]) and m.iloc[2] == 5.0
    f = dates.to_month_end(s.to_frame("x"))
    assert isinstance(f, pd.DataFrame) and f["x"].equals(m)


def test_months_between_ignores_day() -> None:
    assert dates.months_between(date(2026, 1, 31), date(2026, 2, 1)) == 1
    assert dates.months_between(date(2025, 6, 14), date(2026, 6, 13)) == 12
    assert dates.months_between(date(2026, 3, 1), date(2026, 1, 1)) == -2


def test_parse_date_formats_and_refusal() -> None:
    assert dates.parse_date(" 2026-08-23 ") == date(2026, 8, 23)
    assert dates.parse_date("2026-08", formats=("%Y-%m-%d", "%Y-%m")) == date(2026, 8, 1)
    with pytest.raises(ValueError, match="날짜 형식"):
        dates.parse_date("2026/08/23")
    assert dates.asof_or_today("") == date.today()
    assert dates.asof_or_today(None) == date.today()
    assert dates.asof_or_today("2026-01-02") == date(2026, 1, 2)


# ---------------------------------------------------------------- io


@dataclass(frozen=True)
class _Inner:
    when: date
    tags: tuple[str, ...]


@dataclass
class _Outer:
    name: str
    inner: _Inner
    alerts: list[str]
    kind: StrEnum | None = None


class _Kind(StrEnum):
    A = "alpha"


def test_to_plain_matches_old_plain_semantics() -> None:
    o = _Outer("x", _Inner(date(2026, 1, 2), ("a", "b")), ["!"], _Kind.A)
    got = to_plain(o)
    assert got == {
        "name": "x",
        "inner": {"when": "2026-01-02", "tags": ["a", "b"]},
        "alerts": ["!"],
        "kind": "alpha",
    }
    # ops/check.py 의 변종 — 어느 깊이에서든 `alerts` 키를 뺀다
    assert to_plain(
        {"a": {"alerts": 1, "b": [{"alerts": 2, "c": 3}]}}, drop=frozenset({"alerts"})
    ) == {"a": {"b": [{"c": 3}]}}
    # datetime 은 date 의 하위 클래스 — isoformat 으로 떨어진다 (옛 구현과 같다)
    assert to_plain(datetime(2026, 1, 2, 3, 4)) == "2026-01-02T03:04:00"
    assert to_plain(3.5) == 3.5 and to_plain(None) is None


def test_dump_json_yaml_and_snapshot(tmp_path: Path) -> None:
    obj = {"k": "값", "d": date(2026, 1, 2), "n": 1}
    p = dump_json(tmp_path / "a" / "m.json", obj)
    assert p.read_text(encoding="utf-8") == json.dumps(
        obj, ensure_ascii=False, indent=1, default=str
    )
    y = dump_yaml(tmp_path / "b" / "m.yaml", obj)
    assert y.read_text(encoding="utf-8") == yaml_text(obj)
    assert "k: 값" in yaml_text(obj)
    d = write_snapshot(
        tmp_path / "snap",
        frames={"t.csv": pd.DataFrame({"x": [1, 2]}, index=pd.Index(["r1", "r2"], name="id"))},
        texts={"report.txt": "본문"},
        jsons={"meta.json": {"a": 1}},
    )
    assert (d / "t.csv").read_text().splitlines()[0] == "id,x"
    assert (d / "report.txt").read_text(encoding="utf-8") == "본문"
    assert json.loads((d / "meta.json").read_text()) == {"a": 1}


def test_load_yaml_mapping_required_keys_and_custom_error(tmp_path: Path) -> None:
    class Boom(ValueError):
        pass

    p = tmp_path / "x.yaml"
    with pytest.raises(Boom, match="파일이 없다"):
        load_yaml_mapping(p, err=Boom)
    p.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(Boom, match="매핑이 아니다"):
        load_yaml_mapping(p, err=Boom)
    p.write_text("themes: []\n", encoding="utf-8")
    with pytest.raises(Boom, match="최상위에 defaults 키가 없다"):
        load_yaml_mapping(p, required_keys=("themes", "defaults"), err=Boom)
    assert load_yaml_mapping(p, required_keys=("themes",), err=Boom) == {"themes": []}


# ---------------------------------------------------------------- coerce


def test_coerce_optional_scalars() -> None:
    assert coerce.opt_float("1.5") == 1.5 and coerce.opt_float(float("nan")) is None
    assert coerce.opt_float("—") is None and coerce.opt_float("NA") is None
    assert coerce.opt_float("abc") is None and coerce.opt_float(None) is None
    assert coerce.opt_int("3.0") == 3 and coerce.opt_int("") is None
    assert coerce.opt_bool("Yes") is True and coerce.opt_bool("0") is False
    assert coerce.opt_bool("maybe") is None and coerce.opt_bool(1) is True
    assert coerce.opt_bool("") is False  # l3/contracts._b 규약 — 빈 문자열은 False
    assert coerce.opt_str("  x ") == "x" and coerce.opt_str("  ") is None
    assert coerce.opt_date("2026-01-02") == date(2026, 1, 2)
    assert coerce.opt_date(date(2026, 1, 2)) == date(2026, 1, 2)
    assert coerce.opt_date("2026-01", formats=("%Y-%m-%d", "%Y-%m")) == date(2026, 1, 1)
    assert coerce.opt_date("nope") is None and coerce.opt_date(None) is None


def test_require_message_matches_state_files_req() -> None:
    class E(ValueError):
        pass

    assert coerce.require({"a": 1}, "a", "ctx", E) == 1
    with pytest.raises(E, match="ctx: 필수 필드 없음 `b`"):
        coerce.require({"a": 1, "b": None}, "b", "ctx", E)


# ---------------------------------------------------------------- fmt


def test_fmt_pct_and_num_variants() -> None:
    assert fmt.pct(0.1234) == "+12.3%"  # ops/alerts._pct · ops/check._fmt_pct
    assert fmt.pct(None) == "n/a"
    assert fmt.pct(0.1234, sign=False, na="—") == "12.3%"  # l5/plan._pct
    assert fmt.pct(None, sign=False, na="—") == "—"
    assert (
        fmt.pct(0.12345, sign=False, nd=2) == "12.35%"
        or fmt.pct(0.12345, sign=False, nd=2) == "12.34%"
    )
    assert fmt.num(1.23456) == " 1.235" and fmt.num(None) == "   nan"  # l1/backtest._fmt
    assert fmt.num(float("nan"), w=4, p=1) == " nan"


# ---------------------------------------------------------------- status


def test_status_values_are_the_existing_strings() -> None:
    assert [s.value for s in SeriesStatus] == ["ok", "missing"]
    assert [s.value for s in Axis1Status] == [
        "ok_external",
        "ok_fallback",
        "data_missing",
        "not_declared",
    ]
    assert Axis1Status.OK_FALLBACK.is_ok and not Axis1Status.DATA_MISSING.is_ok
    assert [s.value for s in FundStatus] == ["ok", "stale", "none"]
    assert [s.value for s in CoverageStatus] == ["ok", "partial", "unavailable"]
    assert [s.value for s in DeliveryStatus] == [
        "sent",
        "partial",
        "failed",
        "not_configured",
        "nothing_to_send",
    ]
    # StrEnum — 평문 비교·직렬화가 문자열과 같다
    assert SeriesStatus.OK == "ok" and f"{Axis1Status.NOT_DECLARED}" == "not_declared"
    assert json.dumps({"s": DeliveryStatus.SENT}) == '{"s": "sent"}'


# ---------------------------------------------------------------- errors


def test_error_roots_and_exit_codes() -> None:
    assert MsaError.exit_code == 1 and RefusedInput.exit_code == 1
    assert Rejected.exit_code == 2 and ProviderError.exit_code == 3 and Immutable.exit_code == 1
    # 계층 예외는 이름·옛 부모를 유지한 채 뿌리를 얻는다
    from msa.data.store import StoreError
    from msa.l3.schema import ThesisRejected
    from msa.ops.journal import IncompleteEntry, JournalImmutable
    from msa.themes import ThemeSpecError

    assert issubclass(ThemeSpecError, RefusedInput) and issubclass(ThemeSpecError, ValueError)
    assert issubclass(ThesisRejected, Rejected) and issubclass(ThesisRejected, ValueError)
    assert issubclass(JournalImmutable, Immutable) and issubclass(JournalImmutable, RuntimeError)
    assert issubclass(IncompleteEntry, RefusedInput)
    assert issubclass(StoreError, MsaError) and issubclass(StoreError, RuntimeError)
    assert issubclass(MissingApiKey, MsaError) and issubclass(MissingApiKey, RuntimeError)


# ---------------------------------------------------------------- config.Paths


def test_paths_properties_are_the_existing_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSA_STATE", "/srv/st")
    p = paths()
    st = Path("/srv/st")
    assert p.cache == st / "cache" and p.scans == st / "scans" and p.macro == st / "macro"
    assert p.macro_latest == st / "macro" / "latest.json"
    assert p.theses == st / "theses" and p.picks == st / "picks" and p.portfolio == st / "portfolio"
    assert p.checks == st / "checks" and p.backtests_l1 == st / "backtests" / "l1"
    assert p.calibration == st / "calibration" and p.physical == st / "physical"
    assert p.fred_cache == st / "physical" / "fred" and p.manual_dir == st / "physical" / "manual"
    assert p.cases_dir == st / "cases" and p.cases == st / "cases" / "cases.yaml"
    assert p.themes_yaml == st / "themes.yaml" and p.dag_yaml == st / "macro-dag.yaml"
    assert p.positions == st / "positions.yaml" and p.watchlist == st / "watchlist.yaml"
    assert p.rejections == st / "rejections.yaml"
    assert p.rejections_summary == st / "rejections-summary.md"
    assert p.journal == REPO_ROOT / "journal"


def test_rel_is_repo_relative_or_absolute() -> None:
    assert rel(REPO_ROOT / "state" / "scans" / "x") == "state/scans/x"
    assert rel(Path("/elsewhere/y")) == "/elsewhere/y"
