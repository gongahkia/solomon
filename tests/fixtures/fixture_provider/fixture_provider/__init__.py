from datetime import date, datetime
from decimal import Decimal

from stonks_cli.market_data import DailyPrice
from stonks_cli.plugins import Capability, PluginManifest
from stonks_cli.types import Account, Instrument


class FixtureProvider:
    manifest = PluginManifest(
        "fixture",
        "1.0.0",
        frozenset(
            {
                Capability.ACCOUNTS,
                Capability.CORPORATE_ACTIONS,
                Capability.MARKET_DATA,
                Capability.TRANSACTIONS,
            }
        ),
    )

    def accounts(self) -> tuple[Account, ...]:
        return (Account("fixture", "account-1"),)

    def transaction_records(
        self, account: Account, start: datetime, end: datetime
    ) -> tuple[dict[str, str], ...]:
        return ({"account": account.key, "start": start.isoformat(), "end": end.isoformat()},)

    def corporate_actions(
        self, account: Account, start: datetime, end: datetime
    ) -> tuple[dict[str, str], ...]:
        return ({"account": account.key, "start": start.isoformat(), "end": end.isoformat()},)

    def daily_prices(
        self, instruments: tuple[Instrument, ...], start: date, end: date
    ) -> tuple[DailyPrice, ...]:
        return tuple(DailyPrice(item, start, Decimal("100"), "a" * 64) for item in instruments)


provider = FixtureProvider()
