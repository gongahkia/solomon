// SPDX-License-Identifier: MIT

//! `napi-rs` module for the Shibahama Node.js package.

#![allow(missing_docs)]
#![allow(clippy::needless_pass_by_value)]

use napi::bindgen_prelude::*;
use napi_derive::napi;
use shibahama_core::api::{
    Shibahama as CoreShibahama, ShibahamaError, WhyTrace as CoreWhyTrace, WriteEmbedding,
};
use shibahama_core::model::{
    AccessOutcome, CredenceTier, MemoryId, MemoryItem as CoreMemoryItem, MemoryKind,
    Provenance as CoreProvenance, SourceKind, Tier,
};
use shibahama_core::retrieval::{
    RecallCandidate as CoreRecallCandidate, RecallCandidateCurrency, RecallCandidateSource,
    RecallRequest,
};
use shibahama_core::significance::SignificanceBreakdown as CoreSignificanceBreakdown;
use shibahama_core::storage::MemoryWriteEvent;
use shibahama_core::vector::HnswVectorIndex;
use std::sync::Mutex;
use time::OffsetDateTime;
use uuid::Uuid;

#[napi(object)]
#[derive(Clone)]
pub struct Provenance {
    pub source_kind: String,
    pub source_ref: Option<String>,
    pub ingested_by: String,
}

#[napi(object)]
#[derive(Clone)]
pub struct MemoryItem {
    pub id: String,
    pub content: String,
    pub kind: String,
    pub provenance: Provenance,
    pub tier: String,
    pub credence: String,
    pub significance: f64,
    pub credence_floor: String,
    pub valid_from_unix: f64,
    pub valid_to_unix: Option<f64>,
    pub ingested_at_unix: f64,
}

#[napi(object)]
#[derive(Clone)]
pub struct RecallCandidate {
    pub id: String,
    pub item: MemoryItem,
    pub kind: String,
    pub provenance: Provenance,
    pub tier: String,
    pub currency: String,
    pub load_bearing_possibly_stale: bool,
    pub cold_tier_retrieval: bool,
    pub vector_distance: f64,
    pub similarity_score: f64,
    pub significance_score: f64,
    pub recency_score: f64,
    pub graph_score: f64,
    pub source: String,
    pub rank_score: f64,
    pub read_safety_findings: Vec<String>,
}

#[napi(object)]
#[derive(Clone)]
pub struct SignificanceBreakdown {
    pub base_score: f64,
    pub decay_multiplier: f64,
    pub decayed_base: f64,
    pub reinforcement: f64,
    pub outcome_bonus: f64,
    pub contradiction_penalty: f64,
    pub graph_centrality: f64,
    pub final_score: f64,
}

#[napi(object)]
#[derive(Clone)]
pub struct WhyTrace {
    pub item: MemoryItem,
    pub significance: SignificanceBreakdown,
    pub provenance: Provenance,
    pub tier_current: String,
    pub tier_credence: String,
    pub tier_credence_floor: String,
    pub currency_state: String,
    pub currency_as_of_unix: f64,
    pub valid_from_unix: f64,
    pub valid_to_unix: Option<f64>,
    pub ingested_at_unix: f64,
    pub audit_trail: Vec<String>,
}

#[napi(object)]
#[derive(Default)]
pub struct WriteOptions {
    pub vector: Option<Vec<f64>>,
    pub source_kind: Option<String>,
    pub source_ref: Option<String>,
    pub ingested_by: Option<String>,
    pub valid_from_unix: Option<f64>,
    pub ingested_at_unix: Option<f64>,
    pub kind: Option<String>,
    pub index_name: Option<String>,
    pub model: Option<String>,
    pub model_version: Option<String>,
}

#[napi(object)]
#[derive(Default)]
pub struct RecallOptions {
    pub now_unix: Option<f64>,
    pub raw_query_context: Option<String>,
    pub include_cold: Option<bool>,
    pub include_instructions: Option<bool>,
}

/// Iterator over recall candidates.
#[napi]
pub struct RecallStream {
    candidates: std::vec::IntoIter<RecallCandidate>,
}

