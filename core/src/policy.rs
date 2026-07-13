// SPDX-License-Identifier: MIT

//! Versioned deterministic capture and recall policy models.

use crate::model::{MemoryScope, ScopeVisibility, SourceKind};
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Schema version for serialized capture and recall policies.
pub const POLICY_SCHEMA_VERSION: u16 = 1;

/// Class of the actor asking Shibahama to capture or recall memory.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PolicyActorClass {
    /// A human directly initiated the operation.
    Human,
    /// An interactive coding agent initiated the operation.
    Agent,
    /// A non-interactive automated workflow initiated the operation.
    Automation,
    /// A trusted host service initiated the operation.
    Service,
}

/// Explicit capture path selected by the caller or integration.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureIntent {
    /// A caller deliberately asked to persist the memory.
    Manual,
    /// A provider produced a candidate that needs review before persistence.
    Suggested,
    /// An integration asks to persist a candidate without interactive review.
    Automatic,
}

/// Operating mode for capture decisions.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureMode {
    /// Permit only explicit manual capture.
    #[default]
    Manual,
    /// Keep provider candidates as review-required suggestions.
    Suggest,
    /// Permit configured automatic capture without calling a provider itself.
    Automatic,
}

/// Result of a deterministic capture-policy evaluation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureDecisionOutcome {
    /// The capture may be persisted.
    Allow,
    /// The capture must be presented for explicit approval before persistence.
    RequireApproval,
    /// The capture must not be persisted.
    Deny,
}

/// Stable reason attached to a capture-policy decision.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureDecisionReason {
    /// The request satisfied the configured constraints.
    Allowed,
    /// Suggestion mode requires an explicit approval step.
    SuggestionRequiresApproval,
    /// The configured mode does not permit this capture intent.
    IntentNotAllowed,
    /// The actor class is not permitted to capture.
    ActorNotAllowed,
    /// The provenance source kind is not permitted to capture.
    SourceNotAllowed,
    /// The memory scope visibility is not permitted to capture.
    ScopeNotAllowed,
    /// The supplied confidence is below the configured threshold.
    ConfidenceTooLow,
}

/// Serializable capture-policy decision without memory content.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CapturePolicyDecision {
    /// Policy schema version evaluated.
    pub policy_version: u16,
    /// Resulting disposition.
    pub outcome: CaptureDecisionOutcome,
    /// Stable explanation for the disposition.
    pub reason: CaptureDecisionReason,
}

/// Failure returned when a capture decision cannot safely persist memory.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum PolicyError {
    /// The configured policy denied the capture request.
    #[error("capture policy denied: {reason:?}")]
    CaptureDenied {
        /// Stable reason for the denial.
        reason: CaptureDecisionReason,
    },
    /// The configured policy requires explicit review before capture.
    #[error("capture policy requires explicit approval")]
    CaptureApprovalRequired,
}

/// Core operation whose policy decision was audited.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PolicyAuditOperation {
    /// A capture/write decision.
    Capture,
    /// A recall/context-assembly decision.
    Recall,
}

/// Final audited disposition of a policy decision.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PolicyAuditDisposition {
    /// The policy allowed the operation.
    Allowed,
    /// The policy held the operation for explicit approval.
    RequiresApproval,
    /// The policy denied the operation.
    Denied,
}

/// Content-free append-only policy audit payload.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PolicyAuditRecord {
    /// Operation evaluated by the policy.
    pub operation: PolicyAuditOperation,
    /// Schema version of the evaluated policy.
    pub policy_version: u16,
    /// Final policy disposition.
    pub disposition: PolicyAuditDisposition,
    /// Stable capture-decision reason, when this is a capture audit.
    pub capture_reason: Option<CaptureDecisionReason>,
    /// Actor class, when this is a capture audit.
    pub actor: Option<PolicyActorClass>,
    /// Provenance source kind, when this is a capture audit.
    pub source_kind: Option<SourceKind>,
    /// Scope associated with the decision, when known.
    pub scope: Option<MemoryScope>,
    /// Requested recall candidate count, when this is a recall audit.
    pub requested_candidates: Option<usize>,
    /// Policy-permitted recall candidate count, when this is a recall audit.
    pub effective_candidates: Option<usize>,
    /// Policy-permitted context token budget, when this is a recall audit.
    pub context_token_budget: Option<usize>,
    /// Actual returned context tokens, when recall completed.
    pub context_tokens_used: Option<usize>,
}

