// SPDX-License-Identifier: MIT

//! Core data model types shared by storage, retrieval, bindings, and the CLI.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
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

/// Stable identifier for a graph entity.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct EntityId(Uuid);

impl EntityId {
    /// Generates a new time-ordered `UUIDv7` entity identifier.
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

impl Display for EntityId {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        Display::fmt(&self.0, f)
    }
}

impl From<Uuid> for EntityId {
    fn from(value: Uuid) -> Self {
        Self(value)
    }
}

impl From<EntityId> for Uuid {
    fn from(value: EntityId) -> Self {
        value.0
    }
}

/// Stable identifier for a graph relation edge.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct RelationId(Uuid);

impl RelationId {
    /// Generates a new time-ordered `UUIDv7` relation identifier.
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

impl Display for RelationId {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        Display::fmt(&self.0, f)
    }
}

impl From<Uuid> for RelationId {
    fn from(value: Uuid) -> Self {
        Self(value)
    }
}

impl From<RelationId> for Uuid {
    fn from(value: RelationId) -> Self {
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

impl SourceKind {
    /// Stable string used in signed provenance payloads.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::User => "user",
            Self::Agent => "agent",
            Self::File => "file",
            Self::Web => "web",
            Self::Tool => "tool",
        }
    }
}

/// Semantic class for stored memory content.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum MemoryKind {
    /// Descriptive fact or observation.
    #[default]
    Fact,
    /// Instruction or directive that must not be mixed into fact recall by default.
    Instruction,
}

/// Optional keyed signature over provenance attribution fields.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ProvenanceSignature {
    /// Signature algorithm identifier.
    pub algorithm: String,
    /// Caller-managed key identifier.
    pub key_id: String,
    /// Hex-encoded keyed digest.
    pub digest: String,
}

/// Key material used to sign and verify provenance attribution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProvenanceSigningKey {
    key_id: String,
    key: [u8; 32],
}

impl ProvenanceSigningKey {
    /// Builds a signing key from caller-managed secret material.
    #[must_use]
    pub fn new(key_id: impl Into<String>, secret: impl AsRef<[u8]>) -> Self {
        Self {
            key_id: key_id.into(),
            key: blake3::derive_key("shibahama provenance signing v1", secret.as_ref()),
        }
    }

    /// Returns the caller-managed key id.
    #[must_use]
    pub fn key_id(&self) -> &str {
        &self.key_id
    }

    fn sign(&self, provenance: &Provenance) -> ProvenanceSignature {
        let digest = blake3::keyed_hash(&self.key, &provenance_signature_payload(provenance));

        ProvenanceSignature {
            algorithm: PROVENANCE_SIGNATURE_ALGORITHM.to_owned(),
            key_id: self.key_id.clone(),
            digest: digest.to_hex().to_string(),
        }
    }
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
    /// Optional keyed signature for source attribution.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub signature: Option<ProvenanceSignature>,
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
            signature: None,
        }
    }

    /// Returns a copy with a keyed provenance-attribution signature attached.
    #[must_use]
    pub fn with_signature(mut self, key: &ProvenanceSigningKey) -> Self {
        self.sign(key);
        self
    }

    /// Attaches a keyed provenance-attribution signature in place.
    pub fn sign(&mut self, key: &ProvenanceSigningKey) {
        self.signature = Some(key.sign(self));
    }

    /// Verifies the attached provenance signature with `key`.
    #[must_use]
    pub fn verify_signature(&self, key: &ProvenanceSigningKey) -> bool {
        self.signature.as_ref().is_some_and(|signature| {
            signature.algorithm == PROVENANCE_SIGNATURE_ALGORITHM
                && signature.key_id == key.key_id
                && constant_time_eq(&signature.digest, &key.sign(self).digest)
        })
    }
}

const PROVENANCE_SIGNATURE_ALGORITHM: &str = "blake3-keyed-v1";

fn provenance_signature_payload(provenance: &Provenance) -> Vec<u8> {
    let mut payload = Vec::new();

    append_signature_field(&mut payload, "source_kind", provenance.source_kind.as_str());
    append_signature_field(
        &mut payload,
        "source_ref",
        provenance.source_ref.as_deref().unwrap_or(""),
    );
    append_signature_field(&mut payload, "ingested_by", &provenance.ingested_by);

    payload
}

