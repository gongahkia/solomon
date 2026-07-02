// SPDX-License-Identifier: MIT

//! Offline evaluation gates for future learned memory policies.
//!
//! This module deliberately does not train a model and does not apply actions to
//! storage. It only evaluates caller-supplied offline candidate actions against
//! logged human signals and Shibahama's invariants.

#![allow(clippy::module_name_repetitions)]

use crate::model::{CredenceTier, HumanSignal, HumanSignalAction, MemoryId, MemoryItem, Tier};
use crate::significance::SignificanceConfig;
use crate::storage::{EventRecord, MemoryEvent};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;
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

/// Aggregate trace for one candidate action type.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct PolicyActionSummary {
    /// Stable action name, matching `PolicyAction::name`.
    pub action_name: String,
    /// Number of candidate decisions using this action.
    pub decision_count: usize,
    /// Number of decisions with at least one non-neutral human label.
    pub labeled_decision_count: usize,
    /// Number of positive human signals attached to this action.
    pub positive_signal_count: u32,
    /// Number of negative human signals attached to this action.
    pub negative_signal_count: u32,
    /// Number of decisions with both positive and negative labels.
    pub mixed_decision_count: usize,
    /// Number of decisions with no non-neutral labels.
    pub neutral_decision_count: usize,
    /// Candidate score contribution from labeled decisions for this action.
    pub candidate_score: f64,
    /// Baseline score contribution from the same labeled decisions.
    pub baseline_score: f64,
    /// Number of invariant violations emitted by this action.
    pub invariant_violation_count: usize,
}

impl PolicyActionSummary {
    fn empty(action_name: &str) -> Self {
        Self {
            action_name: action_name.to_owned(),
            decision_count: 0,
            labeled_decision_count: 0,
            positive_signal_count: 0,
            negative_signal_count: 0,
            mixed_decision_count: 0,
            neutral_decision_count: 0,
            candidate_score: 0.0,
            baseline_score: 0.0,
            invariant_violation_count: 0,
        }
    }
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

/// Structured explanation for a Stage 1 stop recommendation.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct PolicyNullResult {
    /// Stop reason returned by the Stage 1 gate.
    pub recommendation: PolicyEvaluationRecommendation,
    /// Minimum labeled decisions required by the evaluation config.
    pub required_labeled_decisions: usize,
    /// Observed labeled decisions.
    pub observed_labeled_decisions: usize,
    /// Required score margin over the deterministic baseline.
    pub required_score_margin: f64,
    /// Observed score margin over the deterministic baseline.
    pub observed_score_margin: f64,
    /// Number of invariant violations in the evaluated candidate trace.
    pub invariant_violation_count: usize,
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
    /// Per-action summary used to identify where signal exists or disappears.
    pub action_summaries: Vec<PolicyActionSummary>,
    /// All blocking invariant violations.
    pub invariant_violations: Vec<InvariantViolation>,
    /// Structured null result when the candidate cannot proceed.
    pub null_result: Option<PolicyNullResult>,
    /// Stage 1 gate recommendation.
    pub recommendation: PolicyEvaluationRecommendation,
}

/// Error returned by offline learned-policy evaluation.
#[derive(Clone, Debug, Deserialize, Error, Eq, PartialEq, Serialize)]
pub enum PolicyEvaluationError {
    /// A candidate action was missing from the summary action list.
    #[error("candidate action `{action_name}` is not represented in policy action summaries")]
    MissingActionSummary {
        /// Action name returned by `PolicyAction::name`.
        action_name: String,
    },
}

/// Evaluates offline candidate actions against logged human signals and a deterministic baseline.
///
/// # Errors
///
/// Returns an error when a candidate action is not represented in the policy action summary list.
pub fn evaluate_offline_policy(
    decisions: &[OfflinePolicyDecision],
    memories: &[MemoryItem],
    events: &[EventRecord],
    config: OfflinePolicyEvaluationConfig,
) -> Result<OfflinePolicyEvaluationReport, PolicyEvaluationError> {
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
    let action_summaries = summarize_decisions_by_action(&evaluations)?;
    let null_result = null_result(
        recommendation,
        labeled_decision_count,
        score_margin,
        all_violations.len(),
        config,
    );

    Ok(OfflinePolicyEvaluationReport {
        decisions: evaluations,
        labeled_decision_count,
        labeled_signal_count,
        candidate_score,
        baseline_score,
        score_margin,
        action_summaries,
        invariant_violations: all_violations,
        null_result,
        recommendation,
    })
}

