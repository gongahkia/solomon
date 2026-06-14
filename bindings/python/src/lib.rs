// SPDX-License-Identifier: MIT

//! `PyO3` module for the Shibahama Python package.

#![allow(clippy::needless_pass_by_value, clippy::too_many_arguments)]

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use serde_json::{Value, json};
use shibahama_core::api::{
    ConsolidationPassReport, HumanCorrectionOutcome, HumanSignalOutcome, HumanSignalRequest,
    Shibahama, ShibahamaError, WhyTrace, WriteEmbedding,
};
use shibahama_core::model::{
    AccessOutcome, ConsolidationAction, CredenceTier, HumanSignal, HumanSignalAction, MemoryId,
    MemoryItem, MemoryKind, Provenance, SourceKind, Tier,
};
use shibahama_core::retrieval::{
    RecallCandidate, RecallCandidateCurrency, RecallCandidateSource, RecallRankingConfig,
    RecallRequest, RelatedMemoryProvider,
};
use shibahama_core::significance::SignificanceBreakdown;
use shibahama_core::storage::{EventRecord, MemoryEvent, MemoryWriteEvent, StorageError};
use shibahama_core::vector::HnswVectorIndex;
use std::collections::BTreeMap;
use std::sync::Mutex;
use time::OffsetDateTime;
use uuid::Uuid;

/// Python provenance value.
#[pyclass(frozen, name = "Provenance", skip_from_py_object)]
#[derive(Clone)]
pub struct PyProvenance {
    /// Source class.
    #[pyo3(get)]
    pub source_kind: String,
    /// Stable source reference.
    #[pyo3(get)]
    pub source_ref: Option<String>,
    /// Ingesting actor or integration.
    #[pyo3(get)]
    pub ingested_by: String,
}

/// Python memory item value.
#[pyclass(frozen, name = "MemoryItem", skip_from_py_object)]
#[derive(Clone)]
pub struct PyMemoryItem {
    /// Memory id as a UUID string.
    #[pyo3(get)]
    pub id: String,
    /// Stored memory content.
    #[pyo3(get)]
    pub content: String,
    /// Semantic memory kind.
    #[pyo3(get)]
    pub kind: String,
    /// Provenance metadata.
    #[pyo3(get)]
    pub provenance: PyProvenance,
    /// Accessibility tier.
    #[pyo3(get)]
    pub tier: String,
    /// Trust tier.
    #[pyo3(get)]
    pub credence: String,
    /// Current materialized significance score.
    #[pyo3(get)]
    pub significance: f64,
    /// Coldest tier allowed by credence.
    #[pyo3(get)]
    pub credence_floor: String,
    /// Valid-time start as Unix seconds.
    #[pyo3(get)]
    pub valid_from_unix: i64,
    /// Valid-time end as Unix seconds, when invalidated.
    #[pyo3(get)]
    pub valid_to_unix: Option<i64>,
    /// Ingestion time as Unix seconds.
    #[pyo3(get)]
    pub ingested_at_unix: i64,
}

/// Python recall candidate value.
#[pyclass(frozen, name = "RecallCandidate", skip_from_py_object)]
#[derive(Clone)]
pub struct PyRecallCandidate {
    /// Memory id as a UUID string.
    #[pyo3(get)]
    pub id: String,
    /// Full memory item.
    #[pyo3(get)]
    pub item: PyMemoryItem,
    /// Semantic memory kind.
    #[pyo3(get)]
    pub kind: String,
    /// Provenance metadata.
    #[pyo3(get)]
    pub provenance: PyProvenance,
    /// Accessibility tier.
    #[pyo3(get)]
    pub tier: String,
    /// Validity state at the recall instant.
    #[pyo3(get)]
    pub currency: String,
    /// True when significant and possibly stale.
    #[pyo3(get)]
    pub load_bearing_possibly_stale: bool,
    /// True when explicitly retrieved from cold storage.
    #[pyo3(get)]
    pub cold_tier_retrieval: bool,
    /// Vector distance where lower is closer.
    #[pyo3(get)]
    pub vector_distance: f32,
    /// Normalized vector similarity score.
    #[pyo3(get)]
    pub similarity_score: f64,
    /// Significance contribution.
    #[pyo3(get)]
    pub significance_score: f64,
    /// Recency contribution.
    #[pyo3(get)]
    pub recency_score: f64,
    /// Graph contribution.
    #[pyo3(get)]
    pub graph_score: f64,
    /// Candidate source stage.
    #[pyo3(get)]
    pub source: String,
    /// Final rank score.
    #[pyo3(get)]
    pub rank_score: f64,
    /// Read-safety findings.
    #[pyo3(get)]
    pub read_safety_findings: Vec<String>,
}

