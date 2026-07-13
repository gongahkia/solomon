// SPDX-License-Identifier: MIT

//! Anomaly detection for suspicious writes and provenance.

use crate::model::{AccessEvent, AccessOutcome, CredenceTier, MemoryId, MemoryItem, SourceKind};
use crate::storage::{EventRecord, MemoryEvent};
use std::collections::BTreeMap;
use time::{Duration, OffsetDateTime};

/// Anomaly detection thresholds.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AnomalyConfig {
    /// Window for detecting bursts of contradiction events.
    pub contradiction_burst_window: Duration,
    /// Number of contradictions for one memory inside the window that triggers a flag.
    pub contradiction_burst_threshold: usize,
}

impl Default for AnomalyConfig {
    fn default() -> Self {
        Self {
            contradiction_burst_window: Duration::minutes(5),
            contradiction_burst_threshold: 3,
        }
    }
}

/// Suspicious provenance reason.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SuspiciousProvenanceReason {
    /// File, tool, or web provenance had no stable source reference.
    MissingExternalSourceRef {
        /// Source kind with a missing source reference.
        source_kind: SourceKind,
    },
    /// Web provenance source ref did not look like an HTTP(S) URL.
    WebSourceRefNotUrl,
    /// A non-user source claimed firm-authoritative credence.
    FirmAuthoritativeNonUserSource {
        /// Source kind that claimed high credence.
        source_kind: SourceKind,
    },
}

/// Anomaly flag emitted by inspection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AnomalyFlag {
    /// Many contradiction events were recorded for one memory in a short window.
    ContradictionBurst {
        /// Memory with the contradiction burst.
        memory_id: MemoryId,
        /// Number of contradiction events in the window.
        count: usize,
        /// Window size in seconds.
        window_seconds: i64,
    },
    /// Memory provenance looked suspicious.
    SuspiciousProvenance {
        /// Memory with suspicious provenance.
        memory_id: MemoryId,
        /// Reason it was flagged.
        reason: SuspiciousProvenanceReason,
    },
}

/// Detects contradiction bursts in the event log.
#[must_use]
pub fn detect_contradiction_bursts(
    events: &[EventRecord],
    now: OffsetDateTime,
    config: AnomalyConfig,
) -> Vec<AnomalyFlag> {
    let mut counts = BTreeMap::<MemoryId, usize>::new();

    for record in events {
        let MemoryEvent::AccessRecorded { id, event } = &record.event else {
            continue;
        };

        if event.outcome != AccessOutcome::Contradicted
            || !in_window(event, now, config.contradiction_burst_window)
        {
            continue;
        }

        *counts.entry(*id).or_default() += 1;
    }

    counts
        .into_iter()
        .filter_map(|(memory_id, count)| {
            (count >= config.contradiction_burst_threshold).then_some(
                AnomalyFlag::ContradictionBurst {
                    memory_id,
                    count,
                    window_seconds: config.contradiction_burst_window.whole_seconds(),
                },
            )
        })
        .collect()
}

/// Inspects item provenance for suspicious attribution.
#[must_use]
pub fn inspect_suspicious_provenance(item: &MemoryItem) -> Vec<AnomalyFlag> {
    let mut flags = Vec::new();

    if matches!(
        item.provenance.source_kind,
        SourceKind::File | SourceKind::Tool | SourceKind::Web
    ) && item
        .provenance
        .source_ref
        .as_deref()
        .is_none_or(str::is_empty)
    {
        flags.push(AnomalyFlag::SuspiciousProvenance {
            memory_id: item.id,
            reason: SuspiciousProvenanceReason::MissingExternalSourceRef {
                source_kind: item.provenance.source_kind,
            },
        });
    }

    if item.provenance.source_kind == SourceKind::Web
        && item
            .provenance
            .source_ref
            .as_deref()
            .is_some_and(|source_ref| {
                !source_ref.starts_with("https://") && !source_ref.starts_with("http://")
            })
    {
        flags.push(AnomalyFlag::SuspiciousProvenance {
            memory_id: item.id,
            reason: SuspiciousProvenanceReason::WebSourceRefNotUrl,
        });
    }

    if item.credence == CredenceTier::FirmAuthoritative
        && item.provenance.source_kind != SourceKind::User
    {
        flags.push(AnomalyFlag::SuspiciousProvenance {
            memory_id: item.id,
            reason: SuspiciousProvenanceReason::FirmAuthoritativeNonUserSource {
                source_kind: item.provenance.source_kind,
            },
        });
    }

    flags
}

fn in_window(event: &AccessEvent, now: OffsetDateTime, window: Duration) -> bool {
    window > Duration::ZERO && event.timestamp <= now && event.timestamp >= now - window
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{
        CURRENT_MEMORY_SCHEMA_VERSION, MemoryKind, Provenance, TemporalBounds, Tier,
    };

    fn event(sequence: u64, id: MemoryId, timestamp: OffsetDateTime) -> EventRecord {
        EventRecord {
            sequence,
            recorded_at: timestamp,
            event: MemoryEvent::AccessRecorded {
                id,
                event: AccessEvent::new(timestamp, None, AccessOutcome::Contradicted),
            },
        }
    }

    fn item(
        source_kind: SourceKind,
        source_ref: Option<String>,
        credence: CredenceTier,
    ) -> MemoryItem {
        MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            scope: crate::model::MemoryScope::default(),
            id: MemoryId::new_v7(),
            content: "memory".to_owned(),
            kind: MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            promotion: None,
            embedding_ref: None,
            provenance: Provenance::new(source_kind, source_ref, "anomaly-test"),
            timestamps: TemporalBounds::open_from(
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ),
            tier: Tier::Warm,
            credence,
            significance: 1.0,
            base_significance: 1.0,
            credence_floor: Tier::Cold,
            access_events: Vec::new(),
        }
    }

    #[test]
    fn detects_contradiction_bursts_in_window() {
        let id = MemoryId::new_v7();
        let other = MemoryId::new_v7();
        let now = OffsetDateTime::UNIX_EPOCH + Duration::minutes(10);
        let flags = detect_contradiction_bursts(
            &[
                event(0, id, now - Duration::seconds(10)),
                event(1, id, now - Duration::seconds(20)),
                event(2, id, now - Duration::seconds(30)),
                event(3, other, now - Duration::seconds(10)),
                event(4, id, now - Duration::minutes(10)),
            ],
            now,
            AnomalyConfig {
                contradiction_burst_window: Duration::minutes(1),
                contradiction_burst_threshold: 3,
            },
        );

        assert_eq!(
            flags,
            vec![AnomalyFlag::ContradictionBurst {
                memory_id: id,
                count: 3,
                window_seconds: 60,
            }]
        );
    }

    #[test]
    fn flags_suspicious_provenance() {
        let missing_ref = item(SourceKind::Web, None, CredenceTier::Unverified);
        let authoritative_agent = item(SourceKind::Agent, None, CredenceTier::FirmAuthoritative);

        assert_eq!(
            inspect_suspicious_provenance(&missing_ref),
            vec![AnomalyFlag::SuspiciousProvenance {
                memory_id: missing_ref.id,
                reason: SuspiciousProvenanceReason::MissingExternalSourceRef {
                    source_kind: SourceKind::Web,
                },
            }]
        );
        assert_eq!(
            inspect_suspicious_provenance(&authoritative_agent),
            vec![AnomalyFlag::SuspiciousProvenance {
                memory_id: authoritative_agent.id,
                reason: SuspiciousProvenanceReason::FirmAuthoritativeNonUserSource {
                    source_kind: SourceKind::Agent,
                },
            }]
        );
    }
}
