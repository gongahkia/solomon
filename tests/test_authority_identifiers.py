# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from solomon.authority_identifiers import SQLiteAuthorityIdentifierStore, normalize_authority_identifier
from solomon.contracts import AuthoritySource, AuthoritySourceKind


def test_authority_identifiers_are_idempotent_within_a_source_without_cross_source_conflation(tmp_path):
    store = SQLiteAuthorityIdentifierStore(tmp_path / "authorities.sqlite3")
    first_source = AuthoritySource(
        id="official-gazette", name="official", kind=AuthoritySourceKind.API, root_ref="https://gov.test"
    )
    second_source = AuthoritySource(
        id="publisher-copy", name="publisher", kind=AuthoritySourceKind.API, root_ref="https://publisher.test"
    )

    first = store.resolve(first_source, "HTTPS://EXAMPLE.TEST:443/regulations/12#section")
    repeated = store.resolve(first_source, "https://example.test/regulations/12")
    distinct = store.resolve(second_source, "https://example.test/regulations/12")

    assert first == repeated
    assert first.canonical_id != distinct.canonical_id
    assert first.normalized_identifier == "https://example.test/regulations/12"
    store.close()


def test_authority_identifier_normalization_rejects_empty_and_malformed_urls():
    with pytest.raises(ValueError, match="required"):
        normalize_authority_identifier("  ")
    with pytest.raises(ValueError, match="scheme and host"):
        normalize_authority_identifier("https://")
    assert normalize_authority_identifier("Regulation R section 12") == "Regulation R section 12"
