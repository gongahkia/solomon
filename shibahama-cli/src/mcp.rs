// SPDX-License-Identifier: MIT

//! Standards-compliant Model Context Protocol stdio transport.

use serde_json::{Map, Value, json};
use shibahama_core::model::MemoryScope;
use std::io::{self, BufRead, Write};

const PROTOCOL_VERSION: &str = "2025-11-25";
const NOT_INITIALIZED: i64 = -32002;

/// Fixed principal and scope context for one MCP stdio process.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct McpServerContext {
    scope: MemoryScope,
    principal: String,
}

impl McpServerContext {
    /// Creates one immutable context that MCP messages cannot override.
    #[must_use]
    pub fn new(scope: MemoryScope, principal: String) -> Self {
        Self { scope, principal }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Lifecycle {
    Uninitialized,
    AwaitingInitialized,
    Ready,
}

/// Runs the newline-delimited JSON MCP stdio server until standard input closes.
///
/// # Errors
///
/// Returns an error when reading from standard input or writing a protocol response fails.
pub fn serve_stdio(context: McpServerContext) -> io::Result<()> {
    let stdin = io::stdin();
    let stdout = io::stdout();
    serve_stdio_io(stdin.lock(), stdout.lock(), context)
}

fn serve_stdio_io<R: BufRead, W: Write>(
    reader: R,
    writer: W,
    context: McpServerContext,
) -> io::Result<()> {
    let mut server = McpServer {
        context,
        lifecycle: Lifecycle::Uninitialized,
    };
    let mut writer = writer;

    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let response = match serde_json::from_str::<Value>(&line) {
            Ok(message) => server.handle(message),
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

struct McpServer {
    context: McpServerContext,
    lifecycle: Lifecycle,
}

impl McpServer {
    fn handle(&mut self, message: Value) -> Option<Value> {
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
                    Some(protocol_result(id, json!({ "tools": [] })))
                } else {
                    Some(protocol_error(
                        id,
                        NOT_INITIALIZED,
                        "Server not initialized",
                        None,
                    ))
                }
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
                    "experimental": {
                        "shibahama": {
                            "principal": self.context.principal,
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
        serve_stdio_io(input.as_bytes(), &mut output, context()).expect("server should run");
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
        assert_eq!(
            output[0]["result"]["capabilities"]["experimental"]["shibahama"]["principal"],
            "codex"
        );
        assert_eq!(
            output[0]["result"]["capabilities"]["experimental"]["shibahama"]["scope"]["repository"],
            "repo"
        );
        assert_eq!(output[1]["result"]["tools"], json!([]));
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
        serve_stdio_io(input.as_bytes(), &mut output, context()).expect("server should run");
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
