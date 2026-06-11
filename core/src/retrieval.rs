// SPDX-License-Identifier: MIT

//! Retrieval orchestration for recall.

use crate::model::{AccessEvent, AccessOutcome, MemoryId, MemoryItem};
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
    /// Ranking weights applied to retrieved candidates.
    pub ranking: RecallRankingConfig,
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
            ranking: RecallRankingConfig::default(),
            related_memory_provider: None,
        }
    }

    /// Adds raw query context that will be hashed before storage.
    #[must_use]
    pub const fn with_raw_query_context(mut self, raw_query_context: &'a str) -> Self {
        self.raw_query_context = Some(raw_query_context);
        self
    }

    /// Overrides ranking weights for this request.
    #[must_use]
    pub const fn with_ranking(mut self, ranking: RecallRankingConfig) -> Self {
        self.ranking = ranking;
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
}

impl Default for RecallRankingConfig {
    fn default() -> Self {
        Self {
            similarity_weight: 1.0,
            significance_weight: 1.0,
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
    /// Vector distance from the query, where lower is closer.
    pub vector_distance: f32,
    /// Normalized similarity contribution derived from vector distance.
    pub similarity_score: f64,
    /// Materialized significance contribution used by ranking.
    pub significance_score: f64,
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

            if !item.timestamps.is_valid_at(request.now) {
                return None;
            }

            Some(candidate_from_item(
                result.id,
                item,
                result.distance,
                RecallCandidateSource::Vector,
                request.ranking,
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

                if !item.timestamps.is_valid_at(request.now) {
                    continue;
                }

                expanded_candidates.push(candidate_from_item(
                    related_id,
                    item,
                    f32::INFINITY,
                    RecallCandidateSource::GraphExpansion { anchor },
                    request.ranking,
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

    Ok(candidates)
}

fn candidate_from_item(
    id: MemoryId,
    item: MemoryItem,
    vector_distance: f32,
    source: RecallCandidateSource,
    ranking: RecallRankingConfig,
) -> RecallCandidate {
    let similarity_score = similarity_from_distance(vector_distance);
    let significance_score = item.significance;
    let rank_score = ranking.similarity_weight * similarity_score
        + ranking.significance_weight * significance_score;

    RecallCandidate {
        id,
        item,
        vector_distance,
        similarity_score,
        significance_score,
        source,
        rank_score,
    }
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
}