impl CapturePolicyDecision {
    /// Converts this decision into a fail-closed persistence permission.
    ///
    /// # Errors
    ///
    /// Returns [`PolicyError`] unless the policy explicitly allowed the capture.
    pub const fn require_allowed(self) -> Result<(), PolicyError> {
        match self.outcome {
            CaptureDecisionOutcome::Allow => Ok(()),
            CaptureDecisionOutcome::RequireApproval => Err(PolicyError::CaptureApprovalRequired),
            CaptureDecisionOutcome::Deny => Err(PolicyError::CaptureDenied {
                reason: self.reason,
            }),
        }
    }

    /// Builds a content-free audit payload for this capture decision.
    #[must_use]
    pub fn audit_record(
        self,
        request: CapturePolicyRequest,
        source_kind: SourceKind,
        scope: &MemoryScope,
    ) -> PolicyAuditRecord {
        let disposition = match self.outcome {
            CaptureDecisionOutcome::Allow => PolicyAuditDisposition::Allowed,
            CaptureDecisionOutcome::RequireApproval => PolicyAuditDisposition::RequiresApproval,
            CaptureDecisionOutcome::Deny => PolicyAuditDisposition::Denied,
        };

        PolicyAuditRecord {
            operation: PolicyAuditOperation::Capture,
            policy_version: self.policy_version,
            disposition,
            capture_reason: Some(self.reason),
            actor: Some(request.actor),
            source_kind: Some(source_kind),
            scope: Some(scope.clone()),
            requested_candidates: None,
            effective_candidates: None,
            context_token_budget: None,
            context_tokens_used: None,
        }
    }
}

/// Boolean allow-list for actor classes.
#[allow(clippy::struct_excessive_bools)]
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ActorClassPolicy {
    /// Whether direct human actions are allowed.
    pub human: bool,
    /// Whether interactive agents are allowed.
    pub agent: bool,
    /// Whether non-interactive automation is allowed.
    pub automation: bool,
    /// Whether trusted services are allowed.
    pub service: bool,
}

impl Default for ActorClassPolicy {
    fn default() -> Self {
        Self {
            human: true,
            agent: false,
            automation: false,
            service: true,
        }
    }
}

impl ActorClassPolicy {
    /// Returns whether `actor` is allowed.
    #[must_use]
    pub const fn allows(self, actor: PolicyActorClass) -> bool {
        match actor {
            PolicyActorClass::Human => self.human,
            PolicyActorClass::Agent => self.agent,
            PolicyActorClass::Automation => self.automation,
            PolicyActorClass::Service => self.service,
        }
    }
}

/// Boolean allow-list for provenance source kinds.
#[allow(clippy::struct_excessive_bools)]
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SourceKindPolicy {
    /// Whether user-provided observations are allowed.
    pub user: bool,
    /// Whether agent-authored observations are allowed.
    pub agent: bool,
    /// Whether file-backed observations are allowed.
    pub file: bool,
    /// Whether web observations are allowed.
    pub web: bool,
    /// Whether tool observations are allowed.
    pub tool: bool,
}

impl Default for SourceKindPolicy {
    fn default() -> Self {
        Self {
            user: true,
            agent: true,
            file: true,
            web: true,
            tool: true,
        }
    }
}

impl SourceKindPolicy {
    /// Returns whether `source_kind` is allowed.
    #[must_use]
    pub const fn allows(self, source_kind: SourceKind) -> bool {
        match source_kind {
            SourceKind::User => self.user,
            SourceKind::Agent => self.agent,
            SourceKind::File => self.file,
            SourceKind::Web => self.web,
            SourceKind::Tool => self.tool,
        }
    }
}

/// Visibility allow-list shared by capture and recall policies.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ScopePolicy {
    /// Whether repository-local memory is allowed.
    pub repository: bool,
    /// Whether explicitly shared team memory is allowed.
    pub team: bool,
}

impl Default for ScopePolicy {
    fn default() -> Self {
        Self {
            repository: true,
            team: true,
        }
    }
}