#[napi]
impl RecallStream {
    /// Returns the number of remaining candidates.
    #[napi]
    #[must_use]
    pub fn remaining(&self) -> u32 {
        self.candidates.len() as u32
    }

    /// Returns the next candidate, or null when exhausted.
    #[napi]
    #[allow(clippy::should_implement_trait)]
    pub fn next(&mut self) -> Option<RecallCandidate> {
        self.candidates.next()
    }
}

/// In-process Shibahama engine using the built-in HNSW vector index.
#[napi]
pub struct Shibahama {
    inner: Mutex<CoreShibahama<HnswVectorIndex>>,
}

#[napi]
impl Shibahama {
    /// Opens a Shibahama store.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened.
    #[napi(constructor)]
    pub fn new(path: String, dimensions: u32, capacity: Option<u32>) -> Result<Self> {
        let vector_index =
            HnswVectorIndex::with_capacity(dimensions as usize, capacity.unwrap_or(1024) as usize);
        let inner = CoreShibahama::open(path, vector_index).map_err(js_error)?;

        Ok(Self {
            inner: Mutex::new(inner),
        })
    }

    /// Returns true when the native engine lock is healthy.
    #[napi]
    #[must_use]
    pub fn is_open(&self) -> bool {
        self.inner.lock().is_ok()
    }

    /// Writes a memory, optionally indexing an embedding vector.
    ///
    /// # Errors
    ///
    /// Returns an error when input validation, persistence, or vector indexing fails.
    #[napi]
    pub fn write(&self, content: String, options: Option<WriteOptions>) -> Result<MemoryItem> {
        let options = options.unwrap_or_default();
        let source_kind = options.source_kind.as_deref().unwrap_or("user");
        let ingested_by = options.ingested_by.as_deref().unwrap_or("node");
        let kind = options.kind.as_deref().unwrap_or("fact");
        let index_name = options.index_name.as_deref().unwrap_or("default");
        let model = options.model.as_deref().unwrap_or("unknown");
        let model_version = options.model_version.as_deref().unwrap_or("unknown");
        let mut event = write_event(
            content,
            source_kind,
            options.source_ref.clone(),
            ingested_by,
            options.valid_from_unix,
            options.ingested_at_unix,
        )?;

        match parse_memory_kind(kind)? {
            MemoryKind::Fact => {}
            MemoryKind::Instruction => {
                event = event.as_instruction();
            }
        }

        let vector = options.vector.as_deref().map(vector_to_f32).transpose()?;
        let mut inner = self.inner.lock().map_err(lock_error)?;
        let item = if let Some(vector) = vector.as_deref() {
            inner.write_with_embedding(
                event,
                WriteEmbedding {
                    vector,
                    index_name,
                    model,
                    model_version,
                },
            )
        } else {
            inner.write(event)
        }
        .map_err(js_error)?;

        Ok(MemoryItem::from(item))
    }

    /// Recalls current fact memories for a query embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, or access recording fail.
    #[napi]
    pub fn recall(
        &self,
        query_vector: Vec<f64>,
        top_k: u32,
        options: Option<RecallOptions>,
    ) -> Result<Vec<RecallCandidate>> {
        let query_vector = vector_to_f32(&query_vector)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let request = recall_request(&query_vector, top_k, options.as_ref())?;
        let candidates = inner.recall(&request).map_err(js_error)?;

        Ok(candidates.into_iter().map(RecallCandidate::from).collect())
    }

    /// Streams current fact memories for a query embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, or access recording fail.
    #[napi]
    pub fn stream_recall(
        &self,
        query_vector: Vec<f64>,
        top_k: u32,
        options: Option<RecallOptions>,
    ) -> Result<RecallStream> {
        Ok(RecallStream {
            candidates: self.recall(query_vector, top_k, options)?.into_iter(),
        })
    }

