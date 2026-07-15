// SPDX-License-Identifier: MIT

//! Standards-compliant Model Context Protocol stdio transport.

use serde_json::{Map, Value, json};
use shibahama_core::model::MemoryScope;
use shibahama_core::policy::PolicyActorClass;
use shibahama_core::storage::{AuthorizationPrincipalClass, RbacRole};
use std::collections::BTreeSet;
use std::io::{self, BufRead, Write};

/// Active MCP protocol revision implemented by Shibahama.
pub const PROTOCOL_VERSION: &str = "2025-11-25";
const NOT_INITIALIZED: i64 = -32002;

/// Versioned MCP memory-tool capability advertised after initialization.
pub const MEMORY_TOOLS_CAPABILITY: &str = "shibahama_memory_tools_v1";
const WRITE_REQUIRED_FIELDS: &[&str] = &[
    "content",
    "vector",
    "sourceKind",
    "validFromUnix",
    "ingestedAtUnix",
];

/// Safe application error returned inside an MCP tool result.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct McpToolError {
    code: String,
    detail: String,
    severity: &'static str,
    retryable: bool,
}

impl McpToolError {
    /// Creates content-safe error data for one failed tool call.
    #[must_use]
    pub fn new(code: impl Into<String>, detail: impl Into<String>, retryable: bool) -> Self {
        let severity = if retryable { "recoverable" } else { "fatal" };
        Self {
            code: code.into(),
            detail: detail.into(),
            severity,
            retryable,
        }
    }

    /// Creates content-safe error data with explicit core severity.
    #[must_use]
    pub fn with_severity(
        code: impl Into<String>,
        detail: impl Into<String>,
        severity: &'static str,
        retryable: bool,
    ) -> Self {
        Self {
            code: code.into(),
            detail: detail.into(),
            severity,
            retryable,
        }
    }
}

/// Backend used by a transport-neutral MCP session to execute memory tools.
pub trait McpToolBackend {
    /// Executes `name` with validated JSON object `arguments` in immutable transport `context`.
    fn call(
        &mut self,
        context: &McpServerContext,
        name: &str,
        arguments: &Map<String, Value>,
    ) -> Result<Value, McpToolError>;

    /// Lists resources visible in immutable transport `context`.
    fn list_resources(
        &mut self,
        _context: &McpServerContext,
        _cursor: Option<&str>,
    ) -> Result<Value, McpToolError> {
        Err(McpToolError::new(
            "SHIBA_UNSUPPORTED",
            "MCP resources are unavailable for this transport",
            false,
        ))
    }

    /// Reads one resource visible in immutable transport `context`.
    fn read_resource(
        &mut self,
        _context: &McpServerContext,
        _uri: &str,
    ) -> Result<Value, McpToolError> {
        Err(McpToolError::new(
            "SHIBA_UNSUPPORTED",
            "MCP resources are unavailable for this transport",
            false,
        ))
    }
}

struct UnsupportedMcpToolBackend;

impl McpToolBackend for UnsupportedMcpToolBackend {
    fn call(
        &mut self,
        _context: &McpServerContext,
        _name: &str,
        _arguments: &Map<String, Value>,
    ) -> Result<Value, McpToolError> {
        Err(McpToolError::new(
            "SHIBA_UNSUPPORTED",
            "memory tools are unavailable for this transport",
            false,
        ))
    }
}

/// Fixed principal and scope context for one MCP stdio process.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct McpServerContext {
    scope: MemoryScope,
    principal: String,
    actor: PolicyActorClass,
    credential_role: Option<RbacRole>,
    principal_class: Option<AuthorizationPrincipalClass>,
}

impl McpServerContext {
    /// Creates one immutable context that MCP messages cannot override.
    #[must_use]
    pub fn new(scope: MemoryScope, principal: String, actor: PolicyActorClass) -> Self {
        Self {
            scope,
            principal,
            actor,
            credential_role: None,
            principal_class: None,
        }
    }

    /// Creates one immutable context with a transport-authenticated credential role ceiling.
    #[must_use]
    pub fn new_with_authorization(
        scope: MemoryScope,
        principal: String,
        actor: PolicyActorClass,
        credential_role: Option<RbacRole>,
        principal_class: AuthorizationPrincipalClass,
    ) -> Self {
        Self {
            scope,
            principal,
            actor,
            credential_role,
            principal_class: Some(principal_class),
        }
    }

