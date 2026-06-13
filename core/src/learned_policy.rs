// SPDX-License-Identifier: MIT

//! Offline evaluation gates for future learned memory policies.
//!
//! This module deliberately does not train a model and does not apply actions to
//! storage. It only evaluates caller-supplied offline candidate actions against
//! logged human signals and Shibahama's invariants.

#![allow(clippy::module_name_repetitions)]

use crate::model::{CredenceTier, HumanSignal, HumanSignalAction, MemoryId, MemoryItem, Tier};
use crate::storage::{EventRecord, MemoryEvent};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use time::OffsetDateTime;

/// Public names of every allowed Stage 1 learned-policy action.
pub const ALLOWED_POLICY_ACTION_NAMES: [&str; 5] = [
    "noop",
    "promote",
    "demote",
    "merge_with_provenance",
    "flag_for_review",
];

/// Non-destructive action proposed by an offline candidate policy.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub enum PolicyAction {
    /// Leave the memory unchanged.
    Noop,
    /// Propose a hotter tier.
    Promote {
        /// Target tier proposed by the candidate policy.
        to: Tier,
    },
    /// Propose a colder tier.
    Demote {
        /// Target tier proposed by the candidate policy.
        to: Tier,
    },
    /// Propose a synthesis step that preserves all source-memory lineage.
    MergeWithProvenance {
        /// Source memories that must remain queryable and be recorded as provenance.
        source_memory_ids: Vec<MemoryId>,
    },
    /// Flag the memory for explicit human or source re-verification.
    FlagForReview,
}

impl PolicyAction {
    /// Returns the stable action name used in reports.
    #[must_use]
    pub const fn name(&self) -> &'static str {
        match self {
            Self::Noop => "noop",
            Self::Promote { .. } => "promote",
            Self::Demote { .. } => "demote",
            Self::MergeWithProvenance { .. } => "merge_with_provenance",
            Self::FlagForReview => "flag_for_review",
        }
    }

    /// Returns true for every currently supported action.
    #[must_use]
    pub const fn is_non_destructive(&self) -> bool {
        matches!(
            self,
            Self::Noop
                | Self::Promote { .. }
                | Self::Demote { .. }
                | Self::MergeWithProvenance { .. }
                | Self::FlagForReview
        )
    }
}

/// One candidate action to score in an offline learned-policy evaluation.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct OfflinePolicyDecision {
    /// Memory the decision is anchored to.
    pub memory_id: MemoryId,
    /// Candidate non-destructive action.
    pub action: PolicyAction,
    /// Optional decision time. When present, only later human signals are labels.
    pub decided_at: Option<OffsetDateTime>,
    /// Human-readable policy explanation stored only for evaluation review.
    pub rationale: String,
}

impl OfflinePolicyDecision {
    /// Creates an offline decision without a timestamp filter.
    #[must_use]
    pub fn new(memory_id: MemoryId, action: PolicyAction, rationale: impl Into<String>) -> Self {
        Self {
            memory_id,
            action,
            decided_at: None,
            rationale: rationale.into(),
        }
    }

    /// Creates an offline decision that is judged only against later signals.
    #[must_use]
    pub fn at(
        memory_id: MemoryId,
        action: PolicyAction,
        decided_at: OffsetDateTime,
        rationale: impl Into<String>,
    ) -> Self {
        Self {
            memory_id,
            action,
            decided_at: Some(decided_at),
            rationale: rationale.into(),
        }
    }
}

/// Configuration for Stage 1 offline learned-policy evaluation.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct OfflinePolicyEvaluationConfig {
    /// Minimum labeled decisions before any learned-policy result may proceed.
    pub min_labeled_decisions: usize,
    /// Required candidate score margin over the deterministic baseline.
    pub required_score_margin: f64,
    /// Score at or above which the deterministic baseline promotes one tier.
    pub baseline_promote_threshold: f64,
    /// Score below which the deterministic baseline demotes one tier.
    pub baseline_demote_threshold: f64,
}

