// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import test from "node:test";

import { SolomonClient, SolomonMCPError } from "../dist/index.js";

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mockFetch(responses) {
  const calls = [];
  return {
    calls,
    fetch: async (url, init) => {
      calls.push({ url, init });
      const response = responses.shift();
      assert.ok(response, "unexpected fetch call");
      return response;
    },
  };
}

function toolResponse(output) {
  return jsonResponse({
    jsonrpc: "2.0",
    id: 1,
    result: { structuredContent: output },
  });
}

function requestBody(call) {
  return JSON.parse(call.init.body);
}

test("sends generic streamable-HTTP tool requests", async () => {
  const transport = mockFetch([toolResponse({ version: "0.1.0" })]);
  const client = new SolomonClient({
    baseUrl: "https://mcp.example.test/",
    token: "secret-token",
    fetch: transport.fetch,
  });

  assert.deepEqual(await client.health({ caller_id: "reviewer-1" }), { version: "0.1.0" });
  assert.equal(transport.calls[0].url, "https://mcp.example.test/mcp");
  assert.deepEqual(requestBody(transport.calls[0]), {
    jsonrpc: "2.0",
    id: 1,
    method: "tools/call",
    params: { name: "solomon.health", arguments: { caller_id: "reviewer-1" } },
  });
  const headers = new Headers(transport.calls[0].init.headers);
  assert.equal(headers.get("accept"), "application/json, text/event-stream");
  assert.equal(headers.get("authorization"), "Bearer secret-token");
});

test("maps every public client method to its MCP tool", async () => {
  const methods = [
    ["preflightContext", { query: "query" }, "solomon.preflight_context"],
    ["checkCurrency", { knowledge_item_id: "item-1" }, "solomon.check_currency"],
    ["getDependencies", { knowledge_item_id: "item-1" }, "solomon.get_dependencies"],
    ["verifyPosition", { knowledge_item_id: "item-1", verifier_id: "v-1", decision: "reaffirm", evidence_ref: "e-1" }, "solomon.verify_position"],
    ["ingest", { text: "text", source_ref: "source", scope: {} }, "solomon.ingest"],
    ["auditPack", { knowledge_item_id: "item-1" }, "solomon.audit_pack"],
    ["dependencySuggestions", { knowledge_item_id: "item-1" }, "solomon.dependency_suggestions"],
    ["impact", { external_authority_id: "authority-1" }, "solomon.impact"],
  ];
  const transport = mockFetch(methods.map((_, index) => toolResponse({ index })));
  const client = new SolomonClient({ endpoint: "https://mcp.example.test/rpc", fetch: transport.fetch });

  for (const [method, input] of methods) {
    assert.deepEqual(await client[method](input), { index: transport.calls.length - 1 });
  }
  assert.deepEqual(
    transport.calls.map((call) => requestBody(call).params.name),
    methods.map(([, , name]) => name),
  );
  assert.deepEqual(
    transport.calls.map((call) => requestBody(call).id),
    methods.map((_, index) => index + 1),
  );
});

test("decodes SSE-framed JSON-RPC tool results", async () => {
  const transport = mockFetch([
    new Response(
      "event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"content\":[{\"type\":\"text\",\"text\":\"{\\\"version\\\":\\\"sse\\\"}\"}]}}\n\ndata: [DONE]\n",
      { headers: { "content-type": "text/event-stream; charset=utf-8" } },
    ),
  ]);
  const client = new SolomonClient({ fetch: transport.fetch });

  assert.deepEqual(await client.health(), { version: "sse" });
});

test("surfaces JSON-RPC errors", async () => {
  const transport = mockFetch([
    jsonResponse({
      jsonrpc: "2.0",
      id: 1,
      error: { code: -32602, message: "invalid request", data: { field: "query" } },
    }),
  ]);
  const client = new SolomonClient({ fetch: transport.fetch });

  await assert.rejects(
    () => client.health(),
    (error) => error instanceof SolomonMCPError
      && error.message === "invalid request"
      && error.code === -32602
      && deepEqual(error.data, { field: "query" }),
  );
});

test("surfaces forbidden HTTP responses", async () => {
  const transport = mockFetch([new Response("forbidden", { status: 403 })]);
  const client = new SolomonClient({ fetch: transport.fetch });

  await assert.rejects(
    () => client.health(),
    (error) => error instanceof SolomonMCPError
      && error.message === "Solomon MCP HTTP 403"
      && error.code === 403
      && error.data === "forbidden",
  );
});

function deepEqual(actual, expected) {
  try {
    assert.deepEqual(actual, expected);
    return true;
  } catch {
    return false;
  }
}
