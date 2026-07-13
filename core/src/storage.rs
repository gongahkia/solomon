// SPDX-License-Identifier: MIT

//! Durable storage primitives for Shibahama.

use crate::anomaly::{
    AnomalyConfig, AnomalyFlag, detect_contradiction_bursts, inspect_suspicious_provenance,
};
use crate::capture_worker::AutomaticCaptureAuditRecord;
use crate::encryption::{EncryptionAtRest, EncryptionError, NoopEncryption};
use crate::model::{
    AccessEvent, AccessOutcome, CURRENT_MEMORY_SCHEMA_VERSION, CompactionRef, ConsolidationAction,
    ConsolidationWhy, CredenceTier, EmbeddingRef, Entity, EntityId, HumanSignal, HumanSignalAction,
    MemoryId, MemoryItem, MemoryKind, MemoryScope, Provenance, Relation, RelationId,
    ScopeAuthorizationAction, ScopePromotionRef, ScopeVisibility, SourceKind, TemporalBounds, Tier,
};
use crate::observability::ObservabilityRecord;
use crate::policy::PolicyAuditRecord;
use crate::review::{
    ReviewCandidate, ReviewCandidateId, ReviewDecision, ReviewError, ReviewQueueItem,
};
use crate::significance::{SignificanceBreakdown, SignificanceConfig, SignificanceFunction};
use crate::vector::{VectorIndex, VectorIndexError};
use lz4_flex::{compress_prepend_size, decompress_size_prepended};
use redb::{
    Database, Durability, ReadableDatabase, ReadableTable, ReadableTableMetadata, Table,
    TableDefinition,
};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fs;
use std::path::Path;
use std::sync::Arc;
use thiserror::Error;
use time::OffsetDateTime;

const EVENT_LOG_TABLE: TableDefinition<u64, &[u8]> = TableDefinition::new("event_log");
const MEMORY_ITEMS_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("memory_items");
const MEMORY_SCOPE_INDEX_TABLE: TableDefinition<&str, &[u8]> =
    TableDefinition::new("memory_scope_index");
const EMBEDDINGS_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("embeddings");
const COLD_CONTENT_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("cold_content");
const GRAPH_ENTITIES_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("graph_entities");
const GRAPH_RELATIONS_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("graph_relations");
const LZ4_SIZE_PREPENDED: &str = "lz4-size-prepended";

#[derive(Clone, Copy)]
enum StorageTableName {
    EventLog,
    MemoryItems,
    MemoryScopeIndex,
    Embeddings,
    ColdContent,
    GraphEntities,
    GraphRelations,
}

impl StorageTableName {
    const fn as_str(self) -> &'static str {
        match self {
            Self::EventLog => "event_log",
            Self::MemoryItems => "memory_items",
            Self::MemoryScopeIndex => "memory_scope_index",
            Self::Embeddings => "embeddings",
            Self::ColdContent => "cold_content",
            Self::GraphEntities => "graph_entities",
            Self::GraphRelations => "graph_relations",
        }
    }
}

/// Error returned by storage backends.
#[derive(Debug, Error)]
pub enum StorageError {
    /// Embedded database operation failed.
    #[error("embedded storage operation failed: {0}")]
    Embedded(String),
    /// Event or item serialization failed.
    #[error("serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
    /// Compression or decompression failed.
    #[error("compression failed: {0}")]
    Compression(String),
    /// Encryption or decryption failed.
    #[error(transparent)]
    Encryption(#[from] EncryptionError),
    /// File I/O failed.
    #[error("file I/O failed: {0}")]
    Io(#[from] std::io::Error),
    /// Vector index operation failed.
    #[error(transparent)]
    Vector(#[from] VectorIndexError),
    /// Durable store invariants were violated.
    #[error("storage invariant violated: {0}")]
    InvariantViolation(String),
    /// A persisted record uses an unsupported schema version.
    #[error("unsupported store format in {record}: expected schema v{expected}, found v{found}")]
    SchemaVersionMismatch {
        /// Persisted record label.
        record: String,
        /// Schema version supported by this crate.
        expected: u16,
        /// Schema version decoded from storage.
        found: u16,
    },
    /// Snapshot export would write decrypted data from an encrypted store.
    #[error("plaintext snapshot export is disabled for encrypted stores")]
    EncryptedSnapshotExportDisabled,
}

/// Deterministic storage-write fault point for failure testing.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StorageFaultStage {
    /// After vector insertion and before the durable write transaction starts.
    EmbeddedWrite,
}

/// Injects a deterministic storage failure into an explicit write boundary.
pub trait StorageFaultInjector {
    /// Returns an error to fail the requested stage.
    ///
    /// # Errors
    ///
    /// Returns the deterministic storage error configured for `stage`.
    fn check(&self, stage: StorageFaultStage) -> Result<(), StorageError>;
}

/// Append-only event describing a durable memory-state change.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub enum MemoryEvent {
    /// A memory item was written.
    MemoryWritten {
        /// Full item state at write time.
        item: Box<MemoryItem>,
    },
    /// Repository-local memory was copied into an approved team scope.
    MemoryScopePromoted {
        /// Immutable local source id.
        source_id: MemoryId,
        /// New team-scoped memory id.
        promoted_id: MemoryId,
        /// Principal that approved promotion.
        actor: String,
        /// Human-readable approval rationale.
        rationale: String,
        /// Approval timestamp.
        promoted_at: OffsetDateTime,
    },
    /// Host policy denied a requested repository-to-team promotion.
    ScopeAuthorizationDenied {
        /// Principal requesting the operation.
        principal: String,
        /// Source repository scope, without a memory identifier or content.
        source_scope: MemoryScope,
        /// Requested team target scope.
        target_scope: MemoryScope,
        /// Requested scope-crossing operation.
        action: ScopeAuthorizationAction,
        /// Time the host policy denied the request.
        denied_at: OffsetDateTime,
    },
    /// Content-free audit record for a capture or recall policy decision.
    PolicyDecisionRecorded {
        /// Evaluated policy metadata and outcome.
        record: PolicyAuditRecord,
    },
    /// An extraction candidate and bounded evidence were queued for explicit review.
    ReviewCandidateQueued {
        /// Candidate awaiting review.
        candidate: ReviewCandidate,
    },
    /// A human or attributable agent recorded a review decision.
    ReviewDecisionRecorded {
        /// Durable review decision metadata.
        decision: ReviewDecision,
    },
    /// Content-free audit record for one automatic capture step.
    AutomaticCaptureRecorded {
        /// Policy and evidence provenance metadata.
        record: AutomaticCaptureAuditRecord,
    },
    /// Content-free provider or policy observability record.
    ObservabilityRecorded {
        /// Redaction-safe operational metadata.
        record: ObservabilityRecord,
    },
    /// A memory item was soft-invalidated.
    MemoryInvalidated {
        /// Invalidated memory id.
        id: MemoryId,
        /// Timestamp that closes the valid-time interval.
        valid_to: OffsetDateTime,
    },
    /// A memory was kept current but flagged for explicit re-verification.
    ReverificationFlagged {
        /// Memory id requiring re-verification.
        id: MemoryId,
        /// Timestamp or domain instant that caused the flag.
        flagged_at: OffsetDateTime,
        /// Short machine-readable reason for the flag.
        reason: String,
    },
    /// A usage event was recorded for a memory.
    AccessRecorded {
        /// Accessed memory id.
        id: MemoryId,
        /// Access signal.
        event: AccessEvent,
    },
    /// A memory changed accessibility tier.
    TierChanged {
        /// Memory id.
        id: MemoryId,
        /// Previous tier.
        from: Tier,
        /// New tier.
        to: Tier,
        /// Why the tier changed.
        #[serde(default)]
        cause: TierChangeCause,
    },
    /// A cold memory's content was moved to compressed storage.
    ContentCompacted {
        /// Memory id.
        id: MemoryId,
        /// Pointer to compressed content.
        pointer: CompactionRef,
    },
    /// A reconstructed memory replaced a superseded memory without overwriting history.
    ReconstructionApplied {
        /// Superseded memory id whose valid-time interval was closed.
        superseded_id: MemoryId,
        /// Replacement memory id written as a separate row.
        replacement_id: MemoryId,
        /// Timestamp that closes the superseded memory's valid-time interval.
        valid_to: OffsetDateTime,
    },
    /// An offline consolidation pass made a legible decision.
    ConsolidationDecision {
        /// Stable pass identifier.
        pass_id: String,
        /// Decision action.
        action: ConsolidationAction,
        /// Input memories considered by the decision.
        input_ids: Vec<MemoryId>,
        /// New memory produced by a merge decision, when applicable.
        output_id: Option<MemoryId>,
        /// Previous tier for tier-transition decisions.
        tier_from: Option<Tier>,
        /// New tier for tier-transition decisions.
        tier_to: Option<Tier>,
        /// Explainable usage/safety trace behind the decision.
        why: ConsolidationWhy,
    },
    /// A human supplied a direct deterministic signal for a memory.
    HumanSignalRecorded {
        /// Append-only human signal payload.
        signal: HumanSignal,
    },
}

/// Cause attached to tier-transition events.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum TierChangeCause {
    /// Cause was not recorded by an older event.
    #[default]
    Unknown,
    /// Tier changed because access reinforced significance.
    AccessReinforcement,
    /// Tier changed because significance was refreshed lazily.
    SignificanceRefresh,
    /// Tier changed because a tier capacity policy demoted the item.
    CapacityEnforcement,
    /// Tier changed because an offline consolidation pass applied usage evidence.
    ConsolidationPass,
}

/// Cause shown in an item's audit trail.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryAuditCause {
    /// Initial item write assigned the value.
    InitialWrite,
    /// A direct write changed the value for an already-known id.
    DirectWrite,
    /// Tier changed because access reinforced significance.
    AccessReinforcement,
    /// Tier changed because significance was refreshed lazily.
    SignificanceRefresh,
    /// Tier changed because a tier capacity policy demoted the item.
    CapacityEnforcement,
    /// Tier changed because an offline consolidation pass applied usage evidence.
    ConsolidationPass,
    /// A human challenge, affirmation, correction, pin, or unpin changed state.
    HumanSignal,
    /// Cause was not recorded by an older event.
    Unknown,
}

impl From<TierChangeCause> for MemoryAuditCause {
    fn from(value: TierChangeCause) -> Self {
        match value {
            TierChangeCause::Unknown => Self::Unknown,
            TierChangeCause::AccessReinforcement => Self::AccessReinforcement,
            TierChangeCause::SignificanceRefresh => Self::SignificanceRefresh,
            TierChangeCause::CapacityEnforcement => Self::CapacityEnforcement,
            TierChangeCause::ConsolidationPass => Self::ConsolidationPass,
        }
    }
}

/// Audited memory field change.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryAuditChange {
    /// Credence changed.
    Credence {
        /// Previous credence, or `None` for initial assignment.
        from: Option<CredenceTier>,
        /// New credence.
        to: CredenceTier,
    },
    /// Accessibility tier changed.
    Tier {
        /// Previous tier, or `None` for initial assignment.
        from: Option<Tier>,
        /// New tier.
        to: Tier,
    },
    /// Credence floor changed.
    CredenceFloor {
        /// Previous floor, or `None` for initial assignment.
        from: Option<Tier>,
        /// New floor.
        to: Tier,
    },
}

/// One per-item audit-trail entry.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryAuditEntry {
    /// Event-log sequence that produced this audit entry.
    pub sequence: u64,
    /// Time the source event was recorded.
    pub recorded_at: OffsetDateTime,
    /// Memory this audit entry describes.
    pub memory_id: MemoryId,
    /// Durable scope resolved from the materialized memory row.
    pub scope: MemoryScope,
    /// Field change.
    pub change: MemoryAuditChange,
    /// Why the change happened.
    pub cause: MemoryAuditCause,
}

/// Durable event-log record with a monotonic sequence number.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct EventRecord {
    /// Monotonic event sequence.
    pub sequence: u64,
    /// Time the event was appended to storage.
    pub recorded_at: OffsetDateTime,
    /// Stored event payload.
    pub event: MemoryEvent,
}

/// Summary of startup recovery validation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RecoveryReport {
    /// Number of event-log records decoded successfully.
    pub event_count: usize,
    /// Number of materialized memory items decoded successfully.
    pub materialized_item_count: usize,
}

/// Summary returned after checking that memory-state paths have not deleted durable data.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NeverDeleteInvariantReport {
    /// Number of event-log records that remain replayable.
    pub event_count: usize,
    /// Number of currently materialized memory rows.
    pub materialized_item_count: usize,
    /// Number of distinct memory ids with source write events.
    pub written_item_count: usize,
    /// Number of compressed cold-content payloads still present.
    pub compacted_content_count: usize,
}

/// Events produced by a reconstruction replacement.
#[derive(Clone, Debug, PartialEq)]
pub struct ReconstructionReplacementRecord {
    /// Event closing the superseded memory's valid-time interval.
    pub invalidation: EventRecord,
    /// Event writing the replacement memory as a separate row.
    pub replacement_write: EventRecord,
    /// Reconstruction marker event for replay/debugger consumers.
    pub reconstruction: EventRecord,
}

/// Records created by promoting a repository-local memory into a team scope.
#[derive(Clone, Debug, PartialEq)]
pub struct ScopePromotionRecord {
    /// Immutable copied memory in the target team scope.
    pub promoted: MemoryItem,
    /// Event that materialized the copied memory.
    pub memory_write: EventRecord,
    /// Event linking the source and promoted rows.
    pub promotion: EventRecord,
}

/// Events produced by applying one consolidation decision.
#[derive(Clone, Debug, PartialEq)]
pub struct ConsolidationDecisionRecord {
    /// Event writing a synthesized memory for merge decisions.
    pub memory_write: Option<EventRecord>,
    /// Event recording a tier transition for promote/demote decisions.
    pub tier_change: Option<EventRecord>,
    /// Event flagging a memory for explicit re-verification.
    pub revalidation_flag: Option<EventRecord>,
    /// Legible consolidation marker with the why trace.
    pub decision: EventRecord,
}

/// Events produced by one human signal API call.
#[derive(Clone, Debug, PartialEq)]
pub struct HumanSignalRecord {
    /// Optional usage event emitted by challenge/affirm signals.
    pub access: Option<EventRecord>,
    /// Optional re-verification flag emitted by challenge signals.
    pub revalidation_flag: Option<EventRecord>,
    /// Append-only human signal audit event.
    pub signal: EventRecord,
}

struct HumanCredenceSignalInput {
    id: MemoryId,
    action: HumanSignalAction,
    actor: String,
    reason: String,
    timestamp: OffsetDateTime,
    outcome: AccessOutcome,
}

struct HumanCredenceEventSet {
    item: MemoryItem,
    access: EventRecord,
    revalidation_flag: Option<EventRecord>,
    signal: EventRecord,
}

/// Tier residency limits for materialized memory state.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct TierCapacityConfig {
    /// Maximum number of hot-tier memories to retain, or `None` for no hot-tier limit.
    pub hot_capacity: Option<usize>,
}

/// Detected conflict between an existing graph relation and a proposed relation.
#[derive(Clone, Debug, PartialEq)]
pub struct RelationContradiction {
    /// Active relation already believed by the graph.
    pub existing: Relation,
    /// Proposed relation that conflicts with the existing one.
    pub proposed: Relation,
}

/// Request for typed graph traversal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GraphTraversalRequest {
    /// Entity where traversal starts.
    pub start_entity: EntityId,
    /// Maximum number of relation hops to traverse.
    pub max_hops: usize,
    /// Optional relation-type allow-list.
    pub relation_types: BTreeSet<String>,
    /// Optional bi-temporal instant used to filter relation edges.
    pub as_of: Option<OffsetDateTime>,
    /// Optional exact repository/team visibility boundary.
    pub scope: Option<MemoryScope>,
}

impl GraphTraversalRequest {
    /// Creates a traversal request from `start_entity`.
    #[must_use]
    pub fn new(start_entity: EntityId, max_hops: usize) -> Self {
        Self {
            start_entity,
            max_hops,
            relation_types: BTreeSet::new(),
            as_of: None,
            scope: None,
        }
    }

    /// Restricts traversal to relation types in `relation_types`.
    #[must_use]
    pub fn with_relation_types(mut self, relation_types: impl IntoIterator<Item = String>) -> Self {
        self.relation_types = relation_types.into_iter().collect();
        self
    }

    /// Applies bi-temporal filtering to traversed relations.
    #[must_use]
    pub const fn as_of(mut self, as_of: OffsetDateTime) -> Self {
        self.as_of = Some(as_of);
        self
    }

    /// Restricts traversal to one exact repository/team visibility boundary.
    #[must_use]
    pub fn with_scope(mut self, scope: MemoryScope) -> Self {
        self.scope = Some(scope);
        self
    }
}

/// Entities and relations discovered by graph traversal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GraphTraversalResult {
    /// Entities reached by traversal, including the start entity when present.
    pub entities: Vec<Entity>,
    /// Relations followed during traversal.
    pub relations: Vec<Relation>,
}

/// Entities and relations believed at a point in bi-temporal graph time.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GraphSnapshot {
    /// Instant used for valid-time and ingestion-time reconstruction.
    pub as_of: OffsetDateTime,
    /// Entities believed at `as_of`.
    pub entities: Vec<Entity>,
    /// Relations believed at `as_of`, with both endpoints present in `entities`.
    pub relations: Vec<Relation>,
}

/// Request for extracting a scoped subgraph.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SubgraphRequest {
    /// Entity attribute key used as the scope discriminator.
    pub scope_key: String,
    /// Entity attribute value used as the scope discriminator.
    pub scope_value: String,
    /// Optional bi-temporal instant used to filter relation edges.
    pub as_of: Option<OffsetDateTime>,
}

impl SubgraphRequest {
    /// Creates a subgraph request for an entity attribute scope.
    #[must_use]
    pub fn new(scope_key: impl Into<String>, scope_value: impl Into<String>) -> Self {
        Self {
            scope_key: scope_key.into(),
            scope_value: scope_value.into(),
            as_of: None,
        }
    }

    /// Applies bi-temporal filtering to extracted relations.
    #[must_use]
    pub const fn as_of(mut self, as_of: OffsetDateTime) -> Self {
        self.as_of = Some(as_of);
        self
    }
}

/// Full durable store snapshot.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct StoreSnapshot {
    /// Snapshot schema version.
    pub schema_version: u16,
    /// Exact scope when this is a filtered export; absent for a local full-store snapshot.
    #[serde(default)]
    pub scope: Option<MemoryScope>,
    /// Event-log records.
    pub events: Vec<EventRecord>,
    /// Current materialized memory items.
    pub materialized_items: Vec<MemoryItem>,
    /// Persisted embedding vectors used to hydrate local vector indexes.
    #[serde(default)]
    pub embeddings: Vec<StoredEmbedding>,
    /// Compressed cold-content payloads.
    pub cold_contents: Vec<ColdContentRecord>,
    /// Current graph entities.
    pub graph_entities: Vec<Entity>,
    /// Current graph relations.
    pub graph_relations: Vec<Relation>,
}

/// Persisted embedding vector for local index hydration.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct StoredEmbedding {
    /// Memory id this embedding belongs to.
    pub memory_id: MemoryId,
    /// Scope inherited atomically from the embedding's memory.
    pub scope: MemoryScope,
    /// Embedding vector.
    pub vector: Vec<f32>,
    /// Logical vector index name.
    pub index_name: String,
    /// Embedding model identifier.
    pub model: String,
    /// Embedding model version identifier.
    pub model_version: String,
}

/// Compressed cold-content payload included in a snapshot.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ColdContentRecord {
    /// Storage key referenced by `CompactionRef`.
    pub storage_key: String,
    /// Scope inherited atomically from the compacted memory.
    pub scope: MemoryScope,
    /// Compressed payload bytes.
    pub bytes: Vec<u8>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
struct StoredColdContent {
    scope: MemoryScope,
    compressed: Vec<u8>,
}

/// Caller-supplied memory write event before it is assigned an id and materialized.
#[derive(Clone, Debug, PartialEq)]
pub struct MemoryWriteEvent {
    /// Stored memory content.
    pub content: String,
    /// Repository/team visibility boundary assigned to the materialized memory.
    pub scope: MemoryScope,
    /// Whether this write is a fact/observation or instruction/directive.
    pub kind: MemoryKind,
    /// Mandatory provenance for the observation.
    pub provenance: Provenance,
    /// Start of the interval where the fact is claimed valid.
    pub valid_from: OffsetDateTime,
    /// Optional end of the interval where the fact is claimed valid.
    pub valid_to: Option<OffsetDateTime>,
    /// Time at which Shibahama accepted the observation.
    pub ingested_at: OffsetDateTime,
    /// Initial accessibility tier.
    pub tier: Tier,
    /// Optional credence override; `None` assigns credence from provenance during ingest.
    pub credence: Option<CredenceTier>,
    /// Initial significance score.
    pub significance: f64,
    /// Coldest tier this memory may occupy after demotion.
    pub credence_floor: Tier,
}

impl MemoryWriteEvent {
    /// Creates a write event with mandatory provenance and source-kind credence assignment.
    #[must_use]
    pub fn new(
        content: impl Into<String>,
        provenance: Provenance,
        valid_from: OffsetDateTime,
        ingested_at: OffsetDateTime,
    ) -> Self {
        let tier = default_ingest_tier(provenance.source_kind);

        Self {
            content: content.into(),
            scope: MemoryScope::default(),
            kind: MemoryKind::Fact,
            provenance,
            valid_from,
            valid_to: None,
            ingested_at,
            tier,
            credence: None,
            significance: 1.0,
            credence_floor: Tier::Cold,
        }
    }

    /// Marks this write event as an instruction/directive memory.
    #[must_use]
    pub const fn as_instruction(mut self) -> Self {
        self.kind = MemoryKind::Instruction;
        self
    }

    /// Closes the materialized memory's valid-time interval at `valid_to`.
    #[must_use]
    pub const fn with_valid_to(mut self, valid_to: OffsetDateTime) -> Self {
        self.valid_to = Some(valid_to);
        self
    }

    /// Creates a write event with mandatory provenance and an explicit credence override.
    #[must_use]
    pub fn with_explicit_credence(
        content: impl Into<String>,
        provenance: Provenance,
        valid_from: OffsetDateTime,
        ingested_at: OffsetDateTime,
        tier: Tier,
        credence: CredenceTier,
        credence_floor: Tier,
    ) -> Self {
        Self {
            content: content.into(),
            scope: MemoryScope::default(),
            kind: MemoryKind::Fact,
            provenance,
            valid_from,
            valid_to: None,
            ingested_at,
            tier,
            credence: Some(credence),
            significance: 0.0,
            credence_floor,
        }
    }

    /// Materializes this write event into a memory item using an explicit credence policy.
    #[must_use]
    pub fn into_item_with_policy(self, policy: IngestCredencePolicy) -> MemoryItem {
        self.into_item(policy)
    }

    /// Assigns an explicit validated repository/team scope before materialization.
    #[must_use]
    pub fn with_scope(mut self, scope: MemoryScope) -> Self {
        self.scope = scope;
        self
    }

    fn into_item(self, policy: IngestCredencePolicy) -> MemoryItem {
        let credence = self
            .credence
            .unwrap_or_else(|| policy.credence_for(self.provenance.source_kind));

        MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            scope: self.scope,
            id: MemoryId::new_v7(),
            content: self.content,
            kind: self.kind,
            compaction: None,
            consolidation: None,
            promotion: None,
            embedding_ref: None,
            provenance: self.provenance,
            timestamps: self.valid_to.map_or_else(
                || TemporalBounds::open_from(self.valid_from, self.ingested_at),
                |valid_to| {
                    TemporalBounds::open_from(self.valid_from, self.ingested_at).closed_at(valid_to)
                },
            ),
            tier: self.tier,
            credence,
            significance: self.significance,
            base_significance: self.significance,
            credence_floor: self.credence_floor,
            access_events: Vec::new(),
        }
    }
}

const fn default_ingest_tier(source_kind: SourceKind) -> Tier {
    match source_kind {
        SourceKind::Agent | SourceKind::Web => Tier::Cold,
        SourceKind::User | SourceKind::File | SourceKind::Tool => Tier::Warm,
    }
}

/// Credence defaults assigned by source kind during ingestion.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IngestCredencePolicy {
    /// Credence for user-provided memories.
    pub user: CredenceTier,
    /// Credence for agent-authored memories.
    pub agent: CredenceTier,
    /// Credence for file-backed memories.
    pub file: CredenceTier,
    /// Credence for web-backed memories.
    pub web: CredenceTier,
    /// Credence for tool-output memories.
    pub tool: CredenceTier,
}

impl Default for IngestCredencePolicy {
    fn default() -> Self {
        Self {
            user: CredenceTier::FirmAuthoritative,
            agent: CredenceTier::ModelInferred,
            file: CredenceTier::VerifiedSource,
            web: CredenceTier::Unverified,
            tool: CredenceTier::ModelInferred,
        }
    }
}

impl IngestCredencePolicy {
    /// Returns the default credence for a source kind.
    #[must_use]
    pub const fn credence_for(self, source_kind: SourceKind) -> CredenceTier {
        match source_kind {
            SourceKind::User => self.user,
            SourceKind::Agent => self.agent,
            SourceKind::File => self.file,
            SourceKind::Web => self.web,
            SourceKind::Tool => self.tool,
        }
    }
}

/// Storage backend contract for durable Shibahama memory state.
pub trait MemoryStore {
    /// Appends an event to the source-of-truth log.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot durably append the event.
    fn append_event(&self, event: MemoryEvent) -> Result<EventRecord, StorageError>;

    /// Writes a memory item and updates current materialized state.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot durably write the event and current state.
    fn write(&self, item: &MemoryItem) -> Result<EventRecord, StorageError>;

