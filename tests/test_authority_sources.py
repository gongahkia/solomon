# SPDX-License-Identifier: Apache-2.0

import pytest
from pydantic import ValidationError

from solomon.authority_sources import AuthoritySourceNotFoundError, SQLiteAuthoritySourceRegistry
from solomon.connectors import ConnectorConfiguration, SecretReference, SecretReferenceProvider
from solomon.contracts import AuthorityPollSchedule, AuthoritySource, AuthoritySourceKind


def test_authority_source_registry_persists_validated_configuration_idempotently(tmp_path):
    registry = SQLiteAuthoritySourceRegistry(tmp_path / "authorities.sqlite3")
    source = AuthoritySource(
        id="official-gazette",
        name="official gazette",
        kind=AuthoritySourceKind.API,
        root_ref="https://gazette.test/api",
        canonical_namespace="sg_gazette",
        poll_schedule=AuthorityPollSchedule(interval_seconds=300, jitter_seconds=30),
        config=ConnectorConfiguration(
            settings={"jurisdiction": "SG"},
            secret_references={
                "api_token": SecretReference(provider=SecretReferenceProvider.VAULT, reference="kv/gazette/token")
            },
        ),
    )

    first = registry.register(source)
    repeated = registry.register(source)

    assert first == repeated
    assert registry.get(source.id) == source
    assert registry.list(enabled=True) == [source]
    with pytest.raises(AuthoritySourceNotFoundError):
        registry.get("missing")
    registry.close()


def test_authority_source_rejects_invalid_schedule_and_namespace():
    with pytest.raises(ValidationError, match="jitter_seconds"):
        AuthorityPollSchedule(interval_seconds=60, jitter_seconds=60)
    with pytest.raises(ValidationError):
        AuthoritySource(
            id="source-1",
            name="source",
            kind=AuthoritySourceKind.API,
            root_ref="https://example.test",
            canonical_namespace="Invalid Namespace",
        )