    /// Replays recalled memories as they were believed at a historical instant.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search or storage reads fail.
    #[napi]
    pub fn timeline(
        &self,
        query_vector: Vec<f64>,
        top_k: u32,
        as_of_unix: f64,
        options: Option<RecallOptions>,
    ) -> Result<Vec<RecallCandidate>> {
        let query_vector = vector_to_f32(&query_vector)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let mut options = options.unwrap_or_default();
        options.now_unix = Some(as_of_unix);
        let request = recall_request(&query_vector, top_k, Some(&options))?;
        let candidates = inner.timeline(&request).map_err(js_error)?;

        Ok(candidates.into_iter().map(RecallCandidate::from).collect())
    }

    /// Streams historical recall results.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search or storage reads fail.
    #[napi]
    pub fn stream_timeline(
        &self,
        query_vector: Vec<f64>,
        top_k: u32,
        as_of_unix: f64,
        options: Option<RecallOptions>,
    ) -> Result<RecallStream> {
        Ok(RecallStream {
            candidates: self
                .timeline(query_vector, top_k, as_of_unix, options)?
                .into_iter(),
        })
    }

    /// Records a usage outcome for a memory.
    ///
    /// # Errors
    ///
    /// Returns an error when the memory id or outcome is invalid, or persistence fails.
    #[napi]
    pub fn reinforce(&self, memory_id: String, outcome: Option<String>) -> Result<bool> {
        let id = parse_memory_id(&memory_id)?;
        let outcome = parse_access_outcome(outcome.as_deref().unwrap_or("cited"))?;
        let inner = self.inner.lock().map_err(lock_error)?;

        inner.reinforce(id, outcome).map_err(js_error)
    }

    /// Explains why a memory currently has its state.
    ///
    /// # Errors
    ///
    /// Returns an error when the memory id is invalid or state cannot be read.
    #[napi]
    pub fn why(&self, memory_id: String, now_unix: Option<f64>) -> Result<Option<WhyTrace>> {
        let id = parse_memory_id(&memory_id)?;
        let now = time_from_optional_unix(now_unix)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let why = inner.why_at(id, now).map_err(js_error)?;

        Ok(why.map(WhyTrace::from))
    }

    /// Returns all current materialized memory rows.
    ///
    /// # Errors
    ///
    /// Returns an error when current item state cannot be read.
    #[napi]
    pub fn memory_items(&self) -> Result<Vec<MemoryItem>> {
        let inner = self.inner.lock().map_err(lock_error)?;
        let items = inner.memory_items().map_err(js_error)?;

        Ok(items.into_iter().map(MemoryItem::from).collect())
    }
}

impl From<CoreProvenance> for Provenance {
    fn from(value: CoreProvenance) -> Self {
        Self {
            source_kind: source_kind_str(value.source_kind).to_owned(),
            source_ref: value.source_ref,
            ingested_by: value.ingested_by,
        }
    }
}

impl From<CoreMemoryItem> for MemoryItem {
    fn from(value: CoreMemoryItem) -> Self {
        Self {
            id: value.id.to_string(),
            content: value.content,
            kind: memory_kind_str(value.kind).to_owned(),
            provenance: Provenance::from(value.provenance),
            tier: tier_str(value.tier).to_owned(),
            credence: credence_str(value.credence).to_owned(),
            significance: value.significance,
            credence_floor: tier_str(value.credence_floor).to_owned(),
            valid_from_unix: value.timestamps.valid_from.unix_timestamp() as f64,
            valid_to_unix: value
                .timestamps
                .valid_to
                .map(|timestamp| timestamp.unix_timestamp() as f64),
            ingested_at_unix: value.timestamps.ingested_at.unix_timestamp() as f64,
        }
    }
}

impl From<CoreRecallCandidate> for RecallCandidate {
    fn from(value: CoreRecallCandidate) -> Self {
        Self {
            id: value.id.to_string(),
            item: MemoryItem::from(value.item),
            kind: memory_kind_str(value.kind).to_owned(),
            provenance: Provenance::from(value.provenance),
            tier: tier_str(value.tier).to_owned(),
            currency: currency_str(value.currency).to_owned(),
            load_bearing_possibly_stale: value.load_bearing_possibly_stale,
            cold_tier_retrieval: value.cold_tier_retrieval,
            vector_distance: f64::from(value.vector_distance),
            similarity_score: value.similarity_score,
            significance_score: value.significance_score,
            recency_score: value.recency_score,
            graph_score: value.graph_score,
            source: candidate_source_str(value.source),
            rank_score: value.rank_score,
            read_safety_findings: value
                .read_safety_findings
                .into_iter()
                .map(|finding| format!("{finding:?}"))
                .collect(),
        }
    }
}