impl Default for OfflinePolicyEvaluationConfig {
    fn default() -> Self {
        Self {
            min_labeled_decisions: 20,
            required_score_margin: 0.05,
            baseline_promote_threshold: 2.0,
            baseline_demote_threshold: 0.5,
        }
    }
}

/// Human-label counts derived from append-only human-signal events.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct HumanSignalSummary {
    /// Number of later human challenges.
    pub challenges: u32,
    /// Number of later human affirmations.
    pub affirmations: u32,
    /// Number of later human corrections.
    pub corrections: u32,
    /// Number of later human pins.
    pub pins: u32,
    /// Number of later human unpins.
    pub unpins: u32,
}

impl HumanSignalSummary {
    /// Returns the number of non-neutral labels.
    #[must_use]
    pub const fn labeled_count(self) -> u32 {
        self.challenges
            .saturating_add(self.affirmations)
            .saturating_add(self.corrections)
            .saturating_add(self.pins)
    }

    /// Returns all labels including neutral unpin events.
    #[must_use]
    pub const fn total_count(self) -> u32 {
        self.labeled_count().saturating_add(self.unpins)
    }

    /// Returns whether this summary has a positive, negative, mixed, or neutral direction.
    #[must_use]
    pub const fn direction(self) -> HumanSignalDirection {
        let positive = self.affirmations.saturating_add(self.pins);
        let negative = self.challenges.saturating_add(self.corrections);

        if positive > 0 && negative > 0 {
            HumanSignalDirection::Mixed
        } else if positive > 0 {
            HumanSignalDirection::Positive
        } else if negative > 0 {
            HumanSignalDirection::Negative
        } else {
            HumanSignalDirection::Neutral
        }
    }
}

/// Coarse direction of logged human labels for one memory.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum HumanSignalDirection {
    /// No affirm/challenge/correct/pin labels were available.
    Neutral,
    /// Later labels were affirming or protective.
    Positive,
    /// Later labels were challenging or corrective.
    Negative,
    /// Later labels contained both positive and negative signals.
    Mixed,
}

/// Hard violation that blocks any learned-policy rollout.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum InvariantViolation {
    /// The candidate decision refers to a memory that is not in the evaluated snapshot.
    DecisionTargetsUnknownMemory {
        /// Unknown target memory id.
        memory_id: MemoryId,
    },
    /// A demotion attempted to cross the memory's credence floor.
    DemotesBelowCredenceFloor {
        /// Memory being demoted.
        memory_id: MemoryId,
        /// Coldest tier allowed by the memory.
        floor: Tier,
        /// Candidate target tier.
        proposed: Tier,
    },
    /// A demotion targeted a floor-protected memory.
    DemotesProtectedMemory {
        /// Memory being demoted.
        memory_id: MemoryId,
        /// Active protection floor.
        floor: Tier,
    },
    /// A merge action did not name enough sources to preserve lineage.
    MergeHasTooFewSources {
        /// Memory anchoring the merge decision.
        memory_id: MemoryId,
        /// Number of source ids supplied.
        source_count: usize,
    },
    /// A merge action omitted the anchor memory from its source lineage.
    MergeOmitsTargetMemory {
        /// Memory anchoring the merge decision.
        memory_id: MemoryId,
    },
    /// A merge action named the same source more than once.
    MergeUsesDuplicateSource {
        /// Memory anchoring the merge decision.
        memory_id: MemoryId,
        /// Duplicate source id.
        source_id: MemoryId,
    },
    /// A merge action referenced a source that is not present in the evaluated snapshot.
    MergeUsesUnknownSource {
        /// Memory anchoring the merge decision.
        memory_id: MemoryId,
        /// Missing source id.
        source_id: MemoryId,
    },
}

