// SPDX-License-Identifier: MIT

//! Scope-authorized, versioned MCP resource pages.

use crate::mcp::{McpServerContext, McpToolError};
use crate::{MemoryItemDto, event_kind, event_memory_ids};
use serde_json::{Value, json};
use shibahama_core::api::{ForgettingMode, ScopeMode, Shibahama, ShibahamaError};
use shibahama_core::model::{MemoryId, MemoryScope};
use shibahama_core::policy::PolicyLayerSet;
use shibahama_core::storage::EventRecord;
use shibahama_core::vector::HnswVectorIndex;

const RESOURCE_ROOT: &str = "shibahama://v1/";
const POLICY_URI: &str = "shibahama://v1/policy";
const SCOPE_URI: &str = "shibahama://v1/scope";
const AUDIT_URI: &str = "shibahama://v1/audit";
const TIDELINE_MEMORIES_URI: &str = "shibahama://v1/tideline/memories";
const TIDELINE_EVENTS_URI: &str = "shibahama://v1/tideline/events";
const RESOURCE_PAGE_SIZE: usize = 50;
const RESOURCE_MEMORY_CONTENT_BYTES: usize = 2_048;
const RESOURCE_PROVENANCE_TEXT_BYTES: usize = 512;
const RESOURCE_EVENT_MEMORY_IDS: usize = 64;

enum ResourceTarget {
    Policy,
    Scope,
    Audit(Option<u64>),
    TidelineMemories(Option<MemoryId>),
    TidelineEvents(Option<u64>),
}

/// Lists the stable resources visible in `context`.
pub(super) fn list_resources(
    _context: &McpServerContext,
    cursor: Option<&str>,
) -> Result<Value, McpToolError> {
    if cursor.is_some() {
        return Err(invalid_request());
    }
    Ok(json!({
        "resources": [
            resource(POLICY_URI, "shibahama policy", "Versioned capture and recall policy for the fixed scope."),
            resource(SCOPE_URI, "shibahama scope", "Immutable MCP principal and authorized memory scope."),
            resource(AUDIT_URI, "shibahama audit", "Content-safe audit summary page; at most 50 records."),
            resource(TIDELINE_MEMORIES_URI, "Tideline memories", "Bounded Tideline recording memory page; at most 50 records."),
            resource(TIDELINE_EVENTS_URI, "Tideline events", "Content-safe Tideline recording event page; at most 50 records."),
        ],
        "_meta": { "x-shibahama-schema-version": 1 },
    }))
}

/// Reads one stable resource using only the immutable transport scope.
pub(super) fn read_resource(
    engine: &Shibahama<HnswVectorIndex>,
    context: &McpServerContext,
    uri: &str,
) -> Result<Value, McpToolError> {
    match parse_resource_uri(uri)? {
        ResourceTarget::Policy => policy_resource(engine, context, uri),
        ResourceTarget::Scope => scope_resource(context, uri),
        ResourceTarget::Audit(after) => audit_resource(engine, context, uri, after),
        ResourceTarget::TidelineMemories(after) => {
            tideline_memories_resource(engine, context, uri, after)
        }
        ResourceTarget::TidelineEvents(after) => {
            tideline_events_resource(engine, context, uri, after)
        }
    }
}

fn resource(uri: &str, name: &str, description: &str) -> Value {
    json!({
        "uri": uri,
        "name": name,
        "description": description,
        "mimeType": "application/json",
        "_meta": { "x-shibahama-schema-version": 1 },
    })
}

fn policy_resource(
    engine: &Shibahama<HnswVectorIndex>,
    context: &McpServerContext,
    uri: &str,
) -> Result<Value, McpToolError> {
    let config = engine.config();
    contents(
        uri,
        json!({
            "schemaVersion": 1,
            "scope": context.scope(),
            "scopeMode": scope_mode(config.scope_mode),
            "automaticCaptureEnabled": config.automatic_capture_enabled,
            "capturePolicy": config.capture_policy,
            "recallPolicy": config.recall_policy,
            "effectivePolicy": engine.effective_policy(&PolicyLayerSet::default()),
            "forgettingMode": forgetting_mode(config.forgetting.mode),
        }),
    )
}

