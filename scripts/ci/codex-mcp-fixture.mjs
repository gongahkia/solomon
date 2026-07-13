// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFile, mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ShibahamaMcpClient } from "../../bindings/node/mcp-client.mjs";

const root = new URL("../..", import.meta.url).pathname;
const configPath = new URL("../../integrations/codex/config.toml", import.meta.url);
const dir = await mkdtemp(join(tmpdir(), "shibahama-codex-"));

try {
  const config = parseConfig(await readFile(configPath, "utf8"));
  assert.equal(config.command, "cargo");
  assert.doesNotMatch(config.source, /(?:api[_-]?key|authorization|secret|token)\s*=/i);
  await validateCodexConfig();
  const scope = { repository: "codex-fixture", team: null, visibility: "repository" };
  const args = replaceConfigValues(config.args, join(dir, "codex.redb"), scope.repository);
  const client = await ShibahamaMcpClient.connectStdio({
    command: config.command,
    args,
    cwd: root,
    clientInfo: { name: "codex-fixture", version: "1" },
  });
  const written = await client.write({
    schemaVersion: 1,
    scope,
    actor: "human",
    actorId: "codex",
    content: "Codex fixture explicit capture",
    vector: [1, 0],
    sourceKind: "user",
    validFromUnix: 0,
    ingestedAtUnix: 0,
  });
  const memoryId = written.result.memory.id;
  const recalled = await client.recall({ schemaVersion: 1, scope, queryVector: [1, 0], topK: 1, nowUnix: 0 });
  assert.equal(recalled.result.candidates[0].id, memoryId);
  const review = await client.review({ schemaVersion: 1, scope, actor: "human", actorId: "codex", operation: "list" });
  assert.deepEqual(review.result.queue, []);
  const timeline = await client.timeline({ schemaVersion: 1, scope, queryVector: [1, 0], topK: 1, asOfUnix: 0 });
  assert.equal(timeline.result.candidates[0].id, memoryId);

  await assert.rejects(
    client.write({
      schemaVersion: 1,
      scope,
      actor: "agent",
      actorId: "codex",
      content: "forged actor must reject",
      vector: [1, 0],
      sourceKind: "user",
      validFromUnix: 0,
      ingestedAtUnix: 0,
    }),
    (error) => error.code === "SHIBA_UNAUTHORIZED",
  );
  await client.close();
} finally {
  await rm(dir, { force: true, recursive: true });
}

console.log("Codex MCP fixture passed");

function parseConfig(source) {
  assert.match(source, /^\[mcp_servers\.shibahama\]$/m);
  const command = source.match(/^command\s*=\s*"([^"]+)"$/m)?.[1];
  const args = source.match(/^args\s*=\s*(\[[\s\S]*?^\])$/m)?.[1];
  if (!command || !args) throw new Error("invalid Codex MCP configuration");
  return { command, args: JSON.parse(args), source };
}

function replaceConfigValues(args, path, repository) {
  const resolved = [...args];
  resolved[resolved.indexOf("--path") + 1] = path;
  resolved[resolved.indexOf("--scope-repository") + 1] = repository;
  return resolved;
}

async function validateCodexConfig() {
  const executable = process.env.CODEX_BIN ?? "codex";
  const version = spawnSync(executable, ["--version"], { encoding: "utf8" });
  if (version.error?.code === "ENOENT") {
    console.log("Codex CLI validation skipped: codex is unavailable");
    return;
  }
  assert.equal(version.status, 0, version.stderr);
  const home = join(dir, "codex-home");
  await mkdir(home);
  await copyFile(configPath, join(home, "config.toml"));
  const parsed = spawnSync(executable, ["mcp", "get", "shibahama", "--json"], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, CODEX_HOME: home },
  });
  assert.equal(parsed.status, 0, parsed.stderr);
  const config = JSON.parse(parsed.stdout);
  assert.equal(config.transport?.command, "cargo", JSON.stringify(config));
  assert.ok(config.transport?.args.includes("shibahama-cli"));
}
