"""`msa` CLI.

도는 것: `data status`·`data audit`·`data fred-lag`·`data fred-fetch`(M1·M4) · `scan`(M3) ·
`backtest l1`(M3.5) · `macro`(M4) · `picks`(M5) · `portfolio`(M6) · `research`(M7) ·
`check`·`journal *`·`ops *`(M8).
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
        "macro-sector-agent — 거시 → 산업 사이클 → 테마 → 종목 → 포트폴리오 "
        "(M1~M8: 데이터·L1 스캐너·L2 거시 DAG·L4·L5·L3·운영)"
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
            state = "적재됨" if s.loaded else "미적재 (0행)"
            typer.echo(
                f"{s.name:<14}{_fmt(s.rows):>14}{_fmt(s.tickers):>10}  "
                f"{s.start or '—'!s:<12}{s.end or '—'!s:<12}  {state}"
            )

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
    typer.echo("FRED")
    typer.echo(f"  대상 시리즈   : {len(fred.ALL_SERIES)}종 (docs/08 §6.3 의 '24종')")
    try:
        from msa.config import fred_api_key

        fred_api_key()
        typer.echo("  API 키        : 있음 — `msa data fred-lag` 로 발표지연을 실측해라")
    except MissingApiKey as e:
        typer.echo(f"  API 키        : 없음 — {type(e).__name__}")
        typer.echo("  → §3 표의 `발표지연`·`개정` 열은 아직 실측되지 않았다 (M1 미완료 항목)")


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
    """FRED 시리즈의 발표 지연·개정 실측 — `docs/08` §3 표의 두 열을 채우는 명령."""
    from msa.data.fred import ALL_SERIES, FredClient

    _setup_logging(verbose)
    with FredClient() as client:
        rows = client.measure_all(vintage_date=vintage or None)
    for r in rows:
        typer.echo("  " + r.row())
    typer.echo(f"\n{len(rows)}/{len(ALL_SERIES)} 시리즈 실측 완료")


@app.command()
@cli_guard
def scan(
    asof: str = typer.Option(
        "", help="기준일 YYYY-MM-DD (그 이전 마지막 월말). 기본 = 스토어 최종일"
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
    typer.echo(
        f"미분류 시총 비율: {m['unclassified_mcap']['share']:.3%} · "
        f"소표본 {len(m['small_sample_buckets'])}개"
    )
    ph = m["physical"]
    typer.echo(
        f"축 1: 선언 {ph['declared']} · 데이터 있음 {ph['data_ok']} · "
        f"없음 {ph['data_missing']} · CPI {ph['cpi']}"
    )
    _echo_saved(res.out_dir)


@data_app.command("fred-fetch")
@cli_guard
def data_fred_fetch(
    force: bool = typer.Option(False, "--force", help="이미 캐시된 시리즈도 다시 받는다"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L2 드라이버 24종 + 테마 physical_ref FRED 심볼 + CPIAUCSL 을 state/physical/fred/ 에 캐시.

    키(`FRED_API_KEY`)가 없으면 첫 시리즈에서 던진다. 실패한 시리즈는 이름을 전부 찍고 종료코드 1.
    """
    from msa.data.fred import ALL_SERIES
    from msa.l1.physical import CPI_SERIES, fetch_fred_to_cache, read_fred_cache
    from msa.themes import load_themes

    _setup_logging(verbose)
    want = [*ALL_SERIES, CPI_SERIES]
    try:
        themes = load_themes()
        want += [
            t.physical_ref.symbol
            for t in themes
            if t.physical_ref is not None and t.physical_ref.source == "fred"
        ]
    except Exception as e:  # themes.yaml 문제는 FRED 수집을 막지 않는다 — 그러나 알린다
        typer.echo(f"themes.yaml 을 읽지 못해 physical_ref 심볼은 건너뛴다: {e}")
    symbols = list(dict.fromkeys(want))
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
    """M3.6 — A(망각) 집계 구조 검정: S0(현행)·S1(절대 게이트)·S2(풀/타이밍 2단) 를 관문 0 과
    같은 규칙으로 (docs/12 §4, 사전 등록). 산출물: state/backtests/l1/<store_end>/structures_*.
    """
    from msa.l1.structures import render_structure_report, run_structures

    _setup_logging(verbose)
    res = run_structures(write=not no_write, force=force)
    typer.echo(render_structure_report(res))