/// Python significance breakdown value.
#[pyclass(frozen, name = "SignificanceBreakdown", skip_from_py_object)]
#[derive(Clone)]
pub struct PySignificanceBreakdown {
    /// Base score before adjustments.
    #[pyo3(get)]
    pub base_score: f64,
    /// Time-decay multiplier.
    #[pyo3(get)]
    pub decay_multiplier: f64,
    /// Base score after decay.
    #[pyo3(get)]
    pub decayed_base: f64,
    /// Reinforcement contribution.
    #[pyo3(get)]
    pub reinforcement: f64,
    /// Outcome contribution.
    #[pyo3(get)]
    pub outcome_bonus: f64,
    /// Contradiction penalty.
    #[pyo3(get)]
    pub contradiction_penalty: f64,
    /// Graph-centrality contribution.
    #[pyo3(get)]
    pub graph_centrality: f64,
    /// Final score.
    #[pyo3(get)]
    pub final_score: f64,
}

/// Python why trace value.
#[pyclass(frozen, name = "WhyTrace", skip_from_py_object)]
#[derive(Clone)]
pub struct PyWhyTrace {
    /// Current memory item.
    #[pyo3(get)]
    pub item: PyMemoryItem,
    /// Significance breakdown.
    #[pyo3(get)]
    pub significance: PySignificanceBreakdown,
    /// Provenance metadata.
    #[pyo3(get)]
    pub provenance: PyProvenance,
    /// Current accessibility tier.
    #[pyo3(get)]
    pub tier_current: String,
    /// Current trust tier.
    #[pyo3(get)]
    pub tier_credence: String,
    /// Coldest tier allowed by credence.
    #[pyo3(get)]
    pub tier_credence_floor: String,
    /// Validity state at the explanation instant.
    #[pyo3(get)]
    pub currency_state: String,
    /// Explanation instant as Unix seconds.
    #[pyo3(get)]
    pub currency_as_of_unix: i64,
    /// Valid-time start as Unix seconds.
    #[pyo3(get)]
    pub valid_from_unix: i64,
    /// Valid-time end as Unix seconds, when invalidated.
    #[pyo3(get)]
    pub valid_to_unix: Option<i64>,
    /// Ingestion time as Unix seconds.
    #[pyo3(get)]
    pub ingested_at_unix: i64,
    /// Credence/tier audit entries.
    #[pyo3(get)]
    pub audit_trail: Vec<String>,
}

/// Python iterator over recall candidates.
#[pyclass(name = "RecallStream")]
pub struct PyRecallStream {
    candidates: std::vec::IntoIter<PyRecallCandidate>,
}

struct PyRelatedMemoryProvider {
    related: BTreeMap<MemoryId, Vec<MemoryId>>,
}

impl RelatedMemoryProvider for PyRelatedMemoryProvider {
    fn related_memory_ids(&self, id: MemoryId) -> Result<Vec<MemoryId>, StorageError> {
        Ok(self.related.get(&id).cloned().unwrap_or_default())
    }
}

#[pymethods]
impl PyRecallStream {
    /// Returns the number of remaining candidates.
    #[must_use]
    pub fn remaining(&self) -> usize {
        self.candidates.len()
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(mut slf: PyRefMut<'_, Self>) -> Option<PyRecallCandidate> {
        slf.candidates.next()
    }
}

/// In-process Shibahama engine using the built-in HNSW vector index.
#[pyclass(name = "Shibahama")]
pub struct PyShibahama {
    inner: Mutex<Shibahama<HnswVectorIndex>>,
}

#[pymethods]
impl PyShibahama {
    /// Opens a Shibahama store.
    #[new]
    #[pyo3(signature = (path, dimensions, capacity = 1024))]
    fn new(path: &str, dimensions: usize, capacity: usize) -> PyResult<Self> {
        let vector_index = HnswVectorIndex::with_capacity(dimensions, capacity);
        let inner = Shibahama::open(path, vector_index).map_err(py_error)?;

        Ok(Self {
            inner: Mutex::new(inner),
        })
    }

