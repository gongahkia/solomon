// SPDX-License-Identifier: MIT

//! Core data model types shared by storage, retrieval, bindings, and the CLI.

use serde::{Deserialize, Serialize};
use std::fmt::{self, Display, Formatter};
use time::OffsetDateTime;
use uuid::Uuid;

/// Current schema version for persisted memory items.
pub const CURRENT_MEMORY_SCHEMA_VERSION: u16 = 1;

/// Stable identifier for a persisted memory item.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct MemoryId(Uuid);

impl MemoryId {
    /// Generates a new time-ordered `UUIDv7` memory identifier.
    #[must_use]
    pub fn new_v7() -> Self {
        Self(Uuid::now_v7())
    }

    /// Returns the underlying UUID value.
    #[must_use]
    pub const fn as_uuid(self) -> Uuid {
        self.0
    }
}

impl Display for MemoryId {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        Display::fmt(&self.0, f)
    }
}

impl From<Uuid> for MemoryId {
    fn from(value: Uuid) -> Self {
        Self(value)
    }
}

impl From<MemoryId> for Uuid {
    fn from(value: MemoryId) -> Self {
        value.0
    }
}

/// Trust class assigned to a memory from its provenance and corroboration state.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub enum CredenceTier {
    /// Unconfirmed content, including web imports and quarantined reconstruction proposals.
    Unverified,
    /// Agent or model inference not directly asserted by a trusted source.
    ModelInferred,
    /// Observation from a source Shibahama can re-read or otherwise verify.
    VerifiedSource,
    /// Explicit user instruction, pinned project decision, or other authoritative assertion.
    FirmAuthoritative,
}

impl CredenceTier {
    /// Returns true when this tier may be treated as authoritative for conflict resolution.
    #[must_use]
    pub const fn is_authoritative(self) -> bool {
        matches!(self, Self::FirmAuthoritative)
    }
}

/// Accessibility tier for a memory item.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub enum Tier {
    /// Retained but excluded from default recall unless explicitly requested.
    Cold,
    /// Indexed and normally searchable.
    Warm,
    /// Highly significant and cheap to surface.
    Hot,
}

impl Tier {
    /// Returns the next hotter tier, or this tier if already hot.
    #[must_use]
    pub const fn promote(self) -> Self {
        match self {
            Self::Cold => Self::Warm,
            Self::Warm | Self::Hot => Self::Hot,
        }
    }

    /// Returns the next colder tier, or this tier if already cold.
    #[must_use]
    pub const fn demote(self) -> Self {
        match self {
            Self::Hot => Self::Warm,
            Self::Warm | Self::Cold => Self::Cold,
        }
    }
}

/// Origin class for a memory observation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum SourceKind {
    /// Direct user-provided information or instruction.
    User,
    /// Agent-authored or model-authored observation.
    Agent,
    /// File-system source such as repository content.
    File,
    /// Web source or imported web content.
    Web,
    /// Tool output produced by an integration.
    Tool,
}

/// Provenance attached to every persisted memory.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct Provenance {
    /// Kind of source that produced the memory.
    pub source_kind: SourceKind,
    /// Stable source reference, such as a file path, URL, tool-call id, or external record id.
    pub source_ref: Option<String>,
    /// Actor, process, or integration that ingested the memory.
    pub ingested_by: String,
}

impl Provenance {
    /// Creates a provenance record.
    #[must_use]
    pub fn new(
        source_kind: SourceKind,
        source_ref: impl Into<Option<String>>,
        ingested_by: impl Into<String>,
    ) -> Self {
        Self {
            source_kind,
            source_ref: source_ref.into(),
            ingested_by: ingested_by.into(),
        }
    }
}

/// Bi-temporal timestamps for a memory item or graph edge.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TemporalBounds {
    /// Start of the interval where the fact is claimed valid.
    pub valid_from: OffsetDateTime,
    /// End of the valid interval, or `None` for an open interval.
    pub valid_to: Option<OffsetDateTime>,
    /// Time at which Shibahama ingested the observation.
    pub ingested_at: OffsetDateTime,
}

impl TemporalBounds {
    /// Creates open-ended temporal bounds ingested at the same timestamp.
    #[must_use]
    pub const fn open_from(valid_from: OffsetDateTime, ingested_at: OffsetDateTime) -> Self {
        Self {
            valid_from,
            valid_to: None,
            ingested_at,
        }
    }

    /// Returns true when `instant` falls inside the valid-time interval.
    #[must_use]
    pub fn is_valid_at(self, instant: OffsetDateTime) -> bool {
        if instant < self.valid_from {
            return false;
        }

        self.valid_to.is_none_or(|valid_to| instant < valid_to)
    }

