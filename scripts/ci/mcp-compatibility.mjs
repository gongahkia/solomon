// SPDX-License-Identifier: MIT

import { spawnSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const root = resolve(dirname(new URL(import.meta.url).pathname), "../..");
const output = resolve(root, "target/mcp-compatibility.json");
const checks = [
  {
    client: "node-sdk",
    transport: "streamable-http",
    integration: "MCP client",
    command: ["node", "scripts/ci/sdk-contract.mjs"],
  },
  {
    client: "claude-code",
    transport: "stdio",
    integration: "mcpServers JSON",
    command: ["node", "scripts/ci/claude-code-mcp-fixture.mjs"],
  },
  {
    client: "codex",
    transport: "stdio",
    integration: "config.toml",
    command: ["node", "scripts/ci/codex-mcp-fixture.mjs"],
  },
  {
    client: "pi",
    transport: "stdio",
    integration: "project-local extension",
    command: [
      "npm",
      "exec",
      "--yes",
      "--package",
      "@earendil-works/pi-coding-agent@0.80.6",
      "--",
      "pi",
      "--offline",
      "--no-session",
      "--approve",
      "--no-extensions",
      "--extension",
      ".pi/extensions/shibahama-mcp.ts",
      "--list-models",
    ],
  },
  {
    client: "pi",
    transport: "stdio",
    integration: "project-local extension",
    command: ["node", "scripts/ci/pi-mcp-fixture.mjs"],
  },
];
const unsupported = [
  unsupportedEntry("claude-code", "streamable-http", "The shipped Claude Code integration defines only a stdio server."),
  unsupportedEntry("codex", "streamable-http", "The shipped Codex integration defines only a stdio server."),
  unsupportedEntry("pi", "streamable-http", "The Pi extension currently accepts only command and args stdio configuration."),
];
const results = checks.map(run);
const passed = results.every((result) => result.status === "supported");
const matrix = {
  schemaVersion: 1,
  releaseGate: { passed, requiredChecks: results.length },
  entries: [...results, ...unsupported],
};

await mkdir(dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(matrix, null, 2)}\n`);
if (!passed) process.exitCode = 1;
else process.stdout.write(`MCP compatibility matrix passed: ${output}\n`);

function run(check) {
  const [command, ...args] = check.command;
  const process = spawnSync(command, args, { cwd: root, stdio: "inherit" });
  const succeeded = process.status === 0 && !process.error;
  return {
    client: check.client,
    transport: check.transport,
    integration: check.integration,
    status: succeeded ? "supported" : "failed",
    command: check.command,
    ...(succeeded ? {} : { error: process.error?.message ?? `exit status ${process.status}` }),
  };
}

function unsupportedEntry(client, transport, reason) {
  return {
    client,
    transport,
    integration: "Shibahama shipped integration",
    status: "unsupported",
    reason,
  };
}
