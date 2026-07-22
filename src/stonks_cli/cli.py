from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from stonks_cli import __version__
from stonks_cli.accounting import fifo_lots
from stonks_cli.analytics import allocation, market_values
from stonks_cli.config import (
    ProfileConfig,
    disable_provider,
    enable_provider,
    load_profile,
    save_profile,
)
from stonks_cli.ledger import cash_balances, import_csv, list_events, positions
from stonks_cli.market_data import (
    archive_and_store_daily_prices,
    import_daily_prices_csv,
    latest_prices,
)
from stonks_cli.moomoo import MoomooReadOnlyProvider, OpenDConnection
from stonks_cli.operator import (
    ScheduleDefinition,
    install_linux_schedule,
    linux_schedule_status,
    notify_local,
    notify_telegram,
    render_schedule,
)
from stonks_cli.plugins import builtin_provider_manifests, discover_with_diagnostics
from stonks_cli.storage import (
    EncryptedLedger,
    export_backup,
    generate_key_file,
    restore_backup,
    rotate_key,
)
from stonks_cli.strategy import run_csv_backtest
from stonks_cli.types import Currency, Instrument
from stonks_cli.watchlist import (
    WatchlistItem,
    list_items,
    remove,
)
from stonks_cli.watchlist import add as add_watchlist_item

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _profile(name: str, key_file: Path | None) -> ProfileConfig:
    config = load_profile(name)
    return (
        config
        if key_file is None
        else replace(config, key_file=str(key_file.expanduser().resolve()))
    )


def _instrument(symbol: str, market: str, currency: str, name: str | None) -> Instrument:
    try:
        return Instrument(symbol, market, Currency(currency.upper()), name)
    except ValueError as error:
        raise typer.BadParameter("instrument values are invalid") from error


@app.command("init-profile")
def init_profile(name: str, key_file: Path = typer.Option(..., exists=False)) -> None:
    key_file = key_file.expanduser().resolve()
    generate_key_file(key_file)
    save_profile(ProfileConfig(name=name, key_file=str(key_file)))
    console.print_json(
        json.dumps({"profile": name, "key_file": str(key_file), "status": "initialized"})
    )


@app.command("import-csv")
def import_csv_command(
    profile: str,
    path: Path = typer.Argument(..., exists=True, dir_okay=False),
    key_file: Path | None = typer.Option(None),
) -> None:
    inserted, skipped, source_hash = import_csv(EncryptedLedger(_profile(profile, key_file)), path)
    console.print_json(
        json.dumps({"inserted": inserted, "skipped": skipped, "source_hash": source_hash})
    )


@app.command("import-prices")
def import_prices(
    profile: str,
    path: Path = typer.Argument(..., exists=True, dir_okay=False),
    key_file: Path | None = typer.Option(None),
) -> None:
    count = import_daily_prices_csv(EncryptedLedger(_profile(profile, key_file)), path)
    console.print_json(json.dumps({"profile": profile, "prices": count}))