    /// Returns a copy with the valid interval closed at `valid_to`.
    #[must_use]
    pub const fn closed_at(self, valid_to: OffsetDateTime) -> Self {
        Self {
            valid_to: Some(valid_to),
            ..self
        }
    }
}

/// Outcome signal recorded after a memory is surfaced or used.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum AccessOutcome {
    /// The memory was surfaced as a candidate but no stronger usage signal was reported.
    Surfaced,
    /// The memory helped the caller take a useful next step.
    LedSomewhere,
    /// The memory was cited in generated output or otherwise used explicitly.
    Cited,
    /// The memory was surfaced but ignored by the caller.
    Ignored,
    /// The access exposed or recorded a contradiction.
    Contradicted,
}

/// Usage signal captured for a memory item.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AccessEvent {
    /// Time at which access occurred.
    pub timestamp: OffsetDateTime,
    /// Privacy-safe query-context hash, not raw query text.
    pub query_context_hash: Option<String>,
    /// Caller-provided or system-derived outcome signal.
    pub outcome: AccessOutcome,
}

impl AccessEvent {
    /// Creates an access event.
    #[must_use]
    pub fn new(
        timestamp: OffsetDateTime,
        query_context_hash: impl Into<Option<String>>,
        outcome: AccessOutcome,
    ) -> Self {
        Self {
            timestamp,
            query_context_hash: query_context_hash.into(),
            outcome,
        }
    }
}

/// Reference to a vector stored outside the materialized memory item.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EmbeddingRef {
    /// Name of the vector index backend or logical index.
    pub index: String,
    /// Backend-specific vector identifier.
    pub vector_id: String,
    /// Embedding model identifier.
    pub model: String,
    /// Embedding model version identifier.
    pub model_version: String,
    /// Number of dimensions in the referenced vector.
    pub dimensions: usize,
}

impl EmbeddingRef {
    /// Returns true when this reference was produced by a different embedding model contract.
    #[must_use]
    pub fn requires_reembed(&self, model: &str, model_version: &str, dimensions: usize) -> bool {
        self.model != model || self.model_version != model_version || self.dimensions != dimensions
    }
}

/// Pointer to content moved out of the hot materialized item row.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactionRef {
    /// Compression codec used for the stored payload.
    pub codec: String,
    /// Backend key for the compressed content payload.
    pub storage_key: String,
    /// Original uncompressed byte length.
    pub original_bytes: u64,
    /// Compressed byte length.
    pub compressed_bytes: u64,
}

/// Persisted memory item materialized from the event log.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct MemoryItem {
    /// Persisted schema version for forward migration.
    pub schema_version: u16,
    /// Stable time-ordered item id.
    pub id: MemoryId,
    /// Stored memory content.
    pub content: String,
    /// Pointer to compressed cold content when content has been moved out of this row.
    pub compaction: Option<CompactionRef>,
    /// Optional reference to the associated vector embedding.
    pub embedding_ref: Option<EmbeddingRef>,
    /// Provenance for the observation that produced this memory version.
    pub provenance: Provenance,
    /// Bi-temporal validity and ingestion timestamps.
    pub timestamps: TemporalBounds,
    /// Current accessibility tier.
    pub tier: Tier,
    /// Current trust tier.
    pub credence: CredenceTier,
    /// Current materialized significance score.
    pub significance: f64,
    /// Coldest tier this memory may occupy after significance-based demotion.
    pub credence_floor: Tier,
    /// Captured usage events for this memory.
    pub access_events: Vec<AccessEvent>,
}

