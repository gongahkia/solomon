// SPDX-License-Identifier: MIT

//! Significance scoring primitives.

use crate::model::{AccessEvent, AccessOutcome, MemoryItem, Tier};
use serde::{Deserialize, Serialize};
use time::OffsetDateTime;

/// Configuration for the transparent significance function.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SignificanceConfig {
    /// Half-life in seconds for decay since last use.
    pub half_life_seconds: f64,
    /// Weight applied to the diminishing-returns access reinforcement term.
    pub reinforcement_weight: f64,
    /// Bonus for a memory merely surfaced by recall.
    pub surfaced_weight: f64,
    /// Bonus for a memory that led to useful work.
    pub led_somewhere_weight: f64,
    /// Bonus for a memory cited in output.
    pub cited_weight: f64,
    /// Penalty for a surfaced memory ignored by the caller.
    pub ignored_weight: f64,
    /// Penalty for contradiction outcomes.
    pub contradicted_weight: f64,
    /// Weight applied to graph centrality supplied by graph storage.
    pub graph_centrality_weight: f64,
    /// Score at or above which cold items may promote to warm.
    pub warm_threshold: f64,
    /// Score at or above which warm items may promote to hot.
    pub hot_threshold: f64,
    /// Score below which warm items demote to cold.
    pub warm_demotion_threshold: f64,
    /// Score below which hot items demote to warm.
    pub hot_demotion_threshold: f64,
}

/// Deterministic contribution breakdown for a significance score.
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
pub struct SignificanceBreakdown {
    /// Base score before access-derived adjustments.
    pub base_score: f64,
    /// Time-decay multiplier applied to the base score.
    pub decay_multiplier: f64,
    /// Base score after decay.
    pub decayed_base: f64,
    /// Diminishing-returns access reinforcement.
    pub reinforcement: f64,
    /// Weighted access-outcome contribution.
    pub outcome_bonus: f64,
    /// Positive penalty from contradiction outcomes.
    pub contradiction_penalty: f64,
    /// Weighted graph-centrality contribution.
    pub graph_centrality: f64,
    /// Final score after all transparent terms.
    pub final_score: f64,
}

impl Default for SignificanceConfig {
    fn default() -> Self {
        Self {
            half_life_seconds: 30.0 * 24.0 * 60.0 * 60.0,
            reinforcement_weight: 1.0,
            surfaced_weight: 0.1,
            led_somewhere_weight: 1.0,
            cited_weight: 1.25,
            ignored_weight: -0.05,
            contradicted_weight: -2.0,
            graph_centrality_weight: 0.0,
            warm_threshold: 1.0,
            hot_threshold: 2.0,
            warm_demotion_threshold: 0.8,
            hot_demotion_threshold: 1.8,
        }
    }
}

/// Pluggable significance scoring policy.
pub trait SignificanceFunction {
    /// Computes an explainable significance breakdown for `item`.
    fn explain(&self, item: &MemoryItem, now: OffsetDateTime) -> SignificanceBreakdown;

    /// Recomputes the materialized significance score for `item`.
    fn recompute(&self, item: &MemoryItem, now: OffsetDateTime) -> f64 {
        self.explain(item, now).final_score
    }

    /// Applies policy-specific tier clamping.
    fn clamp_tier_to_credence_floor(&self, item: &MemoryItem, proposed_tier: Tier) -> Tier {
        proposed_tier.max(item.credence_floor)
    }

    /// Applies policy-specific access promotion thresholds.
    fn promote_on_access(&self, current_tier: Tier, score: f64) -> Tier;

    /// Applies policy-specific decay demotion thresholds.
    fn demote_for_score(&self, current_tier: Tier, score: f64) -> Tier;
}

