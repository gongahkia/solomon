export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue };

export type CurrencyStateValue = "live" | "stale_pending" | "superseded" | "retired";
export type DependencyDirection = "upstream" | "downstream" | "both";
export type DependencySuggestionDecision = "pending" | "confirmed" | "rejected";
export type AuditPackFormat = "json" | "pdf";
export type VerificationDecision = "reaffirm" | "supersede" | "retire" | "pin";

export interface EffectiveScope {
  matter_id?: string | null;
  client_id?: string | null;
  caller_id?: string | null;
}

export interface IngestScope {
  matter_id?: string | null;
  client_id?: string | null;
  jurisdiction?: string | null;
}

export interface BoundaryMetadata {
  status: "passed" | "rejected" | "not_applicable";
  classification?: string | null;
  finding_count: number;
  context_id?: string | null;
}

export interface AuditMetadata {
  entry_id?: string | null;
  entry_hash?: string | null;
  journal_path?: string | null;
}

export interface ExcludedContextItem {
  item_id?: string | null;
  reason: string;
  code?: string | null;
}

export interface PreflightContextInput {
  query: string;
  matter_id?: string | null;
  client_id?: string | null;
  max_items?: number;
  max_context_tokens?: number | null;
  caller_id?: string | null;
}

export interface PreflightContextOutput {
  items: JsonObject[];
  excluded: ExcludedContextItem[];
  scope: EffectiveScope;
  boundary: BoundaryMetadata;
  audit?: AuditMetadata | null;
}

export interface CheckCurrencyInput {
  knowledge_item_id: string;
  as_of?: string | null;
  matter_id?: string | null;
  client_id?: string | null;
  caller_id?: string | null;
}

export interface CheckCurrencyOutput {
  knowledge_item_id: string;
  state: CurrencyStateValue;
  reasons: JsonObject[];
  last_verified_at?: string | null;
  verified_by?: string | null;
  successor_id?: string | null;
}

export interface GetDependenciesInput {
  knowledge_item_id: string;
  direction?: DependencyDirection;
  depth?: number;
  matter_id?: string | null;
  client_id?: string | null;
  caller_id?: string | null;
}

export interface GetDependenciesOutput {
  knowledge_item_id: string;
  upstream: JsonObject[];
  downstream: JsonObject[];
  truncated: boolean;
}

export interface VerifyPositionInput {
  knowledge_item_id: string;
  verifier_id: string;
  decision: VerificationDecision;
  evidence_ref: string;
  successor_id?: string | null;
  recorded_at?: string | null;
  matter_id?: string | null;
  client_id?: string | null;
  caller_id?: string | null;
}

export interface VerifyPositionOutput {
  item: JsonObject;
  currency: JsonObject;
  audit: AuditMetadata;
}

export interface IngestInput {
  text: string;
  source_ref: string;
  scope: IngestScope;
  kind?: "position" | "clause" | "house-view" | "advice" | "note";
  source_kind?: "partner" | "associate" | "matter-doc" | "external-feed" | "model";
  author?: string | null;
  caller_id?: string | null;
}

export interface IngestOutput {
  item: JsonObject;
  boundary: BoundaryMetadata;
  dependency_suggestions: JsonObject[];
  audit?: AuditMetadata | null;
}

export interface AuditPackInput {
  knowledge_item_id: string;
  format?: AuditPackFormat;
  matter_id?: string | null;
  client_id?: string | null;
  caller_id?: string | null;
}

export interface AuditPackOutput {
  knowledge_item_id: string;
  format: AuditPackFormat;
  pack: JsonObject | string;
  hash_chain: JsonObject;
}

export interface DependencySuggestionsInput {
  knowledge_item_id: string;
  decision?: DependencySuggestionDecision;
  limit?: number;
  matter_id?: string | null;
  client_id?: string | null;
  caller_id?: string | null;
}

export interface DependencySuggestionsOutput {
  suggestions: JsonObject[];
  scope: EffectiveScope;
}

export interface ImpactInput {
  external_authority_id: string;
  as_of?: string | null;
  matter_id?: string | null;
  client_id?: string | null;
  caller_id?: string | null;
}

export interface ImpactOutput {
  external_authority_id: string;
  stale_item_ids: string[];
  reasons: Record<string, JsonObject[]>;
  scope: EffectiveScope;
}

export interface HealthInput {
  caller_id?: string | null;
}

export interface HealthOutput {
  version: string;
  store: JsonObject;
  journal: JsonObject;
  boundary: JsonObject;
}

export interface SolomonClientOptions {
  endpoint?: string;
  baseUrl?: string;
  token?: string;
  fetch?: typeof fetch;
}

interface JsonRpcResponse {
  id?: string | number | null;
  result?: JsonValue;
  error?: { code?: number | string; message?: string; data?: JsonValue };
}

