// SPDX-License-Identifier: MIT

//! Small public API facade.

use crate::anomaly::AnomalyConfig;
use crate::model::{AccessOutcome, CredenceTier, MemoryId, MemoryItem, Provenance, Tier};
use crate::reconstruction::ReconstructionBudgetConfig;
use crate::retrieval::{
    RecallCandidate, RecallCandidateCurrency, RecallDiversificationConfig, RecallError,
    RecallRankingConfig, RecallRequest, RecallStalenessConfig, recall, timeline,
};
use crate::significance::{SignificanceBreakdown, SignificanceConfig};
use crate::storage::{
    MemoryAuditEntry, MemoryWriteEvent, RedbMemoryStore, StorageError, TierCapacityConfig,
};
use crate::vector::{VectorIndex, VectorIndexError};
use std::iter::FusedIterator;
use std::path::Path;
#[cfg(feature = "tokio")]
use std::path::PathBuf;
#[cfg(feature = "tokio")]
use std::sync::Arc;
use thiserror::Error;
use time::OffsetDateTime;

/// Error returned by the high-level Shibahama API.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum ShibahamaError {
    /// Storage operation failed.
    #[error(
        "[SHIBA_STORAGE] storage operation failed: {0}; action: verify the store path and durable state are accessible, then retry or restore from a snapshot"
    )]
    Storage(#[source] StorageError),
    /// Recall operation failed.
    #[error(
        "[SHIBA_RECALL] recall operation failed: {0}; action: verify the query embedding, vector index, and store availability before retrying"
    )]
    Recall(#[source] RecallError),
    /// Vector operation failed.
    #[error(
        "[SHIBA_VECTOR] vector index operation failed: {0}; action: verify embedding dimensionality and vector backend availability before retrying"
    )]
    Vector(#[source] VectorIndexError),
    /// Caller supplied an unsupported or internally inconsistent request.
    #[error("[SHIBA_INVALID_REQUEST] invalid request: {0}; action: adjust the request and retry")]
    InvalidRequest(String),
    /// Tokio task failed before returning an API result.
    #[cfg(feature = "tokio")]
    #[error(
        "[SHIBA_TASK] async task failed: {0}; action: inspect the runtime for cancellation or panic before retrying"
    )]
    Task(#[source] tokio::task::JoinError),
}

impl From<StorageError> for ShibahamaError {
    fn from(error: StorageError) -> Self {
        match error {
            StorageError::Vector(error) => Self::Vector(error),
            error => Self::Storage(error),
        }
    }
}

impl From<RecallError> for ShibahamaError {
    fn from(error: RecallError) -> Self {
        match error {
            RecallError::Storage(error) => Self::from(error),
            RecallError::Vector(error) => Self::Vector(error),
        }
    }
}

impl From<VectorIndexError> for ShibahamaError {
    fn from(error: VectorIndexError) -> Self {
        Self::Vector(error)
    }
}

#[cfg(feature = "tokio")]
impl From<tokio::task::JoinError> for ShibahamaError {
    fn from(error: tokio::task::JoinError) -> Self {
        Self::Task(error)
    }
}

/// Stable high-level error category for bindings and applications.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum ShibahamaErrorKind {
    /// Durable storage or snapshot state failed.
    Storage,
    /// Recall orchestration failed.
    Recall,
    /// Vector index or embedding dimensionality failed.
    Vector,
    /// Caller supplied an unsupported or internally inconsistent request.
    InvalidRequest,
    /// Tokio task failed before returning an API result.
    #[cfg(feature = "tokio")]
    Task,
}

impl ShibahamaErrorKind {
    /// Stable machine-readable code for this error category.
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::Storage => "SHIBA_STORAGE",
            Self::Recall => "SHIBA_RECALL",
            Self::Vector => "SHIBA_VECTOR",
            Self::InvalidRequest => "SHIBA_INVALID_REQUEST",
            #[cfg(feature = "tokio")]
            Self::Task => "SHIBA_TASK",
        }
    }

    /// Human-readable recovery guidance for this error category.
    #[must_use]
    pub const fn action(self) -> &'static str {
        match self {
            Self::Storage => {
                "verify the store path and durable state are accessible, then retry or restore from a snapshot"
            }
            Self::Recall => {
                "verify the query embedding, vector index, and store availability before retrying"
            }
            Self::Vector => {
                "verify embedding dimensionality and vector backend availability before retrying"
            }
            Self::InvalidRequest => "adjust the request and retry",
            #[cfg(feature = "tokio")]
            Self::Task => "inspect the runtime for cancellation or panic before retrying",
        }
    }
}

