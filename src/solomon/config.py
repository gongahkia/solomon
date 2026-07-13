# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from solomon.api.auth import OIDC_AUTH_ROLES
from solomon.boundary.solomon import BoundaryPolicy
from solomon.credence.policy import CredencePolicy
from solomon.currency.engine import VerificationPolicy
from solomon.currency.models import CredenceTier
from solomon.orchestrator.retrieval import (
    HashedEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    RetrievalEmbeddingProvider,
)
from solomon.store.encryption import ContentEnvelopeCipher


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOLOMON_", env_file=".env", extra="ignore")

    sku: str = Field(default="local", pattern="^(local|server)$")
    data_dir: Path = Field(default=Path("./solomon-data"))
    journal_dir: Path = Field(default=Path("./solomon-journal"))
    boundary_engine_path: Path = Field(default=Path("src/solomon/boundary/engine"))
    boundary_base_url: str = "in-process://solomon-boundary-engine"
    boundary_api_key: str | None = None
    boundary_timeout_seconds: float = 30.0
    jurisdiction: str = "SG"
    server_api_key: str | None = None
    server_auth_mode: str = Field(default="oidc", pattern="^(oidc|legacy-api-key)$")
    server_auto_provision_tenants: bool = True
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_clock_skew_seconds: int = Field(default=60, ge=0, le=300)
    oidc_jwks_cache_seconds: int = Field(default=300, ge=1, le=3600)
    oidc_role_claim: str = Field(default="roles", min_length=1)
    oidc_role_mappings: dict[str, str] = Field(default_factory=dict)
    database_url: str = "sqlite:///./solomon-data/solomon.sqlite3"
    content_encryption_key_ref: str | None = Field(default=None, min_length=1, max_length=256)
    content_encryption_key: SecretStr | None = None
    retention_default_days: int | None = Field(default=None, ge=1, le=36_500)
    telemetry_enabled: bool = False
    telemetry_service_name: str = Field(default="solomon", min_length=1, max_length=120)
    telemetry_otlp_endpoint: str | None = None
    local_model_url: str = "http://127.0.0.1:11434/api/generate"
    local_model_name: str = "qwen2.5-coder:1.5b"
    remote_model_url: str | None = None
    remote_model_provider: str = Field(default="generic", pattern="^(generic|openai-responses)$")
    remote_model_name: str = "gpt-5.5"
    remote_model_api_key: str | None = None
    allow_remote_egress: bool = False
    zero_egress_mode: bool = True
    embedding_provider: str = Field(default="local-hashed", pattern="^(local-hashed|openai-compatible)$")
    embedding_remote_url: str | None = None
    embedding_remote_model: str = "text-embedding-3-small"
    embedding_remote_api_key: SecretStr | None = None
    embedding_dimensions: int = Field(default=256, ge=1, le=2000)
    allow_remote_embedding_egress: bool = False
    verification_attestation_key: str | None = None
    verification_policy_version: str = "verification-policy.v1"
    verification_default_max_age_days: int = Field(default=365, ge=1)
    verification_high_stakes_max_age_days: int = Field(default=180, ge=1)
    credence_policy_version: str = "credence-policy.v1"
    credence_load_bearing_minimum: str = "Verified"
    console_user_id: str = "dev"
    console_bearer_token: str | None = None
    console_role: str = Field(default="curator", pattern="^(admin|curator|reviewer|lawyer|integration)$")

    @model_validator(mode="after")
    def validate_egress_policy(self) -> Settings:
        self.jurisdiction = _normalized_jurisdiction(self.jurisdiction)
        if self.sku == "local" and self.allow_remote_egress:
            raise ValueError("solomon-local cannot enable remote egress")
        if self.sku == "server" and self.server_auth_mode == "legacy-api-key" and not self.server_api_key:
            raise ValueError("legacy API-key mode requires SOLOMON_SERVER_API_KEY")
        if (self.oidc_issuer is None) != (self.oidc_audience is None):
            raise ValueError("OIDC issuer and audience must be configured together")
        if self.oidc_issuer is not None:
            if self.sku != "server":
                raise ValueError("OIDC is available only for the server SKU")
            issuer = urlparse(self.oidc_issuer)
            if issuer.scheme != "https" or not issuer.netloc or issuer.query or issuer.fragment:
                raise ValueError("OIDC issuer must be an HTTPS URL without query or fragment")
            if not self.oidc_role_mappings:
                raise ValueError("OIDC requires at least one role mapping")
            invalid_role_mapping = any(
                not claim_value or mapped_role not in OIDC_AUTH_ROLES
                for claim_value, mapped_role in self.oidc_role_mappings.items()
            )
            if invalid_role_mapping:
                raise ValueError("OIDC role mappings must map non-empty claim values to Solomon roles")
        oidc_configuration_missing = self.oidc_issuer is None and not self.server_api_key
        if self.sku == "server" and self.server_auth_mode == "oidc" and oidc_configuration_missing:
            raise ValueError("OIDC server mode requires issuer, audience, and role mappings")
        if (self.content_encryption_key_ref is None) != (self.content_encryption_key is None):
            raise ValueError("content encryption key reference and key must be configured together")
        if self.content_encryption_key_ref is not None and self.content_encryption_key is not None:
            ContentEnvelopeCipher(
                key_ref=self.content_encryption_key_ref,
                wrapping_key=self.content_encryption_key,
            )
        if self.console_role not in OIDC_AUTH_ROLES:
            raise ValueError("console role must be a Solomon role")
        if self.telemetry_otlp_endpoint is not None:
            endpoint = urlparse(self.telemetry_otlp_endpoint)
            if endpoint.scheme not in {"http", "https"} or not endpoint.netloc or endpoint.query or endpoint.fragment:
                raise ValueError("OpenTelemetry endpoint must be an absolute HTTP(S) URL without query or fragment")
            if not self.telemetry_enabled:
                raise ValueError("OpenTelemetry endpoint requires SOLOMON_TELEMETRY_ENABLED=true")
        if self.zero_egress_mode and self.allow_remote_egress:
            raise ValueError("zero-egress mode conflicts with remote egress")
        if self.sku == "server" and self.allow_remote_egress and not self.remote_model_url:
            raise ValueError("server remote egress requires SOLOMON_REMOTE_MODEL_URL")
        if self.embedding_provider == "local-hashed" and self.allow_remote_embedding_egress:
            raise ValueError("remote embedding egress requires the openai-compatible provider")
        if self.embedding_provider == "openai-compatible":
            if self.sku != "server":
                raise ValueError("solomon-local cannot enable remote embedding egress")
            if self.zero_egress_mode or not self.allow_remote_embedding_egress:
                raise ValueError("remote embedding egress requires explicit opt-in outside zero-egress mode")
            if not self.embedding_remote_url or not self.embedding_remote_api_key:
                raise ValueError("remote embedding egress requires URL and API key")
            if urlparse(self.embedding_remote_url).scheme not in {"http", "https"}:
                raise ValueError("remote embedding URL must use http or https")
        return self

    def public_diagnostics(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "data_dir": str(self.data_dir),
            "journal_dir": str(self.journal_dir),
            "boundary_engine_path": str(self.boundary_engine_path),
            "boundary_base_url": self.boundary_base_url,
            "boundary_api_key_configured": self.boundary_api_key is not None,
            "server_api_key_configured": self.server_api_key is not None,
            "server_auth_mode": self.server_auth_mode,
            "boundary_timeout_seconds": self.boundary_timeout_seconds,
            "jurisdiction": self.jurisdiction,
            "database_url": self.database_url,
            "content_encryption_configured": self.content_encryption_key is not None,
            "content_encryption_key_ref": self.content_encryption_key_ref,
            "retention_default_days": self.retention_default_days,
            "telemetry_enabled": self.telemetry_enabled,
            "telemetry_service_name": self.telemetry_service_name,
            "telemetry_otlp_configured": self.telemetry_otlp_endpoint is not None,
            "server_auto_provision_tenants": self.server_auto_provision_tenants,
            "oidc_configured": self.oidc_issuer is not None,
            "oidc_clock_skew_seconds": self.oidc_clock_skew_seconds,
            "oidc_role_claim": self.oidc_role_claim,
            "oidc_role_mapping_count": len(self.oidc_role_mappings),
            "local_model_url": self.local_model_url,
            "local_model_name": self.local_model_name,
            "remote_model_configured": self.remote_model_url is not None,
            "remote_model_provider": self.remote_model_provider,
            "remote_model_name": self.remote_model_name,
            "remote_model_api_key_configured": self.remote_model_api_key is not None,
            "allow_remote_egress": self.allow_remote_egress,
            "zero_egress_mode": self.zero_egress_mode,
            "embedding_provider": self.embedding_provider,
            "embedding_remote_configured": self.embedding_remote_url is not None,
            "embedding_remote_model": self.embedding_remote_model,
            "embedding_remote_api_key_configured": self.embedding_remote_api_key is not None,
            "embedding_dimensions": self.embedding_dimensions,
            "allow_remote_embedding_egress": self.allow_remote_embedding_egress,
            "verification_attestation_key_configured": self.verification_attestation_key is not None,
            "verification_policy_version": self.verification_policy_version,
            "verification_default_max_age_days": self.verification_default_max_age_days,
            "verification_high_stakes_max_age_days": self.verification_high_stakes_max_age_days,
            "credence_policy_version": self.credence_policy_version,
            "credence_load_bearing_minimum": self.credence_load_bearing_minimum,
            "console_user_id": self.console_user_id,
            "console_bearer_token_configured": self.console_bearer_token is not None,
            "console_role": self.console_role,
        }


