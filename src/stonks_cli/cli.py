from __future__ import annotations

import json
import os
import platform
import shlex
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import typer
from rich.console import Console

from stonks_cli import __version__, advisory, llm, ml, paper
from stonks_cli.accounting import fifo_lots
from stonks_cli.alerts import price_move_alert
from stonks_cli.analytics import (
    allocation,
    allocations_by_currency,
    asset_class_allocation,
    asset_class_allocations_by_currency,
    convert_values_to_currency,
    dividend_and_fee_attribution,
    market_values_by_currency,
    sector_concentration,
    sector_concentrations_by_currency,
)
from stonks_cli.config import (
    BenchmarkComponent,
    BenchmarkSettings,
    DividendSettings,
    JournalSettings,
    LLMSettings,
    ProfileConfig,
    configure_benchmark,
    configure_drawdown,
    configure_journal,
    disable_provider,
    enable_provider,
    load_profile,
    save_profile,
)
from stonks_cli.errors import LedgerError, LLMError, ProfileError, ProviderError
from stonks_cli.ledger import (
    cash_balances,
    credit_mapped_dividend,
    import_csv,
    list_cash_flows,
    list_cash_snapshots,
    list_dividend_credit_mappings,
    list_dividend_declarations,
    list_events,
    list_position_snapshots,
    positions,
)
from stonks_cli.market_data import (
    archive_and_store_daily_prices,
    archive_and_store_quote_snapshots,
    historical_prices,
    import_daily_prices_csv,
    import_fx_rates_csv,
    latest_fx_rates,
    latest_instrument_masters,
    latest_prices,
    latest_quote_snapshots,
)
from stonks_cli.moomoo import (
    MoomooReadOnlyProvider,
    OpenDConnection,
    import_account_snapshot,
    import_cash_flows,
    import_dividend_declarations,
)
from stonks_cli.operator import (
    ScheduleDefinition,
    install_linux_schedule,
    install_macos_schedule,
    linux_schedule_status,
    macos_schedule_status,
    notify_local,
    render_schedule,
)
from stonks_cli.paper import (
    PaperEvent,
    PaperEventKind,
)
from stonks_cli.plugins import (
    PluginDiscovery,
    PluginManifest,
    builtin_provider_manifests,
    discover_with_diagnostics,
)
from stonks_cli.reconciliation import reconcile_latest, render_discrepancy_report
from stonks_cli.report_export import (
    RecipientPublicKey,
    add_recipient_key,
    export_audits,
    export_report,
    load_recipient_keyring,
    revoke_recipient_key,
)
from stonks_cli.storage import (
    EncryptedLedger,
    export_backup,
    generate_key_file,
    restore_backup,
    rotate_key,
)
from stonks_cli.strategy import (
    AdvisoryJournalDisposition,
    AdvisoryJournalEntry,
    StrategyRunCard,
    append_journal_entry,
    link_advisory_journal_evidence,
    list_advisory_journal_entries,
    list_artifacts,
    list_journal_entries,
    open_advisory_journal,
    purge_expired_advisory_journal_entries,
    record_advisory_journal_disposition,
    record_journal_settings_audit,
    run_csv_backtest,
    store_artifact,
)
from stonks_cli.strategy import (
    journal_settings_audit as advisory_journal_settings_audit,
)
from stonks_cli.telegram_delivery import (
    TelegramArtifact,
    TelegramEventCategory,
    TelegramMessageField,
    TelegramSettings,
)
from stonks_cli.telegram_delivery import (
    add_recipient as add_telegram_recipient,
)
from stonks_cli.telegram_delivery import (
    configure as configure_telegram,
)
from stonks_cli.telegram_delivery import (
    deliver as deliver_telegram,
)
from stonks_cli.telegram_delivery import (
    delivery_records as telegram_delivery_records,
)
from stonks_cli.telegram_delivery import (
    settings as telegram_settings,
)
from stonks_cli.telegram_delivery import (
    settings_audit as telegram_settings_audit,
)
from stonks_cli.terminal_delivery import (
    create_artifact,
    latest_scheduled_artifact,
    persist_scheduled_artifact,
    render_terminal,
)
from stonks_cli.terminal_table import TerminalTable, render_table
from stonks_cli.types import Account, Currency, DrawdownResponsePolicy, Instrument
from stonks_cli.watchlist import (
    WatchlistItem,
    audit_history,
    configure_restriction,
    list_items,
    remove,
)
from stonks_cli.watchlist import add as add_watchlist_item
from stonks_cli.watchlist import (
    settings as watchlist_settings,
)

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


def _iso_date(value: str, parameter: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(f"{parameter} must be YYYY-MM-DD") from error


def _llm_settings_data(settings: LLMSettings) -> dict[str, object]:
    return {
        "enabled": settings.enabled,
        "provider": settings.provider,
        "model": settings.model,
        "api_key_env": settings.api_key_env,
        "ollama_url": settings.ollama_url if settings.provider == "ollama" else None,
        "ollama_local_only": settings.ollama_local_only if settings.provider == "ollama" else None,
        "budget_period": settings.budget_period,
        "budget_limit_sgd": settings.budget_limit_sgd,
        "input_cost_per_million_sgd": settings.input_cost_per_million_sgd,
        "output_cost_per_million_sgd": settings.output_cost_per_million_sgd,
        "max_output_tokens": settings.max_output_tokens,
        "allow_cloud": settings.allow_cloud,
    }


def _dividend_settings_data(settings: DividendSettings) -> dict[str, bool]:
    return {
        "allow_explicit_credit": settings.allow_explicit_credit,
        "allow_currency_conversion": settings.allow_currency_conversion,
    }


def _llm_result_data(profile: str, result: llm.LLMResult) -> dict[str, object]:
    return {
        "profile": profile,
        "provider": result.provider,
        "model": result.model,
        "text": result.text,
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        },
        "estimated_cost_sgd": str(result.estimated_cost_sgd),
        "privacy": "public_only",
        "execution": "denied",
    }


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


@app.command("import-fx")
def import_fx(
    profile: str,
    path: Path = typer.Argument(..., exists=True, dir_okay=False),
    key_file: Path | None = typer.Option(None),
) -> None:
    count = import_fx_rates_csv(EncryptedLedger(_profile(profile, key_file)), path)
    console.print_json(json.dumps({"profile": profile, "rates": count}))


@app.command("import-history")
def import_history(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "source_hashes": ledger.archived_source_hashes(),
                "encrypted": True,
            }
        )
    )


