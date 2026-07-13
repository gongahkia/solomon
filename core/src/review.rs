// SPDX-License-Identifier: MIT

//! Reviewable extraction candidates and explicit non-destructive decisions.

use crate::extraction::{
    ExtractionCandidate, ExtractionError, ExtractionRequest, SourceEvidence, validate_candidates,
};
use crate::model::{MemoryId, Provenance};
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
    Approve,
    Reject,
    Defer,
}

/// Durable review decision metadata; approval optionally links the created memory id.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ReviewDecision {
    /// Queue candidate being reviewed.
    pub candidate_id: ReviewCandidateId,
    /// Explicit outcome.
    pub action: ReviewAction,
    /// Human or attributable agent reviewer.
    pub reviewed_by: String,
    /// Content-free rationale for the decision.
    pub rationale: String,
    /// Decision timestamp.
    pub reviewed_at: OffsetDateTime,
    /// Newly created memory id when approved.
    pub approved_memory_id: Option<MemoryId>,
}

/// Queue validation or approval-conversion failure.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
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
            .map_err(|_: ExtractionError| ReviewError::InvalidCandidate)
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
        let evidence = self.evidence.first().ok_or(ReviewError::InvalidCandidate)?;
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
        if self.candidate.kind == crate::model::MemoryKind::Instruction {
            event = event.as_instruction();
        }
        Ok(event)
    }
}
