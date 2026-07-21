from stonks_cli.plugins import Capability, PluginManifest
from stonks_cli.types import Account


class FixtureProvider:
    manifest = PluginManifest("fixture", "1.0.0", frozenset({Capability.ACCOUNTS}))

    def accounts(self) -> tuple[Account, ...]:
        return (Account("fixture", "account-1"),)


provider = FixtureProvider()