impl ShibahamaError {
    /// Stable high-level category for this error.
    #[must_use]
    pub const fn kind(&self) -> ShibahamaErrorKind {
        match self {
            Self::Storage(_) => ShibahamaErrorKind::Storage,
            Self::Recall(_) => ShibahamaErrorKind::Recall,
            Self::Vector(_) => ShibahamaErrorKind::Vector,
            Self::InvalidRequest(_) => ShibahamaErrorKind::InvalidRequest,
            #[cfg(feature = "tokio")]
            Self::Task(_) => ShibahamaErrorKind::Task,
        }
    }

    /// Stable machine-readable code for this error.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        self.kind().code()
    }

    /// Human-readable recovery guidance for this error.
    #[must_use]
    pub const fn action(&self) -> &'static str {
        self.kind().action()
    }
}

/// Sane-default configuration for a Shibahama engine.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct ShibahamaConfig {
    /// Transparent significance scoring and tier-promotion thresholds.
    pub significance: SignificanceConfig,
    /// Default recall ranking weights.
    pub recall_ranking: RecallRankingConfig,
    /// Default stale-load-bearing recall detection thresholds.
    pub recall_staleness: RecallStalenessConfig,
    /// Default near-duplicate suppression policy.
    pub recall_diversification: RecallDiversificationConfig,
    /// Default anomaly detection thresholds.
    pub anomaly: AnomalyConfig,
    /// Default reconstruction rate/cost budget.
    pub reconstruction_budget: ReconstructionBudgetConfig,
    /// Default tier residency budgets.
    pub tier_capacity: TierCapacityConfig,
}

impl ShibahamaConfig {
    /// Builds a recall request populated with this config's recall defaults.
    #[must_use]
    pub fn recall_request(
        self,
        query_vector: &[f32],
        top_k: usize,
        now: OffsetDateTime,
    ) -> RecallRequest<'_> {
        RecallRequest::new(query_vector, top_k, now)
            .with_ranking(self.recall_ranking)
            .with_staleness(self.recall_staleness)
            .with_diversification(self.recall_diversification)
    }
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

/// Owned embedding metadata for async write calls.
#[cfg(feature = "tokio")]
#[derive(Clone, Debug, PartialEq)]
pub struct AsyncWriteEmbedding {
    /// Embedding vector.
    pub vector: Vec<f32>,
    /// Logical vector index name.
    pub index_name: String,
    /// Embedding model name.
    pub model: String,
    /// Embedding model version.
    pub model_version: String,
}

#[cfg(feature = "tokio")]
impl AsyncWriteEmbedding {
    /// Creates owned embedding metadata for async writes.
    #[must_use]
    pub fn new(
        vector: impl Into<Vec<f32>>,
        index_name: impl Into<String>,
        model: impl Into<String>,
        model_version: impl Into<String>,
    ) -> Self {
        Self {
            vector: vector.into(),
            index_name: index_name.into(),
            model: model.into(),
            model_version: model_version.into(),
        }
    }

    fn as_write_embedding(&self) -> WriteEmbedding<'_> {
        WriteEmbedding {
            vector: &self.vector,
            index_name: &self.index_name,
            model: &self.model,
            model_version: &self.model_version,
        }
    }
}

#[cfg(feature = "tokio")]
impl From<WriteEmbedding<'_>> for AsyncWriteEmbedding {
    fn from(value: WriteEmbedding<'_>) -> Self {
        Self::new(
            value.vector.to_vec(),
            value.index_name,
            value.model,
            value.model_version,
        )
    }
}

/// Owned recall request for async task boundaries.
#[cfg(feature = "tokio")]
#[derive(Clone, Debug, PartialEq)]
pub struct AsyncRecallRequest {
    /// Query embedding supplied by the caller's embedding model.
    pub query_vector: Vec<f32>,
    /// Optional raw query/context text to hash into surfaced access events.
    pub raw_query_context: Option<String>,
    /// Maximum number of vector candidates to inspect.
    pub top_k: usize,
    /// Valid-time instant used for default current-fact filtering.
    pub now: OffsetDateTime,
    /// Whether recall may return cold-tier memories.
    pub include_cold: bool,
    /// Whether recall may return instruction/directive memories.
    pub include_instructions: bool,
    /// Ranking weights applied to retrieved candidates.
    pub ranking: RecallRankingConfig,
    /// Policy for flagging load-bearing but possibly stale memories.
    pub staleness: RecallStalenessConfig,
    /// Policy for suppressing near-duplicate results.
    pub diversification: RecallDiversificationConfig,
}

