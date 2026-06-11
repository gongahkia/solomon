// SPDX-License-Identifier: MIT

//! Significance scoring primitives.

use crate::model::{AccessEvent, AccessOutcome, MemoryItem};
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
}

/// Deterministic contribution breakdown for a significance score.
#[derive(Clone, Copy, Debug, PartialEq)]
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
        }
    }
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
            AccessOutcome::Contradicted => self.contradicted_weight,
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
        let last_used_at = item
            .access_events
            .iter()
            .map(|event| event.timestamp)
            .max()
            .unwrap_or(item.timestamps.ingested_at);
        let decay_multiplier = self.time_decay(last_used_at, now);
        let decayed_base = item.significance * decay_multiplier;
        let reinforcement = self.reinforcement(item.access_events.len());
        let outcome_bonus = self.outcome_bonus(&item.access_events);
        let contradiction_penalty = self.contradiction_penalty(&item.access_events);
        let final_score = decayed_base + reinforcement + outcome_bonus - contradiction_penalty;

        SignificanceBreakdown {
            base_score: item.significance,
            decay_multiplier,
            decayed_base,
            reinforcement,
            outcome_bonus,
            contradiction_penalty,
            final_score,
        }
    }

    /// Recomputes the materialized significance score for an item at `now`.
    #[must_use]
    pub fn recompute(self, item: &MemoryItem, now: OffsetDateTime) -> f64 {
        self.explain(item, now).final_score
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
        assert!(config.outcome_weight(AccessOutcome::Contradicted) < 0.0);
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
    fn explain_recomputes_score_from_access_log_lazily() {
        let config = SignificanceConfig::default();
        let now = OffsetDateTime::UNIX_EPOCH;
        let mut item = MemoryItem {
            schema_version: crate::model::CURRENT_MEMORY_SCHEMA_VERSION,
            id: crate::model::MemoryId::new_v7(),
            content: "score me".to_owned(),
            compaction: None,
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
            credence_floor: crate::model::Tier::Cold,
            access_events: Vec::new(),
        };

        item.access_events
            .push(AccessEvent::new(now, None, AccessOutcome::LedSomewhere));

        let breakdown = config.explain(&item, now);

        assert!(breakdown.reinforcement > 0.0);
        assert!(breakdown.outcome_bonus > 0.0);
        assert!((config.recompute(&item, now) - breakdown.final_score).abs() < f64::EPSILON);
    }
}
