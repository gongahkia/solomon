# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, generate_private_key

from solomon.api.app import create_app
from solomon.api.oidc import OIDCValidationError, OIDCValidator
from solomon.config import Settings

ISSUER = "https://issuer.example"
AUDIENCE = "solomon-api"


class DiscoveryTransport:
    def __init__(self, keys: list[dict[str, str]], *, issuer: str = ISSUER, jwks_uri: str = f"{ISSUER}/keys") -> None:
        self.keys = keys
        self.issuer = issuer
        self.jwks_uri = jwks_uri
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if str(request.url) == f"{ISSUER}/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": self.issuer, "jwks_uri": self.jwks_uri})
        if str(request.url) == f"{ISSUER}/keys":
            return httpx.Response(200, json={"keys": self.keys})
        return httpx.Response(404)


def _private_key() -> RSAPrivateKey:
    return generate_private_key(public_exponent=65537, key_size=2048)


def _b64url(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _jwk(private_key: RSAPrivateKey, key_id: str) -> dict[str, str]:
    numbers = private_key.public_key().public_numbers()
    return {"kty": "RSA", "kid": key_id, "use": "sig", "alg": "RS256", "n": _b64url(numbers.n), "e": _b64url(numbers.e)}


def _token(
    private_key: RSAPrivateKey,
    key_id: str,
    **claim_overrides: Any,
) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, Any] = {
        "sub": "lawyer-1",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": now + timedelta(minutes=5),
        "nbf": now - timedelta(seconds=1),
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": key_id})


def _validator(transport: DiscoveryTransport) -> OIDCValidator:
    return OIDCValidator(
        issuer=ISSUER,
        audience=AUDIENCE,
        transport=httpx.MockTransport(transport),
    )


def test_oidc_validator_discovers_and_caches_jwks() -> None:
    private_key = _private_key()
    transport = DiscoveryTransport([_jwk(private_key, "first")])
    validator = _validator(transport)
    token = _token(private_key, "first")

    assert validator.validate(token).subject == "lawyer-1"
    assert validator.validate(token).audience == (AUDIENCE,)
    assert transport.requests == [
        f"{ISSUER}/.well-known/openid-configuration",
        f"{ISSUER}/keys",
    ]


def test_oidc_validator_refreshes_jwks_when_kid_rotates() -> None:
    first_private_key = _private_key()
    second_private_key = _private_key()
    transport = DiscoveryTransport([_jwk(first_private_key, "first")])
    validator = _validator(transport)

    validator.validate(_token(first_private_key, "first"))
    transport.keys = [_jwk(second_private_key, "second")]

    assert validator.validate(_token(second_private_key, "second")).subject == "lawyer-1"
    assert transport.requests.count(f"{ISSUER}/.well-known/openid-configuration") == 2
    assert transport.requests.count(f"{ISSUER}/keys") == 2


def test_oidc_validator_allows_registered_claims_within_configured_clock_skew() -> None:
    private_key = _private_key()
    validator = _validator(DiscoveryTransport([_jwk(private_key, "first")]))
    now = datetime.now(timezone.utc)

    identity = validator.validate(
        _token(
            private_key,
            "first",
            exp=now - timedelta(seconds=30),
            nbf=now + timedelta(seconds=30),
        )
    )

    assert identity.subject == "lawyer-1"


@pytest.mark.parametrize(
    ("name", "claims"),
    [
        ("wrong issuer", {"iss": "https://other-issuer.example"}),
        ("wrong audience", {"aud": "another-api"}),
        ("empty subject", {"sub": ""}),
        ("expired beyond skew", {"exp": datetime.now(timezone.utc) - timedelta(minutes=2)}),
        ("not valid yet beyond skew", {"nbf": datetime.now(timezone.utc) + timedelta(minutes=2)}),
    ],
)
def test_oidc_validator_rejects_invalid_registered_claims(name: str, claims: dict[str, Any]) -> None:
    private_key = _private_key()
    validator = _validator(DiscoveryTransport([_jwk(private_key, "first")]))

    with pytest.raises(OIDCValidationError):
        validator.validate(_token(private_key, "first", **claims))


def test_oidc_validator_rejects_unapproved_algorithm_before_discovery() -> None:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": "lawyer-1", "iss": ISSUER, "aud": AUDIENCE, "exp": now + timedelta(minutes=5)},
        "shared-secret-must-be-at-least-thirty-two-bytes",
        algorithm="HS256",
        headers={"kid": "first"},
    )
    transport = DiscoveryTransport([])

    with pytest.raises(OIDCValidationError):
        _validator(transport).validate(token)

    assert transport.requests == []


