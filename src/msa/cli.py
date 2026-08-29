"""`msa` CLI.

도는 것: `data status`·`data audit`·`data fred-lag`·`data fred-fetch`(M1) · `scan`(M3) ·
`backtest l1`(M3.5) · `backtest l4`(docs/14) · `backtest l4-structures`(docs/15) ·
`picks`(M5) · `portfolio`(M6) · `research`(M7) ·
`check`·`journal *`·`ops *`(M8) · `portfolio-inputs`·`run *`(배선 W1·W4).
남은 스텁은 없다. 새 스텁을 두게 되면 `--help` 에는 나오되 호출 시 `NotImplementedError` 를
던지게 한다 — 있는 척하는 스텁이 조용히 빈 결과를 내는 것보다 낫다 (`CLAUDE.md` §2).
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import typer

from msa import __version__
from msa.config import REPO_ROOT, MissingApiKey, paths
from msa.dates import asof_or_today
from msa.errors import MsaError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "macro-sector-agent — 산업 사이클 → 테마 → 종목 → 포트폴리오 "
        "(M1~M8: 데이터·L1 스캐너·L4·L5·L3·운영 — L2 거시 DAG 는 2026-08-23 제거, docs/13)"
    ),
)
data_app = typer.Typer(no_args_is_help=True, help="L0 데이터 — 스토어 상태와 커버리지 감사")
app.add_typer(data_app, name="data")
journal_app = typer.Typer(
    no_args_is_help=True, help="결정 저널 (append-only) — 항목 작성·검증·논지 diff (docs/09 §2)"
)
app.add_typer(journal_app, name="journal")
ops_app = typer.Typer(
    no_args_is_help=True,
    help="운영 — 케이던스·캘리브레이션·기각 대장·스캔 재현 (docs/09, docs/10 §4·§5)",
)
app.add_typer(ops_app, name="ops")
backtest_app = typer.Typer(
    no_args_is_help=True, help="관문 0 — 결정론 계층의 백테스트 (docs/10 §2). 튜닝 루프가 아니다"
)
app.add_typer(backtest_app, name="backtest")
run_app = typer.Typer(
    no_args_is_help=True,
    help=(
        "케이던스 실행 (docs/09 §1) — monthly: 스캔→상위 K→L3→적재→L4→L5 · "
        "weekly: 스캔+점검 · daily: 후보 다이제스트+무효화 점검 · "
        "quarterly: 분기 명령 목록. 끝은 제안·초안이다 — 집행은 사람 (CLAUDE.md §8)"
    ),
)
app.add_typer(run_app, name="run")


def _setup_logging(verbose: bool) -> None:
    """루트 로거를 **한 번만** 구성한다. 이미 구성됐으면 `verbose` 일 때 레벨만 올린다.

    전역 `msa -v …` 와 명령별 `… -v` 가 둘 다 여기로 온다 — 어느 쪽이든 DEBUG 로 올라간다.
    """
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.DEBUG if verbose else logging.INFO,
            format="%(levelname)s %(name)s: %(message)s",
        )
    elif verbose:
        root.setLevel(logging.DEBUG)


def cli_guard[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """도메인 예외(`MsaError`)를 메시지 + 종료 코드로 바꾼다 — 트레이스백은 버그에만 남긴다.

    종료 코드는 예외 뿌리가 정한다 (`msa.errors`: 입력 거부 1 · 산출물 기각 2 · 제공자 3).
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except MsaError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=e.exit_code) from e

    return wrapper


def _echo_saved(out_dir: Path | str | None) -> None:
    if out_dir:
        typer.echo(f"저장: {out_dir}")


def _fmt(n: int | None) -> str:
    return "—" if n is None else f"{n:,}"


#: 모든 명령이 같은 철자로 받는 옵션.
OPT_VERBOSE = typer.Option(False, "--verbose", "-v")


def _no_write_option(target: str) -> Any:
    """`--no-write` — 도움말의 대상 디렉터리만 다르다."""
    return typer.Option(False, "--no-write", help=f"{target} 에 저장하지 않는다")


@app.callback()
def _main(verbose: bool = OPT_VERBOSE) -> None:
    """전역 옵션. `msa -v <명령>` 은 명령별 `-v` 와 같다."""
    _setup_logging(verbose)


@app.command()
@cli_guard
def version() -> None:
    """버전."""
    typer.echo(f"msa {__version__}")


@data_app.command("status")
@cli_guard
def data_status(
    verbose: bool = OPT_VERBOSE,
    etf: str = typer.Option(
        "", "--etf", help="쉼표로 구분한 ETF 티커. 벌크 funds.csv.zip 을 1회 스캔한다(~12초)."
    ),
) -> None:
    """전 소스의 최신 시점·행수·결측률. (M1 완료 판정 항목)"""
    from msa.data import fred
    from msa.data.store import ETF_IN_STORE, Store, etf_prices

    _setup_logging(verbose)
    p = paths()
    typer.echo(f"DuckDB       : {p.duckdb}")
    typer.echo(f"Sharadar raw : {p.sharadar_raw}")
    typer.echo("")

    with Store(p.duckdb) as store:
        typer.echo(f"{'table':<14}{'rows':>14}{'tickers':>10}  {'start':<12}{'end':<12}  상태")
        typer.echo("-" * 78)
        for s in store.table_stats():
            state = s.status  # 0행이 적재 실패인지 원래 그런지 구분한다 (EMPTY_TABLES)
            typer.echo(
                f"{s.name:<14}{_fmt(s.rows):>14}{_fmt(s.tickers):>10}  "
                f"{s.start or '—'!s:<12}{s.end or '—'!s:<12}  {state}"
            )

        _echo_store_lag(store.table_stats())
        _echo_required_tickers(store)

        typer.echo("")
        typer.echo("결측률 (전체 행 대비 NULL 비율)")
        for table, cols in (
            ("prices", ["close", "closeunadj", "volume", "mcap", "ev", "short_interest"]),
            ("tickers", ["category", "sector", "industry", "siccode", "is_delisted"]),
            ("fundamentals", ["revenue", "capex", "depamor", "assets", "equity", "assetsavg"]),
        ):
            rates = store.null_rates(table, cols)
            body = "  ".join(f"{c}={r:6.1%}" for c, r in rates.items())
            typer.echo(f"  {table:<13}{body}")

        typer.echo("")
        typer.echo("단위·조정 규약 (문서와 다른 지점 — `docs/08-data-contract.md` §2 정정본)")
        typer.echo("  prices.mcap/ev : 달러. 적재 시 백만→달러 환산이 끝났다 — 다시 곱하지 말 것")
        typer.echo("  prices.close   : 분할·배당 조정 종가. closeunadj 가 미조정 원가")
        typer.echo("  tickers        : is_delisted (문서의 isdelisted 아님)")

    typer.echo("")
    typer.echo("ETF (SFP)")
    typer.echo(f"  스토어 적재분 : {', '.join(ETF_IN_STORE)} — 그 외 ETF 는 스토어에 없다")
    if etf.strip():
        want = [t.strip().upper() for t in etf.split(",") if t.strip()]
        df = etf_prices(want, min_rows=0)
        if df.empty:
            typer.echo(f"  벌크 조회     : {want} — 0행")
        else:
            g = df.groupby("ticker")["date"].agg(["count", "min", "max"])
            for t, row in g.sort_index().iterrows():
                typer.echo(f"  {t:<12} {row['count']:>7,}행  {row['min']} ~ {row['max']}")
            absent = [t for t in want if t not in set(df["ticker"])]
            if absent:
                typer.echo(f"  벌크에도 없음 : {absent}")
    else:
        typer.echo("  벌크 조회     : --etf GDX,SIL,URA 로 지정하면 funds.csv.zip 을 읽는다")

    typer.echo("")
    typer.echo("FRED (L1 축 1 실물 참조 + CPI — docs/08 §3)")
    try:
        series = fred.l1_series()
    except Exception as e:  # themes.yaml 을 못 읽으면 CPI 하나만 — 사유를 적는다
        series = fred.L1_SERIES
        typer.echo(f"  themes.yaml 을 읽지 못해 physical_ref 심볼은 셀 수 없다: {e}")
    typer.echo(
        f"  대상 시리즈   : {len(series)}종 (CPI {len(fred.L1_SERIES)} + "
        f"physical_ref {len(series) - len(fred.L1_SERIES)})"
    )
    from msa.l1.physical import read_fred_cache

    cached = [sym for sym in series if read_fred_cache(sym) is not None]
    typer.echo(f"  캐시 있음     : {len(cached)}/{len(series)} (state/physical/fred/)")
    try:
        from msa.config import fred_api_key

        fred_api_key()
        typer.echo("  API 키        : 있음 — `msa data fred-fetch` 로 받고 `fred-lag` 로 지연 실측")
    except MissingApiKey as e:
        typer.echo(f"  API 키        : 없음 — {type(e).__name__}")
        typer.echo("  → 캐시 없는 시리즈는 L1 축 1 에서 data_missing 으로 남는다 (docs/09 §5)")


