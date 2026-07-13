// SPDX-License-Identifier: MIT

//! Offline consolidation planning and summarisation drift controls.

use crate::model::{
    AccessOutcome, CURRENT_MEMORY_SCHEMA_VERSION, ConsolidationAction, ConsolidationRef,
    ConsolidationUsageEvidence, ConsolidationWhy, CredenceTier, MemoryId, MemoryItem, MemoryKind,
    Provenance, SourceKind, TemporalBounds, Tier,
};
use crate::storage::{EventRecord, MemoryEvent};
use std::collections::BTreeSet;
use time::{Duration, OffsetDateTime};

/// Reverification reason used when consolidation flags stale significant memories.
pub const CONSOLIDATION_STALE_REASON: &str = "consolidation:stale-significant";

/// Policy limiting semantic drift from repeated summarisation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ConsolidationPolicy {
    /// Maximum allowed summarisation/consolidation generations from raw observations.
    pub max_resummarization_depth: u16,
}

impl Default for ConsolidationPolicy {
    fn default() -> Self {
        Self {
            max_resummarization_depth: 2,
        }
    }
}

/// Reason a consolidation request was denied.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ConsolidationDenial {
    /// Consolidation cannot run without source memories.
    NoSources,
    /// The next consolidation would exceed the configured depth cap.
    ResummarizationDepthExceeded {
        /// Maximum allowed depth.
        max_depth: u16,
        /// Depth requested by the proposed consolidation.
        requested_depth: u16,
    },
}

/// Decision returned before an auto-consolidated memory is written.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ConsolidationDecision {
    /// Consolidation is allowed with the attached lineage metadata.
    Allowed(ConsolidationRef),
    /// Consolidation was denied before a summary could be produced.
    Denied(ConsolidationDenial),
}

/// Plans consolidation lineage and enforces the resummarisation-depth cap.
#[must_use]
pub fn plan_consolidation(
    sources: &[MemoryItem],
    policy: ConsolidationPolicy,
) -> ConsolidationDecision {
    if sources.is_empty() {
        return ConsolidationDecision::Denied(ConsolidationDenial::NoSources);
    }

    let max_source_depth = sources
        .iter()
        .filter_map(|item| {
            item.consolidation
                .as_ref()
                .map(|consolidation| consolidation.resummarization_depth)
        })
        .max()
        .unwrap_or(0);
    let requested_depth = max_source_depth.saturating_add(1);

    if requested_depth > policy.max_resummarization_depth {
        return ConsolidationDecision::Denied(ConsolidationDenial::ResummarizationDepthExceeded {
            max_depth: policy.max_resummarization_depth,
            requested_depth,
        });
    }

    ConsolidationDecision::Allowed(ConsolidationRef {
        source_memory_ids: sources.iter().map(|item| item.id).collect(),
        resummarization_depth: requested_depth,
    })
}

/// Configuration for the offline/idle consolidation pass.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct OfflineConsolidationConfig {
    /// Minimum source count for a merge decision.
    pub min_merge_sources: usize,
    /// Minimum useful access events across merge sources.
    pub min_actual_use_events_for_merge: usize,
    /// Minimum source significance for a merge group to be considered.
    pub merge_significance_threshold: f64,
    /// Token-overlap threshold used to group fragmented memories.
    pub merge_similarity_threshold: f64,
    /// Score at or above which warm/cold memories may be promoted to hot.
    pub promote_to_hot_score: f64,
    /// Score below which memories may be demoted toward cold, clamped by floor.
    pub demote_to_cold_score: f64,
    /// Score at or above which old memories are considered load-bearing enough to flag.
    pub stale_significance_threshold: f64,
    /// Age since last use after which a significant memory is stale enough to flag.
    pub stale_after: Duration,
    /// Memories at or above this floor are excluded from merge synthesis.
    pub protected_floor: Tier,
}

impl Default for OfflineConsolidationConfig {
    fn default() -> Self {
        Self {
            min_merge_sources: 2,
            min_actual_use_events_for_merge: 2,
            merge_significance_threshold: 1.0,
            merge_similarity_threshold: 0.72,
            promote_to_hot_score: 2.0,
            demote_to_cold_score: 0.5,
            stale_significance_threshold: 2.0,
            stale_after: Duration::days(30),
            protected_floor: Tier::Warm,
        }
    }
}

