// SPDX-License-Identifier: MIT

//! Explainable duplicate and likely-supersession detection without mutation.

use crate::extraction::SourceEvidence;
use crate::model::SourceKind;
use serde::{Deserialize, Serialize};

/// Caller-supplied comparison context; never an instruction to invalidate memory.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CaptureComparison {
    /// Whether external evidence explicitly contradicts the prior observation.
    pub contradicts_prior: bool,
}

/// Why two captures are candidates for a non-destructive supersession review.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LikelySupersessionReason {
    /// The same source reference changed content.
    EditedSource,
    /// Equivalent file evidence moved to a new reference.
    FileMove,
    /// Caller marked the later evidence as contradictory.
    Contradiction,
    /// A tool emitted a changed result for the same source reference.
    RepeatedToolEvent,
}

/// Classification result only; storage invalidation requires a separate explicit action.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureRelation {
    /// Semantically identical bounded evidence.
    Duplicate,
    /// Potential replacement requiring human/policy review.
    LikelySupersession {
        /// Explainable reason for review rather than implicit invalidation.
        reason: LikelySupersessionReason,
    },
    /// No deduplication relationship was detected.
    Distinct,
}

/// Classifies bounded evidence deterministically without persisting or invalidating anything.
#[must_use]
pub fn classify_capture(
    prior: &SourceEvidence,
    incoming: &SourceEvidence,
    comparison: CaptureComparison,
) -> CaptureRelation {
    if comparison.contradicts_prior {
        return CaptureRelation::LikelySupersession {
            reason: LikelySupersessionReason::Contradiction,
        };
    }
    let same_content = normalize(&prior.content) == normalize(&incoming.content);
    if prior.source_ref == incoming.source_ref && prior.source_kind == incoming.source_kind {
        return if same_content {
            CaptureRelation::Duplicate
        } else if prior.source_kind == SourceKind::Tool {
            CaptureRelation::LikelySupersession {
                reason: LikelySupersessionReason::RepeatedToolEvent,
            }
        } else {
            CaptureRelation::LikelySupersession {
                reason: LikelySupersessionReason::EditedSource,
            }
        };
    }
    if same_content
        && prior.source_kind == SourceKind::File
        && incoming.source_kind == SourceKind::File
    {
        return CaptureRelation::LikelySupersession {
            reason: LikelySupersessionReason::FileMove,
        };
    }

    CaptureRelation::Distinct
}

fn normalize(value: &str) -> String {
    value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn evidence(kind: SourceKind, source_ref: &str, content: &str) -> SourceEvidence {
        SourceEvidence {
            source_kind: kind,
            source_ref: source_ref.to_owned(),
            content: content.to_owned(),
        }
    }

    #[test]
    fn classifies_edits_moves_contradictions_and_repeated_tool_events_without_mutation() {
        let file = evidence(SourceKind::File, "file:a.rs", "value is one");

        assert_eq!(
            classify_capture(
                &file,
                &evidence(SourceKind::File, "file:a.rs", "value  is one"),
                CaptureComparison::default()
            ),
            CaptureRelation::Duplicate
        );
        assert!(matches!(
            classify_capture(
                &file,
                &evidence(SourceKind::File, "file:a.rs", "value is two"),
                CaptureComparison::default()
            ),
            CaptureRelation::LikelySupersession {
                reason: LikelySupersessionReason::EditedSource
            }
        ));
        assert!(matches!(
            classify_capture(
                &file,
                &evidence(SourceKind::File, "file:b.rs", "value is one"),
                CaptureComparison::default()
            ),
            CaptureRelation::LikelySupersession {
                reason: LikelySupersessionReason::FileMove
            }
        ));
        assert!(matches!(
            classify_capture(
                &file,
                &evidence(SourceKind::Web, "web:1", "value is two"),
                CaptureComparison {
                    contradicts_prior: true
                }
            ),
            CaptureRelation::LikelySupersession {
                reason: LikelySupersessionReason::Contradiction
            }
        ));
        assert!(matches!(
            classify_capture(
                &evidence(SourceKind::Tool, "tool:build", "failed"),
                &evidence(SourceKind::Tool, "tool:build", "passed"),
                CaptureComparison::default()
            ),
            CaptureRelation::LikelySupersession {
                reason: LikelySupersessionReason::RepeatedToolEvent
            }
        ));
    }
}
