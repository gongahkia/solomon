// SPDX-License-Identifier: MIT

//! Engine-backed execution for versioned MCP memory tools.

use crate::mcp::{McpServerContext, McpToolBackend, McpToolError};
use crate::{MemoryItemDto, RecallCandidateDto, WhyTraceDto};
use serde_json::{Map, Value, json};
use shibahama_core::api::{
    ForgettingMode, ReviewDecisionRequest, Shibahama, ShibahamaError, WriteEmbedding,
};
use shibahama_core::model::{MemoryId, MemoryScope, Provenance, ScopeId, SourceKind};
use shibahama_core::policy::{CaptureIntent, CapturePolicyRequest, PolicyActorClass};
use shibahama_core::retrieval::RecallRequest;
use shibahama_core::review::{ReviewAction, ReviewCandidateId};
use shibahama_core::storage::{AuthorizationAction, MemoryWriteEvent, RbacRole};
use shibahama_core::vector::HnswVectorIndex;
use time::OffsetDateTime;

/// Engine-backed MCP memory-tool implementation.
pub struct McpEngineBackend<'engine> {
    engine: &'engine mut Shibahama<HnswVectorIndex>,
    rbac: Option<McpRbacPolicy>,
}

/// Active service RBAC policy passed to HTTP MCP tool execution.
#[derive(Clone, Copy)]
pub struct McpRbacPolicy {
    /// Enforce explicit grants before first-administrator bootstrap, when configured.
    pub enforce: bool,
    /// Minimum role for erasure tools.
    pub erasure_min_role: RbacRole,
    /// Minimum role for repository-to-team promotion tools.
    pub promotion_min_role: RbacRole,
}

impl<'engine> McpEngineBackend<'engine> {
    /// Wraps one engine for transport-scoped tool execution.
    #[must_use]
    pub const fn new(engine: &'engine mut Shibahama<HnswVectorIndex>) -> Self {
        Self { engine, rbac: None }
    }

    /// Wraps one engine with service RBAC enforcement for HTTP MCP tool execution.
    #[must_use]
    pub const fn with_rbac(
        engine: &'engine mut Shibahama<HnswVectorIndex>,
        rbac: McpRbacPolicy,
    ) -> Self {
        Self {
            engine,
            rbac: Some(rbac),
        }
    }
}

impl McpToolBackend for McpEngineBackend<'_> {
    fn call(
        &mut self,
        context: &McpServerContext,
        name: &str,
        arguments: &Map<String, Value>,
    ) -> Result<Value, McpToolError> {
        require_schema_and_scope(context, arguments)?;
        self.require_rbac_role(context, name)?;
        match name {
            "shibahama_memory_write_v1" => self.write(context, arguments),
            "shibahama_memory_recall_v1" => self.recall(context, arguments),
            "shibahama_memory_explain_v1" => self.explain(context, arguments),
            "shibahama_memory_timeline_v1" => self.timeline(context, arguments),
            "shibahama_memory_review_v1" => self.review(context, arguments),
            "shibahama_memory_promote_v1" => self.promote(context, arguments),
            "shibahama_memory_erase_v1" => self.erase(context, arguments),
            _ => Err(invalid_arguments()),
        }
    }

    fn list_resources(
        &mut self,
        context: &McpServerContext,
        cursor: Option<&str>,
    ) -> Result<Value, McpToolError> {
        crate::mcp_resources::list_resources(context, cursor)
    }

    fn read_resource(
        &mut self,
        context: &McpServerContext,
        uri: &str,
    ) -> Result<Value, McpToolError> {
        crate::mcp_resources::read_resource(self.engine, context, uri)
    }
}

