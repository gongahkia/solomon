// SPDX-License-Identifier: MIT

//! Bounded automatic extraction and capture with explicit policy and audit boundaries.

use crate::api::{ScopeMode, Shibahama, ShibahamaError};
use crate::embedding::EmbeddingProvider;
use crate::extraction::{
    ExtractionCandidate, ExtractionRequest, MemoryExtractor, SourceEvidence, validate_candidates,
};
use crate::model::{MemoryId, MemoryScope, Provenance, SourceKind};
use crate::observability::{ObservabilityOperation, ObservabilityRecord};
use crate::policy::{
    CaptureIntent, CapturePolicyRequest, PolicyActorClass, PolicyAuditDisposition,
};
use crate::storage::{MemoryEvent, MemoryWriteEvent};
use crate::vector::VectorIndex;
use serde::{Deserialize, Serialize};
use std::time::Instant;
use thiserror::Error;
use time::OffsetDateTime;
use uuid::Uuid;

/// Upper bound for extraction tasks started by one automatic-capture worker.
pub const MAX_AUTOMATIC_CAPTURE_CONCURRENCY: usize = 16;
/// Upper bound for candidates accepted from one source item.
pub const MAX_AUTOMATIC_CAPTURE_CANDIDATES: usize = 16;

/// Cooperative cancellation boundary for automatic capture.
pub trait AutomaticCaptureCancellation: Send + Sync {
    /// Returns whether the worker should stop before its next extraction or persistence action.
    fn is_cancelled(&self) -> bool;
}

/// No-op cancellation boundary for batch callers that do not need cancellation.
#[derive(Clone, Copy, Debug, Default)]
pub struct NeverCancelAutomaticCapture;

impl AutomaticCaptureCancellation for NeverCancelAutomaticCapture {
    fn is_cancelled(&self) -> bool {
        false
    }
}

/// One bounded evidence item submitted to the automatic capture worker.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AutomaticCaptureInput {
    /// Scope that extraction candidates must retain.
    pub scope: MemoryScope,
    /// Attributable integration or service identity.
    pub submitted_by: String,
    /// Bounded source evidence supplied to the extractor.
    pub evidence: SourceEvidence,
}

/// Worker limits and policy identity for automatic capture.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AutomaticCaptureWorkerConfig {
    /// Policy actor class attributed to every automatic capture request.
    pub actor: PolicyActorClass,
    /// Maximum concurrent extraction calls; persistence remains serialized.
    pub max_in_flight: usize,
    /// Maximum candidates accepted from one evidence input.
    pub max_candidates_per_input: usize,
}

impl Default for AutomaticCaptureWorkerConfig {
    fn default() -> Self {
        Self {
            actor: PolicyActorClass::Automation,
            max_in_flight: 1,
            max_candidates_per_input: 4,
        }
    }
}

/// Content-free durable outcome for one automatic capture step.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomaticCaptureDisposition {
    /// Candidate was persisted as a normal memory.
    Persisted,
    /// A prior terminal event already processed the same candidate or empty input.
    Duplicate,
    /// Policy rejected automatic capture.
    DeniedByPolicy,
    /// Extractor returned no candidates for the source evidence.
    NoCandidate,
    /// Extractor output was invalid or attempted a scope escalation.
    InvalidCandidate,
    /// Extractor failed without exposing source content in the error record.
    ExtractionFailed,
    /// Durable memory write failed without exposing source content in the error record.
    PersistenceFailed,
    /// Cooperative cancellation stopped this work before persistence.
    Cancelled,
}

impl AutomaticCaptureDisposition {
    /// Returns whether this outcome prevents reprocessing the same idempotency key.
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Persisted | Self::DeniedByPolicy | Self::NoCandidate | Self::InvalidCandidate
        )
    }
}

/// Append-only, content-free automatic-capture audit record.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AutomaticCaptureAuditRecord {
    /// Stable run identifier shared by one worker invocation.
    pub run_id: String,
    /// Opaque hash for idempotency lookup; it never stores source content.
    pub idempotency_key: String,
    /// Final step outcome.
    pub disposition: AutomaticCaptureDisposition,
    /// Policy actor class attributed to the operation.
    pub actor: PolicyActorClass,
    /// Scope enforced for this evidence and candidate.
    pub scope: MemoryScope,
    /// Original source class retained as provenance metadata.
    pub source_kind: SourceKind,
    /// Opaque source-reference fingerprint; never the raw reference.
    pub source_ref_fingerprint: String,
    /// Materialized memory id when persistence succeeded.
    pub memory_id: Option<MemoryId>,
}