@app.command()
def portfolio(
    profile: str,
    key_file: Path | None = typer.Option(None),
    base_currency: str | None = typer.Option(None),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    events = list_events(ledger)
    cash = cash_balances(events)
    holdings = positions(events)
    prices = latest_prices(ledger)
    quotes = latest_quote_snapshots(ledger)
    valuation_sources: dict[str, str] = {instrument_key: "daily_close" for instrument_key in prices}
    for instrument_key, snapshot in quotes.items():
        if snapshot.current_price is not None:
            prices[instrument_key] = snapshot.current_price
            valuation_sources[instrument_key] = "current_quote"
    values_by_currency = market_values_by_currency(events, prices)
    instrument_masters = latest_instrument_masters(ledger)
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
        "market_values_by_currency": {
            currency.value: {
                f"{account}:{instrument}": str(value)
                for (account, instrument), value in values.items()
            }
            for currency, values in values_by_currency.items()
        },
        "allocation_by_currency": {
            currency.value: {
                f"{account}:{instrument}": str(value)
                for (account, instrument), value in values.items()
            }
            for currency, values in allocations_by_currency(events, prices).items()
        },
        "quote_snapshots": {
            instrument_key: {
                "status": snapshot.status.value,
                "as_of": snapshot.as_of_at.isoformat() if snapshot.as_of_at is not None else None,
                "retrieved_at": snapshot.observed_at.isoformat(),
                "price": str(snapshot.current_price) if snapshot.current_price is not None else None,
                "market_session": snapshot.market_session.value,
                "market_session_raw": snapshot.market_session_raw,
                "order_book_status": snapshot.order_book_status,
                "spread": str(snapshot.spread) if snapshot.spread is not None else None,
                "subscription_mode": snapshot.subscription_mode,
                "provider_fingerprint": snapshot.provider_fingerprint,
            }
            for instrument_key, snapshot in quotes.items()
        },
        "valuation_price_sources": valuation_sources,
    }
    try:
        payload["asset_class_allocation_by_currency"] = {
            currency.value: {asset_class.value: str(value) for asset_class, value in allocations.items()}
            for currency, allocations in asset_class_allocations_by_currency(
                values_by_currency, instrument_masters
            ).items()
        }
    except ProviderError:
        payload["asset_class_allocation_status"] = "unavailable"
    try:
        payload["sector_concentration_by_currency"] = {
            currency.value: {
                "allocation": {
                    sector.value: str(value)
                    for sector, value in concentration.allocation.items()
                },
                "hhi": str(concentration.hhi),
            }
            for currency, concentration in sector_concentrations_by_currency(
                values_by_currency, instrument_masters
            ).items()
        }
    except ProviderError:
        payload["sector_concentration_status"] = "unavailable"
    if base_currency is not None:
        try:
            target_currency = Currency(base_currency.upper())
        except ValueError as error:
            raise typer.BadParameter("base-currency is invalid") from error
        converted_values = convert_values_to_currency(
            values_by_currency,
            target_currency,
            latest_fx_rates(EncryptedLedger(_profile(profile, key_file))),
        )
        payload["base_currency"] = target_currency.value
        payload["market_values"] = {
            f"{account}:{instrument}": str(value)
            for (account, instrument), value in converted_values.items()
        }
        payload["allocation"] = {
            f"{account}:{instrument}": str(value)
            for (account, instrument), value in allocation(converted_values).items()
        }
        try:
            payload["asset_class_allocation"] = {
                asset_class.value: str(value)
                for asset_class, value in asset_class_allocation(
                    converted_values, instrument_masters
                ).items()
            }
        except ProviderError:
            payload["asset_class_allocation_status"] = "unavailable"
        try:
            concentration = sector_concentration(converted_values, instrument_masters)
            payload["sector_concentration"] = {
                "allocation": {
                    sector.value: str(value) for sector, value in concentration.allocation.items()
                },
                "hhi": str(concentration.hhi),
            }
        except ProviderError:
            payload["sector_concentration_status"] = "unavailable"
    if as_json:
        console.print_json(json.dumps(payload))
        return
    console.print(
        render_table(
            TerminalTable(
                f"Portfolio: {profile}",
                ("Metric", "Value"),
                (
                    ("Events", str(payload["event_count"])),
                    ("Cash balances", str(len(cash))),
                    ("Open positions", str(len(holdings))),
                ),
            )
        )
    )


@app.command("daily-report")
def daily_report(
    profile: str,
    key_file: Path | None = typer.Option(None),
    base_currency: str | None = typer.Option(None),
) -> None:
    portfolio(profile, key_file, base_currency, True)


@app.command()
def holdings(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    values = positions(list_events(EncryptedLedger(_profile(profile, key_file))))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "positions": [
                    {"account": account, "instrument": instrument, "quantity": str(quantity)}
                    for (account, instrument), quantity in sorted(values.items())
                ],
                "execution": "denied",
            }
        )
    )


@app.command()
def cash(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    values = cash_balances(list_events(EncryptedLedger(_profile(profile, key_file))))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "balances": [
                    {"account": account, "currency": currency.value, "amount": str(amount)}
                    for (account, currency), amount in sorted(values.items())
                ],
                "execution": "denied",
            }
        )
    )


@app.command()
def exposure(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    events = list_events(ledger)
    cash = cash_balances(events)
    market_values = market_values_by_currency(events, latest_prices(ledger))
    cash_by_currency: dict[Currency, Decimal] = defaultdict(Decimal)
    for (_, currency), amount in cash.items():
        cash_by_currency[currency] += amount
    output = []
    for currency in sorted(set(cash_by_currency) | set(market_values), key=lambda item: item.value):
        market_value = sum(market_values.get(currency, {}).values(), Decimal("0"))
        cash_value = cash_by_currency[currency]
        output.append(
            {
                "currency": currency.value,
                "cash": str(cash_value),
                "market_value": str(market_value),
                "exposure": str(cash_value + market_value),
            }
        )
    console.print_json(json.dumps({"profile": profile, "exposure": output, "execution": "denied"}))


@app.command()
def transactions(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    console.print_json(
        json.dumps(
            [event.to_data() for event in list_events(EncryptedLedger(_profile(profile, key_file)))]
        )
    )


@app.command()
def performance(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    events = list_events(EncryptedLedger(_profile(profile, key_file)))
    lots, realized = fifo_lots(events)
    attribution = dividend_and_fee_attribution(events)
    payload = {
        "profile": profile,
        "realized_pnl": str(sum((item.value for item in realized), Decimal("0"))),
        "open_cost": str(sum((item.cost for item in lots), Decimal("0"))),
        "open_lots": len(lots),
        "dividend_and_fee_attribution": {
            currency.value: {
                "dividends": str(item.dividends),
                "standalone_fees": str(item.standalone_fees),
                "trade_fees": str(item.trade_fees),
                "fees": str(item.fees),
                "net_return_contribution": str(item.net_return_contribution),
            }
            for currency, item in attribution.items()
        },
    }
    console.print_json(json.dumps(payload))


@app.command("reconciliation")
def reconciliation(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    differences = reconcile_latest(
        list_events(ledger), list_cash_snapshots(ledger), list_position_snapshots(ledger)
    )
    console.print(render_discrepancy_report(differences))


@app.command("backup-profile")
def backup_profile(
    profile: str, destination: Path, key_file: Path | None = typer.Option(None)
) -> None:
    path = export_backup(_profile(profile, key_file), destination)
    console.print_json(json.dumps({"profile": profile, "backup": str(path)}))


@app.command("recipient-key-add")
def recipient_key_add(
    identifier: str,
    public_key: str,
    recovery: bool = typer.Option(False),
) -> None:
    try:
        key = add_recipient_key(RecipientPublicKey(identifier, public_key, recovery=recovery))
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(json.dumps({"identifier": key.identifier, "recovery": key.recovery}))


@app.command("recipient-key-revoke")
def recipient_key_revoke(identifier: str) -> None:
    try:
        key = revoke_recipient_key(identifier)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(json.dumps({"identifier": key.identifier, "revoked": key.revoked}))


@app.command("recipient-key-list")
def recipient_key_list() -> None:
    console.print_json(
        json.dumps(
            {
                "recipients": [
                    {"identifier": key.identifier, "recovery": key.recovery, "revoked": key.revoked}
                    for key in load_recipient_keyring()
                ]
            }
        )
    )


@app.command("report-export")
def report_export(
    profile: str,
    destination: Path = typer.Argument(..., exists=False),
    recipient: list[str] = typer.Option(..., "--recipient"),
    recovery_recipient: str | None = typer.Option(None),
    key_file: Path | None = typer.Option(None),
) -> None:
    config = _profile(profile, key_file)
    ledger = EncryptedLedger(config)
    events = list_events(ledger)
    report = {
        "format": "stonks-cli-portfolio-report",
        "version": 1,
        "profile": profile,
        "cash": [
            {"account": account, "currency": currency.value, "amount": str(amount)}
            for (account, currency), amount in sorted(cash_balances(events).items())
        ],
        "positions": [
            {"account": account, "instrument": instrument, "quantity": str(quantity)}
            for (account, instrument), quantity in sorted(positions(events).items())
        ],
    }
    provenance = {
        "report_kind": "portfolio",
        "profile_schema_version": config.schema_version,
        "source_hashes": list(ledger.archived_source_hashes()),
    }
    try:
        audit = export_report(
            ledger,
            report,
            destination,
            tuple(recipient),
            provenance=provenance,
            recovery_recipient=recovery_recipient,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "export_id": audit.export_id,
                "recipient_count": len(audit.recipient_identifiers),
                "integrity": audit.integrity_status,
                "execution": "denied",
            }
        )
    )


@app.command("report-export-audit")
def report_export_audit(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    records = export_audits(EncryptedLedger(_profile(profile, key_file)))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "exports": [
                    {
                        "export_id": record.export_id,
                        "created_at": record.created_at.isoformat(),
                        "envelope_hash": record.envelope_hash,
                        "recipient_identifiers": record.recipient_identifiers,
                        "provenance": record.provenance,
                        "integrity": record.integrity_status,
                    }
                    for record in records
                ],
            }
        )
    )


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
    strategy_name: str = typer.Option("csv-eod-long-only"),
    universe: str = typer.Option("CSV input"),
    signal_definition: str = typer.Option("prior-close CSV signal"),
    fee_rate: str = typer.Option("0"),
    slippage_rate: str = typer.Option("0"),
    benchmark_return: str = typer.Option("0"),
    key_file: Path | None = typer.Option(None),
) -> None:
    try:
        fee = Decimal(fee_rate)
        slippage = Decimal(slippage_rate)
        benchmark = Decimal(benchmark_return)
    except Exception as error:
        raise typer.BadParameter("fee-rate and slippage-rate must be decimal values") from error
    ledger = EncryptedLedger(_profile(profile, key_file))
    result, source_hash = run_csv_backtest(
        ledger, path, fee_rate=fee, slippage_rate=slippage
    )
    artifact = store_artifact(
        ledger,
        StrategyRunCard(
            strategy_name,
            universe,
            signal_definition,
            fee,
            slippage,
            source_hash,
            datetime.now(UTC),
        ),
        result,
        benchmark,
    )
    console.print_json(
        json.dumps(
            {
                "source_hash": source_hash,
                "artifact_id": artifact.artifact_id,
                "periods": result.periods,
                "trade_count": result.trade_count,
                "total_return": str(result.total_return),
                "benchmark_return": str(benchmark),
                "execution": "denied",
            }
        )
    )


