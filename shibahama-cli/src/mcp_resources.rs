// SPDX-License-Identifier: MIT

//! Scope-authorized, versioned MCP resource pages.

use crate::mcp::{McpServerContext, McpToolError};
use crate::{MemoryItemDto, tideline_event_from_record};
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
            resource(TIDELINE_MEMORIES_URI, "Tideline memories", "Tideline recording memory page; at most 50 records."),
            resource(TIDELINE_EVENTS_URI, "Tideline events", "Tideline recording event page; at most 50 records."),
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
        ResourceTarget::TidelineMemories(after) => tideline_memories_resource(engine, context, uri, after),
        ResourceTarget::TidelineEvents(after) => tideline_events_resource(engine, context, uri, after),
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
            "memories": records.into_iter().map(MemoryItemDto::from).collect::<Vec<_>>(),
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
        .map(tideline_event_from_record)
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
    let summary = tideline_event_from_record(record);
    json!({
        "sequence": summary.sequence,
        "recordedAtUnix": summary.recorded_at_unix,
        "kind": summary.kind,
        "memoryIds": summary.memory_ids,
    })
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
    }
}

fn core_error(error: ShibahamaError) -> McpToolError {
    let metadata = error.metadata();
    McpToolError::new(metadata.code, metadata.detail, metadata.retryable)
}

fn invalid_request() -> McpToolError {
    McpToolError::new("SHIBA_INVALID_REQUEST", "invalid resource request", false)
}

fn internal_error() -> McpToolError {
    McpToolError::new("SHIBA_INTERNAL", "internal resource error", false)
}