    /// Writes a memory, optionally indexing an embedding vector.
    #[pyo3(signature = (
        content,
        vector = None,
        source_kind = "user",
        source_ref = None,
        ingested_by = "python",
        valid_from_unix = None,
        ingested_at_unix = None,
        kind = "fact",
        index_name = "default",
        model = "unknown",
        model_version = "unknown"
    ))]
    fn write(
        &self,
        content: String,
        vector: Option<Vec<f32>>,
        source_kind: &str,
        source_ref: Option<String>,
        ingested_by: &str,
        valid_from_unix: Option<i64>,
        ingested_at_unix: Option<i64>,
        kind: &str,
        index_name: &str,
        model: &str,
        model_version: &str,
    ) -> PyResult<PyMemoryItem> {
        let mut event = write_event(
            content,
            source_kind,
            source_ref,
            ingested_by,
            valid_from_unix,
            ingested_at_unix,
        )?;

        match parse_memory_kind(kind)? {
            MemoryKind::Fact => {}
            MemoryKind::Instruction => {
                event = event.as_instruction();
            }
        }

        let mut inner = self.inner.lock().map_err(lock_error)?;
        let item = if let Some(vector) = vector {
            inner.write_with_embedding(
                event,
                WriteEmbedding {
                    vector: &vector,
                    index_name,
                    model,
                    model_version,
                },
            )
        } else {
            inner.write(event)
        }
        .map_err(py_error)?;

        Ok(PyMemoryItem::from(item))
    }

    /// Soft-invalidates a memory at a valid-time end.
    #[pyo3(signature = (memory_id, valid_to_unix))]
    fn invalidate(&self, memory_id: &str, valid_to_unix: i64) -> PyResult<bool> {
        let id = parse_memory_id(memory_id)?;
        let valid_to = time_from_optional_unix(Some(valid_to_unix))?;
        let mut inner = self.inner.lock().map_err(lock_error)?;

        inner.invalidate(id, valid_to).map_err(py_error)
    }

    /// Recalls current fact memories for a query embedding.
    #[pyo3(signature = (
        query_vector,
        top_k,
        now_unix = None,
        raw_query_context = None,
        include_cold = false,
        include_instructions = false,
        max_context_tokens = None,
        similarity_weight = 1.0,
        significance_weight = 1.0,
        recency_weight = 0.0,
        graph_weight = 0.0,
        related_memory_ids_by_anchor = None
    ))]
    fn recall(
        &self,
        query_vector: Vec<f32>,
        top_k: usize,
        now_unix: Option<i64>,
        raw_query_context: Option<&str>,
        include_cold: bool,
        include_instructions: bool,
        max_context_tokens: Option<usize>,
        similarity_weight: f64,
        significance_weight: f64,
        recency_weight: f64,
        graph_weight: f64,
        related_memory_ids_by_anchor: Option<BTreeMap<String, Vec<String>>>,
    ) -> PyResult<Vec<PyRecallCandidate>> {
        let inner = self.inner.lock().map_err(lock_error)?;
        let mut request = recall_request(
            &query_vector,
            top_k,
            now_unix,
            raw_query_context,
            include_cold,
            include_instructions,
            max_context_tokens,
        )?
        .with_ranking(RecallRankingConfig {
            similarity_weight,
            significance_weight,
            recency_weight,
            graph_weight,
        });
        let related_provider = related_memory_ids_by_anchor
            .map(parse_related_memory_provider)
            .transpose()?;
        if let Some(provider) = &related_provider {
            request = request.with_related_memory_provider(provider);
        }
        let candidates = inner.recall(&request).map_err(py_error)?;

        Ok(candidates
            .into_iter()
            .map(PyRecallCandidate::from)
            .collect())
    }

    /// Returns all current materialized memory rows.
    fn memory_items(&self) -> PyResult<Vec<PyMemoryItem>> {
        let inner = self.inner.lock().map_err(lock_error)?;
        let items = inner.memory_items().map_err(py_error)?;

        Ok(items.into_iter().map(PyMemoryItem::from).collect())
    }

    /// Returns durable event-log records as JSON.
    fn event_records_json(&self) -> PyResult<String> {
        let inner = self.inner.lock().map_err(lock_error)?;
        let events = inner
            .event_records()
            .map_err(py_error)?
            .iter()
            .map(event_record_json)
            .collect::<Vec<_>>();

        serde_json::to_string(&json!({
            "event_count": events.len(),
            "events": events,
        }))
        .map_err(json_error)
    }

    /// Returns one memory's why trace and related events as JSON.
    #[pyo3(signature = (memory_id, now_unix = None))]
    fn audit_json(&self, memory_id: &str, now_unix: Option<i64>) -> PyResult<String> {
        let id = parse_memory_id(memory_id)?;
        let now = time_from_optional_unix(now_unix)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let why = inner.why_at(id, now).map_err(py_error)?;
        let events = inner
            .event_records()
            .map_err(py_error)?
            .iter()
            .filter(|record| event_touches_memory(record, id))
            .map(event_record_json)
            .collect::<Vec<_>>();

        serde_json::to_string(&json!({
            "memory_id": id.to_string(),
            "why": why.as_ref().map(why_trace_json),
            "events": events,
        }))
        .map_err(json_error)
    }

    /// Runs the offline consolidation pass and returns its report as JSON.
    #[pyo3(signature = (now_unix = None))]
    fn consolidate_json(&self, now_unix: Option<i64>) -> PyResult<String> {
        let now = time_from_optional_unix(now_unix)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let report = inner.consolidate(now).map_err(py_error)?;

        serde_json::to_string(&consolidation_report_json(report)).map_err(json_error)
    }

    /// Streams current fact memories for a query embedding.
    #[pyo3(signature = (
        query_vector,
        top_k,
        now_unix = None,
        raw_query_context = None,
        include_cold = false,
        include_instructions = false,
        max_context_tokens = None,
        similarity_weight = 1.0,
        significance_weight = 1.0,
        recency_weight = 0.0,
        graph_weight = 0.0,
        related_memory_ids_by_anchor = None
    ))]
    fn stream_recall(
        &self,
        query_vector: Vec<f32>,
        top_k: usize,
        now_unix: Option<i64>,
        raw_query_context: Option<&str>,
        include_cold: bool,
        include_instructions: bool,
        max_context_tokens: Option<usize>,
        similarity_weight: f64,
        significance_weight: f64,
        recency_weight: f64,
        graph_weight: f64,
        related_memory_ids_by_anchor: Option<BTreeMap<String, Vec<String>>>,
    ) -> PyResult<PyRecallStream> {
        let candidates = self.recall(
            query_vector,
            top_k,
            now_unix,
            raw_query_context,
            include_cold,
            include_instructions,
            max_context_tokens,
            similarity_weight,
            significance_weight,
            recency_weight,
            graph_weight,
            related_memory_ids_by_anchor,
        )?;

        Ok(PyRecallStream {
            candidates: candidates.into_iter(),
        })
    }

    /// Replays recalled memories as they were believed at a historical instant.
    #[pyo3(signature = (
        query_vector,
        top_k,
        as_of_unix,
        include_cold = false,
        include_instructions = false,
        max_context_tokens = None
    ))]
    fn timeline(
        &self,
        query_vector: Vec<f32>,
        top_k: usize,
        as_of_unix: i64,
        include_cold: bool,
        include_instructions: bool,
        max_context_tokens: Option<usize>,
    ) -> PyResult<Vec<PyRecallCandidate>> {
        let inner = self.inner.lock().map_err(lock_error)?;
        let request = recall_request(
            &query_vector,
            top_k,
            Some(as_of_unix),
            None,
            include_cold,
            include_instructions,
            max_context_tokens,
        )?;
        let candidates = inner.timeline(&request).map_err(py_error)?;

        Ok(candidates
            .into_iter()
            .map(PyRecallCandidate::from)
            .collect())
    }

    /// Streams historical recall results.
    #[pyo3(signature = (
        query_vector,
        top_k,
        as_of_unix,
        include_cold = false,
        include_instructions = false,
        max_context_tokens = None
    ))]
    fn stream_timeline(
        &self,
        query_vector: Vec<f32>,
        top_k: usize,
        as_of_unix: i64,
        include_cold: bool,
        include_instructions: bool,
        max_context_tokens: Option<usize>,
    ) -> PyResult<PyRecallStream> {
        let candidates = self.timeline(
            query_vector,
            top_k,
            as_of_unix,
            include_cold,
            include_instructions,
            max_context_tokens,
        )?;

        Ok(PyRecallStream {
            candidates: candidates.into_iter(),
        })
    }

    /// Records a usage outcome for a memory.
    #[pyo3(signature = (memory_id, outcome = "cited"))]
    fn reinforce(&self, memory_id: &str, outcome: &str) -> PyResult<bool> {
        let id = parse_memory_id(memory_id)?;
        let outcome = parse_access_outcome(outcome)?;
        let inner = self.inner.lock().map_err(lock_error)?;

        inner.reinforce(id, outcome).map_err(py_error)
    }

    /// Challenges a memory and returns the mutation report as JSON.
    #[pyo3(signature = (memory_id, reason, actor = "python", timestamp_unix = None))]
    fn challenge_json(
        &self,
        memory_id: &str,
        reason: &str,
        actor: &str,
        timestamp_unix: Option<i64>,
    ) -> PyResult<String> {
        self.human_signal_json(
            memory_id,
            reason,
            actor,
            timestamp_unix,
            HumanSignalAction::Challenge,
        )
    }

    /// Affirms a memory and returns the mutation report as JSON.
    #[pyo3(signature = (memory_id, reason = "affirmed", actor = "python", timestamp_unix = None))]
    fn affirm_json(
        &self,
        memory_id: &str,
        reason: &str,
        actor: &str,
        timestamp_unix: Option<i64>,
    ) -> PyResult<String> {
        self.human_signal_json(
            memory_id,
            reason,
            actor,
            timestamp_unix,
            HumanSignalAction::Affirm,
        )
    }

    /// Pins a memory and returns the mutation report as JSON.
    #[pyo3(signature = (memory_id, reason = "pinned", actor = "python", timestamp_unix = None))]
    fn pin_json(
        &self,
        memory_id: &str,
        reason: &str,
        actor: &str,
        timestamp_unix: Option<i64>,
    ) -> PyResult<String> {
        self.human_signal_json(
            memory_id,
            reason,
            actor,
            timestamp_unix,
            HumanSignalAction::Pin,
        )
    }

    /// Unpins a memory and returns the mutation report as JSON.
    #[pyo3(signature = (memory_id, reason = "unpinned", actor = "python", timestamp_unix = None))]
    fn unpin_json(
        &self,
        memory_id: &str,
        reason: &str,
        actor: &str,
        timestamp_unix: Option<i64>,
    ) -> PyResult<String> {
        self.human_signal_json(
            memory_id,
            reason,
            actor,
            timestamp_unix,
            HumanSignalAction::Unpin,
        )
    }

    /// Corrects a memory and returns the mutation report as JSON.
    #[pyo3(signature = (
        memory_id,
        proposed_content,
        reason = "corrected",
        actor = "python",
        timestamp_unix = None
    ))]
    fn correct_json(
        &self,
        memory_id: &str,
        proposed_content: String,
        reason: &str,
        actor: &str,
        timestamp_unix: Option<i64>,
    ) -> PyResult<String> {
        let id = parse_memory_id(memory_id)?;
        let request = human_signal_request(actor, reason, timestamp_unix)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let outcome = inner
            .correct_with_request(id, proposed_content, request)
            .map_err(py_error)?;

        serde_json::to_string(&outcome.map_or_else(
            || json!({ "applied": false }),
            human_correction_outcome_json,
        ))
        .map_err(json_error)
    }

    /// Explains why a memory currently has its state.
    #[pyo3(signature = (memory_id, now_unix = None))]
    fn why(&self, memory_id: &str, now_unix: Option<i64>) -> PyResult<Option<PyWhyTrace>> {
        let id = parse_memory_id(memory_id)?;
        let now = time_from_optional_unix(now_unix)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let why = inner.why_at(id, now).map_err(py_error)?;

        Ok(why.map(PyWhyTrace::from))
    }
}

