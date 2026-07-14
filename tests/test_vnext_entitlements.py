import pytest

from stonks_cli.vnext.errors import OpenDDataEntitlementMissingError
from stonks_cli.vnext.moomoo import (
    MoomooMarketDataEntitlements,
    MoomooMarketDataSubscription,
    require_moomoo_data_entitlement,
)


def test_require_moomoo_data_entitlement_requires_type_and_every_symbol():
    entitlements = MoomooMarketDataEntitlements(1, 1, 99, "Moomoo SG", (MoomooMarketDataSubscription("QUOTE", ("US.AAPL",)),))
    require_moomoo_data_entitlement(entitlements, "QUOTE", ("US.AAPL",))
    with pytest.raises(OpenDDataEntitlementMissingError):
        require_moomoo_data_entitlement(entitlements, "QUOTE", ("US.MSFT",))
    with pytest.raises(OpenDDataEntitlementMissingError):
        require_moomoo_data_entitlement(entitlements, "TICKER", ("US.AAPL",))
