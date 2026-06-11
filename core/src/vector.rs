// SPDX-License-Identifier: MIT

//! Vector index abstraction for embedding-backed retrieval.

use crate::model::MemoryId;
use fast_hnsw::distance::Euclidean;
use fast_hnsw::{Builder, LabeledIndex};
use std::collections::{HashMap, HashSet};
use thiserror::Error;

/// Error returned by vector index backends.
#[derive(Debug, Error)]
pub enum VectorIndexError {
    /// Vector dimensions did not match the index.
    #[error("dimension mismatch: expected {expected}, got {actual}")]
    DimensionMismatch {
        /// Expected number of dimensions.
        expected: usize,
        /// Actual number of dimensions.
        actual: usize,
    },
    /// Backend-specific failure.
    #[error("vector backend failed: {0}")]
    Backend(String),
}

/// Search result returned by a vector index.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct VectorSearchResult {
    /// Memory id attached to the vector.
    pub id: MemoryId,
    /// Backend distance where lower is better.
    pub distance: f32,
}

/// Pluggable vector index contract.
pub trait VectorIndex {
    /// Adds or replaces the vector associated with `id`.
    ///
    /// # Errors
    ///
    /// Returns an error when dimensions are invalid or the backend cannot store the vector.
    fn add(&mut self, id: MemoryId, vector: &[f32]) -> Result<(), VectorIndexError>;

    /// Searches the index for the `top_k` nearest vectors.
    ///
    /// # Errors
    ///
    /// Returns an error when dimensions are invalid or the backend cannot search.
    fn search(
        &self,
        query: &[f32],
        top_k: usize,
    ) -> Result<Vec<VectorSearchResult>, VectorIndexError>;

    /// Removes the vector associated with `id`, if present.
    ///
    /// # Errors
    ///
    /// Returns an error when the backend cannot remove the vector.
    fn delete_by_id(&mut self, id: MemoryId) -> Result<(), VectorIndexError>;

    /// Returns the configured vector dimensionality.
    fn dimensions(&self) -> usize;
}

/// In-process HNSW vector index.
pub struct HnswVectorIndex {
    dimensions: usize,
    ef_search: usize,
    index: LabeledIndex<Euclidean, String>,
    deleted_slots: HashSet<usize>,
    slots_by_id: HashMap<MemoryId, usize>,
    ids_by_slot: Vec<MemoryId>,
}

impl HnswVectorIndex {
    /// Creates an HNSW vector index with a default capacity hint.
    #[must_use]
    pub fn new(dimensions: usize) -> Self {
        Self::with_capacity(dimensions, 1024)
    }

    /// Creates an HNSW vector index with a capacity hint.
    #[must_use]
    pub fn with_capacity(dimensions: usize, capacity: usize) -> Self {
        let index = Builder::new()
            .m(16)
            .ef_construction(200)
            .capacity(capacity)
            .build_labeled(Euclidean);

        Self {
            dimensions,
            ef_search: 64,
            index,
            deleted_slots: HashSet::new(),
            slots_by_id: HashMap::new(),
            ids_by_slot: Vec::new(),
        }
    }

    fn ensure_dimensions(&self, vector: &[f32]) -> Result<(), VectorIndexError> {
        if vector.len() != self.dimensions {
            return Err(VectorIndexError::DimensionMismatch {
                expected: self.dimensions,
                actual: vector.len(),
            });
        }

        Ok(())
    }
}

impl VectorIndex for HnswVectorIndex {
    fn add(&mut self, id: MemoryId, vector: &[f32]) -> Result<(), VectorIndexError> {
        self.ensure_dimensions(vector)?;

        if let Some(old_slot) = self.slots_by_id.insert(id, self.ids_by_slot.len()) {
            self.deleted_slots.insert(old_slot);
        }

        let slot = self.index.insert(vector.to_vec(), id.to_string());
        self.ids_by_slot.push(id);
        debug_assert_eq!(slot + 1, self.ids_by_slot.len());

        Ok(())
    }

