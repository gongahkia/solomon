# MCP client config

`mcp.json` is a portable stdio config for Claude Code, Cursor, Continue, and other MCP clients that read `mcpServers`.

Before use, replace `/absolute/path/to/solomon` with this repo path.

Quick Claude Code check:

```bash
claude -p --strict-mcp-config --mcp-config examples/mcp/mcp.json "List the Solomon MCP tools."
```

For HTTP/SSE, run `solomon mcp serve --http` or `--sse` and configure the client with `/mcp` or `/sse` plus `Authorization: Bearer <SOLOMON_MCP_TOKEN>`.
