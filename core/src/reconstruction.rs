// SPDX-License-Identifier: MIT

//! Reconstruction trigger and gating primitives.

use crate::model::{CredenceTier, MemoryId, MemoryItem, Provenance, SourceKind, Tier};
use crate::retrieval::RecallCandidate;
use std::collections::BTreeSet;

/// Tag attached to reconstruction proposals that have not been corroborated.
pub const QUARANTINE_TAG: &str = "reconstruction:quarantine";

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

/// Quarantined reconstruction proposal.
#[derive(Clone, Debug, PartialEq)]
pub struct QuarantinedProposal {
    /// Proposed memory update, held at low trust and cold accessibility.
    pub item: MemoryItem,
    /// Existing memory this proposal may supersede after corroboration.
    pub supersedes: MemoryId,
    /// Tags carried by this proposal.
    pub tags: BTreeSet<String>,
}

/// Evidence that may corroborate a quarantined reconstruction proposal.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CorroborationSignal {
    /// Independent observation that agrees with the proposal.
    ConsistentObservation {
        /// Source kind that produced the observation.
        source_kind: SourceKind,
    },
    /// Human or caller explicitly confirmed the proposal.
    HumanConfirmed,
    /// A trusted source produced the same observation.
    HighCredenceSource {
        /// Source kind that produced the observation.
        source_kind: SourceKind,
        /// Credence assigned to that source.
        credence: CredenceTier,
    },
}

/// Policy controlling when quarantined proposals may be promoted.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CorroborationPolicy {
    /// Minimum number of independent consistent observations needed for promotion.
    pub required_consistent_observations: usize,
    /// Minimum credence that allows a single high-credence source to promote.
    pub high_credence_threshold: CredenceTier,
    /// Credence assigned when promotion is based on repeated consistent observations.
    pub observation_promotion_credence: CredenceTier,
    /// Accessibility tier assigned to promoted proposals.
    pub promoted_tier: Tier,
}

impl Default for CorroborationPolicy {
    fn default() -> Self {
        Self {
            required_consistent_observations: 2,
            high_credence_threshold: CredenceTier::VerifiedSource,
            observation_promotion_credence: CredenceTier::ModelInferred,
            promoted_tier: Tier::Warm,
        }
    }
}

/// Why a quarantined proposal satisfied corroboration.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CorroborationBasis {
    /// Human or caller confirmation.
    HumanConfirmation,
    /// A high-credence source confirmed the proposal.
    HighCredenceSource {
        /// Source kind that confirmed the proposal.
        source_kind: SourceKind,
        /// Credence assigned to that source.
        credence: CredenceTier,
    },
    /// Enough independent consistent observations agreed with the proposal.
    ConsistentObservations {
        /// Number of observations counted.
        count: usize,
    },
}

/// Result of evaluating proposal corroboration.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CorroborationDecision {
    /// Evidence basis that allowed promotion, if any.
    pub basis: Option<CorroborationBasis>,
    /// Credence the proposal may receive after promotion.
    pub promoted_credence: Option<CredenceTier>,
    /// Tier the proposal may enter after promotion.
    pub promoted_tier: Option<Tier>,
}

