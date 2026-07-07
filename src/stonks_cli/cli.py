from __future__ import annotations

import asyncio
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from stonks_cli.commands import (
    do_config_init,
    do_config_set,
    do_config_show,
    do_config_validate,
    do_config_where,
    do_doctor,
    do_version,
)
from stonks_cli.config import load_config
from stonks_cli.errors import ExitCodes, StonksError
from stonks_cli.legal_policy import enforce_legal_policy
from stonks_cli.logging_utils import LoggingConfig, configure_logging
from stonks_cli.whalemirror.attribution import (
    DEFAULT_ATTRIBUTION_FIXTURE,
    rank_wallets_from_fixture,
    render_wallet_ranking_markdown,
)
from stonks_cli.whalemirror.capture_analysis import analyze_capture_archive
from stonks_cli.whalemirror.carry_health import build_carry_health_report, render_carry_health_report
from stonks_cli.whalemirror.carry_live import CarryLivePreflightEvidence, evaluate_carry_live_preflight
from stonks_cli.whalemirror.carry_paper import PaperCarryConfig, run_paper_carry, write_paper_carry_artifacts
from stonks_cli.whalemirror.carry_scanner import (
    CarryCostAssumptions,
    CarryScanRow,
    load_carry_inputs_fixture,
    scan_hyperliquid_carry,
)
from stonks_cli.whalemirror.hyperliquid import HYPERLIQUID_WS_URL, HyperliquidOrderClient
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
    record_live_evidence,
    record_live_probe,
    record_paper_evidence,
    record_paper_probe,
    render_gate_report,
    write_gate_report,
)

app = typer.Typer(add_completion=True, help="WhaleMirror Hyperliquid paper-first observability CLI.")
carry_app = typer.Typer(help="CarryMirror funding and basis scanner commands.")
carry_live_app = typer.Typer(help="CarryMirror fail-closed tiny-live safety commands.")
carry_paper_app = typer.Typer(help="CarryMirror paper carry simulation commands.")
config_app = typer.Typer()
whalemirror_app = typer.Typer(help="WhaleMirror Hyperliquid paper-first commands.")
whalemirror_gates_app = typer.Typer(help="Restartable validation gate harnesses.")
whalemirror_ingest_app = typer.Typer(help="Hyperliquid ingestion fixture and capture commands.")
whalemirror_paper_app = typer.Typer(help="Paper mirror replay and risk-control commands.")
whalemirror_wallets_app = typer.Typer(help="Venue-neutral wallet attribution commands.")

app.add_typer(carry_app, name="carry")
carry_app.add_typer(carry_live_app, name="live")
carry_app.add_typer(carry_paper_app, name="paper")
app.add_typer(config_app, name="config")
app.add_typer(whalemirror_app, name="whalemirror")
whalemirror_app.add_typer(whalemirror_gates_app, name="gates")
whalemirror_app.add_typer(whalemirror_ingest_app, name="ingest")
whalemirror_app.add_typer(whalemirror_paper_app, name="paper")
whalemirror_app.add_typer(whalemirror_wallets_app, name="wallets")


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


@config_app.command("where")
def config_where() -> None:
    """Show config file path."""
    try:
        Console().print(str(do_config_where()))
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("init")
def config_init(
    path: Path | None = typer.Option(None, "--path", help="Override config file path"),
) -> None:
    """Create a default config file."""
    try:
        Console().print(f"Config written to {do_config_init(path)}")
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("show")
def config_show() -> None:
    """Print current config as JSON."""
    try:
        Console().print_json(do_config_show())
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("set")
def config_set(
    field: str = typer.Argument(..., help="Dotted config path (e.g., schedule.cron)"),
    value: str = typer.Argument(..., help="New value"),
) -> None:
    """Set a config field."""
    try:
        Console().print_json(do_config_set(field, value))
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("validate")
def config_validate() -> None:
    """Validate current config."""
    try:
        Console().print_json(json.dumps(do_config_validate()))
    except Exception as e:
        raise _exit_for_error(e)


