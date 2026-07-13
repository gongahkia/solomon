// SPDX-License-Identifier: MIT

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ShibahamaMcpClient } from "../../bindings/node/mcp-client.mjs";

const SERVER_NAME = "shibahama";
const TOOL_PREFIX = "shibahama_memory_";

export function registerPiShibahama(pi, { Type, cwd = process.cwd(), configPath } = {}) {
  if (!pi?.registerTool || !pi?.on || !Type) throw new TypeError("Pi extension API and TypeBox are required");
  const server = loadServerConfig(configPath ?? resolve(cwd, ".pi/mcp.json"));
  let connection;

  const connect = async () => {
    if (!connection) {
      connection = ShibahamaMcpClient.connectStdio({
        ...server,
        clientInfo: { name: "shibahama-pi", version: "0.1.0" },
      }).then((client) => ({ client, identity: serverIdentity(client.server) }));
    }
    return connection;
  };
  const call = (name, mutation, buildArguments) => async (_toolCallId, parameters, signal) => {
    if (signal?.aborted) throw new Error("Shibahama operation cancelled");
    const { client, identity } = await connect();
    if (signal?.aborted) throw new Error("Shibahama operation cancelled");
    const arguments_ = {
      schemaVersion: 1,
      scope: identity.scope,
      ...(mutation ? { actor: identity.actor, actorId: identity.actorId } : {}),
      ...buildArguments(parameters),
    };
    const result = await client.callTool(`${TOOL_PREFIX}${name}_v1`, arguments_);
    return toolResult(result);
  };

  pi.registerTool(tool(Type, "write", "Write Memory", "Store an explicit scoped memory.", Type.Object({
    content: Type.String({ minLength: 1 }),
    vector: vectorSchema(Type),
    sourceKind: Type.Union([Type.Literal("user"), Type.Literal("agent"), Type.Literal("file"), Type.Literal("web"), Type.Literal("tool")]),
    sourceRef: Type.Optional(Type.String()),
    validFromUnix: Type.Integer(),
    ingestedAtUnix: Type.Integer(),
    kind: Type.Optional(Type.Union([Type.Literal("fact"), Type.Literal("instruction")])),
    indexName: Type.Optional(Type.String()),
    model: Type.Optional(Type.String()),
    modelVersion: Type.Optional(Type.String()),
    confidencePercent: Type.Optional(Type.Integer({ minimum: 0, maximum: 100 })),
    captureIntent: Type.Optional(Type.Union([Type.Literal("manual"), Type.Literal("suggested"), Type.Literal("automatic")])),
  }, { additionalProperties: false }), true, (parameters) => parameters, call));
  pi.registerTool(tool(Type, "recall", "Recall Memory", "Recall safe current memories from the fixed scope.", Type.Object({
    queryVector: vectorSchema(Type),
    topK: Type.Integer({ minimum: 1 }),
    nowUnix: Type.Integer(),
    includeCold: Type.Optional(Type.Boolean()),
    includeInstructions: Type.Optional(Type.Boolean()),
    maxContextTokens: Type.Optional(Type.Integer({ minimum: 1 })),
  }, { additionalProperties: false }), false, (parameters) => parameters, call));
  pi.registerTool(tool(Type, "explain", "Explain Memory", "Explain provenance and lifecycle for one scoped memory.", Type.Object({
    memoryId: Type.String(),
    nowUnix: Type.Integer(),
  }, { additionalProperties: false }), false, (parameters) => parameters, call));
  pi.registerTool(tool(Type, "timeline", "Memory Timeline", "Replay scoped memory recall at a valid-time instant.", Type.Object({
    queryVector: vectorSchema(Type),
    topK: Type.Integer({ minimum: 1 }),
    asOfUnix: Type.Integer(),
  }, { additionalProperties: false }), false, (parameters) => parameters, call));
  pi.registerTool(tool(Type, "review", "Review Memory", "Inspect or decide review candidates; a decision requires an explicit confirmation object.", Type.Object({
    operation: Type.Union([Type.Literal("list"), Type.Literal("decide")]),
    candidateId: Type.Optional(Type.String()),
    action: Type.Optional(Type.Union([Type.Literal("approve"), Type.Literal("reject"), Type.Literal("defer")])),
    rationale: Type.Optional(Type.String()),
    reviewedAtUnix: Type.Optional(Type.Integer()),
    confirmation: Type.Optional(confirmationSchema(Type)),
  }, { additionalProperties: false }), true, (parameters) => parameters, call));
  pi.registerTool(tool(Type, "promote", "Promote Memory", "Promote one memory after explicit confirmation.", Type.Object({
    memoryId: Type.String(),
    team: Type.String(),
    rationale: Type.String(),
    promotedAtUnix: Type.Integer(),
    confirmation: confirmationSchema(Type),
  }, { additionalProperties: false }), true, (parameters) => parameters, call));
  pi.registerTool(tool(Type, "erase", "Erase Memory", "Soft-invalidate one memory after explicit confirmation.", Type.Object({
    memoryId: Type.String(),
    validToUnix: Type.Integer(),
    confirmation: confirmationSchema(Type),
  }, { additionalProperties: false }), true, (parameters) => parameters, call));

  pi.on("session_shutdown", async () => {
    if (!connection) return;
    const { client } = await connection;
    await client.close();
  });
}