impl McpEngineBackend<'_> {
    fn require_rbac_role(
        &self,
        context: &McpServerContext,
        tool_name: &str,
    ) -> Result<(), McpToolError> {
        let Some(policy) = self.rbac else {
            return Ok(());
        };
        let administration = self.engine.administration_state().map_err(core_error)?;
        let global_administrator = administration
            .as_ref()
            .and_then(|state| state.administrator.as_ref())
            .is_some_and(|administrator| administrator.principal == context.principal());
        let active = context.credential_role().is_some()
            || policy.enforce
            || administration
                .as_ref()
                .is_some_and(|state| state.administrator.is_some());
        if !active {
            return Ok(());
        }
        let (action, role) = match tool_name {
            "shibahama_memory_recall_v1"
            | "shibahama_memory_explain_v1"
            | "shibahama_memory_timeline_v1" => (AuthorizationAction::Read, RbacRole::Reader),
            "shibahama_memory_write_v1" => (AuthorizationAction::Write, RbacRole::Writer),
            "shibahama_memory_review_v1" => (AuthorizationAction::Maintain, RbacRole::Maintainer),
            "shibahama_memory_promote_v1" => {
                (AuthorizationAction::Promote, policy.promotion_min_role)
            }
            "shibahama_memory_erase_v1" => {
                (AuthorizationAction::SemanticErase, policy.erasure_min_role)
            }
            _ => return Err(invalid_arguments()),
        };
        let allowed = self
            .engine
            .authorize_rbac_role_with_credential(
                context.scope().clone(),
                context.principal(),
                action,
                role,
                global_administrator,
                context.credential_role(),
                context.principal_class(),
                Some(context.actor()),
                OffsetDateTime::now_utc(),
            )
            .map_err(core_error)?;

        if allowed {
            Ok(())
        } else {
            Err(McpToolError::new(
                "SHIBA_UNAUTHORIZED",
                "RBAC role grant is required",
                false,
            ))
        }
    }

    fn write(
        &mut self,
        context: &McpServerContext,
        arguments: &Map<String, Value>,
    ) -> Result<Value, McpToolError> {
        let actor = require_mutation_actor(context, arguments)?;
        let memory_content = required_string(arguments, "content")?;
        let vector = required_vector(arguments, "vector")?;
        let source_kind = source_kind(required_string(arguments, "sourceKind")?)?;
        let source_ref = optional_string(arguments, "sourceRef")?;
        let valid_from = required_time(arguments, "validFromUnix")?;
        let ingested_at = required_time(arguments, "ingestedAtUnix")?;
        let confidence_percent = optional_u8(arguments, "confidencePercent")?.unwrap_or(100);
        let intent = optional_string(arguments, "captureIntent")?
            .as_deref()
            .map(capture_intent)
            .transpose()?
            .unwrap_or(CaptureIntent::Manual);
        let index_name =
            optional_string(arguments, "indexName")?.unwrap_or_else(|| "mcp".to_owned());
        let model =
            optional_string(arguments, "model")?.unwrap_or_else(|| "caller-supplied".to_owned());
        let model_version =
            optional_string(arguments, "modelVersion")?.unwrap_or_else(|| "v1".to_owned());
        let mut event = MemoryWriteEvent::new(
            memory_content,
            Provenance::new(source_kind, source_ref, context.principal()),
            valid_from,
            ingested_at,
        )
        .with_scope(context.scope().clone());
        if optional_string(arguments, "kind")?.as_deref() == Some("instruction") {
            event = event.as_instruction();
        }
        let mut scoped = self
            .engine
            .scoped(context.scope().clone())
            .map_err(core_error)?;
        let item = scoped
            .write_with_embedding_and_capture_policy(
                event,
                WriteEmbedding {
                    vector: &vector,
                    index_name: &index_name,
                    model: &model,
                    model_version: &model_version,
                },
                CapturePolicyRequest {
                    actor,
                    intent,
                    confidence_percent,
                },
            )
            .map_err(core_error)?;

        Ok(output(json!({
            "memory": serializable(MemoryItemDto::from(item))?,
            "policyOutcome": "allowed",
        })))
    }

    fn recall(
        &mut self,
        context: &McpServerContext,
        arguments: &Map<String, Value>,
    ) -> Result<Value, McpToolError> {
        let vector = required_vector(arguments, "queryVector")?;
        let top_k = required_usize(arguments, "topK")?;
        let now = required_time(arguments, "nowUnix")?;
        let mut request = RecallRequest::new(&vector, top_k, now);
        if optional_bool(arguments, "includeCold")?.unwrap_or(false) {
            request = request.include_cold();
        }
        if optional_bool(arguments, "includeInstructions")?.unwrap_or(false) {
            request = request.include_instructions();
        }
        if let Some(max_context_tokens) = optional_usize(arguments, "maxContextTokens")? {
            request = request.with_max_context_tokens(max_context_tokens);
        }
        let mut scoped = self
            .engine
            .scoped(context.scope().clone())
            .map_err(core_error)?;
        let report = scoped
            .recall_with_policy_report(&request)
            .map_err(core_error)?;

        Ok(output(json!({
            "candidates": serializable(report.candidates.into_iter().map(RecallCandidateDto::from).collect::<Vec<_>>())?,
            "policyOutcome": serializable(report.decision)?,
            "contextTokensUsed": report.context_tokens_used,
        })))
    }

    fn explain(
        &mut self,
        context: &McpServerContext,
        arguments: &Map<String, Value>,
    ) -> Result<Value, McpToolError> {
        let memory_id = required_memory_id(arguments, "memoryId")?;
        let now = required_time(arguments, "nowUnix")?;
        let mut scoped = self
            .engine
            .scoped(context.scope().clone())
            .map_err(core_error)?;
        let trace = scoped.why_at(memory_id, now).map_err(core_error)?;

        Ok(output(json!({
            "trace": trace.map(WhyTraceDto::from).map(serializable).transpose()?,
            "policyOutcome": "not_applicable",
        })))
    }

    fn timeline(
        &mut self,
        context: &McpServerContext,
        arguments: &Map<String, Value>,
    ) -> Result<Value, McpToolError> {
        let vector = required_vector(arguments, "queryVector")?;
        let top_k = required_usize(arguments, "topK")?;
        let as_of = required_time(arguments, "asOfUnix")?;
        let request = RecallRequest::new(&vector, top_k, as_of);
        let mut scoped = self
            .engine
            .scoped(context.scope().clone())
            .map_err(core_error)?;
        let report = scoped
            .timeline_with_policy_report(&request)
            .map_err(core_error)?;

        Ok(output(json!({
            "candidates": serializable(report.candidates.into_iter().map(RecallCandidateDto::from).collect::<Vec<_>>())?,
            "policyOutcome": serializable(report.decision)?,
            "contextTokensUsed": report.context_tokens_used,
        })))
    }

    fn review(
        &mut self,
        context: &McpServerContext,
        arguments: &Map<String, Value>,
    ) -> Result<Value, McpToolError> {
        let actor = require_mutation_actor(context, arguments)?;
        let operation = required_string(arguments, "operation")?;
        let mut scoped = self
            .engine
            .scoped(context.scope().clone())
            .map_err(core_error)?;
        if operation == "list" {
            let queue = scoped.review_queue().map_err(core_error)?;
            return Ok(output(
                json!({ "queue": serializable(queue)?, "policyOutcome": "inspection" }),
            ));
        }
        if operation != "decide" {
            return Err(invalid_arguments());
        }
        let candidate_id_text = required_string(arguments, "candidateId")?;
        let candidate_id = required_review_candidate_id(arguments, "candidateId")?;
        let action_name = required_string(arguments, "action")?;
        let action = review_action(action_name)?;
        let rationale = required_string(arguments, "rationale")?;
        let reviewed_at = required_time(arguments, "reviewedAtUnix")?;
        require_confirmation(
            context,
            arguments,
            "review_decision",
            candidate_id_text,
            Some(("action", action_name)),
        )?;
        let outcome = scoped
            .review_candidate(
                candidate_id,
                ReviewDecisionRequest::new(
                    action,
                    actor,
                    context.principal(),
                    rationale,
                    reviewed_at,
                ),
            )
            .map_err(core_error)?;

        Ok(output(json!({
            "queue": [],
            "decision": serializable(outcome.decision)?,
            "memory": outcome.memory.map(MemoryItemDto::from).map(serializable).transpose()?,
            "policyOutcome": "allowed",
        })))
    }

    fn promote(
        &mut self,
        context: &McpServerContext,
        arguments: &Map<String, Value>,
    ) -> Result<Value, McpToolError> {
        let _actor = require_mutation_actor(context, arguments)?;
        let memory_id = required_memory_id(arguments, "memoryId")?;
        let team_name = required_string(arguments, "team")?;
        let team = ScopeId::new(team_name).map_err(|_| invalid_arguments())?;
        let rationale = required_string(arguments, "rationale")?;
        let promoted_at = required_time(arguments, "promotedAtUnix")?;
        require_confirmation(
            context,
            arguments,
            "promotion",
            &memory_id.to_string(),
            Some(("targetTeam", team_name)),
        )?;
        let mut scoped = self
            .engine
            .scoped(context.scope().clone())
            .map_err(core_error)?;
        let promotion = scoped
            .promote_to_team(memory_id, team, context.principal(), rationale, promoted_at)
            .map_err(core_error)?;
        let policy_outcome = if promotion.is_some() {
            "allowed"
        } else {
            "not_found"
        };

        Ok(output(json!({
            "promotion": promotion.map(|record| MemoryItemDto::from(record.promoted)).map(serializable).transpose()?,
            "policyOutcome": policy_outcome,
        })))
    }

    fn erase(
        &mut self,
        context: &McpServerContext,
        arguments: &Map<String, Value>,
    ) -> Result<Value, McpToolError> {
        let _actor = require_mutation_actor(context, arguments)?;
        if self.engine.config().forgetting.mode != ForgettingMode::SoftInvalidate {
            return Err(McpToolError::new(
                "SHIBA_UNSUPPORTED",
                "semantic erase requires soft-invalidation mode",
                false,
            ));
        }
        let memory_id = required_memory_id(arguments, "memoryId")?;
        let valid_to = required_time(arguments, "validToUnix")?;
        let valid_to_unix = valid_to.unix_timestamp();
        require_confirmation(
            context,
            arguments,
            "erasure",
            &memory_id.to_string(),
            Some(("validToUnix", &valid_to_unix.to_string())),
        )?;
        let mut scoped = self
            .engine
            .scoped(context.scope().clone())
            .map_err(core_error)?;
        let applied = scoped.invalidate(memory_id, valid_to).map_err(core_error)?;
        let policy_outcome = if applied { "allowed" } else { "not_found" };

        Ok(output(
            json!({ "applied": applied, "effect": "soft_invalidation", "policyOutcome": policy_outcome }),
        ))
    }
}