#[cfg(feature = "tokio")]
impl AsyncRecallRequest {
    /// Creates an owned async recall request for a query vector.
    #[must_use]
    pub fn new(query_vector: impl Into<Vec<f32>>, top_k: usize, now: OffsetDateTime) -> Self {
        let request = RecallRequest::new(&[], top_k, now);

        Self {
            query_vector: query_vector.into(),
            raw_query_context: None,
            top_k,
            now,
            include_cold: request.include_cold,
            include_instructions: request.include_instructions,
            ranking: request.ranking,
            staleness: request.staleness,
            diversification: request.diversification,
        }
    }

    /// Copies a borrowed sync recall request into an owned async request.
    ///
    /// # Errors
    ///
    /// Returns an error when the borrowed request uses a related-memory provider, which cannot
    /// safely cross the async blocking-task boundary.
    pub fn try_from_recall_request(request: &RecallRequest<'_>) -> Result<Self, ShibahamaError> {
        if request.related_memory_provider.is_some() {
            return Err(ShibahamaError::InvalidRequest(
                "async recall requests must own their data; related-memory providers are only supported by the sync API".to_owned(),
            ));
        }

        Ok(Self {
            query_vector: request.query_vector.to_vec(),
            raw_query_context: request.raw_query_context.map(str::to_owned),
            top_k: request.top_k,
            now: request.now,
            include_cold: request.include_cold,
            include_instructions: request.include_instructions,
            ranking: request.ranking,
            staleness: request.staleness,
            diversification: request.diversification,
        })
    }

    /// Adds raw query context that will be hashed before storage.
    #[must_use]
    pub fn with_raw_query_context(mut self, raw_query_context: impl Into<String>) -> Self {
        self.raw_query_context = Some(raw_query_context.into());
        self
    }

    /// Allows cold-tier memories to be returned.
    #[must_use]
    pub const fn include_cold(mut self) -> Self {
        self.include_cold = true;
        self
    }

    /// Allows instruction/directive memories to be returned.
    #[must_use]
    pub const fn include_instructions(mut self) -> Self {
        self.include_instructions = true;
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

    /// Overrides result diversification policy for this request.
    #[must_use]
    pub const fn with_diversification(
        mut self,
        diversification: RecallDiversificationConfig,
    ) -> Self {
        self.diversification = diversification;
        self
    }

    fn as_recall_request(&self) -> RecallRequest<'_> {
        let mut request = RecallRequest::new(&self.query_vector, self.top_k, self.now);
        request.raw_query_context = self.raw_query_context.as_deref();
        request.include_cold = self.include_cold;
        request.include_instructions = self.include_instructions;
        request.ranking = self.ranking;
        request.staleness = self.staleness;
        request.diversification = self.diversification;

        request
    }
}

/// Owning iterator over ranked recall candidates.
#[derive(Clone, Debug)]
pub struct RecallStream {
    candidates: std::vec::IntoIter<RecallCandidate>,
}

impl RecallStream {
    fn new(candidates: Vec<RecallCandidate>) -> Self {
        Self {
            candidates: candidates.into_iter(),
        }
    }

    /// Number of candidates still available without advancing the stream.
    #[must_use]
    pub fn remaining(&self) -> usize {
        self.candidates.len()
    }
}

impl Iterator for RecallStream {
    type Item = RecallCandidate;

    fn next(&mut self) -> Option<Self::Item> {
        self.candidates.next()
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        self.candidates.size_hint()
    }
}

impl ExactSizeIterator for RecallStream {
    fn len(&self) -> usize {
        self.candidates.len()
    }
}

impl FusedIterator for RecallStream {}

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
    config: ShibahamaConfig,
}

impl<V: VectorIndex> Shibahama<V> {
    /// Opens a Shibahama store with a caller-supplied vector index.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened.
    pub fn open(path: impl AsRef<Path>, vector_index: V) -> Result<Self, ShibahamaError> {
        Self::open_with_config(path, vector_index, ShibahamaConfig::default())
    }