/// Per-decision score and invariant trace.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct DecisionEvaluation {
    /// Memory being evaluated.
    pub memory_id: MemoryId,
    /// Candidate action supplied by the offline policy.
    pub candidate_action: PolicyAction,
    /// Deterministic baseline action for the same memory snapshot.
    pub baseline_action: PolicyAction,
    /// Human labels used to judge both actions.
    pub human_signals: HumanSignalSummary,
    /// Candidate reward under the invariant-first offline scorer.
    pub candidate_score: f64,
    /// Deterministic-baseline reward under the same labels.
    pub baseline_score: f64,
    /// Blocking invariant violations for this decision.
    pub invariant_violations: Vec<InvariantViolation>,
}

/// Gate recommendation returned by Stage 1 evaluation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum PolicyEvaluationRecommendation {
    /// Stop because at least one candidate action violated invariants.
    StopInvariantViolation,
    /// Stop because there are too few later human labels to justify learning.
    StopInsufficientSignal,
    /// Stop because the candidate did not beat the deterministic baseline.
    StopBaselineNotBeaten,
    /// Candidate cleared Stage 1 and may be considered for a bandit experiment.
    ProceedToBanditExperiment,
}

/// Aggregate result for an offline learned-policy evaluation.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct OfflinePolicyEvaluationReport {
    /// Per-decision traces.
    pub decisions: Vec<DecisionEvaluation>,
    /// Number of decisions with at least one non-neutral human label.
    pub labeled_decision_count: usize,
    /// Total non-neutral human labels used.
    pub labeled_signal_count: u32,
    /// Sum of candidate decision scores.
    pub candidate_score: f64,
    /// Sum of deterministic-baseline scores.
    pub baseline_score: f64,
    /// Candidate score minus baseline score.
    pub score_margin: f64,
    /// All blocking invariant violations.
    pub invariant_violations: Vec<InvariantViolation>,
    /// Stage 1 gate recommendation.
    pub recommendation: PolicyEvaluationRecommendation,
}

/// Evaluates offline candidate actions against logged human signals and a deterministic baseline.
#[must_use]
pub fn evaluate_offline_policy(
    decisions: &[OfflinePolicyDecision],
    memories: &[MemoryItem],
    events: &[EventRecord],
    config: OfflinePolicyEvaluationConfig,
) -> OfflinePolicyEvaluationReport {
    let memories_by_id = memories
        .iter()
        .map(|item| (item.id, item))
        .collect::<BTreeMap<_, _>>();
    let known_memory_ids = memories_by_id.keys().copied().collect::<BTreeSet<_>>();
    let mut evaluations = Vec::with_capacity(decisions.len());
    let mut labeled_decision_count = 0_usize;
    let mut labeled_signal_count = 0_u32;
    let mut candidate_score = 0.0_f64;
    let mut baseline_score = 0.0_f64;
    let mut all_violations = Vec::new();

    for decision in decisions {
        let Some(item) = memories_by_id.get(&decision.memory_id) else {
            let violation = InvariantViolation::DecisionTargetsUnknownMemory {
                memory_id: decision.memory_id,
            };
            all_violations.push(violation.clone());
            evaluations.push(DecisionEvaluation {
                memory_id: decision.memory_id,
                candidate_action: decision.action.clone(),
                baseline_action: PolicyAction::Noop,
                human_signals: HumanSignalSummary::default(),
                candidate_score: 0.0,
                baseline_score: 0.0,
                invariant_violations: vec![violation],
            });
            continue;
        };

        let human_signals =
            summarize_human_signals(decision.memory_id, decision.decided_at, events);
        let baseline_action = deterministic_baseline_action(item, config);
        let decision_violations = check_invariants(decision, item, &known_memory_ids);
        let decision_candidate_score = score_action(&decision.action, item, human_signals);
        let decision_baseline_score = score_action(&baseline_action, item, human_signals);

        if human_signals.labeled_count() > 0 {
            labeled_decision_count = labeled_decision_count.saturating_add(1);
            labeled_signal_count =
                labeled_signal_count.saturating_add(human_signals.labeled_count());
            candidate_score += decision_candidate_score;
            baseline_score += decision_baseline_score;
        }

        all_violations.extend(decision_violations.iter().cloned());
        evaluations.push(DecisionEvaluation {
            memory_id: decision.memory_id,
            candidate_action: decision.action.clone(),
            baseline_action,
            human_signals,
            candidate_score: decision_candidate_score,
            baseline_score: decision_baseline_score,
            invariant_violations: decision_violations,
        });
    }

    let score_margin = candidate_score - baseline_score;
    let recommendation = recommendation(
        &all_violations,
        labeled_decision_count,
        score_margin,
        config,
    );

    OfflinePolicyEvaluationReport {
        decisions: evaluations,
        labeled_decision_count,
        labeled_signal_count,
        candidate_score,
        baseline_score,
        score_margin,
        invariant_violations: all_violations,
        recommendation,
    }
}

