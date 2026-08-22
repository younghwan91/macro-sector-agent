"""`msa` CLI.

도는 것: `data status`·`data audit`·`data fred-lag`(M1) · `scan`(M3) ·
`check` · `journal *` · `ops *`(M8 운영).
나머지(`macro`·`research`·`picks`·`portfolio`)는 `--help` 에는 나오되
호출하면 `NotImplementedError` 를 던진다 — 있는 척하는 스텁이 조용히 빈 결과를
내는 것보다 낫다 (`CLAUDE.md` §2).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import typer

from msa import __version__

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "macro-sector-agent — 거시 → 산업 사이클 → 테마 → 종목 → 포트폴리오 "
        "(M1~M3: 데이터·L1 스캐너 · M8: 운영)"
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
        f"`msa {name}` 는 아직 없다. 현재 구현 범위는 M1~M3 (데이터 계층 · L1 스캐너)이다. "
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


@app.command()
def macro() -> None:
    """L2 거시 국면 + 드라이버 상태. (미구현 — M4)"""
    _todo("macro", "docs/03-macro-dag.md")


@app.command()
def research(theme: str) -> None:
    """L3 에이전트 리서치 → thesis 객체. (미구현 — M5)"""
    _todo("research", "docs/05-agent-research.md")


@app.command()
def picks(theme: str) -> None:
    """L4 종목 랭킹. (미구현 — M6)"""
    _todo("picks", "docs/06-stock-selection.md")


@app.command()
def portfolio() -> None:
    """L5 포트 구성 + 매매계획. (미구현 — M7)"""
    _todo("portfolio", "docs/07-portfolio.md")


def _repo_root() -> Path:
    from msa.config import REPO_ROOT

    return REPO_ROOT


def _parse_date(s: str) -> date:
    return date.today() if not s.strip() else date.fromisoformat(s.strip())


# ---------------------------------------------------------------------------
# msa check
# ---------------------------------------------------------------------------


@app.command()
def check(
    asof: str = typer.Option("", help="기준일 YYYY-MM-DD (기본 오늘)"),
    daily: bool = typer.Option(False, "--daily", help="일간 — 무효화·사다리·TP·시간스탑 자동 확인"),
    weekly: bool = typer.Option(False, "--weekly", help="주간 — 전 항목 + manual 목록 (기본)"),
    no_write: bool = typer.Option(False, "--no-write", help="state/checks/ 에 저장하지 않는다"),
    no_send: bool = typer.Option(False, "--no-send", help="텔레그램을 보내지 않는다 (파일만)"),
    positions: str = typer.Option("", help="positions.yaml 경로 (기본 state/positions.yaml)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """보유 포지션의 트리거·무효화·Tier-2·사다리·시간스탑·TP 점검 (docs/09 §1).

    주문은 내지 않는다 (CLAUDE.md §8).
    """
    from msa.config import paths
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
    root = _repo_root()
    asof_d = _parse_date(asof)
    pos_path = Path(positions) if positions else p.state / "positions.yaml"
    out_root = None if no_write else p.state / "checks"
    tracker = RunTracker(LastRunStore(p.state / "checks" / "last_run.json"), key=f"check.{mode}")
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
def journal_template(
    type_: str = typer.Argument(..., metavar="TYPE", help="entry|check|add|tp|exit|reject"),
) -> None:
    """항목 YAML 골격을 출력한다 — 채워서 `msa journal new --from` 에 준다."""
    from msa.ops.journal import TEMPLATES

    if type_ not in TEMPLATES:
        raise typer.BadParameter(f"type ∈ {sorted(TEMPLATES)}")
    typer.echo(TEMPLATES[type_], nl=False)


@journal_app.command("new")
def journal_new(
    from_: str = typer.Option(..., "--from", help="항목 YAML 파일 (type 키로 종류 지정)"),
    suffix: str = typer.Option("", help="같은 날 같은 종류가 둘이면 파일명 접미사"),
    journal: str = typer.Option("", help="journal/ 경로 (기본 저장소 루트의 journal/)"),
) -> None:
    """저널 항목을 추가한다. 필수 필드가 비면 거부, 기존 파일은 덮어쓰지 않는다."""
    import yaml

    from msa.ops.journal import (
        IncompleteEntry,
        JournalImmutable,
        journal_dir,
        record_from_dict,
        write_record,
    )

    d = yaml.safe_load(Path(from_).read_text(encoding="utf-8"))
    if not isinstance(d, dict):
        raise typer.BadParameter("YAML 최상위가 dict 여야 한다")
    jdir = Path(journal) if journal else journal_dir(_repo_root())
    try:
        w = write_record(record_from_dict(d), jdir, suffix=suffix)
    except (IncompleteEntry, JournalImmutable) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"작성: {w.markdown}")
    if w.thesis_snapshot:
        typer.echo(f"스냅샷: {w.thesis_snapshot}")
    if w.diff_text:
        typer.echo("")
        typer.echo(w.diff_text)


@journal_app.command("verify")
def journal_verify(
    staged: bool = typer.Option(False, "--staged", help="인덱스만 본다 (pre-commit)"),
    repo: str = typer.Option("", help="저장소 루트 (기본 이 저장소)"),
) -> None:
    """커밋된 journal/ 파일이 수정·삭제됐으면 실패 (append-only, CLAUDE.md §6)."""
    from msa.ops.journal import verify_append_only

    root = Path(repo) if repo else _repo_root()
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
def journal_install_hook(
    force: bool = typer.Option(False, "--force", help="기존 pre-commit 훅을 덮어쓴다"),
    repo: str = typer.Option("", help="저장소 루트"),
) -> None:
    """.git/hooks/pre-commit 에 scripts/journal-precommit.sh 를 건다 (명시적 호출로만 설치)."""
    from msa.ops.journal import install_hook

    try:
        t = install_hook(Path(repo) if repo else _repo_root(), force=force)
    except FileExistsError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"설치: {t}")


@journal_app.command("diff")
def journal_diff(
    theme: str = typer.Argument(..., help="테마 id"),
    journal: str = typer.Option("", help="journal/ 경로"),
) -> None:
    """최근 두 thesis 스냅샷의 필드 단위 diff — 논지 표류 추적 (docs/05 §6)."""
    from msa.ops.journal import journal_dir, thesis_drift

    typer.echo(thesis_drift(Path(journal) if journal else journal_dir(_repo_root()), theme))


# ---------------------------------------------------------------------------
# msa ops
# ---------------------------------------------------------------------------


@ops_app.command("schedule")
def ops_schedule(
    print_cron: bool = typer.Option(False, "--print-cron", help="crontab 텍스트"),
    systemd: bool = typer.Option(False, "--systemd", help="systemd 타이머 텍스트"),
) -> None:
    """케이던스(docs/09 §1) → crontab/systemd 텍스트. 아무것도 설치하지 않는다."""
    from msa.ops.scheduler import cron_lines, systemd_units

    if systemd:
        typer.echo(systemd_units(_repo_root()))
    else:
        typer.echo(cron_lines(_repo_root()))


@ops_app.command("due")
def ops_due(
    cadence: str = typer.Argument(..., help="monthly|weekly|daily|quarterly"),
    asof: str = typer.Option("", help="기준일 (기본 오늘)"),
) -> None:
    """오늘이 그 케이던스의 실행일이면 0, 아니면 1 — cron 의 '1영업일' 게이트."""
    from msa.ops.scheduler import CADENCES, is_due

    if cadence not in CADENCES:
        raise typer.BadParameter(f"cadence ∈ {CADENCES}")
    d = _parse_date(asof)
    ok = is_due(cadence, d)
    typer.echo(f"{cadence} @ {d}: {'due' if ok else 'not due'}")
    raise typer.Exit(code=0 if ok else 1)


@ops_app.command("calibration")
def ops_calibration(
    journal: str = typer.Option("", help="journal/ 경로"),
    write: bool = typer.Option(
        True, "--write/--no-write", help="state/calibration/<date>.txt 저장"
    ),
) -> None:
    """cycle_confidence 캘리브레이션 (docs/10 §4). N<20 이면 '결론 없음' + 표본 나열."""
    import json

    from msa.config import paths
    from msa.ops.calibration import run, to_json
    from msa.ops.journal import journal_dir

    text, cals = run(Path(journal) if journal else journal_dir(_repo_root()))
    typer.echo(text)
    if write:
        out = paths().state / "calibration"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{date.today().isoformat()}.txt").write_text(text, encoding="utf-8")
        (out / f"{date.today().isoformat()}.json").write_text(
            json.dumps(to_json(cals), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        typer.echo(f"저장: {out}")


@ops_app.command("rejections-update")
def ops_rejections_update(
    asof: str = typer.Option("", help="기준일 (기본 오늘)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="파일을 쓰지 않는다"),
) -> None:
    """기각 대장 r_12m/r_24m 갱신 + 세 질문 집계 → state/rejections-summary.md (내부 기록)."""
    from msa.config import paths
    from msa.ops.journal import journal_dir
    from msa.ops.rejections import load_axis1_monthly, load_theme_index, summarize
    from msa.ops.state_files import load_rejections, save_rejections

    p = paths()
    asof_d = _parse_date(asof)
    rows = load_rejections(p.state / "rejections.yaml")
    if not rows:
        typer.echo("기각 대장이 비어 있다 (state/rejections.yaml) — 월간 스캔이 행을 적재해야 한다")
    cache = p.state / "cache"
    index = load_theme_index(cache)
    summary = summarize(
        rows,
        index=index,
        axis1=load_axis1_monthly(cache),
        jdir=journal_dir(_repo_root()),
        scans_dir=p.state / "scans",
        asof=asof_d,
    )
    typer.echo(summary.text)
    if not dry_run:
        save_rejections(p.state / "rejections.yaml", summary.updated_rows)
        (p.state / "rejections-summary.md").write_text(summary.text, encoding="utf-8")
        typer.echo(
            f"갱신: r_12m {summary.n_filled_12m}개 · r_24m {summary.n_filled_24m}개 → "
            f"{p.state / 'rejections.yaml'}"
        )


@ops_app.command("reproduce")
def ops_reproduce(
    scan_date: str = typer.Argument(..., help="YYYY-MM-DD 또는 state/scans/<date>/ 경로"),
    show: bool = typer.Option(False, "--show", help="재생성 리포트 전문 출력"),
) -> None:
    """저장된 스냅샷만으로 리포트를 재생성하고 보관본과 대조한다 (재계산 없음)."""
    from msa.config import paths
    from msa.ops.reproduce import reproduce

    d = Path(scan_date)
    if not d.exists():
        d = paths().state / "scans" / scan_date
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
