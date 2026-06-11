// SPDX-License-Identifier: MIT

//! Durable storage primitives for Shibahama.

use crate::model::{
    AccessEvent, CompactionRef, EmbeddingRef, Entity, EntityId, MemoryId, MemoryItem, Relation,
    RelationId, Tier,
};
use crate::significance::{SignificanceBreakdown, SignificanceConfig, SignificanceFunction};
use crate::vector::{VectorIndex, VectorIndexError};
use lz4_flex::{compress_prepend_size, decompress_size_prepended};
use redb::{
    Database, Durability, ReadableDatabase, ReadableTable, ReadableTableMetadata, TableDefinition,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fs;
use std::path::Path;
use thiserror::Error;
use time::OffsetDateTime;

const EVENT_LOG_TABLE: TableDefinition<u64, &[u8]> = TableDefinition::new("event_log");
const MEMORY_ITEMS_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("memory_items");
const COLD_CONTENT_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("cold_content");
const GRAPH_ENTITIES_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("graph_entities");
const GRAPH_RELATIONS_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("graph_relations");
const LZ4_SIZE_PREPENDED: &str = "lz4-size-prepended";

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
    /// File I/O failed.
    #[error("file I/O failed: {0}")]
    Io(#[from] std::io::Error),
    /// Vector index operation failed.
    #[error(transparent)]
    Vector(#[from] VectorIndexError),
    /// Durable store invariants were violated.
    #[error("storage invariant violated: {0}")]
    InvariantViolation(String),
}

/// Append-only event describing a durable memory-state change.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub enum MemoryEvent {
    /// A memory item was written.
    MemoryWritten {
        /// Full item state at write time.
        item: Box<MemoryItem>,
    },
    /// A memory item was soft-invalidated.
    MemoryInvalidated {
        /// Invalidated memory id.
        id: MemoryId,
        /// Timestamp that closes the valid-time interval.
        valid_to: OffsetDateTime,
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
    },
    /// A cold memory's content was moved to compressed storage.
    ContentCompacted {
        /// Memory id.
        id: MemoryId,
        /// Pointer to compressed content.
        pointer: CompactionRef,
    },
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
}

/// Entities and relations discovered by graph traversal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GraphTraversalResult {
    /// Entities reached by traversal, including the start entity when present.
    pub entities: Vec<Entity>,
    /// Relations followed during traversal.
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
    /// Event-log records.
    pub events: Vec<EventRecord>,
    /// Current materialized memory items.
    pub materialized_items: Vec<MemoryItem>,
    /// Compressed cold-content payloads.
    pub cold_contents: Vec<ColdContentRecord>,
    /// Current graph entities.
    pub graph_entities: Vec<Entity>,
    /// Current graph relations.
    pub graph_relations: Vec<Relation>,
}

/// Compressed cold-content payload included in a snapshot.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ColdContentRecord {
    /// Storage key referenced by `CompactionRef`.
    pub storage_key: String,
    /// Compressed payload bytes.
    pub bytes: Vec<u8>,
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
}

impl RedbMemoryStore {
    /// Opens or creates a `redb` store at `path`.
    ///
    /// # Errors
    ///
    /// Returns an error when the embedded database cannot be created or opened.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, StorageError> {
        let db = Database::create(path).map_err(embed)?;
        let store = Self { db };

        store.recover()?;

        Ok(store)
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
            let bytes = serde_json::to_vec(&record)?;

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
            let sequence = event_table.len().map_err(embed)?;
            let event = MemoryEvent::MemoryWritten {
                item: Box::new(item.clone()),
            };
            let record = EventRecord {
                sequence,
                recorded_at: OffsetDateTime::now_utc(),
                event,
            };
            let event_bytes = serde_json::to_vec(&record)?;
            let item_bytes = serde_json::to_vec(&item)?;
            let item_key = item.id.to_string();