    /// Returns the immutable scope for the active transport session.
    #[must_use]
    pub const fn scope(&self) -> &MemoryScope {
        &self.scope
    }

    /// Returns the immutable principal identity for the active transport session.
    #[must_use]
    pub fn principal(&self) -> &str {
        &self.principal
    }

    /// Returns the authenticated actor class fixed by the transport.
    #[must_use]
    pub const fn actor(&self) -> PolicyActorClass {
        self.actor
    }

    /// Returns the credential role ceiling fixed by the transport, when any.
    #[must_use]
    pub const fn credential_role(&self) -> Option<RbacRole> {
        self.credential_role
    }

    /// Returns the authentication mechanism fixed by the transport, when available.
    #[must_use]
    pub const fn principal_class(&self) -> Option<AuthorizationPrincipalClass> {
        self.principal_class
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Lifecycle {
    Uninitialized,
    AwaitingInitialized,
    Ready,
}

/// Runs the stdio server with a backend that executes advertised memory tools.
///
/// # Errors
///
/// Returns an error when reading from standard input or writing a protocol response fails.
pub fn serve_stdio_with_backend(
    context: McpServerContext,
    backend: &mut dyn McpToolBackend,
) -> io::Result<()> {
    let stdin = io::stdin();
    let stdout = io::stdout();
    serve_stdio_io_with_backend(stdin.lock(), stdout.lock(), context, backend)
}

fn serve_stdio_io_with_backend<R: BufRead, W: Write>(
    reader: R,
    writer: W,
    context: McpServerContext,
    backend: &mut dyn McpToolBackend,
) -> io::Result<()> {
    let mut server = McpSession::new(context);
    let mut writer = writer;

    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let response = match serde_json::from_str::<Value>(&line) {
            Ok(message) => server.handle_with(message, backend),
            Err(_) => Some(protocol_error(Value::Null, -32700, "Parse error", None)),
        };
        if let Some(response) = response {
            serde_json::to_writer(&mut writer, &response)?;
            writer.write_all(b"\n")?;
            writer.flush()?;
        }
    }

    Ok(())
}

/// Stateful lifecycle dispatcher shared by MCP transports.
pub struct McpSession {
    context: McpServerContext,
    lifecycle: Lifecycle,
    used_confirmation_tokens: BTreeSet<String>,
}

impl McpSession {
    /// Creates one uninitialized MCP session with immutable transport context.
    #[must_use]
    pub fn new(context: McpServerContext) -> Self {
        Self {
            context,
            lifecycle: Lifecycle::Uninitialized,
            used_confirmation_tokens: BTreeSet::new(),
        }
    }

    /// Returns whether `context` matches the immutable session binding.
    #[must_use]
    pub fn matches_context(&self, context: &McpServerContext) -> bool {
        &self.context == context
    }

    /// Handles one JSON-RPC message and returns a response for requests only.
    #[must_use]
    pub fn handle(&mut self, message: Value) -> Option<Value> {
        let mut backend = UnsupportedMcpToolBackend;
        self.handle_with(message, &mut backend)
    }