impl SignificanceConfig {
    /// Computes a decay multiplier from `last_used_at` to `now`.
    ///
    /// The multiplier is `1.0` at the last use time and `0.5` after one configured half-life.
    #[must_use]
    pub fn time_decay(self, last_used_at: OffsetDateTime, now: OffsetDateTime) -> f64 {
        if now <= last_used_at {
            return 1.0;
        }

        let elapsed_seconds = (now - last_used_at).as_seconds_f64();

        0.5_f64.powf(elapsed_seconds / self.half_life_seconds)
    }

    /// Computes a diminishing-returns reinforcement score from access count.
    #[must_use]
    pub fn reinforcement(self, access_count: usize) -> f64 {
        let capped_count = u32::try_from(access_count).unwrap_or(u32::MAX);

        self.reinforcement_weight * f64::from(capped_count).ln_1p()
    }

    /// Returns the configured score contribution for one access outcome.
    #[must_use]
    pub fn outcome_weight(self, outcome: AccessOutcome) -> f64 {
        match outcome {
            AccessOutcome::Surfaced => self.surfaced_weight,
            AccessOutcome::LedSomewhere => self.led_somewhere_weight,
            AccessOutcome::Cited => self.cited_weight,
            AccessOutcome::Ignored => self.ignored_weight,
            AccessOutcome::Contradicted => 0.0,
        }
    }

    /// Computes total outcome contribution for access events.
    #[must_use]
    pub fn outcome_bonus(self, events: &[AccessEvent]) -> f64 {
        events
            .iter()
            .map(|event| self.outcome_weight(event.outcome))
            .sum()
    }

    /// Computes a positive contradiction penalty from access events.
    #[must_use]
    pub fn contradiction_penalty(self, events: &[AccessEvent]) -> f64 {
        let contradiction_count = events
            .iter()
            .filter(|event| event.outcome == AccessOutcome::Contradicted)
            .count();
        let capped_count = u32::try_from(contradiction_count).unwrap_or(u32::MAX);

        f64::from(capped_count) * self.contradicted_weight.abs()
    }

    /// Computes a full significance explanation for an item at `now`.
    #[must_use]
    pub fn explain(self, item: &MemoryItem, now: OffsetDateTime) -> SignificanceBreakdown {
        self.explain_with_graph_centrality(item, now, 0.0)
    }

    /// Computes a full significance explanation with an external graph-centrality score.
    #[must_use]
    pub fn explain_with_graph_centrality(
        self,
        item: &MemoryItem,
        now: OffsetDateTime,
        graph_centrality_score: f64,
    ) -> SignificanceBreakdown {
        let mut last_used_at = item.timestamps.ingested_at;
        let mut outcome_bonus = 0.0;
        let mut contradiction_count = 0_u32;

        for event in &item.access_events {
            last_used_at = last_used_at.max(event.timestamp);
            outcome_bonus += self.outcome_weight(event.outcome);
            if event.outcome == AccessOutcome::Contradicted {
                contradiction_count = contradiction_count.saturating_add(1);
            }
        }

        let decay_multiplier = self.time_decay(last_used_at, now);
        let decayed_base = item.base_significance * decay_multiplier;
        let reinforcement = self.reinforcement(item.access_events.len());
        let contradiction_penalty = f64::from(contradiction_count) * self.contradicted_weight.abs();
        let graph_centrality = self.graph_centrality_weight * graph_centrality_score;
        let final_score =
            decayed_base + reinforcement + outcome_bonus + graph_centrality - contradiction_penalty;

        SignificanceBreakdown {
            base_score: item.base_significance,
            decay_multiplier,
            decayed_base,
            reinforcement,
            outcome_bonus,
            contradiction_penalty,
            graph_centrality,
            final_score,
        }
    }

    /// Recomputes the materialized significance score for an item at `now`.
    #[must_use]
    pub fn recompute(self, item: &MemoryItem, now: OffsetDateTime) -> f64 {
        self.explain(item, now).final_score
    }

