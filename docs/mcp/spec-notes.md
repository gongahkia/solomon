# MCP spec notes

Checked: 2026-06-14  
Spec version: `2025-06-18`  
Primary source: <https://modelcontextprotocol.io/specification/2025-06-18>

## Required baseline

MCP is a JSON-RPC 2.0 protocol for host applications, clients, and servers. The required implementation baseline for Solomon is:

- implement the connection lifecycle: `initialize` request, capability negotiation, server info response, then `notifications/initialized`;
- expose only declared capabilities;
- emit no stdout content except valid MCP messages when using stdio;
- support UTF-8 JSON-RPC messages;
- implement tool discovery and tool invocation if declaring the `tools` capability;
- return standard JSON-RPC errors for protocol failures and structured tool results for domain failures;
- handle shutdown without leaving partial writes or corrupted audit entries.

The current standard transports are `stdio` and Streamable HTTP. The spec says clients should support stdio when possible. Streamable HTTP replaces the older HTTP+SSE transport from the 2024-11-05 protocol version, but may still use SSE inside the Streamable HTTP flow for server-to-client messages.

## Capability matrix

| Capability | Side | Required by spec? | Solomon v0.2 decision |
|---|---|---:|---|
| Tools | Server | Optional, but must be declared if supported | Required for v0.2 |
| Resources | Server | Optional | Defer; use tools for scoped firm context |
| Prompts | Server | Optional | Defer; no drafting/chat surface |
| Sampling | Client | Optional | Do not require; Solomon should not ask the host model to complete work |
| Roots | Client | Optional | Do not require; legal knowledge scope comes from `matter_id`/`client_id`, not filesystem roots |
| Elicitation | Client | Optional; new in `2025-06-18` | Defer; no sensitive-info prompts from server |
| Logging | Server utility | Optional | Use internally, but do not depend on client log display |
| Authorization | Transport-level | Optional overall | stdio: env token; HTTP: bearer token for portfolio scope |

## Tools

Tools are the primary fit for Solomon. They are model-controlled functions with names, descriptions, input schemas, and structured results. The client discovers them through `tools/list` and invokes them through `tools/call`.

[Inference] Solomon should expose narrowly-scoped tools rather than a broad search endpoint. `preflight_context`, `check_currency`, `impact`, `verify_position`, `ingest`, and `audit_pack` match MCP's tool model because they are explicit operations with auditable inputs and outputs.

Security implications:

- every read tool returning firm content must pass boundary review before returning content;
- every write tool must create audit-journal metadata;
- descriptions must not be treated as trust boundaries by hosts, so server-side validation is still mandatory;
- destructive or state-changing calls need explicit caller, scope, and evidence fields.

## Resources and prompts

Resources are application-driven context objects identified by URIs. They fit file trees, database schemas, or static data surfaces. Prompts are user-controlled templates or workflows retrievable by clients.

[Inference] Solomon should not ship resources/prompts in the first MCP cut. A resource like `solomon://matter/{id}/knowledge` risks becoming retrieval UI by another name. A prompt like "draft from firm context" would move Solomon toward a destination/drafting product. Both can wait until tool semantics and scope enforcement are stable.

## Client-side features

Sampling lets a server request LLM generations through the client. Roots let a client expose filesystem boundaries. Elicitation lets a server request structured user input through the client and explicitly must not be used to request sensitive information.

[Inference] Solomon should avoid client-side feature dependencies for v0.2. The server can operate as a deterministic currency/boundary layer with no model-callback dependency, no filesystem-root dependency, and no interactive user-data collection path.

## Transport and auth choices

stdio is the default for Claude Desktop / Claude Code style local registration. It launches Solomon as a subprocess and uses newline-delimited JSON-RPC over stdin/stdout; stderr is acceptable for logs. The server must never print human logs to stdout.

Streamable HTTP is the remote/server option. The spec calls out Origin validation, localhost binding for local HTTP, and authentication for all connections. OAuth 2.1-style authorization is optional, and the spec says stdio implementations should retrieve credentials from the environment rather than use the HTTP auth flow.

[Inference] v0.2 should implement:

- stdio by default;
- Streamable HTTP for remote MCP compatibility;
- `SOLOMON_MCP_TOKEN` bearer-token auth for HTTP portfolio scope;
- localhost default binding;
- strict Origin validation for HTTP;
- no OAuth/SSO until a real enterprise deployment exists.

## Sources

- Specification overview: <https://modelcontextprotocol.io/specification/2025-06-18>
- Lifecycle: <https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle>
- Transports: <https://modelcontextprotocol.io/specification/2025-06-18/basic/transports>
- Authorization: <https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization>
- Tools: <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>
- Resources: <https://modelcontextprotocol.io/specification/2025-06-18/server/resources>
- Prompts: <https://modelcontextprotocol.io/specification/2025-06-18/server/prompts>
- Sampling: <https://modelcontextprotocol.io/specification/2025-06-18/client/sampling>
- Roots: <https://modelcontextprotocol.io/specification/2025-06-18/client/roots>
- Elicitation: <https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation>
