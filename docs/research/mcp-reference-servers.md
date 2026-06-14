# MCP reference server survey

Checked: 2026-06-14

Scope: filesystem, GitHub, Linear, Notion, Postgres. Focus: auth, error/scoping pattern, tool granularity, Solomon implications.

## Summary table

| Server | Auth pattern | Scoping pattern | Tool granularity | Error / safety shape |
|---|---|---|---|---|
| Filesystem reference | local stdio; no app auth; trust boundary is launch config | allowed directories from CLI args or MCP Roots; server refuses operation with no allowed dir | fine-grained file tools: read, write, edit, list, tree, metadata, move, search | path access restricted to allowed dirs; failed multi-file reads do not abort whole operation; tool annotations mark read-only/destructive/idempotent hints |
| GitHub official | remote hosted OAuth; local Docker/binary with PAT env var | repo/user permission from token plus `--toolsets`, `GITHUB_TOOLSETS`, `--tools`, read-only mode | many tools grouped by domain: repos, issues, PRs, actions, code security, users | invalid tool names fail startup; read-only mode skips write tools even if requested |
| Linear official | hosted remote MCP using Streamable HTTP and OAuth 2.1 dynamic client registration; API-key fallback in some clients | Linear account/workspace permissions; centrally hosted server | object-oriented tools for finding, creating, updating issues, projects, comments | client auth flow is part of setup; docs do not publish a domain error taxonomy |
| Notion official | hosted remote MCP via OAuth; legacy local package discouraged | workspace/user access and Notion plan limits; Streamable HTTP preferred, SSE legacy, stdio via `mcp-remote` bridge | content/workspace tools: search, fetch, create/update/move pages, databases, views, comments, users | rate-limit behavior is documented; some tools have stricter limits than global API limit |
| Postgres MCP Pro | local Docker/Python; DB connection string/credentials | DB credentials plus access mode; read-only mode available; supports stdio and SSE | database-health, index, explain-plan, schema-intelligence, safe-SQL tools | safe SQL execution and configurable read/write access; project emphasizes query validation and production tuning |

## Patterns worth copying

1. Scope is enforced outside natural language.

Filesystem uses allowed directories and Roots. GitHub uses token permissions, toolsets, individual tool allow-lists, and read-only mode. Linear and Notion rely on OAuth-connected account/workspace permissions. Postgres scopes to explicit DB credentials and access mode.

[Inference] Solomon MCP should treat `matter_id`, `client_id`, caller identity, tool allow-list, and auth token as enforcement inputs, not prompt text. Tool descriptions can help model behavior, but they are not policy.

2. Tools should be narrow, named, and capability-filtered.

GitHub's toolsets and individual-tool flags are the strongest pattern for a large surface. Filesystem exposes separate read/write/search/edit tools and marks destructive hints. Notion exposes many action-specific tools and documents plan/rate-limit constraints.

[Inference] Solomon should avoid a generic `search_firm_knowledge` tool. It should expose explicit operations: `preflight_context`, `check_currency`, `impact`, `get_dependencies`, `verify_position`, `ingest`, `audit_pack`, and `dependency_suggestions`.

3. Read/write split matters.

Filesystem annotates read-only versus destructive tools. GitHub read-only mode suppresses writes. Postgres access mode changes what the agent may execute.

[Inference] Solomon should make read/write polarity visible in schemas and logs. Read tools return scoped content only after boundary review. Write tools require actor/evidence inputs and append audit entries.

4. Domain errors should be structured, not only protocol errors.

Public docs rarely expose a full domain error taxonomy. The visible pattern is still useful: GitHub fails startup for invalid tool config, Notion documents rate-limit failures, Filesystem handles partial read failures without aborting everything.

[Inference] Solomon should define explicit domain error codes because legal workflows need auditable failures: `boundary_rejected`, `currency_unknown`, `scope_denied`, `model_routing_failure`, and `verification_required`.

## Per-server notes

### Filesystem reference

Best pattern: runtime scoping is explicit and local. The server can get allowed directories from command args or MCP Roots. It requires at least one allowed directory, lists allowed directories as a tool, and annotates read-only/destructive/idempotent hints. Multi-file read behavior allows partial failure reporting.

Solomon translation: add a `solomon.health` tool and expose scope metadata in every result. Use annotations where the SDK supports them.

### GitHub official

Best pattern: large server surface is reduced through toolsets, individual tool names, and read-only mode. Local mode uses `GITHUB_PERSONAL_ACCESS_TOKEN`. Remote mode is hosted by GitHub and uses OAuth in capable hosts.

Solomon translation: ship a minimal default toolset and document how to disable write tools in client config. Keep `verify_position` and `ingest` separately allow-listable.

### Linear official

Best pattern: hosted remote MCP with OAuth 2.1 dynamic client registration. Linear also documents client-specific registration commands for Claude Code, Codex, Cursor, VS Code, and others.

Solomon translation: v0.2 can stay bearer-token only, but install docs should be client-specific and explicit about stdio vs remote HTTP.

### Notion official

Best pattern: remote server first, OAuth setup, documented tool names, tool prerequisites, and rate limits. Notion explicitly calls Streamable HTTP recommended and SSE legacy, with stdio bridged by `mcp-remote`.

Solomon translation: prefer Streamable HTTP terminology over "HTTP/SSE" in future docs, while still supporting legacy SSE only if needed for compatibility.

### Postgres MCP Pro

Best pattern: DB servers need explicit safe-SQL policy, read-only/read-write mode, health/schema tools, and transport choice. The server treats database access as potentially production-impacting, not a generic retrieval surface.

Solomon translation: any MCP path touching firm content should default to read-only, scoped, and audit-logged. Write paths should be deliberately few.

## Sources

- MCP reference server repository: <https://github.com/modelcontextprotocol/servers>
- Filesystem reference server: <https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem>
- GitHub MCP server: <https://github.com/github/github-mcp-server>
- GitHub MCP server docs: <https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp-in-your-ide/use-the-github-mcp-server>
- Linear MCP docs: <https://linear.app/docs/mcp>
- Notion MCP overview: <https://developers.notion.com/guides/mcp/overview>
- Notion MCP setup: <https://developers.notion.com/guides/mcp/get-started-with-mcp>
- Notion MCP tools: <https://developers.notion.com/guides/mcp/mcp-supported-tools>
- Postgres MCP Pro: <https://github.com/crystaldba/postgres-mcp>
