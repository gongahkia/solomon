from __future__ import annotations

import asyncio
import json
import platform
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from stonks_cli.carry.carry_health import build_carry_health_report, render_carry_health_report
from stonks_cli.carry.carry_live import CarryLivePreflightEvidence, evaluate_carry_live_preflight
from stonks_cli.carry.carry_paper import PaperCarryConfig, run_paper_carry, write_paper_carry_artifacts
from stonks_cli.carry.carry_scanner import (
    CarryCostAssumptions,
    CarryScanRow,
    load_carry_inputs_fixture,
    scan_hyperliquid_carry,
)
from stonks_cli.commands import (
    do_config_init,
    do_config_migrate,
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
from stonks_cli.research.attribution import (
    DEFAULT_ATTRIBUTION_FIXTURE,
    rank_wallets_from_fixture,
    render_wallet_ranking_markdown,
)
from stonks_cli.research.capture_analysis import analyze_capture_archive
from stonks_cli.research.hyperliquid import HYPERLIQUID_WS_URL, HyperliquidOrderClient
from stonks_cli.research.ingestion import (
    DEFAULT_CAPTURE_FIXTURE,
    DEFAULT_LIVE_CAPTURE_COINS,
    DEFAULT_LIVE_CAPTURE_SECONDS,
    build_live_capture_subscriptions,
    capture_hyperliquid_to_files,
    replay_capture_fixture,
    runtime_host_metadata,
    write_capture_jsonl,
)
from stonks_cli.research.ledger import (
    DEFAULT_LEDGER_PATH,
    DEFAULT_REPLAY_FIXTURE,
    DEFAULT_TEARSHEET_PATH,
    write_fixture_artifacts,
)
from stonks_cli.research.paper_analysis import (
    DEFAULT_PAPER_MIRROR_FIXTURE,
    PaperAnalysisConfig,
    replay_paper_analysis_fixture,
)
from stonks_cli.research.validation_gates import (
    CAPTURE_GATE,
    assess_gate,
    default_validation_dir,
    gate_state_path,
    load_gate_state,
    record_capture_health,
    record_capture_probe,
    render_gate_report,
    write_gate_report,
)
from stonks_cli.vnext.account_import import import_moomoo_accounts
from stonks_cli.vnext.broker_app_order_ticket import render_broker_app_order_ticket
from stonks_cli.vnext.crypto_universe_snapshot import load_crypto_universe_snapshot
from stonks_cli.vnext.data_confidence import DataConfidenceScore
from stonks_cli.vnext.errors import VNextConfigurationError
from stonks_cli.vnext.holdings_import import import_moomoo_holdings
from stonks_cli.vnext.market_data_refresh import refresh_moomoo_market_data
from stonks_cli.vnext.moomoo import MoomooAccount
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass, PortfolioHolding, PortfolioSnapshot
from stonks_cli.vnext.portfolio_exposure import PortfolioExposure
from stonks_cli.vnext.portfolio_risk_report import render_portfolio_risk_report
from stonks_cli.vnext.reviewed_order_ticket import OrderTicketSide, OrderTicketType, ReviewedOrderTicket
from stonks_cli.vnext.score_components import ScoreComponent
from stonks_cli.vnext.sgd_portfolio_nav import SGDPortfolioNAV
from stonks_cli.vnext.usd_portfolio_nav import USDPortfolioNAV
from stonks_cli.vnext.weighted_ranker import rank_weighted_assets

app = typer.Typer(add_completion=True, help="Stonks CLI paper-carry tools.")


@app.callback()
def _global_options(
    verbose: int = typer.Option(0, "--verbose", "-v", count=True, help="Increase logging verbosity"),
    quiet: bool = typer.Option(False, "--quiet", help="Only show errors"),
    structured_logs: bool = typer.Option(False, "--structured-logs", help="Emit JSON lines logs to stderr"),
) -> None:
    configure_logging(LoggingConfig(verbose=verbose, quiet=quiet, structured=structured_logs))


@app.command("universe-crypto")
def vnext_crypto_universe(
    snapshot: Path = typer.Option(..., "--snapshot", exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True),
) -> None:
    """Render a private persisted crypto-universe snapshot."""
    try:
        typer.echo(json.dumps(load_crypto_universe_snapshot(snapshot).to_data(), sort_keys=True))
    except Exception as error:
        raise _exit_for_error(error)


@app.command("refresh-market")
def vnext_market_refresh(
    symbols: list[str] = typer.Option(..., "--symbol", "-s", help="Canonical Moomoo symbol; repeat for each quote"),
) -> None:
    """Refresh pre-entitled Moomoo US and SG quotes without subscribing."""
    _render_moomoo_market_data_refresh(symbols)


@app.command("rank")
def vnext_ranking(
    components: Path = typer.Option(..., "--components", exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True),
) -> None:
    """Rank canonical local score components with configured vNext weights."""
    try:
        config = load_config()
        if not config.vnext.enabled or not config.vnext.features.crypto_research:
            raise VNextConfigurationError("vNext crypto-research ranking is not enabled")
        ranks = rank_weighted_assets(_load_score_components(components), config.vnext.research.factor_weights)
        typer.echo(json.dumps([asdict(rank) for rank in ranks], sort_keys=True))
    except Exception as error:
        raise _exit_for_error(error)


@app.command("report-daily")
def vnext_daily_report(
    report_input: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True),
) -> None:
    """Render a daily portfolio risk report from strict local input."""
    try:
        config = load_config()
        if not config.vnext.enabled or not config.vnext.features.operator_reports:
            raise VNextConfigurationError("vNext operator reports are not enabled")
        exposure, nav, confidence = _load_daily_report_inputs(report_input)
        typer.echo(f"DAILY REPORT\n{render_portfolio_risk_report(exposure, nav, confidence)}")
    except Exception as error:
        raise _exit_for_error(error)


