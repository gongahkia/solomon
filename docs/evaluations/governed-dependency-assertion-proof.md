<!-- SPDX-License-Identifier: Apache-2.0 -->

# Governed dependency assertion proof record

This record describes the repository-local evidence for the governed dependency assertion implementation. It is not a
claim that synthetic assertions are legally, factually, or semantically correct; it records the behavior exercised by
the tests and deterministic scenario.

## Deterministic scenario

`examples/scenarios/governed-dependency-assertion-proof/run.py` is a headless, model-free proof using fictional
Alpha and Bravo scopes. Its snapshot fixture locks the following observed invariants:

- one human quote assertion, one human commentary assertion, and one trusted-upstream assertion;
- no graph edge on creation; one provenance-linked edge after concurrent/retried confirmation; no edge for rejected,
  deferred, or withdrawn assertions;
- malformed quote offsets, a free-text target, a nonexistent target, a cross-scope target, and creator
  self-confirmation denied;
- denied cross-scope list/get/decision/withdraw operations;
- source revision preserves raw evidence and the historical confirmed edge while requesting re-verification;
- only the confirmed edge affects currency after the fictional authority change; and
- creation, review, edge-linkage, and re-verification audit IDs plus audit-pack verification.

Run it with:

```bash
uv run python examples/scenarios/governed-dependency-assertion-proof/run.py --workspace /tmp/solomon-governed-dependency-assertion-proof
```

The test `[test_governed_dependency_assertion_demo.py](../../tests/test_governed_dependency_assertion_demo.py)` compares
the scenario snapshot byte-for-value after parsing JSON, while allowing only the measured latency field to vary within
the scenario's 2-second local budget.

## Local verification record

The following checks passed on the implementation working tree:

```text
uv run pytest -q tests/test_evidence_to_dependency_proof.py \
  tests/test_adversarial_dependency_corpus.py tests/test_adversarial_dependency_evaluation.py \
  tests/test_adversarial_dependency_properties.py tests/test_reliance_semantics_corpus.py \
  tests/test_governed_dependency_assertion_demo.py tests/test_governed_dependency_assertions.py
# 61 passed

SOLOMON_TEST_POSTGRES_DSN=postgresql://solomon:…@127.0.0.1:55432/solomon \
  uv run pytest -q tests/test_migrations.py tests/test_postgres_live_integration.py
# 6 passed (disposable local pgvector/PostgreSQL 16)

uv run ruff check .
uv run mypy src/solomon
uv run python scripts/check_license_headers.py
uv run python scripts/check_file_lengths.py
uv run bandit -r src/solomon --baseline .bandit-baseline.json
uv run pip-audit --skip-editable
uv run mkdocs build --strict
uv build
```

The final full coverage command used a writable temporary directory because this host's `/tmp` quota caused Helm to
render an empty temporary file and prevented Compose from writing generated test secrets. With `TMPDIR` set to a
disposable directory under `/home`, it passed completely:

```text
TMPDIR=/home/.../solomon-validation uv run pytest --cov=src/solomon
# 462 passed, 3 skipped; total coverage 90.04%
```

The three skips are the configured live-local-model, live-remote-ZDR, and live-PostgreSQL integration tests when
their external endpoint environment variables are absent. The dedicated disposable pgvector/PostgreSQL run above
provides the available real-database migration evidence. The `/tmp` behavior is a host resource constraint, not a
repository failure under a writable temporary directory.

## Boundaries retained

The parser source and its locked corpora remain regression gates; governed assertions do not call parser or model
code. Source documents remain in the SQLite document store when graph/knowledge persistence is PostgreSQL. The
implementation validates source-version binding and uses durable idempotency/event ordering, but does not claim a
cross-store atomic transaction. MCP remains scoped and read-only for governed assertion provenance.
