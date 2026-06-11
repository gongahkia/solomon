// SPDX-License-Identifier: MIT

//! Retrieval orchestration for recall.

use crate::model::{AccessEvent, AccessOutcome, MemoryId, MemoryItem, Provenance, Tier};
use crate::storage::{RedbMemoryStore, StorageError};
use crate::vector::{VectorIndex, VectorIndexError};
use std::collections::BTreeSet;
use thiserror::Error;
use time::OffsetDateTime;

/// Error returned by recall orchestration.
#[derive(Debug, Error)]
pub enum RecallError {
    /// Storage operation failed.
    #[error(transparent)]
    Storage(#[from] StorageError),
    /// Vector index operation failed.
    #[error(transparent)]
    Vector(#[from] VectorIndexError),
}

/// Recall request over a pre-computed query embedding.
#[derive(Clone, Copy)]
pub struct RecallRequest<'a> {
    /// Query embedding supplied by the caller's embedding model.
    pub query_vector: &'a [f32],
    /// Optional raw query/context text to hash into surfaced access events.
    pub raw_query_context: Option<&'a str>,
    /// Maximum number of vector candidates to inspect.
    pub top_k: usize,
    /// Valid-time instant used for default current-fact filtering.
    pub now: OffsetDateTime,
    /// Whether recall may return cold-tier memories.
    pub include_cold: bool,
    /// Ranking weights applied to retrieved candidates.
    pub ranking: RecallRankingConfig,
    /// Policy for flagging load-bearing but possibly stale memories.
    pub staleness: RecallStalenessConfig,
    /// Optional related-memory provider used for graph expansion.
    pub related_memory_provider: Option<&'a dyn RelatedMemoryProvider>,
}

impl<'a> RecallRequest<'a> {
    /// Creates a recall request for a query vector.
    #[must_use]
    pub fn new(query_vector: &'a [f32], top_k: usize, now: OffsetDateTime) -> Self {
        Self {
            query_vector,
            raw_query_context: None,
            top_k,
            now,
            include_cold: false,
            ranking: RecallRankingConfig::default(),
            staleness: RecallStalenessConfig::default(),
            related_memory_provider: None,
        }
    }

    /// Adds raw query context that will be hashed before storage.
    #[must_use]
    pub const fn with_raw_query_context(mut self, raw_query_context: &'a str) -> Self {
        self.raw_query_context = Some(raw_query_context);
        self
    }

    /// Allows cold-tier memories to be returned.
    #[must_use]
    pub const fn include_cold(mut self) -> Self {
        self.include_cold = true;
        self
    }

    /// Overrides ranking weights for this request.
    #[must_use]
    pub const fn with_ranking(mut self, ranking: RecallRankingConfig) -> Self {
        self.ranking = ranking;
        self
    }

    /// Overrides stale-load-bearing detection policy for this request.
    #[must_use]
    pub const fn with_staleness(mut self, staleness: RecallStalenessConfig) -> Self {
        self.staleness = staleness;
        self
    }

    /// Adds a related-memory provider for graph expansion.
    #[must_use]
    pub const fn with_related_memory_provider(
        mut self,
        related_memory_provider: &'a dyn RelatedMemoryProvider,
    ) -> Self {
        self.related_memory_provider = Some(related_memory_provider);
        self
    }
}

/// Provides graph-related memory ids for recall expansion.
pub trait RelatedMemoryProvider {
    /// Returns memory ids related to `id`.
    ///
    /// # Errors
    ///
    /// Returns an error when related ids cannot be loaded.
    fn related_memory_ids(&self, id: MemoryId) -> Result<Vec<MemoryId>, StorageError>;
}

/// Active ranking weights for vector recall.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RecallRankingConfig {
    /// Weight applied to normalized vector similarity.
    pub similarity_weight: f64,
    /// Weight applied to materialized significance.
    pub significance_weight: f64,
    /// Weight applied to recency of the last access or ingestion.
    pub recency_weight: f64,
    /// Weight applied when a candidate comes from graph expansion.
    pub graph_weight: f64,
}

impl Default for RecallRankingConfig {
    fn default() -> Self {
        Self {
            similarity_weight: 1.0,
            significance_weight: 1.0,
            recency_weight: 0.0,
            graph_weight: 0.0,
        }
    }
}

/// Policy for identifying important memories that may need re-validation.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RecallStalenessConfig {
    /// Minimum significance for a memory to be considered load-bearing.
    pub load_bearing_significance_threshold: f64,
    /// Age in seconds after which the last validation-like signal is considered stale.
    pub stale_after_seconds: f64,
}

