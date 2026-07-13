// SPDX-License-Identifier: MIT

//! Small public API facade.

use crate::anomaly::AnomalyConfig;
use crate::consolidation::{
    ConsolidationPolicy, OfflineConsolidationConfig, PlannedConsolidationDecision,
    plan_offline_consolidation,
};
use crate::embedding::{EmbeddingProvider, EmbeddingPurpose, validate_embedding};
use crate::learned_policy::{
    ContextualBanditExperimentConfig, ContextualBanditExperimentReport, OfflinePolicyDecision,
    OfflinePolicyEvaluationConfig, OfflinePolicyEvaluationReport, PolicyEvaluationError,
    Stage3TrainingReadinessConfig, Stage3TrainingReadinessReport, assess_stage3_training_readiness,
    evaluate_offline_policy, plan_contextual_bandit_experiment,
};
use crate::model::{
    AccessOutcome, CredenceTier, Entity, EntityId, HumanSignal, HumanSignalAction, MemoryId,
    MemoryItem, MemoryScope, Provenance, Relation, RelationId, ScopeAuthorizationAction, ScopeId,
    SourceKind, Tier,
};
use crate::policy::{
    CapturePolicy, CapturePolicyRequest, CapturePolicySimulation, EffectivePolicy,
    PolicyAuditDisposition, PolicyAuditRecord, PolicyError, PolicyLayerSet, RecallPolicy,
    RecallPolicyDecision, RecallPolicySimulation, resolve_policy_inheritance,
};
use crate::reconstruction::{
    BackgroundReconstructionConfig, CorroborationDecision, CorroborationPolicy,
    CorroborationSignal, DefaultRevalidationHook, QuarantinedProposal, ReconstructionBudgetConfig,
    ReconstructionBudgetDenial, ReconstructionMode, ReconstructionTrigger, RevalidationAction,
    RevalidationHook, RevalidationSource, apply_reconstruction_budget, evaluate_corroboration,
    evaluate_reconstruction_gate, promote_corroborated_proposal, quarantine_proposal,
    triggers_from_recall,
};
use crate::retrieval::{
    DegradedRecallResult, RecallCandidate, RecallCandidateCurrency, RecallDiversificationConfig,
    RecallError, RecallRankingConfig, RecallRequest, RecallStalenessConfig, recall,
    recall_with_degradation, timeline,
};
use crate::significance::{SignificanceBreakdown, SignificanceConfig};
use crate::storage::{
    ConsolidationDecisionRecord, EventRecord, GraphSnapshot, GraphTraversalRequest,
    GraphTraversalResult, HumanSignalRecord, IngestCredencePolicy, MemoryAuditEntry, MemoryEvent,
    MemoryWriteEvent, ReconstructionReplacementRecord, RedbMemoryStore, ScopePromotionRecord,
    StorageError, SubgraphRequest, TierCapacityConfig,
};
use crate::vector::{VectorIndex, VectorIndexError};
use serde::Serialize;
use std::collections::BTreeMap;
use std::iter::FusedIterator;
use std::path::Path;
#[cfg(feature = "tokio")]
use std::path::PathBuf;
#[cfg(feature = "tokio")]
use std::sync::Arc;
use thiserror::Error;
use time::OffsetDateTime;

/// Error returned by the high-level Shibahama API.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum ShibahamaError {
    /// Storage operation failed.
    #[error(
        "[SHIBA_STORAGE] storage operation failed: {0}; action: verify the store path and durable state are accessible, then retry or restore from a snapshot"
    )]
    Storage(#[source] StorageError),
    /// Recall operation failed.
    #[error(
        "[SHIBA_RECALL] recall operation failed: {0}; action: verify the query embedding, vector index, and store availability before retrying"
    )]
    Recall(#[source] RecallError),
    /// Vector operation failed.
    #[error(
        "[SHIBA_VECTOR] vector index operation failed: {0}; action: verify embedding dimensionality and vector backend availability before retrying"
    )]
    Vector(#[source] VectorIndexError),
    /// Caller supplied an unsupported or internally inconsistent request.
    #[error("[SHIBA_INVALID_REQUEST] invalid request: {0}; action: adjust the request and retry")]
    InvalidRequest(String),
    /// Host policy denied a scope-crossing operation.
    #[error(
        "[SHIBA_UNAUTHORIZED] authorization denied; action: request access from a configured maintainer"
    )]
    AuthorizationDenied,
    /// Configured capture or recall policy denied the requested operation.
    #[error(
        "[SHIBA_POLICY] policy denied the requested operation; action: adjust the policy or request explicit approval"
    )]
    PolicyDenied(#[source] PolicyError),
    /// Tokio task failed before returning an API result.
    #[cfg(feature = "tokio")]
    #[error(
        "[SHIBA_TASK] async task failed: {0}; action: inspect the runtime for cancellation or panic before retrying"
    )]
    Task(#[source] tokio::task::JoinError),
}

impl From<StorageError> for ShibahamaError {
    fn from(error: StorageError) -> Self {
        match error {
            StorageError::Vector(error) => Self::Vector(error),
            error => Self::Storage(error),
        }
    }
}

impl From<RecallError> for ShibahamaError {
    fn from(error: RecallError) -> Self {
        match error {
            RecallError::Storage(error) => Self::from(error),
            RecallError::Vector(error) => Self::Vector(error),
            error @ RecallError::StageUnavailable { .. } => Self::Recall(error),
        }
    }
}

impl From<VectorIndexError> for ShibahamaError {
    fn from(error: VectorIndexError) -> Self {
        Self::Vector(error)
    }
}

impl From<PolicyError> for ShibahamaError {
    fn from(error: PolicyError) -> Self {
        Self::PolicyDenied(error)
    }
}

impl From<PolicyEvaluationError> for ShibahamaError {
    fn from(error: PolicyEvaluationError) -> Self {
        Self::InvalidRequest(error.to_string())
    }
}

#[cfg(feature = "tokio")]
impl From<tokio::task::JoinError> for ShibahamaError {
    fn from(error: tokio::task::JoinError) -> Self {
        Self::Task(error)
    }
}

/// Stable high-level error category for bindings and applications.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum ShibahamaErrorKind {
    /// Durable storage or snapshot state failed.
    Storage,
    /// Recall orchestration failed.
    Recall,
    /// Vector index or embedding dimensionality failed.
    Vector,
    /// Caller supplied an unsupported or internally inconsistent request.
    InvalidRequest,
    /// Host policy denied a scope-crossing operation.
    AuthorizationDenied,
    /// Configured policy denied the requested operation.
    PolicyDenied,
    /// Tokio task failed before returning an API result.
    #[cfg(feature = "tokio")]
    Task,
}

/// Operational severity for a Shibahama error category.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum ShibahamaErrorSeverity {
    /// The caller can continue with an explicitly degraded result or retry.
    Recoverable,
    /// The requested operation cannot safely complete.
    Fatal,
}

/// Stable transport-safe metadata for a high-level error.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct ShibahamaErrorMetadata {
    /// Machine-readable error code.
    pub code: &'static str,
    /// Whether the caller can continue with a degraded result.
    pub severity: ShibahamaErrorSeverity,
    /// Whether retrying unchanged input can reasonably succeed.
    pub retryable: bool,
    /// Detail safe to return from a host transport.
    pub detail: &'static str,
}

impl ShibahamaErrorSeverity {
    /// Stable machine-readable severity value.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Recoverable => "recoverable",
            Self::Fatal => "fatal",
        }
    }
}

impl ShibahamaErrorKind {
    /// Resolves a stable machine-readable code to its error category.
    #[must_use]
    pub fn from_code(code: &str) -> Option<Self> {
        match code {
            "SHIBA_STORAGE" => Some(Self::Storage),
            "SHIBA_RECALL" => Some(Self::Recall),
            "SHIBA_VECTOR" => Some(Self::Vector),
            "SHIBA_INVALID_REQUEST" => Some(Self::InvalidRequest),
            "SHIBA_UNAUTHORIZED" => Some(Self::AuthorizationDenied),
            "SHIBA_POLICY" => Some(Self::PolicyDenied),
            #[cfg(feature = "tokio")]
            "SHIBA_TASK" => Some(Self::Task),
            _ => None,
        }
    }

    /// Stable machine-readable code for this error category.
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::Storage => "SHIBA_STORAGE",
            Self::Recall => "SHIBA_RECALL",
            Self::Vector => "SHIBA_VECTOR",
            Self::InvalidRequest => "SHIBA_INVALID_REQUEST",
            Self::AuthorizationDenied => "SHIBA_UNAUTHORIZED",
            Self::PolicyDenied => "SHIBA_POLICY",
            #[cfg(feature = "tokio")]
            Self::Task => "SHIBA_TASK",
        }
    }

    /// Human-readable recovery guidance for this error category.
    #[must_use]
    pub const fn action(self) -> &'static str {
        match self {
            Self::Storage => {
                "verify the store path and durable state are accessible, then retry or restore from a snapshot"
            }
            Self::Recall => {
                "verify the query embedding, vector index, and store availability before retrying"
            }
            Self::Vector => {
                "verify embedding dimensionality and vector backend availability before retrying"
            }
            Self::InvalidRequest => "adjust the request and retry",
            Self::AuthorizationDenied => "request access from a configured maintainer",
            Self::PolicyDenied => "adjust the policy or request explicit approval",
            #[cfg(feature = "tokio")]
            Self::Task => "inspect the runtime for cancellation or panic before retrying",
        }
    }

    /// Detail safe to expose to host-language callers.
    #[must_use]
    pub const fn detail(self) -> &'static str {
        match self {
            Self::Storage => "storage operation failed",
            Self::Recall => "recall operation failed",
            Self::Vector => "vector index operation failed",
            Self::InvalidRequest => "invalid request",
            Self::AuthorizationDenied => "authorization denied",
            Self::PolicyDenied => "policy denied the requested operation",
            #[cfg(feature = "tokio")]
            Self::Task => "async task failed",
        }
    }

    /// Operational severity for this category.
    #[must_use]
    pub const fn severity(self) -> ShibahamaErrorSeverity {
        match self {
            Self::Recall => ShibahamaErrorSeverity::Recoverable,
            #[cfg(feature = "tokio")]
            Self::Task => ShibahamaErrorSeverity::Recoverable,
            Self::Storage
            | Self::Vector
            | Self::InvalidRequest
            | Self::AuthorizationDenied
            | Self::PolicyDenied => ShibahamaErrorSeverity::Fatal,
        }
    }

    /// Whether retrying unchanged input can reasonably succeed.
    #[must_use]
    pub const fn retryable(self) -> bool {
        match self {
            Self::Recall => true,
            #[cfg(feature = "tokio")]
            Self::Task => true,
            Self::Storage
            | Self::Vector
            | Self::InvalidRequest
            | Self::AuthorizationDenied
            | Self::PolicyDenied => false,
        }
    }
}

impl ShibahamaError {
    /// Stable high-level category for this error.
    #[must_use]
    pub const fn kind(&self) -> ShibahamaErrorKind {
        match self {
            Self::Storage(_) => ShibahamaErrorKind::Storage,
            Self::Recall(_) => ShibahamaErrorKind::Recall,
            Self::Vector(_) => ShibahamaErrorKind::Vector,
            Self::InvalidRequest(_) => ShibahamaErrorKind::InvalidRequest,
            Self::AuthorizationDenied => ShibahamaErrorKind::AuthorizationDenied,
            Self::PolicyDenied(_) => ShibahamaErrorKind::PolicyDenied,
            #[cfg(feature = "tokio")]
            Self::Task(_) => ShibahamaErrorKind::Task,
        }
    }

    /// Stable machine-readable code for this error.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        self.kind().code()
    }

    /// Human-readable recovery guidance for this error.
    #[must_use]
    pub const fn action(&self) -> &'static str {
        self.kind().action()
    }

    /// Operational severity for this error.
    #[must_use]
    pub const fn severity(&self) -> ShibahamaErrorSeverity {
        self.kind().severity()
    }

    /// Whether retrying unchanged input can reasonably succeed.
    #[must_use]
    pub const fn retryable(&self) -> bool {
        self.kind().retryable()
    }

    /// Stable transport-safe metadata without backend or caller content.
    #[must_use]
    pub const fn metadata(&self) -> ShibahamaErrorMetadata {
        let kind = self.kind();

        ShibahamaErrorMetadata {
            code: kind.code(),
            severity: kind.severity(),
            retryable: kind.retryable(),
            detail: kind.detail(),
        }
    }
}

impl ShibahamaErrorMetadata {
    /// Resolves transport-safe metadata from a stable core error code.
    #[must_use]
    pub fn for_code(code: &str) -> Option<Self> {
        let kind = ShibahamaErrorKind::from_code(code)?;

        Some(Self {
            code: kind.code(),
            severity: kind.severity(),
            retryable: kind.retryable(),
            detail: kind.detail(),
        })
    }
}

/// Sane-default configuration for a Shibahama engine.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct ShibahamaConfig {
    /// Whether callers must use an explicit [`ScopedShibahama`] context.
    pub scope_mode: ScopeMode,
    /// Transparent significance scoring and tier-promotion thresholds.
    pub significance: SignificanceConfig,
    /// Default recall ranking weights.
    pub recall_ranking: RecallRankingConfig,
    /// Default stale-load-bearing recall detection thresholds.
    pub recall_staleness: RecallStalenessConfig,
    /// Default near-duplicate suppression policy.
    pub recall_diversification: RecallDiversificationConfig,
    /// Default anomaly detection thresholds.
    pub anomaly: AnomalyConfig,
    /// Default reconstruction rate/cost budget.
    pub reconstruction_budget: ReconstructionBudgetConfig,
    /// Optional idle/background reconstruction planning.
    pub background_reconstruction: BackgroundReconstructionConfig,
    /// Offline/idle consolidation pass settings.
    pub consolidation: OfflineConsolidationConfig,
    /// Default tier residency budgets.
    pub tier_capacity: TierCapacityConfig,
    /// Default source-kind to credence mapping used for writes without explicit credence.
    pub ingest_credence: IngestCredencePolicy,
    /// Independent capture policy; manual capture is the default.
    pub capture_policy: CapturePolicy,
    /// Independent recall and context-assembly policy with conservative defaults.
    pub recall_policy: RecallPolicy,
    /// Policy for caller-requested forgetting/invalidation.
    pub forgetting: ForgettingConfig,
}

/// Recall output with the policy decision and consumed context budget.
#[derive(Clone, Debug, PartialEq)]
pub struct PolicyRecallResult {
    /// Ranked candidates after policy limits were enforced.
    pub candidates: Vec<RecallCandidate>,
    /// Deterministic policy decision that constrained the request.
    pub decision: RecallPolicyDecision,
    /// Approximate whitespace tokens in returned candidate content.
    pub context_tokens_used: usize,
}

/// Scope-context requirement for the core engine.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum ScopeMode {
    /// Preserve legacy embedded behavior for one local store.
    #[default]
    LocalSingleStore,
    /// Reject unscoped public operations.
    RequireExplicit,
}

/// Host authorization input for a scope-crossing operation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ScopeAuthorizationRequest<'a> {
    /// Authenticated principal requesting the operation.
    pub principal: &'a str,
    /// Repository-local source scope.
    pub source_scope: &'a MemoryScope,
    /// Requested team target scope.
    pub target_scope: &'a MemoryScope,
    /// Requested operation.
    pub action: ScopeAuthorizationAction,
}

/// Host policy decision for a scope-crossing operation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScopeAuthorizationDecision {
    /// The host allows the requested operation.
    Allow,
    /// The host denies the requested operation.
    Deny,
}

impl ScopeAuthorizationDecision {
    /// Returns whether the requested operation is authorized.
    #[must_use]
    pub const fn is_allowed(self) -> bool {
        matches!(self, Self::Allow)
    }
}

/// Host-provided authorization policy for scope-crossing operations.
pub trait ScopeAuthorizationPolicy: Send + Sync {
    /// Evaluates a scope-crossing request without receiving memory content or identifiers.
    fn authorize(&self, request: ScopeAuthorizationRequest<'_>) -> ScopeAuthorizationDecision;
}

/// Fail-closed default policy for embedded engines.
#[derive(Clone, Copy, Debug, Default)]
pub struct DenyScopePromotionPolicy;

impl ScopeAuthorizationPolicy for DenyScopePromotionPolicy {
    fn authorize(&self, _: ScopeAuthorizationRequest<'_>) -> ScopeAuthorizationDecision {
        ScopeAuthorizationDecision::Deny
    }
}

/// Explicit local/test policy that allows repository-to-team promotion.
#[derive(Clone, Copy, Debug, Default)]
pub struct AllowScopePromotionPolicy;

impl ScopeAuthorizationPolicy for AllowScopePromotionPolicy {
    fn authorize(&self, request: ScopeAuthorizationRequest<'_>) -> ScopeAuthorizationDecision {
        match request.action {
            ScopeAuthorizationAction::PromoteToTeam => ScopeAuthorizationDecision::Allow,
        }
    }
}

impl ShibahamaConfig {
    /// Resolves global settings with optional team, repository, and session policy layers.
    ///
    /// Returned source layers are redacted to layer kinds and contain no scope identifiers.
    #[must_use]
    pub fn effective_policy(self, layers: &PolicyLayerSet) -> EffectivePolicy {
        resolve_policy_inheritance(self.capture_policy, self.recall_policy, layers)
    }

    /// Builds a recall request populated with this config's recall defaults.
    #[must_use]
    pub fn recall_request(
        self,
        query_vector: &[f32],
        top_k: usize,
        now: OffsetDateTime,
    ) -> RecallRequest<'_> {
        RecallRequest::new(query_vector, top_k, now)
            .with_ranking(self.recall_ranking)
            .with_significance(self.significance)
            .with_staleness(self.recall_staleness)
            .with_diversification(self.recall_diversification)
    }
}

/// How the engine handles caller-requested forgetting.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ForgettingConfig {
    /// Forgetting behavior used by `Shibahama::invalidate`.
    pub mode: ForgettingMode,
}

/// Engine behavior for `invalidate` requests.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum ForgettingMode {
    /// Close `valid_to` and remove the memory's vector from default current recall.
    #[default]
    SoftInvalidate,
    /// Keep the memory valid and append a durable flag for explicit re-verification.
    FlagForReverification,
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