/// Aggregate result of one bounded automatic-capture run.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct AutomaticCaptureReport {
    /// Stable run identifier used by all emitted audit records.
    pub run_id: String,
    /// Number of input sources considered.
    pub inputs_considered: usize,
    /// Number of normal memories persisted.
    pub persisted_memory_ids: Vec<MemoryId>,
    /// Count of candidates skipped by durable idempotency state.
    pub duplicates: usize,
    /// Count of policy-denied candidates.
    pub denied: usize,
    /// Count of invalid candidates.
    pub invalid: usize,
    /// Count of failed extractor or persistence operations.
    pub failed: usize,
    /// Count of cancelled inputs or candidates.
    pub cancelled: usize,
}

/// Automatic-capture worker configuration failure.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum AutomaticCaptureError {
    /// Configured worker limits exceed fixed safe bounds.
    #[error("automatic capture worker limits are invalid")]
    InvalidConfig,
    /// Input context is incomplete or malformed.
    #[error("automatic capture input is invalid")]
    InvalidInput,
    /// Candidate validity cannot be represented by the memory model.
    #[error("automatic capture candidate validity is invalid")]
    InvalidValidity,
    /// Core policy or persistence operation failed.
    #[error("automatic capture core operation failed")]
    Core,
}

/// Executes bounded extraction concurrently and persistence serially.
#[derive(Clone, Copy, Debug)]
pub struct AutomaticCaptureWorker {
    config: AutomaticCaptureWorkerConfig,
}

impl AutomaticCaptureWorker {
    /// Creates a worker only when concurrency and candidate limits are bounded.
    ///
    /// # Errors
    ///
    /// Returns [`AutomaticCaptureError::InvalidConfig`] for unsupported limits.
    pub fn new(config: AutomaticCaptureWorkerConfig) -> Result<Self, AutomaticCaptureError> {
        if config.max_in_flight == 0
            || config.max_in_flight > MAX_AUTOMATIC_CAPTURE_CONCURRENCY
            || config.max_candidates_per_input == 0
            || config.max_candidates_per_input > MAX_AUTOMATIC_CAPTURE_CANDIDATES
        {
            return Err(AutomaticCaptureError::InvalidConfig);
        }
        Ok(Self { config })
    }

    /// Runs a bounded capture batch with cooperative cancellation and durable idempotency.
    ///
    /// Extraction calls run in groups no larger than `max_in_flight`; all writes are serialized
    /// through the supplied engine after policy evaluation.
    ///
    /// # Errors
    ///
    /// Returns an error only for malformed input or an unavailable durable audit boundary. Per-item
    /// extractor, policy, and persistence failures are recorded in the returned report.
    pub fn run<V: VectorIndex>(
        &self,
        engine: &mut Shibahama<V>,
        inputs: &[AutomaticCaptureInput],
        extractor: &dyn MemoryExtractor,
        cancellation: &dyn AutomaticCaptureCancellation,
    ) -> Result<AutomaticCaptureReport, AutomaticCaptureError> {
        self.run_inner(engine, None, inputs, extractor, cancellation)
    }

    /// Runs a bounded capture batch and embeds every persisted memory through `provider`.
    ///
    /// # Errors
    ///
    /// Returns an error only for malformed input or an unavailable durable audit boundary. Per-item
    /// extractor, policy, provider, and persistence failures are recorded in the returned report.
    pub fn run_with_provider<V: VectorIndex>(
        &self,
        engine: &mut Shibahama<V>,
        inputs: &[AutomaticCaptureInput],
        extractor: &dyn MemoryExtractor,
        provider: &dyn EmbeddingProvider,
        index_name: &str,
        cancellation: &dyn AutomaticCaptureCancellation,
    ) -> Result<AutomaticCaptureReport, AutomaticCaptureError> {
        self.run_inner(
            engine,
            Some((provider, index_name)),
            inputs,
            extractor,
            cancellation,
        )
    }