    /// Ingests a caller-supplied write event with mandatory provenance.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot durably materialize and write the event.
    fn write_event(
        &self,
        event: MemoryWriteEvent,
    ) -> Result<(EventRecord, MemoryItem), StorageError>;

    /// Ingests a caller-supplied write event with an explicit source-kind credence policy.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot durably materialize and write the event.
    fn write_event_with_policy(
        &self,
        event: MemoryWriteEvent,
        policy: IngestCredencePolicy,
    ) -> Result<(EventRecord, MemoryItem), StorageError>;

    /// Reads current materialized state for one memory id.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot read or decode current state.
    fn get(&self, id: MemoryId) -> Result<Option<MemoryItem>, StorageError>;

    /// Reads current materialized state for many ids, preserving input order.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot read or decode current state.
    fn get_many(&self, ids: &[MemoryId]) -> Result<Vec<Option<MemoryItem>>, StorageError>;

    /// Soft-invalidates a memory without deleting it.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot durably write the invalidation.
    fn soft_invalidate(
        &self,
        id: MemoryId,
        valid_to: OffsetDateTime,
    ) -> Result<Option<EventRecord>, StorageError>;

    /// Flags a memory for explicit re-verification without changing its valid-time interval.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot durably write the flag event.
    fn flag_for_reverification(
        &self,
        id: MemoryId,
        flagged_at: OffsetDateTime,
        reason: String,
    ) -> Result<Option<EventRecord>, StorageError>;

    /// Atomically closes a superseded memory and writes its reconstructed replacement.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot durably write both events and materialized rows,
    /// or when the replacement would overwrite the superseded memory.
    fn insert_reconstruction_replacement(
        &self,
        superseded_id: MemoryId,
        replacement: &MemoryItem,
        valid_to: OffsetDateTime,
    ) -> Result<Option<ReconstructionReplacementRecord>, StorageError>;

    /// Replays the event log in sequence order.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot read or decode event records.
    fn events(&self) -> Result<Vec<EventRecord>, StorageError>;
}

/// `redb`-backed store for event log and materialized memory state.
pub struct RedbMemoryStore {
    db: Database,
    encryption: Arc<dyn EncryptionAtRest>,
}