@app.command("import-portfolio")
def vnext_portfolio_import(
    account_id: str = typer.Option(..., "--account-id"),
    account_index: int = typer.Option(..., "--account-index", min=0),
    trading_environment: str = typer.Option(..., "--trading-environment"),
    captured_at: str = typer.Option(..., "--captured-at", help="Timezone-aware ISO-8601 timestamp"),
) -> None:
    """Import a canonical read-only Moomoo holdings snapshot."""
    try:
        snapshot = import_moomoo_holdings(
            load_config(),
            MoomooAccount(account_id, account_index, trading_environment),
            datetime.fromisoformat(captured_at),
        )
        typer.echo(json.dumps(_portfolio_snapshot_to_data(snapshot), sort_keys=True))
    except Exception as error:
        raise _exit_for_error(error)


@app.command("show-portfolio")
def vnext_portfolio_show(
    snapshot: Path = typer.Option(..., "--snapshot", exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True),
) -> None:
    """Show a strict canonical portfolio snapshot without broker access."""
    try:
        typer.echo(json.dumps(_portfolio_snapshot_to_data(_load_portfolio_snapshot(snapshot)), sort_keys=True))
    except Exception as error:
        raise _exit_for_error(error)


@app.command("ticket-order")
def vnext_order_ticket(
    ticket_id: str = typer.Option(..., "--ticket-id"),
    account_id: str = typer.Option(..., "--account-id"),
    symbol: str = typer.Option(..., "--symbol"),
    side: OrderTicketSide = typer.Option(..., "--side"),
    quantity: float = typer.Option(..., "--quantity"),
    limit_price: float = typer.Option(..., "--limit-price"),
    currency: str = typer.Option(..., "--currency"),
    rationale: str = typer.Option(..., "--rationale"),
    prepared_at: str = typer.Option(..., "--prepared-at", help="Timezone-aware ISO-8601 timestamp"),
    reviewed_by: str = typer.Option(..., "--reviewed-by"),
    reviewed_at: str = typer.Option(..., "--reviewed-at", help="Timezone-aware ISO-8601 timestamp"),
) -> None:
    """Render a reviewed limit ticket for manual broker-app entry only."""
    try:
        ticket = ReviewedOrderTicket(
            ticket_id,
            account_id,
            symbol,
            side,
            OrderTicketType.LIMIT,
            quantity,
            limit_price,
            currency,
            rationale,
            datetime.fromisoformat(prepared_at),
            reviewed_by,
            datetime.fromisoformat(reviewed_at),
        )
        typer.echo(render_broker_app_order_ticket(ticket))
    except Exception as error:
        raise _exit_for_error(error)


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
    """Diagnose the local stonks-cli environment."""
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


