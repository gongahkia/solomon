// SPDX-License-Identifier: MIT

//! Reconstruction trigger and gating primitives.

use crate::model::{MemoryId, Provenance, SourceKind};
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

/// Caller mode used by the reconstruction gate.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReconstructionMode {
    /// Ordinary recall/read path. Reconstruction must not run.
    PlainRead,
    /// Caller explicitly requested a re-validation/reconstruction step.
    ExplicitRevalidation,
}

/// Result of evaluating reconstruction triggers against the gate.
#[derive(Clone, Debug, PartialEq)]
pub struct ReconstructionGateDecision {
    /// Triggers considered by the gate.
    pub triggers: Vec<ReconstructionTrigger>,
    /// Whether reconstruction work is allowed to run now.
    pub may_run: bool,
}

/// Planned re-validation action for a reconstruction trigger.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RevalidationAction {
    /// Re-read an external source reference.
    ReReadSource {
        /// Memory being re-validated.
        memory_id: MemoryId,
        /// Source kind to re-read.
        source_kind: SourceKind,
        /// Stable source reference.
        source_ref: String,
    },
    /// Re-query the graph substrate for the memory.
    QueryGraph {
        /// Memory being re-validated.
        memory_id: MemoryId,
        /// Graph reference or query key.
        graph_ref: String,
    },
    /// Ask the caller or a human to confirm the memory.
    SurfaceToCaller {
        /// Memory needing confirmation.
        memory_id: MemoryId,
    },
}

/// Re-validation hook that plans how a trigger should be checked.
pub trait RevalidationHook {
    /// Plans a re-validation action.
    fn plan_revalidation(
        &self,
        trigger: &ReconstructionTrigger,
        provenance: &Provenance,
    ) -> RevalidationAction;
}

/// Default provenance-driven re-validation planner.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct DefaultRevalidationHook;

impl RevalidationHook for DefaultRevalidationHook {
    fn plan_revalidation(
        &self,
        trigger: &ReconstructionTrigger,
        provenance: &Provenance,
    ) -> RevalidationAction {
        let Some(source_ref) = provenance.source_ref.clone() else {
            return RevalidationAction::SurfaceToCaller {
                memory_id: trigger.memory_id,
            };
        };

        if source_ref.starts_with("graph:") {
            return RevalidationAction::QueryGraph {
                memory_id: trigger.memory_id,
                graph_ref: source_ref,
            };
        }

        match provenance.source_kind {
            SourceKind::File | SourceKind::Tool | SourceKind::Web => {
                RevalidationAction::ReReadSource {
                    memory_id: trigger.memory_id,
                    source_kind: provenance.source_kind,
                    source_ref,
                }
            }
            SourceKind::User | SourceKind::Agent => RevalidationAction::SurfaceToCaller {
                memory_id: trigger.memory_id,
            },
        }
    }
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

/// Evaluates reconstruction triggers without executing reconstruction.
#[must_use]
pub fn evaluate_reconstruction_gate(
    triggers: &[ReconstructionTrigger],
    mode: ReconstructionMode,
) -> ReconstructionGateDecision {
    ReconstructionGateDecision {
        triggers: triggers.to_vec(),
        may_run: mode == ReconstructionMode::ExplicitRevalidation && !triggers.is_empty(),
    }
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

    #[test]
    fn reconstruction_gate_never_runs_on_plain_read() {
        let stale = candidate(true);
        let triggers = triggers_from_recall(&[stale]);
        let plain_read = evaluate_reconstruction_gate(&triggers, ReconstructionMode::PlainRead);
        let explicit =
            evaluate_reconstruction_gate(&triggers, ReconstructionMode::ExplicitRevalidation);

        assert!(!plain_read.may_run);
        assert_eq!(plain_read.triggers.len(), 1);
        assert!(explicit.may_run);
    }

    #[test]
    fn default_revalidation_hook_plans_source_graph_or_caller_checks() {
        let stale = candidate(true);
        let trigger = triggers_from_recall(&[stale])[0];
        let hook = DefaultRevalidationHook;
        let file = Provenance::new(SourceKind::File, Some("/tmp/source.md".to_owned()), "test");
        let graph = Provenance::new(SourceKind::Tool, Some("graph:claim:123".to_owned()), "test");
        let user = Provenance::new(SourceKind::User, None, "test");

        assert_eq!(
            hook.plan_revalidation(&trigger, &file),
            RevalidationAction::ReReadSource {
                memory_id: trigger.memory_id,
                source_kind: SourceKind::File,
                source_ref: "/tmp/source.md".to_owned(),
            }
        );
        assert_eq!(
            hook.plan_revalidation(&trigger, &graph),
            RevalidationAction::QueryGraph {
                memory_id: trigger.memory_id,
                graph_ref: "graph:claim:123".to_owned(),
            }
        );
        assert_eq!(
            hook.plan_revalidation(&trigger, &user),
            RevalidationAction::SurfaceToCaller {
                memory_id: trigger.memory_id,
            }
        );
    }
}
