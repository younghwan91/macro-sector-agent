"""`msa` CLI.

도는 것: `data status`·`data audit`·`data fred-lag`·`data fred-fetch`(M1·M4) · `scan`(M3) ·
`macro`(M4) · `picks`(M5) · `portfolio`(M6) · `research`(M7).
나머지(`check`)는 `--help` 에는 나오되
호출하면 `NotImplementedError` 를 던진다 — 있는 척하는 스텁이 조용히 빈 결과를
내는 것보다 낫다 (`CLAUDE.md` §2).
"""

from __future__ import annotations

import logging
import os
from datetime import date

import typer

from msa import __version__

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "macro-sector-agent — 거시 → 산업 사이클 → 테마 → 종목 → 포트폴리오 "
        "(M1~M7: 데이터·L1 스캐너·L2 거시 DAG·L4 종목 선정·L5 포트·L3 리서치)"
    ),
)
data_app = typer.Typer(no_args_is_help=True, help="L0 데이터 — 스토어 상태와 커버리지 감사")
app.add_typer(data_app, name="data")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _fmt(n: int | None) -> str:
    return "—" if n is None else f"{n:,}"


@app.command()
def version() -> None:
    """버전."""
    typer.echo(f"msa {__version__}")


@data_app.command("status")
def data_status(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    etf: str = typer.Option(
        "", "--etf", help="쉼표로 구분한 ETF 티커. 벌크 funds.csv.zip 을 1회 스캔한다(~12초)."
    ),
) -> None:
    """전 소스의 최신 시점·행수·결측률. (M1 완료 판정 항목)"""
    from msa.config import paths
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
    except Exception as e:
        typer.echo(f"  API 키        : 없음 — {type(e).__name__}")
        typer.echo("  → §3 표의 `발표지연`·`개정` 열은 아직 실측되지 않았다 (M1 미완료 항목)")