@app.command("where-config")
def config_where() -> None:
    """Show config file path."""
    try:
        Console().print(str(do_config_where()))
    except Exception as e:
        raise _exit_for_error(e)


@app.command("init-config")
def config_init(
    path: Path | None = typer.Option(None, "--path", help="Override config file path"),
) -> None:
    """Create a default config file."""
    try:
        Console().print(f"Config written to {do_config_init(path)}")
    except Exception as e:
        raise _exit_for_error(e)


@app.command("migrate-config")
def config_migrate(
    path: Path | None = typer.Option(None, "--path", help="Override config file path"),
) -> None:
    """Migrate an existing config file to the current schema."""
    try:
        Console().print(f"Config migrated at {do_config_migrate(path)}")
    except Exception as e:
        raise _exit_for_error(e)


@app.command("show-config")
def config_show() -> None:
    """Print current config as JSON."""
    try:
        Console().print_json(do_config_show())
    except Exception as e:
        raise _exit_for_error(e)


@app.command("set-config")
def config_set(
    field: str = typer.Argument(..., help="Dotted config path (e.g., schedule.cron)"),
    value: str = typer.Argument(..., help="New value"),
) -> None:
    """Set a config field."""
    try:
        Console().print_json(do_config_set(field, value))
    except Exception as e:
        raise _exit_for_error(e)


@app.command("validate-config")
def config_validate(
    path: Path | None = typer.Option(None, "--path", help="Override config file path"),
) -> None:
    """Emit machine-readable config validation."""
    try:
        result = do_config_validate(path)
    except Exception as e:
        raise _exit_for_error(e)
    Console().print_json(json.dumps(result))
    if not result["valid"]:
        raise typer.Exit(code=ExitCodes.BAD_CONFIG)


@app.command("import-account")
def broker_account_import() -> None:
    """Import account metadata from local operator-managed Moomoo OpenD."""
    try:
        config = load_config()
        accounts = import_moomoo_accounts(config)
        Console().print_json(
            json.dumps(
                {
                    "broker": "moomoo",
                    "endpoint": f"{config.vnext.moomoo.host}:{config.vnext.moomoo.port}",
                    "read_only": True,
                    "accounts": [
                        {
                            "account_id": account.account_id,
                            "account_index": account.account_index,
                            "trading_environment": account.trading_environment,
                        }
                        for account in accounts
                    ],
                }
            )
        )
    except Exception as e:
        raise _exit_for_error(e)


@app.command("refresh-market-data")
def broker_market_data_refresh(
    symbols: list[str] = typer.Option(..., "--symbol", "-s", help="Canonical Moomoo symbol; repeat for each quote"),
) -> None:
    """Refresh pre-entitled Moomoo US and SG quotes without subscribing."""
    _render_moomoo_market_data_refresh(symbols)