#[must_use]
fn recommendation(
    violations: &[InvariantViolation],
    labeled_decision_count: usize,
    score_margin: f64,
    config: OfflinePolicyEvaluationConfig,
) -> PolicyEvaluationRecommendation {
    if !violations.is_empty() {
        return PolicyEvaluationRecommendation::StopInvariantViolation;
    }

    if labeled_decision_count < config.min_labeled_decisions {
        return PolicyEvaluationRecommendation::StopInsufficientSignal;
    }

    if score_margin <= config.required_score_margin {
        return PolicyEvaluationRecommendation::StopBaselineNotBeaten;
    }

    PolicyEvaluationRecommendation::ProceedToBanditExperiment
}

#[must_use]
fn summarize_human_signals(
    memory_id: MemoryId,
    decided_at: Option<OffsetDateTime>,
    events: &[EventRecord],
) -> HumanSignalSummary {
    let mut summary = HumanSignalSummary::default();

    for signal in events.iter().filter_map(human_signal) {
        if signal.memory_id != memory_id || !is_label_after_decision(signal, decided_at) {
            continue;
        }

        match signal.action {
            HumanSignalAction::Challenge => {
                summary.challenges = summary.challenges.saturating_add(1);
            }
            HumanSignalAction::Affirm => {
                summary.affirmations = summary.affirmations.saturating_add(1);
            }
            HumanSignalAction::Correct => {
                summary.corrections = summary.corrections.saturating_add(1);
            }
            HumanSignalAction::Pin => {
                summary.pins = summary.pins.saturating_add(1);
            }
            HumanSignalAction::Unpin => {
                summary.unpins = summary.unpins.saturating_add(1);
            }
        }
    }

    summary
}

#[must_use]
fn human_signal(record: &EventRecord) -> Option<&HumanSignal> {
    let MemoryEvent::HumanSignalRecorded { signal } = &record.event else {
        return None;
    };

    Some(signal)
}

#[must_use]
fn is_label_after_decision(signal: &HumanSignal, decided_at: Option<OffsetDateTime>) -> bool {
    decided_at.is_none_or(|at| signal.timestamp > at)
}

#[must_use]
fn deterministic_baseline_action(
    item: &MemoryItem,
    config: OfflinePolicyEvaluationConfig,
) -> PolicyAction {
    if item.significance >= config.baseline_promote_threshold {
        let promoted = item.tier.promote();

        if promoted > item.tier {
            return PolicyAction::Promote { to: promoted };
        }
    }

    if item.significance < config.baseline_demote_threshold {
        let demoted = item.clamp_tier_to_floor(item.tier.demote());

        if demoted < item.tier {
            return PolicyAction::Demote { to: demoted };
        }
    }

    PolicyAction::Noop
}