impl RedbMemoryStore {
    /// Opens or creates a `redb` store at `path`.
    ///
    /// # Errors
    ///
    /// Returns an error when the embedded database cannot be created or opened.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, StorageError> {
        Self::open_with_encryption(path, NoopEncryption)
    }

    /// Opens or creates a `redb` store at `path` with an encryption provider.
    ///
    /// # Errors
    ///
    /// Returns an error when the embedded database cannot be created, opened, or decoded with the
    /// configured provider.
    pub fn open_with_encryption<E>(
        path: impl AsRef<Path>,
        encryption: E,
    ) -> Result<Self, StorageError>
    where
        E: EncryptionAtRest + 'static,
    {
        let db = Database::create(path).map_err(embed)?;
        let store = Self {
            db,
            encryption: Arc::new(encryption),
        };

        store.recover()?;

        Ok(store)
    }

    fn storage_context(table: StorageTableName, key: &[u8]) -> Vec<u8> {
        let mut context =
            Vec::with_capacity(b"shibahama:redb:".len() + table.as_str().len() + 1 + key.len());

        context.extend_from_slice(b"shibahama:redb:");
        context.extend_from_slice(table.as_str().as_bytes());
        context.push(b':');
        context.extend_from_slice(key);

        context
    }

    fn event_key(sequence: u64) -> [u8; 8] {
        sequence.to_be_bytes()
    }

    fn scope_index_key(scope: &MemoryScope) -> String {
        let visibility = match scope.visibility {
            ScopeVisibility::Repository => "repository",
            ScopeVisibility::Team => "team",
        };
        let team = scope.team.as_ref().map_or("", |team| team.as_str());

        format!("{visibility}\u{1f}{}\u{1f}{team}", scope.repository)
    }

    fn index_memory_scope(
        &self,
        table: &mut Table<'_, &str, &[u8]>,
        item: &MemoryItem,
    ) -> Result<(), StorageError> {
        item.scope
            .validate()
            .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        let key = Self::scope_index_key(&item.scope);
        let mut ids: Vec<MemoryId> = table
            .get(key.as_str())
            .map_err(embed)?
            .map(|value| {
                self.decode_json(
                    StorageTableName::MemoryScopeIndex,
                    key.as_bytes(),
                    value.value(),
                )
            })
            .transpose()?
            .unwrap_or_default();

        if !ids.contains(&item.id) {
            ids.push(item.id);
            ids.sort_unstable();
            let bytes =
                self.encode_json(StorageTableName::MemoryScopeIndex, key.as_bytes(), &ids)?;
            table
                .insert(key.as_str(), bytes.as_slice())
                .map_err(embed)?;
        }

        Ok(())
    }

    fn encode_json<T: Serialize>(
        &self,
        table: StorageTableName,
        key: &[u8],
        value: &T,
    ) -> Result<Vec<u8>, StorageError> {
        let plaintext = serde_json::to_vec(value)?;
        self.encode_bytes(table, key, &plaintext)
    }

    fn decode_json<T: DeserializeOwned>(
        &self,
        table: StorageTableName,
        key: &[u8],
        value: &[u8],
    ) -> Result<T, StorageError> {
        let plaintext = self.decode_bytes(table, key, value)?;

        Ok(serde_json::from_slice(&plaintext)?)
    }

    fn encode_bytes(
        &self,
        table: StorageTableName,
        key: &[u8],
        value: &[u8],
    ) -> Result<Vec<u8>, StorageError> {
        let context = Self::storage_context(table, key);

        Ok(self.encryption.encrypt(&context, value)?)
    }

    fn decode_bytes(
        &self,
        table: StorageTableName,
        key: &[u8],
        value: &[u8],
    ) -> Result<Vec<u8>, StorageError> {
        let context = Self::storage_context(table, key);

        Ok(self.encryption.decrypt(&context, value)?)
    }

    /// Appends an event and returns its durable record.
    ///
    /// # Errors
    ///
    /// Returns an error when the event cannot be serialized, appended, committed, or read back.
    pub fn append_event(&self, event: MemoryEvent) -> Result<EventRecord, StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let sequence = {
            let mut table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let sequence = table.len().map_err(embed)?;
            let record = EventRecord {
                sequence,
                recorded_at: OffsetDateTime::now_utc(),
                event,
            };
            let event_key = Self::event_key(sequence);
            let bytes = self.encode_json(StorageTableName::EventLog, &event_key, &record)?;

            table.insert(sequence, bytes.as_slice()).map_err(embed)?;

            sequence
        };

        write_txn.commit().map_err(embed)?;

        self.event(sequence)?
            .ok_or_else(|| StorageError::Embedded("committed event was not readable".to_owned()))
    }

    /// Writes a memory item by appending a source event and updating materialized state atomically.
    ///
    /// # Errors
    ///
    /// Returns an error when the item or event cannot be serialized, written, committed, or read
    /// back.
    pub fn write(&self, item: &MemoryItem) -> Result<EventRecord, StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let sequence = {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut scope_table = write_txn
                .open_table(MEMORY_SCOPE_INDEX_TABLE)
                .map_err(embed)?;
            let sequence = event_table.len().map_err(embed)?;
            let event = MemoryEvent::MemoryWritten {
                item: Box::new(item.clone()),
            };
            let record = EventRecord {
                sequence,
                recorded_at: OffsetDateTime::now_utc(),
                event,
            };
            let item_key = item.id.to_string();
            let event_key = Self::event_key(sequence);
            let event_bytes = self.encode_json(StorageTableName::EventLog, &event_key, &record)?;
            let item_bytes =
                self.encode_json(StorageTableName::MemoryItems, item_key.as_bytes(), item)?;

            event_table
                .insert(sequence, event_bytes.as_slice())
                .map_err(embed)?;
            item_table
                .insert(item_key.as_str(), item_bytes.as_slice())
                .map_err(embed)?;
            self.index_memory_scope(&mut scope_table, item)?;

            sequence
        };

        write_txn.commit().map_err(embed)?;

        self.event(sequence)?.ok_or_else(|| {
            StorageError::Embedded("committed write event was not readable".to_owned())
        })
    }

    /// Ingests a caller-supplied write event by assigning an id and writing a memory item.
    ///
    /// # Errors
    ///
    /// Returns an error when the event cannot be materialized, written, committed, or read back.
    pub fn write_event(
        &self,
        event: MemoryWriteEvent,
    ) -> Result<(EventRecord, MemoryItem), StorageError> {
        self.write_event_with_policy(event, IngestCredencePolicy::default())
    }

    /// Ingests a caller-supplied write event with an explicit source-kind credence policy.
    ///
    /// # Errors
    ///
    /// Returns an error when the event cannot be materialized, written, committed, or read back.
    pub fn write_event_with_policy(
        &self,
        event: MemoryWriteEvent,
        policy: IngestCredencePolicy,
    ) -> Result<(EventRecord, MemoryItem), StorageError> {
        let item = event.into_item(policy);
        let record = self.write(&item)?;

        Ok((record, item))
    }

    /// Copies a repository-local memory into an approved team scope without mutating the source.
    ///
    /// # Errors
    ///
    /// Returns an error when source/target scopes are incompatible or durable writes fail.
    #[allow(clippy::too_many_lines)]
    pub fn promote_memory_scope(
        &self,
        source_id: MemoryId,
        promoted_id: MemoryId,
        target_scope: MemoryScope,
        actor: impl Into<String>,
        rationale: impl Into<String>,
        promoted_at: OffsetDateTime,
    ) -> Result<Option<ScopePromotionRecord>, StorageError> {
        target_scope
            .validate()
            .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        if target_scope.visibility != ScopeVisibility::Team {
            return Err(StorageError::InvariantViolation(
                "scope promotion requires a team target scope".to_owned(),
            ));
        }
        let Some(source) = self.get(source_id)? else {
            return Ok(None);
        };
        if source.scope.visibility != ScopeVisibility::Repository
            || source.scope.repository != target_scope.repository
        {
            return Err(StorageError::InvariantViolation(
                "scope promotion requires a repository-local source in the same repository"
                    .to_owned(),
            ));
        }
        let actor = actor.into();
        let rationale = rationale.into();
        if actor.trim().is_empty() || rationale.trim().is_empty() {
            return Err(StorageError::InvariantViolation(
                "scope promotion requires a non-empty actor and rationale".to_owned(),
            ));
        }
        let mut promoted = source.clone();
        promoted.id = promoted_id;
        promoted.scope = target_scope.clone();
        promoted.timestamps.ingested_at = promoted_at;
        promoted.access_events.clear();
        promoted.promotion = Some(ScopePromotionRef {
            source_memory_id: source_id,
            rationale: rationale.clone(),
            promoted_by: actor.clone(),
            promoted_at,
        });
        if let Some(embedding_ref) = promoted.embedding_ref.as_mut() {
            embedding_ref.vector_id = promoted.id.to_string();
        }

        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let (write_sequence, promotion_sequence) = {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut scope_table = write_txn
                .open_table(MEMORY_SCOPE_INDEX_TABLE)
                .map_err(embed)?;
            let mut embedding_table = write_txn.open_table(EMBEDDINGS_TABLE).map_err(embed)?;
            let source_key = source_id.to_string();
            let promoted_key = promoted.id.to_string();
            if item_table
                .get(promoted_key.as_str())
                .map_err(embed)?
                .is_some()
            {
                return Err(StorageError::InvariantViolation(format!(
                    "promoted memory {} already exists",
                    promoted.id
                )));
            }
            let write_sequence = event_table.len().map_err(embed)?;
            let promotion_sequence = write_sequence + 1;
            let write_record = EventRecord {
                sequence: write_sequence,
                recorded_at: promoted_at,
                event: MemoryEvent::MemoryWritten {
                    item: Box::new(promoted.clone()),
                },
            };
            let promotion_record = EventRecord {
                sequence: promotion_sequence,
                recorded_at: promoted_at,
                event: MemoryEvent::MemoryScopePromoted {
                    source_id,
                    promoted_id: promoted.id,
                    actor,
                    rationale,
                    promoted_at,
                },
            };
            let write_key = Self::event_key(write_sequence);
            let promotion_key = Self::event_key(promotion_sequence);
            let write_bytes =
                self.encode_json(StorageTableName::EventLog, &write_key, &write_record)?;
            let promotion_bytes = self.encode_json(
                StorageTableName::EventLog,
                &promotion_key,
                &promotion_record,
            )?;
            let item_bytes = self.encode_json(
                StorageTableName::MemoryItems,
                promoted_key.as_bytes(),
                &promoted,
            )?;

            event_table
                .insert(write_sequence, write_bytes.as_slice())
                .map_err(embed)?;
            event_table
                .insert(promotion_sequence, promotion_bytes.as_slice())
                .map_err(embed)?;
            item_table
                .insert(promoted_key.as_str(), item_bytes.as_slice())
                .map_err(embed)?;
            self.index_memory_scope(&mut scope_table, &promoted)?;

            let source_embedding: Option<StoredEmbedding> = embedding_table
                .get(source_key.as_str())
                .map_err(embed)?
                .map(|source_embedding| {
                    self.decode_json(
                        StorageTableName::Embeddings,
                        source_key.as_bytes(),
                        source_embedding.value(),
                    )
                })
                .transpose()?;
            if let Some(mut embedding) = source_embedding {
                embedding.memory_id = promoted.id;
                embedding.scope = target_scope;
                let bytes = self.encode_json(
                    StorageTableName::Embeddings,
                    promoted_key.as_bytes(),
                    &embedding,
                )?;
                embedding_table
                    .insert(promoted_key.as_str(), bytes.as_slice())
                    .map_err(embed)?;
            }

            (write_sequence, promotion_sequence)
        };
        write_txn.commit().map_err(embed)?;
        let memory_write = self.event(write_sequence)?.ok_or_else(|| {
            StorageError::Embedded("committed promotion write was not readable".to_owned())
        })?;
        let promotion = self.event(promotion_sequence)?.ok_or_else(|| {
            StorageError::Embedded("committed promotion event was not readable".to_owned())
        })?;

        Ok(Some(ScopePromotionRecord {
            promoted,
            memory_write,
            promotion,
        }))
    }

    /// Appends a scope-only audit record for a policy-denied promotion attempt.
    ///
    /// # Errors
    ///
    /// Returns an error when scope validation or durable event append fails.
    pub fn record_scope_authorization_denial(
        &self,
        principal: impl Into<String>,
        source_scope: &MemoryScope,
        target_scope: &MemoryScope,
        action: ScopeAuthorizationAction,
        denied_at: OffsetDateTime,
    ) -> Result<EventRecord, StorageError> {
        source_scope
            .validate()
            .and_then(|()| target_scope.validate())
            .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        let principal = principal.into();
        if principal.trim().is_empty() {
            return Err(StorageError::InvariantViolation(
                "scope authorization audit requires a non-empty principal".to_owned(),
            ));
        }

        self.append_event(MemoryEvent::ScopeAuthorizationDenied {
            principal,
            source_scope: source_scope.clone(),
            target_scope: target_scope.clone(),
            action,
            denied_at,
        })
    }

    /// Appends a content-free capture or recall policy decision to the event log.
    ///
    /// # Errors
    ///
    /// Returns an error when durable event append fails.
    pub fn record_policy_decision(
        &self,
        record: PolicyAuditRecord,
    ) -> Result<EventRecord, StorageError> {
        self.append_event(MemoryEvent::PolicyDecisionRecorded { record })
    }

    /// Adds a validated extraction candidate to the durable review queue.
    ///
    /// # Errors
    ///
    /// Returns an error when candidate validation or durable event append fails.
    pub fn enqueue_review_candidate(
        &self,
        candidate: ReviewCandidate,
    ) -> Result<EventRecord, StorageError> {
        candidate.validate().map_err(review_storage_error)?;
        if self
            .review_queue(None)?
            .iter()
            .any(|item| item.candidate.id == candidate.id)
        {
            return Err(StorageError::InvariantViolation(
                "review candidate id already exists".to_owned(),
            ));
        }
        self.append_event(MemoryEvent::ReviewCandidateQueued { candidate })
    }

    /// Replays durable review candidates and their ordered decisions.
    ///
    /// # Errors
    ///
    /// Returns an error when the event log cannot be read or contains invalid review state.
    pub fn review_queue(
        &self,
        scope: Option<&MemoryScope>,
    ) -> Result<Vec<ReviewQueueItem>, StorageError> {
        if let Some(scope) = scope {
            scope
                .validate()
                .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        }
        let mut items = BTreeMap::<ReviewCandidateId, ReviewQueueItem>::new();
        for record in self.events()? {
            match record.event {
                MemoryEvent::ReviewCandidateQueued { candidate } => {
                    candidate.validate().map_err(review_storage_error)?;
                    if items
                        .insert(
                            candidate.id,
                            ReviewQueueItem {
                                candidate,
                                decisions: Vec::new(),
                            },
                        )
                        .is_some()
                    {
                        return Err(StorageError::InvariantViolation(
                            "review queue contains a duplicate candidate id".to_owned(),
                        ));
                    }
                }
                MemoryEvent::ReviewDecisionRecorded { decision } => {
                    let item = items.get_mut(&decision.candidate_id).ok_or_else(|| {
                        StorageError::InvariantViolation(
                            "review decision references an unknown candidate".to_owned(),
                        )
                    })?;
                    decision
                        .validate_for(&item.candidate)
                        .map_err(review_storage_error)?;
                    if item
                        .decisions
                        .last()
                        .is_some_and(ReviewDecision::is_terminal)
                    {
                        return Err(StorageError::InvariantViolation(
                            "review queue contains a decision after terminal resolution".to_owned(),
                        ));
                    }
                    item.decisions.push(decision);
                }
                _ => {}
            }
        }
        Ok(items
            .into_values()
            .filter(|item| {
                scope.is_none_or(|scope| item.candidate.candidate.suggested_scope == *scope)
            })
            .collect())
    }

    /// Records one validated review decision for a queued candidate.
    ///
    /// # Errors
    ///
    /// Returns an error when the candidate is unknown, terminal, or durable append fails.
    pub fn record_review_decision(
        &self,
        decision: ReviewDecision,
    ) -> Result<EventRecord, StorageError> {
        let queue = self.review_queue(None)?;
        let item = queue
            .iter()
            .find(|item| item.candidate.id == decision.candidate_id)
            .ok_or_else(|| {
                StorageError::InvariantViolation(
                    "review decision references an unknown candidate".to_owned(),
                )
            })?;
        decision
            .validate_for(&item.candidate)
            .map_err(review_storage_error)?;
        if item
            .decisions
            .last()
            .is_some_and(ReviewDecision::is_terminal)
        {
            return Err(StorageError::InvariantViolation(
                "review candidate is already resolved".to_owned(),
            ));
        }
        self.append_event(MemoryEvent::ReviewDecisionRecorded { decision })
    }

    /// Atomically materializes an approved candidate and records its approval decision.
    ///
    /// # Errors
    ///
    /// Returns an error when queue state is invalid, the approval does not match its candidate,
    /// or either durable event cannot be committed.
    pub fn approve_review_candidate(
        &self,
        item: &MemoryItem,
        decision: ReviewDecision,
    ) -> Result<(EventRecord, EventRecord), StorageError> {
        let queue = self.review_queue(None)?;
        let queued = queue
            .iter()
            .find(|queued| queued.candidate.id == decision.candidate_id)
            .ok_or_else(|| {
                StorageError::InvariantViolation(
                    "review approval references an unknown candidate".to_owned(),
                )
            })?;
        decision
            .validate_for(&queued.candidate)
            .map_err(review_storage_error)?;
        if decision.approved_memory_id != Some(item.id)
            || decision.action != crate::review::ReviewAction::Approve
            || item.scope != queued.candidate.candidate.suggested_scope
        {
            return Err(StorageError::InvariantViolation(
                "review approval does not match the queued candidate".to_owned(),
            ));
        }
        if queued
            .decisions
            .last()
            .is_some_and(ReviewDecision::is_terminal)
        {
            return Err(StorageError::InvariantViolation(
                "review candidate is already resolved".to_owned(),
            ));
        }

        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let (memory_sequence, decision_sequence) = {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut scope_table = write_txn
                .open_table(MEMORY_SCOPE_INDEX_TABLE)
                .map_err(embed)?;
            let item_key = item.id.to_string();
            if item_table.get(item_key.as_str()).map_err(embed)?.is_some() {
                return Err(StorageError::InvariantViolation(
                    "review approval would overwrite an existing memory".to_owned(),
                ));
            }
            let memory_sequence = event_table.len().map_err(embed)?;
            let recorded_at = OffsetDateTime::now_utc();
            let memory_record = EventRecord {
                sequence: memory_sequence,
                recorded_at,
                event: MemoryEvent::MemoryWritten {
                    item: Box::new(item.clone()),
                },
            };
            let memory_key = Self::event_key(memory_sequence);
            let memory_bytes =
                self.encode_json(StorageTableName::EventLog, &memory_key, &memory_record)?;
            event_table
                .insert(memory_sequence, memory_bytes.as_slice())
                .map_err(embed)?;

            let decision_sequence = memory_sequence + 1;
            let decision_record = EventRecord {
                sequence: decision_sequence,
                recorded_at,
                event: MemoryEvent::ReviewDecisionRecorded { decision },
            };
            let decision_key = Self::event_key(decision_sequence);
            let decision_bytes =
                self.encode_json(StorageTableName::EventLog, &decision_key, &decision_record)?;
            event_table
                .insert(decision_sequence, decision_bytes.as_slice())
                .map_err(embed)?;

            let item_bytes =
                self.encode_json(StorageTableName::MemoryItems, item_key.as_bytes(), item)?;
            item_table
                .insert(item_key.as_str(), item_bytes.as_slice())
                .map_err(embed)?;
            self.index_memory_scope(&mut scope_table, item)?;

            (memory_sequence, decision_sequence)
        };
        write_txn.commit().map_err(embed)?;
        let memory = self.event(memory_sequence)?.ok_or_else(|| {
            StorageError::Embedded("committed review memory event was not readable".to_owned())
        })?;
        let decision = self.event(decision_sequence)?.ok_or_else(|| {
            StorageError::Embedded("committed review decision event was not readable".to_owned())
        })?;

        Ok((memory, decision))
    }

    /// Appends a content-free automatic-capture audit record.
    ///
    /// # Errors
    ///
    /// Returns an error when durable event append fails.
    pub fn record_automatic_capture(
        &self,
        record: AutomaticCaptureAuditRecord,
    ) -> Result<EventRecord, StorageError> {
        self.append_event(MemoryEvent::AutomaticCaptureRecorded { record })
    }

    /// Appends a redaction-safe provider or policy observability record.
    ///
    /// # Errors
    ///
    /// Returns an error when durable event append fails.
    pub fn record_observability(
        &self,
        record: ObservabilityRecord,
    ) -> Result<EventRecord, StorageError> {
        self.append_event(MemoryEvent::ObservabilityRecorded { record })
    }

    /// Returns idempotency keys with a terminal automatic-capture outcome.
    ///
    /// # Errors
    ///
    /// Returns an error when the event log cannot be read.
    pub fn automatic_capture_terminal_keys(&self) -> Result<BTreeSet<String>, StorageError> {
        Ok(self
            .events()?
            .into_iter()
            .filter_map(|event| match event.event {
                MemoryEvent::AutomaticCaptureRecorded { record }
                    if record.disposition.is_terminal() =>
                {
                    Some(record.idempotency_key)
                }
                _ => None,
            })
            .collect())
    }

    /// Ingests a caller-supplied write event and vector embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when the vector cannot be indexed or the event cannot be durably written.
    pub fn write_event_embedded(
        &self,
        event: MemoryWriteEvent,
        vector_index: &mut dyn VectorIndex,
        vector: &[f32],
        index_name: impl Into<String>,
        model: impl Into<String>,
        model_version: impl Into<String>,
    ) -> Result<(EventRecord, MemoryItem), StorageError> {
        let mut item = event.into_item(IngestCredencePolicy::default());
        let record = self.write_embedded(
            &mut item,
            vector_index,
            vector,
            index_name,
            model,
            model_version,
        )?;

        Ok((record, item))
    }

    /// Writes an item and its embedding, keeping item metadata and vector index in sync.
    ///
    /// If durable item write fails after vector insertion, the vector insertion is rolled back.
    ///
    /// # Errors
    ///
    /// Returns an error when vector insertion fails or the item cannot be durably written.
    pub fn write_embedded(
        &self,
        item: &mut MemoryItem,
        vector_index: &mut dyn VectorIndex,
        vector: &[f32],
        index_name: impl Into<String>,
        model: impl Into<String>,
        model_version: impl Into<String>,
    ) -> Result<EventRecord, StorageError> {
        self.write_embedded_with_fault_injector(
            item,
            vector_index,
            vector,
            index_name,
            model,
            model_version,
            None,
        )
    }

    /// Writes an item and embedding while optionally injecting a deterministic storage fault.
    ///
    /// This exists for failure-path tests. Production callers should use [`Self::write_embedded`].
    ///
    /// # Errors
    ///
    /// Returns an error when vector insertion, the injected fault, or the durable write fails.
    #[allow(clippy::too_many_arguments)]
    pub fn write_embedded_with_fault_injector(
        &self,
        item: &mut MemoryItem,
        vector_index: &mut dyn VectorIndex,
        vector: &[f32],
        index_name: impl Into<String>,
        model: impl Into<String>,
        model_version: impl Into<String>,
        fault_injector: Option<&dyn StorageFaultInjector>,
    ) -> Result<EventRecord, StorageError> {
        let index_name = index_name.into();
        let model = model.into();
        let model_version = model_version.into();

        vector_index
            .add(item.id, vector)
            .map_err(StorageError::from)?;

        item.embedding_ref = Some(EmbeddingRef {
            index: index_name.clone(),
            vector_id: item.id.to_string(),
            model: model.clone(),
            model_version: model_version.clone(),
            dimensions: vector_index.dimensions(),
        });

        let result = (|| {
            if let Some(fault_injector) = fault_injector {
                fault_injector.check(StorageFaultStage::EmbeddedWrite)?;
            }
            let mut write_txn = self.db.begin_write().map_err(embed)?;
            write_txn
                .set_durability(Durability::Immediate)
                .map_err(embed)?;
            let sequence = {
                let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
                let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
                let mut scope_table = write_txn
                    .open_table(MEMORY_SCOPE_INDEX_TABLE)
                    .map_err(embed)?;
                let mut embedding_table = write_txn.open_table(EMBEDDINGS_TABLE).map_err(embed)?;
                let sequence = event_table.len().map_err(embed)?;
                let event = MemoryEvent::MemoryWritten {
                    item: Box::new(item.clone()),
                };
                let record = EventRecord {
                    sequence,
                    recorded_at: OffsetDateTime::now_utc(),
                    event,
                };
                let embedding = StoredEmbedding {
                    memory_id: item.id,
                    scope: item.scope.clone(),
                    vector: vector.to_vec(),
                    index_name,
                    model,
                    model_version,
                };
                let item_key = item.id.to_string();
                let event_key = Self::event_key(sequence);
                let event_bytes =
                    self.encode_json(StorageTableName::EventLog, &event_key, &record)?;
                let item_bytes =
                    self.encode_json(StorageTableName::MemoryItems, item_key.as_bytes(), item)?;
                let embedding_bytes = self.encode_json(
                    StorageTableName::Embeddings,
                    item_key.as_bytes(),
                    &embedding,
                )?;

                event_table
                    .insert(sequence, event_bytes.as_slice())
                    .map_err(embed)?;
                item_table
                    .insert(item_key.as_str(), item_bytes.as_slice())
                    .map_err(embed)?;
                self.index_memory_scope(&mut scope_table, item)?;
                embedding_table
                    .insert(item_key.as_str(), embedding_bytes.as_slice())
                    .map_err(embed)?;

                sequence
            };

            write_txn.commit().map_err(embed)?;

            self.event(sequence)?.ok_or_else(|| {
                StorageError::Embedded("committed write event was not readable".to_owned())
            })
        })();

        if result.is_err() {
            let _ = vector_index.delete_by_id(item.id);
        }

        result
    }

    /// Returns all persisted embedding rows.
    ///
    /// # Errors
    ///
    /// Returns an error when the embedding table cannot be read or decoded.
    pub fn stored_embeddings(&self) -> Result<Vec<StoredEmbedding>, StorageError> {
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(EMBEDDINGS_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(Vec::new()),
            Err(error) => return Err(embed(error)),
        };
        let mut embeddings = Vec::new();

        for row in table.iter().map_err(embed)? {
            let (key, value) = row.map_err(embed)?;
            let key = key.value();

            embeddings.push(self.decode_json(
                StorageTableName::Embeddings,
                key.as_bytes(),
                value.value(),
            )?);
        }

        Ok(embeddings)
    }

    fn delete_embedding(&self, id: MemoryId) -> Result<(), StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut table = write_txn.open_table(EMBEDDINGS_TABLE).map_err(embed)?;
            let key = id.to_string();

            table.remove(key.as_str()).map_err(embed)?;
        }

        write_txn.commit().map_err(embed)
    }

    /// Returns all event-log records in sequence order.
    ///
    /// # Errors
    ///
    /// Returns an error when the event table cannot be read or a stored record cannot be decoded.
    pub fn events(&self) -> Result<Vec<EventRecord>, StorageError> {
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(EVENT_LOG_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(Vec::new()),
            Err(error) => return Err(embed(error)),
        };
        let mut records = Vec::new();

        for row in table.iter().map_err(embed)? {
            let (sequence, value) = row.map_err(embed)?;
            let event_key = Self::event_key(sequence.value());
            let record: EventRecord =
                self.decode_json(StorageTableName::EventLog, &event_key, value.value())?;

            validate_event_schema_version(&record)?;
            records.push(record);
        }

        Ok(records)
    }

    /// Reconstructs memory rows believed at `as_of` from the event log.
    ///
    /// Writes become visible at their ingestion time. Backdated invalidations only affect an
    /// `as_of` query once the invalidation event itself has been recorded, so timeline queries do
    /// not retroactively erase what the system believed before the invalidation was known.
    ///
    /// # Errors
    ///
    /// Returns an error when the event table cannot be read or a stored record cannot be decoded.
    pub fn memory_items_believed_at(
        &self,
        as_of: OffsetDateTime,
    ) -> Result<Vec<MemoryItem>, StorageError> {
        let mut items = BTreeMap::<MemoryId, MemoryItem>::new();

        for record in self.events()? {
            match record.event {
                MemoryEvent::MemoryWritten { item } => {
                    let item = *item;
                    if item.timestamps.ingested_at <= as_of {
                        items.insert(item.id, item);
                    }
                }
                MemoryEvent::MemoryInvalidated { id, valid_to } => {
                    if record.recorded_at <= as_of
                        && let Some(item) = items.get_mut(&id)
                    {
                        item.timestamps = item.timestamps.closed_at(valid_to);
                    }
                }
                MemoryEvent::AccessRecorded { id, event } => {
                    if record.recorded_at <= as_of
                        && event.timestamp <= as_of
                        && let Some(item) = items.get_mut(&id)
                    {
                        item.access_events.push(event);
                    }
                }
                MemoryEvent::TierChanged { id, to, .. } => {
                    if record.recorded_at <= as_of
                        && let Some(item) = items.get_mut(&id)
                    {
                        item.tier = to;
                    }
                }
                MemoryEvent::ContentCompacted { id, pointer } => {
                    if record.recorded_at <= as_of
                        && let Some(item) = items.get_mut(&id)
                    {
                        item.compaction = Some(pointer);
                        item.content.clear();
                    }
                }
                MemoryEvent::HumanSignalRecorded { signal } => {
                    if record.recorded_at <= as_of
                        && signal.timestamp <= as_of
                        && let Some(item) = items.get_mut(&signal.memory_id)
                    {
                        if let Some(credence) = signal.new_credence {
                            item.credence = credence;
                        }
                        if let Some(floor) = signal.new_credence_floor {
                            item.credence_floor = floor;
                        }
                    }
                }
                MemoryEvent::ReverificationFlagged { .. }
                | MemoryEvent::ReconstructionApplied { .. }
                | MemoryEvent::ConsolidationDecision { .. }
                | MemoryEvent::MemoryScopePromoted { .. }
                | MemoryEvent::ScopeAuthorizationDenied { .. }
                | MemoryEvent::PolicyDecisionRecorded { .. }
                | MemoryEvent::ReviewCandidateQueued { .. }
                | MemoryEvent::ReviewDecisionRecorded { .. }
                | MemoryEvent::AutomaticCaptureRecorded { .. }
                | MemoryEvent::ObservabilityRecorded { .. } => {}
            }
        }

        Ok(items
            .into_values()
            .filter(|item| item.timestamps.is_valid_at(as_of))
            .collect())
    }

    /// Validates persisted tables after opening the store.
    ///
    /// # Errors
    ///
    /// Returns an error when stored event-log or materialized item records cannot be read or
    /// decoded.
    pub fn recover(&self) -> Result<RecoveryReport, StorageError> {
        let events = self.events()?;
        let materialized_items = self.materialized_items()?;
        let _stored_embeddings = self.stored_embeddings()?;
        let _graph_entities = self.graph_entities()?;
        let _graph_relations = self.graph_relations()?;

        Ok(RecoveryReport {
            event_count: events.len(),
            materialized_item_count: materialized_items.len(),
        })
    }

    /// Verifies the memory never-delete invariant for durable state.
    ///
    /// The invariant is scoped to memory state: writes, invalidation, significance refresh,
    /// reinforcement, compaction, and future tier eviction must preserve memory rows, event-log
    /// history, provenance, and any compacted cold content. Vector indexes may tombstone
    /// invalidated ids because vectors are secondary retrieval indexes, not memory history.
    ///
    /// # Errors
    ///
    /// Returns an error when store state cannot be read or when a written memory id is missing
    /// from materialized state, or compacted content referenced by a materialized row is missing.
    pub fn verify_never_delete_invariant(
        &self,
    ) -> Result<NeverDeleteInvariantReport, StorageError> {
        let events = self.events()?;
        let materialized_items = self.materialized_items()?;
        let cold_content_records = self.cold_content_records()?;
        let materialized_ids = materialized_items
            .iter()
            .map(|item| item.id)
            .collect::<BTreeSet<_>>();
        let written_ids = events
            .iter()
            .filter_map(|record| match &record.event {
                MemoryEvent::MemoryWritten { item } => Some(item.id),
                _ => None,
            })
            .collect::<BTreeSet<_>>();
        let cold_content_keys = cold_content_records
            .iter()
            .map(|record| record.storage_key.as_str())
            .collect::<BTreeSet<_>>();

        for written_id in &written_ids {
            if !materialized_ids.contains(written_id) {
                return Err(StorageError::InvariantViolation(format!(
                    "memory {written_id} was written but is missing from materialized state"
                )));
            }
        }

        for item in &materialized_items {
            if let Some(pointer) = &item.compaction
                && !cold_content_keys.contains(pointer.storage_key.as_str())
            {
                return Err(StorageError::InvariantViolation(format!(
                    "memory {} references missing compacted content {}",
                    item.id, pointer.storage_key
                )));
            }
        }

        Ok(NeverDeleteInvariantReport {
            event_count: events.len(),
            materialized_item_count: materialized_items.len(),
            written_item_count: written_ids.len(),
            compacted_content_count: cold_content_records.len(),
        })
    }

    /// Returns anomaly flags detected from current materialized state and event history.
    ///
    /// # Errors
    ///
    /// Returns an error when event-log or materialized item state cannot be read.
    pub fn anomaly_flags(
        &self,
        config: AnomalyConfig,
        now: OffsetDateTime,
    ) -> Result<Vec<AnomalyFlag>, StorageError> {
        let mut flags = detect_contradiction_bursts(&self.events()?, now, config);

        for item in self.materialized_items()? {
            flags.extend(inspect_suspicious_provenance(&item));
        }

        Ok(flags)
    }

    /// Returns the credence/tier audit trail for one memory id.
    ///
    /// # Errors
    ///
    /// Returns an error when event-log records cannot be read.
    #[allow(clippy::too_many_lines)]
    pub fn audit_trail(&self, id: MemoryId) -> Result<Vec<MemoryAuditEntry>, StorageError> {
        let Some(scope) = self.materialized_item(id)?.map(|item| item.scope) else {
            return Ok(Vec::new());
        };
        let mut entries = Vec::new();
        let mut previous_credence = None;
        let mut previous_tier = None;
        let mut previous_credence_floor = None;

        for record in self.events()? {
            match record.event {
                MemoryEvent::MemoryWritten { ref item } if item.id == id => {
                    let cause = if previous_credence.is_none()
                        && previous_tier.is_none()
                        && previous_credence_floor.is_none()
                    {
                        MemoryAuditCause::InitialWrite
                    } else {
                        MemoryAuditCause::DirectWrite
                    };

                    if previous_credence != Some(item.credence) {
                        push_credence_audit_entry(
                            &mut entries,
                            &record,
                            id,
                            &scope,
                            previous_credence,
                            item.credence,
                            cause,
                        );
                        previous_credence = Some(item.credence);
                    }

                    if previous_tier != Some(item.tier) {
                        push_tier_audit_entry(
                            &mut entries,
                            &record,
                            id,
                            &scope,
                            previous_tier,
                            item.tier,
                            cause,
                        );
                        previous_tier = Some(item.tier);
                    }

                    if previous_credence_floor != Some(item.credence_floor) {
                        push_floor_audit_entry(
                            &mut entries,
                            &record,
                            id,
                            &scope,
                            previous_credence_floor,
                            item.credence_floor,
                            cause,
                        );
                        previous_credence_floor = Some(item.credence_floor);
                    }
                }
                MemoryEvent::TierChanged {
                    id: changed_id,
                    from,
                    to,
                    cause,
                } if changed_id == id => {
                    push_tier_audit_entry(
                        &mut entries,
                        &record,
                        id,
                        &scope,
                        Some(from),
                        to,
                        MemoryAuditCause::from(cause),
                    );
                    previous_tier = Some(to);
                }
                MemoryEvent::HumanSignalRecorded { ref signal } if signal.memory_id == id => {
                    if let Some(to) = signal.new_credence {
                        push_credence_audit_entry(
                            &mut entries,
                            &record,
                            id,
                            &scope,
                            signal.previous_credence.or(previous_credence),
                            to,
                            MemoryAuditCause::HumanSignal,
                        );
                        previous_credence = Some(to);
                    }

                    if let Some(to) = signal.new_credence_floor {
                        push_floor_audit_entry(
                            &mut entries,
                            &record,
                            id,
                            &scope,
                            signal.previous_credence_floor.or(previous_credence_floor),
                            to,
                            MemoryAuditCause::HumanSignal,
                        );
                        previous_credence_floor = Some(to);
                    }
                }
                _ => {}
            }
        }

        Ok(entries)
    }

    /// Writes a full snapshot of event log, materialized state, and cold content to one file.
    ///
    /// # Errors
    ///
    /// Returns an error when store tables cannot be read, the snapshot cannot be encoded, or the
    /// destination file cannot be written.
    pub fn snapshot(&self, path: impl AsRef<Path>) -> Result<(), StorageError> {
        if self.encryption.is_enabled() {
            return Err(StorageError::EncryptedSnapshotExportDisabled);
        }

        let snapshot = StoreSnapshot {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            scope: None,
            events: self.events()?,
            materialized_items: self.materialized_items()?,
            embeddings: self.stored_embeddings()?,
            cold_contents: self.cold_content_records()?,
            graph_entities: self.graph_entities()?,
            graph_relations: self.graph_relations()?,
        };
        let bytes = serde_json::to_vec_pretty(&snapshot)?;

        fs::write(path, bytes)?;

        Ok(())
    }

    /// Writes a scope-marked snapshot containing only one repository/team visibility boundary.
    ///
    /// # Errors
    ///
    /// Returns an error when scope validation, storage reads, or file serialization fails.
    pub fn snapshot_scope(
        &self,
        path: impl AsRef<Path>,
        scope: &MemoryScope,
    ) -> Result<(), StorageError> {
        if self.encryption.is_enabled() {
            return Err(StorageError::EncryptedSnapshotExportDisabled);
        }
        scope
            .validate()
            .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        let materialized_items = self.memory_items_in_scope(scope)?;
        let snapshot = StoreSnapshot {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            scope: Some(scope.clone()),
            events: self.events_in_scope(scope)?,
            materialized_items,
            embeddings: self
                .stored_embeddings()?
                .into_iter()
                .filter(|embedding| embedding.scope == *scope)
                .collect(),
            cold_contents: self
                .cold_content_records()?
                .into_iter()
                .filter(|content| content.scope == *scope)
                .collect(),
            graph_entities: self
                .graph_entities()?
                .into_iter()
                .filter(|entity| entity.scope == *scope)
                .collect(),
            graph_relations: self
                .graph_relations()?
                .into_iter()
                .filter(|relation| relation.scope == *scope)
                .collect(),
        };
        let bytes = serde_json::to_vec_pretty(&snapshot)?;

        fs::write(path, bytes)?;

        Ok(())
    }

    /// Restores a snapshot into a store at `db_path`.
    ///
    /// # Errors
    ///
    /// Returns an error when the snapshot cannot be read or decoded, the destination store cannot
    /// be opened, or restored records cannot be written.
    pub fn restore_from_snapshot(
        db_path: impl AsRef<Path>,
        snapshot_path: impl AsRef<Path>,
    ) -> Result<Self, StorageError> {
        let bytes = fs::read(snapshot_path)?;
        let snapshot: StoreSnapshot = serde_json::from_slice(&bytes)?;
        let store = Self::open(db_path)?;

        store.restore(snapshot)?;

        Ok(store)
    }

    fn event(&self, sequence: u64) -> Result<Option<EventRecord>, StorageError> {
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(EVENT_LOG_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(None),
            Err(error) => return Err(embed(error)),
        };

        table
            .get(sequence)
            .map_err(embed)?
            .map(|value| {
                let key = Self::event_key(sequence);

                let record: EventRecord =
                    self.decode_json(StorageTableName::EventLog, &key, value.value())?;

                validate_event_schema_version(&record)?;

                Ok(record)
            })
            .transpose()
    }

    /// Stores the current materialized state for a memory item.
    ///
    /// # Errors
    ///
    /// Returns an error when the item cannot be serialized, written, or committed.
    pub fn put_materialized_item(&self, item: &MemoryItem) -> Result<(), StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut scope_table = write_txn
                .open_table(MEMORY_SCOPE_INDEX_TABLE)
                .map_err(embed)?;
            let key = item.id.to_string();
            let bytes = self.encode_json(StorageTableName::MemoryItems, key.as_bytes(), item)?;

            table
                .insert(key.as_str(), bytes.as_slice())
                .map_err(embed)?;
            self.index_memory_scope(&mut scope_table, item)?;
        }

        write_txn.commit().map_err(embed)
    }

    /// Returns the current materialized state for a memory id.
    ///
    /// # Errors
    ///
    /// Returns an error when the item table cannot be read or a stored item cannot be decoded.
    pub fn materialized_item(&self, id: MemoryId) -> Result<Option<MemoryItem>, StorageError> {
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(MEMORY_ITEMS_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(None),
            Err(error) => return Err(embed(error)),
        };
        let key = id.to_string();

        table
            .get(key.as_str())
            .map_err(embed)?
            .map(|value| {
                let item: MemoryItem =
                    self.decode_json(StorageTableName::MemoryItems, key.as_bytes(), value.value())?;

                validate_memory_schema_version(
                    &format!("materialized memory {}", item.id),
                    item.schema_version,
                )?;

                Ok(item)
            })
            .transpose()
    }

    /// Returns all current materialized memory rows.
    ///
    /// # Errors
    ///
    /// Returns an error when the item table cannot be read or a stored item cannot be decoded.
    pub fn memory_items(&self) -> Result<Vec<MemoryItem>, StorageError> {
        self.materialized_items()
    }

    /// Returns current memory ids for one exact repository/team visibility scope.
    ///
    /// # Errors
    ///
    /// Returns an error when scope validation or indexed storage reads fail.
    pub fn memory_ids_in_scope(&self, scope: &MemoryScope) -> Result<Vec<MemoryId>, StorageError> {
        scope
            .validate()
            .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(MEMORY_SCOPE_INDEX_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(Vec::new()),
            Err(error) => return Err(embed(error)),
        };
        let key = Self::scope_index_key(scope);

        table
            .get(key.as_str())
            .map_err(embed)?
            .map(|value| {
                self.decode_json(
                    StorageTableName::MemoryScopeIndex,
                    key.as_bytes(),
                    value.value(),
                )
            })
            .transpose()
            .map(Option::unwrap_or_default)
    }

    /// Returns materialized memories for one exact scope using the scope index.
    ///
    /// # Errors
    ///
    /// Returns an error when indexed ids or materialized rows cannot be read.
    pub fn memory_items_in_scope(
        &self,
        scope: &MemoryScope,
    ) -> Result<Vec<MemoryItem>, StorageError> {
        let ids = self.memory_ids_in_scope(scope)?;

        Ok(self
            .get_many(&ids)?
            .into_iter()
            .flatten()
            .filter(|item| item.scope == *scope)
            .collect())
    }

    /// Returns durable inspection events visible to one exact scope.
    ///
    /// Cross-scope lineage markers may expose only the paired memory identifiers, never the
    /// opposite scope's memory payload.
    ///
    /// # Errors
    ///
    /// Returns an error when scope-index or event-log reads fail.
    pub fn events_in_scope(&self, scope: &MemoryScope) -> Result<Vec<EventRecord>, StorageError> {
        let memory_ids = self
            .memory_ids_in_scope(scope)?
            .into_iter()
            .collect::<BTreeSet<_>>();

        Ok(self
            .events()?
            .into_iter()
            .filter(|record| event_belongs_to_memory_ids(record, &memory_ids, scope))
            .collect())
    }

    /// Returns one memory's audit trail only if it belongs to `scope`.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read.
    pub fn audit_trail_in_scope(
        &self,
        id: MemoryId,
        scope: &MemoryScope,
    ) -> Result<Vec<MemoryAuditEntry>, StorageError> {
        scope
            .validate()
            .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        let Some(item) = self.get(id)? else {
            return Ok(Vec::new());
        };
        if item.scope != *scope {
            return Ok(Vec::new());
        }

        self.audit_trail(id)
    }

    fn materialized_items(&self) -> Result<Vec<MemoryItem>, StorageError> {
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(MEMORY_ITEMS_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(Vec::new()),
            Err(error) => return Err(embed(error)),
        };
        let mut items = Vec::new();

        for row in table.iter().map_err(embed)? {
            let (key, value) = row.map_err(embed)?;
            let key = key.value();

            let item: MemoryItem =
                self.decode_json(StorageTableName::MemoryItems, key.as_bytes(), value.value())?;

            validate_memory_schema_version(
                &format!("materialized memory {}", item.id),
                item.schema_version,
            )?;
            items.push(item);
        }

        Ok(items)
    }

    fn cold_content_records(&self) -> Result<Vec<ColdContentRecord>, StorageError> {
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(COLD_CONTENT_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(Vec::new()),
            Err(error) => return Err(embed(error)),
        };
        let mut records = Vec::new();

        for row in table.iter().map_err(embed)? {
            let (key, value) = row.map_err(embed)?;
            let key = key.value();
            let stored: StoredColdContent =
                self.decode_json(StorageTableName::ColdContent, key.as_bytes(), value.value())?;

            records.push(ColdContentRecord {
                storage_key: key.to_owned(),
                scope: stored.scope,
                bytes: stored.compressed,
            });
        }

        Ok(records)
    }

    fn graph_entities(&self) -> Result<Vec<Entity>, StorageError> {
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(GRAPH_ENTITIES_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(Vec::new()),
            Err(error) => return Err(embed(error)),
        };
        let mut entities = Vec::new();

        for row in table.iter().map_err(embed)? {
            let (key, value) = row.map_err(embed)?;
            let key = key.value();

            entities.push(self.decode_json(
                StorageTableName::GraphEntities,
                key.as_bytes(),
                value.value(),
            )?);
        }

        Ok(entities)
    }

    fn graph_relations(&self) -> Result<Vec<Relation>, StorageError> {
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(GRAPH_RELATIONS_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(Vec::new()),
            Err(error) => return Err(embed(error)),
        };
        let mut relations = Vec::new();

        for row in table.iter().map_err(embed)? {
            let (key, value) = row.map_err(embed)?;
            let key = key.value();

            relations.push(self.decode_json(
                StorageTableName::GraphRelations,
                key.as_bytes(),
                value.value(),
            )?);
        }

        Ok(relations)
    }

    fn restore(&self, snapshot: StoreSnapshot) -> Result<(), StorageError> {
        validate_memory_schema_version("store snapshot", snapshot.schema_version)?;

        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut scope_table = write_txn
                .open_table(MEMORY_SCOPE_INDEX_TABLE)
                .map_err(embed)?;
            let mut embedding_table = write_txn.open_table(EMBEDDINGS_TABLE).map_err(embed)?;
            let mut cold_table = write_txn.open_table(COLD_CONTENT_TABLE).map_err(embed)?;
            let mut entity_table = write_txn.open_table(GRAPH_ENTITIES_TABLE).map_err(embed)?;
            let mut relation_table = write_txn.open_table(GRAPH_RELATIONS_TABLE).map_err(embed)?;

            for event in snapshot.events {
                let event_key = Self::event_key(event.sequence);
                let bytes = self.encode_json(StorageTableName::EventLog, &event_key, &event)?;

                event_table
                    .insert(event.sequence, bytes.as_slice())
                    .map_err(embed)?;
            }

            for item in snapshot.materialized_items {
                let key = item.id.to_string();
                let bytes =
                    self.encode_json(StorageTableName::MemoryItems, key.as_bytes(), &item)?;

                item_table
                    .insert(key.as_str(), bytes.as_slice())
                    .map_err(embed)?;
                self.index_memory_scope(&mut scope_table, &item)?;
            }

            for embedding in snapshot.embeddings {
                let key = embedding.memory_id.to_string();
                let bytes =
                    self.encode_json(StorageTableName::Embeddings, key.as_bytes(), &embedding)?;

                embedding_table
                    .insert(key.as_str(), bytes.as_slice())
                    .map_err(embed)?;
            }

            for cold_content in snapshot.cold_contents {
                let stored = StoredColdContent {
                    scope: cold_content.scope,
                    compressed: cold_content.bytes,
                };
                let bytes = self.encode_json(
                    StorageTableName::ColdContent,
                    cold_content.storage_key.as_bytes(),
                    &stored,
                )?;

                cold_table
                    .insert(cold_content.storage_key.as_str(), bytes.as_slice())
                    .map_err(embed)?;
            }

            for entity in snapshot.graph_entities {
                let key = entity.id.to_string();
                let bytes =
                    self.encode_json(StorageTableName::GraphEntities, key.as_bytes(), &entity)?;

                entity_table
                    .insert(key.as_str(), bytes.as_slice())
                    .map_err(embed)?;
            }

            for relation in snapshot.graph_relations {
                let key = relation.id.to_string();
                let bytes =
                    self.encode_json(StorageTableName::GraphRelations, key.as_bytes(), &relation)?;

                relation_table
                    .insert(key.as_str(), bytes.as_slice())
                    .map_err(embed)?;
            }
        }

        write_txn.commit().map_err(embed)
    }

    /// Returns the current materialized state for `id`.
    ///
    /// # Errors
    ///
    /// Returns an error when the item table cannot be read or a stored item cannot be decoded.
    pub fn get(&self, id: MemoryId) -> Result<Option<MemoryItem>, StorageError> {
        self.materialized_item(id)
    }

    /// Returns current materialized states for `ids`, preserving input order.
    ///
    /// Missing items are represented as `None`.
    ///
    /// # Errors
    ///
    /// Returns an error when the item table cannot be read or a stored item cannot be decoded.
    pub fn get_many(&self, ids: &[MemoryId]) -> Result<Vec<Option<MemoryItem>>, StorageError> {
        ids.iter().map(|id| self.get(*id)).collect()
    }

    /// Stores or replaces a graph entity in the same redb database as memories.
    ///
    /// # Errors
    ///
    /// Returns an error when the entity cannot be serialized, written, or committed.
    pub fn put_entity(&self, entity: &Entity) -> Result<(), StorageError> {
        entity
            .scope
            .validate()
            .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut table = write_txn.open_table(GRAPH_ENTITIES_TABLE).map_err(embed)?;
            let key = entity.id.to_string();
            let bytes =
                self.encode_json(StorageTableName::GraphEntities, key.as_bytes(), entity)?;

            table
                .insert(key.as_str(), bytes.as_slice())
                .map_err(embed)?;
        }

        write_txn.commit().map_err(embed)
    }

    /// Reads a graph entity by id.
    ///
    /// # Errors
    ///
    /// Returns an error when the entity table cannot be read or decoded.
    pub fn get_entity(&self, id: EntityId) -> Result<Option<Entity>, StorageError> {
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(GRAPH_ENTITIES_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(None),
            Err(error) => return Err(embed(error)),
        };
        let key = id.to_string();

        table
            .get(key.as_str())
            .map_err(embed)?
            .map(|value| {
                self.decode_json(
                    StorageTableName::GraphEntities,
                    key.as_bytes(),
                    value.value(),
                )
            })
            .transpose()
    }

    /// Finds an entity by type and stable key.
    ///
    /// # Errors
    ///
    /// Returns an error when graph entity rows cannot be read or decoded.
    pub fn find_entity_by_stable_key(
        &self,
        entity_type: &str,
        stable_key: &str,
    ) -> Result<Option<Entity>, StorageError> {
        Ok(self
            .graph_entities()?
            .into_iter()
            .find(|entity| entity.entity_type == entity_type && entity.stable_key == stable_key))
    }

    /// Finds an entity by type and stable key within one exact scope.
    ///
    /// # Errors
    ///
    /// Returns an error when graph entity rows cannot be read or decoded.
    pub fn find_entity_by_stable_key_in_scope(
        &self,
        entity_type: &str,
        stable_key: &str,
        scope: &MemoryScope,
    ) -> Result<Option<Entity>, StorageError> {
        Ok(self.graph_entities()?.into_iter().find(|entity| {
            entity.scope == *scope
                && entity.entity_type == entity_type
                && entity.stable_key == stable_key
        }))
    }

    /// Resolves `entity` to an existing entity with the same type and stable key, or stores it.
    ///
    /// This is the graph deduplication boundary for aliases or alternate labels that refer to the
    /// same typed entity.
    ///
    /// # Errors
    ///
    /// Returns an error when graph entity rows cannot be read, written, or decoded.
    pub fn resolve_entity(&self, entity: &Entity) -> Result<Entity, StorageError> {
        if let Some(existing) = self.find_entity_by_stable_key_in_scope(
            &entity.entity_type,
            &entity.stable_key,
            &entity.scope,
        )? {
            return Ok(existing);
        }

        self.put_entity(entity)?;

        Ok(entity.clone())
    }

    /// Stores or replaces a graph relation edge in the same redb database as memories.
    ///
    /// # Errors
    ///
    /// Returns an error when the relation cannot be serialized, written, or committed.
    pub fn put_relation(&self, relation: &Relation) -> Result<(), StorageError> {
        self.validate_graph_relation_scope(relation)?;
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut table = write_txn.open_table(GRAPH_RELATIONS_TABLE).map_err(embed)?;
            let key = relation.id.to_string();
            let bytes =
                self.encode_json(StorageTableName::GraphRelations, key.as_bytes(), relation)?;

            table
                .insert(key.as_str(), bytes.as_slice())
                .map_err(embed)?;
        }

        write_txn.commit().map_err(embed)
    }

    /// Reads a graph relation by id.
    ///
    /// # Errors
    ///
    /// Returns an error when the relation table cannot be read or decoded.
    pub fn get_relation(&self, id: RelationId) -> Result<Option<Relation>, StorageError> {
        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(GRAPH_RELATIONS_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(None),
            Err(error) => return Err(embed(error)),
        };
        let key = id.to_string();

        table
            .get(key.as_str())
            .map_err(embed)?
            .map(|value| {
                self.decode_json(
                    StorageTableName::GraphRelations,
                    key.as_bytes(),
                    value.value(),
                )
            })
            .transpose()
    }

    fn validate_graph_relation_scope(&self, relation: &Relation) -> Result<(), StorageError> {
        relation
            .scope
            .validate()
            .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        let from = self.get_entity(relation.from_entity)?.ok_or_else(|| {
            StorageError::InvariantViolation(format!(
                "relation {} references missing source entity {}",
                relation.id, relation.from_entity
            ))
        })?;
        let to = self.get_entity(relation.to_entity)?.ok_or_else(|| {
            StorageError::InvariantViolation(format!(
                "relation {} references missing target entity {}",
                relation.id, relation.to_entity
            ))
        })?;
        if from.scope != relation.scope || to.scope != relation.scope {
            return Err(StorageError::InvariantViolation(format!(
                "relation {} scope must match both endpoint scopes",
                relation.id
            )));
        }
        if let Some(memory_id) = relation.memory_id {
            let memory = self.get(memory_id)?.ok_or_else(|| {
                StorageError::InvariantViolation(format!(
                    "relation {} references missing memory {memory_id}",
                    relation.id
                ))
            })?;
            if memory.scope != relation.scope {
                return Err(StorageError::InvariantViolation(format!(
                    "relation {} scope must match its supporting memory",
                    relation.id
                )));
            }
        }
        if let Some(supersedes) = relation.supersedes {
            let existing = self.get_relation(supersedes)?.ok_or_else(|| {
                StorageError::InvariantViolation(format!(
                    "relation {} supersedes missing relation {supersedes}",
                    relation.id
                ))
            })?;
            if existing.scope != relation.scope {
                return Err(StorageError::InvariantViolation(format!(
                    "relation {} scope must match its superseded relation",
                    relation.id
                )));
            }
        }

        Ok(())
    }

    /// Returns direct relation edges touching `entity_id`.
    ///
    /// When `as_of` is supplied, relation valid-time and ingestion-time must both be in scope.
    ///
    /// # Errors
    ///
    /// Returns an error when relation rows cannot be read or decoded.
    pub fn relations_for_entity(
        &self,
        entity_id: EntityId,
        as_of: Option<OffsetDateTime>,
    ) -> Result<Vec<Relation>, StorageError> {
        let mut relations = self
            .graph_relations()?
            .into_iter()
            .filter(|relation| {
                (relation.from_entity == entity_id || relation.to_entity == entity_id)
                    && as_of.is_none_or(|instant| relation_believed_at(relation, instant))
            })
            .collect::<Vec<_>>();

        relations.sort_by_key(|relation| relation.id);

        Ok(relations)
    }

    /// Reconstructs the full graph believed at `as_of`.
    ///
    /// Both entities and relations must have been ingested by `as_of` and valid at `as_of`.
    /// Relations are returned only when both endpoints are also present in the snapshot, so callers
    /// never receive dangling historical edges.
    ///
    /// # Errors
    ///
    /// Returns an error when graph entity or relation rows cannot be read or decoded.
    pub fn graph_snapshot(&self, as_of: OffsetDateTime) -> Result<GraphSnapshot, StorageError> {
        let mut entities = self
            .graph_entities()?
            .into_iter()
            .filter(|entity| entity_believed_at(entity, as_of))
            .collect::<Vec<_>>();
        let entity_ids = entities
            .iter()
            .map(|entity| entity.id)
            .collect::<BTreeSet<_>>();
        let mut relations = self
            .graph_relations()?
            .into_iter()
            .filter(|relation| {
                relation_believed_at(relation, as_of)
                    && entity_ids.contains(&relation.from_entity)
                    && entity_ids.contains(&relation.to_entity)
            })
            .collect::<Vec<_>>();

        entities.sort_by_key(|entity| entity.id);
        relations.sort_by_key(|relation| relation.id);

        Ok(GraphSnapshot {
            as_of,
            entities,
            relations,
        })
    }

    /// Reconstructs graph state for one exact scope at a point in time.
    ///
    /// # Errors
    ///
    /// Returns an error when graph state cannot be read or the scope is invalid.
    pub fn graph_snapshot_in_scope(
        &self,
        as_of: OffsetDateTime,
        scope: &MemoryScope,
    ) -> Result<GraphSnapshot, StorageError> {
        scope
            .validate()
            .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        let mut entities = self
            .graph_entities()?
            .into_iter()
            .filter(|entity| entity.scope == *scope && entity_believed_at(entity, as_of))
            .collect::<Vec<_>>();
        let entity_ids = entities
            .iter()
            .map(|entity| entity.id)
            .collect::<BTreeSet<_>>();
        let mut relations = self
            .graph_relations()?
            .into_iter()
            .filter(|relation| {
                relation.scope == *scope
                    && relation_believed_at(relation, as_of)
                    && entity_ids.contains(&relation.from_entity)
                    && entity_ids.contains(&relation.to_entity)
            })
            .collect::<Vec<_>>();

        entities.sort_by_key(|entity| entity.id);
        relations.sort_by_key(|relation| relation.id);

        Ok(GraphSnapshot {
            as_of,
            entities,
            relations,
        })
    }

    /// Detects whether `proposed` contradicts an active relation at `as_of`.
    ///
    /// A relation contradiction is defined as the same source entity and relation type pointing to
    /// a different target entity while the existing relation is believed at `as_of`.
    ///
    /// # Errors
    ///
    /// Returns an error when relation rows cannot be read or decoded.
    pub fn detect_relation_contradiction(
        &self,
        proposed: &Relation,
        as_of: OffsetDateTime,
    ) -> Result<Option<RelationContradiction>, StorageError> {
        let existing = self.graph_relations()?.into_iter().find(|relation| {
            relation.id != proposed.id
                && relation.scope == proposed.scope
                && relation.from_entity == proposed.from_entity
                && relation.relation_type == proposed.relation_type
                && relation.to_entity != proposed.to_entity
                && relation_believed_at(relation, as_of)
        });

        Ok(existing.map(|existing| RelationContradiction {
            existing,
            proposed: proposed.clone(),
        }))
    }

    /// Inserts `proposed`, resolving any active contradiction on the same entity and relation type.
    ///
    /// When a contradiction exists, the old relation's valid interval is closed at
    /// `proposed.timestamps.valid_from`, the proposed relation is linked to it through
    /// `Relation::supersedes`, and both rows are written atomically.
    ///
    /// # Errors
    ///
    /// Returns an error when relation rows cannot be read, serialized, written, or committed.
    pub fn put_relation_resolving_contradiction(
        &self,
        proposed: &mut Relation,
    ) -> Result<Option<RelationId>, StorageError> {
        self.validate_graph_relation_scope(proposed)?;
        let contradiction =
            self.detect_relation_contradiction(proposed, proposed.timestamps.valid_from)?;
        let superseded_relation_id = contradiction
            .as_ref()
            .map(|contradiction| contradiction.existing.id);

        if let Some(superseded_relation_id) = superseded_relation_id {
            proposed.supersedes = Some(superseded_relation_id);
            self.validate_graph_relation_scope(proposed)?;
        }

        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut relation_table = write_txn.open_table(GRAPH_RELATIONS_TABLE).map_err(embed)?;

            if let Some(contradiction) = contradiction {
                let mut existing = contradiction.existing;
                let existing_key = existing.id.to_string();

                existing.timestamps = existing
                    .timestamps
                    .closed_at(proposed.timestamps.valid_from);

                let existing_bytes = self.encode_json(
                    StorageTableName::GraphRelations,
                    existing_key.as_bytes(),
                    &existing,
                )?;
                relation_table
                    .insert(existing_key.as_str(), existing_bytes.as_slice())
                    .map_err(embed)?;
            }

            let proposed_key = proposed.id.to_string();
            let proposed_bytes = self.encode_json(
                StorageTableName::GraphRelations,
                proposed_key.as_bytes(),
                proposed,
            )?;

            relation_table
                .insert(proposed_key.as_str(), proposed_bytes.as_slice())
                .map_err(embed)?;
        }

        write_txn.commit().map_err(embed)?;

        Ok(superseded_relation_id)
    }

    /// Traverses graph relations from a start entity.
    ///
    /// Traversal treats relations as navigable in either direction, applies the optional relation
    /// type allow-list, and applies `as_of` bi-temporal filtering when present.
    ///
    /// # Errors
    ///
    /// Returns an error when graph entity or relation rows cannot be read or decoded.
    pub fn traverse_graph(
        &self,
        request: &GraphTraversalRequest,
    ) -> Result<GraphTraversalResult, StorageError> {
        let entities_by_id = self
            .graph_entities()?
            .into_iter()
            .filter(|entity| {
                request
                    .scope
                    .as_ref()
                    .is_none_or(|scope| entity.scope == *scope)
            })
            .map(|entity| (entity.id, entity))
            .collect::<BTreeMap<_, _>>();
        let relations = self
            .graph_relations()?
            .into_iter()
            .filter(|relation| {
                request
                    .scope
                    .as_ref()
                    .is_none_or(|scope| relation.scope == *scope)
            })
            .collect::<Vec<_>>();
        let mut visited_entities = BTreeSet::new();
        let mut selected_relation_ids = BTreeSet::new();
        let mut queue = VecDeque::from([(request.start_entity, 0_usize)]);
        let mut result_entities = Vec::new();
        let mut result_relations = Vec::new();

        while let Some((entity_id, depth)) = queue.pop_front() {
            if !visited_entities.insert(entity_id) {
                continue;
            }

            if let Some(entity) = entities_by_id.get(&entity_id) {
                result_entities.push(entity.clone());
            }

            if depth >= request.max_hops {
                continue;
            }

            for relation in &relations {
                if !relation_touches_entity(relation, entity_id)
                    || !relation_matches_traversal(relation, request)
                {
                    continue;
                }

                if selected_relation_ids.insert(relation.id) {
                    result_relations.push(relation.clone());
                }

                let next_entity = if relation.from_entity == entity_id {
                    relation.to_entity
                } else {
                    relation.from_entity
                };

                if !visited_entities.contains(&next_entity) {
                    queue.push_back((next_entity, depth + 1));
                }
            }
        }

        result_entities.sort_by_key(|entity| entity.id);
        result_relations.sort_by_key(|relation| relation.id);

        Ok(GraphTraversalResult {
            entities: result_entities,
            relations: result_relations,
        })
    }

    /// Extracts a subgraph for a matter, namespace, or scope attribute.
    ///
    /// Entities are included when `scope_key` equals `scope_value` in their attributes. Relations
    /// are included only when both endpoints are in scope and the optional `as_of` filter accepts
    /// the relation.
    ///
    /// # Errors
    ///
    /// Returns an error when graph entity or relation rows cannot be read or decoded.
    pub fn extract_subgraph(
        &self,
        request: &SubgraphRequest,
    ) -> Result<GraphTraversalResult, StorageError> {
        let mut entities = self
            .graph_entities()?
            .into_iter()
            .filter(|entity| {
                entity
                    .attributes
                    .get(&request.scope_key)
                    .is_some_and(|value| value == &request.scope_value)
            })
            .collect::<Vec<_>>();
        let entity_ids = entities
            .iter()
            .map(|entity| entity.id)
            .collect::<BTreeSet<_>>();
        let mut relations = self
            .graph_relations()?
            .into_iter()
            .filter(|relation| {
                entity_ids.contains(&relation.from_entity)
                    && entity_ids.contains(&relation.to_entity)
                    && request
                        .as_of
                        .is_none_or(|instant| relation_believed_at(relation, instant))
            })
            .collect::<Vec<_>>();

        entities.sort_by_key(|entity| entity.id);
        relations.sort_by_key(|relation| relation.id);

        Ok(GraphTraversalResult {
            entities,
            relations,
        })
    }

    /// Soft-invalidates a memory by closing its valid-time interval without deleting history.
    ///
    /// Returns `Ok(None)` when the item does not exist.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written, or when stored state cannot be
    /// decoded.
    pub fn soft_invalidate(
        &self,
        id: MemoryId,
        valid_to: OffsetDateTime,
    ) -> Result<Option<EventRecord>, StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let sequence = {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let key = id.to_string();
            let mut item: MemoryItem = {
                let Some(value) = item_table.get(key.as_str()).map_err(embed)? else {
                    return Ok(None);
                };

                self.decode_json(StorageTableName::MemoryItems, key.as_bytes(), value.value())?
            };

            item.timestamps = item.timestamps.closed_at(valid_to);

            let sequence = event_table.len().map_err(embed)?;
            let record = EventRecord {
                sequence,
                recorded_at: OffsetDateTime::now_utc(),
                event: MemoryEvent::MemoryInvalidated { id, valid_to },
            };
            let event_key = Self::event_key(sequence);
            let event_bytes = self.encode_json(StorageTableName::EventLog, &event_key, &record)?;
            let item_bytes =
                self.encode_json(StorageTableName::MemoryItems, key.as_bytes(), &item)?;

            event_table
                .insert(sequence, event_bytes.as_slice())
                .map_err(embed)?;
            item_table
                .insert(key.as_str(), item_bytes.as_slice())
                .map_err(embed)?;

            sequence
        };

        write_txn.commit().map_err(embed)?;

        self.event(sequence)?
            .ok_or_else(|| {
                StorageError::Embedded("committed invalidation event was not readable".to_owned())
            })
            .map(Some)
    }

    /// Flags a memory for explicit re-verification without changing valid-time or vector state.
    ///
    /// Returns `Ok(None)` when the item does not exist.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written.
    pub fn flag_for_reverification(
        &self,
        id: MemoryId,
        flagged_at: OffsetDateTime,
        reason: impl Into<String>,
    ) -> Result<Option<EventRecord>, StorageError> {
        let reason = reason.into();
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let sequence = {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let key = id.to_string();

            if item_table.get(key.as_str()).map_err(embed)?.is_none() {
                return Ok(None);
            }

            let sequence = event_table.len().map_err(embed)?;
            let record = EventRecord {
                sequence,
                recorded_at: OffsetDateTime::now_utc(),
                event: MemoryEvent::ReverificationFlagged {
                    id,
                    flagged_at,
                    reason,
                },
            };
            let event_key = Self::event_key(sequence);
            let event_bytes = self.encode_json(StorageTableName::EventLog, &event_key, &record)?;

            event_table
                .insert(sequence, event_bytes.as_slice())
                .map_err(embed)?;

            sequence
        };

        write_txn.commit().map_err(embed)?;

        self.event(sequence)?
            .ok_or_else(|| {
                StorageError::Embedded(
                    "committed re-verification flag event was not readable".to_owned(),
                )
            })
            .map(Some)
    }

    /// Atomically invalidates a superseded memory and writes a reconstructed replacement.
    ///
    /// The replacement must use a distinct id so the superseded row remains readable for
    /// historical queries and invariant checks.
    ///
    /// Returns `Ok(None)` when the superseded item does not exist.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written, stored state cannot be decoded, or
    /// the replacement would overwrite an existing memory row.
    #[allow(clippy::too_many_lines)]
    pub fn insert_reconstruction_replacement(
        &self,
        superseded_id: MemoryId,
        replacement: &MemoryItem,
        valid_to: OffsetDateTime,
    ) -> Result<Option<ReconstructionReplacementRecord>, StorageError> {
        if superseded_id == replacement.id {
            return Err(StorageError::InvariantViolation(
                "reconstruction replacement must use a distinct memory id".to_owned(),
            ));
        }

        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let (invalidation_sequence, write_sequence, reconstruction_sequence) = {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut scope_table = write_txn
                .open_table(MEMORY_SCOPE_INDEX_TABLE)
                .map_err(embed)?;
            let superseded_key = superseded_id.to_string();
            let replacement_key = replacement.id.to_string();
            let mut superseded: MemoryItem = {
                let Some(value) = item_table.get(superseded_key.as_str()).map_err(embed)? else {
                    return Ok(None);
                };

                self.decode_json(
                    StorageTableName::MemoryItems,
                    superseded_key.as_bytes(),
                    value.value(),
                )?
            };

            if item_table
                .get(replacement_key.as_str())
                .map_err(embed)?
                .is_some()
            {
                return Err(StorageError::InvariantViolation(format!(
                    "reconstruction replacement {} already exists",
                    replacement.id
                )));
            }

            superseded.timestamps = superseded.timestamps.closed_at(valid_to);

            let (invalidation_record, write_record, reconstruction_record) =
                reconstruction_replacement_events(
                    event_table.len().map_err(embed)?,
                    superseded_id,
                    replacement,
                    valid_to,
                );
            let invalidation_sequence = invalidation_record.sequence;
            let write_sequence = write_record.sequence;
            let reconstruction_sequence = reconstruction_record.sequence;
            let invalidation_key = Self::event_key(invalidation_sequence);
            let write_key = Self::event_key(write_sequence);
            let reconstruction_key = Self::event_key(reconstruction_sequence);
            let invalidation_event_bytes = self.encode_json(
                StorageTableName::EventLog,
                &invalidation_key,
                &invalidation_record,
            )?;
            let write_event_bytes =
                self.encode_json(StorageTableName::EventLog, &write_key, &write_record)?;
            let reconstruction_event_bytes = self.encode_json(
                StorageTableName::EventLog,
                &reconstruction_key,
                &reconstruction_record,
            )?;
            let superseded_bytes = self.encode_json(
                StorageTableName::MemoryItems,
                superseded_key.as_bytes(),
                &superseded,
            )?;
            let replacement_bytes = self.encode_json(
                StorageTableName::MemoryItems,
                replacement_key.as_bytes(),
                replacement,
            )?;

            event_table
                .insert(invalidation_sequence, invalidation_event_bytes.as_slice())
                .map_err(embed)?;
            event_table
                .insert(write_sequence, write_event_bytes.as_slice())
                .map_err(embed)?;
            event_table
                .insert(
                    reconstruction_sequence,
                    reconstruction_event_bytes.as_slice(),
                )
                .map_err(embed)?;
            item_table
                .insert(superseded_key.as_str(), superseded_bytes.as_slice())
                .map_err(embed)?;
            item_table
                .insert(replacement_key.as_str(), replacement_bytes.as_slice())
                .map_err(embed)?;
            self.index_memory_scope(&mut scope_table, replacement)?;

            (
                invalidation_sequence,
                write_sequence,
                reconstruction_sequence,
            )
        };

        write_txn.commit().map_err(embed)?;

        let invalidation = self.event(invalidation_sequence)?.ok_or_else(|| {
            StorageError::Embedded(
                "committed reconstruction invalidation event was not readable".to_owned(),
            )
        })?;
        let replacement_write = self.event(write_sequence)?.ok_or_else(|| {
            StorageError::Embedded(
                "committed reconstruction write event was not readable".to_owned(),
            )
        })?;
        let reconstruction = self.event(reconstruction_sequence)?.ok_or_else(|| {
            StorageError::Embedded(
                "committed reconstruction marker event was not readable".to_owned(),
            )
        })?;

        Ok(Some(ReconstructionReplacementRecord {
            invalidation,
            replacement_write,
            reconstruction,
        }))
    }

    /// Writes a synthesized consolidation memory and a legible decision marker atomically.
    ///
    /// The source memories are not modified; the new memory carries its own consolidation lineage.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written, or the synthesized id already
    /// exists.
    pub fn insert_consolidated_memory(
        &self,
        item: &MemoryItem,
        pass_id: impl Into<String>,
        input_ids: Vec<MemoryId>,
        why: ConsolidationWhy,
    ) -> Result<ConsolidationDecisionRecord, StorageError> {
        let pass_id = pass_id.into();
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let (write_sequence, decision_sequence) = {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut scope_table = write_txn
                .open_table(MEMORY_SCOPE_INDEX_TABLE)
                .map_err(embed)?;
            let item_key = item.id.to_string();

            if item_table.get(item_key.as_str()).map_err(embed)?.is_some() {
                return Err(StorageError::InvariantViolation(format!(
                    "consolidated memory {} already exists",
                    item.id
                )));
            }

            let write_sequence = event_table.len().map_err(embed)?;
            let decision_sequence = write_sequence + 1;
            let recorded_at = OffsetDateTime::now_utc();
            let write_record = EventRecord {
                sequence: write_sequence,
                recorded_at,
                event: MemoryEvent::MemoryWritten {
                    item: Box::new(item.clone()),
                },
            };
            let decision_record = EventRecord {
                sequence: decision_sequence,
                recorded_at,
                event: MemoryEvent::ConsolidationDecision {
                    pass_id,
                    action: ConsolidationAction::Merge,
                    input_ids,
                    output_id: Some(item.id),
                    tier_from: None,
                    tier_to: Some(item.tier),
                    why,
                },
            };
            let write_key = Self::event_key(write_sequence);
            let decision_key = Self::event_key(decision_sequence);
            let write_bytes =
                self.encode_json(StorageTableName::EventLog, &write_key, &write_record)?;
            let decision_bytes =
                self.encode_json(StorageTableName::EventLog, &decision_key, &decision_record)?;
            let item_bytes =
                self.encode_json(StorageTableName::MemoryItems, item_key.as_bytes(), item)?;

            event_table
                .insert(write_sequence, write_bytes.as_slice())
                .map_err(embed)?;
            event_table
                .insert(decision_sequence, decision_bytes.as_slice())
                .map_err(embed)?;
            item_table
                .insert(item_key.as_str(), item_bytes.as_slice())
                .map_err(embed)?;
            self.index_memory_scope(&mut scope_table, item)?;

            (write_sequence, decision_sequence)
        };

        write_txn.commit().map_err(embed)?;

        Ok(ConsolidationDecisionRecord {
            memory_write: Some(self.event(write_sequence)?.ok_or_else(|| {
                StorageError::Embedded(
                    "committed consolidated memory write was not readable".to_owned(),
                )
            })?),
            tier_change: None,
            revalidation_flag: None,
            decision: self.event(decision_sequence)?.ok_or_else(|| {
                StorageError::Embedded(
                    "committed consolidation decision event was not readable".to_owned(),
                )
            })?,
        })
    }

    /// Applies an offline consolidation tier transition with a legible decision marker.
    ///
    /// Returns `Ok(None)` when the memory is missing or already in `tier_to`.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written.
    pub fn apply_consolidation_tier_change(
        &self,
        id: MemoryId,
        tier_to: Tier,
        pass_id: impl Into<String>,
        why: ConsolidationWhy,
    ) -> Result<Option<ConsolidationDecisionRecord>, StorageError> {
        let pass_id = pass_id.into();
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let Some((tier_sequence, decision_sequence)) =
            (|| -> Result<Option<(u64, u64)>, StorageError> {
                let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
                let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
                let key = id.to_string();
                let mut item: MemoryItem = {
                    let Some(value) = item_table.get(key.as_str()).map_err(embed)? else {
                        return Ok(None);
                    };

                    self.decode_json(StorageTableName::MemoryItems, key.as_bytes(), value.value())?
                };
                let tier_from = item.tier;

                if tier_from == tier_to {
                    return Ok(None);
                }

                item.tier = tier_to;

                let tier_sequence = event_table.len().map_err(embed)?;
                let decision_sequence = tier_sequence + 1;
                let recorded_at = OffsetDateTime::now_utc();
                let action = if tier_to > tier_from {
                    ConsolidationAction::Promote
                } else {
                    ConsolidationAction::Demote
                };
                let tier_record = EventRecord {
                    sequence: tier_sequence,
                    recorded_at,
                    event: MemoryEvent::TierChanged {
                        id,
                        from: tier_from,
                        to: tier_to,
                        cause: TierChangeCause::ConsolidationPass,
                    },
                };
                let decision_record = EventRecord {
                    sequence: decision_sequence,
                    recorded_at,
                    event: MemoryEvent::ConsolidationDecision {
                        pass_id,
                        action,
                        input_ids: vec![id],
                        output_id: None,
                        tier_from: Some(tier_from),
                        tier_to: Some(tier_to),
                        why,
                    },
                };
                let tier_key = Self::event_key(tier_sequence);
                let decision_key = Self::event_key(decision_sequence);
                let tier_bytes =
                    self.encode_json(StorageTableName::EventLog, &tier_key, &tier_record)?;
                let decision_bytes =
                    self.encode_json(StorageTableName::EventLog, &decision_key, &decision_record)?;
                let item_bytes =
                    self.encode_json(StorageTableName::MemoryItems, key.as_bytes(), &item)?;

                event_table
                    .insert(tier_sequence, tier_bytes.as_slice())
                    .map_err(embed)?;
                event_table
                    .insert(decision_sequence, decision_bytes.as_slice())
                    .map_err(embed)?;
                item_table
                    .insert(key.as_str(), item_bytes.as_slice())
                    .map_err(embed)?;

                Ok(Some((tier_sequence, decision_sequence)))
            })()?
        else {
            write_txn.commit().map_err(embed)?;
            return Ok(None);
        };

        write_txn.commit().map_err(embed)?;

        Ok(Some(ConsolidationDecisionRecord {
            memory_write: None,
            tier_change: Some(self.event(tier_sequence)?.ok_or_else(|| {
                StorageError::Embedded(
                    "committed consolidation tier event was not readable".to_owned(),
                )
            })?),
            revalidation_flag: None,
            decision: self.event(decision_sequence)?.ok_or_else(|| {
                StorageError::Embedded(
                    "committed consolidation decision event was not readable".to_owned(),
                )
            })?,
        }))
    }

    /// Flags a memory from an offline consolidation pass with a legible decision marker.
    ///
    /// Returns `Ok(None)` when the memory is missing.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written.
    pub fn flag_for_consolidation_revalidation(
        &self,
        id: MemoryId,
        flagged_at: OffsetDateTime,
        reason: impl Into<String>,
        pass_id: impl Into<String>,
        why: ConsolidationWhy,
    ) -> Result<Option<ConsolidationDecisionRecord>, StorageError> {
        let reason = reason.into();
        let pass_id = pass_id.into();
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let Some((flag_sequence, decision_sequence)) =
            (|| -> Result<Option<(u64, u64)>, StorageError> {
                let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
                let item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
                let key = id.to_string();

                if item_table.get(key.as_str()).map_err(embed)?.is_none() {
                    return Ok(None);
                }

                let flag_sequence = event_table.len().map_err(embed)?;
                let decision_sequence = flag_sequence + 1;
                let recorded_at = OffsetDateTime::now_utc();
                let flag_record = EventRecord {
                    sequence: flag_sequence,
                    recorded_at,
                    event: MemoryEvent::ReverificationFlagged {
                        id,
                        flagged_at,
                        reason,
                    },
                };
                let decision_record = EventRecord {
                    sequence: decision_sequence,
                    recorded_at,
                    event: MemoryEvent::ConsolidationDecision {
                        pass_id,
                        action: ConsolidationAction::FlagStale,
                        input_ids: vec![id],
                        output_id: None,
                        tier_from: None,
                        tier_to: None,
                        why,
                    },
                };
                let flag_key = Self::event_key(flag_sequence);
                let decision_key = Self::event_key(decision_sequence);
                let flag_bytes =
                    self.encode_json(StorageTableName::EventLog, &flag_key, &flag_record)?;
                let decision_bytes =
                    self.encode_json(StorageTableName::EventLog, &decision_key, &decision_record)?;

                event_table
                    .insert(flag_sequence, flag_bytes.as_slice())
                    .map_err(embed)?;
                event_table
                    .insert(decision_sequence, decision_bytes.as_slice())
                    .map_err(embed)?;

                Ok(Some((flag_sequence, decision_sequence)))
            })()?
        else {
            write_txn.commit().map_err(embed)?;
            return Ok(None);
        };

        write_txn.commit().map_err(embed)?;

        Ok(Some(ConsolidationDecisionRecord {
            memory_write: None,
            tier_change: None,
            revalidation_flag: Some(self.event(flag_sequence)?.ok_or_else(|| {
                StorageError::Embedded(
                    "committed consolidation flag event was not readable".to_owned(),
                )
            })?),
            decision: self.event(decision_sequence)?.ok_or_else(|| {
                StorageError::Embedded(
                    "committed consolidation decision event was not readable".to_owned(),
                )
            })?,
        }))
    }

    /// Records a human challenge by lowering credence, appending a negative usage signal, and
    /// flagging the item for review.
    ///
    /// Returns `Ok(None)` when the memory is missing.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written.
    pub fn challenge_memory(
        &self,
        id: MemoryId,
        actor: impl Into<String>,
        reason: impl Into<String>,
        timestamp: OffsetDateTime,
        policy: &dyn SignificanceFunction,
    ) -> Result<Option<HumanSignalRecord>, StorageError> {
        self.apply_human_credence_signal(
            HumanCredenceSignalInput {
                id,
                action: HumanSignalAction::Challenge,
                actor: actor.into(),
                reason: reason.into(),
                timestamp,
                outcome: AccessOutcome::Contradicted,
            },
            policy,
        )
    }

    /// Records a human affirmation by raising credence and appending a positive usage signal.
    ///
    /// Returns `Ok(None)` when the memory is missing.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written.
    pub fn affirm_memory(
        &self,
        id: MemoryId,
        actor: impl Into<String>,
        reason: impl Into<String>,
        timestamp: OffsetDateTime,
        policy: &dyn SignificanceFunction,
    ) -> Result<Option<HumanSignalRecord>, StorageError> {
        self.apply_human_credence_signal(
            HumanCredenceSignalInput {
                id,
                action: HumanSignalAction::Affirm,
                actor: actor.into(),
                reason: reason.into(),
                timestamp,
                outcome: AccessOutcome::Cited,
            },
            policy,
        )
    }

    fn apply_human_credence_signal(
        &self,
        input: HumanCredenceSignalInput,
        policy: &dyn SignificanceFunction,
    ) -> Result<Option<HumanSignalRecord>, StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let Some((access_sequence, flag_sequence, signal_sequence)) =
            (|| -> Result<Option<(u64, Option<u64>, u64)>, StorageError> {
                let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
                let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
                let key = input.id.to_string();
                let item: MemoryItem = {
                    let Some(value) = item_table.get(key.as_str()).map_err(embed)? else {
                        return Ok(None);
                    };

                    self.decode_json(StorageTableName::MemoryItems, key.as_bytes(), value.value())?
                };
                let access_sequence = event_table.len().map_err(embed)?;
                let event_set =
                    build_human_credence_event_set(access_sequence, item, input, policy);
                let signal_sequence = event_set.signal.sequence;
                let access_key = Self::event_key(access_sequence);
                let signal_key = Self::event_key(signal_sequence);
                let access_bytes =
                    self.encode_json(StorageTableName::EventLog, &access_key, &event_set.access)?;
                let signal_bytes =
                    self.encode_json(StorageTableName::EventLog, &signal_key, &event_set.signal)?;
                let item_bytes = self.encode_json(
                    StorageTableName::MemoryItems,
                    key.as_bytes(),
                    &event_set.item,
                )?;

                event_table
                    .insert(access_sequence, access_bytes.as_slice())
                    .map_err(embed)?;
                if let Some(flag_record) = &event_set.revalidation_flag {
                    let flag_key = Self::event_key(flag_record.sequence);
                    let flag_bytes =
                        self.encode_json(StorageTableName::EventLog, &flag_key, flag_record)?;

                    event_table
                        .insert(flag_record.sequence, flag_bytes.as_slice())
                        .map_err(embed)?;
                }
                event_table
                    .insert(signal_sequence, signal_bytes.as_slice())
                    .map_err(embed)?;
                item_table
                    .insert(key.as_str(), item_bytes.as_slice())
                    .map_err(embed)?;

                Ok(Some((
                    access_sequence,
                    event_set.revalidation_flag.map(|record| record.sequence),
                    signal_sequence,
                )))
            })()?
        else {
            write_txn.commit().map_err(embed)?;
            return Ok(None);
        };

        write_txn.commit().map_err(embed)?;

        Ok(Some(HumanSignalRecord {
            access: Some(self.event(access_sequence)?.ok_or_else(|| {
                StorageError::Embedded("committed human access event was not readable".to_owned())
            })?),
            revalidation_flag: flag_sequence
                .map(|sequence| {
                    self.event(sequence)?.ok_or_else(|| {
                        StorageError::Embedded(
                            "committed human review flag was not readable".to_owned(),
                        )
                    })
                })
                .transpose()?,
            signal: self.event(signal_sequence)?.ok_or_else(|| {
                StorageError::Embedded("committed human signal was not readable".to_owned())
            })?,
        }))
    }

    /// Raises or clears the credence floor from a human pin/unpin signal.
    ///
    /// Returns `Ok(None)` when the memory is missing.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written.
    pub fn set_human_credence_floor(
        &self,
        id: MemoryId,
        action: HumanSignalAction,
        actor: impl Into<String>,
        reason: impl Into<String>,
        timestamp: OffsetDateTime,
    ) -> Result<Option<HumanSignalRecord>, StorageError> {
        debug_assert!(matches!(
            action,
            HumanSignalAction::Pin | HumanSignalAction::Unpin
        ));

        let actor = actor.into();
        let reason = reason.into();
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let Some(signal_sequence) = (|| -> Result<Option<u64>, StorageError> {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let key = id.to_string();
            let mut item: MemoryItem = {
                let Some(value) = item_table.get(key.as_str()).map_err(embed)? else {
                    return Ok(None);
                };

                self.decode_json(StorageTableName::MemoryItems, key.as_bytes(), value.value())?
            };
            let previous_floor = item.credence_floor;
            let new_floor = match action {
                HumanSignalAction::Pin => item.credence_floor.max(item.tier).max(Tier::Warm),
                HumanSignalAction::Unpin => Tier::Cold,
                HumanSignalAction::Challenge
                | HumanSignalAction::Affirm
                | HumanSignalAction::Correct => item.credence_floor,
            };

            item.credence_floor = new_floor;

            let signal = HumanSignal {
                action,
                memory_id: id,
                actor,
                timestamp,
                reason,
                proposed_content: None,
                proposal_id: None,
                previous_credence: None,
                new_credence: None,
                previous_credence_floor: Some(previous_floor),
                new_credence_floor: Some(new_floor),
            };
            let signal_sequence = event_table.len().map_err(embed)?;
            let signal_record = EventRecord {
                sequence: signal_sequence,
                recorded_at: timestamp,
                event: MemoryEvent::HumanSignalRecorded { signal },
            };
            let signal_key = Self::event_key(signal_sequence);
            let signal_bytes =
                self.encode_json(StorageTableName::EventLog, &signal_key, &signal_record)?;
            let item_bytes =
                self.encode_json(StorageTableName::MemoryItems, key.as_bytes(), &item)?;

            event_table
                .insert(signal_sequence, signal_bytes.as_slice())
                .map_err(embed)?;
            item_table
                .insert(key.as_str(), item_bytes.as_slice())
                .map_err(embed)?;

            Ok(Some(signal_sequence))
        })()?
        else {
            write_txn.commit().map_err(embed)?;
            return Ok(None);
        };

        write_txn.commit().map_err(embed)?;

        Ok(Some(HumanSignalRecord {
            access: None,
            revalidation_flag: None,
            signal: self.event(signal_sequence)?.ok_or_else(|| {
                StorageError::Embedded("committed human floor signal was not readable".to_owned())
            })?,
        }))
    }

    /// Appends a human signal audit event that does not directly mutate a row.
    ///
    /// # Errors
    ///
    /// Returns an error when the event cannot be appended.
    pub fn append_human_signal(&self, signal: HumanSignal) -> Result<EventRecord, StorageError> {
        self.append_event(MemoryEvent::HumanSignalRecorded { signal })
    }

    /// Soft-invalidates an item and removes its vector from the index.
    ///
    /// # Errors
    ///
    /// Returns an error when invalidation cannot be written or the vector index cannot remove the
    /// invalidated id.
    pub fn soft_invalidate_with_vector(
        &self,
        id: MemoryId,
        valid_to: OffsetDateTime,
        vector_index: &mut dyn VectorIndex,
    ) -> Result<Option<EventRecord>, StorageError> {
        let record = self.soft_invalidate(id, valid_to)?;

        if record.is_some() {
            vector_index.delete_by_id(id).map_err(StorageError::from)?;
            self.delete_embedding(id)?;
        }

        Ok(record)
    }

    /// Appends a caller-supplied access event to a memory item.
    ///
    /// Returns `Ok(None)` when the memory id is unknown.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written, or stored state cannot be decoded.
    pub fn record_access(
        &self,
        id: MemoryId,
        access_event: AccessEvent,
    ) -> Result<Option<EventRecord>, StorageError> {
        self.record_access_with_policy(id, access_event, &SignificanceConfig::default())
    }

    /// Appends a caller-supplied access event and recomputes significance with `policy`.
    ///
    /// Returns `Ok(None)` when the memory id is unknown.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written, or stored state cannot be decoded.
    pub fn record_access_with_policy(
        &self,
        id: MemoryId,
        access_event: AccessEvent,
        policy: &dyn SignificanceFunction,
    ) -> Result<Option<EventRecord>, StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let sequence = {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let key = id.to_string();
            let mut item: MemoryItem = {
                let Some(value) = item_table.get(key.as_str()).map_err(embed)? else {
                    return Ok(None);
                };

                self.decode_json(StorageTableName::MemoryItems, key.as_bytes(), value.value())?
            };

            let previous_tier = item.tier;

            item.access_events.push(access_event.clone());
            item.significance = policy.recompute(&item, access_event.timestamp);
            item.tier = policy.promote_on_access(item.tier, item.significance);

            let recorded_at = access_event.timestamp;
            let sequence = event_table.len().map_err(embed)?;
            let record = EventRecord {
                sequence,
                recorded_at,
                event: MemoryEvent::AccessRecorded {
                    id,
                    event: access_event,
                },
            };
            let event_key = Self::event_key(sequence);
            let event_bytes = self.encode_json(StorageTableName::EventLog, &event_key, &record)?;
            let item_bytes =
                self.encode_json(StorageTableName::MemoryItems, key.as_bytes(), &item)?;

            event_table
                .insert(sequence, event_bytes.as_slice())
                .map_err(embed)?;

            if item.tier != previous_tier {
                let tier_sequence = sequence + 1;
                let tier_record = EventRecord {
                    sequence: tier_sequence,
                    recorded_at,
                    event: MemoryEvent::TierChanged {
                        id,
                        from: previous_tier,
                        to: item.tier,
                        cause: TierChangeCause::AccessReinforcement,
                    },
                };
                let tier_key = Self::event_key(tier_sequence);
                let tier_event_bytes =
                    self.encode_json(StorageTableName::EventLog, &tier_key, &tier_record)?;

                event_table
                    .insert(tier_sequence, tier_event_bytes.as_slice())
                    .map_err(embed)?;
            }

            item_table
                .insert(key.as_str(), item_bytes.as_slice())
                .map_err(embed)?;

            sequence
        };

        write_txn.commit().map_err(embed)?;

        self.event(sequence)?
            .ok_or_else(|| {
                StorageError::Embedded("committed access event was not readable".to_owned())
            })
            .map(Some)
    }

    /// Appends an outcome signal to a memory item.
    ///
    /// Returns `Ok(None)` when the memory id is unknown.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written, or stored state cannot be decoded.
    pub fn reinforce(
        &self,
        id: MemoryId,
        outcome: crate::model::AccessOutcome,
    ) -> Result<Option<EventRecord>, StorageError> {
        self.record_access(
            id,
            AccessEvent::new(OffsetDateTime::now_utc(), None, outcome),
        )
    }

    /// Records that a memory was contradicted by a newer observation.
    ///
    /// # Errors
    ///
    /// Returns an error when the contradiction event cannot be durably recorded.
    pub fn record_contradiction(&self, id: MemoryId) -> Result<Option<EventRecord>, StorageError> {
        self.reinforce(id, crate::model::AccessOutcome::Contradicted)
    }

    /// Lazily recomputes significance and applies decay-based tier demotion.
    ///
    /// Returns `Ok(None)` when the memory id is unknown.
    ///
    /// # Errors
    ///
    /// Returns an error when current item state or a tier-transition event cannot be read,
    /// decoded, or written.
    pub fn refresh_significance(
        &self,
        id: MemoryId,
        policy: &dyn SignificanceFunction,
        now: OffsetDateTime,
    ) -> Result<Option<MemoryItem>, StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        let refreshed = {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let key = id.to_string();
            let mut item: MemoryItem = {
                let Some(value) = item_table.get(key.as_str()).map_err(embed)? else {
                    return Ok(None);
                };

                self.decode_json(StorageTableName::MemoryItems, key.as_bytes(), value.value())?
            };
            let previous_tier = item.tier;

            item.significance = policy.recompute(&item, now);
            let demoted = policy.demote_for_score(item.tier, item.significance);
            item.tier = policy.clamp_tier_to_credence_floor(&item, demoted);

            let bytes = self.encode_json(StorageTableName::MemoryItems, key.as_bytes(), &item)?;

            if item.tier != previous_tier {
                let sequence = event_table.len().map_err(embed)?;
                let record = EventRecord {
                    sequence,
                    recorded_at: now,
                    event: MemoryEvent::TierChanged {
                        id,
                        from: previous_tier,
                        to: item.tier,
                        cause: TierChangeCause::SignificanceRefresh,
                    },
                };
                let event_key = Self::event_key(sequence);
                let event_bytes =
                    self.encode_json(StorageTableName::EventLog, &event_key, &record)?;

                event_table
                    .insert(sequence, event_bytes.as_slice())
                    .map_err(embed)?;
            }

            item_table
                .insert(key.as_str(), bytes.as_slice())
                .map_err(embed)?;

            item
        };

        write_txn.commit().map_err(embed)?;

        Ok(Some(refreshed))
    }

    /// Explains the current significance score for an item.
    ///
    /// Returns `Ok(None)` when the memory id is unknown.
    ///
    /// # Errors
    ///
    /// Returns an error when current item state cannot be read or decoded.
    pub fn explain_significance(
        &self,
        id: MemoryId,
        policy: &dyn SignificanceFunction,
        now: OffsetDateTime,
    ) -> Result<Option<SignificanceBreakdown>, StorageError> {
        self.get(id)
            .map(|maybe_item| maybe_item.map(|item| policy.explain(&item, now)))
    }

    /// Computes a graph-centrality score for memory-backed relations.
    ///
    /// The score is the natural log of one plus the number of distinct entities touched by
    /// relations citing `id`.
    ///
    /// # Errors
    ///
    /// Returns an error when graph relation rows cannot be read or decoded.
    pub fn graph_centrality_for_memory(&self, id: MemoryId) -> Result<f64, StorageError> {
        let mut entity_ids = BTreeSet::new();

        for relation in self.graph_relations()? {
            if relation.memory_id == Some(id) {
                entity_ids.insert(relation.from_entity);
                entity_ids.insert(relation.to_entity);
            }
        }

        let degree = u32::try_from(entity_ids.len()).unwrap_or(u32::MAX);

        Ok(f64::from(degree).ln_1p())
    }

    /// Explains significance with graph centrality supplied from memory-backed relations.
    ///
    /// Returns `Ok(None)` when the memory id is unknown.
    ///
    /// # Errors
    ///
    /// Returns an error when current item state or graph relation rows cannot be read or decoded.
    pub fn explain_significance_with_graph_centrality(
        &self,
        id: MemoryId,
        policy: SignificanceConfig,
        now: OffsetDateTime,
    ) -> Result<Option<SignificanceBreakdown>, StorageError> {
        let Some(item) = self.get(id)? else {
            return Ok(None);
        };
        let graph_centrality = self.graph_centrality_for_memory(id)?;

        Ok(Some(policy.explain_with_graph_centrality(
            &item,
            now,
            graph_centrality,
        )))
    }

    /// Enforces configured tier capacity limits by demoting the least-significant hot items.
    ///
    /// Hot-tier capacity is optional. When configured and the hot tier is over budget, this method
    /// demotes the lowest-significance hot memories to warm and appends one `TierChanged` event for
    /// each demotion. It never deletes rows or event history.
    ///
    /// # Errors
    ///
    /// Returns an error when materialized state cannot be read, decoded, updated, or logged.
    pub fn enforce_tier_capacity(
        &self,
        config: TierCapacityConfig,
    ) -> Result<Vec<MemoryId>, StorageError> {
        let Some(hot_capacity) = config.hot_capacity else {
            return Ok(Vec::new());
        };
        let mut hot_items = self
            .materialized_items()?
            .into_iter()
            .filter(|item| item.tier == Tier::Hot)
            .collect::<Vec<_>>();

        if hot_items.len() <= hot_capacity {
            return Ok(Vec::new());
        }

        hot_items.sort_by(|left, right| {
            left.significance
                .total_cmp(&right.significance)
                .then_with(|| left.id.cmp(&right.id))
        });

        let demotion_count = hot_items.len() - hot_capacity;
        let victims = hot_items
            .into_iter()
            .take(demotion_count)
            .map(|item| item.id)
            .collect::<Vec<_>>();
        let mut demoted = Vec::with_capacity(victims.len());
        let mut write_txn = self.db.begin_write().map_err(embed)?;

        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;

        {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut next_sequence = event_table.len().map_err(embed)?;

            for id in victims {
                let key = id.to_string();
                let mut item: MemoryItem = {
                    let Some(value) = item_table.get(key.as_str()).map_err(embed)? else {
                        continue;
                    };

                    self.decode_json(StorageTableName::MemoryItems, key.as_bytes(), value.value())?
                };

                if item.tier != Tier::Hot {
                    continue;
                }

                item.tier = Tier::Warm;

                let event_record = EventRecord {
                    sequence: next_sequence,
                    recorded_at: OffsetDateTime::now_utc(),
                    event: MemoryEvent::TierChanged {
                        id,
                        from: Tier::Hot,
                        to: Tier::Warm,
                        cause: TierChangeCause::CapacityEnforcement,
                    },
                };
                let event_key = Self::event_key(next_sequence);
                let event_bytes =
                    self.encode_json(StorageTableName::EventLog, &event_key, &event_record)?;
                let item_bytes =
                    self.encode_json(StorageTableName::MemoryItems, key.as_bytes(), &item)?;

                event_table
                    .insert(next_sequence, event_bytes.as_slice())
                    .map_err(embed)?;
                item_table
                    .insert(key.as_str(), item_bytes.as_slice())
                    .map_err(embed)?;

                next_sequence += 1;
                demoted.push(id);
            }
        }

        write_txn.commit().map_err(embed)?;

        Ok(demoted)
    }

    /// Compacts inline content for a cold-tier item into compressed storage.
    ///
    /// Returns `Ok(false)` when the item is missing, is not cold, or is already compacted.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read or written, serialization fails, or compressed
    /// content cannot be represented.
    pub fn compact_cold_item(&self, id: MemoryId) -> Result<bool, StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut cold_table = write_txn.open_table(COLD_CONTENT_TABLE).map_err(embed)?;
            let key = id.to_string();
            let mut item: MemoryItem = {
                let Some(value) = item_table.get(key.as_str()).map_err(embed)? else {
                    return Ok(false);
                };

                self.decode_json(StorageTableName::MemoryItems, key.as_bytes(), value.value())?
            };

            if item.tier != Tier::Cold || item.compaction.is_some() {
                return Ok(false);
            }

            let content_bytes = item.content.as_bytes();
            let compressed = compress_prepend_size(content_bytes);
            let pointer = CompactionRef {
                codec: LZ4_SIZE_PREPENDED.to_owned(),
                storage_key: key.clone(),
                original_bytes: u64::try_from(content_bytes.len()).map_err(compression)?,
                compressed_bytes: u64::try_from(compressed.len()).map_err(compression)?,
            };
            let sequence = event_table.len().map_err(embed)?;
            let record = EventRecord {
                sequence,
                recorded_at: OffsetDateTime::now_utc(),
                event: MemoryEvent::ContentCompacted {
                    id,
                    pointer: pointer.clone(),
                },
            };

            item.content.clear();
            item.compaction = Some(pointer);

            let event_key = Self::event_key(sequence);
            let event_bytes = self.encode_json(StorageTableName::EventLog, &event_key, &record)?;
            let item_bytes =
                self.encode_json(StorageTableName::MemoryItems, key.as_bytes(), &item)?;
            let cold_content = StoredColdContent {
                scope: item.scope.clone(),
                compressed,
            };
            let cold_bytes =
                self.encode_json(StorageTableName::ColdContent, key.as_bytes(), &cold_content)?;

            cold_table
                .insert(key.as_str(), cold_bytes.as_slice())
                .map_err(embed)?;
            event_table
                .insert(sequence, event_bytes.as_slice())
                .map_err(embed)?;
            item_table
                .insert(key.as_str(), item_bytes.as_slice())
                .map_err(embed)?;
        }

        write_txn.commit().map_err(embed)?;

        Ok(true)
    }

    /// Reads and decompresses content referenced by a compaction pointer.
    ///
    /// # Errors
    ///
    /// Returns an error when storage cannot be read, decompression fails, or the content is not
    /// valid UTF-8.
    pub fn read_compacted_content(
        &self,
        pointer: &CompactionRef,
    ) -> Result<Option<String>, StorageError> {
        if pointer.codec != LZ4_SIZE_PREPENDED {
            return Err(StorageError::Compression(format!(
                "unsupported codec {}",
                pointer.codec
            )));
        }

        let read_txn = self.db.begin_read().map_err(embed)?;
        let table = match read_txn.open_table(COLD_CONTENT_TABLE) {
            Ok(table) => table,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(None),
            Err(error) => return Err(embed(error)),
        };
        let Some(value) = table.get(pointer.storage_key.as_str()).map_err(embed)? else {
            return Ok(None);
        };
        let stored: StoredColdContent = self.decode_json(
            StorageTableName::ColdContent,
            pointer.storage_key.as_bytes(),
            value.value(),
        )?;
        stored
            .scope
            .validate()
            .map_err(|error| StorageError::InvariantViolation(error.to_string()))?;
        let decompressed = decompress_size_prepended(&stored.compressed).map_err(compression)?;
        let content = String::from_utf8(decompressed).map_err(compression)?;

        Ok(Some(content))
    }
}