/// Status for one explicit reconstruction trigger.
#[derive(Clone, Debug, PartialEq)]
pub enum ExplicitReconstructionStatus {
    /// Trigger was blocked by the reconstruction budget.
    Deferred(ReconstructionBudgetDenial),
    /// Gate allowed the trigger, but the referenced memory no longer exists.
    MissingOriginal,
    /// Revalidation source produced no replacement observation.
    NoObservation,
    /// Replacement observation exists but remains quarantined pending corroboration.
    Quarantined,
    /// Corroborated replacement invalidated the superseded memory and was written.
    Applied,
}

/// Result for one trigger processed by explicit reconstruction.
#[derive(Clone, Debug, PartialEq)]
pub struct ExplicitReconstructionOutcome {
    /// Trigger considered by the loop.
    pub trigger: ReconstructionTrigger,
    /// Action planned for external revalidation, when the trigger was processed.
    pub action: Option<RevalidationAction>,
    /// Quarantined proposal, when a revalidation source produced a replacement observation.
    pub proposal: Option<QuarantinedProposal>,
    /// Corroboration decision for the proposal.
    pub corroboration: Option<CorroborationDecision>,
    /// Promoted replacement written to storage, when applied.
    pub replacement: Option<MemoryItem>,
    /// Event records produced by invalidate-not-delete plus replacement write.
    pub records: Option<ReconstructionReplacementRecord>,
    /// Final status.
    pub status: ExplicitReconstructionStatus,
}

/// Applied result for one offline consolidation decision.
#[derive(Clone, Debug, PartialEq)]
pub struct ConsolidationOutcome {
    /// Planned decision that was applied.
    pub decision: PlannedConsolidationDecision,
    /// Durable event records written while applying the decision.
    pub records: ConsolidationDecisionRecord,
}

/// Result of one offline consolidation pass.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConsolidationPassReport {
    /// Stable pass id shared by emitted consolidation decision events.
    pub pass_id: String,
    /// Applied decisions. Empty means the store was already consolidated for this state.
    pub applied: Vec<ConsolidationOutcome>,
}

/// Caller metadata attached to a human-in-the-loop signal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HumanSignalRequest {
    /// Human or process actor supplying the signal.
    pub actor: String,
    /// Human-readable reason stored in the append-only audit event.
    pub reason: String,
    /// Time the caller supplied the signal.
    pub timestamp: OffsetDateTime,
}

impl HumanSignalRequest {
    /// Creates an explicit human signal request.
    #[must_use]
    pub fn new(
        actor: impl Into<String>,
        reason: impl Into<String>,
        timestamp: OffsetDateTime,
    ) -> Self {
        Self {
            actor: actor.into(),
            reason: reason.into(),
            timestamp,
        }
    }

    fn api_default(reason: impl Into<String>) -> Self {
        Self::new("api", reason, OffsetDateTime::now_utc())
    }
}

/// Result for a direct human signal that mutates credence or floor state.
#[derive(Clone, Debug, PartialEq)]
pub struct HumanSignalOutcome {
    /// Signal payload stored in the append-only log.
    pub signal: HumanSignal,
    /// Durable event records emitted by the call.
    pub records: HumanSignalRecord,
}

/// Result for a human correction routed through quarantine and corroboration.
#[derive(Clone, Debug, PartialEq)]
pub struct HumanCorrectionOutcome {
    /// Low-credence quarantined proposal before corroboration.
    pub proposal: QuarantinedProposal,
    /// Corroboration decision that allowed the proposal to replace the prior version.
    pub corroboration: CorroborationDecision,
    /// Promoted replacement that was durably written.
    pub replacement: MemoryItem,
    /// Invalidate-not-delete reconstruction records.
    pub records: ReconstructionReplacementRecord,
    /// Signal payload stored in the append-only log.
    pub signal: HumanSignal,
    /// Durable human signal event.
    pub signal_record: EventRecord,
}

impl ExplicitReconstructionOutcome {
    fn deferred(trigger: ReconstructionTrigger, reason: ReconstructionBudgetDenial) -> Self {
        Self {
            trigger,
            action: None,
            proposal: None,
            corroboration: None,
            replacement: None,
            records: None,
            status: ExplicitReconstructionStatus::Deferred(reason),
        }
    }

    fn missing_original(trigger: ReconstructionTrigger) -> Self {
        Self {
            trigger,
            action: None,
            proposal: None,
            corroboration: None,
            replacement: None,
            records: None,
            status: ExplicitReconstructionStatus::MissingOriginal,
        }
    }

    fn no_observation(trigger: ReconstructionTrigger, action: RevalidationAction) -> Self {
        Self {
            trigger,
            action: Some(action),
            proposal: None,
            corroboration: None,
            replacement: None,
            records: None,
            status: ExplicitReconstructionStatus::NoObservation,
        }
    }

    fn quarantined(
        trigger: ReconstructionTrigger,
        action: RevalidationAction,
        proposal: QuarantinedProposal,
        corroboration: CorroborationDecision,
    ) -> Self {
        Self {
            trigger,
            action: Some(action),
            proposal: Some(proposal),
            corroboration: Some(corroboration),
            replacement: None,
            records: None,
            status: ExplicitReconstructionStatus::Quarantined,
        }
    }

    fn applied(
        trigger: ReconstructionTrigger,
        action: RevalidationAction,
        proposal: QuarantinedProposal,
        corroboration: CorroborationDecision,
        replacement: MemoryItem,
        records: ReconstructionReplacementRecord,
    ) -> Self {
        Self {
            trigger,
            action: Some(action),
            proposal: Some(proposal),
            corroboration: Some(corroboration),
            replacement: Some(replacement),
            records: Some(records),
            status: ExplicitReconstructionStatus::Applied,
        }
    }
}

/// Owned embedding metadata for async write calls.
#[cfg(feature = "tokio")]
#[derive(Clone, Debug, PartialEq)]
pub struct AsyncWriteEmbedding {
    /// Embedding vector.
    pub vector: Vec<f32>,
    /// Logical vector index name.
    pub index_name: String,
    /// Embedding model name.
    pub model: String,
    /// Embedding model version.
    pub model_version: String,
}

#[cfg(feature = "tokio")]
impl AsyncWriteEmbedding {
    /// Creates owned embedding metadata for async writes.
    #[must_use]
    pub fn new(
        vector: impl Into<Vec<f32>>,
        index_name: impl Into<String>,
        model: impl Into<String>,
        model_version: impl Into<String>,
    ) -> Self {
        Self {
            vector: vector.into(),
            index_name: index_name.into(),
            model: model.into(),
            model_version: model_version.into(),
        }
    }

    fn as_write_embedding(&self) -> WriteEmbedding<'_> {
        WriteEmbedding {
            vector: &self.vector,
            index_name: &self.index_name,
            model: &self.model,
            model_version: &self.model_version,
        }
    }
}

#[cfg(feature = "tokio")]
impl From<WriteEmbedding<'_>> for AsyncWriteEmbedding {
    fn from(value: WriteEmbedding<'_>) -> Self {
        Self::new(
            value.vector.to_vec(),
            value.index_name,
            value.model,
            value.model_version,
        )
    }
}

/// Owned recall request for async task boundaries.
#[cfg(feature = "tokio")]
#[derive(Clone, Debug, PartialEq)]
pub struct AsyncRecallRequest {
    /// Query embedding supplied by the caller's embedding model.
    pub query_vector: Vec<f32>,
    /// Optional raw query/context text to hash into surfaced access events.
    pub raw_query_context: Option<String>,
    /// Maximum number of vector candidates to inspect.
    pub top_k: usize,
    /// Valid-time instant used for default current-fact filtering.
    pub now: OffsetDateTime,
    /// Whether recall may return cold-tier memories.
    pub include_cold: bool,
    /// Whether recall may return instruction/directive memories.
    pub include_instructions: bool,
    /// Ranking weights applied to retrieved candidates.
    pub ranking: RecallRankingConfig,
    /// Significance policy used for lazy pre-rank refresh and surfaced-access updates.
    pub significance: SignificanceConfig,
    /// Policy for flagging load-bearing but possibly stale memories.
    pub staleness: RecallStalenessConfig,
    /// Policy for suppressing near-duplicate results.
    pub diversification: RecallDiversificationConfig,
    /// Optional maximum approximate context tokens to return.
    pub max_context_tokens: Option<usize>,
}

#[cfg(feature = "tokio")]
impl AsyncRecallRequest {
    /// Creates an owned async recall request for a query vector.
    #[must_use]
    pub fn new(query_vector: impl Into<Vec<f32>>, top_k: usize, now: OffsetDateTime) -> Self {
        let request = RecallRequest::new(&[], top_k, now);

        Self {
            query_vector: query_vector.into(),
            raw_query_context: None,
            top_k,
            now,
            include_cold: request.include_cold,
            include_instructions: request.include_instructions,
            ranking: request.ranking,
            significance: request.significance,
            staleness: request.staleness,
            diversification: request.diversification,
            max_context_tokens: request.max_context_tokens,
        }
    }

    /// Copies a borrowed sync recall request into an owned async request.
    ///
    /// # Errors
    ///
    /// Returns an error when the borrowed request uses callback-style sync hooks, which cannot
    /// safely cross the async blocking-task boundary.
    pub fn try_from_recall_request(request: &RecallRequest<'_>) -> Result<Self, ShibahamaError> {
        if request.related_memory_provider.is_some() {
            return Err(ShibahamaError::InvalidRequest(
                "async recall requests must own their data; related-memory providers are only supported by the sync API".to_owned(),
            ));
        }

        if request.sanitizing_gateway.is_some() {
            return Err(ShibahamaError::InvalidRequest(
                "async recall requests must own their data; sanitizing gateways are only supported by the sync API".to_owned(),
            ));
        }

        Ok(Self {
            query_vector: request.query_vector.to_vec(),
            raw_query_context: request.raw_query_context.map(str::to_owned),
            top_k: request.top_k,
            now: request.now,
            include_cold: request.include_cold,
            include_instructions: request.include_instructions,
            ranking: request.ranking,
            significance: request.significance,
            staleness: request.staleness,
            diversification: request.diversification,
            max_context_tokens: request.max_context_tokens,
        })
    }

    /// Adds raw query context that will be hashed before storage.
    #[must_use]
    pub fn with_raw_query_context(mut self, raw_query_context: impl Into<String>) -> Self {
        self.raw_query_context = Some(raw_query_context.into());
        self
    }

    /// Allows cold-tier memories to be returned.
    #[must_use]
    pub const fn include_cold(mut self) -> Self {
        self.include_cold = true;
        self
    }

    /// Allows instruction/directive memories to be returned.
    #[must_use]
    pub const fn include_instructions(mut self) -> Self {
        self.include_instructions = true;
        self
    }

    /// Overrides ranking weights for this request.
    #[must_use]
    pub const fn with_ranking(mut self, ranking: RecallRankingConfig) -> Self {
        self.ranking = ranking;
        self
    }

    /// Overrides the significance policy used by this request.
    #[must_use]
    pub const fn with_significance(mut self, significance: SignificanceConfig) -> Self {
        self.significance = significance;
        self
    }

    /// Overrides stale-load-bearing detection policy for this request.
    #[must_use]
    pub const fn with_staleness(mut self, staleness: RecallStalenessConfig) -> Self {
        self.staleness = staleness;
        self
    }

    /// Overrides result diversification policy for this request.
    #[must_use]
    pub const fn with_diversification(
        mut self,
        diversification: RecallDiversificationConfig,
    ) -> Self {
        self.diversification = diversification;
        self
    }

    /// Limits the approximate number of whitespace tokens returned as recall context.
    #[must_use]
    pub const fn with_max_context_tokens(mut self, max_context_tokens: usize) -> Self {
        self.max_context_tokens = Some(max_context_tokens);
        self
    }

    fn as_recall_request(&self) -> RecallRequest<'_> {
        let mut request = RecallRequest::new(&self.query_vector, self.top_k, self.now);
        request.raw_query_context = self.raw_query_context.as_deref();
        request.include_cold = self.include_cold;
        request.include_instructions = self.include_instructions;
        request.ranking = self.ranking;
        request.significance = self.significance;
        request.staleness = self.staleness;
        request.diversification = self.diversification;
        request.max_context_tokens = self.max_context_tokens;

        request
    }
}

/// Owning iterator over ranked recall candidates.
#[derive(Clone, Debug)]
pub struct RecallStream {
    candidates: std::vec::IntoIter<RecallCandidate>,
}

impl RecallStream {
    fn new(candidates: Vec<RecallCandidate>) -> Self {
        Self {
            candidates: candidates.into_iter(),
        }
    }

    /// Number of candidates still available without advancing the stream.
    #[must_use]
    pub fn remaining(&self) -> usize {
        self.candidates.len()
    }
}

impl Iterator for RecallStream {
    type Item = RecallCandidate;

    fn next(&mut self) -> Option<Self::Item> {
        self.candidates.next()
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        self.candidates.size_hint()
    }
}

impl ExactSizeIterator for RecallStream {
    fn len(&self) -> usize {
        self.candidates.len()
    }
}

impl FusedIterator for RecallStream {}

/// Structured explanation for why a memory currently has its state.
#[derive(Clone, Debug, PartialEq)]
pub struct WhyTrace {
    /// Current materialized memory item.
    pub item: MemoryItem,
    /// Deterministic significance score breakdown at `currency.as_of`.
    pub significance: SignificanceBreakdown,
    /// Current provenance copied to the trace boundary.
    pub provenance: Provenance,
    /// Current tier, credence floor, and tier/credence audit entries.
    pub tier: WhyTierTrace,
    /// Validity and ingestion state at the explanation instant.
    pub currency: WhyCurrencyTrace,
    /// Complete credence/tier audit trail for this memory.
    pub audit_trail: Vec<MemoryAuditEntry>,
}

/// Tier and credence portion of a `why` explanation.
#[derive(Clone, Debug, PartialEq)]
pub struct WhyTierTrace {
    /// Current accessibility tier.
    pub current: Tier,
    /// Current credence tier.
    pub credence: CredenceTier,
    /// Lowest tier allowed by the memory's credence.
    pub credence_floor: Tier,
    /// Audit entries that changed this memory's tier or credence.
    pub audit: Vec<MemoryAuditEntry>,
}

/// Currency portion of a `why` explanation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WhyCurrencyTrace {
    /// Instant the currency state was evaluated against.
    pub as_of: OffsetDateTime,
    /// Whether the memory is current, not-yet-valid, or invalidated at `as_of`.
    pub state: RecallCandidateCurrency,
    /// Valid-time start for this memory.
    pub valid_from: OffsetDateTime,
    /// Valid-time end, if the memory was superseded or invalidated.
    pub valid_to: Option<OffsetDateTime>,
    /// Time Shibahama ingested the observation.
    pub ingested_at: OffsetDateTime,
}

impl WhyCurrencyTrace {
    fn from_item(item: &MemoryItem, as_of: OffsetDateTime) -> Self {
        let state = if as_of < item.timestamps.valid_from {
            RecallCandidateCurrency::NotYetValid
        } else if item
            .timestamps
            .valid_to
            .is_some_and(|valid_to| as_of >= valid_to)
        {
            RecallCandidateCurrency::Invalidated
        } else {
            RecallCandidateCurrency::Current
        };

        Self {
            as_of,
            state,
            valid_from: item.timestamps.valid_from,
            valid_to: item.timestamps.valid_to,
            ingested_at: item.timestamps.ingested_at,
        }
    }
}

/// In-process Shibahama engine over a store and vector index.
pub struct Shibahama<V> {
    store: RedbMemoryStore,
    vector_index: V,
    config: ShibahamaConfig,
    scope_authorization: Box<dyn ScopeAuthorizationPolicy>,
}

/// Explicit repository/team scope context for core memory operations.
pub struct ScopedShibahama<'a, V> {
    engine: &'a mut Shibahama<V>,
    scope: MemoryScope,
    previous_scope_mode: ScopeMode,
}

impl<V: VectorIndex> Shibahama<V> {
    /// Opens a Shibahama store with a caller-supplied vector index.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened.
    pub fn open(path: impl AsRef<Path>, vector_index: V) -> Result<Self, ShibahamaError> {
        Self::open_with_config(path, vector_index, ShibahamaConfig::default())
    }

    /// Opens an engine only after strict runtime configuration validation succeeds.
    ///
    /// # Errors
    ///
    /// Returns an error before opening storage when configuration is invalid or incompatible.
    pub fn open_from_runtime_config(
        runtime_config: &crate::config::RuntimeConfig,
        vector_index: V,
    ) -> Result<Self, ShibahamaError> {
        runtime_config.validate().map_err(|_| {
            ShibahamaError::InvalidRequest("runtime configuration is invalid".to_owned())
        })?;
        if runtime_config.provider.dimensions != vector_index.dimensions() {
            return Err(ShibahamaError::InvalidRequest(
                "runtime provider dimensions do not match the vector index".to_owned(),
            ));
        }
        if runtime_config.storage.encryption == crate::config::StorageEncryptionMode::Required {
            return Err(ShibahamaError::InvalidRequest(
                "runtime configuration requires an encrypted store opener".to_owned(),
            ));
        }

        Self::open_with_config(
            &runtime_config.storage.path,
            vector_index,
            runtime_config.engine_config(),
        )
    }

    /// Opens a Shibahama store with an explicit engine config.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened.
    pub fn open_with_config(
        path: impl AsRef<Path>,
        vector_index: V,
        config: ShibahamaConfig,
    ) -> Result<Self, ShibahamaError> {
        let mut engine = Self {
            store: RedbMemoryStore::open(path)?,
            vector_index,
            config,
            scope_authorization: Box::new(DenyScopePromotionPolicy),
        };

        engine.hydrate_vector_index()?;

        Ok(engine)
    }

    /// Returns the underlying store for lower-level operations.
    #[must_use]
    pub const fn store(&self) -> &RedbMemoryStore {
        &self.store
    }

    /// Returns the active vector index.
    #[must_use]
    pub const fn vector_index(&self) -> &V {
        &self.vector_index
    }

    /// Returns this engine's active config.
    #[must_use]
    pub const fn config(&self) -> ShibahamaConfig {
        self.config
    }