fn require_schema_and_scope(
    context: &McpServerContext,
    arguments: &Map<String, Value>,
) -> Result<(), McpToolError> {
    if arguments.get("schemaVersion").and_then(Value::as_u64) != Some(1) {
        return Err(invalid_arguments());
    }
    let Some(scope) = arguments.get("scope") else {
        return Err(invalid_arguments());
    };
    let scope =
        serde_json::from_value::<MemoryScope>(scope.clone()).map_err(|_| invalid_arguments())?;
    if scope != *context.scope() {
        return Err(McpToolError::new(
            "SHIBA_UNAUTHORIZED",
            "tool scope does not match transport context",
            false,
        ));
    }
    Ok(())
}

fn require_mutation_actor(
    context: &McpServerContext,
    arguments: &Map<String, Value>,
) -> Result<PolicyActorClass, McpToolError> {
    let actor = match required_string(arguments, "actor")? {
        "human" => PolicyActorClass::Human,
        "agent" => PolicyActorClass::Agent,
        "automation" => PolicyActorClass::Automation,
        "service" => PolicyActorClass::Service,
        _ => return Err(invalid_arguments()),
    };
    if actor != context.actor() {
        return Err(McpToolError::new(
            "SHIBA_UNAUTHORIZED",
            "tool actor does not match transport identity",
            false,
        ));
    }
    if required_string(arguments, "actorId")? != context.principal() {
        return Err(McpToolError::new(
            "SHIBA_UNAUTHORIZED",
            "tool actor does not match transport principal",
            false,
        ));
    }
    Ok(actor)
}

