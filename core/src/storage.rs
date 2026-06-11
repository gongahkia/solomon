// SPDX-License-Identifier: MIT

//! Durable storage primitives for Shibahama.

use crate::model::{AccessEvent, CompactionRef, MemoryId, MemoryItem, Tier};
use lz4_flex::{compress_prepend_size, decompress_size_prepended};
use redb::{
    Database, Durability, ReadableDatabase, ReadableTable, ReadableTableMetadata, TableDefinition,
};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;
use thiserror::Error;
use time::OffsetDateTime;

const EVENT_LOG_TABLE: TableDefinition<u64, &[u8]> = TableDefinition::new("event_log");
const MEMORY_ITEMS_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("memory_items");
const COLD_CONTENT_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("cold_content");
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

        Ok(RecoveryReport {
            event_count: events.len(),
            materialized_item_count: materialized_items.len(),
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

    fn restore(&self, snapshot: StoreSnapshot) -> Result<(), StorageError> {
        let mut write_txn = self.db.begin_write().map_err(embed)?;
        write_txn
            .set_durability(Durability::Immediate)
            .map_err(embed)?;
        {
            let mut event_table = write_txn.open_table(EVENT_LOG_TABLE).map_err(embed)?;
            let mut item_table = write_txn.open_table(MEMORY_ITEMS_TABLE).map_err(embed)?;
            let mut cold_table = write_txn.open_table(COLD_CONTENT_TABLE).map_err(embed)?;

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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{
        CURRENT_MEMORY_SCHEMA_VERSION, CredenceTier, Provenance, SourceKind, TemporalBounds,
    };
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
