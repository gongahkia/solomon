// SPDX-License-Identifier: MIT

//! Deterministic store and corpus setup for Criterion benchmarks.

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use shibahama_core::api::{Shibahama, WriteEmbedding};
use shibahama_core::model::{CredenceTier, MemoryId, MemoryItem, Provenance, SourceKind, Tier};
use shibahama_core::retrieval::{RecallCandidate, RecallRequest};
use shibahama_core::storage::MemoryWriteEvent;
use shibahama_core::vector::HnswVectorIndex;
use std::path::PathBuf;
use std::time::{Duration as StdDuration, Instant};
use tempfile::TempDir;
use time::{Duration as TimeDuration, OffsetDateTime};

/// Default embedding dimension used by the Phase A performance spec.
pub const EMBEDDING_DIMENSIONS: usize = 768;
/// Default deterministic corpus seed.
pub const DEFAULT_SEED: u64 = 0x5f1b_a4d0_2026_0001;
/// Default scale for local Criterion smoke benches.
pub const DEFAULT_BENCH_SCALE: usize = 1_000;
/// Default recall top-k.
pub const TOP_K: usize = 10;
/// Logical vector index name used in benchmark embeddings.
pub const INDEX_NAME: &str = "perf-hnsw";
/// Synthetic embedding model label used in benchmark metadata.
pub const EMBEDDING_MODEL: &str = "synthetic-unit-rng";
/// Synthetic embedding model version used in benchmark metadata.
pub const EMBEDDING_MODEL_VERSION: &str = "phase-a-v1";

const QUERY_SEED_OFFSET: u64 = 0x9e37_79b9_7f4a_7c15;
const WRITE_SEED_OFFSET: u64 = 0xd1b5_4a32_d192_ed03;

/// Result type used by benchmark setup helpers.
pub type BenchResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

/// Deterministic synthetic item plus embedding vector.
#[derive(Clone, Debug)]
pub struct GeneratedItem {
    /// Stable corpus index.
    pub index: usize,
    /// Stored memory content.
    pub content: String,
    /// Unit-normalized embedding vector.
    pub vector: Vec<f32>,
    /// Initial storage tier.
    pub tier: Tier,
    /// Explicit credence tier.
    pub credence: CredenceTier,
    /// Provenance source kind.
    pub source_kind: SourceKind,
}

/// Result of the post-write availability check.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PostWriteAvailability {
    /// Newly written memory id.
    pub memory_id: MemoryId,
    /// Whether immediate recall found the new memory.
    pub available: bool,
    /// Latency of the first recall after the write.
    pub recall_latency: StdDuration,
}

/// Temporary benchmark store with a live Shibahama engine.
pub struct BenchStore {
    _tempdir: TempDir,
    /// Redb file path inside the temporary directory.
    pub path: PathBuf,
    /// Active Shibahama engine.
    pub engine: Shibahama<HnswVectorIndex>,
}

impl BenchStore {
    /// Opens an empty benchmark store with capacity for `capacity` vectors.
    ///
    /// # Errors
    ///
    /// Returns an error when the temporary directory or store cannot be created.
    pub fn empty(capacity: usize) -> BenchResult<Self> {
        let tempdir = TempDir::new()?;
        let path = tempdir.path().join("shibahama-perf.redb");
        let vector_index = HnswVectorIndex::with_capacity(EMBEDDING_DIMENSIONS, capacity);
        let engine = Shibahama::open(&path, vector_index)?;

        Ok(Self {
            _tempdir: tempdir,
            path,
            engine,
        })
    }

    /// Opens a benchmark store populated with `scale` deterministic items.
    ///
    /// # Errors
    ///
    /// Returns an error when setup writes or indexing fail.
    pub fn populated(scale: usize) -> BenchResult<Self> {
        let mut store = Self::empty(scale.saturating_add(1024))?;
        store.ingest_range(0, scale)?;

        Ok(store)
    }

    /// Writes `count` deterministic items beginning at `start_index`.
    ///
    /// # Errors
    ///
    /// Returns an error when a write or vector-index insert fails.
    pub fn ingest_range(&mut self, start_index: usize, count: usize) -> BenchResult<()> {
        for index in start_index..start_index.saturating_add(count) {
            let item = generated_item(index, DEFAULT_SEED);
            self.write_generated(index, &item)?;
        }

        Ok(())
    }