impl PyShibahama {
    fn human_signal_json(
        &self,
        memory_id: &str,
        reason: &str,
        actor: &str,
        timestamp_unix: Option<i64>,
        action: HumanSignalAction,
    ) -> PyResult<String> {
        let id = parse_memory_id(memory_id)?;
        let request = human_signal_request(actor, reason, timestamp_unix)?;
        let inner = self.inner.lock().map_err(lock_error)?;
        let outcome = match action {
            HumanSignalAction::Challenge => inner.challenge_with_request(id, request),
            HumanSignalAction::Affirm => inner.affirm_with_request(id, request),
            HumanSignalAction::Pin => inner.pin_with_request(id, request),
            HumanSignalAction::Unpin => inner.unpin_with_request(id, request),
            HumanSignalAction::Correct => {
                return Err(PyValueError::new_err("use correct_json for corrections"));
            }
        }
        .map_err(py_error)?;

        serde_json::to_string(
            &outcome.map_or_else(|| json!({ "applied": false }), human_signal_outcome_json),
        )
        .map_err(json_error)
    }
}

impl From<Provenance> for PyProvenance {
    fn from(value: Provenance) -> Self {
        Self {
            source_kind: source_kind_str(value.source_kind).to_owned(),
            source_ref: value.source_ref,
            ingested_by: value.ingested_by,
        }
    }
}

