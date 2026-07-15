// SPDX-License-Identifier: MIT

import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

export const MCP_PROTOCOL_VERSION = "2025-11-25";
export const MCP_MEMORY_TOOL_NAMES = Object.freeze([
  "shibahama_memory_write_v1",
  "shibahama_memory_recall_v1",
  "shibahama_memory_explain_v1",
  "shibahama_memory_timeline_v1",
  "shibahama_memory_review_v1",
  "shibahama_memory_promote_v1",
  "shibahama_memory_erase_v1",
]);
export const MCP_RESOURCE_URIS = Object.freeze([
  "shibahama://v1/policy",
  "shibahama://v1/scope",
  "shibahama://v1/audit",
  "shibahama://v1/tideline/memories",
  "shibahama://v1/tideline/events",
]);

export class ShibahamaMcpError extends Error {
  constructor({ code = "SHIBA_TRANSPORT", detail = "MCP transport failed", severity, retryable = true }) {
    super(detail);
    this.name = "ShibahamaMcpError";
    this.code = code;
    this.detail = detail;
    this.severity = severity ?? (retryable ? "recoverable" : "fatal");
    this.retryable = retryable;
  }
}

export class StdioMcpTransport {
  constructor({ command, args = [], env, cwd }) {
    this.child = spawn(command, args, {
      cwd,
      env: env ? { ...process.env, ...env } : process.env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.pending = new Map();
    this.stderr = "";
    createInterface({ input: this.child.stdout }).on("line", (line) => this.#receive(line));
    createInterface({ input: this.child.stderr }).on("line", (line) => {
      this.stderr = `${this.stderr}${line}\n`.slice(-8192);
    });
    this.child.on("error", (error) => this.#failAll(error));
    this.child.on("exit", (code) => {
      if (code !== 0) this.#failAll(new Error(`stdio MCP process exited with code ${code}`));
    });
  }

  request(message) {
    if (!this.child.stdin.writable) {
      return Promise.reject(new ShibahamaMcpError({ retryable: true }));
    }
    if (message.id === undefined) {
      this.child.stdin.write(`${JSON.stringify(message)}\n`);
      return Promise.resolve(undefined);
    }
    return new Promise((resolve, reject) => {
      this.pending.set(String(message.id), { resolve, reject });
      this.child.stdin.write(`${JSON.stringify(message)}\n`, (error) => {
        if (error) this.#fail(String(message.id), error);
      });
    });
  }

  async close() {
    if (!this.child.killed) this.child.kill("SIGTERM");
  }

  #receive(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      this.#failAll(new Error("stdio MCP server emitted invalid JSON"));
      return;
    }
    if (message.id === undefined) return;
    const pending = this.pending.get(String(message.id));
    if (!pending) return;
    this.pending.delete(String(message.id));
    pending.resolve(message);
  }

  #fail(id, error) {
    const pending = this.pending.get(id);
    if (!pending) return;
    this.pending.delete(id);
    pending.reject(new ShibahamaMcpError({ detail: error.message, retryable: true }));
  }

  #failAll(error) {
    for (const id of this.pending.keys()) this.#fail(id, error);
  }
}

export class StreamableHttpMcpTransport {
  constructor({ url, apiKey, namespace, scope, headers = {}, fetch: fetchImpl = globalThis.fetch }) {
    if (typeof fetchImpl !== "function") throw new TypeError("a fetch implementation is required");
    this.url = url;
    this.fetch = fetchImpl;
    this.sessionId = undefined;
    this.headers = {
      accept: "application/json, text/event-stream",
      "content-type": "application/json",
      ...headers,
    };
    if (apiKey) this.headers["x-api-key"] = apiKey;
    if (namespace) this.headers["x-shibahama-namespace"] = namespace;
    if (scope?.visibility) this.headers["x-shibahama-scope-visibility"] = scope.visibility;
    if (scope?.team) this.headers["x-shibahama-scope-team"] = scope.team;
  }