impl From<CoreSignificanceBreakdown> for SignificanceBreakdown {
    fn from(value: CoreSignificanceBreakdown) -> Self {
        Self {
            base_score: value.base_score,
            decay_multiplier: value.decay_multiplier,
            decayed_base: value.decayed_base,
            reinforcement: value.reinforcement,
            outcome_bonus: value.outcome_bonus,
            contradiction_penalty: value.contradiction_penalty,
            graph_centrality: value.graph_centrality,
            final_score: value.final_score,
        }
    }
}

impl From<CoreWhyTrace> for WhyTrace {
    fn from(value: CoreWhyTrace) -> Self {
        Self {
            item: MemoryItem::from(value.item),
            significance: SignificanceBreakdown::from(value.significance),
            provenance: Provenance::from(value.provenance),
            tier_current: tier_str(value.tier.current).to_owned(),
            tier_credence: credence_str(value.tier.credence).to_owned(),
            tier_credence_floor: tier_str(value.tier.credence_floor).to_owned(),
            currency_state: currency_str(value.currency.state).to_owned(),
            currency_as_of_unix: value.currency.as_of.unix_timestamp() as f64,
            valid_from_unix: value.currency.valid_from.unix_timestamp() as f64,
            valid_to_unix: value
                .currency
                .valid_to
                .map(|timestamp| timestamp.unix_timestamp() as f64),
            ingested_at_unix: value.currency.ingested_at.unix_timestamp() as f64,
            audit_trail: value
                .audit_trail
                .into_iter()
                .map(|entry| format!("{entry:?}"))
                .collect(),
        }
    }
}

/// Returns the Shibahama core crate version.
#[napi]
#[must_use]
pub fn version() -> String {
    shibahama_core::version().to_owned()
}

fn write_event(
    content: String,
    source_kind: &str,
    source_ref: Option<String>,
    ingested_by: &str,
    valid_from_unix: Option<f64>,
    ingested_at_unix: Option<f64>,
) -> Result<MemoryWriteEvent> {
    let valid_from = time_from_optional_unix(valid_from_unix)?;
    let ingested_at = time_from_optional_unix(ingested_at_unix)?;
    let provenance = CoreProvenance::new(parse_source_kind(source_kind)?, source_ref, ingested_by);

    Ok(MemoryWriteEvent::new(
        content,
        provenance,
        valid_from,
        ingested_at,
    ))
}

fn recall_request<'a>(
    query_vector: &'a [f32],
    top_k: u32,
    options: Option<&'a RecallOptions>,
) -> Result<RecallRequest<'a>> {
    let options = options.unwrap_or(&DEFAULT_RECALL_OPTIONS);
    let mut request = RecallRequest::new(
        query_vector,
        top_k as usize,
        time_from_optional_unix(options.now_unix)?,
    );

    if let Some(raw_query_context) = options.raw_query_context.as_deref() {
        request = request.with_raw_query_context(raw_query_context);
    }
    if options.include_cold.unwrap_or(false) {
        request = request.include_cold();
    }
    if options.include_instructions.unwrap_or(false) {
        request = request.include_instructions();
    }

    Ok(request)
}

static DEFAULT_RECALL_OPTIONS: RecallOptions = RecallOptions {
    now_unix: None,
    raw_query_context: None,
    include_cold: None,
    include_instructions: None,
};

fn time_from_optional_unix(value: Option<f64>) -> Result<OffsetDateTime> {
    match value {
        Some(value) => OffsetDateTime::from_unix_timestamp(number_to_unix_timestamp(value)?)
            .map_err(|error| Error::from_reason(format!("invalid Unix timestamp: {error}"))),
        None => Ok(OffsetDateTime::now_utc()),
    }
}