fn scope_resource(context: &McpServerContext, uri: &str) -> Result<Value, McpToolError> {
    contents(
        uri,
        json!({
            "schemaVersion": 1,
            "scope": context.scope(),
            "principal": context.principal(),
            "actorClass": context.actor(),
        }),
    )
}

fn audit_resource(
    engine: &Shibahama<HnswVectorIndex>,
    context: &McpServerContext,
    uri: &str,
    after: Option<u64>,
) -> Result<Value, McpToolError> {
    let page = event_page(engine, context.scope(), after)?;
    let next_cursor = page.next_cursor;
    let entries = page
        .records
        .into_iter()
        .map(audit_summary)
        .collect::<Vec<_>>();
    contents(
        uri,
        json!({
            "schemaVersion": 1,
            "scope": context.scope(),
            "auditEvents": entries,
            "nextCursor": next_cursor,
            "nextUri": next_cursor.map(|cursor| format!("{AUDIT_URI}?after={cursor}")),
        }),
    )
}

fn tideline_memories_resource(
    engine: &Shibahama<HnswVectorIndex>,
    context: &McpServerContext,
    uri: &str,
    after: Option<MemoryId>,
) -> Result<Value, McpToolError> {
    let mut memories = engine
        .store()
        .memory_items_in_scope(context.scope())
        .map_err(|error| core_error(error.into()))?;
    memories.sort_by_key(|item| item.id);
    let mut records = memories
        .into_iter()
        .filter(|item| after.is_none_or(|cursor| item.id > cursor))
        .take(RESOURCE_PAGE_SIZE + 1)
        .collect::<Vec<_>>();
    let next_cursor = if records.len() > RESOURCE_PAGE_SIZE {
        let cursor = records[RESOURCE_PAGE_SIZE - 1].id;
        records.truncate(RESOURCE_PAGE_SIZE);
        Some(cursor)
    } else {
        None
    };
    contents(
        uri,
        json!({
            "schemaVersion": 1,
            "scope": context.scope(),
            "memories": records.into_iter().map(tideline_memory).collect::<Result<Vec<_>, _>>()?,
            "nextCursor": next_cursor.map(|cursor| cursor.to_string()),
            "nextUri": next_cursor.map(|cursor| format!("{TIDELINE_MEMORIES_URI}?after={cursor}")),
        }),
    )
}

fn tideline_events_resource(
    engine: &Shibahama<HnswVectorIndex>,
    context: &McpServerContext,
    uri: &str,
    after: Option<u64>,
) -> Result<Value, McpToolError> {
    let page = event_page(engine, context.scope(), after)?;
    let next_cursor = page.next_cursor;
    let events = page
        .records
        .into_iter()
        .map(audit_summary)
        .collect::<Vec<_>>();
    contents(
        uri,
        json!({
            "schemaVersion": 1,
            "scope": context.scope(),
            "events": events,
            "nextCursor": next_cursor,
            "nextUri": next_cursor.map(|cursor| format!("{TIDELINE_EVENTS_URI}?after={cursor}")),
        }),
    )
}

struct EventPage {
    records: Vec<EventRecord>,
    next_cursor: Option<u64>,
}

fn event_page(
    engine: &Shibahama<HnswVectorIndex>,
    scope: &MemoryScope,
    after: Option<u64>,
) -> Result<EventPage, McpToolError> {
    let mut records = engine
        .store()
        .events_in_scope(scope)
        .map_err(|error| core_error(error.into()))?;
    records.sort_by_key(|record| record.sequence);
    let mut records = records
        .into_iter()
        .filter(|record| after.is_none_or(|cursor| record.sequence > cursor))
        .take(RESOURCE_PAGE_SIZE + 1)
        .collect::<Vec<_>>();
    let next_cursor = if records.len() > RESOURCE_PAGE_SIZE {
        let cursor = records[RESOURCE_PAGE_SIZE - 1].sequence;
        records.truncate(RESOURCE_PAGE_SIZE);
        Some(cursor)
    } else {
        None
    };
    Ok(EventPage {
        records,
        next_cursor,
    })
}