  async request(message) {
    const headers = { ...this.headers };
    if (this.sessionId) {
      headers["mcp-session-id"] = this.sessionId;
      headers["mcp-protocol-version"] = MCP_PROTOCOL_VERSION;
    }
    let response;
    try {
      response = await this.fetch(this.url, { method: "POST", headers, body: JSON.stringify(message) });
    } catch (error) {
      throw new ShibahamaMcpError({ detail: error instanceof Error ? error.message : "HTTP MCP request failed", retryable: true });
    }
    const payload = await response.json().catch(() => undefined);
    if (!response.ok) throw httpError(payload, response.status);
    const sessionId = response.headers.get("mcp-session-id");
    if (sessionId) this.sessionId = sessionId;
    return payload;
  }

  async close() {
    if (!this.sessionId) return;
    await this.fetch(this.url, {
      method: "DELETE",
      headers: {
        ...this.headers,
        "mcp-session-id": this.sessionId,
        "mcp-protocol-version": MCP_PROTOCOL_VERSION,
      },
    });
    this.sessionId = undefined;
  }
}

export class ShibahamaMcpClient {
  constructor(transport) {
    this.transport = transport;
    this.nextId = 1;
    this.server = undefined;
  }

  static async connectStdio(config) {
    return ShibahamaMcpClient.connect(new StdioMcpTransport(config), config.clientInfo);
  }

  static async connectHttp(config) {
    return ShibahamaMcpClient.connect(new StreamableHttpMcpTransport(config), config.clientInfo);
  }

  static async connect(transport, clientInfo = { name: "shibahama-node", version: "0.1.0" }) {
    const client = new ShibahamaMcpClient(transport);
    client.server = await client.request("initialize", {
      protocolVersion: MCP_PROTOCOL_VERSION,
      capabilities: {},
      clientInfo,
    });
    await transport.request({ jsonrpc: "2.0", method: "notifications/initialized" });
    return client;
  }

  async request(method, params) {
    const id = this.nextId++;
    const response = await this.transport.request({ jsonrpc: "2.0", id, method, params });
    if (!response || response.id !== id) throw new ShibahamaMcpError({ detail: "MCP response id mismatch", retryable: true });
    if (response.error) throw rpcError(response.error);
    return response.result;
  }

  listTools() { return this.request("tools/list").then((result) => result.tools); }
  listResources(cursor) { return this.request("resources/list", cursor ? { cursor } : undefined); }
  readResource(uri) { return this.request("resources/read", { uri }); }

  async callTool(name, arguments_) {
    const result = await this.request("tools/call", { name, arguments: arguments_ });
    if (result.isError) throw toolError(result.structuredContent);
    return result.structuredContent;
  }

  write(arguments_) { return this.callTool("shibahama_memory_write_v1", arguments_); }
  recall(arguments_) { return this.callTool("shibahama_memory_recall_v1", arguments_); }
  explain(arguments_) { return this.callTool("shibahama_memory_explain_v1", arguments_); }
  timeline(arguments_) { return this.callTool("shibahama_memory_timeline_v1", arguments_); }
  review(arguments_) { return this.callTool("shibahama_memory_review_v1", arguments_); }
  promote(arguments_) { return this.callTool("shibahama_memory_promote_v1", arguments_); }
  erase(arguments_) { return this.callTool("shibahama_memory_erase_v1", arguments_); }
  close() { return this.transport.close?.(); }
}

function toolError(content) {
  const error = content?.error ?? {};
  return new ShibahamaMcpError({ code: error.code, detail: error.detail, severity: error.severity, retryable: error.retryable });
}

function rpcError(error) {
  const metadata = error?.data ?? {};
  return new ShibahamaMcpError({ code: metadata.code ?? "SHIBA_RPC", detail: metadata.detail ?? error?.message, severity: metadata.severity, retryable: metadata.retryable ?? false });
}

function httpError(payload, status) {
  return new ShibahamaMcpError({
    code: payload?.code ?? "SHIBA_HTTP",
    detail: payload?.detail ?? `HTTP MCP request failed with status ${status}`,
    severity: payload?.severity,
    retryable: payload?.retryable ?? status >= 500,
  });
}
