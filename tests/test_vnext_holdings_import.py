from datetime import UTC, datetime

import pytest

from stonks_cli.config import AppConfig
from stonks_cli.vnext.errors import VNextConfigurationError, VNextExternalDataError
from stonks_cli.vnext.holdings_import import import_moomoo_holdings
from stonks_cli.vnext.moomoo import MoomooAccount, MoomooSdkCompatibility, MoomooSdkStatus
from stonks_cli.vnext.portfolio_domain import PortfolioAssetClass


def test_moomoo_holdings_imports_read_only_us_and_sg_positions_into_canonical_snapshot():
    config = AppConfig.model_validate(
        {"vnext": {"enabled": True, "moomoo": {"enabled": True}, "features": {"broker_data": True, "portfolio": True}}}
    )

    snapshot = import_moomoo_holdings(
        config,
        MoomooAccount("100", 0, "REAL"),
        datetime(2026, 7, 14, 12, tzinfo=UTC),
        sdk_compatibility=_compatible,
        context_factory=lambda host, port: _Context(
            [
                {"position_id": "msft", "code": "US.MSFT", "qty": 2, "can_sell_qty": 2, "currency": "USD", "market_val": 800},
                {"position_id": "d05", "code": "SG.D05", "qty": 1, "can_sell_qty": 1, "currency": "SGD", "market_val": 40},
            ]
        ),
    )

    assert [(holding.symbol, holding.asset_class) for holding in snapshot.holdings] == [
        ("SG.D05", PortfolioAssetClass.EQUITY),
        ("US.MSFT", PortfolioAssetClass.EQUITY),
    ]


def test_moomoo_holdings_import_fails_closed_without_portfolio_capability_or_for_unsupported_positions():
    config = AppConfig.model_validate({"vnext": {"enabled": True, "moomoo": {"enabled": True}, "features": {"broker_data": True}}})
    with pytest.raises(VNextConfigurationError, match="portfolio capabilities"):
        import_moomoo_holdings(config, MoomooAccount("100", 0, "REAL"), datetime(2026, 7, 14, 12, tzinfo=UTC), sdk_compatibility=_compatible)

    enabled_config = AppConfig.model_validate(
        {"vnext": {"enabled": True, "moomoo": {"enabled": True}, "features": {"broker_data": True, "portfolio": True}}}
    )
    with pytest.raises(VNextExternalDataError, match="unsupported"):
        import_moomoo_holdings(
            enabled_config,
            MoomooAccount("100", 0, "REAL"),
            datetime(2026, 7, 14, 12, tzinfo=UTC),
            sdk_compatibility=_compatible,
            context_factory=lambda host, port: _Context(
                [{"position_id": "hk", "code": "HK.00700", "qty": 1, "can_sell_qty": 1, "currency": "HKD", "market_val": 100}]
            ),
        )


def _compatible() -> MoomooSdkCompatibility:
    return MoomooSdkCompatibility(MoomooSdkStatus.COMPATIBLE, "sdk_compatible", "9.1.0")


class _Context:
    def __init__(self, records):
        self.records = records

    def position_list_query(self, **kwargs):
        return 0, self.records

    def close(self) -> None:
        return None
