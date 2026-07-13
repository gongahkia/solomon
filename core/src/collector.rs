// SPDX-License-Identifier: MIT

//! Framework-neutral repository and coding-session evidence collection contracts.

use crate::extraction::SourceEvidence;
use crate::model::{MemoryScope, SourceKind};
use crate::policy::{
    CaptureDecisionOutcome, CapturePolicy, CapturePolicyRequest, PolicyActorClass,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use thiserror::Error;

/// Repository change event without host-specific assumptions.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum RepositoryEventKind {
    /// A version-control commit.
    Commit {
        /// Commit or revision identifier.
        revision: String,
    },
    /// A bounded diff for one path.
    Diff {
        /// Repository-relative path.
        path: String,
    },
    /// A file move or rename.
    FileMoved {
        /// Previous repository-relative path.
        from: String,
        /// New repository-relative path.
        to: String,
    },
    /// An issue, pull request, or equivalent work-item decision.
    WorkItemDecision {
        /// Host-neutral work-item system identifier.
        system: String,
        /// Work-item identifier in that system.
        work_item: String,
    },
    /// Tool-produced repository metadata.
    ToolMetadata {
        /// Tool identifier.
        tool: String,
    },
}

/// Repository event with scope, actor, timestamp, and optional bounded content.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RepositoryEvent {
    /// Repository/team scope containing the event.
    pub scope: MemoryScope,
    /// Attributable event actor.
    pub actor: String,
    /// Event Unix timestamp.
    pub timestamp_unix: i64,
    /// Framework-neutral event category.
    pub kind: RepositoryEventKind,
    /// Non-secret structured metadata.
    pub metadata: BTreeMap<String, String>,
    /// Optional bounded raw content for later policy-gated extraction.
    pub content: Option<String>,
}

/// Session or tool event emitted by a coding agent or host integration.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CodingSessionEvent {
    /// Stable session identifier.
    pub session_id: String,
    /// Repository/team scope.
    pub scope: MemoryScope,
    /// Attributable actor.
    pub actor: String,
    /// Event Unix timestamp.
    pub timestamp_unix: i64,
    /// Command or tool identifier.
    pub tool: String,
    /// Outcome classification such as `succeeded` or `failed`.
    pub outcome: String,
    /// Optional raw output requiring redaction before extraction.
    pub content: Option<String>,
}

/// Framework-neutral repository-event source.
pub trait RepositoryEventCollector: Send + Sync {
    /// Collects repository-relevant events without persisting or extracting them.
    ///
    /// # Errors
    ///
    /// Returns an error when the underlying host cannot produce a bounded event batch.
    fn collect(&self) -> Result<Vec<RepositoryEvent>, CollectorError>;
}

/// Redacts secrets before session evidence reaches extraction.
pub trait EvidenceRedactor: Send + Sync {
    /// Returns content safe to pass to extraction.
    fn redact(&self, content: &str) -> String;
}

/// Bounded collector validation failure.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum CollectorError {
    /// Required attribution, scope, or event identity is missing.
    #[error("collector event is missing required context")]
    MissingContext,
    /// Event content is too large for safe extraction.
    #[error("collector event content exceeds the bounded evidence limit")]
    ContentTooLarge,
}

/// Converts a repository event into policy-gated extraction evidence without persistence.
///
/// `None` means capture policy denied the content or the event carries no content.
///
/// # Errors
///
/// Returns [`CollectorError`] when required event context or content bounds are invalid.
pub fn repository_event_evidence(
    event: &RepositoryEvent,
    policy: CapturePolicy,
    actor: PolicyActorClass,
) -> Result<Option<SourceEvidence>, CollectorError> {
    validate_repository_event(event)?;
    let Some(content) = event.content.as_ref() else {
        return Ok(None);
    };
    let decision = policy.evaluate(
        CapturePolicyRequest {
            actor,
            intent: crate::policy::CaptureIntent::Suggested,
            confidence_percent: 100,
        },
        SourceKind::File,
        &event.scope,
    );
    if decision.outcome == CaptureDecisionOutcome::Deny {
        return Ok(None);
    }

    Ok(Some(SourceEvidence {
        source_kind: SourceKind::File,
        source_ref: repository_event_ref(event),
        content: content.clone(),
    }))
}

