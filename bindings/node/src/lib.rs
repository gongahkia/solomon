// SPDX-License-Identifier: MIT

//! `napi-rs` module for the Shibahama Node.js package.

#![allow(missing_docs)]
#![allow(clippy::needless_pass_by_value)]

use napi::bindgen_prelude::*;
use napi_derive::napi;
use serde_json::{Value, json};
use shibahama_core::api::{
    ConsolidationPassReport, HumanCorrectionOutcome, HumanSignalOutcome, HumanSignalRequest,
    Shibahama as CoreShibahama, ShibahamaError, WhyTrace as CoreWhyTrace, WriteEmbedding,
};
use shibahama_core::extraction::ExtractionCandidate;
use shibahama_core::model::{
    AccessOutcome, ConsolidationAction, CredenceTier, HumanSignal, HumanSignalAction, MemoryId,
    MemoryItem as CoreMemoryItem, MemoryKind, MemoryScope as CoreMemoryScope,
    Provenance as CoreProvenance, ScopeId, ScopeVisibility, SourceKind, Tier,
};
use shibahama_core::policy::{CaptureIntent, CapturePolicyRequest, PolicyActorClass};
use shibahama_core::retrieval::{
    RecallCandidate as CoreRecallCandidate, RecallCandidateCurrency, RecallCandidateSource,
    RecallRankingConfig, RecallRequest, RecallUnavailableStage,
};
use shibahama_core::significance::SignificanceBreakdown as CoreSignificanceBreakdown;
use shibahama_core::storage::{EventRecord, MemoryEvent, MemoryWriteEvent};
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
pub struct MemoryScope {
    pub repository: String,
    pub team: Option<String>,
    pub visibility: String,
}

#[napi(object)]
#[derive(Clone)]
pub struct MemoryItem {
    pub id: String,
    pub content: String,
    pub kind: String,
    pub provenance: Provenance,
    pub scope: MemoryScope,
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
pub struct DegradedRecallResult {
    pub candidates: Vec<RecallCandidate>,
    pub unavailable_stages: Vec<String>,
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
    pub scope: Option<MemoryScope>,
}

#[napi(object)]
#[derive(Default)]
pub struct RecallOptions {
    pub now_unix: Option<f64>,
    pub raw_query_context: Option<String>,
    pub include_cold: Option<bool>,
    pub include_instructions: Option<bool>,
    pub max_context_tokens: Option<u32>,
    pub similarity_weight: Option<f64>,
    pub significance_weight: Option<f64>,
    pub recency_weight: Option<f64>,
    pub graph_weight: Option<f64>,
}

#[napi(object)]
#[derive(Default)]
pub struct CapturePolicySimulationOptions {
    pub actor: Option<String>,
    pub intent: Option<String>,
    pub confidence_percent: Option<u32>,
    pub scope: Option<MemoryScope>,
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

    /// Simulates capture policy without writing memory or audit events.
    #[napi]
    pub fn simulate_capture_policy(
        &self,
        source_kind: String,
        options: Option<CapturePolicySimulationOptions>,
    ) -> Result<String> {
        let options = options.unwrap_or_default();
        let source_kind = parse_source_kind(&source_kind)?;
        let scope = options
            .scope
            .map(parse_memory_scope)
            .transpose()?
            .unwrap_or_default();
        let request = CapturePolicyRequest {
            actor: parse_policy_actor(options.actor.as_deref().unwrap_or("human"))?,
            intent: parse_capture_intent(options.intent.as_deref().unwrap_or("manual"))?,
            confidence_percent: options
                .confidence_percent
                .unwrap_or(100)
                .try_into()
                .map_err(|_| Error::from_reason("confidence_percent must be between 0 and 255"))?,
        };
        let inner = self.inner.lock().map_err(lock_error)?;

        serde_json::to_string(&inner.simulate_capture_policy(source_kind, &scope, request))
            .map_err(json_error)
    }