impl ScopePolicy {
    /// Returns whether `scope` is allowed by visibility.
    #[must_use]
    pub const fn allows(self, scope: &MemoryScope) -> bool {
        match scope.visibility {
            ScopeVisibility::Repository => self.repository,
            ScopeVisibility::Team => self.team,
        }
    }
}

/// Caller-supplied metadata for one capture decision.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CapturePolicyRequest {
    /// Actor class requesting capture.
    pub actor: PolicyActorClass,
    /// Capture path being requested.
    pub intent: CaptureIntent,
    /// Caller-assessed confidence in percent, from 0 through 100.
    pub confidence_percent: u8,
}

impl CapturePolicyRequest {
    /// Creates a direct human manual-capture request with full confidence.
    #[must_use]
    pub const fn manual() -> Self {
        Self {
            actor: PolicyActorClass::Human,
            intent: CaptureIntent::Manual,
            confidence_percent: 100,
        }
    }
}

/// Independent, deterministic capture policy.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CapturePolicy {
    /// Version used to decode and audit this policy.
    pub version: u16,
    /// Capture operating mode.
    pub mode: CaptureMode,
    /// Actor classes permitted to request capture.
    pub actors: ActorClassPolicy,
    /// Provenance source kinds permitted to capture.
    pub sources: SourceKindPolicy,
    /// Memory visibility classes permitted to capture.
    pub scopes: ScopePolicy,
    /// Minimum required confidence in percent, from 0 through 100.
    pub minimum_confidence_percent: u8,
}

impl Default for CapturePolicy {
    fn default() -> Self {
        Self {
            version: POLICY_SCHEMA_VERSION,
            mode: CaptureMode::Manual,
            actors: ActorClassPolicy::default(),
            sources: SourceKindPolicy::default(),
            scopes: ScopePolicy::default(),
            minimum_confidence_percent: 0,
        }
    }
}

impl CapturePolicy {
    /// Deterministically evaluates a capture without calling a provider or mutating storage.
    #[must_use]
    pub fn evaluate(
        self,
        request: CapturePolicyRequest,
        source_kind: SourceKind,
        scope: &MemoryScope,
    ) -> CapturePolicyDecision {
        let reason = if !self.actors.allows(request.actor) {
            CaptureDecisionReason::ActorNotAllowed
        } else if !self.sources.allows(source_kind) {
            CaptureDecisionReason::SourceNotAllowed
        } else if !self.scopes.allows(scope) {
            CaptureDecisionReason::ScopeNotAllowed
        } else if request.confidence_percent < self.minimum_confidence_percent {
            CaptureDecisionReason::ConfidenceTooLow
        } else {
            match (self.mode, request.intent) {
                (CaptureMode::Manual | CaptureMode::Suggest, CaptureIntent::Manual)
                | (CaptureMode::Automatic, CaptureIntent::Manual | CaptureIntent::Automatic) => {
                    CaptureDecisionReason::Allowed
                }
                (CaptureMode::Suggest, CaptureIntent::Suggested) => {
                    CaptureDecisionReason::SuggestionRequiresApproval
                }
                (CaptureMode::Manual, CaptureIntent::Suggested | CaptureIntent::Automatic)
                | (CaptureMode::Suggest, CaptureIntent::Automatic)
                | (CaptureMode::Automatic, CaptureIntent::Suggested) => {
                    CaptureDecisionReason::IntentNotAllowed
                }
            }
        };
        let outcome = match reason {
            CaptureDecisionReason::Allowed => CaptureDecisionOutcome::Allow,
            CaptureDecisionReason::SuggestionRequiresApproval => {
                CaptureDecisionOutcome::RequireApproval
            }
            CaptureDecisionReason::IntentNotAllowed
            | CaptureDecisionReason::ActorNotAllowed
            | CaptureDecisionReason::SourceNotAllowed
            | CaptureDecisionReason::ScopeNotAllowed
            | CaptureDecisionReason::ConfidenceTooLow => CaptureDecisionOutcome::Deny,
        };

        CapturePolicyDecision {
            policy_version: self.version,
            outcome,
            reason,
        }
    }
}

/// Independent recall/context-assembly operating mode.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecallMode {
    /// Recall happens only through an explicit request.
    #[default]
    Manual,
    /// A caller may prepare a reviewable recall suggestion.
    Suggest,
    /// A configured worker may assemble context automatically.
    Automatic,
}

