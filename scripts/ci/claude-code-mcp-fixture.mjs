// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ShibahamaMcpClient } from "../../bindings/node/mcp-client.mjs";

const root = new URL("../..", import.meta.url).pathname;
const configPath = new URL("../../integrations/claude-code/mcp.json", import.meta.url);
const dir = await mkdtemp(join(tmpdir(), "shibahama-claude-code-"));
const scope = { repository: "claude-code-fixture", team: null, visibility: "repository" };
const env = {
  SHIBAHAMA_MCP_PATH: join(dir, "claude-code.redb"),
  SHIBAHAMA_MCP_DIMENSIONS: "2",
  SHIBAHAMA_MCP_SCOPE_REPOSITORY: scope.repository,
};

try {
  const config = JSON.parse(await readFile(configPath, "utf8"));
  assert.deepEqual(Object.keys(config), ["mcpServers"]);
  assert.equal(Object.keys(config.mcpServers).length, 1);
  assert.equal(config.mcpServers.shibahama.command, "cargo");
  assert.doesNotMatch(JSON.stringify(config), /"(?:api[_-]?key|authorization|secret|token)"\s*:/i);
  await validateClaudeCodeConfig(config.mcpServers.shibahama);
  const client = await ShibahamaMcpClient.connectStdio({
    command: expand(config.mcpServers.shibahama.command, env),
    args: config.mcpServers.shibahama.args.map((value) => expand(value, env)),
    cwd: root,
    env,
    clientInfo: { name: "claude-code-fixture", version: "1" },
  });
  const tools = await client.listTools();
  const write = tools.find((tool) => tool.name === "shibahama_memory_write_v1");
  assert.deepEqual(write.inputSchema.properties.captureIntent.enum, ["manual", "suggested", "automatic"]);

  const suggested = writeArguments("suggested capture");
  suggested.captureIntent = "suggested";
  await assert.rejects(client.write(suggested), (error) => error.code === "SHIBA_POLICY");

  const written = await client.write(writeArguments("Claude Code fixture memory"));
  const memoryId = written.result.memory.id;
  const recalled = await client.recall({
    schemaVersion: 1,
    scope,
    queryVector: [1, 0],
    topK: 1,
    nowUnix: 0,
  });
  assert.equal(recalled.result.candidates[0].id, memoryId);
  const explained = await client.explain({ schemaVersion: 1, scope, memoryId, nowUnix: 0 });
  assert.equal(explained.result.trace.provenance.ingested_by, "claude-code");

  const rejected = writeArguments("forged actor must reject");
  rejected.actor = "agent";
  await assert.rejects(client.write(rejected), (error) => error.code === "SHIBA_UNAUTHORIZED");
  await client.close();
} finally {
  await rm(dir, { force: true, recursive: true });
}

console.log("Claude Code MCP fixture passed");

function writeArguments(content) {
  return {
    schemaVersion: 1,
    scope,
    actor: "human",
    actorId: "claude-code",
    content,
    vector: [1, 0],
    sourceKind: "user",
    validFromUnix: 0,
    ingestedAtUnix: 0,
  };
}

function expand(value, values) {
  return value.replace(/\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}/g, (_, name, fallback) => {
    const resolved = values[name] ?? process.env[name] ?? fallback;
    if (resolved === undefined) throw new Error(`missing environment value for ${name}`);
    return resolved;
  });
}

async function validateClaudeCodeConfig(server) {
  const version = spawnSync("claude", ["--version"], { encoding: "utf8" });
  if (version.error?.code === "ENOENT") {
    console.log("Claude Code CLI validation skipped: claude is unavailable");
    return;
  }
  assert.equal(version.status, 0, version.stderr);
  const project = join(dir, "claude-project");
  await mkdir(project);
  const configured = spawnSync(
    "claude",
    ["mcp", "add-json", "--scope", "project", "shibahama", JSON.stringify(server)],
    { cwd: project, encoding: "utf8" },
  );
  assert.equal(configured.status, 0, configured.stderr);
  const parsed = JSON.parse(await readFile(join(project, ".mcp.json"), "utf8"));
  assert.deepEqual(parsed.mcpServers.shibahama, server);
}
