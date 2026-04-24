from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from stonks_cli.config import AppConfig

CLOB_HOST = "https://clob.polymarket.com"


@dataclass(frozen=True)
class ApiCredentials:
    api_key: str
    secret: str
    passphrase: str

    def as_dict(self) -> dict[str, str]:
        return {
            "apiKey": self.api_key,
            "secret": self.secret,
            "passphrase": self.passphrase,
        }


def private_key_from_env(cfg: AppConfig) -> str:
    value = os.getenv(cfg.polymarket.private_key_env or "POLYMARKET_PRIVATE_KEY", "").strip()
    if not value:
        raise ValueError(
            f"missing private key in environment variable {cfg.polymarket.private_key_env or 'POLYMARKET_PRIVATE_KEY'}"
        )
    return value


def load_api_credentials_from_env(cfg: AppConfig) -> ApiCredentials | None:
    api_key = os.getenv(cfg.polymarket.api_key_env or "POLYMARKET_API_KEY", "").strip()
    secret = os.getenv(cfg.polymarket.api_secret_env or "POLYMARKET_API_SECRET", "").strip()
    passphrase = os.getenv(cfg.polymarket.api_passphrase_env or "POLYMARKET_API_PASSPHRASE", "").strip()
    if not api_key or not secret or not passphrase:
        return None
    return ApiCredentials(api_key=api_key, secret=secret, passphrase=passphrase)


def build_clob_client(cfg: AppConfig, *, creds: ApiCredentials | None = None, client_class: type | None = None):
    client_class = client_class or _import_clob_client()
    key = private_key_from_env(cfg)
    kwargs = {"host": CLOB_HOST, "chain_id": cfg.polymarket.chain_id, "key": key}
    if creds is not None:
        kwargs["creds"] = creds.as_dict()
    attempts: list[dict[str, Any]] = [
        kwargs,
        {"host": CLOB_HOST, "chain": cfg.polymarket.chain_id, "key": key, **({"creds": creds.as_dict()} if creds else {})},
        {"config": {"host": CLOB_HOST, "chain": cfg.polymarket.chain_id, "key": key, **({"creds": creds.as_dict()} if creds else {})}},
    ]
    last_error: Exception | None = None
    for attempt in attempts:
        try:
            return client_class(**attempt)
        except TypeError as e:
            last_error = e
            continue
    raise TypeError(f"unable to initialize CLOB client with supported signatures: {last_error}")


def derive_api_credentials(cfg: AppConfig, *, client_class: type | None = None) -> ApiCredentials:
    existing = load_api_credentials_from_env(cfg)
    if existing is not None:
        return existing
    client = build_clob_client(cfg, client_class=client_class)
    payload = _call_first_available(client, "create_or_derive_api_creds", "create_or_derive_api_key")
    if not isinstance(payload, dict):
        raise ValueError("unexpected CLOB API credentials payload")
    api_key = str(payload.get("apiKey") or payload.get("api_key") or "").strip()
    secret = str(payload.get("secret") or "").strip()
    passphrase = str(payload.get("passphrase") or "").strip()
    if not api_key or not secret or not passphrase:
        raise ValueError("derived CLOB API credentials are incomplete")
    return ApiCredentials(api_key=api_key, secret=secret, passphrase=passphrase)


def authenticated_clob_client(cfg: AppConfig, *, client_class: type | None = None):
    creds = derive_api_credentials(cfg, client_class=client_class)
    return build_clob_client(cfg, creds=creds, client_class=client_class), creds


def _import_clob_client():
    try:
        from py_clob_client_v2 import ClobClient
    except Exception as e:
        raise ImportError("live trading requires optional dependency `py-clob-client-v2`") from e
    return ClobClient


def _call_first_available(target: object, *names: str):
    for name in names:
        method = getattr(target, name, None)
        if method is None:
            continue
        return method()
    raise AttributeError(f"client does not expose any of: {', '.join(names)}")
