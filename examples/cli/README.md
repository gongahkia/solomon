<!-- SPDX-License-Identifier: Apache-2.0 -->

# CLI examples

Minimal local flow:

```bash
uv run solomon ingest "Structure X relies on Regulation R section 12." --source-ref memo-1 --kind position --source-kind partner
uv run solomon preflight "structure X regulation"
uv run solomon dependency-suggestions
uv run solomon impact regulation-r-section-12
```

Use `uv run solomon --help` for command-specific examples.
