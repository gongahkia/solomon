# MCP directory submission

Research date: 2026-06-14

Access caveat: no access to the private submission portal UI. This note uses public docs and public review artifacts only.

## Listing copy

**MCP-native currency infrastructure for verified legal knowledge.**

Use this exact description in MCP Registry or directory metadata until a separate product-description decision is
made.

## Scope

Anthropic's public docs now distinguish three related but separate distribution paths:

1. Anthropic Connectors Directory: curated Claude directory listing for remote MCP servers, MCP Apps, and MCPB desktop extensions.
2. Official MCP Registry: ecosystem metadata registry at `registry.modelcontextprotocol.io`; downstream marketplaces can consume it.
3. MCPB: bundled local MCP server format for Claude Desktop and other desktop hosts.

For Solomon, the directory-ready path is remote MCP over HTTPS, plus an MCPB package later if local desktop install matters. A standalone `solomon-mcp.json` should be treated as an MCP Registry `server.json` draft unless the target is MCPB, where the required file name is `manifest.json`.

## Anthropic Connectors Directory

### Submission paths

- Remote MCP servers and MCP Apps: submit through Claude.ai admin settings submission portal.
- Access requires a Team or Enterprise org and directory-management permissions.
- If the portal is inaccessible, Anthropic also documents an MCP directory submission form.
- Desktop extensions use a separate MCPB submission form.
- The remote portal accepts remote MCP servers only; local servers are distributed as MCPB desktop extensions or plugins.

Source: https://claude.com/docs/connectors/building/submission

### Required submission material

Before portal submission, prepare:

- HTTPS MCP server URL.
- Transport: streamable HTTP or SSE.
- Documentation URL.
- Privacy policy URL.
- Icon.
- Support contact.
- Test account credentials and step-by-step reviewer access instructions.
- For MCP Apps: 3-5 PNG screenshots, at least 1000px wide, cropped to the app response; prompt text is submitted separately.

The portal flow covers: introduction, connection, tool sync, listing, use cases, company, authentication, data handling, test and launch, compliance, review.

### Review criteria

Reviewers functionally test every tool and run a policy compliance scan. Main rejection causes:

- Mixed read/write catch-all tools. Split read-only and write actions.
- Missing tool annotations. Every tool needs `title` and either `readOnlyHint: true` or `destructiveHint: true`.
- Tool names over 64 chars.
- Vague or inaccurate tool descriptions.
- Prompt-injection language in descriptions, including hidden or encoded instructions.
- Generic failures instead of actionable errors.
- Oversized responses relative to the requested task.
- Collection of conversation data beyond tool function.
- Queries against Claude memory, chat history, summaries, or user files.
- APIs the submitter does not own or legitimately proxy.
- Unsupported flows: asset transfer and AI image/video/audio generation.
- Missing test credentials or incomplete docs.

Source: https://claude.com/docs/connectors/building/review-criteria

### Authentication and privacy

- Authenticated services should use OAuth 2.0 unless using a documented custom/no-auth flow.
- Local connectors need a README privacy section and `privacy_policies` in `manifest.json` for manifest version 0.2+.
- Privacy policy must cover collection, use/storage, sharing, retention, and contact info.
- Missing or incomplete privacy policies are immediate rejection.
- If using `ui/open-link`, declare owned HTTPS origins or custom URI schemes to avoid per-link confirmation prompts.

Source: https://claude.com/docs/connectors/building/submission

## MCP Registry `server.json`

The MCP Registry is not the same as Anthropic's curated directory. It is the official public metadata registry for publicly accessible MCP servers and is currently preview-stage. It hosts metadata, not artifacts.

Source: https://modelcontextprotocol.io/registry/about

### Publish flow

1. Publish the package or expose the remote server.
2. Install `mcp-publisher`.
3. Run `mcp-publisher init`.
4. Edit `server.json`.
5. Authenticate, for example with GitHub.
6. Run `mcp-publisher publish`.

Source: https://modelcontextprotocol.io/registry/quickstart

### Schema essentials

Required top-level fields:

- `name`: reverse-DNS format with one slash, e.g. `io.github.user/weather`.
- `description`: 1-100 chars.
- `version`.

Common top-level fields:

- `$schema`.
- `title`.
- `repository`.
- `websiteUrl`.
- `icons`.
- `packages`.
- `remotes`.
- `_meta`.

Package entries require:

- `registryType`.
- `identifier`.
- `transport`.

Transport values include:

- Local/package: `stdio`, `streamable-http`, `sse`.
- Remote: `streamable-http` or `sse` with URL template.

Source: https://raw.githubusercontent.com/modelcontextprotocol/registry/main/docs/reference/server-json/draft/server.schema.json

### Registry moderation

The official registry is permissive. It removes illegal content, malware, spam, and non-functioning servers. It does not generally remove low-quality servers, vulnerable servers, duplicate functionality, or adult content. Downstream marketplaces are expected to apply stricter curation.

Source: https://modelcontextprotocol.io/registry/moderation-policy

## MCPB `manifest.json`

MCPB is a zip archive containing a local MCP server and `manifest.json`. Claude Desktop now recommends `.mcpb` for new desktop extensions.

Sources:

- https://www.anthropic.com/engineering/desktop-extensions
- https://github.com/modelcontextprotocol/mcpb

### Required manifest fields

- `manifest_version`.
- `name`.
- `version`.
- `description`.
- `author.name`.
- `server`.

### Relevant optional fields

- `display_name`.
- `long_description`.
- `repository`.
- `homepage`.
- `documentation`.
- `support`.
- `icon` / `icons`.
- `screenshots`.
- `tools`.
- `tools_generated`.
- `keywords`.
- `license`.
- `privacy_policies`.
- `compatibility`.
- `user_config`.
- `_meta`.

Source: https://raw.githubusercontent.com/modelcontextprotocol/mcpb/main/MANIFEST.md

### Solomon implication

For a local Claude Desktop listing, Solomon needs:

- MCPB `manifest.json`, not `solomon-mcp.json`.
- `server.type = "uv"` if relying on `pyproject.toml` and host-managed Python dependencies.
- `user_config` for data dir, journal dir, database URL, and bearer token if needed.
- `privacy_policies` because Solomon can process user legal data and may call external services depending on deployment.

## Observed reviewer feedback

In a public Anthropic MCP Directory review issue, requested fixes included:

- Add `privacy_policies` entries when tools call external hosts or return telemetry.
- Declare required env vars in `user_config` with title, description, required, and sensitive flags.
- Reference user config values from `server.mcp_config.env`.
- Disclose invocation telemetry in privacy docs.
- Fill manifest `license` when the repo has a license.

Source: https://github.com/dns-aid/dns-aid-core/issues/83

## Solomon readiness checklist

- Remote HTTPS deployment with streamable HTTP or SSE.
- OAuth 2.0 story, or explicit no-auth/custom-auth rationale.
- Tool annotations include `title`, `readOnlyHint`, and `destructiveHint` as appropriate.
- Read/write tools are split. Current split is mostly OK: `verify_position` and `ingest` are write tools.
- Tool names are <=64 chars.
- Tool descriptions only describe function. No behavioral instructions.
- Every tool smoke-tested in MCP Inspector and Claude custom connector.
- Documentation URL and privacy policy URL published.
- Support contact and icon ready.
- Test account/fixture with populated Solomon data ready.
- No external-link capability unless owned allowed link URIs are declared.
- If packaging local: MCPB manifest with `privacy_policies`, `user_config`, `license`, and `server.type = "uv"`.
