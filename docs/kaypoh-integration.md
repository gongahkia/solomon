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

Solomon uses:

- `/review` before storing sensitive knowledge.
- `/pseudonymize` before model egress, with `persist_mapping=false`.
- `/reidentify` after model response, using volatile in-process mappings.
- `/documents/scrub` before file extraction.

Run a local smoke test:

```bash
uv run python scripts/kaypoh_smoke.py
```

If the vendored boundary engine is unavailable or errors, Solomon refuses ingestion or egress paths that require
the boundary.

## Optional Office Surfaces

Solomon can reuse Kaypoh's existing Word and Office taskpanes as thin clients without editing Kaypoh source.
The Solomon-side adapter contract is documented in [office-frontends.md](office-frontends.md).