@app.command()
def portfolio(
    profile: str,
    key_file: Path | None = typer.Option(None),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    events = list_events(EncryptedLedger(_profile(profile, key_file)))
    cash = cash_balances(events)
    holdings = positions(events)
    values = market_values(holdings, latest_prices(EncryptedLedger(_profile(profile, key_file))))
    payload = {
        "profile": profile,
        "event_count": len(events),
        "cash": {
            f"{account}:{currency}": str(amount) for (account, currency), amount in cash.items()
        },
        "positions": {
            f"{account}:{instrument}": str(quantity)
            for (account, instrument), quantity in holdings.items()
        },
        "market_values": {
            f"{account}:{instrument}": str(value) for (account, instrument), value in values.items()
        },
        "allocation": {
            f"{account}:{instrument}": str(value)
            for (account, instrument), value in allocation(values).items()
        },
    }
    if as_json:
        console.print_json(json.dumps(payload))
        return
    table = Table(title=f"Portfolio: {profile}")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Events", str(payload["event_count"]))
    table.add_row("Cash balances", str(len(cash)))
    table.add_row("Open positions", str(len(holdings)))
    console.print(table)


@app.command()
def transactions(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    console.print_json(
        json.dumps(
            [event.to_data() for event in list_events(EncryptedLedger(_profile(profile, key_file)))]
        )
    )


@app.command()
def performance(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    lots, realized = fifo_lots(list_events(EncryptedLedger(_profile(profile, key_file))))
    payload = {
        "profile": profile,
        "realized_pnl": str(sum((item.value for item in realized), Decimal("0"))),
        "open_cost": str(sum((item.cost for item in lots), Decimal("0"))),
        "open_lots": len(lots),
    }
    console.print_json(json.dumps(payload))


@app.command("backup-profile")
def backup_profile(
    profile: str, destination: Path, key_file: Path | None = typer.Option(None)
) -> None:
    path = export_backup(_profile(profile, key_file), destination)
    console.print_json(json.dumps({"profile": profile, "backup": str(path)}))


@app.command("restore-profile")
def restore_profile(source: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    config = restore_backup(source)
    console.print_json(json.dumps({"profile": config.name, "status": "restored"}))


@app.command("rotate-key")
def rotate_profile_key(
    profile: str, new_key_file: Path, key_file: Path | None = typer.Option(None)
) -> None:
    updated = rotate_key(_profile(profile, key_file), new_key_file)
    console.print_json(
        json.dumps({"profile": profile, "key_file": updated.key_file, "status": "rotated"})
    )


@app.command("backtest-csv")
def backtest_csv(
    profile: str,
    path: Path = typer.Argument(..., exists=True, dir_okay=False),
    fee_rate: str = typer.Option("0"),
    slippage_rate: str = typer.Option("0"),
    key_file: Path | None = typer.Option(None),
) -> None:
    try:
        fee = Decimal(fee_rate)
        slippage = Decimal(slippage_rate)
    except Exception as error:
        raise typer.BadParameter("fee-rate and slippage-rate must be decimal values") from error
    result, source_hash = run_csv_backtest(
        EncryptedLedger(_profile(profile, key_file)), path, fee_rate=fee, slippage_rate=slippage
    )
    console.print_json(
        json.dumps(
            {
                "source_hash": source_hash,
                "periods": result.periods,
                "trade_count": result.trade_count,
                "total_return": str(result.total_return),
                "execution": "denied",
            }
        )
    )


@app.command("watchlist-add")
def watchlist_add(
    profile: str,
    symbol: str,
    market: str,
    currency: str,
    name: str | None = typer.Option(None),
    note: str | None = typer.Option(None),
    key_file: Path | None = typer.Option(None),
) -> None:
    item = WatchlistItem(_instrument(symbol, market, currency, name), note)
    add_watchlist_item(EncryptedLedger(_profile(profile, key_file)), item)
    console.print_json(json.dumps({"profile": profile, "instrument": item.instrument.key}))


@app.command("watchlist-remove")
def watchlist_remove(
    profile: str,
    market: str,
    symbol: str,
    key_file: Path | None = typer.Option(None),
) -> None:
    instrument_key = f"{market.strip().upper()}:{symbol.strip().upper()}"
    if not remove(EncryptedLedger(_profile(profile, key_file)), instrument_key):
        raise typer.BadParameter("watchlist instrument is not present")
    console.print_json(json.dumps({"profile": profile, "instrument": instrument_key}))


@app.command("watchlist")
def watchlist(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    items = list_items(EncryptedLedger(_profile(profile, key_file)))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "items": [
                    {
                        "instrument": item.instrument.key,
                        "currency": item.instrument.currency.value,
                        "name": item.instrument.name,
                        "note": item.note,
                    }
                    for item in items
                ],
            }
        )
    )


@app.command("refresh-moomoo-prices")
def refresh_moomoo_prices(
    profile: str,
    days: int = typer.Option(7, min=1, max=365),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(11111),
    key_file: Path | None = typer.Option(None),
) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    instruments = tuple(item.instrument for item in list_items(ledger))
    if not instruments:
        raise typer.BadParameter("watchlist is empty")
    end = date.today()
    start = end - timedelta(days=days - 1)
    provider = MoomooReadOnlyProvider.from_installed_sdk(OpenDConnection(host, port))
    prices = provider.daily_prices(instruments, start, end)
    count, source_hash = archive_and_store_daily_prices(ledger, prices)
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "instruments": len(instruments),
                "prices": count,
                "source_hash": source_hash,
                "execution": "denied",
            }
        )
    )