    /// Handles one JSON-RPC message with a transport-specific memory-tool backend.
    #[must_use]
    pub fn handle_with(
        &mut self,
        message: Value,
        backend: &mut dyn McpToolBackend,
    ) -> Option<Value> {
        let Some(object) = message.as_object() else {
            return Some(protocol_error(Value::Null, -32600, "Invalid Request", None));
        };
        let id = object.get("id").cloned();
        let response_id = match id {
            Some(id) if valid_request_id(&id) => Some(id),
            Some(_) => {
                return Some(protocol_error(Value::Null, -32600, "Invalid Request", None));
            }
            None => None,
        };
        if object.get("jsonrpc") != Some(&Value::String("2.0".to_owned())) {
            return response_id.map(|id| protocol_error(id, -32600, "Invalid Request", None));
        }
        let Some(method) = object.get("method").and_then(Value::as_str) else {
            return response_id.map(|id| protocol_error(id, -32600, "Invalid Request", None));
        };
        let params = object.get("params").cloned().unwrap_or(Value::Null);

        match (method, response_id) {
            ("notifications/initialized", None) => {
                if self.lifecycle == Lifecycle::AwaitingInitialized {
                    self.lifecycle = Lifecycle::Ready;
                }
                None
            }
            ("notifications/cancelled", None) => {
                let _ = cancellation_request_id(&params);
                None
            }
            (_, None) => None,
            ("initialize", Some(id)) => Some(self.initialize(id, params)),
            ("ping", Some(id)) => Some(protocol_result(id, json!({}))),
            ("tools/list", Some(id)) => {
                if self.lifecycle == Lifecycle::Ready {
                    Some(protocol_result(id, json!({ "tools": tool_definitions() })))
                } else {
                    Some(protocol_error(
                        id,
                        NOT_INITIALIZED,
                        "Server not initialized",
                        None,
                    ))
                }
            }
            ("resources/list", Some(id)) => {
                if self.lifecycle != Lifecycle::Ready {
                    return Some(protocol_error(
                        id,
                        NOT_INITIALIZED,
                        "Server not initialized",
                        None,
                    ));
                }
                Some(self.list_resources(id, params, backend))
            }
            ("resources/read", Some(id)) => {
                if self.lifecycle != Lifecycle::Ready {
                    return Some(protocol_error(
                        id,
                        NOT_INITIALIZED,
                        "Server not initialized",
                        None,
                    ));
                }
                Some(self.read_resource(id, params, backend))
            }
            ("tools/call", Some(id)) => {
                if self.lifecycle != Lifecycle::Ready {
                    return Some(protocol_error(
                        id,
                        NOT_INITIALIZED,
                        "Server not initialized",
                        None,
                    ));
                }
                Some(self.call_tool(id, params, backend))
            }
            (_, Some(id)) if self.lifecycle != Lifecycle::Ready => Some(protocol_error(
                id,
                NOT_INITIALIZED,
                "Server not initialized",
                None,
            )),
            (_, Some(id)) => Some(protocol_error(id, -32601, "Method not found", None)),
        }
    }

    fn initialize(&mut self, id: Value, params: Value) -> Value {
        if self.lifecycle != Lifecycle::Uninitialized {
            return protocol_error(id, -32600, "Already initialized", None);
        }
        let Some(params) = params.as_object() else {
            return protocol_error(id, -32602, "Invalid params", None);
        };
        let Some(protocol_version) = params.get("protocolVersion").and_then(Value::as_str) else {
            return protocol_error(id, -32602, "Invalid params", None);
        };
        if protocol_version != PROTOCOL_VERSION {
            return protocol_error(
                id,
                -32602,
                "Unsupported protocol version",
                Some(json!({ "supported": [PROTOCOL_VERSION], "requested": protocol_version })),
            );
        }
        if !valid_initialize_params(params) {
            return protocol_error(id, -32602, "Invalid params", None);
        }

        self.lifecycle = Lifecycle::AwaitingInitialized;
        protocol_result(
            id,
            json!({
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "experimental": {
                        "shibahama": {
                            "capabilities": [MEMORY_TOOLS_CAPABILITY],
                            "principal": self.context.principal,
                            "actorClass": self.context.actor,
                            "scope": self.context.scope,
                        }
                    }
                },
                "serverInfo": {
                    "name": "shibahama",
                    "version": shibahama_core::version(),
                },
                "instructions": "Scope and principal are fixed at server startup and cannot be overridden by MCP messages.",
            }),
        )
    }

    fn call_tool(&mut self, id: Value, params: Value, backend: &mut dyn McpToolBackend) -> Value {
        let Some(params) = params.as_object() else {
            return protocol_error(id, -32602, "Invalid params", None);
        };
        let Some(name) = params.get("name").and_then(Value::as_str) else {
            return protocol_error(id, -32602, "Invalid params", None);
        };
        let Some(arguments) = params.get("arguments").and_then(Value::as_object) else {
            return protocol_error(id, -32602, "Invalid params", None);
        };
        if !tool_definitions()
            .iter()
            .any(|tool| tool.get("name").and_then(Value::as_str) == Some(name))
        {
            return protocol_error(id, -32601, "Method not found", None);
        }
        let confirmation_token = destructive_confirmation_token(name, arguments);
        if confirmation_token.is_some_and(|token| self.used_confirmation_tokens.contains(token)) {
            return protocol_result(
                id,
                tool_result(
                    json!({
                        "schemaVersion": 1,
                        "error": {
                            "code": "SHIBA_CONFIRMATION_CONSUMED",
                            "detail": "confirmation token was already consumed",
                            "severity": "fatal",
                            "retryable": false,
                        }
                    }),
                    true,
                ),
            );
        }
        match backend.call(&self.context, name, arguments) {
            Ok(structured_content) => {
                if let Some(token) = confirmation_token {
                    self.used_confirmation_tokens.insert(token.to_owned());
                }
                protocol_result(id, tool_result(structured_content, false))
            }
            Err(error) => protocol_result(
                id,
                tool_result(
                    json!({
                        "schemaVersion": 1,
                        "error": {
                            "code": error.code,
                            "detail": error.detail,
                            "severity": error.severity,
                            "retryable": error.retryable,
                        }
                    }),
                    true,
                ),
            ),
        }
    }