    /// Simulates recall policy without reading memory or writing access events.
    #[napi]
    pub fn simulate_recall_policy(
        &self,
        top_k: u32,
        options: Option<RecallOptions>,
        scope: Option<MemoryScope>,
    ) -> Result<String> {
        let options = options.unwrap_or_default();
        let scope = scope.map(parse_memory_scope).transpose()?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let simulation = inner.simulate_recall_policy(
            top_k as usize,
            options.max_context_tokens.map(|value| value as usize),
            options.include_cold.unwrap_or(false),
            options.include_instructions.unwrap_or(false),
            scope.as_ref(),
        );

        serde_json::to_string(&simulation).map_err(json_error)
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
        if let Some(scope) = options.scope {
            event = event.with_scope(parse_memory_scope(scope)?);
        }

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

    /// Soft-invalidates a memory at a valid-time end.
    ///
    /// # Errors
    ///
    /// Returns an error when the memory id is invalid or persistence fails.
    #[napi]
    pub fn invalidate(&self, memory_id: String, valid_to_unix: f64) -> Result<bool> {
        let id = parse_memory_id(&memory_id)?;
        let valid_to = time_from_optional_unix(Some(valid_to_unix))?;
        let mut inner = self.inner.lock().map_err(lock_error)?;

        inner.invalidate(id, valid_to).map_err(js_error)
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

    /// Recalls usable candidates and reports unavailable optional stages.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search or initial candidate materialization cannot complete.
    #[napi]
    pub fn recall_with_degradation(
        &self,
        query_vector: Vec<f64>,
        top_k: u32,
        options: Option<RecallOptions>,
    ) -> Result<DegradedRecallResult> {
        let query_vector = vector_to_f32(&query_vector)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let request = recall_request(&query_vector, top_k, options.as_ref())?;
        let result = inner.recall_with_degradation(&request).map_err(js_error)?;

        Ok(DegradedRecallResult {
            candidates: result
                .candidates
                .into_iter()
                .map(RecallCandidate::from)
                .collect(),
            unavailable_stages: result
                .unavailable_stages
                .into_iter()
                .map(recall_unavailable_stage_str)
                .map(str::to_owned)
                .collect(),
        })
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

    /// Returns durable event-log records as JSON.
    ///
    /// # Errors
    ///
    /// Returns an error when event records cannot be read or serialized.
    #[napi]
    pub fn event_records_json(&self) -> Result<String> {
        let inner = self.inner.lock().map_err(lock_error)?;
        let events = inner
            .event_records()
            .map_err(js_error)?
            .iter()
            .map(event_record_json)
            .collect::<Vec<_>>();

        serde_json::to_string(&json!({
            "eventCount": events.len(),
            "events": events,
        }))
        .map_err(json_error)
    }

    /// Returns one memory's why trace and related events as JSON.
    ///
    /// # Errors
    ///
    /// Returns an error when the memory id is invalid or storage cannot be read.
    #[napi]
    pub fn audit_json(&self, memory_id: String, now_unix: Option<f64>) -> Result<String> {
        let id = parse_memory_id(&memory_id)?;
        let now = time_from_optional_unix(now_unix)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let why = inner.why_at(id, now).map_err(js_error)?;
        let events = inner
            .event_records()
            .map_err(js_error)?
            .iter()
            .filter(|record| event_touches_memory(record, id))
            .map(event_record_json)
            .collect::<Vec<_>>();

        serde_json::to_string(&json!({
            "memoryId": id.to_string(),
            "why": why.as_ref().map(why_trace_json),
            "events": events,
        }))
        .map_err(json_error)
    }

    /// Runs the offline consolidation pass and returns its report as JSON.
    ///
    /// # Errors
    ///
    /// Returns an error when consolidation cannot be planned or applied.
    #[napi]
    pub fn consolidate_json(&self, now_unix: Option<f64>) -> Result<String> {
        let now = time_from_optional_unix(now_unix)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let report = inner.consolidate(now).map_err(js_error)?;

        serde_json::to_string(&consolidation_report_json(report)).map_err(json_error)
    }

    /// Challenges a memory and returns the mutation report as JSON.
    ///
    /// # Errors
    ///
    /// Returns an error when the memory id is invalid or persistence fails.
    #[napi]
    pub fn challenge_json(
        &self,
        memory_id: String,
        reason: String,
        actor: Option<String>,
        timestamp_unix: Option<f64>,
    ) -> Result<String> {
        self.human_signal_json(
            &memory_id,
            &reason,
            actor.as_deref().unwrap_or("node"),
            timestamp_unix,
            HumanSignalAction::Challenge,
        )
    }

    /// Affirms a memory and returns the mutation report as JSON.
    ///
    /// # Errors
    ///
    /// Returns an error when the memory id is invalid or persistence fails.
    #[napi]
    pub fn affirm_json(
        &self,
        memory_id: String,
        reason: Option<String>,
        actor: Option<String>,
        timestamp_unix: Option<f64>,
    ) -> Result<String> {
        self.human_signal_json(
            &memory_id,
            reason.as_deref().unwrap_or("affirmed"),
            actor.as_deref().unwrap_or("node"),
            timestamp_unix,
            HumanSignalAction::Affirm,
        )
    }

    /// Pins a memory and returns the mutation report as JSON.
    ///
    /// # Errors
    ///
    /// Returns an error when the memory id is invalid or persistence fails.
    #[napi]
    pub fn pin_json(
        &self,
        memory_id: String,
        reason: Option<String>,
        actor: Option<String>,
        timestamp_unix: Option<f64>,
    ) -> Result<String> {
        self.human_signal_json(
            &memory_id,
            reason.as_deref().unwrap_or("pinned"),
            actor.as_deref().unwrap_or("node"),
            timestamp_unix,
            HumanSignalAction::Pin,
        )
    }

    /// Unpins a memory and returns the mutation report as JSON.
    ///
    /// # Errors
    ///
    /// Returns an error when the memory id is invalid or persistence fails.
    #[napi]
    pub fn unpin_json(
        &self,
        memory_id: String,
        reason: Option<String>,
        actor: Option<String>,
        timestamp_unix: Option<f64>,
    ) -> Result<String> {
        self.human_signal_json(
            &memory_id,
            reason.as_deref().unwrap_or("unpinned"),
            actor.as_deref().unwrap_or("node"),
            timestamp_unix,
            HumanSignalAction::Unpin,
        )
    }

    /// Corrects a memory and returns the mutation report as JSON.
    ///
    /// # Errors
    ///
    /// Returns an error when the memory id is invalid or persistence fails.
    #[napi]
    pub fn correct_json(
        &self,
        memory_id: String,
        proposed_content: String,
        reason: Option<String>,
        actor: Option<String>,
        timestamp_unix: Option<f64>,
    ) -> Result<String> {
        let id = parse_memory_id(&memory_id)?;
        let request = human_signal_request(
            actor.as_deref().unwrap_or("node"),
            reason.as_deref().unwrap_or("corrected"),
            timestamp_unix,
        )?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let outcome = inner
            .correct_with_request(id, proposed_content, request)
            .map_err(js_error)?;

        serde_json::to_string(&outcome.map_or_else(
            || json!({ "applied": false }),
            human_correction_outcome_json,
        ))
        .map_err(json_error)
    }
}

impl Shibahama {
    fn human_signal_json(
        &self,
        memory_id: &str,
        reason: &str,
        actor: &str,
        timestamp_unix: Option<f64>,
        action: HumanSignalAction,
    ) -> Result<String> {
        let id = parse_memory_id(memory_id)?;
        let request = human_signal_request(actor, reason, timestamp_unix)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let outcome = match action {
            HumanSignalAction::Challenge => inner.challenge_with_request(id, request),
            HumanSignalAction::Affirm => inner.affirm_with_request(id, request),
            HumanSignalAction::Pin => inner.pin_with_request(id, request),
            HumanSignalAction::Unpin => inner.unpin_with_request(id, request),
            HumanSignalAction::Correct => return Err(Error::from_reason("use correctJson")),
        }
        .map_err(js_error)?;

        serde_json::to_string(
            &outcome.map_or_else(|| json!({ "applied": false }), human_signal_outcome_json),
        )
        .map_err(json_error)
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

impl From<CoreMemoryScope> for MemoryScope {
    fn from(value: CoreMemoryScope) -> Self {
        Self {
            repository: value.repository.to_string(),
            team: value.team.map(|team| team.to_string()),
            visibility: scope_visibility_str(value.visibility).to_owned(),
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
            scope: MemoryScope::from(value.scope),
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

fn event_record_json(record: &EventRecord) -> Value {
    json!({
        "sequence": record.sequence,
        "recordedAtUnix": record.recorded_at.unix_timestamp() as f64,
        "kind": event_kind(&record.event),
        "memoryIds": event_memory_ids(&record.event),
        "event": serde_json::to_value(&record.event).unwrap_or_else(|error| {
            json!({ "serializationError": error.to_string() })
        }),
    })
}

fn memory_item_json(item: &CoreMemoryItem) -> Value {
    json!({
        "id": item.id.to_string(),
        "content": item.content,
        "kind": memory_kind_str(item.kind),
        "provenance": {
            "sourceKind": source_kind_str(item.provenance.source_kind),
            "sourceRef": item.provenance.source_ref,
            "ingestedBy": item.provenance.ingested_by,
        },
        "tier": tier_str(item.tier),
        "credence": credence_str(item.credence),
        "significance": item.significance,
        "credenceFloor": tier_str(item.credence_floor),
        "validFromUnix": item.timestamps.valid_from.unix_timestamp() as f64,
        "validToUnix": item.timestamps.valid_to.map(|timestamp| timestamp.unix_timestamp() as f64),
        "ingestedAtUnix": item.timestamps.ingested_at.unix_timestamp() as f64,
    })
}

fn why_trace_json(trace: &CoreWhyTrace) -> Value {
    json!({
        "item": memory_item_json(&trace.item),
        "significance": trace.significance,
        "provenance": {
            "sourceKind": source_kind_str(trace.provenance.source_kind),
            "sourceRef": trace.provenance.source_ref,
            "ingestedBy": trace.provenance.ingested_by,
        },
        "tierCurrent": tier_str(trace.tier.current),
        "tierCredence": credence_str(trace.tier.credence),
        "tierCredenceFloor": tier_str(trace.tier.credence_floor),
        "currencyState": currency_str(trace.currency.state),
        "currencyAsOfUnix": trace.currency.as_of.unix_timestamp() as f64,
        "validFromUnix": trace.currency.valid_from.unix_timestamp() as f64,
        "validToUnix": trace.currency.valid_to.map(|timestamp| timestamp.unix_timestamp() as f64),
        "ingestedAtUnix": trace.currency.ingested_at.unix_timestamp() as f64,
        "auditTrail": trace.audit_trail.iter().map(|entry| format!("{entry:?}")).collect::<Vec<_>>(),
    })
}

fn human_signal_json(signal: &HumanSignal) -> Value {
    json!({
        "action": human_signal_action_str(signal.action),
        "memoryId": signal.memory_id.to_string(),
        "actor": signal.actor,
        "timestampUnix": signal.timestamp.unix_timestamp() as f64,
        "reason": signal.reason,
        "proposedContent": signal.proposed_content,
        "proposalId": signal.proposal_id.map(|id| id.to_string()),
        "previousCredence": signal.previous_credence.map(credence_str),
        "newCredence": signal.new_credence.map(credence_str),
        "previousCredenceFloor": signal.previous_credence_floor.map(tier_str),
        "newCredenceFloor": signal.new_credence_floor.map(tier_str),
    })
}

fn human_signal_outcome_json(outcome: HumanSignalOutcome) -> Value {
    let events = [
        outcome.records.access,
        outcome.records.revalidation_flag,
        Some(outcome.records.signal),
    ]
    .into_iter()
    .flatten()
    .map(|record| event_record_json(&record))
    .collect::<Vec<_>>();

    json!({
        "applied": true,
        "signal": human_signal_json(&outcome.signal),
        "events": events,
    })
}

fn human_correction_outcome_json(outcome: HumanCorrectionOutcome) -> Value {
    let events = vec![
        outcome.records.invalidation,
        outcome.records.replacement_write,
        outcome.records.reconstruction,
        outcome.signal_record,
    ]
    .into_iter()
    .map(|record| event_record_json(&record))
    .collect::<Vec<_>>();

    json!({
        "applied": true,
        "signal": human_signal_json(&outcome.signal),
        "proposal": memory_item_json(&outcome.proposal.item),
        "replacement": memory_item_json(&outcome.replacement),
        "events": events,
    })
}

fn consolidation_report_json(report: ConsolidationPassReport) -> Value {
    let applied_count = report.applied.len();
    let outcomes = report
        .applied
        .into_iter()
        .map(|outcome| {
            let events = [
                outcome.records.memory_write,
                outcome.records.tier_change,
                outcome.records.revalidation_flag,
                Some(outcome.records.decision),
            ]
            .into_iter()
            .flatten()
            .map(|record| event_record_json(&record))
            .collect::<Vec<_>>();

            json!({
                "action": consolidation_action_str(outcome.decision.action),
                "inputIds": outcome.decision.input_ids.into_iter().map(|id| id.to_string()).collect::<Vec<_>>(),
                "outputId": outcome.decision.output.map(|item| item.id.to_string()),
                "tierFrom": outcome.decision.tier_from.map(tier_str),
                "tierTo": outcome.decision.tier_to.map(tier_str),
                "why": outcome.decision.why.summary,
                "events": events,
            })
        })
        .collect::<Vec<_>>();

    json!({
        "passId": report.pass_id,
        "appliedCount": applied_count,
        "outcomes": outcomes,
    })
}

/// Returns the Shibahama core crate version.
#[napi]
#[must_use]
pub fn version() -> String {
    shibahama_core::version().to_owned()
}

/// Returns the versioned capability document as JSON.
#[napi]
pub fn capabilities_json() -> Result<String> {
    serde_json::to_string(&shibahama_core::capabilities()).map_err(json_error)
}

/// Parses and canonicalizes one typed extraction candidate without persisting it.
#[napi]
pub fn canonicalize_extraction_candidate_json(value: String) -> Result<String> {
    let candidate: ExtractionCandidate = serde_json::from_str(&value).map_err(json_error)?;

    serde_json::to_string(&candidate).map_err(json_error)
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

fn parse_memory_scope(value: MemoryScope) -> Result<CoreMemoryScope> {
    let repository =
        ScopeId::new(value.repository).map_err(|error| Error::from_reason(error.to_string()))?;
    match value.visibility.as_str() {
        "repository" => {
            if value.team.is_some() {
                return Err(Error::from_reason(
                    "repository scope must not specify a team",
                ));
            }
            Ok(CoreMemoryScope::repository(repository))
        }
        "team" => Ok(CoreMemoryScope::team(
            repository,
            ScopeId::new(
                value
                    .team
                    .ok_or_else(|| Error::from_reason("team scope requires a team"))?,
            )
            .map_err(|error| Error::from_reason(error.to_string()))?,
        )),
        _ => Err(Error::from_reason(
            "scope.visibility must be `repository` or `team`",
        )),
    }
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
    if let Some(max_context_tokens) = options.max_context_tokens {
        request = request.with_max_context_tokens(max_context_tokens as usize);
    }
    request = request.with_ranking(recall_ranking(options)?);

    Ok(request)
}

static DEFAULT_RECALL_OPTIONS: RecallOptions = RecallOptions {
    now_unix: None,
    raw_query_context: None,
    include_cold: None,
    include_instructions: None,
    max_context_tokens: None,
    similarity_weight: None,
    significance_weight: None,
    recency_weight: None,
    graph_weight: None,
};

fn recall_ranking(options: &RecallOptions) -> Result<RecallRankingConfig> {
    let default = RecallRankingConfig::default();

    Ok(RecallRankingConfig {
        similarity_weight: finite_weight(
            options.similarity_weight,
            "similarityWeight",
            default.similarity_weight,
        )?,
        significance_weight: finite_weight(
            options.significance_weight,
            "significanceWeight",
            default.significance_weight,
        )?,
        recency_weight: finite_weight(
            options.recency_weight,
            "recencyWeight",
            default.recency_weight,
        )?,
        graph_weight: finite_weight(options.graph_weight, "graphWeight", default.graph_weight)?,
    })
}

fn finite_weight(value: Option<f64>, name: &str, default: f64) -> Result<f64> {
    match value {
        Some(value) if value.is_finite() => Ok(value),
        Some(_) => Err(Error::from_reason(format!("{name} must be finite"))),
        None => Ok(default),
    }
}

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

fn human_signal_request(
    actor: &str,
    reason: &str,
    timestamp_unix: Option<f64>,
) -> Result<HumanSignalRequest> {
    Ok(HumanSignalRequest::new(
        actor,
        reason,
        time_from_optional_unix(timestamp_unix)?,
    ))
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

fn parse_policy_actor(value: &str) -> Result<PolicyActorClass> {
    match value {
        "human" => Ok(PolicyActorClass::Human),
        "agent" => Ok(PolicyActorClass::Agent),
        "automation" => Ok(PolicyActorClass::Automation),
        "service" => Ok(PolicyActorClass::Service),
        _ => Err(Error::from_reason(
            "actor must be `human`, `agent`, `automation`, or `service`",
        )),
    }
}

fn parse_capture_intent(value: &str) -> Result<CaptureIntent> {
    match value {
        "manual" => Ok(CaptureIntent::Manual),
        "suggested" => Ok(CaptureIntent::Suggested),
        "automatic" => Ok(CaptureIntent::Automatic),
        _ => Err(Error::from_reason(
            "intent must be `manual`, `suggested`, or `automatic`",
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
        "led_somewhere" | "led-somewhere" => Ok(AccessOutcome::LedSomewhere),
        "cited" => Ok(AccessOutcome::Cited),
        "ignored" => Ok(AccessOutcome::Ignored),
        "contradicted" => Ok(AccessOutcome::Contradicted),
        _ => Err(Error::from_reason(
            "outcome must be one of: surfaced, led_somewhere, cited, ignored, contradicted",
        )),
    }
}

fn consolidation_action_str(value: ConsolidationAction) -> &'static str {
    match value {
        ConsolidationAction::Merge => "merge",
        ConsolidationAction::Promote => "promote",
        ConsolidationAction::Demote => "demote",
        ConsolidationAction::FlagStale => "flag_stale",
    }
}

fn human_signal_action_str(value: HumanSignalAction) -> &'static str {
    match value {
        HumanSignalAction::Challenge => "challenge",
        HumanSignalAction::Affirm => "affirm",
        HumanSignalAction::Correct => "correct",
        HumanSignalAction::Pin => "pin",
        HumanSignalAction::Unpin => "unpin",
    }
}

fn event_kind(event: &MemoryEvent) -> &'static str {
    match event {
        MemoryEvent::MemoryWritten { .. } => "memory_written",
        MemoryEvent::MemoryScopePromoted { .. } => "memory_scope_promoted",
        MemoryEvent::ScopeAuthorizationDenied { .. } => "scope_authorization_denied",
        MemoryEvent::PolicyDecisionRecorded { .. } => "policy_decision",
        MemoryEvent::MemoryInvalidated { .. } => "memory_invalidated",
        MemoryEvent::ReverificationFlagged { .. } => "reverification_flagged",
        MemoryEvent::AccessRecorded { .. } => "access_recorded",
        MemoryEvent::TierChanged { .. } => "tier_changed",
        MemoryEvent::ContentCompacted { .. } => "content_compacted",
        MemoryEvent::ReconstructionApplied { .. } => "reconstruction_applied",
        MemoryEvent::ConsolidationDecision { .. } => "consolidation_decision",
        MemoryEvent::HumanSignalRecorded { .. } => "human_signal",
    }
}

fn event_memory_ids(event: &MemoryEvent) -> Vec<String> {
    match event {
        MemoryEvent::MemoryWritten { item } => vec![item.id.to_string()],
        MemoryEvent::MemoryScopePromoted {
            source_id,
            promoted_id,
            ..
        } => vec![source_id.to_string(), promoted_id.to_string()],
        MemoryEvent::ScopeAuthorizationDenied { .. }
        | MemoryEvent::PolicyDecisionRecorded { .. } => Vec::new(),
        MemoryEvent::MemoryInvalidated { id, .. }
        | MemoryEvent::ReverificationFlagged { id, .. }
        | MemoryEvent::AccessRecorded { id, .. }
        | MemoryEvent::TierChanged { id, .. }
        | MemoryEvent::ContentCompacted { id, .. } => vec![id.to_string()],
        MemoryEvent::ReconstructionApplied {
            superseded_id,
            replacement_id,
            ..
        } => vec![superseded_id.to_string(), replacement_id.to_string()],
        MemoryEvent::ConsolidationDecision {
            input_ids,
            output_id,
            ..
        } => input_ids
            .iter()
            .chain(output_id.iter())
            .map(ToString::to_string)
            .collect(),
        MemoryEvent::HumanSignalRecorded { signal } => [Some(signal.memory_id), signal.proposal_id]
            .into_iter()
            .flatten()
            .map(|id| id.to_string())
            .collect(),
    }
}

fn event_touches_memory(record: &EventRecord, id: MemoryId) -> bool {
    match &record.event {
        MemoryEvent::MemoryWritten { item } => item.id == id,
        MemoryEvent::MemoryScopePromoted {
            source_id,
            promoted_id,
            ..
        } => *source_id == id || *promoted_id == id,
        MemoryEvent::ScopeAuthorizationDenied { .. }
        | MemoryEvent::PolicyDecisionRecorded { .. } => false,
        MemoryEvent::MemoryInvalidated { id: event_id, .. }
        | MemoryEvent::ReverificationFlagged { id: event_id, .. }
        | MemoryEvent::AccessRecorded { id: event_id, .. }
        | MemoryEvent::TierChanged { id: event_id, .. }
        | MemoryEvent::ContentCompacted { id: event_id, .. } => *event_id == id,
        MemoryEvent::ReconstructionApplied {
            superseded_id,
            replacement_id,
            ..
        } => *superseded_id == id || *replacement_id == id,
        MemoryEvent::ConsolidationDecision {
            input_ids,
            output_id,
            ..
        } => input_ids.contains(&id) || output_id.is_some_and(|output_id| output_id == id),
        MemoryEvent::HumanSignalRecorded { signal } => {
            signal.memory_id == id
                || signal
                    .proposal_id
                    .is_some_and(|proposal_id| proposal_id == id)
        }
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

fn scope_visibility_str(value: ScopeVisibility) -> &'static str {
    match value {
        ScopeVisibility::Repository => "repository",
        ScopeVisibility::Team => "team",
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

fn recall_unavailable_stage_str(value: RecallUnavailableStage) -> &'static str {
    match value {
        RecallUnavailableStage::VectorSearch => "vector_search",
        RecallUnavailableStage::StorageHydration => "storage_hydration",
        RecallUnavailableStage::GraphExpansion => "graph_expansion",
        RecallUnavailableStage::Sanitization => "sanitization",
        RecallUnavailableStage::AccessRecording => "access_recording",
    }
}

fn js_error(error: ShibahamaError) -> Error {
    Error::from_reason(structured_error_reason(error))
}

fn structured_error_reason(error: ShibahamaError) -> String {
    serde_json::to_string(&error.metadata()).unwrap_or_else(|_| {
        "{\"code\":\"SHIBA_INTERNAL\",\"severity\":\"fatal\",\"retryable\":false,\"detail\":\"internal error\"}".to_owned()
    })
}

fn json_error(error: serde_json::Error) -> Error {
    Error::from_reason(error.to_string())
}

fn lock_error(error: std::sync::PoisonError<impl Sized>) -> Error {
    Error::from_reason(format!("Shibahama engine lock poisoned: {error}"))
}