/// One planned durable change from an offline consolidation pass.
#[derive(Clone, Debug, PartialEq)]
pub struct PlannedConsolidationDecision {
    /// Stable id for this pass, included in emitted decision events.
    pub pass_id: String,
    /// Decision action.
    pub action: ConsolidationAction,
    /// Source memories considered by the decision.
    pub input_ids: Vec<MemoryId>,
    /// New synthesized item for merge decisions.
    pub output: Option<MemoryItem>,
    /// Previous tier for tier-transition decisions.
    pub tier_from: Option<Tier>,
    /// New tier for tier-transition decisions.
    pub tier_to: Option<Tier>,
    /// Timestamp used for stale flags.
    pub flag_at: Option<OffsetDateTime>,
    /// Reverification reason used for stale flags.
    pub flag_reason: Option<String>,
    /// Explainable usage and safety evidence.
    pub why: ConsolidationWhy,
}

/// Deterministic plan for one offline consolidation pass.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct OfflineConsolidationPlan {
    /// Stable id for this pass.
    pub pass_id: String,
    /// Decisions to apply in order.
    pub decisions: Vec<PlannedConsolidationDecision>,
}

/// Builds an offline consolidation plan from current items and append-only history.
#[must_use]
pub fn plan_offline_consolidation(
    items: &[MemoryItem],
    events: &[EventRecord],
    now: OffsetDateTime,
    config: OfflineConsolidationConfig,
    depth_policy: ConsolidationPolicy,
) -> OfflineConsolidationPlan {
    let pass_id = consolidation_pass_id(items, events, now);
    let existing_merge_keys = existing_consolidation_source_keys(items);
    let existing_stale_flags = existing_consolidation_stale_flags(events);
    let mut decisions = Vec::new();

    decisions.extend(plan_merge_decisions(
        items,
        &pass_id,
        &existing_merge_keys,
        now,
        config,
        depth_policy,
    ));
    decisions.extend(plan_tier_decisions(items, &pass_id, now, config));
    decisions.extend(plan_stale_flag_decisions(
        items,
        &pass_id,
        &existing_stale_flags,
        now,
        config,
    ));

    OfflineConsolidationPlan { pass_id, decisions }
}

fn plan_merge_decisions(
    items: &[MemoryItem],
    pass_id: &str,
    existing_merge_keys: &BTreeSet<String>,
    now: OffsetDateTime,
    config: OfflineConsolidationConfig,
    depth_policy: ConsolidationPolicy,
) -> Vec<PlannedConsolidationDecision> {
    let candidates = items
        .iter()
        .filter(|item| merge_candidate(item, now, config))
        .collect::<Vec<_>>();
    let mut groups = Vec::<Vec<&MemoryItem>>::new();

    for candidate in candidates {
        if let Some(group) = groups.iter_mut().find(|group| {
            group.iter().any(|member| {
                token_similarity(&member.content, &candidate.content)
                    >= config.merge_similarity_threshold
            })
        }) {
            group.push(candidate);
        } else {
            groups.push(vec![candidate]);
        }
    }

    groups
        .into_iter()
        .filter_map(|mut group| {
            group.sort_by_key(|item| item.id);

            if group.len() < config.min_merge_sources {
                return None;
            }

            let actual_uses = group.iter().map(|item| actual_use_count(item)).sum::<usize>();
            let max_significance = group
                .iter()
                .map(|item| item.significance)
                .fold(f64::NEG_INFINITY, f64::max);

            if actual_uses < config.min_actual_use_events_for_merge
                || max_significance < config.merge_significance_threshold
            {
                return None;
            }

            let sources = group.iter().map(|item| (*item).clone()).collect::<Vec<_>>();
            let source_ids = sources.iter().map(|item| item.id).collect::<Vec<_>>();
            let source_key = source_key(&source_ids);

            if existing_merge_keys.contains(&source_key) {
                return None;
            }

            let ConsolidationDecision::Allowed(lineage) =
                plan_consolidation(&sources, depth_policy)
            else {
                return None;
            };
            let evidence = sources.iter().map(usage_evidence).collect::<Vec<_>>();
            let output = synthesized_memory(&sources, lineage, now, max_significance);

            Some(PlannedConsolidationDecision {
                pass_id: pass_id.to_owned(),
                action: ConsolidationAction::Merge,
                input_ids: source_ids,
                output: Some(output),
                tier_from: None,
                tier_to: None,
                flag_at: None,
                flag_reason: None,
                why: ConsolidationWhy {
                    summary: format!(
                        "Merged {} used duplicate/fragmented memories into a new synthesized memory; originals remain queryable.",
                        sources.len()
                    ),
                    evidence,
                },
            })
        })
        .collect()
}

