from __future__ import annotations

import asyncio
import json
import platform
import sys
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from stonks_cli.commands import (
    do_analyze,
    do_analyze_artifacts,
    do_backtest,
    do_backtest_artifacts,
    do_bench,
    do_chart,
    do_chart_compare,
    do_chart_rsi,
    do_config_init,
    do_config_set,
    do_config_show,
    do_config_validate,
    do_config_where,
    do_correlation,
    do_data_cache_info,
    do_data_fetch,
    do_data_purge,
    do_data_verify,
    do_doctor,
    do_earnings,
    do_fundamentals,
    do_history_list,
    do_history_show,
    do_insider,
    do_news,
    do_plugins_list,
    do_polymarket_book,
    do_polymarket_emergency_stop,
    do_polymarket_guard_status,
    do_polymarket_journal,
    do_polymarket_market_get,
    do_polymarket_markets_list,
    do_polymarket_paper_buy,
    do_polymarket_paper_init,
    do_polymarket_paper_sell,
    do_polymarket_paper_status,
    do_polymarket_preflight,
    do_polymarket_replay_market,
    do_polymarket_replay_user,
    do_polymarket_research_list,
    do_polymarket_research_thesis,
    do_polymarket_runtime_halt,
    do_polymarket_runtime_loop,
    do_polymarket_runtime_once,
    do_polymarket_runtime_resume,
    do_polymarket_runtime_soak,
    do_polymarket_runtime_status,
    do_polymarket_rust_ping,
    do_polymarket_rust_replay,
    do_polymarket_rust_status,
    do_polymarket_rust_test,
    do_polymarket_scan,
    do_polymarket_settle,
    do_polymarket_wallet_market_signals,
    do_polymarket_wallet_targets,
    do_polymarket_wallets_import,
    do_polymarket_wallets_rank,
    do_portfolio_add,
    do_portfolio_allocation,
    do_portfolio_history,
    do_portfolio_optimize,
    do_portfolio_remove,
    do_portfolio_show,
    do_quick,
    do_report_latest,
    do_report_open,
    do_report_view,
    do_research_list,
    do_research_log,
    do_research_search,
    do_schedule_once,
    do_schedule_run,
    do_schedule_status,
    do_sector,
    do_signals_diff,
    do_version,
    do_watchlist_analyze,
    do_watchlist_list,
    do_watchlist_remove,
    do_watchlist_set,
)
from stonks_cli.errors import ExitCodes, StonksError
from stonks_cli.logging_utils import LoggingConfig, configure_logging, log_suppressed_exception
from stonks_cli.whalemirror.attribution import (
    DEFAULT_ATTRIBUTION_FIXTURE,
    rank_wallets_from_fixture,
    render_wallet_ranking_markdown,
)
from stonks_cli.whalemirror.hyperliquid import HYPERLIQUID_WS_URL
from stonks_cli.whalemirror.ingestion import (
    DEFAULT_CAPTURE_FIXTURE,
    DEFAULT_LIVE_CAPTURE_COINS,
    DEFAULT_LIVE_CAPTURE_SECONDS,
    build_live_capture_subscriptions,
    capture_hyperliquid_to_files,
    replay_capture_fixture,
    runtime_host_metadata,
    write_capture_jsonl,
)
from stonks_cli.whalemirror.ledger import (
    DEFAULT_LEDGER_PATH,
    DEFAULT_REPLAY_FIXTURE,
    DEFAULT_TEARSHEET_PATH,
    write_fixture_artifacts,
)
from stonks_cli.whalemirror.paper_mirror import (
    DEFAULT_PAPER_MIRROR_FIXTURE,
    PaperMirrorConfig,
    replay_paper_mirror_fixture,
)
from stonks_cli.whalemirror.validation_gates import (
    CAPTURE_GATE,
    DEFAULT_LIVE_VALIDATION_FIXTURE,
    LIVE_GATE,
    PAPER_GATE,
    assess_gate,
    default_validation_dir,
    gate_state_path,
    load_gate_state,
    record_capture_health,
    record_capture_probe,
    record_live_probe,
    record_paper_probe,
    render_gate_report,
    write_gate_report,
)

app = typer.Typer(add_completion=True, help="WhaleMirror Hyperliquid paper-first observability CLI.")
config_app = typer.Typer()
schedule_app = typer.Typer()
data_app = typer.Typer()
report_app = typer.Typer()
history_app = typer.Typer()
plugins_app = typer.Typer()
watchlist_app = typer.Typer()
signals_app = typer.Typer()
portfolio_app = typer.Typer()
research_app = typer.Typer(help="Legacy research notes and searchable thesis history.")
paper_app = typer.Typer(help="Legacy stock paper trading commands.")
alert_app = typer.Typer()
dividend_app = typer.Typer()
polymarket_app = typer.Typer(help="Historical Polymarket commands retained for migration reference.")
whalemirror_app = typer.Typer(help="WhaleMirror Hyperliquid paper-first commands.")
whalemirror_gates_app = typer.Typer(help="Restartable validation gate harnesses.")
whalemirror_ingest_app = typer.Typer(help="Hyperliquid ingestion fixture and capture commands.")
whalemirror_paper_app = typer.Typer(help="Paper mirror replay and risk-control commands.")
whalemirror_wallets_app = typer.Typer(help="Venue-neutral wallet attribution commands.")
polymarket_markets_app = typer.Typer()
polymarket_runtime_app = typer.Typer()
polymarket_wallets_app = typer.Typer()
polymarket_paper_app = typer.Typer()
polymarket_replay_app = typer.Typer()
polymarket_research_app = typer.Typer()
polymarket_rust_app = typer.Typer()

app.add_typer(config_app, name="config")
app.add_typer(whalemirror_app, name="whalemirror")
# legacy/dead-weight equity surface, hidden from --help but kept for tests
app.add_typer(data_app, name="data", hidden=True)
app.add_typer(report_app, name="report", hidden=True)
app.add_typer(history_app, name="history", hidden=True)
app.add_typer(research_app, name="research", hidden=True)
app.add_typer(polymarket_app, name="polymarket", hidden=True)
app.add_typer(schedule_app, name="schedule", hidden=True)
app.add_typer(plugins_app, name="plugins", hidden=True)
app.add_typer(watchlist_app, name="watchlist", hidden=True)
app.add_typer(signals_app, name="signals", hidden=True)
app.add_typer(portfolio_app, name="portfolio", hidden=True)
app.add_typer(paper_app, name="paper", hidden=True)
app.add_typer(alert_app, name="alert", hidden=True)
app.add_typer(dividend_app, name="dividend", hidden=True)
whalemirror_app.add_typer(whalemirror_gates_app, name="gates")
whalemirror_app.add_typer(whalemirror_ingest_app, name="ingest")
whalemirror_app.add_typer(whalemirror_paper_app, name="paper")
whalemirror_app.add_typer(whalemirror_wallets_app, name="wallets")
polymarket_app.add_typer(polymarket_markets_app, name="markets")
polymarket_app.add_typer(polymarket_runtime_app, name="runtime")
polymarket_app.add_typer(polymarket_wallets_app, name="wallets")
polymarket_app.add_typer(polymarket_paper_app, name="paper")
polymarket_app.add_typer(polymarket_replay_app, name="replay")
polymarket_app.add_typer(polymarket_research_app, name="research")
polymarket_app.add_typer(polymarket_rust_app, name="rust")


@app.callback()
def _global_options(
    verbose: int = typer.Option(0, "--verbose", "-v", count=True, help="Increase logging verbosity"),
    quiet: bool = typer.Option(False, "--quiet", help="Only show errors"),
    structured_logs: bool = typer.Option(False, "--structured-logs", help="Emit JSON lines logs to stderr"),
) -> None:
    configure_logging(LoggingConfig(verbose=verbose, quiet=quiet, structured=structured_logs))


def _exit_for_error(e: Exception) -> typer.Exit:
    if isinstance(e, StonksError):
        Console().print(f"[red]Error:[/red] {e}")
        return typer.Exit(code=e.code)
    if isinstance(e, ValidationError):
        Console().print(f"[red]Bad config:[/red] {e}")
        return typer.Exit(code=ExitCodes.BAD_CONFIG)
    if isinstance(e, (FileNotFoundError, IndexError, ValueError)):
        Console().print(f"[red]Error:[/red] {e}")
        return typer.Exit(code=ExitCodes.USAGE_ERROR)
    Console().print(f"[red]Error:[/red] {e}")
    return typer.Exit(code=ExitCodes.UNKNOWN_ERROR)


@app.command()
def version() -> None:
    """Print version."""
    try:
        Console().print(do_version())
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def doctor() -> None:
    """Diagnose the local WhaleMirror environment."""
    try:
        results = do_doctor()
        console = Console()
        score_raw = results.get("health_score")
        if score_raw is not None:
            try:
                score = int(score_raw)
            except Exception:
                score = 0
            color = "green" if score >= 85 else "yellow" if score >= 60 else "red"
            console.print(f"health_score: [{color}]{score}[/]")

        for k in sorted(results.keys()):
            if k == "health_score":
                continue
            console.print(f"{k}: {results[k]}")
    except Exception as e:
        raise _exit_for_error(e)


@whalemirror_app.command("ledger-demo")
def whalemirror_ledger_demo(
    fixture: Path = typer.Option(DEFAULT_REPLAY_FIXTURE, "--fixture", exists=True, readable=True),
    ledger: Path = typer.Option(DEFAULT_LEDGER_PATH, "--ledger"),
    tearsheet: Path = typer.Option(DEFAULT_TEARSHEET_PATH, "--tearsheet"),
) -> None:
    """Generate the fixture-backed public ledger and tearsheet."""
    try:
        result = write_fixture_artifacts(fixture_path=fixture, ledger_path=ledger, tearsheet_path=tearsheet)
        Console().print(json.dumps(result, indent=2, sort_keys=True))
    except Exception as e:
        raise _exit_for_error(e)


@whalemirror_ingest_app.command("replay")
def whalemirror_ingest_replay(
    fixture: Path = typer.Option(DEFAULT_CAPTURE_FIXTURE, "--fixture", exists=True, readable=True),
    out: Path | None = typer.Option(None, "--out", help="Optional JSONL path for normalized trades"),
) -> None:
    """Decode a Hyperliquid websocket fixture into normalized trades."""
    try:
        trades, health = replay_capture_fixture(fixture)
        if out is not None:
            write_capture_jsonl(trades, out)
        Console().print_json(
            json.dumps(
                {
                    "fixture_path": str(fixture),
                    "out_path": str(out) if out else None,
                    "health": health.to_dict(),
                    "trades": [trade.to_dict() for trade in trades],
                }
            )
        )
    except Exception as e:
        raise _exit_for_error(e)


