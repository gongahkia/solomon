// SPDX-License-Identifier: MIT

//! Reconstruction trigger and gating primitives.

use crate::model::{CredenceTier, MemoryId, MemoryItem, Provenance, SourceKind, Tier};
use crate::retrieval::RecallCandidate;
use crate::storage::MemoryWriteEvent;
use std::collections::{BTreeMap, BTreeSet};
use time::{Duration, OffsetDateTime};

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

/// Windowed reconstruction budget configuration.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReconstructionBudgetConfig {
    /// Maximum number of re-validations allowed inside the budget window.
    pub max_revalidations_per_window: usize,
    /// Maximum estimated cost units allowed inside the budget window.
    pub max_cost_per_window: u64,
    /// Cost used when a trigger has no explicit cost estimate.
    pub default_cost_per_revalidation: u64,
    /// Window used for rate and cost accounting.
    pub window: Duration,
}

impl Default for ReconstructionBudgetConfig {
    fn default() -> Self {
        Self {
            max_revalidations_per_window: 8,
            max_cost_per_window: 100,
            default_cost_per_revalidation: 1,
            window: Duration::minutes(1),
        }
    }
}

/// A reconstruction or re-validation already attempted inside a budget window.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReconstructionAttempt {
    /// Time the attempt was started.
    pub occurred_at: OffsetDateTime,
    /// Estimated cost units consumed by the attempt.
    pub estimated_cost: u64,
}

/// Estimated cost for a pending reconstruction trigger.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReconstructionCostEstimate {
    /// Trigger memory id.
    pub memory_id: MemoryId,
    /// Estimated cost units for re-validating this memory.
    pub estimated_cost: u64,
}

/// Reason a reconstruction trigger was deferred by the budget.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReconstructionBudgetDenial {
    /// The rate limit for the window has already been reached.
    RateLimitExceeded {
        /// Maximum allowed re-validations for the window.
        max_revalidations_per_window: usize,
        /// Re-validations already used or reserved in the window.
        used_revalidations: usize,
    },
    /// The estimated cost cap for the window has already been reached.
    CostCapExceeded {
        /// Maximum allowed estimated cost units for the window.
        max_cost_per_window: u64,
        /// Estimated cost units already used or reserved in the window.
        used_cost: u64,
        /// Estimated cost units requested by the deferred trigger.
        requested_cost: u64,
    },
}

/// Reconstruction trigger deferred by the budget.
#[derive(Clone, Debug, PartialEq)]
pub struct DeferredReconstructionTrigger {
    /// Trigger that was not allowed to run now.
    pub trigger: ReconstructionTrigger,
    /// Estimated cost units for this trigger.
    pub estimated_cost: u64,
    /// Budget reason for deferring this trigger.
    pub reason: ReconstructionBudgetDenial,
}

/// Result of applying rate and cost limits to reconstruction triggers.
#[derive(Clone, Debug, PartialEq)]
pub struct ReconstructionBudgetDecision {
    /// Triggers allowed to run now.
    pub allowed: Vec<ReconstructionTrigger>,
    /// Triggers deferred by rate or cost budget.
    pub deferred: Vec<DeferredReconstructionTrigger>,
    /// Re-validations already present in the active window before this decision.
    pub used_revalidations_before: usize,
    /// Estimated cost already present in the active window before this decision.
    pub used_cost_before: u64,
    /// Re-validations used after reserving allowed triggers.
    pub used_revalidations_after: usize,
    /// Estimated cost used after reserving allowed triggers.
    pub used_cost_after: u64,
}

/// Optional idle/background reconstruction planning config.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BackgroundReconstructionConfig {
    /// Whether idle-time re-validation planning is enabled.
    pub validate_on_idle: bool,
    /// Maximum stale load-bearing triggers to reserve in one idle pass.
    pub max_idle_triggers: usize,
}

impl Default for BackgroundReconstructionConfig {
    fn default() -> Self {
        Self {
            validate_on_idle: false,
            max_idle_triggers: 4,
        }
    }
}

/// Idle/background re-validation plan.
#[derive(Clone, Debug, PartialEq)]
pub struct BackgroundReconstructionPlan {
    /// Re-validation actions allowed by the idle config and budget.
    pub actions: Vec<RevalidationAction>,
    /// Budget decision for considered triggers.
    pub budget: ReconstructionBudgetDecision,
    /// True when planning was skipped because idle validation is disabled.
    pub skipped_disabled: bool,
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

/// Strategy used to re-validate a memory from a provenance type.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RevalidationStrategy {
    /// Re-read the provenance source reference.
    ReReadSource,
    /// Query the graph substrate using the provenance source reference.
    QueryGraph,
    /// Ask the caller or a human to confirm the memory.
    SurfaceToCaller,
}