    /// Resolves this engine's global policy with caller-supplied scoped layers.
    #[must_use]
    pub fn effective_policy(&self, layers: &PolicyLayerSet) -> EffectivePolicy {
        self.config.effective_policy(layers)
    }

    /// Simulates a capture-policy decision without writing memory, events, or provider requests.
    #[must_use]
    pub fn simulate_capture_policy(
        &self,
        source_kind: SourceKind,
        scope: &MemoryScope,
        request: CapturePolicyRequest,
    ) -> CapturePolicySimulation {
        CapturePolicySimulation {
            decision: self
                .config
                .capture_policy
                .evaluate(request, source_kind, scope),
        }
    }

    /// Simulates a recall-policy decision without reading memory or writing access events.
    #[must_use]
    pub fn simulate_recall_policy(
        &self,
        requested_candidates: usize,
        requested_context_tokens: Option<usize>,
        include_cold: bool,
        include_instructions: bool,
        scope: Option<&MemoryScope>,
    ) -> RecallPolicySimulation {
        RecallPolicySimulation {
            decision: self.config.recall_policy.decide(
                requested_candidates,
                requested_context_tokens,
                include_cold,
                include_instructions,
            ),
            scope_allowed: scope.is_none_or(|scope| self.config.recall_policy.scopes.allows(scope)),
        }
    }

    /// Replaces this engine's active config.
    pub fn set_config(&mut self, config: ShibahamaConfig) {
        self.config = config;
    }

    /// Replaces the host policy for repository-to-team promotion.
    pub fn set_scope_authorization_policy(
        &mut self,
        policy: impl ScopeAuthorizationPolicy + 'static,
    ) {
        self.scope_authorization = Box::new(policy);
    }

    /// Enters an explicit repository/team scope for fail-closed core operations.
    ///
    /// The unscoped API remains available only for local single-store embedding compatibility.
    ///
    /// # Errors
    ///
    /// Returns an error when the supplied scope is internally inconsistent.
    pub fn scoped(&mut self, scope: MemoryScope) -> Result<ScopedShibahama<'_, V>, ShibahamaError> {
        scope
            .validate()
            .map_err(|error| ShibahamaError::InvalidRequest(error.to_string()))?;

        let previous_scope_mode = self.config.scope_mode;
        self.config.scope_mode = ScopeMode::LocalSingleStore;

