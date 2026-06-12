// SPDX-License-Identifier: MIT

//! Consolidation and summarisation drift controls.

use crate::model::{ConsolidationRef, MemoryItem};

/// Policy limiting semantic drift from repeated summarisation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ConsolidationPolicy {
    /// Maximum allowed summarisation/consolidation generations from raw observations.
    pub max_resummarization_depth: u16,
}

impl Default for ConsolidationPolicy {
    fn default() -> Self {
        Self {
            max_resummarization_depth: 2,
        }
    }
}

/// Reason a consolidation request was denied.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ConsolidationDenial {
    /// Consolidation cannot run without source memories.
    NoSources,
    /// The next consolidation would exceed the configured depth cap.
    ResummarizationDepthExceeded {
        /// Maximum allowed depth.
        max_depth: u16,
        /// Depth requested by the proposed consolidation.
        requested_depth: u16,
    },
}

/// Decision returned before an auto-consolidated memory is written.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ConsolidationDecision {
    /// Consolidation is allowed with the attached lineage metadata.
    Allowed(ConsolidationRef),
    /// Consolidation was denied before a summary could be produced.
    Denied(ConsolidationDenial),
}

/// Plans consolidation lineage and enforces the resummarisation-depth cap.
#[must_use]
pub fn plan_consolidation(
    sources: &[MemoryItem],
    policy: ConsolidationPolicy,
) -> ConsolidationDecision {
    if sources.is_empty() {
        return ConsolidationDecision::Denied(ConsolidationDenial::NoSources);
    }

    let max_source_depth = sources
        .iter()
        .filter_map(|item| {
            item.consolidation
                .as_ref()
                .map(|consolidation| consolidation.resummarization_depth)
        })
        .max()
        .unwrap_or(0);
    let requested_depth = max_source_depth.saturating_add(1);

    if requested_depth > policy.max_resummarization_depth {
        return ConsolidationDecision::Denied(ConsolidationDenial::ResummarizationDepthExceeded {
            max_depth: policy.max_resummarization_depth,
            requested_depth,
        });
    }

    ConsolidationDecision::Allowed(ConsolidationRef {
        source_memory_ids: sources.iter().map(|item| item.id).collect(),
        resummarization_depth: requested_depth,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{
        CURRENT_MEMORY_SCHEMA_VERSION, CredenceTier, MemoryId, MemoryKind, Provenance, SourceKind,
        TemporalBounds, Tier,
    };
    use time::OffsetDateTime;

    fn memory(content: &str, consolidation: Option<ConsolidationRef>) -> MemoryItem {
        MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            id: MemoryId::new_v7(),
            content: content.to_owned(),
            kind: MemoryKind::Fact,
            compaction: None,
            consolidation,
            embedding_ref: None,
            provenance: Provenance::new(SourceKind::User, None, "consolidation-test"),
            timestamps: TemporalBounds::open_from(
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ),
            tier: Tier::Warm,
            credence: CredenceTier::FirmAuthoritative,
            significance: 1.0,
            base_significance: 1.0,
            credence_floor: Tier::Warm,
            access_events: Vec::new(),
        }
    }

    #[test]
    fn raw_sources_consolidate_to_depth_one() {
        let first = memory("first", None);
        let second = memory("second", None);
        let decision = plan_consolidation(
            &[first.clone(), second.clone()],
            ConsolidationPolicy::default(),
        );

        assert_eq!(
            decision,
            ConsolidationDecision::Allowed(ConsolidationRef {
                source_memory_ids: vec![first.id, second.id],
                resummarization_depth: 1,
            })
        );
    }

    #[test]
    fn resummarization_depth_is_capped() {
        let raw = memory("raw", None);
        let first_summary = memory(
            "summary",
            Some(ConsolidationRef {
                source_memory_ids: vec![raw.id],
                resummarization_depth: 2,
            }),
        );
        let decision = plan_consolidation(
            &[first_summary],
            ConsolidationPolicy {
                max_resummarization_depth: 2,
            },
        );

        assert_eq!(
            decision,
            ConsolidationDecision::Denied(ConsolidationDenial::ResummarizationDepthExceeded {
                max_depth: 2,
                requested_depth: 3,
            })
        );
    }

    #[test]
    fn consolidation_requires_sources() {
        let decision = plan_consolidation(&[], ConsolidationPolicy::default());

        assert_eq!(
            decision,
            ConsolidationDecision::Denied(ConsolidationDenial::NoSources)
        );
    }
}
