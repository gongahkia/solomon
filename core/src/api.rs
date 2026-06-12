// SPDX-License-Identifier: MIT

//! Small public API facade.

use crate::anomaly::AnomalyConfig;
use crate::model::{AccessOutcome, CredenceTier, MemoryId, MemoryItem, Provenance, Tier};
use crate::reconstruction::{
    BackgroundReconstructionConfig, CorroborationDecision, CorroborationPolicy,
    CorroborationSignal, DefaultRevalidationHook, QuarantinedProposal, ReconstructionBudgetConfig,
    ReconstructionBudgetDenial, ReconstructionMode, ReconstructionTrigger, RevalidationAction,
    RevalidationHook, RevalidationSource, apply_reconstruction_budget, evaluate_corroboration,
    evaluate_reconstruction_gate, promote_corroborated_proposal, quarantine_proposal,
    triggers_from_recall,
};
use crate::retrieval::{
    RecallCandidate, RecallCandidateCurrency, RecallDiversificationConfig, RecallError,
    RecallRankingConfig, RecallRequest, RecallStalenessConfig, recall, timeline,
};
use crate::significance::{SignificanceBreakdown, SignificanceConfig};
use crate::storage::{
    EventRecord, IngestCredencePolicy, MemoryAuditEntry, MemoryWriteEvent,
    ReconstructionReplacementRecord, RedbMemoryStore, StorageError, TierCapacityConfig,
};
use crate::vector::{VectorIndex, VectorIndexError};
use std::collections::BTreeMap;
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
    /// Optional idle/background reconstruction planning.
    pub background_reconstruction: BackgroundReconstructionConfig,
    /// Default tier residency budgets.
    pub tier_capacity: TierCapacityConfig,
    /// Default source-kind to credence mapping used for writes without explicit credence.
    pub ingest_credence: IngestCredencePolicy,
    /// Policy for caller-requested forgetting/invalidation.
    pub forgetting: ForgettingConfig,
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
            .with_significance(self.significance)
            .with_staleness(self.recall_staleness)
            .with_diversification(self.recall_diversification)
    }
}

/// How the engine handles caller-requested forgetting.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ForgettingConfig {
    /// Forgetting behavior used by `Shibahama::invalidate`.
    pub mode: ForgettingMode,
}

/// Engine behavior for `invalidate` requests.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum ForgettingMode {
    /// Close `valid_to` and remove the memory's vector from default current recall.
    #[default]
    SoftInvalidate,
    /// Keep the memory valid and append a durable flag for explicit re-verification.
    FlagForReverification,
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

/// Status for one explicit reconstruction trigger.
#[derive(Clone, Debug, PartialEq)]
pub enum ExplicitReconstructionStatus {
    /// Trigger was blocked by the reconstruction budget.
    Deferred(ReconstructionBudgetDenial),
    /// Gate allowed the trigger, but the referenced memory no longer exists.
    MissingOriginal,
    /// Revalidation source produced no replacement observation.
    NoObservation,
    /// Replacement observation exists but remains quarantined pending corroboration.
    Quarantined,
    /// Corroborated replacement invalidated the superseded memory and was written.
    Applied,
}