impl From<MemoryItem> for PyMemoryItem {
    fn from(value: MemoryItem) -> Self {
        Self {
            id: value.id.to_string(),
            content: value.content,
            kind: memory_kind_str(value.kind).to_owned(),
            provenance: PyProvenance::from(value.provenance),
            tier: tier_str(value.tier).to_owned(),
            credence: credence_str(value.credence).to_owned(),
            significance: value.significance,
            credence_floor: tier_str(value.credence_floor).to_owned(),
            valid_from_unix: value.timestamps.valid_from.unix_timestamp(),
            valid_to_unix: value
                .timestamps
                .valid_to
                .map(OffsetDateTime::unix_timestamp),
            ingested_at_unix: value.timestamps.ingested_at.unix_timestamp(),
        }
    }
}

impl From<RecallCandidate> for PyRecallCandidate {
    fn from(value: RecallCandidate) -> Self {
        Self {
            id: value.id.to_string(),
            item: PyMemoryItem::from(value.item),
            kind: memory_kind_str(value.kind).to_owned(),
            provenance: PyProvenance::from(value.provenance),
            tier: tier_str(value.tier).to_owned(),
            currency: currency_str(value.currency).to_owned(),
            load_bearing_possibly_stale: value.load_bearing_possibly_stale,
            cold_tier_retrieval: value.cold_tier_retrieval,
            vector_distance: value.vector_distance,
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

impl From<SignificanceBreakdown> for PySignificanceBreakdown {
    fn from(value: SignificanceBreakdown) -> Self {
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

impl From<WhyTrace> for PyWhyTrace {
    fn from(value: WhyTrace) -> Self {
        Self {
            item: PyMemoryItem::from(value.item),
            significance: PySignificanceBreakdown::from(value.significance),
            provenance: PyProvenance::from(value.provenance),
            tier_current: tier_str(value.tier.current).to_owned(),
            tier_credence: credence_str(value.tier.credence).to_owned(),
            tier_credence_floor: tier_str(value.tier.credence_floor).to_owned(),
            currency_state: currency_str(value.currency.state).to_owned(),
            currency_as_of_unix: value.currency.as_of.unix_timestamp(),
            valid_from_unix: value.currency.valid_from.unix_timestamp(),
            valid_to_unix: value.currency.valid_to.map(OffsetDateTime::unix_timestamp),
            ingested_at_unix: value.currency.ingested_at.unix_timestamp(),
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
        "recorded_at_unix": record.recorded_at.unix_timestamp(),
        "kind": event_kind(&record.event),
        "memory_ids": event_memory_ids(&record.event),
        "event": serde_json::to_value(&record.event).unwrap_or_else(|error| {
            json!({ "serialization_error": error.to_string() })
        }),
    })
}

fn memory_item_json(item: &MemoryItem) -> Value {
    json!({
        "id": item.id.to_string(),
        "content": item.content,
        "kind": memory_kind_str(item.kind),
        "provenance": {
            "source_kind": source_kind_str(item.provenance.source_kind),
            "source_ref": item.provenance.source_ref,
            "ingested_by": item.provenance.ingested_by,
        },
        "tier": tier_str(item.tier),
        "credence": credence_str(item.credence),
        "significance": item.significance,
        "credence_floor": tier_str(item.credence_floor),
        "valid_from_unix": item.timestamps.valid_from.unix_timestamp(),
        "valid_to_unix": item.timestamps.valid_to.map(OffsetDateTime::unix_timestamp),
        "ingested_at_unix": item.timestamps.ingested_at.unix_timestamp(),
    })
}

fn why_trace_json(trace: &WhyTrace) -> Value {
    json!({
        "item": memory_item_json(&trace.item),
        "significance": trace.significance,
        "provenance": {
            "source_kind": source_kind_str(trace.provenance.source_kind),
            "source_ref": trace.provenance.source_ref,
            "ingested_by": trace.provenance.ingested_by,
        },
        "tier_current": tier_str(trace.tier.current),
        "tier_credence": credence_str(trace.tier.credence),
        "tier_credence_floor": tier_str(trace.tier.credence_floor),
        "currency_state": currency_str(trace.currency.state),
        "currency_as_of_unix": trace.currency.as_of.unix_timestamp(),
        "valid_from_unix": trace.currency.valid_from.unix_timestamp(),
        "valid_to_unix": trace.currency.valid_to.map(OffsetDateTime::unix_timestamp),
        "ingested_at_unix": trace.currency.ingested_at.unix_timestamp(),
        "audit_trail": trace.audit_trail.iter().map(|entry| format!("{entry:?}")).collect::<Vec<_>>(),
    })
}

fn human_signal_json(signal: &HumanSignal) -> Value {
    json!({
        "action": human_signal_action_str(signal.action),
        "memory_id": signal.memory_id.to_string(),
        "actor": signal.actor,
        "timestamp_unix": signal.timestamp.unix_timestamp(),
        "reason": signal.reason,
        "proposed_content": signal.proposed_content,
        "proposal_id": signal.proposal_id.map(|id| id.to_string()),
        "previous_credence": signal.previous_credence.map(credence_str),
        "new_credence": signal.new_credence.map(credence_str),
        "previous_credence_floor": signal.previous_credence_floor.map(tier_str),
        "new_credence_floor": signal.new_credence_floor.map(tier_str),
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
                "input_ids": outcome.decision.input_ids.into_iter().map(|id| id.to_string()).collect::<Vec<_>>(),
                "output_id": outcome.decision.output.map(|item| item.id.to_string()),
                "tier_from": outcome.decision.tier_from.map(tier_str),
                "tier_to": outcome.decision.tier_to.map(tier_str),
                "why": outcome.decision.why.summary,
                "events": events,
            })
        })
        .collect::<Vec<_>>();

    json!({
        "pass_id": report.pass_id,
        "applied_count": applied_count,
        "outcomes": outcomes,
    })
}

/// Returns the Shibahama core crate version.
#[pyfunction]
fn version() -> &'static str {
    shibahama_core::version()
}

/// Python extension module entry point.
#[pymodule]
fn _shibahama(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", shibahama_core::version())?;
    module.add_function(wrap_pyfunction!(version, module)?)?;
    module.add_class::<PyProvenance>()?;
    module.add_class::<PyMemoryItem>()?;
    module.add_class::<PyRecallCandidate>()?;
    module.add_class::<PySignificanceBreakdown>()?;
    module.add_class::<PyWhyTrace>()?;
    module.add_class::<PyRecallStream>()?;
    module.add_class::<PyShibahama>()?;

    Ok(())
}

fn write_event(
    content: String,
    source_kind: &str,
    source_ref: Option<String>,
    ingested_by: &str,
    valid_from_unix: Option<i64>,
    ingested_at_unix: Option<i64>,
) -> PyResult<MemoryWriteEvent> {
    let valid_from = time_from_optional_unix(valid_from_unix)?;
    let ingested_at = time_from_optional_unix(ingested_at_unix)?;
    let provenance = Provenance::new(parse_source_kind(source_kind)?, source_ref, ingested_by);

    Ok(MemoryWriteEvent::new(
        content,
        provenance,
        valid_from,
        ingested_at,
    ))
}

fn recall_request<'a>(
    query_vector: &'a [f32],
    top_k: usize,
    now_unix: Option<i64>,
    raw_query_context: Option<&'a str>,
    include_cold: bool,
    include_instructions: bool,
    max_context_tokens: Option<usize>,
) -> PyResult<RecallRequest<'a>> {
    let mut request = RecallRequest::new(query_vector, top_k, time_from_optional_unix(now_unix)?);