    #[allow(clippy::too_many_lines)]
    fn run_inner<V: VectorIndex>(
        &self,
        engine: &mut Shibahama<V>,
        provider: Option<(&dyn EmbeddingProvider, &str)>,
        inputs: &[AutomaticCaptureInput],
        extractor: &dyn MemoryExtractor,
        cancellation: &dyn AutomaticCaptureCancellation,
    ) -> Result<AutomaticCaptureReport, AutomaticCaptureError> {
        let started = Instant::now();
        for input in inputs {
            validate_input(input)?;
        }
        let run_id = Uuid::now_v7().to_string();
        let policy = engine.config().capture_policy;
        let policy_fingerprint =
            fingerprint(&serde_json::to_vec(&policy).map_err(|_| AutomaticCaptureError::Core)?);
        let mut terminal_keys = engine
            .store()
            .automatic_capture_terminal_keys()
            .map_err(|_| AutomaticCaptureError::Core)?;
        let mut report = AutomaticCaptureReport {
            run_id: run_id.clone(),
            inputs_considered: inputs.len(),
            ..AutomaticCaptureReport::default()
        };
        if !engine.config().automatic_capture_enabled {
            for input in inputs {
                let key = input_key(input, self.config.actor, &policy_fingerprint);
                record_audit(
                    engine,
                    audit_record(
                        &run_id,
                        input,
                        key,
                        AutomaticCaptureDisposition::DeniedByPolicy,
                        self.config.actor,
                        None,
                    ),
                )?;
                report.denied += 1;
            }
            record_automatic_capture_observability(
                engine,
                &run_id,
                started.elapsed().as_millis().try_into().unwrap_or(u64::MAX),
                provider,
            )?;
            return Ok(report);
        }

        for group in inputs.chunks(self.config.max_in_flight) {
            let extracted = std::thread::scope(|scope| {
                group
                    .iter()
                    .map(|input| {
                        scope.spawn(|| {
                            extract_input(
                                input,
                                self.config.max_candidates_per_input,
                                extractor,
                                cancellation,
                            )
                        })
                    })
                    .collect::<Vec<_>>()
                    .into_iter()
                    .map(|task| task.join().unwrap_or(ExtractedInput::Failed))
                    .collect::<Vec<_>>()
            });
            for (input, extraction) in group.iter().zip(extracted) {
                let input_key = input_key(input, self.config.actor, &policy_fingerprint);
                if cancellation.is_cancelled() {
                    record_audit(
                        engine,
                        audit_record(
                            &run_id,
                            input,
                            input_key,
                            AutomaticCaptureDisposition::Cancelled,
                            self.config.actor,
                            None,
                        ),
                    )?;
                    report.cancelled += 1;
                    continue;
                }
                match extraction {
                    ExtractedInput::Failed => {
                        record_audit(
                            engine,
                            audit_record(
                                &run_id,
                                input,
                                input_key,
                                AutomaticCaptureDisposition::ExtractionFailed,
                                self.config.actor,
                                None,
                            ),
                        )?;
                        report.failed += 1;
                    }
                    ExtractedInput::Invalid => {
                        record_audit(
                            engine,
                            audit_record(
                                &run_id,
                                input,
                                input_key.clone(),
                                AutomaticCaptureDisposition::InvalidCandidate,
                                self.config.actor,
                                None,
                            ),
                        )?;
                        terminal_keys.insert(input_key);
                        report.invalid += 1;
                    }
                    ExtractedInput::Candidates(candidates) if candidates.is_empty() => {
                        if terminal_keys.contains(&input_key) {
                            report.duplicates += 1;
                            record_audit(
                                engine,
                                audit_record(
                                    &run_id,
                                    input,
                                    input_key,
                                    AutomaticCaptureDisposition::Duplicate,
                                    self.config.actor,
                                    None,
                                ),
                            )?;
                        } else {
                            record_audit(
                                engine,
                                audit_record(
                                    &run_id,
                                    input,
                                    input_key.clone(),
                                    AutomaticCaptureDisposition::NoCandidate,
                                    self.config.actor,
                                    None,
                                ),
                            )?;
                            terminal_keys.insert(input_key);
                        }
                    }
                    ExtractedInput::Candidates(candidates) => {
                        for candidate in candidates {
                            let key = candidate_key(&input_key, &candidate);
                            if terminal_keys.contains(&key) {
                                record_audit(
                                    engine,
                                    audit_record(
                                        &run_id,
                                        input,
                                        key,
                                        AutomaticCaptureDisposition::Duplicate,
                                        self.config.actor,
                                        None,
                                    ),
                                )?;
                                report.duplicates += 1;
                                continue;
                            }
                            if cancellation.is_cancelled() {
                                record_audit(
                                    engine,
                                    audit_record(
                                        &run_id,
                                        input,
                                        key,
                                        AutomaticCaptureDisposition::Cancelled,
                                        self.config.actor,
                                        None,
                                    ),
                                )?;
                                report.cancelled += 1;
                                continue;
                            }
                            let Ok(event) = candidate_write_event(&candidate, input) else {
                                record_audit(
                                    engine,
                                    audit_record(
                                        &run_id,
                                        input,
                                        key.clone(),
                                        AutomaticCaptureDisposition::InvalidCandidate,
                                        self.config.actor,
                                        None,
                                    ),
                                )?;
                                terminal_keys.insert(key);
                                report.invalid += 1;
                                continue;
                            };
                            let request = CapturePolicyRequest {
                                actor: self.config.actor,
                                intent: CaptureIntent::Automatic,
                                confidence_percent: candidate.confidence_percent,
                            };
                            let write = persist_candidate(engine, provider, event, request);
                            match write {
                                Ok(item) => {
                                    record_audit(
                                        engine,
                                        audit_record(
                                            &run_id,
                                            input,
                                            key.clone(),
                                            AutomaticCaptureDisposition::Persisted,
                                            self.config.actor,
                                            Some(item.id),
                                        ),
                                    )?;
                                    terminal_keys.insert(key);
                                    report.persisted_memory_ids.push(item.id);
                                }
                                Err(ShibahamaError::PolicyDenied(_)) => {
                                    record_audit(
                                        engine,
                                        audit_record(
                                            &run_id,
                                            input,
                                            key.clone(),
                                            AutomaticCaptureDisposition::DeniedByPolicy,
                                            self.config.actor,
                                            None,
                                        ),
                                    )?;
                                    terminal_keys.insert(key);
                                    report.denied += 1;
                                }
                                Err(_) => {
                                    record_audit(
                                        engine,
                                        audit_record(
                                            &run_id,
                                            input,
                                            key,
                                            AutomaticCaptureDisposition::PersistenceFailed,
                                            self.config.actor,
                                            None,
                                        ),
                                    )?;
                                    report.failed += 1;
                                }
                            }
                        }
                    }
                }
            }
        }

        record_automatic_capture_observability(
            engine,
            &run_id,
            started.elapsed().as_millis().try_into().unwrap_or(u64::MAX),
            provider,
        )?;
        Ok(report)
    }
}

