# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.connectors import SecretReference
from solomon.contracts import AuthoritySource
from solomon.workflow.models import AuthorityChangeEvent


class AuthorityWebhookPayload(SolomonModel):
    idempotency_key: str = Field(min_length=1)
    authority_id: str = Field(min_length=1)
    new_version: str = Field(min_length=1)
    changed_at: datetime
    previous_version: str | None = None
    evidence_url: str | None = None
    evidence_sha256: str | None = None
    diff: dict[str, Any] = Field(default_factory=dict)


class AuthorityWebhookVerificationError(ValueError):
    pass


class AuthorityWebhookIntake:
    def __init__(self, resolve_secret: Callable[[SecretReference], str]) -> None:
        self.resolve_secret = resolve_secret

    def parse(self, source: AuthoritySource, body: bytes, signature: str | None) -> AuthorityChangeEvent:
        secret_reference = source.config.secret_references.get("webhook_signing_secret")
        if secret_reference is None:
            raise AuthorityWebhookVerificationError("authority source has no webhook signing-secret reference")
        expected = hmac.new(self.resolve_secret(secret_reference).encode(), body, hashlib.sha256).hexdigest()
        supplied = _signature_value(signature)
        if supplied is None or not hmac.compare_digest(supplied, expected):
            raise AuthorityWebhookVerificationError("authority webhook signature is invalid")
        try:
            payload = AuthorityWebhookPayload.model_validate_json(body)
        except ValueError as exc:
            raise AuthorityWebhookVerificationError("authority webhook payload is invalid") from exc
        return AuthorityChangeEvent(
            source_id=source.id,
            idempotency_key=payload.idempotency_key,
            authority_id=payload.authority_id,
            previous_version=payload.previous_version,
            new_version=payload.new_version,
            changed_at=payload.changed_at,
            evidence_url=payload.evidence_url,
            evidence_sha256=payload.evidence_sha256,
            diff=payload.diff,
        )


def _signature_value(signature: str | None) -> str | None:
    if signature is None:
        return None
    prefix = "sha256="
    return signature[len(prefix) :] if signature.startswith(prefix) else None


__all__ = ["AuthorityWebhookIntake", "AuthorityWebhookPayload", "AuthorityWebhookVerificationError"]
