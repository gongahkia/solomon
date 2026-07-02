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
use shibahama_core::vector::{HnswVectorIndex, HnswVectorParams, VectorIndex};
use std::collections::BTreeSet;
use std::io::{Error as IoError, ErrorKind};
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

/// Median recall latency by tier in nanoseconds.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TierLatencyBreakdown {
    /// Hot-tier recall latency.
    pub hot_ns: u128,
    /// Warm-tier recall latency.
    pub warm_ns: u128,
    /// Cold compacted-content recall latency.
    pub cold_ns: u128,
}

/// Temporary benchmark store with a live Shibahama engine.
pub struct BenchStore {
    _tempdir: TempDir,
    /// Redb file path inside the temporary directory.
    pub path: PathBuf,
    /// Active Shibahama engine.
    pub engine: Shibahama<HnswVectorIndex>,
    quality_ids: Option<Vec<MemoryId>>,
}

impl BenchStore {
    /// Opens an empty benchmark store with capacity for `capacity` vectors.
    ///
    /// # Errors
    ///
    /// Returns an error when the temporary directory or store cannot be created.
    pub fn empty(capacity: usize) -> BenchResult<Self> {
        Self::empty_with_params(capacity, HnswVectorParams::default())
    }

    /// Opens an empty benchmark store with explicit HNSW parameters.
    ///
    /// # Errors
    ///
    /// Returns an error when the temporary directory or store cannot be created.
    pub fn empty_with_params(capacity: usize, params: HnswVectorParams) -> BenchResult<Self> {
        let tempdir = TempDir::new()?;
        let path = tempdir.path().join("shibahama-perf.redb");
        let vector_index = HnswVectorIndex::with_params(EMBEDDING_DIMENSIONS, capacity, params);
        let engine = Shibahama::open(&path, vector_index)?;

        Ok(Self {
            _tempdir: tempdir,
            path,
            engine,
            quality_ids: None,
        })
    }

    /// Opens a benchmark store populated with `scale` deterministic items.
    ///
    /// # Errors
    ///
    /// Returns an error when setup writes or indexing fail.
    pub fn populated(scale: usize) -> BenchResult<Self> {
        Self::populated_with_quality_ids(scale, false)
    }

    /// Opens a populated benchmark store and retains ids for exact-quality checks.
    ///
    /// # Errors
    ///
    /// Returns an error when snapshot setup or vector-index hydration fails.
    pub fn populated_for_quality(scale: usize) -> BenchResult<Self> {
        Self::populated_with_quality_ids(scale, true)
    }

    /// Opens a store populated through the write path and returns ingest throughput.
    ///
    /// # Errors
    ///
    /// Returns an error when setup writes or indexing fail.
    pub fn populated_by_ingest(scale: usize, keep_quality_ids: bool) -> BenchResult<(Self, f64)> {
        Self::populated_by_ingest_with_params(scale, keep_quality_ids, HnswVectorParams::default())
    }

    /// Opens a write-populated store with explicit HNSW parameters and ingest throughput.
    ///
    /// # Errors
    ///
    /// Returns an error when setup writes or indexing fail.
    pub fn populated_by_ingest_with_params(
        scale: usize,
        keep_quality_ids: bool,
        params: HnswVectorParams,
    ) -> BenchResult<(Self, f64)> {
        let mut store = Self::empty_with_params(scale.saturating_add(1024), params)?;
        let started_at = Instant::now();
        let quality_ids = store.ingest_range_with_ids(0, scale)?;
        let elapsed_seconds = started_at.elapsed().as_secs_f64().max(f64::EPSILON);

        if keep_quality_ids {
            store.quality_ids = Some(quality_ids);
        }

        Ok((store, scale as f64 / elapsed_seconds))
    }