fn audit_summary(record: EventRecord) -> Value {
    let mut memory_ids = event_memory_ids(&record.event);
    let memory_ids_truncated = memory_ids.len() > RESOURCE_EVENT_MEMORY_IDS;
    memory_ids.truncate(RESOURCE_EVENT_MEMORY_IDS);
    json!({
        "sequence": record.sequence,
        "recordedAtUnix": record.recorded_at.unix_timestamp(),
        "kind": event_kind(&record.event),
        "memoryIds": memory_ids,
        "memoryIdsTruncated": memory_ids_truncated,
    })
}

fn tideline_memory(item: shibahama_core::model::MemoryItem) -> Result<Value, McpToolError> {
    let mut memory =
        serde_json::to_value(MemoryItemDto::from(item)).map_err(|_| internal_error())?;
    let mut content_truncated = truncate_string(
        memory.get_mut("content").ok_or_else(internal_error)?,
        RESOURCE_MEMORY_CONTENT_BYTES,
    );
    let provenance = memory
        .get_mut("provenance")
        .and_then(Value::as_object_mut)
        .ok_or_else(internal_error)?;
    content_truncated |= truncate_string(
        provenance
            .get_mut("source_ref")
            .ok_or_else(internal_error)?,
        RESOURCE_PROVENANCE_TEXT_BYTES,
    );
    content_truncated |= truncate_string(
        provenance
            .get_mut("ingested_by")
            .ok_or_else(internal_error)?,
        RESOURCE_PROVENANCE_TEXT_BYTES,
    );
    if content_truncated {
        memory
            .as_object_mut()
            .ok_or_else(internal_error)?
            .insert("content_truncated".to_owned(), Value::Bool(true));
    }
    Ok(memory)
}

fn truncate_string(value: &mut Value, maximum_bytes: usize) -> bool {
    let Some(text) = value.as_str() else {
        return false;
    };
    if text.len() <= maximum_bytes {
        return false;
    }
    let mut end = maximum_bytes.saturating_sub(3);
    while end > 0 && !text.is_char_boundary(end) {
        end -= 1;
    }
    *value = Value::String(format!("{}...", &text[..end]));
    true
}

fn contents(uri: &str, document: Value) -> Result<Value, McpToolError> {
    let text = serde_json::to_string(&document).map_err(|_| internal_error())?;
    Ok(json!({
        "contents": [{
            "uri": uri,
            "mimeType": "application/json",
            "text": text,
        }],
    }))
}

fn parse_resource_uri(uri: &str) -> Result<ResourceTarget, McpToolError> {
    let Some(path_and_query) = uri.strip_prefix(RESOURCE_ROOT) else {
        return Err(invalid_request());
    };
    let (path, query) = path_and_query
        .split_once('?')
        .map_or((path_and_query, None), |(path, query)| (path, Some(query)));
    match path {
        "policy" if query.is_none() => Ok(ResourceTarget::Policy),
        "scope" if query.is_none() => Ok(ResourceTarget::Scope),
        "audit" => parse_event_target(query).map(ResourceTarget::Audit),
        "tideline/memories" => parse_memory_target(query).map(ResourceTarget::TidelineMemories),
        "tideline/events" => parse_event_target(query).map(ResourceTarget::TidelineEvents),
        _ => Err(invalid_request()),
    }
}

fn parse_event_target(query: Option<&str>) -> Result<Option<u64>, McpToolError> {
    query
        .map(query_cursor)
        .transpose()?
        .map(|cursor| cursor.parse::<u64>().map_err(|_| invalid_request()))
        .transpose()
}

fn parse_memory_target(query: Option<&str>) -> Result<Option<MemoryId>, McpToolError> {
    let Some(cursor) = query.map(query_cursor).transpose()? else {
        return Ok(None);
    };
    serde_json::from_value(Value::String(cursor.to_owned())).map_err(|_| invalid_request())
}

fn query_cursor(query: &str) -> Result<&str, McpToolError> {
    query
        .strip_prefix("after=")
        .filter(|cursor| !cursor.is_empty() && !cursor.contains('&'))
        .ok_or_else(invalid_request)
}

fn scope_mode(value: ScopeMode) -> &'static str {
    match value {
        ScopeMode::LocalSingleStore => "local_single_store",
        ScopeMode::RequireExplicit => "require_explicit",
    }
}

