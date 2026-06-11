// SPDX-License-Identifier: MIT

//! Vector index abstraction for embedding-backed retrieval.

use crate::model::MemoryId;
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
}
