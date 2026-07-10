# ADR 0001: Service Decomposition

Status: Accepted

## Context

`SolomonService`, the Postgres backend, and the MCP tool runtime had grown into broad coordination files. They mixed request models, orchestration, storage DDL, event persistence, tool registration, and per-tool behavior in single modules.

## Decision

Keep public import paths stable while splitting implementation by responsibility:

- `solomon.api.service` remains the façade for API, CLI, MCP, and tests.
- `solomon.api.service_models` owns request/response models.
- `solomon.api.services.*` owns ingestion, recall/primitive plans, answer/model calls, and authority/dependency workflows.
- `solomon.store.postgres.*` separates connection/schema helpers, DDL, serialization, knowledge storage, graph storage, and retrieval index behavior.
- `solomon.mcp.tools.*` separates tool specs, registration, runtime delegation, shared helpers, and handler groups.

## Consequences

The public service and MCP entrypoints remain unchanged, while later feature work lands in smaller modules with narrower ownership. CI now runs `scripts/check_file_lengths.py`, failing new `src/solomon` files over 500 lines unless an explicit allowlist entry explains why the exception is intentional.