def test_oidc_validator_rejects_missing_key_id_before_discovery() -> None:
    private_key = _private_key()
    transport = DiscoveryTransport([_jwk(private_key, "first")])
    token = jwt.encode(
        {
            "sub": "lawyer-1",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(OIDCValidationError):
        _validator(transport).validate(token)

    assert transport.requests == []


def test_oidc_validator_rejects_discovery_issuer_mismatch_and_http_jwks() -> None:
    private_key = _private_key()
    token = _token(private_key, "first")

    for transport in (
        DiscoveryTransport([_jwk(private_key, "first")], issuer="https://other-issuer.example"),
        DiscoveryTransport([_jwk(private_key, "first")], jwks_uri="http://issuer.example/keys"),
    ):
        with pytest.raises(OIDCValidationError):
            _validator(transport).validate(token)


def test_oidc_http_authentication_audits_identity_and_denial(tmp_path: Path) -> None:
    private_key = _private_key()
    transport = DiscoveryTransport([_jwk(private_key, "first")])
    app = create_app(
        Settings(
            sku="server",
            zero_egress_mode=False,
            data_dir=tmp_path / "data",
            journal_dir=tmp_path / "journal",
            server_api_key="admin-secret",
            server_auto_provision_tenants=False,
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
        )
    )
    app.state.oidc_validator = _validator(transport)
    expired_token = _token(
        private_key,
        "first",
        exp=datetime.now(timezone.utc) - timedelta(minutes=2),
    )

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            created = await client.post("/tenants", headers={"x-api-key": "admin-secret"}, json={"tenant_id": "oidc"})
            allowed = await client.post(
                "/recall",
                headers={
                    "Authorization": f"Bearer {_token(private_key, 'first')}",
                    "x-tenant-id": "oidc",
                    "x-correlation-id": "oidc-allowed",
                },
                json={"query": "nothing"},
            )
            denied = await client.post(
                "/recall",
                headers={
                    "Authorization": f"Bearer {expired_token}",
                    "x-tenant-id": "oidc",
                    "x-correlation-id": "oidc-denied",
                },
                json={"query": "nothing"},
            )
            return created, allowed, denied

    created, allowed, denied = asyncio.run(exercise())

    assert created.status_code == 201
    assert allowed.status_code == 200
    assert denied.status_code == 401
    entries = [
        entry for entry in app.state.service.audit.list_entries() if entry.event_type == "oidc_authentication"
    ]
    decisions = [
        (entry.payload["decision"], entry.attribution.actor_id, entry.attribution.correlation_id)
        for entry in entries
    ]
    assert decisions == [
        ("allowed", "lawyer-1", "oidc-allowed"),
        ("denied", None, "oidc-denied"),
    ]


def test_oidc_settings_reject_local_and_insecure_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="server SKU"):
        Settings(oidc_issuer=ISSUER, oidc_audience=AUDIENCE)
    with pytest.raises(ValueError, match="HTTPS URL"):
        Settings(
            sku="server",
            zero_egress_mode=False,
            server_api_key="admin-secret",
            oidc_issuer="http://issuer.example",
            oidc_audience=AUDIENCE,
            data_dir=tmp_path / "data",
            journal_dir=tmp_path / "journal",
        )
