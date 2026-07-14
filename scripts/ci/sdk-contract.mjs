// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ShibahamaMcpClient } from "../../bindings/node/mcp-client.mjs";
import { EmbeddedShibahama } from "../../bindings/node/sdk.mjs";

const root = new URL("../..", import.meta.url).pathname;
const dir = await mkdtemp(join(tmpdir(), "shibahama-sdk-contract-"));
const port = await unusedPort();
const baseUrl = `http://127.0.0.1:${port}`;
const apiKey = "sdk-contract-key";
const encryptionKey = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
const namespace = "sdk-contract";
const scope = { repository: namespace, visibility: "repository" };
const mcpScope = { ...scope, team: null };
const server = spawn(
  "cargo",
  [
    "run",
    "-q",
    "-p",
    "shibahama-cli",
    "--",
    "serve",
    "--path",
    join(dir, "server.redb"),
    "--dimensions",
    "2",
    "--api-key",
    apiKey,
    "--namespace",
    namespace,
    "--bind",
    `127.0.0.1:${port}`,
  ],
  { cwd: root, env: { ...process.env, SHIBAHAMA_ENCRYPTION_KEY: encryptionKey }, stdio: "ignore" },
);

try {
  await waitForReady();
  const embedded = new EmbeddedShibahama({
    path: join(dir, "embedded.redb"),
    dimensions: 2,
    scope,
  });
  const embeddedItem = embedded.write("SDK contract embedded", {
    vector: [1, 0],
    sourceKind: "user",
    sourceRef: "embedded",
    validFromUnix: 0,
    ingestedAtUnix: 0,
  });
  const httpItem = await request("POST", "/write", {
    content: "SDK contract HTTP",
    vector: [1, 0],
    source_kind: "user",
    source_ref: "http",
    valid_from_unix: 0,
    ingested_at_unix: 0,
    scope,
  });
  const mcp = await ShibahamaMcpClient.connectHttp({
    url: `${baseUrl}/mcp`,
    apiKey,
    namespace,
    scope: mcpScope,
  });
  const mcpWrite = await mcp.write({
    schemaVersion: 1,
    scope: mcpScope,
    actor: "service",
    actorId: "api_key",
    content: "SDK contract MCP",
    vector: [1, 0],
    sourceKind: "user",
    validFromUnix: 0,
    ingestedAtUnix: 0,
  });
  const mcpItem = mcpWrite.result.memory;

  assert.deepEqual(
    [embeddedItem, httpItem, mcpItem].map(normalizeItem),
    [
      { content: "SDK contract embedded", kind: "fact", sourceKind: "user", scope: mcpScope },
      { content: "SDK contract HTTP", kind: "fact", sourceKind: "user", scope: mcpScope },
      { content: "SDK contract MCP", kind: "fact", sourceKind: "user", scope: mcpScope },
    ],
  );

  const embeddedRecall = embedded.recall([1, 0], 1, { nowUnix: 0 });
  const httpRecall = await request("POST", "/recall", {
    query_vector: [1, 0],
    top_k: 3,
    now_unix: 0,
  });
  const mcpRecall = await mcp.recall({
    schemaVersion: 1,
    scope: mcpScope,
    queryVector: [1, 0],
    topK: 3,
    nowUnix: 0,
  });

  assert.deepEqual(normalizeCandidate(embeddedRecall[0]), normalizeItem(embeddedItem));
  assert.deepEqual(normalizeCandidate(httpRecall.find((candidate) => candidate.id === httpItem.id)), normalizeItem(httpItem));
  assert.deepEqual(normalizeCandidate(mcpRecall.result.candidates.find((candidate) => candidate.id === mcpItem.id)), normalizeItem(mcpItem));
  assert.equal(embedded.simulateRecallPolicy(20).decision.effective_candidates, 8);
  assert.equal((await request("POST", "/policy/simulate/recall", { top_k: 20 })).decision.effective_candidates, 8);
  assert.equal(JSON.parse((await mcp.readResource("shibahama://v1/policy")).contents[0].text).schemaVersion, 1);
  await mcp.close();
} finally {
  server.kill("SIGTERM");
  await rm(dir, { force: true, recursive: true });
}

console.log("embedded/HTTP/MCP SDK contract passed");

async function request(method, path, body) {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "x-shibahama-namespace": namespace,
      "x-shibahama-scope-visibility": "repository",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`HTTP ${method} ${path} failed with ${response.status}`);
  return response.json();
}

function normalizeItem(item) {
  return {
    content: item.content,
    kind: item.kind,
    sourceKind: item.provenance.sourceKind ?? item.provenance.source_kind,
    scope: {
      repository: item.scope.repository,
      team: item.scope.team ?? null,
      visibility: item.scope.visibility,
    },
  };
}

function normalizeCandidate(candidate) {
  if (!candidate) throw new Error("expected recall candidate");
  return normalizeItem(candidate.item);
}

async function waitForReady() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(`${baseUrl}/readyz`, {
        headers: { "x-api-key": apiKey, "x-shibahama-namespace": namespace },
      });
      if (response.ok) return;
    } catch {} // server is starting
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("SDK contract server did not become ready");
}

function unusedPort() {
  return new Promise((resolve, reject) => {
    const listener = net.createServer();
    listener.once("error", reject);
    listener.listen(0, "127.0.0.1", () => {
      const { port } = listener.address();
      listener.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}
