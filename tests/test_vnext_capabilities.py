from __future__ import annotations

import pytest

from stonks_cli.vnext.capabilities import Capability, CapabilityRegistry
from stonks_cli.vnext.errors import VNextExecutionDeniedError, VNextInvariantError


def test_capability_registry_exposes_only_explicitly_enabled_read_only_features():
    registry = CapabilityRegistry.from_feature_data(
        {
            "broker_data": True,
            "crypto_research": True,
            "portfolio": False,
            "operator_reports": False,
            "execution": False,
        }
    )

    assert registry.is_enabled(Capability.BROKER_DATA) is True
    assert registry.is_enabled(Capability.PORTFOLIO) is False
    registry.require(Capability.CRYPTO_RESEARCH)
    with pytest.raises(VNextInvariantError, match="capability is disabled"):
        registry.require(Capability.PORTFOLIO)
    with pytest.raises(VNextExecutionDeniedError):
        registry.require(Capability.EXECUTION)


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"broker_data": True, "crypto_research": False, "portfolio": False, "operator_reports": False, "execution": False, "unknown": False},
        {"broker_data": "true", "crypto_research": False, "portfolio": False, "operator_reports": False, "execution": False},
        {"broker_data": False, "crypto_research": False, "portfolio": False, "operator_reports": False, "execution": True},
    ],
)
def test_capability_registry_rejects_malformed_or_execution_enabled_feature_data(data):
    with pytest.raises((TypeError, ValueError, VNextExecutionDeniedError)):
        CapabilityRegistry.from_feature_data(data)