impl MemoryStore for RedbMemoryStore {
    fn append_event(&self, event: MemoryEvent) -> Result<EventRecord, StorageError> {
        RedbMemoryStore::append_event(self, event)
    }

    fn write(&self, item: &MemoryItem) -> Result<EventRecord, StorageError> {
        RedbMemoryStore::write(self, item)
    }

    fn write_event(
        &self,
        event: MemoryWriteEvent,
    ) -> Result<(EventRecord, MemoryItem), StorageError> {
        RedbMemoryStore::write_event(self, event)
    }

    fn write_event_with_policy(
        &self,
        event: MemoryWriteEvent,
        policy: IngestCredencePolicy,
    ) -> Result<(EventRecord, MemoryItem), StorageError> {
        RedbMemoryStore::write_event_with_policy(self, event, policy)
    }

    fn get(&self, id: MemoryId) -> Result<Option<MemoryItem>, StorageError> {
        RedbMemoryStore::get(self, id)
    }

    fn get_many(&self, ids: &[MemoryId]) -> Result<Vec<Option<MemoryItem>>, StorageError> {
        RedbMemoryStore::get_many(self, ids)
    }

    fn soft_invalidate(
        &self,
        id: MemoryId,
        valid_to: OffsetDateTime,
    ) -> Result<Option<EventRecord>, StorageError> {
        RedbMemoryStore::soft_invalidate(self, id, valid_to)
    }