    fn list_resources(
        &mut self,
        id: Value,
        params: Value,
        backend: &mut dyn McpToolBackend,
    ) -> Value {
        let cursor = match params {
            Value::Null => None,
            Value::Object(params) => match params.get("cursor") {
                None => None,
                Some(Value::String(cursor)) => Some(cursor.clone()),
                Some(_) => return protocol_error(id, -32602, "Invalid params", None),
            },
            _ => return protocol_error(id, -32602, "Invalid params", None),
        };
        match backend.list_resources(&self.context, cursor.as_deref()) {
            Ok(result) => protocol_result(id, result),
            Err(error) => resource_error(id, error),
        }
    }

    fn read_resource(
        &mut self,
        id: Value,
        params: Value,
        backend: &mut dyn McpToolBackend,
    ) -> Value {
        let Some(uri) = params
            .as_object()
            .and_then(|params| params.get("uri"))
            .and_then(Value::as_str)
        else {
            return protocol_error(id, -32602, "Invalid params", None);
        };
        match backend.read_resource(&self.context, uri) {
            Ok(result) => protocol_result(id, result),
            Err(error) => resource_error(id, error),
        }
    }
}

fn destructive_confirmation_token<'a>(
    name: &str,
    arguments: &'a Map<String, Value>,
) -> Option<&'a str> {
    let destructive = matches!(
        name,
        "shibahama_memory_promote_v1" | "shibahama_memory_erase_v1"
    ) || (name == "shibahama_memory_review_v1"
        && arguments.get("operation").and_then(Value::as_str) == Some("decide"));
    destructive
        .then(|| arguments.get("confirmation"))?
        .and_then(Value::as_object)?
        .get("token")?
        .as_str()
}

/// Returns whether a JSON-RPC message is an `initialize` request.
#[must_use]
pub fn is_initialize_request(message: &Value) -> bool {
    message
        .as_object()
        .is_some_and(|object| object.get("method") == Some(&Value::String("initialize".to_owned())))
}

