from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from stonks_cli.vnext.errors import VNextExecutionDeniedError, VNextInvariantError


class Capability(StrEnum):
    BROKER_DATA = "broker_data"
    CRYPTO_RESEARCH = "crypto_research"
    PORTFOLIO = "portfolio"
    OPERATOR_REPORTS = "operator_reports"
    EXECUTION = "execution"


@dataclass(frozen=True)
class CapabilityRegistry:
    enabled: frozenset[Capability]

    def __post_init__(self) -> None:
        if not all(isinstance(capability, Capability) for capability in self.enabled):
            raise TypeError("enabled capabilities must be Capability values")
        if Capability.EXECUTION in self.enabled:
            raise VNextExecutionDeniedError("execution capability cannot be enabled")

    @classmethod
    def from_feature_data(cls, data: Mapping[str, object]) -> CapabilityRegistry:
        if not isinstance(data, Mapping):
            raise TypeError("feature data must be an object")
        expected = {capability.value for capability in Capability}
        if set(data) != expected:
            raise ValueError("feature data keys do not match capability registry")
        if any(not isinstance(value, bool) for value in data.values()):
            raise ValueError("feature values must be booleans")
        return cls(frozenset(Capability(name) for name, enabled in data.items() if enabled))

    def is_enabled(self, capability: Capability) -> bool:
        _validate_capability(capability)
        return capability in self.enabled

    def require(self, capability: Capability) -> None:
        _validate_capability(capability)
        if capability is Capability.EXECUTION:
            raise VNextExecutionDeniedError()
        if capability not in self.enabled:
            raise VNextInvariantError(f"capability is disabled:{capability}")


def _validate_capability(capability: object) -> None:
    if not isinstance(capability, Capability):
        raise TypeError("capability must be a Capability")