    fn flag_for_reverification(
        &self,
        id: MemoryId,
        flagged_at: OffsetDateTime,
        reason: String,
    ) -> Result<Option<EventRecord>, StorageError> {
        RedbMemoryStore::flag_for_reverification(self, id, flagged_at, reason)
    }

    fn insert_reconstruction_replacement(
        &self,
        superseded_id: MemoryId,
        replacement: &MemoryItem,
        valid_to: OffsetDateTime,
    ) -> Result<Option<ReconstructionReplacementRecord>, StorageError> {
        RedbMemoryStore::insert_reconstruction_replacement(
            self,
            superseded_id,
            replacement,
            valid_to,
        )
    }

    fn events(&self) -> Result<Vec<EventRecord>, StorageError> {
        RedbMemoryStore::events(self)
    }
}

const fn lower_credence(credence: CredenceTier) -> CredenceTier {
    match credence {
        CredenceTier::FirmAuthoritative => CredenceTier::VerifiedSource,
        CredenceTier::VerifiedSource => CredenceTier::ModelInferred,
        CredenceTier::ModelInferred | CredenceTier::Unverified => CredenceTier::Unverified,
    }
}

const fn raise_credence(credence: CredenceTier) -> CredenceTier {
    match credence {
        CredenceTier::Unverified => CredenceTier::ModelInferred,
        CredenceTier::ModelInferred => CredenceTier::VerifiedSource,
        CredenceTier::VerifiedSource | CredenceTier::FirmAuthoritative => {
            CredenceTier::FirmAuthoritative
        }
    }
}