fn append_signature_field(payload: &mut Vec<u8>, name: &str, value: &str) {
    payload.extend_from_slice(name.as_bytes());
    payload.push(0);
    payload.extend_from_slice(value.len().to_string().as_bytes());
    payload.push(0);
    payload.extend_from_slice(value.as_bytes());
    payload.push(0xff);
}

fn constant_time_eq(left: &str, right: &str) -> bool {
    let left = left.as_bytes();
    let right = right.as_bytes();

    if left.len() != right.len() {
        return false;
    }

    let mut diff = 0_u8;

    for (left, right) in left.iter().zip(right) {
        diff |= left ^ right;
    }

    diff == 0
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

/// Typed graph entity extracted from or linked to memories.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct Entity {
    /// Stable entity id.
    pub id: EntityId,
    /// Caller-defined entity type, such as `Person`, `Project`, or `Claim`.
    pub entity_type: String,
    /// Canonical display label.
    pub label: String,
    /// Stable resolution key within the entity type.
    pub stable_key: String,
    /// Optional attributes used by typed graph integrations.
    pub attributes: BTreeMap<String, String>,
    /// Entity validity and ingestion timestamps.
    pub timestamps: TemporalBounds,
}

impl Entity {
    /// Creates a typed graph entity.
    #[must_use]
    pub fn new(
        entity_type: impl Into<String>,
        label: impl Into<String>,
        stable_key: impl Into<String>,
        timestamps: TemporalBounds,
    ) -> Self {
        Self {
            id: EntityId::new_v7(),
            entity_type: entity_type.into(),
            label: label.into(),
            stable_key: stable_key.into(),
            attributes: BTreeMap::new(),
            timestamps,
        }
    }
}

/// Typed directed relation edge between graph entities.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct Relation {
    /// Stable relation id.
    pub id: RelationId,
    /// Caller-defined relation type, such as `owns`, `contradicts`, or `supersedes`.
    pub relation_type: String,
    /// Source entity id.
    pub from_entity: EntityId,
    /// Target entity id.
    pub to_entity: EntityId,
    /// Optional memory that supports this edge.
    pub memory_id: Option<MemoryId>,
    /// Relation this edge supersedes, when inserted as a contradiction resolution.
    pub supersedes: Option<RelationId>,
    /// Optional attributes used by typed graph integrations.
    pub attributes: BTreeMap<String, String>,
    /// Relation validity and ingestion timestamps.
    pub timestamps: TemporalBounds,
}

impl Relation {
    /// Creates a typed directed relation edge.
    #[must_use]
    pub fn new(
        relation_type: impl Into<String>,
        from_entity: EntityId,
        to_entity: EntityId,
        memory_id: impl Into<Option<MemoryId>>,
        timestamps: TemporalBounds,
    ) -> Self {
        Self {
            id: RelationId::new_v7(),
            relation_type: relation_type.into(),
            from_entity,
            to_entity,
            memory_id: memory_id.into(),
            supersedes: None,
            attributes: BTreeMap::new(),
            timestamps,
        }
    }
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

impl AccessOutcome {
    /// Returns true when the memory was surfaced but not confirmed as useful.
    #[must_use]
    pub const fn is_surface_only(self) -> bool {
        matches!(self, Self::Surfaced | Self::Ignored)
    }

    /// Returns true when the caller indicated the memory materially mattered.
    #[must_use]
    pub const fn is_actual_use(self) -> bool {
        matches!(self, Self::LedSomewhere | Self::Cited)
    }
}

/// Privacy-safe fingerprint of recall/query context.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(transparent)]
pub struct QueryContextHash(String);

impl QueryContextHash {
    /// Hashes raw query context into a stable non-reversible fingerprint.
    #[must_use]
    pub fn from_raw(raw_context: &str) -> Self {
        Self(blake3::hash(raw_context.as_bytes()).to_hex().to_string())
    }

    /// Returns the hexadecimal fingerprint.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<QueryContextHash> for String {
    fn from(value: QueryContextHash) -> Self {
        value.0
    }
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