@whalemirror_ingest_app.command("run")
def whalemirror_ingest_run(
    coins: list[str] = typer.Option(None, "--coin", help="Repeatable Hyperliquid trade coin, e.g. BTC or @107"),
    user_fill_wallets: list[str] = typer.Option(None, "--user-fill-wallet", help="Repeatable wallet for userFills"),
    user_funding_wallets: list[str] = typer.Option(
        None, "--user-funding-wallet", help="Repeatable wallet for userFundings"
    ),
    all_mids: bool = typer.Option(True, "--all-mids/--no-all-mids", help="Include allMids; first dex includes spot mids"),
    all_mids_dex: str | None = typer.Option(None, "--all-mids-dex", help="Optional allMids dex selector"),
    duration_seconds: float = typer.Option(float(DEFAULT_LIVE_CAPTURE_SECONDS), "--duration-seconds", min=1.0),
    raw_out: Path = typer.Option(Path(".cache/whalemirror-gates/captures/hyperliquid-raw.jsonl"), "--raw-out"),
    out: Path = typer.Option(Path(".cache/whalemirror-gates/captures/hyperliquid-normalized.jsonl"), "--out"),
    health: Path = typer.Option(Path(".cache/whalemirror-gates/reports/capture-health.json"), "--health"),
    state_dir: Path = typer.Option(default_validation_dir(), "--state-dir"),
    report: Path = typer.Option(Path(".cache/whalemirror-gates/reports/capture-gate.md"), "--report"),
    ws_url: str = typer.Option(HYPERLIQUID_WS_URL, "--ws-url"),
    heartbeat_seconds: float = typer.Option(30.0, "--heartbeat-seconds", min=1.0),
    health_interval_seconds: float = typer.Option(300.0, "--health-interval-seconds", min=1.0),
    max_reconnects: int | None = typer.Option(None, "--max-reconnects", min=0),
    stop_after_messages: int | None = typer.Option(None, "--stop-after-messages", min=1),
    reset: bool = typer.Option(False, "--reset", help="Start a fresh #13 gate state before recording evidence"),
    allow_non_linux: bool = typer.Option(False, "--allow-non-linux", help="Development-only override for Mac/Windows"),
) -> None:
    """Run a live Hyperliquid websocket capture for the #13 Linux validation gate."""
    if not allow_non_linux and platform.system().lower() != "linux":
        raise _exit_for_error(
            ValueError(
                "live WhaleMirror validation captures must run on the always-on Linux host; "
                "use --allow-non-linux only for development smoke tests"
            )
        )

    subscriptions = build_live_capture_subscriptions(
        coins=tuple(coins or DEFAULT_LIVE_CAPTURE_COINS),
        user_fill_wallets=tuple(user_fill_wallets or ()),
        user_funding_wallets=tuple(user_funding_wallets or ()),
        include_all_mids=all_mids,
        all_mids_dex=all_mids_dex,
    )
    latest_state = None
    first_evidence = True

    async def record_progress(payload: dict[str, object]) -> None:
        nonlocal first_evidence, latest_state
        latest_state = record_capture_health(
            state_dir=state_dir,
            capture_payload=dict(payload),
            reset=reset and first_evidence,
        )
        first_evidence = False
        write_gate_report(latest_state, report_path=report)

    try:
        result = asyncio.run(
            capture_hyperliquid_to_files(
                subscriptions=subscriptions,
                raw_out_path=raw_out,
                trades_out_path=out,
                health_out_path=health,
                duration_seconds=duration_seconds,
                ws_url=ws_url,
                heartbeat_seconds=heartbeat_seconds,
                health_interval_seconds=health_interval_seconds,
                max_reconnects=max_reconnects,
                stop_after_messages=stop_after_messages,
                progress_handler=record_progress,
            )
        )
        if latest_state is None:
            latest_state = record_capture_health(state_dir=state_dir, capture_payload=result, reset=reset)
            write_gate_report(latest_state, report_path=report)
        Console().print_json(
            json.dumps(
                {
                    "state_path": str(gate_state_path(CAPTURE_GATE, state_dir=state_dir)),
                    "report_path": str(report),
                    "raw_out_path": str(raw_out),
                    "out_path": str(out),
                    "health_path": str(health),
                    "assessment": assess_gate(latest_state).to_dict(),
                    "latest_evidence": latest_state.evidence[-1].to_dict(),
                }
            )
        )
    except Exception as e:
        interrupted = {
            "source": "live_capture",
            "final_status": "interrupted",
            "error": str(e),
            "ws_url": ws_url,
            "subscriptions": subscriptions,
            "raw_out_path": str(raw_out),
            "capture_out_path": str(out),
            "health_out_path": str(health),
            "runtime": runtime_host_metadata(),
            "health": {},
        }
        state = record_capture_health(state_dir=state_dir, capture_payload=interrupted, reset=reset and first_evidence)
        write_gate_report(state, report_path=report)
        raise _exit_for_error(e)


@whalemirror_wallets_app.command("rank")
def whalemirror_wallets_rank(
    fixture: Path = typer.Option(DEFAULT_ATTRIBUTION_FIXTURE, "--fixture", exists=True, readable=True),
    limit: int = typer.Option(100, "--limit", min=1, max=1000),
    markdown: bool = typer.Option(False, "--markdown", help="Render a markdown ranking table instead of JSON"),
) -> None:
    """Rank wallets from reproducible trade-outcome and funding fixtures."""
    try:
        rankings = rank_wallets_from_fixture(fixture, limit=limit)
        if markdown:
            Console().print(render_wallet_ranking_markdown(rankings))
        else:
            Console().print_json(
                json.dumps(
                    {
                        "fixture_path": str(fixture),
                        "rankings": [ranking.to_dict() for ranking in rankings],
                    }
                )
            )
    except Exception as e:
        raise _exit_for_error(e)


@whalemirror_paper_app.command("replay")
def whalemirror_paper_replay(
    fixture: Path = typer.Option(DEFAULT_PAPER_MIRROR_FIXTURE, "--fixture", exists=True, readable=True),
    rankings_fixture: Path = typer.Option(DEFAULT_ATTRIBUTION_FIXTURE, "--rankings-fixture", exists=True, readable=True),
    bankroll: float = typer.Option(1000.0, "--bankroll", min=0.0),
    max_position_fraction: float = typer.Option(0.10, "--max-position-fraction", min=0.0, max=1.0),
    max_order_notional: float = typer.Option(75.0, "--max-order-notional", min=0.0),
    stop_loss_pct: float = typer.Option(0.08, "--stop-loss-pct", min=0.0, max=1.0),
    cooldown_minutes: float = typer.Option(60.0, "--cooldown-minutes", min=0.0),
) -> None:
    """Replay paper mirror decisions with size-down, stop-loss, and cooldown controls."""
    try:
        rankings = rank_wallets_from_fixture(rankings_fixture, limit=5)
        replay = replay_paper_mirror_fixture(
            fixture_path=fixture,
            rankings=rankings,
            config=PaperMirrorConfig(
                follower_bankroll_usd=bankroll,
                max_position_fraction=max_position_fraction,
                max_order_notional_usd=max_order_notional,
                stop_loss_pct=stop_loss_pct,
                cooldown_minutes=cooldown_minutes,
            ),
        )
        Console().print_json(
            json.dumps(
                {
                    "fixture_path": str(fixture),
                    "rankings_fixture": str(rankings_fixture),
                    "tearsheet": replay.tearsheet,
                    "decisions": [decision.ledger_record.to_dict() for decision in replay.decisions],
                    "execution_intents": [
                        decision.intent.to_dict() for decision in replay.decisions if decision.intent is not None
                    ],
                }
            )
        )
    except Exception as e:
        raise _exit_for_error(e)


@whalemirror_gates_app.command("capture-sample")
def whalemirror_gates_capture_sample(
    fixture: Path = typer.Option(DEFAULT_CAPTURE_FIXTURE, "--fixture", exists=True, readable=True),
    state_dir: Path = typer.Option(default_validation_dir(), "--state-dir"),
    capture_out_dir: Path = typer.Option(Path(".cache/whalemirror-gates/captures"), "--capture-out-dir"),
    report: Path = typer.Option(Path(".cache/whalemirror-gates/capture-gate.md"), "--report"),
    reset: bool = typer.Option(False, "--reset", help="Start a fresh gate state before recording this sample"),
) -> None:
    """Record a restartable #13 capture-health sample."""
    try:
        state = record_capture_probe(
            state_dir=state_dir,
            fixture_path=fixture,
            capture_out_dir=capture_out_dir,
            reset=reset,
        )
        write_gate_report(state, report_path=report)
        Console().print_json(
            json.dumps(
                {
                    "state_path": str(gate_state_path(CAPTURE_GATE, state_dir=state_dir)),
                    "report_path": str(report),
                    "assessment": assess_gate(state).to_dict(),
                    "latest_evidence": state.evidence[-1].to_dict(),
                }
            )
        )
    except Exception as e:
        raise _exit_for_error(e)


@whalemirror_gates_app.command("paper-sample")
def whalemirror_gates_paper_sample(
    fixture: Path = typer.Option(DEFAULT_PAPER_MIRROR_FIXTURE, "--fixture", exists=True, readable=True),
    rankings_fixture: Path = typer.Option(DEFAULT_ATTRIBUTION_FIXTURE, "--rankings-fixture", exists=True, readable=True),
    state_dir: Path = typer.Option(default_validation_dir(), "--state-dir"),
    report: Path = typer.Option(Path(".cache/whalemirror-gates/paper-gate.md"), "--report"),
    bankroll: float = typer.Option(1000.0, "--bankroll", min=0.0),
    max_position_fraction: float = typer.Option(0.10, "--max-position-fraction", min=0.0, max=1.0),
    max_order_notional: float = typer.Option(75.0, "--max-order-notional", min=0.0),
    reset: bool = typer.Option(False, "--reset", help="Start a fresh gate state before recording this sample"),
) -> None:
    """Record a restartable #14 paper-mirror gate sample."""
    try:
        state = record_paper_probe(
            state_dir=state_dir,
            fixture_path=fixture,
            rankings_fixture=rankings_fixture,
            config=PaperMirrorConfig(
                follower_bankroll_usd=bankroll,
                max_position_fraction=max_position_fraction,
                max_order_notional_usd=max_order_notional,
            ),
            reset=reset,
        )
        write_gate_report(state, report_path=report)
        Console().print_json(
            json.dumps(
                {
                    "state_path": str(gate_state_path(PAPER_GATE, state_dir=state_dir)),
                    "report_path": str(report),
                    "assessment": assess_gate(state).to_dict(),
                    "latest_evidence": state.evidence[-1].to_dict(),
                }
            )
        )
    except Exception as e:
        raise _exit_for_error(e)


@whalemirror_gates_app.command("live-sample")
def whalemirror_gates_live_sample(
    fixture: Path = typer.Option(DEFAULT_LIVE_VALIDATION_FIXTURE, "--fixture", exists=True, readable=True),
    state_dir: Path = typer.Option(default_validation_dir(), "--state-dir"),
    report: Path = typer.Option(Path(".cache/whalemirror-gates/live-gate.md"), "--report"),
    reset: bool = typer.Option(False, "--reset", help="Start a fresh gate state before recording this sample"),
) -> None:
    """Record a restartable #10 latency, slippage, and scale-gate sample."""
    try:
        state = record_live_probe(state_dir=state_dir, fixture_path=fixture, reset=reset)
        write_gate_report(state, report_path=report)
        Console().print_json(
            json.dumps(
                {
                    "state_path": str(gate_state_path(LIVE_GATE, state_dir=state_dir)),
                    "report_path": str(report),
                    "assessment": assess_gate(state).to_dict(),
                    "latest_evidence": state.evidence[-1].to_dict(),
                }
            )
        )
    except Exception as e:
        raise _exit_for_error(e)


@whalemirror_gates_app.command("status")
def whalemirror_gates_status(
    gate: str = typer.Option("all", "--gate", help="all, capture, paper, live, capture-7d, paper-30d, or live-60d"),
    state_dir: Path = typer.Option(default_validation_dir(), "--state-dir"),
    markdown: bool = typer.Option(False, "--markdown", help="Render markdown reports instead of JSON"),
) -> None:
    """Show validation gate status from restartable state files."""
    try:
        gate_ids = _resolve_gate_ids(gate)
        states = []
        for gate_id in gate_ids:
            path = gate_state_path(gate_id, state_dir=state_dir)
            if path.exists():
                state = load_gate_state(gate_id, state_dir=state_dir)
                states.append(state)
        if markdown:
            Console().print("\n".join(render_gate_report(state) for state in states))
        else:
            Console().print_json(
                json.dumps(
                    {
                        "state_dir": str(state_dir),
                        "gates": [
                            {
                                "state_path": str(gate_state_path(state.gate_id, state_dir=state_dir)),
                                "assessment": assess_gate(state).to_dict(),
                            }
                            for state in states
                        ],
                    }
                )
            )
    except Exception as e:
        raise _exit_for_error(e)


def _resolve_gate_ids(gate: str) -> list[str]:
    normalized = gate.strip().lower()
    mapping = {
        "all": [CAPTURE_GATE, PAPER_GATE, LIVE_GATE],
        "capture": [CAPTURE_GATE],
        "capture-7d": [CAPTURE_GATE],
        "paper": [PAPER_GATE],
        "paper-30d": [PAPER_GATE],
        "live": [LIVE_GATE],
        "live-60d": [LIVE_GATE],
    }
    if normalized not in mapping:
        raise ValueError(f"unsupported gate: {gate}")
    return mapping[normalized]