# --- CarryMirror commands ---


@carry_app.command("health")
def carry_health(
    state_dir: Path = typer.Option(Path(".cache/carry-paper"), "--state-dir"),
    ledger: Path = typer.Option(Path(".cache/carry-paper/ledger.md"), "--ledger"),
    stream_heartbeat: Path | None = typer.Option(None, "--stream-heartbeat"),
    reconciliation: Path | None = typer.Option(None, "--reconciliation"),
    json_output: bool = typer.Option(False, "--json/--table"),
    skip_network: bool = typer.Option(False, "--skip-network", help="Skip network and venue API checks"),
    max_stream_age_seconds: float = typer.Option(120.0, "--max-stream-age-seconds", min=0.0),
) -> None:
    """Check CarryMirror Pi paper-run host and artifact health."""
    try:
        report = build_carry_health_report(
            cfg=load_config(),
            state_dir=state_dir,
            ledger_path=ledger,
            stream_heartbeat_path=stream_heartbeat,
            reconciliation_path=reconciliation,
            skip_network=skip_network,
            max_stream_age_seconds=max_stream_age_seconds,
        )
        console = Console()
        if json_output:
            console.print_json(json.dumps(report.to_dict()))
        else:
            console.print(render_carry_health_report(report))
    except Exception as e:
        raise _exit_for_error(e)


