// SPDX-License-Identifier: MIT

//! Small public API facade.

use crate::model::{AccessOutcome, MemoryId, MemoryItem};
use crate::retrieval::{RecallCandidate, RecallError, RecallRequest, recall, timeline};
use crate::storage::{MemoryWriteEvent, RedbMemoryStore, StorageError};
use crate::vector::{VectorIndex, VectorIndexError};
use std::path::Path;
use thiserror::Error;

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

    /// Returns the current materialized memory for `id`.
    ///
    /// # Errors
    ///
    /// Returns an error when the item cannot be read.
    pub fn why(&self, id: MemoryId) -> Result<Option<MemoryItem>, ShibahamaError> {
        Ok(self.store.get(id)?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Provenance, SourceKind};
    use crate::retrieval::RecallRequest;
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
        assert_eq!(
            shibahama
                .why(item.id)
                .expect("why should read")
                .expect("item should exist")
                .content,
            "facade memory"
        );
    }
}