impl MemoryItem {
    /// Applies this item's credence floor to a proposed tier.
    #[must_use]
    pub fn clamp_tier_to_floor(&self, proposed_tier: Tier) -> Tier {
        proposed_tier.max(self.credence_floor)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_memory_ids_are_uuid_v7() {
        let id = MemoryId::new_v7();

        assert_eq!(id.as_uuid().get_version_num(), 7);
    }

    #[test]
    fn generated_memory_ids_are_time_orderable() {
        let first = MemoryId::new_v7();
        let second = MemoryId::new_v7();

        assert!(first < second);
    }

    #[test]
    fn credence_tiers_order_from_weakest_to_strongest() {
        assert!(CredenceTier::Unverified < CredenceTier::ModelInferred);
        assert!(CredenceTier::ModelInferred < CredenceTier::VerifiedSource);
        assert!(CredenceTier::VerifiedSource < CredenceTier::FirmAuthoritative);
        assert!(CredenceTier::FirmAuthoritative.is_authoritative());
    }

    #[test]
    fn tier_transitions_are_bounded() {
        assert_eq!(Tier::Cold.promote(), Tier::Warm);
        assert_eq!(Tier::Warm.promote(), Tier::Hot);
        assert_eq!(Tier::Hot.promote(), Tier::Hot);

        assert_eq!(Tier::Hot.demote(), Tier::Warm);
        assert_eq!(Tier::Warm.demote(), Tier::Cold);
        assert_eq!(Tier::Cold.demote(), Tier::Cold);
    }

    #[test]
    fn provenance_keeps_source_and_ingester() {
        let provenance = Provenance::new(
            SourceKind::File,
            Some("core/src/model.rs".to_owned()),
            "unit-test",
        );

        assert_eq!(provenance.source_kind, SourceKind::File);
        assert_eq!(provenance.source_ref.as_deref(), Some("core/src/model.rs"));
        assert_eq!(provenance.ingested_by, "unit-test");
    }

    #[test]
    fn temporal_bounds_support_open_and_closed_validity() {
        let valid_from = OffsetDateTime::UNIX_EPOCH;
        let ingested_at = valid_from;
        let bounds = TemporalBounds::open_from(valid_from, ingested_at);

        assert!(bounds.is_valid_at(valid_from));
        assert!(bounds.is_valid_at(valid_from + time::Duration::days(1)));

        let closed = bounds.closed_at(valid_from + time::Duration::days(1));

        assert!(closed.is_valid_at(valid_from));
        assert!(!closed.is_valid_at(valid_from + time::Duration::days(1)));
    }

    #[test]
    fn access_event_keeps_timestamp_context_hash_and_outcome() {
        let event = AccessEvent::new(
            OffsetDateTime::UNIX_EPOCH,
            Some("query-hash".to_owned()),
            AccessOutcome::Cited,
        );

        assert_eq!(event.timestamp, OffsetDateTime::UNIX_EPOCH);
        assert_eq!(event.query_context_hash.as_deref(), Some("query-hash"));
        assert_eq!(event.outcome, AccessOutcome::Cited);
    }

    #[test]
    fn memory_item_carries_core_representation_fields() {
        let item = MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            id: MemoryId::new_v7(),
            content: "Use the Rust core as the source of truth.".to_owned(),
            compaction: None,
            embedding_ref: Some(EmbeddingRef {
                index: "default".to_owned(),
                vector_id: "vec-1".to_owned(),
                model: "test-embedding-model".to_owned(),
                model_version: "v1".to_owned(),
                dimensions: 3,
            }),
            provenance: Provenance::new(SourceKind::User, None, "unit-test"),
            timestamps: TemporalBounds::open_from(
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ),
            tier: Tier::Warm,
            credence: CredenceTier::FirmAuthoritative,
            significance: 1.0,
            credence_floor: Tier::Warm,
            access_events: Vec::new(),
        };

        assert_eq!(
            item.embedding_ref
                .as_ref()
                .map(|embedding| embedding.dimensions),
            Some(3)
        );
        assert_eq!(item.tier, Tier::Warm);
        assert_eq!(item.credence, CredenceTier::FirmAuthoritative);
        assert_eq!(item.schema_version, CURRENT_MEMORY_SCHEMA_VERSION);
        assert!((item.significance - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn embedding_ref_detects_reembed_requirements() {
        let embedding = EmbeddingRef {
            index: "default".to_owned(),
            vector_id: "vec-1".to_owned(),
            model: "model-a".to_owned(),
            model_version: "v1".to_owned(),
            dimensions: 3,
        };

        assert!(!embedding.requires_reembed("model-a", "v1", 3));
        assert!(embedding.requires_reembed("model-a", "v2", 3));
        assert!(embedding.requires_reembed("model-b", "v1", 3));
        assert!(embedding.requires_reembed("model-a", "v1", 4));
    }

    #[test]
    fn memory_item_clamps_proposed_tier_to_credence_floor() {
        let item = MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            id: MemoryId::new_v7(),
            content: "Do not reintroduce the rejected cache design.".to_owned(),
            compaction: None,
            embedding_ref: None,
            provenance: Provenance::new(SourceKind::User, None, "unit-test"),
            timestamps: TemporalBounds::open_from(
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ),
            tier: Tier::Hot,
            credence: CredenceTier::FirmAuthoritative,
            significance: 0.0,
            credence_floor: Tier::Warm,
            access_events: Vec::new(),
        };

        assert_eq!(item.clamp_tier_to_floor(Tier::Cold), Tier::Warm);
        assert_eq!(item.clamp_tier_to_floor(Tier::Hot), Tier::Hot);
    }
}