fn require_confirmation(
    context: &McpServerContext,
    arguments: &Map<String, Value>,
    intent: &str,
    target_id: &str,
    bound_field: Option<(&str, &str)>,
) -> Result<(), McpToolError> {
    let confirmation = arguments
        .get("confirmation")
        .and_then(Value::as_object)
        .ok_or_else(confirmation_required)?;
    if confirmation.get("schemaVersion").and_then(Value::as_u64) != Some(1)
        || confirmation.get("intent").and_then(Value::as_str) != Some(intent)
        || !confirmation
            .get("token")
            .and_then(Value::as_str)
            .is_some_and(|token| (16..=128).contains(&token.len()))
        || confirmation.get("actorId").and_then(Value::as_str) != Some(context.principal())
        || confirmation.get("targetId").and_then(Value::as_str) != Some(target_id)
    {
        return Err(confirmation_required());
    }
    let scope = confirmation
        .get("scope")
        .cloned()
        .and_then(|value| serde_json::from_value::<MemoryScope>(value).ok())
        .ok_or_else(confirmation_required)?;
    if scope != *context.scope() {
        return Err(confirmation_required());
    }
    if let Some((field, expected)) = bound_field
        && !confirmation
            .get(field)
            .is_some_and(|value| confirmation_value_matches(value, expected))
    {
        return Err(confirmation_required());
    }
    Ok(())
}

fn confirmation_value_matches(value: &Value, expected: &str) -> bool {
    value.as_str() == Some(expected)
        || value
            .as_i64()
            .is_some_and(|integer| integer.to_string() == expected)
}

fn required_string<'a>(
    arguments: &'a Map<String, Value>,
    field: &str,
) -> Result<&'a str, McpToolError> {
    arguments
        .get(field)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(invalid_arguments)
}

fn optional_string(
    arguments: &Map<String, Value>,
    field: &str,
) -> Result<Option<String>, McpToolError> {
    match arguments.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) if !value.is_empty() => Ok(Some(value.clone())),
        _ => Err(invalid_arguments()),
    }
}

fn optional_bool(
    arguments: &Map<String, Value>,
    field: &str,
) -> Result<Option<bool>, McpToolError> {
    match arguments.get(field) {
        None => Ok(None),
        Some(Value::Bool(value)) => Ok(Some(*value)),
        _ => Err(invalid_arguments()),
    }
}

fn required_vector(arguments: &Map<String, Value>, field: &str) -> Result<Vec<f32>, McpToolError> {
    let Some(values) = arguments.get(field).and_then(Value::as_array) else {
        return Err(invalid_arguments());
    };
    if values.is_empty() {
        return Err(invalid_arguments());
    }
    let vector = serde_json::from_value::<Vec<f32>>(Value::Array(values.clone()))
        .map_err(|_| invalid_arguments())?;
    if vector.iter().all(|value| value.is_finite()) {
        Ok(vector)
    } else {
        Err(invalid_arguments())
    }
}

fn required_usize(arguments: &Map<String, Value>, field: &str) -> Result<usize, McpToolError> {
    let value = arguments
        .get(field)
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .filter(|value| *value > 0)
        .ok_or_else(invalid_arguments)?;
    Ok(value)
}

fn optional_usize(
    arguments: &Map<String, Value>,
    field: &str,
) -> Result<Option<usize>, McpToolError> {
    match arguments.get(field) {
        None => Ok(None),
        Some(Value::Number(value)) => value
            .as_u64()
            .and_then(|value| usize::try_from(value).ok())
            .filter(|value| *value > 0)
            .map(Some)
            .ok_or_else(invalid_arguments),
        _ => Err(invalid_arguments()),
    }
}

fn optional_u8(arguments: &Map<String, Value>, field: &str) -> Result<Option<u8>, McpToolError> {
    match arguments.get(field) {
        None => Ok(None),
        Some(Value::Number(value)) => value
            .as_u64()
            .and_then(|value| u8::try_from(value).ok())
            .filter(|value| *value <= 100)
            .map(Some)
            .ok_or_else(invalid_arguments),
        _ => Err(invalid_arguments()),
    }
}

fn required_time(
    arguments: &Map<String, Value>,
    field: &str,
) -> Result<OffsetDateTime, McpToolError> {
    let value = arguments
        .get(field)
        .and_then(Value::as_i64)
        .ok_or_else(invalid_arguments)?;
    OffsetDateTime::from_unix_timestamp(value).map_err(|_| invalid_arguments())
}

fn required_memory_id(
    arguments: &Map<String, Value>,
    field: &str,
) -> Result<MemoryId, McpToolError> {
    let value = arguments
        .get(field)
        .cloned()
        .ok_or_else(invalid_arguments)?;
    serde_json::from_value(value).map_err(|_| invalid_arguments())
}

fn required_review_candidate_id(
    arguments: &Map<String, Value>,
    field: &str,
) -> Result<ReviewCandidateId, McpToolError> {
    let value = arguments
        .get(field)
        .cloned()
        .ok_or_else(invalid_arguments)?;
    serde_json::from_value(value).map_err(|_| invalid_arguments())
}

fn source_kind(value: &str) -> Result<SourceKind, McpToolError> {
    match value {
        "user" => Ok(SourceKind::User),
        "agent" => Ok(SourceKind::Agent),
        "file" => Ok(SourceKind::File),
        "web" => Ok(SourceKind::Web),
        "tool" => Ok(SourceKind::Tool),
        _ => Err(invalid_arguments()),
    }
}