interface ToolResult {
  structuredContent?: JsonValue;
  content?: Array<{ type?: string; text?: string }>;
}

export class SolomonMCPError extends Error {
  constructor(
    message: string,
    readonly code?: number | string,
    readonly data?: JsonValue,
  ) {
    super(message);
    this.name = "SolomonMCPError";
  }
}

export class SolomonClient {
  readonly endpoint: string;
  private readonly token?: string;
  private readonly fetchImpl: typeof fetch;
  private nextId = 1;

  constructor(options: SolomonClientOptions = {}) {
    this.endpoint = options.endpoint ?? `${trimTrailingSlash(options.baseUrl ?? "http://127.0.0.1:8141")}/mcp`;
    this.token = options.token;
    this.fetchImpl = options.fetch ?? fetch;
  }

  health(input: HealthInput = {}): Promise<HealthOutput> {
    return this.callTool("solomon.health", input);
  }

  preflightContext(input: PreflightContextInput): Promise<PreflightContextOutput> {
    return this.callTool("solomon.preflight_context", input);
  }

  checkCurrency(input: CheckCurrencyInput): Promise<CheckCurrencyOutput> {
    return this.callTool("solomon.check_currency", input);
  }

  getDependencies(input: GetDependenciesInput): Promise<GetDependenciesOutput> {
    return this.callTool("solomon.get_dependencies", input);
  }

  verifyPosition(input: VerifyPositionInput): Promise<VerifyPositionOutput> {
    return this.callTool("solomon.verify_position", input);
  }

  ingest(input: IngestInput): Promise<IngestOutput> {
    return this.callTool("solomon.ingest", input);
  }

  auditPack(input: AuditPackInput): Promise<AuditPackOutput> {
    return this.callTool("solomon.audit_pack", input);
  }

  dependencySuggestions(input: DependencySuggestionsInput): Promise<DependencySuggestionsOutput> {
    return this.callTool("solomon.dependency_suggestions", input);
  }

  impact(input: ImpactInput): Promise<ImpactOutput> {
    return this.callTool("solomon.impact", input);
  }

  async callTool<Output>(name: string, args: object): Promise<Output> {
    const response = await this.fetchImpl(this.endpoint, {
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: this.nextId++,
        method: "tools/call",
        params: { name, arguments: args },
      }),
      headers: this.headers(),
      method: "POST",
    });
    if (!response.ok) {
      throw new SolomonMCPError(`Solomon MCP HTTP ${response.status}`, response.status, await safeText(response));
    }
    const payload = await parseJsonRpcResponse(response);
    if (payload.error) {
      throw new SolomonMCPError(payload.error.message ?? "Solomon MCP error", payload.error.code, payload.error.data);
    }
    return extractToolOutput<Output>(payload.result);
  }

  private headers(): HeadersInit {
    const headers: Record<string, string> = {
      Accept: "application/json, text/event-stream",
      "Content-Type": "application/json",
    };
    if (this.token) {
      headers.Authorization = `Bearer ${this.token}`;
    }
    return headers;
  }
}

async function parseJsonRpcResponse(response: Response): Promise<JsonRpcResponse> {
  const text = await response.text();
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream")) {
    return parseSseJsonRpc(text);
  }
  return JSON.parse(text) as JsonRpcResponse;
}

function parseSseJsonRpc(text: string): JsonRpcResponse {
  const messages: JsonRpcResponse[] = [];
  let dataLines: string[] = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trimEnd();
    if (line === "") {
      pushSseMessage(messages, dataLines);
      dataLines = [];
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }
  pushSseMessage(messages, dataLines);
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.result !== undefined || message.error !== undefined) {
      return message;
    }
  }
  throw new SolomonMCPError("Solomon MCP SSE response did not contain JSON-RPC data");
}

function pushSseMessage(messages: JsonRpcResponse[], dataLines: string[]): void {
  if (dataLines.length === 0) {
    return;
  }
  const data = dataLines.join("\n");
  if (data === "[DONE]") {
    return;
  }
  messages.push(JSON.parse(data) as JsonRpcResponse);
}

function extractToolOutput<Output>(result: JsonValue | undefined): Output {
  const toolResult = result as ToolResult | undefined;
  if (toolResult?.structuredContent !== undefined) {
    return toolResult.structuredContent as Output;
  }
  const text = toolResult?.content?.find((item) => item.type === "text" && item.text)?.text;
  if (text) {
    return JSON.parse(text) as Output;
  }
  if (result !== undefined) {
    return result as Output;
  }
  throw new SolomonMCPError("Solomon MCP response did not contain tool output");
}

async function safeText(response: Response): Promise<string> {
  try {
    return await response.text();
  } catch {
    return "";
  }
}

function trimTrailingSlash(value: string): string {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}
