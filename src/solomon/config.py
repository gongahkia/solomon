# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOLOMON_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path("./solomon-data"))
    journal_dir: Path = Field(default=Path("./solomon-journal"))
    kaypoh_repo_path: Path = Field(default=Path("../kaypoh"))
    kaypoh_base_url: str = "http://127.0.0.1:8000"
    kaypoh_api_key: str | None = None
    kaypoh_timeout_seconds: float = 30.0

    def public_diagnostics(self) -> dict[str, Any]:
        return {
            "data_dir": str(self.data_dir),
            "journal_dir": str(self.journal_dir),
            "kaypoh_repo_path": str(self.kaypoh_repo_path),
            "kaypoh_base_url": self.kaypoh_base_url,
            "kaypoh_api_key_configured": self.kaypoh_api_key is not None,
            "kaypoh_timeout_seconds": self.kaypoh_timeout_seconds,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