@app.command("strategy-artifacts")
def strategy_artifacts(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    artifacts = list_artifacts(EncryptedLedger(_profile(profile, key_file)))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "artifacts": [
                    {
                        "artifact_id": item.artifact_id,
                        "strategy_name": item.run_card.strategy_name,
                        "universe": item.run_card.universe,
                        "source_hash": item.run_card.source_hash,
                        "total_return": str(item.result.total_return),
                        "benchmark_return": str(item.benchmark_return),
                    }
                    for item in artifacts
                ],
                "execution": "denied",
            }
        )
    )


@app.command("strategy-journal")
def strategy_journal(
    profile: str,
    summary: str = typer.Option(...),
    rationale: str = typer.Option(...),
    key_file: Path | None = typer.Option(None),
) -> None:
    entry = append_journal_entry(EncryptedLedger(_profile(profile, key_file)), summary, rationale)
    console.print_json(json.dumps({"profile": profile, "entry_id": entry.entry_id}))


@app.command("strategy-journal-list")
def strategy_journal_list(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    entries = list_journal_entries(EncryptedLedger(_profile(profile, key_file)))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "entries": [
                    {
                        "entry_id": item.entry_id,
                        "created_at": item.created_at.isoformat(),
                        "summary": item.summary,
                        "rationale": item.rationale,
                    }
                    for item in entries
                ],
            }
        )
    )


def _journal_settings_data(profile: str, settings: JournalSettings) -> dict[str, object]:
    return {
        "profile": profile,
        "open_on_advisory": settings.open_on_advisory,
        "retention_days": settings.retention_days,
        "display_reasons": settings.display_reasons,
        "configuration_version": settings.version,
    }


def _benchmark_settings_data(profile: str, settings: BenchmarkSettings) -> dict[str, object]:
    return {
        "profile": profile,
        "components": [
            {
                "identifier": component.identifier,
                "name": component.name,
                "currency": component.currency.value,
                "weight": component.weight,
                "source_url": component.source_url,
                "return_basis": component.return_basis,
            }
            for component in settings.components
        ],
        "configuration_version": settings.version,
        "reference_only": True,
        "execution": "denied",
    }


def _benchmark_component_option(value: str) -> BenchmarkComponent:
    try:
        item = json.loads(value)
        if not isinstance(item, dict):
            raise TypeError("component must be an object")
        return BenchmarkComponent(
            identifier=item["identifier"],
            name=item["name"],
            currency=Currency(item["currency"]),
            weight=item["weight"],
            source_url=item["source_url"],
            return_basis=item.get("return_basis", "total_return"),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, ProfileError) as error:
        raise typer.BadParameter("component must be a valid benchmark JSON object") from error


def _advisory_journal_entry_data(
    entry: AdvisoryJournalEntry, *, display_reasons: bool
) -> dict[str, object]:
    data: dict[str, object] = {
        "entry_id": entry.entry_id,
        "advisory_id": entry.advisory_id,
        "profile": entry.profile,
        "configuration_version": entry.configuration_version,
        "opened_at": entry.opened_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
        "disposition": None if entry.disposition is None else entry.disposition.value,
        "disposition_at": None if entry.disposition_at is None else entry.disposition_at.isoformat(),
        "evidence_fingerprints": list(entry.evidence_fingerprints),
        "disposition_history": [
            {
                "recorded_at": item.recorded_at.isoformat(),
                "disposition": item.disposition.value,
                **({"reason": item.reason} if display_reasons else {}),
            }
            for item in entry.disposition_history
        ],
    }
    if display_reasons:
        data["reason"] = entry.reason
    return data


@app.command("strategy-advisory-journal-open")
def strategy_advisory_journal_open(
    profile: str,
    advisory_id: str,
    configuration_version: str,
    key_file: Path | None = typer.Option(None),
) -> None:
    config = _profile(profile, key_file)
    entry = open_advisory_journal(
        EncryptedLedger(config), advisory_id, configuration_version, config.journal
    )
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "opened": entry is not None,
                "entry": None
                if entry is None
                else _advisory_journal_entry_data(entry, display_reasons=config.journal.display_reasons),
                "execution": "denied",
            }
        )
    )


@app.command("strategy-advisory-journal-dispose")
def strategy_advisory_journal_dispose(
    profile: str,
    entry_id: str,
    disposition: AdvisoryJournalDisposition,
    reason: str | None = typer.Option(None),
    key_file: Path | None = typer.Option(None),
) -> None:
    config = _profile(profile, key_file)
    try:
        entry = record_advisory_journal_disposition(
            EncryptedLedger(config), entry_id, disposition, reason=reason
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(
        json.dumps(_advisory_journal_entry_data(entry, display_reasons=config.journal.display_reasons))
    )


@app.command("strategy-advisory-journal-link-evidence")
def strategy_advisory_journal_link_evidence(
    profile: str,
    entry_id: str,
    event_fingerprint: str,
    key_file: Path | None = typer.Option(None),
) -> None:
    config = _profile(profile, key_file)
    try:
        entry = link_advisory_journal_evidence(EncryptedLedger(config), entry_id, event_fingerprint)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(
        json.dumps(_advisory_journal_entry_data(entry, display_reasons=config.journal.display_reasons))
    )


@app.command("strategy-advisory-journal-list")
def strategy_advisory_journal_list(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    config = _profile(profile, key_file)
    entries = list_advisory_journal_entries(
        EncryptedLedger(config), retention_days=config.journal.retention_days
    )
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "entries": [
                    _advisory_journal_entry_data(item, display_reasons=config.journal.display_reasons)
                    for item in entries
                ],
                "execution": "denied",
            }
        )
    )