impl Default for RecallStalenessConfig {
    fn default() -> Self {
        Self {
            load_bearing_significance_threshold: 2.0,
            stale_after_seconds: 30.0 * 24.0 * 60.0 * 60.0,
        }
    }
}

/// Ranked memory returned from recall.
#[derive(Clone, Debug, PartialEq)]
pub struct RecallCandidate {
    /// Memory id.
    pub id: MemoryId,
    /// Full materialized memory item, including provenance, tier, and validity metadata.
    pub item: MemoryItem,
    /// Provenance copied to the candidate boundary so recall never returns bare text.
    pub provenance: Provenance,
    /// Accessibility tier copied to the candidate boundary.
    pub tier: Tier,
    /// Validity state at the recall instant.
    pub currency: RecallCandidateCurrency,
    /// True when this is significant, old, and lacks a recent validation-like access signal.
    pub load_bearing_possibly_stale: bool,
    /// True when this result was returned from cold-tier storage by explicit opt-in.
    pub cold_tier_retrieval: bool,
    /// Vector distance from the query, where lower is closer.
    pub vector_distance: f32,
    /// Normalized similarity contribution derived from vector distance.
    pub similarity_score: f64,
    /// Materialized significance contribution used by ranking.
    pub significance_score: f64,
    /// Recency contribution derived from last access or ingestion.
    pub recency_score: f64,
    /// Graph-expansion contribution.
    pub graph_score: f64,
    /// How this candidate entered the recall result set.
    pub source: RecallCandidateSource,
    /// Current rank score, where higher is better.
    pub rank_score: f64,
}

/// Source stage that contributed a recall candidate.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecallCandidateSource {
    /// Candidate came directly from vector similarity search.
    Vector,
    /// Candidate was pulled in because it is related to a vector or graph-expanded anchor.
    GraphExpansion {
        /// Anchor memory that supplied this related candidate.
        anchor: MemoryId,
    },
}

/// Validity state attached to a recalled candidate.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecallCandidateCurrency {
    /// Candidate is valid at the recall instant.
    Current,
    /// Candidate is not valid yet at the recall instant.
    NotYetValid,
    /// Candidate has been invalidated before or at the recall instant.
    Invalidated,
}

/// Recalls ranked candidates by vector similarity and records surfaced access.
///
/// The default recall path only returns memories whose valid-time interval contains
/// `request.now`. Every returned candidate receives a `Surfaced` access event with a hashed query
/// context when one is supplied.
///
/// # Errors
///
/// Returns an error when vector search fails, storage cannot be read, or surfaced access cannot be
/// recorded.
pub fn recall(
    store: &RedbMemoryStore,
    vector_index: &dyn VectorIndex,
    request: &RecallRequest<'_>,
) -> Result<Vec<RecallCandidate>, RecallError> {
    recall_inner(store, vector_index, request, true)
}

/// Reconstructs query results as they were believed at `request.now`.
///
/// Unlike `recall`, this is a read-only timeline query: it does not record surfaced access events.
/// Both valid-time and ingestion-time must be in scope, so an observation valid on a date but
/// ingested later is not returned for that earlier `as_of` instant.
///
/// # Errors
///
/// Returns an error when vector search or storage reads fail.
pub fn timeline(
    store: &RedbMemoryStore,
    vector_index: &dyn VectorIndex,
    request: &RecallRequest<'_>,
) -> Result<Vec<RecallCandidate>, RecallError> {
    recall_inner(store, vector_index, request, false)
}