fn capture_intent(value: &str) -> Result<CaptureIntent, McpToolError> {
    match value {
        "manual" => Ok(CaptureIntent::Manual),
        "suggested" => Ok(CaptureIntent::Suggested),
        "automatic" => Ok(CaptureIntent::Automatic),
        _ => Err(invalid_arguments()),
    }
}

fn review_action(value: &str) -> Result<ReviewAction, McpToolError> {
    match value {
        "approve" => Ok(ReviewAction::Approve),
        "reject" => Ok(ReviewAction::Reject),
        "defer" => Ok(ReviewAction::Defer),
        _ => Err(invalid_arguments()),
    }
}

fn serializable(value: impl serde::Serialize) -> Result<Value, McpToolError> {
    serde_json::to_value(value).map_err(|_| internal_error())
}

fn output(result: Value) -> Value {
    json!({ "schemaVersion": 1, "result": result })
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

fn invalid_arguments() -> McpToolError {
    McpToolError::new("SHIBA_INVALID_REQUEST", "invalid tool arguments", false)
}

fn internal_error() -> McpToolError {
    McpToolError::new("SHIBA_INTERNAL", "internal tool error", false)
}

fn confirmation_required() -> McpToolError {
    McpToolError::new(
        "SHIBA_CONFIRMATION_REQUIRED",
        "explicit confirmation does not match the destructive action",
        false,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mcp::{McpSession, PROTOCOL_VERSION};
    use proptest::prelude::*;
    use serde_json::json;
    use shibahama_core::api::{AllowScopePromotionPolicy, ScopeMode, ShibahamaConfig};
    use shibahama_core::model::{ScopeId, ScopeVisibility};
    use shibahama_core::policy::{
        ActorClassPolicy, CaptureMode, CapturePolicy, ScopePolicy, SourceKindPolicy,
    };
    use shibahama_core::storage::MemoryEvent;
    use tempfile::NamedTempFile;

    fn context() -> McpServerContext {
        McpServerContext::new(
            MemoryScope {
                repository: ScopeId::new("repo").expect("constant scope"),
                team: None,
                visibility: ScopeVisibility::Repository,
            },
            "alice".to_owned(),
            PolicyActorClass::Human,
        )
    }

    fn scope() -> Value {
        json!({ "repository": "repo", "team": null, "visibility": "repository" })
    }

    fn property_actor(index: u8) -> (PolicyActorClass, &'static str) {
        match index % 4 {
            0 => (PolicyActorClass::Human, "human"),
            1 => (PolicyActorClass::Agent, "agent"),
            2 => (PolicyActorClass::Automation, "automation"),
            _ => (PolicyActorClass::Service, "service"),
        }
    }

    fn property_source(index: u8) -> (SourceKind, &'static str) {
        match index % 5 {
            0 => (SourceKind::User, "user"),
            1 => (SourceKind::Agent, "agent"),
            2 => (SourceKind::File, "file"),
            3 => (SourceKind::Web, "web"),
            _ => (SourceKind::Tool, "tool"),
        }
    }

    fn property_scope(team: bool) -> MemoryScope {
        let repository = ScopeId::new("property-repo").expect("constant scope");
        if team {
            MemoryScope::team(
                repository,
                ScopeId::new("property-team").expect("constant scope"),
            )
        } else {
            MemoryScope::repository(repository)
        }
    }

    fn property_actor_policy(actor: PolicyActorClass, allowed: bool) -> ActorClassPolicy {
        let mut policy = ActorClassPolicy {
            human: false,
            agent: false,
            automation: false,
            service: false,
        };
        match actor {
            PolicyActorClass::Human => policy.human = allowed,
            PolicyActorClass::Agent => policy.agent = allowed,
            PolicyActorClass::Automation => policy.automation = allowed,
            PolicyActorClass::Service => policy.service = allowed,
        }
        policy
    }

    fn property_source_policy(source: SourceKind, allowed: bool) -> SourceKindPolicy {
        let mut policy = SourceKindPolicy {
            user: false,
            agent: false,
            file: false,
            web: false,
            tool: false,
        };
        match source {
            SourceKind::User => policy.user = allowed,
            SourceKind::Agent => policy.agent = allowed,
            SourceKind::File => policy.file = allowed,
            SourceKind::Web => policy.web = allowed,
            SourceKind::Tool => policy.tool = allowed,
        }
        policy
    }

    fn initialize(session: &mut McpSession, backend: &mut McpEngineBackend<'_>) {
        let initialized = session.handle_with(
            json!({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": { "name": "test", "version": "1" },
                }
            }),
            backend,
        );
        assert_eq!(
            initialized.expect("initialize should respond")["result"]["protocolVersion"],
            PROTOCOL_VERSION
        );
        assert!(
            session
                .handle_with(
                    json!({ "jsonrpc": "2.0", "method": "notifications/initialized" }),
                    backend,
                )
                .is_none()
        );
    }

    fn call(
        session: &mut McpSession,
        backend: &mut McpEngineBackend<'_>,
        id: u64,
        name: &str,
        arguments: Value,
    ) -> Value {
        session
            .handle_with(
                json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "method": "tools/call",
                    "params": { "name": name, "arguments": arguments },
                }),
                backend,
            )
            .expect("tool call should respond")
    }

    fn write_arguments(actor: &str, actor_id: &str, content: &str) -> Value {
        json!({
            "schemaVersion": 1,
            "scope": scope(),
            "actor": actor,
            "actorId": actor_id,
            "content": content,
            "vector": [1.0, 0.0],
            "sourceKind": "user",
            "validFromUnix": 0,
            "ingestedAtUnix": 0,
        })
    }

    fn recall_arguments() -> Value {
        json!({
            "schemaVersion": 1,
            "scope": scope(),
            "queryVector": [1.0, 0.0],
            "topK": 1,
            "nowUnix": 0,
        })
    }

    fn explain_arguments(memory_id: &str) -> Value {
        json!({
            "schemaVersion": 1,
            "scope": scope(),
            "memoryId": memory_id,
            "nowUnix": 0,
        })
    }

    fn timeline_arguments() -> Value {
        json!({
            "schemaVersion": 1,
            "scope": scope(),
            "queryVector": [1.0, 0.0],
            "topK": 1,
            "asOfUnix": 0,
        })
    }

    fn review_arguments() -> Value {
        json!({
            "schemaVersion": 1,
            "scope": scope(),
            "actor": "human",
            "actorId": "alice",
            "operation": "list",
        })
    }

    fn promotion_arguments(memory_id: &str) -> Value {
        json!({
            "schemaVersion": 1,
            "scope": scope(),
            "actor": "human",
            "actorId": "alice",
            "memoryId": memory_id,
            "team": "team",
            "rationale": "share",
            "promotedAtUnix": 1,
            "confirmation": {
                "schemaVersion": 1,
                "intent": "promotion",
                "token": "promotion-confirm-0001",
                "actorId": "alice",
                "scope": scope(),
                "targetId": memory_id,
                "targetTeam": "team",
            },
        })
    }

    fn erase_arguments(memory_id: &str) -> Value {
        json!({
            "schemaVersion": 1,
            "scope": scope(),
            "actor": "human",
            "actorId": "alice",
            "memoryId": memory_id,
            "validToUnix": 2,
            "confirmation": {
                "schemaVersion": 1,
                "intent": "erasure",
                "token": "erasure-confirmation-0001",
                "actorId": "alice",
                "scope": scope(),
                "targetId": memory_id,
                "validToUnix": 2,
            },
        })
    }

    fn exercise_read_tools(session: &mut McpSession, backend: &mut McpEngineBackend<'_>) -> String {
        let write = call(
            session,
            backend,
            2,
            "shibahama_memory_write_v1",
            write_arguments("human", "alice", "MCP tool memory"),
        );
        assert!(
            !write["result"]["isError"]
                .as_bool()
                .expect("isError should be bool")
        );
        let memory_id = write["result"]["structuredContent"]["result"]["memory"]["id"]
            .as_str()
            .expect("memory id should be present")
            .to_owned();
        assert_eq!(
            write["result"]["structuredContent"]["result"]["memory"]["provenance"]["ingested_by"],
            "alice"
        );
        assert_eq!(
            write["result"]["structuredContent"]["result"]["policyOutcome"],
            "allowed"
        );

        let recall = call(
            session,
            backend,
            3,
            "shibahama_memory_recall_v1",
            recall_arguments(),
        );
        assert_eq!(
            recall["result"]["structuredContent"]["result"]["candidates"][0]["id"],
            memory_id
        );
        assert!(recall["result"]["structuredContent"]["result"]["policyOutcome"].is_object());

        let explain = call(
            session,
            backend,
            4,
            "shibahama_memory_explain_v1",
            explain_arguments(&memory_id),
        );
        assert_eq!(
            explain["result"]["structuredContent"]["result"]["trace"]["provenance"]["ingested_by"],
            "alice"
        );
        assert_eq!(
            explain["result"]["structuredContent"]["result"]["policyOutcome"],
            "not_applicable"
        );

        let timeline = call(
            session,
            backend,
            5,
            "shibahama_memory_timeline_v1",
            timeline_arguments(),
        );
        assert_eq!(
            timeline["result"]["structuredContent"]["result"]["candidates"][0]["id"],
            memory_id
        );
        assert!(timeline["result"]["structuredContent"]["result"]["policyOutcome"].is_object());
        memory_id
    }

    fn exercise_mutating_tools(
        session: &mut McpSession,
        backend: &mut McpEngineBackend<'_>,
        memory_id: &str,
    ) {
        let review = call(
            session,
            backend,
            6,
            "shibahama_memory_review_v1",
            review_arguments(),
        );
        assert_eq!(
            review["result"]["structuredContent"]["result"]["queue"],
            json!([])
        );
        assert_eq!(
            review["result"]["structuredContent"]["result"]["policyOutcome"],
            "inspection"
        );

        let promotion = call(
            session,
            backend,
            7,
            "shibahama_memory_promote_v1",
            promotion_arguments(memory_id),
        );
        assert_eq!(
            promotion["result"]["structuredContent"]["result"]["promotion"]["scope"]["visibility"],
            "team"
        );
        assert_eq!(
            promotion["result"]["structuredContent"]["result"]["policyOutcome"],
            "allowed"
        );

        let mut confused_deputy = promotion_arguments(memory_id);
        confused_deputy["confirmation"]["targetId"] = json!("other-memory");
        confused_deputy["confirmation"]["token"] = json!("confused-deputy-0001");
        let rejected = call(
            session,
            backend,
            8,
            "shibahama_memory_promote_v1",
            confused_deputy,
        );
        assert_eq!(rejected["result"]["isError"], true);
        assert_eq!(
            rejected["result"]["structuredContent"]["error"]["code"],
            "SHIBA_CONFIRMATION_REQUIRED"
        );

        let erase = call(
            session,
            backend,
            9,
            "shibahama_memory_erase_v1",
            erase_arguments(memory_id),
        );
        assert_eq!(
            erase["result"]["structuredContent"]["result"]["effect"],
            "soft_invalidation"
        );
        assert_eq!(
            erase["result"]["structuredContent"]["result"]["policyOutcome"],
            "allowed"
        );

        let retry = call(
            session,
            backend,
            10,
            "shibahama_memory_erase_v1",
            erase_arguments(memory_id),
        );
        assert_eq!(retry["result"]["isError"], true);
        assert_eq!(
            retry["result"]["structuredContent"]["error"]["code"],
            "SHIBA_CONFIRMATION_CONSUMED"
        );
    }

    fn assert_forged_actor_is_safe(session: &mut McpSession, backend: &mut McpEngineBackend<'_>) {
        let forged_principal = call(
            session,
            backend,
            11,
            "shibahama_memory_write_v1",
            write_arguments("human", "mallory", "secret must not appear in the error"),
        );
        assert_eq!(forged_principal["result"]["isError"], true);
        let error = &forged_principal["result"]["structuredContent"]["error"];
        assert_eq!(error["code"], "SHIBA_UNAUTHORIZED");
        assert_eq!(error["severity"], "fatal");
        assert_eq!(error["retryable"], false);
        assert!(!error.to_string().contains("secret must not appear"));

        let forged_actor = call(
            session,
            backend,
            12,
            "shibahama_memory_write_v1",
            write_arguments("agent", "alice", "actor class must not be forgeable"),
        );
        assert_eq!(forged_actor["result"]["isError"], true);
        assert_eq!(
            forged_actor["result"]["structuredContent"]["error"]["code"],
            "SHIBA_UNAUTHORIZED"
        );
        assert!(
            !forged_actor
                .to_string()
                .contains("actor class must not be forgeable")
        );
    }

    fn assert_capture_audits_transport_actor(engine: &Shibahama<HnswVectorIndex>) {
        let events = engine
            .store()
            .events_in_scope(context().scope())
            .expect("audit events should be readable");
        assert!(events.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::PolicyDecisionRecorded { record }
                    if record.actor == Some(PolicyActorClass::Human)
            )
        }));
    }

    fn assert_review_decision_requires_confirmation(
        session: &mut McpSession,
        backend: &mut McpEngineBackend<'_>,
    ) {
        let rejected = call(
            session,
            backend,
            13,
            "shibahama_memory_review_v1",
            json!({
                "schemaVersion": 1,
                "scope": scope(),
                "actor": "human",
                "actorId": "alice",
                "operation": "decide",
                "candidateId": "00000000-0000-4000-8000-000000000001",
                "action": "reject",
                "rationale": "missing explicit confirmation",
                "reviewedAtUnix": 0,
            }),
        );
        assert_eq!(rejected["result"]["isError"], true);
        assert_eq!(
            rejected["result"]["structuredContent"]["error"]["code"],
            "SHIBA_CONFIRMATION_REQUIRED"
        );
        assert!(
            !rejected
                .to_string()
                .contains("missing explicit confirmation")
        );
    }

    fn assert_suggested_capture_is_policy_rejected(
        session: &mut McpSession,
        backend: &mut McpEngineBackend<'_>,
    ) {
        let mut suggested = write_arguments("human", "alice", "suggested capture must not persist");
        suggested["captureIntent"] = json!("suggested");
        let rejected = call(session, backend, 14, "shibahama_memory_write_v1", suggested);
        assert_eq!(rejected["result"]["isError"], true);
        let error = &rejected["result"]["structuredContent"]["error"];
        assert_eq!(error["code"], "SHIBA_POLICY");
        assert_eq!(error["severity"], "fatal");
        assert_eq!(error["retryable"], false);
        assert!(
            !error
                .to_string()
                .contains("suggested capture must not persist")
        );
    }

    proptest! {
        #![proptest_config(ProptestConfig::with_cases(64))]

        #[test]
        fn automatic_mcp_capture_never_bypasses_policy_boundary(
            actor_index in 0_u8..4,
            source_index in 0_u8..5,
            team_scope in any::<bool>(),
            allow_actor in any::<bool>(),
            allow_source in any::<bool>(),
            allow_scope in any::<bool>(),
            minimum_confidence in 0_u8..=100,
            confidence in 0_u8..=100,
        ) {
            let (actor, actor_name) = property_actor(actor_index);
            let (source, source_name) = property_source(source_index);
            let scope = property_scope(team_scope);
            let capture_policy = CapturePolicy {
                mode: CaptureMode::Automatic,
                actors: property_actor_policy(actor, allow_actor),
                sources: property_source_policy(source, allow_source),
                scopes: ScopePolicy {
                    repository: !team_scope && allow_scope,
                    team: team_scope && allow_scope,
                },
                minimum_confidence_percent: minimum_confidence,
                ..CapturePolicy::default()
            };
            let config = ShibahamaConfig {
                scope_mode: ScopeMode::RequireExplicit,
                capture_policy,
                ..ShibahamaConfig::default()
            };
            let file = NamedTempFile::new().expect("temporary store should open");
            let mut engine = Shibahama::open_with_config(
                file.path(),
                HnswVectorIndex::with_capacity(2, 8),
                config,
            ).expect("engine should open");
            let context = McpServerContext::new(scope.clone(), "property-agent".to_owned(), actor);
            let arguments = json!({
                "schemaVersion": 1,
                "scope": scope.clone(),
                "actor": actor_name,
                "actorId": "property-agent",
                "content": "policy property fixture",
                "vector": [1.0, 0.0],
                "sourceKind": source_name,
                "validFromUnix": 0,
                "ingestedAtUnix": 0,
                "captureIntent": "automatic",
                "confidencePercent": confidence,
            });
            let response = {
                let mut backend = McpEngineBackend::new(&mut engine);
                let mut session = McpSession::new(context);
                initialize(&mut session, &mut backend);
                call(
                    &mut session,
                    &mut backend,
                    2,
                    "shibahama_memory_write_v1",
                    arguments,
                )
            };
            let denied = !allow_actor || !allow_source || !allow_scope || confidence < minimum_confidence;

            prop_assert_eq!(response["result"]["isError"].as_bool(), Some(denied));
            if denied {
                prop_assert_eq!(
                    response["result"]["structuredContent"]["error"]["code"].as_str(),
                    Some("SHIBA_POLICY")
                );
            } else {
                prop_assert_eq!(
                    response["result"]["structuredContent"]["result"]["policyOutcome"].as_str(),
                    Some("allowed")
                );
            }
            let count = engine
                .scoped(scope)
                .expect("scope should be valid")
                .memory_items()
                .expect("memory items should read")
                .len();
            prop_assert_eq!(count, usize::from(!denied));
        }
    }

    #[test]
    fn memory_tools_are_scoped_versioned_and_safe_on_rejection() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut engine = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("engine should open");
        engine.set_scope_authorization_policy(AllowScopePromotionPolicy);
        {
            let mut backend = McpEngineBackend::new(&mut engine);
            let mut session = McpSession::new(context());
            initialize(&mut session, &mut backend);
            let memory_id = exercise_read_tools(&mut session, &mut backend);
            exercise_mutating_tools(&mut session, &mut backend, &memory_id);
            assert_forged_actor_is_safe(&mut session, &mut backend);
            assert_review_decision_requires_confirmation(&mut session, &mut backend);
            assert_suggested_capture_is_policy_rejected(&mut session, &mut backend);
        }
        assert_capture_audits_transport_actor(&engine);
    }

    #[test]
    fn service_rbac_requires_explicit_mcp_roles_for_writes_and_maintenance() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut engine = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("engine should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let commitment = "a".repeat(64);
        let context = context();

        engine
            .ensure_administration_bootstrap_window(
                &commitment,
                now,
                now + time::Duration::hours(1),
            )
            .expect("bootstrap window should open");
        engine
            .bootstrap_administrator(&commitment, "oidc:admin", now)
            .expect("administrator should bootstrap");
        engine
            .grant_rbac_role(
                context.scope().clone(),
                context.principal(),
                RbacRole::Reader,
                "oidc:admin",
                now,
            )
            .expect("reader grant should persist");

        {
            let backend = McpEngineBackend::with_rbac(
                &mut engine,
                McpRbacPolicy {
                    enforce: false,
                    erasure_min_role: RbacRole::Maintainer,
                    promotion_min_role: RbacRole::Maintainer,
                },
            );
            assert!(
                backend
                    .require_rbac_role(&context, "shibahama_memory_recall_v1")
                    .is_ok()
            );
            for tool in [
                "shibahama_memory_write_v1",
                "shibahama_memory_review_v1",
                "shibahama_memory_promote_v1",
                "shibahama_memory_erase_v1",
            ] {
                let error = backend
                    .require_rbac_role(&context, tool)
                    .expect_err("reader must not mutate or maintain via MCP");
                assert_eq!(
                    error,
                    McpToolError::new("SHIBA_UNAUTHORIZED", "RBAC role grant is required", false)
                );
            }
        }
        engine
            .grant_rbac_role(
                context.scope().clone(),
                context.principal(),
                RbacRole::Maintainer,
                "oidc:admin",
                now,
            )
            .expect("maintainer grant should persist");
        {
            let backend = McpEngineBackend::with_rbac(
                &mut engine,
                McpRbacPolicy {
                    enforce: false,
                    erasure_min_role: RbacRole::Maintainer,
                    promotion_min_role: RbacRole::Maintainer,
                },
            );
            assert!(
                backend
                    .require_rbac_role(&context, "shibahama_memory_promote_v1")
                    .is_ok()
            );
            assert!(
                backend
                    .require_rbac_role(&context, "shibahama_memory_erase_v1")
                    .is_ok()
            );
        }
        let audit = engine
            .authorization_audit_in_scope(context.scope())
            .expect("authorization audit should read");
        assert!(audit.iter().any(|record| {
            record.action == AuthorizationAction::Promote
                && record.required_role == RbacRole::Maintainer
                && record.allowed
                && record.actor_class == Some(PolicyActorClass::Human)
        }));
        assert!(audit.iter().any(|record| {
            record.action == AuthorizationAction::SemanticErase
                && record.required_role == RbacRole::Maintainer
                && record.allowed
        }));
    }
}
