// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { registerPiShibahama } from "../../integrations/pi/shibahama-mcp-core.mjs";
import { ShibahamaMcpClient, ShibahamaMcpError } from "../../bindings/node/mcp-client.mjs";

const root = resolve(dirname(new URL(import.meta.url).pathname), "../..");
const fixture = await mkdtemp(resolve(tmpdir(), "shibahama-pi-mcp-"));

try {
  const config = await fixtureConfig(fixture);
  assertStandardConfig(config);
  const pi = fakePi();
  const configPath = resolve(fixture, "mcp.json");
  registerPiShibahama(pi, { Type: fakeType(), configPath });
  assert.equal(pi.tools.size, 7);
  for (const tool of pi.tools.values()) {
    assert.equal(Object.hasOwn(tool.parameters.properties, "scope"), false);
    assert.equal(Object.hasOwn(tool.parameters.properties, "actor"), false);
    assert.equal(Object.hasOwn(tool.parameters.properties, "actorId"), false);
  }

  const now = Math.floor(Date.now() / 1000);
  await assert.rejects(
    pi.tools.get("shibahama_memory_write").execute("suggested", {
      content: "Pi suggested memory must be reviewed.",
      vector: [0.2, 0.8],
      sourceKind: "agent",
      validFromUnix: now,
      ingestedAtUnix: now,
      captureIntent: "suggested",
    }),
    (error) => error instanceof ShibahamaMcpError && error.code === "SHIBA_POLICY",
  );
  const write = await pi.tools.get("shibahama_memory_write").execute("manual", {
    content: "Pi manual memory fixture.",
    vector: [0.2, 0.8],
    sourceKind: "user",
    validFromUnix: now,
    ingestedAtUnix: now,
    captureIntent: "manual",
  });
  assert.equal(write.details.result.policyOutcome, "allowed");
  const recall = await pi.tools.get("shibahama_memory_recall").execute("recall", {
    queryVector: [0.2, 0.8],
    topK: 3,
    nowUnix: now,
  });
  assert.equal(recall.details.result.candidates.length, 1);
  const review = await pi.tools.get("shibahama_memory_review").execute("review", { operation: "list" });
  assert.deepEqual(review.details.result.queue, []);
  await Promise.all(pi.handlers.get("session_shutdown").map((handler) => handler()));

  const client = await ShibahamaMcpClient.connectStdio({
    ...config.mcpServers.shibahama,
    clientInfo: { name: "shibahama-pi-fixture", version: "1" },
  });
  const audit = await client.readResource("shibahama://v1/audit");
  const auditPayload = JSON.parse(audit.contents[0].text);
  assert.equal(auditPayload.scope.repository, "pi-fixture");
  assert.equal(auditPayload.auditEvents.some((event) => event.kind === "memory_written"), true);
  await client.close();
  process.stdout.write("Pi MCP fixture passed\n");
} finally {
  await rm(fixture, { recursive: true, force: true });
}

async function fixtureConfig(directory) {
  const config = JSON.parse(await readFile(resolve(root, ".pi/mcp.json"), "utf8"));
  const server = config.mcpServers.shibahama;
  const pathIndex = server.args.indexOf("--path") + 1;
  const repositoryIndex = server.args.indexOf("--scope-repository") + 1;
  server.args[pathIndex] = resolve(directory, "pi.redb");
  server.args[repositoryIndex] = "pi-fixture";
  server.cwd = root;
  await writeFile(resolve(directory, "mcp.json"), `${JSON.stringify(config, null, 2)}\n`);
  return config;
}

function assertStandardConfig(config) {
  const server = config?.mcpServers?.shibahama;
  assert.equal(typeof server?.command, "string");
  assert.equal(Array.isArray(server?.args), true);
  assert.equal(Object.keys(server).every((key) => ["command", "args", "cwd", "env"].includes(key)), true);
  assert.equal(JSON.stringify(config).toLowerCase().includes("secret"), false);
  assert.equal(JSON.stringify(config).toLowerCase().includes("token"), false);
}

function fakePi() {
  const tools = new Map();
  const handlers = new Map();
  return {
    tools,
    handlers,
    registerTool(tool) { tools.set(tool.name, tool); },
    on(event, handler) {
      const existing = handlers.get(event) ?? [];
      existing.push(handler);
      handlers.set(event, existing);
    },
  };
}

function fakeType() {
  return {
    Array: (items, options = {}) => ({ type: "array", items, ...options }),
    Boolean: (options = {}) => ({ type: "boolean", ...options }),
    Integer: (options = {}) => ({ type: "integer", ...options }),
    Literal: (value) => ({ const: value }),
    Null: () => ({ type: "null" }),
    Number: (options = {}) => ({ type: "number", ...options }),
    Object: (properties, options = {}) => ({ type: "object", properties, ...options }),
    Optional: (schema) => ({ ...schema, optional: true }),
    String: (options = {}) => ({ type: "string", ...options }),
    Union: (variants) => ({ anyOf: variants }),
  };
}