fn forgetting_mode(value: ForgettingMode) -> &'static str {
    match value {
        ForgettingMode::SoftInvalidate => "soft_invalidate",
        ForgettingMode::FlagForReverification => "flag_for_reverification",
        ForgettingMode::FullSemanticErase => "full_semantic_erase",
    }
}

fn core_error(error: ShibahamaError) -> McpToolError {
    let metadata = error.metadata();
    McpToolError::with_severity(
        metadata.code,
        metadata.detail,
        metadata.severity.as_str(),
        metadata.retryable,
    )
}

fn invalid_request() -> McpToolError {
    McpToolError::new("SHIBA_INVALID_REQUEST", "invalid resource request", false)
}

fn internal_error() -> McpToolError {
    McpToolError::new("SHIBA_INTERNAL", "internal resource error", false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mcp::{McpSession, PROTOCOL_VERSION};
    use crate::mcp_tools::McpEngineBackend;
    use serde_json::json;
    use shibahama_core::api::WriteEmbedding;
    use shibahama_core::model::{Provenance, ScopeId, ScopeVisibility, SourceKind};
    use shibahama_core::policy::PolicyActorClass;
    use shibahama_core::storage::MemoryWriteEvent;
    use tempfile::NamedTempFile;
    use time::OffsetDateTime;

    fn scope() -> MemoryScope {
        MemoryScope {
            repository: ScopeId::new("repo").expect("constant scope"),
            team: None,
            visibility: ScopeVisibility::Repository,
        }
    }

    fn other_scope() -> MemoryScope {
        MemoryScope {
            repository: ScopeId::new("other").expect("constant scope"),
            team: None,
            visibility: ScopeVisibility::Repository,
        }
    }

    fn context() -> McpServerContext {
        McpServerContext::new(scope(), "alice".to_owned(), PolicyActorClass::Human)
    }

    fn request(
        session: &mut McpSession,
        backend: &mut McpEngineBackend<'_>,
        id: u64,
        method: &str,
        params: Value,
    ) -> Value {
        session
            .handle_with(
                json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "method": method,
                    "params": params,
                }),
                backend,
            )
            .expect("request should respond")
    }

    fn initialize(session: &mut McpSession, backend: &mut McpEngineBackend<'_>) {
        let initialized = request(
            session,
            backend,
            1,
            "initialize",
            json!({
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": { "name": "test", "version": "1" },
            }),
        );
        assert_eq!(initialized["result"]["protocolVersion"], PROTOCOL_VERSION);
        assert!(
            session
                .handle_with(
                    json!({ "jsonrpc": "2.0", "method": "notifications/initialized" }),
                    backend,
                )
                .is_none()
        );
    }

    fn resource_document(
        session: &mut McpSession,
        backend: &mut McpEngineBackend<'_>,
        id: u64,
        uri: &str,
    ) -> Value {
        let response = request(
            session,
            backend,
            id,
            "resources/read",
            json!({ "uri": uri }),
        );
        let text = response["result"]["contents"][0]["text"]
            .as_str()
            .expect("resource content should be text");
        serde_json::from_str(text).expect("resource content should be JSON")
    }

    fn write_memory(engine: &mut Shibahama<HnswVectorIndex>, scope: MemoryScope, content: &str) {
        let now = OffsetDateTime::UNIX_EPOCH;
        let event = MemoryWriteEvent::new(
            content,
            Provenance::new(SourceKind::User, None, "alice"),
            now,
            now,
        )
        .with_scope(scope.clone());
        engine
            .scoped(scope)
            .expect("scope should be valid")
            .write_with_embedding(
                event,
                WriteEmbedding {
                    vector: &[1.0, 0.0],
                    index_name: "test",
                    model: "test",
                    model_version: "v1",
                },
            )
            .expect("write should succeed");
    }

    fn assert_resources_listed(session: &mut McpSession, backend: &mut McpEngineBackend<'_>) {
        let listed = request(session, backend, 2, "resources/list", json!({}));
        let resources = listed["result"]["resources"]
            .as_array()
            .expect("resources should be an array");
        assert_eq!(resources.len(), 5);
        assert!(resources.iter().all(|resource| {
            resource["uri"]
                .as_str()
                .is_some_and(|uri| uri.starts_with(RESOURCE_ROOT))
                && resource["_meta"]["x-shibahama-schema-version"] == 1
        }));
    }

    fn assert_policy_and_scope(session: &mut McpSession, backend: &mut McpEngineBackend<'_>) {
        let policy = resource_document(session, backend, 3, POLICY_URI);
        assert_eq!(policy["schemaVersion"], 1);
        assert!(policy["capturePolicy"].is_object());
        assert!(policy["recallPolicy"].is_object());

        let scope = resource_document(session, backend, 4, SCOPE_URI);
        assert_eq!(scope["scope"]["repository"], "repo");
        assert_eq!(scope["principal"], "alice");
    }

    fn assert_pages_are_bounded_and_scoped(
        session: &mut McpSession,
        backend: &mut McpEngineBackend<'_>,
    ) {
        let audit = resource_document(session, backend, 5, AUDIT_URI);
        assert_eq!(
            audit["auditEvents"].as_array().map(Vec::len),
            Some(RESOURCE_PAGE_SIZE)
        );
        let audit_last_sequence = audit["auditEvents"]
            .as_array()
            .and_then(|events| events.last())
            .and_then(|event| event["sequence"].as_u64())
            .expect("audit page should have a sequence");
        let audit_next = audit["nextUri"].as_str().expect("audit next page");
        let audit_following = resource_document(session, backend, 6, audit_next);
        let audit_following_first = audit_following["auditEvents"]
            .as_array()
            .and_then(|events| events.first())
            .and_then(|event| event["sequence"].as_u64())
            .expect("following audit page should have a sequence");
        assert!(audit_following_first > audit_last_sequence);
        assert!(
            audit_following["auditEvents"]
                .as_array()
                .is_some_and(|events| events.len() <= RESOURCE_PAGE_SIZE)
        );

        let memories = resource_document(session, backend, 7, TIDELINE_MEMORIES_URI);
        assert_eq!(
            memories["memories"].as_array().map(Vec::len),
            Some(RESOURCE_PAGE_SIZE)
        );
        assert!(memories["memories"].as_array().is_some_and(|records| {
            records
                .iter()
                .any(|record| record["content_truncated"] == true)
        }));
        assert!(!memories.to_string().contains("other scope private"));
        let memories_next = memories["nextUri"].as_str().expect("memory next page");
        let memories_last = resource_document(session, backend, 8, memories_next);
        assert_eq!(memories_last["memories"].as_array().map(Vec::len), Some(1));
    }

    fn assert_invalid_uri_is_safe(session: &mut McpSession, backend: &mut McpEngineBackend<'_>) {
        let response = request(
            session,
            backend,
            9,
            "resources/read",
            json!({ "uri": "shibahama://v1/tideline/memories?after=secret" }),
        );
        assert_eq!(response["error"]["code"], -32000);
        assert_eq!(response["error"]["data"]["code"], "SHIBA_INVALID_REQUEST");
        assert_eq!(response["error"]["data"]["severity"], "fatal");
        assert_eq!(response["error"]["data"]["retryable"], false);
        assert!(!response.to_string().contains("after=secret"));
    }

    #[test]
    fn resources_are_versioned_scoped_and_bounded() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut engine = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 128))
            .expect("engine should open");
        for index in 0..=RESOURCE_PAGE_SIZE {
            let content = if index == 0 {
                "x".repeat(RESOURCE_MEMORY_CONTENT_BYTES + 1)
            } else {
                format!("record {index}")
            };
            write_memory(&mut engine, scope(), &content);
        }
        write_memory(&mut engine, other_scope(), "other scope private");
        let mut backend = McpEngineBackend::new(&mut engine);
        let mut session = McpSession::new(context());
        initialize(&mut session, &mut backend);
        assert_resources_listed(&mut session, &mut backend);
        assert_policy_and_scope(&mut session, &mut backend);
        assert_pages_are_bounded_and_scoped(&mut session, &mut backend);
        assert_invalid_uri_is_safe(&mut session, &mut backend);
    }
}