        Ok(ScopedShibahama {
            engine: self,
            scope,
            previous_scope_mode,
        })
    }

    fn hydrate_vector_index(&mut self) -> Result<(), ShibahamaError> {
        for embedding in self.store.stored_embeddings()? {
            self.vector_index
                .add(embedding.memory_id, &embedding.vector)?;
        }

        Ok(())
    }

    fn require_scope_context(&self) -> Result<(), ShibahamaError> {
        if self.config.scope_mode == ScopeMode::RequireExplicit {
            return Err(ShibahamaError::InvalidRequest(
                "an explicit scope context is required; call scoped(scope)".to_owned(),
            ));
        }

        Ok(())
    }

    /// Builds a recall request from this engine's recall defaults.
    #[must_use]
    pub fn recall_request<'a>(
        &self,
        query_vector: &'a [f32],
        top_k: usize,
        now: OffsetDateTime,
    ) -> RecallRequest<'a> {
        self.config.recall_request(query_vector, top_k, now)
    }

    /// Writes a memory event without adding an embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when the write cannot be persisted.
    pub fn write(&self, event: MemoryWriteEvent) -> Result<MemoryItem, ShibahamaError> {
        self.require_scope_context()?;
        let audit = self.prepare_capture_policy(&event, CapturePolicyRequest::manual())?;
        let (_, item) = self
            .store
            .write_event_with_policy(event, self.config.ingest_credence)?;
        self.store.record_policy_decision(audit)?;

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
        self.require_scope_context()?;
        let audit = self.prepare_capture_policy(&event, CapturePolicyRequest::manual())?;
        let mut item = event.into_item_with_policy(self.config.ingest_credence);

        self.store.write_embedded(
            &mut item,
            &mut self.vector_index,
            embedding.vector,
            embedding.index_name,
            embedding.model,
            embedding.model_version,
        )?;
        self.store.record_policy_decision(audit)?;

        Ok(item)
    }

    /// Embeds and writes memory through a provider after metadata and dimension validation.
    ///
    /// # Errors
    ///
    /// Returns an error before persistence when provider metadata/output is incompatible.
    pub fn write_with_provider(
        &mut self,
        event: MemoryWriteEvent,
        provider: &dyn EmbeddingProvider,
        index_name: &str,
    ) -> Result<MemoryItem, ShibahamaError> {
        let metadata = provider.metadata();
        if metadata.dimensions != self.vector_index.dimensions() {
            return Err(ShibahamaError::InvalidRequest(
                "embedding provider dimensions do not match vector index".to_owned(),
            ));
        }
        let vector = provider
            .embed(&event.content, EmbeddingPurpose::Document)
            .map_err(|error| ShibahamaError::InvalidRequest(error.detail))?;
        validate_embedding(&metadata, EmbeddingPurpose::Document, &vector)
            .map_err(|error| ShibahamaError::InvalidRequest(error.detail))?;

        self.write_with_embedding(
            event,
            WriteEmbedding {
                vector: &vector,
                index_name,
                model: &metadata.model,
                model_version: &metadata.version,
            },
        )
    }

    /// Writes a memory event after evaluating caller-supplied capture policy metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when policy denies the request or the write cannot be persisted.
    pub fn write_with_capture_policy(
        &self,
        event: MemoryWriteEvent,
        request: CapturePolicyRequest,
    ) -> Result<MemoryItem, ShibahamaError> {
        self.require_scope_context()?;
        let audit = self.prepare_capture_policy(&event, request)?;
        let (_, item) = self
            .store
            .write_event_with_policy(event, self.config.ingest_credence)?;
        self.store.record_policy_decision(audit)?;

        Ok(item)
    }

    /// Soft-invalidates a memory at `valid_to` and removes its stored embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when invalidation cannot be persisted or the vector index cannot be
    /// updated.
    pub fn invalidate(
        &mut self,
        id: MemoryId,
        valid_to: OffsetDateTime,
    ) -> Result<bool, ShibahamaError> {
        self.require_scope_context()?;
        match self.config.forgetting.mode {
            ForgettingMode::SoftInvalidate => Ok(self
                .store
                .soft_invalidate_with_vector(id, valid_to, &mut self.vector_index)?
                .is_some()),
            ForgettingMode::FlagForReverification => Ok(self
                .store
                .flag_for_reverification(id, valid_to, "forgetting-disabled".to_owned())?
                .is_some()),
        }
    }

    /// Copies an approved repository-local memory into one team scope without mutating its source.
    ///
    /// # Errors
    ///
    /// Returns an error when scope requirements, vector indexing, or durable promotion fail.
    pub fn promote_to_team(
        &mut self,
        source_id: MemoryId,
        team: ScopeId,
        actor: impl Into<String>,
        rationale: impl Into<String>,
        promoted_at: OffsetDateTime,
    ) -> Result<Option<ScopePromotionRecord>, ShibahamaError> {
        self.require_scope_context()?;
        let Some(source) = self.store.get(source_id)? else {
            return Ok(None);
        };
        let target_scope = MemoryScope::team(source.scope.repository.clone(), team);
        let actor = actor.into();
        let authorization = ScopeAuthorizationRequest {
            principal: &actor,
            source_scope: &source.scope,
            target_scope: &target_scope,
            action: ScopeAuthorizationAction::PromoteToTeam,
        };
        if !self
            .scope_authorization
            .authorize(authorization)
            .is_allowed()
        {
            self.store.record_scope_authorization_denial(
                actor,
                &source.scope,
                &target_scope,
                ScopeAuthorizationAction::PromoteToTeam,
                promoted_at,
            )?;
            return Err(ShibahamaError::AuthorizationDenied);
        }
        let promoted_id = MemoryId::new_v7();
        let vector = self
            .store
            .stored_embeddings()?
            .into_iter()
            .find(|embedding| embedding.memory_id == source_id)
            .map(|embedding| embedding.vector);
        if let Some(vector) = vector.as_deref() {
            self.vector_index.add(promoted_id, vector)?;
        }
        let result = self.store.promote_memory_scope(
            source_id,
            promoted_id,
            target_scope,
            actor,
            rationale,
            promoted_at,
        );
        if result.is_err() && vector.is_some() {
            let _ = self.vector_index.delete_by_id(promoted_id);
        }

        Ok(result?)
    }

    /// Returns all current materialized memory rows.
    ///
    /// # Errors
    ///
    /// Returns an error when current item state cannot be read.
    pub fn memory_items(&self) -> Result<Vec<MemoryItem>, ShibahamaError> {
        self.require_scope_context()?;
        Ok(self.store.memory_items()?)
    }

    /// Returns all durable event-log records in sequence order.
    ///
    /// # Errors
    ///
    /// Returns an error when event-log records cannot be read.
    pub fn event_records(&self) -> Result<Vec<EventRecord>, ShibahamaError> {
        self.require_scope_context()?;
        Ok(self.store.events()?)
    }

    /// Writes a local full-store snapshot when local single-store mode is enabled.
    ///
    /// # Errors
    ///
    /// Returns an error when explicit scope mode is enabled or snapshot export fails.
    pub fn snapshot(&self, path: impl AsRef<Path>) -> Result<(), ShibahamaError> {
        self.require_scope_context()?;
        Ok(self.store.snapshot(path)?)
    }

    /// Evaluates offline learned-policy candidates against current memory state and event logs.
    ///
    /// The evaluator is read-only: it does not train a model, mutate memory state, or apply any
    /// candidate action.
    ///
    /// # Errors
    ///
    /// Returns an error when current item state or event-log records cannot be read, or when the
    /// policy action summary list is inconsistent with candidate actions.
    pub fn evaluate_offline_policy(
        &self,
        decisions: &[OfflinePolicyDecision],
        config: OfflinePolicyEvaluationConfig,
    ) -> Result<OfflinePolicyEvaluationReport, ShibahamaError> {
        let memories = self.store.memory_items()?;
        let events = self.store.events()?;

        Ok(evaluate_offline_policy(
            decisions, &memories, &events, config,
        )?)
    }

    /// Plans a disabled-by-default Stage 2 contextual-bandit shadow experiment.
    ///
    /// The report is read-only and never mutates runtime significance configuration.
    #[must_use]
    pub fn plan_contextual_bandit_experiment(
        &self,
        stage1_report: &OfflinePolicyEvaluationReport,
        significance_config: SignificanceConfig,
        config: ContextualBanditExperimentConfig,
    ) -> ContextualBanditExperimentReport {
        plan_contextual_bandit_experiment(stage1_report, significance_config, config)
    }

    /// Assesses whether Stage 3 policy-model training research is ready to begin.
    ///
    /// This is a readiness gate only and never authorizes runtime learned-policy deployment.
    #[must_use]
    pub fn assess_stage3_training_readiness(
        &self,
        stage2_report: &ContextualBanditExperimentReport,
        config: &Stage3TrainingReadinessConfig,
    ) -> Stage3TrainingReadinessReport {
        assess_stage3_training_readiness(stage2_report, config)
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
        self.require_scope_context()?;
        let (request, decision) = self.policy_recall_request(request)?;
        let candidates = recall(&self.store, &self.vector_index, &request)?;
        self.record_recall_policy(&decision, &request, &candidates)?;

        Ok(candidates)
    }

    /// Recalls candidates and returns the policy decision and context-budget use.
    ///
    /// # Errors
    ///
    /// Returns an error when scope policy, vector search, storage reads, or access recording fail.
    pub fn recall_with_policy_report(
        &self,
        request: &RecallRequest<'_>,
    ) -> Result<PolicyRecallResult, ShibahamaError> {
        self.require_scope_context()?;
        let (request, decision) = self.policy_recall_request(request)?;
        let candidates = recall(&self.store, &self.vector_index, &request)?;
        let context_tokens_used = candidates
            .iter()
            .map(|candidate| candidate.item.content.split_whitespace().count())
            .sum();
        self.record_recall_policy(&decision, &request, &candidates)?;

        Ok(PolicyRecallResult {
            candidates,
            decision,
            context_tokens_used,
        })
    }

    /// Embeds text through a provider and recalls using the same policy path as supplied vectors.
    ///
    /// # Errors
    ///
    /// Returns an error before retrieval when provider metadata/output is incompatible.
    pub fn recall_text_with_provider(
        &self,
        query: &str,
        top_k: usize,
        now: OffsetDateTime,
        provider: &dyn EmbeddingProvider,
    ) -> Result<Vec<RecallCandidate>, ShibahamaError> {
        let metadata = provider.metadata();
        if metadata.dimensions != self.vector_index.dimensions() {
            return Err(ShibahamaError::InvalidRequest(
                "embedding provider dimensions do not match vector index".to_owned(),
            ));
        }
        let vector = provider
            .embed(query, EmbeddingPurpose::Query)
            .map_err(|error| ShibahamaError::InvalidRequest(error.detail))?;
        validate_embedding(&metadata, EmbeddingPurpose::Query, &vector)
            .map_err(|error| ShibahamaError::InvalidRequest(error.detail))?;
        let request = self.recall_request(&vector, top_k, now);

        self.recall(&request)
    }

    /// Recalls usable candidates while reporting unavailable optional stages.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search or initial candidate materialization cannot complete.
    pub fn recall_with_degradation(
        &self,
        request: &RecallRequest<'_>,
    ) -> Result<DegradedRecallResult, ShibahamaError> {
        self.require_scope_context()?;
        let (request, decision) = self.policy_recall_request(request)?;
        let result = recall_with_degradation(&self.store, &self.vector_index, &request)?;
        self.record_recall_policy(&decision, &request, &result.candidates)?;

        Ok(result)
    }

    fn policy_recall_request<'request>(
        &self,
        request: &RecallRequest<'request>,
    ) -> Result<(RecallRequest<'request>, RecallPolicyDecision), ShibahamaError> {
        let simulation = self.simulate_recall_policy(
            request.top_k,
            request.max_context_tokens,
            request.include_cold,
            request.include_instructions,
            request.scope,
        );
        if !simulation.scope_allowed {
            self.store
                .record_policy_decision(simulation.decision.audit_record(
                    request.scope,
                    PolicyAuditDisposition::Denied,
                    None,
                ))?;
            return Err(ShibahamaError::AuthorizationDenied);
        }
        let decision = simulation.decision;
        let mut effective = *request;
        effective.top_k = decision.effective_candidates;
        effective.max_context_tokens = Some(decision.effective_context_tokens);
        effective.include_cold = decision.include_cold;
        effective.include_instructions = decision.include_instructions;
        effective.scope_policy = decision.allowed_scopes;
        if effective.significance == SignificanceConfig::default() {
            effective.significance = self.config.significance;
        }

        Ok((effective, decision))
    }

    fn record_recall_policy(
        &self,
        decision: &RecallPolicyDecision,
        request: &RecallRequest<'_>,
        candidates: &[RecallCandidate],
    ) -> Result<(), ShibahamaError> {
        let context_tokens_used = candidates
            .iter()
            .map(|candidate| candidate.item.content.split_whitespace().count())
            .sum();
        self.store.record_policy_decision(decision.audit_record(
            request.scope,
            PolicyAuditDisposition::Allowed,
            Some(context_tokens_used),
        ))?;

        Ok(())
    }

    fn prepare_capture_policy(
        &self,
        event: &MemoryWriteEvent,
        request: CapturePolicyRequest,
    ) -> Result<PolicyAuditRecord, ShibahamaError> {
        let decision = self
            .simulate_capture_policy(event.provenance.source_kind, &event.scope, request)
            .decision;
        let audit = decision.audit_record(request, event.provenance.source_kind, &event.scope);
        if let Err(error) = decision.require_allowed() {
            self.store.record_policy_decision(audit)?;
            return Err(error.into());
        }

        Ok(audit)
    }

    /// Recalls current fact memories and returns an owning iterator over ranked candidates.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, or access recording fail.
    pub fn stream_recall(
        &self,
        request: &RecallRequest<'_>,
    ) -> Result<RecallStream, ShibahamaError> {
        Ok(RecallStream::new(self.recall(request)?))
    }

    /// Runs the offline/idle consolidation pass.
    ///
    /// This method is never called by `recall`; callers opt in when they can afford background
    /// work. It may write new consolidated memories, apply tier transitions, and flag stale
    /// significant memories for explicit reconstruction. It never deletes source memories.
    ///
    /// # Errors
    ///
    /// Returns an error when event replay, materialized state reads, or decision writes fail.
    pub fn consolidate(
        &self,
        now: OffsetDateTime,
    ) -> Result<ConsolidationPassReport, ShibahamaError> {
        let items = self.store.memory_items()?;
        let events = self.store.events()?;
        let plan = plan_offline_consolidation(
            &items,
            &events,
            now,
            self.config.consolidation,
            ConsolidationPolicy::default(),
        );
        let mut applied = Vec::new();

        for decision in plan.decisions {
            if let Some(records) = self.apply_consolidation_decision(&decision)? {
                applied.push(ConsolidationOutcome { decision, records });
            }
        }

        Ok(ConsolidationPassReport {
            pass_id: plan.pass_id,
            applied,
        })
    }

    fn apply_consolidation_decision(
        &self,
        decision: &PlannedConsolidationDecision,
    ) -> Result<Option<ConsolidationDecisionRecord>, ShibahamaError> {
        let records = match decision.action {
            crate::model::ConsolidationAction::Merge => {
                let output = decision.output.as_ref().ok_or_else(|| {
                    ShibahamaError::InvalidRequest(
                        "merge consolidation decision did not include an output memory".to_owned(),
                    )
                })?;

                Some(self.store.insert_consolidated_memory(
                    output,
                    decision.pass_id.clone(),
                    decision.input_ids.clone(),
                    decision.why.clone(),
                )?)
            }
            crate::model::ConsolidationAction::Promote
            | crate::model::ConsolidationAction::Demote => {
                let id = decision.input_ids.first().copied().ok_or_else(|| {
                    ShibahamaError::InvalidRequest(
                        "tier consolidation decision did not include an input memory".to_owned(),
                    )
                })?;
                let tier_to = decision.tier_to.ok_or_else(|| {
                    ShibahamaError::InvalidRequest(
                        "tier consolidation decision did not include a target tier".to_owned(),
                    )
                })?;

                self.store.apply_consolidation_tier_change(
                    id,
                    tier_to,
                    decision.pass_id.clone(),
                    decision.why.clone(),
                )?
            }
            crate::model::ConsolidationAction::FlagStale => {
                let id = decision.input_ids.first().copied().ok_or_else(|| {
                    ShibahamaError::InvalidRequest(
                        "stale-flag consolidation decision did not include an input memory"
                            .to_owned(),
                    )
                })?;
                let flag_at = decision.flag_at.ok_or_else(|| {
                    ShibahamaError::InvalidRequest(
                        "stale-flag consolidation decision did not include a flag timestamp"
                            .to_owned(),
                    )
                })?;
                let reason = decision.flag_reason.clone().ok_or_else(|| {
                    ShibahamaError::InvalidRequest(
                        "stale-flag consolidation decision did not include a reason".to_owned(),
                    )
                })?;

                self.store.flag_for_consolidation_revalidation(
                    id,
                    flag_at,
                    reason,
                    decision.pass_id.clone(),
                    decision.why.clone(),
                )?
            }
        };

        Ok(records)
    }

    /// Runs the gated reconstruction loop for stale load-bearing recall candidates.
    ///
    /// Plain `recall` never calls this method or mutates validity. Callers must explicitly provide
    /// a revalidation source and corroboration signals before a replacement can leave quarantine.
    ///
    /// # Errors
    ///
    /// Returns an error when storage reads, budgeted replacement writes, or event replay fail.
    pub fn reconstruct_from_recall<S>(
        &self,
        candidates: &[RecallCandidate],
        source: &S,
        corroboration_signals: &[(MemoryId, Vec<CorroborationSignal>)],
        now: OffsetDateTime,
    ) -> Result<Vec<ExplicitReconstructionOutcome>, ShibahamaError>
    where
        S: RevalidationSource,
    {
        let triggers = triggers_from_recall(candidates);
        let gate =
            evaluate_reconstruction_gate(&triggers, ReconstructionMode::ExplicitRevalidation);

        if !gate.may_run {
            return Ok(Vec::new());
        }

        let budget = apply_reconstruction_budget(
            &gate.triggers,
            &[],
            &[],
            now,
            self.config.reconstruction_budget,
        );
        let signals_by_memory = corroboration_signals
            .iter()
            .map(|(id, signals)| (*id, signals.as_slice()))
            .collect::<BTreeMap<_, _>>();
        let candidates_by_memory = candidates
            .iter()
            .map(|candidate| (candidate.id, candidate))
            .collect::<BTreeMap<_, _>>();
        let mut outcomes = Vec::new();

        for deferred in budget.deferred {
            outcomes.push(ExplicitReconstructionOutcome::deferred(
                deferred.trigger,
                deferred.reason,
            ));
        }

        for trigger in budget.allowed {
            outcomes.push(
                self.reconstruct_allowed_trigger(
                    trigger,
                    candidates_by_memory.get(&trigger.memory_id).copied(),
                    source,
                    signals_by_memory
                        .get(&trigger.memory_id)
                        .copied()
                        .unwrap_or(&[]),
                    now,
                )?,
            );
        }

        Ok(outcomes)
    }

    fn reconstruct_allowed_trigger<S>(
        &self,
        trigger: ReconstructionTrigger,
        candidate: Option<&RecallCandidate>,
        source: &S,
        signals: &[CorroborationSignal],
        now: OffsetDateTime,
    ) -> Result<ExplicitReconstructionOutcome, ShibahamaError>
    where
        S: RevalidationSource,
    {
        let Some(candidate) = candidate else {
            return Ok(ExplicitReconstructionOutcome::missing_original(trigger));
        };
        let Some(original) = self.store.get(trigger.memory_id)? else {
            return Ok(ExplicitReconstructionOutcome::missing_original(trigger));
        };

        let hook = DefaultRevalidationHook;
        let policy = CorroborationPolicy::default();
        let action = hook.plan_revalidation(&trigger, &candidate.provenance);
        let Some(event) = source.revalidate(&action, &original, now) else {
            return Ok(ExplicitReconstructionOutcome::no_observation(
                trigger, action,
            ));
        };

        let proposal = quarantine_proposal(
            event.into_item_with_policy(self.config.ingest_credence),
            trigger.memory_id,
        );
        let corroboration = evaluate_corroboration(signals, policy);
        let Some(replacement) = promote_corroborated_proposal(&proposal, signals, policy) else {
            return Ok(ExplicitReconstructionOutcome::quarantined(
                trigger,
                action,
                proposal,
                corroboration,
            ));
        };

        let records = self
            .store
            .insert_reconstruction_replacement(
                trigger.memory_id,
                &replacement,
                replacement.timestamps.valid_from,
            )?
            .ok_or_else(|| {
                ShibahamaError::InvalidRequest(format!(
                    "memory {} disappeared before reconstruction replacement",
                    trigger.memory_id,
                ))
            })?;

        Ok(ExplicitReconstructionOutcome::applied(
            trigger,
            action,
            proposal,
            corroboration,
            replacement,
            records,
        ))
    }

    /// Challenges a memory with a human-readable reason.
    ///
    /// This lowers credence deterministically, records a contradicted access outcome, and flags the
    /// memory for review. The signal is logged in an RL-ready shape but is not connected to a
    /// learned reward or policy update.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted.
    pub fn challenge(
        &self,
        id: MemoryId,
        reason: impl Into<String>,
    ) -> Result<bool, ShibahamaError> {
        Ok(self
            .challenge_with_request(id, HumanSignalRequest::api_default(reason))?
            .is_some())
    }

    /// Challenges a memory with explicit actor, reason, and timestamp metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted.
    pub fn challenge_with_request(
        &self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        self.require_scope_context()?;
        self.store
            .challenge_memory(
                id,
                request.actor,
                request.reason,
                request.timestamp,
                &self.config.significance,
            )?
            .map(human_signal_outcome_from_records)
            .transpose()
    }

    /// Affirms a memory using default API actor metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted.
    pub fn affirm(&self, id: MemoryId) -> Result<bool, ShibahamaError> {
        Ok(self
            .affirm_with_request(id, HumanSignalRequest::api_default("affirmed"))?
            .is_some())
    }

    /// Affirms a memory with explicit actor, reason, and timestamp metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted.
    pub fn affirm_with_request(
        &self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        self.require_scope_context()?;
        self.store
            .affirm_memory(
                id,
                request.actor,
                request.reason,
                request.timestamp,
                &self.config.significance,
            )?
            .map(human_signal_outcome_from_records)
            .transpose()
    }

    /// Corrects a memory with proposed replacement content.
    ///
    /// The proposed replacement first enters the reconstruction quarantine at low credence. Human
    /// confirmation then corroborates it through the existing reconstruction pipeline, which
    /// invalidate-not-deletes the prior version and writes the promoted replacement as a new row.
    ///
    /// # Errors
    ///
    /// Returns an error when the correction cannot be persisted.
    pub fn correct(
        &self,
        id: MemoryId,
        proposed_content: impl Into<String>,
    ) -> Result<Option<HumanCorrectionOutcome>, ShibahamaError> {
        self.correct_with_request(
            id,
            proposed_content,
            HumanSignalRequest::api_default("corrected"),
        )
    }

    /// Corrects a memory with explicit actor, reason, and timestamp metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the correction cannot be persisted.
    pub fn correct_with_request(
        &self,
        id: MemoryId,
        proposed_content: impl Into<String>,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanCorrectionOutcome>, ShibahamaError> {
        self.require_scope_context()?;
        let Some(original) = self.store.get(id)? else {
            return Ok(None);
        };
        let proposed_content = proposed_content.into();
        let correction_source_ref = original.provenance.source_ref.as_ref().map_or_else(
            || format!("human-correction:{id}"),
            |source_ref| format!("{source_ref};human-correction:{id}"),
        );
        let mut event = MemoryWriteEvent::new(
            proposed_content.clone(),
            Provenance::new(
                SourceKind::User,
                Some(correction_source_ref),
                request.actor.clone(),
            ),
            request.timestamp,
            request.timestamp,
        );
        event = event.with_scope(original.scope.clone());
        event.tier = Tier::Cold;
        event.credence = Some(CredenceTier::Unverified);
        event.credence_floor = Tier::Cold;
        event.significance = original.base_significance.max(1.0);

        let proposal =
            quarantine_proposal(event.into_item_with_policy(self.config.ingest_credence), id);
        let corroboration_signals = [CorroborationSignal::HumanConfirmed];
        let policy = CorroborationPolicy::default();
        let corroboration = evaluate_corroboration(&corroboration_signals, policy);
        let replacement = promote_corroborated_proposal(&proposal, &corroboration_signals, policy)
            .ok_or_else(|| {
                ShibahamaError::InvalidRequest(
                    "human correction failed to corroborate its proposal".to_owned(),
                )
            })?;
        let Some(records) = self.store.insert_reconstruction_replacement(
            id,
            &replacement,
            replacement.timestamps.valid_from,
        )?
        else {
            return Ok(None);
        };
        let signal = HumanSignal {
            action: HumanSignalAction::Correct,
            memory_id: id,
            actor: request.actor,
            timestamp: request.timestamp,
            reason: request.reason,
            proposed_content: Some(proposed_content),
            proposal_id: Some(replacement.id),
            previous_credence: Some(original.credence),
            new_credence: Some(replacement.credence),
            previous_credence_floor: Some(original.credence_floor),
            new_credence_floor: Some(replacement.credence_floor),
        };
        let signal_record = self.store.append_human_signal(signal.clone())?;

        Ok(Some(HumanCorrectionOutcome {
            proposal,
            corroboration,
            replacement,
            records,
            signal,
            signal_record,
        }))
    }

    /// Pins a memory using default API actor metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted.
    pub fn pin(&self, id: MemoryId) -> Result<bool, ShibahamaError> {
        Ok(self
            .pin_with_request(id, HumanSignalRequest::api_default("pinned"))?
            .is_some())
    }

    /// Pins a memory by raising its credence floor with explicit metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted.
    pub fn pin_with_request(
        &self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        self.require_scope_context()?;
        self.store
            .set_human_credence_floor(
                id,
                HumanSignalAction::Pin,
                request.actor,
                request.reason,
                request.timestamp,
            )?
            .map(human_signal_outcome_from_records)
            .transpose()
    }

    /// Removes a human floor pin using default API actor metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted.
    pub fn unpin(&self, id: MemoryId) -> Result<bool, ShibahamaError> {
        Ok(self
            .unpin_with_request(id, HumanSignalRequest::api_default("unpinned"))?
            .is_some())
    }

    /// Removes a human floor pin with explicit metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted.
    pub fn unpin_with_request(
        &self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        self.require_scope_context()?;
        self.store
            .set_human_credence_floor(
                id,
                HumanSignalAction::Unpin,
                request.actor,
                request.reason,
                request.timestamp,
            )?
            .map(human_signal_outcome_from_records)
            .transpose()
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
        self.require_scope_context()?;
        let (request, decision) = self.policy_recall_request(request)?;
        let candidates = timeline(&self.store, &self.vector_index, &request)?;
        self.record_recall_policy(&decision, &request, &candidates)?;

        Ok(candidates)
    }

    /// Replays timeline recall and returns an owning iterator over ranked candidates.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search or storage reads fail.
    pub fn stream_timeline(
        &self,
        request: &RecallRequest<'_>,
    ) -> Result<RecallStream, ShibahamaError> {
        Ok(RecallStream::new(self.timeline(request)?))
    }

    /// Stores or replaces a graph entity.
    ///
    /// # Errors
    ///
    /// Returns an error when the graph entity cannot be persisted.
    pub fn put_graph_entity(&self, entity: &Entity) -> Result<Entity, ShibahamaError> {
        self.require_scope_context()?;
        self.store.put_entity(entity)?;

        Ok(entity.clone())
    }

    /// Reads a graph entity by id.
    ///
    /// # Errors
    ///
    /// Returns an error when graph state cannot be read.
    pub fn graph_entity(&self, id: EntityId) -> Result<Option<Entity>, ShibahamaError> {
        self.require_scope_context()?;
        Ok(self.store.get_entity(id)?)
    }

    /// Stores or replaces a graph relation.
    ///
    /// # Errors
    ///
    /// Returns an error when the graph relation cannot be persisted.
    pub fn put_graph_relation(&self, relation: &Relation) -> Result<Relation, ShibahamaError> {
        self.require_scope_context()?;
        self.store.put_relation(relation)?;

        Ok(relation.clone())
    }

    /// Reads a graph relation by id.
    ///
    /// # Errors
    ///
    /// Returns an error when graph state cannot be read.
    pub fn graph_relation(&self, id: RelationId) -> Result<Option<Relation>, ShibahamaError> {
        self.require_scope_context()?;
        Ok(self.store.get_relation(id)?)
    }

    /// Reconstructs graph state believed at a point in time.
    ///
    /// # Errors
    ///
    /// Returns an error when graph state cannot be read.
    pub fn graph_snapshot(&self, as_of: OffsetDateTime) -> Result<GraphSnapshot, ShibahamaError> {
        self.require_scope_context()?;
        Ok(self.store.graph_snapshot(as_of)?)
    }

    /// Traverses graph relations from a starting entity.
    ///
    /// # Errors
    ///
    /// Returns an error when graph state cannot be read.
    pub fn traverse_graph(
        &self,
        request: &GraphTraversalRequest,
    ) -> Result<GraphTraversalResult, ShibahamaError> {
        self.require_scope_context()?;
        Ok(self.store.traverse_graph(request)?)
    }

    /// Extracts a graph slice by entity attribute scope.
    ///
    /// # Errors
    ///
    /// Returns an error when graph state cannot be read.
    pub fn extract_subgraph(
        &self,
        request: &SubgraphRequest,
    ) -> Result<GraphTraversalResult, ShibahamaError> {
        Ok(self.store.extract_subgraph(request)?)
    }

    /// Reinforces a memory with a usage outcome.
    ///
    /// # Errors
    ///
    /// Returns an error when the access event cannot be persisted.
    pub fn reinforce(&self, id: MemoryId, outcome: AccessOutcome) -> Result<bool, ShibahamaError> {
        self.require_scope_context()?;
        Ok(self
            .store
            .record_access_with_policy(
                id,
                crate::model::AccessEvent::new(OffsetDateTime::now_utc(), None, outcome),
                &self.config.significance,
            )?
            .is_some())
    }

    /// Returns a full explanation for the current memory state.
    ///
    /// # Errors
    ///
    /// Returns an error when the item, significance inputs, or audit trail cannot be read.
    pub fn why(&self, id: MemoryId) -> Result<Option<WhyTrace>, ShibahamaError> {
        self.why_at(id, OffsetDateTime::now_utc())
    }

    /// Returns a full explanation for the memory state at `now`.
    ///
    /// # Errors
    ///
    /// Returns an error when the item, significance inputs, or audit trail cannot be read.
    pub fn why_at(
        &self,
        id: MemoryId,
        now: OffsetDateTime,
    ) -> Result<Option<WhyTrace>, ShibahamaError> {
        self.why_with_significance_policy(id, now, self.config.significance)
    }

    /// Returns a full explanation using a caller-supplied significance policy.
    ///
    /// # Errors
    ///
    /// Returns an error when the item, graph centrality, or audit trail cannot be read.
    pub fn why_with_significance_policy(
        &self,
        id: MemoryId,
        now: OffsetDateTime,
        policy: SignificanceConfig,
    ) -> Result<Option<WhyTrace>, ShibahamaError> {
        self.require_scope_context()?;
        let Some(item) = self.store.get(id)? else {
            return Ok(None);
        };
        let graph_centrality = self.store.graph_centrality_for_memory(id)?;
        let significance = policy.explain_with_graph_centrality(&item, now, graph_centrality);
        let audit_trail = self.store.audit_trail(id)?;

        Ok(Some(WhyTrace {
            provenance: item.provenance.clone(),
            tier: WhyTierTrace {
                current: item.tier,
                credence: item.credence,
                credence_floor: item.credence_floor,
                audit: audit_trail.clone(),
            },
            currency: WhyCurrencyTrace::from_item(&item, now),
            item,
            significance,
            audit_trail,
        }))
    }
}

impl<V> Drop for ScopedShibahama<'_, V> {
    fn drop(&mut self) {
        self.engine.config.scope_mode = self.previous_scope_mode;
    }
}

