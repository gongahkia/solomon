from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.fx_conversion_cost import estimate_fx_conversion_cost
from stonks_cli.vnext.fx_reference_rates import FXReferenceRate


def test_fx_conversion_cost_estimates_quote_currency_spread_from_direct_reference_rate():
    rate = FXReferenceRate("SGD", "USD", 0.75, datetime(2026, 7, 14, 12, tzinfo=UTC))

    estimate = estimate_fx_conversion_cost(1000.0, rate, 20.0)

    assert estimate.gross_quote_amount == 750.0
    assert estimate.estimated_cost_quote == 1.5
    assert estimate.net_quote_amount == 748.5


def test_fx_conversion_cost_fails_closed_for_malformed_inputs_or_overflow():
    rate = FXReferenceRate("SGD", "USD", 0.75, datetime(2026, 7, 14, 12, tzinfo=UTC))

    with pytest.raises(ValueError, match="base amount"):
        estimate_fx_conversion_cost(0.0, rate, 20.0)
    with pytest.raises(ValueError, match="spread"):
        estimate_fx_conversion_cost(1000.0, rate, 10_000.1)
    with pytest.raises(TypeError, match="reference rate"):
        estimate_fx_conversion_cost(1000.0, None, 20.0)
    with pytest.raises(ValueError, match="overflowed"):
        estimate_fx_conversion_cost(2.0, FXReferenceRate("SGD", "USD", 1e308, datetime(2026, 7, 14, 12, tzinfo=UTC)), 20.0)