@data_app.command("audit")
@cli_guard
def data_audit(
    start: str = typer.Option("2010-01-01", help="폐지 종목 포함 감사 구간 시작"),
    end: str = typer.Option(str(date.today()), help="감사 구간 끝"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """커버리지 감사(`docs/01` §5) 중 데이터 부분 — category 제외 수 · 폐지 포함 · 중복 소속.

    미분류 시총 비율과 ETF 상관은 테마 버킷 정의(M2)가 있어야 계산되므로 여기 없다.
    """
    from msa.data.store import Store
    from msa.data.universe import (
        CANADIAN_COMMON_CATEGORIES,
        COMMON_STOCK_CATEGORIES,
        audit_delisted_included,
        common_stock,
        drop_secondary_class,
    )

    _setup_logging(verbose)
    with Store() as store:
        meta = store.tickers_meta(min_rows=10_000)
        uni = common_stock(meta)
        typer.echo("[1] category 필터 — 보통주만")
        typer.echo(f"  {uni.report()}")
        typer.echo(f"  허용 category : {list(COMMON_STOCK_CATEGORIES)}")
        typer.echo(f"  제외한 캐나다 : {list(CANADIAN_COMMON_CATEGORIES)} (docs/01 §6-3)")
        typer.echo("  제외 내역 전체:")
        for k, v in sorted(uni.excluded_by_category.items(), key=lambda kv: -kv[1]):
            typer.echo(f"    {k:<38}{v:>7,}")
        primary = drop_secondary_class(uni)
        typer.echo(f"  2종주 추가 제외 후 집계 유니버스: {primary.kept:,}")

        typer.echo("")
        typer.echo("[2] 폐지 종목 자기이력 포함 (docs/01 §5)")
        cov = audit_delisted_included(store, start, end, meta=meta)
        typer.echo(f"  {cov.report()}")
        for c, n in sorted(cov.excluded_non_equity.items(), key=lambda kv: -kv[1]):
            typer.echo(f"    검사 모집단 밖(보통주 아님) {c:<30}{n:>7,}")
        if not cov.ok:
            typer.echo(f"  누락: {cov.delisted_missing[:20]}")

        typer.echo("")
        typer.echo("[3] 중복 소속")
        typer.echo("  테마 버킷 정의가 없다 (M2). 검사기는 있으나 입력이 없어 실행하지 않는다.")
        typer.echo("  → msa.data.universe.audit_duplicate_membership(buckets)")

    typer.echo("")
    if not cov.ok:
        raise typer.Exit(code=1)


@data_app.command("fred-lag")
@cli_guard
def data_fred_lag(
    vintage: str = typer.Option(
        "", help="ALFRED 빈티지 날짜(YYYY-MM-DD). 주면 개정 여부까지 판정한다"
    ),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L1 이 쓰는 FRED 시리즈(CPI + physical_ref)의 발표 지연·개정 실측 — `docs/08` §3 표."""
    from msa.data.fred import FredClient, l1_series

    _setup_logging(verbose)
    series = l1_series()
    with FredClient() as client:
        rows = client.measure_all(series, vintage_date=vintage or None)
    for r in rows:
        typer.echo("  " + r.row())
    typer.echo(f"\n{len(rows)}/{len(series)} 시리즈 실측 완료")


@app.command()
@cli_guard
def scan(
    asof: str = typer.Option(
        "",
        help=(
            "기준일 YYYY-MM-DD → 그 이전 마지막 **완결** 월말 버킷. "
            "기본 = 스토어 최종일 (이때만 진행 중인 달의 부분 버킷을 쓴다)"
        ),
    ),
    top: int = typer.Option(0, help="표에 보일 상위 N (0 = 전부)"),
    force: bool = typer.Option(False, "--force", help="패널·재무·지표 캐시를 무시하고 다시 만든다"),
    no_write: bool = _no_write_option("state/scans/"),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="FRED 를 받지 않는다 (캐시만)"),
    no_vcp: bool = typer.Option(False, "--no-vcp", help="vcp_index 계산 생략 (빠른 확인용)"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L1 사이클 스캐너 → 테마 스코어보드 (docs/02). 산출물: state/scans/<date>/"""
    from msa.l1.scan import run_scan

    _setup_logging(verbose)
    res = run_scan(
        asof=asof or None,
        force=force,
        write=not no_write,
        allow_fetch=not no_fetch,
        compute_vcp=not no_vcp,
    )
    typer.echo(res.scoreboard.render(top or None))
    typer.echo("")
    m = res.meta
    typer.echo(f"구성원: {m['membership']}")
    _u = m["unclassified_mcap"]
    typer.echo(
        f"미분류 시총 비율: {_u['share']:.3%} · "
        f"시총 결측 {_u.get('n_missing_mcap', '?')}종(미배정 "
        f"{_u.get('n_missing_mcap_unassigned', '?')}) · "
        f"소표본 {len(m['small_sample_buckets'])}개"
    )
    ph = m["physical"]
    typer.echo(
        f"축 1: 선언 {ph['declared']} · 데이터 있음 {ph['data_ok']} · "
        f"없음 {ph['data_missing']} · CPI {ph['cpi']}"
    )
    _echo_saved(res.out_dir)


#: `prices` 가 오늘보다 이만큼 넘게 뒤처지면 `msa data status` 가 적재를 권한다.
#: 거래일 기준 3일(주말+공휴일 한 번)이면 정상 범위다 — 그 이상은 적재를 건너뛴 것이다.
#: 이 저장소는 적재를 하지 않는다 (`docs/18` §6): 실제 적재는 `opt_portfolio` 가 한다.
STORE_LAG_WARN_DAYS = 4


def _echo_store_lag(stats: list[Any]) -> None:
    """스토어가 며칠 뒤처졌는지 찍는다. 문서에만 적으면 아무도 안 본다 (`CLAUDE.md` §2)."""
    from datetime import date as _date

    px = next((s for s in stats if s.name == "prices" and s.end), None)
    if px is None:
        typer.echo("\n주가 스토어에 end 가 없다 — 적재 상태를 확인하라")
        return
    end = px.end if isinstance(px.end, _date) else _date.fromisoformat(str(px.end))
    lag = (_date.today() - end).days
    typer.echo("")
    if lag <= STORE_LAG_WARN_DAYS:
        typer.echo(f"스토어 최신도: {end} · {lag}일 전 — 정상")
        return
    typer.echo(
        f"스토어 최신도: {end} · **{lag}일 전** — 뒤처져 있다 (기준 {STORE_LAG_WARN_DAYS}일).\n"
        "  스캔은 이 시점 가격으로 순위를 내고, 판별은 오늘 날짜 웹을 본다.\n"
        "  적재는 이 저장소가 하지 않는다 (docs/18 §6) — opt_portfolio 에서:\n"
        "    uv run opt-factor ingest --store ~/data/us_micro.duckdb \\\n"
        "        --provider sharadar --tables sf1,sep,daily --since $(date -d '-3 day' +%F)"
    )


def _echo_required_tickers(store: Any) -> None:
    """스토어에 **반드시 있어야 하는 종목**이 있는지 본다. 최신도만 보면 놓친다.

    2026-08-25 실측: 일간 증분 적재를 `--tables sf1,sep,daily` 로 돌렸더니 `prices` 가
    ETF 없이 다시 만들어져 **SPY 가 0행**이 됐다. 스토어 최신도는 "1일 전 · 정상" 이었고
    행수도 비슷해서 `msa data status` 로는 아무 이상이 없어 보였다. 스캔을 돌려야 알았다.
    Sharadar 는 주식(`sep`)과 펀드(`sfp`)를 다른 테이블로 준다 (`docs/18` §6).
    """
    from msa.data.store import ETF_IN_STORE

    missing = [t for t in ETF_IN_STORE if not int(store.scalar(_TICKER_COUNT_SQL.format(t=t)))]
    if not missing:
        return
    typer.echo("")
    typer.echo(
        f"**필수 종목이 prices 에 없다: {', '.join(missing)}** — 스캔이 멈춘다.\n"
        "  SPY 는 RS·상대거래대금의 기준이라 없으면 C 블록이 통째로 무의미하다.\n"
        "  원인은 대개 적재에서 `sfp`(펀드 가격) 테이블이 빠진 것이다 (docs/18 §6):\n"
        "    uv run opt-factor ingest --store ~/data/us_micro.duckdb \\\n"
        "        --provider sharadar --tables sfp --since 2020-01-01"
    )


#: 종목 하나의 행수. `Store.scalar` 는 파라미터를 받지 않아 티커를 끼워 넣는다 —
#: 값은 `ETF_IN_STORE` 상수라 외부 입력이 아니다.
_TICKER_COUNT_SQL = "select count(*) from prices where ticker = '{t}'"


@data_app.command("fred-fetch")
@cli_guard
def data_fred_fetch(
    force: bool = typer.Option(False, "--force", help="이미 캐시된 시리즈도 다시 받는다"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L1 이 쓰는 FRED 시리즈(CPIAUCSL + 테마 physical_ref 심볼)를 state/physical/fred/ 에 캐시.

    키(`FRED_API_KEY`)가 없으면 첫 시리즈에서 던진다. 실패한 시리즈는 이름을 전부 찍고 종료코드 1.
    (L2 드라이버 24종은 2026-08-23 L2 제거와 함께 받지 않는다 — docs/13 §9.)
    """
    from msa.data.fred import L1_SERIES, l1_series
    from msa.l1.physical import fetch_fred_to_cache, read_fred_cache

    _setup_logging(verbose)
    try:
        symbols = list(l1_series())
    except Exception as e:  # themes.yaml 문제는 CPI 수집을 막지 않는다 — 그러나 알린다
        typer.echo(f"themes.yaml 을 읽지 못해 physical_ref 심볼은 건너뛴다: {e}")
        symbols = list(L1_SERIES)
    ok: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for sym in symbols:
        if not force and read_fred_cache(sym) is not None:
            skipped.append(sym)
            continue
        try:
            s = fetch_fred_to_cache(sym)
            ok.append(sym)
            typer.echo(f"  {sym:<14} {len(s):>6}개 {s.index.min().date()} ~ {s.index.max().date()}")
        except Exception as e:
            failed.append(f"{sym}: {type(e).__name__}: {e}")
            typer.echo(f"  {sym:<14} 실패 — {type(e).__name__}: {e}")
            if isinstance(e, MissingApiKey):
                break
    typer.echo("")
    typer.echo(
        f"받음 {len(ok)} · 캐시 있어 건너뜀 {len(skipped)} · 실패 {len(failed)} "
        f"/ 대상 {len(symbols)}"
    )
    if failed:
        typer.echo("실패 목록:")
        for f in failed:
            typer.echo(f"  ! {f}")
        raise typer.Exit(code=1)


@backtest_app.command("l1")
@cli_guard
def backtest_l1(
    force: bool = typer.Option(False, "--force", help="패널·재무·지표 캐시를 무시하고 다시 만든다"),
    no_write: bool = _no_write_option("state/backtests/"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L1 스코어보드 백테스트 — rank-IC · 스프레드 · breadth_lead 실측 · DSR/PBO (M3.5).

    산출물: state/backtests/l1/<store_end>/. 결과로 가중치를 바꾸지 않는다 (CLAUDE.md §1).
    """
    from msa.l1.backtest import render_report, run_backtest

    _setup_logging(verbose)
    res = run_backtest(write=not no_write, force=force)
    typer.echo(render_report(res))
    _echo_saved(res.out_dir)


@backtest_app.command("l1-structures")
@cli_guard
def backtest_l1_structures(
    force: bool = typer.Option(False, "--force", help="패널·재무·지표 캐시를 무시하고 다시 만든다"),
    no_write: bool = _no_write_option("state/backtests/"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L1 점수 구조 검정 — S0·S1·S2 (M3.6, docs/12 §4) + S3(C 단독)·S2ʹ(C·E) (M3.7, docs/17).

    M3.6 은 후보별 rank-IC CI 하한 > 0, M3.7 은 짝지은 스프레드 차 `X − S2` 의 CI 하한 > 0 으로
    판정한다. 둘 다 사전 등록이고 결과로 가중치를 옮기지 않는다 (CLAUDE.md §1).
    산출물: state/backtests/l1/<store_end>/structures_*.
    """
    from msa.l1.structures import render_structure_report, run_structures

    _setup_logging(verbose)
    res = run_structures(write=not no_write, force=force)
    typer.echo(render_structure_report(res))


@backtest_app.command("l4")
@cli_guard
def backtest_l4(
    force: bool = typer.Option(
        False, "--force", help="테마별 특성 패널 parquet 캐시를 무시하고 다시 만든다"
    ),
    jobs: int = typer.Option(0, "--jobs", help="테마 단위 병렬 프로세스 수 (0 = min(14, cpu−2))"),
    themes: str = typer.Option(
        "", "--themes", help="스모크 전용 — 이 테마들만 (쉼표). 주면 산출물이 -smoke 로 갈린다"
    ),
    max_months: int = typer.Option(
        0, "--max-months", help="스모크 전용 — 격자 마지막 N 개월만. 주면 판정하지 않는다"
    ),
    no_write: bool = _no_write_option("state/backtests/"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L4 종목 선정 백테스트 — docs/14 사전 등록의 집행 (테마 내 rank-IC · 축 · 하드 필터 · 지표).

    산출물: state/backtests/l4/<store_end>/. 결과로 축 가중치·하드 임계를 바꾸지 않는다
    (CLAUDE.md §1, docs/14 §4.2·§4.3). --themes/--max-months 는 스모크용이며 판정을 내지 않는다.
    """
    from msa.l4.backtest import render_report, run_backtest

    _setup_logging(verbose)
    res = run_backtest(
        write=not no_write,
        force=force,
        jobs=jobs or None,
        themes_filter=[t.strip() for t in themes.split(",") if t.strip()] or None,
        max_months=max_months or None,
    )
    typer.echo(render_report(res))
    _echo_saved(res.out_dir)


@backtest_app.command("l4-structures")
@cli_guard
def backtest_l4_structures(
    force: bool = typer.Option(
        False, "--force", help="테마별 특성 패널 parquet 캐시를 무시하고 다시 만든다"
    ),
    jobs: int = typer.Option(0, "--jobs", help="테마 단위 병렬 프로세스 수 (0 = min(14, cpu-2))"),
    themes: str = typer.Option(
        "", "--themes", help="스모크 전용 — 이 테마들만 (쉼표). 주면 산출물이 -smoke 로 갈린다"
    ),
    max_months: int = typer.Option(
        0, "--max-months", help="스모크 전용 — 격자 마지막 N 개월만. 주면 판정하지 않는다"
    ),
    no_write: bool = _no_write_option("state/backtests/"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L4 선정 구조 비교 (docs/15 사전 등록의 집행) — B0~B4 후보 규칙의 테마 EW 초과 · 사망률 ·
    회전율 · PBO.

    산출물: state/backtests/l4-structures/<store_end>/ · 판정 docs/15. 특성 패널 캐시는
    `msa backtest l4` 의 것(state/backtests/l4/<store_end>/cache/)을 그대로 재사용한다.
    결과로 축 가중치·하드 임계를 바꾸지 않는다 (CLAUDE.md §1).
    """
    from msa.l4.structures import render_report, run_structures

    _setup_logging(verbose)
    res = run_structures(
        write=not no_write,
        force=force,
        jobs=jobs or None,
        themes_filter=[t.strip() for t in themes.split(",") if t.strip()] or None,
        max_months=max_months or None,
    )
    typer.echo(render_report(res))
    _echo_saved(res.out_dir)


@app.command()
@cli_guard
def balance(
    themes: str = typer.Argument(
        "", help="테마 id 쉼표 구분. 비우면 회전 선정 (조사 없는 것 먼저, 그다음 낡은 것)"
    ),
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD (기본 = 오늘)"),
    n: int = typer.Option(2, "-n", help="회전 선정 시 한 번에 조사할 테마 수"),
    unit: str = typer.Option("", "--unit", help="실물 단위 힌트 (예: 온스·톤·TEU)"),
    provider: str = typer.Option(
        "claude_code", "--provider", help="claude_code | anthropic | mock | fixture"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="MockProvider 로 경로만 검증"),
    no_write: bool = _no_write_option("state/balance/"),
    fixtures: str = typer.Option("", help="--provider fixture 의 루트"),
    show: bool = typer.Option(False, "--show", help="호출하지 않고 가진 조사만 보여준다"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L3.5 수급 균형 조사 — "수요 나누기 공급" (docs/26).

    판별기(L3)는 "안 죽었나" 만 묻는다. 이건 다른 질문이다:
    **향후 3~5년, 실물 수요 증가율이 실물 공급 증가율을 앞지르는가.**
    가격이 아니라 물량 대 물량이다.

    **매일 모든 섹터를 하지 않는다.** 수급 구조는 분기 단위로도 잘 안 바뀌므로 회전으로 돈다 —
    테마를 지정하지 않으면 조사 없는 편입 가능 테마부터, 그다음 90일 지난 것부터 n개.

    산출물 state/balance/<theme>.balance.yaml · .report.md.
    **트리아지 점수에 들어가지 않는다** (docs/26 §3.5) — 명단이 아니라 논지를 준다.
    """
    from datetime import date as _date

    from msa.config import paths as _paths
    from msa.l3.providers import make_provider as _make
    from msa.l35 import analyst as _ba
    from msa.l35 import balance as _bal
    from msa.thesis import all_theses, find_thesis, read_thesis_yaml

    p = _paths()
    root = p.balance
    if show:
        docs = []
        if root.exists():
            for f in sorted(root.glob("*.balance.yaml")):
                d = _bal.read(root, f.name.removesuffix(".balance.yaml"))
                if d:
                    docs.append(d)
        typer.echo(_bal.summarize(docs))
        today = _date.today()
        for d in docs:
            typer.echo("  " + _bal.summarize_theme(d, today=today))
        raise typer.Exit(0)

    today = _date.fromisoformat(asof) if asof else _date.today()
    picked = [t.strip() for t in themes.split(",") if t.strip()]
    if not picked:
        # **코드가 고른다** — 편입 가능 테마 중 조사 없는 것 먼저, 그다음 가장 낡은 것
        eligible = [h.theme for h in all_theses(today.isoformat()) if h.eligible]
        if not eligible:
            typer.echo("편입 가능 테마가 없다 — 조사할 대상이 없다", err=True)
            raise typer.Exit(2)
        picked = _bal.rotation(root, eligible, n=n, today=today)
        if not picked:
            typer.echo("전부 최근에 조사했다 — 낡은 것이 없다 (--show 로 확인)")
            raise typer.Exit(0)
        typer.echo(f"회전 선정: {' · '.join(picked)}")

    kind = "mock" if dry_run else provider
    fails = 0
    saved = 0
    for theme in picked:
        thesis = None
        tp = find_thesis(theme, today.isoformat(), p.theses)
        if tp is not None:
            thesis = read_thesis_yaml(tp)
        prov = _make(
            kind, theme_id=theme, fixture_root=Path(fixtures) if fixtures else None
        )
        try:
            doc = _ba.run(prov, theme, today.isoformat(), unit_hint=unit, thesis=thesis)
            _bal.validate(doc)
        except Exception as e:
            typer.echo(f"  {theme:22} 실패 — {type(e).__name__}: {e}", err=True)
            fails += 1
            continue
        typer.echo("  " + _bal.summarize_theme(doc, today=today))
        if not no_write:
            out = _bal.write(root, doc)
            out.with_suffix("").with_suffix(".report.md").write_text(
                _ba.render_report(doc), encoding="utf-8"
            )
            saved += 1
    if no_write:
        typer.echo("no-write — state/balance/ 에 쓰지 않았다")
    if fails:
        tail = f"저장 {saved}건" if saved else "저장된 것 없음"
        typer.echo(f"실패 {fails}건 · {tail}", err=True)
        raise typer.Exit(1)


@app.command("stock-notes")
@cli_guard
def stock_notes(
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD — 그 날 다이제스트를 읽는다. 기본 = 최신"),
    top_n: int = typer.Option(
        5, "--top-n", help="구획 I-A 의 triage 상위 몇 종목에 분석가를 붙일지"
    ),
    provider: str = typer.Option(
        "claude_code", "--provider", help="claude_code | anthropic | mock | fixture"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="MockProvider 로 경로만 검증"),
    no_write: bool = _no_write_option("state/stock_notes/"),
    refresh: bool = typer.Option(
        False, "--refresh", help="노트가 이미 있어도 다시 부른다 (기본은 새 종목만)"
    ),
    fixtures: str = typer.Option("", help="--provider fixture 의 루트"),
    show: bool = typer.Option(False, "--show", help="호출하지 않고 가진 노트만 보여준다"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """P3 종목 분석가 — "이 회사의 재무가 무너지고 있는가" (설계 §9.2).

    **후보는 코드가 정한다** — 구획 I-A 의 triage 상위 N. LLM 은 명단을 만들지 않고 받는다
    (CLAUDE.md §4). 질문은 하나뿐이고 '살 만한가' 를 묻지 않는다 — 스키마에 그 답을 담을 칸이
    없다.

    **온디맨드다.** 기본은 노트가 없는 종목만 부른다 (--refresh 로 강제). 매일 전부 부르면
    같은 종목의 판정이 매일 흔들려 사람이 무엇을 믿을지 모르게 된다.

    산출물 state/stock_notes/<TICKER>.yaml → 다음 `msa run daily` 의 J 축에 반영된다.
    """
    import json as _json

    from msa.config import paths as _paths
    from msa.l3.providers import make_provider as _make
    from msa.l4 import analyst as _sa

    p = _paths()
    root = p.stock_notes
    if show:
        have = sorted(x.stem for x in root.glob("*.yaml")) if root.exists() else []
        notes = [n for t in have if (n := _sa.read(root, t)) is not None]
        typer.echo(_sa.summarize(notes))
        for n in notes:
            typer.echo(f"  {n['ticker']:8} {n.get('verdict'):10} {n.get('theme')}")
        raise typer.Exit(0)

    days = sorted(x.name for x in p.daily.iterdir()) if p.daily.exists() else []
    if asof:
        days = [d for d in days if d <= asof]
    if not days:
        typer.echo("다이제스트가 없다 — `msa run daily` 를 먼저 돌린다", err=True)
        raise typer.Exit(2)
    digest = _json.loads((p.daily / days[-1] / "digest.json").read_text(encoding="utf-8"))
    rows = (digest.get("triage") or {}).get("rows") or []
    if not rows:
        typer.echo("트리아지 블록이 없다 — 다이제스트가 낡았다", err=True)
        raise typer.Exit(2)

    cands = _sa.candidates(rows, partition="I-A", top_n=top_n)
    if not refresh:
        cands = [c for c in cands if _sa.read(root, c.ticker) is None]
    if not cands:
        typer.echo("부를 종목이 없다 — 구획 I-A 상위가 전부 노트를 갖고 있다")
        raise typer.Exit(0)

    picks = {
        str(x.get("ticker")): x
        for e in (digest.get("themes") or [])
        for x in (e.get("picks") or [])
    }
    kind = "mock" if dry_run else provider
    fails = 0
    saved = 0
    for c in cands:
        prov = _make(
            kind, theme_id=c.ticker, fixture_root=Path(fixtures) if fixtures else None
        )
        try:
            note = _sa.run(prov, c, picks.get(c.ticker, {}), digest.get("asof") or days[-1])
            _sa.validate(note)
        except Exception as e:  # 한 종목의 실패가 나머지를 죽이지 않게 — 그러나 센다
            typer.echo(f"  {c.ticker:8} 실패 — {type(e).__name__}: {e}", err=True)
            fails += 1
            continue
        typer.echo(f"  {c.ticker:8} {note['verdict']}")
        if not no_write:
            _sa.write(root, note)
            saved += 1
    if no_write:
        typer.echo("no-write — state/stock_notes/ 에 쓰지 않았다")
    if fails:
        # **"나머지는 저장했다" 를 무조건 쓰지 않는다** — 전부 실패했는데 그렇게 적으면
        # 거짓말이 된다 (`CLAUDE.md` §2 의 정신).
        tail = f"저장 {saved}건" if saved else "저장된 것 없음"
        typer.echo(f"실패 {fails}건 · {tail}", err=True)
        raise typer.Exit(1)


@app.command()
@cli_guard
def regime(
    week: str = typer.Option("", help="ISO 주 YYYY-Www (기본 = 오늘이 속한 주)"),
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD (기본 = 오늘)"),
    provider: str = typer.Option(
        "claude_code",
        "--provider",
        help=(
            "claude_code | anthropic | mock | fixture. "
            "claude_code = 로컬 claude CLI 하위 프로세스 (구독 인증 — API 크레딧 0)"
        ),
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="MockProvider 로 경로만 검증"),
    no_write: bool = _no_write_option("state/regime/"),
    fixtures: str = typer.Option("", help="--provider fixture 의 루트"),
    show: bool = typer.Option(False, "--show", help="호출하지 않고 최신 레짐만 보여준다"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """P2 매크로 분석가 — cycle_class 8칸에 3값 판정 (docs/25).

    **주간 1회**다. 매일 돌리지 않는다 — 같은 날 두 번 돌리면 다른 값이 나와 재현성을 잃는다
    (docs/25 §4.3). 산출물 state/regime/<week>.yaml.

    판정은 트리아지 **R 축의 계수**로만 쓰인다: tailwind 1.00 · neutral 0.85 · headwind 0.70.
    J(판정 신뢰도)·C(재무 명료도)·구획은 **못 건드린다** — 매크로는 그 테마의 가치함정 판별이
    옳은지에 대해서도 그 회사의 재무에 대해서도 아무 말을 하지 않는다.
    """
    from datetime import date as _date

    from msa.config import paths as _paths
    from msa.l2 import analyst as _analyst
    from msa.l2 import regime as _regime
    from msa.l3.providers import make_provider as _make

    root = _paths().regime
    if show:
        doc = _regime.latest(root)
        typer.echo(_analyst.summarize(doc))
        if doc:
            for name in sorted(doc.get("classes") or {}):
                body = doc["classes"][name]
                typer.echo(f"  {name:24} {body.get('verdict')}")
        raise typer.Exit(0)

    today = _date.fromisoformat(asof) if asof else _date.today()
    iso = today.isocalendar()
    wk = week or f"{iso.year}-W{iso.week:02d}"
    kind = "mock" if dry_run else provider
    prov = _make(
        kind,
        theme_id="__macro__",
        fixture_root=Path(fixtures) if fixtures else None,
    )
    doc = _analyst.run(prov, week=wk, asof=today.isoformat())
    # 검증은 저장 전에 — 무효화 조건·증거가 없으면 저장하지 않는다 (CLAUDE.md §3·§5)
    _regime.validate(doc)
    typer.echo(_analyst.summarize(doc))
    if no_write:
        typer.echo("no-write — state/regime/ 에 쓰지 않았다")
        raise typer.Exit(0)
    out = _regime.write(root, doc)
    typer.echo(f"저장: {out}")


@app.command()
@cli_guard
def research(
    theme: str = typer.Argument(..., help="테마 id (state/themes.yaml)"),
    asof: str = typer.Option(
        "", help="기준일 YYYY-MM-DD — 그 이전 최신 스캔을 쓴다. 기본 = 최신 스캔"
    ),
    decision_date: str = typer.Option(
        "",
        "--decision-date",
        help=(
            "판정을 내리는 날 YYYY-MM-DD (기본 = 오늘). 증거가 미래인지는 이 날짜로 잰다 — "
            "스캔 날짜로 재면 스토어가 뒤처진 만큼 실재하는 문서가 미래로 오판된다. "
            "과거 시점을 되돌려 재현할 때만 명시한다"
        ),
    ),
    provider: str = typer.Option(
        "claude_code",
        "--provider",
        help=(
            "claude_code | anthropic | mock | fixture. "
            "claude_code = 로컬 claude CLI 하위 프로세스 (구독 인증 — API 크레딧 0). "
            "anthropic 은 ANTHROPIC_API_KEY 로 크레딧을 쓴다"
        ),
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="MockProvider 로 경로만 검증 (저장도 한다 — 합성 표기)"
    ),
    no_write: bool = _no_write_option("state/theses/"),
    no_store: bool = typer.Option(
        False, "--no-store", help="DuckDB 구성원 재무 요약 생략 (경고로 표시)"
    ),
    fixtures: str = typer.Option("", help="--provider fixture 의 루트 (기본 tests/fixtures/l3)"),
    record: str = typer.Option(
        "",
        "--record",
        help=(
            "claude_code 성공 산출을 <dir>/<theme>/<role>.json 으로 남긴다 — "
            "이후 --provider fixture 로 같은 라운드를 오프라인·$0 재현. 예: state/fixtures"
        ),
    ),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L3 에이전트 리서치 (supply · catalyst · bear · referee) → thesis 객체 (docs/05).

    산출물: state/theses/<date>/<theme>.thesis.yaml · <theme>.report.md · rejections-pending.yaml ·
    contested.json.
    스키마 미달이면 저장하지 않고 종료 코드 2. 게이트 기각은 저장한다 (docs/05 §4).
    """
    from msa.l3.contracts import InputsError, assemble_inputs
    from msa.l3.pipeline import run_research
    from msa.l3.providers import ProviderError, make_provider
    from msa.l3.schema import ThesisRejected

    _setup_logging(verbose)
    kind = "mock" if dry_run else provider
    try:
        inputs = assemble_inputs(
            theme,
            state_dir=paths().state,
            asof=asof or None,
            decision_date=decision_date or None,
            with_store=not no_store,
        )
    except InputsError as e:
        typer.echo(f"입력 오류: {e}", err=True)
        raise typer.Exit(code=1) from e
    prov = make_provider(
        kind,
        theme_id=theme,
        fixture_root=Path(fixtures) if fixtures else None,
        record_dir=Path(record) if record else None,
    )
    if kind == "anthropic" and not (
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    ):
        typer.echo(
            "경고: ANTHROPIC_API_KEY 가 비어 있다 — SDK 가 `ant auth login` 프로필을 찾지 못하면 "
            "인증 오류가 난다. "
            "오프라인 검증은 --dry-run 또는 --provider fixture.",
            err=True,
        )
    try:
        res = run_research(inputs, prov, theses_root=paths().theses, write=not no_write)
    except ThesisRejected as e:
        typer.echo("thesis 스키마 검증 실패 — 저장하지 않는다 (CLAUDE.md §3·§5):", err=True)
        for line in e.result.errors:
            typer.echo(f"  - {line}", err=True)
        raise typer.Exit(code=2) from e
    except ProviderError as e:
        typer.echo(f"제공자 오류: {e}", err=True)
        raise typer.Exit(code=3) from e
    typer.echo(res.report_md)
    if res.thesis_path:
        typer.echo(f"\n저장: {res.thesis_path}")


@app.command()
@cli_guard
def picks(
    theme: str,
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD. 기본 = 스토어 최종일"),
    top: int = typer.Option(
        4, help="관찰용 바벨 라벨 수 (선정에 쓰이지 않는다 — 선정은 적격 종목 전부·동일가중)"
    ),
    no_write: bool = _no_write_option("state/picks/"),
    no_physical: bool = typer.Option(
        False,
        "--no-physical",
        help="상품가 탄력성(price_beta_hist) 계산 생략 — ETF 벌크 스캔 ~12초",
    ),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="FRED 를 받지 않는다 (캐시만)"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L4 종목 선정 — 하드 제외 통과 종목 전부·테마 내 동일가중 (docs/06 §5.1·§6.1).

    3축(S·T·M)·종합·순위·바벨 라벨은 함께 산출되지만 **관찰 지표이고 선정에 쓰이지 않는다.**
    산출물: state/picks/<date>/<theme>/
    """
    from msa.l4.picks import run_picks

    _setup_logging(verbose)
    res = run_picks(
        theme,
        asof=asof or None,
        top=top,
        write=not no_write,
        allow_fetch=not no_fetch,
        with_physical=not no_physical,
    )
    typer.echo(res.report)
    _echo_saved(res.out_dir)


@app.command()
@cli_guard
def portfolio(
    inputs: str = typer.Option(
        ..., "--inputs", help="입력 디렉터리: picks.csv · theses/*.yaml (· returns.csv 선택)"
    ),
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD. 기본 = 오늘"),
    cases: str = typer.Option(
        "",
        "--cases",
        help="케이스 스터디 표. 기본 = state/cases/cases.yaml (없으면 L_i 형성 불가로 표기)",
    ),
    capital: float = typer.Option(
        0.0, "--capital", help="총자본(USD). 주면 C4 유동성 상한(ADV20 의 10%)을 건다"
    ),
    cluster_cap: list[str] = typer.Option(  # noqa: B008 — typer 의 옵션 선언 관용구
        [], "--cluster-cap", help="선택적 클러스터 상한 name=cap (docs/07 §2.5 — 요구했을 때만)"
    ),
    no_write: bool = _no_write_option("state/portfolio/"),
    emit_positions: bool = typer.Option(
        False,
        "--emit-positions",
        help="positions.yaml 모양의 미체결 제안(positions-proposal.yaml + .md 체크리스트)도 쓴다. "
        "state/positions.yaml 은 건드리지 않는다 — 승격은 사람이 (--no-write 와 양립 불가)",
    ),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L5 포트 구성 + 매매계획서 (docs/07). 산출물: state/portfolio/<date>/"""
    from msa.l5.plan import render_plan
    from msa.l5.run import cluster_caps_from_args, run_portfolio

    _setup_logging(verbose)
    if emit_positions and no_write:
        raise typer.BadParameter(
            "--emit-positions 는 --no-write 와 같이 줄 수 없다 (제안은 파일이다)"
        )
    res = run_portfolio(
        asof=asof or None,
        inputs_dir=inputs,
        cases_path=cases or None,
        capital_usd=capital if capital > 0 else None,
        cluster_caps=cluster_caps_from_args(cluster_cap),
        write=not no_write,
        emit_positions=emit_positions,
    )
    typer.echo(render_plan(res))
    _echo_saved(res.out_dir)
    if emit_positions and res.out_dir is not None:
        typer.echo(
            f"positions 제안: {res.out_dir / 'positions-proposal.yaml'} (미체결 — "
            "승격 절차는 positions-proposal.md · state/positions.yaml 은 쓰지 않았다)"
        )


@app.command("portfolio-inputs")
@cli_guard
def portfolio_inputs(
    asof: str = typer.Option(
        "", help="기준일 YYYY-MM-DD. 기본 = 오늘. 이 날짜 이하의 최신 picks·thesis"
    ),
    themes: str = typer.Option(..., "--themes", help="테마 id 쉼표 목록 (state/themes.yaml)"),
    human_theses: str = typer.Option(
        "",
        "--human-theses",
        help="사람이 쓴 논지 디렉터리 <dir>/<theme>.yaml — 있으면 L3 산출보다 우선 (source=human)",
    ),
    top: int = typer.Option(
        0, "--top", help="테마당 종목 상한 — 사람이 주는 상한이지 L4 규칙이 아니다 (0 = 적격 전부)"
    ),
    no_write: bool = _no_write_option("state/portfolio_inputs/"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L4 picks + L3/사람 thesis → L5 입력 묶음 (picks.csv · theses/).

    산출물: state/portfolio_inputs/<date>/
    """
    from msa.pipeline.assemble import assemble_inputs

    _setup_logging(verbose)
    res = assemble_inputs(
        asof=asof_or_today(asof or None),
        themes=[t for t in themes.split(",") if t.strip()],
        human_theses_dir=human_theses or None,
        top_per_theme=top if top > 0 else None,
        write=not no_write,
    )
    typer.echo(res.report_text)
    _echo_saved(res.out_dir)


# ---------------------------------------------------------------------------
# msa run — 케이던스 오케스트레이터 (배선 W4)
# ---------------------------------------------------------------------------


def _echo_run_report(rep: Any) -> None:
    """단계 표 + 사람 TODO 를 찍는다 (마크다운 전문은 파일에)."""
    typer.echo(f"{rep.cadence} · {rep.asof}" + ("" if rep.write else " · no-write"))
    for s in rep.steps:
        outs = f"  → {', '.join(s.outputs)}" if s.outputs else ""
        typer.echo(f"  {s.name:<10} {s.status:<12} {s.seconds:6.1f}s  {s.reason}{outs}")
    if rep.stopped:
        typer.echo(f"중단: {rep.stopped_reason}", err=True)
    if rep.human_todo:
        typer.echo("사람이 할 것:")
        for x in rep.human_todo:
            typer.echo(f"  - {x}")


@run_app.command("monthly")
@cli_guard
def run_monthly_cmd(
    asof: str = typer.Option(
        "", help="기준일 YYYY-MM-DD (기본 오늘). 스캔·thesis·picks·포트 전부 이 날짜"
    ),
    top_k: int = typer.Option(
        8, "--top-k", help="스코어보드 상위 K (자격 테마만 — docs/05 §1, docs/02 §7.1)"
    ),
    themes: str = typer.Option(
        "", "--themes", help="사용자 지정 테마 쉼표 목록 — 순위와 무관하게 L3 에 넣는다"
    ),
    provider: str = typer.Option(
        "none",
        "--provider",
        help="none | claude_code | mock | fixture | anthropic. "
        "none = L3 를 부르지 않고 사람 논지/직전 thesis 만 찾는다. "
        "claude_code = 로컬 claude CLI (API 크레딧 0)",
    ),
    human_theses: str = typer.Option(
        "",
        "--human-theses",
        help="사람이 쓴 논지 디렉터리 <dir>/<theme>.yaml — 있으면 L3 보다 우선",
    ),
    capital: float = typer.Option(0.0, "--capital", help="총자본(USD). 주면 L5 C4 유동성 상한"),
    skip_research: bool = typer.Option(
        False, "--skip-research", help="L3 단계 생략 (논지는 찾는다)"
    ),
    skip_picks: bool = typer.Option(False, "--skip-picks", help="L4 단계 생략"),
    skip_portfolio: bool = typer.Option(False, "--skip-portfolio", help="묶음·L5 단계 생략"),
    no_write: bool = typer.Option(
        False, "--no-write", help="state/ 에 아무것도 쓰지 않는다 (중간 산출물은 임시 샌드박스)"
    ),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """월간 실행 (docs/09 §1): scan → 상위 K → research → ingest → picks → assemble → L5.

    산출물: state/runs/<date>/monthly-report.md · run.json (+ 각 계층의 state/ 산출물).
    끝은 진입 초안·미체결 제안이다 — 저널 확정·positions.yaml 승격·주문은 사람이 한다.
    종료 코드 1 은 스캔 중단일 때만; 부분 가용(테마별 실패)은 0 + 리포트.
    """
    from msa.pipeline.run import RunError, run_monthly

    _setup_logging(verbose)
    try:
        res = run_monthly(
            asof=asof or None,
            top_k=top_k,
            extra_themes=[t for t in themes.split(",") if t.strip()],
            provider=provider,
            human_theses_dir=Path(human_theses) if human_theses else None,
            write=not no_write,
            skip_research=skip_research,
            skip_picks=skip_picks,
            skip_portfolio=skip_portfolio,
            capital=capital if capital > 0 else None,
        )
    except RunError as e:
        raise typer.BadParameter(str(e)) from e
    _echo_run_report(res.report)
    _echo_saved(res.out_dir)
    if res.exit_code:
        raise typer.Exit(code=res.exit_code)


@run_app.command("weekly")
@cli_guard
def run_weekly_cmd(
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD (기본 오늘)"),
    no_write: bool = typer.Option(False, "--no-write", help="state/ 에 아무것도 쓰지 않는다"),
    send: bool = typer.Option(
        False, "--send", help="점검 알림을 텔레그램으로 보낸다 (기본은 파일에만 남긴다)"
    ),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """주간 실행 (docs/09 §1): 전수 스캔(경량 갱신 대용) + 보유 포지션 점검 (= msa check --weekly).

    --send 없이는 아무것도 발신하지 않는다 (alerts.json 에만 남는다) — msa run daily 와 같다.

    산출물: state/runs/<date>/weekly-report.md · run.json · state/checks/<date>/.
    """
    from msa.pipeline.run import RunError, run_weekly

    _setup_logging(verbose)
    try:
        res = run_weekly(asof=asof or None, write=not no_write, send=send)
    except RunError as e:
        raise typer.BadParameter(str(e)) from e
    _echo_run_report(res.report)
    if res.check is not None:
        typer.echo("")
        typer.echo(res.check.render())
    _echo_saved(res.out_dir)
    if res.exit_code:
        raise typer.Exit(code=res.exit_code)


@run_app.command("daily")
@cli_guard
def run_daily_cmd(
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD (기본 오늘)"),
    top_k: int = typer.Option(
        8, "--top-k", help="스코어보드 상위 K (자격 테마만 — docs/05 §1과 같은 K)"
    ),
    themes: str = typer.Option(
        "", "--themes", help="사용자 지정 테마 쉼표 목록 — 순위와 무관하게 다이제스트에 넣는다"
    ),
    per_theme: int = typer.Option(
        5, "--per-theme", help="테마당 표시 종목 수 (표시 개수 — 선정 규칙이 아니다)"
    ),
    no_write: bool = typer.Option(
        False, "--no-write", help="state/daily/ 에 쓰지 않는다 (화면 출력만; --send 도 무효)"
    ),
    send: bool = typer.Option(
        False,
        "--send",
        help="이 실행의 발신 허용 — 다이제스트 요약 + 보유 점검 알림 "
        "(MSA_TELEGRAM_* 둘 다 있을 때만). 없으면 아무것도 보내지 않는다",
    ),
    no_audit: bool = typer.Option(
        False,
        "--no-audit",
        help="편입 가능 테마의 증거 실사를 건너뛴다 (네트워크를 쓴다 — 테마당 ~35초)",
    ),
    no_readme: bool = typer.Option(
        False,
        "--no-readme",
        help="README.md 의 '오늘의 결론' 블록을 갱신하지 않는다 (기본은 갱신 — 커밋은 사람이)",
    ),
    no_research: bool = typer.Option(
        False,
        "--no-research",
        help="미판별 상위 테마 판별을 건너뛴다 (기본은 편입 가능이 나올 때까지 위에서부터)",
    ),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """일간 후보 다이제스트 (docs/09 §1 일간 행): 스캔(캐시) → 상위 K → 테마별 L4 랭킹 →
    직전 다이제스트 diff → 보유 점검(positions.yaml 이 있을 때).

    산출물: state/daily/<date>/digest.json · digest.md · report.txt. 읽기 전용 후보 뷰다 —
    측정값·후보 목록이지 투자 조언이 아니다 (L1 점수 예측력 약함, docs/02 §7.1).
    결정 케이던스는 월간 그대로 (msa run monthly).
    --send 없이는 아무것도 발신하지 않는다 — 다이제스트도, 보유 점검 알림도 (파일에만 남는다).
    """
    from msa.pipeline.daily import run_daily
    from msa.pipeline.run import RunError

    _setup_logging(verbose)
    try:
        res = run_daily(
            asof=asof or None,
            top_k=top_k,
            extra_themes=[t for t in themes.split(",") if t.strip()],
            picks_per_theme=per_theme,
            write=not no_write,
            send=send,
            audit=not no_audit,
            update_readme=not no_readme,
            research=not no_research,
        )
    except RunError as e:
        raise typer.BadParameter(str(e)) from e
    _echo_run_report(res.report)
    typer.echo("")
    typer.echo(res.digest_md)
    if res.telegram is not None:
        typer.echo(f"텔레그램: {res.telegram}")
    _echo_saved(res.out_dir)
    if res.exit_code:
        raise typer.Exit(code=res.exit_code)


@run_app.command("quarterly")
@cli_guard
def run_quarterly_cmd() -> None:
    """분기 작업 목록 (docs/09 §1): 캘리브레이션 · 기각 대장. 실행 안 함."""
    from msa.pipeline.run import run_quarterly

    typer.echo(run_quarterly())


# ---------------------------------------------------------------------------
# msa check
# ---------------------------------------------------------------------------


@app.command()
@cli_guard
def check(
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD (기본 오늘)"),
    daily: bool = typer.Option(False, "--daily", help="일간 — 무효화·사다리·TP·시간스탑 자동 확인"),
    weekly: bool = typer.Option(False, "--weekly", help="주간 — 전 항목 + manual 목록 (기본)"),
    no_write: bool = _no_write_option("state/checks/"),
    no_send: bool = typer.Option(False, "--no-send", help="텔레그램을 보내지 않는다 (파일만)"),
    positions: str = typer.Option("", help="positions.yaml 경로 (기본 state/positions.yaml)"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """보유 포지션의 트리거·무효화·Tier-2·사다리·시간스탑·TP 점검 (docs/09 §1).

    주문은 내지 않는다 (CLAUDE.md §8).
    """
    from msa.data.store import Store
    from msa.ops.alerts import deliver
    from msa.ops.check import StorePriceSource, run_check
    from msa.ops.journal import journal_dir
    from msa.vendor.scheduler import LastRunStore, RunTracker

    _setup_logging(verbose)
    if daily and weekly:
        raise typer.BadParameter("--daily 와 --weekly 는 동시에 줄 수 없다")
    mode = "daily" if daily else "weekly"
    p = paths()
    root = REPO_ROOT
    asof_d = asof_or_today(asof)
    pos_path = Path(positions) if positions else p.positions
    out_root = None if no_write else p.checks
    tracker = RunTracker(LastRunStore(p.checks / "last_run.json"), key=f"check.{mode}")
    lookback = tracker.lookback_days(asof_d)
    if lookback > 1:
        typer.echo(
            f"마지막 성공 점검 이후 {lookback}일 — 그 사이의 발동은 이번 판정(가격 이력)에 포함된다"
        )

    with Store(p.duckdb) as store:
        prices = StorePriceSource(store)
        report = run_check(
            asof=asof_d,
            mode=mode,
            prices=prices,
            positions_path=pos_path,
            journal_dir=journal_dir(root),
            repo_root=root,
            out_root=out_root,
        )
    typer.echo(report.render())
    if report.out_dir is not None:
        res = deliver(report.alerts, report.out_dir, use_env=not no_send, send=not no_send)
        typer.echo("")
        typer.echo(f"저장: {report.out_dir}  ·  알림 {len(report.alerts)}건 → {res.json_path.name}")
        typer.echo(
            f"텔레그램: {res.status}"
            + (
                " (MSA_TELEGRAM_TOKEN / MSA_TELEGRAM_CHAT_ID 둘 다 있어야 보낸다)"
                if res.status == "not_configured"
                else " (--no-send — 파일만 썼다)"
                if res.status == "suppressed"
                else f" 전송 {res.sent} 실패 {res.failed}"
            )
        )
        if not no_write:
            tracker.mark_polled()
    if report.problems:
        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# msa journal
# ---------------------------------------------------------------------------


@journal_app.command("template")
@cli_guard
def journal_template(
    type_: str = typer.Argument(..., metavar="TYPE", help="entry|check|add|tp|exit|reject"),
) -> None:
    """항목 YAML 골격을 출력한다 — 채워서 `msa journal new --from` 에 준다."""
    from msa.ops.journal import TEMPLATES

    if type_ not in TEMPLATES:
        raise typer.BadParameter(f"type ∈ {sorted(TEMPLATES)}")
    typer.echo(TEMPLATES[type_], nl=False)


@journal_app.command("new")
@cli_guard
def journal_new(
    from_: str = typer.Option(..., "--from", help="항목 YAML 파일 (type 키로 종류 지정)"),
    suffix: str = typer.Option("", help="같은 날 같은 종류가 둘이면 파일명 접미사"),
    journal: str = typer.Option("", help="journal/ 경로 (기본 저장소 루트의 journal/)"),
) -> None:
    """저널 항목을 추가한다. 필수 필드가 비면 거부, 기존 파일은 덮어쓰지 않는다."""
    import yaml

    from msa.ops.journal import journal_dir, record_from_dict, write_record

    d = yaml.safe_load(Path(from_).read_text(encoding="utf-8"))
    if not isinstance(d, dict):
        raise typer.BadParameter("YAML 최상위가 dict 여야 한다")
    jdir = Path(journal) if journal else journal_dir(REPO_ROOT)
    # IncompleteEntry · JournalImmutable 은 `cli_guard` 가 메시지 + 종료 코드 1 로 바꾼다
    w = write_record(record_from_dict(d), jdir, suffix=suffix)
    typer.echo(f"작성: {w.markdown}")
    if w.thesis_snapshot:
        typer.echo(f"스냅샷: {w.thesis_snapshot}")
    if w.diff_text:
        typer.echo("")
        typer.echo(w.diff_text)


@journal_app.command("verify")
@cli_guard
def journal_verify(
    staged: bool = typer.Option(False, "--staged", help="인덱스만 본다 (pre-commit)"),
    repo: str = typer.Option("", help="저장소 루트 (기본 이 저장소)"),
) -> None:
    """커밋된 journal/ 파일이 수정·삭제됐으면 실패 (append-only, CLAUDE.md §6)."""
    from msa.ops.journal import verify_append_only

    root = Path(repo) if repo else REPO_ROOT
    v = verify_append_only(root, staged_only=staged)
    if v:
        typer.echo(
            "journal/ append-only 위반 — 기존 항목은 고치지 않는다. 새 항목을 추가하고 링크해라:",
            err=True,
        )
        for x in v:
            typer.echo(f"  {x.render()}", err=True)
        raise typer.Exit(code=1)
    typer.echo("journal/ OK — 기존 항목 변경 없음")


@journal_app.command("install-hook")
@cli_guard
def journal_install_hook(
    force: bool = typer.Option(False, "--force", help="기존 pre-commit 훅을 덮어쓴다"),
    repo: str = typer.Option("", help="저장소 루트"),
) -> None:
    """.git/hooks/pre-commit 에 scripts/journal-precommit.sh 를 건다 (명시적 호출로만 설치)."""
    from msa.ops.journal import install_hook

    try:
        t = install_hook(Path(repo) if repo else REPO_ROOT, force=force)
    except FileExistsError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"설치: {t}")


@journal_app.command("diff")
@cli_guard
def journal_diff(
    theme: str = typer.Argument(..., help="테마 id"),
    journal: str = typer.Option("", help="journal/ 경로"),
) -> None:
    """최근 두 thesis 스냅샷의 필드 단위 diff — 논지 표류 추적 (docs/05 §6)."""
    from msa.ops.journal import journal_dir, thesis_drift

    typer.echo(thesis_drift(Path(journal) if journal else journal_dir(REPO_ROOT), theme))


# ---------------------------------------------------------------------------
# msa ops
# ---------------------------------------------------------------------------


@ops_app.command("audit-evidence")
@cli_guard
def ops_audit_evidence(
    theme: str = typer.Argument(..., help="테마 id"),
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD 이하의 최신 논지 (기본 오늘)"),
    all_evidence: bool = typer.Option(
        False, "--all", help="판정을 만든 증거뿐 아니라 **전부** 실사한다 (느리다)"
    ),
    no_write: bool = _no_write_option("state/audits/"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """증거 실사 — `claim` 의 숫자가 **그 문서에 실제로 있는지** 확인한다 (`docs/05` §6.10).

    스키마는 형식만 본다. 그것을 통과하면서 원문에 없는 수치를 적을 수 있고, 2026-08-25
    실사에서 표본의 20% 가 그랬다. 이 명령은 판정을 만든 증거만 골라 원문을 받아 대조한다.
    문맥은 못 본다 — 못 찾은 것과 못 읽은 것을 알려줘 **사람이 어느 URL 을 먼저 열지** 정한다.
    """
    from msa.io import write_snapshot
    from msa.l3.evidence_audit import audit_thesis, http_fetch, render_audit
    from msa.thesis import find_thesis, read_thesis_yaml

    _setup_logging(verbose)
    p = paths()
    asof_s = asof or date.today().isoformat()
    path = find_thesis(theme, asof_s, p.theses)
    if path is None:
        typer.echo(
            f"{theme}: {asof_s} 이하의 논지가 없다 — `msa research {theme}` 를 먼저", err=True
        )
        raise typer.Exit(code=1)
    thesis = read_thesis_yaml(path)
    res = audit_thesis(thesis, http_fetch, only_axis_refs=not all_evidence)
    typer.echo(render_audit(theme, res))

    # **어느 것을 먼저 열지**까지 적는다 — 목록만 내면 사람이 매번 손으로 훑는다.
    from msa.l3.evidence_audit import PARTIAL
    from msa.l3.evidence_triage import render_triage, run_triage

    items, why = run_triage(theme, res.checks, thesis.get("evidence") or [], res.axis_refs)
    if items:
        typer.echo("")
        if why:
            typer.echo(f"(분류가 기계 순서로 내려갔다 — {why})")
        for line in render_triage(
            items,
            total_partial=sum(1 for c in res.checks if c.status == PARTIAL),
            urls={c.evidence_id: c.url for c in res.checks},
        ):
            typer.echo(line)
    if not no_write:
        out = write_snapshot(
            p.state / "audits" / asof_s,
            jsons={
                f"{theme}.audit.json": {
                    "theme": theme,
                    "thesis": str(path),
                    "counts": res.counts(),
                    "unverified_axes": res.unverified_axes(),
                    "checks": [c.as_dict() for c in res.checks],
                }
            },
        )
        _echo_saved(out)


@ops_app.command("schedule")
@cli_guard
def ops_schedule(
    print_cron: bool = typer.Option(False, "--print-cron", help="crontab 텍스트"),
    systemd: bool = typer.Option(False, "--systemd", help="systemd 타이머 텍스트"),
) -> None:
    """케이던스(docs/09 §1) → crontab/systemd 텍스트. 아무것도 설치하지 않는다."""
    from msa.ops.scheduler import cron_lines, systemd_units

    if systemd:
        typer.echo(systemd_units(REPO_ROOT))
    else:
        typer.echo(cron_lines(REPO_ROOT))


@ops_app.command("why")
@cli_guard
def ops_why(
    name: str = typer.Argument("", help="상수 이름 (비우면 전체 표)"),
    missing_only: bool = typer.Option(False, "--missing", help="근거 없는 것만"),
    unsearched: bool = typer.Option(False, "--unsearched", help="아직 조사하지 않은 것만"),
    weak: bool = typer.Option(False, "--weak", help="자르는데 근거가 없는 것만 — 가장 약한 고리"),
) -> None:
    """필터 상수의 **근거** — 왜 그 값인가 (`msa ops why RUNWAY_MIN_Q`).

    인용이면 원문과 URL 을, 근거가 없으면 **없다는 사실과 왜 없는지**를 찍는다.
    근거 없음은 결함이 아니라 CLAUDE.md §1 이 요구하는 기록이다.
    """
    from msa.basis import BASES, Citation, NoBasis, render, render_table, weakest_links

    if name:
        typer.echo(render(name))
        return
    if weak:
        links = weakest_links()
        typer.echo(
            f"**자르거나 게이트를 쥐는데 근거가 없는 상수 {len(links)}개**\n"
            "근거 없음 자체는 §1 위반이 아니다. 다만 자르는 값이 그런 것은 무게가 다르다.\n"
        )
        for n in links:
            typer.echo(render(n) + "\n")
        return
    if missing_only or unsearched:
        sel = [
            n
            for n, e in BASES.items()
            if isinstance(e.basis, NoBasis) and (not e.basis.searched if unsearched else True)
        ]
        what = "아직 조사하지 않은" if unsearched else "근거가 없는"
        typer.echo(f"{what} 필터 상수 {len(sel)}개\n")
        for n in sel:
            typer.echo(render(n) + "\n")
        if unsearched:
            typer.echo("→ 이 목록이 줄어드는 것이 진척이다. 조사 후 searched 날짜를 적어라.")
        return
    typer.echo(render_table())
    n_cite = sum(1 for e in BASES.values() if isinstance(e.basis, Citation))
    typer.echo(
        f"\n인용 {n_cite}개는 원문·URL 을 들고 있다 — `msa ops why <이름>` 으로 본다.\n"
        "근거 없음은 숨긴 것이 아니라 적은 것이다 (CLAUDE.md §1)."
    )


@ops_app.command("due")
@cli_guard
def ops_due(
    cadence: str = typer.Argument(..., help="monthly|weekly|daily|quarterly"),
    asof: str = typer.Option("", help="기준일 (기본 오늘)"),
) -> None:
    """오늘이 그 케이던스의 실행일이면 0, 아니면 1 — cron 의 '1영업일' 게이트."""
    from msa.ops.scheduler import CADENCES, is_due

    if cadence not in CADENCES:
        raise typer.BadParameter(f"cadence ∈ {CADENCES}")
    d = asof_or_today(asof)
    ok = is_due(cadence, d)
    typer.echo(f"{cadence} @ {d}: {'due' if ok else 'not due'}")
    raise typer.Exit(code=0 if ok else 1)


@ops_app.command("calibration")
@cli_guard
def ops_calibration(
    journal: str = typer.Option("", help="journal/ 경로"),
    write: bool = typer.Option(
        True, "--write/--no-write", help="state/calibration/<date>.txt 저장"
    ),
) -> None:
    """cycle_confidence 캘리브레이션 (docs/10 §4). N<20 이면 '결론 없음' + 표본 나열."""
    import json

    from msa.ops.calibration import run, to_json
    from msa.ops.journal import journal_dir

    text, cals = run(Path(journal) if journal else journal_dir(REPO_ROOT))
    typer.echo(text)
    if write:
        out = paths().calibration
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{date.today().isoformat()}.txt").write_text(text, encoding="utf-8")
        (out / f"{date.today().isoformat()}.json").write_text(
            json.dumps(to_json(cals), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        _echo_saved(out)


@ops_app.command("rejections-update")
@cli_guard
def ops_rejections_update(
    asof: str = typer.Option("", help="기준일 (기본 오늘)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="파일을 쓰지 않는다"),
) -> None:
    """기각 대장 r_12m/r_24m 갱신 + 세 질문 집계 → state/rejections-summary.md (내부 기록)."""
    from msa.ops.journal import journal_dir
    from msa.ops.rejections import load_axis1_monthly, load_theme_index, summarize
    from msa.ops.state_files import load_rejections, save_rejections

    p = paths()
    asof_d = asof_or_today(asof)
    rows = load_rejections(p.rejections)
    if not rows:
        typer.echo("기각 대장이 비어 있다 (state/rejections.yaml) — 월간 스캔이 행을 적재해야 한다")
    cache = p.cache
    index = load_theme_index(cache)
    summary = summarize(
        rows,
        index=index,
        axis1=load_axis1_monthly(cache),
        jdir=journal_dir(REPO_ROOT),
        scans_dir=p.scans,
        asof=asof_d,
    )
    typer.echo(summary.text)
    if not dry_run:
        save_rejections(p.rejections, summary.updated_rows)
        p.rejections_summary.write_text(summary.text, encoding="utf-8")
        typer.echo(
            f"갱신: r_12m {summary.n_filled_12m}개 · r_24m {summary.n_filled_24m}개 → "
            f"{p.rejections}"
        )


@ops_app.command("ingest-theses")
@cli_guard
def ops_ingest_theses(
    theses_dir: str = typer.Option(
        ..., "--theses-dir", help="state/theses/<date>/ (msa research 산출 라운드)"
    ),
    scan: str = typer.Option(
        "", "--scan", help="state/scans/<date>/ (순위·블록 6개). 없으면 thesis 의 inputs.scan_dir"
    ),
    asof: str = typer.Option(
        "", help="기각일/관찰 등록일 (기본 theses-dir 이름의 날짜, 아니면 오늘)"
    ),
    journal: str = typer.Option("", help="journal/ 경로 (기본 저장소 루트의 journal/)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="판정만 하고 파일을 쓰지 않는다"),
) -> None:
    """L3 라운드 → 저널 기각 항목·기각 대장·관찰 목록·진입 초안 (docs/09 §2·§4, docs/05 §4).

    진입 항목은 쓰지 않는다 — 초안(journal-draft-<theme>.yaml)을 남기고 사람이 종목·비중·사다리와
    "기계 권고와 다르게 결정한 이유" 를 채워 `msa journal new --from` 으로 확정한다.
    """
    from msa.dates import parse_date
    from msa.ops.ingest import ingest_round
    from msa.ops.journal import journal_dir

    tdir = Path(theses_dir)
    if not tdir.is_dir():
        raise typer.BadParameter(f"theses-dir 가 디렉터리가 아니다: {tdir}")
    if asof:
        asof_d = asof_or_today(asof)
    else:
        try:
            asof_d = parse_date(tdir.name)
        except ValueError:
            asof_d = date.today()
    p = paths()
    report = ingest_round(
        tdir,
        asof=asof_d,
        scan_dir=Path(scan) if scan else None,
        journal_dir=Path(journal) if journal else journal_dir(REPO_ROOT),
        rejections_path=p.rejections,
        watchlist_path=p.watchlist,
        write=not dry_run,
    )
    typer.echo(report.render())
    if report.n_rejected_blocked or report.count("unknown_status"):
        raise typer.Exit(code=1)


@ops_app.command("reproduce")
@cli_guard
def ops_reproduce(
    scan_date: str = typer.Argument(..., help="YYYY-MM-DD 또는 state/scans/<date>/ 경로"),
    show: bool = typer.Option(False, "--show", help="재생성 리포트 전문 출력"),
) -> None:
    """저장된 스냅샷만으로 리포트를 재생성하고 보관본과 대조한다 (재계산 없음)."""
    from msa.ops.reproduce import reproduce

    d = Path(scan_date)
    if not d.exists():
        d = paths().scans / scan_date
    r = reproduce(d)
    if show:
        typer.echo(r.rendered)
        typer.echo("")
    typer.echo(f"{r.scan_dir}: 재생성 == 보관본 → {r.identical}")
    if not r.identical:
        for line in r.diff_lines()[:60]:
            typer.echo(line)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