    if let Some(raw_query_context) = raw_query_context {
        request = request.with_raw_query_context(raw_query_context);
    }
    if include_cold {
        request = request.include_cold();
    }
    if include_instructions {
        request = request.include_instructions();
    }
    if let Some(max_context_tokens) = max_context_tokens {
        request = request.with_max_context_tokens(max_context_tokens);
    }

    Ok(request)
}

fn time_from_optional_unix(value: Option<i64>) -> PyResult<OffsetDateTime> {
    match value {
        Some(value) => OffsetDateTime::from_unix_timestamp(value)
            .map_err(|error| PyValueError::new_err(format!("invalid Unix timestamp: {error}"))),
        None => Ok(OffsetDateTime::now_utc()),
    }
}

fn parse_memory_id(value: &str) -> PyResult<MemoryId> {
    Uuid::parse_str(value)
        .map(MemoryId::from)
        .map_err(|error| PyValueError::new_err(format!("invalid memory id: {error}")))
}

fn human_signal_request(
    actor: &str,
    reason: &str,
    timestamp_unix: Option<i64>,
) -> PyResult<HumanSignalRequest> {
    Ok(HumanSignalRequest::new(
        actor,
        reason,
        time_from_optional_unix(timestamp_unix)?,
    ))
}

fn parse_related_memory_provider(
    value: BTreeMap<String, Vec<String>>,
) -> PyResult<PyRelatedMemoryProvider> {
    let mut related = BTreeMap::new();

    for (anchor, related_values) in value {
        related.insert(
            parse_memory_id(&anchor)?,
            related_values
                .into_iter()
                .map(|related_id| parse_memory_id(&related_id))
                .collect::<PyResult<Vec<_>>>()?,
        );
    }

    Ok(PyRelatedMemoryProvider { related })
}