/// Independent recall policy and resource budget.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RecallPolicy {
    /// Version used to decode and audit this policy.
    pub version: u16,
    /// Recall operating mode.
    pub mode: RecallMode,
    /// Maximum candidates inspected and returned.
    pub max_candidates: usize,
    /// Maximum approximate whitespace tokens returned as context.
    pub max_context_tokens: usize,
    /// Memory visibility classes permitted for recall.
    pub scopes: ScopePolicy,
    /// Whether a request may include cold-tier memory.
    pub allow_cold: bool,
    /// Whether a request may include instruction memories.
    pub allow_instructions: bool,
}

impl Default for RecallPolicy {
    fn default() -> Self {
        Self {
            version: POLICY_SCHEMA_VERSION,
            mode: RecallMode::Manual,
            max_candidates: 8,
            max_context_tokens: 2_048,
            scopes: ScopePolicy::default(),
            allow_cold: false,
            allow_instructions: false,
        }
    }
}

/// Effective recall limits selected by a deterministic policy evaluation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RecallPolicyDecision {
    /// Policy schema version evaluated.
    pub policy_version: u16,
    /// Candidate count requested by the caller.
    pub requested_candidates: usize,
    /// Candidate count permitted by the policy.
    pub effective_candidates: usize,
    /// Caller token budget, when supplied.
    pub requested_context_tokens: Option<usize>,
    /// Token budget enforced by the policy.
    pub effective_context_tokens: usize,
    /// Scope visibility classes permitted by the policy.
    pub allowed_scopes: ScopePolicy,
    /// Whether cold-tier recall remains enabled after policy enforcement.
    pub include_cold: bool,
    /// Whether instruction recall remains enabled after policy enforcement.
    pub include_instructions: bool,
}

/// Pure capture-policy simulation result.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CapturePolicySimulation {
    /// Decision that live capture evaluation would produce for the same inputs.
    pub decision: CapturePolicyDecision,
}

/// Pure recall-policy simulation result.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RecallPolicySimulation {
    /// Decision that live recall evaluation would produce for the same inputs.
    pub decision: RecallPolicyDecision,
    /// Whether the requested scope is permitted by the effective scope policy.
    pub scope_allowed: bool,
}

impl RecallPolicy {
    /// Applies this policy to caller-provided recall limits without performing retrieval.
    #[must_use]
    pub fn decide(
        self,
        requested_candidates: usize,
        requested_context_tokens: Option<usize>,
        include_cold: bool,
        include_instructions: bool,
    ) -> RecallPolicyDecision {
        let effective_context_tokens = match requested_context_tokens {
            Some(requested) if requested < self.max_context_tokens => requested,
            Some(_) | None => self.max_context_tokens,
        };

        RecallPolicyDecision {
            policy_version: self.version,
            requested_candidates,
            effective_candidates: requested_candidates.min(self.max_candidates),
            requested_context_tokens,
            effective_context_tokens,
            allowed_scopes: self.scopes,
            include_cold: include_cold && self.allow_cold,
            include_instructions: include_instructions && self.allow_instructions,
        }
    }
}

impl RecallPolicyDecision {
    /// Builds a content-free audit payload for this recall decision.
    #[must_use]
    pub fn audit_record(
        self,
        scope: Option<&MemoryScope>,
        disposition: PolicyAuditDisposition,
        context_tokens_used: Option<usize>,
    ) -> PolicyAuditRecord {
        PolicyAuditRecord {
            operation: PolicyAuditOperation::Recall,
            policy_version: self.policy_version,
            disposition,
            capture_reason: None,
            actor: None,
            source_kind: None,
            scope: scope.cloned(),
            requested_candidates: Some(self.requested_candidates),
            effective_candidates: Some(self.effective_candidates),
            context_token_budget: Some(self.effective_context_tokens),
            context_tokens_used,
        }
    }
}

/// Partial boolean overrides for actor-class permissions.
#[allow(clippy::struct_excessive_bools)]
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct ActorClassPolicyOverride {
    /// Override for direct human actions.
    pub human: Option<bool>,
    /// Override for interactive agents.
    pub agent: Option<bool>,
    /// Override for non-interactive automation.
    pub automation: Option<bool>,
    /// Override for trusted services.
    pub service: Option<bool>,
}

