// SPDX-License-Identifier: MIT

//! Reviewable extraction candidates and explicit non-destructive decisions.

use crate::extraction::{
    ExtractionCandidate, ExtractionError, ExtractionRequest, SourceEvidence, validate_candidates,
};
use crate::model::{MemoryId, MemoryScope, Provenance};
use crate::policy::PolicyActorClass;
use crate::storage::MemoryWriteEvent;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use time::OffsetDateTime;
use uuid::Uuid;

/// Stable review-queue identifier.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ReviewCandidateId(Uuid);

impl ReviewCandidateId {
    /// Generates a time-ordered review candidate id.
    #[must_use]
    pub fn new_v7() -> Self {
        Self(Uuid::now_v7())
    }
}

/// Candidate awaiting explicit review; it is not persisted as a memory item.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ReviewCandidate {
    /// Stable queue id.
    pub id: ReviewCandidateId,
    /// Extraction candidate to review.
    pub candidate: ExtractionCandidate,
    /// Bounded supporting evidence.
    pub evidence: Vec<SourceEvidence>,
    /// Actor or integration submitting the candidate.
    pub submitted_by: String,
    /// Queue submission timestamp.
    pub submitted_at: OffsetDateTime,
}

/// Explicit review action. None implicitly invalidates prior memory.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReviewAction {
    /// Approve and materialize a normal scoped memory.
    Approve,
    /// Reject without promoting candidate content.
    Reject,
    /// Keep the candidate pending for later review.
    Defer,
}

/// Durable review decision metadata; approval optionally links the created memory id.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ReviewDecision {
    /// Queue candidate being reviewed.
    pub candidate_id: ReviewCandidateId,
    /// Scope containing the candidate and its decision audit trail.
    pub scope: MemoryScope,
    /// Explicit outcome.
    pub action: ReviewAction,
    /// Human or attributable agent reviewer.
    pub reviewed_by: String,
    /// Policy actor class of the reviewer.
    pub reviewer_actor: PolicyActorClass,
    /// Content-free rationale for the decision.
    pub rationale: String,
    /// Decision timestamp.
    pub reviewed_at: OffsetDateTime,
    /// Newly created memory id when approved.
    pub approved_memory_id: Option<MemoryId>,
}

/// Current durable review state for one queued candidate.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ReviewQueueItem {
    /// Submitted candidate and its source evidence.
    pub candidate: ReviewCandidate,
    /// Ordered decision history, including non-terminal deferrals.
    pub decisions: Vec<ReviewDecision>,
}

/// Queue validation or approval-conversion failure.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ReviewError {
    /// Candidate evidence fails bounded extraction validation.
    #[error("review candidate evidence is invalid")]
    InvalidCandidate,
    /// Required reviewer/submission metadata is missing.
    #[error("review metadata is invalid")]
    InvalidMetadata,
    /// Candidate timestamp cannot be represented by the memory model.
    #[error("review candidate validity is invalid")]
    InvalidValidity,
    /// A decision does not match its candidate or has incomplete attribution.
    #[error("review decision is invalid")]
    InvalidDecision,
}

impl ReviewCandidate {
    /// Validates a candidate before durable queue insertion.
    ///
    /// # Errors
    ///
    /// Returns [`ReviewError`] when evidence, candidate spans, or attribution is invalid.
    pub fn validate(&self) -> Result<(), ReviewError> {
        if self.submitted_by.trim().is_empty() {
            return Err(ReviewError::InvalidMetadata);
        }
        let request = ExtractionRequest {
            evidence: self.evidence.clone(),
            max_candidates: 1,
        };
        validate_candidates(&request, std::slice::from_ref(&self.candidate))
            .map_err(|_: ExtractionError| ReviewError::InvalidCandidate)?;
        let validity = self.candidate.validity;
        let valid_from = OffsetDateTime::from_unix_timestamp(validity.valid_from_unix)
            .map_err(|_| ReviewError::InvalidValidity)?;
        let ingested_at = OffsetDateTime::from_unix_timestamp(validity.ingested_at_unix)
            .map_err(|_| ReviewError::InvalidValidity)?;
        if ingested_at < valid_from
            || validity.valid_to_unix.is_some_and(|timestamp| {
                OffsetDateTime::from_unix_timestamp(timestamp)
                    .map(|valid_to| valid_to <= valid_from)
                    .unwrap_or(true)
            })
        {
            return Err(ReviewError::InvalidValidity);
        }
        Ok(())
    }