fn plan_tier_decisions(
    items: &[MemoryItem],
    pass_id: &str,
    now: OffsetDateTime,
    config: OfflineConsolidationConfig,
) -> Vec<PlannedConsolidationDecision> {
    items
        .iter()
        .filter(|item| item.timestamps.is_valid_at(now))
        .filter_map(|item| {
            let proposed = if item.significance >= config.promote_to_hot_score {
                Tier::Hot
            } else if item.significance < config.demote_to_cold_score {
                item.clamp_tier_to_floor(Tier::Cold)
            } else {
                item.tier
            };

            if proposed == item.tier {
                return None;
            }

            let action = if proposed > item.tier {
                ConsolidationAction::Promote
            } else {
                ConsolidationAction::Demote
            };

            Some(PlannedConsolidationDecision {
                pass_id: pass_id.to_owned(),
                action,
                input_ids: vec![item.id],
                output: None,
                tier_from: Some(item.tier),
                tier_to: Some(proposed),
                flag_at: None,
                flag_reason: None,
                why: ConsolidationWhy {
                    summary: format!(
                        "Moved tier from {:?} to {:?} from offline significance score {:.3}; credence floor {:?} was enforced.",
                        item.tier, proposed, item.significance, item.credence_floor
                    ),
                    evidence: vec![usage_evidence(item)],
                },
            })
        })
        .collect()
}

fn plan_stale_flag_decisions(
    items: &[MemoryItem],
    pass_id: &str,
    existing_stale_flags: &BTreeSet<MemoryId>,
    now: OffsetDateTime,
    config: OfflineConsolidationConfig,
) -> Vec<PlannedConsolidationDecision> {
    items
        .iter()
        .filter(|item| item.timestamps.is_valid_at(now))
        .filter(|item| item.significance >= config.stale_significance_threshold)
        .filter(|item| !existing_stale_flags.contains(&item.id))
        .filter(|item| last_usage_at(item).is_none_or(|last_use| now - last_use >= config.stale_after))
        .map(|item| PlannedConsolidationDecision {
            pass_id: pass_id.to_owned(),
            action: ConsolidationAction::FlagStale,
            input_ids: vec![item.id],
            output: None,
            tier_from: None,
            tier_to: None,
            flag_at: Some(now),
            flag_reason: Some(CONSOLIDATION_STALE_REASON.to_owned()),
            why: ConsolidationWhy {
                summary: format!(
                    "Flagged stale significant memory for explicit reconstruction after no use for at least {} seconds.",
                    config.stale_after.whole_seconds()
                ),
                evidence: vec![usage_evidence(item)],
            },
        })
        .collect()
}

fn merge_candidate(
    item: &MemoryItem,
    now: OffsetDateTime,
    config: OfflineConsolidationConfig,
) -> bool {
    item.timestamps.is_valid_at(now)
        && item.kind == MemoryKind::Fact
        && item.consolidation.is_none()
        && item.credence_floor < config.protected_floor
        && !item.content.trim().is_empty()
        && (item.significance >= config.merge_significance_threshold || actual_use_count(item) > 0)
}

