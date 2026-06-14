<!-- SPDX-License-Identifier: Apache-2.0 -->

# Contributing

Solomon is legal infrastructure, so changes should be conservative, auditable, and backed by tests.

## Ground Rules

- Keep boundary logic fail-closed: if Solomon cannot review or pseudonymize, Solomon must not store unsafe
  material or send model context out.
- Never delete knowledge records to express currency. Supersede, retire, quarantine, or append events.
- Add or update tests for any changed invariant, route, storage behavior, or audit record.

## Local Checks

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy src tests scripts
uv run pytest
```

## Commit Shape

Prefer focused commits tied to a TODO item or a coherent implementation slice. Each commit should leave
the repo in a runnable state.