    /// Creates an access event by hashing raw query context before storage.
    #[must_use]
    pub fn with_raw_query_context(
        timestamp: OffsetDateTime,
        raw_context: &str,
        outcome: AccessOutcome,
    ) -> Self {
        Self::new(
            timestamp,
            Some(String::from(QueryContextHash::from_raw(raw_context))),
            outcome,
        )
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

/// Metadata for a memory produced by consolidation or summarisation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ConsolidationRef {
    /// Source memories that were consolidated into this item.
    pub source_memory_ids: Vec<MemoryId>,
    /// Number of summarisation/consolidation generations from raw observations.
    pub resummarization_depth: u16,
}

/// Durable action type emitted by an offline consolidation pass.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ConsolidationAction {
    /// Multiple source memories were synthesized into a new lineage-bearing memory item.
    Merge,
    /// A memory was promoted to a hotter accessibility tier.
    Promote,
    /// A memory was demoted to a colder accessibility tier while respecting its floor.
    Demote,
    /// A significant stale memory was flagged for explicit reconstruction/reverification.
    FlagStale,
}

/// Usage and safety evidence behind one consolidation decision.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ConsolidationUsageEvidence {
    /// Memory considered by the consolidation pass.
    pub memory_id: MemoryId,
    /// Materialized significance score used by the pass.
    pub significance: f64,
    /// Number of usage events captured for the memory.
    pub access_count: usize,
    /// Number of caller-confirmed useful events.
    pub actual_use_count: usize,
    /// Number of contradiction events captured for the memory.
    pub contradiction_count: usize,
    /// Tier before the consolidation decision.
    pub tier: Tier,
    /// Credence before the consolidation decision.
    pub credence: CredenceTier,
    /// Coldest tier this memory may occupy after demotion.
    pub credence_floor: Tier,
}