impl RevalidationStrategy {
    fn plan(
        self,
        trigger: &ReconstructionTrigger,
        provenance: &Provenance,
        source_ref: Option<String>,
    ) -> RevalidationAction {
        match (self, source_ref) {
            (Self::ReReadSource, Some(source_ref)) => RevalidationAction::ReReadSource {
                memory_id: trigger.memory_id,
                source_kind: provenance.source_kind,
                source_ref,
            },
            (Self::QueryGraph, Some(graph_ref)) => RevalidationAction::QueryGraph {
                memory_id: trigger.memory_id,
                graph_ref,
            },
            _ => RevalidationAction::SurfaceToCaller {
                memory_id: trigger.memory_id,
            },
        }
    }
}

/// Re-validation strategies selected by provenance source kind.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RevalidationStrategyConfig {
    /// Strategy for user-provided memories.
    pub user: RevalidationStrategy,
    /// Strategy for agent-authored memories.
    pub agent: RevalidationStrategy,
    /// Strategy for file-backed memories.
    pub file: RevalidationStrategy,
    /// Strategy for web-backed memories.
    pub web: RevalidationStrategy,
    /// Strategy for tool-output memories.
    pub tool: RevalidationStrategy,
}

impl Default for RevalidationStrategyConfig {
    fn default() -> Self {
        Self {
            user: RevalidationStrategy::SurfaceToCaller,
            agent: RevalidationStrategy::SurfaceToCaller,
            file: RevalidationStrategy::ReReadSource,
            web: RevalidationStrategy::ReReadSource,
            tool: RevalidationStrategy::ReReadSource,
        }
    }
}

impl RevalidationStrategyConfig {
    /// Returns the configured strategy for a source kind.
    #[must_use]
    pub const fn strategy_for(&self, source_kind: SourceKind) -> RevalidationStrategy {
        match source_kind {
            SourceKind::User => self.user,
            SourceKind::Agent => self.agent,
            SourceKind::File => self.file,
            SourceKind::Web => self.web,
            SourceKind::Tool => self.tool,
        }
    }
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

/// Source/tool boundary used by explicit reconstruction.
///
/// Plain recall never calls this trait. It is only invoked by an explicit
/// re-validation/reconstruction API after the gate and budget allow a trigger.
pub trait RevalidationSource {
    /// Revalidates `original` using a planned action and returns a proposed replacement write.
    ///
    /// Returning `None` leaves the proposal unwritten.
    fn revalidate(
        &self,
        action: &RevalidationAction,
        original: &MemoryItem,
        now: OffsetDateTime,
    ) -> Option<MemoryWriteEvent>;
}

/// Configurable provenance-driven re-validation planner.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ConfigurableRevalidationHook {
    /// Per-provenance re-validation strategy config.
    pub config: RevalidationStrategyConfig,
}

impl ConfigurableRevalidationHook {
    /// Creates a configurable re-validation hook.
    #[must_use]
    pub const fn new(config: RevalidationStrategyConfig) -> Self {
        Self { config }
    }
}

