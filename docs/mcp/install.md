# MCP install

Research date: 2026-06-14

Access caveat: Claude Code CLI was verified locally. Claude Desktop was not installed in this environment.

## Prereqs

From repo root:

```bash
uv sync --extra dev
uv run solomon mcp serve --help
```

Seed data before trying client prompts:

```bash
uv run solomon ingest "Structure X relies on Regulation R section 12." --source-ref memo-1 --kind position --source-kind partner
```

## Stdio config

Use [`examples/mcp/mcp.json`](../../examples/mcp/mcp.json) as the shared stdio config.

Replace `/absolute/path/to/solomon` with this repo path. The server command is:

```bash
uv --directory /absolute/path/to/solomon run python -m solomon.mcp.server
```

Stdio has no HTTP bearer exchange; bind a trusted launch identity when authorization is required. It reads these env
vars:

- `SOLOMON_DATA_DIR`
- `SOLOMON_JOURNAL_DIR`
- `SOLOMON_DATABASE_URL`
- `SOLOMON_MCP_PRINCIPAL_JSON` — trusted principal JSON with `subject`, `role`, `scopes`, `matter_ids`, and `client_ids`.
- `SOLOMON_MCP_REQUIRE_IDENTITY=true` — refuse unbound calls.

For HTTP/SSE, combine `SOLOMON_MCP_TOKEN` with the same principal JSON. `solomon.read`, `solomon.write`, and
`solomon.audit` are distinct tool scopes; `solomon.admin` grants all three. A scoped principal must explicitly provide
its permitted matter/client scope. `audit_pack` and firm/practice-area currency reports require unrestricted scope
because their current export formats are global. Caller-supplied `caller_id` is ignored when an identity is bound.

```bash
export SOLOMON_MCP_PRINCIPAL_JSON='{"subject":"lawyer-a","role":"lawyer","scopes":["solomon.read"],"matter_ids":["matter-a"],"client_ids":["client-a"]}'
export SOLOMON_MCP_REQUIRE_IDENTITY=true
```

Embedding hosts can supply a validated bearer-to-principal resolver to the HTTP/SSE app factory; the MCP layer does
not parse unvalidated token claims.

## Claude Code

Verified local CLI: `claude` 2.1.119.

One-shot config:

```bash
claude -p --strict-mcp-config --mcp-config examples/mcp/mcp.json "List the Solomon MCP tools."
```

Project registration:

```bash
claude mcp add --scope project solomon -- uv --directory "$PWD" run python -m solomon.mcp.server
claude mcp list
claude mcp get solomon
```

Use env flags when registering against non-default storage:

```bash
claude mcp add --scope project \
  -e SOLOMON_DATA_DIR="$PWD/solomon-data" \
  -e SOLOMON_JOURNAL_DIR="$PWD/solomon-journal" \
  -e SOLOMON_DATABASE_URL="sqlite:///$PWD/solomon-data/solomon.sqlite3" \
  solomon -- uv --directory "$PWD" run python -m solomon.mcp.server
```

Source: local `claude mcp --help`.

## Claude Desktop

[Unverified] No local Claude Desktop app was installed here.

Use the app's Developer settings to edit the MCP config. On macOS, common docs place the file at:

```text
~/Library/Application Support/Claude/claude_desktop_config.json
```

Add the contents of `examples/mcp/mcp.json`, after replacing paths, then restart Claude Desktop.

Source for common path and JSON shape: https://www.files.com/docs/integrations/ai/model-context-protocol-mcp-server/quickstart-for-claude-desktop

## Cursor

Cursor's MCP docs cover connecting external tools/data through MCP: https://cursor.com/docs/mcp

Use either:

- Cursor Settings -> MCP -> add server.
- Project file: `.cursor/mcp.json`.

For project file use:

```bash
mkdir -p .cursor
cp examples/mcp/mcp.json .cursor/mcp.json
```

Then edit absolute paths and restart/reload Cursor.

## Continue

Continue requires agent mode for MCP tool use. It accepts JSON MCP files copied from Claude/Cursor into `.continue/mcpServers/`.

```bash
mkdir -p .continue/mcpServers
cp examples/mcp/mcp.json .continue/mcpServers/mcp.json
```

Alternative YAML block:

```yaml
name: Solomon mcpServer
version: 0.0.1
schema: v1
mcpServers:
  - name: Solomon
    type: stdio
    command: uv
    args:
      - --directory
      - /absolute/path/to/solomon
      - run
      - python
      - -m
      - solomon.mcp.server
```

Sources:

- https://docs.continue.dev/customize/mcp-tools
- https://docs.continue.dev/customize/deep-dives/mcp

## HTTP/SSE

Start HTTP:

```bash
SOLOMON_MCP_TOKEN=change-me uv run solomon mcp serve --http --host 127.0.0.1 --port 8141
```

Start SSE:

```bash
SOLOMON_MCP_TOKEN=change-me uv run solomon mcp serve --sse --host 127.0.0.1 --port 8141
```

Claude Code HTTP registration:

```bash
claude mcp add --transport http \
  --header "Authorization: Bearer change-me" \
  solomon http://127.0.0.1:8141/mcp
```

Claude Code SSE registration:

```bash
claude mcp add --transport sse \
  --header "Authorization: Bearer change-me" \
  solomon http://127.0.0.1:8141/sse
```

Source: local `claude mcp --help`.

## Smoke prompt

After seeding data:

```text
Use the Solomon MCP preflight_context tool with query "structure x regulation", matter_id "matter-a", client_id "client-a", and max_items 1. Return the item id and currency state.
```

Expected result: the client should call `solomon.preflight_context` and return one live Solomon item.