/// Human-readable why trace attached to every consolidation decision event.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ConsolidationWhy {
    /// Short explanation suitable for the Tideline and logs.
    pub summary: String,
    /// Usage/safety evidence for each input memory.
    pub evidence: Vec<ConsolidationUsageEvidence>,
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
    /// Whether this memory is a fact/observation or an instruction/directive.
    #[serde(default)]
    pub kind: MemoryKind,
    /// Pointer to compressed cold content when content has been moved out of this row.
    pub compaction: Option<CompactionRef>,
    /// Consolidation lineage, when this item is an auto-generated summary.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub consolidation: Option<ConsolidationRef>,
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
    /// Immutable base significance captured at write time.
    ///
    /// `significance` is a materialized score derived from this base plus access history. Keeping
    /// the original base separate makes lazy recomputation idempotent instead of feeding each
    /// refreshed score back into the next refresh.
    #[serde(default)]
    pub base_significance: f64,
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
    fn graph_ids_are_uuid_v7() {
        let entity_id = EntityId::new_v7();
        let relation_id = RelationId::new_v7();

        assert_eq!(entity_id.as_uuid().get_version_num(), 7);
        assert_eq!(relation_id.as_uuid().get_version_num(), 7);
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
    fn provenance_signature_verifies_source_attribution() {
        let key = ProvenanceSigningKey::new("unit-key", b"shared secret");
        let provenance = Provenance::new(
            SourceKind::Tool,
            Some("tool:calendar".to_owned()),
            "unit-test",
        )
        .with_signature(&key);

        assert!(provenance.verify_signature(&key));
        assert_eq!(
            provenance
                .signature
                .as_ref()
                .map(|signature| signature.key_id.as_str()),
            Some("unit-key")
        );
    }

    #[test]
    fn provenance_signature_rejects_tampering_and_wrong_keys() {
        let key = ProvenanceSigningKey::new("unit-key", b"shared secret");
        let wrong_key = ProvenanceSigningKey::new("other-key", b"shared secret");
        let mut provenance = Provenance::new(
            SourceKind::File,
            Some("repo:Cargo.toml".to_owned()),
            "unit-test",
        )
        .with_signature(&key);

        assert!(!provenance.verify_signature(&wrong_key));

        provenance.ingested_by = "attacker".to_owned();
        assert!(!provenance.verify_signature(&key));
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
    fn graph_entity_carries_type_key_attributes_and_time() {
        let now = OffsetDateTime::UNIX_EPOCH;
        let mut entity = Entity::new(
            "Project",
            "Shibahama",
            "project:shibahama",
            TemporalBounds::open_from(now, now),
        );

        entity
            .attributes
            .insert("namespace".to_owned(), "core".to_owned());

        assert_eq!(entity.entity_type, "Project");
        assert_eq!(entity.label, "Shibahama");
        assert_eq!(entity.stable_key, "project:shibahama");
        assert_eq!(
            entity.attributes.get("namespace").map(String::as_str),
            Some("core")
        );
        assert!(entity.timestamps.is_valid_at(now));
    }

    #[test]
    fn graph_relation_is_typed_directed_and_bitemporal() {
        let now = OffsetDateTime::UNIX_EPOCH;
        let source = Entity::new(
            "Claim",
            "old fact",
            "claim:old",
            TemporalBounds::open_from(now, now),
        );
        let target = Entity::new(
            "Claim",
            "new fact",
            "claim:new",
            TemporalBounds::open_from(now, now),
        );
        let memory_id = MemoryId::new_v7();
        let mut relation = Relation::new(
            "supersedes",
            source.id,
            target.id,
            memory_id,
            TemporalBounds::open_from(now, now).closed_at(now + time::Duration::days(1)),
        );

        relation
            .attributes
            .insert("reason".to_owned(), "contradiction".to_owned());

        assert_eq!(relation.relation_type, "supersedes");
        assert_eq!(relation.from_entity, source.id);
        assert_eq!(relation.to_entity, target.id);
        assert_eq!(relation.memory_id, Some(memory_id));
        assert_eq!(relation.supersedes, None);
        assert_eq!(
            relation.attributes.get("reason").map(String::as_str),
            Some("contradiction")
        );
        assert!(relation.timestamps.is_valid_at(now));
        assert!(
            !relation
                .timestamps
                .is_valid_at(now + time::Duration::days(1))
        );
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
    fn query_context_hash_does_not_store_raw_query() {
        let raw_query = "what changed in auth/session.ts?";
        let first = QueryContextHash::from_raw(raw_query);
        let second = QueryContextHash::from_raw(raw_query);
        let event = AccessEvent::with_raw_query_context(
            OffsetDateTime::UNIX_EPOCH,
            raw_query,
            AccessOutcome::Surfaced,
        );

        assert_eq!(first, second);
        assert_ne!(first.as_str(), raw_query);
        assert_eq!(event.query_context_hash.as_deref(), Some(first.as_str()));
    }

    #[test]
    fn access_outcomes_distinguish_surfaced_from_used() {
        assert!(AccessOutcome::Surfaced.is_surface_only());
        assert!(AccessOutcome::Ignored.is_surface_only());
        assert!(AccessOutcome::LedSomewhere.is_actual_use());
        assert!(AccessOutcome::Cited.is_actual_use());
        assert!(!AccessOutcome::Contradicted.is_actual_use());
    }

    #[test]
    fn memory_item_carries_core_representation_fields() {
        let item = MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            id: MemoryId::new_v7(),
            content: "Use the Rust core as the source of truth.".to_owned(),
            kind: MemoryKind::Fact,
            compaction: None,
            consolidation: None,
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
            base_significance: 1.0,
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
        assert_eq!(item.kind, MemoryKind::Fact);
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
            kind: MemoryKind::Instruction,
            compaction: None,
            consolidation: None,
            embedding_ref: None,
            provenance: Provenance::new(SourceKind::User, None, "unit-test"),
            timestamps: TemporalBounds::open_from(
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ),
            tier: Tier::Hot,
            credence: CredenceTier::FirmAuthoritative,
            significance: 0.0,
            base_significance: 0.0,
            credence_floor: Tier::Warm,
            access_events: Vec::new(),
        };

        assert_eq!(item.clamp_tier_to_floor(Tier::Cold), Tier::Warm);
        assert_eq!(item.clamp_tier_to_floor(Tier::Hot), Tier::Hot);
    }
}