    /// Opens a Shibahama store with an explicit engine config.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened.
    pub fn open_with_config(
        path: impl AsRef<Path>,
        vector_index: V,
        config: ShibahamaConfig,
    ) -> Result<Self, ShibahamaError> {
        Ok(Self {
            store: RedbMemoryStore::open(path)?,
            vector_index,
            config,
        })
    }

    /// Returns the underlying store for lower-level operations.
    #[must_use]
    pub const fn store(&self) -> &RedbMemoryStore {
        &self.store
    }

    /// Returns this engine's active config.
    #[must_use]
    pub const fn config(&self) -> ShibahamaConfig {
        self.config
    }

    /// Replaces this engine's active config.
    pub fn set_config(&mut self, config: ShibahamaConfig) {
        self.config = config;
    }

    /// Builds a recall request from this engine's recall defaults.
    #[must_use]
    pub fn recall_request<'a>(
        &self,
        query_vector: &'a [f32],
        top_k: usize,
        now: OffsetDateTime,
    ) -> RecallRequest<'a> {
        self.config.recall_request(query_vector, top_k, now)
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

    /// Recalls current fact memories and returns an owning iterator over ranked candidates.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, or access recording fail.
    pub fn stream_recall(
        &self,
        request: &RecallRequest<'_>,
    ) -> Result<RecallStream, ShibahamaError> {
        Ok(RecallStream::new(self.recall(request)?))
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

    /// Replays timeline recall and returns an owning iterator over ranked candidates.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search or storage reads fail.
    pub fn stream_timeline(
        &self,
        request: &RecallRequest<'_>,
    ) -> Result<RecallStream, ShibahamaError> {
        Ok(RecallStream::new(self.timeline(request)?))
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
        self.why_with_significance_policy(id, now, self.config.significance)
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

/// Tokio-compatible async API facade around the sync engine.
#[cfg(feature = "tokio")]
#[derive(Clone)]
pub struct AsyncShibahama<V> {
    inner: Arc<tokio::sync::Mutex<Shibahama<V>>>,
}

#[cfg(feature = "tokio")]
impl<V> AsyncShibahama<V>
where
    V: VectorIndex + Send + 'static,
{
    /// Wraps an existing sync engine in the async facade.
    #[must_use]
    pub fn from_sync(engine: Shibahama<V>) -> Self {
        Self {
            inner: Arc::new(tokio::sync::Mutex::new(engine)),
        }
    }

    /// Opens a Shibahama store with a caller-supplied vector index.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened or the blocking task fails.
    pub async fn open(path: impl AsRef<Path>, vector_index: V) -> Result<Self, ShibahamaError> {
        Self::open_with_config(path, vector_index, ShibahamaConfig::default()).await
    }

    /// Opens a Shibahama store with an explicit engine config.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened or the blocking task fails.
    pub async fn open_with_config(
        path: impl AsRef<Path>,
        vector_index: V,
        config: ShibahamaConfig,
    ) -> Result<Self, ShibahamaError> {
        let path = PathBuf::from(path.as_ref());

        tokio::task::spawn_blocking(move || {
            Shibahama::open_with_config(path, vector_index, config).map(Self::from_sync)
        })
        .await?
    }

    /// Returns this engine's active config.
    pub async fn config(&self) -> ShibahamaConfig {
        self.inner.lock().await.config()
    }

    /// Replaces this engine's active config.
    pub async fn set_config(&self, config: ShibahamaConfig) {
        self.inner.lock().await.set_config(config);
    }

    /// Builds an owned async recall request from this engine's recall defaults.
    pub async fn recall_request(
        &self,
        query_vector: impl Into<Vec<f32>>,
        top_k: usize,
        now: OffsetDateTime,
    ) -> AsyncRecallRequest {
        let config = self.config().await;
        AsyncRecallRequest::new(query_vector, top_k, now)
            .with_ranking(config.recall_ranking)
            .with_staleness(config.recall_staleness)
            .with_diversification(config.recall_diversification)
    }

    /// Writes a memory event without adding an embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when the write cannot be persisted or the blocking task fails.
    pub async fn write(&self, event: MemoryWriteEvent) -> Result<MemoryItem, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().write(event)).await?
    }

    /// Writes a memory event and indexes its embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when the vector cannot be indexed, the write cannot be persisted, or the
    /// blocking task fails.
    pub async fn write_with_embedding(
        &self,
        event: MemoryWriteEvent,
        embedding: WriteEmbedding<'_>,
    ) -> Result<MemoryItem, ShibahamaError> {
        let inner = Arc::clone(&self.inner);
        let embedding = AsyncWriteEmbedding::from(embedding);

        tokio::task::spawn_blocking(move || {
            inner
                .blocking_lock()
                .write_with_embedding(event, embedding.as_write_embedding())
        })
        .await?
    }

    /// Recalls current fact memories for an owned query embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, access recording, or the blocking task
    /// fails.
    pub async fn recall(
        &self,
        request: AsyncRecallRequest,
    ) -> Result<Vec<RecallCandidate>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || {
            let request = request.as_recall_request();

            inner.blocking_lock().recall(&request)
        })
        .await?
    }

    /// Recalls current fact memories and returns an owning iterator over ranked candidates.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, access recording, or the blocking task
    /// fails.
    pub async fn stream_recall(
        &self,
        request: AsyncRecallRequest,
    ) -> Result<RecallStream, ShibahamaError> {
        Ok(RecallStream::new(self.recall(request).await?))
    }

    /// Replays recalled memories as they were believed at `request.now`.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, or the blocking task fails.
    pub async fn timeline(
        &self,
        request: AsyncRecallRequest,
    ) -> Result<Vec<RecallCandidate>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || {
            let request = request.as_recall_request();

            inner.blocking_lock().timeline(&request)
        })
        .await?
    }

    /// Replays timeline recall and returns an owning iterator over ranked candidates.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, or the blocking task fails.
    pub async fn stream_timeline(
        &self,
        request: AsyncRecallRequest,
    ) -> Result<RecallStream, ShibahamaError> {
        Ok(RecallStream::new(self.timeline(request).await?))
    }

    /// Reinforces a memory with a usage outcome.
    ///
    /// # Errors
    ///
    /// Returns an error when the access event cannot be persisted or the blocking task fails.
    pub async fn reinforce(
        &self,
        id: MemoryId,
        outcome: AccessOutcome,
    ) -> Result<bool, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().reinforce(id, outcome)).await?
    }

    /// Returns a full explanation for the current memory state.
    ///
    /// # Errors
    ///
    /// Returns an error when the item, significance inputs, audit trail, or blocking task fails.
    pub async fn why(&self, id: MemoryId) -> Result<Option<WhyTrace>, ShibahamaError> {
        self.why_at(id, OffsetDateTime::now_utc()).await
    }

    /// Returns a full explanation for the memory state at `now`.
    ///
    /// # Errors
    ///
    /// Returns an error when the item, significance inputs, audit trail, or blocking task fails.
    pub async fn why_at(
        &self,
        id: MemoryId,
        now: OffsetDateTime,
    ) -> Result<Option<WhyTrace>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().why_at(id, now)).await?
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

    #[test]
    fn facade_errors_expose_stable_kind_code_and_action() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let event = MemoryWriteEvent::new(
            "bad embedding",
            Provenance::new(SourceKind::User, None, "api-test"),
            OffsetDateTime::UNIX_EPOCH,
            OffsetDateTime::UNIX_EPOCH,
        );

        let error = shibahama
            .write_with_embedding(
                event,
                WriteEmbedding {
                    vector: &[0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect_err("dimension mismatch should fail");

        assert_eq!(error.kind(), ShibahamaErrorKind::Vector);
        assert_eq!(error.code(), "SHIBA_VECTOR");
        assert_eq!(error.action(), ShibahamaErrorKind::Vector.action());
        assert!(error.to_string().contains("[SHIBA_VECTOR]"));
        assert!(
            error
                .to_string()
                .contains("action: verify embedding dimensionality")
        );
    }

    #[test]
    fn config_defaults_capture_decay_thresholds_and_tier_budget() {
        let config = ShibahamaConfig::default();
        let thirty_days = 30.0 * 24.0 * 60.0 * 60.0;

        assert!((config.significance.half_life_seconds - thirty_days).abs() < f64::EPSILON);
        assert!((config.significance.warm_threshold - 1.0).abs() < f64::EPSILON);
        assert!((config.significance.hot_threshold - 2.0).abs() < f64::EPSILON);
        assert!(
            (config.recall_staleness.load_bearing_significance_threshold - 2.0).abs()
                < f64::EPSILON
        );
        assert_eq!(config.tier_capacity.hot_capacity, None);
        assert_eq!(config.reconstruction_budget.max_revalidations_per_window, 8);
    }

    #[test]
    fn engine_config_seeds_recall_requests() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut config = ShibahamaConfig::default();
        config.significance.half_life_seconds = 60.0;
        config.recall_ranking.similarity_weight = 2.0;
        config.recall_staleness.load_bearing_significance_threshold = 3.0;
        config.recall_diversification.enabled = false;
        config.tier_capacity.hot_capacity = Some(64);
        let mut shibahama =
            Shibahama::open_with_config(file.path(), HnswVectorIndex::with_capacity(2, 8), config)
                .expect("api should open");
        let query = [0.0, 0.0];
        let request = shibahama.recall_request(&query, 3, OffsetDateTime::UNIX_EPOCH);

        assert!((shibahama.config().significance.half_life_seconds - 60.0).abs() < f64::EPSILON);
        assert!((request.ranking.similarity_weight - 2.0).abs() < f64::EPSILON);
        assert!((request.staleness.load_bearing_significance_threshold - 3.0).abs() < f64::EPSILON);
        assert!(!request.diversification.enabled);
        assert_eq!(shibahama.config().tier_capacity.hot_capacity, Some(64));

        shibahama.set_config(ShibahamaConfig::default());
        assert_eq!(shibahama.config().tier_capacity.hot_capacity, None);
    }

    #[test]
    fn streaming_recall_iterates_ranked_candidates() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let first = shibahama
            .write_with_embedding(
                MemoryWriteEvent::new(
                    "stream alpha",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    now,
                    now,
                ),
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("first write should work");
        shibahama
            .write_with_embedding(
                MemoryWriteEvent::new(
                    "stream beta",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    now,
                    now,
                ),
                WriteEmbedding {
                    vector: &[1.0, 1.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("second write should work");
        shibahama
            .write_with_embedding(
                MemoryWriteEvent::new(
                    "stream gamma",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    now,
                    now,
                ),
                WriteEmbedding {
                    vector: &[2.0, 2.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("third write should work");
        let query = [0.0, 0.0];
        let request = shibahama.recall_request(&query, 3, now);
        let mut stream = shibahama
            .stream_recall(&request)
            .expect("stream recall should work");

        assert_eq!(stream.remaining(), 3);
        assert_eq!(stream.next().expect("first candidate").id, first.id);
        assert_eq!(stream.remaining(), 2);
        assert_eq!(stream.by_ref().count(), 2);
        assert_eq!(stream.remaining(), 0);
        assert!(stream.next().is_none());
    }

    #[cfg(feature = "tokio")]
    #[tokio::test]
    async fn async_facade_write_recall_reinforce_why_and_stream_work() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let shibahama = AsyncShibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .await
            .expect("api should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let item = shibahama
            .write_with_embedding(
                MemoryWriteEvent::new(
                    "async facade memory",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    now,
                    now,
                ),
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .await
            .expect("write should work");
        let request = shibahama.recall_request(vec![0.0, 0.0], 1, now).await;
        let recalled = shibahama
            .recall(request.clone())
            .await
            .expect("recall should work");
        let timeline = shibahama
            .timeline(request.clone())
            .await
            .expect("timeline should work");
        let mut stream = shibahama
            .stream_recall(request)
            .await
            .expect("stream should work");

        assert_eq!(recalled[0].id, item.id);
        assert_eq!(timeline[0].id, item.id);
        assert_eq!(stream.remaining(), 1);
        assert_eq!(stream.next().expect("stream candidate").id, item.id);
        assert!(
            shibahama
                .reinforce(item.id, AccessOutcome::Cited)
                .await
                .expect("reinforce should work")
        );
        assert_eq!(
            shibahama
                .why_at(item.id, now)
                .await
                .expect("why should read")
                .expect("item should exist")
                .item
                .content,
            "async facade memory"
        );
    }

    #[cfg(feature = "tokio")]
    #[tokio::test]
    async fn async_recall_request_copies_supported_sync_request() {
        let query = [0.0, 0.0];
        let sync_request = RecallRequest::new(&query, 4, OffsetDateTime::UNIX_EPOCH)
            .include_cold()
            .include_instructions()
            .with_raw_query_context("hello");
        let async_request = AsyncRecallRequest::try_from_recall_request(&sync_request)
            .expect("request should copy");

        assert_eq!(async_request.query_vector, query);
        assert_eq!(async_request.top_k, 4);
        assert_eq!(async_request.raw_query_context.as_deref(), Some("hello"));
        assert!(async_request.include_cold);
        assert!(async_request.include_instructions);
    }
}