@app.command("strategy-advisory-journal-configure")
def strategy_advisory_journal_configure(
    profile: str,
    open_on_advisory: bool = typer.Option(True, "--open-on-advisory/--no-open-on-advisory"),
    retention_days: int | None = typer.Option(None, min=1, max=36_500),
    display_reasons: bool = typer.Option(False, "--display-reasons/--hide-reasons"),
) -> None:
    current = load_profile(profile)
    try:
        configured = configure_journal(
            current,
            open_on_advisory=open_on_advisory,
            retention_days=retention_days,
            display_reasons=display_reasons,
        )
    except ProfileError as error:
        raise typer.BadParameter(str(error)) from error
    ledger = EncryptedLedger(configured)
    if configured != current:
        save_profile(configured)
        record_journal_settings_audit(ledger, configured.journal)
    purged = purge_expired_advisory_journal_entries(ledger, configured.journal.retention_days)
    payload = _journal_settings_data(profile, configured.journal)
    payload["purged_entries"] = purged
    console.print_json(json.dumps(payload))


@app.command("strategy-advisory-journal-settings")
def strategy_advisory_journal_settings(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    config = _profile(profile, key_file)
    records = advisory_journal_settings_audit(EncryptedLedger(config))
    payload = _journal_settings_data(profile, config.journal)
    payload["audit"] = [
        {
            "changed_at": record.changed_at.isoformat(),
            "open_on_advisory": record.settings.open_on_advisory,
            "retention_days": record.settings.retention_days,
            "display_reasons": record.settings.display_reasons,
            "configuration_version": record.settings.version,
        }
        for record in records
    ]
    console.print_json(json.dumps(payload))


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
    add_watchlist_item(EncryptedLedger(_profile(profile, key_file)), item, source="cli")
    console.print_json(json.dumps({"profile": profile, "instrument": item.instrument.key}))


@app.command("watchlist-remove")
def watchlist_remove(
    profile: str,
    market: str,
    symbol: str,
    key_file: Path | None = typer.Option(None),
) -> None:
    instrument_key = f"{market.strip().upper()}:{symbol.strip().upper()}"
    if not remove(EncryptedLedger(_profile(profile, key_file)), instrument_key, source="cli"):
        raise typer.BadParameter("watchlist instrument is not present")
    console.print_json(json.dumps({"profile": profile, "instrument": instrument_key}))


@app.command("watchlist")
def watchlist(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    items = list_items(ledger)
    settings = watchlist_settings(ledger)
    audit = audit_history(ledger)
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "restriction_enabled": settings.restriction_enabled,
                "configuration_version": settings.version,
                "items": [
                    {
                        "instrument": item.instrument.key,
                        "currency": item.instrument.currency.value,
                        "name": item.instrument.name,
                        "note": item.note,
                    }
                    for item in items
                ],
                "audit": [
                    {
                        "changed_at": entry.changed_at.isoformat(),
                        "action": entry.action,
                        "source": entry.source,
                        "configuration_version": entry.configuration_version,
                        "restriction_enabled": entry.restriction_enabled,
                        "instrument": None
                        if entry.item is None
                        else entry.item.instrument.key,
                    }
                    for entry in audit
                ],
            }
        )
    )


@app.command("watchlist-configure")
def watchlist_configure(
    profile: str,
    restriction_enabled: bool = typer.Option(
        ..., "--restrict-recommendations/--allow-all-recommendations"
    ),
    key_file: Path | None = typer.Option(None),
) -> None:
    settings = configure_restriction(
        EncryptedLedger(_profile(profile, key_file)), restriction_enabled, source="cli"
    )
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "restriction_enabled": settings.restriction_enabled,
                "configuration_version": settings.version,
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
    count, source_hash, instruments = _refresh_moomoo_watchlist(ledger, days, host, port)
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


@app.command("refresh-moomoo-quotes")
def refresh_moomoo_quotes(
    profile: str,
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(11111),
    key_file: Path | None = typer.Option(None),
) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    instruments = tuple(item.instrument for item in list_items(ledger))
    if not instruments:
        raise typer.BadParameter("watchlist is empty")
    provider = MoomooReadOnlyProvider.from_installed_sdk(OpenDConnection(host, port))
    snapshots = provider.market_snapshots(instruments, datetime.now(UTC))
    count, source_hash = archive_and_store_quote_snapshots(ledger, snapshots)
    statuses: dict[str, int] = defaultdict(int)
    for snapshot in snapshots:
        statuses[snapshot.status.value] += 1
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "instruments": len(instruments),
                "quotes": count,
                "source_hash": source_hash,
                "quote_statuses": dict(sorted(statuses.items())),
                "subscription_mode": "none",
                "execution": "denied",
            }
        )
    )


def _refresh_moomoo_watchlist(
    ledger: EncryptedLedger, days: int, host: str, port: int
) -> tuple[int, str, tuple[Instrument, ...]]:
    instruments = tuple(item.instrument for item in list_items(ledger))
    if not instruments:
        raise typer.BadParameter("watchlist is empty")
    end = date.today()
    start = end - timedelta(days=days - 1)
    provider = MoomooReadOnlyProvider.from_installed_sdk(OpenDConnection(host, port))
    prices = provider.daily_prices(instruments, start, end)
    count, source_hash = archive_and_store_daily_prices(ledger, prices)
    return count, source_hash, instruments


def _paper_event(
    kind: PaperEventKind,
    currency: str,
    amount: str,
    *,
    symbol: str | None = None,
    market: str | None = None,
    quantity: str = "0",
    fee: str = "0",
    model_id: str | None = None,
) -> PaperEvent:
    try:
        parsed_currency = Currency(currency.upper())
        instrument = (
            None
            if symbol is None or market is None
            else Instrument(symbol, market, parsed_currency)
        )
        return PaperEvent(
            str(__import__("uuid").uuid4()),
            datetime.now(UTC),
            kind,
            parsed_currency,
            Decimal(amount),
            Decimal(quantity),
            instrument,
            Decimal(fee),
            model_id,
        )
    except ValueError as error:
        raise typer.BadParameter("paper event values are invalid") from error


@app.command("paper-deposit")
def paper_deposit(
    profile: str,
    amount: str,
    currency: str,
    key_file: Path | None = typer.Option(None),
) -> None:
    event = _paper_event(PaperEventKind.DEPOSIT, currency, amount)
    paper.append(EncryptedLedger(_profile(profile, key_file)), event)
    console.print_json(json.dumps({"profile": profile, "event_id": event.event_id}))


@app.command("paper-open")
def paper_open(
    profile: str,
    symbol: str,
    market: str,
    currency: str,
    quantity: str,
    price: str,
    fee: str = typer.Option("0"),
    model_id: str | None = typer.Option(None),
    key_file: Path | None = typer.Option(None),
) -> None:
    try:
        amount = Decimal(quantity) * Decimal(price)
    except Exception as error:
        raise typer.BadParameter("paper quantity and price must be decimal values") from error
    event = _paper_event(
        PaperEventKind.OPEN,
        currency,
        str(amount),
        symbol=symbol,
        market=market,
        quantity=quantity,
        fee=fee,
        model_id=model_id,
    )
    paper.append(EncryptedLedger(_profile(profile, key_file)), event)
    console.print_json(json.dumps({"profile": profile, "event_id": event.event_id}))


@app.command("paper-close")
def paper_close(
    profile: str,
    symbol: str,
    market: str,
    currency: str,
    quantity: str,
    price: str,
    fee: str = typer.Option("0"),
    model_id: str | None = typer.Option(None),
    key_file: Path | None = typer.Option(None),
) -> None:
    try:
        amount = Decimal(quantity) * Decimal(price)
    except Exception as error:
        raise typer.BadParameter("paper quantity and price must be decimal values") from error
    event = _paper_event(
        PaperEventKind.CLOSE,
        currency,
        str(amount),
        symbol=symbol,
        market=market,
        quantity=quantity,
        fee=fee,
        model_id=model_id,
    )
    paper.append(EncryptedLedger(_profile(profile, key_file)), event)
    console.print_json(json.dumps({"profile": profile, "event_id": event.event_id}))


@app.command("paper-portfolio")
def paper_portfolio(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    events = paper.list_events(EncryptedLedger(_profile(profile, key_file)))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "cash": {currency.value: str(amount) for currency, amount in paper.cash(events).items()},
                "positions": {key: str(quantity) for key, quantity in paper.positions(events).items()},
                "event_count": len(events),
            }
        )
    )