fn parse_source_kind(value: &str) -> PyResult<SourceKind> {
    match value {
        "user" => Ok(SourceKind::User),
        "agent" => Ok(SourceKind::Agent),
        "file" => Ok(SourceKind::File),
        "web" => Ok(SourceKind::Web),
        "tool" => Ok(SourceKind::Tool),
        _ => Err(PyValueError::new_err(
            "source_kind must be one of: user, agent, file, web, tool",
        )),
    }
}

fn parse_memory_kind(value: &str) -> PyResult<MemoryKind> {
    match value {
        "fact" => Ok(MemoryKind::Fact),
        "instruction" => Ok(MemoryKind::Instruction),
        _ => Err(PyValueError::new_err(
            "kind must be one of: fact, instruction",
        )),
    }
}

fn parse_access_outcome(value: &str) -> PyResult<AccessOutcome> {
    match value {
        "surfaced" => Ok(AccessOutcome::Surfaced),
        "led_somewhere" | "led-somewhere" => Ok(AccessOutcome::LedSomewhere),
        "cited" => Ok(AccessOutcome::Cited),
        "ignored" => Ok(AccessOutcome::Ignored),
        "contradicted" => Ok(AccessOutcome::Contradicted),
        _ => Err(PyValueError::new_err(
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

fn py_error(error: ShibahamaError) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

fn json_error(error: serde_json::Error) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

fn lock_error(error: std::sync::PoisonError<impl Sized>) -> PyErr {
    PyRuntimeError::new_err(format!("Shibahama engine lock poisoned: {error}"))
}