/// Result for one trigger processed by explicit reconstruction.
#[derive(Clone, Debug, PartialEq)]
pub struct ExplicitReconstructionOutcome {
    /// Trigger considered by the loop.
    pub trigger: ReconstructionTrigger,
    /// Action planned for external revalidation, when the trigger was processed.
    pub action: Option<RevalidationAction>,
    /// Quarantined proposal, when a revalidation source produced a replacement observation.
    pub proposal: Option<QuarantinedProposal>,
    /// Corroboration decision for the proposal.
    pub corroboration: Option<CorroborationDecision>,
    /// Promoted replacement written to storage, when applied.
    pub replacement: Option<MemoryItem>,
    /// Event records produced by invalidate-not-delete plus replacement write.
    pub records: Option<ReconstructionReplacementRecord>,
    /// Final status.
    pub status: ExplicitReconstructionStatus,
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
    /// Significance policy used for lazy pre-rank refresh and surfaced-access updates.
    pub significance: SignificanceConfig,
    /// Policy for flagging load-bearing but possibly stale memories.
    pub staleness: RecallStalenessConfig,
    /// Policy for suppressing near-duplicate results.
    pub diversification: RecallDiversificationConfig,
    /// Optional maximum approximate context tokens to return.
    pub max_context_tokens: Option<usize>,
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
            significance: request.significance,
            staleness: request.staleness,
            diversification: request.diversification,
            max_context_tokens: request.max_context_tokens,
        }
    }

    /// Copies a borrowed sync recall request into an owned async request.
    ///
    /// # Errors
    ///
    /// Returns an error when the borrowed request uses callback-style sync hooks, which cannot
    /// safely cross the async blocking-task boundary.
    pub fn try_from_recall_request(request: &RecallRequest<'_>) -> Result<Self, ShibahamaError> {
        if request.related_memory_provider.is_some() {
            return Err(ShibahamaError::InvalidRequest(
                "async recall requests must own their data; related-memory providers are only supported by the sync API".to_owned(),
            ));
        }

        if request.sanitizing_gateway.is_some() {
            return Err(ShibahamaError::InvalidRequest(
                "async recall requests must own their data; sanitizing gateways are only supported by the sync API".to_owned(),
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
            significance: request.significance,
            staleness: request.staleness,
            diversification: request.diversification,
            max_context_tokens: request.max_context_tokens,
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

    /// Overrides the significance policy used by this request.
    #[must_use]
    pub const fn with_significance(mut self, significance: SignificanceConfig) -> Self {
        self.significance = significance;
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

    /// Limits the approximate number of whitespace tokens returned as recall context.
    #[must_use]
    pub const fn with_max_context_tokens(mut self, max_context_tokens: usize) -> Self {
        self.max_context_tokens = Some(max_context_tokens);
        self
    }

    fn as_recall_request(&self) -> RecallRequest<'_> {
        let mut request = RecallRequest::new(&self.query_vector, self.top_k, self.now);
        request.raw_query_context = self.raw_query_context.as_deref();
        request.include_cold = self.include_cold;
        request.include_instructions = self.include_instructions;
        request.ranking = self.ranking;
        request.significance = self.significance;
        request.staleness = self.staleness;
        request.diversification = self.diversification;
        request.max_context_tokens = self.max_context_tokens;

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
        let mut engine = Self {
            store: RedbMemoryStore::open(path)?,
            vector_index,
            config,
        };

        engine.hydrate_vector_index()?;

        Ok(engine)
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

    fn hydrate_vector_index(&mut self) -> Result<(), ShibahamaError> {
        for embedding in self.store.stored_embeddings()? {
            self.vector_index
                .add(embedding.memory_id, &embedding.vector)?;
        }

        Ok(())
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
        let (_, item) = self
            .store
            .write_event_with_policy(event, self.config.ingest_credence)?;

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
        let mut item = event.into_item_with_policy(self.config.ingest_credence);

        self.store.write_embedded(
            &mut item,
            &mut self.vector_index,
            embedding.vector,
            embedding.index_name,
            embedding.model,
            embedding.model_version,
        )?;

        Ok(item)
    }

    /// Soft-invalidates a memory at `valid_to` and removes its stored embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when invalidation cannot be persisted or the vector index cannot be
    /// updated.
    pub fn invalidate(
        &mut self,
        id: MemoryId,
        valid_to: OffsetDateTime,
    ) -> Result<bool, ShibahamaError> {
        match self.config.forgetting.mode {
            ForgettingMode::SoftInvalidate => Ok(self
                .store
                .soft_invalidate_with_vector(id, valid_to, &mut self.vector_index)?
                .is_some()),
            ForgettingMode::FlagForReverification => Ok(self
                .store
                .flag_for_reverification(id, valid_to, "forgetting-disabled".to_owned())?
                .is_some()),
        }
    }

    /// Returns all current materialized memory rows.
    ///
    /// # Errors
    ///
    /// Returns an error when current item state cannot be read.
    pub fn memory_items(&self) -> Result<Vec<MemoryItem>, ShibahamaError> {
        Ok(self.store.memory_items()?)
    }

    /// Returns all durable event-log records in sequence order.
    ///
    /// # Errors
    ///
    /// Returns an error when event-log records cannot be read.
    pub fn event_records(&self) -> Result<Vec<EventRecord>, ShibahamaError> {
        Ok(self.store.events()?)
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
        let mut request = *request;
        if request.significance == SignificanceConfig::default() {
            request.significance = self.config.significance;
        }

        Ok(recall(&self.store, &self.vector_index, &request)?)
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

    /// Runs the gated reconstruction loop for stale load-bearing recall candidates.
    ///
    /// Plain `recall` never calls this method or mutates validity. Callers must explicitly provide
    /// a revalidation source and corroboration signals before a replacement can leave quarantine.
    ///
    /// # Errors
    ///
    /// Returns an error when storage reads, budgeted replacement writes, or event replay fail.
    pub fn reconstruct_from_recall<S>(
        &self,
        candidates: &[RecallCandidate],
        source: &S,
        corroboration_signals: &[(MemoryId, Vec<CorroborationSignal>)],
        now: OffsetDateTime,
    ) -> Result<Vec<ExplicitReconstructionOutcome>, ShibahamaError>
    where
        S: RevalidationSource,
    {
        let triggers = triggers_from_recall(candidates);
        let gate =
            evaluate_reconstruction_gate(&triggers, ReconstructionMode::ExplicitRevalidation);

        if !gate.may_run {
            return Ok(Vec::new());
        }

        let budget = apply_reconstruction_budget(
            &gate.triggers,
            &[],
            &[],
            now,
            self.config.reconstruction_budget,
        );
        let signals_by_memory = corroboration_signals
            .iter()
            .map(|(id, signals)| (*id, signals.as_slice()))
            .collect::<BTreeMap<_, _>>();
        let candidates_by_memory = candidates
            .iter()
            .map(|candidate| (candidate.id, candidate))
            .collect::<BTreeMap<_, _>>();
        let hook = DefaultRevalidationHook;
        let policy = CorroborationPolicy::default();
        let mut outcomes = Vec::new();

        for deferred in budget.deferred {
            outcomes.push(ExplicitReconstructionOutcome {
                trigger: deferred.trigger,
                action: None,
                proposal: None,
                corroboration: None,
                replacement: None,
                records: None,
                status: ExplicitReconstructionStatus::Deferred(deferred.reason),
            });
        }

        for trigger in budget.allowed {
            let Some(candidate) = candidates_by_memory.get(&trigger.memory_id) else {
                outcomes.push(ExplicitReconstructionOutcome {
                    trigger,
                    action: None,
                    proposal: None,
                    corroboration: None,
                    replacement: None,
                    records: None,
                    status: ExplicitReconstructionStatus::MissingOriginal,
                });
                continue;
            };

            let Some(original) = self.store.get(trigger.memory_id)? else {
                outcomes.push(ExplicitReconstructionOutcome {
                    trigger,
                    action: None,
                    proposal: None,
                    corroboration: None,
                    replacement: None,
                    records: None,
                    status: ExplicitReconstructionStatus::MissingOriginal,
                });
                continue;
            };

            let action = hook.plan_revalidation(&trigger, &candidate.provenance);
            let Some(event) = source.revalidate(&action, &original, now) else {
                outcomes.push(ExplicitReconstructionOutcome {
                    trigger,
                    action: Some(action),
                    proposal: None,
                    corroboration: None,
                    replacement: None,
                    records: None,
                    status: ExplicitReconstructionStatus::NoObservation,
                });
                continue;
            };

            let proposal = quarantine_proposal(
                event.into_item_with_policy(self.config.ingest_credence),
                trigger.memory_id,
            );
            let signals = signals_by_memory
                .get(&trigger.memory_id)
                .copied()
                .unwrap_or(&[]);
            let corroboration = evaluate_corroboration(signals, policy);
            let Some(replacement) = promote_corroborated_proposal(&proposal, signals, policy)
            else {
                outcomes.push(ExplicitReconstructionOutcome {
                    trigger,
                    action: Some(action),
                    proposal: Some(proposal),
                    corroboration: Some(corroboration),
                    replacement: None,
                    records: None,
                    status: ExplicitReconstructionStatus::Quarantined,
                });
                continue;
            };

            let records = self
                .store
                .insert_reconstruction_replacement(
                    trigger.memory_id,
                    &replacement,
                    replacement.timestamps.valid_from,
                )?
                .ok_or_else(|| {
                    ShibahamaError::InvalidRequest(format!(
                        "memory {} disappeared before reconstruction replacement",
                        trigger.memory_id
                    ))
                })?;

            outcomes.push(ExplicitReconstructionOutcome {
                trigger,
                action: Some(action),
                proposal: Some(proposal),
                corroboration: Some(corroboration),
                replacement: Some(replacement),
                records: Some(records),
                status: ExplicitReconstructionStatus::Applied,
            });
        }

        Ok(outcomes)
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
        let mut request = *request;
        if request.significance == SignificanceConfig::default() {
            request.significance = self.config.significance;
        }

        Ok(timeline(&self.store, &self.vector_index, &request)?)
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
        Ok(self
            .store
            .record_access_with_policy(
                id,
                crate::model::AccessEvent::new(OffsetDateTime::now_utc(), None, outcome),
                &self.config.significance,
            )?
            .is_some())
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
            .with_significance(config.significance)
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

    /// Soft-invalidates a memory at `valid_to` and removes its stored embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when invalidation cannot be persisted, the vector index cannot be updated,
    /// or the blocking task fails.
    pub async fn invalidate(
        &self,
        id: MemoryId,
        valid_to: OffsetDateTime,
    ) -> Result<bool, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().invalidate(id, valid_to)).await?
    }

    /// Returns all current materialized memory rows.
    ///
    /// # Errors
    ///
    /// Returns an error when current item state cannot be read or the blocking task fails.
    pub async fn memory_items(&self) -> Result<Vec<MemoryItem>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().memory_items()).await?
    }

    /// Returns all durable event-log records in sequence order.
    ///
    /// # Errors
    ///
    /// Returns an error when event-log records cannot be read or the blocking task fails.
    pub async fn event_records(&self) -> Result<Vec<EventRecord>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().event_records()).await?
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
    #[cfg(feature = "tokio")]
    use crate::read_safety::DefaultSanitizingGateway;
    use crate::retrieval::{RecallCandidateCurrency, RecallRequest};
    use crate::storage::MemoryEvent;
    use crate::vector::HnswVectorIndex;
    use tempfile::NamedTempFile;
    use time::{Duration, OffsetDateTime};

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
        assert!((why.significance.base_score - why.item.base_significance).abs() < f64::EPSILON);
        assert_eq!(why.audit_trail.len(), why.tier.audit.len());
        assert!(why.audit_trail.len() >= 2);
    }

    #[test]
    fn explicit_reconstruction_is_gated_quarantined_and_applied_after_corroboration() {
        struct StaticRevalidator {
            event: MemoryWriteEvent,
        }

        impl RevalidationSource for StaticRevalidator {
            fn revalidate(
                &self,
                _action: &RevalidationAction,
                _original: &MemoryItem,
                _now: OffsetDateTime,
            ) -> Option<MemoryWriteEvent> {
                Some(self.event.clone())
            }
        }

        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let ingested_at = OffsetDateTime::UNIX_EPOCH;
        let now = ingested_at + Duration::days(90);
        let mut event = MemoryWriteEvent::new(
            "old API endpoint is /v1",
            Provenance::new(SourceKind::File, Some("docs://api".to_owned()), "api-test"),
            ingested_at,
            ingested_at,
        );
        event.significance = 16.0;
        event.tier = Tier::Warm;
        event.credence_floor = Tier::Warm;
        let original = shibahama
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
        let request = RecallRequest::new(&query, 1, now);
        let recalled = shibahama.recall(&request).expect("recall should work");

        assert_eq!(recalled.len(), 1);
        assert!(recalled[0].load_bearing_possibly_stale);
        assert!(
            !shibahama
                .event_records()
                .expect("events should read")
                .iter()
                .any(|record| matches!(
                    record.event,
                    MemoryEvent::MemoryInvalidated { .. }
                        | MemoryEvent::ReconstructionApplied { .. }
                ))
        );

        let mut replacement_event = MemoryWriteEvent::new(
            "current API endpoint is /v2",
            Provenance::new(SourceKind::File, Some("docs://api".to_owned()), "api-test"),
            now,
            now,
        );
        replacement_event.significance = 16.0;
        replacement_event.tier = Tier::Warm;
        replacement_event.credence_floor = Tier::Warm;
        let revalidator = StaticRevalidator {
            event: replacement_event,
        };
        let outcomes = shibahama
            .reconstruct_from_recall(
                &recalled,
                &revalidator,
                &[(original.id, vec![CorroborationSignal::HumanConfirmed])],
                now,
            )
            .expect("reconstruction should run");

        assert_eq!(outcomes.len(), 1);
        assert!(matches!(
            outcomes[0].status,
            ExplicitReconstructionStatus::Applied
        ));
        assert_eq!(
            outcomes[0]
                .proposal
                .as_ref()
                .expect("proposal should exist")
                .item
                .credence,
            CredenceTier::Unverified
        );
        let replacement = outcomes[0]
            .replacement
            .as_ref()
            .expect("replacement should be promoted");
        assert_eq!(replacement.content, "current API endpoint is /v2");
        assert_eq!(replacement.credence, CredenceTier::FirmAuthoritative);

        let rows = shibahama.memory_items().expect("rows should read");
        let superseded = rows
            .iter()
            .find(|item| item.id == original.id)
            .expect("old row should remain");
        assert_eq!(superseded.timestamps.valid_to, Some(now));
        assert!(
            rows.iter()
                .any(|item| item.content == "current API endpoint is /v2")
        );
        assert!(
            shibahama
                .event_records()
                .expect("events should read")
                .iter()
                .any(|record| matches!(record.event, MemoryEvent::ReconstructionApplied { .. }))
        );
    }

    #[test]
    fn facade_hydrates_embeddings_after_reopen() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let event = MemoryWriteEvent::new(
            "reopened memory",
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
        drop(shibahama);

        let reopened = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should reopen and hydrate embeddings");
        let query = [0.0, 0.0];
        let request = RecallRequest::new(&query, 1, OffsetDateTime::UNIX_EPOCH);
        let recalled = reopened.recall(&request).expect("recall should work");

        assert_eq!(recalled[0].id, item.id);
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
    fn forgetting_config_flags_for_reverification_without_invalidating() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut config = ShibahamaConfig::default();
        config.forgetting.mode = ForgettingMode::FlagForReverification;
        let mut shibahama =
            Shibahama::open_with_config(file.path(), HnswVectorIndex::with_capacity(2, 8), config)
                .expect("api should open");
        let valid_from = OffsetDateTime::UNIX_EPOCH;
        let flag_at = valid_from + time::Duration::days(1);
        let item = shibahama
            .write_with_embedding(
                MemoryWriteEvent::new(
                    "keep current but reverify",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    valid_from,
                    valid_from,
                ),
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("write should work");

        assert!(
            shibahama
                .invalidate(item.id, flag_at)
                .expect("flag should work")
        );

        let why = shibahama
            .why_at(item.id, flag_at)
            .expect("why should read")
            .expect("item should exist");
        let query = [0.0, 0.0];
        let recalled = shibahama
            .recall(&RecallRequest::new(&query, 1, flag_at))
            .expect("recall should keep flagged memory current");
        let event_records = shibahama
            .event_records()
            .expect("events should read after flag");

        assert_eq!(why.currency.state, RecallCandidateCurrency::Current);
        assert_eq!(why.currency.valid_to, None);
        assert_eq!(recalled[0].id, item.id);
        assert!(event_records.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::ReverificationFlagged {
                    id,
                    flagged_at,
                    reason
                } if *id == item.id
                    && *flagged_at == flag_at
                    && reason == "forgetting-disabled"
            )
        }));
    }

    #[test]
    fn engine_config_swaps_ingest_credence_policy() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut config = ShibahamaConfig::default();
        config.ingest_credence.web = CredenceTier::VerifiedSource;
        config.ingest_credence.user = CredenceTier::ModelInferred;
        let shibahama =
            Shibahama::open_with_config(file.path(), HnswVectorIndex::with_capacity(2, 8), config)
                .expect("api should open");
        let web_item = shibahama
            .write(MemoryWriteEvent::new(
                "domain-vetted web source",
                Provenance::new(
                    SourceKind::Web,
                    Some("https://example.test".to_owned()),
                    "api-test",
                ),
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ))
            .expect("write should use configured credence policy");
        let explicit_item = shibahama
            .write(MemoryWriteEvent::with_explicit_credence(
                "explicit caller override",
                Provenance::new(SourceKind::User, None, "api-test"),
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
                Tier::Cold,
                CredenceTier::Unverified,
                Tier::Cold,
            ))
            .expect("explicit credence write should work");

        assert_eq!(web_item.credence, CredenceTier::VerifiedSource);
        assert_eq!(explicit_item.credence, CredenceTier::Unverified);
        assert_eq!(
            shibahama.config().ingest_credence.user,
            CredenceTier::ModelInferred
        );
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
        assert!(!config.background_reconstruction.validate_on_idle);
        assert_eq!(config.ingest_credence.web, CredenceTier::Unverified);
        assert_eq!(config.forgetting.mode, ForgettingMode::SoftInvalidate);
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
        config.background_reconstruction.validate_on_idle = true;
        config.ingest_credence.web = CredenceTier::VerifiedSource;
        config.forgetting.mode = ForgettingMode::FlagForReverification;
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
        assert!(
            shibahama
                .config()
                .background_reconstruction
                .validate_on_idle
        );
        assert_eq!(
            shibahama.config().ingest_credence.web,
            CredenceTier::VerifiedSource
        );
        assert_eq!(
            shibahama.config().forgetting.mode,
            ForgettingMode::FlagForReverification
        );

        shibahama.set_config(ShibahamaConfig::default());
        assert_eq!(shibahama.config().tier_capacity.hot_capacity, None);
        assert!(
            !shibahama
                .config()
                .background_reconstruction
                .validate_on_idle
        );
        assert_eq!(
            shibahama.config().ingest_credence.web,
            CredenceTier::Unverified
        );
        assert_eq!(
            shibahama.config().forgetting.mode,
            ForgettingMode::SoftInvalidate
        );
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
            .with_raw_query_context("hello")
            .with_max_context_tokens(8);
        let async_request = AsyncRecallRequest::try_from_recall_request(&sync_request)
            .expect("request should copy");

        assert_eq!(async_request.query_vector, query);
        assert_eq!(async_request.top_k, 4);
        assert_eq!(async_request.raw_query_context.as_deref(), Some("hello"));
        assert!(async_request.include_cold);
        assert!(async_request.include_instructions);
        assert_eq!(async_request.max_context_tokens, Some(8));

        let gateway = DefaultSanitizingGateway;
        let unsupported = RecallRequest::new(&query, 4, OffsetDateTime::UNIX_EPOCH)
            .with_sanitizing_gateway(&gateway);
        let error = AsyncRecallRequest::try_from_recall_request(&unsupported)
            .expect_err("sync sanitizing gateway should be rejected");

        assert!(matches!(
            error,
            ShibahamaError::InvalidRequest(message)
                if message.contains("sanitizing gateways")
        ));
    }
}
