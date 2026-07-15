export const MCP_PROTOCOL_VERSION: "2025-11-25";
export const MCP_MEMORY_TOOL_NAMES: readonly [
  "shibahama_memory_write_v1",
  "shibahama_memory_recall_v1",
  "shibahama_memory_explain_v1",
  "shibahama_memory_timeline_v1",
  "shibahama_memory_review_v1",
  "shibahama_memory_promote_v1",
  "shibahama_memory_erase_v1",
];
export const MCP_RESOURCE_URIS: readonly [
  "shibahama://v1/policy",
  "shibahama://v1/scope",
  "shibahama://v1/audit",
  "shibahama://v1/tideline/memories",
  "shibahama://v1/tideline/events",
];

export type McpActor = "human" | "agent" | "automation" | "service";
export type McpToolName = (typeof MCP_MEMORY_TOOL_NAMES)[number];
export type McpResourceUri = (typeof MCP_RESOURCE_URIS)[number];
export type McpScope = { repository: string; team: string | null; visibility: "repository" | "team" };
export type McpConfirmation = {
  schemaVersion: 1;
  intent: "review_decision" | "promotion" | "erasure";
  token: string;
  actorId: string;
  scope: McpScope;
  targetId: string;
  targetTeam?: string;
  action?: "approve" | "reject" | "defer";
  validToUnix?: number;
};
export type McpMemoryToolArguments = {
  schemaVersion: 1;
  scope: McpScope;
  actor?: McpActor;
  actorId?: string;
  confirmation?: McpConfirmation;
  [key: string]: unknown;
};
export type McpClientInfo = { name: string; version: string };
export type McpResource = { uri: string; name: string; description?: string; mimeType?: string };
export type McpRequestTransport = { request(message: unknown): Promise<unknown>; close?(): Promise<void> | void };

export class ShibahamaMcpError extends Error {
  code: string;
  detail: string;
  severity: "recoverable" | "fatal";
  retryable: boolean;
}

export class StdioMcpTransport implements McpRequestTransport {
  constructor(config: { command: string; args?: string[]; env?: Record<string, string | undefined>; cwd?: string });
  request(message: unknown): Promise<unknown>;
  close(): Promise<void>;
}

export class StreamableHttpMcpTransport implements McpRequestTransport {
  constructor(config: {
    url: string;
    apiKey?: string;
    namespace?: string;
    scope?: Pick<McpScope, "visibility" | "team">;
    headers?: Record<string, string>;
    fetch?: typeof globalThis.fetch;
  });
  request(message: unknown): Promise<unknown>;
  close(): Promise<void>;
}

export class ShibahamaMcpClient {
  server: unknown;
  static connectStdio(config: ConstructorParameters<typeof StdioMcpTransport>[0] & { clientInfo?: McpClientInfo }): Promise<ShibahamaMcpClient>;
  static connectHttp(config: ConstructorParameters<typeof StreamableHttpMcpTransport>[0] & { clientInfo?: McpClientInfo }): Promise<ShibahamaMcpClient>;
  static connect(transport: McpRequestTransport, clientInfo?: McpClientInfo): Promise<ShibahamaMcpClient>;
  listTools(): Promise<Array<{ name: McpToolName; inputSchema: object; outputSchema: object }>>;
  listResources(cursor?: string): Promise<{ resources: McpResource[]; nextCursor?: string }>;
  readResource(uri: string): Promise<{ contents: Array<{ uri: string; mimeType?: string; text?: string }> }>;
  callTool(name: McpToolName, arguments_: McpMemoryToolArguments): Promise<{ schemaVersion: 1; result: Record<string, unknown> }>;
  write(arguments_: McpMemoryToolArguments): ReturnType<ShibahamaMcpClient["callTool"]>;
  recall(arguments_: McpMemoryToolArguments): ReturnType<ShibahamaMcpClient["callTool"]>;
  explain(arguments_: McpMemoryToolArguments): ReturnType<ShibahamaMcpClient["callTool"]>;
  timeline(arguments_: McpMemoryToolArguments): ReturnType<ShibahamaMcpClient["callTool"]>;
  review(arguments_: McpMemoryToolArguments): ReturnType<ShibahamaMcpClient["callTool"]>;
  promote(arguments_: McpMemoryToolArguments): ReturnType<ShibahamaMcpClient["callTool"]>;
  erase(arguments_: McpMemoryToolArguments): ReturnType<ShibahamaMcpClient["callTool"]>;
  close(): Promise<void> | void;
}