    /// Recomputes the materialized significance score with an external graph-centrality score.
    #[must_use]
    pub fn recompute_with_graph_centrality(
        self,
        item: &MemoryItem,
        now: OffsetDateTime,
        graph_centrality_score: f64,
    ) -> f64 {
        self.explain_with_graph_centrality(item, now, graph_centrality_score)
            .final_score
    }

    /// Applies the item's credence floor to a proposed tier.
    #[must_use]
    pub fn clamp_tier_to_credence_floor(self, item: &MemoryItem, proposed_tier: Tier) -> Tier {
        proposed_tier.max(item.credence_floor)
    }

    /// Applies threshold-based promotion after access.
    #[must_use]
    pub fn promote_on_access(self, current_tier: Tier, score: f64) -> Tier {
        if score >= self.hot_threshold {
            Tier::Hot
        } else if score >= self.warm_threshold {
            current_tier.max(Tier::Warm)
        } else {
            current_tier
        }
    }

    /// Applies threshold-based demotion as significance decays.
    #[must_use]
    pub fn demote_for_score(self, current_tier: Tier, score: f64) -> Tier {
        if score < self.warm_demotion_threshold {
            Tier::Cold
        } else if score < self.hot_demotion_threshold && current_tier == Tier::Hot {
            Tier::Warm
        } else {
            current_tier
        }
    }
}

impl SignificanceFunction for SignificanceConfig {
    fn explain(&self, item: &MemoryItem, now: OffsetDateTime) -> SignificanceBreakdown {
        (*self).explain(item, now)
    }

    fn promote_on_access(&self, current_tier: Tier, score: f64) -> Tier {
        (*self).promote_on_access(current_tier, score)
    }