fn recall_inner(
    store: &RedbMemoryStore,
    vector_index: &dyn VectorIndex,
    request: &RecallRequest<'_>,
    record_surface_access: bool,
) -> Result<Vec<RecallCandidate>, RecallError> {
    let vector_results = vector_index.search(request.query_vector, request.top_k)?;
    let ids = vector_results
        .iter()
        .map(|result| result.id)
        .collect::<Vec<_>>();
    let items = store.get_many(&ids)?;
    let mut seen_ids = BTreeSet::new();
    let mut candidates = vector_results
        .into_iter()
        .zip(items)
        .filter_map(|(result, item)| {
            let item = item?;

            if !is_recallable_item(&item, request) {
                return None;
            }

            Some(candidate_from_item(
                result.id,
                item,
                result.distance,
                RecallCandidateSource::Vector,
                request.ranking,
                request.staleness,
                request.now,
            ))
        })
        .collect::<Vec<_>>();

    for candidate in &candidates {
        seen_ids.insert(candidate.id);
    }

    if let Some(provider) = request.related_memory_provider {
        let anchors = candidates
            .iter()
            .map(|candidate| candidate.id)
            .collect::<Vec<_>>();
        let mut expanded_candidates = Vec::new();

        for anchor in anchors {
            let related_ids = provider.related_memory_ids(anchor)?;
            let related_items = store.get_many(&related_ids)?;

            for (related_id, related_item) in related_ids.into_iter().zip(related_items) {
                if !seen_ids.insert(related_id) {
                    continue;
                }

                let Some(item) = related_item else {
                    continue;
                };

                if !is_recallable_item(&item, request) {
                    continue;
                }

                expanded_candidates.push(candidate_from_item(
                    related_id,
                    item,
                    f32::INFINITY,
                    RecallCandidateSource::GraphExpansion { anchor },
                    request.ranking,
                    request.staleness,
                    request.now,
                ));
            }
        }

        candidates.extend(expanded_candidates);
    }

    candidates.sort_by(|left, right| {
        right
            .rank_score
            .total_cmp(&left.rank_score)
            .then_with(|| left.id.cmp(&right.id))
    });

    if record_surface_access {
        for candidate in &candidates {
            let access_event = request.raw_query_context.map_or_else(
                || AccessEvent::new(request.now, None, AccessOutcome::Surfaced),
                |raw_context| {
                    AccessEvent::with_raw_query_context(
                        request.now,
                        raw_context,
                        AccessOutcome::Surfaced,
                    )
                },
            );

            store.record_access(candidate.id, access_event)?;
        }
    }

    Ok(candidates)
}

fn candidate_from_item(
    id: MemoryId,
    item: MemoryItem,
    vector_distance: f32,
    source: RecallCandidateSource,
    ranking: RecallRankingConfig,
    staleness: RecallStalenessConfig,
    now: OffsetDateTime,
) -> RecallCandidate {
    let similarity_score = similarity_from_distance(vector_distance);
    let significance_score = item.significance;
    let recency_score = recency_score(&item, now);
    let graph_score = graph_score(source);
    let rank_score = ranking.similarity_weight * similarity_score
        + ranking.significance_weight * significance_score
        + ranking.recency_weight * recency_score
        + ranking.graph_weight * graph_score;
    let provenance = item.provenance.clone();
    let tier = item.tier;
    let currency = candidate_currency(&item, now);
    let load_bearing_possibly_stale = load_bearing_possibly_stale(&item, staleness, now);
    let cold_tier_retrieval = tier == Tier::Cold;

    RecallCandidate {
        id,
        item,
        provenance,
        tier,
        currency,
        load_bearing_possibly_stale,
        cold_tier_retrieval,
        vector_distance,
        similarity_score,
        significance_score,
        recency_score,
        graph_score,
        source,
        rank_score,
    }
}

fn recency_score(item: &MemoryItem, now: OffsetDateTime) -> f64 {
    let last_seen_at = item
        .access_events
        .iter()
        .map(|event| event.timestamp)
        .max()
        .unwrap_or(item.timestamps.ingested_at);

    if now <= last_seen_at {
        return 1.0;
    }

    let age_days = (now - last_seen_at).as_seconds_f64() / (24.0 * 60.0 * 60.0);

    1.0 / (1.0 + age_days)
}

fn graph_score(source: RecallCandidateSource) -> f64 {
    match source {
        RecallCandidateSource::Vector => 0.0,
        RecallCandidateSource::GraphExpansion { .. } => 1.0,
    }
}

fn candidate_currency(item: &MemoryItem, now: OffsetDateTime) -> RecallCandidateCurrency {
    if now < item.timestamps.valid_from {
        return RecallCandidateCurrency::NotYetValid;
    }

    if item
        .timestamps
        .valid_to
        .is_some_and(|valid_to| now >= valid_to)
    {
        return RecallCandidateCurrency::Invalidated;
    }

    RecallCandidateCurrency::Current
}

fn is_believed_at(item: &MemoryItem, as_of: OffsetDateTime) -> bool {
    item.timestamps.ingested_at <= as_of && item.timestamps.is_valid_at(as_of)
}

fn is_recallable_item(item: &MemoryItem, request: &RecallRequest<'_>) -> bool {
    is_believed_at(item, request.now) && (request.include_cold || item.tier != Tier::Cold)
}

