<!-- SPDX-License-Identifier: Apache-2.0 -->

# Kaypoh Integration

Solomon reuses Kaypoh as the boundary layer and does not modify Kaypoh source.

Expected layout:

```text
projects/
  kaypoh/
  solomon/
```

Solomon uses:

- `/review` before storing sensitive knowledge.
- `/pseudonymize` before model egress, with `persist_mapping=false`.
- `/reidentify` after model response, using volatile in-process mappings.
- `/documents/scrub` before file extraction.

Run a local smoke test:

```bash
uv run python scripts/kaypoh_smoke.py --base-url http://127.0.0.1:8131
```

If Kaypoh is unavailable, Solomon refuses ingestion or egress paths that require the boundary.