fn summarize_decisions_by_action(
    evaluations: &[DecisionEvaluation],
) -> Result<Vec<PolicyActionSummary>, PolicyEvaluationError> {
    summarize_decisions_by_action_with_names(evaluations, &ALLOWED_POLICY_ACTION_NAMES)
}

fn summarize_decisions_by_action_with_names(
    evaluations: &[DecisionEvaluation],
    action_names: &[&str],
) -> Result<Vec<PolicyActionSummary>, PolicyEvaluationError> {
    let mut summaries = action_names
        .iter()
        .map(|name| PolicyActionSummary::empty(name))
        .collect::<Vec<_>>();

    for evaluation in evaluations {
        let action_name = evaluation.candidate_action.name();
        let Some(summary) = summaries
            .iter_mut()
            .find(|summary| summary.action_name == action_name)
        else {
            return Err(PolicyEvaluationError::MissingActionSummary {
                action_name: action_name.to_owned(),
            });
        };
        let positive = evaluation
            .human_signals
            .affirmations
            .saturating_add(evaluation.human_signals.pins);
        let negative = evaluation
            .human_signals
            .challenges
            .saturating_add(evaluation.human_signals.corrections);

        summary.decision_count = summary.decision_count.saturating_add(1);
        summary.positive_signal_count = summary.positive_signal_count.saturating_add(positive);
        summary.negative_signal_count = summary.negative_signal_count.saturating_add(negative);
        summary.invariant_violation_count = summary
            .invariant_violation_count
            .saturating_add(evaluation.invariant_violations.len());

        if evaluation.human_signals.labeled_count() > 0 {
            summary.labeled_decision_count = summary.labeled_decision_count.saturating_add(1);
            summary.candidate_score += evaluation.candidate_score;
            summary.baseline_score += evaluation.baseline_score;
        }

        match evaluation.human_signals.direction() {
            HumanSignalDirection::Mixed => {
                summary.mixed_decision_count = summary.mixed_decision_count.saturating_add(1);
            }
            HumanSignalDirection::Neutral => {
                summary.neutral_decision_count = summary.neutral_decision_count.saturating_add(1);
            }
            HumanSignalDirection::Positive | HumanSignalDirection::Negative => {}
        }
    }

    Ok(summaries)
}

#[must_use]
fn null_result(
    recommendation: PolicyEvaluationRecommendation,
    observed_labeled_decisions: usize,
    observed_score_margin: f64,
    invariant_violation_count: usize,
    config: OfflinePolicyEvaluationConfig,
) -> Option<PolicyNullResult> {
    if recommendation == PolicyEvaluationRecommendation::ProceedToBanditExperiment {
        return None;
    }

    Some(PolicyNullResult {
        recommendation,
        required_labeled_decisions: config.min_labeled_decisions,
        observed_labeled_decisions,
        required_score_margin: config.required_score_margin,
        observed_score_margin,
        invariant_violation_count,
    })
}

/// Configuration for the Stage 2 contextual-bandit shadow experiment.
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
pub struct ContextualBanditExperimentConfig {
    /// Stage 2 is disabled unless a caller explicitly opts in.
    pub enabled: bool,
    /// Minimum Stage 1 labeled decisions required before planning any experiment.
    pub min_stage1_labeled_decisions: usize,
    /// Minimum Stage 1 score margin required before planning any experiment.
    pub min_stage1_score_margin: f64,
    /// Conservative learning-rate cap for proposed significance-weight deltas.
    pub learning_rate: f64,
    /// Maximum absolute delta allowed for any single proposed weight.
    pub max_weight_delta: f64,
}

impl Default for ContextualBanditExperimentConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            min_stage1_labeled_decisions: 100,
            min_stage1_score_margin: 0.05,
            learning_rate: 0.05,
            max_weight_delta: 0.25,
        }
    }
}