#[must_use]
fn check_invariants(
    decision: &OfflinePolicyDecision,
    item: &MemoryItem,
    known_memory_ids: &BTreeSet<MemoryId>,
) -> Vec<InvariantViolation> {
    let mut violations = Vec::new();

    match &decision.action {
        PolicyAction::Noop | PolicyAction::FlagForReview | PolicyAction::Promote { .. } => {}
        PolicyAction::Demote { to } => {
            if *to < item.credence_floor {
                violations.push(InvariantViolation::DemotesBelowCredenceFloor {
                    memory_id: item.id,
                    floor: item.credence_floor,
                    proposed: *to,
                });
            }

            if item.credence_floor > Tier::Cold && *to < item.tier {
                violations.push(InvariantViolation::DemotesProtectedMemory {
                    memory_id: item.id,
                    floor: item.credence_floor,
                });
            }
        }
        PolicyAction::MergeWithProvenance { source_memory_ids } => {
            violations.extend(check_merge_lineage(
                item.id,
                source_memory_ids,
                known_memory_ids,
            ));
        }
    }

    violations
}

#[must_use]
fn check_merge_lineage(
    memory_id: MemoryId,
    source_memory_ids: &[MemoryId],
    known_memory_ids: &BTreeSet<MemoryId>,
) -> Vec<InvariantViolation> {
    let mut violations = Vec::new();

    if source_memory_ids.len() < 2 {
        violations.push(InvariantViolation::MergeHasTooFewSources {
            memory_id,
            source_count: source_memory_ids.len(),
        });
    }

    if !source_memory_ids.contains(&memory_id) {
        violations.push(InvariantViolation::MergeOmitsTargetMemory { memory_id });
    }

    let mut seen = BTreeSet::new();
    for source_id in source_memory_ids {
        if !seen.insert(*source_id) {
            violations.push(InvariantViolation::MergeUsesDuplicateSource {
                memory_id,
                source_id: *source_id,
            });
        }

        if !known_memory_ids.contains(source_id) {
            violations.push(InvariantViolation::MergeUsesUnknownSource {
                memory_id,
                source_id: *source_id,
            });
        }
    }

    violations
}

#[must_use]
fn score_action(action: &PolicyAction, item: &MemoryItem, labels: HumanSignalSummary) -> f64 {
    match labels.direction() {
        HumanSignalDirection::Neutral => 0.0,
        HumanSignalDirection::Positive => score_against_positive_label(action, item),
        HumanSignalDirection::Negative => score_against_negative_label(action),
        HumanSignalDirection::Mixed => mixed_label_score(action, item),
    }
}

#[must_use]
fn score_against_positive_label(action: &PolicyAction, item: &MemoryItem) -> f64 {
    match action {
        PolicyAction::Promote { to } if *to > item.tier => 1.0,
        PolicyAction::Noop
            if item.tier == Tier::Hot || item.credence >= CredenceTier::VerifiedSource =>
        {
            0.5
        }
        PolicyAction::Noop => 0.25,
        PolicyAction::MergeWithProvenance { .. } => 0.1,
        PolicyAction::FlagForReview => -0.5,
        PolicyAction::Demote { .. } => -1.0,
        PolicyAction::Promote { .. } => 0.0,
    }
}

#[must_use]
fn score_against_negative_label(action: &PolicyAction) -> f64 {
    match action {
        PolicyAction::FlagForReview => 1.0,
        PolicyAction::Demote { .. } => 0.75,
        PolicyAction::MergeWithProvenance { .. } => 0.25,
        PolicyAction::Noop => 0.0,
        PolicyAction::Promote { .. } => -1.0,
    }
}

