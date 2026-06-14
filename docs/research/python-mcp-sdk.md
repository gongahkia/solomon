# Python MCP SDK survey

Checked: 2026-06-14

## Decision

[Inference] Use the official `mcp` Python SDK for Solomon v0.2, pinned as `mcp>=1.27,<2`.

Rationale:

- It is the official Python implementation under `modelcontextprotocol/python-sdk`.
- It implements clients, servers, resources, prompts, tools, stdio, SSE, Streamable HTTP, lifecycle handling, and MCP protocol messages.
- It already contains `mcp.server.fastmcp.FastMCP`, so Solomon can get a high-level decorator API without adding the standalone `fastmcp` package.
- The upstream README says v1.x is stable/current, v2 is alpha, beta is targeted for 2026-06-30, and stable v2 for 2026-07-27; it explicitly recommends `<2` for packages depending on `mcp`.
- Solomon needs protocol compatibility and predictable transport behavior more than interactive MCP apps or generated UI.

Revisit after upstream v2 reaches stable and after Solomon's stdio + Streamable HTTP tests exist.

## Options

| Option | Evidence | Fit | Risk |
|---|---|---|---|
| `mcp` official SDK | PyPI `mcp` 1.27.2, released 2026-05-29; Python >=3.10; MIT; official repo/docs | Best default for stdio/Streamable HTTP server work | v2 alpha transition; pin `<2` |
| standalone `fastmcp` | PyPI `fastmcp` 3.4.2, released 2026-06-06; Apache-2.0; docs position it as Pythonic framework for servers, clients, apps | Fastest high-level build path; useful if official SDK API is too low-level | extra dependency; docs track main branch and may include unreleased behavior; app/UI features are outside Solomon scope |
| Anthropic SDK MCP helpers | Anthropic docs expose `anthropic.lib.tools.mcp` via `pip install anthropic[mcp]` | Useful for a client that maps MCP tools into Claude API calls | Not a Solomon MCP server framework; tied to Claude API use |
| `anthropic-mcp` standalone | No primary PyPI/GitHub source found under that exact package name in this check | No fit | [Unverified] Treat as not a usable SDK until a primary package/repo is found |

## Notes

The official SDK README's quickstart uses `from mcp.server.fastmcp import FastMCP`, and PyPI documents support for resources, prompts, tools, stdio, SSE, and Streamable HTTP. That is enough for Solomon's immediate server work: the first MCP surface is tools-only, with stdio default and Streamable HTTP for remote MCP scenarios.

Standalone FastMCP is credible and active. Its docs say FastMCP 1.0 was incorporated into the official Python SDK in 2024, and its PyPI project advertises servers, clients, apps, schema generation, transport negotiation, authentication, and lifecycle handling. For Solomon, that breadth is not the first requirement. The project already has FastAPI, Typer, Pydantic, and strict tests; minimizing MCP-specific dependency surface is preferable until the tool contract is stable.

Anthropic's Python package should not be confused with a server SDK. Anthropic documents MCP connector helpers for converting MCP tools/resources/prompts into Claude API types, installed through `anthropic[mcp]`. That is relevant for client-side demos or vendor simulation, not for implementing `solomon mcp serve`.

## Implementation implication

- Add dependency: `mcp>=1.27,<2` when implementing TODO 23/24.
- Build with `mcp.server.fastmcp.FastMCP` unless low-level server hooks are needed for custom auth/logging.
- Keep tool functions thin and delegate to `SolomonService`; do not duplicate currency/graph/audit logic in MCP handlers.
- Add a local compatibility note for future v2 migration before removing the `<2` pin.

## Sources

- Official Python SDK repo: <https://github.com/modelcontextprotocol/python-sdk>
- Official Python SDK docs: <https://py.sdk.modelcontextprotocol.io/>
- PyPI `mcp`: <https://pypi.org/project/mcp/>
- FastMCP docs: <https://gofastmcp.com/getting-started/welcome>
- PyPI `fastmcp`: <https://pypi.org/project/fastmcp/>
- Anthropic MCP connector docs: <https://platform.claude.com/docs/en/agents-and-tools/mcp-connector>
