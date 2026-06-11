// SPDX-License-Identifier: MIT

//! Small public API facade.

use crate::model::{AccessOutcome, CredenceTier, MemoryId, MemoryItem, Provenance, Tier};
use crate::retrieval::{
    RecallCandidate, RecallCandidateCurrency, RecallError, RecallRequest, recall, timeline,
};
use crate::significance::{SignificanceBreakdown, SignificanceConfig};
use crate::storage::{MemoryAuditEntry, MemoryWriteEvent, RedbMemoryStore, StorageError};
use crate::vector::{VectorIndex, VectorIndexError};
use std::path::Path;
use thiserror::Error;
use time::OffsetDateTime;

/// Error returned by the high-level Shibahama API.
#[derive(Debug, Error)]
pub enum ShibahamaError {
    /// Storage operation failed.
    #[error(transparent)]
    Storage(#[from] StorageError),
    /// Recall operation failed.
    #[error(transparent)]
    Recall(#[from] RecallError),
    /// Vector operation failed.
    #[error(transparent)]
    Vector(#[from] VectorIndexError),
}

/// Embedding metadata supplied to `write_with_embedding`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct WriteEmbedding<'a> {
    /// Embedding vector.
    pub vector: &'a [f32],
    /// Logical vector index name.
    pub index_name: &'a str,
    /// Embedding model name.
    pub model: &'a str,
    /// Embedding model version.
    pub model_version: &'a str,
}

/// Structured explanation for why a memory currently has its state.
#[derive(Clone, Debug, PartialEq)]
pub struct WhyTrace {
    /// Current materialized memory item.
    pub item: MemoryItem,
    /// Deterministic significance score breakdown at `currency.as_of`.
    pub significance: SignificanceBreakdown,
    /// Current provenance copied to the trace boundary.
    pub provenance: Provenance,
    /// Current tier, credence floor, and tier/credence audit entries.
    pub tier: WhyTierTrace,
    /// Validity and ingestion state at the explanation instant.
    pub currency: WhyCurrencyTrace,
    /// Complete credence/tier audit trail for this memory.
    pub audit_trail: Vec<MemoryAuditEntry>,
}

/// Tier and credence portion of a `why` explanation.
#[derive(Clone, Debug, PartialEq)]
pub struct WhyTierTrace {
    /// Current accessibility tier.
    pub current: Tier,
    /// Current credence tier.
    pub credence: CredenceTier,
    /// Lowest tier allowed by the memory's credence.
    pub credence_floor: Tier,
    /// Audit entries that changed this memory's tier or credence.
    pub audit: Vec<MemoryAuditEntry>,
}

/// Currency portion of a `why` explanation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WhyCurrencyTrace {
    /// Instant the currency state was evaluated against.
    pub as_of: OffsetDateTime,
    /// Whether the memory is current, not-yet-valid, or invalidated at `as_of`.
    pub state: RecallCandidateCurrency,
    /// Valid-time start for this memory.
    pub valid_from: OffsetDateTime,
    /// Valid-time end, if the memory was superseded or invalidated.
    pub valid_to: Option<OffsetDateTime>,
    /// Time Shibahama ingested the observation.
    pub ingested_at: OffsetDateTime,
}

impl WhyCurrencyTrace {
    fn from_item(item: &MemoryItem, as_of: OffsetDateTime) -> Self {
        let state = if as_of < item.timestamps.valid_from {
            RecallCandidateCurrency::NotYetValid
        } else if item
            .timestamps
            .valid_to
            .is_some_and(|valid_to| as_of >= valid_to)
        {
            RecallCandidateCurrency::Invalidated
        } else {
            RecallCandidateCurrency::Current
        };

        Self {
            as_of,
            state,
            valid_from: item.timestamps.valid_from,
            valid_to: item.timestamps.valid_to,
            ingested_at: item.timestamps.ingested_at,
        }
    }
}

/// In-process Shibahama engine over a store and vector index.
pub struct Shibahama<V> {
    store: RedbMemoryStore,
    vector_index: V,
}

impl<V: VectorIndex> Shibahama<V> {
    /// Opens a Shibahama store with a caller-supplied vector index.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened.
    pub fn open(path: impl AsRef<Path>, vector_index: V) -> Result<Self, ShibahamaError> {
        Ok(Self {
            store: RedbMemoryStore::open(path)?,
            vector_index,
        })
    }

    /// Returns the underlying store for lower-level operations.
    #[must_use]
    pub const fn store(&self) -> &RedbMemoryStore {
        &self.store
    }

    /// Writes a memory event without adding an embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when the write cannot be persisted.
    pub fn write(&self, event: MemoryWriteEvent) -> Result<MemoryItem, ShibahamaError> {
        let (_, item) = self.store.write_event(event)?;

        Ok(item)
    }

    /// Writes a memory event and indexes its embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when the vector cannot be indexed or the write cannot be persisted.
    pub fn write_with_embedding(
        &mut self,
        event: MemoryWriteEvent,
        embedding: WriteEmbedding<'_>,
    ) -> Result<MemoryItem, ShibahamaError> {
        let (_, item) = self.store.write_event_embedded(
            event,
            &mut self.vector_index,
            embedding.vector,
            embedding.index_name,
            embedding.model,
            embedding.model_version,
        )?;

        Ok(item)
    }