@app.command("ml-train")
def ml_train(
    profile: str,
    market: str,
    symbol: str,
    key_file: Path | None = typer.Option(None),
) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    instrument_key = f"{market.strip().upper()}:{symbol.strip().upper()}"
    model = ml.train_instrument_trend_model(instrument_key, historical_prices(ledger, instrument_key))
    ml.store_model(ledger, model)
    prediction = ml.predict_trend(model, historical_prices(ledger, instrument_key))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "model_id": model.model_id,
                "instrument": instrument_key,
                "validation_accuracy": model.validation_accuracy,
                "validation_periods": model.validation_periods,
                "upward_probability": prediction.upward_probability,
                "execution": "denied",
            }
        )
    )


@app.command("ml-predict")
def ml_predict(
    profile: str,
    market: str,
    symbol: str,
    key_file: Path | None = typer.Option(None),
) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    instrument_key = f"{market.strip().upper()}:{symbol.strip().upper()}"
    prediction = ml.predict_trend(
        ml.latest_model(ledger, instrument_key), historical_prices(ledger, instrument_key)
    )
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "model_id": prediction.model_id,
                "instrument": instrument_key,
                "as_of": prediction.as_of.isoformat(),
                "upward_probability": prediction.upward_probability,
                "validation_accuracy": prediction.validation_accuracy,
                "validation_periods": prediction.validation_periods,
                "execution": "denied",
            }
        )
    )


@app.command("ml-rank")
def ml_rank(
    profile: str,
    minimum_validation_accuracy: float = typer.Option(0.5, min=0, max=1),
    key_file: Path | None = typer.Option(None),
) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    candidates: list[dict[str, str | float | int]] = []
    for item in list_items(ledger):
        try:
            prediction = ml.predict_trend(
                ml.latest_model(ledger, item.instrument.key),
                historical_prices(ledger, item.instrument.key),
            )
        except ProviderError:
            continue
        if prediction.validation_accuracy >= minimum_validation_accuracy:
            candidates.append(
                {
                    "instrument": item.instrument.key,
                    "as_of": prediction.as_of.isoformat(),
                    "upward_probability": prediction.upward_probability,
                    "validation_accuracy": prediction.validation_accuracy,
                    "validation_periods": prediction.validation_periods,
                    "model_id": prediction.model_id,
                }
            )
    candidates.sort(key=lambda item: (-float(item["upward_probability"]), str(item["instrument"])))
    console.print_json(
        json.dumps({"profile": profile, "candidates": candidates, "execution": "denied"})
    )


@app.command("research-candidates")
def research_candidates_command(
    profile: str,
    minimum_validation_accuracy: float = typer.Option(0.5, min=0, max=1),
    key_file: Path | None = typer.Option(None),
) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    candidates = advisory.research_candidates(
        ledger,
        tuple(item.instrument.key for item in list_items(ledger)),
        minimum_validation_accuracy=minimum_validation_accuracy,
    )
    artifact = advisory.store_research_artifact(ledger, candidates)
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "artifact_id": artifact.artifact_id,
                "candidates": [candidate.__dict__ for candidate in candidates],
                "execution": "denied",
            }
        )
    )


@app.command("research-artifacts")
def research_artifacts(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    artifacts = advisory.list_research_artifacts(EncryptedLedger(_profile(profile, key_file)))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "artifacts": [
                    {
                        "artifact_id": artifact.artifact_id,
                        "created_at": artifact.created_at.isoformat(),
                        "candidate_count": len(artifact.candidates),
                    }
                    for artifact in artifacts
                ],
                "execution": "denied",
            }
        )
    )


@app.command("llm-configure")
def llm_configure(
    profile: str,
    provider: str,
    model: str,
    budget_period: str = typer.Option("none"),
    budget_limit_sgd: str | None = typer.Option(None),
    input_cost_per_million_sgd: str = typer.Option("0"),
    output_cost_per_million_sgd: str = typer.Option("0"),
    max_output_tokens: int = typer.Option(600, min=1, max=4096),
    api_key_env: str | None = typer.Option(None),
    ollama_url: str = typer.Option("http://127.0.0.1:11434"),
    ollama_local_only: bool = typer.Option(False),
    allow_cloud: bool = typer.Option(False),
) -> None:
    try:
        settings = LLMSettings(
            provider=provider,
            model=model,
            api_key_env=api_key_env,
            ollama_url=ollama_url,
            ollama_local_only=ollama_local_only,
            budget_period=budget_period,
            budget_limit_sgd=budget_limit_sgd,
            input_cost_per_million_sgd=input_cost_per_million_sgd,
            output_cost_per_million_sgd=output_cost_per_million_sgd,
            max_output_tokens=max_output_tokens,
            allow_cloud=allow_cloud,
        )
    except ProfileError as error:
        raise typer.BadParameter(str(error)) from error
    config = replace(load_profile(profile), llm=settings)
    save_profile(config)
    console.print_json(json.dumps({"profile": profile, "llm": _llm_settings_data(settings)}))


@app.command("llm-status")
def llm_status(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    config = _profile(profile, key_file)
    status = llm.budget_status(EncryptedLedger(config), config.llm)
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "llm": _llm_settings_data(config.llm),
                "budget": {
                    "period": status.period,
                    "limit_sgd": None if status.limit_sgd is None else str(status.limit_sgd),
                    "used_sgd": str(status.used_sgd),
                    "remaining_sgd": (
                        None if status.remaining_sgd is None else str(status.remaining_sgd)
                    ),
                },
            }
        )
    )


@app.command("llm-chat")
def llm_chat(
    profile: str,
    question: str,
    key_file: Path | None = typer.Option(None),
) -> None:
    try:
        prompt = llm.validate_public_question(question)
        result = llm.complete(
            EncryptedLedger(_profile(profile, key_file)),
            _profile(profile, key_file).llm,
            system=(
                "Answer a general public-information question. Do not use tools, request private "
                "financial data, give personalized financial advice, or provide instructions to act."
            ),
            prompt=prompt,
        )
    except LLMError as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(json.dumps(_llm_result_data(profile, result)))