fn build_human_credence_event_set(
    access_sequence: u64,
    mut item: MemoryItem,
    input: HumanCredenceSignalInput,
    policy: &dyn SignificanceFunction,
) -> HumanCredenceEventSet {
    let previous_credence = item.credence;
    let new_credence = match input.action {
        HumanSignalAction::Challenge => lower_credence(item.credence),
        HumanSignalAction::Affirm => raise_credence(item.credence),
        HumanSignalAction::Correct | HumanSignalAction::Pin | HumanSignalAction::Unpin => {
            item.credence
        }
    };
    let access_event = AccessEvent::new(input.timestamp, None, input.outcome);

    item.credence = new_credence;
    item.access_events.push(access_event.clone());
    item.significance = policy.recompute(&item, input.timestamp);

    let access = EventRecord {
        sequence: access_sequence,
        recorded_at: input.timestamp,
        event: MemoryEvent::AccessRecorded {
            id: input.id,
            event: access_event,
        },
    };
    let revalidation_flag = human_challenge_flag(access_sequence, &input);
    let signal_sequence = access_sequence + 1 + u64::from(revalidation_flag.is_some());
    let signal = HumanSignal {
        action: input.action,
        memory_id: input.id,
        actor: input.actor,
        timestamp: input.timestamp,
        reason: input.reason,
        proposed_content: None,
        proposal_id: None,
        previous_credence: Some(previous_credence),
        new_credence: Some(new_credence),
        previous_credence_floor: None,
        new_credence_floor: None,
    };
    let signal = EventRecord {
        sequence: signal_sequence,
        recorded_at: signal.timestamp,
        event: MemoryEvent::HumanSignalRecorded { signal },
    };

    HumanCredenceEventSet {
        item,
        access,
        revalidation_flag,
        signal,
    }
}

fn human_challenge_flag(
    access_sequence: u64,
    input: &HumanCredenceSignalInput,
) -> Option<EventRecord> {
    (input.action == HumanSignalAction::Challenge).then(|| EventRecord {
        sequence: access_sequence + 1,
        recorded_at: input.timestamp,
        event: MemoryEvent::ReverificationFlagged {
            id: input.id,
            flagged_at: input.timestamp,
            reason: format!("human-challenge: {}", input.reason),
        },
    })
}

fn push_credence_audit_entry(
    entries: &mut Vec<MemoryAuditEntry>,
    record: &EventRecord,
    memory_id: MemoryId,
    scope: &MemoryScope,
    from: Option<CredenceTier>,
    to: CredenceTier,
    cause: MemoryAuditCause,
) {
    entries.push(MemoryAuditEntry {
        sequence: record.sequence,
        recorded_at: record.recorded_at,
        memory_id,
        scope: scope.clone(),
        change: MemoryAuditChange::Credence { from, to },
        cause,
    });
}

fn push_tier_audit_entry(
    entries: &mut Vec<MemoryAuditEntry>,
    record: &EventRecord,
    memory_id: MemoryId,
    scope: &MemoryScope,
    from: Option<Tier>,
    to: Tier,
    cause: MemoryAuditCause,
) {
    entries.push(MemoryAuditEntry {
        sequence: record.sequence,
        recorded_at: record.recorded_at,
        memory_id,
        scope: scope.clone(),
        change: MemoryAuditChange::Tier { from, to },
        cause,
    });
}

fn push_floor_audit_entry(
    entries: &mut Vec<MemoryAuditEntry>,
    record: &EventRecord,
    memory_id: MemoryId,
    scope: &MemoryScope,
    from: Option<Tier>,
    to: Tier,
    cause: MemoryAuditCause,
) {
    entries.push(MemoryAuditEntry {
        sequence: record.sequence,
        recorded_at: record.recorded_at,
        memory_id,
        scope: scope.clone(),
        change: MemoryAuditChange::CredenceFloor { from, to },
        cause,
    });
}

fn reconstruction_replacement_events(
    first_sequence: u64,
    superseded_id: MemoryId,
    replacement: &MemoryItem,
    valid_to: OffsetDateTime,
) -> (EventRecord, EventRecord, EventRecord) {
    let recorded_at = OffsetDateTime::now_utc();
    let invalidation = EventRecord {
        sequence: first_sequence,
        recorded_at,
        event: MemoryEvent::MemoryInvalidated {
            id: superseded_id,
            valid_to,
        },
    };
    let replacement_write = EventRecord {
        sequence: first_sequence + 1,
        recorded_at,
        event: MemoryEvent::MemoryWritten {
            item: Box::new(replacement.clone()),
        },
    };
    let reconstruction = EventRecord {
        sequence: first_sequence + 2,
        recorded_at,
        event: MemoryEvent::ReconstructionApplied {
            superseded_id,
            replacement_id: replacement.id,
            valid_to,
        },
    };

    (invalidation, replacement_write, reconstruction)
}

fn embed(error: impl std::error::Error) -> StorageError {
    StorageError::Embedded(error.to_string())
}

fn validate_event_schema_version(record: &EventRecord) -> Result<(), StorageError> {
    if let MemoryEvent::MemoryWritten { item } = &record.event {
        validate_memory_schema_version(
            &format!("event {} memory {}", record.sequence, item.id),
            item.schema_version,
        )?;
    }

    Ok(())
}

fn validate_memory_schema_version(record: &str, found: u16) -> Result<(), StorageError> {
    // v2 migrations should branch here before decoded state is exposed.
    if found == CURRENT_MEMORY_SCHEMA_VERSION {
        return Ok(());
    }

    Err(StorageError::SchemaVersionMismatch {
        record: record.to_owned(),
        expected: CURRENT_MEMORY_SCHEMA_VERSION,
        found,
    })
}

fn event_belongs_to_memory_ids(
    record: &EventRecord,
    memory_ids: &BTreeSet<MemoryId>,
    scope: &MemoryScope,
) -> bool {
    match &record.event {
        MemoryEvent::MemoryWritten { item } => {
            item.scope == *scope && memory_ids.contains(&item.id)
        }
        MemoryEvent::MemoryInvalidated { id, .. }
        | MemoryEvent::ReverificationFlagged { id, .. }
        | MemoryEvent::AccessRecorded { id, .. }
        | MemoryEvent::TierChanged { id, .. }
        | MemoryEvent::ContentCompacted { id, .. } => memory_ids.contains(id),
        MemoryEvent::ReconstructionApplied {
            superseded_id,
            replacement_id,
            ..
        } => memory_ids.contains(superseded_id) && memory_ids.contains(replacement_id),
        MemoryEvent::ConsolidationDecision {
            input_ids,
            output_id,
            ..
        } => {
            input_ids.iter().all(|id| memory_ids.contains(id))
                && output_id.is_none_or(|id| memory_ids.contains(&id))
        }
        MemoryEvent::HumanSignalRecorded { signal } => {
            memory_ids.contains(&signal.memory_id)
                && signal.proposal_id.is_none_or(|id| memory_ids.contains(&id))
        }
        MemoryEvent::MemoryScopePromoted {
            source_id,
            promoted_id,
            ..
        } => memory_ids.contains(source_id) || memory_ids.contains(promoted_id),
        MemoryEvent::ScopeAuthorizationDenied {
            source_scope,
            target_scope,
            ..
        } => source_scope == scope || target_scope == scope,
        MemoryEvent::PolicyDecisionRecorded { record } => record
            .scope
            .as_ref()
            .is_some_and(|record_scope| record_scope == scope),
        MemoryEvent::ReviewCandidateQueued { candidate } => {
            candidate.candidate.suggested_scope == *scope
        }
        MemoryEvent::ReviewDecisionRecorded { decision } => decision.scope == *scope,
        MemoryEvent::AutomaticCaptureRecorded { record } => record.scope == *scope,
        MemoryEvent::ObservabilityRecorded { record } => record
            .scope
            .as_ref()
            .is_some_and(|record_scope| record_scope == scope),
    }
}

fn review_storage_error(error: ReviewError) -> StorageError {
    StorageError::InvariantViolation(error.to_string())
}

fn compression(error: impl std::fmt::Display) -> StorageError {
    StorageError::Compression(error.to_string())
}

fn entity_believed_at(entity: &Entity, as_of: OffsetDateTime) -> bool {
    entity.timestamps.ingested_at <= as_of && entity.timestamps.is_valid_at(as_of)
}

fn relation_believed_at(relation: &Relation, as_of: OffsetDateTime) -> bool {
    relation.timestamps.ingested_at <= as_of && relation.timestamps.is_valid_at(as_of)
}

fn relation_touches_entity(relation: &Relation, entity_id: EntityId) -> bool {
    relation.from_entity == entity_id || relation.to_entity == entity_id
}

