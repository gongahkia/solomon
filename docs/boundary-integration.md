<!-- SPDX-License-Identifier: Apache-2.0 -->

# Boundary Integration

Solomon owns the local boundary surfaces it calls. No sibling repository or external boundary service is
required for the local SKU.

Boundary source:

```text
src/solomon/boundary/engine/
```

Solomon includes these local surfaces:

- `/review` before storing sensitive knowledge.
- `/pseudonymize` before model egress, with `persist_mapping=false`.
- `/anonymize` for irreversible placeholder-only rewrites with no mapping.
- `/redact` for opaque markers that do not expose entity type or original text.
- `/reidentify` after model response, using volatile in-process mappings.
- `/documents/scrub` before file extraction.
- `capabilities()` for the local boundary manifest.

Run a local smoke test:

```bash
uv run python scripts/boundary_smoke.py
```

Run the committed boundary-confidence fixture suite:

```bash
uv run pytest tests/test_boundary_accuracy.py
```

The fixture suite exercises representative PII, client-reference, MNPI, privacy-marker, pseudonymization,
anonymization, redaction, and reidentification behavior. It is regression evidence, not a claim of complete
DLP or legal coverage.

If the boundary engine is unavailable or errors, Solomon refuses ingestion or egress paths that require it.