fn synthesized_memory(
    sources: &[MemoryItem],
    lineage: ConsolidationRef,
    now: OffsetDateTime,
    max_significance: f64,
) -> MemoryItem {
    let source_ids = sources.iter().map(|item| item.id).collect::<Vec<_>>();
    let content = if sources
        .windows(2)
        .all(|pair| normalized_content(&pair[0].content) == normalized_content(&pair[1].content))
    {
        sources
            .first()
            .map(|item| item.content.clone())
            .unwrap_or_default()
    } else {
        let bullets = sources
            .iter()
            .map(|item| format!("- {}", item.content.trim()))
            .collect::<Vec<_>>()
            .join("\n");

        format!("Consolidated view:\n{bullets}")
    };

    MemoryItem {
        schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
        scope: crate::model::MemoryScope::default(),
        id: MemoryId::new_v7(),
        content,
        kind: MemoryKind::Fact,
        compaction: None,
        consolidation: Some(lineage),
        promotion: None,
        embedding_ref: None,
        provenance: Provenance::new(
            SourceKind::Agent,
            Some(consolidation_source_ref(sources, &source_ids)),
            "shibahama-consolidation",
        ),
        timestamps: TemporalBounds::open_from(now, now),
        tier: Tier::Warm,
        credence: CredenceTier::ModelInferred,
        significance: max_significance,
        base_significance: max_significance,
        credence_floor: Tier::Cold,
        access_events: Vec::new(),
    }
}

fn consolidation_source_ref(sources: &[MemoryItem], source_ids: &[MemoryId]) -> String {
    let consolidation_ref = format!("shibahama://consolidation/{}", source_key(source_ids));

    common_server_namespace_prefix(sources)
        .map(|prefix| format!("{prefix}{consolidation_ref}"))
        .unwrap_or(consolidation_ref)
}

fn common_server_namespace_prefix(sources: &[MemoryItem]) -> Option<&str> {
    let mut prefixes = sources
        .iter()
        .filter_map(|item| item.provenance.source_ref.as_deref())
        .filter_map(|source_ref| {
            source_ref
                .strip_prefix("shibahama-server:namespace=")
                .and_then(|rest| {
                    rest.find(';').map(|index| {
                        let semicolon_index = source_ref.len() - rest.len() + index;

                        &source_ref[..=semicolon_index]
                    })
                })
        });
    let first = prefixes.next()?;

    if prefixes.all(|prefix| prefix == first) {
        Some(first)
    } else {
        None
    }
}

fn existing_consolidation_source_keys(items: &[MemoryItem]) -> BTreeSet<String> {
    items
        .iter()
        .filter_map(|item| item.consolidation.as_ref())
        .map(|lineage| source_key(&lineage.source_memory_ids))
        .collect()
}

fn existing_consolidation_stale_flags(events: &[EventRecord]) -> BTreeSet<MemoryId> {
    events
        .iter()
        .filter_map(|record| match &record.event {
            MemoryEvent::ReverificationFlagged { id, reason, .. }
                if reason == CONSOLIDATION_STALE_REASON =>
            {
                Some(*id)
            }
            MemoryEvent::ConsolidationDecision {
                action: ConsolidationAction::FlagStale,
                input_ids,
                ..
            } => input_ids.first().copied(),
            _ => None,
        })
        .collect()
}

fn source_key(ids: &[MemoryId]) -> String {
    let mut ids = ids.iter().map(ToString::to_string).collect::<Vec<_>>();

    ids.sort();
    ids.join("+")
}

fn consolidation_pass_id(
    items: &[MemoryItem],
    events: &[EventRecord],
    now: OffsetDateTime,
) -> String {
    let mut hasher = blake3::Hasher::new();

    hasher.update(&now.unix_timestamp().to_le_bytes());
    hasher.update(
        &u64::try_from(events.len())
            .unwrap_or(u64::MAX)
            .to_le_bytes(),
    );

    for item in items {
        hasher.update(item.id.to_string().as_bytes());
        hasher.update(tier_bytes(item.tier));
        hasher.update(&item.significance.to_le_bytes());
        hasher.update(
            &u64::try_from(item.access_events.len())
                .unwrap_or(u64::MAX)
                .to_le_bytes(),
        );
    }

    let hex = hasher.finalize().to_hex().to_string();
    format!("consolidation:{}", hex.chars().take(16).collect::<String>())
}

fn tier_bytes(tier: Tier) -> &'static [u8] {
    match tier {
        Tier::Cold => b"cold",
        Tier::Warm => b"warm",
        Tier::Hot => b"hot",
    }
}