fn relation_matches_traversal(relation: &Relation, request: &GraphTraversalRequest) -> bool {
    let type_allowed = request.relation_types.is_empty()
        || request.relation_types.contains(&relation.relation_type);
    let time_allowed = request
        .as_of
        .is_none_or(|instant| relation_believed_at(relation, instant));

    type_allowed
        && time_allowed
        && request
            .scope
            .as_ref()
            .is_none_or(|scope| relation.scope == *scope)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::encryption::{
        Aes256GcmEncryption, EnvelopeEncryption, LocalKeyProvider, envelope_key_metadata,
    };
    use crate::model::{
        AccessOutcome, CURRENT_MEMORY_SCHEMA_VERSION, CredenceTier, Provenance, ScopeId,
        SourceKind, TemporalBounds,
    };
    use crate::vector::{HnswVectorIndex, VectorIndex};
    use proptest::prelude::*;
    use std::sync::{Arc, Barrier};
    use std::thread;
    use tempfile::NamedTempFile;
    use tempfile::tempdir;
    use time::Duration;

    fn test_item(content: &str) -> MemoryItem {
        MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            scope: MemoryScope::default(),
            id: MemoryId::new_v7(),
            content: content.to_owned(),
            kind: MemoryKind::Fact,
            compaction: None,
            consolidation: None,
            promotion: None,
            embedding_ref: None,
            provenance: Provenance::new(SourceKind::User, None, "storage-test"),
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

    struct FailingEmbeddedWrite;

    impl StorageFaultInjector for FailingEmbeddedWrite {
        fn check(&self, stage: StorageFaultStage) -> Result<(), StorageError> {
            assert_eq!(stage, StorageFaultStage::EmbeddedWrite);
            Err(StorageError::Embedded(
                "injected durable write failure".to_owned(),
            ))
        }
    }

    #[test]
    fn injected_durable_write_failure_rolls_back_vector_and_persisted_state() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let mut item = test_item("failed durable write");

        let error = store
            .write_embedded_with_fault_injector(
                &mut item,
                &mut vector_index,
                &[0.0, 0.0],
                "test",
                "model",
                "v1",
                Some(&FailingEmbeddedWrite),
            )
            .expect_err("injected durable write should fail");

        assert!(
            matches!(error, StorageError::Embedded(message) if message == "injected durable write failure")
        );
        assert!(store.memory_items().expect("items should read").is_empty());
        assert!(store.events().expect("events should read").is_empty());
        assert!(
            store
                .stored_embeddings()
                .expect("embeddings should read")
                .is_empty()
        );
        assert!(
            vector_index
                .search(&[0.0, 0.0], 1)
                .expect("vector index should remain readable")
                .is_empty()
        );
    }

    #[test]
    fn scope_index_persists_memory_ids_with_the_source_event() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let scope = MemoryScope::team(
            ScopeId::new("repo-scope").expect("repository should validate"),
            ScopeId::new("team-scope").expect("team should validate"),
        );
        let event = MemoryWriteEvent::new(
            "scoped memory",
            Provenance::new(SourceKind::User, None, "scope-test"),
            OffsetDateTime::UNIX_EPOCH,
            OffsetDateTime::UNIX_EPOCH,
        )
        .with_scope(scope.clone());
        let (record, item) = store.write_event(event).expect("write should succeed");

        assert!(matches!(record.event, MemoryEvent::MemoryWritten { .. }));
        assert_eq!(
            store
                .memory_ids_in_scope(&scope)
                .expect("index should read"),
            [item.id]
        );
        assert!(
            store
                .memory_ids_in_scope(&MemoryScope::default())
                .expect("other index should read")
                .is_empty()
        );
    }

    #[test]
    fn scoped_snapshot_excludes_other_memory_scopes() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let snapshot_file = NamedTempFile::new().expect("snapshot file should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let scope = MemoryScope::repository(
            ScopeId::new("snapshot-repo-a").expect("scope should validate"),
        );
        let other_scope = MemoryScope::repository(
            ScopeId::new("snapshot-repo-b").expect("scope should validate"),
        );
        let (_, included) = store
            .write_event(
                MemoryWriteEvent::new(
                    "included",
                    Provenance::new(SourceKind::User, None, "snapshot-test"),
                    OffsetDateTime::UNIX_EPOCH,
                    OffsetDateTime::UNIX_EPOCH,
                )
                .with_scope(scope.clone()),
            )
            .expect("included write should work");
        store
            .write_event(
                MemoryWriteEvent::new(
                    "excluded",
                    Provenance::new(SourceKind::User, None, "snapshot-test"),
                    OffsetDateTime::UNIX_EPOCH,
                    OffsetDateTime::UNIX_EPOCH,
                )
                .with_scope(other_scope),
            )
            .expect("excluded write should work");

        store
            .snapshot_scope(snapshot_file.path(), &scope)
            .expect("scoped snapshot should write");
        let snapshot: StoreSnapshot = serde_json::from_slice(
            &std::fs::read(snapshot_file.path()).expect("snapshot should read"),
        )
        .expect("snapshot should decode");

        assert_eq!(snapshot.scope, Some(scope));
        assert_eq!(snapshot.materialized_items.len(), 1);
        assert_eq!(snapshot.materialized_items[0].id, included.id);
        assert_eq!(snapshot.events.len(), 1);
    }

    #[test]
    fn graph_relations_reject_cross_scope_endpoints_and_traversal_is_filtered() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let timestamps =
            TemporalBounds::open_from(OffsetDateTime::UNIX_EPOCH, OffsetDateTime::UNIX_EPOCH);
        let scope =
            MemoryScope::repository(ScopeId::new("graph-repo-a").expect("scope should validate"));
        let other_scope =
            MemoryScope::repository(ScopeId::new("graph-repo-b").expect("scope should validate"));
        let source =
            Entity::new("Project", "source", "source", timestamps).with_scope(scope.clone());
        let target =
            Entity::new("Project", "target", "target", timestamps).with_scope(scope.clone());
        let outside =
            Entity::new("Project", "outside", "outside", timestamps).with_scope(other_scope);
        store.put_entity(&source).expect("source should write");
        store.put_entity(&target).expect("target should write");
        store.put_entity(&outside).expect("outside should write");

        let valid_relation = Relation::new("supports", source.id, target.id, None, timestamps)
            .with_scope(scope.clone());
        store
            .put_relation(&valid_relation)
            .expect("same-scope relation should write");
        let cross_scope = Relation::new("supports", source.id, outside.id, None, timestamps)
            .with_scope(scope.clone());
        assert!(matches!(
            store.put_relation(&cross_scope),
            Err(StorageError::InvariantViolation(message)) if message.contains("both endpoint")
        ));

        let snapshot = store
            .graph_snapshot_in_scope(OffsetDateTime::UNIX_EPOCH, &scope)
            .expect("scoped snapshot should read");
        assert_eq!(snapshot.entities.len(), 2);
        assert_eq!(snapshot.relations, vec![valid_relation.clone()]);
        let traversed = store
            .traverse_graph(&GraphTraversalRequest::new(source.id, 1).with_scope(scope.clone()))
            .expect("scoped traversal should read");
        assert_eq!(traversed.entities.len(), 2);
        assert_eq!(traversed.relations, vec![valid_relation]);
    }

    fn test_entity(label: &str, timestamps: TemporalBounds) -> Entity {
        Entity::new("Claim", label, format!("claim:{label}"), timestamps)
    }

    proptest! {
        #[test]
        fn never_delete_invariant_survives_generated_memory_operations(
            operations in proptest::collection::vec(0_u8..=255, 1..32)
        ) {
            let file = NamedTempFile::new().expect("tempfile should be created");
            let store = RedbMemoryStore::open(file.path()).expect("store should open");
            let mut ids = Vec::<MemoryId>::new();
            let policy = SignificanceConfig::default();

            for (index, operation) in operations.into_iter().enumerate() {
                match operation % 5 {
                    op if ids.is_empty() || op == 0 => {
                        let mut item = test_item(&format!("generated memory {index}"));
                        item.tier = if operation % 2 == 0 { Tier::Cold } else { Tier::Warm };
                        item.credence_floor = Tier::Cold;
                        store.write(&item).expect("write should succeed");
                        ids.push(item.id);
                    }
                    1 => {
                        let id = ids[usize::from(operation) % ids.len()];
                        store
                            .record_access(
                                id,
                                AccessEvent::new(
                                    OffsetDateTime::UNIX_EPOCH
                                        + Duration::seconds(i64::try_from(index).unwrap_or(i64::MAX)),
                                    None,
                                    AccessOutcome::Surfaced,
                                ),
                            )
                            .expect("access should record");
                    }
                    2 => {
                        let id = ids[usize::from(operation) % ids.len()];
                        store
                            .refresh_significance(
                                id,
                                &policy,
                                OffsetDateTime::UNIX_EPOCH
                                    + Duration::seconds(i64::try_from(index).unwrap_or(i64::MAX)),
                            )
                            .expect("refresh should succeed");
                    }
                    3 => {
                        let id = ids[usize::from(operation) % ids.len()];
                        store
                            .soft_invalidate(
                                id,
                                OffsetDateTime::UNIX_EPOCH
                                    + Duration::seconds(i64::try_from(index + 1).unwrap_or(i64::MAX)),
                            )
                            .expect("invalidate should succeed");
                    }
                    _ => {
                        let id = ids[usize::from(operation) % ids.len()];
                        store.compact_cold_item(id).expect("compaction should not delete");
                    }
                }

                let report = store
                    .verify_never_delete_invariant()
                    .expect("never-delete invariant should hold");
                prop_assert_eq!(
                    report.written_item_count,
                    ids.iter().copied().collect::<BTreeSet<_>>().len()
                );
            }
        }
    }

    fn graph_snapshot_ids(snapshot: &GraphSnapshot) -> (BTreeSet<EntityId>, BTreeSet<RelationId>) {
        let entity_ids = snapshot
            .entities
            .iter()
            .map(|entity| entity.id)
            .collect::<BTreeSet<_>>();
        let relation_ids = snapshot
            .relations
            .iter()
            .map(|relation| relation.id)
            .collect::<BTreeSet<_>>();

        (entity_ids, relation_ids)
    }

    fn assert_memory_ids_survive(
        store: &RedbMemoryStore,
        ids: &[MemoryId],
    ) -> NeverDeleteInvariantReport {
        let report = store
            .verify_never_delete_invariant()
            .expect("never-delete invariant should hold");

        for id in ids {
            assert!(
                store.get(*id).expect("memory row should read").is_some(),
                "memory {id} should remain materialized"
            );
        }

        assert_eq!(report.materialized_item_count, ids.len());
        assert_eq!(report.written_item_count, ids.len());

        report
    }

    #[test]
    fn append_only_event_log_replays_after_reopen() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let path = file.path();
        let first_item = test_item("first");
        let second_item = test_item("second");

        {
            let store = RedbMemoryStore::open(path).expect("store should open");

            let first = store
                .append_event(MemoryEvent::MemoryWritten {
                    item: Box::new(first_item.clone()),
                })
                .expect("first event should append");
            let second = store
                .append_event(MemoryEvent::MemoryWritten {
                    item: Box::new(second_item.clone()),
                })
                .expect("second event should append");

            assert_eq!(first.sequence, 0);
            assert_eq!(second.sequence, 1);
        }

        let reopened = RedbMemoryStore::open(path).expect("store should reopen");
        let events = reopened.events().expect("events should replay");

        assert_eq!(events.len(), 2);
        assert_eq!(
            events[0].event,
            MemoryEvent::MemoryWritten {
                item: Box::new(first_item)
            }
        );
        assert_eq!(
            events[1].event,
            MemoryEvent::MemoryWritten {
                item: Box::new(second_item)
            }
        );
    }

    #[test]
    fn materialized_item_table_persists_current_state() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let path = file.path();
        let mut item = test_item("current");
        let item_id = item.id;

        {
            let store = RedbMemoryStore::open(path).expect("store should open");

            store
                .put_materialized_item(&item)
                .expect("item should materialize");

            item.significance = 2.0;
            store
                .put_materialized_item(&item)
                .expect("item should update materialized state");
        }

        let reopened = RedbMemoryStore::open(path).expect("store should reopen");
        let stored = reopened
            .materialized_item(item_id)
            .expect("item should read")
            .expect("item should exist");

        assert!((stored.significance - 2.0).abs() < f64::EPSILON);
        assert_eq!(stored.content, "current");
    }

    #[test]
    fn write_appends_event_and_updates_materialized_state() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("write-through");
        let item_id = item.id;

        let record = store.write(&item).expect("item should write");

        assert_eq!(record.sequence, 0);
        assert_eq!(
            record.event,
            MemoryEvent::MemoryWritten {
                item: Box::new(item.clone())
            }
        );

        let events = store.events().expect("events should read");
        let stored = store
            .materialized_item(item_id)
            .expect("item should read")
            .expect("item should exist");

        assert_eq!(events.len(), 1);
        assert_eq!(stored, item);
    }

    #[test]
    fn write_event_ingests_memory_with_mandatory_provenance() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let provenance = Provenance::new(
            SourceKind::File,
            Some("/repo/README.md".to_owned()),
            "ingest-test",
        );
        let event = MemoryWriteEvent::with_explicit_credence(
            "ingested from file",
            provenance.clone(),
            OffsetDateTime::UNIX_EPOCH,
            OffsetDateTime::UNIX_EPOCH + time::Duration::seconds(1),
            Tier::Warm,
            CredenceTier::VerifiedSource,
            Tier::Cold,
        );

        let (record, item) = store.write_event(event).expect("write event should ingest");
        let stored = store
            .get(item.id)
            .expect("stored item should read")
            .expect("stored item should exist");

        assert_eq!(item.schema_version, CURRENT_MEMORY_SCHEMA_VERSION);
        assert_eq!(item.content, "ingested from file");
        assert_eq!(item.provenance, provenance);
        assert_eq!(item.timestamps.valid_from, OffsetDateTime::UNIX_EPOCH);
        assert_eq!(
            item.timestamps.ingested_at,
            OffsetDateTime::UNIX_EPOCH + time::Duration::seconds(1)
        );
        assert_eq!(item.timestamps.valid_to, None);
        assert_eq!(item.credence, CredenceTier::VerifiedSource);
        assert_eq!(item.credence_floor, Tier::Cold);
        assert_eq!(
            record.event,
            MemoryEvent::MemoryWritten {
                item: Box::new(item.clone())
            }
        );
        assert_eq!(stored, item);
    }

    #[test]
    fn redb_store_allows_concurrent_readers_with_a_single_writer() {
        fn assert_send_sync<T: Send + Sync>() {}

        assert_send_sync::<RedbMemoryStore>();

        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = Arc::new(RedbMemoryStore::open(file.path()).expect("store should open"));
        let seed = test_item("seed");
        let seed_id = seed.id;

        store.write(&seed).expect("seed should write");

        let participants = 5;
        let barrier = Arc::new(Barrier::new(participants));
        let readers = (0..4)
            .map(|_| {
                let store = Arc::clone(&store);
                let barrier = Arc::clone(&barrier);

                thread::spawn(move || {
                    barrier.wait();

                    for _ in 0..64 {
                        let item = store
                            .get(seed_id)
                            .expect("reader should not fail")
                            .expect("seed should remain readable");
                        let events = store.events().expect("events should remain readable");

                        assert_eq!(item.content, "seed");
                        assert!(!events.is_empty());
                    }
                })
            })
            .collect::<Vec<_>>();
        let writer = {
            let store = Arc::clone(&store);
            let barrier = Arc::clone(&barrier);

            thread::spawn(move || {
                barrier.wait();

                for index in 0..16 {
                    let item = test_item(&format!("writer-{index}"));

                    store.write(&item).expect("single writer should commit");
                }
            })
        };

        for reader in readers {
            reader.join().expect("reader should finish");
        }
        writer.join().expect("writer should finish");

        assert_eq!(store.events().expect("events should read").len(), 17);
        assert_eq!(store.memory_items().expect("items should read").len(), 17);
    }

    #[test]
    fn write_event_assigns_credence_from_source_kind() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let cases = [
            (SourceKind::User, CredenceTier::FirmAuthoritative),
            (SourceKind::File, CredenceTier::VerifiedSource),
            (SourceKind::Agent, CredenceTier::ModelInferred),
            (SourceKind::Tool, CredenceTier::ModelInferred),
            (SourceKind::Web, CredenceTier::Unverified),
        ];

        for (source_kind, expected_credence) in cases {
            let event = MemoryWriteEvent::new(
                format!("content from {source_kind:?}"),
                Provenance::new(source_kind, None, "ingest-test"),
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            );
            let (_, item) = store.write_event(event).expect("write event should ingest");

            assert_eq!(item.provenance.source_kind, source_kind);
            assert_eq!(item.credence, expected_credence);
        }
    }

    #[test]
    fn write_event_quarantines_agent_and_web_sources_by_default() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let cases = [
            (SourceKind::Agent, Tier::Cold, CredenceTier::ModelInferred),
            (SourceKind::Web, Tier::Cold, CredenceTier::Unverified),
            (
                SourceKind::User,
                Tier::Warm,
                CredenceTier::FirmAuthoritative,
            ),
            (SourceKind::File, Tier::Warm, CredenceTier::VerifiedSource),
            (SourceKind::Tool, Tier::Warm, CredenceTier::ModelInferred),
        ];

        for (source_kind, expected_tier, expected_credence) in cases {
            let event = MemoryWriteEvent::new(
                format!("content from {source_kind:?}"),
                Provenance::new(source_kind, None, "ingest-test"),
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            );
            let (_, item) = store.write_event(event).expect("write event should ingest");

            assert_eq!(item.tier, expected_tier);
            assert_eq!(item.credence, expected_credence);
            assert_eq!(item.credence_floor, Tier::Cold);
        }
    }

    #[test]
    fn write_event_can_store_instruction_memory_kind() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let event = MemoryWriteEvent::new(
            "remember this instruction",
            Provenance::new(SourceKind::User, None, "ingest-test"),
            OffsetDateTime::UNIX_EPOCH,
            OffsetDateTime::UNIX_EPOCH,
        )
        .as_instruction();

        let (_, item) = store
            .write_event(event)
            .expect("instruction write event should ingest");

        assert_eq!(item.kind, MemoryKind::Instruction);
        assert_eq!(
            store
                .get(item.id)
                .expect("stored instruction should read")
                .expect("stored instruction should exist")
                .kind,
            MemoryKind::Instruction
        );
    }

    #[test]
    fn get_and_get_many_read_materialized_items() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let first = test_item("first");
        let second = test_item("second");
        let missing = MemoryId::new_v7();

        store.write(&first).expect("first should write");
        store.write(&second).expect("second should write");

        assert_eq!(
            store.get(first.id).expect("get should read"),
            Some(first.clone())
        );

        let items = store
            .get_many(&[second.id, missing, first.id])
            .expect("get_many should read");

        assert_eq!(items, vec![Some(second), None, Some(first)]);
    }

    #[test]
    fn graph_storage_persists_entities_and_relations() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let path = file.path();
        let now = OffsetDateTime::UNIX_EPOCH;
        let entity = Entity::new(
            "Project",
            "Shibahama",
            "project:shibahama",
            TemporalBounds::open_from(now, now),
        );
        let target = Entity::new(
            "Claim",
            "never-delete",
            "claim:never-delete",
            TemporalBounds::open_from(now, now),
        );
        let relation = Relation::new(
            "documents",
            entity.id,
            target.id,
            None,
            TemporalBounds::open_from(now, now),
        );

        {
            let store = RedbMemoryStore::open(path).expect("store should open");

            store.put_entity(&entity).expect("entity should write");
            store.put_entity(&target).expect("target should write");
            store
                .put_relation(&relation)
                .expect("relation should write");
        }

        let reopened = RedbMemoryStore::open(path).expect("store should reopen");

        assert_eq!(
            reopened.get_entity(entity.id).expect("entity should read"),
            Some(entity)
        );
        assert_eq!(
            reopened
                .get_relation(relation.id)
                .expect("relation should read"),
            Some(relation)
        );
    }

    #[test]
    fn resolve_entity_deduplicates_by_type_and_stable_key() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let canonical = Entity::new(
            "Project",
            "Shibahama",
            "project:shibahama",
            TemporalBounds::open_from(now, now),
        );
        let alias = Entity::new(
            "Project",
            "shibahama repo",
            "project:shibahama",
            TemporalBounds::open_from(now, now),
        );

        let first = store
            .resolve_entity(&canonical)
            .expect("canonical should resolve");
        let second = store.resolve_entity(&alias).expect("alias should resolve");
        let found = store
            .find_entity_by_stable_key("Project", "project:shibahama")
            .expect("entity should search")
            .expect("entity should exist");

        assert_eq!(first, canonical);
        assert_eq!(second.id, canonical.id);
        assert_eq!(second.label, "Shibahama");
        assert_eq!(found.id, canonical.id);
        assert!(
            store
                .get_entity(alias.id)
                .expect("alias id should read")
                .is_none()
        );
    }

    #[test]
    fn relations_for_entity_filters_by_relation_valid_time() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let source = Entity::new(
            "Claim",
            "old",
            "claim:old",
            TemporalBounds::open_from(now, now),
        );
        let target = Entity::new(
            "Claim",
            "new",
            "claim:new",
            TemporalBounds::open_from(now, now),
        );
        let relation = Relation::new(
            "supersedes",
            source.id,
            target.id,
            None,
            TemporalBounds::open_from(now, now).closed_at(now + time::Duration::days(1)),
        );

        store.put_entity(&source).expect("source should write");
        store.put_entity(&target).expect("target should write");
        store
            .put_relation(&relation)
            .expect("relation should write");

        assert_eq!(
            store
                .relations_for_entity(source.id, Some(now))
                .expect("relations should read"),
            vec![relation]
        );
        assert!(
            store
                .relations_for_entity(source.id, Some(now + time::Duration::days(1)))
                .expect("relations should read")
                .is_empty()
        );
    }

    #[test]
    fn graph_snapshot_reconstructs_graph_at_as_of() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let later = now + time::Duration::days(1);
        let source = test_entity("source", TemporalBounds::open_from(now, now));
        let target = test_entity("target", TemporalBounds::open_from(now, now));
        let expired = test_entity(
            "expired",
            TemporalBounds::open_from(now, now).closed_at(later),
        );
        let future = test_entity("future", TemporalBounds::open_from(later, later));
        let late_ingest = test_entity("late-ingest", TemporalBounds::open_from(now, later));
        let active = Relation::new(
            "supports",
            source.id,
            target.id,
            None,
            TemporalBounds::open_from(now, now),
        );
        let expired_relation = Relation::new(
            "supports",
            source.id,
            expired.id,
            None,
            TemporalBounds::open_from(now, now).closed_at(later),
        );
        let dangling_until_later = Relation::new(
            "supports",
            source.id,
            future.id,
            None,
            TemporalBounds::open_from(now, now),
        );
        let future_relation = Relation::new(
            "supports",
            source.id,
            future.id,
            None,
            TemporalBounds::open_from(later, later),
        );
        let late_relation = Relation::new(
            "supports",
            source.id,
            late_ingest.id,
            None,
            TemporalBounds::open_from(now, later),
        );

        for entity in [&source, &target, &expired, &future, &late_ingest] {
            store.put_entity(entity).expect("entity should write");
        }

        for relation in [
            &active,
            &expired_relation,
            &dangling_until_later,
            &future_relation,
            &late_relation,
        ] {
            store.put_relation(relation).expect("relation should write");
        }

        let now_snapshot = store.graph_snapshot(now).expect("snapshot should read");
        let (now_entity_ids, now_relation_ids) = graph_snapshot_ids(&now_snapshot);

        assert_eq!(now_snapshot.as_of, now);
        assert_eq!(
            now_entity_ids,
            BTreeSet::from([source.id, target.id, expired.id])
        );
        assert_eq!(
            now_relation_ids,
            BTreeSet::from([active.id, expired_relation.id])
        );

        let later_snapshot = store.graph_snapshot(later).expect("snapshot should read");
        let (later_entity_ids, later_relation_ids) = graph_snapshot_ids(&later_snapshot);

        assert_eq!(later_snapshot.as_of, later);
        assert_eq!(
            later_entity_ids,
            BTreeSet::from([source.id, target.id, future.id, late_ingest.id])
        );
        assert_eq!(
            later_relation_ids,
            BTreeSet::from([
                active.id,
                dangling_until_later.id,
                future_relation.id,
                late_relation.id,
            ])
        );
    }

    #[test]
    fn detect_relation_contradiction_matches_same_entity_and_attribute() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let subject = Entity::new(
            "Project",
            "Shibahama",
            "project:shibahama",
            TemporalBounds::open_from(now, now),
        );
        let old_value = Entity::new(
            "Value",
            "red",
            "value:red",
            TemporalBounds::open_from(now, now),
        );
        let new_value = Entity::new(
            "Value",
            "blue",
            "value:blue",
            TemporalBounds::open_from(now, now),
        );
        let existing = Relation::new(
            "status",
            subject.id,
            old_value.id,
            None,
            TemporalBounds::open_from(now, now),
        );
        let proposed = Relation::new(
            "status",
            subject.id,
            new_value.id,
            None,
            TemporalBounds::open_from(now, now),
        );
        let consistent = Relation::new(
            "status",
            subject.id,
            old_value.id,
            None,
            TemporalBounds::open_from(now, now),
        );

        store.put_entity(&subject).expect("subject should write");
        store
            .put_entity(&old_value)
            .expect("old value should write");
        store
            .put_entity(&new_value)
            .expect("new value should write");
        store
            .put_relation(&existing)
            .expect("existing relation should write");

        let contradiction = store
            .detect_relation_contradiction(&proposed, now)
            .expect("detection should read")
            .expect("contradiction should be detected");

        assert_eq!(contradiction.existing, existing);
        assert_eq!(contradiction.proposed, proposed);
        assert!(
            store
                .detect_relation_contradiction(&consistent, now)
                .expect("detection should read")
                .is_none()
        );
    }

    #[test]
    fn resolving_relation_contradiction_invalidates_old_and_links_new() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let replacement_time = now + time::Duration::days(1);
        let subject = Entity::new(
            "Project",
            "Shibahama",
            "project:shibahama",
            TemporalBounds::open_from(now, now),
        );
        let old_value = Entity::new(
            "Value",
            "red",
            "value:red",
            TemporalBounds::open_from(now, now),
        );
        let new_value = Entity::new(
            "Value",
            "blue",
            "value:blue",
            TemporalBounds::open_from(now, now),
        );
        let existing = Relation::new(
            "status",
            subject.id,
            old_value.id,
            None,
            TemporalBounds::open_from(now, now),
        );
        let mut proposed = Relation::new(
            "status",
            subject.id,
            new_value.id,
            None,
            TemporalBounds::open_from(replacement_time, replacement_time),
        );

        store.put_entity(&subject).expect("subject should write");
        store
            .put_entity(&old_value)
            .expect("old value should write");
        store
            .put_entity(&new_value)
            .expect("new value should write");
        store
            .put_relation(&existing)
            .expect("existing relation should write");

        let superseded = store
            .put_relation_resolving_contradiction(&mut proposed)
            .expect("resolution should write");
        let stored_existing = store
            .get_relation(existing.id)
            .expect("existing should read")
            .expect("existing should exist");
        let stored_proposed = store
            .get_relation(proposed.id)
            .expect("proposed should read")
            .expect("proposed should exist");

        assert_eq!(superseded, Some(existing.id));
        assert_eq!(stored_existing.timestamps.valid_to, Some(replacement_time));
        assert_eq!(stored_proposed.supersedes, Some(existing.id));
        assert_eq!(proposed.supersedes, Some(existing.id));
        assert_eq!(
            store
                .relations_for_entity(subject.id, Some(now))
                .expect("relations should read"),
            vec![stored_existing]
        );
        assert_eq!(
            store
                .relations_for_entity(subject.id, Some(replacement_time))
                .expect("relations should read"),
            vec![stored_proposed]
        );
    }

    #[test]
    fn traverse_graph_walks_n_hops_with_type_filter() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let start = Entity::new(
            "Claim",
            "start",
            "claim:start",
            TemporalBounds::open_from(now, now),
        );
        let middle = Entity::new(
            "Claim",
            "middle",
            "claim:middle",
            TemporalBounds::open_from(now, now),
        );
        let end = Entity::new(
            "Claim",
            "end",
            "claim:end",
            TemporalBounds::open_from(now, now),
        );
        let blocked = Entity::new(
            "Claim",
            "blocked",
            "claim:blocked",
            TemporalBounds::open_from(now, now),
        );
        let first = Relation::new(
            "supports",
            start.id,
            middle.id,
            None,
            TemporalBounds::open_from(now, now),
        );
        let second = Relation::new(
            "supports",
            middle.id,
            end.id,
            None,
            TemporalBounds::open_from(now, now),
        );
        let blocked_relation = Relation::new(
            "blocks",
            start.id,
            blocked.id,
            None,
            TemporalBounds::open_from(now, now),
        );

        for entity in [&start, &middle, &end, &blocked] {
            store.put_entity(entity).expect("entity should write");
        }

        for relation in [&first, &second, &blocked_relation] {
            store.put_relation(relation).expect("relation should write");
        }

        let request = GraphTraversalRequest::new(start.id, 2)
            .with_relation_types(["supports".to_owned()])
            .as_of(now);
        let result = store
            .traverse_graph(&request)
            .expect("traversal should read");
        let entity_ids = result
            .entities
            .iter()
            .map(|entity| entity.id)
            .collect::<BTreeSet<_>>();
        let relation_ids = result
            .relations
            .iter()
            .map(|relation| relation.id)
            .collect::<BTreeSet<_>>();

        assert_eq!(entity_ids, BTreeSet::from([start.id, middle.id, end.id]));
        assert_eq!(relation_ids, BTreeSet::from([first.id, second.id]));
    }

    #[test]
    fn extract_subgraph_filters_entities_and_relations_by_scope() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let mut first = Entity::new(
            "Claim",
            "first",
            "claim:first",
            TemporalBounds::open_from(now, now),
        );
        let mut second = Entity::new(
            "Claim",
            "second",
            "claim:second",
            TemporalBounds::open_from(now, now),
        );
        let mut outside = Entity::new(
            "Claim",
            "outside",
            "claim:outside",
            TemporalBounds::open_from(now, now),
        );
        let in_scope = Relation::new(
            "supports",
            first.id,
            second.id,
            None,
            TemporalBounds::open_from(now, now),
        );
        let out_of_scope = Relation::new(
            "supports",
            first.id,
            outside.id,
            None,
            TemporalBounds::open_from(now, now),
        );

        first
            .attributes
            .insert("namespace".to_owned(), "matter-a".to_owned());
        second
            .attributes
            .insert("namespace".to_owned(), "matter-a".to_owned());
        outside
            .attributes
            .insert("namespace".to_owned(), "matter-b".to_owned());

        for entity in [&first, &second, &outside] {
            store.put_entity(entity).expect("entity should write");
        }

        for relation in [&in_scope, &out_of_scope] {
            store.put_relation(relation).expect("relation should write");
        }

        let result = store
            .extract_subgraph(&SubgraphRequest::new("namespace", "matter-a").as_of(now))
            .expect("subgraph should read");
        let entity_ids = result
            .entities
            .iter()
            .map(|entity| entity.id)
            .collect::<BTreeSet<_>>();
        let relation_ids = result
            .relations
            .iter()
            .map(|relation| relation.id)
            .collect::<BTreeSet<_>>();

        assert_eq!(entity_ids, BTreeSet::from([first.id, second.id]));
        assert_eq!(relation_ids, BTreeSet::from([in_scope.id]));
    }

    #[test]
    fn mutation_paths_preserve_memory_rows_events_and_cold_content() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let mut active = test_item("active item");
        let mut cold = test_item("cold item content");
        let valid_to = OffsetDateTime::UNIX_EPOCH + time::Duration::days(7);
        let demotion_policy = SignificanceConfig {
            half_life_seconds: 1.0,
            ..SignificanceConfig::default()
        };

        cold.tier = Tier::Cold;
        cold.credence_floor = Tier::Cold;

        store
            .write_embedded(
                &mut active,
                &mut vector_index,
                &[0.0, 0.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("embedded write should work");
        store.write(&cold).expect("cold item should write");

        let ids = [active.id, cold.id];
        let initial_report = assert_memory_ids_survive(&store, &ids);

        assert_eq!(initial_report.event_count, 2);

        store
            .reinforce(active.id, crate::model::AccessOutcome::LedSomewhere)
            .expect("reinforce should preserve row");
        assert_memory_ids_survive(&store, &ids);

        store
            .refresh_significance(
                active.id,
                &demotion_policy,
                OffsetDateTime::UNIX_EPOCH + time::Duration::seconds(10),
            )
            .expect("refresh should preserve row");
        assert_memory_ids_survive(&store, &ids);

        store
            .soft_invalidate_with_vector(active.id, valid_to, &mut vector_index)
            .expect("soft invalidation should preserve row");
        assert_memory_ids_survive(&store, &ids);

        assert!(
            vector_index
                .search(&[0.0, 0.0], 1)
                .expect("vector search should work")
                .is_empty()
        );

        assert!(
            store
                .compact_cold_item(cold.id)
                .expect("compaction should preserve row")
        );

        let final_report = assert_memory_ids_survive(&store, &ids);
        let compacted = store
            .get(cold.id)
            .expect("cold row should read")
            .expect("cold row should exist");
        let pointer = compacted
            .compaction
            .as_ref()
            .expect("cold content pointer should exist");

        assert_eq!(final_report.compacted_content_count, 1);
        assert!(final_report.event_count >= 5);
        assert_eq!(compacted.content, "");
        assert_eq!(
            store
                .read_compacted_content(pointer)
                .expect("compacted content should read")
                .as_deref(),
            Some("cold item content")
        );
    }

    #[test]
    fn soft_invalidate_closes_validity_and_preserves_events() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("invalidate me");
        let item_id = item.id;
        let valid_to = OffsetDateTime::UNIX_EPOCH + time::Duration::days(7);

        store.write(&item).expect("item should write");

        let record = store
            .soft_invalidate(item_id, valid_to)
            .expect("invalidation should write")
            .expect("item should exist");

        assert_eq!(
            record.event,
            MemoryEvent::MemoryInvalidated {
                id: item_id,
                valid_to
            }
        );

        let stored = store
            .get(item_id)
            .expect("item should read")
            .expect("item should still exist");
        let events = store.events().expect("events should read");

        assert_eq!(stored.timestamps.valid_to, Some(valid_to));
        assert_eq!(events.len(), 2);
        assert!(matches!(events[0].event, MemoryEvent::MemoryWritten { .. }));
        assert!(matches!(
            events[1].event,
            MemoryEvent::MemoryInvalidated { .. }
        ));
    }

    #[test]
    fn reconstruction_replacement_invalidates_without_overwriting_superseded_memory() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let superseded = test_item("old fact");
        let replacement = test_item("new fact");
        let valid_to = OffsetDateTime::UNIX_EPOCH + time::Duration::days(10);

        store
            .write(&superseded)
            .expect("superseded item should write");

        let record = store
            .insert_reconstruction_replacement(superseded.id, &replacement, valid_to)
            .expect("replacement should write")
            .expect("superseded item should exist");
        let stored_superseded = store
            .get(superseded.id)
            .expect("superseded should read")
            .expect("superseded row should remain");
        let stored_replacement = store
            .get(replacement.id)
            .expect("replacement should read")
            .expect("replacement row should exist");
        let events = store.events().expect("events should read");
        let report = assert_memory_ids_survive(&store, &[superseded.id, replacement.id]);

        assert_eq!(stored_superseded.content, "old fact");
        assert_eq!(stored_superseded.timestamps.valid_to, Some(valid_to));
        assert_eq!(stored_replacement.content, "new fact");
        assert_eq!(stored_replacement.timestamps.valid_to, None);
        assert_eq!(record.invalidation.sequence, 1);
        assert_eq!(record.replacement_write.sequence, 2);
        assert_eq!(record.reconstruction.sequence, 3);
        assert_eq!(
            record.invalidation.event,
            MemoryEvent::MemoryInvalidated {
                id: superseded.id,
                valid_to
            }
        );
        assert_eq!(
            record.replacement_write.event,
            MemoryEvent::MemoryWritten {
                item: Box::new(replacement.clone())
            }
        );
        assert_eq!(
            record.reconstruction.event,
            MemoryEvent::ReconstructionApplied {
                superseded_id: superseded.id,
                replacement_id: replacement.id,
                valid_to,
            }
        );
        assert_eq!(events.len(), 4);
        assert!(matches!(events[0].event, MemoryEvent::MemoryWritten { .. }));
        assert!(matches!(
            events[1].event,
            MemoryEvent::MemoryInvalidated { .. }
        ));
        assert!(matches!(events[2].event, MemoryEvent::MemoryWritten { .. }));
        assert!(matches!(
            events[3].event,
            MemoryEvent::ReconstructionApplied { .. }
        ));
        assert_eq!(report.event_count, 4);
    }

    #[test]
    fn reconstruction_replacement_does_not_write_when_superseded_missing() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let replacement = test_item("new fact");
        let valid_to = OffsetDateTime::UNIX_EPOCH + time::Duration::days(10);

        let record = store
            .insert_reconstruction_replacement(MemoryId::new_v7(), &replacement, valid_to)
            .expect("missing superseded id should be handled");

        assert!(record.is_none());
        assert!(
            store
                .get(replacement.id)
                .expect("replacement lookup should succeed")
                .is_none()
        );
        assert!(store.events().expect("events should read").is_empty());
    }

    #[test]
    fn reconstruction_replacement_rejects_same_id_overwrite() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let superseded = test_item("old fact");
        let mut replacement = test_item("same id replacement");
        let valid_to = OffsetDateTime::UNIX_EPOCH + time::Duration::days(10);

        replacement.id = superseded.id;
        store
            .write(&superseded)
            .expect("superseded item should write");

        let error = store
            .insert_reconstruction_replacement(superseded.id, &replacement, valid_to)
            .expect_err("same id replacement should be rejected");
        let stored = store
            .get(superseded.id)
            .expect("superseded should read")
            .expect("superseded should remain");

        assert!(matches!(error, StorageError::InvariantViolation(_)));
        assert_eq!(stored.content, "old fact");
        assert_eq!(stored.timestamps.valid_to, None);
        assert_eq!(store.events().expect("events should read").len(), 1);
    }

    #[test]
    fn compact_cold_item_moves_content_to_compressed_storage() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut item = test_item("large cold content that should move out of the hot row");

        item.tier = Tier::Cold;
        store.write(&item).expect("item should write");

        assert!(
            store
                .compact_cold_item(item.id)
                .expect("compaction should run")
        );

        let compacted = store
            .get(item.id)
            .expect("item should read")
            .expect("item should exist");
        let pointer = compacted.compaction.as_ref().expect("pointer should exist");
        let restored = store
            .read_compacted_content(pointer)
            .expect("content should read");
        let events = store.events().expect("events should read");

        assert_eq!(compacted.content, "");
        assert_eq!(
            restored.as_deref(),
            Some("large cold content that should move out of the hot row")
        );
        assert!(pointer.compressed_bytes > 0);
        assert!(
            events
                .iter()
                .any(|event| matches!(event.event, MemoryEvent::ContentCompacted { .. }))
        );
    }

    #[test]
    fn recovery_decodes_persisted_event_log_and_materialized_items() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let path = file.path();

        {
            let store = RedbMemoryStore::open(path).expect("store should open");

            store
                .write(&test_item("first"))
                .expect("first should write");
            store
                .write(&test_item("second"))
                .expect("second should write");
        }

        let reopened = RedbMemoryStore::open(path).expect("store should recover on open");
        let report = reopened.recover().expect("recovery should report");

        assert_eq!(
            report,
            RecoveryReport {
                event_count: 2,
                materialized_item_count: 2
            }
        );
    }

    #[test]
    fn recovery_fails_closed_on_schema_version_mismatch() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let path = file.path();

        {
            let store = RedbMemoryStore::open(path).expect("store should open");
            let mut item = test_item("future schema");

            item.schema_version = CURRENT_MEMORY_SCHEMA_VERSION + 1;
            let record = EventRecord {
                sequence: 0,
                recorded_at: OffsetDateTime::UNIX_EPOCH,
                event: MemoryEvent::MemoryWritten {
                    item: Box::new(item.clone()),
                },
            };
            let event_key = RedbMemoryStore::event_key(record.sequence);
            let item_key = item.id.to_string();
            let event_bytes = store
                .encode_json(StorageTableName::EventLog, &event_key, &record)
                .expect("event should encode");
            let item_bytes = store
                .encode_json(StorageTableName::MemoryItems, item_key.as_bytes(), &item)
                .expect("item should encode");
            let mut write_txn = store.db.begin_write().expect("write txn should begin");

            write_txn
                .set_durability(Durability::Immediate)
                .expect("durability should set");
            {
                let mut event_table = write_txn
                    .open_table(EVENT_LOG_TABLE)
                    .expect("event table should open");
                let mut item_table = write_txn
                    .open_table(MEMORY_ITEMS_TABLE)
                    .expect("item table should open");

                event_table
                    .insert(record.sequence, event_bytes.as_slice())
                    .expect("event should insert");
                item_table
                    .insert(item_key.as_str(), item_bytes.as_slice())
                    .expect("item should insert");
            }
            write_txn.commit().expect("txn should commit");
        }

        let Err(error) = RedbMemoryStore::open(path) else {
            panic!("recovery should reject future schema");
        };

        assert!(matches!(
            error,
            StorageError::SchemaVersionMismatch {
                expected: CURRENT_MEMORY_SCHEMA_VERSION,
                found,
                ..
            } if found == CURRENT_MEMORY_SCHEMA_VERSION + 1
        ));
        assert!(error.to_string().contains("unsupported store format"));
        assert!(error.to_string().contains(&format!(
            "expected schema v{}, found v{}",
            CURRENT_MEMORY_SCHEMA_VERSION,
            CURRENT_MEMORY_SCHEMA_VERSION + 1
        )));
    }

    #[test]
    #[allow(clippy::too_many_lines)]
    fn encrypted_store_round_trips_without_plaintext_payloads_on_disk() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let path = file.path().to_path_buf();
        let key = [7_u8; 32];
        let hot_secret = "encrypted hot payload alpha 47291";
        let embedded_secret = "encrypted embedded payload beta 47291";
        let cold_secret = "encrypted cold payload gamma 47291";
        let graph_secret = "encrypted graph entity delta 47291";
        let mut embedded_item = test_item(embedded_secret);
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let mut cold_item = test_item(cold_secret);
        let hot_item = test_item(hot_secret);
        let timestamps =
            TemporalBounds::open_from(OffsetDateTime::UNIX_EPOCH, OffsetDateTime::UNIX_EPOCH);
        let source = test_entity(graph_secret, timestamps);
        let target = test_entity("encrypted graph entity epsilon 47291", timestamps);
        let relation = Relation::new(
            "supports",
            source.id,
            target.id,
            Some(hot_item.id),
            timestamps,
        );
        let cold_pointer = {
            let store = RedbMemoryStore::open_with_encryption(&path, Aes256GcmEncryption::new(key))
                .expect("encrypted store should open");

            cold_item.tier = Tier::Cold;
            store.write(&hot_item).expect("hot item should write");
            store
                .write_embedded(
                    &mut embedded_item,
                    &mut vector_index,
                    &[0.25, 0.75],
                    "encrypted-local",
                    "test-embedding",
                    "v1",
                )
                .expect("embedded item should write");
            store.write(&cold_item).expect("cold item should write");
            store
                .compact_cold_item(cold_item.id)
                .expect("cold item should compact");
            store
                .put_entity(&source)
                .expect("source entity should write");
            store
                .put_entity(&target)
                .expect("target entity should write");
            store
                .put_relation(&relation)
                .expect("relation should write");

            let stored_cold = store
                .get(cold_item.id)
                .expect("cold item should read")
                .expect("cold item should exist");
            let pointer = stored_cold
                .compaction
                .expect("cold item should have compaction pointer");
            assert_eq!(
                store
                    .read_compacted_content(&pointer)
                    .expect("cold content should decrypt")
                    .as_deref(),
                Some(cold_secret)
            );
            assert_eq!(
                store
                    .stored_embeddings()
                    .expect("embeddings should read")
                    .len(),
                1
            );
            assert_eq!(
                store
                    .get_entity(source.id)
                    .expect("entity should read")
                    .expect("entity should exist"),
                source
            );
            assert_eq!(
                store
                    .get_relation(relation.id)
                    .expect("relation should read")
                    .expect("relation should exist"),
                relation
            );

            pointer
        };

        let bytes = std::fs::read(&path).expect("database should be readable");
        for secret in [hot_secret, embedded_secret, cold_secret, graph_secret] {
            assert!(
                !bytes
                    .windows(secret.len())
                    .any(|window| window == secret.as_bytes()),
                "encrypted database contained plaintext payload: {secret}"
            );
        }

        let reopened = RedbMemoryStore::open_with_encryption(&path, Aes256GcmEncryption::new(key))
            .expect("encrypted store should reopen with the same key");
        assert_eq!(
            reopened
                .get(hot_item.id)
                .expect("hot item should read")
                .expect("hot item should exist")
                .content,
            hot_secret
        );
        assert_eq!(
            reopened
                .read_compacted_content(&cold_pointer)
                .expect("cold content should decrypt after reopen")
                .as_deref(),
            Some(cold_secret)
        );
        assert_eq!(
            reopened
                .stored_embeddings()
                .expect("embedding rows should decrypt after reopen")[0]
                .vector,
            vec![0.25, 0.75]
        );
    }

    #[test]
    fn encrypted_store_rejects_wrong_key_and_plaintext_provider() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let path = file.path().to_path_buf();

        {
            let store =
                RedbMemoryStore::open_with_encryption(&path, Aes256GcmEncryption::new([11_u8; 32]))
                    .expect("encrypted store should open");
            store
                .write(&test_item("wrong key protected payload"))
                .expect("item should write");
        }

        assert!(matches!(
            RedbMemoryStore::open_with_encryption(&path, Aes256GcmEncryption::new([12_u8; 32])),
            Err(StorageError::Encryption(_))
        ));
        assert!(matches!(
            RedbMemoryStore::open(&path),
            Err(StorageError::Encryption(_))
        ));
    }

    #[test]
    fn envelope_encrypted_store_assigns_distinct_metadata_to_each_semantic_record() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let path = file.path().to_path_buf();
        let first = test_item("first envelope-record payload");
        let second = test_item("second envelope-record payload");

        let store = RedbMemoryStore::open_with_encryption(
            &path,
            EnvelopeEncryption::new(LocalKeyProvider::new("development-kek", [31_u8; 32])),
        )
        .expect("envelope store should open");
        let first_event = store.write(&first).expect("first item should write");
        let second_event = store.write(&second).expect("second item should write");
        let first_key = first.id.to_string();
        let second_key = second.id.to_string();
        let read_txn = store.db.begin_read().expect("read txn should begin");
        let item_table = read_txn
            .open_table(MEMORY_ITEMS_TABLE)
            .expect("item table should open");
        let event_table = read_txn
            .open_table(EVENT_LOG_TABLE)
            .expect("event table should open");
        let first_item = item_table
            .get(first_key.as_str())
            .expect("first item should read")
            .expect("first item should exist")
            .value()
            .to_vec();
        let second_item = item_table
            .get(second_key.as_str())
            .expect("second item should read")
            .expect("second item should exist")
            .value()
            .to_vec();
        let first_event = event_table
            .get(first_event.sequence)
            .expect("first event should read")
            .expect("first event should exist")
            .value()
            .to_vec();
        let second_event = event_table
            .get(second_event.sequence)
            .expect("second event should read")
            .expect("second event should exist")
            .value()
            .to_vec();
        let metadata = [first_item, second_item, first_event, second_event]
            .iter()
            .map(|record| envelope_key_metadata(record).expect("metadata should parse"))
            .collect::<Vec<_>>();

        assert!(metadata.iter().all(
            |entry| entry.provider == "local-aes-256-gcm" && entry.key_id == "development-kek"
        ));
        assert_ne!(metadata[0].wrapped_data_key, metadata[1].wrapped_data_key);
        assert_ne!(metadata[0].wrapped_data_key, metadata[2].wrapped_data_key);
        assert_ne!(metadata[2].wrapped_data_key, metadata[3].wrapped_data_key);
        drop(event_table);
        drop(item_table);
        drop(read_txn);
        drop(store);
        assert!(matches!(
            RedbMemoryStore::open(&path),
            Err(StorageError::Encryption(_))
        ));
    }

    #[test]
    fn encrypted_store_refuses_plaintext_snapshot_export() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let snapshot_file = NamedTempFile::new().expect("snapshot tempfile should be created");
        let store = RedbMemoryStore::open_with_encryption(
            file.path(),
            Aes256GcmEncryption::new([21_u8; 32]),
        )
        .expect("encrypted store should open");

        store
            .write(&test_item("snapshot protected payload"))
            .expect("item should write");

        assert!(matches!(
            store.snapshot(snapshot_file.path()),
            Err(StorageError::EncryptedSnapshotExportDisabled)
        ));
    }

    #[test]
    fn snapshot_and_restore_round_trip_full_store_state() {
        let source_db = NamedTempFile::new().expect("source tempfile should be created");
        let snapshot_file = NamedTempFile::new().expect("snapshot tempfile should be created");
        let restore_dir = tempdir().expect("restore dir should be created");
        let restored_db = restore_dir.path().join("restored.redb");
        let source = RedbMemoryStore::open(source_db.path()).expect("source should open");
        let hot = test_item("hot content");
        let mut cold = test_item("cold content");

        cold.tier = Tier::Cold;
        source.write(&hot).expect("hot should write");
        source.write(&cold).expect("cold should write");
        source
            .compact_cold_item(cold.id)
            .expect("cold should compact");
        source
            .snapshot(snapshot_file.path())
            .expect("snapshot should write");

        let restored = RedbMemoryStore::restore_from_snapshot(&restored_db, snapshot_file.path())
            .expect("snapshot should restore");
        let restored_hot = restored
            .get(hot.id)
            .expect("hot should read")
            .expect("hot should exist");
        let restored_cold = restored
            .get(cold.id)
            .expect("cold should read")
            .expect("cold should exist");
        let restored_pointer = restored_cold
            .compaction
            .as_ref()
            .expect("cold pointer should exist");
        let restored_cold_content = restored
            .read_compacted_content(restored_pointer)
            .expect("cold content should read");

        assert_eq!(restored_hot.content, "hot content");
        assert_eq!(restored_cold.content, "");
        assert_eq!(restored_cold_content.as_deref(), Some("cold content"));
        assert_eq!(restored.events().expect("events should read").len(), 3);
    }

    #[test]
    fn embedded_write_and_invalidate_keep_vector_index_consistent() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut vector_index = HnswVectorIndex::with_capacity(2, 8);
        let mut item = test_item("embedded");
        let item_id = item.id;

        store
            .write_embedded(
                &mut item,
                &mut vector_index,
                &[0.0, 0.0],
                "hnsw-test",
                "embedding-model",
                "v1",
            )
            .expect("embedded write should work");

        let stored = store
            .get(item_id)
            .expect("item should read")
            .expect("item should exist");
        let search_before = vector_index
            .search(&[0.0, 0.0], 1)
            .expect("search should work");

        assert_eq!(
            stored.embedding_ref.as_ref().map(|eref| eref.dimensions),
            Some(2)
        );
        assert_eq!(search_before[0].id, item_id);

        store
            .soft_invalidate_with_vector(
                item_id,
                OffsetDateTime::UNIX_EPOCH + time::Duration::days(1),
                &mut vector_index,
            )
            .expect("invalidate should work");

        let search_after = vector_index
            .search(&[0.0, 0.0], 1)
            .expect("search should work");

        assert!(search_after.is_empty());
    }

    #[test]
    fn reinforce_appends_access_event_to_log_and_item() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("reinforce me");
        let item_id = item.id;

        store.write(&item).expect("item should write");

        let record = store
            .reinforce(item_id, crate::model::AccessOutcome::LedSomewhere)
            .expect("reinforce should write")
            .expect("item should exist");

        assert!(matches!(
            record.event,
            MemoryEvent::AccessRecorded {
                id,
                event: AccessEvent {
                    outcome: crate::model::AccessOutcome::LedSomewhere,
                    ..
                }
            } if id == item_id
        ));

        let stored = store
            .get(item_id)
            .expect("item should read")
            .expect("item should exist");

        assert_eq!(stored.access_events.len(), 1);
        assert_eq!(
            stored.access_events[0].outcome,
            crate::model::AccessOutcome::LedSomewhere
        );
        assert!(stored.significance > item.significance);
        assert_eq!(stored.tier, Tier::Hot);
    }

    #[test]
    fn reinforce_emits_tier_transition_event_when_promoted() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("promote me");
        let item_id = item.id;

        store.write(&item).expect("item should write");

        let record = store
            .reinforce(item_id, crate::model::AccessOutcome::LedSomewhere)
            .expect("reinforce should write")
            .expect("item should exist");
        let events = store.events().expect("events should read");

        assert!(matches!(
            record.event,
            MemoryEvent::AccessRecorded { id, .. } if id == item_id
        ));
        assert_eq!(events.len(), 3);
        assert!(matches!(
            events[1].event,
            MemoryEvent::AccessRecorded { id, .. } if id == item_id
        ));
        assert!(matches!(
            events[2].event,
            MemoryEvent::TierChanged {
                id,
                from: Tier::Warm,
                to: Tier::Hot,
                cause: TierChangeCause::AccessReinforcement,
            } if id == item_id
        ));
    }

    #[test]
    fn audit_trail_records_credence_and_tier_changes_with_causes() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("audit me");
        let item_id = item.id;

        store.write(&item).expect("item should write");
        store
            .reinforce(item_id, crate::model::AccessOutcome::LedSomewhere)
            .expect("reinforce should write");

        let audit = store.audit_trail(item_id).expect("audit trail should read");

        assert_eq!(audit.len(), 4);
        assert_eq!(
            audit[0].change,
            MemoryAuditChange::Credence {
                from: None,
                to: CredenceTier::FirmAuthoritative,
            }
        );
        assert_eq!(audit[0].cause, MemoryAuditCause::InitialWrite);
        assert_eq!(
            audit[1].change,
            MemoryAuditChange::Tier {
                from: None,
                to: Tier::Warm,
            }
        );
        assert_eq!(audit[1].cause, MemoryAuditCause::InitialWrite);
        assert_eq!(
            audit[2].change,
            MemoryAuditChange::CredenceFloor {
                from: None,
                to: Tier::Warm,
            }
        );
        assert_eq!(audit[2].cause, MemoryAuditCause::InitialWrite);
        assert_eq!(
            audit[3].change,
            MemoryAuditChange::Tier {
                from: Some(Tier::Warm),
                to: Tier::Hot,
            }
        );
        assert_eq!(audit[3].cause, MemoryAuditCause::AccessReinforcement);
    }

    #[test]
    fn reinforce_captures_cited_outcome_signal() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("cite me");
        let item_id = item.id;

        store.write(&item).expect("item should write");
        store
            .reinforce(item_id, crate::model::AccessOutcome::Cited)
            .expect("cited outcome should write");

        let stored = store
            .get(item_id)
            .expect("item should read")
            .expect("item should exist");

        assert_eq!(
            stored.access_events[0].outcome,
            crate::model::AccessOutcome::Cited
        );
    }

    #[test]
    fn record_contradiction_captures_contradicted_outcome() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("contradict me");
        let item_id = item.id;

        store.write(&item).expect("item should write");
        store
            .record_contradiction(item_id)
            .expect("contradiction should write");

        let stored = store
            .get(item_id)
            .expect("item should read")
            .expect("item should exist");

        assert_eq!(
            stored.access_events[0].outcome,
            crate::model::AccessOutcome::Contradicted
        );
    }

    #[test]
    fn anomaly_flags_report_contradiction_bursts_and_suspicious_provenance() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let now = OffsetDateTime::UNIX_EPOCH + time::Duration::minutes(10);
        let mut item = test_item("suspicious web memory");

        item.provenance = Provenance::new(SourceKind::Web, None, "storage-test");
        item.credence = CredenceTier::Unverified;
        store.write(&item).expect("item should write");

        for seconds_ago in [10, 20, 30] {
            store
                .record_access(
                    item.id,
                    AccessEvent::new(
                        now - time::Duration::seconds(seconds_ago),
                        None,
                        crate::model::AccessOutcome::Contradicted,
                    ),
                )
                .expect("contradiction should record");
        }

        let flags = store
            .anomaly_flags(
                AnomalyConfig {
                    contradiction_burst_window: time::Duration::minutes(1),
                    contradiction_burst_threshold: 3,
                },
                now,
            )
            .expect("anomaly flags should read");

        assert!(flags.iter().any(|flag| matches!(
            flag,
            AnomalyFlag::ContradictionBurst {
                memory_id,
                count: 3,
                ..
            } if *memory_id == item.id
        )));
        assert!(flags.iter().any(|flag| matches!(
            flag,
            AnomalyFlag::SuspiciousProvenance {
                memory_id,
                reason:
                    crate::anomaly::SuspiciousProvenanceReason::MissingExternalSourceRef {
                        source_kind: SourceKind::Web,
                    },
            } if *memory_id == item.id
        )));
    }

    #[test]
    fn explain_significance_returns_deterministic_breakdown() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("explain me");
        let item_id = item.id;
        let now = OffsetDateTime::UNIX_EPOCH + time::Duration::days(1);
        let policy = SignificanceConfig::default();

        store.write(&item).expect("item should write");

        let first = store
            .explain_significance(item_id, &policy, now)
            .expect("explain should read")
            .expect("item should exist");
        let second = store
            .explain_significance(item_id, &policy, now)
            .expect("explain should read")
            .expect("item should exist");

        assert_eq!(first, second);
        assert!(first.decay_multiplier <= 1.0);
    }

    #[test]
    fn explain_significance_can_use_graph_centrality() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("central memory");
        let item_id = item.id;
        let now = OffsetDateTime::UNIX_EPOCH;
        let source = Entity::new(
            "Claim",
            "source",
            "claim:source",
            TemporalBounds::open_from(now, now),
        );
        let target = Entity::new(
            "Claim",
            "target",
            "claim:target",
            TemporalBounds::open_from(now, now),
        );
        let relation = Relation::new(
            "supports",
            source.id,
            target.id,
            item_id,
            TemporalBounds::open_from(now, now),
        );
        let policy = SignificanceConfig {
            graph_centrality_weight: 2.0,
            ..SignificanceConfig::default()
        };

        store.write(&item).expect("item should write");
        store.put_entity(&source).expect("source should write");
        store.put_entity(&target).expect("target should write");
        store
            .put_relation(&relation)
            .expect("relation should write");

        let centrality = store
            .graph_centrality_for_memory(item_id)
            .expect("centrality should read");
        let breakdown = store
            .explain_significance_with_graph_centrality(item_id, policy, now)
            .expect("explain should read")
            .expect("item should exist");

        assert!(centrality > 0.0);
        assert!((breakdown.graph_centrality - (2.0 * centrality)).abs() < f64::EPSILON);
    }

    #[test]
    fn refresh_significance_demotes_lazily_as_score_decays() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut item = test_item("decay me");
        let policy = SignificanceConfig {
            half_life_seconds: 1.0,
            ..SignificanceConfig::default()
        };

        item.tier = Tier::Hot;
        item.significance = 1.0;
        item.credence_floor = Tier::Cold;
        store.write(&item).expect("item should write");

        let refreshed = store
            .refresh_significance(
                item.id,
                &policy,
                OffsetDateTime::UNIX_EPOCH + time::Duration::seconds(10),
            )
            .expect("refresh should work")
            .expect("item should exist");

        assert_eq!(refreshed.tier, Tier::Cold);
        assert!(refreshed.significance < policy.warm_threshold);

        let events = store.events().expect("events should read");

        assert_eq!(events.len(), 2);
        assert!(matches!(
            events[1].event,
            MemoryEvent::TierChanged {
                id,
                from: Tier::Hot,
                to: Tier::Cold,
                cause: TierChangeCause::SignificanceRefresh,
            } if id == item.id
        ));
    }

    #[test]
    fn enforce_tier_capacity_demotes_lowest_significance_hot_items() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let mut low = test_item("low");
        let mut middle = test_item("middle");
        let mut high = test_item("high");

        low.tier = Tier::Hot;
        low.significance = 1.0;
        middle.tier = Tier::Hot;
        middle.significance = 5.0;
        high.tier = Tier::Hot;
        high.significance = 10.0;

        store.write(&low).expect("low should write");
        store.write(&middle).expect("middle should write");
        store.write(&high).expect("high should write");

        assert!(
            store
                .enforce_tier_capacity(TierCapacityConfig::default())
                .expect("unbounded capacity should work")
                .is_empty()
        );

        let demoted = store
            .enforce_tier_capacity(TierCapacityConfig {
                hot_capacity: Some(2),
            })
            .expect("capacity should enforce");
        let stored_low = store
            .get(low.id)
            .expect("low should read")
            .expect("low should exist");
        let stored_middle = store
            .get(middle.id)
            .expect("middle should read")
            .expect("middle should exist");
        let stored_high = store
            .get(high.id)
            .expect("high should read")
            .expect("high should exist");
        let events = store.events().expect("events should read");

        assert_eq!(demoted, vec![low.id]);
        assert_eq!(stored_low.tier, Tier::Warm);
        assert_eq!(stored_middle.tier, Tier::Hot);
        assert_eq!(stored_high.tier, Tier::Hot);
        assert!(matches!(
            events[3].event,
            MemoryEvent::TierChanged {
                id,
                from: Tier::Hot,
                to: Tier::Warm,
                cause: TierChangeCause::CapacityEnforcement,
            } if id == low.id
        ));
        assert_eq!(
            store
                .verify_never_delete_invariant()
                .expect("never-delete invariant should hold")
                .materialized_item_count,
            3
        );
    }

    #[test]
    fn redb_store_satisfies_memory_store_trait() {
        fn write_and_get(store: &dyn MemoryStore, item: &MemoryItem) -> MemoryItem {
            store.write(item).expect("trait write should work");

            store
                .get(item.id)
                .expect("trait get should read")
                .expect("item should exist")
        }

        fn write_event_and_get(store: &dyn MemoryStore, event: MemoryWriteEvent) -> MemoryItem {
            let (_, item) = store
                .write_event(event)
                .expect("trait write_event should work");

            store
                .get(item.id)
                .expect("trait event get should read")
                .expect("event item should exist")
        }

        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("trait-backed");
        let event = MemoryWriteEvent::with_explicit_credence(
            "trait event",
            Provenance::new(SourceKind::Tool, Some("tool:1".to_owned()), "trait-test"),
            OffsetDateTime::UNIX_EPOCH,
            OffsetDateTime::UNIX_EPOCH,
            Tier::Warm,
            CredenceTier::ModelInferred,
            Tier::Cold,
        );

        assert_eq!(write_and_get(&store, &item), item);
        assert_eq!(write_event_and_get(&store, event).content, "trait event");
    }
}