def _render_moomoo_market_data_refresh(symbols: list[str]) -> None:
    try:
        config = load_config()
        quotes = refresh_moomoo_market_data(config, symbols)
        Console().print_json(
            json.dumps(
                {
                    "broker": "moomoo",
                    "endpoint": f"{config.vnext.moomoo.host}:{config.vnext.moomoo.port}",
                    "read_only": True,
                    "quotes": [asdict(quote) for quote in quotes],
                }
            )
        )
    except Exception as e:
        raise _exit_for_error(e)


def _load_score_components(path: Path) -> tuple[ScoreComponent, ...]:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("ranking components cannot be loaded") from error
    if not isinstance(records, list) or not records:
        raise ValueError("ranking components are invalid")
    fields = {"provider_id", "provider_asset_id", "factor_id", "raw_value", "normalized_score"}
    if not all(isinstance(record, dict) and set(record) == fields for record in records):
        raise ValueError("ranking component fields are invalid")
    try:
        return tuple(
            ScoreComponent(
                record["provider_id"],
                record["provider_asset_id"],
                record["factor_id"],
                record["raw_value"],
                record["normalized_score"],
            )
            for record in records
        )
    except (TypeError, ValueError) as error:
        raise ValueError("ranking components are malformed") from error


def _load_daily_report_inputs(path: Path) -> tuple[PortfolioExposure, SGDPortfolioNAV | USDPortfolioNAV, DataConfidenceScore]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("daily report input cannot be loaded") from error
    if not isinstance(data, dict) or set(data) != {"exposure", "nav", "data_confidence"}:
        raise ValueError("daily report input fields are invalid")
    exposure_data, nav_data, confidence_data = data["exposure"], data["nav"], data["data_confidence"]
    exposure_fields = {"account_id", "quote_currency", "long_exposure", "short_exposure", "gross_exposure", "net_exposure"}
    nav_fields = {"account_id", "currency", "captured_at", "holdings_value", "cash_value", "net_asset_value"}
    confidence_fields = {
        "provider_id",
        "evaluated_at",
        "maximum_age_seconds",
        "source_count",
        "fresh_source_count",
        "stale_source_urls",
        "score",
    }
    if not isinstance(exposure_data, dict) or set(exposure_data) != exposure_fields:
        raise ValueError("daily report exposure fields are invalid")
    if not isinstance(nav_data, dict) or set(nav_data) != nav_fields:
        raise ValueError("daily report NAV fields are invalid")
    if not isinstance(confidence_data, dict) or set(confidence_data) != confidence_fields:
        raise ValueError("daily report data-confidence fields are invalid")
    try:
        exposure = PortfolioExposure(**exposure_data)
        captured_at = datetime.fromisoformat(nav_data["captured_at"])
        if nav_data["currency"] == "SGD":
            nav = SGDPortfolioNAV(nav_data["account_id"], captured_at, nav_data["holdings_value"], nav_data["cash_value"], nav_data["net_asset_value"])
        elif nav_data["currency"] == "USD":
            nav = USDPortfolioNAV(nav_data["account_id"], captured_at, nav_data["holdings_value"], nav_data["cash_value"], nav_data["net_asset_value"])
        else:
            raise ValueError("daily report NAV currency is invalid")
        confidence = DataConfidenceScore(
            confidence_data["provider_id"],
            datetime.fromisoformat(confidence_data["evaluated_at"]),
            timedelta(seconds=confidence_data["maximum_age_seconds"]),
            confidence_data["source_count"],
            confidence_data["fresh_source_count"],
            tuple(confidence_data["stale_source_urls"]),
            confidence_data["score"],
        )
    except (TypeError, ValueError) as error:
        raise ValueError("daily report input is malformed") from error
    return exposure, nav, confidence


def _portfolio_snapshot_to_data(snapshot: PortfolioSnapshot) -> dict[str, object]:
    return {
        "provider_id": snapshot.provider_id,
        "account_id": snapshot.account_id,
        "captured_at": snapshot.captured_at.isoformat().replace("+00:00", "Z"),
        "holdings": [
            {
                "holding_id": holding.holding_id,
                "symbol": holding.symbol,
                "asset_class": holding.asset_class.value,
                "quantity": holding.quantity,
                "currency": holding.currency,
                "market_value": holding.market_value,
            }
            for holding in snapshot.holdings
        ],
    }


