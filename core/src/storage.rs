// SPDX-License-Identifier: MIT

//! Durable storage primitives for Shibahama.

use crate::model::{AccessEvent, MemoryId, MemoryItem, Tier};
use redb::{Database, ReadableDatabase, ReadableTable, ReadableTableMetadata, TableDefinition};
use serde::{Deserialize, Serialize};
use std::path::Path;
use thiserror::Error;
use time::OffsetDateTime;

const EVENT_LOG_TABLE: TableDefinition<u64, &[u8]> = TableDefinition::new("event_log");
const MEMORY_ITEMS_TABLE: TableDefinition<&str, &[u8]> = TableDefinition::new("memory_items");

/// Error returned by storage backends.
#[derive(Debug, Error)]
pub enum StorageError {
    /// Embedded database operation failed.
    #[error("embedded storage operation failed: {0}")]
    Embedded(String),
    /// Event or item serialization failed.
    #[error("serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
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

        Ok(Self { db })
    }

    /// Appends an event and returns its durable record.
    ///
    /// # Errors
    ///
    /// Returns an error when the event cannot be serialized, appended, committed, or read back.
    pub fn append_event(&self, event: MemoryEvent) -> Result<EventRecord, StorageError> {
        let write_txn = self.db.begin_write().map_err(embed)?;
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
        let write_txn = self.db.begin_write().map_err(embed)?;
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
        let write_txn = self.db.begin_write().map_err(embed)?;
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
        let write_txn = self.db.begin_write().map_err(embed)?;
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
}

fn embed(error: impl std::error::Error) -> StorageError {
    StorageError::Embedded(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{
        CURRENT_MEMORY_SCHEMA_VERSION, CredenceTier, Provenance, SourceKind, TemporalBounds,
    };
    use tempfile::NamedTempFile;

    fn test_item(content: &str) -> MemoryItem {
        MemoryItem {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            id: MemoryId::new_v7(),
            content: content.to_owned(),
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
}
