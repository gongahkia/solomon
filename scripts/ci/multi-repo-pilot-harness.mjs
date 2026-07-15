// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ShibahamaMcpClient } from "../../bindings/node/mcp-client.mjs";

const root = new URL("../..", import.meta.url).pathname;
const fixtures = JSON.parse(await readFile(new URL("./multi-repo-pilot-fixtures.json", import.meta.url), "utf8"));
const directory = await mkdtemp(join(tmpdir(), "shibahama-multi-repo-pilot-"));
const apiKey = "multi-repo-pilot-api-key";
const encryptionKey = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
const base = `http://127.0.0.1:${process.env.SHIBAHAMA_PILOT_BIND_PORT ?? "8887"}`;
let server;

try {
  const embeddedId = runEmbedded();
  await runService();
  await runMcp();
  process.stdout.write(`multi-repo pilot harness passed embedded_memory_id=${embeddedId}\n`);
} finally {
  if (server?.exitCode === null) {
    server.kill("SIGTERM");
    await new Promise((resolve) => server.once("exit", resolve));
  }
  await rm(directory, { force: true, recursive: true });
}

function cli(arguments_) {
  const result = spawnSync("cargo", ["run", "-q", "-p", "shibahama-cli", "--", ...arguments_], {
    cwd: root,
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

function runEmbedded() {
  const db = join(directory, "embedded.redb");
  const item = cli([
    "write", "--path", db, "--dimensions", "2", "--content", fixtures.embedded.content,
    "--vector", "1,0", "--source-kind", "file", "--source-ref", fixtures.embedded.sourceRef,
    "--ingested-by", "agent-alpha-1", "--valid-from-unix", "0", "--ingested-at-unix", "0",
  ]);
  cli([
    "challenge", "--path", db, "--dimensions", "2", "--memory-id", item.id,
    "--reason", fixtures.embedded.rejectionReason, "--actor", fixtures.mcp.principal, "--timestamp-unix", "1",
  ]);
  const audit = cli(["audit", "--path", db, "--dimensions", "2", "--memory-id", item.id]);
  assertAuditKinds(audit.events, fixtures.embedded.expectedAuditKinds);
  assert.equal(audit.why.item.provenance.source_ref, fixtures.embedded.sourceRef);
  return item.id;
}

async function runService() {
  const db = join(directory, "service.redb");
  let stderr = "";
  server = spawn("cargo", [
    "run", "-q", "-p", "shibahama-cli", "--", "serve", "--path", db, "--dimensions", "2",
    "--api-key", apiKey, "--bind", base.replace("http://", ""), "--namespace", fixtures.repositories[0],
  ], {
    cwd: root,
    env: { ...process.env, SHIBAHAMA_ENCRYPTION_KEY: encryptionKey },
    stdio: ["ignore", "ignore", "pipe"],
  });
  server.stderr.on("data", (chunk) => { stderr = `${stderr}${chunk}`.slice(-8192); });
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(`${base}/healthz`);
      if (response.ok) break;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (attempt === 39) assert.fail(stderr || "pilot service did not become healthy");
  }

  const memoryIds = new Map();
  for (const session of fixtures.service.sessions) {
    const item = await request(session.repository, "/write", {
      content: session.content,
      vector: [1, 0],
      source_kind: "agent",
      source_ref: session.sourceRef,
      ingested_by: session.agent,
      valid_from_unix: 0,
      ingested_at_unix: 0,
      scope: { repository: session.repository, team: null, visibility: "repository" },
    });
    memoryIds.set(session.agent, item.id);
  }
  for (const repository of fixtures.repositories) {
    const inspection = await request(repository, "/inspect");
    const expected = fixtures.service.sessions.filter((session) => session.repository === repository);
    assert.equal(inspection.memory_count, expected.length);
    assert.deepEqual(new Set(inspection.memories.map((memory) => memory.provenance.ingested_by)), new Set(expected.map((session) => session.agent)));
  }
  const audit = await request(fixtures.repositories[0], `/audit/${memoryIds.get("agent-alpha-1")}`);
  assertAuditKinds(audit.events, fixtures.service.expectedAuditKinds);
}

async function runMcp() {
  const db = join(directory, "mcp.redb");
  const scope = { repository: fixtures.repositories[0], team: null, visibility: "repository" };
  const client = await ShibahamaMcpClient.connectStdio({
    command: "cargo",
    args: [
      "run", "-q", "-p", "shibahama-cli", "--", "mcp", "--path", db, "--dimensions", "2",
      "--scope-repository", scope.repository, "--scope-visibility", scope.visibility,
      "--principal", fixtures.mcp.principal, "--actor", "human", "--allow-scope-promotion",
    ],
    cwd: root,
    clientInfo: { name: "multi-repo-pilot", version: "1" },
  });
  try {
    const written = await client.write({
      schemaVersion: 1, scope, actor: "human", actorId: fixtures.mcp.principal,
      content: fixtures.mcp.content, vector: [1, 0], sourceKind: "user", validFromUnix: 0, ingestedAtUnix: 0,
    });
    const memoryId = written.result.memory.id;
    const promotion = await client.promote({
      schemaVersion: 1, scope, actor: "human", actorId: fixtures.mcp.principal, memoryId,
      team: fixtures.team, rationale: "maintainer approved cross-repository sharing", promotedAtUnix: 2,
      confirmation: {
        schemaVersion: 1, intent: "promotion", token: "pilot-promotion-0001", actorId: fixtures.mcp.principal,
        scope, targetId: memoryId, targetTeam: fixtures.team,
      },
    });
    assert.equal(promotion.result.promotion.scope.visibility, "team");
    assert.equal(promotion.result.promotion.scope.team, fixtures.team);
    const resource = await client.readResource("shibahama://v1/audit");
    const audit = JSON.parse(resource.contents[0].text);
    assertAuditKinds(audit.auditEvents, fixtures.mcp.expectedAuditKinds);
  } finally {
    await client.close();
  }
}

async function request(repository, path, body) {
  const response = await fetch(`${base}${path}`, {
    method: body ? "POST" : "GET",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "x-shibahama-namespace": repository,
      "x-shibahama-scope-visibility": "repository",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json();
  assert.equal(response.status, 200, JSON.stringify(payload));
  return payload;
}

function assertAuditKinds(events, expectedKinds) {
  const actual = new Set(events.map((event) => event.kind));
  for (const kind of expectedKinds) assert.ok(actual.has(kind), `missing audit kind: ${kind}`);
}
