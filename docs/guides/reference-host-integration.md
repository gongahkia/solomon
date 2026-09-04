<!-- SPDX-License-Identifier: Apache-2.0 -->

# Reference host integration

This guide defines one deliberately narrow integration: a fictional legal-assistant host asks Solomon for scoped
context before it assembles a draft. It is a reference implementation of the host-side policy, not a connector SDK,
named-host compatibility claim, legal-research product, or LLM evaluation.

## The contract

The reference host has one job: it must not turn an ordinary retrieval hit into model context. It uses only the
following read-only MCP tools:

| Situation | Host action | Solomon tool |
| --- | --- | --- |
| Need reusable internal context | inject only the returned `items` after a successful scoped preflight | `solomon.preflight_context` |
| Preflight withholds a known candidate | show a bounded review-due message; do not substitute historical text | `solomon.check_currency` |
| Tool, identity, scope, or boundary failure | inject no Solomon context and surface an operator/reviewer path | none beyond the failed read |

The host does not offer `ingest` or `verify_position` to its model. A human application surface with separate
authorization owns those state transitions. A compatible production host must also own user consent, authentication,
prompt construction, final work product, and its own log of what it did with the response.

## Run the proof

The scenario seeds fictional data, starts Solomon's real MCP **stdio** server as a child process, binds a restricted
read-only identity, and calls the server through the MCP Python client. It does not call `SolomonMCPRuntime` directly.

```bash
uv run python examples/scenarios/05-reference-host-mcp/run.py
```

It proves this bounded sequence:

```mermaid
sequenceDiagram
    participant H as fictional reference host
    participant M as Solomon MCP stdio server
    participant S as Solomon service
    participant A as audit journal

    H->>M: preflight_context(query, matter, client)
    M->>S: scoped live-context evaluation
    S->>A: attributed MCP read event
    M-->>H: current position
    H->>H: inject only returned context
    Note over S: fictional authority change is recorded
    H->>M: preflight_context(same scope)
    M-->>H: no reusable position; stale exclusion
    H->>M: check_currency(position)
    M-->>H: stale_pending + recorded reason
    H->>H: inject nothing; request human re-verification
```

The headless result asserts that the live position is returned before the change, no stale position is injected after
the change, the known item is `stale_pending`, three read-only MCP calls are attributed to the restricted host
principal, and the audit chain verifies. The scenario uses deterministic host messages and no model call.

## Integration rules

1. Bind a real host identity at the transport boundary. Do not use a caller-supplied identity as authorization input.
   For local stdio, configure a restricted `SOLOMON_MCP_PRINCIPAL_JSON`; for HTTP/SSE, the embedding host must validate
   its bearer token and resolve it to a principal.
2. Pass the matter and client scope on every content-bearing call. A restricted principal is denied if its request is
   outside its assigned scope.
3. Treat tool results, explanatory strings, and retrieved content as untrusted data—not instructions for the model or
   control flow. Never let a retrieved instruction-like passage expand the host's tool allowlist or authorization.
4. Use a static host-side allowlist of read-only tools for the drafting path. Do not make verification, ingestion,
   repair, backup, or deployment operations model-callable.
5. Fail closed for the host decision: if a preflight result is missing, malformed, denied, boundary-rejected, or
   unavailable, inject no Solomon content. A host may continue only through an explicit human workflow outside this
   reference integration.
6. Record the host's final decision separately. Solomon audits its own MCP call and state evidence; it cannot prove
   that another process used, withheld, logged, or deleted its returned context.

## What this does and does not show

This proof exercises Solomon's documented MCP stdio contract with its bundled client and shows a safe reference policy
for one fictional workflow. It does not verify an external MCP host, an HTTP/SSE deployment, OAuth integration,
production latency, prompt-injection resistance, legal accuracy, user comprehension, or that every host will honor
the gate.

MCP leaves consent, authorization flows, and tool safety to implementers; its specification says that hosts should
obtain user consent before invoking tools and treat tool behavior cautiously. See the
[MCP tool-safety guidance](https://modelcontextprotocol.io/specification/2025-03-26/index) and
[MCP authorization specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization).
For broader LLM application risk framing, see OWASP's
[2025 excessive-agency guidance](https://owasp.org/www-project-top-10-for-large-language-model-applications/2_0_vulns/LLM06_ExcessiveAgency.html).