#[must_use]
fn mixed_label_score(action: &PolicyAction, item: &MemoryItem) -> f64 {
    match action {
        PolicyAction::FlagForReview => 0.5,
        PolicyAction::Noop if item.credence >= CredenceTier::VerifiedSource => 0.25,
        PolicyAction::MergeWithProvenance { .. } => 0.1,
        PolicyAction::Noop | PolicyAction::Promote { .. } | PolicyAction::Demote { .. } => 0.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{
        CURRENT_MEMORY_SCHEMA_VERSION, MemoryKind, Provenance, SourceKind, TemporalBounds,
    };
    use crate::storage::EventRecord;
    use time::Duration;

    fn memory(content: &str, tier: Tier, floor: Tier, significance: f64) -> MemoryItem {
        let now = OffsetDateTime::UNIX_EPOCH;

        MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            id: MemoryId::new_v7(),
            content: content.to_owned(),
            kind: MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            embedding_ref: None,
            provenance: Provenance::new(SourceKind::User, None, "test"),
            timestamps: TemporalBounds::open_from(now, now),
            tier,
            credence: CredenceTier::VerifiedSource,
            significance,
            base_significance: significance,
            credence_floor: floor,
            access_events: Vec::new(),
        }
    }

    fn human_signal_event(
        sequence: u64,
        memory_id: MemoryId,
        action: HumanSignalAction,
        timestamp: OffsetDateTime,
    ) -> EventRecord {
        EventRecord {
            sequence,
            recorded_at: timestamp,
            event: MemoryEvent::HumanSignalRecorded {
                signal: HumanSignal {
                    action,
                    memory_id,
                    actor: "reviewer".to_owned(),
                    timestamp,
                    reason: "offline label".to_owned(),
                    proposed_content: None,
                    proposal_id: None,
                    previous_credence: None,
                    new_credence: None,
                    previous_credence_floor: None,
                    new_credence_floor: None,
                },
            },
        }
    }

    fn single_label_config() -> OfflinePolicyEvaluationConfig {
        OfflinePolicyEvaluationConfig {
            min_labeled_decisions: 1,
            required_score_margin: 0.0,
            baseline_promote_threshold: 2.0,
            baseline_demote_threshold: 0.5,
        }
    }

    #[test]
    fn action_space_has_no_destructive_operations() {
        assert_eq!(
            ALLOWED_POLICY_ACTION_NAMES,
            [
                "noop",
                "promote",
                "demote",
                "merge_with_provenance",
                "flag_for_review"
            ]
        );
        assert!(!ALLOWED_POLICY_ACTION_NAMES.contains(&"delete"));
        assert!(!ALLOWED_POLICY_ACTION_NAMES.contains(&"overwrite"));

        let action = PolicyAction::FlagForReview;

        assert!(action.is_non_destructive());
    }

    #[test]
    fn floor_violations_stop_the_evaluation() {
        let item = memory("pinned deployment rule", Tier::Hot, Tier::Warm, 0.3);
        let decision = OfflinePolicyDecision::new(
            item.id,
            PolicyAction::Demote { to: Tier::Cold },
            "candidate tried to demote a protected item",
        );
        let events = vec![human_signal_event(
            0,
            item.id,
            HumanSignalAction::Challenge,
            OffsetDateTime::UNIX_EPOCH + Duration::hours(1),
        )];
        let report = evaluate_offline_policy(&[decision], &[item], &events, single_label_config());

        assert_eq!(
            report.recommendation,
            PolicyEvaluationRecommendation::StopInvariantViolation
        );
        assert!(report.invariant_violations.iter().any(|violation| matches!(
            violation,
            InvariantViolation::DemotesBelowCredenceFloor { .. }
        )));
        assert!(report.invariant_violations.iter().any(|violation| matches!(
            violation,
            InvariantViolation::DemotesProtectedMemory { .. }
        )));
    }

    #[test]
    fn insufficient_human_signal_stops_before_training() {
        let item = memory("uncertain runbook", Tier::Warm, Tier::Cold, 1.2);
        let decision =
            OfflinePolicyDecision::new(item.id, PolicyAction::FlagForReview, "weak signal");
        let report = evaluate_offline_policy(
            &[decision],
            &[item],
            &[],
            OfflinePolicyEvaluationConfig::default(),
        );

        assert_eq!(
            report.recommendation,
            PolicyEvaluationRecommendation::StopInsufficientSignal
        );
        assert_eq!(report.labeled_decision_count, 0);
        assert!(report.candidate_score.abs() <= f64::EPSILON);
    }

    #[test]
    fn labels_are_derived_only_from_subsequent_human_signals() {
        let item = memory("host moved", Tier::Warm, Tier::Cold, 1.0);
        let decided_at = OffsetDateTime::UNIX_EPOCH + Duration::hours(2);
        let decision = OfflinePolicyDecision::at(
            item.id,
            PolicyAction::FlagForReview,
            decided_at,
            "flag contested host",
        );
        let events = vec![
            human_signal_event(
                0,
                item.id,
                HumanSignalAction::Affirm,
                decided_at - Duration::minutes(1),
            ),
            human_signal_event(
                1,
                item.id,
                HumanSignalAction::Challenge,
                decided_at + Duration::minutes(1),
            ),
            human_signal_event(
                2,
                item.id,
                HumanSignalAction::Correct,
                decided_at + Duration::minutes(2),
            ),
        ];
        let report = evaluate_offline_policy(&[decision], &[item], &events, single_label_config());
        let labels = report.decisions[0].human_signals;

        assert_eq!(labels.affirmations, 0);
        assert_eq!(labels.challenges, 1);
        assert_eq!(labels.corrections, 1);
        assert_eq!(labels.direction(), HumanSignalDirection::Negative);
        assert_eq!(
            report.recommendation,
            PolicyEvaluationRecommendation::ProceedToBanditExperiment
        );
    }

    #[test]
    fn merge_actions_must_preserve_known_source_lineage() {
        let first = memory("api endpoint /v1", Tier::Warm, Tier::Cold, 1.5);
        let second = memory("api endpoint remains /v1", Tier::Warm, Tier::Cold, 1.4);
        let valid_decision = OfflinePolicyDecision::new(
            first.id,
            PolicyAction::MergeWithProvenance {
                source_memory_ids: vec![first.id, second.id],
            },
            "merge duplicate endpoint memories",
        );
        let missing_source = MemoryId::new_v7();
        let invalid_decision = OfflinePolicyDecision::new(
            first.id,
            PolicyAction::MergeWithProvenance {
                source_memory_ids: vec![first.id, missing_source],
            },
            "merge with missing lineage",
        );
        let events = vec![human_signal_event(
            0,
            first.id,
            HumanSignalAction::Challenge,
            OffsetDateTime::UNIX_EPOCH + Duration::hours(1),
        )];

        let valid_report = evaluate_offline_policy(
            &[valid_decision],
            &[first.clone(), second.clone()],
            &events,
            single_label_config(),
        );
        assert!(valid_report.invariant_violations.is_empty());

        let invalid_report = evaluate_offline_policy(
            &[invalid_decision],
            &[first, second],
            &events,
            single_label_config(),
        );
        assert!(
            invalid_report
                .invariant_violations
                .iter()
                .any(|violation| matches!(
                    violation,
                    InvariantViolation::MergeUsesUnknownSource { .. }
                ))
        );
        assert_eq!(
            invalid_report.recommendation,
            PolicyEvaluationRecommendation::StopInvariantViolation
        );
    }

    #[test]
    fn null_result_is_reported_when_baseline_is_not_beaten() {
        let item = memory("stable project decision", Tier::Warm, Tier::Cold, 1.0);
        let decision = OfflinePolicyDecision::new(
            item.id,
            PolicyAction::Promote { to: Tier::Hot },
            "candidate overreacted to a challenged memory",
        );
        let events = vec![human_signal_event(
            0,
            item.id,
            HumanSignalAction::Challenge,
            OffsetDateTime::UNIX_EPOCH + Duration::hours(1),
        )];
        let report = evaluate_offline_policy(&[decision], &[item], &events, single_label_config());

        assert_eq!(
            report.recommendation,
            PolicyEvaluationRecommendation::StopBaselineNotBeaten
        );
        assert!(report.score_margin < 0.0);
    }
}