@carry_app.command("scan")
def carry_scan(
    venue: str = typer.Option("hyperliquid", "--venue", help="Carry venue; currently hyperliquid only"),
    paper: bool = typer.Option(True, "--paper/--no-paper", help="Paper scanner mode; live scan is blocked"),
    assets: list[str] = typer.Option(None, "--asset", help="Repeatable asset; defaults to BTC and ETH"),
    fixture: Path | None = typer.Option(None, "--fixture", exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json/--table", help="Emit JSON instead of a rich table"),
    now: str | None = typer.Option(None, "--now", help="UTC timestamp for deterministic fixture scans"),
    fee_bps: float = typer.Option(4.0, "--fee-bps", min=0.0),
    slippage_bps: float = typer.Option(5.0, "--slippage-bps", min=0.0),
    rebalance_bps: float = typer.Option(5.0, "--rebalance-bps", min=0.0),
    borrow_bps: float = typer.Option(0.0, "--borrow-bps", min=0.0),
    volatility_buffer_bps: float = typer.Option(25.0, "--volatility-buffer-bps", min=0.0),
) -> None:
    """Scan BTC/ETH Hyperliquid carry opportunities without placing orders."""
    try:
        cfg = load_config()
        enforce_legal_policy(cfg, venue_id=venue, strategy_class="carry_funding_basis")
        if venue != "hyperliquid":
            raise ValueError("carry scan currently supports --venue hyperliquid only")
        if not paper:
            raise ValueError("carry scan is paper-only; --no-paper is not supported")
        assumptions = CarryCostAssumptions(
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            rebalance_bps=rebalance_bps,
            borrow_bps=borrow_bps,
            volatility_buffer_bps=volatility_buffer_bps,
        )
        source_inputs = load_carry_inputs_fixture(fixture) if fixture else None
        rows = scan_hyperliquid_carry(
            cfg=cfg,
            inputs=source_inputs,
            assets=tuple(assets or ("BTC", "ETH")),
            assumptions=assumptions,
            now=_parse_cli_time(now) if now else None,
        )
        payload = {
            "venue": venue,
            "paper": True,
            "min_net_apr": cfg.carrymirror.min_net_apr,
            "rows": [row.to_dict() for row in rows],
        }
        console = Console()
        if json_output:
            console.print_json(json.dumps(payload))
        else:
            console.print(_render_carry_scan_table(rows))
    except Exception as e:
        raise _exit_for_error(e)


@carry_live_app.command("preflight")
def carry_live_preflight(
    paper_gate_passed: bool = typer.Option(False, "--paper-gate-passed"),
    legal_review_recorded: bool = typer.Option(False, "--legal-review-recorded"),
    venue_health_ok: bool = typer.Option(False, "--venue-health-ok"),
    manual_cap_confirmed: bool = typer.Option(False, "--manual-cap-confirmed"),
    requested_notional_usd: float = typer.Option(0.0, "--requested-notional-usd", min=0.0),
    cap_usd: float = typer.Option(0.0, "--cap-usd", min=0.0),
    secrets_path: Path | None = typer.Option(None, "--secrets-path"),
) -> None:
    """Report tiny-live preflight blockers without placing orders."""
    try:
        result = evaluate_carry_live_preflight(
            cfg=load_config(),
            evidence=CarryLivePreflightEvidence(
                paper_gate_passed=paper_gate_passed,
                legal_review_recorded=legal_review_recorded,
                venue_health_ok=venue_health_ok,
                manual_cap_confirmed=manual_cap_confirmed,
                requested_notional_usd=requested_notional_usd,
                cap_usd=cap_usd,
                secrets_path=str(secrets_path) if secrets_path else None,
            ),
        )
        Console().print_json(json.dumps(result.to_dict()))
    except Exception as e:
        raise _exit_for_error(e)


def _render_carry_scan_table(rows: list[CarryScanRow]) -> Table:
    table = Table(title="CarryMirror scan")
    table.add_column("Asset", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Direction", no_wrap=True)
    table.add_column("Gross APR", justify="right")
    table.add_column("Net APR", justify="right")
    table.add_column("Costs", justify="right")
    table.add_column("Missing/Caveats")
    table.add_column("Source Health")
    for row in rows:
        opportunity = row.opportunity
        table.add_row(
            opportunity.asset,
            row.status,
            opportunity.direction,
            _pct(opportunity.gross_apr),
            _pct(opportunity.net_apr),
            _pct(row.cost_assumptions.total_cost_apr),
            ", ".join(opportunity.required_fields_missing) or "-",
            ", ".join(f"{k}={v}" for k, v in sorted(row.source_health.items())) or "-",
        )
    return table


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _parse_cli_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@carry_paper_app.command("run")
def carry_paper_run(
    venue: str = typer.Option("hyperliquid", "--venue", help="Carry venue; currently hyperliquid only"),
    paper: bool = typer.Option(True, "--paper/--no-paper", help="Paper mode; live execution is blocked"),
    assets: list[str] = typer.Option(None, "--asset", help="Repeatable asset; defaults to BTC and ETH"),
    fixture: Path | None = typer.Option(None, "--fixture", exists=True, readable=True),
    duration_hours: float = typer.Option(24.0, "--duration-hours", min=0.0),
    state_dir: Path = typer.Option(Path(".cache/carry-paper"), "--state-dir"),
    report: Path = typer.Option(Path(".cache/carry-paper/report.md"), "--report"),
    ledger: Path = typer.Option(Path(".cache/carry-paper/ledger.md"), "--ledger"),
    bankroll_usd: float = typer.Option(1000.0, "--bankroll-usd", min=0.0),
    position_notional_usd: float = typer.Option(100.0, "--position-notional-usd", min=0.0),
    maker_fee_bps: float = typer.Option(2.0, "--maker-fee-bps", min=0.0),
    taker_fee_bps: float = typer.Option(5.0, "--taker-fee-bps", min=0.0),
    slippage_bps: float = typer.Option(3.0, "--slippage-bps", min=0.0),
    missed_fill_probability: float = typer.Option(0.0, "--missed-fill-probability", min=0.0, max=1.0),
) -> None:
    """Run a paper-only delta-neutral carry simulation."""
    try:
        cfg = load_config()
        enforce_legal_policy(cfg, venue_id=venue, strategy_class="carry_funding_basis")
        if venue != "hyperliquid":
            raise ValueError("carry paper currently supports --venue hyperliquid only")
        if not paper:
            raise ValueError("carry paper is paper-only; --no-paper is not supported")
        source_inputs = (
            load_carry_inputs_fixture(fixture)
            if fixture
            else HyperliquidOrderClient().fetch_carry_inputs(assets=tuple(assets or ("BTC", "ETH")))
        )
        result = run_paper_carry(
            inputs=source_inputs,
            min_net_apr=cfg.carrymirror.min_net_apr,
            config=PaperCarryConfig(
                bankroll_usd=bankroll_usd,
                position_notional_usd=position_notional_usd,
                maker_fee_bps=maker_fee_bps,
                taker_fee_bps=taker_fee_bps,
                slippage_bps=slippage_bps,
                missed_fill_probability=missed_fill_probability,
            ),
        )
        paths = write_paper_carry_artifacts(result=result, state_dir=state_dir, report_path=report, ledger_path=ledger)
        Console().print_json(
            json.dumps(
                {
                    "duration_hours": duration_hours,
                    "paper": True,
                    "venue": venue,
                    **paths,
                    "summary": {
                        "open_positions": len(result.state.positions),
                        "closed_positions": len(result.state.closed_positions),
                        "decisions": len(result.state.decisions),
                    },
                }
            )
        )
    except Exception as e:
        raise _exit_for_error(e)


# --- WhaleMirror commands ---

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


@whalemirror_ingest_app.command("analyze")
def whalemirror_ingest_analyze(
    capture_dir: Path = typer.Option(..., "--capture-dir", exists=True, file_okay=False, readable=True),
    raw: Path | None = typer.Option(None, "--raw", exists=True, dir_okay=False, readable=True),
    normalized: Path | None = typer.Option(None, "--normalized", exists=True, dir_okay=False, readable=True),
    health: Path | None = typer.Option(None, "--health", exists=True, dir_okay=False, readable=True),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False),
    target_seconds: float = typer.Option(float(DEFAULT_LIVE_CAPTURE_SECONDS), "--target-seconds", min=1.0),
    top_limit: int = typer.Option(20, "--top-limit", min=1, max=100),
) -> None:
    """Analyze an archived partial live capture without treating it as gate-passing evidence."""
    try:
        result = analyze_capture_archive(
            capture_dir=capture_dir,
            raw_path=raw,
            normalized_path=normalized,
            health_path=health,
            output_dir=output_dir,
            target_seconds=target_seconds,
            top_limit=top_limit,
        )
        summary = dict(result["summary"])
        summary.pop("raw", None)
        summary.pop("normalized", None)
        Console().print_json(
            json.dumps(
                {
                    "analysis_json_path": result["analysis_json_path"],
                    "analysis_report_path": result["analysis_report_path"],
                    "executive_summary_path": result["executive_summary_path"],
                    "summary": summary,
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


@whalemirror_gates_app.command("paper-record")
def whalemirror_gates_paper_record(
    evidence: Path = typer.Option(..., "--evidence", exists=True, dir_okay=False, readable=True),
    state_dir: Path = typer.Option(default_validation_dir(), "--state-dir"),
    report: Path = typer.Option(Path(".cache/whalemirror-gates/paper-gate.md"), "--report"),
    reset: bool = typer.Option(False, "--reset", help="Start a fresh #14 gate state before recording evidence"),
) -> None:
    """Record operator-produced #14 Linux paper-run evidence."""
    try:
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("paper evidence must be a JSON object")
        state = record_paper_evidence(state_dir=state_dir, paper_payload=payload, reset=reset)
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


@whalemirror_gates_app.command("live-record")
def whalemirror_gates_live_record(
    evidence: Path = typer.Option(..., "--evidence", exists=True, dir_okay=False, readable=True),
    state_dir: Path = typer.Option(default_validation_dir(), "--state-dir"),
    report: Path = typer.Option(Path(".cache/whalemirror-gates/live-gate.md"), "--report"),
    reset: bool = typer.Option(False, "--reset", help="Start a fresh #10 gate state before recording evidence"),
) -> None:
    """Record operator-produced #10 Linux live validation evidence."""
    try:
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("live evidence must be a JSON object")
        state = record_live_evidence(state_dir=state_dir, live_payload=payload, reset=reset)
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


def main() -> None:
    app()