            event_table
                .insert(sequence, event_bytes.as_slice())
                .map_err(embed)?;
            item_table
                .insert(item_key.as_str(), item_bytes.as_slice())
                .map_err(embed)?;

            sequence
        };

        write_txn.commit().map_err(embed)?;

        self.event(sequence)?.ok_or_else(|| {
            StorageError::Embedded("committed write event was not readable".to_owned())
        })
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
        vector_index
            .add(item.id, vector)
            .map_err(StorageError::from)?;

        item.embedding_ref = Some(EmbeddingRef {
            index: index_name.into(),
            vector_id: item.id.to_string(),
            model: model.into(),
            model_version: model_version.into(),
            dimensions: vector_index.dimensions(),
        });

        match self.write(item) {
            Ok(record) => Ok(record),
            Err(error) => {
                let _ = vector_index.delete_by_id(item.id);
                Err(error)
            }
        }
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
            let (_, value) = row.map_err(embed)?;
            records.push(serde_json::from_slice(value.value())?);
        }

        Ok(records)
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

    /// Writes a full snapshot of event log, materialized state, and cold content to one file.
    ///
    /// # Errors
    ///
    /// Returns an error when store tables cannot be read, the snapshot cannot be encoded, or the
    /// destination file cannot be written.
    pub fn snapshot(&self, path: impl AsRef<Path>) -> Result<(), StorageError> {
        let snapshot = StoreSnapshot {
            schema_version: 1,
            events: self.events()?,
            materialized_items: self.materialized_items()?,
            cold_contents: self.cold_content_records()?,
            graph_entities: self.graph_entities()?,
            graph_relations: self.graph_relations()?,
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
            .map(|value| serde_json::from_slice(value.value()).map_err(StorageError::from))
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
            let key = item.id.to_string();
            let bytes = serde_json::to_vec(item)?;

            table
                .insert(key.as_str(), bytes.as_slice())
                .map_err(embed)?;
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
            .map(|value| serde_json::from_slice(value.value()).map_err(StorageError::from))
            .transpose()
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
            let (_, value) = row.map_err(embed)?;
            items.push(serde_json::from_slice(value.value())?);
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
            records.push(ColdContentRecord {
                storage_key: key.value().to_owned(),
                bytes: value.value().to_vec(),
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
            let (_, value) = row.map_err(embed)?;
            entities.push(serde_json::from_slice(value.value())?);
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
            let (_, value) = row.map_err(embed)?;
            relations.push(serde_json::from_slice(value.value())?);
        }

        Ok(relations)
    }

    fn restore(&self, snapshot: StoreSnapshot) -> Result<(), StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut cold_table = write_txn.open_table(COLD_CONTENT_TABLE).map_err(embed)?;
            let mut entity_table = write_txn.open_table(GRAPH_ENTITIES_TABLE).map_err(embed)?;
            let mut relation_table = write_txn.open_table(GRAPH_RELATIONS_TABLE).map_err(embed)?;

            for event in snapshot.events {
                let bytes = serde_json::to_vec(&event)?;

                event_table
                    .insert(event.sequence, bytes.as_slice())
                    .map_err(embed)?;
            }

            for item in snapshot.materialized_items {
                let key = item.id.to_string();
                let bytes = serde_json::to_vec(&item)?;

                item_table
                    .insert(key.as_str(), bytes.as_slice())
                    .map_err(embed)?;
            }

            for cold_content in snapshot.cold_contents {
                cold_table
                    .insert(
                        cold_content.storage_key.as_str(),
                        cold_content.bytes.as_slice(),
                    )
                    .map_err(embed)?;
            }

            for entity in snapshot.graph_entities {
                let key = entity.id.to_string();
                let bytes = serde_json::to_vec(&entity)?;

                entity_table
                    .insert(key.as_str(), bytes.as_slice())
                    .map_err(embed)?;
            }

            for relation in snapshot.graph_relations {
                let key = relation.id.to_string();
                let bytes = serde_json::to_vec(&relation)?;

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
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut table = write_txn.open_table(GRAPH_ENTITIES_TABLE).map_err(embed)?;
            let key = entity.id.to_string();
            let bytes = serde_json::to_vec(entity)?;

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
            .map(|value| serde_json::from_slice(value.value()).map_err(StorageError::from))
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

    /// Resolves `entity` to an existing entity with the same type and stable key, or stores it.
    ///
    /// This is the graph deduplication boundary for aliases or alternate labels that refer to the
    /// same typed entity.
    ///
    /// # Errors
    ///
    /// Returns an error when graph entity rows cannot be read, written, or decoded.
    pub fn resolve_entity(&self, entity: &Entity) -> Result<Entity, StorageError> {
        if let Some(existing) =
            self.find_entity_by_stable_key(&entity.entity_type, &entity.stable_key)?
        {
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
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut table = write_txn.open_table(GRAPH_RELATIONS_TABLE).map_err(embed)?;
            let key = relation.id.to_string();
            let bytes = serde_json::to_vec(relation)?;

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
            .map(|value| serde_json::from_slice(value.value()).map_err(StorageError::from))
            .transpose()
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
        let contradiction =
            self.detect_relation_contradiction(proposed, proposed.timestamps.valid_from)?;
        let superseded_relation_id = contradiction
            .as_ref()
            .map(|contradiction| contradiction.existing.id);

        if let Some(superseded_relation_id) = superseded_relation_id {
            proposed.supersedes = Some(superseded_relation_id);
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

                let existing_bytes = serde_json::to_vec(&existing)?;
                relation_table
                    .insert(existing_key.as_str(), existing_bytes.as_slice())
                    .map_err(embed)?;
            }

            let proposed_key = proposed.id.to_string();
            let proposed_bytes = serde_json::to_vec(proposed)?;

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
            .map(|entity| (entity.id, entity))
            .collect::<BTreeMap<_, _>>();
        let relations = self.graph_relations()?;
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

                serde_json::from_slice(value.value())?
            };

            item.timestamps = item.timestamps.closed_at(valid_to);

            let sequence = event_table.len().map_err(embed)?;
            let record = EventRecord {
                sequence,
                recorded_at: OffsetDateTime::now_utc(),
                event: MemoryEvent::MemoryInvalidated { id, valid_to },
            };
            let event_bytes = serde_json::to_vec(&record)?;
            let item_bytes = serde_json::to_vec(&item)?;

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
        let (invalidation_sequence, write_sequence) = {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let superseded_key = superseded_id.to_string();
            let replacement_key = replacement.id.to_string();
            let mut superseded: MemoryItem = {
                let Some(value) = item_table.get(superseded_key.as_str()).map_err(embed)? else {
                    return Ok(None);
                };

                serde_json::from_slice(value.value())?
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

            let invalidation_sequence = event_table.len().map_err(embed)?;
            let write_sequence = invalidation_sequence + 1;
            let recorded_at = OffsetDateTime::now_utc();
            let invalidation_record = EventRecord {
                sequence: invalidation_sequence,
                recorded_at,
                event: MemoryEvent::MemoryInvalidated {
                    id: superseded_id,
                    valid_to,
                },
            };
            let write_record = EventRecord {
                sequence: write_sequence,
                recorded_at,
                event: MemoryEvent::MemoryWritten {
                    item: Box::new(replacement.clone()),
                },
            };
            let invalidation_event_bytes = serde_json::to_vec(&invalidation_record)?;
            let write_event_bytes = serde_json::to_vec(&write_record)?;
            let superseded_bytes = serde_json::to_vec(&superseded)?;
            let replacement_bytes = serde_json::to_vec(replacement)?;

            event_table
                .insert(invalidation_sequence, invalidation_event_bytes.as_slice())
                .map_err(embed)?;
            event_table
                .insert(write_sequence, write_event_bytes.as_slice())
                .map_err(embed)?;
            item_table
                .insert(superseded_key.as_str(), superseded_bytes.as_slice())
                .map_err(embed)?;
            item_table
                .insert(replacement_key.as_str(), replacement_bytes.as_slice())
                .map_err(embed)?;

            (invalidation_sequence, write_sequence)
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

        Ok(Some(ReconstructionReplacementRecord {
            invalidation,
            replacement_write,
        }))
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

                serde_json::from_slice(value.value())?
            };

            let previous_tier = item.tier;

            item.access_events.push(access_event.clone());
            item.significance =
                SignificanceConfig::default().recompute(&item, access_event.timestamp);
            item.tier =
                SignificanceConfig::default().promote_on_access(item.tier, item.significance);

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
            let event_bytes = serde_json::to_vec(&record)?;
            let item_bytes = serde_json::to_vec(&item)?;

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
                    },
                };
                let tier_event_bytes = serde_json::to_vec(&tier_record)?;

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

                serde_json::from_slice(value.value())?
            };
            let previous_tier = item.tier;

            item.significance = policy.recompute(&item, now);
            let demoted = policy.demote_for_score(item.tier, item.significance);
            item.tier = policy.clamp_tier_to_credence_floor(&item, demoted);

            let bytes = serde_json::to_vec(&item)?;

            if item.tier != previous_tier {
                let sequence = event_table.len().map_err(embed)?;
                let record = EventRecord {
                    sequence,
                    recorded_at: now,
                    event: MemoryEvent::TierChanged {
                        id,
                        from: previous_tier,
                        to: item.tier,
                    },
                };
                let event_bytes = serde_json::to_vec(&record)?;

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

                    serde_json::from_slice(value.value())?
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
                    },
                };
                let event_bytes = serde_json::to_vec(&event_record)?;
                let item_bytes = serde_json::to_vec(&item)?;

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

                serde_json::from_slice(value.value())?
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

            let event_bytes = serde_json::to_vec(&record)?;
            let item_bytes = serde_json::to_vec(&item)?;

            cold_table
                .insert(key.as_str(), compressed.as_slice())
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
        let decompressed = decompress_size_prepended(value.value()).map_err(compression)?;
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

fn embed(error: impl std::error::Error) -> StorageError {
    StorageError::Embedded(error.to_string())
}

fn compression(error: impl std::fmt::Display) -> StorageError {
    StorageError::Compression(error.to_string())
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

    type_allowed && time_allowed
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{
        CURRENT_MEMORY_SCHEMA_VERSION, CredenceTier, Provenance, SourceKind, TemporalBounds,
    };
    use crate::vector::{HnswVectorIndex, VectorIndex};
    use tempfile::NamedTempFile;
    use tempfile::tempdir;

    fn test_item(content: &str) -> MemoryItem {
        MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            id: MemoryId::new_v7(),
            content: content.to_owned(),
            compaction: None,
            embedding_ref: None,
            provenance: Provenance::new(SourceKind::User, None, "storage-test"),
            timestamps: TemporalBounds::open_from(
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ),
            tier: Tier::Warm,
            credence: CredenceTier::FirmAuthoritative,
            significance: 1.0,
            credence_floor: Tier::Warm,
            access_events: Vec::new(),
        }
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
        assert_eq!(events.len(), 3);
        assert!(matches!(events[0].event, MemoryEvent::MemoryWritten { .. }));
        assert!(matches!(
            events[1].event,
            MemoryEvent::MemoryInvalidated { .. }
        ));
        assert!(matches!(events[2].event, MemoryEvent::MemoryWritten { .. }));
        assert_eq!(report.event_count, 3);
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
            } if id == item_id
        ));
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

        let file = NamedTempFile::new().expect("tempfile should be created");
        let store = RedbMemoryStore::open(file.path()).expect("store should open");
        let item = test_item("trait-backed");

        assert_eq!(write_and_get(&store, &item), item);
    }
}
