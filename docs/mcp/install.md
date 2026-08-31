<!-- SPDX-License-Identifier: Apache-2.0 -->

# MCP installation

Solomon supports the MCP stdio process contract and optional HTTP/SSE transports. Host applications vary in how they register a server, so this guide documents Solomon's supported configuration and smoke test rather than claiming compatibility with a particular desktop application.

## Stdio

From the repository root:

```bash
uv sync --extra dev
uv run solomon mcp serve --help
```

Use [`examples/mcp/mcp.json`](https://github.com/gongahkia/solomon/blob/main/examples/mcp/mcp.json) as a template and replace `/absolute/path/to/solomon`.

```bash
uv --directory /absolute/path/to/solomon run python -m solomon.mcp.server
```

The server writes protocol traffic to stdout. Hosts should keep human logs on stderr. The generic tool/schema smoke tests are `tests/test_mcp_runtime.py`, `tests/test_mcp_schemas.py`, and `tests/test_mcp_authorization.py`; the Currency Loop Proof adds a restricted-scope MCP impact check.

## Identity and scope

Stdio has no HTTP bearer exchange. For a trusted local launch identity, configure:

```bash
export SOLOMON_MCP_PRINCIPAL_JSON='{"subject":"lawyer-a","role":"lawyer","scopes":["solomon.read"],"matter_ids":["matter-a"],"client_ids":["client-a"]}'
export SOLOMON_MCP_REQUIRE_IDENTITY=true
```

`solomon.read`, `solomon.write`, and `solomon.audit` are separate MCP scopes; `solomon.admin` grants all three. A restricted principal must supply a permitted matter and client scope. Caller-supplied identity is ignored when a principal is bound.

Useful storage variables are `SOLOMON_DATA_DIR`, `SOLOMON_JOURNAL_DIR`, and `SOLOMON_DATABASE_URL`. The bound identity configuration is local process trust configuration; an embedding host must validate bearer tokens before supplying a principal to the HTTP/SSE app.

## HTTP and SSE

Start a local HTTP or SSE endpoint:

```bash
SOLOMON_MCP_TOKEN=change-me uv run solomon mcp serve --http --host 127.0.0.1 --port 8141
SOLOMON_MCP_TOKEN=change-me uv run solomon mcp serve --sse --host 127.0.0.1 --port 8141
```

Connect a compatible client to `/mcp` or `/sse` with `Authorization: Bearer <SOLOMON_MCP_TOKEN>`. For deployed identity, use the bearer-to-principal resolver rather than trusting caller-provided claims.

## Protocol smoke prompt

Seed one item and invoke a read tool through the configured host:

```bash
uv run solomon ingest "Structure X relies on Regulation R section 12." --source-ref memo-1 --kind position --source-kind partner
```

```text
Use solomon.preflight_context with query "structure x regulation", matter_id "matter-a", client_id "client-a", and max_items 1. Return the item ID and currency state.
```

Expected behavior: the host calls `solomon.preflight_context` and gets a live item. A host-specific failure should be recorded as a reproducible protocol/configuration defect only if the same process contract and tool schema work in the bundled smoke tests but fail in that host.