fn load_bearing_possibly_stale(
    item: &MemoryItem,
    staleness: RecallStalenessConfig,
    now: OffsetDateTime,
) -> bool {
    if item.significance < staleness.load_bearing_significance_threshold {
        return false;
    }

    let last_validation_like_signal = item
        .access_events
        .iter()
        .filter(|event| event.outcome.is_actual_use())
        .map(|event| event.timestamp)
        .max()
        .unwrap_or(item.timestamps.ingested_at);

    if now <= last_validation_like_signal {
        return false;
    }

    (now - last_validation_like_signal).as_seconds_f64() >= staleness.stale_after_seconds
}

fn similarity_from_distance(distance: f32) -> f64 {
    let distance = f64::from(distance);

    if !distance.is_finite() || distance < 0.0 {
        return 0.0;
    }

    1.0 / (1.0 + distance)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{
        CURRENT_MEMORY_SCHEMA_VERSION, CredenceTier, Provenance, SourceKind, TemporalBounds, Tier,
    };
    use crate::storage::MemoryEvent;
    use crate::vector::HnswVectorIndex;
    use std::collections::BTreeMap;
    use tempfile::NamedTempFile;
    use time::Duration;

    #[derive(Default)]
    struct StaticRelatedMemoryProvider {
        related: BTreeMap<MemoryId, Vec<MemoryId>>,
    }

    impl RelatedMemoryProvider for StaticRelatedMemoryProvider {
        fn related_memory_ids(&self, id: MemoryId) -> Result<Vec<MemoryId>, StorageError> {
            Ok(self.related.get(&id).cloned().unwrap_or_default())
        }
    }

    fn test_item(content: &str, now: OffsetDateTime) -> MemoryItem {
        MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            id: MemoryId::new_v7(),
            content: content.to_owned(),
            compaction: None,
            embedding_ref: None,
            provenance: Provenance::new(SourceKind::User, None, "retrieval-test"),
            timestamps: TemporalBounds::open_from(now, now),
            tier: Tier::Warm,
            credence: CredenceTier::FirmAuthoritative,
            significance: 1.0,
            credence_floor: Tier::Warm,
            access_events: Vec::new(),
        }
    }

    #[test]
    fn recall_returns_vector_ranked_valid_candidates_and_records_surface_access() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(1);
        let mut near = test_item("near", OffsetDateTime::UNIX_EPOCH);
        let mut far = test_item("far", OffsetDateTime::UNIX_EPOCH);
        let mut invalid = test_item("invalid", OffsetDateTime::UNIX_EPOCH);

        invalid.timestamps = invalid.timestamps.closed_at(now - Duration::seconds(1));

        store
            .write_embedded(
                &mut near,
                &mut vector_index,
                &[0.0, 0.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("near should write");
        store
            .write_embedded(
                &mut far,
                &mut vector_index,
                &[5.0, 5.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("far should write");
        store
            .write_embedded(
                &mut invalid,
                &mut vector_index,
                &[0.1, 0.1],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("invalid should write");

        let query = [0.0, 0.0];
        let request =
            RecallRequest::new(&query, 3, now).with_raw_query_context("raw matter context");
        let candidates = recall(&store, &vector_index, &request).expect("recall should work");
        let stored_near = store
            .get(near.id)
            .expect("near should read")
            .expect("near should exist");
        let stored_far = store
            .get(far.id)
            .expect("far should read")
            .expect("far should exist");
        let stored_invalid = store
            .get(invalid.id)
            .expect("invalid should read")
            .expect("invalid should exist");
        let events = store.events().expect("events should read");

        assert_eq!(
            candidates
                .iter()
                .map(|candidate| candidate.id)
                .collect::<Vec<_>>(),
            vec![near.id, far.id]
        );
        assert_eq!(candidates[0].provenance, near.provenance);
        assert_eq!(candidates[0].tier, Tier::Warm);
        assert_eq!(candidates[0].currency, RecallCandidateCurrency::Current);
        assert!(candidates[0].rank_score > candidates[1].rank_score);
        assert_eq!(stored_near.access_events.len(), 1);
        assert_eq!(stored_far.access_events.len(), 1);
        assert!(stored_invalid.access_events.is_empty());
        assert_eq!(
            stored_near.access_events[0].outcome,
            AccessOutcome::Surfaced
        );
        assert_ne!(
            stored_near.access_events[0].query_context_hash.as_deref(),
            Some("raw matter context")
        );
        assert!(matches!(
            events.last().map(|record| &record.event),
            Some(MemoryEvent::AccessRecorded { id, .. }) if *id == far.id
        ));
    }

    #[test]
    fn recall_requires_explicit_cold_tier_opt_in() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(1);
        let mut cold = test_item("cold", OffsetDateTime::UNIX_EPOCH);
        let mut warm = test_item("warm", OffsetDateTime::UNIX_EPOCH);

        cold.tier = Tier::Cold;
        cold.credence_floor = Tier::Cold;

        store
            .write_embedded(
                &mut cold,
                &mut vector_index,
                &[0.0, 0.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("cold should write");
        store
            .write_embedded(
                &mut warm,
                &mut vector_index,
                &[5.0, 5.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("warm should write");

        let query = [0.0, 0.0];
        let default_request = RecallRequest::new(&query, 2, now);
        let cold_request = RecallRequest::new(&query, 2, now).include_cold();
        let default_candidates =
            recall(&store, &vector_index, &default_request).expect("recall should work");
        let cold_candidates =
            recall(&store, &vector_index, &cold_request).expect("cold recall should work");
        let cold_candidate = cold_candidates
            .iter()
            .find(|candidate| candidate.id == cold.id)
            .expect("cold candidate should be present when opted in");

        assert_eq!(
            default_candidates
                .iter()
                .map(|candidate| candidate.id)
                .collect::<Vec<_>>(),
            vec![warm.id]
        );
        assert!(cold_candidate.cold_tier_retrieval);
        assert_eq!(cold_candidate.tier, Tier::Cold);
    }

    #[test]
    fn recall_rank_score_includes_materialized_significance() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(1);
        let mut near = test_item("near but low value", OffsetDateTime::UNIX_EPOCH);
        let mut far = test_item("far but important", OffsetDateTime::UNIX_EPOCH);

        near.significance = 0.0;
        far.significance = 10.0;

        store
            .write_embedded(
                &mut near,
                &mut vector_index,
                &[0.0, 0.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("near should write");
        store
            .write_embedded(
                &mut far,
                &mut vector_index,
                &[5.0, 5.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("far should write");

        let query = [0.0, 0.0];
        let request = RecallRequest::new(&query, 2, now);
        let candidates = recall(&store, &vector_index, &request).expect("recall should work");

        assert_eq!(candidates[0].id, far.id);
        assert!((candidates[0].significance_score - 10.0).abs() < f64::EPSILON);
        assert!(candidates[0].rank_score > candidates[1].rank_score);
    }

    #[test]
    fn recall_ranking_can_be_tuned_by_recency() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(30);
        let mut old = test_item("old", OffsetDateTime::UNIX_EPOCH);
        let mut recent = test_item("recent", now - Duration::days(1));

        old.significance = 0.0;
        recent.significance = 0.0;

        store
            .write_embedded(
                &mut old,
                &mut vector_index,
                &[0.0, 0.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("old should write");
        store
            .write_embedded(
                &mut recent,
                &mut vector_index,
                &[5.0, 5.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("recent should write");

        let query = [0.0, 0.0];
        let request = RecallRequest::new(&query, 2, now).with_ranking(RecallRankingConfig {
            similarity_weight: 0.0,
            significance_weight: 0.0,
            recency_weight: 1.0,
            graph_weight: 0.0,
        });
        let candidates = recall(&store, &vector_index, &request).expect("recall should work");

        assert_eq!(candidates[0].id, recent.id);
        assert!(candidates[0].recency_score > candidates[1].recency_score);
    }

    #[test]
    fn recall_expands_graph_related_memories() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(1);
        let mut anchor = test_item("anchor", OffsetDateTime::UNIX_EPOCH);
        let related = test_item("related", OffsetDateTime::UNIX_EPOCH);
        let mut provider = StaticRelatedMemoryProvider::default();

        provider.related.insert(anchor.id, vec![related.id]);

        store
            .write_embedded(
                &mut anchor,
                &mut vector_index,
                &[0.0, 0.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("anchor should write");
        store.write(&related).expect("related should write");

        let query = [0.0, 0.0];
        let request = RecallRequest::new(&query, 1, now).with_related_memory_provider(&provider);
        let candidates = recall(&store, &vector_index, &request).expect("recall should work");
        let related_candidate = candidates
            .iter()
            .find(|candidate| candidate.id == related.id)
            .expect("related candidate should be present");
        let stored_related = store
            .get(related.id)
            .expect("related should read")
            .expect("related should exist");

        assert_eq!(candidates.len(), 2);
        assert_eq!(
            related_candidate.source,
            RecallCandidateSource::GraphExpansion { anchor: anchor.id }
        );
        assert_eq!(
            stored_related.access_events[0].outcome,
            AccessOutcome::Surfaced
        );
    }

    #[test]
    fn recall_ranking_can_be_tuned_by_graph_expansion() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(1);
        let mut anchor = test_item("anchor", OffsetDateTime::UNIX_EPOCH);
        let related = test_item("related", OffsetDateTime::UNIX_EPOCH);
        let mut provider = StaticRelatedMemoryProvider::default();

        anchor.significance = 0.0;
        provider.related.insert(anchor.id, vec![related.id]);

        store
            .write_embedded(
                &mut anchor,
                &mut vector_index,
                &[0.0, 0.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("anchor should write");
        store.write(&related).expect("related should write");

        let query = [0.0, 0.0];
        let request = RecallRequest::new(&query, 1, now)
            .with_related_memory_provider(&provider)
            .with_ranking(RecallRankingConfig {
                similarity_weight: 0.0,
                significance_weight: 0.0,
                recency_weight: 0.0,
                graph_weight: 1.0,
            });
        let candidates = recall(&store, &vector_index, &request).expect("recall should work");

        assert_eq!(candidates[0].id, related.id);
        assert!(candidates[0].graph_score > candidates[1].graph_score);
    }

    #[test]
    fn recall_flags_load_bearing_but_possibly_stale_candidates() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let ingested_at = OffsetDateTime::UNIX_EPOCH;
        let now = ingested_at + Duration::days(60);
        let mut stale = test_item("stale load bearing", ingested_at);
        let mut recently_validated = test_item("recently used", ingested_at);

        stale.significance = 3.0;
        recently_validated.significance = 3.0;
        recently_validated.access_events.push(AccessEvent::new(
            now - Duration::days(1),
            None,
            AccessOutcome::Cited,
        ));

        store
            .write_embedded(
                &mut stale,
                &mut vector_index,
                &[0.0, 0.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("stale should write");
        store
            .write_embedded(
                &mut recently_validated,
                &mut vector_index,
                &[1.0, 1.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("recently validated should write");

        let query = [0.0, 0.0];
        let request = RecallRequest::new(&query, 2, now);
        let candidates = recall(&store, &vector_index, &request).expect("recall should work");
        let stale_candidate = candidates
            .iter()
            .find(|candidate| candidate.id == stale.id)
            .expect("stale candidate should be present");
        let recently_validated_candidate = candidates
            .iter()
            .find(|candidate| candidate.id == recently_validated.id)
            .expect("recently validated candidate should be present");

        assert!(stale_candidate.load_bearing_possibly_stale);
        assert!(!recently_validated_candidate.load_bearing_possibly_stale);
    }

    #[test]
    fn timeline_returns_believed_candidates_as_of_without_recording_access() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let ingested_at = OffsetDateTime::UNIX_EPOCH + Duration::days(1);
        let valid_to = ingested_at + Duration::days(10);
        let mut item = test_item("historical", ingested_at);

        item.timestamps = item.timestamps.closed_at(valid_to);

        store
            .write_embedded(
                &mut item,
                &mut vector_index,
                &[0.0, 0.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("item should write");

        let query = [0.0, 0.0];
        let before_ingest = RecallRequest::new(&query, 1, ingested_at - Duration::seconds(1));
        let while_valid = RecallRequest::new(&query, 1, ingested_at + Duration::days(1));
        let after_invalid = RecallRequest::new(&query, 1, valid_to + Duration::seconds(1));

        assert!(
            timeline(&store, &vector_index, &before_ingest)
                .expect("timeline should read")
                .is_empty()
        );

        let historical =
            timeline(&store, &vector_index, &while_valid).expect("timeline should read");

        assert_eq!(historical.len(), 1);
        assert_eq!(historical[0].id, item.id);
        assert_eq!(historical[0].currency, RecallCandidateCurrency::Current);
        assert!(
            timeline(&store, &vector_index, &after_invalid)
                .expect("timeline should read")
                .is_empty()
        );

        let stored = store
            .get(item.id)
            .expect("item should read")
            .expect("item should exist");

        assert!(stored.access_events.is_empty());
    }
}
