# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from solomon.authority_webhooks import AuthorityWebhookIntake, AuthorityWebhookVerificationError
from solomon.connectors import ConnectorConfiguration, SecretReference, SecretReferenceProvider
from solomon.contracts import AuthoritySource, AuthoritySourceKind


def _source() -> AuthoritySource:
    return AuthoritySource(
        id="official-gazette",
        name="official gazette",
        kind=AuthoritySourceKind.WEBHOOK,
        root_ref="https://gazette.test/webhooks",
        config=ConnectorConfiguration(
            secret_references={
                "webhook_signing_secret": SecretReference(
                    provider=SecretReferenceProvider.VAULT,
                    reference="kv/gazette/webhook-signing-secret",
                )
            }
        ),
    )


def test_authenticated_authority_webhook_returns_only_a_change_event():
    body = json.dumps(
        {
            "idempotency_key": "regulation-r-12:v3",
            "authority_id": "regulation-r-12",
            "previous_version": "v2",
            "new_version": "v3",
            "changed_at": "2026-07-13T00:00:00Z",
            "evidence_url": "https://gazette.test/regulation-r-12/v3",
            "diff": {"sections_changed": ["12"]},
        }
    ).encode()
    secret = "webhook-secret"  # noqa: S105
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    intake = AuthorityWebhookIntake(lambda reference: secret if reference.reference.endswith("signing-secret") else "")

    event = intake.parse(_source(), body, signature)

    assert event.source_id == "official-gazette"
    assert event.new_version == "v3"
    assert event.diff == {"sections_changed": ["12"]}


def test_authority_webhook_rejects_missing_secret_bad_signature_and_invalid_payload():
    body = b"{}"
    intake = AuthorityWebhookIntake(lambda _reference: "webhook-secret")

    with pytest.raises(AuthorityWebhookVerificationError, match="signature"):
        intake.parse(_source(), body, "sha256=wrong")
    with pytest.raises(AuthorityWebhookVerificationError, match="payload"):
        signature = "sha256=" + hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
        intake.parse(_source(), body, signature)
    with pytest.raises(AuthorityWebhookVerificationError, match="signing-secret"):
        intake.parse(
            AuthoritySource(id="missing", name="missing", kind=AuthoritySourceKind.WEBHOOK, root_ref="https://test"),
            body,
            "sha256=wrong",
        )