/// Converts a session event into redacted policy-gated extraction evidence without persistence.
///
/// # Errors
///
/// Returns [`CollectorError`] when session context or content bounds are invalid.
pub fn session_event_evidence(
    event: &CodingSessionEvent,
    policy: CapturePolicy,
    actor: PolicyActorClass,
    redactor: &dyn EvidenceRedactor,
) -> Result<Option<SourceEvidence>, CollectorError> {
    validate_session_event(event)?;
    let Some(content) = event.content.as_ref() else {
        return Ok(None);
    };
    let decision = policy.evaluate(
        CapturePolicyRequest {
            actor,
            intent: crate::policy::CaptureIntent::Suggested,
            confidence_percent: 100,
        },
        SourceKind::Tool,
        &event.scope,
    );
    if decision.outcome == CaptureDecisionOutcome::Deny {
        return Ok(None);
    }

    Ok(Some(SourceEvidence {
        source_kind: SourceKind::Tool,
        source_ref: format!("session:{}:tool:{}", event.session_id, event.tool),
        content: redactor.redact(content),
    }))
}

fn validate_repository_event(event: &RepositoryEvent) -> Result<(), CollectorError> {
    if event.actor.trim().is_empty() || event.scope.validate().is_err() {
        return Err(CollectorError::MissingContext);
    }
    if event
        .content
        .as_ref()
        .is_some_and(|content| content.len() > 64 * 1024)
    {
        return Err(CollectorError::ContentTooLarge);
    }

    Ok(())
}

fn validate_session_event(event: &CodingSessionEvent) -> Result<(), CollectorError> {
    if event.session_id.trim().is_empty()
        || event.actor.trim().is_empty()
        || event.tool.trim().is_empty()
        || event.scope.validate().is_err()
    {
        return Err(CollectorError::MissingContext);
    }
    if event
        .content
        .as_ref()
        .is_some_and(|content| content.len() > 64 * 1024)
    {
        return Err(CollectorError::ContentTooLarge);
    }

    Ok(())
}

fn repository_event_ref(event: &RepositoryEvent) -> String {
    match &event.kind {
        RepositoryEventKind::Commit { revision } => format!("commit:{revision}"),
        RepositoryEventKind::Diff { path } => format!("diff:{path}"),
        RepositoryEventKind::FileMoved { from, to } => format!("move:{from}->{to}"),
        RepositoryEventKind::WorkItemDecision { system, work_item } => {
            format!("work-item:{system}:{work_item}")
        }
        RepositoryEventKind::ToolMetadata { tool } => format!("tool:{tool}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::ScopeId;
    use crate::policy::CaptureMode;

    #[test]
    fn collectors_are_host_neutral_policy_gated_and_redacted() {
        struct Redactor;
        impl EvidenceRedactor for Redactor {
            fn redact(&self, content: &str) -> String {
                content.replace("secret", "[redacted]")
            }
        }
        let scope = MemoryScope::repository(ScopeId::new("repo").expect("constant scope"));
        let policy = CapturePolicy {
            mode: CaptureMode::Suggest,
            ..CapturePolicy::default()
        };
        let event = RepositoryEvent {
            scope: scope.clone(),
            actor: "dev".to_owned(),
            timestamp_unix: 0,
            kind: RepositoryEventKind::FileMoved {
                from: "a.rs".to_owned(),
                to: "b.rs".to_owned(),
            },
            metadata: BTreeMap::new(),
            content: Some("move rationale".to_owned()),
        };
        let session = CodingSessionEvent {
            session_id: "s1".to_owned(),
            scope,
            actor: "agent".to_owned(),
            timestamp_unix: 0,
            tool: "cargo".to_owned(),
            outcome: "failed".to_owned(),
            content: Some("secret token".to_owned()),
        };

        assert!(
            repository_event_evidence(&event, policy, PolicyActorClass::Human)
                .expect("valid")
                .is_some()
        );
        assert_eq!(
            session_event_evidence(&session, policy, PolicyActorClass::Human, &Redactor)
                .expect("valid")
                .expect("allowed")
                .content,
            "[redacted] token"
        );
    }

    #[test]
    fn multi_session_replay_fixture_preserves_context_before_redaction() {
        struct Redactor;
        impl EvidenceRedactor for Redactor {
            fn redact(&self, content: &str) -> String {
                content.replace("secret token", "[redacted]")
            }
        }
        let events: Vec<CodingSessionEvent> =
            serde_json::from_str(include_str!("../fixtures/coding-session-replay.json"))
                .expect("fixture must deserialize");
        let policy = CapturePolicy {
            mode: CaptureMode::Suggest,
            ..CapturePolicy::default()
        };

        let evidence = events
            .iter()
            .map(|event| {
                session_event_evidence(event, policy, PolicyActorClass::Human, &Redactor)
                    .expect("fixture event should validate")
                    .expect("suggestions should reach review")
            })
            .collect::<Vec<_>>();

        assert_eq!(evidence.len(), 2);
        assert!(evidence[0].source_ref.contains("session-a"));
        assert!(!evidence[0].content.contains("secret token"));
        assert!(evidence[1].source_ref.contains("session-b"));
    }
}