@app.command("llm-news-summary")
def llm_news_summary(
    profile: str,
    path: Path = typer.Argument(..., exists=True, dir_okay=False),
    source_url: str = typer.Option(...),
    key_file: Path | None = typer.Option(None),
) -> None:
    try:
        article = path.read_text(encoding="utf-8")
        system, prompt = llm.news_prompt(source_url, article)
        config = _profile(profile, key_file)
        result = llm.complete(EncryptedLedger(config), config.llm, system=system, prompt=prompt)
    except (LLMError, UnicodeDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    payload = _llm_result_data(profile, result)
    payload["source_url"] = source_url
    console.print_json(json.dumps(payload))


@app.command("llm-explain-candidates")
def llm_explain_candidates(
    profile: str,
    minimum_validation_accuracy: float = typer.Option(0.5, min=0, max=1),
    key_file: Path | None = typer.Option(None),
) -> None:
    try:
        config = _profile(profile, key_file)
        ledger = EncryptedLedger(config)
        candidates = advisory.research_candidates(
            ledger,
            tuple(item.instrument.key for item in list_items(ledger)),
            minimum_validation_accuracy=minimum_validation_accuracy,
        )
        data = tuple(
            {
                "instrument": item.instrument_key,
                "as_of": item.as_of,
                "upward_probability": item.upward_probability,
                "validation_accuracy": item.validation_accuracy,
                "validation_periods": item.validation_periods,
                "model_id": item.model_id,
                "risk_flags": item.risk_flags,
            }
            for item in candidates
        )
        system, prompt = llm.research_prompt(data)
        result = llm.complete(ledger, config.llm, system=system, prompt=prompt)
    except (LLMError, ProviderError) as error:
        raise typer.BadParameter(str(error)) from error
    payload = _llm_result_data(profile, result)
    payload["candidate_count"] = len(candidates)
    console.print_json(json.dumps(payload))


@app.command("llm-agent-prompt")
def llm_agent_prompt(agent: str, question: str) -> None:
    try:
        argv = llm.coding_agent_wrapper(agent, question)
    except LLMError as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(
        json.dumps(
            {
                "agent": agent,
                "argv": argv,
                "shell_command": shlex.join(argv),
                "privacy": "public_only",
                "budget_control": "external",
                "cwd_policy": "run outside directories containing private data",
                "execution": "manual_only",
            }
        )
    )


@app.command("scan-alerts")
def scan_alerts(
    profile: str,
    threshold_percent: str = typer.Option("5"),
    key_file: Path | None = typer.Option(None),
) -> None:
    try:
        threshold = Decimal(threshold_percent)
    except Exception as error:
        raise typer.BadParameter("threshold-percent must be a decimal value") from error
    if threshold < 0:
        raise typer.BadParameter("threshold-percent must be non-negative")
    alerts = _scan_price_alerts(EncryptedLedger(_profile(profile, key_file)), threshold)
    console.print_json(json.dumps({"profile": profile, "alerts": alerts, "execution": "denied"}))


def _scan_price_alerts(ledger: EncryptedLedger, threshold: Decimal) -> list[dict[str, str]]:
    alerts = []
    for item in list_items(ledger):
        alert = price_move_alert(item.instrument.key, historical_prices(ledger, item.instrument.key), threshold)
        if alert is not None:
            alerts.append(
                {
                    "instrument": alert.instrument_key,
                    "as_of": alert.as_of.isoformat(),
                    "change_percent": str(alert.change_percent),
                }
            )
    return alerts


@app.command("monitor")
def monitor(
    profile: str,
    days: int = typer.Option(7, min=1, max=365),
    threshold_percent: str = typer.Option("5"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(11111),
    key_file: Path | None = typer.Option(None),
) -> None:
    try:
        threshold = Decimal(threshold_percent)
    except Exception as error:
        raise typer.BadParameter("threshold-percent must be a decimal value") from error
    if threshold < 0:
        raise typer.BadParameter("threshold-percent must be non-negative")
    ledger = EncryptedLedger(_profile(profile, key_file))
    job_label = ScheduleDefinition(profile, 8, 30).label
    try:
        count, source_hash, instruments = _refresh_moomoo_watchlist(ledger, days, host, port)
        alerts = _scan_price_alerts(ledger, threshold)
        content = json.dumps(
            {
                "profile": profile,
                "instruments": len(instruments),
                "prices": count,
                "source_hash": source_hash,
                "alerts": alerts,
                "telegram_delivered": False,
                "execution": "denied",
            }
        )
        artifact = create_artifact("monitor", content)
        persist_scheduled_artifact(ledger, job_label, artifact, "succeeded")
    except Exception as error:
        artifact = create_artifact(
            "monitor",
            json.dumps(
                {
                    "profile": profile,
                    "status": "failed",
                    "error_classification": type(error).__name__,
                    "execution": "denied",
                }
            ),
        )
        persist_scheduled_artifact(ledger, job_label, artifact, "failed")
        raise
    typer.echo(render_terminal(artifact))


@app.command("schedule-render")
def schedule_render(
    profile: str,
    hour_singapore: int = typer.Option(8),
    minute_singapore: int = typer.Option(30),
) -> None:
    load_profile(profile)
    typer.echo(render_schedule(ScheduleDefinition(profile, hour_singapore, minute_singapore)))


@app.command("schedule-install")
def schedule_install(
    profile: str,
    hour_singapore: int = typer.Option(8),
    minute_singapore: int = typer.Option(30),
    unit_directory: Path = typer.Option(Path("~/.config/systemd/user")),
) -> None:
    load_profile(profile)
    definition = ScheduleDefinition(profile, hour_singapore, minute_singapore)
    if platform.system() == "Darwin":
        path = install_macos_schedule(definition, Path("~/Library/LaunchAgents"))
        console.print_json(json.dumps({"plist": str(path)}))
    else:
        service, timer = install_linux_schedule(definition, unit_directory.expanduser())
        console.print_json(json.dumps({"service": str(service), "timer": str(timer)}))


@app.command("schedule-status")
def schedule_status(
    profile: str,
    hour_singapore: int = typer.Option(8),
    minute_singapore: int = typer.Option(30),
) -> None:
    load_profile(profile)
    definition = ScheduleDefinition(profile, hour_singapore, minute_singapore)
    status = (
        macos_schedule_status(definition)
        if platform.system() == "Darwin"
        else linux_schedule_status(definition)
    )
    artifact = latest_scheduled_artifact(EncryptedLedger(_profile(profile, None)), definition.label)
    console.print_json(
        json.dumps(
            {
                "label": status.label,
                "enabled": status.enabled,
                "active": status.active,
                "last_artifact": None
                if artifact is None
                else {
                    "artifact_id": artifact.artifact.artifact_id,
                    "status": artifact.status,
                    "created_at": artifact.artifact.created_at.isoformat(),
                },
            }
        )
    )


@app.command("schedule-artifact")
def schedule_artifact(
    profile: str,
    hour_singapore: int = typer.Option(8),
    minute_singapore: int = typer.Option(30),
) -> None:
    definition = ScheduleDefinition(profile, hour_singapore, minute_singapore)
    artifact = latest_scheduled_artifact(EncryptedLedger(_profile(profile, None)), definition.label)
    if artifact is None:
        raise typer.BadParameter("no scheduled artifact is available")
    typer.echo(render_terminal(artifact.artifact))


@app.command("notify-local")
def notify(title: str, message: str) -> None:
    if not notify_local(title, message):
        raise typer.Exit(1)


@app.command("telegram-recipient-add")
def telegram_recipient_add(
    profile: str,
    alias: str,
    token_env: str = typer.Option("STONKS_CLI_TELEGRAM_TOKEN"),
    recipient_env: str = typer.Option("STONKS_CLI_TELEGRAM_RECIPIENT"),
    key_file: Path | None = typer.Option(None),
) -> None:
    token = os.environ.get(token_env)
    recipient = os.environ.get(recipient_env)
    if token is None or recipient is None:
        raise typer.BadParameter("Telegram token and recipient environment variables are required")
    try:
        configured = add_telegram_recipient(
            EncryptedLedger(_profile(profile, key_file)), alias, token, recipient, source="cli"
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(
        json.dumps({"profile": profile, "recipient_count": len(configured.recipient_aliases)})
    )


@app.command("telegram-configure")
def telegram_configure(
    profile: str,
    recipient_alias: list[str] = typer.Option(..., "--recipient"),
    events: str = typer.Option("advisory,policy_conflict,job_failure"),
    fields: str = typer.Option("instrument,action,rationale"),
    enabled: bool = typer.Option(True, "--enable/--disable"),
    scheduled_enabled: bool = typer.Option(False, "--enable-scheduled/--disable-scheduled"),
    key_file: Path | None = typer.Option(None),
) -> None:
    try:
        event_categories = tuple(
            TelegramEventCategory(value.strip()) for value in events.split(",") if value.strip()
        )
        message_fields = tuple(
            TelegramMessageField(value.strip()) for value in fields.split(",") if value.strip()
        )
        configured = configure_telegram(
            EncryptedLedger(_profile(profile, key_file)),
            enabled=enabled,
            recipient_aliases=tuple(recipient_alias),
            event_categories=event_categories,
            message_fields=message_fields,
            scheduled_enabled=scheduled_enabled,
            source="cli",
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(json.dumps(_telegram_settings_data(profile, configured)))


@app.command("telegram-settings")
def telegram_settings_command(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    ledger = EncryptedLedger(_profile(profile, key_file))
    payload = _telegram_settings_data(profile, telegram_settings(ledger))
    payload["configuration_audit"] = [
        {
            "created_at": record.created_at.isoformat(),
            "version": record.version,
            "source": record.source,
            "recipient_count": record.recipient_count,
            "scheduled_enabled": record.scheduled_enabled,
        }
        for record in telegram_settings_audit(ledger)
    ]
    console.print_json(json.dumps(payload))


def _telegram_settings_data(profile: str, configured: TelegramSettings) -> dict[str, object]:
    return {
        "profile": profile,
        "enabled": configured.enabled,
        "recipient_count": len(configured.recipient_aliases),
        "event_categories": configured.event_categories,
        "message_fields": configured.message_fields,
        "scheduled_enabled": configured.scheduled_enabled,
        "version": configured.version,
    }


def _send_telegram_artifact(
    profile: str,
    artifact_id: str,
    event_category: TelegramEventCategory,
    instrument: str | None,
    action: str | None,
    rationale: str | None,
    amounts: str | None,
    quantities: str | None,
    balances: str | None,
    token_env: str | None,
    recipient_env: str | None,
    key_file: Path | None,
) -> None:
    if (token_env is None) != (recipient_env is None):
        raise typer.BadParameter("Telegram environment overrides require token and recipient")
    token = None if token_env is None else os.environ.get(token_env)
    recipient = None if recipient_env is None else os.environ.get(recipient_env)
    if token_env is not None and (token is None or recipient is None):
        raise typer.BadParameter("Telegram override environment variables are required")
    try:
        records = deliver_telegram(
            EncryptedLedger(_profile(profile, key_file)),
            TelegramArtifact(
                artifact_id,
                event_category,
                instrument,
                action,
                rationale,
                amounts,
                quantities,
                balances,
            ),
            token_override=token,
            chat_id_override=recipient,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if not records:
        raise typer.BadParameter("Telegram delivery is disabled or the artifact event is not enabled")
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "attempted": len(records),
                "delivered": sum(record.result == "delivered" for record in records),
                "failed": sum(record.result == "failed" for record in records),
                "execution": "denied",
            }
        )
    )


@app.command("telegram-send")
def telegram_send(
    profile: str,
    artifact_id: str,
    event_category: TelegramEventCategory = typer.Option(...),
    instrument: str | None = typer.Option(None),
    action: str | None = typer.Option(None),
    rationale: str | None = typer.Option(None),
    amounts: str | None = typer.Option(None),
    quantities: str | None = typer.Option(None),
    balances: str | None = typer.Option(None),
    token_env: str | None = typer.Option(None),
    recipient_env: str | None = typer.Option(None),
    key_file: Path | None = typer.Option(None),
) -> None:
    _send_telegram_artifact(
        profile,
        artifact_id,
        event_category,
        instrument,
        action,
        rationale,
        amounts,
        quantities,
        balances,
        token_env,
        recipient_env,
        key_file,
    )


@app.command("notify-telegram")
def notify_telegram_command(
    profile: str,
    artifact_id: str,
    event_category: TelegramEventCategory = typer.Option(...),
    instrument: str | None = typer.Option(None),
    action: str | None = typer.Option(None),
    rationale: str | None = typer.Option(None),
    token_env: str | None = typer.Option(None),
    recipient_env: str | None = typer.Option(None),
    key_file: Path | None = typer.Option(None),
) -> None:
    _send_telegram_artifact(
        profile,
        artifact_id,
        event_category,
        instrument,
        action,
        rationale,
        None,
        None,
        None,
        token_env,
        recipient_env,
        key_file,
    )


@app.command("telegram-delivery-audit")
def telegram_delivery_audit(profile: str, key_file: Path | None = typer.Option(None)) -> None:
    records = telegram_delivery_records(EncryptedLedger(_profile(profile, key_file)))
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "deliveries": [
                    {
                        "profile": record.profile,
                        "artifact_id": record.artifact_id,
                        "channel": record.channel,
                        "attempted_at": record.attempted_at.isoformat(),
                        "delivered_at": None
                        if record.delivered_at is None
                        else record.delivered_at.isoformat(),
                        "result": record.result,
                        "error_classification": record.error_classification,
                    }
                    for record in records
                ],
            }
        )
    )