    /// Writes one generated item with its embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when the memory or embedding cannot be written.
    pub fn write_generated(
        &mut self,
        source_index: usize,
        item: &GeneratedItem,
    ) -> BenchResult<MemoryItem> {
        let now = timestamp_for(source_index);
        let provenance = Provenance::new(
            item.source_kind,
            Some(format!("perf:item:{source_index:08}")),
            "shibahama-perf",
        );
        let mut event = MemoryWriteEvent::with_explicit_credence(
            item.content.clone(),
            provenance,
            now,
            now,
            item.tier,
            item.credence,
            Tier::Cold,
        );

        event.significance = 1.0;

        Ok(self.engine.write_with_embedding(
            event,
            WriteEmbedding {
                vector: &item.vector,
                index_name: INDEX_NAME,
                model: EMBEDDING_MODEL,
                model_version: EMBEDDING_MODEL_VERSION,
            },
        )?)
    }

    /// Runs recall at the benchmark timestamp.
    ///
    /// # Errors
    ///
    /// Returns an error when recall fails.
    pub fn recall(&self, query: &[f32], top_k: usize) -> BenchResult<Vec<RecallCandidate>> {
        let request = RecallRequest::new(query, top_k, benchmark_now());

        Ok(self.engine.recall(&request)?)
    }

    /// Writes a distinctive item and checks first-call recallability.
    ///
    /// # Errors
    ///
    /// Returns an error when the write or recall fails.
    pub fn post_write_availability(&mut self, index: usize) -> BenchResult<PostWriteAvailability> {
        let item = generated_item(index, DEFAULT_SEED ^ WRITE_SEED_OFFSET);
        let written = self.write_generated(index, &item)?;
        let started_at = Instant::now();
        let candidates = self.recall(&item.vector, TOP_K)?;
        let recall_latency = started_at.elapsed();
        let available = candidates
            .iter()
            .any(|candidate| candidate.id == written.id);

        Ok(PostWriteAvailability {
            memory_id: written.id,
            available,
            recall_latency,
        })
    }
}

/// Generates one deterministic synthetic item.
#[must_use]
pub fn generated_item(index: usize, seed: u64) -> GeneratedItem {
    GeneratedItem {
        index,
        content: format!("item_{index:08}"),
        vector: unit_vector(seed_for_index(seed, index)),
        tier: tier_for_index(index),
        credence: credence_for_index(index),
        source_kind: source_kind_for_index(index),
    }
}

/// Generates a held-out query vector that is not in the corpus.
#[must_use]
pub fn held_out_query(seed: u64) -> Vec<f32> {
    unit_vector(seed ^ QUERY_SEED_OFFSET)
}

/// Returns the fixed timestamp used for benchmark recall.
#[must_use]
pub fn benchmark_now() -> OffsetDateTime {
    OffsetDateTime::UNIX_EPOCH + TimeDuration::days(30)
}

fn timestamp_for(index: usize) -> OffsetDateTime {
    let seconds = i64::try_from(index).unwrap_or(i64::MAX / 2);

    OffsetDateTime::UNIX_EPOCH + TimeDuration::seconds(seconds)
}

fn seed_for_index(seed: u64, index: usize) -> u64 {
    seed ^ u64::try_from(index)
        .unwrap_or(u64::MAX)
        .wrapping_mul(0x9e37_79b9_7f4a_7c15)
}

fn unit_vector(seed: u64) -> Vec<f32> {
    let mut rng = StdRng::seed_from_u64(seed);
    let mut vector = (0..EMBEDDING_DIMENSIONS)
        .map(|_| rng.gen_range(-1.0_f32..=1.0_f32))
        .collect::<Vec<_>>();
    let norm = vector
        .iter()
        .map(|value| value.mul_add(*value, 0.0))
        .sum::<f32>()
        .sqrt()
        .max(f32::EPSILON);

    for value in &mut vector {
        *value /= norm;
    }

    vector
}

fn tier_for_index(index: usize) -> Tier {
    match index % 3 {
        0 => Tier::Hot,
        1 => Tier::Warm,
        _ => Tier::Cold,
    }
}

fn credence_for_index(index: usize) -> CredenceTier {
    match index % 10 {
        0 => CredenceTier::VerifiedSource,
        1 | 2 => CredenceTier::ModelInferred,
        _ => CredenceTier::Unverified,
    }
}

fn source_kind_for_index(index: usize) -> SourceKind {
    match index % 5 {
        0 => SourceKind::User,
        1 => SourceKind::Agent,
        2 => SourceKind::File,
        3 => SourceKind::Tool,
        _ => SourceKind::Web,
    }
}