enum ExtractedInput {
    Candidates(Vec<ExtractionCandidate>),
    Invalid,
    Failed,
}

fn extract_input(
    input: &AutomaticCaptureInput,
    max_candidates: usize,
    extractor: &dyn MemoryExtractor,
    cancellation: &dyn AutomaticCaptureCancellation,
) -> ExtractedInput {
    if cancellation.is_cancelled() {
        return ExtractedInput::Candidates(Vec::new());
    }
    let request = ExtractionRequest {
        evidence: vec![input.evidence.clone()],
        max_candidates,
    };
    match extractor.extract(&request) {
        Ok(_) if cancellation.is_cancelled() => ExtractedInput::Candidates(Vec::new()),
        Ok(candidates) if validate_candidates(&request, &candidates).is_ok() => {
            ExtractedInput::Candidates(candidates)
        }
        Ok(_) => ExtractedInput::Invalid,
        Err(_) => ExtractedInput::Failed,
    }
}

fn validate_input(input: &AutomaticCaptureInput) -> Result<(), AutomaticCaptureError> {
    if input.submitted_by.trim().is_empty()
        || input.scope.validate().is_err()
        || input.evidence.source_ref.trim().is_empty()
        || input.evidence.content.is_empty()
        || input.evidence.content.len() > crate::extraction::MAX_EXTRACTION_EVIDENCE_BYTES
    {
        return Err(AutomaticCaptureError::InvalidInput);
    }
    Ok(())
}

fn candidate_write_event(
    candidate: &ExtractionCandidate,
    input: &AutomaticCaptureInput,
) -> Result<MemoryWriteEvent, AutomaticCaptureError> {
    if candidate.suggested_scope != input.scope
        || candidate
            .evidence_spans
            .iter()
            .any(|span| span.evidence_index != 0)
    {
        return Err(AutomaticCaptureError::InvalidInput);
    }
    let valid_from = OffsetDateTime::from_unix_timestamp(candidate.validity.valid_from_unix)
        .map_err(|_| AutomaticCaptureError::InvalidValidity)?;
    let ingested_at = OffsetDateTime::from_unix_timestamp(candidate.validity.ingested_at_unix)
        .map_err(|_| AutomaticCaptureError::InvalidValidity)?;
    let mut event = MemoryWriteEvent::new(
        candidate.content.clone(),
        Provenance::new(
            input.evidence.source_kind,
            Some(input.evidence.source_ref.clone()),
            format!("automatic:{}", input.submitted_by),
        ),
        valid_from,
        ingested_at,
    )
    .with_scope(candidate.suggested_scope.clone());
    if let Some(valid_to) = candidate.validity.valid_to_unix {
        let valid_to = OffsetDateTime::from_unix_timestamp(valid_to)
            .map_err(|_| AutomaticCaptureError::InvalidValidity)?;
        if valid_to <= valid_from {
            return Err(AutomaticCaptureError::InvalidValidity);
        }
        event = event.with_valid_to(valid_to);
    }
    if ingested_at < valid_from {
        return Err(AutomaticCaptureError::InvalidValidity);
    }
    if candidate.kind == crate::model::MemoryKind::Instruction {
        event = event.as_instruction();
    }
    Ok(event)
}