function tool(Type, name, label, description, parameters, mutation, buildArguments, call) {
  return {
    name: `${TOOL_PREFIX}${name}`,
    label,
    description,
    promptSnippet: description,
    promptGuidelines: [`Use ${TOOL_PREFIX}${name} only for scoped Shibahama memory operations.`],
    parameters,
    execute: call(name, mutation, buildArguments),
  };
}

function vectorSchema(Type) {
  return Type.Array(Type.Number(), { minItems: 1 });
}

function confirmationSchema(Type) {
  return Type.Object({
    schemaVersion: Type.Literal(1),
    intent: Type.Union([Type.Literal("review_decision"), Type.Literal("promotion"), Type.Literal("erasure")]),
    token: Type.String({ minLength: 16, maxLength: 128 }),
    actorId: Type.String({ minLength: 1 }),
    scope: Type.Object({
      repository: Type.String(),
      team: Type.Union([Type.String(), Type.Null()]),
      visibility: Type.Union([Type.Literal("repository"), Type.Literal("team")]),
    }),
    targetId: Type.String({ minLength: 1 }),
    targetTeam: Type.Optional(Type.String({ minLength: 1 })),
    action: Type.Optional(Type.Union([Type.Literal("approve"), Type.Literal("reject"), Type.Literal("defer")])),
    validToUnix: Type.Optional(Type.Integer()),
  }, { additionalProperties: false });
}

function loadServerConfig(configPath) {
  let config;
  try {
    config = JSON.parse(readFileSync(configPath, "utf8"));
  } catch (error) {
    throw new Error(`Cannot load Pi MCP config at ${configPath}: ${error instanceof Error ? error.message : "invalid JSON"}`);
  }
  const server = config?.mcpServers?.[SERVER_NAME];
  if (!server || typeof server !== "object" || Array.isArray(server)) {
    throw new Error(`Pi MCP config must define mcpServers.${SERVER_NAME}`);
  }
  if (typeof server.command !== "string" || server.command.length === 0) {
    throw new Error(`Pi MCP server ${SERVER_NAME} requires a command`);
  }
  if (!Array.isArray(server.args) || !server.args.every((argument) => typeof argument === "string")) {
    throw new Error(`Pi MCP server ${SERVER_NAME} requires string args`);
  }
  if (server.cwd !== undefined && typeof server.cwd !== "string") {
    throw new Error(`Pi MCP server ${SERVER_NAME} cwd must be a string`);
  }
  if (server.env !== undefined && (!server.env || typeof server.env !== "object" || Array.isArray(server.env)
    || !Object.values(server.env).every((value) => typeof value === "string"))) {
    throw new Error(`Pi MCP server ${SERVER_NAME} env values must be strings`);
  }
  return { command: server.command, args: server.args, cwd: server.cwd, env: server.env };
}

function serverIdentity(server) {
  const capability = server?.capabilities?.experimental?.shibahama;
  const scope = capability?.scope;
  if (!scope || typeof scope.repository !== "string" || !["repository", "team"].includes(scope.visibility)
    || !["human", "agent", "automation", "service"].includes(capability?.actorClass)
    || typeof capability.principal !== "string" || capability.principal.length === 0) {
    throw new Error("Shibahama MCP server did not provide a valid fixed scope and identity");
  }
  return { scope, actor: capability.actorClass, actorId: capability.principal };
}

function toolResult(result) {
  return {
    content: [{ type: "text", text: JSON.stringify(result) }],
    details: result,
  };
}