@app.command("plugins")
def plugins_command() -> None:
    discovery = discover_with_diagnostics()
    built_in = builtin_provider_manifests()
    console.print_json(
        json.dumps(
            {
                "installed": [identifier for identifier, _ in discovery.providers],
                "built_in": ["csv", *(manifest.identifier for manifest in built_in)],
                "providers": _plugin_manifest_data(built_in, discovery),
                "diagnostics": [
                    {"entry_point": item.entry_point, "error": item.error}
                    for item in discovery.diagnostics
                ],
            }
        )
    )


def _plugin_manifest_data(
    built_in: tuple[PluginManifest, ...], discovery: PluginDiscovery
) -> list[dict[str, object]]:
    adapters: list[dict[str, object]] = [
        {
            "identifier": "csv",
            "api_version": None,
            "capabilities": [],
            "source": "built_in_adapter",
        }
    ]
    manifests = (
        *((manifest, "built_in") for manifest in built_in),
        *((provider.manifest, "external") for _, provider in discovery.providers),
    )
    return adapters + [
        {
            "identifier": manifest.identifier,
            "api_version": manifest.api_version,
            "capabilities": sorted(capability.value for capability in manifest.capabilities),
            "source": source,
        }
        for manifest, source in manifests
    ]


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


@app.command("plugins-validate")
def plugins_validate(profile: str) -> None:
    config = load_profile(profile)
    discovery = discover_with_diagnostics()
    built_in = {"csv", *(manifest.identifier for manifest in builtin_provider_manifests())}
    external = {identifier for identifier, _ in discovery.providers}
    enabled = [
        {
            "identifier": identifier,
            "source": "built_in" if identifier in built_in else "external",
            "valid": identifier in built_in or identifier in external,
        }
        for identifier in config.providers
    ]
    valid = all(item["valid"] is True for item in enabled)
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "valid": valid,
                "enabled": enabled,
                "diagnostics": [
                    {"entry_point": item.entry_point, "error": item.error}
                    for item in discovery.diagnostics
                ],
                "execution": "denied",
            }
        )
    )
    if not valid:
        raise typer.Exit(1)


@app.command("dividend-configure")
def dividend_configure(
    profile: str,
    allow_explicit_credit: bool = typer.Option(
        False, "--allow-explicit-credit/--disallow-explicit-credit"
    ),
    allow_currency_conversion: bool = typer.Option(
        False, "--allow-currency-conversion/--disallow-currency-conversion"
    ),
) -> None:
    try:
        settings = DividendSettings(allow_explicit_credit, allow_currency_conversion)
    except ProfileError as error:
        raise typer.BadParameter(str(error)) from error
    config = replace(load_profile(profile), dividends=settings)
    save_profile(config)
    console.print_json(json.dumps({"profile": profile, "dividends": _dividend_settings_data(settings)}))


@app.command("drawdown-configure")
def drawdown_configure(
    profile: str,
    warning_threshold: str = typer.Option("0.25"),
    response_policy: DrawdownResponsePolicy = typer.Option(DrawdownResponsePolicy.ALERT_ONLY),
) -> None:
    try:
        config = configure_drawdown(load_profile(profile), warning_threshold, response_policy)
    except ProfileError as error:
        raise typer.BadParameter(str(error)) from error
    save_profile(config)
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "drawdown": {
                    "warning_threshold": config.drawdown.warning_threshold,
                    "response_policy": config.drawdown.response_policy,
                    "version": config.drawdown.version,
                    "execution": "denied",
                },
            }
        )
    )


@app.command("benchmark-configure")
def benchmark_configure(
    profile: str,
    component: list[str] = typer.Option([], "--component"),
    reset_defaults: bool = typer.Option(False, "--reset-defaults"),
) -> None:
    if component and reset_defaults:
        raise typer.BadParameter("component and reset-defaults cannot be used together")
    if not component and not reset_defaults:
        raise typer.BadParameter("provide at least one component or reset-defaults")
    try:
        components = (
            BenchmarkSettings().components
            if reset_defaults
            else tuple(_benchmark_component_option(value) for value in component)
        )
        config = configure_benchmark(load_profile(profile), components)
    except ProfileError as error:
        raise typer.BadParameter(str(error)) from error
    save_profile(config)
    console.print_json(json.dumps(_benchmark_settings_data(profile, config.benchmark)))


@app.command("benchmark-settings")
def benchmark_settings(profile: str) -> None:
    console.print_json(json.dumps(_benchmark_settings_data(profile, load_profile(profile).benchmark)))


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