fn number_to_unix_timestamp(value: f64) -> Result<i64> {
    if !value.is_finite() || value.fract() != 0.0 {
        return Err(Error::from_reason(
            "Unix timestamp must be a finite integer number",
        ));
    }
    if value < i64::MIN as f64 || value > i64::MAX as f64 {
        return Err(Error::from_reason("Unix timestamp is outside i64 range"));
    }

    Ok(value as i64)
}

fn vector_to_f32(values: &[f64]) -> Result<Vec<f32>> {
    values
        .iter()
        .map(|value| {
            if value.is_finite() && *value >= f64::from(f32::MIN) && *value <= f64::from(f32::MAX) {
                Ok(*value as f32)
            } else {
                Err(Error::from_reason(
                    "embedding vectors must contain finite f32-range numbers",
                ))
            }
        })
        .collect()
}

fn parse_memory_id(value: &str) -> Result<MemoryId> {
    Uuid::parse_str(value)
        .map(MemoryId::from)
        .map_err(|error| Error::from_reason(format!("invalid memory id: {error}")))
}

fn parse_source_kind(value: &str) -> Result<SourceKind> {
    match value {
        "user" => Ok(SourceKind::User),
        "agent" => Ok(SourceKind::Agent),
        "file" => Ok(SourceKind::File),
        "web" => Ok(SourceKind::Web),
        "tool" => Ok(SourceKind::Tool),
        _ => Err(Error::from_reason(
            "sourceKind must be one of: user, agent, file, web, tool",
        )),
    }
}

fn parse_memory_kind(value: &str) -> Result<MemoryKind> {
    match value {
        "fact" => Ok(MemoryKind::Fact),
        "instruction" => Ok(MemoryKind::Instruction),
        _ => Err(Error::from_reason("kind must be one of: fact, instruction")),
    }
}

fn parse_access_outcome(value: &str) -> Result<AccessOutcome> {
    match value {
        "surfaced" => Ok(AccessOutcome::Surfaced),
        "led_somewhere" => Ok(AccessOutcome::LedSomewhere),
        "cited" => Ok(AccessOutcome::Cited),
        "ignored" => Ok(AccessOutcome::Ignored),
        "contradicted" => Ok(AccessOutcome::Contradicted),
        _ => Err(Error::from_reason(
            "outcome must be one of: surfaced, led_somewhere, cited, ignored, contradicted",
        )),
    }
}

fn source_kind_str(value: SourceKind) -> &'static str {
    match value {
        SourceKind::User => "user",
        SourceKind::Agent => "agent",
        SourceKind::File => "file",
        SourceKind::Web => "web",
        SourceKind::Tool => "tool",
    }
}

fn memory_kind_str(value: MemoryKind) -> &'static str {
    match value {
        MemoryKind::Fact => "fact",
        MemoryKind::Instruction => "instruction",
    }
}

fn tier_str(value: Tier) -> &'static str {
    match value {
        Tier::Cold => "cold",
        Tier::Warm => "warm",
        Tier::Hot => "hot",
    }
}

fn credence_str(value: CredenceTier) -> &'static str {
    match value {
        CredenceTier::Unverified => "unverified",
        CredenceTier::ModelInferred => "model_inferred",
        CredenceTier::VerifiedSource => "verified_source",
        CredenceTier::FirmAuthoritative => "firm_authoritative",
    }
}

fn currency_str(value: RecallCandidateCurrency) -> &'static str {
    match value {
        RecallCandidateCurrency::Current => "current",
        RecallCandidateCurrency::NotYetValid => "not_yet_valid",
        RecallCandidateCurrency::Invalidated => "invalidated",
    }
}

fn candidate_source_str(value: RecallCandidateSource) -> String {
    match value {
        RecallCandidateSource::Vector => "vector".to_owned(),
        RecallCandidateSource::GraphExpansion { anchor } => {
            format!("graph_expansion:{anchor}")
        }
    }
}

fn js_error(error: ShibahamaError) -> Error {
    Error::from_reason(error.to_string())
}

fn lock_error(error: std::sync::PoisonError<impl Sized>) -> Error {
    Error::from_reason(format!("Shibahama engine lock poisoned: {error}"))
}
