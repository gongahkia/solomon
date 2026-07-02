// SPDX-License-Identifier: MIT

//! Deterministic store and corpus setup for Criterion benchmarks.

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use shibahama_core::api::{Shibahama, WriteEmbedding};
use shibahama_core::model::{CURRENT_MEMORY_SCHEMA_VERSION, EmbeddingRef};
use shibahama_core::model::{CredenceTier, MemoryId, MemoryItem, Provenance, SourceKind, Tier};
use shibahama_core::retrieval::{RecallCandidate, RecallRequest};
use shibahama_core::storage::{
    EventRecord, IngestCredencePolicy, MemoryEvent, MemoryWriteEvent, RedbMemoryStore,
    StoreSnapshot, StoredEmbedding,
};
use shibahama_core::vector::{HnswVectorIndex, VectorIndex};
use std::collections::BTreeSet;
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
        let tempdir = TempDir::new()?;
        let path = tempdir.path().join("shibahama-perf.redb");
        let snapshot_path = tempdir.path().join("shibahama-perf-snapshot.json");
        let snapshot = snapshot_for_range(0, scale);
        let snapshot_bytes = serde_json::to_vec(&snapshot)?;

        std::fs::write(&snapshot_path, snapshot_bytes)?;
        RedbMemoryStore::restore_from_snapshot(&path, &snapshot_path)?;

        let vector_index =
            HnswVectorIndex::with_capacity(EMBEDDING_DIMENSIONS, scale.saturating_add(1024));
        let engine = Shibahama::open(&path, vector_index)?;

        Ok(Self {
            _tempdir: tempdir,
            path,
            engine,
        })
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
        let request = RecallRequest::new(query, top_k, benchmark_now()).include_cold();

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

fn snapshot_for_range(start_index: usize, count: usize) -> StoreSnapshot {
    let mut events = Vec::with_capacity(count);
    let mut materialized_items = Vec::with_capacity(count);
    let mut embeddings = Vec::with_capacity(count);

    for offset in 0..count {
        let index = start_index.saturating_add(offset);
        let generated = generated_item(index, DEFAULT_SEED);
        let mut item = memory_item_for_generated(index, &generated);
        let sequence = u64::try_from(offset).unwrap_or(u64::MAX);

        item.embedding_ref = Some(EmbeddingRef {
            index: INDEX_NAME.to_owned(),
            vector_id: item.id.to_string(),
            model: EMBEDDING_MODEL.to_owned(),
            model_version: EMBEDDING_MODEL_VERSION.to_owned(),
            dimensions: EMBEDDING_DIMENSIONS,
        });

        events.push(EventRecord {
            sequence,
            recorded_at: item.timestamps.ingested_at,
            event: MemoryEvent::MemoryWritten {
                item: Box::new(item.clone()),
            },
        });
        embeddings.push(StoredEmbedding {
            memory_id: item.id,
            vector: generated.vector,
            index_name: INDEX_NAME.to_owned(),
            model: EMBEDDING_MODEL.to_owned(),
            model_version: EMBEDDING_MODEL_VERSION.to_owned(),
        });
        materialized_items.push(item);
    }

    StoreSnapshot {
        schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
        events,
        materialized_items,
        embeddings,
        cold_contents: Vec::new(),
        graph_entities: Vec::new(),
        graph_relations: Vec::new(),
    }
}

fn memory_item_for_generated(source_index: usize, item: &GeneratedItem) -> MemoryItem {
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
    event.into_item_with_policy(IngestCredencePolicy::default())
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

/// Computes average HNSW recall@10 against exact linear-scan ground truth.
///
/// # Errors
///
/// Returns an error when the vector index rejects a generated vector.
pub fn hnsw_recall_at_10(item_count: usize, query_count: usize) -> BenchResult<f64> {
    let mut index =
        HnswVectorIndex::with_capacity(EMBEDDING_DIMENSIONS, item_count.saturating_add(1024));
    let mut corpus = Vec::with_capacity(item_count);
    let mut hits = 0_u32;

    for item_index in 0..item_count {
        let id = MemoryId::new_v7();
        let vector = generated_item(item_index, DEFAULT_SEED).vector;

        index.add(id, &vector)?;
        corpus.push((id, vector));
    }

    for query_index in 0..query_count {
        let query = generated_item(item_count.saturating_add(query_index), DEFAULT_SEED).vector;
        let exact_ids = exact_top_k(&corpus, &query, TOP_K);
        let hnsw_ids = index
            .search(&query, TOP_K)?
            .into_iter()
            .map(|result| result.id)
            .collect::<BTreeSet<_>>();
        let query_hits = exact_ids.iter().filter(|id| hnsw_ids.contains(id)).count();

        hits = hits.saturating_add(u32::try_from(query_hits).unwrap_or(u32::MAX));
    }

    let denominator = query_count.saturating_mul(TOP_K);
    let denominator = u32::try_from(denominator).unwrap_or(u32::MAX);

    Ok(f64::from(hits) / f64::from(denominator))
}

/// Returns the fixed timestamp used for benchmark recall.
#[must_use]
pub fn benchmark_now() -> OffsetDateTime {
    OffsetDateTime::UNIX_EPOCH + TimeDuration::days(30)
}

fn exact_top_k(corpus: &[(MemoryId, Vec<f32>)], query: &[f32], top_k: usize) -> BTreeSet<MemoryId> {
    let mut distances = corpus
        .iter()
        .map(|(id, vector)| (*id, squared_distance(vector, query)))
        .collect::<Vec<_>>();

    distances.sort_by(|left, right| {
        left.1
            .total_cmp(&right.1)
            .then_with(|| left.0.cmp(&right.0))
    });

    distances
        .into_iter()
        .take(top_k)
        .map(|(id, _)| id)
        .collect()
}

fn squared_distance(left: &[f32], right: &[f32]) -> f32 {
    left.iter()
        .zip(right)
        .map(|(left, right)| {
            let delta = left - right;
            delta * delta
        })
        .sum()
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
