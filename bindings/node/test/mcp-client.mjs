// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";

import {
  MCP_PROTOCOL_VERSION,
  MCP_RESOURCE_URIS,
  ShibahamaMcpClient,
  ShibahamaMcpError,
  StdioMcpTransport,
  StreamableHttpMcpTransport,
} from "../mcp-client.mjs";

class FixtureTransport {
  constructor() { this.messages = []; }
  async request(message) {
    this.messages.push(message);
    if (message.method === "initialize") {
      return { jsonrpc: "2.0", id: message.id, result: { protocolVersion: MCP_PROTOCOL_VERSION } };
    }
    if (message.method === "tools/list") {
      return { jsonrpc: "2.0", id: message.id, result: { tools: [{ name: "shibahama_memory_recall_v1" }] } };
    }
    if (message.method === "tools/call") {
      return { jsonrpc: "2.0", id: message.id, result: { isError: true, structuredContent: { error: { code: "SHIBA_POLICY", detail: "policy denied", severity: "fatal", retryable: false } } } };
    }
    return undefined;
  }
}

const fixture = new FixtureTransport();
const client = await ShibahamaMcpClient.connect(fixture, { name: "test", version: "1" });
assert.equal(client.server.protocolVersion, MCP_PROTOCOL_VERSION);
assert.equal(MCP_RESOURCE_URIS[1], "shibahama://v1/scope");
assert.equal(fixture.messages[1].method, "notifications/initialized");
assert.deepEqual(await client.listTools(), [{ name: "shibahama_memory_recall_v1" }]);
await assert.rejects(
  client.recall({ schemaVersion: 1, scope: { repository: "repo", team: null, visibility: "repository" } }),
  (error) => error instanceof ShibahamaMcpError
    && error.code === "SHIBA_POLICY"
    && error.severity === "fatal"
    && error.retryable === false,
);

const requests = [];
const http = new StreamableHttpMcpTransport({
  url: "https://example.invalid/mcp",
  apiKey: "test-key",
  namespace: "repo",
  scope: { visibility: "repository", team: null },
  fetch: async (url, init) => {
    requests.push({ url, init });
    return new Response(JSON.stringify({ jsonrpc: "2.0", id: 1, result: { protocolVersion: MCP_PROTOCOL_VERSION } }), {
      headers: { "content-type": "application/json", "mcp-session-id": "session-1" },
    });
  },
});
const initialized = await http.request({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} });
assert.equal(initialized.result.protocolVersion, MCP_PROTOCOL_VERSION);
assert.equal(requests[0].init.headers["x-api-key"], "test-key");
assert.equal(http.sessionId, "session-1");

const stdioServer = [
  "process.stdin.on('data', chunk => {",
  "for (const line of chunk.toString().trim().split('\\n')) {",
  "const message = JSON.parse(line);",
  "if (message.id !== undefined) process.stdout.write(JSON.stringify({jsonrpc:'2.0', id:message.id, result:{protocolVersion:'2025-11-25'}})+'\\n');",
  "}",
  "});",
].join("");
const stdio = new StdioMcpTransport({ command: process.execPath, args: ["-e", stdioServer] });
const stdioClient = await ShibahamaMcpClient.connect(stdio);
assert.equal(stdioClient.server.protocolVersion, MCP_PROTOCOL_VERSION);
await stdioClient.close();

console.log("MCP client lane passed");
