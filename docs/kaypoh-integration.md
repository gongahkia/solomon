<!-- SPDX-License-Identifier: Apache-2.0 -->

# Kaypoh Integration

Solomon vendors the Kaypoh-derived local boundary surfaces it calls and does not require a sibling Kaypoh
checkout at runtime.

Vendored source:

```text
src/solomon/boundary/engine/
```

The vendored source is pinned in `src/solomon/boundary/engine/NOTICE` to Kaypoh commit
`7415069e57d69398e2c44ef6ababafb0c04a988b`.

Solomon vendors the Kaypoh-compatible surfaces needed for local operation:

- `/review` before storing sensitive knowledge.
- `/pseudonymize` before model egress, with `persist_mapping=false`.
- `/anonymize` for irreversible placeholder-only rewrites with no mapping.
- `/redact` for opaque markers that do not expose entity type or original text.
- `/reidentify` after model response, using volatile in-process mappings.
- `/documents/scrub` before file extraction.
- `capabilities()` for the local parity manifest.

The vendored engine carries the same jurisdiction coverage list exposed by Kaypoh's schema docs:
`AE`, `AU`, `CN`, `EU`, `HK`, `ID`, `IN`, `JP`, `KR`, `MY`, `PH`, `SA`, `SEA`, `SG`, `TH`, `UK`, `US`,
and `VN`. It also includes deterministic universal PII, special-category PII, privacy-handling event,
financial-scalar, and MNPI lexicon detectors. Solomon still treats the boundary as a gate and evidence source,
not as legal advice or a complete DLP replacement.

Run a local smoke test:

```bash
uv run python scripts/kaypoh_smoke.py
```

Run the committed boundary-confidence fixture suite:

```bash
uv run pytest tests/test_boundary_accuracy.py
```

The fixture suite exercises representative PII, client-reference, MNPI, privacy-marker, pseudonymization,
anonymization, redaction, and reidentification behavior. It is regression evidence for Solomon's vendored
boundary, not a claim of complete DLP or legal coverage.

If the vendored boundary engine is unavailable or errors, Solomon refuses ingestion or egress paths that require
the boundary.

## Optional Office Surfaces

Solomon can reuse Kaypoh's existing Word and Office taskpanes as thin clients without editing Kaypoh source.
The Solomon-side adapter contract is documented in [office-frontends.md](office-frontends.md).