impl<V: VectorIndex> ScopedShibahama<'_, V> {
    /// Returns the active repository/team scope.
    #[must_use]
    pub const fn scope(&self) -> &MemoryScope {
        &self.scope
    }

    /// Writes a scope-marked snapshot containing only this context's memories and durable state.
    ///
    /// # Errors
    ///
    /// Returns an error when scoped snapshot export fails.
    pub fn snapshot(&mut self, path: impl AsRef<Path>) -> Result<(), ShibahamaError> {
        Ok(self.engine.store.snapshot_scope(path, &self.scope)?)
    }

    /// Returns materialized memories in the active scope.
    ///
    /// # Errors
    ///
    /// Returns an error when scoped storage cannot be read.
    pub fn memory_items(&mut self) -> Result<Vec<MemoryItem>, ShibahamaError> {
        Ok(self.engine.store.memory_items_in_scope(&self.scope)?)
    }

    /// Returns inspection events visible to the active scope.
    ///
    /// # Errors
    ///
    /// Returns an error when scoped storage cannot be read.
    pub fn event_records(&mut self) -> Result<Vec<EventRecord>, ShibahamaError> {
        Ok(self.engine.store.events_in_scope(&self.scope)?)
    }

    /// Stores an entity only when its scope matches this context.
    ///
    /// # Errors
    ///
    /// Returns an error when the entity scope differs or storage rejects the write.
    pub fn put_graph_entity(&mut self, entity: &Entity) -> Result<Entity, ShibahamaError> {
        self.ensure_graph_scope(&entity.scope)?;
        self.engine.put_graph_entity(entity)
    }

    /// Reads an entity only when it belongs to this context.
    ///
    /// # Errors
    ///
    /// Returns an error when graph storage cannot be read.
    pub fn graph_entity(&mut self, id: EntityId) -> Result<Option<Entity>, ShibahamaError> {
        let entity = self.engine.graph_entity(id)?;
        if entity
            .as_ref()
            .is_some_and(|entity| entity.scope != self.scope)
        {
            return Err(ShibahamaError::InvalidRequest(
                "graph entity id is outside the active scope context".to_owned(),
            ));
        }

        Ok(entity)
    }

    /// Stores a relation only when its scope matches this context and both endpoints are scoped.
    ///
    /// # Errors
    ///
    /// Returns an error when the relation scope differs or storage rejects the write.
    pub fn put_graph_relation(&mut self, relation: &Relation) -> Result<Relation, ShibahamaError> {
        self.ensure_graph_scope(&relation.scope)?;
        self.engine.put_graph_relation(relation)
    }

    /// Reads a relation only when it belongs to this context.
    ///
    /// # Errors
    ///
    /// Returns an error when graph storage cannot be read.
    pub fn graph_relation(&mut self, id: RelationId) -> Result<Option<Relation>, ShibahamaError> {
        let relation = self.engine.graph_relation(id)?;
        if relation
            .as_ref()
            .is_some_and(|relation| relation.scope != self.scope)
        {
            return Err(ShibahamaError::InvalidRequest(
                "graph relation id is outside the active scope context".to_owned(),
            ));
        }

        Ok(relation)
    }

    /// Reconstructs graph state only within this context.
    ///
    /// # Errors
    ///
    /// Returns an error when graph storage cannot be read.
    pub fn graph_snapshot(
        &mut self,
        as_of: OffsetDateTime,
    ) -> Result<GraphSnapshot, ShibahamaError> {
        Ok(self
            .engine
            .store
            .graph_snapshot_in_scope(as_of, &self.scope)?)
    }

    /// Traverses graph relations only within this context.
    ///
    /// # Errors
    ///
    /// Returns an error when a conflicting request scope is supplied or traversal fails.
    pub fn traverse_graph(
        &mut self,
        request: &GraphTraversalRequest,
    ) -> Result<GraphTraversalResult, ShibahamaError> {
        if request
            .scope
            .as_ref()
            .is_some_and(|scope| scope != &self.scope)
        {
            return Err(ShibahamaError::InvalidRequest(
                "graph traversal scope conflicts with the active scope context".to_owned(),
            ));
        }

        self.engine
            .traverse_graph(&request.clone().with_scope(self.scope.clone()))
    }

    /// Writes a memory only when its scope matches this context.
    ///
    /// # Errors
    ///
    /// Returns an error when the event scope differs or storage rejects the write.
    pub fn write(&mut self, event: MemoryWriteEvent) -> Result<MemoryItem, ShibahamaError> {
        self.ensure_event_scope(&event)?;
        self.engine.write(event)
    }

    /// Writes and indexes a memory only when its scope matches this context.
    ///
    /// # Errors
    ///
    /// Returns an error when the event scope differs or the write/index fails.
    pub fn write_with_embedding(
        &mut self,
        event: MemoryWriteEvent,
        embedding: WriteEmbedding<'_>,
    ) -> Result<MemoryItem, ShibahamaError> {
        self.ensure_event_scope(&event)?;
        self.engine.write_with_embedding(event, embedding)
    }

    /// Recalls only memories in this scope.
    ///
    /// # Errors
    ///
    /// Returns an error when a conflicting request scope is supplied or recall fails.
    pub fn recall(
        &mut self,
        request: &RecallRequest<'_>,
    ) -> Result<Vec<RecallCandidate>, ShibahamaError> {
        self.engine.recall(&self.scoped_request(request)?)
    }

    /// Recalls this scope and returns the applied policy decision and budget use.
    ///
    /// # Errors
    ///
    /// Returns an error when a conflicting scope is supplied or recall fails.
    pub fn recall_with_policy_report(
        &mut self,
        request: &RecallRequest<'_>,
    ) -> Result<PolicyRecallResult, ShibahamaError> {
        self.engine
            .recall_with_policy_report(&self.scoped_request(request)?)
    }

    /// Replays only memories in this scope at a historical instant.
    ///
    /// # Errors
    ///
    /// Returns an error when a conflicting request scope is supplied or timeline recall fails.
    pub fn timeline(
        &mut self,
        request: &RecallRequest<'_>,
    ) -> Result<Vec<RecallCandidate>, ShibahamaError> {
        self.engine.timeline(&self.scoped_request(request)?)
    }

    /// Invalidates one memory only when its id belongs to this scope.
    ///
    /// # Errors
    ///
    /// Returns an error when the id belongs to another scope or invalidation fails.
    pub fn invalidate(
        &mut self,
        id: MemoryId,
        valid_to: OffsetDateTime,
    ) -> Result<bool, ShibahamaError> {
        self.ensure_memory_scope(id)?;
        self.engine.invalidate(id, valid_to)
    }

    /// Promotes a repository-local memory in this context into one team scope.
    ///
    /// # Errors
    ///
    /// Returns an error when the source is outside this scope or promotion fails.
    pub fn promote_to_team(
        &mut self,
        source_id: MemoryId,
        team: ScopeId,
        actor: impl Into<String>,
        rationale: impl Into<String>,
        promoted_at: OffsetDateTime,
    ) -> Result<Option<ScopePromotionRecord>, ShibahamaError> {
        self.ensure_memory_scope(source_id)?;
        self.engine
            .promote_to_team(source_id, team, actor, rationale, promoted_at)
    }

    /// Records a usage outcome only when the memory belongs to this scope.
    ///
    /// # Errors
    ///
    /// Returns an error when the id belongs to another scope or storage rejects the event.
    pub fn reinforce(
        &mut self,
        id: MemoryId,
        outcome: AccessOutcome,
    ) -> Result<bool, ShibahamaError> {
        self.ensure_memory_scope(id)?;
        self.engine.reinforce(id, outcome)
    }

    /// Returns an explanation only for a memory in this scope.
    ///
    /// # Errors
    ///
    /// Returns an error when the id belongs to another scope or explanation fails.
    pub fn why_at(
        &mut self,
        id: MemoryId,
        now: OffsetDateTime,
    ) -> Result<Option<WhyTrace>, ShibahamaError> {
        if self.ensure_memory_scope(id)?.is_none() {
            return Ok(None);
        }

        let mut trace = self.engine.why_at(id, now)?;
        if let Some(trace) = trace.as_mut() {
            trace.audit_trail = self.engine.store.audit_trail_in_scope(id, &self.scope)?;
            trace.tier.audit = trace.audit_trail.clone();
        }

        Ok(trace)
    }

    /// Challenges a memory only when it belongs to this scope.
    ///
    /// # Errors
    ///
    /// Returns an error when the id belongs to another scope or the signal fails.
    pub fn challenge_with_request(
        &mut self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        if self.ensure_memory_scope(id)?.is_none() {
            return Ok(None);
        }

        self.engine.challenge_with_request(id, request)
    }

    /// Affirms a memory only when it belongs to this scope.
    ///
    /// # Errors
    ///
    /// Returns an error when the id belongs to another scope or the signal fails.
    pub fn affirm_with_request(
        &mut self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        if self.ensure_memory_scope(id)?.is_none() {
            return Ok(None);
        }

        self.engine.affirm_with_request(id, request)
    }

    /// Pins a memory only when it belongs to this scope.
    ///
    /// # Errors
    ///
    /// Returns an error when the id belongs to another scope or the signal fails.
    pub fn pin_with_request(
        &mut self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        if self.ensure_memory_scope(id)?.is_none() {
            return Ok(None);
        }

        self.engine.pin_with_request(id, request)
    }

    /// Unpins a memory only when it belongs to this scope.
    ///
    /// # Errors
    ///
    /// Returns an error when the id belongs to another scope or the signal fails.
    pub fn unpin_with_request(
        &mut self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        if self.ensure_memory_scope(id)?.is_none() {
            return Ok(None);
        }

        self.engine.unpin_with_request(id, request)
    }

    /// Corrects a memory only when it belongs to this scope.
    ///
    /// # Errors
    ///
    /// Returns an error when the id belongs to another scope or correction fails.
    pub fn correct_with_request(
        &mut self,
        id: MemoryId,
        proposed_content: impl Into<String>,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanCorrectionOutcome>, ShibahamaError> {
        if self.ensure_memory_scope(id)?.is_none() {
            return Ok(None);
        }

        self.engine
            .correct_with_request(id, proposed_content, request)
    }

    fn ensure_event_scope(&self, event: &MemoryWriteEvent) -> Result<(), ShibahamaError> {
        if event.scope == self.scope {
            Ok(())
        } else {
            Err(ShibahamaError::InvalidRequest(
                "memory event scope does not match the active scope context".to_owned(),
            ))
        }
    }

    fn ensure_graph_scope(&self, scope: &MemoryScope) -> Result<(), ShibahamaError> {
        if *scope == self.scope {
            Ok(())
        } else {
            Err(ShibahamaError::InvalidRequest(
                "graph scope does not match the active scope context".to_owned(),
            ))
        }
    }

    fn ensure_memory_scope(&self, id: MemoryId) -> Result<Option<MemoryItem>, ShibahamaError> {
        let item = self.engine.store.get(id)?;
        if item.as_ref().is_some_and(|item| item.scope != self.scope) {
            return Err(ShibahamaError::InvalidRequest(
                "memory id is outside the active scope context".to_owned(),
            ));
        }

        Ok(item)
    }

    fn scoped_request<'request>(
        &'request self,
        request: &RecallRequest<'request>,
    ) -> Result<RecallRequest<'request>, ShibahamaError> {
        if request.scope.is_some_and(|scope| scope != &self.scope) {
            return Err(ShibahamaError::InvalidRequest(
                "recall request scope conflicts with the active scope context".to_owned(),
            ));
        }

        Ok((*request).with_scope(&self.scope))
    }
}

fn human_signal_outcome_from_records(
    records: HumanSignalRecord,
) -> Result<HumanSignalOutcome, ShibahamaError> {
    let MemoryEvent::HumanSignalRecorded { signal } = &records.signal.event else {
        return Err(ShibahamaError::InvalidRequest(
            "human signal record did not contain a human signal event".to_owned(),
        ));
    };

    Ok(HumanSignalOutcome {
        signal: signal.clone(),
        records,
    })
}

/// Tokio-compatible async API facade around the sync engine.
#[cfg(feature = "tokio")]
#[derive(Clone)]
pub struct AsyncShibahama<V> {
    inner: Arc<tokio::sync::Mutex<Shibahama<V>>>,
}