    /// Converts an approved candidate into a normal scoped memory write event.
    ///
    /// # Errors
    ///
    /// Returns [`ReviewError`] when the candidate validity timestamps are invalid.
    pub fn approved_write_event(&self, reviewer: &str) -> Result<MemoryWriteEvent, ReviewError> {
        if reviewer.trim().is_empty() {
            return Err(ReviewError::InvalidMetadata);
        }
        let valid_from =
            OffsetDateTime::from_unix_timestamp(self.candidate.validity.valid_from_unix)
                .map_err(|_| ReviewError::InvalidValidity)?;
        let ingested_at =
            OffsetDateTime::from_unix_timestamp(self.candidate.validity.ingested_at_unix)
                .map_err(|_| ReviewError::InvalidValidity)?;
        let evidence = self
            .candidate
            .evidence_spans
            .first()
            .and_then(|span| self.evidence.get(span.evidence_index))
            .ok_or(ReviewError::InvalidCandidate)?;
        let mut event = MemoryWriteEvent::new(
            self.candidate.content.clone(),
            Provenance::new(
                evidence.source_kind,
                Some(evidence.source_ref.clone()),
                format!("review:{reviewer}"),
            ),
            valid_from,
            ingested_at,
        )
        .with_scope(self.candidate.suggested_scope.clone());
        if let Some(valid_to_unix) = self.candidate.validity.valid_to_unix {
            let valid_to = OffsetDateTime::from_unix_timestamp(valid_to_unix)
                .map_err(|_| ReviewError::InvalidValidity)?;
            event = event.with_valid_to(valid_to);
        }
        if self.candidate.kind == crate::model::MemoryKind::Instruction {
            event = event.as_instruction();
        }
        Ok(event)
    }
}

impl ReviewDecision {
    /// Validates durable decision metadata against one queued candidate.
    ///
    /// # Errors
    ///
    /// Returns [`ReviewError`] when attribution, scope, or approval linkage is inconsistent.
    pub fn validate_for(&self, candidate: &ReviewCandidate) -> Result<(), ReviewError> {
        if self.candidate_id != candidate.id
            || self.scope != candidate.candidate.suggested_scope
            || self.reviewed_by.trim().is_empty()
            || self.rationale.trim().is_empty()
            || matches!(self.action, ReviewAction::Approve) != self.approved_memory_id.is_some()
        {
            return Err(ReviewError::InvalidDecision);
        }
        Ok(())
    }

    /// Returns whether no subsequent review action may change this decision.
    #[must_use]
    pub const fn is_terminal(&self) -> bool {
        matches!(self.action, ReviewAction::Approve | ReviewAction::Reject)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extraction::{CandidateValidity, EvidenceSpan};
    use crate::model::{MemoryKind, ScopeId, SourceKind};

    fn candidate() -> ReviewCandidate {
        ReviewCandidate {
            id: ReviewCandidateId::new_v7(),
            candidate: ExtractionCandidate {
                content: "reviewed fact".to_owned(),
                kind: MemoryKind::Fact,
                validity: CandidateValidity {
                    valid_from_unix: 0,
                    valid_to_unix: Some(10),
                    ingested_at_unix: 0,
                },
                evidence_spans: vec![EvidenceSpan {
                    evidence_index: 0,
                    start: 0,
                    end: 8,
                }],
                confidence_percent: 80,
                rationale: "bounded source statement".to_owned(),
                suggested_scope: MemoryScope::repository(
                    ScopeId::new("repo").expect("constant scope"),
                ),
            },
            evidence: vec![SourceEvidence {
                source_kind: SourceKind::File,
                source_ref: "file:src/lib.rs".to_owned(),
                content: "reviewed source text".to_owned(),
            }],
            submitted_by: "extractor".to_owned(),
            submitted_at: OffsetDateTime::UNIX_EPOCH,
        }
    }

    #[test]
    fn approval_conversion_preserves_scope_provenance_and_validity() {
        let mut candidate = candidate();
        candidate.evidence.insert(
            0,
            SourceEvidence {
                source_kind: SourceKind::Web,
                source_ref: "web:unrelated".to_owned(),
                content: "unrelated web evidence".to_owned(),
            },
        );
        candidate.candidate.evidence_spans[0].evidence_index = 1;
        candidate.validate().expect("candidate is valid");
        let event = candidate
            .approved_write_event("reviewer")
            .expect("approval conversion works");

        assert_eq!(event.scope, candidate.candidate.suggested_scope);
        assert_eq!(event.provenance.ingested_by, "review:reviewer");
        assert_eq!(event.provenance.source_kind, SourceKind::File);
        assert_eq!(
            event.valid_to,
            Some(OffsetDateTime::from_unix_timestamp(10).expect("constant"))
        );
    }

    #[test]
    fn decision_requires_matching_scope_and_approval_linkage() {
        let candidate = candidate();
        let decision = ReviewDecision {
            candidate_id: candidate.id,
            scope: candidate.candidate.suggested_scope.clone(),
            action: ReviewAction::Approve,
            reviewed_by: "reviewer".to_owned(),
            reviewer_actor: PolicyActorClass::Human,
            rationale: "evidence is sufficient".to_owned(),
            reviewed_at: OffsetDateTime::UNIX_EPOCH,
            approved_memory_id: None,
        };

        assert_eq!(
            decision.validate_for(&candidate),
            Err(ReviewError::InvalidDecision)
        );
    }
}
