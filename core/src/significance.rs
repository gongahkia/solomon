// SPDX-License-Identifier: MIT

//! Significance scoring primitives.

use time::OffsetDateTime;

/// Configuration for the transparent significance function.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SignificanceConfig {
    /// Half-life in seconds for decay since last use.
    pub half_life_seconds: f64,
    /// Weight applied to the diminishing-returns access reinforcement term.
    pub reinforcement_weight: f64,
}

impl Default for SignificanceConfig {
    fn default() -> Self {
        Self {
            half_life_seconds: 30.0 * 24.0 * 60.0 * 60.0,
            reinforcement_weight: 1.0,
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
}