@app.command(hidden=True)
def quick(
    tickers: list[str] = typer.Argument(..., help="Ticker symbol(s) (e.g., AAPL MSFT GOOG)"),
    no_color: bool = typer.Option(False, "--no-color", help="Strip color formatting for piping"),
    spark: bool = typer.Option(False, "--spark", help="Append sparkline of last 20 days"),
    detailed: bool = typer.Option(False, "--detailed", help="Include fundamental data summary"),
) -> None:
    """Quick one-liner analysis for one or more tickers."""
    from stonks_cli.formatting.numbers import format_market_cap
    from stonks_cli.formatting.oneliner import format_quick_summary
    from stonks_cli.formatting.sparkline import generate_sparkline

    try:
        results = do_quick(tickers)
        console = Console(force_terminal=not no_color, no_color=no_color)

        for result in results:
            line = format_quick_summary(
                ticker=result.ticker,
                price=result.price,
                change_pct=result.change_pct,
                action=result.action,
                confidence=result.confidence,
                use_color=not no_color,
            )
            if spark and result.prices:
                sparkline = generate_sparkline(result.prices, width=20)
                line = f"{line} {sparkline}"
            console.print(line)

            if detailed:
                # Show fundamental summary
                try:
                    from stonks_cli.data.fundamentals import fetch_fundamentals_yahoo

                    base_ticker = result.ticker.split(".")[0]
                    fundamentals = fetch_fundamentals_yahoo(base_ticker)
                    if fundamentals:
                        pe = f"P/E: {fundamentals.pe_ratio:.1f}" if fundamentals.pe_ratio else "P/E: N/A"
                        mc = f"MCap: {format_market_cap(fundamentals.market_cap)}"
                        div = (
                            f"Div: {fundamentals.dividend_yield * 100:.2f}%"
                            if fundamentals.dividend_yield
                            else "Div: N/A"
                        )
                        range_str = ""
                        if fundamentals.fifty_two_week_low and fundamentals.fifty_two_week_high:
                            range_str = (
                                f"52w: ${fundamentals.fifty_two_week_low:.2f}-${fundamentals.fifty_two_week_high:.2f}"
                            )
                        details = f"  {pe} | {mc} | {div}"
                        if range_str:
                            details = f"{details} | {range_str}"
                        console.print(details, style="dim")
                except ImportError:
                    console.print("  [dim](yfinance not installed for fundamentals)[/dim]")
                except Exception as inner_err:
                    log_suppressed_exception(
                        context="cli.quick.detailed_fundamentals",
                        error=inner_err,
                        ticker=result.ticker,
                    )
    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def chart(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g., AAPL)"),
    days: int = typer.Option(90, "--days", help="Number of days to display"),
    candle: bool = typer.Option(False, "--candle", help="Display candlestick chart instead of line chart"),
    volume: bool = typer.Option(False, "--volume", help="Include volume subplot below price chart"),
    sma: str = typer.Option(None, "--sma", help="Overlay SMAs (comma-separated periods, e.g., 20,50,200)"),
    bb: bool = typer.Option(False, "--bb", help="Overlay Bollinger Bands (20-period, 2 std dev)"),
) -> None:
    """Display an ASCII price chart for a ticker."""
    try:
        sma_periods = None
        if sma:
            sma_periods = [int(p.strip()) for p in sma.split(",") if p.strip()]
        do_chart(ticker, days=days, candle=candle, volume=volume, sma_periods=sma_periods, show_bb=bb)
    except Exception as e:
        raise _exit_for_error(e)


@app.command("chart-compare", hidden=True)
def chart_compare(
    tickers: list[str] = typer.Argument(..., help="Ticker symbols to compare (e.g., AAPL MSFT GOOG)"),
    days: int = typer.Option(90, "--days", help="Number of days to display"),
) -> None:
    """Compare performance of multiple tickers on a normalized chart."""
    try:
        do_chart_compare(tickers, days=days)
    except Exception as e:
        raise _exit_for_error(e)