    fn demote_for_score(&self, current_tier: Tier, score: f64) -> Tier {
        (*self).demote_for_score(current_tier, score)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use time::Duration;

    #[test]
    fn time_decay_halves_after_one_half_life() {
        let config = SignificanceConfig {
            half_life_seconds: 10.0,
            ..SignificanceConfig::default()
        };
        let start = OffsetDateTime::UNIX_EPOCH;
        let decayed = config.time_decay(start, start + Duration::seconds(10));

        assert!((decayed - 0.5).abs() < f64::EPSILON);
    }

    #[test]
    fn time_decay_does_not_increase_for_future_last_use() {
        let config = SignificanceConfig {
            half_life_seconds: 10.0,
            ..SignificanceConfig::default()
        };
        let now = OffsetDateTime::UNIX_EPOCH;

        assert!((config.time_decay(now + Duration::seconds(1), now) - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn reinforcement_grows_with_diminishing_returns() {
        let config = SignificanceConfig {
            reinforcement_weight: 2.0,
            ..SignificanceConfig::default()
        };
        let first = config.reinforcement(1);
        let second = config.reinforcement(2);
        let tenth = config.reinforcement(10);

        assert!(first > 0.0);
        assert!(second > first);
        assert!(tenth > second);
        assert!((second - first) > (tenth - config.reinforcement(9)));
    }

    #[test]
    fn outcome_weighting_rewards_use_more_than_surfacing() {
        let config = SignificanceConfig::default();
        let now = OffsetDateTime::UNIX_EPOCH;
        let events = vec![
            AccessEvent::new(now, None, AccessOutcome::Surfaced),
            AccessEvent::new(now, None, AccessOutcome::LedSomewhere),
            AccessEvent::new(now, None, AccessOutcome::Cited),
        ];

        assert!(
            config.outcome_weight(AccessOutcome::LedSomewhere)
                > config.outcome_weight(AccessOutcome::Surfaced)
        );
        assert!(config.outcome_bonus(&events) > config.outcome_weight(AccessOutcome::Surfaced));
        assert!(config.outcome_weight(AccessOutcome::Contradicted).abs() < f64::EPSILON);
    }

    #[test]
    fn contradiction_penalty_scales_with_contradictions() {
        let config = SignificanceConfig::default();
        let now = OffsetDateTime::UNIX_EPOCH;
        let events = vec![
            AccessEvent::new(now, None, AccessOutcome::Contradicted),
            AccessEvent::new(now, None, AccessOutcome::LedSomewhere),
            AccessEvent::new(now, None, AccessOutcome::Contradicted),
        ];

        let expected = config.contradicted_weight.abs() * 2.0;

        assert!((config.contradiction_penalty(&events) - expected).abs() < f64::EPSILON);
    }

    #[test]
    fn contradicted_access_applies_one_penalty() {
        let config = SignificanceConfig::default();
        let now = OffsetDateTime::UNIX_EPOCH;
        let item = MemoryItem {
            schema_version: crate::model::CURRENT_MEMORY_SCHEMA_VERSION,
            id: crate::model::MemoryId::new_v7(),
            content: "contradicted".to_owned(),
            kind: crate::model::MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            embedding_ref: None,
            provenance: crate::model::Provenance::new(
                crate::model::SourceKind::User,
                None,
                "significance-test",
            ),
            timestamps: crate::model::TemporalBounds::open_from(now, now),
            tier: crate::model::Tier::Warm,
            credence: crate::model::CredenceTier::VerifiedSource,
            significance: 10.0,
            base_significance: 10.0,
            credence_floor: crate::model::Tier::Cold,
            access_events: vec![AccessEvent::new(now, None, AccessOutcome::Contradicted)],
        };

        let breakdown = config.explain(&item, now);
        let expected_penalty = config.contradicted_weight.abs();
        let expected_score = breakdown.decayed_base + breakdown.reinforcement - expected_penalty;

        assert!(breakdown.outcome_bonus.abs() < f64::EPSILON);
        assert!((breakdown.contradiction_penalty - expected_penalty).abs() < f64::EPSILON);
        assert!((breakdown.final_score - expected_score).abs() < f64::EPSILON);
    }

    #[test]
    fn explain_recomputes_score_from_access_log_lazily() {
        let config = SignificanceConfig::default();
        let now = OffsetDateTime::UNIX_EPOCH;
        let mut item = MemoryItem {
            schema_version: crate::model::CURRENT_MEMORY_SCHEMA_VERSION,
            id: crate::model::MemoryId::new_v7(),
            content: "score me".to_owned(),
            kind: crate::model::MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            embedding_ref: None,
            provenance: crate::model::Provenance::new(
                crate::model::SourceKind::User,
                None,
                "significance-test",
            ),
            timestamps: crate::model::TemporalBounds::open_from(now, now),
            tier: crate::model::Tier::Warm,
            credence: crate::model::CredenceTier::VerifiedSource,
            significance: 1.0,
            base_significance: 1.0,
            credence_floor: crate::model::Tier::Cold,
            access_events: Vec::new(),
        };

        item.access_events
            .push(AccessEvent::new(now, None, AccessOutcome::LedSomewhere));

        let breakdown = config.explain(&item, now);

        assert!(breakdown.reinforcement > 0.0);
        assert!(breakdown.outcome_bonus > 0.0);
        assert!(breakdown.graph_centrality.abs() < f64::EPSILON);
        assert!((config.recompute(&item, now) - breakdown.final_score).abs() < f64::EPSILON);
    }

    #[test]
    fn recompute_is_idempotent_from_base_score_and_access_log() {
        let config = SignificanceConfig::default();
        let now = OffsetDateTime::UNIX_EPOCH + Duration::seconds(10);
        let mut item = MemoryItem {
            schema_version: crate::model::CURRENT_MEMORY_SCHEMA_VERSION,
            id: crate::model::MemoryId::new_v7(),
            content: "stable recompute".to_owned(),
            kind: crate::model::MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            embedding_ref: None,
            provenance: crate::model::Provenance::new(
                crate::model::SourceKind::User,
                None,
                "significance-test",
            ),
            timestamps: crate::model::TemporalBounds::open_from(
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ),
            tier: crate::model::Tier::Warm,
            credence: crate::model::CredenceTier::VerifiedSource,
            significance: 1.0,
            base_significance: 1.0,
            credence_floor: crate::model::Tier::Cold,
            access_events: vec![
                AccessEvent::new(now, None, AccessOutcome::Surfaced),
                AccessEvent::new(now, None, AccessOutcome::Cited),
            ],
        };

        let first = config.recompute(&item, now);
        item.significance = first;
        let second = config.recompute(&item, now);

        assert!((second - first).abs() < f64::EPSILON);
    }

    #[test]
    fn explain_access_summary_matches_separate_pass_helpers() {
        let config = SignificanceConfig::default();
        let mut item = MemoryItem {
            schema_version: crate::model::CURRENT_MEMORY_SCHEMA_VERSION,
            id: crate::model::MemoryId::new_v7(),
            content: "single pass".to_owned(),
            kind: crate::model::MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            embedding_ref: None,
            provenance: crate::model::Provenance::new(
                crate::model::SourceKind::User,
                None,
                "significance-test",
            ),
            timestamps: crate::model::TemporalBounds::open_from(
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ),
            tier: crate::model::Tier::Warm,
            credence: crate::model::CredenceTier::VerifiedSource,
            significance: 2.0,
            base_significance: 2.0,
            credence_floor: crate::model::Tier::Cold,
            access_events: vec![
                AccessEvent::new(
                    OffsetDateTime::UNIX_EPOCH + Duration::seconds(5),
                    None,
                    AccessOutcome::Surfaced,
                ),
                AccessEvent::new(
                    OffsetDateTime::UNIX_EPOCH + Duration::seconds(10),
                    None,
                    AccessOutcome::Cited,
                ),
                AccessEvent::new(
                    OffsetDateTime::UNIX_EPOCH + Duration::seconds(7),
                    None,
                    AccessOutcome::Contradicted,
                ),
            ],
        };
        let now = OffsetDateTime::UNIX_EPOCH + Duration::seconds(20);
        let separate_last_used = item
            .access_events
            .iter()
            .map(|event| event.timestamp)
            .max()
            .expect("access history should be non-empty");
        let expected_decayed_base =
            item.base_significance * config.time_decay(separate_last_used, now);
        let expected_outcome_bonus = config.outcome_bonus(&item.access_events);
        let expected_contradiction_penalty = config.contradiction_penalty(&item.access_events);
        let explanation = config.explain(&item, now);

        item.access_events.reverse();
        let reversed = config.explain(&item, now);

        assert!((explanation.decayed_base - expected_decayed_base).abs() < f64::EPSILON);
        assert!((explanation.outcome_bonus - expected_outcome_bonus).abs() < f64::EPSILON);
        assert!(
            (explanation.contradiction_penalty - expected_contradiction_penalty).abs()
                < f64::EPSILON
        );
        assert!((reversed.final_score - explanation.final_score).abs() < f64::EPSILON);
    }

    #[test]
    fn graph_centrality_can_contribute_to_significance() {
        let config = SignificanceConfig {
            graph_centrality_weight: 2.0,
            ..SignificanceConfig::default()
        };
        let now = OffsetDateTime::UNIX_EPOCH;
        let item = MemoryItem {
            schema_version: crate::model::CURRENT_MEMORY_SCHEMA_VERSION,
            id: crate::model::MemoryId::new_v7(),
            content: "central".to_owned(),
            kind: crate::model::MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            embedding_ref: None,
            provenance: crate::model::Provenance::new(
                crate::model::SourceKind::User,
                None,
                "significance-test",
            ),
            timestamps: crate::model::TemporalBounds::open_from(now, now),
            tier: crate::model::Tier::Warm,
            credence: crate::model::CredenceTier::VerifiedSource,
            significance: 1.0,
            base_significance: 1.0,
            credence_floor: crate::model::Tier::Cold,
            access_events: Vec::new(),
        };
        let breakdown = config.explain_with_graph_centrality(&item, now, 3.0);

        assert!((breakdown.graph_centrality - 6.0).abs() < f64::EPSILON);
        assert!(
            (config.recompute_with_graph_centrality(&item, now, 3.0) - breakdown.final_score).abs()
                < f64::EPSILON
        );
    }

    #[test]
    fn significance_policy_respects_credence_floor() {
        let config = SignificanceConfig::default();
        let now = OffsetDateTime::UNIX_EPOCH;
        let item = MemoryItem {
            schema_version: crate::model::CURRENT_MEMORY_SCHEMA_VERSION,
            id: crate::model::MemoryId::new_v7(),
            content: "floor me".to_owned(),
            kind: crate::model::MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            embedding_ref: None,
            provenance: crate::model::Provenance::new(
                crate::model::SourceKind::User,
                None,
                "significance-test",
            ),
            timestamps: crate::model::TemporalBounds::open_from(now, now),
            tier: crate::model::Tier::Hot,
            credence: crate::model::CredenceTier::FirmAuthoritative,
            significance: 0.0,
            base_significance: 0.0,
            credence_floor: crate::model::Tier::Warm,
            access_events: Vec::new(),
        };

        assert_eq!(
            config.clamp_tier_to_credence_floor(&item, Tier::Cold),
            Tier::Warm
        );
    }

    #[test]
    fn promote_on_access_uses_score_thresholds() {
        let config = SignificanceConfig::default();

        assert_eq!(config.promote_on_access(Tier::Cold, 1.0), Tier::Warm);
        assert_eq!(config.promote_on_access(Tier::Warm, 2.0), Tier::Hot);
        assert_eq!(config.promote_on_access(Tier::Cold, 0.1), Tier::Cold);
    }

    #[test]
    fn demote_for_score_uses_decay_thresholds() {
        let config = SignificanceConfig::default();

        assert_eq!(config.demote_for_score(Tier::Hot, 1.0), Tier::Warm);
        assert_eq!(config.demote_for_score(Tier::Warm, 0.1), Tier::Cold);
        assert_eq!(config.demote_for_score(Tier::Cold, 0.1), Tier::Cold);
    }

    #[test]
    fn demotion_thresholds_create_hysteresis_gap() {
        let config = SignificanceConfig::default();

        assert_eq!(config.promote_on_access(Tier::Warm, 2.0), Tier::Hot);
        assert_eq!(config.demote_for_score(Tier::Hot, 1.9), Tier::Hot);
        assert_eq!(config.demote_for_score(Tier::Hot, 1.7), Tier::Warm);
        assert_eq!(config.promote_on_access(Tier::Cold, 1.0), Tier::Warm);
        assert_eq!(config.demote_for_score(Tier::Warm, 0.9), Tier::Warm);
        assert_eq!(config.demote_for_score(Tier::Warm, 0.7), Tier::Cold);
    }

    #[test]
    fn significance_function_trait_supports_swappable_policy() {
        let config = SignificanceConfig::default();
        let policy: &dyn SignificanceFunction = &config;
        let now = OffsetDateTime::UNIX_EPOCH;
        let item = MemoryItem {
            schema_version: crate::model::CURRENT_MEMORY_SCHEMA_VERSION,
            id: crate::model::MemoryId::new_v7(),
            content: "policy".to_owned(),
            kind: crate::model::MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            embedding_ref: None,
            provenance: crate::model::Provenance::new(
                crate::model::SourceKind::User,
                None,
                "significance-test",
            ),
            timestamps: crate::model::TemporalBounds::open_from(now, now),
            tier: crate::model::Tier::Warm,
            credence: crate::model::CredenceTier::VerifiedSource,
            significance: 1.0,
            base_significance: 1.0,
            credence_floor: crate::model::Tier::Cold,
            access_events: Vec::new(),
        };

        assert!((policy.recompute(&item, now) - config.recompute(&item, now)).abs() < f64::EPSILON);
    }
}