/// Returns the versioned memory-tool definitions advertised through `tools/list`.
#[must_use]
pub fn tool_definitions() -> Vec<Value> {
    vec![
        tool_definition(
            "shibahama_memory_write_v1",
            "Write a scoped memory with explicit actor and capture-policy metadata.",
            write_tool_properties(),
            json!({ "memory": { "type": "object" }, "policyOutcome": { "const": "allowed" } }),
            false,
            false,
            WRITE_REQUIRED_FIELDS,
        ),
        tool_definition(
            "shibahama_memory_recall_v1",
            "Recall safe current memories in the fixed session scope.",
            json!({
                "queryVector": { "type": "array", "items": { "type": "number" } },
                "topK": { "type": "integer", "minimum": 1 },
                "nowUnix": { "type": "integer" },
                "includeCold": { "type": "boolean" },
                "includeInstructions": { "type": "boolean" },
                "maxContextTokens": { "type": "integer", "minimum": 1 },
            }),
            json!({ "candidates": { "type": "array" }, "policyOutcome": { "type": "object" } }),
            true,
            false,
            &["queryVector", "topK", "nowUnix"],
        ),
        tool_definition(
            "shibahama_memory_explain_v1",
            "Explain provenance, currency, tier, and significance for one scoped memory.",
            json!({ "memoryId": { "type": "string" }, "nowUnix": { "type": "integer" } }),
            json!({ "trace": { "type": ["object", "null"] } }),
            true,
            false,
            &["memoryId", "nowUnix"],
        ),
        tool_definition(
            "shibahama_memory_timeline_v1",
            "Replay scoped memory recall at an explicit valid-time instant.",
            json!({
                "queryVector": { "type": "array", "items": { "type": "number" } },
                "topK": { "type": "integer", "minimum": 1 },
                "asOfUnix": { "type": "integer" },
            }),
            json!({ "candidates": { "type": "array" }, "policyOutcome": { "type": "object" } }),
            true,
            false,
            &["queryVector", "topK", "asOfUnix"],
        ),
        tool_definition(
            "shibahama_memory_review_v1",
            "Inspect or decide a scoped review candidate with explicit reviewer identity.",
            json!({
                "operation": { "enum": ["list", "decide"] },
                "candidateId": { "type": "string" },
                "action": { "enum": ["approve", "reject", "defer"] },
                "rationale": { "type": "string" },
                "reviewedAtUnix": { "type": "integer" },
                "confirmation": confirmation_schema(),
            }),
            json!({ "queue": { "type": "array" }, "decision": { "type": "object" } }),
            false,
            true,
            &["operation"],
        ),
        tool_definition(
            "shibahama_memory_promote_v1",
            "Copy one repository-local memory into an approved team scope.",
            json!({
                "memoryId": { "type": "string" },
                "team": { "type": "string" },
                "rationale": { "type": "string" },
                "promotedAtUnix": { "type": "integer" },
            }),
            json!({ "promotion": { "type": ["object", "null"] }, "policyOutcome": { "type": "string" } }),
            false,
            true,
            &["memoryId", "team", "rationale", "promotedAtUnix"],
        ),
        tool_definition(
            "shibahama_memory_erase_v1",
            "Soft-invalidate one scoped memory; append-only history is retained.",
            json!({ "memoryId": { "type": "string" }, "validToUnix": { "type": "integer" } }),
            json!({ "applied": { "type": "boolean" }, "effect": { "const": "soft_invalidation" } }),
            false,
            true,
            &["memoryId", "validToUnix"],
        ),
    ]
}

fn write_tool_properties() -> Value {
    json!({
        "content": { "type": "string", "minLength": 1 },
        "vector": { "type": "array", "items": { "type": "number" } },
        "sourceKind": { "enum": ["user", "agent", "file", "web", "tool"] },
        "sourceRef": { "type": ["string", "null"] },
        "validFromUnix": { "type": "integer" },
        "ingestedAtUnix": { "type": "integer" },
        "kind": { "enum": ["fact", "instruction"] },
        "indexName": { "type": "string" },
        "model": { "type": "string" },
        "modelVersion": { "type": "string" },
        "confidencePercent": { "type": "integer", "minimum": 0, "maximum": 100 },
        "captureIntent": { "enum": ["manual", "suggested", "automatic"] },
    })
}

fn tool_definition(
    name: &str,
    description: &str,
    properties: Value,
    output_properties: Value,
    read_only: bool,
    destructive: bool,
    required_tool_fields: &[&str],
) -> Value {
    let mut properties = properties.as_object().cloned().unwrap_or_default();
    properties.insert("schemaVersion".to_owned(), json!({ "const": 1 }));
    properties.insert(
        "scope".to_owned(),
        json!({
            "type": "object",
            "properties": {
                "repository": { "type": "string" },
                "team": { "type": ["string", "null"] },
                "visibility": { "enum": ["repository", "team"] },
            },
            "required": ["repository", "team", "visibility"],
            "additionalProperties": false,
        }),
    );
    if !read_only {
        properties.insert(
            "actor".to_owned(),
            json!({ "enum": ["human", "agent", "automation", "service"] }),
        );
        if destructive {
            properties.insert("confirmation".to_owned(), confirmation_schema());
        }
        properties.insert(
            "actorId".to_owned(),
            json!({ "type": "string", "minLength": 1 }),
        );
    }
    let mut required = vec![
        Value::String("schemaVersion".to_owned()),
        Value::String("scope".to_owned()),
    ];
    if !read_only {
        required.extend([
            Value::String("actor".to_owned()),
            Value::String("actorId".to_owned()),
        ]);
    }
    if destructive && name != "shibahama_memory_review_v1" {
        required.push(Value::String("confirmation".to_owned()));
    }
    required.extend(
        required_tool_fields
            .iter()
            .map(|field| Value::String((*field).to_owned())),
    );
    let confirmation_required_for = if !destructive {
        "never"
    } else if name == "shibahama_memory_review_v1" {
        "operation=decide"
    } else {
        "always"
    };
    json!({
        "name": name,
        "description": description,
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": false,
            "x-shibahama-schema-version": 1,
            "x-shibahama-capability": MEMORY_TOOLS_CAPABILITY,
            "x-shibahama-confirmation-required": destructive,
            "x-shibahama-confirmation-required-for": confirmation_required_for,
        },
        "outputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "schemaVersion": { "const": 1 },
                "result": output_properties,
            },
            "required": ["schemaVersion", "result"],
            "additionalProperties": false,
            "x-shibahama-schema-version": 1,
        },
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
        },
    })
}