@app.command("chart-rsi", hidden=True)
def chart_rsi(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g., AAPL)"),
    period: int = typer.Option(14, "--period", help="RSI period"),
    days: int = typer.Option(90, "--days", help="Number of days to display"),
) -> None:
    """Display RSI indicator chart with overbought/oversold zones."""
    try:
        do_chart_rsi(ticker, period=period, days=days)
    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def correlation(
    tickers: list[str] = typer.Argument(..., help="Ticker symbols (e.g., AAPL MSFT GOOG)"),
    days: int = typer.Option(252, "--days", help="Number of trading days for correlation calculation"),
    method: str = typer.Option("pearson", "--method", help="Correlation method: pearson or spearman"),
) -> None:
    """Display correlation matrix for multiple tickers."""
    from rich.table import Table

    try:
        result = do_correlation(tickers, days=days, method=method)
        console = Console()

        matrix = result["matrix"]
        ticker_list = result["tickers"]

        if matrix.empty:
            console.print("[yellow]No correlation data available[/yellow]")
            return

        table = Table(title=f"Correlation Matrix ({days} days, {result.get('method', method)})")
        table.add_column("", style="bold")

        for t in ticker_list:
            table.add_column(t, justify="right")

        for row_ticker in ticker_list:
            row_values = []
            for col_ticker in ticker_list:
                val = matrix.loc[row_ticker, col_ticker]
                # Color based on correlation value
                if row_ticker == col_ticker:
                    cell = "[dim]1.00[/dim]"
                elif val < 0.3:
                    cell = f"[green]{val:.2f}[/green]"
                elif val > 0.7:
                    cell = f"[red]{val:.2f}[/red]"
                else:
                    cell = f"[yellow]{val:.2f}[/yellow]"
                row_values.append(cell)
            table.add_row(row_ticker, *row_values)

        console.print(table)
    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def sector(
    sector_name: str = typer.Argument(..., help="Sector name (e.g., Technology, Healthcare, Financials)"),
) -> None:
    """Display sector ETF performance compared to SPY."""
    from rich.table import Table

    try:
        result = do_sector(sector_name)
        console = Console()

        table = Table(title=f"{result['sector']} ({result['etf']}) vs SPY")
        table.add_column("Period", style="cyan")
        table.add_column(result["etf"], justify="right")
        table.add_column("SPY", justify="right")
        table.add_column("Relative", justify="right")

        def fmt_pct(val: float | None) -> str:
            if val is None:
                return "N/A"
            color = "green" if val >= 0 else "red"
            return f"[{color}]{val:+.2f}%[/{color}]"

        def fmt_relative(sector_val: float | None, spy_val: float | None) -> str:
            if sector_val is None or spy_val is None:
                return "N/A"
            diff = sector_val - spy_val
            color = "green" if diff >= 0 else "red"
            return f"[{color}]{diff:+.2f}%[/{color}]"

        periods = [("Daily", "daily"), ("Weekly", "weekly"), ("Monthly", "monthly"), ("YTD", "ytd")]
        for label, key in periods:
            sector_val = result["sector_performance"][key]
            spy_val = result["spy_performance"][key]
            table.add_row(
                label,
                fmt_pct(sector_val),
                fmt_pct(spy_val),
                fmt_relative(sector_val, spy_val),
            )

        console.print(table)
    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def fundamentals(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g., AAPL)"),
    json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Display fundamental data for a ticker (requires yfinance)."""
    import json

    from rich.table import Table

    from stonks_cli.formatting.numbers import format_market_cap, format_percent, format_ratio

    try:
        data = do_fundamentals(ticker, as_json=True)
        console = Console()

        if data is None:
            console.print(f"[red]No fundamental data available for {ticker}[/red]")
            return

        if json_out:
            console.print(json.dumps(data, indent=2))
            return

        table = Table(title=f"Fundamentals: {ticker}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("P/E Ratio", format_ratio(data.get("pe_ratio")))
        table.add_row("Forward P/E", format_ratio(data.get("forward_pe")))
        table.add_row("PEG Ratio", format_ratio(data.get("peg_ratio")))
        table.add_row("Price/Book", format_ratio(data.get("price_to_book")))
        table.add_row("Market Cap", format_market_cap(data.get("market_cap")))
        table.add_row("Enterprise Value", format_market_cap(data.get("enterprise_value")))
        table.add_row("Profit Margin", format_percent(data.get("profit_margin")))
        table.add_row("Revenue Growth (YoY)", format_percent(data.get("revenue_growth_yoy")))
        table.add_row("Earnings Growth (YoY)", format_percent(data.get("earnings_growth_yoy")))
        table.add_row("Dividend Yield", format_percent(data.get("dividend_yield")))
        table.add_row("Beta", format_ratio(data.get("beta")))
        table.add_row(
            "52-Week High", f"${data.get('fifty_two_week_high', 0):.2f}" if data.get("fifty_two_week_high") else "N/A"
        )
        table.add_row(
            "52-Week Low", f"${data.get('fifty_two_week_low', 0):.2f}" if data.get("fifty_two_week_low") else "N/A"
        )

        console.print(table)
    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def news(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g., AAPL)"),
    sentiment: bool = typer.Option(False, "--sentiment", help="Show only notable sentiment headlines"),
) -> None:
    """Display recent news headlines for a ticker with sentiment."""
    from rich.table import Table

    try:
        items = do_news(ticker, notable_only=sentiment)
        console = Console()

        if not items:
            console.print(f"[yellow]No news found for {ticker}[/yellow]")
            return

        table = Table(title=f"News: {ticker}")
        table.add_column("Date", style="dim", width=12)
        table.add_column("Source", width=15)
        table.add_column("Headline")
        table.add_column("Sent", justify="center", width=6)

        for item in items[:20]:
            # Date
            date_str = item["published_date"][:10] if item.get("published_date") else "N/A"

            # Truncate headline
            headline = item["title"][:80] + "..." if len(item["title"]) > 80 else item["title"]

            # Sentiment indicator
            score = item.get("sentiment_score", 0)
            if score > 0.2:
                sent_str = "[green]+[/green]"
            elif score < -0.2:
                sent_str = "[red]-[/red]"
            else:
                sent_str = "[dim]o[/dim]"

            table.add_row(date_str, item["source"], headline, sent_str)

        console.print(table)
    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def earnings(
    ticker: str = typer.Option(None, "--ticker", help="Show earnings history for specific ticker"),
    show_next: bool = typer.Option(False, "--next", help="Show only next upcoming earnings date"),
    implied_move: bool = typer.Option(
        False, "--implied-move", help="Show historically implied earnings move percentage"
    ),
) -> None:
    """Display earnings calendar or ticker history (requires yfinance)."""
    from rich.table import Table

    try:
        # Handle implied move flag
        if implied_move and ticker:
            from stonks_cli.data.earnings import compute_earnings_implied_move

            console = Console()
            move = compute_earnings_implied_move(ticker)
            if move is not None:
                console.print(f"[bold]{ticker.upper()}[/bold] Implied Earnings Move: [cyan]{move:.1f}%[/cyan]")
                console.print("[dim]Based on average absolute post-earnings move from historical data[/dim]")
            else:
                console.print(f"[yellow]No implied move data available for {ticker}[/yellow]")
            return

        data = do_earnings(ticker=ticker, show_next=show_next)
        console = Console()

        if data["mode"] == "next":
            event = data["next_earnings"]
            days = data["days_until"]
            console.print(f"[bold]{data['ticker']}[/bold] Next Earnings")
            console.print(f"Date: {event['report_date']} ({days} days)")
            console.print(f"Time: {event['report_time']}")
            if event.get("eps_estimate"):
                console.print(f"EPS Estimate: ${event['eps_estimate']:.2f}")
            return

        if data["mode"] == "history":
            events = data["events"]
            if not events:
                console.print(f"[yellow]No earnings history for {data['ticker']}[/yellow]")
                return

            table = Table(title=f"Earnings History: {data['ticker']}")
            table.add_column("Date")
            table.add_column("Time")
            table.add_column("EPS Est", justify="right")
            table.add_column("EPS Actual", justify="right")
            table.add_column("Surprise", justify="right")

            for e in events:
                eps_est = f"${e['eps_estimate']:.2f}" if e.get("eps_estimate") else "N/A"
                eps_act = f"${e['eps_actual']:.2f}" if e.get("eps_actual") else "N/A"

                surprise_str = "N/A"
                if e.get("surprise_pct") is not None:
                    s = e["surprise_pct"]
                    color = "green" if s >= 0 else "red"
                    surprise_str = f"[{color}]{s:+.1f}%[/{color}]"

                table.add_row(e["report_date"], e["report_time"], eps_est, eps_act, surprise_str)

            console.print(table)
            return

        if data["mode"] == "calendar":
            events = data.get("events") or []
            scanned = int(data.get("tickers_scanned") or 0)
            if not events:
                if scanned > 0:
                    console.print(f"[yellow]No upcoming earnings found across {scanned} configured tickers[/yellow]")
                else:
                    console.print("[yellow]No configured tickers available for calendar mode[/yellow]")
                return

            table = Table(title="Upcoming Earnings Calendar")
            table.add_column("Days", justify="right", style="bold")
            table.add_column("Date")
            table.add_column("Ticker", style="cyan")
            table.add_column("Company")
            table.add_column("Time")
            table.add_column("EPS Est", justify="right")

            for e in events:
                days_until = int(e.get("days_until") or 0)
                if days_until == 0:
                    days_str = "[yellow]today[/yellow]"
                elif days_until < 0:
                    days_str = str(days_until)
                else:
                    days_str = str(days_until)
                eps_est = f"${e['eps_estimate']:.2f}" if e.get("eps_estimate") is not None else "N/A"
                table.add_row(
                    days_str,
                    str(e.get("report_date") or "N/A"),
                    str(e.get("ticker") or "N/A"),
                    str(e.get("company_name") or "N/A"),
                    str(e.get("report_time") or "unknown"),
                    eps_est,
                )
            console.print(table)
            return

        console.print("[yellow]No earnings data available[/yellow]")

    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def insider(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g., AAPL)"),
    days: int = typer.Option(90, "--days", help="Days to look back"),
    buys_only: bool = typer.Option(False, "--buys-only", help="Show only buy transactions"),
    sells_only: bool = typer.Option(False, "--sells-only", help="Show only sell transactions"),
) -> None:
    """Display recent insider transactions for a ticker."""
    from rich.table import Table

    from stonks_cli.formatting.numbers import format_market_cap

    try:
        transactions = do_insider(ticker, days=days, buys_only=buys_only, sells_only=sells_only)
        console = Console()

        if not transactions:
            console.print(f"[yellow]No insider transactions found for {ticker}[/yellow]")
            return

        table = Table(title=f"Insider Transactions: {ticker}")
        table.add_column("Date", style="dim")
        table.add_column("Insider")
        table.add_column("Title")
        table.add_column("Type", style="bold")
        table.add_column("Shares", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Value", justify="right")

        for t in transactions:
            trans_type = t["transaction_type"]
            if trans_type == "buy":
                type_str = "[green]BUY[/green]"
            elif trans_type == "sell":
                type_str = "[red]SELL[/red]"
            else:
                type_str = trans_type.upper()

            shares_str = f"{t['shares']:,.0f}"
            price_str = f"${t['price_per_share']:.2f}" if t.get("price_per_share") else "N/A"
            value_str = format_market_cap(t.get("total_value"))

            table.add_row(
                t["filing_date"],
                t["insider_name"],
                t["insider_title"],
                type_str,
                shares_str,
                price_str,
                value_str,
            )

        console.print(table)
    except Exception as e:
        raise _exit_for_error(e)


@watchlist_app.command("list")
def watchlist_list() -> None:
    """List configured watchlists."""
    try:
        out = do_watchlist_list()
        console = Console()
        if not out:
            console.print("No watchlists configured")
            return
        for name in sorted(out.keys()):
            tickers = out.get(name) or []
            console.print(f"{name}: {', '.join(tickers) if tickers else '-'}")
    except Exception as e:
        raise _exit_for_error(e)


@watchlist_app.command("set")
def watchlist_set(name: str = typer.Argument(...), tickers: list[str] = typer.Argument(...)) -> None:
    """Create/replace a watchlist."""
    try:
        do_watchlist_set(name, tickers)
        Console().print(f"Updated watchlist: {name}")
    except Exception as e:
        raise _exit_for_error(e)


@watchlist_app.command("remove")
def watchlist_remove(name: str = typer.Argument(...)) -> None:
    """Remove a watchlist."""
    try:
        do_watchlist_remove(name)
        Console().print(f"Removed watchlist: {name}")
    except Exception as e:
        raise _exit_for_error(e)


@watchlist_app.command("analyze")
def watchlist_analyze(
    name: str = typer.Argument(...),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD"),
    out_dir: str = typer.Option("reports", "--out-dir"),
    report_name: str | None = typer.Option(None, "--name", help="Stable report filename (e.g. report_latest.txt)"),
    json_out: bool = typer.Option(False, "--json", "--no-json", help="Write JSON output alongside the report"),
    csv_out: bool = typer.Option(False, "--csv", "--no-csv", help="Write CSV summary alongside the report"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run without persisting last-run history"),
) -> None:
    """Analyze a named watchlist."""
    try:
        artifacts = do_watchlist_analyze(
            name,
            out_dir=Path(out_dir),
            start=start,
            end=end,
            report_name=report_name,
            json_out=json_out,
            csv_out=csv_out,
            sandbox=sandbox,
        )
        Console().print(f"Wrote report: {artifacts.report_path}")
        if artifacts.json_path:
            Console().print(f"Wrote json: {artifacts.json_path}")
    except Exception as e:
        raise _exit_for_error(e)


@signals_app.command("diff")
def signals_diff() -> None:
    """Compare latest vs previous run and highlight changes."""
    try:
        from rich.table import Table

        out = do_signals_diff()
        changes = list(out.get("changes") or [])
        if not changes:
            Console().print("No changes")
            return

        table = Table(title="Signals Diff")
        table.add_column("Ticker", style="cyan")
        table.add_column("Kind")
        table.add_column("Old")
        table.add_column("New")
        table.add_column("Δconf", justify="right")

        for row in changes:
            t = str(row.get("ticker"))
            kind = str(row.get("kind"))
            old = row.get("old")
            new = row.get("new")
            delta = row.get("delta")

            def fmt_side(v) -> str:
                if v is None:
                    return "-"
                if isinstance(v, dict):
                    a = v.get("action")
                    c = v.get("confidence")
                    try:
                        c_f = float(c)
                        return f"{a} ({c_f:.2f})"
                    except Exception:
                        return f"{a}"
                return str(v)

            d_s = "-"
            try:
                if delta is not None:
                    d_s = f"{float(delta):+.2f}"
            except Exception:
                d_s = "-"

            table.add_row(t, kind, fmt_side(old), fmt_side(new), d_s)

        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@plugins_app.command("list")
def plugins_list() -> None:
    """Show loaded plugins and discovered strategies/providers."""
    try:
        out = do_plugins_list()
        console = Console()

        configured = list(out.get("configured") or [])
        ok = set(out.get("ok") or [])
        errors = dict(out.get("errors") or {})

        if not configured:
            console.print("No plugins configured")
        else:
            for spec in configured:
                if spec in ok:
                    console.print(f"ok: {spec}")
                elif spec in errors:
                    console.print(f"error: {spec}: {errors[spec]}")
                else:
                    console.print(f"unknown: {spec}")

        strategies = list(out.get("strategies") or [])
        provider_factories = list(out.get("provider_factories") or [])
        console.print(f"strategies: {', '.join(strategies) if strategies else '-'}")
        console.print(f"provider_factories: {', '.join(provider_factories) if provider_factories else '-'}")
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_markets_app.command("list")
def polymarket_markets_list(
    limit: int = typer.Option(50, "--limit", min=1, max=1000),
    active: bool = typer.Option(True, "--active/--all", help="Prefer active markets by default"),
    closed: bool = typer.Option(False, "--closed/--open", help="Include closed markets"),
    order: str = typer.Option("volume", "--order", help="Gamma order field"),
) -> None:
    """List Polymarket markets using the Polymarket-native client."""
    try:
        rows = do_polymarket_markets_list(limit=limit, active=active, closed=closed, order=order)
        table = Table(title="Polymarket Markets")
        table.add_column("Slug")
        table.add_column("Question")
        table.add_column("Liquidity", justify="right")
        table.add_column("Volume", justify="right")
        table.add_column("End")
        for row in rows:
            table.add_row(
                str(row.get("slug") or "-"),
                str(row.get("question") or "-"),
                f"${float(row['liquidity_usd']):,.0f}" if row.get("liquidity_usd") is not None else "-",
                f"${float(row['volume_usd']):,.0f}" if row.get("volume_usd") is not None else "-",
                str(row.get("end_date_iso") or "-"),
            )
        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_markets_app.command("get")
def polymarket_market_get(slug_or_id: str = typer.Argument(..., help="Polymarket market slug or numeric id")) -> None:
    """Show one Polymarket market as JSON."""
    try:
        data = do_polymarket_market_get(slug_or_id)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_app.command("book")
def polymarket_book(token_id: str = typer.Argument(..., help="CLOB token id")) -> None:
    """Show a Polymarket order book as JSON."""
    try:
        data = do_polymarket_book(token_id)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_app.command("scan")
def polymarket_scan(
    limit: int | None = typer.Option(None, "--limit", min=1, max=1000),
    include_filtered: bool = typer.Option(False, "--include-filtered", help="Include rejected markets"),
) -> None:
    """Run a deterministic structural Polymarket scanner."""
    try:
        rows = do_polymarket_scan(limit=limit, include_filtered=include_filtered)
        table = Table(title="Polymarket Scan Queue")
        table.add_column("Status")
        table.add_column("Slug")
        table.add_column("Mid", justify="right")
        table.add_column("Bid Depth", justify="right")
        table.add_column("Ask Depth", justify="right")
        table.add_column("Hours", justify="right")
        table.add_column("Wallets", justify="right")
        table.add_column("Score", justify="right")
        table.add_column("Reasons")
        for row in rows:
            table.add_row(
                str(row.get("status") or "-"),
                str(row.get("slug") or "-"),
                f"{float(row['midpoint']):.3f}" if row.get("midpoint") is not None else "-",
                f"${float(row.get('bids_depth_usd') or 0):,.0f}",
                f"${float(row.get('asks_depth_usd') or 0):,.0f}",
                f"{float(row['hours_to_resolution']):.1f}" if row.get("hours_to_resolution") is not None else "-",
                str(int(row.get("target_wallet_count") or 0)),
                f"{float(row.get('score') or 0):.2f}",
                ", ".join(row.get("reasons") or []) or "-",
            )
        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_research_app.command("thesis")
def polymarket_research_thesis(
    market_id: str = typer.Argument(..., help="Market id from `stonks-cli polymarket scan`"),
    provider: str = typer.Option("claude", "--provider", help="claude, openai, or codex"),
    model: str | None = typer.Option(None, "--model", help="Provider model override"),
    api_key_env: str | None = typer.Option(None, "--api-key-env", help="Environment variable containing the API key"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build and cache a no-network thesis placeholder"),
) -> None:
    """Generate and cache an offline LLM thesis for a scanned market."""
    try:
        data = do_polymarket_research_thesis(
            market_id=market_id,
            provider=provider,
            model=model,
            api_key_env=api_key_env,
            dry_run=dry_run,
        )
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_research_app.command("list")
def polymarket_research_list() -> None:
    """Show cached Polymarket LLM theses."""
    try:
        Console().print_json(json.dumps(do_polymarket_research_list()))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_app.command("run")
def polymarket_run(
    cycles: int = typer.Option(1, "--cycles", min=1, help="Number of runtime cycles"),
    limit: int | None = typer.Option(None, "--limit", min=1, max=1000),
    sleep_seconds: float | None = typer.Option(None, "--sleep-seconds", min=0.0),
    market_messages: int = typer.Option(0, "--market-messages", min=0),
    user_messages: int = typer.Option(0, "--user-messages", min=0),
    soak: bool = typer.Option(False, "--soak", help="Deterministic soak using recorded events"),
    market_events_path: Path | None = typer.Option(None, "--market-events-path", exists=True, readable=True),
    user_events_path: Path | None = typer.Option(None, "--user-events-path", exists=True, readable=True),
    batch_size: int = typer.Option(1, "--batch-size", min=1),
) -> None:
    """Unified Polymarket runtime entrypoint (replaces runtime once/loop/soak)."""
    try:
        if soak:
            data = do_polymarket_runtime_soak(
                limit=limit,
                cycles=cycles,
                market_events_path=market_events_path,
                user_events_path=user_events_path,
                batch_size=batch_size,
            )
        elif cycles == 1 and not market_messages and not user_messages and sleep_seconds is None:
            data = do_polymarket_runtime_once(limit=limit)
        else:
            data = do_polymarket_runtime_loop(
                limit=limit,
                cycles=cycles,
                sleep_seconds=sleep_seconds,
                market_messages=market_messages,
                user_messages=user_messages,
            )
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_runtime_app.command("status")
def polymarket_runtime_status() -> None:
    """Show Polymarket runtime state."""
    try:
        data = do_polymarket_runtime_status()
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_runtime_app.command("once")
def polymarket_runtime_once(
    limit: int | None = typer.Option(None, "--limit", min=1, max=1000),
) -> None:
    """Run one Polymarket scan cycle and persist runtime status."""
    try:
        data = do_polymarket_runtime_once(limit=limit)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_runtime_app.command("loop")
def polymarket_runtime_loop(
    cycles: int = typer.Option(1, "--cycles", min=1),
    limit: int | None = typer.Option(None, "--limit", min=1, max=1000),
    sleep_seconds: float | None = typer.Option(None, "--sleep-seconds", min=0.0),
    market_messages: int = typer.Option(0, "--market-messages", min=0, help="Pump market websocket messages per cycle"),
    user_messages: int = typer.Option(0, "--user-messages", min=0, help="Pump user websocket messages per cycle"),
) -> None:
    """Run multiple Polymarket runtime cycles with optional websocket pumping."""
    try:
        data = do_polymarket_runtime_loop(
            limit=limit,
            cycles=cycles,
            sleep_seconds=sleep_seconds,
            market_messages=market_messages,
            user_messages=user_messages,
        )
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_runtime_app.command("guard-status")
def polymarket_runtime_guard_status() -> None:
    """Show Polymarket trading guard and halt state."""
    try:
        data = do_polymarket_guard_status()
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_runtime_app.command("halt")
def polymarket_runtime_halt(
    reason: str = typer.Option("manual_halt", "--reason"),
) -> None:
    """Manually halt Polymarket trading until resumed."""
    try:
        data = do_polymarket_runtime_halt(reason)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_runtime_app.command("resume")
def polymarket_runtime_resume() -> None:
    """Resume Polymarket trading after a manual or automatic halt."""
    try:
        data = do_polymarket_runtime_resume()
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_app.command("journal")
def polymarket_journal(
    limit: int = typer.Option(100, "--limit", min=1, max=1000),
    by_signal: bool = typer.Option(False, "--by-signal", help="Aggregate paper trade realized PnL by signal source"),
    tearsheet: bool = typer.Option(False, "--tearsheet", help="Show full quantstats-style metrics (Sortino, Calmar, profit factor, expectancy)"),
) -> None:
    """Show recent Polymarket runtime journal, or PnL grouped by signal source."""
    try:
        if by_signal or tearsheet:
            from stonks_cli.polymarket.paper import pnl_by_signal

            data = pnl_by_signal()
            rows = data.get("by_signal") or []
            if tearsheet:
                table = Table(title="Polymarket Tearsheet by Signal Source")
                table.add_column("Signal")
                table.add_column("PnL", justify="right")
                table.add_column("RTs", justify="right")
                table.add_column("Win%", justify="right")
                table.add_column("Sharpe", justify="right")
                table.add_column("Sortino", justify="right")
                table.add_column("Calmar", justify="right")
                table.add_column("MaxDD", justify="right")
                table.add_column("PF", justify="right")
                table.add_column("Expect", justify="right")
                table.add_column("AvgWin", justify="right")
                table.add_column("AvgLoss", justify="right")
                for row in rows:
                    table.add_row(
                        str(row.get("signal") or "-"),
                        f"${float(row.get('realized_pnl') or 0):,.2f}",
                        str(int(row.get("round_trips") or 0)),
                        f"{float(row.get('win_rate') or 0) * 100:.1f}%",
                        f"{float(row.get('sharpe') or 0):.2f}",
                        f"{float(row.get('sortino') or 0):.2f}",
                        f"{float(row.get('calmar') or 0):.2f}",
                        f"{float(row.get('max_drawdown') or 0) * 100:.1f}%",
                        f"{float(row.get('profit_factor') or 0):.2f}",
                        f"${float(row.get('expectancy') or 0):,.4f}",
                        f"${float(row.get('avg_win') or 0):,.2f}",
                        f"${float(row.get('avg_loss') or 0):,.2f}",
                    )
            else:
                table = Table(title="Polymarket PnL by Signal Source")
                table.add_column("Signal")
                table.add_column("Realized PnL", justify="right")
                table.add_column("RTs", justify="right")
                table.add_column("Win%", justify="right")
                table.add_column("Sharpe", justify="right")
                table.add_column("MaxDD", justify="right")
                table.add_column("Buy $", justify="right")
                table.add_column("Sell $", justify="right")
                table.add_column("Open $", justify="right")
                for row in rows:
                    table.add_row(
                        str(row.get("signal") or "-"),
                        f"${float(row.get('realized_pnl') or 0):,.2f}",
                        str(int(row.get("round_trips") or 0)),
                        f"{float(row.get('win_rate') or 0) * 100:.1f}%",
                        f"{float(row.get('sharpe') or 0):.2f}",
                        f"{float(row.get('max_drawdown') or 0) * 100:.1f}%",
                        f"${float(row.get('buy_notional') or 0):,.2f}",
                        f"${float(row.get('sell_notional') or 0):,.2f}",
                        f"${float(row.get('open_notional') or 0):,.2f}",
                    )
            Console().print(table)
            Console().print(f"[bold]Total realized:[/bold] ${float(data.get('total_realized_pnl') or 0):,.2f} | trades={int(data.get('trade_count') or 0)}")
            return
        data = do_polymarket_journal(limit=limit)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_app.command("doctor")
def polymarket_doctor(
    deep_auth: bool = typer.Option(False, "--deep-auth", help="Attempt authenticated client initialization"),
) -> None:
    """Run pre-live Polymarket environment and safety checks."""
    try:
        data = do_polymarket_preflight(deep_auth=deep_auth)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_app.command("emergency-stop")
def polymarket_emergency_stop(
    reason: str = typer.Option("operator_emergency_stop", "--reason"),
    close_positions: bool = typer.Option(False, "--close-positions", help="Also try to close positions where current prices are available"),
) -> None:
    """Halt runtime and cancel all live open orders."""
    try:
        data = do_polymarket_emergency_stop(reason=reason, close_positions=close_positions)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_wallets_app.command("import")
def polymarket_wallets_import(
    csv_path: Path = typer.Argument(..., exists=True, readable=True, help="Path to poly_data processed/trades.csv"),
) -> None:
    """Register a wallet trade dataset for ranking and copy-trading research."""
    try:
        data = do_polymarket_wallets_import(csv_path)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_wallets_app.command("rank")
def polymarket_wallets_rank(
    csv_path: Path | None = typer.Option(None, "--csv-path", help="Override imported source path"),
    min_trades: int = typer.Option(100, "--min-trades", min=1),
    min_win_rate: float = typer.Option(0.70, "--min-win-rate", min=0.0, max=1.0),
    limit: int = typer.Option(50, "--limit", min=1, max=1000),
) -> None:
    """Rank wallets by realized PnL and win rate from imported trade history."""
    try:
        rows = do_polymarket_wallets_rank(
            csv_path=csv_path,
            min_trades=min_trades,
            min_win_rate=min_win_rate,
            limit=limit,
        )
        table = Table(title="Polymarket Wallet Targets")
        table.add_column("Wallet")
        table.add_column("Trades", justify="right")
        table.add_column("Realized PnL", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Closed RT", justify="right")
        table.add_column("Gross Vol", justify="right")
        table.add_column("Source")
        for row in rows:
            table.add_row(
                str(row.get("wallet") or "-"),
                str(int(row.get("trades") or 0)),
                f"${float(row.get('realized_pnl') or 0):,.2f}",
                f"{float(row.get('win_rate') or 0) * 100:.1f}%",
                str(int(row.get("closed_round_trips") or 0)),
                f"${float(row.get('gross_volume') or 0):,.2f}",
                str(row.get("source") or "-"),
            )
        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_wallets_app.command("whales")
def polymarket_wallets_whales(
    csv_path: Path | None = typer.Option(None, "--csv-path", help="Override imported source path"),
    min_notional: float = typer.Option(10000.0, "--min-notional", min=0.0),
    limit: int = typer.Option(50, "--limit", min=1, max=1000),
    market_id: str | None = typer.Option(None, "--market-id"),
) -> None:
    """List individual whale trades (notional >= --min-notional) from imported wallet CSV."""
    try:
        from stonks_cli.polymarket.wallets import detect_whale_trades

        rows = detect_whale_trades(csv_path=csv_path, min_notional_usd=min_notional, limit=limit, market_id=market_id)
        table = Table(title=f"Polymarket Whale Trades (>= ${min_notional:,.0f})")
        table.add_column("Wallet")
        table.add_column("Market")
        table.add_column("Dir")
        table.add_column("Side")
        table.add_column("Px", justify="right")
        table.add_column("Shares", justify="right")
        table.add_column("Notional", justify="right")
        table.add_column("TS")
        for w in rows:
            table.add_row(
                w.wallet[:10] + "…",
                w.market_id,
                w.direction,
                w.side,
                f"{w.price:.4f}",
                f"{w.shares:,.2f}",
                f"${w.notional:,.0f}",
                w.ts or "-",
            )
        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_wallets_app.command("targets")
def polymarket_wallet_targets() -> None:
    """Show the saved wallet target list."""
    try:
        rows = do_polymarket_wallet_targets()
        Console().print_json(json.dumps(rows))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_wallets_app.command("signals")
def polymarket_wallet_signals() -> None:
    """Show aggregated target-wallet market and outcome signals."""
    try:
        rows = do_polymarket_wallet_market_signals()
        table = Table(title="Polymarket Wallet Market Signals")
        table.add_column("Market")
        table.add_column("Outcome")
        table.add_column("Category")
        table.add_column("Wallets", justify="right")
        table.add_column("Trades", justify="right")
        table.add_column("Net Vol", justify="right")
        table.add_column("Gross Vol", justify="right")
        for row in rows:
            table.add_row(
                str(row.get("market_id") or "-"),
                str(row.get("outcome") or "-"),
                str(row.get("category") or "-"),
                str(int(row.get("wallet_count") or 0)),
                str(int(row.get("trade_count") or 0)),
                f"{float(row.get('net_volume') or 0):,.2f}",
                f"{float(row.get('gross_volume') or 0):,.2f}",
            )
        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_paper_app.command("init")
def polymarket_paper_init(
    cash: float | None = typer.Option(None, "--cash", min=0.0, help="Override starting cash"),
) -> None:
    """Initialize the Polymarket paper account."""
    try:
        data = do_polymarket_paper_init(cash)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_paper_app.command("status")
def polymarket_paper_status() -> None:
    """Show Polymarket paper account state."""
    try:
        data = do_polymarket_paper_status()
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_paper_app.command("buy")
def polymarket_paper_buy(
    token_id: str = typer.Argument(...),
    market_id: str = typer.Option(..., "--market-id"),
    price: float = typer.Option(..., "--price", min=0.0),
    shares: float = typer.Option(..., "--shares", min=0.0),
    slug: str | None = typer.Option(None, "--slug"),
    outcome: str | None = typer.Option(None, "--outcome"),
) -> None:
    """Execute a Polymarket paper buy."""
    try:
        data = do_polymarket_paper_buy(token_id, market_id, price, shares, slug=slug, outcome=outcome)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_paper_app.command("sell")
def polymarket_paper_sell(
    token_id: str = typer.Argument(...),
    shares: float = typer.Option(..., "--shares", min=0.0),
    price: float = typer.Option(..., "--price", min=0.0),
) -> None:
    """Execute a Polymarket paper sell."""
    try:
        data = do_polymarket_paper_sell(token_id, shares, price)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_replay_app.command("market")
def polymarket_replay_market(
    path: Path = typer.Argument(..., exists=True, readable=True, help="Path to JSON or JSONL market events"),
) -> None:
    """Replay recorded market websocket events into the local cache model."""
    try:
        data = do_polymarket_replay_market(path)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_replay_app.command("user")
def polymarket_replay_user(
    path: Path = typer.Argument(..., exists=True, readable=True, help="Path to JSON or JSONL user events"),
) -> None:
    """Replay recorded user/order websocket events into the local order manager."""
    try:
        data = do_polymarket_replay_user(path)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_app.command("settle")
def polymarket_settle(
    market_id: str = typer.Option(..., "--market-id"),
    winning_token_id: str = typer.Option(..., "--winning-token-id"),
) -> None:
    """Manually settle a resolved Polymarket paper market."""
    try:
        data = do_polymarket_settle(market_id=market_id, winning_token_id=winning_token_id)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_rust_app.command("status")
def polymarket_rust_status() -> None:
    """Show the local Rust hot-path workspace and binary status."""
    try:
        data = do_polymarket_rust_status()
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_rust_app.command("ping")
def polymarket_rust_ping(
    use_cargo: bool = typer.Option(False, "--use-cargo", help="Run via cargo instead of an already-built binary"),
) -> None:
    """Smoke test the Rust hot-path binary."""
    try:
        data = do_polymarket_rust_ping(use_cargo=use_cargo)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_rust_app.command("test")
def polymarket_rust_test() -> None:
    """Run the Rust hot-path test suite."""
    try:
        data = do_polymarket_rust_test()
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_rust_app.command("replay")
def polymarket_rust_replay(
    path: Path = typer.Argument(..., exists=True, readable=True, help="Path to line-based Rust protocol fixture"),
) -> None:
    """Run the Rust replay command against a protocol fixture file."""
    try:
        data = do_polymarket_rust_replay(path)
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@polymarket_runtime_app.command("soak")
def polymarket_runtime_soak(
    cycles: int = typer.Option(1, "--cycles", min=1),
    limit: int | None = typer.Option(None, "--limit", min=1, max=1000),
    market_events_path: Path | None = typer.Option(None, "--market-events-path", exists=True, readable=True),
    user_events_path: Path | None = typer.Option(None, "--user-events-path", exists=True, readable=True),
    batch_size: int = typer.Option(1, "--batch-size", min=1),
) -> None:
    """Run deterministic multi-cycle soak testing with recorded event files."""
    try:
        data = do_polymarket_runtime_soak(
            limit=limit,
            cycles=cycles,
            market_events_path=market_events_path,
            user_events_path=user_events_path,
            batch_size=batch_size,
        )
        Console().print_json(json.dumps(data))
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("init")
def config_init(path: str | None = typer.Option(None, "--path")) -> None:
    """Create a default config file."""
    try:
        p = Path(path).expanduser() if path else None
        out = do_config_init(p)
        Console().print(f"Created config: {out}")
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("show")
def config_show() -> None:
    """Print effective config."""
    try:
        Console().print(do_config_show())
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("where")
def config_where() -> None:
    """Print config path."""
    try:
        Console().print(str(do_config_where()))
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("set")
def config_set(field: str = typer.Argument(...), value: str = typer.Argument(...)) -> None:
    """Set a config field value (supports basic JSON parsing)."""
    try:
        import json

        parsed = value
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = value
        Console().print(do_config_set(field, parsed))
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("validate")
def config_validate() -> None:
    """Validate config and show effective provider selection."""
    try:
        out = do_config_validate()
        tickers = list(out.get("tickers") or [])
        providers = dict(out.get("providers") or {})

        console = Console()
        for t in tickers:
            console.print(t)
        for t in tickers:
            p = providers.get(t)
            if p:
                console.print(f"{t}: {p}")
    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def analyze(
    tickers: list[str] = typer.Argument(None),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD"),
    out_dir: str = typer.Option("reports", "--out-dir"),
    name: str | None = typer.Option(None, "--name", help="Stable report filename (e.g. report_latest.txt)"),
    json_out: bool = typer.Option(False, "--json", "--no-json", help="Write JSON output alongside the report"),
    csv_out: bool = typer.Option(False, "--csv", "--no-csv", help="Write CSV summary alongside the report"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run without persisting last-run history"),
    benchmark: str | None = typer.Option(None, "--benchmark", help="Benchmark ticker for beta calculation (e.g., SPY)"),
) -> None:
    """Analyze tickers and write a report."""
    try:
        if json_out:
            artifacts = do_analyze_artifacts(
                tickers if tickers else None,
                out_dir=Path(out_dir),
                json_out=True,
                csv_out=csv_out,
                start=start,
                end=end,
                report_name=name,
                sandbox=sandbox,
                benchmark=benchmark,
            )
            Console().print(f"Wrote report: {artifacts.report_path}")
            if artifacts.json_path:
                Console().print(f"Wrote json: {artifacts.json_path}")
            return
        do_analyze(
            tickers if tickers else None,
            out_dir=Path(out_dir),
            start=start,
            end=end,
            report_name=name,
            csv_out=csv_out,
            sandbox=sandbox,
            benchmark=benchmark,
        )
    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def backtest(
    tickers: list[str] = typer.Argument(None),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD"),
    out_dir: str = typer.Option("reports", "--out-dir"),
    json_out: bool = typer.Option(False, "--json", help="Write JSON output alongside the text report"),
    advanced: bool = typer.Option(False, "--advanced", help="Include advanced risk metrics in JSON output"),
    validate: bool = typer.Option(False, "--validate", help="Include statistical validation in JSON output"),
) -> None:
    """Run a simple walk-forward backtest and write a summary report."""
    try:
        if json_out or advanced or validate:
            artifacts = do_backtest_artifacts(
                tickers if tickers else None,
                start=start,
                end=end,
                out_dir=Path(out_dir),
                json_out=json_out,
                advanced=advanced,
                validate=validate,
            )
            Console().print(f"Wrote backtest: {artifacts.report_path}")
            if artifacts.json_path:
                Console().print(f"Wrote json: {artifacts.json_path}")
            return
        path = do_backtest(tickers if tickers else None, start=start, end=end, out_dir=Path(out_dir))
        Console().print(f"Wrote backtest: {path}")
    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def bench(
    tickers: list[str] = typer.Argument(None),
    iterations: int = typer.Option(5, "--iterations", min=1, max=50),
    warmup: int = typer.Option(1, "--warmup", min=0, max=10),
) -> None:
    """Run a simple multi-ticker analysis benchmark."""
    try:
        summary = do_bench(tickers if tickers else None, iterations=iterations, warmup=warmup)
        Console().print(summary)
    except Exception as e:
        raise _exit_for_error(e)


@schedule_app.command("run")
def schedule_run(
    out_dir: str = typer.Option("reports", "--out-dir"),
    name: str | None = typer.Option(None, "--name", help="Stable report filename (overwrites each run)"),
    csv_out: bool = typer.Option(False, "--csv", "--no-csv", help="Write CSV summary alongside the report"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run without persisting last-run history"),
) -> None:
    """Run the cron-like scheduler in the foreground."""
    try:
        do_schedule_run(out_dir=Path(out_dir), report_name=name, csv_out=csv_out, sandbox=sandbox)
    except Exception as e:
        raise _exit_for_error(e)


@schedule_app.command("once")
def schedule_once(
    out_dir: str = typer.Option("reports", "--out-dir"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run without persisting last-run history"),
    name: str | None = typer.Option(None, "--name", help="Stable report filename"),
    csv_out: bool = typer.Option(False, "--csv", "--no-csv", help="Write CSV summary alongside the report"),
) -> None:
    """Run one analysis+report (same as a single scheduled job)."""
    try:
        do_schedule_once(out_dir=Path(out_dir), sandbox=sandbox, report_name=name, csv_out=csv_out)
    except Exception as e:
        raise _exit_for_error(e)


@schedule_app.command("status")
def schedule_status() -> None:
    """Show cron expression and next run time (best-effort)."""
    try:
        status = do_schedule_status()
        console = Console()
        console.print(f"cron: {status.cron}")
        if status.next_run:
            console.print(f"next: {status.next_run}")
        else:
            console.print(f"next: [red]unavailable[/red] ({status.error})")
    except Exception as e:
        raise _exit_for_error(e)


@data_app.command("fetch")
def data_fetch(tickers: list[str] = typer.Argument(None)) -> None:
    """Fetch price data for tickers (populates cache)."""
    try:
        fetched = do_data_fetch(tickers if tickers else None)
        Console().print(f"Fetched {len(fetched)} tickers")
    except Exception as e:
        raise _exit_for_error(e)


@data_app.command("verify")
def data_verify(tickers: list[str] = typer.Argument(None)) -> None:
    """Verify data provider(s) for tickers."""
    try:
        results = do_data_verify(tickers if tickers else None)
        for t, status in results.items():
            Console().print(f"{t}: {status}")
    except Exception as e:
        raise _exit_for_error(e)


@data_app.command("cache-info")
def data_cache_info() -> None:
    """Show cache directory info."""
    try:
        info = do_data_cache_info()
        Console().print(f"cache_dir: {info.get('cache_dir')}")
        Console().print(f"entries: {info.get('entries')}")
        Console().print(f"size_bytes: {info.get('size_bytes')}")
        examples = list(info.get("examples") or [])
        if examples:
            Console().print(f"examples: {', '.join(str(x) for x in examples)}")
    except Exception as e:
        raise _exit_for_error(e)


@data_app.command("purge")
def data_purge(older_than_days: int | None = typer.Option(None, "--older-than-days", min=0)) -> None:
    """Purge cache entries (optionally older than N days)."""
    try:
        out = do_data_purge(older_than_days=older_than_days)
        Console().print(f"cache_dir: {out.get('cache_dir')}")
        Console().print(f"deleted: {out.get('deleted')}")
    except Exception as e:
        raise _exit_for_error(e)


@report_app.command("open")
def report_open(
    json_out: bool = typer.Option(False, "--json", help="Also print the latest JSON path if available"),
) -> None:
    """Print latest report path (if any)."""
    try:
        if json_out:
            out = do_report_latest(include_json=True)
            Console().print(str(out.get("report_path")))
            if out.get("json_path"):
                Console().print(str(out.get("json_path")))
            return
        p = do_report_open()
        Console().print(str(p))
    except Exception as e:
        raise _exit_for_error(e)


@report_app.command("latest")
def report_latest(
    json_out: bool = typer.Option(False, "--json", help="Also print the latest JSON path if available"),
) -> None:
    """Print latest report path (and optionally JSON) from state."""
    try:
        out = do_report_latest(include_json=json_out)
        Console().print(str(out.get("report_path")))
        if json_out and out.get("json_path"):
            Console().print(str(out.get("json_path")))
    except Exception as e:
        raise _exit_for_error(e)


@report_app.command("view")
def report_view(path: Path | None = typer.Argument(None)) -> None:
    """View a report (defaults to latest) in a pager when interactive."""
    try:
        out = do_report_view(path)
        text = str(out.get("text") or "")
        console = Console()
        if sys.stdout.isatty():
            with console.pager():
                console.print(text, end="")
            return
        # Non-interactive: keep it scriptable.
        sys.stdout.write(text)
    except Exception as e:
        raise _exit_for_error(e)


@history_app.command("list")
def history_list(limit: int = typer.Option(20, "--limit", min=1, max=200)) -> None:
    """List recent runs."""
    try:
        records = do_history_list(limit=limit)
        if not records:
            Console().print("No history")
            return
        for i, r in enumerate(records):
            Console().print(f"{i}: {r.started_at}  {','.join(r.tickers)}  {r.report_path}  {r.json_path}")
    except Exception as e:
        raise _exit_for_error(e)


@history_app.command("show")
def history_show(
    index: int = typer.Argument(..., min=0), limit: int = typer.Option(2000, "--limit", min=1, max=2000)
) -> None:
    """Show details for a prior run by index (within the last --limit entries)."""
    try:
        r = do_history_show(index, limit=limit)
        Console().print(f"started_at: {r.started_at}")
        Console().print(f"tickers: {','.join(r.tickers)}")
        Console().print(f"report_path: {r.report_path}")
        Console().print(f"json_path: {r.json_path}")
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("add")
def portfolio_add(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    shares: float = typer.Argument(..., help="Number of shares"),
    cost_basis: float = typer.Argument(..., help="Cost basis per share"),
    purchase_date: str = typer.Option(None, "--date", help="Purchase date (YYYY-MM-DD)"),
    notes: str = typer.Option(None, "--notes", help="Optional notes"),
) -> None:
    """Add a position to the portfolio."""
    try:
        result = do_portfolio_add(ticker, shares, cost_basis, purchase_date=purchase_date, notes=notes)
        Console().print(
            f"Added {result['shares']} shares of {result['ticker']} at ${result['cost_basis']:.2f} cost basis"
        )
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("remove")
def portfolio_remove(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    shares: float = typer.Argument(..., help="Number of shares to sell"),
    sale_price: float = typer.Argument(..., help="Sale price per share"),
) -> None:
    """Remove shares from the portfolio."""
    try:
        result = do_portfolio_remove(ticker, shares, sale_price)
        gain_loss = result["realized_gain_loss"]
        pct = result["gain_loss_pct"]
        color = "green" if gain_loss >= 0 else "red"

        Console().print(f"Sold {result['shares_sold']} shares of {result['ticker']} at ${result['sale_price']:.2f}")
        Console().print(f"Realized Gain/Loss: [{color}]${gain_loss:.2f} ({pct:+.2f}%)[/{color}]")
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("show")
def portfolio_show(
    total: bool = typer.Option(False, "--total", help="Show portfolio totals"),
) -> None:
    """Show portfolio positions."""
    from rich.table import Table

    try:
        data = do_portfolio_show(include_total=total)
        positions = data["positions"]
        totals = data["totals"]

        if not positions:
            Console().print("[yellow]Portfolio is empty[/yellow]")
            return

        table = Table(title="Portfolio positions", show_footer=total)

        # Format totals for footer if requested
        f_ticker = "TOTAL" if total else ""
        f_shares = ""
        f_cost_basis = ""
        f_price = ""
        f_value = ""
        f_gl_dollar = ""
        f_gl_pct = ""

        if totals:
            t_cb = totals["total_cost_basis"]
            t_mv = totals["total_market_value"]
            t_gl = totals["total_gain_loss"]
            t_ret = totals["total_return_pct"]

            gl_color = "green" if t_gl >= 0 else "red"

            f_cost_basis = f"${t_cb:.2f}"
            f_value = f"${t_mv:.2f}"
            f_gl_dollar = f"[{gl_color}]${t_gl:.2f}[/{gl_color}]"
            f_gl_pct = f"[{gl_color}]{t_ret:+.2f}%[/{gl_color}]"

        table.add_column("Ticker", style="cyan", footer=f_ticker)
        table.add_column("Shares", justify="right", footer=f_shares)
        table.add_column("Cost Basis", justify="right", footer=f_cost_basis)
        table.add_column("Price", justify="right", footer=f_price)
        table.add_column("Value", justify="right", footer=f_value)
        table.add_column("G/L ($)", justify="right", footer=f_gl_dollar)
        table.add_column("G/L (%)", justify="right", footer=f_gl_pct)

        for p in positions:
            gl_color = "green" if p["gain_loss"] >= 0 else "red"
            table.add_row(
                p["ticker"],
                f"{p['shares']:.2f}",
                f"${p['cost_basis']:.2f}",
                f"${p['current_price']:.2f}",
                f"${p['market_value']:.2f}",
                f"[{gl_color}]${p['gain_loss']:.2f}[/{gl_color}]",
                f"[{gl_color}]{p['gain_loss_pct']:+.2f}%[/{gl_color}]",
            )

        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("allocation")
def portfolio_allocation() -> None:
    """Show portfolio allocation."""
    from rich.table import Table

    try:
        data = do_portfolio_allocation()
        allocations = data.get("allocations", {})

        if not allocations:
            Console().print("[yellow]Portfolio is empty[/yellow]")
            return

        # Sort by percentage descending
        sorted_allocs = sorted(allocations.items(), key=lambda x: x[1], reverse=True)

        table = Table(title="Portfolio Allocation")
        table.add_column("Asset", style="cyan")
        table.add_column("Allocation", justify="right")
        table.add_column("Chart", style="bold")

        for ticker, pct in sorted_allocs:
            # Simple ascii bar chart
            bar_len = int(pct / 2)  # 50 chars for 100%
            bar = "█" * bar_len
            table.add_row(ticker, f"{pct:.2f}%", f"[blue]{bar}[/blue]")

        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("optimize")
def portfolio_optimize(
    method: str = typer.Option(
        "risk_parity",
        "--method",
        help="Optimizer: equal, equal_volatility, risk_parity, or mean_variance",
    ),
    lookback: int = typer.Option(60, "--lookback", min=5, help="Trailing price rows used for covariance"),
) -> None:
    """Suggest long-only target weights for current portfolio positions."""
    from rich.table import Table

    try:
        data = do_portfolio_optimize(method=method, lookback=lookback)
        weights = data.get("weights", {})
        if not weights:
            Console().print("[yellow]No optimizable portfolio positions found[/yellow]")
            return

        table = Table(title=f"Portfolio Optimizer ({data['method']}, lookback={data['lookback']})")
        table.add_column("Ticker", style="cyan")
        table.add_column("Weight", justify="right")
        for ticker, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
            table.add_row(str(ticker), f"{float(weight) * 100:.2f}%")
        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("history")
def portfolio_history() -> None:
    """Show portfolio transaction history."""
    from rich.table import Table

    try:
        transactions = do_portfolio_history()

        if not transactions:
            Console().print("[yellow]No transaction history[/yellow]")
            return

        table = Table(title="Transaction History")
        table.add_column("Date", style="dim")
        table.add_column("Action", style="bold")
        table.add_column("Ticker")
        table.add_column("Shares", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Value", justify="right")
        table.add_column("G/L", justify="right")

        for t in transactions:
            # t has: timestamp, action, ticker, shares, price, gain_loss (optional)
            action = t["action"].upper()
            action_color = "green" if action in ("ADD", "BUY") else "red"

            ts = t["timestamp"][:16].replace("T", " ")  # YYYY-MM-DD HH:MM
            ticker = t["ticker"]
            shares = t["shares"]
            price = t["price"]
            value = shares * price
            gain_loss = t.get("gain_loss")

            gl_str = "-"
            if gain_loss is not None:
                color = "green" if gain_loss >= 0 else "red"
                gl_str = f"[{color}]${gain_loss:.2f}[/{color}]"

            table.add_row(
                ts,
                f"[{action_color}]{action}[/{action_color}]",
                ticker,
                f"{shares:.2f}",
                f"${price:.2f}",
                f"${value:.2f}",
                gl_str,
            )

        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@research_app.command("log")
def research_log(
    title: str = typer.Argument(..., help="Short research title"),
    body: str = typer.Argument(..., help="Research note or thesis body"),
    tags: list[str] = typer.Option(None, "--tag", help="Repeatable tag"),
) -> None:
    """Append a research note to the local searchable log."""
    try:
        entry = do_research_log(title, body, tags=tags)
        Console().print(f"Logged research: {entry['entry_id']}")
    except Exception as e:
        raise _exit_for_error(e)


@research_app.command("list")
def research_list(limit: int = typer.Option(20, "--limit", min=1, max=200)) -> None:
    """List recent research notes."""
    from rich.table import Table

    try:
        rows = do_research_list(limit=limit)
        if not rows:
            Console().print("[yellow]No research notes logged[/yellow]")
            return
        table = Table(title="Research Notes")
        table.add_column("Created", style="dim")
        table.add_column("ID", style="cyan")
        table.add_column("Title")
        table.add_column("Tags")
        for row in rows:
            table.add_row(
                str(row.get("created_at", ""))[:19],
                str(row.get("entry_id", "")),
                str(row.get("title", "")),
                ", ".join(str(t) for t in (row.get("tags") or [])),
            )
        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@research_app.command("search")
def research_search(
    query: str = typer.Argument(..., help="Text to search for"),
    limit: int = typer.Option(20, "--limit", min=1, max=200),
) -> None:
    """Search local research notes."""
    from rich.table import Table

    try:
        rows = do_research_search(query, limit=limit)
        if not rows:
            Console().print("[yellow]No matching research notes[/yellow]")
            return
        table = Table(title=f"Research Search: {query}")
        table.add_column("Created", style="dim")
        table.add_column("ID", style="cyan")
        table.add_column("Title")
        table.add_column("Excerpt")
        for row in rows:
            body = str(row.get("body", ""))
            table.add_row(str(row.get("created_at", ""))[:19], str(row.get("entry_id", "")), str(row.get("title", "")), body[:80])
        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@paper_app.command("init")
def paper_init(
    cash: float = typer.Option(10000.0, "--cash", help="Initial cash balance"),
) -> None:
    """Initialize paper trading portfolio."""
    from stonks_cli.portfolio.paper import init_paper_portfolio

    try:
        p = init_paper_portfolio(starting_cash=cash)
        Console().print(f"Initialized paper portfolio with ${p.cash_balance:.2f} cash")
    except Exception as e:
        raise _exit_for_error(e)


@paper_app.command("buy")
def paper_buy_cmd(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    shares: float = typer.Argument(..., help="Number of shares"),
) -> None:
    """Buy shares in paper portfolio."""
    from stonks_cli.commands import do_paper_buy

    try:
        res = do_paper_buy(ticker, shares)
        # Res: ticker, shares, price, total_cost, cash_remaining

        Console().print(
            f"Bought {res['shares']} {res['ticker']} @ ${res['price']:.2f} "
            f"(${res['total_cost']:.2f} total). "
            f"Cash remaining: ${res['cash_remaining']:.2f}"
        )
    except Exception as e:
        raise _exit_for_error(e)


@paper_app.command("sell")
def paper_sell_cmd(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    shares: float = typer.Argument(..., help="Number of shares"),
) -> None:
    """Sell shares from paper portfolio."""
    from stonks_cli.commands import do_paper_sell

    try:
        res = do_paper_sell(ticker, shares)
        color = "green" if res["gain_loss"] >= 0 else "red"

        Console().print(
            f"Sold {res['shares']} {res['ticker']} @ ${res['price']:.2f} "
            f"(${res['proceeds']:.2f} total). "
            f"Cash remaining: ${res['cash_remaining']:.2f}"
        )
        Console().print(
            f"Realized Gain/Loss: [{color}]${res['gain_loss']:.2f} ({res['gain_loss_pct']:+.2f}%)[/{color}]"
        )
    except Exception as e:
        raise _exit_for_error(e)


@paper_app.command("status")
def paper_status() -> None:
    """Show paper portfolio status."""
    from rich.table import Table

    from stonks_cli.commands import do_paper_status

    try:
        status = do_paper_status()

        Console().print(f"Cash Balance: ${status['cash_balance']:.2f}")

        # Positions Table
        if status["positions"]:
            table = Table(title="Positions")
            table.add_column("Ticker", style="cyan")
            table.add_column("Shares", justify="right")
            table.add_column("Price", justify="right")
            table.add_column("Value", justify="right")
            table.add_column("G/L", justify="right")

            for p in status["positions"]:
                gl_color = "green" if p["gain_loss"] >= 0 else "red"
                table.add_row(
                    p["ticker"],
                    f"{p['shares']:.2f}",
                    f"${p['current_price']:.2f}",
                    f"${p['market_value']:.2f}",
                    f"[{gl_color}]${p['gain_loss']:.2f} ({p['gain_loss_pct']:+.2f}%)[/{gl_color}]",
                )
            Console().print(table)
        else:
            Console().print("[yellow]No open positions[/yellow]")

        pl_color = "green" if status["overall_pl"] >= 0 else "red"
        Console().print(f"Total Portfolio Value: ${status['total_portfolio_value']:.2f}")
        Console().print(
            f"Overall P&L: [{pl_color}]${status['overall_pl']:.2f} ({status['overall_pl_pct']:+.2f}%)[/{pl_color}]"
        )

    except Exception as e:
        raise _exit_for_error(e)


@paper_app.command("reset")
def paper_reset(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Reset paper trading portfolio."""
    from stonks_cli.portfolio.paper import get_paper_history_path, get_paper_portfolio_path

    if not force:
        typer.confirm(
            "Are you sure you want to reset your paper portfolio? This will delete all data.",
            abort=True,
        )

    p_path = get_paper_portfolio_path()
    h_path = get_paper_history_path()

    if p_path.exists():
        p_path.unlink()
    if h_path.exists():
        h_path.unlink()

    Console().print("[green]Paper portfolio reset successfully.[/green]")


