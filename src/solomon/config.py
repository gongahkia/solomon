# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOLOMON_", env_file=".env", extra="ignore")

    sku: str = Field(default="local", pattern="^(local|server)$")
    data_dir: Path = Field(default=Path("./solomon-data"))
    journal_dir: Path = Field(default=Path("./solomon-journal"))
    kaypoh_repo_path: Path = Field(default=Path("../kaypoh"))
    kaypoh_base_url: str = "http://127.0.0.1:8000"
    kaypoh_api_key: str | None = None
    kaypoh_timeout_seconds: float = 30.0
    server_api_key: str | None = None
    database_url: str = "sqlite:///./solomon-data/solomon.sqlite3"
    local_model_url: str = "http://127.0.0.1:11434/api/generate"
    remote_model_url: str | None = None
    allow_remote_egress: bool = False
    zero_egress_mode: bool = True
    verification_attestation_key: str | None = None

    @model_validator(mode="after")
    def validate_egress_policy(self) -> Settings:
        if self.sku == "local" and self.allow_remote_egress:
            raise ValueError("solomon-local cannot enable remote egress")
        if self.zero_egress_mode and self.allow_remote_egress:
            raise ValueError("zero-egress mode conflicts with remote egress")
        if self.sku == "server" and self.allow_remote_egress and not self.remote_model_url:
            raise ValueError("server remote egress requires SOLOMON_REMOTE_MODEL_URL")
        return self

    def public_diagnostics(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "data_dir": str(self.data_dir),
            "journal_dir": str(self.journal_dir),
            "kaypoh_repo_path": str(self.kaypoh_repo_path),
            "kaypoh_base_url": self.kaypoh_base_url,
            "kaypoh_api_key_configured": self.kaypoh_api_key is not None,
            "server_api_key_configured": self.server_api_key is not None,
            "kaypoh_timeout_seconds": self.kaypoh_timeout_seconds,
            "database_url": self.database_url,
            "local_model_url": self.local_model_url,
            "remote_model_configured": self.remote_model_url is not None,
            "allow_remote_egress": self.allow_remote_egress,
            "zero_egress_mode": self.zero_egress_mode,
            "verification_attestation_key_configured": self.verification_attestation_key is not None,
        }


def local_settings(**overrides: Any) -> Settings:
    return Settings(sku="local", allow_remote_egress=False, zero_egress_mode=True, **overrides)


def server_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {"sku": "server", "zero_egress_mode": False}
    defaults.update(overrides)
    return Settings(**defaults)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