def _load_portfolio_snapshot(path: Path) -> PortfolioSnapshot:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("portfolio snapshot cannot be loaded") from error
    fields = {"provider_id", "account_id", "captured_at", "holdings"}
    holding_fields = {"holding_id", "symbol", "asset_class", "quantity", "currency", "market_value"}
    if not isinstance(data, dict) or set(data) != fields or not isinstance(data["holdings"], list):
        raise ValueError("portfolio snapshot fields are invalid")
    if not all(isinstance(holding, dict) and set(holding) == holding_fields for holding in data["holdings"]):
        raise ValueError("portfolio snapshot holding fields are invalid")
    try:
        return PortfolioSnapshot(
            data["provider_id"],
            data["account_id"],
            datetime.fromisoformat(data["captured_at"]),
            tuple(
                PortfolioHolding(
                    data["account_id"],
                    holding["holding_id"],
                    holding["symbol"],
                    PortfolioAssetClass(holding["asset_class"]),
                    holding["quantity"],
                    holding["currency"],
                    holding["market_value"],
                )
                for holding in data["holdings"]
            ),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("portfolio snapshot is malformed") from error


# --- Carry commands ---


@app.command("health-carry")
def carry_health(
    state_dir: Path = typer.Option(Path(".cache/carry-paper"), "--state-dir"),
    ledger: Path = typer.Option(Path(".cache/carry-paper/ledger.md"), "--ledger"),
    stream_heartbeat: Path | None = typer.Option(None, "--stream-heartbeat"),
    reconciliation: Path | None = typer.Option(None, "--reconciliation"),
    json_output: bool = typer.Option(False, "--json/--table"),
    skip_network: bool = typer.Option(False, "--skip-network", help="Skip network and venue API checks"),
    max_stream_age_seconds: float = typer.Option(120.0, "--max-stream-age-seconds", min=0.0),
) -> None:
    """Check Carry Pi paper-run host and artifact health."""
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


@app.command("scan-carry")
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
            "min_net_apr": cfg.carry.min_net_apr,
            "rows": [row.to_dict() for row in rows],
        }
        console = Console()
        if json_output:
            console.print_json(json.dumps(payload))
        else:
            console.print(_render_carry_scan_table(rows))
    except Exception as e:
        raise _exit_for_error(e)


@app.command("preflight-carry-live")
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
    table = Table(title="Carry scan")
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


@app.command("run-carry-paper")
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
            min_net_apr=cfg.carry.min_net_apr,
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


# --- Research commands ---