fn record_audit<V: VectorIndex>(
    engine: &Shibahama<V>,
    record: AutomaticCaptureAuditRecord,
) -> Result<(), AutomaticCaptureError> {
    engine
        .store()
        .record_automatic_capture(record)
        .map_err(|_| AutomaticCaptureError::Core)?;
    Ok(())
}

fn record_automatic_capture_observability<V: VectorIndex>(
    engine: &Shibahama<V>,
    run_id: &str,
    duration_ms: u64,
    provider: Option<(&dyn EmbeddingProvider, &str)>,
) -> Result<(), AutomaticCaptureError> {
    let audits = engine
        .store()
        .events()
        .map_err(|_| AutomaticCaptureError::Core)?
        .into_iter()
        .filter_map(|event| match event.event {
            MemoryEvent::AutomaticCaptureRecorded { record } if record.run_id == run_id => {
                Some(record)
            }
            _ => None,
        })
        .collect::<Vec<_>>();

    for audit in audits {
        let (policy_outcome, error_code) = match audit.disposition {
            AutomaticCaptureDisposition::DeniedByPolicy => {
                (PolicyAuditDisposition::Denied, Some("SHIBA_POLICY_DENIED"))
            }
            AutomaticCaptureDisposition::InvalidCandidate => (
                PolicyAuditDisposition::Allowed,
                Some("SHIBA_INVALID_REQUEST"),
            ),
            AutomaticCaptureDisposition::ExtractionFailed
            | AutomaticCaptureDisposition::PersistenceFailed => (
                PolicyAuditDisposition::Allowed,
                Some("SHIBA_CAPTURE_FAILED"),
            ),
            AutomaticCaptureDisposition::Cancelled => {
                (PolicyAuditDisposition::Allowed, Some("SHIBA_CANCELLED"))
            }
            AutomaticCaptureDisposition::Persisted
            | AutomaticCaptureDisposition::Duplicate
            | AutomaticCaptureDisposition::NoCandidate => (PolicyAuditDisposition::Allowed, None),
        };
        engine
            .store()
            .record_observability(ObservabilityRecord {
                operation: ObservabilityOperation::AutomaticCapture,
                duration_ms,
                item_count: usize::from(audit.memory_id.is_some()),
                provider: provider.map(|(provider, _)| provider.metadata().provider),
                model: provider.map(|(provider, _)| provider.metadata().model),
                policy_outcome: Some(policy_outcome),
                error_code: error_code.map(str::to_owned),
                scope: Some(audit.scope),
            })
            .map_err(|_| AutomaticCaptureError::Core)?;
    }
    Ok(())
}

fn persist_candidate<V: VectorIndex>(
    engine: &mut Shibahama<V>,
    provider: Option<(&dyn EmbeddingProvider, &str)>,
    event: MemoryWriteEvent,
    request: CapturePolicyRequest,
) -> Result<crate::model::MemoryItem, ShibahamaError> {
    if engine.config().scope_mode == ScopeMode::RequireExplicit {
        let mut scoped = engine.scoped(event.scope.clone())?;
        return match provider {
            Some((provider, index_name)) => {
                scoped.write_with_provider_and_capture_policy(event, provider, index_name, request)
            }
            None => scoped.write_with_capture_policy(event, request),
        };
    }
    match provider {
        Some((provider, index_name)) => {
            engine.write_with_provider_and_capture_policy(event, provider, index_name, request)
        }
        None => engine.write_with_capture_policy(event, request),
    }
}

fn audit_record(
    run_id: &str,
    input: &AutomaticCaptureInput,
    idempotency_key: String,
    disposition: AutomaticCaptureDisposition,
    actor: PolicyActorClass,
    memory_id: Option<MemoryId>,
) -> AutomaticCaptureAuditRecord {
    AutomaticCaptureAuditRecord {
        run_id: run_id.to_owned(),
        idempotency_key,
        disposition,
        actor,
        scope: input.scope.clone(),
        source_kind: input.evidence.source_kind,
        source_ref_fingerprint: fingerprint(input.evidence.source_ref.as_bytes()),
        memory_id,
    }
}

fn input_key(
    input: &AutomaticCaptureInput,
    actor: PolicyActorClass,
    policy_fingerprint: &str,
) -> String {
    let mut payload = Vec::new();
    append_key_part(&mut payload, "policy", policy_fingerprint);
    append_key_part(&mut payload, "actor", policy_actor_key(actor));
    append_key_part(&mut payload, "scope", &scope_key(&input.scope));
    append_key_part(
        &mut payload,
        "source_kind",
        source_kind_key(input.evidence.source_kind),
    );
    append_key_part(&mut payload, "source_ref", &input.evidence.source_ref);
    append_key_part(&mut payload, "content", &input.evidence.content);
    fingerprint(&payload)
}

