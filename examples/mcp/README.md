# MCP client config

`mcp.json` is a portable stdio template for MCP clients that use an `mcpServers` registry.

Before use, replace `/absolute/path/to/solomon` with this repo path.

Check the server process contract:

```bash
uv --directory /absolute/path/to/solomon run python -m solomon.mcp.server
```

For HTTP/SSE, run `solomon mcp serve --http` or `--sse` and configure a compatible client with `/mcp` or `/sse` plus `Authorization: Bearer <SOLOMON_MCP_TOKEN>`. See [`docs/mcp/install.md`](../../docs/mcp/install.md) for generic identity, scope, and smoke-test guidance.
