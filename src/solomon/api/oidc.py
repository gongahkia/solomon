# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt


class OIDCValidationError(ValueError):
    pass


@dataclass(frozen=True)
class OIDCIdentity:
    subject: str
    issuer: str
    audience: tuple[str, ...]
    claims: dict[str, Any]


class OIDCValidator:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        clock_skew_seconds: int = 60,
        cache_seconds: int = 300,
        allowed_algorithms: frozenset[str] = frozenset({"RS256", "ES256"}),
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.clock_skew_seconds = clock_skew_seconds
        self.cache_seconds = cache_seconds
        self.allowed_algorithms = allowed_algorithms
        self.transport = transport
        if not _is_https_url(self.issuer):
            raise ValueError("OIDC issuer must be an HTTPS URL")
        if not audience:
            raise ValueError("OIDC audience is required")
        if not allowed_algorithms:
            raise ValueError("at least one OIDC signing algorithm is required")
        self._metadata: dict[str, Any] | None = None
        self._jwks: dict[str, jwt.PyJWK] = {}
        self._expires_at = 0.0

    def validate(self, token: str) -> OIDCIdentity:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise OIDCValidationError("malformed bearer token") from exc
        algorithm = header.get("alg")
        key_id = header.get("kid")
        if algorithm not in self.allowed_algorithms or not isinstance(key_id, str) or not key_id:
            raise OIDCValidationError("unsupported bearer token header")
        key = self._key_for(key_id)
        if key.algorithm_name != algorithm:
            raise OIDCValidationError("bearer token algorithm does not match key")
        try:
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=sorted(self.allowed_algorithms),
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.clock_skew_seconds,
                options={"require": ["sub", "iss", "aud", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise OIDCValidationError("invalid bearer token") from exc
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject:
            raise OIDCValidationError("invalid bearer token subject")
        audience = claims["aud"]
        values = (audience,) if isinstance(audience, str) else tuple(str(value) for value in audience)
        return OIDCIdentity(subject=subject, issuer=str(claims["iss"]), audience=values, claims=claims)

    def _key_for(self, key_id: str) -> jwt.PyJWK:
        self._refresh_if_needed()
        key = self._jwks.get(key_id)
        if key is None:
            self._refresh(force=True)
            key = self._jwks.get(key_id)
        if key is None:
            raise OIDCValidationError("bearer token key is unavailable")
        return key

    def _refresh_if_needed(self) -> None:
        if self._metadata is None or time.monotonic() >= self._expires_at:
            self._refresh(force=True)

    def _refresh(self, *, force: bool) -> None:
        if not force and self._metadata is not None and time.monotonic() < self._expires_at:
            return
        metadata = self._get_json(f"{self.issuer}/.well-known/openid-configuration")
        jwks_uri = metadata.get("jwks_uri") if isinstance(metadata, dict) else None
        if metadata.get("issuer") != self.issuer or not isinstance(jwks_uri, str) or not _is_https_url(jwks_uri):
            raise OIDCValidationError("invalid OIDC discovery document")
        jwks = self._get_json(jwks_uri)
        raw_keys = jwks.get("keys") if isinstance(jwks, dict) else None
        if not isinstance(raw_keys, list):
            raise OIDCValidationError("invalid OIDC key set")
        keys: dict[str, jwt.PyJWK] = {}
        for raw_key in raw_keys:
            if (
                not isinstance(raw_key, dict)
                or not isinstance(raw_key.get("kid"), str)
                or raw_key.get("use") not in {None, "sig"}
            ):
                continue
            try:
                key = jwt.PyJWK.from_dict(raw_key, algorithm=raw_key.get("alg"))
            except jwt.PyJWTError:
                continue
            if key.algorithm_name in self.allowed_algorithms:
                keys[str(raw_key["kid"])] = key
        if not keys:
            raise OIDCValidationError("OIDC key set has no supported signing keys")
        self._metadata = metadata
        self._jwks = keys
        self._expires_at = time.monotonic() + self.cache_seconds

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            with httpx.Client(transport=self.transport, timeout=10.0) as client:
                response = client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCValidationError("OIDC metadata is unavailable") from exc
        if not isinstance(payload, dict):
            raise OIDCValidationError("OIDC metadata must be an object")
        return payload


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)