impl CorroborationDecision {
    /// Returns true when the proposal may leave quarantine.
    #[must_use]
    pub const fn may_promote(self) -> bool {
        self.promoted_credence.is_some()
    }
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

/// Quarantines a proposed reconstruction update.
#[must_use]
pub fn quarantine_proposal(mut item: MemoryItem, supersedes: MemoryId) -> QuarantinedProposal {
    item.credence = CredenceTier::Unverified;
    item.tier = Tier::Cold;
    item.credence_floor = Tier::Cold;

    QuarantinedProposal {
        item,
        supersedes,
        tags: BTreeSet::from([QUARANTINE_TAG.to_owned()]),
    }
}

/// Evaluates whether corroboration signals are enough to promote a proposal.
#[must_use]
pub fn evaluate_corroboration(
    signals: &[CorroborationSignal],
    policy: CorroborationPolicy,
) -> CorroborationDecision {
    let human_confirmed = signals
        .iter()
        .any(|signal| matches!(signal, CorroborationSignal::HumanConfirmed));
    if human_confirmed {
        return CorroborationDecision {
            basis: Some(CorroborationBasis::HumanConfirmation),
            promoted_credence: Some(CredenceTier::FirmAuthoritative),
            promoted_tier: Some(policy.promoted_tier),
        };
    }

    if let Some((source_kind, credence)) = signals.iter().find_map(|signal| match signal {
        CorroborationSignal::HighCredenceSource {
            source_kind,
            credence,
        } if *credence >= policy.high_credence_threshold => Some((*source_kind, *credence)),
        _ => None,
    }) {
        return CorroborationDecision {
            basis: Some(CorroborationBasis::HighCredenceSource {
                source_kind,
                credence,
            }),
            promoted_credence: Some(credence),
            promoted_tier: Some(policy.promoted_tier),
        };
    }

    let consistent_observations = signals
        .iter()
        .filter(|signal| matches!(signal, CorroborationSignal::ConsistentObservation { .. }))
        .count();
    let required_observations = policy.required_consistent_observations.max(2);
    if consistent_observations >= required_observations {
        return CorroborationDecision {
            basis: Some(CorroborationBasis::ConsistentObservations {
                count: consistent_observations,
            }),
            promoted_credence: Some(policy.observation_promotion_credence),
            promoted_tier: Some(policy.promoted_tier),
        };
    }

    CorroborationDecision {
        basis: None,
        promoted_credence: None,
        promoted_tier: None,
    }
}

/// Returns a promoted copy of a quarantined proposal when corroboration permits it.
#[must_use]
pub fn promote_corroborated_proposal(
    proposal: &QuarantinedProposal,
    signals: &[CorroborationSignal],
    policy: CorroborationPolicy,
) -> Option<MemoryItem> {
    let decision = evaluate_corroboration(signals, policy);
    let (Some(promoted_credence), Some(promoted_tier)) =
        (decision.promoted_credence, decision.promoted_tier)
    else {
        return None;
    };

    let mut item = proposal.item.clone();
    item.credence = promoted_credence;
    item.tier = item.clamp_tier_to_floor(promoted_tier);
    Some(item)
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

    #[test]
    fn quarantine_proposal_downgrades_and_tags_update() {
        let proposed = candidate(false).item;
        let superseded = MemoryId::new_v7();
        let quarantined = quarantine_proposal(proposed, superseded);

        assert_eq!(quarantined.item.credence, CredenceTier::Unverified);
        assert_eq!(quarantined.item.tier, Tier::Cold);
        assert_eq!(quarantined.item.credence_floor, Tier::Cold);
        assert_eq!(quarantined.supersedes, superseded);
        assert!(quarantined.tags.contains(QUARANTINE_TAG));
    }

    #[test]
    fn corroboration_rejects_single_consistent_observation() {
        let decision = evaluate_corroboration(
            &[CorroborationSignal::ConsistentObservation {
                source_kind: SourceKind::Tool,
            }],
            CorroborationPolicy::default(),
        );

        assert!(!decision.may_promote());
        assert_eq!(decision.basis, None);
    }

    #[test]
    fn corroboration_allows_second_consistent_observation() {
        let decision = evaluate_corroboration(
            &[
                CorroborationSignal::ConsistentObservation {
                    source_kind: SourceKind::File,
                },
                CorroborationSignal::ConsistentObservation {
                    source_kind: SourceKind::Tool,
                },
            ],
            CorroborationPolicy::default(),
        );

        assert!(decision.may_promote());
        assert_eq!(
            decision.basis,
            Some(CorroborationBasis::ConsistentObservations { count: 2 })
        );
        assert_eq!(
            decision.promoted_credence,
            Some(CredenceTier::ModelInferred)
        );
    }

    #[test]
    fn corroboration_allows_human_confirmation() {
        let decision = evaluate_corroboration(
            &[CorroborationSignal::HumanConfirmed],
            CorroborationPolicy::default(),
        );

        assert!(decision.may_promote());
        assert_eq!(decision.basis, Some(CorroborationBasis::HumanConfirmation));
        assert_eq!(
            decision.promoted_credence,
            Some(CredenceTier::FirmAuthoritative)
        );
    }

    #[test]
    fn corroboration_allows_high_credence_source() {
        let decision = evaluate_corroboration(
            &[CorroborationSignal::HighCredenceSource {
                source_kind: SourceKind::File,
                credence: CredenceTier::VerifiedSource,
            }],
            CorroborationPolicy::default(),
        );

        assert!(decision.may_promote());
        assert_eq!(
            decision.basis,
            Some(CorroborationBasis::HighCredenceSource {
                source_kind: SourceKind::File,
                credence: CredenceTier::VerifiedSource,
            })
        );
        assert_eq!(
            decision.promoted_credence,
            Some(CredenceTier::VerifiedSource)
        );
    }

    #[test]
    fn promote_corroborated_proposal_returns_promoted_copy() {
        let quarantined = quarantine_proposal(candidate(false).item, MemoryId::new_v7());
        let promoted = promote_corroborated_proposal(
            &quarantined,
            &[CorroborationSignal::HumanConfirmed],
            CorroborationPolicy::default(),
        )
        .expect("human confirmation should promote proposal");

        assert_eq!(promoted.id, quarantined.item.id);
        assert_eq!(promoted.credence, CredenceTier::FirmAuthoritative);
        assert_eq!(promoted.tier, Tier::Warm);
        assert_eq!(quarantined.item.credence, CredenceTier::Unverified);
        assert_eq!(quarantined.item.tier, Tier::Cold);
    }
}