@app.command()
@cli_guard
def macro(
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD (그 이전 마지막 월말). 기본 = 오늘"),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="FRED 를 받지 않는다 (캐시만)"),
    no_etf: bool = typer.Option(False, "--no-etf", help="ETF 벌크(GLD·CPER 프록시)를 읽지 않는다"),
    no_store: bool = typer.Option(
        False, "--no-store", help="DuckDB 스토어(hyperscaler_capex)를 읽지 않는다"
    ),
    no_write: bool = _no_write_option("state/macro/"),
    no_sign_check: bool = typer.Option(
        False, "--no-sign-check", help="엣지 부호 일치율 실측을 건너뛴다"
    ),
    doc_out: str = typer.Option(
        "", "--doc-out", help="부호 실측 문서를 이 경로에도 쓴다 (예: docs/macro-dag-sign-check.md)"
    ),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L2 거시 DAG — 드라이버 상태 · tailwind · 국면 4분면 · 모순 감사 · 부호 실측 (docs/03).

    산출물: state/macro/<date>/. 없는 드라이버는 이름으로 보고된다.
    """
    from msa.l2.runtime import render_report, run_macro

    _setup_logging(verbose)
    res = run_macro(
        asof=asof or None,
        allow_fetch=not no_fetch,
        allow_etf=not no_etf,
        allow_store=not no_store,
        write=not no_write,
        sign_check=not no_sign_check,
        doc_out=Path(doc_out) if doc_out else None,
    )
    typer.echo(render_report(res))
    _echo_saved(res.out_dir)


@app.command()
@cli_guard
def research(
    theme: str = typer.Argument(..., help="테마 id (state/themes.yaml)"),
    asof: str = typer.Option(
        "", help="기준일 YYYY-MM-DD — 그 이전 최신 스캔을 쓴다. 기본 = 최신 스캔"
    ),
    provider: str = typer.Option(
        "anthropic",
        "--provider",
        help="anthropic | mock | fixture. anthropic 은 ANTHROPIC_API_KEY 필요",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="MockProvider 로 경로만 검증 (저장도 한다 — 합성 표기)"
    ),
    no_write: bool = _no_write_option("state/theses/"),
    no_store: bool = typer.Option(
        False, "--no-store", help="DuckDB 구성원 재무 요약 생략 (경고로 표시)"
    ),
    macro: str = typer.Option(
        "", help="L2 거시 상태 JSON 경로 (기본 state/macro/latest.json 이 있으면 사용)"
    ),
    fixtures: str = typer.Option("", help="--provider fixture 의 루트 (기본 tests/fixtures/l3)"),
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
            macro_path=Path(macro) if macro else None,
            with_store=not no_store,
        )
    except InputsError as e:
        typer.echo(f"입력 오류: {e}", err=True)
        raise typer.Exit(code=1) from e
    prov = make_provider(kind, theme_id=theme, fixture_root=Path(fixtures) if fixtures else None)
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
    top: int = typer.Option(4, help="바벨 종목 수 (앵커 max(1, top//2) + 토크)"),
    no_write: bool = _no_write_option("state/picks/"),
    no_physical: bool = typer.Option(
        False,
        "--no-physical",
        help="상품가 탄력성(price_beta_hist) 계산 생략 — ETF 벌크 스캔 ~12초",
    ),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="FRED 를 받지 않는다 (캐시만)"),
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L4 종목 선정 — 3축(S·T·M)·하드 필터·바벨 (docs/06). 산출물: state/picks/<date>/<theme>/"""
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
    verbose: bool = OPT_VERBOSE,
) -> None:
    """L5 포트 구성 + 매매계획서 (docs/07). 산출물: state/portfolio/<date>/"""
    from msa.l5.plan import render_plan
    from msa.l5.run import cluster_caps_from_args, run_portfolio

    _setup_logging(verbose)
    res = run_portfolio(
        asof=asof or None,
        inputs_dir=inputs,
        cases_path=cases or None,
        capital_usd=capital if capital > 0 else None,
        cluster_caps=cluster_caps_from_args(cluster_cap),
        write=not no_write,
    )
    typer.echo(render_plan(res))
    _echo_saved(res.out_dir)


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
        res = deliver(report.alerts, report.out_dir, use_env=not no_send)
        typer.echo("")
        typer.echo(f"저장: {report.out_dir}  ·  알림 {len(report.alerts)}건 → {res.json_path.name}")
        typer.echo(
            f"텔레그램: {res.status}"
            + (
                " (MSA_TELEGRAM_TOKEN / MSA_TELEGRAM_CHAT_ID 둘 다 있어야 보낸다)"
                if res.status == "not_configured"
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
        macro_latest=p.macro_latest,
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