@app.command("moomoo-dividends")
def moomoo_dividends(
    profile: str,
    account_id: str,
    symbol: str,
    market: str,
    currency: str,
    name: str | None = typer.Option(None),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(11111),
    key_file: Path | None = typer.Option(None),
) -> None:
    instrument = _instrument(symbol, market, currency, name)
    provider = MoomooReadOnlyProvider.from_installed_sdk(OpenDConnection(host, port))
    try:
        selected = provider.selected_account(account_id)
    except ProviderError:
        raise typer.BadParameter("account-id is not available from this local OpenD instance")
    inserted, skipped = import_dividend_declarations(
        EncryptedLedger(_profile(profile, key_file)),
        Account("moomoo", selected.account_id),
        instrument,
        provider.corporate_dividends(instrument),
    )
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "account_id": selected.account_id,
                "instrument": instrument.key,
                "inserted": inserted,
                "skipped": skipped,
                "cash_credit": "pending_explicit_mapping",
                "execution": "denied",
            }
        )
    )


@app.command("moomoo-dividend-status")
def moomoo_dividend_status(
    profile: str, account_id: str, key_file: Path | None = typer.Option(None)
) -> None:
    account = Account("moomoo", account_id)
    config = _profile(profile, key_file)
    ledger = EncryptedLedger(config)
    mapped = {
        mapping.declaration_source_key: mapping
        for mapping in list_dividend_credit_mappings(ledger)
    }
    declarations = [
        declaration
        for declaration in list_dividend_declarations(ledger)
        if declaration.account == account
    ]
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "account_id": account.account_id,
                "settings": _dividend_settings_data(config.dividends),
                "declarations": [
                    {
                        "declaration_id": declaration.source.record_id,
                        "instrument": declaration.instrument.key,
                        "announced_at": (
                            None
                            if declaration.announced_at is None
                            else declaration.announced_at.isoformat()
                        ),
                        "record_date": (
                            None if declaration.record_date is None else declaration.record_date.isoformat()
                        ),
                        "payable_date": (
                            None
                            if declaration.payable_date is None
                            else declaration.payable_date.isoformat()
                        ),
                        "status": declaration.status,
                        "statement": declaration.statement,
                        "cash_credit": (
                            "credited"
                            if declaration.source.key in mapped
                            else "pending_explicit_mapping"
                        ),
                        "reason": (
                            None
                            if declaration.source.key in mapped
                            else "declared dividends never credit automatically"
                        ),
                    }
                    for declaration in declarations
                ],
                "cash_flows": [
                    {
                        "cash_flow_id": flow.source.record_id,
                        "clearing_date": flow.clearing_date.isoformat(),
                        "settlement_date": flow.settlement_date.isoformat(),
                        "currency": flow.currency.value,
                        "direction": flow.direction,
                        "amount": str(flow.amount),
                    }
                    for flow in list_cash_flows(ledger)
                    if flow.account == account
                ],
                "cash_snapshots": [
                    {
                        "cash_snapshot_id": snapshot.source.record_id,
                        "observed_at": snapshot.observed_at.isoformat(),
                        "currency": snapshot.currency.value,
                        "amount": str(snapshot.amount),
                    }
                    for snapshot in list_cash_snapshots(ledger)
                    if snapshot.account == account
                ],
                "execution": "denied",
            }
        )
    )


@app.command("moomoo-map-dividend")
def moomoo_map_dividend(
    profile: str,
    account_id: str,
    declaration_id: str = typer.Option(...),
    cash_flow_id: str = typer.Option(...),
    cash_snapshot_id: str = typer.Option(...),
    gross_currency: str = typer.Option(...),
    gross_amount: str = typer.Option(...),
    withholding_amount: str = typer.Option("0"),
    conversion_rate: str | None = typer.Option(None),
    confirm_reconciled_funds: bool = typer.Option(False, "--confirm-reconciled-funds"),
    key_file: Path | None = typer.Option(None),
) -> None:
    config = _profile(profile, key_file)
    if not config.dividends.allow_explicit_credit:
        raise typer.BadParameter("dividend explicit credit is disabled in profile settings")
    try:
        parsed_gross_currency = Currency(gross_currency.strip().upper())
    except ValueError as error:
        raise typer.BadParameter("gross-currency is invalid") from error
    try:
        event, inserted = credit_mapped_dividend(
            EncryptedLedger(config),
            Account("moomoo", account_id),
            declaration_record_id=declaration_id,
            cash_flow_record_id=cash_flow_id,
            cash_snapshot_record_id=cash_snapshot_id,
            gross_currency=parsed_gross_currency,
            gross_amount=gross_amount,
            withholding_amount=withholding_amount,
            conversion_rate=conversion_rate,
            allow_currency_conversion=config.dividends.allow_currency_conversion,
            confirm_reconciled_funds=confirm_reconciled_funds,
        )
    except LedgerError as error:
        raise typer.BadParameter(str(error)) from error
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "account_id": account_id,
                "event_fingerprint": event.fingerprint,
                "inserted": inserted,
                "cash_credit": "explicit_mapping",
                "execution": "denied",
            }
        )
    )


@app.command("moomoo-sync")
def moomoo_sync(
    profile: str,
    account_id: str,
    start: str = typer.Option(...),
    end: str = typer.Option(...),
    opend_timezone: str = typer.Option("Asia/Singapore"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(11111),
    key_file: Path | None = typer.Option(None),
) -> None:
    start_date = _iso_date(start, "start")
    end_date = _iso_date(end, "end")
    if start_date > end_date:
        raise typer.BadParameter("start must not be after end")
    provider = MoomooReadOnlyProvider.from_installed_sdk(OpenDConnection(host, port))
    try:
        selected = provider.selected_account(account_id)
    except ProviderError:
        raise typer.BadParameter("account-id is not available from this local OpenD instance")
    account = Account("moomoo", selected.account_id)
    result = import_account_snapshot(
        EncryptedLedger(_profile(profile, key_file)),
        account,
        fills=provider.historical_fills(
            account.account_id,
            f"{start_date.isoformat()} 00:00:00",
            f"{end_date.isoformat()} 23:59:59",
        ),
        positions=provider.positions(account.account_id),
        balances=provider.balances(account.account_id),
        observed_at=datetime.now(UTC),
        opend_timezone=opend_timezone,
    )
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "account_id": account.account_id,
                "environment": selected.environment,
                "fills_inserted": result.fills_inserted,
                "fills_skipped": result.fills_skipped,
                "position_snapshots": result.position_snapshots,
                "cash_snapshots": result.cash_snapshots,
                "execution": "denied",
            }
        )
    )


@app.command("moomoo-cash-flows")
def moomoo_cash_flows(
    profile: str,
    account_id: str,
    clearing_date: str = typer.Option(...),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(11111),
    key_file: Path | None = typer.Option(None),
) -> None:
    _iso_date(clearing_date, "clearing-date")
    provider = MoomooReadOnlyProvider.from_installed_sdk(OpenDConnection(host, port))
    try:
        selected = provider.selected_account(account_id)
    except ProviderError:
        raise typer.BadParameter("account-id is not available from this local OpenD instance")
    inserted, skipped = import_cash_flows(
        EncryptedLedger(_profile(profile, key_file)),
        Account("moomoo", selected.account_id),
        provider.cash_flows(selected.account_id, clearing_date),
    )
    console.print_json(
        json.dumps(
            {
                "profile": profile,
                "account_id": selected.account_id,
                "clearing_date": clearing_date,
                "inserted": inserted,
                "skipped": skipped,
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


@app.command("moomoo-sdk-status")
def moomoo_sdk_status() -> None:
    status = MoomooReadOnlyProvider.sdk_status()
    console.print_json(
        json.dumps(
            {
                "available": status.available,
                "version": status.version,
                "reason": status.reason,
                "execution": "denied",
            }
        )
    )
    if not status.available:
        raise typer.Exit(1)


@app.command()
def version() -> None:
    typer.echo(__version__)


def main() -> None:
    app()