fn confirmation_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "schemaVersion": { "const": 1 },
            "intent": { "enum": ["review_decision", "promotion", "erasure"] },
            "token": { "type": "string", "minLength": 16, "maxLength": 128 },
            "actorId": { "type": "string", "minLength": 1 },
            "scope": {
                "type": "object",
                "properties": {
                    "repository": { "type": "string" },
                    "team": { "type": ["string", "null"] },
                    "visibility": { "enum": ["repository", "team"] },
                },
                "required": ["repository", "team", "visibility"],
                "additionalProperties": false,
            },
            "targetId": { "type": "string", "minLength": 1 },
            "targetTeam": { "type": "string", "minLength": 1 },
            "action": { "enum": ["approve", "reject", "defer"] },
            "validToUnix": { "type": "integer" },
        },
        "required": ["schemaVersion", "intent", "token", "actorId", "scope", "targetId"],
        "additionalProperties": false,
    })
}

fn valid_request_id(id: &Value) -> bool {
    id.is_string() || id.is_i64() || id.is_u64()
}

fn valid_initialize_params(params: &Map<String, Value>) -> bool {
    params.get("capabilities").is_some_and(Value::is_object)
        && params
            .get("clientInfo")
            .and_then(Value::as_object)
            .is_some_and(|client_info| {
                client_info.get("name").is_some_and(Value::is_string)
                    && client_info.get("version").is_some_and(Value::is_string)
            })
}

fn cancellation_request_id(params: &Value) -> Option<&Value> {
    params
        .as_object()?
        .get("requestId")
        .filter(|request_id| valid_request_id(request_id))
}

fn protocol_result(id: Value, result: Value) -> Value {
    json!({ "jsonrpc": "2.0", "id": id, "result": result })
}

fn tool_result(structured_content: Value, is_error: bool) -> Value {
    let text = serde_json::to_string(&structured_content).unwrap_or_else(|_| {
        "{\"schemaVersion\":1,\"error\":{\"code\":\"SHIBA_INTERNAL\"}}".to_owned()
    });
    json!({
        "content": [{ "type": "text", "text": text }],
        "structuredContent": structured_content,
        "isError": is_error,
    })
}

fn resource_error(id: Value, error: McpToolError) -> Value {
    protocol_error(
        id,
        -32000,
        "Resource unavailable",
        Some(json!({
            "code": error.code,
            "detail": error.detail,
            "severity": error.severity,
            "retryable": error.retryable,
        })),
    )
}

fn protocol_error(id: Value, code: i64, message: &str, data: Option<Value>) -> Value {
    let mut error = Map::from_iter([
        ("code".to_owned(), Value::from(code)),
        ("message".to_owned(), Value::String(message.to_owned())),
    ]);
    if let Some(data) = data {
        error.insert("data".to_owned(), data);
    }
    json!({ "jsonrpc": "2.0", "id": id, "error": error })
}

#[cfg(test)]
mod tests {
    use super::*;
    use shibahama_core::model::{ScopeId, ScopeVisibility};

    fn context() -> McpServerContext {
        McpServerContext::new(
            MemoryScope {
                repository: ScopeId::new("repo").expect("constant scope"),
                team: Some(ScopeId::new("team").expect("constant scope")),
                visibility: ScopeVisibility::Team,
            },
            "codex".to_owned(),
            PolicyActorClass::Agent,
        )
    }