fn candidate_key(input_key: &str, candidate: &ExtractionCandidate) -> String {
    let mut payload = Vec::new();
    append_key_part(&mut payload, "input", input_key);
    append_key_part(&mut payload, "content", &candidate.content);
    append_key_part(&mut payload, "kind", memory_kind_key(candidate.kind));
    append_key_part(
        &mut payload,
        "valid_from",
        &candidate.validity.valid_from_unix.to_string(),
    );
    append_key_part(
        &mut payload,
        "valid_to",
        &candidate
            .validity
            .valid_to_unix
            .map_or_else(String::new, |value| value.to_string()),
    );
    append_key_part(
        &mut payload,
        "ingested_at",
        &candidate.validity.ingested_at_unix.to_string(),
    );
    append_key_part(
        &mut payload,
        "confidence",
        &candidate.confidence_percent.to_string(),
    );
    append_key_part(&mut payload, "rationale", &candidate.rationale);
    append_key_part(
        &mut payload,
        "scope",
        &scope_key(&candidate.suggested_scope),
    );
    for span in &candidate.evidence_spans {
        append_key_part(
            &mut payload,
            "span",
            &format!("{}:{}:{}", span.evidence_index, span.start, span.end),
        );
    }
    fingerprint(&payload)
}

fn scope_key(scope: &MemoryScope) -> String {
    let visibility = match scope.visibility {
        crate::model::ScopeVisibility::Repository => "repository",
        crate::model::ScopeVisibility::Team => "team",
    };
    format!(
        "{visibility}:{}:{}",
        scope.repository,
        scope
            .team
            .as_ref()
            .map_or("", crate::model::ScopeId::as_str)
    )
}

const fn policy_actor_key(actor: PolicyActorClass) -> &'static str {
    match actor {
        PolicyActorClass::Human => "human",
        PolicyActorClass::Agent => "agent",
        PolicyActorClass::Automation => "automation",
        PolicyActorClass::Service => "service",
    }
}

const fn source_kind_key(source_kind: SourceKind) -> &'static str {
    match source_kind {
        SourceKind::User => "user",
        SourceKind::Agent => "agent",
        SourceKind::File => "file",
        SourceKind::Web => "web",
        SourceKind::Tool => "tool",
    }
}

const fn memory_kind_key(kind: crate::model::MemoryKind) -> &'static str {
    match kind {
        crate::model::MemoryKind::Fact => "fact",
        crate::model::MemoryKind::Instruction => "instruction",
    }
}

fn append_key_part(payload: &mut Vec<u8>, name: &str, value: &str) {
    payload.extend_from_slice(name.as_bytes());
    payload.push(0);
    payload.extend_from_slice(value.len().to_string().as_bytes());
    payload.push(0);
    payload.extend_from_slice(value.as_bytes());
    payload.push(0xff);
}

