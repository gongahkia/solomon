from __future__ import annotations

from stonks_cli.config import AppConfig, PolymarketConfig
from stonks_cli.polymarket.auth import ApiCredentials, authenticated_clob_client, derive_api_credentials


class _FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def create_or_derive_api_creds(self):
        return {
            "apiKey": "key-1",
            "secret": "secret-1",
            "passphrase": "pass-1",
        }


def test_derive_api_credentials_prefers_environment(monkeypatch):
    cfg = AppConfig(polymarket=PolymarketConfig())
    monkeypatch.setenv("POLYMARKET_API_KEY", "env-key")
    monkeypatch.setenv("POLYMARKET_API_SECRET", "env-secret")
    monkeypatch.setenv("POLYMARKET_API_PASSPHRASE", "env-pass")

    creds = derive_api_credentials(cfg, client_class=_FakeClient)

    assert creds == ApiCredentials(api_key="env-key", secret="env-secret", passphrase="env-pass")


def test_authenticated_clob_client_derives_credentials_when_env_missing(monkeypatch):
    cfg = AppConfig(polymarket=PolymarketConfig())
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0xabc")
    monkeypatch.delenv("POLYMARKET_API_KEY", raising=False)
    monkeypatch.delenv("POLYMARKET_API_SECRET", raising=False)
    monkeypatch.delenv("POLYMARKET_API_PASSPHRASE", raising=False)

    client, creds = authenticated_clob_client(cfg, client_class=_FakeClient)

    assert isinstance(client, _FakeClient)
    assert creds.api_key == "key-1"
    assert client.kwargs["creds"]["apiKey"] == "key-1"