/// Stage 2 gate recommendation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ContextualBanditRecommendation {
    /// Stage 2 was not explicitly enabled.
    Disabled,
    /// Stage 1 evidence did not clear the stricter Stage 2 gate.
    StopStage1Gate,
    /// Stage 2 config is invalid or too risky.
    StopUnsafeExperimentConfig,
    /// A shadow experiment may be run; runtime memory policy is still unchanged.
    ProceedToShadowExperiment,
}

/// Proposed delta to one existing `SignificanceConfig` weight.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct SignificanceWeightDelta {
    /// Existing significance config field.
    pub weight_name: String,
    /// Current value supplied by the caller.
    pub current_value: f64,
    /// Bounded proposed delta for a shadow arm.
    pub delta: f64,
    /// Current value plus delta.
    pub proposed_value: f64,
}

/// Stage 2 contextual-bandit planning report.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ContextualBanditExperimentReport {
    /// Stage 2 gate recommendation.
    pub recommendation: ContextualBanditRecommendation,
    /// Stage 1 recommendation this report was based on.
    pub stage1_recommendation: PolicyEvaluationRecommendation,
    /// True only for a shadow experiment; Shibahama never mutates runtime policy here.
    pub shadow_experiment_allowed: bool,
    /// Runtime policy mutation remains disabled by this API.
    pub runtime_policy_update_allowed: bool,
    /// Proposed bounded deltas to existing significance weights.
    pub proposed_weight_deltas: Vec<SignificanceWeightDelta>,
    /// Human-readable gate rationale.
    pub rationale: String,
}

/// Plans a disabled-by-default Stage 2 shadow experiment over existing significance weights.
///
/// This does not learn online, mutate runtime config, or apply candidate actions. It only returns
/// a conservative shadow-arm plan when Stage 1 already produced enough signal and beat the
/// deterministic baseline without invariant violations.
#[must_use]
pub fn plan_contextual_bandit_experiment(
    stage1_report: &OfflinePolicyEvaluationReport,
    current_significance: SignificanceConfig,
    config: ContextualBanditExperimentConfig,
) -> ContextualBanditExperimentReport {
    if !config.enabled {
        return ContextualBanditExperimentReport {
            recommendation: ContextualBanditRecommendation::Disabled,
            stage1_recommendation: stage1_report.recommendation,
            shadow_experiment_allowed: false,
            runtime_policy_update_allowed: false,
            proposed_weight_deltas: Vec::new(),
            rationale: "Stage 2 is disabled by default".to_owned(),
        };
    }

    if let Some(reason) = unsafe_bandit_config_reason(config) {
        return ContextualBanditExperimentReport {
            recommendation: ContextualBanditRecommendation::StopUnsafeExperimentConfig,
            stage1_recommendation: stage1_report.recommendation,
            shadow_experiment_allowed: false,
            runtime_policy_update_allowed: false,
            proposed_weight_deltas: Vec::new(),
            rationale: reason.to_owned(),
        };
    }

    if stage1_report.recommendation != PolicyEvaluationRecommendation::ProceedToBanditExperiment
        || stage1_report.labeled_decision_count < config.min_stage1_labeled_decisions
        || stage1_report.score_margin < config.min_stage1_score_margin
    {
        return ContextualBanditExperimentReport {
            recommendation: ContextualBanditRecommendation::StopStage1Gate,
            stage1_recommendation: stage1_report.recommendation,
            shadow_experiment_allowed: false,
            runtime_policy_update_allowed: false,
            proposed_weight_deltas: Vec::new(),
            rationale: "Stage 1 did not clear the stricter Stage 2 evidence gate".to_owned(),
        };
    }

    let positive_signals = stage1_report
        .action_summaries
        .iter()
        .map(|summary| summary.positive_signal_count)
        .sum::<u32>();
    let negative_signals = stage1_report
        .action_summaries
        .iter()
        .map(|summary| summary.negative_signal_count)
        .sum::<u32>();
    let total_directional_signals = positive_signals.saturating_add(negative_signals);

    if total_directional_signals == 0 {
        return ContextualBanditExperimentReport {
            recommendation: ContextualBanditRecommendation::StopStage1Gate,
            stage1_recommendation: stage1_report.recommendation,
            shadow_experiment_allowed: false,
            runtime_policy_update_allowed: false,
            proposed_weight_deltas: Vec::new(),
            rationale: "Stage 1 had no directional human labels for weight planning".to_owned(),
        };
    }

    let delta_scale = (stage1_report.score_margin * config.learning_rate)
        .abs()
        .min(config.max_weight_delta);
    let total = f64::from(total_directional_signals);
    let mut proposed_weight_deltas = Vec::new();

    if positive_signals > 0 {
        let delta = delta_scale * (f64::from(positive_signals) / total);
        proposed_weight_deltas.push(SignificanceWeightDelta {
            weight_name: "cited_weight".to_owned(),
            current_value: current_significance.cited_weight,
            delta,
            proposed_value: current_significance.cited_weight + delta,
        });
    }

    if negative_signals > 0 {
        let delta = -delta_scale * (f64::from(negative_signals) / total);
        proposed_weight_deltas.push(SignificanceWeightDelta {
            weight_name: "contradicted_weight".to_owned(),
            current_value: current_significance.contradicted_weight,
            delta,
            proposed_value: current_significance.contradicted_weight + delta,
        });
    }

    ContextualBanditExperimentReport {
        recommendation: ContextualBanditRecommendation::ProceedToShadowExperiment,
        stage1_recommendation: stage1_report.recommendation,
        shadow_experiment_allowed: true,
        runtime_policy_update_allowed: false,
        proposed_weight_deltas,
        rationale: "Stage 2 may run as a shadow experiment over existing significance weights"
            .to_owned(),
    }
}