/// Partial boolean overrides for provenance source-kind permissions.
#[allow(clippy::struct_excessive_bools)]
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct SourceKindPolicyOverride {
    /// Override for user-provided observations.
    pub user: Option<bool>,
    /// Override for agent-authored observations.
    pub agent: Option<bool>,
    /// Override for file-backed observations.
    pub file: Option<bool>,
    /// Override for web observations.
    pub web: Option<bool>,
    /// Override for tool observations.
    pub tool: Option<bool>,
}

/// Partial boolean overrides for scope-visibility permissions.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct ScopePolicyOverride {
    /// Override for repository-local memory.
    pub repository: Option<bool>,
    /// Override for team-shared memory.
    pub team: Option<bool>,
}

/// Partial capture-policy settings for one inheritance layer.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct CapturePolicyOverride {
    /// Override for capture operating mode.
    pub mode: Option<CaptureMode>,
    /// Actor-class permission overrides.
    pub actors: ActorClassPolicyOverride,
    /// Provenance source-kind permission overrides.
    pub sources: SourceKindPolicyOverride,
    /// Scope visibility permission overrides.
    pub scopes: ScopePolicyOverride,
    /// Override for the minimum capture confidence.
    pub minimum_confidence_percent: Option<u8>,
}

/// Partial recall-policy settings for one inheritance layer.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct RecallPolicyOverride {
    /// Override for recall operating mode.
    pub mode: Option<RecallMode>,
    /// Override for the maximum candidate count.
    pub max_candidates: Option<usize>,
    /// Override for the maximum context-token budget.
    pub max_context_tokens: Option<usize>,
    /// Scope visibility permission overrides.
    pub scopes: ScopePolicyOverride,
    /// Override for cold-tier recall permission.
    pub allow_cold: Option<bool>,
    /// Override for instruction-memory recall permission.
    pub allow_instructions: Option<bool>,
}

/// One redaction-safe policy configuration layer.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct PolicyLayer {
    /// Capture settings configured by this layer.
    pub capture: CapturePolicyOverride,
    /// Recall settings configured by this layer.
    pub recall: RecallPolicyOverride,
}

impl PolicyLayer {
    /// Returns whether this layer contains any configured override.
    #[must_use]
    pub const fn is_empty(self) -> bool {
        self.capture.mode.is_none()
            && self.capture.actors.human.is_none()
            && self.capture.actors.agent.is_none()
            && self.capture.actors.automation.is_none()
            && self.capture.actors.service.is_none()
            && self.capture.sources.user.is_none()
            && self.capture.sources.agent.is_none()
            && self.capture.sources.file.is_none()
            && self.capture.sources.web.is_none()
            && self.capture.sources.tool.is_none()
            && self.capture.scopes.repository.is_none()
            && self.capture.scopes.team.is_none()
            && self.capture.minimum_confidence_percent.is_none()
            && self.recall.mode.is_none()
            && self.recall.max_candidates.is_none()
            && self.recall.max_context_tokens.is_none()
            && self.recall.scopes.repository.is_none()
            && self.recall.scopes.team.is_none()
            && self.recall.allow_cold.is_none()
            && self.recall.allow_instructions.is_none()
    }
}

/// Scoped layers applied after the global engine policy.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct PolicyLayerSet {
    /// Optional team-wide settings.
    pub team: Option<PolicyLayer>,
    /// Optional repository-specific settings.
    pub repository: Option<PolicyLayer>,
    /// Optional session-specific settings.
    pub session: Option<PolicyLayer>,
}

/// Redacted identity of a layer contributing to an effective policy.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PolicyLayerSource {
    /// Engine-global configuration.
    Global,
    /// Team-wide configuration; team identity is intentionally omitted.
    Team,
    /// Repository-specific configuration; repository identity is intentionally omitted.
    Repository,
    /// Per-session configuration; session identity is intentionally omitted.
    Session,
}

/// Resolved policies with redacted layer provenance.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EffectivePolicy {
    /// Effective capture policy.
    pub capture: CapturePolicy,
    /// Effective recall policy.
    pub recall: RecallPolicy,
    /// Ordered source layers that contributed settings, without identifiers or secrets.
    pub source_layers: Vec<PolicyLayerSource>,
}