#[cfg(feature = "tokio")]
impl<V> AsyncShibahama<V>
where
    V: VectorIndex + Send + 'static,
{
    /// Wraps an existing sync engine in the async facade.
    #[must_use]
    pub fn from_sync(engine: Shibahama<V>) -> Self {
        Self {
            inner: Arc::new(tokio::sync::Mutex::new(engine)),
        }
    }

    /// Opens a Shibahama store with a caller-supplied vector index.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened or the blocking task fails.
    pub async fn open(path: impl AsRef<Path>, vector_index: V) -> Result<Self, ShibahamaError> {
        Self::open_with_config(path, vector_index, ShibahamaConfig::default()).await
    }

    /// Opens a Shibahama store with an explicit engine config.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened or the blocking task fails.
    pub async fn open_with_config(
        path: impl AsRef<Path>,
        vector_index: V,
        config: ShibahamaConfig,
    ) -> Result<Self, ShibahamaError> {
        let path = PathBuf::from(path.as_ref());

        tokio::task::spawn_blocking(move || {
            Shibahama::open_with_config(path, vector_index, config).map(Self::from_sync)
        })
        .await?
    }

    /// Returns this engine's active config.
    pub async fn config(&self) -> ShibahamaConfig {
        self.inner.lock().await.config()
    }

    /// Replaces this engine's active config.
    pub async fn set_config(&self, config: ShibahamaConfig) {
        self.inner.lock().await.set_config(config);
    }

    /// Builds an owned async recall request from this engine's recall defaults.
    pub async fn recall_request(
        &self,
        query_vector: impl Into<Vec<f32>>,
        top_k: usize,
        now: OffsetDateTime,
    ) -> AsyncRecallRequest {
        let config = self.config().await;
        AsyncRecallRequest::new(query_vector, top_k, now)
            .with_ranking(config.recall_ranking)
            .with_significance(config.significance)
            .with_staleness(config.recall_staleness)
            .with_diversification(config.recall_diversification)
    }

    /// Writes a memory event without adding an embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when the write cannot be persisted or the blocking task fails.
    pub async fn write(&self, event: MemoryWriteEvent) -> Result<MemoryItem, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().write(event)).await?
    }

    /// Writes a memory event and indexes its embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when the vector cannot be indexed, the write cannot be persisted, or the
    /// blocking task fails.
    pub async fn write_with_embedding(
        &self,
        event: MemoryWriteEvent,
        embedding: WriteEmbedding<'_>,
    ) -> Result<MemoryItem, ShibahamaError> {
        let inner = Arc::clone(&self.inner);
        let embedding = AsyncWriteEmbedding::from(embedding);

        tokio::task::spawn_blocking(move || {
            inner
                .blocking_lock()
                .write_with_embedding(event, embedding.as_write_embedding())
        })
        .await?
    }

    /// Soft-invalidates a memory at `valid_to` and removes its stored embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when invalidation cannot be persisted, the vector index cannot be updated,
    /// or the blocking task fails.
    pub async fn invalidate(
        &self,
        id: MemoryId,
        valid_to: OffsetDateTime,
    ) -> Result<bool, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().invalidate(id, valid_to)).await?
    }

    /// Returns all current materialized memory rows.
    ///
    /// # Errors
    ///
    /// Returns an error when current item state cannot be read or the blocking task fails.
    pub async fn memory_items(&self) -> Result<Vec<MemoryItem>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().memory_items()).await?
    }

    /// Returns all durable event-log records in sequence order.
    ///
    /// # Errors
    ///
    /// Returns an error when event-log records cannot be read or the blocking task fails.
    pub async fn event_records(&self) -> Result<Vec<EventRecord>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().event_records()).await?
    }

    /// Evaluates offline learned-policy candidates against current memory state and event logs.
    ///
    /// The evaluator is read-only: it does not train a model, mutate memory state, or apply any
    /// candidate action.
    ///
    /// # Errors
    ///
    /// Returns an error when current item state, event-log records, or the blocking task fails.
    pub async fn evaluate_offline_policy(
        &self,
        decisions: Vec<OfflinePolicyDecision>,
        config: OfflinePolicyEvaluationConfig,
    ) -> Result<OfflinePolicyEvaluationReport, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || {
            inner
                .blocking_lock()
                .evaluate_offline_policy(&decisions, config)
        })
        .await?
    }

    /// Plans a disabled-by-default Stage 2 contextual-bandit shadow experiment.
    #[must_use]
    pub fn plan_contextual_bandit_experiment(
        &self,
        stage1_report: &OfflinePolicyEvaluationReport,
        significance_config: SignificanceConfig,
        config: ContextualBanditExperimentConfig,
    ) -> ContextualBanditExperimentReport {
        plan_contextual_bandit_experiment(stage1_report, significance_config, config)
    }

    /// Assesses whether Stage 3 policy-model training research is ready to begin.
    #[must_use]
    pub fn assess_stage3_training_readiness(
        &self,
        stage2_report: &ContextualBanditExperimentReport,
        config: &Stage3TrainingReadinessConfig,
    ) -> Stage3TrainingReadinessReport {
        assess_stage3_training_readiness(stage2_report, config)
    }

    /// Recalls current fact memories for an owned query embedding.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, access recording, or the blocking task
    /// fails.
    pub async fn recall(
        &self,
        request: AsyncRecallRequest,
    ) -> Result<Vec<RecallCandidate>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || {
            let request = request.as_recall_request();

            inner.blocking_lock().recall(&request)
        })
        .await?
    }

    /// Recalls current fact memories and returns an owning iterator over ranked candidates.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, access recording, or the blocking task
    /// fails.
    pub async fn stream_recall(
        &self,
        request: AsyncRecallRequest,
    ) -> Result<RecallStream, ShibahamaError> {
        Ok(RecallStream::new(self.recall(request).await?))
    }

    /// Replays recalled memories as they were believed at `request.now`.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, or the blocking task fails.
    pub async fn timeline(
        &self,
        request: AsyncRecallRequest,
    ) -> Result<Vec<RecallCandidate>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || {
            let request = request.as_recall_request();

            inner.blocking_lock().timeline(&request)
        })
        .await?
    }

    /// Replays timeline recall and returns an owning iterator over ranked candidates.
    ///
    /// # Errors
    ///
    /// Returns an error when vector search, storage reads, or the blocking task fails.
    pub async fn stream_timeline(
        &self,
        request: AsyncRecallRequest,
    ) -> Result<RecallStream, ShibahamaError> {
        Ok(RecallStream::new(self.timeline(request).await?))
    }

    /// Runs the offline/idle consolidation pass.
    ///
    /// # Errors
    ///
    /// Returns an error when event replay, materialized state reads, decision writes, or the
    /// blocking task fails.
    pub async fn consolidate(
        &self,
        now: OffsetDateTime,
    ) -> Result<ConsolidationPassReport, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().consolidate(now)).await?
    }

    /// Challenges a memory with a human-readable reason.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted or the blocking task fails.
    pub async fn challenge(
        &self,
        id: MemoryId,
        reason: impl Into<String>,
    ) -> Result<bool, ShibahamaError> {
        let inner = Arc::clone(&self.inner);
        let reason = reason.into();

        tokio::task::spawn_blocking(move || inner.blocking_lock().challenge(id, reason)).await?
    }

    /// Challenges a memory with explicit metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted or the blocking task fails.
    pub async fn challenge_with_request(
        &self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || {
            inner.blocking_lock().challenge_with_request(id, request)
        })
        .await?
    }

    /// Affirms a memory using default API actor metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted or the blocking task fails.
    pub async fn affirm(&self, id: MemoryId) -> Result<bool, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().affirm(id)).await?
    }

    /// Affirms a memory with explicit metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted or the blocking task fails.
    pub async fn affirm_with_request(
        &self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().affirm_with_request(id, request))
            .await?
    }

    /// Corrects a memory with proposed replacement content.
    ///
    /// # Errors
    ///
    /// Returns an error when the correction cannot be persisted or the blocking task fails.
    pub async fn correct(
        &self,
        id: MemoryId,
        proposed_content: impl Into<String>,
    ) -> Result<Option<HumanCorrectionOutcome>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);
        let proposed_content = proposed_content.into();

        tokio::task::spawn_blocking(move || inner.blocking_lock().correct(id, proposed_content))
            .await?
    }

    /// Corrects a memory with explicit metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the correction cannot be persisted or the blocking task fails.
    pub async fn correct_with_request(
        &self,
        id: MemoryId,
        proposed_content: impl Into<String>,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanCorrectionOutcome>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);
        let proposed_content = proposed_content.into();

        tokio::task::spawn_blocking(move || {
            inner
                .blocking_lock()
                .correct_with_request(id, proposed_content, request)
        })
        .await?
    }

    /// Pins a memory using default API actor metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted or the blocking task fails.
    pub async fn pin(&self, id: MemoryId) -> Result<bool, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().pin(id)).await?
    }

    /// Pins a memory with explicit metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted or the blocking task fails.
    pub async fn pin_with_request(
        &self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().pin_with_request(id, request))
            .await?
    }

    /// Removes a human floor pin using default API actor metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted or the blocking task fails.
    pub async fn unpin(&self, id: MemoryId) -> Result<bool, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().unpin(id)).await?
    }

    /// Removes a human floor pin with explicit metadata.
    ///
    /// # Errors
    ///
    /// Returns an error when the signal cannot be persisted or the blocking task fails.
    pub async fn unpin_with_request(
        &self,
        id: MemoryId,
        request: HumanSignalRequest,
    ) -> Result<Option<HumanSignalOutcome>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().unpin_with_request(id, request))
            .await?
    }

    /// Reinforces a memory with a usage outcome.
    ///
    /// # Errors
    ///
    /// Returns an error when the access event cannot be persisted or the blocking task fails.
    pub async fn reinforce(
        &self,
        id: MemoryId,
        outcome: AccessOutcome,
    ) -> Result<bool, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().reinforce(id, outcome)).await?
    }

    /// Returns a full explanation for the current memory state.
    ///
    /// # Errors
    ///
    /// Returns an error when the item, significance inputs, audit trail, or blocking task fails.
    pub async fn why(&self, id: MemoryId) -> Result<Option<WhyTrace>, ShibahamaError> {
        self.why_at(id, OffsetDateTime::now_utc()).await
    }

    /// Returns a full explanation for the memory state at `now`.
    ///
    /// # Errors
    ///
    /// Returns an error when the item, significance inputs, audit trail, or blocking task fails.
    pub async fn why_at(
        &self,
        id: MemoryId,
        now: OffsetDateTime,
    ) -> Result<Option<WhyTrace>, ShibahamaError> {
        let inner = Arc::clone(&self.inner);

        tokio::task::spawn_blocking(move || inner.blocking_lock().why_at(id, now)).await?
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{
        ConsolidationAction, HumanSignalAction, MemoryScope, Provenance, ScopeId, SourceKind,
    };
    #[cfg(feature = "tokio")]
    use crate::read_safety::DefaultSanitizingGateway;
    use crate::retrieval::{RecallCandidateCurrency, RecallRequest};
    use crate::storage::MemoryEvent;
    use crate::vector::{HnswVectorIndex, VectorIndex, VectorIndexError, VectorSearchResult};
    use std::sync::{Arc, Mutex};
    use tempfile::NamedTempFile;
    use time::{Duration, OffsetDateTime};

    type ScopeAuthorizationLog = (String, MemoryScope, MemoryScope, ScopeAuthorizationAction);

    #[derive(Clone, Default)]
    struct RecordingDenyScopePolicy {
        requests: Arc<Mutex<Vec<ScopeAuthorizationLog>>>,
    }

    impl ScopeAuthorizationPolicy for RecordingDenyScopePolicy {
        fn authorize(&self, request: ScopeAuthorizationRequest<'_>) -> ScopeAuthorizationDecision {
            self.requests
                .lock()
                .expect("policy request lock should be healthy")
                .push((
                    request.principal.to_owned(),
                    request.source_scope.clone(),
                    request.target_scope.clone(),
                    request.action,
                ));
            ScopeAuthorizationDecision::Deny
        }
    }

    struct StaticRevalidator {
        event: MemoryWriteEvent,
    }

    #[derive(Clone, Copy)]
    enum FailingVectorMode {
        Add,
        Search,
    }

    struct FailingVectorIndex {
        dimensions: usize,
        mode: FailingVectorMode,
    }

    impl VectorIndex for FailingVectorIndex {
        fn add(&mut self, _id: MemoryId, _vector: &[f32]) -> Result<(), VectorIndexError> {
            match self.mode {
                FailingVectorMode::Add => {
                    Err(VectorIndexError::Backend("injected add failure".to_owned()))
                }
                FailingVectorMode::Search => Ok(()),
            }
        }

        fn search(
            &self,
            _query: &[f32],
            _top_k: usize,
        ) -> Result<Vec<VectorSearchResult>, VectorIndexError> {
            match self.mode {
                FailingVectorMode::Add => Ok(Vec::new()),
                FailingVectorMode::Search => Err(VectorIndexError::Backend(
                    "injected search failure".to_owned(),
                )),
            }
        }

        fn delete_by_id(&mut self, _id: MemoryId) -> Result<(), VectorIndexError> {
            Ok(())
        }

        fn dimensions(&self) -> usize {
            self.dimensions
        }
    }

    impl RevalidationSource for StaticRevalidator {
        fn revalidate(
            &self,
            _action: &RevalidationAction,
            _original: &MemoryItem,
            _now: OffsetDateTime,
        ) -> Option<MemoryWriteEvent> {
            Some(self.event.clone())
        }
    }

    fn api_endpoint_event(content: &str, at: OffsetDateTime) -> MemoryWriteEvent {
        let mut event = MemoryWriteEvent::new(
            content,
            Provenance::new(SourceKind::File, Some("docs://api".to_owned()), "api-test"),
            at,
            at,
        );
        event.significance = 16.0;
        event.tier = Tier::Warm;
        event.credence_floor = Tier::Warm;
        event
    }

    fn write_api_endpoint_memory(
        shibahama: &mut Shibahama<HnswVectorIndex>,
        event: MemoryWriteEvent,
    ) -> MemoryItem {
        shibahama
            .write_with_embedding(
                event,
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("write should work")
    }

    fn has_reconstruction_event(shibahama: &Shibahama<HnswVectorIndex>) -> bool {
        shibahama
            .event_records()
            .expect("events should read")
            .iter()
            .any(|record| matches!(record.event, MemoryEvent::ReconstructionApplied { .. }))
    }

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
        let why = shibahama
            .why_at(item.id, OffsetDateTime::UNIX_EPOCH)
            .expect("why should read")
            .expect("item should exist");

        assert_eq!(why.item.content, "facade memory");
        assert_eq!(why.provenance.source_kind, SourceKind::User);
        assert_eq!(why.tier.current, why.item.tier);
        assert_eq!(why.tier.credence, why.item.credence);
        assert_eq!(why.currency.state, RecallCandidateCurrency::Current);
        assert_eq!(why.currency.valid_from, item.timestamps.valid_from);
        assert!((why.significance.base_score - why.item.base_significance).abs() < f64::EPSILON);
        assert_eq!(why.audit_trail.len(), why.tier.audit.len());
        assert!(why.audit_trail.len() >= 2);
    }

    #[test]
    fn recall_policy_report_clamps_candidates_tokens_and_unsafe_opt_ins() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let config = ShibahamaConfig {
            recall_policy: RecallPolicy {
                max_candidates: 1,
                max_context_tokens: 2,
                ..RecallPolicy::default()
            },
            ..ShibahamaConfig::default()
        };
        let mut shibahama =
            Shibahama::open_with_config(file.path(), HnswVectorIndex::with_capacity(2, 8), config)
                .expect("api should open");
        write_api_endpoint_memory(
            &mut shibahama,
            api_endpoint_event("first compact", OffsetDateTime::UNIX_EPOCH),
        );
        write_api_endpoint_memory(
            &mut shibahama,
            api_endpoint_event("second compact", OffsetDateTime::UNIX_EPOCH),
        );
        let query = [0.0, 0.0];
        let request = RecallRequest::new(&query, 10, OffsetDateTime::UNIX_EPOCH)
            .include_cold()
            .include_instructions()
            .with_max_context_tokens(100);

        let report = shibahama
            .recall_with_policy_report(&request)
            .expect("policy recall should work");

        assert_eq!(report.decision.requested_candidates, 10);
        assert_eq!(report.decision.effective_candidates, 1);
        assert_eq!(report.decision.effective_context_tokens, 2);
        assert!(!report.decision.include_cold);
        assert!(!report.decision.include_instructions);
        assert_eq!(report.candidates.len(), 1);
        assert_eq!(report.context_tokens_used, 2);
        assert!(
            shibahama
                .event_records()
                .expect("events should read")
                .iter()
                .any(|event| matches!(
                    event.event,
                    MemoryEvent::PolicyDecisionRecorded { ref record }
                        if record.operation == crate::policy::PolicyAuditOperation::Recall
                            && record.context_tokens_used == Some(2)
                ))
        );
    }

    #[test]
    fn capture_policy_is_enforced_at_core_write_boundaries() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let config = ShibahamaConfig {
            capture_policy: CapturePolicy {
                mode: crate::policy::CaptureMode::Automatic,
                actors: crate::policy::ActorClassPolicy {
                    automation: true,
                    ..crate::policy::ActorClassPolicy::default()
                },
                minimum_confidence_percent: 80,
                ..CapturePolicy::default()
            },
            ..ShibahamaConfig::default()
        };
        let shibahama =
            Shibahama::open_with_config(file.path(), HnswVectorIndex::with_capacity(2, 8), config)
                .expect("api should open");
        let event = api_endpoint_event("policy-boundary", OffsetDateTime::UNIX_EPOCH);
        let denied = shibahama
            .write_with_capture_policy(
                event.clone(),
                CapturePolicyRequest {
                    actor: crate::policy::PolicyActorClass::Automation,
                    intent: crate::policy::CaptureIntent::Automatic,
                    confidence_percent: 79,
                },
            )
            .expect_err("low-confidence automatic capture must be denied");

        assert!(matches!(
            denied,
            ShibahamaError::PolicyDenied(PolicyError::CaptureDenied {
                reason: crate::policy::CaptureDecisionReason::ConfidenceTooLow
            })
        ));
        assert!(
            shibahama
                .write_with_capture_policy(
                    event,
                    CapturePolicyRequest {
                        actor: crate::policy::PolicyActorClass::Automation,
                        intent: crate::policy::CaptureIntent::Automatic,
                        confidence_percent: 80,
                    },
                )
                .is_ok()
        );
        assert_eq!(
            shibahama
                .memory_items()
                .expect("memory items should read")
                .len(),
            1
        );
        let audits = shibahama
            .event_records()
            .expect("events should read")
            .into_iter()
            .filter_map(|event| match event.event {
                MemoryEvent::PolicyDecisionRecorded { record } => Some(record),
                _ => None,
            })
            .collect::<Vec<_>>();

        assert_eq!(audits.len(), 2);
        assert_eq!(audits[0].disposition, PolicyAuditDisposition::Denied);
        assert_eq!(
            audits[0].capture_reason,
            Some(crate::policy::CaptureDecisionReason::ConfidenceTooLow)
        );
        assert_eq!(audits[1].disposition, PolicyAuditDisposition::Allowed);
        assert!(
            audits
                .iter()
                .all(|audit| audit.source_kind == Some(SourceKind::File))
        );
    }

    #[test]
    fn policy_simulation_matches_live_decisions_without_mutation() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let scope = MemoryScope::default();
        let before_events = shibahama.event_records().expect("events should read");
        let before_items = shibahama.memory_items().expect("items should read");
        let capture_request = CapturePolicyRequest {
            actor: crate::policy::PolicyActorClass::Automation,
            intent: crate::policy::CaptureIntent::Automatic,
            confidence_percent: 100,
        };

        let capture = shibahama.simulate_capture_policy(SourceKind::Agent, &scope, capture_request);
        let recall = shibahama.simulate_recall_policy(20, Some(5_000), true, true, Some(&scope));

        assert_eq!(
            capture.decision,
            shibahama
                .config()
                .capture_policy
                .evaluate(capture_request, SourceKind::Agent, &scope)
        );
        assert_eq!(
            recall.decision,
            shibahama
                .config()
                .recall_policy
                .decide(20, Some(5_000), true, true)
        );
        assert!(recall.scope_allowed);
        assert_eq!(
            shibahama.event_records().expect("events should read"),
            before_events
        );
        assert_eq!(
            shibahama.memory_items().expect("items should read"),
            before_items
        );
    }

    #[test]
    fn provider_embeddings_match_supplied_vectors_and_reject_dimension_mismatch_before_write() {
        struct FixedProvider {
            vector: Vec<f32>,
            dimensions: usize,
        }

        impl EmbeddingProvider for FixedProvider {
            fn metadata(&self) -> crate::embedding::EmbeddingModelMetadata {
                crate::embedding::EmbeddingModelMetadata {
                    provider: "test".to_owned(),
                    model: "fixed".to_owned(),
                    version: "v1".to_owned(),
                    dimensions: self.dimensions,
                    capabilities: vec![
                        crate::embedding::EmbeddingCapability::Document,
                        crate::embedding::EmbeddingCapability::Query,
                    ],
                }
            }

            fn embed(
                &self,
                _text: &str,
                _purpose: EmbeddingPurpose,
            ) -> Result<Vec<f32>, crate::embedding::EmbeddingError> {
                Ok(self.vector.clone())
            }
        }

        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let provider = FixedProvider {
            vector: vec![1.0, 0.0],
            dimensions: 2,
        };
        let item = shibahama
            .write_with_provider(
                api_endpoint_event("provider memory", OffsetDateTime::UNIX_EPOCH),
                &provider,
                "provider-test",
            )
            .expect("provider write should work");
        let candidates = shibahama
            .recall_text_with_provider("provider query", 1, OffsetDateTime::UNIX_EPOCH, &provider)
            .expect("provider recall should work");
        let bad_provider = FixedProvider {
            vector: vec![1.0, 0.0, 0.0],
            dimensions: 3,
        };

        assert_eq!(candidates[0].id, item.id);
        assert!(matches!(
            shibahama.write_with_provider(
                api_endpoint_event("must not persist", OffsetDateTime::UNIX_EPOCH),
                &bad_provider,
                "provider-test",
            ),
            Err(ShibahamaError::InvalidRequest(_))
        ));
        assert_eq!(
            shibahama.memory_items().expect("items should read").len(),
            1
        );
    }

    #[test]
    fn scoped_facade_rejects_cross_scope_ids_and_conflicting_writes() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let scope_a =
            MemoryScope::repository(ScopeId::new("repo-a").expect("scope should validate"));
        let scope_b =
            MemoryScope::repository(ScopeId::new("repo-b").expect("scope should validate"));
        shibahama.set_config(ShibahamaConfig {
            scope_mode: ScopeMode::RequireExplicit,
            ..ShibahamaConfig::default()
        });
        assert!(matches!(
            shibahama.write(MemoryWriteEvent::new(
                "unscoped memory",
                Provenance::new(SourceKind::User, None, "api-test"),
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            )),
            Err(ShibahamaError::InvalidRequest(message)) if message.contains("explicit scope")
        ));
        let event = MemoryWriteEvent::new(
            "scoped facade memory",
            Provenance::new(SourceKind::User, None, "api-test"),
            OffsetDateTime::UNIX_EPOCH,
            OffsetDateTime::UNIX_EPOCH,
        )
        .with_scope(scope_a.clone());
        let item = shibahama
            .scoped(scope_a.clone())
            .expect("scope should open")
            .write_with_embedding(
                event,
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("scoped write should work");

        let query = [0.0, 0.0];
        let recalled = shibahama
            .scoped(scope_a.clone())
            .expect("scope should open")
            .recall(&RecallRequest::new(&query, 1, OffsetDateTime::UNIX_EPOCH))
            .expect("scoped recall should work");
        assert_eq!(recalled[0].id, item.id);

        let mut other = shibahama.scoped(scope_b).expect("scope should open");
        assert!(matches!(
            other.why_at(item.id, OffsetDateTime::UNIX_EPOCH),
            Err(ShibahamaError::InvalidRequest(message)) if message.contains("outside")
        ));
        assert!(matches!(
            other.write(MemoryWriteEvent::new(
                "wrong scope",
                Provenance::new(SourceKind::User, None, "api-test"),
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            )),
            Err(ShibahamaError::InvalidRequest(message)) if message.contains("does not match")
        ));
    }

    #[test]
    fn team_promotion_preserves_local_source_provenance_and_credence_ordering() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let local_scope =
            MemoryScope::repository(ScopeId::new("promotion-repo").expect("scope should validate"));
        let team = ScopeId::new("promotion-team").expect("team should validate");
        let team_scope = MemoryScope::team(local_scope.repository.clone(), team.clone());
        let now = OffsetDateTime::UNIX_EPOCH;
        let mut local_event = MemoryWriteEvent::new(
            "low credence local memory",
            Provenance::new(
                SourceKind::User,
                Some("source://local".to_owned()),
                "api-test",
            ),
            now,
            now,
        )
        .with_scope(local_scope.clone());
        local_event.credence = Some(CredenceTier::Unverified);
        local_event.tier = Tier::Warm;
        let source = shibahama
            .scoped(local_scope.clone())
            .expect("local scope should open")
            .write_with_embedding(
                local_event,
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "promotion-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("local write should work");
        shibahama.set_scope_authorization_policy(AllowScopePromotionPolicy);
        let promoted = shibahama
            .scoped(local_scope.clone())
            .expect("local scope should open")
            .promote_to_team(
                source.id,
                team,
                "maintainer",
                "shared build convention",
                now + Duration::seconds(1),
            )
            .expect("promotion should work")
            .expect("source should exist");

        assert_scope_promotion(&shibahama, &source, &promoted, &local_scope, &team_scope);

        let mut authoritative = MemoryWriteEvent::new(
            "authoritative team memory",
            Provenance::new(
                SourceKind::File,
                Some("source://team".to_owned()),
                "api-test",
            ),
            now,
            now + Duration::seconds(1),
        )
        .with_scope(team_scope.clone());
        authoritative.credence = Some(CredenceTier::FirmAuthoritative);
        authoritative.tier = Tier::Warm;
        let authoritative = shibahama
            .scoped(team_scope.clone())
            .expect("team scope should open")
            .write_with_embedding(
                authoritative,
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "promotion-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("team write should work");
        let query = [0.0, 0.0];
        let recalled = shibahama
            .scoped(team_scope)
            .expect("team scope should open")
            .recall(&RecallRequest::new(&query, 2, now + Duration::seconds(2)).include_cold())
            .expect("team recall should work");

        assert_eq!(recalled[0].id, authoritative.id, "{recalled:#?}");
        assert!(
            recalled
                .iter()
                .any(|candidate| candidate.id == promoted.promoted.id)
        );
    }

    fn assert_scope_promotion(
        engine: &Shibahama<HnswVectorIndex>,
        source: &MemoryItem,
        promotion: &ScopePromotionRecord,
        local_scope: &MemoryScope,
        team_scope: &MemoryScope,
    ) {
        assert_eq!(source.scope, *local_scope);
        assert_eq!(
            engine
                .store()
                .get(source.id)
                .expect("source should read")
                .expect("source should remain stored"),
            *source
        );
        assert_eq!(promotion.promoted.scope, *team_scope);
        assert_eq!(promotion.promoted.provenance, source.provenance);
        assert_eq!(
            promotion
                .promoted
                .promotion
                .as_ref()
                .map(|value| value.source_memory_id),
            Some(source.id)
        );
        assert_eq!(
            promotion
                .promoted
                .promotion
                .as_ref()
                .map(|value| (value.promoted_by.as_str(), value.rationale.as_str())),
            Some(("maintainer", "shared build convention"))
        );
        assert!(matches!(
            promotion.promotion.event,
            MemoryEvent::MemoryScopePromoted { source_id, promoted_id, .. }
                if source_id == source.id && promoted_id == promotion.promoted.id
        ));
    }

    #[test]
    fn scope_promotion_policy_is_fail_closed_and_audits_without_memory_content() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut engine = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let source_scope = MemoryScope::repository(
            ScopeId::new("authorization-repo").expect("scope should validate"),
        );
        let team = ScopeId::new("authorization-team").expect("scope should validate");
        let target_scope = MemoryScope::team(source_scope.repository.clone(), team.clone());
        let now = OffsetDateTime::UNIX_EPOCH;
        let source = engine
            .scoped(source_scope.clone())
            .expect("scope should open")
            .write(
                MemoryWriteEvent::new(
                    "do not expose this secret memory",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    now,
                    now,
                )
                .with_scope(source_scope.clone()),
            )
            .expect("source should write");
        let policy = RecordingDenyScopePolicy::default();
        let requests = Arc::clone(&policy.requests);
        engine.set_scope_authorization_policy(policy);

        assert!(matches!(
            engine.promote_to_team(source.id, team.clone(), "principal-1", "share", now),
            Err(ShibahamaError::AuthorizationDenied)
        ));
        assert_eq!(
            requests
                .lock()
                .expect("policy request lock should be healthy")
                .as_slice(),
            [(
                "principal-1".to_owned(),
                source_scope.clone(),
                target_scope.clone(),
                ScopeAuthorizationAction::PromoteToTeam,
            )]
        );

        let denial = engine
            .event_records()
            .expect("events should read")
            .pop()
            .expect("denial should be recorded");
        let denial_json = serde_json::to_string(&denial).expect("denial should serialize");
        assert!(!denial_json.contains(&source.id.to_string()));
        assert!(!denial_json.contains("do not expose this secret memory"));
        assert!(matches!(
            denial.event,
            MemoryEvent::ScopeAuthorizationDenied {
                principal,
                source_scope: recorded_source,
                target_scope: recorded_target,
                action: ScopeAuthorizationAction::PromoteToTeam,
                ..
            } if principal == "principal-1"
                && recorded_source == source_scope
                && recorded_target == target_scope
        ));

        engine.set_scope_authorization_policy(AllowScopePromotionPolicy);
        assert!(
            engine
                .promote_to_team(source.id, team, "principal-1", "share", now)
                .expect("explicit local policy should allow promotion")
                .is_some()
        );
    }

    #[test]
    fn scoped_inspection_projects_events_audit_and_snapshot_without_cross_scope_payloads() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let snapshot = NamedTempFile::new().expect("snapshot file should be created");
        let mut engine = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let source_scope = MemoryScope::repository(
            ScopeId::new("inspection-repo").expect("scope should validate"),
        );
        let team = ScopeId::new("inspection-team").expect("scope should validate");
        let team_scope = MemoryScope::team(source_scope.repository.clone(), team.clone());
        let other_scope = MemoryScope::repository(
            ScopeId::new("inspection-other").expect("scope should validate"),
        );
        let now = OffsetDateTime::UNIX_EPOCH;
        let source = write_scoped_memory(
            &mut engine,
            source_scope.clone(),
            "source-only inspection payload",
            now,
        );
        write_scoped_memory(
            &mut engine,
            source_scope.clone(),
            "private source inspection payload",
            now,
        );
        let other = write_scoped_memory(
            &mut engine,
            other_scope.clone(),
            "other-only inspection payload",
            now,
        );
        engine.set_scope_authorization_policy(AllowScopePromotionPolicy);
        let promoted = engine
            .scoped(source_scope)
            .expect("scope should open")
            .promote_to_team(source.id, team, "maintainer", "share", now)
            .expect("promotion should work")
            .expect("source should exist");

        let mut team_context = engine
            .scoped(team_scope.clone())
            .expect("scope should open");
        assert_eq!(
            team_context
                .memory_items()
                .expect("items should read")
                .len(),
            1
        );
        assert!(matches!(
            team_context.event_records().expect("events should read").as_slice(),
            [
                EventRecord { event: MemoryEvent::MemoryWritten { .. }, .. },
                EventRecord { event: MemoryEvent::MemoryScopePromoted { source_id, promoted_id, .. }, .. },
            ] if *source_id == source.id && *promoted_id == promoted.promoted.id
        ));
        assert!(
            team_context
                .why_at(promoted.promoted.id, now)
                .expect("why should read")
                .is_some()
        );
        team_context
            .snapshot(snapshot.path())
            .expect("snapshot should write");
        drop(team_context);

        let snapshot_json = std::fs::read_to_string(snapshot.path()).expect("snapshot should read");
        assert!(snapshot_json.contains(&source.id.to_string()));
        assert!(!snapshot_json.contains("private source inspection payload"));
        let mut other_context = engine.scoped(other_scope).expect("scope should open");
        assert_eq!(
            other_context.memory_items().expect("items should read")[0].id,
            other.id
        );
        assert!(other_context.why_at(source.id, now).is_err());
    }

    fn write_scoped_memory(
        engine: &mut Shibahama<HnswVectorIndex>,
        scope: MemoryScope,
        content: &str,
        now: OffsetDateTime,
    ) -> MemoryItem {
        engine
            .scoped(scope.clone())
            .expect("scope should open")
            .write(
                MemoryWriteEvent::new(
                    content,
                    Provenance::new(SourceKind::User, None, "api-test"),
                    now,
                    now,
                )
                .with_scope(scope),
            )
            .expect("memory should write")
    }

    #[test]
    fn explicit_reconstruction_is_gated_quarantined_and_applied_after_corroboration() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let now = OffsetDateTime::now_utc();
        let ingested_at = now - Duration::days(90);
        let original = write_api_endpoint_memory(
            &mut shibahama,
            api_endpoint_event("old API endpoint is /v1", ingested_at),
        );
        let query = [0.0, 0.0];
        let request = RecallRequest::new(&query, 1, now);
        let recalled = shibahama.recall(&request).expect("recall should work");

        assert_eq!(recalled.len(), 1);
        assert!(recalled[0].load_bearing_possibly_stale);
        assert!(
            !shibahama
                .event_records()
                .expect("events should read")
                .iter()
                .any(|record| matches!(
                    record.event,
                    MemoryEvent::MemoryInvalidated { .. }
                        | MemoryEvent::ReconstructionApplied { .. }
                ))
        );

        let revalidator = StaticRevalidator {
            event: api_endpoint_event("current API endpoint is /v2", now),
        };
        let outcomes = shibahama
            .reconstruct_from_recall(
                &recalled,
                &revalidator,
                &[(original.id, vec![CorroborationSignal::HumanConfirmed])],
                now,
            )
            .expect("reconstruction should run");

        assert_eq!(outcomes.len(), 1);
        assert!(matches!(
            outcomes[0].status,
            ExplicitReconstructionStatus::Applied
        ));
        assert_eq!(
            outcomes[0]
                .proposal
                .as_ref()
                .expect("proposal should exist")
                .item
                .credence,
            CredenceTier::Unverified
        );
        let replacement = outcomes[0]
            .replacement
            .as_ref()
            .expect("replacement should be promoted");
        assert_eq!(replacement.content, "current API endpoint is /v2");
        assert_eq!(replacement.credence, CredenceTier::FirmAuthoritative);

        let rows = shibahama.memory_items().expect("rows should read");
        let superseded = rows
            .iter()
            .find(|item| item.id == original.id)
            .expect("old row should remain");
        assert_eq!(superseded.timestamps.valid_to, Some(now));
        assert!(
            rows.iter()
                .any(|item| item.content == "current API endpoint is /v2")
        );
        assert!(has_reconstruction_event(&shibahama));
    }

    struct ConsolidationFixture {
        first: MemoryItem,
        second: MemoryItem,
        floored: MemoryItem,
        stale: MemoryItem,
        now: OffsetDateTime,
    }

    fn seed_consolidation_fixture(shibahama: &Shibahama<HnswVectorIndex>) -> ConsolidationFixture {
        let ingested_at = OffsetDateTime::UNIX_EPOCH;
        let now = ingested_at + Duration::days(90);
        let mut first_event = MemoryWriteEvent::new(
            "API endpoint is /v1",
            Provenance::new(SourceKind::User, None, "api-test"),
            ingested_at,
            ingested_at,
        );
        first_event.credence_floor = Tier::Cold;
        first_event.significance = 2.2;
        let mut second_event = MemoryWriteEvent::new(
            "api endpoint is /v1",
            Provenance::new(SourceKind::User, None, "api-test"),
            ingested_at,
            ingested_at,
        );
        second_event.credence_floor = Tier::Cold;
        second_event.significance = 1.8;
        let mut floored_event = MemoryWriteEvent::with_explicit_credence(
            "pinned safety rule",
            Provenance::new(SourceKind::User, None, "api-test"),
            ingested_at,
            ingested_at,
            Tier::Hot,
            CredenceTier::FirmAuthoritative,
            Tier::Warm,
        );
        floored_event.significance = 0.1;
        let mut stale_event = MemoryWriteEvent::new(
            "old but load-bearing source pointer",
            Provenance::new(SourceKind::File, Some("docs://old".to_owned()), "api-test"),
            ingested_at,
            ingested_at,
        );
        stale_event.credence_floor = Tier::Cold;
        stale_event.significance = 3.2;
        let first = shibahama.write(first_event).expect("first should write");
        let second = shibahama.write(second_event).expect("second should write");
        let floored = shibahama
            .write(floored_event)
            .expect("floored should write");
        let stale = shibahama.write(stale_event).expect("stale should write");

        shibahama
            .reinforce(first.id, AccessOutcome::Cited)
            .expect("first use should record");
        shibahama
            .reinforce(second.id, AccessOutcome::LedSomewhere)
            .expect("second use should record");

        ConsolidationFixture {
            first,
            second,
            floored,
            stale,
            now,
        }
    }

    fn assert_consolidation_report(
        report: &ConsolidationPassReport,
        fixture: &ConsolidationFixture,
    ) {
        assert!(report.applied.iter().any(|outcome| {
            outcome.decision.action == ConsolidationAction::Merge
                && outcome.decision.input_ids == vec![fixture.first.id, fixture.second.id]
        }));
        assert!(report.applied.iter().any(|outcome| {
            outcome.decision.action == ConsolidationAction::FlagStale
                && outcome.decision.input_ids == vec![fixture.stale.id]
        }));
        assert!(report.applied.iter().any(|outcome| {
            outcome.decision.action == ConsolidationAction::Demote
                && outcome.decision.input_ids == vec![fixture.floored.id]
                && outcome.decision.tier_to == Some(Tier::Warm)
        }));
    }

    fn assert_consolidated_rows<'a>(
        rows: &'a [MemoryItem],
        fixture: &ConsolidationFixture,
    ) -> &'a MemoryItem {
        let consolidated = rows
            .iter()
            .find(|item| {
                item.consolidation.as_ref().is_some_and(|lineage| {
                    lineage.source_memory_ids == vec![fixture.first.id, fixture.second.id]
                })
            })
            .expect("consolidated memory should exist");

        assert_eq!(consolidated.content, "API endpoint is /v1");
        assert!(rows.iter().any(|item| item.id == fixture.first.id));
        assert!(rows.iter().any(|item| item.id == fixture.second.id));
        assert_eq!(
            rows.iter()
                .find(|item| item.id == fixture.floored.id)
                .expect("floored row should remain")
                .tier,
            Tier::Warm
        );

        consolidated
    }

    fn assert_consolidation_events(
        shibahama: &Shibahama<HnswVectorIndex>,
        consolidated: &MemoryItem,
    ) {
        let events = shibahama.event_records().expect("events should read");
        let consolidation_events = events
            .iter()
            .filter(|record| matches!(record.event, MemoryEvent::ConsolidationDecision { .. }))
            .count();

        assert!(consolidation_events >= 3);
        assert!(events.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::ConsolidationDecision {
                    action: ConsolidationAction::Merge,
                    output_id: Some(output_id),
                    why,
                    ..
                } if *output_id == consolidated.id && !why.evidence.is_empty()
            )
        }));
    }

    fn assert_consolidation_rerun_is_idempotent(
        shibahama: &Shibahama<HnswVectorIndex>,
        now: OffsetDateTime,
    ) {
        let before_rerun = shibahama.memory_items().expect("rows should read").len();
        let rerun = shibahama
            .consolidate(now)
            .expect("rerun should be idempotent");
        let after_rerun = shibahama.memory_items().expect("rows should read").len();

        assert_eq!(before_rerun, after_rerun);
        assert!(
            !rerun
                .applied
                .iter()
                .any(|outcome| outcome.decision.action == ConsolidationAction::Merge)
        );
    }

    #[test]
    fn offline_consolidation_merges_flags_demotes_and_is_idempotent() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let fixture = seed_consolidation_fixture(&shibahama);
        let report = shibahama
            .consolidate(fixture.now)
            .expect("consolidation should run");

        assert_consolidation_report(&report, &fixture);

        let rows = shibahama.memory_items().expect("rows should read");
        let consolidated = assert_consolidated_rows(&rows, &fixture);

        shibahama
            .store()
            .verify_never_delete_invariant()
            .expect("consolidation should preserve never-delete");
        assert_consolidation_events(&shibahama, consolidated);
        assert_consolidation_rerun_is_idempotent(&shibahama, fixture.now);
    }

    #[test]
    fn human_challenge_and_affirm_update_credence_and_emit_audit_events() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(1);
        let item = shibahama
            .write(MemoryWriteEvent::new(
                "deploys go through the old host",
                Provenance::new(SourceKind::User, None, "api-test"),
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ))
            .expect("write should work");

        let challenge = shibahama
            .challenge_with_request(
                item.id,
                HumanSignalRequest::new("cody", "host was retired", now),
            )
            .expect("challenge should persist")
            .expect("item should exist");
        let challenged = shibahama
            .store()
            .get(item.id)
            .expect("item should read")
            .expect("item should exist");

        assert_eq!(challenge.signal.action, HumanSignalAction::Challenge);
        assert_eq!(challenge.signal.actor, "cody");
        assert_eq!(challenged.credence, CredenceTier::VerifiedSource);
        assert!(challenge.records.access.is_some());
        assert!(challenge.records.revalidation_flag.is_some());
        assert!(
            challenged
                .access_events
                .iter()
                .any(|event| event.outcome == AccessOutcome::Contradicted)
        );

        let affirm = shibahama
            .affirm_with_request(
                item.id,
                HumanSignalRequest::new(
                    "cody",
                    "verified after migration",
                    now + Duration::hours(1),
                ),
            )
            .expect("affirm should persist")
            .expect("item should exist");
        let affirmed = shibahama
            .store()
            .get(item.id)
            .expect("item should read")
            .expect("item should exist");
        let events = shibahama.event_records().expect("events should read");

        assert_eq!(affirm.signal.action, HumanSignalAction::Affirm);
        assert_eq!(affirmed.credence, CredenceTier::FirmAuthoritative);
        assert!(events.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::HumanSignalRecorded {
                    signal
                } if signal.action == HumanSignalAction::Challenge
                    && signal.memory_id == item.id
                    && signal.reason == "host was retired"
            )
        }));
        assert!(events.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::HumanSignalRecorded {
                    signal
                } if signal.action == HumanSignalAction::Affirm
                    && signal.memory_id == item.id
                    && signal.reason == "verified after migration"
            )
        }));
        assert!(events.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::ReverificationFlagged {
                    id,
                    reason,
                    ..
                } if *id == item.id && reason.contains("host was retired")
            )
        }));
        shibahama
            .store()
            .verify_never_delete_invariant()
            .expect("human signals should preserve never-delete");
    }

    #[test]
    fn human_pin_enforces_floor_and_unpin_emits_audit_event() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(2);
        let mut event = MemoryWriteEvent::with_explicit_credence(
            "do not auto-run destructive deploys",
            Provenance::new(SourceKind::User, None, "api-test"),
            OffsetDateTime::UNIX_EPOCH,
            OffsetDateTime::UNIX_EPOCH,
            Tier::Cold,
            CredenceTier::VerifiedSource,
            Tier::Cold,
        );
        event.significance = 0.0;
        let item = shibahama.write(event).expect("write should work");

        let pin = shibahama
            .pin_with_request(
                item.id,
                HumanSignalRequest::new("cody", "safety-critical", now),
            )
            .expect("pin should persist")
            .expect("item should exist");
        let pinned = shibahama
            .store()
            .refresh_significance(item.id, &shibahama.config().significance, now)
            .expect("refresh should work")
            .expect("item should exist");

        assert_eq!(pin.signal.action, HumanSignalAction::Pin);
        assert_eq!(pinned.credence_floor, Tier::Warm);
        assert!(pinned.tier >= pinned.credence_floor);

        let unpin = shibahama
            .unpin_with_request(
                item.id,
                HumanSignalRequest::new("cody", "explicitly replaced", now + Duration::hours(1)),
            )
            .expect("unpin should persist")
            .expect("item should exist");
        let unpinned = shibahama
            .store()
            .get(item.id)
            .expect("item should read")
            .expect("item should exist");
        let events = shibahama.event_records().expect("events should read");

        assert_eq!(unpin.signal.action, HumanSignalAction::Unpin);
        assert_eq!(unpinned.credence_floor, Tier::Cold);
        assert!(events.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::HumanSignalRecorded {
                    signal
                } if signal.action == HumanSignalAction::Pin
                    && signal.memory_id == item.id
                    && signal.reason == "safety-critical"
            )
        }));
        assert!(events.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::HumanSignalRecorded {
                    signal
                } if signal.action == HumanSignalAction::Unpin
                    && signal.memory_id == item.id
                    && signal.reason == "explicitly replaced"
            )
        }));
    }

    #[test]
    fn human_correct_routes_through_quarantine_corroboration_and_reconstruction() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let now = OffsetDateTime::UNIX_EPOCH + Duration::days(3);
        let original = shibahama
            .write(MemoryWriteEvent::new(
                "current deploy target is old-host",
                Provenance::new(SourceKind::User, None, "api-test"),
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ))
            .expect("write should work");

        let correction = shibahama
            .correct_with_request(
                original.id,
                "current deploy target is new-host",
                HumanSignalRequest::new("cody", "runbook updated", now),
            )
            .expect("correction should persist")
            .expect("item should exist");
        let rows = shibahama.memory_items().expect("rows should read");
        let superseded = rows
            .iter()
            .find(|item| item.id == original.id)
            .expect("original should remain");
        let events = shibahama.event_records().expect("events should read");

        assert_eq!(correction.proposal.item.credence, CredenceTier::Unverified);
        assert_eq!(correction.proposal.item.tier, Tier::Cold);
        assert_eq!(
            correction.corroboration.promoted_credence,
            Some(CredenceTier::FirmAuthoritative)
        );
        assert_eq!(
            correction.replacement.content,
            "current deploy target is new-host"
        );
        assert_eq!(
            correction.replacement.credence,
            CredenceTier::FirmAuthoritative
        );
        assert_eq!(superseded.timestamps.valid_to, Some(now));
        assert!(rows.iter().any(|item| item.id == correction.replacement.id));
        assert!(events.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::ReconstructionApplied {
                    superseded_id,
                    replacement_id,
                    ..
                } if *superseded_id == original.id
                    && *replacement_id == correction.replacement.id
            )
        }));
        assert!(events.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::HumanSignalRecorded {
                    signal
                } if signal.action == HumanSignalAction::Correct
                    && signal.memory_id == original.id
                    && signal.proposal_id == Some(correction.replacement.id)
                    && signal.proposed_content.as_deref()
                        == Some("current deploy target is new-host")
                    && signal.reason == "runbook updated"
            )
        }));
        shibahama
            .store()
            .verify_never_delete_invariant()
            .expect("correction should preserve never-delete");
    }

    #[test]
    fn facade_hydrates_embeddings_after_reopen() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let event = MemoryWriteEvent::new(
            "reopened memory",
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
        drop(shibahama);

        let reopened = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should reopen and hydrate embeddings");
        let query = [0.0, 0.0];
        let request = RecallRequest::new(&query, 1, OffsetDateTime::UNIX_EPOCH);
        let recalled = reopened.recall(&request).expect("recall should work");

        assert_eq!(recalled[0].id, item.id);
    }

    #[test]
    fn why_trace_reports_invalidated_currency() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let valid_from = OffsetDateTime::UNIX_EPOCH;
        let valid_to = valid_from + time::Duration::days(1);
        let item = shibahama
            .write(MemoryWriteEvent::new(
                "old facade memory",
                Provenance::new(SourceKind::User, None, "api-test"),
                valid_from,
                valid_from,
            ))
            .expect("write should work");

        shibahama
            .store()
            .soft_invalidate(item.id, valid_to)
            .expect("invalidate should work");

        let why = shibahama
            .why_at(item.id, valid_to)
            .expect("why should read")
            .expect("item should exist");

        assert_eq!(why.currency.state, RecallCandidateCurrency::Invalidated);
        assert_eq!(why.currency.valid_to, Some(valid_to));
    }

    #[test]
    fn forgetting_config_flags_for_reverification_without_invalidating() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut config = ShibahamaConfig::default();
        config.forgetting.mode = ForgettingMode::FlagForReverification;
        let mut shibahama =
            Shibahama::open_with_config(file.path(), HnswVectorIndex::with_capacity(2, 8), config)
                .expect("api should open");
        let valid_from = OffsetDateTime::UNIX_EPOCH;
        let flag_at = valid_from + time::Duration::days(1);
        let item = shibahama
            .write_with_embedding(
                MemoryWriteEvent::new(
                    "keep current but reverify",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    valid_from,
                    valid_from,
                ),
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("write should work");

        assert!(
            shibahama
                .invalidate(item.id, flag_at)
                .expect("flag should work")
        );

        let why = shibahama
            .why_at(item.id, flag_at)
            .expect("why should read")
            .expect("item should exist");
        let query = [0.0, 0.0];
        let recalled = shibahama
            .recall(&RecallRequest::new(&query, 1, flag_at))
            .expect("recall should keep flagged memory current");
        let event_records = shibahama
            .event_records()
            .expect("events should read after flag");

        assert_eq!(why.currency.state, RecallCandidateCurrency::Current);
        assert_eq!(why.currency.valid_to, None);
        assert_eq!(recalled[0].id, item.id);
        assert!(event_records.iter().any(|record| {
            matches!(
                &record.event,
                MemoryEvent::ReverificationFlagged {
                    id,
                    flagged_at,
                    reason
                } if *id == item.id
                    && *flagged_at == flag_at
                    && reason == "forgetting-disabled"
            )
        }));
    }

    #[test]
    fn engine_config_swaps_ingest_credence_policy() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut config = ShibahamaConfig::default();
        config.ingest_credence.web = CredenceTier::VerifiedSource;
        config.ingest_credence.user = CredenceTier::ModelInferred;
        let shibahama =
            Shibahama::open_with_config(file.path(), HnswVectorIndex::with_capacity(2, 8), config)
                .expect("api should open");
        let web_item = shibahama
            .write(MemoryWriteEvent::new(
                "domain-vetted web source",
                Provenance::new(
                    SourceKind::Web,
                    Some("https://example.test".to_owned()),
                    "api-test",
                ),
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
            ))
            .expect("write should use configured credence policy");
        let explicit_item = shibahama
            .write(MemoryWriteEvent::with_explicit_credence(
                "explicit caller override",
                Provenance::new(SourceKind::User, None, "api-test"),
                OffsetDateTime::UNIX_EPOCH,
                OffsetDateTime::UNIX_EPOCH,
                Tier::Cold,
                CredenceTier::Unverified,
                Tier::Cold,
            ))
            .expect("explicit credence write should work");

        assert_eq!(web_item.credence, CredenceTier::VerifiedSource);
        assert_eq!(explicit_item.credence, CredenceTier::Unverified);
        assert_eq!(
            shibahama.config().ingest_credence.user,
            CredenceTier::ModelInferred
        );
    }

    #[test]
    fn facade_errors_expose_stable_kind_code_and_action() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let event = MemoryWriteEvent::new(
            "bad embedding",
            Provenance::new(SourceKind::User, None, "api-test"),
            OffsetDateTime::UNIX_EPOCH,
            OffsetDateTime::UNIX_EPOCH,
        );

        let error = shibahama
            .write_with_embedding(
                event,
                WriteEmbedding {
                    vector: &[0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect_err("dimension mismatch should fail");

        assert_eq!(error.kind(), ShibahamaErrorKind::Vector);
        assert_eq!(error.code(), "SHIBA_VECTOR");
        assert_eq!(error.action(), ShibahamaErrorKind::Vector.action());
        assert_eq!(error.severity(), ShibahamaErrorSeverity::Fatal);
        assert!(!error.retryable());
        assert_eq!(
            error.metadata(),
            ShibahamaErrorMetadata {
                code: "SHIBA_VECTOR",
                severity: ShibahamaErrorSeverity::Fatal,
                retryable: false,
                detail: "vector index operation failed",
            }
        );
        assert!(error.to_string().contains("[SHIBA_VECTOR]"));
        assert!(
            error
                .to_string()
                .contains("action: verify embedding dimensionality")
        );
    }

    #[test]
    fn injected_vector_write_failure_leaves_no_durable_state() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(
            file.path(),
            FailingVectorIndex {
                dimensions: 2,
                mode: FailingVectorMode::Add,
            },
        )
        .expect("engine should open");
        let event = MemoryWriteEvent::new(
            "injected write failure",
            Provenance::new(SourceKind::User, None, "api-test"),
            OffsetDateTime::UNIX_EPOCH,
            OffsetDateTime::UNIX_EPOCH,
        );

        let error = shibahama
            .write_with_embedding(
                event,
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect_err("injected vector failure should fail the write");

        assert_eq!(error.code(), "SHIBA_VECTOR");
        assert!(
            shibahama
                .memory_items()
                .expect("items should read")
                .is_empty()
        );
        assert!(
            shibahama
                .event_records()
                .expect("events should read")
                .is_empty()
        );
    }

    #[test]
    fn injected_vector_search_failure_is_explicit() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let shibahama = Shibahama::open(
            file.path(),
            FailingVectorIndex {
                dimensions: 2,
                mode: FailingVectorMode::Search,
            },
        )
        .expect("engine should open");
        let request = shibahama.recall_request(&[0.0, 0.0], 1, OffsetDateTime::UNIX_EPOCH);

        let error = shibahama
            .recall(&request)
            .expect_err("injected vector failure should fail recall");

        assert_eq!(error.code(), "SHIBA_VECTOR");
        assert_eq!(error.severity(), ShibahamaErrorSeverity::Fatal);
    }

    #[test]
    fn config_defaults_capture_decay_thresholds_and_tier_budget() {
        let config = ShibahamaConfig::default();
        let thirty_days = 30.0 * 24.0 * 60.0 * 60.0;

        assert!((config.significance.half_life_seconds - thirty_days).abs() < f64::EPSILON);
        assert!((config.significance.warm_threshold - 1.0).abs() < f64::EPSILON);
        assert!((config.significance.hot_threshold - 2.0).abs() < f64::EPSILON);
        assert!(
            (config.recall_staleness.load_bearing_significance_threshold - 2.0).abs()
                < f64::EPSILON
        );
        assert!((config.recall_ranking.recency_weight - 0.25).abs() < f64::EPSILON);
        assert!((config.recall_ranking.graph_weight - 0.25).abs() < f64::EPSILON);
        assert_eq!(config.tier_capacity.hot_capacity, None);
        assert_eq!(config.reconstruction_budget.max_revalidations_per_window, 8);
        assert!(!config.background_reconstruction.validate_on_idle);
        assert_eq!(config.consolidation.min_merge_sources, 2);
        assert_eq!(config.ingest_credence.web, CredenceTier::Unverified);
        assert_eq!(config.forgetting.mode, ForgettingMode::SoftInvalidate);
    }

    #[test]
    fn engine_config_seeds_recall_requests() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut config = ShibahamaConfig::default();
        config.significance.half_life_seconds = 60.0;
        config.recall_ranking.similarity_weight = 2.0;
        config.recall_staleness.load_bearing_significance_threshold = 3.0;
        config.recall_diversification.enabled = false;
        config.tier_capacity.hot_capacity = Some(64);
        config.background_reconstruction.validate_on_idle = true;
        config.ingest_credence.web = CredenceTier::VerifiedSource;
        config.forgetting.mode = ForgettingMode::FlagForReverification;
        let mut shibahama =
            Shibahama::open_with_config(file.path(), HnswVectorIndex::with_capacity(2, 8), config)
                .expect("api should open");
        let query = [0.0, 0.0];
        let request = shibahama.recall_request(&query, 3, OffsetDateTime::UNIX_EPOCH);

        assert!((shibahama.config().significance.half_life_seconds - 60.0).abs() < f64::EPSILON);
        assert!((request.ranking.similarity_weight - 2.0).abs() < f64::EPSILON);
        assert!((request.staleness.load_bearing_significance_threshold - 3.0).abs() < f64::EPSILON);
        assert!(!request.diversification.enabled);
        assert_eq!(shibahama.config().tier_capacity.hot_capacity, Some(64));
        assert!(
            shibahama
                .config()
                .background_reconstruction
                .validate_on_idle
        );
        assert_eq!(
            shibahama.config().ingest_credence.web,
            CredenceTier::VerifiedSource
        );
        assert_eq!(
            shibahama.config().forgetting.mode,
            ForgettingMode::FlagForReverification
        );

        shibahama.set_config(ShibahamaConfig::default());
        assert_eq!(shibahama.config().tier_capacity.hot_capacity, None);
        assert!(
            !shibahama
                .config()
                .background_reconstruction
                .validate_on_idle
        );
        assert_eq!(
            shibahama.config().ingest_credence.web,
            CredenceTier::Unverified
        );
        assert_eq!(
            shibahama.config().forgetting.mode,
            ForgettingMode::SoftInvalidate
        );
    }

    #[test]
    fn streaming_recall_iterates_ranked_candidates() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let mut shibahama = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .expect("api should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let first = shibahama
            .write_with_embedding(
                MemoryWriteEvent::new(
                    "stream alpha",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    now,
                    now,
                ),
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("first write should work");
        shibahama
            .write_with_embedding(
                MemoryWriteEvent::new(
                    "stream beta",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    now,
                    now,
                ),
                WriteEmbedding {
                    vector: &[1.0, 1.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("second write should work");
        shibahama
            .write_with_embedding(
                MemoryWriteEvent::new(
                    "stream gamma",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    now,
                    now,
                ),
                WriteEmbedding {
                    vector: &[2.0, 2.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .expect("third write should work");
        let query = [0.0, 0.0];
        let request = shibahama.recall_request(&query, 3, now);
        let mut stream = shibahama
            .stream_recall(&request)
            .expect("stream recall should work");

        assert_eq!(stream.remaining(), 3);
        assert_eq!(stream.next().expect("first candidate").id, first.id);
        assert_eq!(stream.remaining(), 2);
        assert_eq!(stream.by_ref().count(), 2);
        assert_eq!(stream.remaining(), 0);
        assert!(stream.next().is_none());
    }

    #[cfg(feature = "tokio")]
    #[tokio::test]
    async fn async_facade_write_recall_reinforce_why_and_stream_work() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let shibahama = AsyncShibahama::open(file.path(), HnswVectorIndex::with_capacity(2, 8))
            .await
            .expect("api should open");
        let now = OffsetDateTime::UNIX_EPOCH;
        let item = shibahama
            .write_with_embedding(
                MemoryWriteEvent::new(
                    "async facade memory",
                    Provenance::new(SourceKind::User, None, "api-test"),
                    now,
                    now,
                ),
                WriteEmbedding {
                    vector: &[0.0, 0.0],
                    index_name: "api-test",
                    model: "embedding-model",
                    model_version: "v1",
                },
            )
            .await
            .expect("write should work");
        let request = shibahama.recall_request(vec![0.0, 0.0], 1, now).await;
        let recalled = shibahama
            .recall(request.clone())
            .await
            .expect("recall should work");
        let timeline = shibahama
            .timeline(request.clone())
            .await
            .expect("timeline should work");
        let mut stream = shibahama
            .stream_recall(request)
            .await
            .expect("stream should work");

        assert_eq!(recalled[0].id, item.id);
        assert_eq!(timeline[0].id, item.id);
        assert_eq!(stream.remaining(), 1);
        assert_eq!(stream.next().expect("stream candidate").id, item.id);
        assert!(
            shibahama
                .reinforce(item.id, AccessOutcome::Cited)
                .await
                .expect("reinforce should work")
        );
        assert_eq!(
            shibahama
                .why_at(item.id, now)
                .await
                .expect("why should read")
                .expect("item should exist")
                .item
                .content,
            "async facade memory"
        );
    }

    #[cfg(feature = "tokio")]
    #[tokio::test]
    async fn async_recall_request_copies_supported_sync_request() {
        let query = [0.0, 0.0];
        let sync_request = RecallRequest::new(&query, 4, OffsetDateTime::UNIX_EPOCH)
            .include_cold()
            .include_instructions()
            .with_raw_query_context("hello")
            .with_max_context_tokens(8);
        let async_request = AsyncRecallRequest::try_from_recall_request(&sync_request)
            .expect("request should copy");

        assert_eq!(async_request.query_vector, query);
        assert_eq!(async_request.top_k, 4);
        assert_eq!(async_request.raw_query_context.as_deref(), Some("hello"));
        assert!(async_request.include_cold);
        assert!(async_request.include_instructions);
        assert_eq!(async_request.max_context_tokens, Some(8));

        let gateway = DefaultSanitizingGateway;
        let unsupported = RecallRequest::new(&query, 4, OffsetDateTime::UNIX_EPOCH)
            .with_sanitizing_gateway(&gateway);
        let error = AsyncRecallRequest::try_from_recall_request(&unsupported)
            .expect_err("sync sanitizing gateway should be rejected");

        assert!(matches!(
            error,
            ShibahamaError::InvalidRequest(message)
                if message.contains("sanitizing gateways")
        ));
    }
}