    fn initialize(id: u64) -> Value {
        json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": { "name": "test-client", "version": "1" },
            }
        })
    }

    fn responses(input: Vec<Value>) -> Vec<Value> {
        let input = input
            .into_iter()
            .map(|value| serde_json::to_string(&value).expect("request serializes"))
            .collect::<Vec<_>>()
            .join("\n");
        let mut output = Vec::new();
        let mut backend = UnsupportedMcpToolBackend;
        serve_stdio_io_with_backend(input.as_bytes(), &mut output, context(), &mut backend)
            .expect("server should run");
        String::from_utf8(output)
            .expect("output is utf-8")
            .lines()
            .map(|line| serde_json::from_str(line).expect("response is JSON"))
            .collect()
    }

    #[test]
    fn initializes_advertises_fixed_context_and_serves_tools_list() {
        let output = responses(vec![
            initialize(1),
            json!({ "jsonrpc": "2.0", "method": "notifications/initialized" }),
            json!({ "jsonrpc": "2.0", "id": 2, "method": "tools/list" }),
        ]);

        assert_eq!(output.len(), 2);
        assert_eq!(output[0]["result"]["protocolVersion"], PROTOCOL_VERSION);
        assert_eq!(output[0]["result"]["capabilities"]["tools"], json!({}));
        assert_eq!(output[0]["result"]["capabilities"]["resources"], json!({}));
        assert_eq!(
            output[0]["result"]["capabilities"]["experimental"]["shibahama"]["principal"],
            "codex"
        );
        assert_eq!(
            output[0]["result"]["capabilities"]["experimental"]["shibahama"]["actorClass"],
            "agent"
        );
        assert_eq!(
            output[0]["result"]["capabilities"]["experimental"]["shibahama"]["scope"]["repository"],
            "repo"
        );
        let tools = output[1]["result"]["tools"]
            .as_array()
            .expect("tools should be an array");
        assert_eq!(tools.len(), 7);
        assert!(tools.iter().all(|tool| {
            tool["inputSchema"]["x-shibahama-schema-version"] == 1
                && tool["outputSchema"]["x-shibahama-schema-version"] == 1
                && tool["inputSchema"]["x-shibahama-capability"] == MEMORY_TOOLS_CAPABILITY
        }));
        let write = tools
            .iter()
            .find(|tool| tool["name"] == "shibahama_memory_write_v1")
            .expect("write tool should exist");
        assert_eq!(write["annotations"]["destructiveHint"], false);
        assert_eq!(
            write["inputSchema"]["properties"]["captureIntent"],
            json!({ "enum": ["manual", "suggested", "automatic"] })
        );
        let erase = tools
            .iter()
            .find(|tool| tool["name"] == "shibahama_memory_erase_v1")
            .expect("erase tool should exist");
        assert_eq!(erase["annotations"]["destructiveHint"], true);
        assert_eq!(
            erase["inputSchema"]["x-shibahama-confirmation-required"],
            true
        );
        assert!(
            erase["inputSchema"]["required"]
                .as_array()
                .is_some_and(|fields| fields.iter().any(|field| field == "confirmation"))
        );
        let review = tools
            .iter()
            .find(|tool| tool["name"] == "shibahama_memory_review_v1")
            .expect("review tool should exist");
        assert_eq!(
            review["inputSchema"]["x-shibahama-confirmation-required-for"],
            "operation=decide"
        );
    }

    #[test]
    fn rejects_malformed_requests_and_ignores_cancellation_notifications() {
        let input = concat!(
            "{not-json}\n",
            "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}\n",
            "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"test\",\"version\":\"1\"}}}\n",
            "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"test\",\"version\":\"1\"}}}\n",
            "{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n",
            "{\"jsonrpc\":\"2.0\",\"method\":\"notifications/cancelled\",\"params\":{\"requestId\":99}}\n",
            "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"unknown\"}\n"
        );
        let mut output = Vec::new();
        let mut backend = UnsupportedMcpToolBackend;
        serve_stdio_io_with_backend(input.as_bytes(), &mut output, context(), &mut backend)
            .expect("server should run");
        let output = String::from_utf8(output).expect("output is utf-8");
        let responses = output
            .lines()
            .map(|line| serde_json::from_str::<Value>(line).expect("response is JSON"))
            .collect::<Vec<_>>();

        assert_eq!(responses.len(), 5);
        assert_eq!(responses[0]["error"]["code"], -32700);
        assert_eq!(responses[1]["error"]["code"], NOT_INITIALIZED);
        assert_eq!(responses[2]["error"]["code"], -32602);
        assert_eq!(responses[3]["result"]["protocolVersion"], PROTOCOL_VERSION);
        assert_eq!(responses[4]["error"]["code"], -32601);
    }
}