/// Resolves global, team, repository, and session settings into one effective policy.
///
/// Scalar mode precedence is global, team, repository, then session. Explicit `false` values are
/// monotonic denies: no later layer can re-enable them. Minimum confidence is tightened by the
/// maximum value, while recall candidate and token budgets are tightened by the minimum value.
#[must_use]
pub fn resolve_policy_inheritance(
    global_capture: CapturePolicy,
    global_recall: RecallPolicy,
    layers: &PolicyLayerSet,
) -> EffectivePolicy {
    let ordered = [layers.team, layers.repository, layers.session];
    let capture = resolve_capture_policy(global_capture, ordered);
    let recall = resolve_recall_policy(global_recall, ordered);
    let mut source_layers = vec![PolicyLayerSource::Global];

    for (source, layer) in [
        (PolicyLayerSource::Team, layers.team),
        (PolicyLayerSource::Repository, layers.repository),
        (PolicyLayerSource::Session, layers.session),
    ] {
        if layer.is_some_and(|layer| !layer.is_empty()) {
            source_layers.push(source);
        }
    }

    EffectivePolicy {
        capture,
        recall,
        source_layers,
    }
}

fn resolve_capture_policy(base: CapturePolicy, layers: [Option<PolicyLayer>; 3]) -> CapturePolicy {
    let configured = layers.into_iter().flatten().collect::<Vec<_>>();

    CapturePolicy {
        version: base.version,
        mode: configured
            .iter()
            .filter_map(|layer| layer.capture.mode)
            .next_back()
            .unwrap_or(base.mode),
        actors: ActorClassPolicy {
            human: resolve_permission(
                base.actors.human,
                configured.iter().map(|layer| layer.capture.actors.human),
            ),
            agent: resolve_permission(
                base.actors.agent,
                configured.iter().map(|layer| layer.capture.actors.agent),
            ),
            automation: resolve_permission(
                base.actors.automation,
                configured
                    .iter()
                    .map(|layer| layer.capture.actors.automation),
            ),
            service: resolve_permission(
                base.actors.service,
                configured.iter().map(|layer| layer.capture.actors.service),
            ),
        },
        sources: SourceKindPolicy {
            user: resolve_permission(
                base.sources.user,
                configured.iter().map(|layer| layer.capture.sources.user),
            ),
            agent: resolve_permission(
                base.sources.agent,
                configured.iter().map(|layer| layer.capture.sources.agent),
            ),
            file: resolve_permission(
                base.sources.file,
                configured.iter().map(|layer| layer.capture.sources.file),
            ),
            web: resolve_permission(
                base.sources.web,
                configured.iter().map(|layer| layer.capture.sources.web),
            ),
            tool: resolve_permission(
                base.sources.tool,
                configured.iter().map(|layer| layer.capture.sources.tool),
            ),
        },
        scopes: ScopePolicy {
            repository: resolve_permission(
                base.scopes.repository,
                configured
                    .iter()
                    .map(|layer| layer.capture.scopes.repository),
            ),
            team: resolve_permission(
                base.scopes.team,
                configured.iter().map(|layer| layer.capture.scopes.team),
            ),
        },
        minimum_confidence_percent: configured
            .iter()
            .filter_map(|layer| layer.capture.minimum_confidence_percent)
            .fold(base.minimum_confidence_percent, u8::max),
    }
}

fn resolve_recall_policy(base: RecallPolicy, layers: [Option<PolicyLayer>; 3]) -> RecallPolicy {
    let configured = layers.into_iter().flatten().collect::<Vec<_>>();

    RecallPolicy {
        version: base.version,
        mode: configured
            .iter()
            .filter_map(|layer| layer.recall.mode)
            .next_back()
            .unwrap_or(base.mode),
        max_candidates: configured
            .iter()
            .filter_map(|layer| layer.recall.max_candidates)
            .fold(base.max_candidates, usize::min),
        max_context_tokens: configured
            .iter()
            .filter_map(|layer| layer.recall.max_context_tokens)
            .fold(base.max_context_tokens, usize::min),
        scopes: ScopePolicy {
            repository: resolve_permission(
                base.scopes.repository,
                configured
                    .iter()
                    .map(|layer| layer.recall.scopes.repository),
            ),
            team: resolve_permission(
                base.scopes.team,
                configured.iter().map(|layer| layer.recall.scopes.team),
            ),
        },
        allow_cold: resolve_permission(
            base.allow_cold,
            configured.iter().map(|layer| layer.recall.allow_cold),
        ),
        allow_instructions: resolve_permission(
            base.allow_instructions,
            configured
                .iter()
                .map(|layer| layer.recall.allow_instructions),
        ),
    }
}