impl RevalidationHook for ConfigurableRevalidationHook {
    fn plan_revalidation(
        &self,
        trigger: &ReconstructionTrigger,
        provenance: &Provenance,
    ) -> RevalidationAction {
        let source_ref = provenance.source_ref.clone();

        if let Some(graph_ref) = source_ref
            .as_ref()
            .filter(|source_ref| source_ref.starts_with("graph:"))
        {
            return RevalidationAction::QueryGraph {
                memory_id: trigger.memory_id,
                graph_ref: graph_ref.clone(),
            };
        }

        self.config
            .strategy_for(provenance.source_kind)
            .plan(trigger, provenance, source_ref)
    }
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
        ConfigurableRevalidationHook::default().plan_revalidation(trigger, provenance)
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

/// Applies rate and cost budget limits to pending reconstruction triggers.
#[must_use]
pub fn apply_reconstruction_budget(
    triggers: &[ReconstructionTrigger],
    cost_estimates: &[ReconstructionCostEstimate],
    recent_attempts: &[ReconstructionAttempt],
    now: OffsetDateTime,
    config: ReconstructionBudgetConfig,
) -> ReconstructionBudgetDecision {
    let cost_by_memory_id = cost_estimates
        .iter()
        .map(|estimate| (estimate.memory_id, estimate.estimated_cost))
        .collect::<BTreeMap<_, _>>();
    let active_attempts = recent_attempts
        .iter()
        .filter(|attempt| attempt_in_budget_window(**attempt, now, config.window));
    let mut used_revalidations = 0;
    let mut used_cost = 0_u64;

    for attempt in active_attempts {
        used_revalidations += 1;
        used_cost = used_cost.saturating_add(attempt.estimated_cost);
    }

    let used_revalidations_before = used_revalidations;
    let used_cost_before = used_cost;
    let mut allowed = Vec::new();
    let mut deferred = Vec::new();

    for trigger in triggers {
        let estimated_cost = cost_by_memory_id
            .get(&trigger.memory_id)
            .copied()
            .unwrap_or(config.default_cost_per_revalidation);

        if used_revalidations >= config.max_revalidations_per_window {
            deferred.push(DeferredReconstructionTrigger {
                trigger: *trigger,
                estimated_cost,
                reason: ReconstructionBudgetDenial::RateLimitExceeded {
                    max_revalidations_per_window: config.max_revalidations_per_window,
                    used_revalidations,
                },
            });
            continue;
        }

        if used_cost.saturating_add(estimated_cost) > config.max_cost_per_window {
            deferred.push(DeferredReconstructionTrigger {
                trigger: *trigger,
                estimated_cost,
                reason: ReconstructionBudgetDenial::CostCapExceeded {
                    max_cost_per_window: config.max_cost_per_window,
                    used_cost,
                    requested_cost: estimated_cost,
                },
            });
            continue;
        }

        allowed.push(*trigger);
        used_revalidations += 1;
        used_cost = used_cost.saturating_add(estimated_cost);
    }

    ReconstructionBudgetDecision {
        allowed,
        deferred,
        used_revalidations_before,
        used_cost_before,
        used_revalidations_after: used_revalidations,
        used_cost_after: used_cost,
    }
}

/// Plans idle-time re-validations from known stale recall candidates without mutating memory.
#[must_use]
pub fn plan_background_revalidations(
    candidates: &[RecallCandidate],
    hook: &dyn RevalidationHook,
    cost_estimates: &[ReconstructionCostEstimate],
    recent_attempts: &[ReconstructionAttempt],
    now: OffsetDateTime,
    budget_config: ReconstructionBudgetConfig,
    background_config: BackgroundReconstructionConfig,
) -> BackgroundReconstructionPlan {
    if !background_config.validate_on_idle {
        return BackgroundReconstructionPlan {
            actions: Vec::new(),
            budget: apply_reconstruction_budget(
                &[],
                cost_estimates,
                recent_attempts,
                now,
                budget_config,
            ),
            skipped_disabled: true,
        };
    }

    let mut triggers = triggers_from_recall(candidates);
    triggers.truncate(background_config.max_idle_triggers);
    let budget = apply_reconstruction_budget(
        &triggers,
        cost_estimates,
        recent_attempts,
        now,
        budget_config,
    );
    let actions = budget
        .allowed
        .iter()
        .filter_map(|trigger| {
            candidates
                .iter()
                .find(|candidate| candidate.id == trigger.memory_id)
                .map(|candidate| hook.plan_revalidation(trigger, &candidate.provenance))
        })
        .collect();

    BackgroundReconstructionPlan {
        actions,
        budget,
        skipped_disabled: false,
    }
}

fn attempt_in_budget_window(
    attempt: ReconstructionAttempt,
    now: OffsetDateTime,
    window: Duration,
) -> bool {
    window > Duration::ZERO && attempt.occurred_at <= now && attempt.occurred_at >= now - window
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
        CURRENT_MEMORY_SCHEMA_VERSION, CredenceTier, MemoryItem, MemoryKind, Provenance,
        SourceKind, TemporalBounds, Tier,
    };
    use crate::retrieval::{RecallCandidate, RecallCandidateCurrency, RecallCandidateSource};
    use time::OffsetDateTime;

    fn candidate(load_bearing_possibly_stale: bool) -> RecallCandidate {
        let now = OffsetDateTime::UNIX_EPOCH;
        let item = MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            id: MemoryId::new_v7(),
            content: "memory".to_owned(),
            kind: MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            embedding_ref: None,
            provenance: Provenance::new(SourceKind::User, None, "reconstruction-test"),
            timestamps: TemporalBounds::open_from(now, now),
            tier: Tier::Warm,
            credence: CredenceTier::FirmAuthoritative,
            significance: 3.0,
            base_significance: 3.0,
            credence_floor: Tier::Warm,
            access_events: Vec::new(),
        };