fn fingerprint(value: &[u8]) -> String {
    blake3::hash(value).to_hex().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::ShibahamaConfig;
    use crate::embedding::DeterministicLocalEmbeddingProvider;
    use crate::extraction::{CandidateValidity, EvidenceSpan};
    use crate::model::{MemoryKind, ScopeId};
    use crate::policy::{ActorClassPolicy, CaptureMode, CapturePolicy};
    use crate::storage::MemoryEvent;
    use crate::vector::HnswVectorIndex;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::thread;
    use std::time::Duration;
    use tempfile::NamedTempFile;

    struct Extractor {
        scope: MemoryScope,
        active: AtomicUsize,
        max_active: AtomicUsize,
    }

    impl Extractor {
        fn new(scope: MemoryScope) -> Self {
            Self {
                scope,
                active: AtomicUsize::new(0),
                max_active: AtomicUsize::new(0),
            }
        }

        fn update_max(&self, active: usize) {
            let mut maximum = self.max_active.load(Ordering::SeqCst);
            while active > maximum {
                match self.max_active.compare_exchange(
                    maximum,
                    active,
                    Ordering::SeqCst,
                    Ordering::SeqCst,
                ) {
                    Ok(_) => break,
                    Err(observed) => maximum = observed,
                }
            }
        }
    }

    impl MemoryExtractor for Extractor {
        fn extract(
            &self,
            request: &ExtractionRequest,
        ) -> Result<Vec<ExtractionCandidate>, crate::extraction::ExtractionError> {
            let active = self.active.fetch_add(1, Ordering::SeqCst) + 1;
            self.update_max(active);
            thread::sleep(Duration::from_millis(10));
            self.active.fetch_sub(1, Ordering::SeqCst);
            let evidence = &request.evidence[0];
            Ok(vec![ExtractionCandidate {
                content: format!("captured: {}", evidence.content),
                kind: MemoryKind::Fact,
                validity: CandidateValidity {
                    valid_from_unix: 0,
                    valid_to_unix: None,
                    ingested_at_unix: 0,
                },
                evidence_spans: vec![EvidenceSpan {
                    evidence_index: 0,
                    start: 0,
                    end: evidence.content.len(),
                }],
                confidence_percent: 90,
                rationale: "bounded extractor output".to_owned(),
                suggested_scope: self.scope.clone(),
            }])
        }
    }

    struct Cancelled(AtomicBool);

    impl AutomaticCaptureCancellation for Cancelled {
        fn is_cancelled(&self) -> bool {
            self.0.load(Ordering::SeqCst)
        }
    }

    fn input(scope: MemoryScope, content: &str) -> AutomaticCaptureInput {
        AutomaticCaptureInput {
            scope,
            submitted_by: "capture-worker".to_owned(),
            evidence: SourceEvidence {
                source_kind: SourceKind::File,
                source_ref: format!("file:{content}.rs"),
                content: content.to_owned(),
            },
        }
    }

    fn open_engine(file: &NamedTempFile) -> Shibahama<HnswVectorIndex> {
        Shibahama::open_with_config(
            file.path(),
            HnswVectorIndex::with_capacity(2, 16),
            ShibahamaConfig {
                scope_mode: ScopeMode::RequireExplicit,
                automatic_capture_enabled: true,
                capture_policy: CapturePolicy {
                    mode: CaptureMode::Automatic,
                    actors: ActorClassPolicy {
                        automation: true,
                        ..ActorClassPolicy::default()
                    },
                    ..CapturePolicy::default()
                },
                ..ShibahamaConfig::default()
            },
        )
        .expect("engine should open")
    }

    #[test]
    fn worker_bounds_concurrency_persists_idempotently_and_audits() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut engine = open_engine(&file);
        let scope = MemoryScope::repository(ScopeId::new("repo").expect("constant scope"));
        let extractor = Extractor::new(scope.clone());
        let worker = AutomaticCaptureWorker::new(AutomaticCaptureWorkerConfig {
            max_in_flight: 2,
            max_candidates_per_input: 1,
            ..AutomaticCaptureWorkerConfig::default()
        })
        .expect("worker limits should be valid");
        let inputs = vec![
            input(scope.clone(), "one"),
            input(scope.clone(), "two"),
            input(scope.clone(), "three"),
        ];
        let provider = DeterministicLocalEmbeddingProvider::new(2).expect("provider should work");

        let first = worker
            .run_with_provider(
                &mut engine,
                &inputs,
                &extractor,
                &provider,
                "automatic-capture",
                &NeverCancelAutomaticCapture,
            )
            .expect("worker should run");
        assert_eq!(first.persisted_memory_ids.len(), 3);
        assert_eq!(extractor.max_active.load(Ordering::SeqCst), 2);
        assert_eq!(
            engine
                .store()
                .memory_items_in_scope(&scope)
                .expect("memory should read")
                .len(),
            3
        );
        assert_eq!(
            engine
                .store()
                .stored_embeddings()
                .expect("embeddings should read")
                .len(),
            3
        );
        drop(engine);
        let mut engine = open_engine(&file);

        let second = worker
            .run(
                &mut engine,
                &inputs,
                &extractor,
                &NeverCancelAutomaticCapture,
            )
            .expect("worker rerun should succeed");
        assert!(second.persisted_memory_ids.is_empty());
        assert_eq!(second.duplicates, 3);
        assert_eq!(
            engine
                .store()
                .memory_items_in_scope(&scope)
                .expect("memory should read")
                .len(),
            3
        );
        let automatic_audits = engine
            .store()
            .events_in_scope(&scope)
            .expect("events should read")
            .into_iter()
            .filter(|event| matches!(event.event, MemoryEvent::AutomaticCaptureRecorded { .. }))
            .count();
        assert_eq!(automatic_audits, 6);
        let telemetry = engine
            .store()
            .events_in_scope(&scope)
            .expect("events should read")
            .into_iter()
            .filter_map(|event| match event.event {
                MemoryEvent::ObservabilityRecorded { record }
                    if record.operation == ObservabilityOperation::AutomaticCapture =>
                {
                    Some(record)
                }
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(telemetry.len(), 6);
        assert!(telemetry.iter().all(|record| {
            record.scope.as_ref() == Some(&scope)
                && record.policy_outcome == Some(PolicyAuditDisposition::Allowed)
        }));
        assert!(telemetry.iter().any(|record| record.item_count == 0));
    }

    #[test]
    fn worker_records_cancellation_without_persistence() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut engine = open_engine(&file);
        let scope = MemoryScope::repository(ScopeId::new("repo").expect("constant scope"));
        let extractor = Extractor::new(scope.clone());
        let cancellation = Cancelled(AtomicBool::new(true));
        let report = AutomaticCaptureWorker::new(AutomaticCaptureWorkerConfig::default())
            .expect("worker limits should be valid")
            .run(
                &mut engine,
                &[input(scope.clone(), "cancelled")],
                &extractor,
                &cancellation,
            )
            .expect("cancelled run should audit");

        assert_eq!(report.cancelled, 1);
        assert!(report.persisted_memory_ids.is_empty());
        assert!(
            engine
                .store()
                .memory_items_in_scope(&scope)
                .expect("memory should read")
                .is_empty()
        );
        assert!(
            engine
                .store()
                .events_in_scope(&scope)
                .expect("events should read")
                .iter()
                .any(|event| matches!(
                    event.event,
                    MemoryEvent::AutomaticCaptureRecorded {
                        ref record
                    } if record.disposition == AutomaticCaptureDisposition::Cancelled
                ))
        );
    }

    #[test]
    fn worker_records_policy_denial_without_persistence() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut engine = Shibahama::open_with_config(
            file.path(),
            HnswVectorIndex::with_capacity(2, 8),
            ShibahamaConfig {
                automatic_capture_enabled: true,
                capture_policy: CapturePolicy {
                    mode: CaptureMode::Suggest,
                    actors: ActorClassPolicy {
                        automation: true,
                        ..ActorClassPolicy::default()
                    },
                    ..CapturePolicy::default()
                },
                ..ShibahamaConfig::default()
            },
        )
        .expect("engine should open");
        let scope = MemoryScope::repository(ScopeId::new("repo").expect("constant scope"));
        let extractor = Extractor::new(scope.clone());
        let report = AutomaticCaptureWorker::new(AutomaticCaptureWorkerConfig::default())
            .expect("worker limits should be valid")
            .run(
                &mut engine,
                &[input(scope, "denied")],
                &extractor,
                &NeverCancelAutomaticCapture,
            )
            .expect("policy denial should be audited");

        assert_eq!(report.denied, 1);
        assert!(
            engine
                .memory_items()
                .expect("memory should read")
                .is_empty()
        );
        assert!(
            engine
                .event_records()
                .expect("events should read")
                .iter()
                .any(|event| matches!(
                    event.event,
                    MemoryEvent::AutomaticCaptureRecorded {
                        ref record
                    } if record.disposition == AutomaticCaptureDisposition::DeniedByPolicy
                        && record.source_ref_fingerprint != "file:denied.rs"
                ))
        );
    }

    #[test]
    fn worker_requires_explicit_engine_enablement_before_extraction() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut engine = Shibahama::open_with_config(
            file.path(),
            HnswVectorIndex::with_capacity(2, 8),
            ShibahamaConfig {
                capture_policy: CapturePolicy {
                    mode: CaptureMode::Automatic,
                    actors: ActorClassPolicy {
                        automation: true,
                        ..ActorClassPolicy::default()
                    },
                    ..CapturePolicy::default()
                },
                ..ShibahamaConfig::default()
            },
        )
        .expect("engine should open");
        let scope = MemoryScope::repository(ScopeId::new("repo").expect("constant scope"));
        let extractor = Extractor::new(scope.clone());
        let report = AutomaticCaptureWorker::new(AutomaticCaptureWorkerConfig::default())
            .expect("worker limits should be valid")
            .run(
                &mut engine,
                &[input(scope, "disabled")],
                &extractor,
                &NeverCancelAutomaticCapture,
            )
            .expect("disabled worker should audit");

        assert_eq!(report.denied, 1);
        assert_eq!(extractor.active.load(Ordering::SeqCst), 0);
        assert_eq!(extractor.max_active.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn worker_rejects_unbounded_limits() {
        assert!(matches!(
            AutomaticCaptureWorker::new(AutomaticCaptureWorkerConfig {
                max_in_flight: 0,
                ..AutomaticCaptureWorkerConfig::default()
            }),
            Err(AutomaticCaptureError::InvalidConfig)
        ));
        assert!(matches!(
            AutomaticCaptureWorker::new(AutomaticCaptureWorkerConfig {
                max_candidates_per_input: MAX_AUTOMATIC_CAPTURE_CANDIDATES + 1,
                ..AutomaticCaptureWorkerConfig::default()
            }),
            Err(AutomaticCaptureError::InvalidConfig)
        ));
    }
}