@app.command("schedule-render")
def schedule_render(
    profile: str,
    hour_singapore: int = typer.Option(18),
    minute_singapore: int = typer.Option(0),
) -> None:
    load_profile(profile)
    typer.echo(render_schedule(ScheduleDefinition(profile, hour_singapore, minute_singapore)))


@app.command("schedule-install")
def schedule_install(
    profile: str,
    hour_singapore: int = typer.Option(18),
    minute_singapore: int = typer.Option(0),
    unit_directory: Path = typer.Option(Path("~/.config/systemd/user")),
) -> None:
    load_profile(profile)
    service, timer = install_linux_schedule(
        ScheduleDefinition(profile, hour_singapore, minute_singapore), unit_directory.expanduser()
    )
    console.print_json(json.dumps({"service": str(service), "timer": str(timer)}))


@app.command("schedule-status")
def schedule_status(profile: str) -> None:
    load_profile(profile)
    status = linux_schedule_status(ScheduleDefinition(profile, 18))
    console.print_json(
        json.dumps({"label": status.label, "enabled": status.enabled, "active": status.active})
    )


@app.command("notify-local")
def notify(title: str, message: str) -> None:
    if not notify_local(title, message):
        raise typer.Exit(1)


@app.command("notify-telegram")
def notify_telegram_command(title: str, message: str, chat_id: str = typer.Option(...)) -> None:
    token = os.environ.get("STONKS_CLI_TELEGRAM_TOKEN")
    if token is None:
        raise typer.BadParameter("STONKS_CLI_TELEGRAM_TOKEN is required")
    if not notify_telegram(token, chat_id, title, message):
        raise typer.Exit(1)


@app.command("plugins")
def plugins_command() -> None:
    discovery = discover_with_diagnostics()
    console.print_json(
        json.dumps(
            {
                "installed": [identifier for identifier, _ in discovery.providers],
                "built_in": [
                    "csv",
                    *(manifest.identifier for manifest in builtin_provider_manifests()),
                ],
                "diagnostics": [
                    {"entry_point": item.entry_point, "error": item.error}
                    for item in discovery.diagnostics
                ],
            }
        )
    )


@app.command("enable-provider")
def enable_provider_command(profile: str, provider_id: str) -> None:
    config = enable_provider(load_profile(profile), provider_id)
    save_profile(config)
    console.print_json(json.dumps({"profile": profile, "providers": list(config.providers)}))


@app.command("disable-provider")
def disable_provider_command(profile: str, provider_id: str) -> None:
    config = disable_provider(load_profile(profile), provider_id)
    save_profile(config)
    console.print_json(json.dumps({"profile": profile, "providers": list(config.providers)}))


@app.command("moomoo-accounts")
def moomoo_accounts(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(11111)) -> None:
    provider = MoomooReadOnlyProvider.from_installed_sdk(OpenDConnection(host, port))
    accounts = provider.accounts()
    console.print_json(
        json.dumps(
            {
                "endpoint": f"{host}:{port}",
                "accounts": [
                    {
                        "account_id": account.account_id,
                        "account_index": account.account_index,
                        "environment": account.environment,
                    }
                    for account in accounts
                ],
                "execution": "denied",
            }
        )
    )


@app.command("moomoo-probe")
def moomoo_probe(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(11111)) -> None:
    probe = MoomooReadOnlyProvider.probe(OpenDConnection(host, port))
    console.print_json(
        json.dumps(
            {
                "endpoint": f"{probe.endpoint.host}:{probe.endpoint.port}",
                "sdk_version": probe.sdk_version,
                "account_count": probe.account_count,
                "execution": "denied",
            }
        )
    )


@app.command()
def version() -> None:
    typer.echo(__version__)


def main() -> None:
    app()