    fn search(
        &self,
        query: &[f32],
        top_k: usize,
    ) -> Result<Vec<VectorSearchResult>, VectorIndexError> {
        self.ensure_dimensions(query)?;

        if top_k == 0 {
            return Ok(Vec::new());
        }

        let search_k = top_k.saturating_add(self.deleted_slots.len()).max(top_k);
        let ef = self.ef_search.max(search_k);

        Ok(self
            .index
            .search(query, search_k, ef)
            .into_iter()
            .filter(|result| !self.deleted_slots.contains(&result.id))
            .take(top_k)
            .map(|result| VectorSearchResult {
                id: self.ids_by_slot[result.id],
                distance: result.distance,
            })
            .collect())
    }

    fn delete_by_id(&mut self, id: MemoryId) -> Result<(), VectorIndexError> {
        if let Some(slot) = self.slots_by_id.remove(&id) {
            self.deleted_slots.insert(slot);
        }

        Ok(())
    }

    fn dimensions(&self) -> usize {
        self.dimensions
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct EmptyIndex {
        dimensions: usize,
    }

    impl VectorIndex for EmptyIndex {
        fn add(&mut self, _id: MemoryId, vector: &[f32]) -> Result<(), VectorIndexError> {
            if vector.len() != self.dimensions {
                return Err(VectorIndexError::DimensionMismatch {
                    expected: self.dimensions,
                    actual: vector.len(),
                });
            }

            Ok(())
        }

        fn search(
            &self,
            query: &[f32],
            _top_k: usize,
        ) -> Result<Vec<VectorSearchResult>, VectorIndexError> {
            if query.len() != self.dimensions {
                return Err(VectorIndexError::DimensionMismatch {
                    expected: self.dimensions,
                    actual: query.len(),
                });
            }

            Ok(Vec::new())
        }

        fn delete_by_id(&mut self, _id: MemoryId) -> Result<(), VectorIndexError> {
            Ok(())
        }

        fn dimensions(&self) -> usize {
            self.dimensions
        }
    }

    #[test]
    fn vector_index_contract_reports_dimensions() {
        let mut index = EmptyIndex { dimensions: 3 };
        let id = MemoryId::new_v7();

        index.add(id, &[1.0, 2.0, 3.0]).expect("add should work");

        assert_eq!(index.dimensions(), 3);
        assert!(matches!(
            index.search(&[1.0, 2.0], 1),
            Err(VectorIndexError::DimensionMismatch {
                expected: 3,
                actual: 2
            })
        ));
    }

    #[test]
    fn hnsw_index_searches_nearest_vectors() {
        let mut index = HnswVectorIndex::with_capacity(2, 8);
        let near = MemoryId::new_v7();
        let middle = MemoryId::new_v7();
        let far = MemoryId::new_v7();

        index.add(near, &[0.0, 0.0]).expect("near should add");
        index.add(middle, &[1.0, 1.0]).expect("middle should add");
        index.add(far, &[10.0, 10.0]).expect("far should add");

        let results = index.search(&[0.1, 0.1], 2).expect("search should work");

        assert_eq!(results.len(), 2);
        assert_eq!(results[0].id, near);
        assert_eq!(results[1].id, middle);
        assert!(results[0].distance < results[1].distance);
    }

    #[test]
    fn hnsw_index_tombstones_deleted_ids() {
        let mut index = HnswVectorIndex::with_capacity(2, 8);
        let deleted = MemoryId::new_v7();
        let remaining = MemoryId::new_v7();

        index.add(deleted, &[0.0, 0.0]).expect("deleted should add");
        index
            .add(remaining, &[1.0, 1.0])
            .expect("remaining should add");
        index.delete_by_id(deleted).expect("delete should succeed");

        let results = index.search(&[0.0, 0.0], 2).expect("search should work");

        assert_eq!(results.len(), 1);
        assert_eq!(results[0].id, remaining);
    }
}
