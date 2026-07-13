# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from enum import Enum

from pydantic import Field, JsonValue, model_validator

from solomon.api.schemas import SolomonModel


class SecretReferenceProvider(str, Enum):
    ENVIRONMENT = "environment"
    KEYCHAIN = "keychain"
    VAULT = "vault"


class SecretReference(SolomonModel):
    provider: SecretReferenceProvider
    reference: str = Field(min_length=1)


class ConnectorConfiguration(SolomonModel):
    settings: dict[str, JsonValue] = Field(default_factory=dict)
    secret_references: dict[str, SecretReference] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_raw_secret_settings(self) -> ConnectorConfiguration:
        _validate_setting_keys(self.settings)
        return self


def _validate_setting_keys(settings: dict[str, JsonValue]) -> None:
    for key, value in settings.items():
        normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
        if _is_sensitive_key(normalized):
            raise ValueError(f"connector setting {key!r} must use secret_references")
        if isinstance(value, dict):
            _validate_setting_keys(value)


def _is_sensitive_key(key: str) -> bool:
    sensitive = ("password", "secret", "token", "credential", "private_key", "api_key", "authorization")
    return any(token in key for token in sensitive)


__all__ = ["ConnectorConfiguration", "SecretReference", "SecretReferenceProvider"]
