// SPDX-License-Identifier: MIT

//! Significance scoring primitives.

use time::OffsetDateTime;

/// Configuration for the transparent significance function.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SignificanceConfig {
    /// Half-life in seconds for decay since last use.
    pub half_life_seconds: f64,
}

impl Default for SignificanceConfig {
    fn default() -> Self {
        Self {
            half_life_seconds: 30.0 * 24.0 * 60.0 * 60.0,
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
}

#[cfg(test)]
mod tests {
    use super::*;
    use time::Duration;

    #[test]
    fn time_decay_halves_after_one_half_life() {
        let config = SignificanceConfig {
            half_life_seconds: 10.0,
        };
        let start = OffsetDateTime::UNIX_EPOCH;
        let decayed = config.time_decay(start, start + Duration::seconds(10));

        assert!((decayed - 0.5).abs() < f64::EPSILON);
    }

    #[test]
    fn time_decay_does_not_increase_for_future_last_use() {
        let config = SignificanceConfig {
            half_life_seconds: 10.0,
        };
        let now = OffsetDateTime::UNIX_EPOCH;

        assert!((config.time_decay(now + Duration::seconds(1), now) - 1.0).abs() < f64::EPSILON);
    }
}