def local_settings(**overrides: Any) -> Settings:
    return Settings(sku="local", allow_remote_egress=False, zero_egress_mode=True, **overrides)


def server_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "sku": "server",
        "zero_egress_mode": False,
        "server_api_key": "test-server-key",
        "server_auth_mode": "legacy-api-key",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def embedding_provider_from_settings(settings: Settings) -> RetrievalEmbeddingProvider:
    if settings.embedding_provider == "openai-compatible":
        api_key = settings.embedding_remote_api_key
        if settings.embedding_remote_url is None or api_key is None:
            raise ValueError("remote embedding provider configuration is incomplete")
        return OpenAICompatibleEmbeddingProvider(
            url=settings.embedding_remote_url,
            api_key=api_key,
            model=settings.embedding_remote_model,
            dimensions=settings.embedding_dimensions,
        )
    return HashedEmbeddingProvider()


def content_envelope_from_settings(settings: Settings) -> ContentEnvelopeCipher | None:
    if settings.content_encryption_key_ref is None or settings.content_encryption_key is None:
        return None
    return ContentEnvelopeCipher(
        key_ref=settings.content_encryption_key_ref,
        wrapping_key=settings.content_encryption_key,
    )


def verification_policy_from_settings(settings: Settings) -> VerificationPolicy:
    return VerificationPolicy(
        default_max_age_days=settings.verification_default_max_age_days,
        high_stakes_max_age_days=settings.verification_high_stakes_max_age_days,
    )


def credence_policy_from_settings(settings: Settings) -> CredencePolicy:
    return CredencePolicy(load_bearing_minimum=CredenceTier(settings.credence_load_bearing_minimum))


def boundary_policy_from_settings(settings: Settings, *, jurisdiction: str | None = None) -> BoundaryPolicy:
    code = _normalized_jurisdiction(jurisdiction or settings.jurisdiction)
    return BoundaryPolicy(default_source_jurisdiction=code, default_destination_jurisdiction=code)


def settings_with_jurisdiction(settings: Settings, jurisdiction: str) -> Settings:
    values = settings.model_dump()
    values["jurisdiction"] = _normalized_jurisdiction(jurisdiction)
    return Settings(**values)


def _normalized_jurisdiction(value: str) -> str:
    code = value.upper()
    if code not in {"SG", "MY", "UK", "EU"}:
        raise ValueError("jurisdiction must be one of SG, MY, UK, EU")
    return code


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
