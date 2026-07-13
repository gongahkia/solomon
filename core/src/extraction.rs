// SPDX-License-Identifier: MIT

//! Bounded, provider-neutral memory extraction contracts.

use crate::model::{MemoryKind, MemoryScope, SourceKind};
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Maximum source-evidence bytes accepted by one extraction request.
pub const MAX_EXTRACTION_EVIDENCE_BYTES: usize = 64 * 1024;
/// Maximum candidates returned by one extraction request.
pub const MAX_EXTRACTION_CANDIDATES: usize = 64;

/// One bounded source supplied to an extractor, never a persistence handle.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SourceEvidence {
    /// Provenance class for extracted candidates.
    pub source_kind: SourceKind,
    /// Stable source reference.
    pub source_ref: String,
    /// Bounded source text evaluated by the extractor.
    pub content: String,
}

/// Span into one request evidence item.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EvidenceSpan {
    /// Index into [`ExtractionRequest::evidence`].
    pub evidence_index: usize,
    /// Byte offset into the referenced evidence content.
    pub start: usize,
    /// Exclusive byte offset into the referenced evidence content.
    pub end: usize,
}

/// Typed request passed to an extractor without durable-store access.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ExtractionRequest {
    /// Bounded evidence available for extraction.
    pub evidence: Vec<SourceEvidence>,
    /// Maximum candidates the extractor may return.
    pub max_candidates: usize,
}

/// Proposed memory returned by an extractor; persistence requires a separate approval path.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ExtractionCandidate {
    /// Candidate content.
    pub content: String,
    /// Semantic memory class.
    pub kind: MemoryKind,
    /// Suggested validity interval expressed as portable Unix timestamps.
    pub validity: CandidateValidity,
    /// Source spans supporting this candidate.
    pub evidence_spans: Vec<EvidenceSpan>,
    /// Extractor confidence in percent, from 0 through 100.
    pub confidence_percent: u8,
    /// Content-free explanation of the extraction decision.
    pub rationale: String,
    /// Scope proposed for later review/approval.
    pub suggested_scope: MemoryScope,
}

/// Suggested candidate validity without platform-specific timestamp serialization.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CandidateValidity {
    /// Unix timestamp at which the candidate becomes valid.
    pub valid_from_unix: i64,
    /// Optional Unix timestamp after which the candidate is not valid.
    pub valid_to_unix: Option<i64>,
    /// Unix timestamp at which its source evidence was observed.
    pub ingested_at_unix: i64,
}

/// Validation failure for bounded extraction input or output.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum ExtractionError {
    /// The request has no evidence or exceeds its byte budget.
    #[error("extraction evidence is empty or exceeds the byte budget")]
    EvidenceBounds,
    /// The requested candidate limit is outside the supported range.
    #[error("extraction candidate limit is invalid")]
    CandidateLimit,
    /// A candidate is missing bounded content, rationale, scope, or valid evidence spans.
    #[error("extraction candidate is invalid")]
    CandidateInvalid,
}

/// Provider-neutral extractor interface; it has no storage or promotion capability.
pub trait MemoryExtractor: Send + Sync {
    /// Produces typed candidates from bounded evidence only.
    ///
    /// # Errors
    ///
    /// Returns an extraction error when bounded evidence cannot be processed.
    fn extract(
        &self,
        request: &ExtractionRequest,
    ) -> Result<Vec<ExtractionCandidate>, ExtractionError>;
}

/// Validates an extraction request before it reaches a provider.
///
/// # Errors
///
/// Returns [`ExtractionError`] for unbounded/empty evidence or an invalid candidate limit.
pub fn validate_request(request: &ExtractionRequest) -> Result<(), ExtractionError> {
    let bytes = request
        .evidence
        .iter()
        .map(|evidence| evidence.content.len())
        .sum::<usize>();
    if request.evidence.is_empty()
        || bytes > MAX_EXTRACTION_EVIDENCE_BYTES
        || request
            .evidence
            .iter()
            .any(|evidence| evidence.source_ref.is_empty())
    {
        return Err(ExtractionError::EvidenceBounds);
    }
    if request.max_candidates == 0 || request.max_candidates > MAX_EXTRACTION_CANDIDATES {
        return Err(ExtractionError::CandidateLimit);
    }

    Ok(())
}

/// Validates candidates against their bounded request evidence before review or serialization.
///
/// # Errors
///
/// Returns [`ExtractionError`] when any candidate exceeds limits or references invalid spans.
pub fn validate_candidates(
    request: &ExtractionRequest,
    candidates: &[ExtractionCandidate],
) -> Result<(), ExtractionError> {
    validate_request(request)?;
    if candidates.len() > request.max_candidates {
        return Err(ExtractionError::CandidateLimit);
    }
    for candidate in candidates {
        if candidate.content.is_empty()
            || candidate.content.len() > MAX_EXTRACTION_EVIDENCE_BYTES
            || candidate.rationale.is_empty()
            || candidate.evidence_spans.is_empty()
            || candidate.suggested_scope.validate().is_err()
            || candidate.evidence_spans.iter().any(|span| {
                request
                    .evidence
                    .get(span.evidence_index)
                    .is_none_or(|evidence| {
                        span.start >= span.end || span.end > evidence.content.len()
                    })
            })
        {
            return Err(ExtractionError::CandidateInvalid);
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::ScopeId;

    #[test]
    fn candidates_are_serializable_and_must_reference_bounded_evidence() {
        let request = ExtractionRequest {
            evidence: vec![SourceEvidence {
                source_kind: SourceKind::File,
                source_ref: "file:src/lib.rs".to_owned(),
                content: "the store uses append-only events".to_owned(),
            }],
            max_candidates: 1,
        };
        let candidate = ExtractionCandidate {
            content: "storage is append-only".to_owned(),
            kind: MemoryKind::Fact,
            validity: CandidateValidity {
                valid_from_unix: 0,
                valid_to_unix: None,
                ingested_at_unix: 0,
            },
            evidence_spans: vec![EvidenceSpan {
                evidence_index: 0,
                start: 0,
                end: 9,
            }],
            confidence_percent: 80,
            rationale: "explicit implementation statement".to_owned(),
            suggested_scope: MemoryScope::repository(ScopeId::new("repo").expect("constant scope")),
        };

        validate_candidates(&request, std::slice::from_ref(&candidate))
            .expect("candidate is bounded");
        assert_eq!(
            serde_json::from_str::<ExtractionCandidate>(
                &serde_json::to_string(&candidate).expect("serialize")
            )
            .expect("deserialize"),
            candidate
        );
        assert!(
            validate_candidates(
                &request,
                &[ExtractionCandidate {
                    evidence_spans: vec![EvidenceSpan {
                        evidence_index: 1,
                        start: 0,
                        end: 1
                    }],
                    ..candidate
                }]
            )
            .is_err()
        );
    }
}