    /// Recalls current fact memories for a query embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, or access recording fail.
    pub fn recall(
        &self,
        request: &RecallRequest<'_>,
    ) -> Result<Vec<RecallCandidate>, ShibahamaError> {
        Ok(recall(&self.store, &self.vector_index, request)?)
    }

    /// Replays recalled memories as they were believed at `request.now`.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search or storage reads fail.
    pub fn timeline(
        &self,
        request: &RecallRequest<'_>,
    ) -> Result<Vec<RecallCandidate>, ShibahamaError> {
        Ok(timeline(&self.store, &self.vector_index, request)?)
    }

    /// Reinforces a memory with a usage outcome.
    ///
    /// # Errors
    ///
    /// Returns an error when the access event cannot be persisted.
    pub fn reinforce(&self, id: MemoryId, outcome: AccessOutcome) -> Result<bool, ShibahamaError> {
        Ok(self.store.reinforce(id, outcome)?.is_some())
    }

    /// Returns a full explanation for the current memory state.
    ///
    /// # Errors
    ///
    /// Returns an error when the item, significance inputs, or audit trail cannot be read.
    pub fn why(&self, id: MemoryId) -> Result<Option<WhyTrace>, ShibahamaError> {
        self.why_at(id, OffsetDateTime::now_utc())
    }

    /// Returns a full explanation for the memory state at `now`.
    ///
    /// # Errors
    ///
    /// Returns an error when the item, significance inputs, or audit trail cannot be read.
    pub fn why_at(
        &self,
        id: MemoryId,
        now: OffsetDateTime,
    ) -> Result<Option<WhyTrace>, ShibahamaError> {
        self.why_with_significance_policy(id, now, SignificanceConfig::default())
    }

    /// Returns a full explanation using a caller-supplied significance policy.
    ///
    /// # Errors
    ///
    /// Returns an error when the item, graph centrality, or audit trail cannot be read.
    pub fn why_with_significance_policy(
        &self,
        id: MemoryId,
        now: OffsetDateTime,
        policy: SignificanceConfig,
    ) -> Result<Option<WhyTrace>, ShibahamaError> {
        let Some(item) = self.store.get(id)? else {
            return Ok(None);
        };
        let graph_centrality = self.store.graph_centrality_for_memory(id)?;
        let significance = policy.explain_with_graph_centrality(&item, now, graph_centrality);
        let audit_trail = self.store.audit_trail(id)?;

        Ok(Some(WhyTrace {
            provenance: item.provenance.clone(),
            tier: WhyTierTrace {
                current: item.tier,
                credence: item.credence,
                credence_floor: item.credence_floor,
                audit: audit_trail.clone(),
            },
            currency: WhyCurrencyTrace::from_item(&item, now),
            item,
            significance,
            audit_trail,
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Provenance, SourceKind};
    use crate::retrieval::{RecallCandidateCurrency, RecallRequest};
    use crate::vector::HnswVectorIndex;
    use tempfile::NamedTempFile;
    use time::OffsetDateTime;

    #[test]
    fn facade_write_recall_reinforce_why_and_timeline_work() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let event = MemoryWriteEvent::new(
            "facade memory",
            Provenance::new(SourceKind::User, None, "api-test"),
            OffsetDateTime::UNIX_EPOCH,
            OffsetDateTime::UNIX_EPOCH,
        );
        let item = shibahama
            .write_with_embedding(
                event,
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("write should work");
        let query = [0.0, 0.0];
        let request = RecallRequest::new(&query, 1, OffsetDateTime::UNIX_EPOCH);
        let recalled = shibahama.recall(&request).expect("recall should work");
        let timeline = shibahama.timeline(&request).expect("timeline should work");

        assert_eq!(recalled[0].id, item.id);
        assert_eq!(timeline[0].id, item.id);
        assert!(
            shibahama
                .reinforce(item.id, AccessOutcome::Cited)
                .expect("reinforce should work")
        );
        let why = shibahama
            .why_at(item.id, OffsetDateTime::UNIX_EPOCH)
            .expect("why should read")
            .expect("item should exist");

        assert_eq!(why.item.content, "facade memory");
        assert_eq!(why.provenance.source_kind, SourceKind::User);
        assert_eq!(why.tier.current, why.item.tier);
        assert_eq!(why.tier.credence, why.item.credence);
        assert_eq!(why.currency.state, RecallCandidateCurrency::Current);
        assert_eq!(why.currency.valid_from, item.timestamps.valid_from);
        assert!((why.significance.base_score - why.item.significance).abs() < f64::EPSILON);
        assert_eq!(why.audit_trail.len(), why.tier.audit.len());
        assert!(why.audit_trail.len() >= 2);
    }

    #[test]
    fn why_trace_reports_invalidated_currency() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let valid_from = OffsetDateTime::UNIX_EPOCH;
        let valid_to = valid_from + time::Duration::days(1);
        let item = shibahama
            .write(MemoryWriteEvent::new(
                "old facade memory",
                Provenance::new(SourceKind::User, None, "api-test"),
                valid_from,
                valid_from,
            ))
            .expect("write should work");

        shibahama
            .store()
            .soft_invalidate(item.id, valid_to)
            .expect("invalidate should work");

        let why = shibahama
            .why_at(item.id, valid_to)
            .expect("why should read")
            .expect("item should exist");

        assert_eq!(why.currency.state, RecallCandidateCurrency::Invalidated);
        assert_eq!(why.currency.valid_to, Some(valid_to));
    }
}
