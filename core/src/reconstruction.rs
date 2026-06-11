// SPDX-License-Identifier: MIT

//! Reconstruction trigger and gating primitives.

use crate::model::MemoryId;
use crate::retrieval::RecallCandidate;

/// Reason a memory should be considered for reconstruction.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReconstructionTriggerReason {
    /// Recall surfaced a significant memory that appears old and not recently validated.
    LoadBearingPossiblyStale,
}

/// Pure trigger emitted from recall results.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ReconstructionTrigger {
    /// Memory that may need re-validation.
    pub memory_id: MemoryId,
    /// Trigger reason.
    pub reason: ReconstructionTriggerReason,
    /// Significance score observed at recall time.
    pub significance_score: f64,
}

/// Derives reconstruction triggers from recall candidates without running reconstruction.
#[must_use]
pub fn triggers_from_recall(candidates: &[RecallCandidate]) -> Vec<ReconstructionTrigger> {
    candidates
        .iter()
        .filter(|candidate| candidate.load_bearing_possibly_stale)
        .map(|candidate| ReconstructionTrigger {
            memory_id: candidate.id,
            reason: ReconstructionTriggerReason::LoadBearingPossiblyStale,
            significance_score: candidate.significance_score,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{
        CURRENT_MEMORY_SCHEMA_VERSION, CredenceTier, MemoryItem, Provenance, SourceKind,
        TemporalBounds, Tier,
    };
    use crate::retrieval::{RecallCandidate, RecallCandidateCurrency, RecallCandidateSource};
    use time::OffsetDateTime;

    fn candidate(load_bearing_possibly_stale: bool) -> RecallCandidate {
        let now = OffsetDateTime::UNIX_EPOCH;
        let item = MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            id: MemoryId::new_v7(),
            content: "memory".to_owned(),
            compaction: None,
            embedding_ref: None,
            provenance: Provenance::new(SourceKind::User, None, "reconstruction-test"),
            timestamps: TemporalBounds::open_from(now, now),
            tier: Tier::Warm,
            credence: CredenceTier::FirmAuthoritative,
            significance: 3.0,
            credence_floor: Tier::Warm,
            access_events: Vec::new(),
        };

        RecallCandidate {
            id: item.id,
            item: item.clone(),
            provenance: item.provenance.clone(),
            tier: item.tier,
            currency: RecallCandidateCurrency::Current,
            load_bearing_possibly_stale,
            cold_tier_retrieval: false,
            vector_distance: 0.0,
            similarity_score: 1.0,
            significance_score: 3.0,
            recency_score: 0.0,
            graph_score: 0.0,
            source: RecallCandidateSource::Vector,
            rank_score: 4.0,
        }
    }

    #[test]
    fn triggers_from_recall_only_uses_stale_load_bearing_candidates() {
        let stale = candidate(true);
        let fresh = candidate(false);
        let triggers = triggers_from_recall(&[stale.clone(), fresh]);

        assert_eq!(triggers.len(), 1);
        assert_eq!(triggers[0].memory_id, stale.id);
        assert_eq!(
            triggers[0].reason,
            ReconstructionTriggerReason::LoadBearingPossiblyStale
        );
        assert!((triggers[0].significance_score - 3.0).abs() < f64::EPSILON);
    }
}