@data_app.command("audit")
def data_audit(
    start: str = typer.Option("2010-01-01", help="폐지 종목 포함 감사 구간 시작"),
    end: str = typer.Option(str(date.today()), help="감사 구간 끝"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
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
        cov = audit_delisted_included(store, start, end)
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
def data_fred_lag(
    vintage: str = typer.Option(
        "", help="ALFRED 빈티지 날짜(YYYY-MM-DD). 주면 개정 여부까지 판정한다"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """FRED 시리즈의 발표 지연·개정 실측 — `docs/08` §3 표의 두 열을 채우는 명령."""
    from msa.data.fred import ALL_SERIES, FredClient

    _setup_logging(verbose)
    with FredClient() as client:
        rows = client.measure_all(vintage_date=vintage or None)
    for r in rows:
        typer.echo("  " + r.row())
    typer.echo(f"\n{len(rows)}/{len(ALL_SERIES)} 시리즈 실측 완료")


def _todo(name: str, doc: str) -> None:
    raise NotImplementedError(
        f"`msa {name}` 는 아직 없다. 현재 구현 범위는 M1~M4 "
        "(데이터 계층 · L1 스캐너 · L2 거시 DAG)이다. "
        f"설계: {doc}"
    )


@app.command()
def scan(
    asof: str = typer.Option(
        "", help="기준일 YYYY-MM-DD (그 이전 마지막 월말). 기본 = 스토어 최종일"
    ),
    top: int = typer.Option(0, help="표에 보일 상위 N (0 = 전부)"),
    force: bool = typer.Option(False, "--force", help="패널·재무·지표 캐시를 무시하고 다시 만든다"),
    no_write: bool = typer.Option(False, "--no-write", help="state/scans/ 에 저장하지 않는다"),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="FRED 를 받지 않는다 (캐시만)"),
    no_vcp: bool = typer.Option(False, "--no-vcp", help="vcp_index 계산 생략 (빠른 확인용)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
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
    if res.out_dir:
        typer.echo(f"저장: {res.out_dir}")


@data_app.command("fred-fetch")
def data_fred_fetch(
    force: bool = typer.Option(False, "--force", help="이미 캐시된 시리즈도 다시 받는다"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
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
            if type(e).__name__ == "MissingApiKey":
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


@app.command()
def macro(
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD (그 이전 마지막 월말). 기본 = 오늘"),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="FRED 를 받지 않는다 (캐시만)"),
    no_etf: bool = typer.Option(False, "--no-etf", help="ETF 벌크(GLD·CPER 프록시)를 읽지 않는다"),
    no_store: bool = typer.Option(
        False, "--no-store", help="DuckDB 스토어(hyperscaler_capex)를 읽지 않는다"
    ),
    no_write: bool = typer.Option(False, "--no-write", help="state/macro/ 에 저장하지 않는다"),
    no_sign_check: bool = typer.Option(
        False, "--no-sign-check", help="엣지 부호 일치율 실측을 건너뛴다"
    ),
    doc_out: str = typer.Option(
        "", "--doc-out", help="부호 실측 문서를 이 경로에도 쓴다 (예: docs/macro-dag-sign-check.md)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """L2 거시 DAG — 드라이버 상태 · tailwind · 국면 4분면 · 모순 감사 · 부호 실측 (docs/03).

    산출물: state/macro/<date>/. 없는 드라이버는 이름으로 보고된다.
    """
    from pathlib import Path

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
    if res.out_dir:
        typer.echo(f"저장: {res.out_dir}")


@app.command()
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
    no_write: bool = typer.Option(False, "--no-write", help="state/theses/ 에 저장하지 않는다"),
    no_store: bool = typer.Option(
        False, "--no-store", help="DuckDB 구성원 재무 요약 생략 (경고로 표시)"
    ),
    macro: str = typer.Option(
        "", help="L2 거시 상태 JSON 경로 (기본 state/macro/latest.json 이 있으면 사용)"
    ),
    fixtures: str = typer.Option("", help="--provider fixture 의 루트 (기본 tests/fixtures/l3)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """L3 에이전트 리서치 (supply · catalyst · bear · referee) → thesis 객체 (docs/05).

    산출물: state/theses/<date>/<theme>.thesis.yaml · <theme>.report.md · rejections-pending.yaml ·
    contested.json.
    스키마 미달이면 저장하지 않고 종료 코드 2. 게이트 기각은 저장한다 (docs/05 §4).
    """
    from pathlib import Path

    from msa.config import paths
    from msa.l3.contracts import InputsError, assemble_inputs
    from msa.l3.pipeline import run_research
    from msa.l3.providers import ProviderError, make_provider
    from msa.l3.schema import ThesisRejected

    _setup_logging(verbose)
    kind = "mock" if dry_run else provider
    state = paths().state
    try:
        inputs = assemble_inputs(
            theme,
            state_dir=state,
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
        res = run_research(inputs, prov, theses_root=state / "theses", write=not no_write)
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
def picks(
    theme: str,
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD. 기본 = 스토어 최종일"),
    top: int = typer.Option(4, help="바벨 종목 수 (앵커 max(1, top//2) + 토크)"),
    no_write: bool = typer.Option(False, "--no-write", help="state/picks/ 에 저장하지 않는다"),
    no_physical: bool = typer.Option(
        False,
        "--no-physical",
        help="상품가 탄력성(price_beta_hist) 계산 생략 — ETF 벌크 스캔 ~12초",
    ),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="FRED 를 받지 않는다 (캐시만)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
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
    if res.out_dir:
        typer.echo(f"저장: {res.out_dir}")


@app.command()
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
    no_write: bool = typer.Option(False, "--no-write", help="state/portfolio/ 에 저장하지 않는다"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
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
    if res.out_dir:
        typer.echo(f"저장: {res.out_dir}")


@app.command()
def check() -> None:
    """주간 트리거/무효화 점검. (미구현 — M8)"""
    _todo("check", "docs/09-operations.md")


if __name__ == "__main__":
    app()
