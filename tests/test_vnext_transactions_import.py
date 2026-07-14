from datetime import UTC, datetime

import pytest

from stonks_cli.config import AppConfig
from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.exchange_time import ExchangeTimeZone
from stonks_cli.vnext.moomoo import MoomooAccount, MoomooOrderHistoryWindow, MoomooSdkCompatibility, MoomooSdkStatus
from stonks_cli.vnext.transactions_import import PortfolioTransactionSide, import_moomoo_transactions


def test_moomoo_transactions_imports_completed_read_only_orders_in_canonical_order():
    config = AppConfig.model_validate(
        {"vnext": {"enabled": True, "moomoo": {"enabled": True}, "features": {"broker_data": True, "portfolio": True}}}
    )

    transactions = import_moomoo_transactions(
        config,
        MoomooAccount("100", 0, "REAL"),
        MoomooOrderHistoryWindow("2026-07-01 00:00:00", "2026-07-02 00:00:00"),
        ExchangeTimeZone.US_EASTERN,
        sdk_compatibility=_compatible,
        context_factory=lambda host, port: _Context(
            [
                _order("sell", "US.MSFT", "SELL", "2026-07-01 10:00:00"),
                _order("buy", "US.AAPL", "BUY", "2026-07-01 09:30:00"),
                _order("cancelled", "US.NVDA", "BUY", "2026-07-01 09:00:00", status="CANCELLED_ALL", dealt_quantity=0.0),
            ]
        ),
    )

    assert [(item.transaction_id, item.side, item.recorded_at) for item in transactions] == [
        ("buy", PortfolioTransactionSide.BUY, datetime(2026, 7, 1, 13, 30, tzinfo=UTC)),
        ("sell", PortfolioTransactionSide.SELL, datetime(2026, 7, 1, 14, tzinfo=UTC)),
    ]


def test_moomoo_transactions_fail_closed_for_partial_fills_or_unsupported_time_zone_symbols():
    config = AppConfig.model_validate(
        {"vnext": {"enabled": True, "moomoo": {"enabled": True}, "features": {"broker_data": True, "portfolio": True}}}
    )
    window = MoomooOrderHistoryWindow("2026-07-01 00:00:00", "2026-07-02 00:00:00")

    with pytest.raises(VNextExternalDataError, match="incomplete fills"):
        import_moomoo_transactions(
            config,
            MoomooAccount("100", 0, "REAL"),
            window,
            ExchangeTimeZone.US_EASTERN,
            sdk_compatibility=_compatible,
            context_factory=lambda host, port: _Context([_order("partial", "US.AAPL", "BUY", "2026-07-01 09:30:00", status="FILLED_PART", dealt_quantity=1.0)]),
        )
    with pytest.raises(VNextExternalDataError, match="time zone"):
        import_moomoo_transactions(
            config,
            MoomooAccount("100", 0, "REAL"),
            window,
            ExchangeTimeZone.US_EASTERN,
            sdk_compatibility=_compatible,
            context_factory=lambda host, port: _Context([_order("sg", "SG.D05", "BUY", "2026-07-01 09:30:00")]),
        )


def _compatible() -> MoomooSdkCompatibility:
    return MoomooSdkCompatibility(MoomooSdkStatus.COMPATIBLE, "sdk_compatible", "9.1.0")


def _order(order_id, symbol, side, updated_at, *, status="FILLED_ALL", dealt_quantity=2.0):
    return {
        "order_id": order_id,
        "code": symbol,
        "order_status": status,
        "trd_side": side,
        "qty": 2.0,
        "dealt_qty": dealt_quantity,
        "price": 100.0,
        "dealt_avg_price": 101.0 if dealt_quantity else 0.0,
        "currency": "USD",
        "create_time": "2026-07-01 09:00:00",
        "updated_time": updated_at,
    }


class _Context:
    def __init__(self, records):
        self.records = records

    def history_order_list_query(self, **kwargs):
        return 0, self.records

    def close(self) -> None:
        return None