#[must_use]
fn unsafe_bandit_config_reason(config: ContextualBanditExperimentConfig) -> Option<&'static str> {
    if !config.min_stage1_score_margin.is_finite() || config.min_stage1_score_margin < 0.0 {
        return Some("Stage 2 minimum score margin must be finite and non-negative");
    }
    if !config.learning_rate.is_finite()
        || config.learning_rate <= 0.0
        || config.learning_rate > 1.0
    {
        return Some("Stage 2 learning rate must be finite and in the range (0, 1]");
    }
    if !config.max_weight_delta.is_finite() || config.max_weight_delta <= 0.0 {
        return Some("Stage 2 maximum weight delta must be finite and positive");
    }

    None
}

/// Required artifact for Stage 3 policy-model training readiness.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
pub enum Stage3TrainingPrerequisite {
    /// A written GPU/cost/runtime budget exists.
    GpuAndCostPlan,
    /// A training data card exists with volume, source, privacy, and split details.
    TrainingDatasetCard,
    /// Reward ablations exist for human labels, task outcome, and invariant penalties.
    RewardAblations,
    /// Property tests or model-checking cover the full non-destructive action trace.
    InvariantPropertyTests,
    /// A held-out continuity eval exists against the deterministic significance baseline.
    HeldoutContinuityEval,
}

impl Stage3TrainingPrerequisite {
    const ALL: [Self; 5] = [
        Self::GpuAndCostPlan,
        Self::TrainingDatasetCard,
        Self::RewardAblations,
        Self::InvariantPropertyTests,
        Self::HeldoutContinuityEval,
    ];

    const fn name(self) -> &'static str {
        match self {
            Self::GpuAndCostPlan => "gpu_and_cost_plan",
            Self::TrainingDatasetCard => "training_dataset_card",
            Self::RewardAblations => "reward_ablations",
            Self::InvariantPropertyTests => "invariant_property_tests",
            Self::HeldoutContinuityEval => "heldout_continuity_eval",
        }
    }
}

/// Configuration for Stage 3 policy-model training readiness.
#[derive(Clone, Debug, Default, Deserialize, PartialEq, Serialize)]
pub struct Stage3TrainingReadinessConfig {
    /// Stage 3 readiness checks are disabled unless a caller explicitly opts in.
    pub enabled: bool,
    /// Completed prerequisite artifacts.
    pub completed_prerequisites: BTreeSet<Stage3TrainingPrerequisite>,
}