@app.command("demo-ledger")
def research_ledger_demo(
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


@app.command("replay-ingest")
def research_ingest_replay(
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


@app.command("analyze-ingest")
def research_ingest_analyze(
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


@app.command("run-ingest")
def research_ingest_run(
    coins: list[str] = typer.Option(None, "--coin", help="Repeatable Hyperliquid trade coin, e.g. BTC or @107"),
    user_fill_wallets: list[str] = typer.Option(None, "--user-fill-wallet", help="Repeatable wallet for userFills"),
    user_funding_wallets: list[str] = typer.Option(
        None, "--user-funding-wallet", help="Repeatable wallet for userFundings"
    ),
    all_mids: bool = typer.Option(True, "--all-mids/--no-all-mids", help="Include allMids; first dex includes spot mids"),
    all_mids_dex: str | None = typer.Option(None, "--all-mids-dex", help="Optional allMids dex selector"),
    duration_seconds: float = typer.Option(float(DEFAULT_LIVE_CAPTURE_SECONDS), "--duration-seconds", min=1.0),
    raw_out: Path = typer.Option(Path(".cache/validation-gates/captures/hyperliquid-raw.jsonl"), "--raw-out"),
    out: Path = typer.Option(Path(".cache/validation-gates/captures/hyperliquid-normalized.jsonl"), "--out"),
    health: Path = typer.Option(Path(".cache/validation-gates/reports/capture-health.json"), "--health"),
    state_dir: Path = typer.Option(default_validation_dir(), "--state-dir"),
    report: Path = typer.Option(Path(".cache/validation-gates/reports/capture-gate.md"), "--report"),
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
                "live Research validation captures must run on the always-on Linux host; "
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
                    "state_path": str(gate_state_path(state_dir=state_dir)),
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


@app.command("rank-wallet")
def research_wallets_rank(
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


@app.command("replay-paper")
def research_paper_replay(
    fixture: Path = typer.Option(DEFAULT_PAPER_MIRROR_FIXTURE, "--fixture", exists=True, readable=True),
    rankings_fixture: Path = typer.Option(DEFAULT_ATTRIBUTION_FIXTURE, "--rankings-fixture", exists=True, readable=True),
    bankroll: float = typer.Option(1000.0, "--bankroll", min=0.0),
    max_position_fraction: float = typer.Option(0.10, "--max-position-fraction", min=0.0, max=1.0),
    max_order_notional: float = typer.Option(75.0, "--max-order-notional", min=0.0),
    stop_loss_pct: float = typer.Option(0.08, "--stop-loss-pct", min=0.0, max=1.0),
    cooldown_minutes: float = typer.Option(60.0, "--cooldown-minutes", min=0.0),
) -> None:
    """Replay paper trade analysis with sizing, stop-loss, and cooldown controls."""
    try:
        rankings = rank_wallets_from_fixture(rankings_fixture, limit=5)
        replay = replay_paper_analysis_fixture(
            fixture_path=fixture,
            rankings=rankings,
            config=PaperAnalysisConfig(
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


@app.command("sample-capture-gate")
def research_gates_capture_sample(
    fixture: Path = typer.Option(DEFAULT_CAPTURE_FIXTURE, "--fixture", exists=True, readable=True),
    state_dir: Path = typer.Option(default_validation_dir(), "--state-dir"),
    capture_out_dir: Path = typer.Option(Path(".cache/validation-gates/captures"), "--capture-out-dir"),
    report: Path = typer.Option(Path(".cache/validation-gates/capture-gate.md"), "--report"),
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
                    "state_path": str(gate_state_path(state_dir=state_dir)),
                    "report_path": str(report),
                    "assessment": assess_gate(state).to_dict(),
                    "latest_evidence": state.evidence[-1].to_dict(),
                }
            )
        )
    except Exception as e:
        raise _exit_for_error(e)


@app.command("status-gate")
def research_gates_status(
    gate: str = typer.Option("capture", "--gate", help="capture or capture-7d"),
    state_dir: Path = typer.Option(default_validation_dir(), "--state-dir"),
    markdown: bool = typer.Option(False, "--markdown", help="Render markdown reports instead of JSON"),
) -> None:
    """Show validation gate status from restartable state files."""
    try:
        gate_ids = _resolve_gate_ids(gate)
        states = []
        for _gate_id in gate_ids:
            path = gate_state_path(state_dir=state_dir)
            if path.exists():
                states.append(load_gate_state(state_dir=state_dir))
        if markdown:
            Console().print("\n".join(render_gate_report(state) for state in states))
        else:
            Console().print_json(
                json.dumps(
                    {
                        "state_dir": str(state_dir),
                        "gates": [
                            {
                                "state_path": str(gate_state_path(state_dir=state_dir)),
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
        "all": [CAPTURE_GATE],
        "capture": [CAPTURE_GATE],
        "capture-7d": [CAPTURE_GATE],
    }
    if normalized not in mapping:
        raise ValueError(f"unsupported gate: {gate}")
    return mapping[normalized]


def main() -> None:
    app()