fn usage_evidence(item: &MemoryItem) -> ConsolidationUsageEvidence {
    ConsolidationUsageEvidence {
        memory_id: item.id,
        significance: item.significance,
        access_count: item.access_events.len(),
        actual_use_count: actual_use_count(item),
        contradiction_count: item
            .access_events
            .iter()
            .filter(|event| event.outcome == AccessOutcome::Contradicted)
            .count(),
        tier: item.tier,
        credence: item.credence,
        credence_floor: item.credence_floor,
    }
}

fn actual_use_count(item: &MemoryItem) -> usize {
    item.access_events
        .iter()
        .filter(|event| event.outcome.is_actual_use())
        .count()
}

fn last_usage_at(item: &MemoryItem) -> Option<OffsetDateTime> {
    item.access_events
        .iter()
        .map(|event| event.timestamp)
        .max()
        .or(Some(item.timestamps.ingested_at))
}

fn token_similarity(left: &str, right: &str) -> f64 {
    let left_tokens = tokens(left);
    let right_tokens = tokens(right);

    if left_tokens.is_empty() || right_tokens.is_empty() {
        return 0.0;
    }

    let intersection =
        u32::try_from(left_tokens.intersection(&right_tokens).count()).unwrap_or(u32::MAX);
    let union = u32::try_from(left_tokens.union(&right_tokens).count()).unwrap_or(u32::MAX);

    if union == 0 {
        0.0
    } else {
        f64::from(intersection) / f64::from(union)
    }
}

fn tokens(value: &str) -> BTreeSet<String> {
    normalized_content(value)
        .split_whitespace()
        .filter(|token| token.len() > 2)
        .map(str::to_owned)
        .collect()
}