/// Stage 3 readiness recommendation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum Stage3TrainingRecommendation {
    /// Stage 3 readiness checking was not explicitly enabled.
    Disabled,
    /// Stage 2 did not clear its gate.
    StopStage2Gate,
    /// Required research artifacts are missing.
    StopMissingPrerequisites,
    /// Offline model-training research may start; runtime deployment is still blocked.
    ProceedToOfflineTrainingResearch,
}

/// Stage 3 readiness report.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct Stage3TrainingReadinessReport {
    /// Stage 3 readiness recommendation.
    pub recommendation: Stage3TrainingRecommendation,
    /// Missing prerequisite artifact names.
    pub missing_prerequisites: Vec<String>,
    /// Offline training research is allowed only after Stage 2 and all prerequisites pass.
    pub offline_training_research_allowed: bool,
    /// Runtime deployment remains blocked by this readiness API.
    pub runtime_deployment_allowed: bool,
    /// Human-readable gate rationale.
    pub rationale: String,
}

/// Assesses whether Stage 3 GRPO/PPO-style research is ready to begin.
///
/// This is a readiness gate only. It does not train a model and never authorizes runtime
/// deployment of a learned policy.
#[must_use]
pub fn assess_stage3_training_readiness(
    stage2_report: &ContextualBanditExperimentReport,
    config: &Stage3TrainingReadinessConfig,
) -> Stage3TrainingReadinessReport {
    if !config.enabled {
        return Stage3TrainingReadinessReport {
            recommendation: Stage3TrainingRecommendation::Disabled,
            missing_prerequisites: Vec::new(),
            offline_training_research_allowed: false,
            runtime_deployment_allowed: false,
            rationale: "Stage 3 readiness checking is disabled by default".to_owned(),
        };
    }

    if stage2_report.recommendation != ContextualBanditRecommendation::ProceedToShadowExperiment {
        return Stage3TrainingReadinessReport {
            recommendation: Stage3TrainingRecommendation::StopStage2Gate,
            missing_prerequisites: Vec::new(),
            offline_training_research_allowed: false,
            runtime_deployment_allowed: false,
            rationale: "Stage 2 did not clear the shadow-experiment gate".to_owned(),
        };
    }

    let mut missing_prerequisites = Vec::new();
    for prerequisite in Stage3TrainingPrerequisite::ALL {
        if !config.completed_prerequisites.contains(&prerequisite) {
            missing_prerequisites.push(prerequisite.name().to_owned());
        }
    }

    if !missing_prerequisites.is_empty() {
        return Stage3TrainingReadinessReport {
            recommendation: Stage3TrainingRecommendation::StopMissingPrerequisites,
            missing_prerequisites,
            offline_training_research_allowed: false,
            runtime_deployment_allowed: false,
            rationale: "Stage 3 is missing required research and safety artifacts".to_owned(),
        };
    }

    Stage3TrainingReadinessReport {
        recommendation: Stage3TrainingRecommendation::ProceedToOfflineTrainingResearch,
        missing_prerequisites,
        offline_training_research_allowed: true,
        runtime_deployment_allowed: false,
        rationale: "Offline Stage 3 training research may begin; deployment remains gated"
            .to_owned(),
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

    fn proceeding_stage1_report() -> OfflinePolicyEvaluationReport {
        let positive = memory("stable useful preference", Tier::Warm, Tier::Cold, 1.0);
        let negative = memory("contested endpoint", Tier::Warm, Tier::Cold, 1.0);
        let decisions = vec![
            OfflinePolicyDecision::new(
                positive.id,
                PolicyAction::Promote { to: Tier::Hot },
                "positive labels favored promotion",
            ),
            OfflinePolicyDecision::new(
                negative.id,
                PolicyAction::FlagForReview,
                "negative labels favored review",
            ),
        ];
        let events = vec![
            human_signal_event(
                0,
                positive.id,
                HumanSignalAction::Affirm,
                OffsetDateTime::UNIX_EPOCH + Duration::hours(1),
            ),
            human_signal_event(
                1,
                negative.id,
                HumanSignalAction::Challenge,
                OffsetDateTime::UNIX_EPOCH + Duration::hours(1),
            ),
        ];

        evaluate_offline_policy(
            &decisions,
            &[positive, negative],
            &events,
            single_label_config(),
        )
        .expect("evaluation should succeed")
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
    fn action_summary_drift_returns_recoverable_error() {
        let item = memory("review this", Tier::Warm, Tier::Cold, 1.0);
        let evaluation = DecisionEvaluation {
            memory_id: item.id,
            candidate_action: PolicyAction::FlagForReview,
            baseline_action: PolicyAction::Noop,
            human_signals: HumanSignalSummary::default(),
            candidate_score: 0.0,
            baseline_score: 0.0,
            invariant_violations: Vec::new(),
        };
        let error = summarize_decisions_by_action_with_names(&[evaluation], &["noop"])
            .expect_err("stale action list should return an error");

        assert_eq!(
            error,
            PolicyEvaluationError::MissingActionSummary {
                action_name: "flag_for_review".to_owned()
            }
        );
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
        let report = evaluate_offline_policy(&[decision], &[item], &events, single_label_config())
            .expect("evaluation should succeed");

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
        )
        .expect("evaluation should succeed");

        assert_eq!(
            report.recommendation,
            PolicyEvaluationRecommendation::StopInsufficientSignal
        );
        assert_eq!(report.labeled_decision_count, 0);
        assert!(report.candidate_score.abs() <= f64::EPSILON);
        assert_eq!(
            report
                .null_result
                .as_ref()
                .map(|result| result.recommendation),
            Some(PolicyEvaluationRecommendation::StopInsufficientSignal)
        );
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
        let report = evaluate_offline_policy(&[decision], &[item], &events, single_label_config())
            .expect("evaluation should succeed");
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
        )
        .expect("evaluation should succeed");
        assert!(valid_report.invariant_violations.is_empty());

        let invalid_report = evaluate_offline_policy(
            &[invalid_decision],
            &[first, second],
            &events,
            single_label_config(),
        )
        .expect("evaluation should succeed");
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
        let report = evaluate_offline_policy(&[decision], &[item], &events, single_label_config())
            .expect("evaluation should succeed");

        assert_eq!(
            report.recommendation,
            PolicyEvaluationRecommendation::StopBaselineNotBeaten
        );
        assert!(report.score_margin < 0.0);
        assert_eq!(
            report
                .null_result
                .as_ref()
                .map(|result| result.recommendation),
            Some(PolicyEvaluationRecommendation::StopBaselineNotBeaten)
        );
        let promote_summary = report
            .action_summaries
            .iter()
            .find(|summary| summary.action_name == "promote")
            .expect("promote summary should exist");
        assert_eq!(promote_summary.decision_count, 1);
        assert_eq!(promote_summary.negative_signal_count, 1);
    }

    #[test]
    fn stage2_bandit_planning_is_disabled_by_default() {
        let report = proceeding_stage1_report();
        let stage2 = plan_contextual_bandit_experiment(
            &report,
            SignificanceConfig::default(),
            ContextualBanditExperimentConfig::default(),
        );

        assert_eq!(
            stage2.recommendation,
            ContextualBanditRecommendation::Disabled
        );
        assert!(!stage2.shadow_experiment_allowed);
        assert!(!stage2.runtime_policy_update_allowed);
        assert!(stage2.proposed_weight_deltas.is_empty());
    }

    #[test]
    fn stage2_bandit_planning_stops_when_stage1_does_not_clear_gate() {
        let item = memory("weak signal", Tier::Warm, Tier::Cold, 1.0);
        let decision =
            OfflinePolicyDecision::new(item.id, PolicyAction::FlagForReview, "no labels");
        let report = evaluate_offline_policy(
            &[decision],
            &[item],
            &[],
            OfflinePolicyEvaluationConfig::default(),
        )
        .expect("evaluation should succeed");
        let stage2 = plan_contextual_bandit_experiment(
            &report,
            SignificanceConfig::default(),
            ContextualBanditExperimentConfig {
                enabled: true,
                min_stage1_labeled_decisions: 1,
                min_stage1_score_margin: 0.0,
                ..ContextualBanditExperimentConfig::default()
            },
        );

        assert_eq!(
            stage2.recommendation,
            ContextualBanditRecommendation::StopStage1Gate
        );
        assert!(!stage2.shadow_experiment_allowed);
    }

    #[test]
    fn stage2_bandit_planning_returns_bounded_shadow_weight_deltas() {
        let report = proceeding_stage1_report();
        let significance = SignificanceConfig::default();
        let stage2 = plan_contextual_bandit_experiment(
            &report,
            significance,
            ContextualBanditExperimentConfig {
                enabled: true,
                min_stage1_labeled_decisions: 1,
                min_stage1_score_margin: 0.0,
                learning_rate: 0.25,
                max_weight_delta: 0.10,
            },
        );

        assert_eq!(
            stage2.recommendation,
            ContextualBanditRecommendation::ProceedToShadowExperiment
        );
        assert!(stage2.shadow_experiment_allowed);
        assert!(!stage2.runtime_policy_update_allowed);
        assert_eq!(stage2.proposed_weight_deltas.len(), 2);
        assert!(stage2.proposed_weight_deltas.iter().all(|delta| {
            delta.delta.abs() <= 0.10
                && (delta.current_value + delta.delta - delta.proposed_value).abs() <= f64::EPSILON
        }));
        assert!(stage2.proposed_weight_deltas.iter().any(|delta| {
            delta.weight_name == "cited_weight" && delta.proposed_value > significance.cited_weight
        }));
        assert!(stage2.proposed_weight_deltas.iter().any(|delta| {
            delta.weight_name == "contradicted_weight"
                && delta.proposed_value < significance.contradicted_weight
        }));
    }

    #[test]
    fn stage3_readiness_is_disabled_and_fail_closed_until_prerequisites_exist() {
        let report = proceeding_stage1_report();
        let stage2 = plan_contextual_bandit_experiment(
            &report,
            SignificanceConfig::default(),
            ContextualBanditExperimentConfig {
                enabled: true,
                min_stage1_labeled_decisions: 1,
                min_stage1_score_margin: 0.0,
                ..ContextualBanditExperimentConfig::default()
            },
        );

        let disabled =
            assess_stage3_training_readiness(&stage2, &Stage3TrainingReadinessConfig::default());
        assert_eq!(
            disabled.recommendation,
            Stage3TrainingRecommendation::Disabled
        );

        let missing = assess_stage3_training_readiness(
            &stage2,
            &Stage3TrainingReadinessConfig {
                enabled: true,
                ..Stage3TrainingReadinessConfig::default()
            },
        );
        assert_eq!(
            missing.recommendation,
            Stage3TrainingRecommendation::StopMissingPrerequisites
        );
        assert!(
            missing
                .missing_prerequisites
                .contains(&"gpu_and_cost_plan".to_owned())
        );
        assert!(!missing.offline_training_research_allowed);
        assert!(!missing.runtime_deployment_allowed);
    }

    #[test]
    fn stage3_readiness_allows_only_offline_research_after_all_gates() {
        let report = proceeding_stage1_report();
        let stage2 = plan_contextual_bandit_experiment(
            &report,
            SignificanceConfig::default(),
            ContextualBanditExperimentConfig {
                enabled: true,
                min_stage1_labeled_decisions: 1,
                min_stage1_score_margin: 0.0,
                ..ContextualBanditExperimentConfig::default()
            },
        );
        let ready = assess_stage3_training_readiness(
            &stage2,
            &Stage3TrainingReadinessConfig {
                enabled: true,
                completed_prerequisites: [
                    Stage3TrainingPrerequisite::GpuAndCostPlan,
                    Stage3TrainingPrerequisite::TrainingDatasetCard,
                    Stage3TrainingPrerequisite::RewardAblations,
                    Stage3TrainingPrerequisite::InvariantPropertyTests,
                    Stage3TrainingPrerequisite::HeldoutContinuityEval,
                ]
                .into_iter()
                .collect(),
            },
        );

        assert_eq!(
            ready.recommendation,
            Stage3TrainingRecommendation::ProceedToOfflineTrainingResearch
        );
        assert!(ready.offline_training_research_allowed);
        assert!(!ready.runtime_deployment_allowed);
    }
}
