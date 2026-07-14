from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.fx_reference_rates import FXReferenceRate, ingest_fx_reference_rates


def test_fx_reference_rate_ingestion_requires_complete_canonical_direct_rates():
    class Provider:
        provider_id = "fixture"

        def list_fx_reference_rates(self, base_currencies, quote_currency):
            assert base_currencies == ("USD", "ZAR")
            assert quote_currency == "SGD"
            return (
                FXReferenceRate("USD", "SGD", 1.34, datetime(2026, 7, 14, tzinfo=UTC)),
                FXReferenceRate("ZAR", "SGD", 0.074, datetime(2026, 7, 14, tzinfo=UTC)),
            )

    batch = ingest_fx_reference_rates(Provider(), ("ZAR", "USD"), "SGD")

    assert [(rate.base_currency, rate.quote_amount_per_base) for rate in batch.rates] == [("USD", 1.34), ("ZAR", 0.074)]


def test_fx_reference_rate_ingestion_fails_closed_for_missing_or_invalid_rates():
    class IncompleteProvider:
        provider_id = "fixture"

        def list_fx_reference_rates(self, base_currencies, quote_currency):
            return (FXReferenceRate("USD", "SGD", 1.34, datetime(2026, 7, 14, tzinfo=UTC)),)

    with pytest.raises(VNextExternalDataError, match="incomplete"):
        ingest_fx_reference_rates(IncompleteProvider(), ("USD", "ZAR"), "SGD")
    with pytest.raises(ValueError, match="quote currency"):
        ingest_fx_reference_rates(IncompleteProvider(), ("USD",), "USD")