fn normalized_content(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character.to_ascii_lowercase()
            } else {
                ' '
            }
        })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{AccessEvent, CURRENT_MEMORY_SCHEMA_VERSION, MemoryKind};

    fn memory(content: &str, consolidation: Option<ConsolidationRef>) -> MemoryItem {
        MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            scope: crate::model::MemoryScope::default(),
            id: MemoryId::new_v7(),
            content: content.to_owned(),
            kind: MemoryKind::Fact,
            compaction: None,
            consolidation,
            promotion: None,
            embedding_ref: None,
            provenance: Provenance::new(SourceKind::User, None, "consolidation-test"),
            timestamps: TemporalBounds::open_from(
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ),
            tier: Tier::Warm,
            credence: CredenceTier::FirmAuthoritative,
            significance: 1.0,
            base_significance: 1.0,
            credence_floor: Tier::Warm,
            access_events: Vec::new(),
        }
    }

    #[test]
    fn raw_sources_consolidate_to_depth_one() {
        let first = memory("first", None);
        let second = memory("second", None);
        let decision = plan_consolidation(
            &[first.clone(), second.clone()],
            ConsolidationPolicy::default(),
        );

        assert_eq!(
            decision,
            ConsolidationDecision::Allowed(ConsolidationRef {
                source_memory_ids: vec![first.id, second.id],
                resummarization_depth: 1,
            })
        );
    }

    #[test]
    fn resummarization_depth_is_capped() {
        let raw = memory("raw", None);
        let first_summary = memory(
            "summary",
            Some(ConsolidationRef {
                source_memory_ids: vec![raw.id],
                resummarization_depth: 2,
            }),
        );
        let decision = plan_consolidation(
            &[first_summary],
            ConsolidationPolicy {
                max_resummarization_depth: 2,
            },
        );

        assert_eq!(
            decision,
            ConsolidationDecision::Denied(ConsolidationDenial::ResummarizationDepthExceeded {
                max_depth: 2,
                requested_depth: 3,
            })
        );
    }

    #[test]
    fn consolidation_requires_sources() {
        let decision = plan_consolidation(&[], ConsolidationPolicy::default());

        assert_eq!(
            decision,
            ConsolidationDecision::Denied(ConsolidationDenial::NoSources)
        );
    }

    #[test]
    fn offline_plan_merges_used_duplicate_memories_once() {
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(1);
        let mut first = memory("API endpoint is /v1", None);
        let mut second = memory("api endpoint is /v1", None);

        first.credence_floor = Tier::Cold;
        second.credence_floor = Tier::Cold;
        first.significance = 2.1;
        second.significance = 1.7;
        first
            .access_events
            .push(AccessEvent::new(now, None, AccessOutcome::Cited));
        second
            .access_events
            .push(AccessEvent::new(now, None, AccessOutcome::LedSomewhere));

        let plan = plan_offline_consolidation(
            &[first.clone(), second.clone()],
            &[],
            now,
            OfflineConsolidationConfig::default(),
            ConsolidationPolicy::default(),
        );

        assert_eq!(plan.decisions.len(), 2);
        let merge = plan
            .decisions
            .iter()
            .find(|decision| decision.action == ConsolidationAction::Merge)
            .expect("merge decision should exist");
        let output = merge.output.as_ref().expect("merge should synthesize item");

        assert_eq!(merge.input_ids, vec![first.id, second.id]);
        assert_eq!(output.content, first.content);
        assert_eq!(
            output
                .consolidation
                .as_ref()
                .expect("lineage should exist")
                .source_memory_ids,
            vec![first.id, second.id]
        );

        let existing = [first, second, output.clone()];
        let rerun = plan_offline_consolidation(
            &existing,
            &[],
            now,
            OfflineConsolidationConfig::default(),
            ConsolidationPolicy::default(),
        );

        assert!(
            !rerun
                .decisions
                .iter()
                .any(|decision| decision.action == ConsolidationAction::Merge)
        );
    }

    #[test]
    fn offline_plan_respects_floor_protection() {
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(1);
        let mut protected = memory("pinned project rule", None);
        let mut duplicate = memory("pinned project rule", None);

        protected.credence_floor = Tier::Warm;
        duplicate.credence_floor = Tier::Cold;
        protected.tier = Tier::Hot;
        protected.significance = 0.1;
        duplicate.significance = 2.0;
        protected
            .access_events
            .push(AccessEvent::new(now, None, AccessOutcome::Cited));
        duplicate
            .access_events
            .push(AccessEvent::new(now, None, AccessOutcome::Cited));

        let plan = plan_offline_consolidation(
            &[protected.clone(), duplicate],
            &[],
            now,
            OfflineConsolidationConfig::default(),
            ConsolidationPolicy::default(),
        );

        assert!(
            !plan
                .decisions
                .iter()
                .any(|decision| decision.action == ConsolidationAction::Merge
                    && decision.input_ids.contains(&protected.id))
        );
        let demotion = plan
            .decisions
            .iter()
            .find(|decision| decision.input_ids == vec![protected.id])
            .expect("protected item may be demoted to its floor");

        assert_eq!(demotion.action, ConsolidationAction::Demote);
        assert_eq!(demotion.tier_to, Some(Tier::Warm));
    }

    #[test]
    fn offline_plan_flags_stale_significant_memories_idempotently() {
        let ingested_at = OffsetDateTime::UNIX_EPOCH;
        let now = ingested_at + Duration::days(90);
        let mut stale = memory("old but load-bearing", None);

        stale.timestamps = TemporalBounds::open_from(ingested_at, ingested_at);
        stale.significance = 3.2;

        let first = plan_offline_consolidation(
            &[stale.clone()],
            &[],
            now,
            OfflineConsolidationConfig::default(),
            ConsolidationPolicy::default(),
        );
        let flag = first
            .decisions
            .iter()
            .find(|decision| decision.action == ConsolidationAction::FlagStale)
            .expect("stale significant item should be flagged");
        let event = EventRecord {
            sequence: 0,
            recorded_at: now,
            event: MemoryEvent::ConsolidationDecision {
                pass_id: flag.pass_id.clone(),
                action: flag.action,
                input_ids: flag.input_ids.clone(),
                output_id: None,
                tier_from: None,
                tier_to: None,
                why: flag.why.clone(),
            },
        };
        let second = plan_offline_consolidation(
            &[stale],
            &[event],
            now,
            OfflineConsolidationConfig::default(),
            ConsolidationPolicy::default(),
        );

        assert!(
            !second
                .decisions
                .iter()
                .any(|decision| decision.action == ConsolidationAction::FlagStale)
        );
    }
}