@paper_app.command("leaderboard")
def paper_leaderboard() -> None:
    """Show paper trading performance metrics."""
    from rich.table import Table

    from stonks_cli.commands import do_paper_leaderboard

    try:
        metrics = do_paper_leaderboard()

        table = Table(title="Performance Metrics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        color = "green" if metrics["total_return_pct"] >= 0 else "red"
        table.add_row("Total Return %", f"[{color}]{metrics['total_return_pct']:+.2f}%[/{color}]")
        table.add_row("Sharpe Ratio (Trade)", f"{metrics['sharpe_ratio']:.2f}")
        table.add_row("Max Drawdown", f"{metrics['max_drawdown'] * 100:.2f}%")
        table.add_row("Trades", str(metrics["num_trades"]))
        table.add_row("Win Rate", f"{metrics['win_rate']:.1f}%")

        Console().print(table)

    except Exception as e:
        raise _exit_for_error(e)


@alert_app.command("add")
def alert_add(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    condition: str = typer.Argument(
        ...,
        help="Condition type (price-above, price-below, rsi-above, rsi-below, golden-cross, death-cross, new-high-52w, new-low-52w, volume-spike, earnings-soon)",
    ),
    threshold: float = typer.Argument(None, help="Threshold value (not required for cross/52w alerts)"),
) -> None:
    """Add a new alert."""
    from stonks_cli.commands import do_alert_add

    try:
        # Normalize condition to use underscores
        cond_normalized = condition.replace("-", "_")

        # Conditions that don't require a threshold
        no_threshold_conditions = {"golden_cross", "death_cross", "new_high_52w", "new_low_52w"}

        if cond_normalized in no_threshold_conditions:
            final_threshold = threshold if threshold is not None else 0.0
        else:
            if threshold is None:
                # Default for volume-spike is 2.0x
                if cond_normalized == "volume_spike":
                    final_threshold = 2.0
                else:
                    Console().print(f"[red]Threshold required for condition: {condition}[/red]")
                    raise typer.Exit(code=1)
            else:
                final_threshold = threshold

        alert = do_alert_add(ticker, cond_normalized, final_threshold)

        # Format confirmation message
        condition_str = cond_normalized.replace("_", " ")
        if cond_normalized in no_threshold_conditions:
            msg_val = ""
        elif "rsi" in cond_normalized:
            msg_val = f" {final_threshold:.1f}"
        elif cond_normalized == "volume_spike":
            msg_val = f" {final_threshold:.1f}x"
        elif cond_normalized == "earnings_soon":
            msg_val = f" {int(final_threshold)} days"
        else:
            msg_val = f" ${final_threshold:.2f}"

        Console().print(f"Alert created: {alert['ticker']} {condition_str}{msg_val} (ID: {alert['id'][:6]})")
    except Exception as e:
        raise _exit_for_error(e)


@alert_app.command("list")
def alert_list() -> None:
    """List all alerts."""
    from rich.table import Table

    from stonks_cli.commands import do_alert_list

    try:
        alerts = do_alert_list()
        if not alerts:
            Console().print("[yellow]No alerts configured[/yellow]")
            return

        table = Table(title="Active Alerts")
        table.add_column("ID", style="dim", width=8)
        table.add_column("Ticker", style="bold")
        table.add_column("Condition")
        table.add_column("Threshold", justify="right")
        table.add_column("Status")
        table.add_column("Created", style="dim")

        for a in alerts:
            cond = a["condition_type"].replace("_", " ")
            thr = a["threshold"]
            # Formatting threshold based on condition
            if "rsi" in a["condition_type"]:
                val_str = f"{thr:.1f}"
            else:
                val_str = f"${thr:.2f}"

            status = []
            if a["enabled"]:
                status.append("[green]enabled[/green]")
            else:
                status.append("[dim]disabled[/dim]")

            if a.get("triggered_at"):
                status.append("[red]TRIGGERED[/red]")

            created = a["created_at"][:10]  # Just date

            table.add_row(a["id"][:6], a["ticker"], cond, val_str, ", ".join(status), created)

        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@alert_app.command("remove")
def alert_remove(
    alert_id: str = typer.Argument(..., help="Alert ID (or prefix)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Remove an alert."""
    from stonks_cli.commands import do_alert_list, do_alert_remove

    try:
        # Resolve prefix
        alerts = do_alert_list()
        matches = [a for a in alerts if a["id"].startswith(alert_id)]

        if len(matches) == 0:
            Console().print(f"[red]No alert found with ID prefix: {alert_id}[/red]")
            raise typer.Exit(code=1)

        if len(matches) > 1:
            Console().print(f"[red]Multiple alerts match prefix {alert_id}. Be more specific.[/red]")
            raise typer.Exit(code=1)

        target = matches[0]

        if not force:
            typer.confirm(
                f"Remove alert {target['id'][:6]} ({target['ticker']} {target['condition_type']} {target['threshold']})?",
                abort=True,
            )

        if do_alert_remove(target["id"]):
            Console().print(f"Removed alert: {target['id'][:6]}")
        else:
            Console().print("[red]Failed to remove alert[/red]")

    except Exception as e:
        raise _exit_for_error(e)


@alert_app.command("enable")
def alert_enable(
    alert_id: str = typer.Argument(..., help="Alert ID (or prefix)"),
) -> None:
    """Enable an alert."""
    _toggle_alert(alert_id, True)


@alert_app.command("disable")
def alert_disable(
    alert_id: str = typer.Argument(..., help="Alert ID (or prefix)"),
) -> None:
    """Disable an alert."""
    _toggle_alert(alert_id, False)


def _toggle_alert(alert_id: str, enabled: bool) -> None:
    from stonks_cli.commands import do_alert_list, do_alert_toggle

    try:
        # Resolve prefix
        alerts = do_alert_list()
        matches = [a for a in alerts if a["id"].startswith(alert_id)]

        if len(matches) == 0:
            Console().print(f"[red]No alert found with ID prefix: {alert_id}[/red]")
            raise typer.Exit(code=1)

        if len(matches) > 1:
            Console().print(f"[red]Multiple alerts match prefix {alert_id}. Be more specific.[/red]")
            raise typer.Exit(code=1)

        target = matches[0]
        result = do_alert_toggle(target["id"], enabled)

        if result:
            status = "enabled" if enabled else "disabled"
            color = "green" if enabled else "yellow"
            Console().print(f"Alert {result['id'][:6]} [{color}]{status}[/{color}]")
        else:
            Console().print("[red]Failed to update alert[/red]")

    except Exception as e:
        raise _exit_for_error(e)


@alert_app.command("check")
def alert_check() -> None:
    """Check all alerts and trigger notifications for conditions met."""
    from stonks_cli.commands import do_alert_check

    try:
        triggered = do_alert_check()

        if not triggered:
            Console().print("[green]No alerts triggered[/green]")
            return

        Console().print(f"[bold red]{len(triggered)} alert(s) triggered![/bold red]")
        for a in triggered:
            cond = a["condition_type"].replace("_", " ")
            Console().print(f"  • {a['ticker']} {cond} {a['threshold']}")

    except Exception as e:
        raise _exit_for_error(e)


@dividend_app.command("info")
def dividend_info(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
) -> None:
    """Display dividend information for a ticker."""
    from datetime import date

    from rich.panel import Panel
    from rich.table import Table

    from stonks_cli.commands import do_dividend_info

    try:
        info = do_dividend_info(ticker)
        console = Console()

        # Build info panel content
        lines = []

        if info.get("dividend_yield") is not None:
            lines.append(f"[bold]Dividend Yield:[/bold] {info['dividend_yield']:.2f}%")
        else:
            lines.append("[bold]Dividend Yield:[/bold] N/A")

        if info.get("annual_dividend") is not None:
            lines.append(f"[bold]Annual Payment:[/bold] ${info['annual_dividend']:.2f}")
        else:
            lines.append("[bold]Annual Payment:[/bold] N/A")

        if info.get("payout_ratio") is not None:
            lines.append(f"[bold]Payout Ratio:[/bold] {info['payout_ratio']:.1f}%")
        else:
            lines.append("[bold]Payout Ratio:[/bold] N/A")

        # Ex-date countdown
        if info.get("ex_dividend_date"):
            try:
                ex_date = date.fromisoformat(info["ex_dividend_date"])
                days_until = (ex_date - date.today()).days
                if days_until >= 0:
                    lines.append(f"[bold]Ex-Dividend Date:[/bold] {info['ex_dividend_date']} ({days_until} days)")
                else:
                    lines.append(f"[bold]Last Ex-Date:[/bold] {info['ex_dividend_date']} ({abs(days_until)} days ago)")
            except Exception:
                lines.append(f"[bold]Ex-Dividend Date:[/bold] {info['ex_dividend_date']}")

        if info.get("next_dividend_date"):
            lines.append(f"[bold]Next Dividend (est):[/bold] {info['next_dividend_date']}")

        console.print(
            Panel("\n".join(lines), title=f"[bold cyan]{info.get('ticker', ticker).upper()} Dividend Info[/bold cyan]")
        )

        # History table
        history = info.get("dividend_history", [])
        if history:
            table = Table(title="Dividend History (Last 8)")
            table.add_column("Ex-Date", style="dim")
            table.add_column("Amount", justify="right")

            for h in history:
                table.add_row(
                    h.get("ex_date", "N/A"),
                    f"${h.get('amount', 0):.4f}",
                )

            console.print(table)
        else:
            console.print("[yellow]No dividend history available[/yellow]")

    except Exception as e:
        raise _exit_for_error(e)


@dividend_app.command("calendar")
def dividend_calendar(
    days: int = typer.Option(30, "--days", "-d", help="Number of days to look ahead"),
) -> None:
    """Display upcoming ex-dividend dates from watchlist tickers."""
    from rich.table import Table

    from stonks_cli.commands import do_dividend_calendar

    try:
        results = do_dividend_calendar(days=days)
        console = Console()

        if not results:
            console.print(f"[yellow]No ex-dividend dates found in the next {days} days[/yellow]")
            return

        table = Table(title=f"Upcoming Ex-Dividend Dates (Next {days} Days)")
        table.add_column("Days", justify="right", style="bold")
        table.add_column("Ex-Date")
        table.add_column("Ticker", style="cyan")
        table.add_column("Amount", justify="right")

        for r in results:
            days_until = r["days_until"]
            if days_until == 0:
                days_str = "[red]TODAY[/red]"
            elif days_until == 1:
                days_str = "[yellow]1[/yellow]"
            else:
                days_str = str(days_until)

            amount_str = f"${r['amount']:.4f}" if r.get("amount") else "N/A"

            table.add_row(
                days_str,
                r["ex_date"],
                r["ticker"],
                amount_str,
            )

        console.print(table)

    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def snapshot(
    tickers: list[str] = typer.Argument(None, help="Optional ticker override list"),
    unusual_threshold: float = typer.Option(2.0, "--unusual-threshold", min=1.0),
    movers_limit: int = typer.Option(4, "--movers-limit", min=1, max=20),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output"),
) -> None:
    """Show one-command market snapshot for configured tickers."""
    import json

    from rich.table import Table

    from stonks_cli.commands import do_market_snapshot

    try:
        snapshot_payload = do_market_snapshot(
            tickers if tickers else None,
            unusual_threshold=unusual_threshold,
            top_movers_limit=movers_limit,
        )
        console = Console()

        if as_json:
            console.print(json.dumps(snapshot_payload, indent=2))
            return

        alerts = snapshot_payload.get("alerts") or {}
        generated_at = snapshot_payload.get("generated_at")
        console.print(
            f"generated_at: {generated_at} | alerts enabled: {alerts.get('enabled', 0)} | triggered: {alerts.get('triggered', 0)}"
        )

        tickers_table = Table(title="Snapshot Tickers")
        tickers_table.add_column("Ticker", style="cyan")
        tickers_table.add_column("Price", justify="right")
        tickers_table.add_column("Change", justify="right")
        tickers_table.add_column("Action")
        tickers_table.add_column("Conf", justify="right")
        tickers_table.add_column("Freshness", justify="right")

        for row in snapshot_payload.get("tickers") or []:
            price = row.get("price")
            change_pct = row.get("change_pct")
            age_days = row.get("data_age_days")
            stale = bool(row.get("stale"))

            price_str = "-" if price is None else f"${float(price):.2f}"
            if change_pct is None:
                change_str = "-"
            else:
                change_f = float(change_pct)
                if change_f >= 0:
                    change_str = f"[green]+{change_f:.2f}%[/green]"
                else:
                    change_str = f"[red]{change_f:.2f}%[/red]"
            if age_days is None:
                fresh_str = "-"
            else:
                base = f"{int(age_days)}d"
                fresh_str = f"[red]{base}[/red]" if stale else base

            tickers_table.add_row(
                str(row.get("ticker")),
                price_str,
                change_str,
                str(row.get("action")),
                f"{float(row.get('confidence') or 0.0):.2f}",
                fresh_str,
            )
        console.print(tickers_table)

        movers = snapshot_payload.get("top_movers") or []
        if movers:
            movers_table = Table(title="Top Movers")
            movers_table.add_column("Ticker", style="cyan")
            movers_table.add_column("Name")
            movers_table.add_column("%", justify="right")
            for m in movers:
                pct = float(m.get("change_pct") or 0.0)
                pct_str = f"[green]+{pct:.2f}%[/green]" if pct >= 0 else f"[red]{pct:.2f}%[/red]"
                movers_table.add_row(str(m.get("ticker")), str(m.get("name")), pct_str)
            console.print(movers_table)

        unusual = snapshot_payload.get("unusual_volume") or []
        console.print(f"unusual_volume_hits: {len(unusual)} (threshold={unusual_threshold}x)")

        signals = snapshot_payload.get("signals_diff")
        if signals:
            console.print(f"signals_diff_changes: {signals.get('count')}")
        else:
            console.print("signals_diff_changes: unavailable")

        for note in snapshot_payload.get("notes") or []:
            console.print(f"[yellow]note:[/yellow] {note}")

    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def movers(
    sector: bool = typer.Option(False, "--sector", "-s", help="Show sector ETF performance instead of indices"),
) -> None:
    """Display daily performance of major indices or sector ETFs."""
    from rich.table import Table

    from stonks_cli.commands import do_movers

    try:
        results = do_movers(sector=sector)
        console = Console()

        if not results:
            console.print("[yellow]No market data available[/yellow]")
            return

        title = "Sector Performance" if sector else "Market Movers"
        table = Table(title=title)
        table.add_column("Ticker", style="cyan")
        table.add_column("Name")
        table.add_column("Price", justify="right")
        table.add_column("Change", justify="right")
        table.add_column("%", justify="right")

        for r in results:
            pct = r["change_pct"]
            if pct >= 0:
                change_str = f"[green]+${r['change']:.2f}[/green]"
                pct_str = f"[green]+{pct:.2f}%[/green]"
            else:
                change_str = f"[red]-${abs(r['change']):.2f}[/red]"
                pct_str = f"[red]{pct:.2f}%[/red]"

            table.add_row(
                r["ticker"],
                r["name"],
                f"${r['price']:.2f}",
                change_str,
                pct_str,
            )

        console.print(table)

    except Exception as e:
        raise _exit_for_error(e)


@app.command(hidden=True)
def unusual(
    threshold: float = typer.Option(2.0, "--threshold", "-t", help="Volume multiple threshold (default 2.0x)"),
) -> None:
    """Scan watchlist for unusual volume activity."""
    from rich.table import Table

    from stonks_cli.commands import do_unusual

    try:
        results = do_unusual(threshold=threshold)
        console = Console()

        if not results:
            console.print(f"[green]No unusual volume activity detected (>{threshold}x avg)[/green]")
            return

        table = Table(title=f"Unusual Volume Activity (>{threshold}x avg)")
        table.add_column("Ticker", style="cyan")
        table.add_column("Volume", justify="right")
        table.add_column("Avg Vol", justify="right")
        table.add_column("Multiple", justify="right", style="bold")
        table.add_column("Price", justify="right")
        table.add_column("Change", justify="right")

        def format_volume(vol: float) -> str:
            if vol >= 1_000_000:
                return f"{vol / 1_000_000:.1f}M"
            elif vol >= 1_000:
                return f"{vol / 1_000:.1f}K"
            return str(int(vol))

        for r in results:
            pct = r["change_pct"]
            if pct >= 0:
                pct_str = f"[green]+{pct:.2f}%[/green]"
            else:
                pct_str = f"[red]{pct:.2f}%[/red]"

            table.add_row(
                r["ticker"],
                format_volume(r["current_volume"]),
                format_volume(r["avg_volume"]),
                f"{r['multiple']:.1f}x",
                f"${r['price']:.2f}",
                pct_str,
            )

        console.print(table)

    except Exception as e:
        raise _exit_for_error(e)


def main() -> None:
    app()