fn resolve_permission(
    base: bool,
    overrides: impl DoubleEndedIterator<Item = Option<bool>> + Clone,
) -> bool {
    if !base || overrides.clone().any(|value| value == Some(false)) {
        return false;
    }

    overrides.flatten().next_back().unwrap_or(base)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::ScopeId;
    use proptest::prelude::*;

    #[test]
    fn policies_are_versioned_and_serializable() -> Result<(), serde_json::Error> {
        let capture = CapturePolicy::default();
        let recall = RecallPolicy::default();

        assert_eq!(capture.version, POLICY_SCHEMA_VERSION);
        assert_eq!(recall.version, POLICY_SCHEMA_VERSION);
        assert_eq!(
            serde_json::from_str::<CapturePolicy>(&serde_json::to_string(&capture)?)?,
            capture
        );
        assert_eq!(
            serde_json::from_str::<RecallPolicy>(&serde_json::to_string(&recall)?)?,
            recall
        );

        Ok(())
    }

    #[test]
    fn capture_modes_are_explicit_and_provider_free() -> Result<(), crate::model::ScopeError> {
        let scope = MemoryScope::repository(ScopeId::new("repo")?);
        let manual = CapturePolicy::default();
        let suggested = CapturePolicy {
            mode: CaptureMode::Suggest,
            ..manual
        };
        let automatic = CapturePolicy {
            mode: CaptureMode::Automatic,
            actors: ActorClassPolicy {
                automation: true,
                ..manual.actors
            },
            ..manual
        };

        assert_eq!(
            manual
                .evaluate(CapturePolicyRequest::manual(), SourceKind::Agent, &scope)
                .outcome,
            CaptureDecisionOutcome::Allow
        );

        assert_eq!(
            manual
                .evaluate(
                    CapturePolicyRequest {
                        intent: CaptureIntent::Automatic,
                        ..CapturePolicyRequest::manual()
                    },
                    SourceKind::Agent,
                    &scope
                )
                .outcome,
            CaptureDecisionOutcome::Deny
        );
        assert_eq!(
            suggested
                .evaluate(
                    CapturePolicyRequest {
                        intent: CaptureIntent::Suggested,
                        ..CapturePolicyRequest::manual()
                    },
                    SourceKind::Agent,
                    &scope
                )
                .outcome,
            CaptureDecisionOutcome::RequireApproval
        );
        assert_eq!(
            automatic
                .evaluate(
                    CapturePolicyRequest {
                        actor: PolicyActorClass::Automation,
                        intent: CaptureIntent::Automatic,
                        confidence_percent: 100
                    },
                    SourceKind::Agent,
                    &scope
                )
                .outcome,
            CaptureDecisionOutcome::Allow
        );

        Ok(())
    }

    #[test]
    fn recall_policy_clamps_budget_and_never_enables_instructions_by_default() {
        let decision = RecallPolicy::default().decide(20, Some(3_000), true, true);

        assert_eq!(decision.effective_candidates, 8);
        assert_eq!(decision.effective_context_tokens, 2_048);
        assert!(!decision.include_cold);
        assert!(!decision.include_instructions);
    }

    #[test]
    fn inheritance_is_ordered_and_explicit_denies_cannot_be_reenabled() {
        let global_capture = CapturePolicy {
            actors: ActorClassPolicy {
                agent: true,
                ..ActorClassPolicy::default()
            },
            minimum_confidence_percent: 20,
            ..CapturePolicy::default()
        };
        let global_recall = RecallPolicy {
            max_candidates: 20,
            max_context_tokens: 5_000,
            allow_cold: true,
            allow_instructions: true,
            ..RecallPolicy::default()
        };
        let layers = PolicyLayerSet {
            team: Some(PolicyLayer {
                capture: CapturePolicyOverride {
                    actors: ActorClassPolicyOverride {
                        agent: Some(false),
                        ..ActorClassPolicyOverride::default()
                    },
                    minimum_confidence_percent: Some(45),
                    ..CapturePolicyOverride::default()
                },
                recall: RecallPolicyOverride {
                    max_candidates: Some(12),
                    allow_cold: Some(false),
                    ..RecallPolicyOverride::default()
                },
            }),
            repository: Some(PolicyLayer {
                capture: CapturePolicyOverride {
                    mode: Some(CaptureMode::Suggest),
                    actors: ActorClassPolicyOverride {
                        agent: Some(true),
                        ..ActorClassPolicyOverride::default()
                    },
                    ..CapturePolicyOverride::default()
                },
                recall: RecallPolicyOverride {
                    max_candidates: Some(16),
                    allow_cold: Some(true),
                    ..RecallPolicyOverride::default()
                },
            }),
            session: Some(PolicyLayer {
                capture: CapturePolicyOverride {
                    mode: Some(CaptureMode::Automatic),
                    ..CapturePolicyOverride::default()
                },
                recall: RecallPolicyOverride {
                    max_candidates: Some(4),
                    max_context_tokens: Some(100),
                    allow_instructions: Some(false),
                    ..RecallPolicyOverride::default()
                },
            }),
        };

        let effective = resolve_policy_inheritance(global_capture, global_recall, &layers);

        assert_eq!(effective.capture.mode, CaptureMode::Automatic);
        assert!(!effective.capture.actors.agent);
        assert_eq!(effective.capture.minimum_confidence_percent, 45);
        assert_eq!(effective.recall.max_candidates, 4);
        assert_eq!(effective.recall.max_context_tokens, 100);
        assert!(!effective.recall.allow_cold);
        assert!(!effective.recall.allow_instructions);
        assert_eq!(
            effective.source_layers,
            vec![
                PolicyLayerSource::Global,
                PolicyLayerSource::Team,
                PolicyLayerSource::Repository,
                PolicyLayerSource::Session,
            ]
        );
    }

    proptest! {
        #[test]
        fn automatic_capture_never_bypasses_denied_actor_source_scope_or_confidence(
            allow_actor in any::<bool>(),
            allow_source in any::<bool>(),
            allow_scope in any::<bool>(),
            minimum_confidence in 0u8..=100,
            confidence in 0u8..=100,
        ) {
            let scope = MemoryScope::repository(ScopeId::new("property-repo").expect("constant scope should validate"));
            let policy = CapturePolicy {
                mode: CaptureMode::Automatic,
                actors: ActorClassPolicy {
                    automation: allow_actor,
                    ..ActorClassPolicy::default()
                },
                sources: SourceKindPolicy {
                    agent: allow_source,
                    ..SourceKindPolicy::default()
                },
                scopes: ScopePolicy {
                    repository: allow_scope,
                    ..ScopePolicy::default()
                },
                minimum_confidence_percent: minimum_confidence,
                ..CapturePolicy::default()
            };
            let decision = policy.evaluate(
                CapturePolicyRequest {
                    actor: PolicyActorClass::Automation,
                    intent: CaptureIntent::Automatic,
                    confidence_percent: confidence,
                },
                SourceKind::Agent,
                &scope,
            );

            if !allow_actor || !allow_source || !allow_scope || confidence < minimum_confidence {
                prop_assert_eq!(decision.outcome, CaptureDecisionOutcome::Deny);
            } else {
                prop_assert_eq!(decision.outcome, CaptureDecisionOutcome::Allow);
            }
        }

        #[test]
        fn recall_limits_never_expand_past_policy(
            max_candidates in 0usize..64,
            max_tokens in 0usize..4096,
            requested_candidates in 0usize..128,
            requested_tokens in proptest::option::of(0usize..8192),
            allow_cold in any::<bool>(),
            allow_instructions in any::<bool>(),
        ) {
            let policy = RecallPolicy {
                max_candidates,
                max_context_tokens: max_tokens,
                allow_cold,
                allow_instructions,
                ..RecallPolicy::default()
            };
            let decision = policy.decide(requested_candidates, requested_tokens, true, true);

            prop_assert!(decision.effective_candidates <= max_candidates);
            prop_assert!(decision.effective_context_tokens <= max_tokens);
            prop_assert_eq!(decision.include_cold, allow_cold);
            prop_assert_eq!(decision.include_instructions, allow_instructions);
        }
    }
}