    fn populated_with_quality_ids(scale: usize, keep_quality_ids: bool) -> BenchResult<Self> {
        let tempdir = TempDir::new()?;
        let path = tempdir.path().join("shibahama-perf.redb");
        let snapshot_path = tempdir.path().join("shibahama-perf-snapshot.json");
        let (snapshot, quality_ids) = snapshot_for_range(0, scale);
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
            quality_ids: keep_quality_ids.then_some(quality_ids),
        })
    }

    /// Writes `count` deterministic items beginning at `start_index`.
    ///
    /// # Errors
    ///
    /// Returns an error when a write or vector-index insert fails.
    pub fn ingest_range(&mut self, start_index: usize, count: usize) -> BenchResult<()> {
        self.ingest_range_with_ids(start_index, count).map(|_| ())
    }

    /// Writes deterministic items and returns their memory ids.
    ///
    /// # Errors
    ///
    /// Returns an error when a write or vector-index insert fails.
    pub fn ingest_range_with_ids(
        &mut self,
        start_index: usize,
        count: usize,
    ) -> BenchResult<Vec<MemoryId>> {
        let mut ids = Vec::with_capacity(count);

        for index in start_index..start_index.saturating_add(count) {
            let item = generated_item(index, DEFAULT_SEED);
            let written = self.write_generated(index, &item)?;

            ids.push(written.id);
        }

        Ok(ids)
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

    /// Computes average HNSW recall@10 against exact linear-scan ground truth.
    ///
    /// # Errors
    ///
    /// Returns an error when this store was not opened with quality ids, or when vector search
    /// fails.
    pub fn hnsw_recall_at_10(&self, query_count: usize) -> BenchResult<f64> {
        let Some(ids) = &self.quality_ids else {
            return Err(invalid_input(
                "quality ids were not retained for this store".to_owned(),
            ));
        };
        let corpus = ids
            .iter()
            .enumerate()
            .map(|(index, id)| (*id, generated_item(index, DEFAULT_SEED).vector))
            .collect::<Vec<_>>();
        let mut hits = 0_u32;

        for query_index in 0..query_count {
            let query = generated_item(ids.len().saturating_add(query_index), DEFAULT_SEED).vector;
            let exact_ids = exact_top_k(&corpus, &query, TOP_K);
            let hnsw_ids = self
                .engine
                .vector_index()
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

    /// Measures median exact-hit recall latency for hot, warm, and compacted cold items.
    ///
    /// # Errors
    ///
    /// Returns an error when this store lacks retained ids, cold compaction fails, or recall misses
    /// a target item.
    pub fn tier_latency_breakdown(&self, repetitions: usize) -> BenchResult<TierLatencyBreakdown> {
        let Some(ids) = &self.quality_ids else {
            return Err(invalid_input(
                "quality ids were not retained for this store".to_owned(),
            ));
        };
        let hot = tier_target(ids, Tier::Hot)?;
        let warm = tier_target(ids, Tier::Warm)?;
        let cold = tier_target(ids, Tier::Cold)?;

        self.engine.store().compact_cold_item(cold.id)?;

        Ok(TierLatencyBreakdown {
            hot_ns: self.recall_latency_for_target(hot, repetitions)?,
            warm_ns: self.recall_latency_for_target(warm, repetitions)?,
            cold_ns: self.recall_latency_for_target(cold, repetitions)?,
        })
    }

    fn recall_latency_for_target(
        &self,
        target: TierTarget,
        repetitions: usize,
    ) -> BenchResult<u128> {
        let query = generated_item(target.index, DEFAULT_SEED).vector;
        let mut latencies = Vec::with_capacity(repetitions);

        for _ in 0..repetitions {
            let started_at = Instant::now();
            let candidates = self.recall(&query, TOP_K)?;

            if !candidates.iter().any(|candidate| candidate.id == target.id) {
                return Err(invalid_input(format!(
                    "tier recall missed {:?} target {}",
                    target.tier, target.id
                )));
            }

            latencies.push(started_at.elapsed().as_nanos());
        }

        Ok(median(&mut latencies))
    }
}

#[derive(Clone, Copy)]
struct TierTarget {
    index: usize,
    id: MemoryId,
    tier: Tier,
}

fn snapshot_for_range(start_index: usize, count: usize) -> (StoreSnapshot, Vec<MemoryId>) {
    let mut events = Vec::with_capacity(count);
    let mut materialized_items = Vec::with_capacity(count);
    let mut embeddings = Vec::with_capacity(count);
    let mut quality_ids = Vec::with_capacity(count);

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
        quality_ids.push(item.id);
        materialized_items.push(item);
    }

    (
        StoreSnapshot {
            schema_version: CURRENT_MEMORY_SCHEMA_VERSION,
            events,
            materialized_items,
            embeddings,
            cold_contents: Vec::new(),
            graph_entities: Vec::new(),
            graph_relations: Vec::new(),
        },
        quality_ids,
    )
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

fn tier_target(ids: &[MemoryId], tier: Tier) -> BenchResult<TierTarget> {
    for (index, id) in ids.iter().enumerate() {
        if tier_for_index(index) == tier {
            return Ok(TierTarget {
                index,
                id: *id,
                tier,
            });
        }
    }

    Err(invalid_input(format!(
        "no {tier:?} target in generated corpus"
    )))
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

fn median(values: &mut [u128]) -> u128 {
    values.sort_unstable();
    values[values.len() / 2]
}

fn invalid_input(message: String) -> Box<dyn std::error::Error + Send + Sync> {
    Box::new(IoError::new(ErrorKind::InvalidInput, message))
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