        RecallCandidate {
            id: item.id,
            item: item.clone(),
            kind: item.kind,
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
            read_safety_findings: Vec::new(),
        }
    }

    fn trigger() -> ReconstructionTrigger {
        ReconstructionTrigger {
            memory_id: MemoryId::new_v7(),
            reason: ReconstructionTriggerReason::LoadBearingPossiblyStale,
            significance_score: 3.0,
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
    fn reconstruction_budget_limits_revalidation_count() {
        let triggers = vec![trigger(), trigger(), trigger()];
        let decision = apply_reconstruction_budget(
            &triggers,
            &[],
            &[],
            OffsetDateTime::UNIX_EPOCH,
            ReconstructionBudgetConfig {
                max_revalidations_per_window: 2,
                max_cost_per_window: 10,
                default_cost_per_revalidation: 1,
                window: time::Duration::minutes(1),
            },
        );

        assert_eq!(decision.allowed, triggers[..2]);
        assert_eq!(decision.deferred.len(), 1);
        assert_eq!(decision.used_revalidations_after, 2);
        assert_eq!(
            decision.deferred[0].reason,
            ReconstructionBudgetDenial::RateLimitExceeded {
                max_revalidations_per_window: 2,
                used_revalidations: 2,
            }
        );
    }

    #[test]
    fn reconstruction_budget_limits_estimated_cost_with_recent_attempts() {
        let now = OffsetDateTime::UNIX_EPOCH + time::Duration::minutes(5);
        let triggers = vec![trigger()];
        let recent_attempts = vec![
            ReconstructionAttempt {
                occurred_at: now - time::Duration::seconds(30),
                estimated_cost: 4,
            },
            ReconstructionAttempt {
                occurred_at: now - time::Duration::minutes(2),
                estimated_cost: 100,
            },
        ];
        let decision = apply_reconstruction_budget(
            &triggers,
            &[],
            &recent_attempts,
            now,
            ReconstructionBudgetConfig {
                max_revalidations_per_window: 10,
                max_cost_per_window: 5,
                default_cost_per_revalidation: 2,
                window: time::Duration::minutes(1),
            },
        );

        assert!(decision.allowed.is_empty());
        assert_eq!(decision.deferred.len(), 1);
        assert_eq!(decision.used_revalidations_before, 1);
        assert_eq!(decision.used_cost_before, 4);
        assert_eq!(
            decision.deferred[0].reason,
            ReconstructionBudgetDenial::CostCapExceeded {
                max_cost_per_window: 5,
                used_cost: 4,
                requested_cost: 2,
            }
        );
    }

    #[test]
    fn reconstruction_budget_uses_explicit_cost_estimates() {
        let triggers = vec![trigger(), trigger()];
        let estimates = vec![
            ReconstructionCostEstimate {
                memory_id: triggers[0].memory_id,
                estimated_cost: 2,
            },
            ReconstructionCostEstimate {
                memory_id: triggers[1].memory_id,
                estimated_cost: 5,
            },
        ];
        let decision = apply_reconstruction_budget(
            &triggers,
            &estimates,
            &[],
            OffsetDateTime::UNIX_EPOCH,
            ReconstructionBudgetConfig {
                max_revalidations_per_window: 10,
                max_cost_per_window: 6,
                default_cost_per_revalidation: 10,
                window: time::Duration::minutes(1),
            },
        );

        assert_eq!(decision.allowed, vec![triggers[0]]);
        assert_eq!(decision.used_cost_after, 2);
        assert_eq!(decision.deferred.len(), 1);
        assert_eq!(decision.deferred[0].trigger, triggers[1]);
        assert_eq!(
            decision.deferred[0].reason,
            ReconstructionBudgetDenial::CostCapExceeded {
                max_cost_per_window: 6,
                used_cost: 2,
                requested_cost: 5,
            }
        );
    }

    #[test]
    fn background_revalidation_planning_is_disabled_by_default() {
        let stale = candidate(true);
        let plan = plan_background_revalidations(
            &[stale],
            &DefaultRevalidationHook,
            &[],
            &[],
            OffsetDateTime::UNIX_EPOCH,
            ReconstructionBudgetConfig::default(),
            BackgroundReconstructionConfig::default(),
        );

        assert!(plan.skipped_disabled);
        assert!(plan.actions.is_empty());
        assert!(plan.budget.allowed.is_empty());
    }

    #[test]
    fn background_revalidation_plans_idle_actions_with_budget() {
        let stale = candidate(true);
        let second = candidate(true);
        let plan = plan_background_revalidations(
            &[stale.clone(), second],
            &DefaultRevalidationHook,
            &[ReconstructionCostEstimate {
                memory_id: stale.id,
                estimated_cost: 2,
            }],
            &[],
            OffsetDateTime::UNIX_EPOCH,
            ReconstructionBudgetConfig {
                max_revalidations_per_window: 1,
                max_cost_per_window: 10,
                default_cost_per_revalidation: 1,
                window: time::Duration::minutes(1),
            },
            BackgroundReconstructionConfig {
                validate_on_idle: true,
                max_idle_triggers: 2,
            },
        );

        assert!(!plan.skipped_disabled);
        assert_eq!(plan.budget.allowed.len(), 1);
        assert_eq!(
            plan.actions,
            vec![RevalidationAction::SurfaceToCaller {
                memory_id: stale.id,
            }]
        );
        assert_eq!(plan.budget.deferred.len(), 1);
    }

    #[test]
    fn background_revalidation_respects_idle_batch_limit() {
        let first = candidate(true);
        let second = candidate(true);
        let plan = plan_background_revalidations(
            &[first.clone(), second],
            &DefaultRevalidationHook,
            &[],
            &[],
            OffsetDateTime::UNIX_EPOCH,
            ReconstructionBudgetConfig::default(),
            BackgroundReconstructionConfig {
                validate_on_idle: true,
                max_idle_triggers: 1,
            },
        );

        assert_eq!(plan.actions.len(), 1);
        assert_eq!(
            plan.actions[0],
            RevalidationAction::SurfaceToCaller {
                memory_id: first.id,
            }
        );
        assert!(plan.budget.deferred.is_empty());
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
    fn configurable_revalidation_hook_overrides_strategy_by_source_kind() {
        let stale = candidate(true);
        let trigger = triggers_from_recall(&[stale])[0];
        let hook = ConfigurableRevalidationHook::new(RevalidationStrategyConfig {
            web: RevalidationStrategy::SurfaceToCaller,
            file: RevalidationStrategy::QueryGraph,
            ..RevalidationStrategyConfig::default()
        });
        let web = Provenance::new(
            SourceKind::Web,
            Some("https://example.test/fact".to_owned()),
            "test",
        );
        let file = Provenance::new(SourceKind::File, Some("repo:path".to_owned()), "test");

        assert_eq!(
            hook.plan_revalidation(&trigger, &web),
            RevalidationAction::SurfaceToCaller {
                memory_id: trigger.memory_id,
            }
        );
        assert_eq!(
            hook.plan_revalidation(&trigger, &file),
            RevalidationAction::QueryGraph {
                memory_id: trigger.memory_id,
                graph_ref: "repo:path".to_owned(),
            }
        );
    }

    #[test]
    fn revalidation_strategy_with_missing_ref_surfaces_to_caller() {
        let stale = candidate(true);
        let trigger = triggers_from_recall(&[stale])[0];
        let hook = ConfigurableRevalidationHook::new(RevalidationStrategyConfig {
            user: RevalidationStrategy::ReReadSource,
            ..RevalidationStrategyConfig::default()
        });
        let user = Provenance::new(SourceKind::User, None, "test");

        assert_eq!(
            hook.plan_revalidation(&trigger, &user),
            RevalidationAction::SurfaceToCaller {
                memory_id: trigger.memory_id,
            }
        );
    }

    #[test]
    fn graph_refs_still_use_graph_revalidation() {
        let stale = candidate(true);
        let trigger = triggers_from_recall(&[stale])[0];
        let hook = ConfigurableRevalidationHook::new(RevalidationStrategyConfig {
            tool: RevalidationStrategy::SurfaceToCaller,
            ..RevalidationStrategyConfig::default()
        });
        let graph = Provenance::new(SourceKind::Tool, Some("graph:claim:123".to_owned()), "test");

        assert_eq!(
            hook.plan_revalidation(&trigger, &graph),
            RevalidationAction::QueryGraph {
                memory_id: trigger.memory_id,
                graph_ref: "graph:claim:123".to_owned(),
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
