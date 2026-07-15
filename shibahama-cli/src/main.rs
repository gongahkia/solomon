// SPDX-License-Identifier: MIT

//! Command-line entry point for Shibahama.

#![allow(clippy::needless_pass_by_value)]

mod mcp;
mod mcp_resources;
mod mcp_tools;
mod oidc;

use axum::body::Bytes;
use axum::extract::{MatchedPath, Path as AxumPath, Query, Request, State};
use axum::http::header::{ACCEPT, AUTHORIZATION, CONTENT_TYPE, HeaderName, ORIGIN, RETRY_AFTER};
use axum::http::{HeaderMap, HeaderValue, Method, StatusCode};
use axum::middleware::{self, Next};
use axum::response::sse::{Event as SseEvent, KeepAlive, Sse};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use clap::{Args, Parser, Subcommand, ValueEnum};
use serde::{Deserialize, Serialize};
use serde_json::json;
use shibahama_core::api::{
    ConsolidationPassReport, ForgettingConfig, ForgettingMode, HumanCorrectionOutcome,
    HumanSignalOutcome, HumanSignalRequest, SemanticErasureRequest, Shibahama, ShibahamaConfig,
    ShibahamaErrorMetadata, WhyTrace, WriteEmbedding,
};
use shibahama_core::encryption::{EnvelopeEncryption, LocalKeyProvider};
use shibahama_core::model::{
    AccessOutcome, ConsolidationAction, ConsolidationWhy, CredenceTier, Entity, EntityId,
    HumanSignal, HumanSignalAction, MemoryId, MemoryItem, MemoryKind, MemoryScope, Provenance,
    Relation, RelationId, ScopeId, ScopeVisibility, SourceKind, TemporalBounds, Tier,
};
use shibahama_core::policy::{CaptureIntent, CapturePolicyRequest, PolicyActorClass};
use shibahama_core::retrieval::{
    RecallCandidate, RecallCandidateCurrency, RecallCandidateSource, RecallRequest,
    RecallUnavailableStage,
};
use shibahama_core::significance::SignificanceBreakdown;
use shibahama_core::storage::{
    AdministrationAuditRecord, AdministrationBootstrapOutcome, AdministrationRecoveryOutcome,
    AuthorizationAction, AuthorizationAuditRecord, AuthorizationPrincipalClass, EventRecord,
    GraphTraversalRequest, GraphTraversalResult, MemoryEvent, MemoryWriteEvent, RbacGrant,
    RbacRole, RedbMemoryStore, ServiceToken, ServiceTokenAuditRecord, ServiceTokenStoredMaterial,
};
use shibahama_core::vector::HnswVectorIndex;
use std::collections::{BTreeMap, BTreeSet};
use std::convert::Infallible;
use std::env;
use std::error::Error;
use std::fmt::{self, Display, Formatter};
use std::io::{self, Write};
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use time::OffsetDateTime;
use tokio_stream::Stream;
use tokio_stream::StreamExt;
use tokio_stream::wrappers::IntervalStream;
use tower_http::cors::CorsLayer;
use url::Url;
use uuid::Uuid;

use crate::oidc::{OidcAuthenticator, OidcConfig};

type CliResult<T> = Result<T, Box<dyn Error>>;

const ADMIN_BOOTSTRAP_SECRET_DOMAIN: &[u8] = b"shibahama:admin:bootstrap-secret:v1";
const ADMIN_RECOVERY_SECRET_DOMAIN: &[u8] = b"shibahama:admin:recovery-secret:v1";
const SERVICE_TOKEN_SECRET_DOMAIN: &[u8] = b"shibahama:service-token:bearer:v1";
const SERVICE_TOKEN_PREFIX: &str = "shb_at_";
const OPERATIONAL_LOG_SCHEMA_VERSION: u32 = 1;
const OPERATIONAL_LOG_SCOPE_DOMAIN: &[u8] = b"shibahama:operational-log:scope:v1";

#[derive(Clone)]
struct ServerRequestLogContext {
    started_at: Instant,
    emitted: Arc<AtomicBool>,
    scope_hash_key: [u8; 32],
}

tokio::task_local! {
    static SERVER_REQUEST_LOG_CONTEXT: ServerRequestLogContext;
}

#[derive(Parser)]
#[command(author, version, about = "Shibahama memory engine CLI")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
#[allow(clippy::large_enum_variant)]
enum Command {
    /// Initialise or open a store.
    Init(StoreCommand),
    /// Write a memory item.
    Write(WriteCommand),
    /// Recall memories for a query embedding.
    Recall(RecallCommand),
    /// Record a usage outcome for a memory.
    Reinforce(ReinforceCommand),
    /// Explain why a memory has its current state.
    Why(WhyCommand),
    /// Run the offline consolidation pass.
    Consolidate(ConsolidateCommand),
    /// Challenge a memory and flag it for review.
    Challenge(HumanSignalCommand),
    /// Affirm a memory.
    Affirm(HumanSignalCommand),
    /// Correct a memory through quarantine and reconstruction.
    Correct(CorrectCommand),
    /// Pin a memory's credence floor.
    Pin(HumanSignalCommand),
    /// Remove a human credence-floor pin.
    Unpin(HumanSignalCommand),
    /// Export durable event-log records.
    Events(EventsCommand),
    /// Inspect the audit trail for one memory.
    Audit(AuditCommand),
    /// Inspect current materialized memory state.
    Inspect(InspectCommand),
    /// Export materialized memory state.
    Export(ExportCommand),
    /// Start the optional HTTP server mode.
    Serve(ServeCommand),
    /// Start the local Model Context Protocol server over stdio.
    Mcp(McpCommand),
}

#[derive(Args)]
struct StoreArgs {
    /// Store path.
    #[arg(long, default_value = "shibahama.redb")]
    path: PathBuf,
    /// Vector dimensions. Defaults to vector length when a vector is supplied.
    #[arg(long)]
    dimensions: Option<usize>,
    /// In-memory HNSW index capacity.
    #[arg(long, default_value_t = 1024)]
    capacity: usize,
}

#[derive(Args)]
struct StoreCommand {
    #[command(flatten)]
    store: StoreArgs,
}

#[derive(Args)]
struct WriteCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Memory content.
    #[arg(long)]
    content: String,
    /// Optional embedding vector, e.g. "0.1,0.2".
    #[arg(long)]
    vector: Option<String>,
    /// Provenance source kind.
    #[arg(long, default_value = "user")]
    source_kind: String,
    /// Optional source reference.
    #[arg(long)]
    source_ref: Option<String>,
    /// Ingesting actor or integration.
    #[arg(long, default_value = "cli")]
    ingested_by: String,
    /// Valid-time start as Unix seconds.
    #[arg(long)]
    valid_from_unix: Option<i64>,
    /// Ingestion time as Unix seconds.
    #[arg(long)]
    ingested_at_unix: Option<i64>,
    /// Memory kind: fact or instruction.
    #[arg(long, default_value = "fact")]
    kind: String,
    /// Vector index name.
    #[arg(long, default_value = "default")]
    index_name: String,
    /// Embedding model name.
    #[arg(long, default_value = "unknown")]
    model: String,
    /// Embedding model version.
    #[arg(long, default_value = "unknown")]
    model_version: String,
}

#[derive(Args)]
struct RecallCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Query embedding vector, e.g. "0.1,0.2".
    #[arg(long)]
    query_vector: String,
    /// Number of candidates to return.
    #[arg(long, default_value_t = 5)]
    top_k: usize,
    /// Recall instant as Unix seconds.
    #[arg(long)]
    now_unix: Option<i64>,
    /// Raw query/context text to hash into surfaced access events.
    #[arg(long)]
    raw_query_context: Option<String>,
    /// Include cold-tier memories.
    #[arg(long)]
    include_cold: bool,
    /// Include instruction memories.
    #[arg(long)]
    include_instructions: bool,
    /// Maximum approximate whitespace tokens of recalled context to return.
    #[arg(long)]
    max_context_tokens: Option<usize>,
}

#[derive(Args)]
struct ReinforceCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Memory id to reinforce.
    #[arg(long)]
    memory_id: String,
    /// Access outcome: surfaced, `led_somewhere`, cited, ignored, or contradicted.
    #[arg(long, default_value = "cited")]
    outcome: String,
}

#[derive(Args)]
struct WhyCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Memory id to explain.
    #[arg(long)]
    memory_id: String,
    /// Explanation instant as Unix seconds.
    #[arg(long)]
    now_unix: Option<i64>,
    /// Output format.
    #[arg(long, default_value = "text")]
    format: WhyFormat,
}

#[derive(Args)]
struct ConsolidateCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Consolidation instant as Unix seconds.
    #[arg(long)]
    now_unix: Option<i64>,
}

#[derive(Args)]
struct HumanSignalCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Memory id to update.
    #[arg(long)]
    memory_id: String,
    /// Human-readable reason.
    #[arg(long)]
    reason: String,
    /// Actor supplying the signal.
    #[arg(long, default_value = "cli")]
    actor: String,
    /// Signal timestamp as Unix seconds.
    #[arg(long)]
    timestamp_unix: Option<i64>,
}

#[derive(Args)]
struct CorrectCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Memory id to correct.
    #[arg(long)]
    memory_id: String,
    /// Proposed replacement content.
    #[arg(long)]
    proposed_content: String,
    /// Human-readable reason.
    #[arg(long, default_value = "corrected")]
    reason: String,
    /// Actor supplying the correction.
    #[arg(long, default_value = "cli")]
    actor: String,
    /// Signal timestamp as Unix seconds.
    #[arg(long)]
    timestamp_unix: Option<i64>,
}

#[derive(Args)]
struct EventsCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Maximum records to return from the end of the event log.
    #[arg(long)]
    limit: Option<usize>,
}

#[derive(Args)]
struct AuditCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Memory id to audit.
    #[arg(long)]
    memory_id: String,
}

#[derive(Args)]
struct InspectCommand {
    #[command(flatten)]
    store: StoreArgs,
}

#[derive(Args)]
struct ExportCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Export format.
    #[arg(long, default_value = "json")]
    format: ExportFormat,
}

#[derive(Args)]
#[allow(clippy::struct_excessive_bools)]
struct ServeCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Address to bind.
    #[arg(long, default_value = "127.0.0.1:8765")]
    bind: SocketAddr,
    /// Default namespace when x-shibahama-namespace is absent.
    #[arg(long, default_value = "default")]
    namespace: String,
    /// Optional API key. Also falls back to `SHIBAHAMA_API_KEY`.
    #[arg(long)]
    api_key: Option<String>,
    /// Exact HTTPS OIDC issuer. Also falls back to `SHIBAHAMA_OIDC_ISSUER`.
    #[arg(long)]
    oidc_issuer: Option<String>,
    /// Required OIDC audience/client identifier. Also falls back to `SHIBAHAMA_OIDC_AUDIENCE`.
    #[arg(long)]
    oidc_audience: Option<String>,
    /// OIDC string claim mapped to the opaque internal principal. Defaults to `sub`.
    #[arg(long)]
    oidc_principal_claim: Option<String>,
    /// Additional PEM root certificate trusted only for OIDC discovery and JWKS retrieval.
    #[arg(long)]
    oidc_ca_certificate: Option<PathBuf>,
    /// One-time first-administrator secret. Also falls back to `SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET`.
    #[arg(long)]
    admin_bootstrap_secret: Option<String>,
    /// Bootstrap window duration in seconds. Defaults to 15 minutes.
    #[arg(long, default_value_t = 900)]
    admin_bootstrap_ttl_seconds: u64,
    /// Recovery secret required to replace the initialized administrator. Also falls back to `SHIBAHAMA_ADMIN_RECOVERY_SECRET`.
    #[arg(long)]
    admin_recovery_secret: Option<String>,
    /// Require scoped RBAC grants even before bootstrap administration is initialized.
    #[arg(long)]
    rbac_enforce: bool,
    /// Minimum role for semantic erasure: `maintainer` or `administrator`.
    #[arg(long, default_value = "maintainer")]
    rbac_erasure_min_role: String,
    /// Minimum role for repository-to-team promotion: `maintainer` or `administrator`.
    #[arg(long, default_value = "maintainer")]
    rbac_promotion_min_role: String,
    /// 64-character hexadecimal local envelope key. Also falls back to `SHIBAHAMA_ENCRYPTION_KEY`.
    #[arg(long)]
    encryption_key: Option<String>,
    /// Stable local envelope-key identifier, stored as ciphertext metadata only.
    #[arg(long, default_value = "service-local")]
    encryption_key_id: String,
    /// Permit an unencrypted service store for local development only.
    #[arg(long)]
    unsafe_development_plaintext: bool,
    /// Enable the irreversible, authorization-bound semantic-erasure endpoint.
    #[arg(long)]
    full_semantic_erasure: bool,
    /// Maximum materialized memories allowed per namespace.
    #[arg(long, default_value_t = 10_000)]
    max_memories_per_namespace: usize,
    /// Sustained requests permitted per authenticated principal and exact scope window.
    #[arg(long, default_value_t = 120)]
    rate_limit_requests_per_window: u32,
    /// Token-bucket refill window in seconds.
    #[arg(long, default_value_t = 60)]
    rate_limit_window_seconds: u64,
    /// Immediate requests permitted before token-bucket refills are required.
    #[arg(long, default_value_t = 30)]
    rate_limit_burst: u32,
    /// Exact scope granted to HTTP MCP sessions.
    #[arg(long, default_value = "repository")]
    mcp_scope_visibility: String,
    /// Team required when `--mcp-scope-visibility team` is selected.
    #[arg(long)]
    mcp_scope_team: Option<String>,
    /// Allowed browser origin. Repeat or comma-separate values; also reads `SHIBAHAMA_CORS_ORIGINS`.
    #[arg(long, value_delimiter = ',')]
    cors_origin: Vec<String>,
    /// Allowed browser request method. Repeat or comma-separate values; also reads `SHIBAHAMA_CORS_METHODS`.
    #[arg(long, value_delimiter = ',')]
    cors_method: Vec<String>,
    /// Allowed browser request header. Repeat or comma-separate values; also reads `SHIBAHAMA_CORS_HEADERS`.
    #[arg(long, value_delimiter = ',')]
    cors_header: Vec<String>,
    /// Emit Access-Control-Allow-Credentials; also reads `SHIBAHAMA_CORS_ALLOW_CREDENTIALS`.
    #[arg(long)]
    cors_allow_credentials: bool,
}

#[derive(Args)]
struct McpCommand {
    #[command(flatten)]
    store: StoreArgs,
    /// Repository scope fixed for this MCP server process.
    #[arg(long)]
    scope_repository: String,
    /// Owning team scope when `--scope-visibility team` is selected.
    #[arg(long)]
    scope_team: Option<String>,
    /// Scope visibility: `repository` or `team`.
    #[arg(long)]
    scope_visibility: String,
    /// Local principal identity fixed for this MCP server process.
    #[arg(long)]
    principal: String,
    /// Authenticated actor class fixed for this MCP server process.
    #[arg(long, default_value = "human")]
    actor: String,
}

#[derive(Clone, Copy, ValueEnum)]
enum ExportFormat {
    /// Pretty JSON array.
    Json,
    /// Newline-delimited JSON records.
    Jsonl,
}

#[derive(Clone, Copy, ValueEnum)]
enum WhyFormat {
    /// Human-readable terminal output.
    Text,
    /// JSON object.
    Json,
}

#[derive(Debug)]
struct CliError(String);

impl Display for CliError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for CliError {}

#[derive(Serialize)]
struct InitOutput {
    version: &'static str,
    path: String,
    dimensions: usize,
    capacity: usize,
}

#[derive(Serialize)]
struct InspectOutput {
    version: &'static str,
    path: String,
    memory_count: usize,
    memories: Vec<MemoryItemDto>,
}

#[derive(Serialize)]
struct ProvenanceDto {
    source_kind: String,
    source_ref: Option<String>,
    ingested_by: String,
}

#[derive(Serialize)]
struct MemoryScopeDto {
    repository: String,
    team: Option<String>,
    visibility: String,
}

#[derive(Serialize)]
struct MemoryItemDto {
    id: String,
    content: String,
    kind: String,
    provenance: ProvenanceDto,
    scope: MemoryScopeDto,
    tier: String,
    credence: String,
    significance: f64,
    credence_floor: String,
    valid_from_unix: i64,
    valid_to_unix: Option<i64>,
    ingested_at_unix: i64,
}

#[derive(Serialize)]
struct RecallCandidateDto {
    id: String,
    item: MemoryItemDto,
    kind: String,
    provenance: ProvenanceDto,
    tier: String,
    currency: String,
    load_bearing_possibly_stale: bool,
    cold_tier_retrieval: bool,
    vector_distance: f32,
    similarity_score: f64,
    significance_score: f64,
    recency_score: f64,
    graph_score: f64,
    source: String,
    rank_score: f64,
    read_safety_findings: Vec<String>,
}

#[derive(Serialize)]
struct DegradedRecallDto {
    candidates: Vec<RecallCandidateDto>,
    unavailable_stages: Vec<String>,
}

#[derive(Serialize)]
struct EventRecordDto {
    sequence: u64,
    recorded_at_unix: i64,
    kind: String,
    memory_ids: Vec<String>,
    event: serde_json::Value,
}

#[derive(Serialize)]
struct EventLogDto {
    event_count: usize,
    events: Vec<EventRecordDto>,
}

#[derive(Serialize)]
struct WhyTraceDto {
    item: MemoryItemDto,
    significance: SignificanceBreakdown,
    provenance: ProvenanceDto,
    tier_current: String,
    tier_credence: String,
    tier_credence_floor: String,
    currency_state: String,
    currency_as_of_unix: i64,
    valid_from_unix: i64,
    valid_to_unix: Option<i64>,
    ingested_at_unix: i64,
    audit_trail: Vec<String>,
}

#[derive(Serialize)]
struct AuditDetailDto {
    memory_id: String,
    why: Option<WhyTraceDto>,
    events: Vec<EventRecordDto>,
}

#[derive(Serialize)]
struct HumanSignalDto {
    action: String,
    memory_id: String,
    actor: String,
    timestamp_unix: i64,
    reason: String,
    proposed_content: Option<String>,
    proposal_id: Option<String>,
    previous_credence: Option<String>,
    new_credence: Option<String>,
    previous_credence_floor: Option<String>,
    new_credence_floor: Option<String>,
}

#[derive(Serialize)]
struct HumanSignalOutcomeDto {
    applied: bool,
    signal: HumanSignalDto,
    events: Vec<EventRecordDto>,
}

#[derive(Serialize)]
struct HumanCorrectionOutcomeDto {
    applied: bool,
    signal: HumanSignalDto,
    proposal: MemoryItemDto,
    replacement: MemoryItemDto,
    events: Vec<EventRecordDto>,
}

#[derive(Serialize)]
#[serde(untagged)]
enum HumanMutationDto {
    Signal(Box<HumanSignalOutcomeDto>),
    Correction(Box<HumanCorrectionOutcomeDto>),
    NotFound { applied: bool },
}

#[derive(Serialize)]
struct ConsolidationOutcomeDto {
    action: String,
    input_ids: Vec<String>,
    output_id: Option<String>,
    tier_from: Option<String>,
    tier_to: Option<String>,
    why: String,
    events: Vec<EventRecordDto>,
}

#[derive(Serialize)]
struct ConsolidationPassDto {
    pass_id: String,
    applied_count: usize,
    outcomes: Vec<ConsolidationOutcomeDto>,
}

#[derive(Serialize)]
struct TidelineSnapshotDto {
    schema_version: u32,
    version: &'static str,
    path: String,
    namespace: String,
    generated_at_unix: i64,
    as_of_unix: Option<i64>,
    memory_count: usize,
    event_count: usize,
    last_sequence: Option<u64>,
    memories: Vec<MemoryItemDto>,
    events: Vec<TidelineEventDto>,
    graph: TidelineGraphDto,
}

#[derive(Serialize)]
struct TidelineEventDto {
    sequence: u64,
    recorded_at_unix: i64,
    kind: String,
    memory_ids: Vec<String>,
    tier_from: Option<String>,
    tier_to: Option<String>,
    access_outcome: Option<String>,
    valid_to_unix: Option<i64>,
    consolidation_action: Option<String>,
    consolidation_why: Option<String>,
    consolidation_evidence: Vec<TidelineConsolidationEvidenceDto>,
    human_signal_action: Option<String>,
    human_signal_actor: Option<String>,
    human_signal_reason: Option<String>,
}

#[derive(Serialize)]
struct TidelineConsolidationEvidenceDto {
    memory_id: String,
    significance: f64,
    access_count: usize,
    actual_use_count: usize,
    contradiction_count: usize,
    tier: String,
    credence: String,
    credence_floor: String,
}

struct ConsolidationEventParts {
    action: ConsolidationAction,
    input_ids: Vec<MemoryId>,
    output_id: Option<MemoryId>,
    tier_from: Option<Tier>,
    tier_to: Option<Tier>,
    why: ConsolidationWhy,
}

#[derive(Serialize)]
struct TidelineGraphDto {
    nodes: Vec<TidelineGraphNodeDto>,
    edges: Vec<TidelineGraphEdgeDto>,
}

#[derive(Serialize)]
struct TidelineGraphNodeDto {
    id: String,
    label: String,
    tier: String,
    credence: String,
    significance: f64,
    valid_from_unix: i64,
    valid_to_unix: Option<i64>,
}

#[derive(Serialize)]
struct TidelineGraphEdgeDto {
    id: String,
    from: String,
    to: String,
    kind: String,
    valid_from_unix: Option<i64>,
    valid_to_unix: Option<i64>,
}

#[derive(Serialize)]
struct GraphEntityDto {
    id: String,
    scope: MemoryScopeDto,
    source_memory_id: Option<String>,
    entity_type: String,
    label: String,
    stable_key: String,
    attributes: BTreeMap<String, String>,
    valid_from_unix: i64,
    valid_to_unix: Option<i64>,
    ingested_at_unix: i64,
}

#[derive(Serialize)]
struct GraphRelationDto {
    id: String,
    scope: MemoryScopeDto,
    relation_type: String,
    from_entity: String,
    to_entity: String,
    memory_id: Option<String>,
    supersedes: Option<String>,
    attributes: BTreeMap<String, String>,
    valid_from_unix: i64,
    valid_to_unix: Option<i64>,
    ingested_at_unix: i64,
}

#[derive(Serialize)]
struct GraphSnapshotDto {
    as_of_unix: i64,
    entities: Vec<GraphEntityDto>,
    relations: Vec<GraphRelationDto>,
}

#[derive(Clone)]
struct ServerState {
    engine: Arc<Mutex<Shibahama<HnswVectorIndex>>>,
    mcp_sessions: Arc<Mutex<BTreeMap<String, mcp::McpSession>>>,
    path: String,
    default_namespace: String,
    authentication: ServerAuthentication,
    administration: ServerAdministration,
    rbac: ServerRbacPolicy,
    rate_limiter: Arc<Mutex<ServerRateLimiter>>,
    mcp_scope: MemoryScope,
    max_memories_per_namespace: usize,
    operational_log_key: [u8; 32],
}

struct ServerRequestContext {
    namespace: String,
    scope: MemoryScope,
    principal: String,
    principal_class: AuthorizationPrincipalClass,
    actor_class: PolicyActorClass,
    credential_role: Option<RbacRole>,
}

struct ServerAuthenticatedPrincipal {
    principal: String,
    principal_class: AuthorizationPrincipalClass,
    actor_class: PolicyActorClass,
    credential_role: Option<RbacRole>,
    token_scope: Option<MemoryScope>,
}

#[derive(Clone)]
struct ServerAuthentication {
    api_key: Option<String>,
    oidc: Option<OidcAuthenticator>,
}

#[derive(Clone)]
struct ServerAdministration {
    bootstrap: Option<BootstrapAdministration>,
    recovery_secret_commitment: Option<String>,
}

#[derive(Clone)]
struct BootstrapAdministration {
    secret_commitment: String,
    ttl_seconds: u64,
}

#[derive(Clone, Copy)]
struct ServerRbacPolicy {
    enforce: bool,
    erasure_min_role: RbacRole,
    promotion_min_role: RbacRole,
}

struct ServerCorsPolicy {
    origins: Vec<HeaderValue>,
    methods: Vec<Method>,
    headers: Vec<HeaderName>,
    allow_credentials: bool,
    uses_unsafe_local_defaults: bool,
}

#[derive(Clone, Copy)]
struct ServerRateLimitPolicy {
    requests_per_window: u32,
    window: Duration,
    burst: u32,
}

struct ServerRateLimiter {
    policy: ServerRateLimitPolicy,
    buckets: BTreeMap<String, ServerRateLimitBucket>,
}

struct ServerRateLimitBucket {
    available: f64,
    last_refill: Instant,
}

impl ServerCorsPolicy {
    fn layer(self) -> CorsLayer {
        CorsLayer::new()
            .allow_origin(self.origins)
            .allow_methods(self.methods)
            .allow_headers(self.headers)
            .allow_credentials(self.allow_credentials)
    }
}

impl ServerRateLimiter {
    fn new(policy: ServerRateLimitPolicy) -> Self {
        Self {
            policy,
            buckets: BTreeMap::new(),
        }
    }

    fn admit(&mut self, context: &ServerRequestContext, now: Instant) -> Result<(), u64> {
        let key = format!(
            "{}\u{1f}{:?}\u{1f}{}\u{1f}",
            context.principal, context.scope.visibility, context.scope.repository,
        ) + context.scope.team.as_ref().map_or("", ScopeId::as_str);
        let capacity = f64::from(self.policy.burst);
        let refill_per_second =
            f64::from(self.policy.requests_per_window) / self.policy.window.as_secs_f64();
        let bucket = self
            .buckets
            .entry(key)
            .or_insert_with(|| ServerRateLimitBucket {
                available: capacity,
                last_refill: now,
            });
        let elapsed = now
            .saturating_duration_since(bucket.last_refill)
            .as_secs_f64();

        bucket.available = (bucket.available + elapsed * refill_per_second).min(capacity);
        bucket.last_refill = now;
        if bucket.available >= 1.0 {
            bucket.available -= 1.0;
            return Ok(());
        }
        let retry_after = Duration::from_secs_f64((1.0 - bucket.available) / refill_per_second);
        let retry_after = retry_after
            .as_secs()
            .saturating_add(u64::from(retry_after.subsec_nanos() > 0));

        Err(retry_after.max(1))
    }
}

#[derive(Clone, Copy)]
struct RbacRequirement {
    action: AuthorizationAction,
    role: RbacRole,
}

#[derive(Clone, Deserialize)]
struct ServerScopeRequest {
    repository: String,
    team: Option<String>,
    visibility: String,
}

#[derive(Deserialize)]
struct ServerWriteRequest {
    content: String,
    vector: Option<Vec<f32>>,
    source_kind: Option<String>,
    source_ref: Option<String>,
    ingested_by: Option<String>,
    valid_from_unix: Option<i64>,
    ingested_at_unix: Option<i64>,
    kind: Option<String>,
    index_name: Option<String>,
    model: Option<String>,
    model_version: Option<String>,
    scope: Option<ServerScopeRequest>,
}

#[derive(Deserialize)]
struct ServerRecallRequest {
    query_vector: Vec<f32>,
    top_k: Option<usize>,
    now_unix: Option<i64>,
    raw_query_context: Option<String>,
    include_cold: Option<bool>,
    include_instructions: Option<bool>,
    max_context_tokens: Option<usize>,
}

#[derive(Deserialize)]
struct ServerCapturePolicySimulationRequest {
    source_kind: Option<String>,
    actor: Option<String>,
    intent: Option<String>,
    confidence_percent: Option<u8>,
}

#[derive(Deserialize)]
struct ServerRecallPolicySimulationRequest {
    top_k: Option<usize>,
    include_cold: Option<bool>,
    include_instructions: Option<bool>,
    max_context_tokens: Option<usize>,
}

#[derive(Deserialize)]
struct ServerInvalidateRequest {
    memory_id: String,
    valid_to_unix: i64,
}

#[derive(Deserialize)]
struct ServerSemanticEraseRequest {
    memory_id: String,
    authorization_id: String,
}

#[derive(Deserialize)]
struct ServerRbacGrantRequest {
    principal: String,
    role: String,
    scope: Option<ServerScopeRequest>,
}

#[derive(Deserialize)]
struct ServerRbacRevokeRequest {
    principal: String,
    scope: Option<ServerScopeRequest>,
}

#[derive(Deserialize)]
struct ServerServiceTokenIssueRequest {
    role: String,
    expires_at_unix: i64,
    scope: Option<ServerScopeRequest>,
}

#[derive(Deserialize)]
struct ServerServiceTokenRotateRequest {
    expires_at_unix: i64,
}

#[derive(Serialize)]
struct ServerIssuedServiceToken {
    token: ServiceToken,
    access_token: String,
}

#[derive(Deserialize)]
struct ServerTimelineRequest {
    query_vector: Vec<f32>,
    top_k: Option<usize>,
    as_of_unix: Option<i64>,
    raw_query_context: Option<String>,
    include_cold: Option<bool>,
    include_instructions: Option<bool>,
    max_context_tokens: Option<usize>,
}

#[derive(Deserialize)]
struct ServerReinforceRequest {
    memory_id: String,
    outcome: Option<String>,
}

#[derive(Deserialize)]
struct ServerConsolidateRequest {
    now_unix: Option<i64>,
    allow_store_wide: Option<bool>,
}

#[derive(Deserialize)]
struct ServerHumanSignalRequest {
    memory_id: String,
    reason: Option<String>,
    actor: Option<String>,
    timestamp_unix: Option<i64>,
    proposed_content: Option<String>,
}

#[derive(Deserialize)]
struct WhyQuery {
    now_unix: Option<i64>,
}

#[derive(Deserialize)]
struct TidelineQuery {
    as_of_unix: Option<i64>,
}

#[derive(Deserialize)]
struct EventsQuery {
    as_of_unix: Option<i64>,
    limit: Option<usize>,
}

#[derive(Deserialize)]
struct GraphSnapshotQuery {
    as_of_unix: Option<i64>,
}

#[derive(Deserialize)]
struct GraphDeleteQuery {
    valid_to_unix: Option<i64>,
}

#[derive(Deserialize)]
struct ServerGraphEntityRequest {
    id: Option<String>,
    memory_id: Option<String>,
    entity_type: String,
    label: String,
    stable_key: String,
    attributes: Option<BTreeMap<String, String>>,
    valid_from_unix: Option<i64>,
    valid_to_unix: Option<i64>,
    ingested_at_unix: Option<i64>,
}

#[derive(Deserialize)]
struct ServerGraphRelationRequest {
    id: Option<String>,
    relation_type: String,
    from_entity: String,
    to_entity: String,
    memory_id: Option<String>,
    supersedes: Option<String>,
    attributes: Option<BTreeMap<String, String>>,
    valid_from_unix: Option<i64>,
    valid_to_unix: Option<i64>,
    ingested_at_unix: Option<i64>,
}

#[derive(Deserialize)]
struct ServerGraphTraverseRequest {
    start_entity: String,
    max_hops: Option<usize>,
    relation_types: Option<Vec<String>>,
    as_of_unix: Option<i64>,
}

#[derive(Debug)]
struct ServerError {
    status: StatusCode,
    code: String,
    severity: &'static str,
    retryable: bool,
    retry_after_seconds: Option<u64>,
    detail: &'static str,
}

impl ServerError {
    fn internal(error: impl Display) -> Self {
        let message = error.to_string();
        let Some(code) = shibahama_error_code(&message) else {
            return Self {
                status: StatusCode::INTERNAL_SERVER_ERROR,
                code: "SHIBA_INTERNAL".to_owned(),
                severity: "fatal",
                retryable: false,
                retry_after_seconds: None,
                detail: "internal server error",
            };
        };
        let Some(metadata) = ShibahamaErrorMetadata::for_code(code) else {
            return Self {
                status: StatusCode::INTERNAL_SERVER_ERROR,
                code: "SHIBA_INTERNAL".to_owned(),
                severity: "fatal",
                retryable: false,
                retry_after_seconds: None,
                detail: "internal server error",
            };
        };

        Self::from_metadata(server_status_for_error_code(code), metadata)
    }

    fn from_metadata(status: StatusCode, metadata: ShibahamaErrorMetadata) -> Self {
        Self {
            status,
            code: metadata.code.to_owned(),
            severity: metadata.severity.as_str(),
            retryable: metadata.retryable,
            retry_after_seconds: None,
            detail: metadata.detail,
        }
    }

    fn bad_request(_error: impl Display) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            code: "SHIBA_INVALID_REQUEST".to_owned(),
            severity: "fatal",
            retryable: false,
            retry_after_seconds: None,
            detail: "invalid request",
        }
    }

    fn unauthorized(_error: impl Display) -> Self {
        Self {
            status: StatusCode::UNAUTHORIZED,
            code: "SHIBA_UNAUTHORIZED".to_owned(),
            severity: "fatal",
            retryable: false,
            retry_after_seconds: None,
            detail: "authorization denied",
        }
    }

    fn forbidden(_error: impl Display) -> Self {
        Self {
            status: StatusCode::FORBIDDEN,
            code: "SHIBA_UNAUTHORIZED".to_owned(),
            severity: "fatal",
            retryable: false,
            retry_after_seconds: None,
            detail: "authorization denied",
        }
    }

    fn not_found(_error: impl Display) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            code: "SHIBA_NOT_FOUND".to_owned(),
            severity: "fatal",
            retryable: false,
            retry_after_seconds: None,
            detail: "resource not found",
        }
    }

    fn too_many_requests(_error: impl Display) -> Self {
        Self {
            status: StatusCode::TOO_MANY_REQUESTS,
            code: "SHIBA_RATE_LIMITED".to_owned(),
            severity: "recoverable",
            retryable: true,
            retry_after_seconds: None,
            detail: "request rate limited",
        }
    }

    fn rate_limited(retry_after_seconds: u64) -> Self {
        Self {
            status: StatusCode::TOO_MANY_REQUESTS,
            code: "SHIBA_RATE_LIMITED".to_owned(),
            severity: "recoverable",
            retryable: true,
            retry_after_seconds: Some(retry_after_seconds),
            detail: "request rate limited",
        }
    }
}

impl IntoResponse for ServerError {
    fn into_response(self) -> Response {
        let retry_after_seconds = self.retry_after_seconds;
        let mut response = (
            self.status,
            Json(json!({
                "error": self.detail,
                "code": self.code,
                "severity": self.severity,
                "retryable": self.retryable,
                "retry_after_seconds": retry_after_seconds,
                "detail": self.detail,
            })),
        )
            .into_response();
        if let Some(retry_after_seconds) = retry_after_seconds
            && let Ok(value) = HeaderValue::from_str(&retry_after_seconds.to_string())
        {
            response.headers_mut().insert(RETRY_AFTER, value);
        }

        response
    }
}

fn shibahama_error_code(message: &str) -> Option<&str> {
    let start = message.find("[SHIBA_")? + 1;
    let end = message[start..].find(']')? + start;
    Some(&message[start..end])
}

fn server_status_for_error_code(code: &str) -> StatusCode {
    match code {
        "SHIBA_INVALID_REQUEST" | "SHIBA_VECTOR" => StatusCode::BAD_REQUEST,
        "SHIBA_UNAUTHORIZED" => StatusCode::UNAUTHORIZED,
        "SHIBA_RECALL" | "SHIBA_TASK" => StatusCode::SERVICE_UNAVAILABLE,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    }
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("error: {error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> CliResult<()> {
    let cli = Cli::parse();

    match cli.command {
        Command::Init(command) => init(command),
        Command::Write(command) => write(command),
        Command::Recall(command) => recall(command),
        Command::Reinforce(command) => reinforce(command),
        Command::Why(command) => why(command),
        Command::Consolidate(command) => consolidate(command),
        Command::Challenge(command) => challenge(command),
        Command::Affirm(command) => affirm(command),
        Command::Correct(command) => correct(command),
        Command::Pin(command) => pin(command),
        Command::Unpin(command) => unpin(command),
        Command::Events(command) => events(command),
        Command::Audit(command) => audit(command),
        Command::Inspect(command) => inspect(command),
        Command::Export(command) => export(command),
        Command::Serve(command) => serve(command),
        Command::Mcp(command) => serve_mcp(command),
    }
}

fn init(command: StoreCommand) -> CliResult<()> {
    let dimensions = command.store.dimensions.unwrap_or(1);
    let _engine = open_engine_with_dimensions(&command.store, dimensions)?;

    write_json(&InitOutput {
        version: shibahama_core::version(),
        path: command.store.path.display().to_string(),
        dimensions,
        capacity: command.store.capacity,
    })
}

fn write(command: WriteCommand) -> CliResult<()> {
    let vector = command.vector.as_deref().map(parse_vector).transpose()?;
    let mut engine = open_engine(&command.store, vector.as_deref())?;
    let mut event = write_event(
        command.content,
        &command.source_kind,
        command.source_ref,
        &command.ingested_by,
        command.valid_from_unix,
        command.ingested_at_unix,
    )?;

    if parse_memory_kind(&command.kind)? == MemoryKind::Instruction {
        event = event.as_instruction();
    }

    let item = if let Some(vector) = vector.as_deref() {
        engine.write_with_embedding(
            event,
            WriteEmbedding {
                vector,
                index_name: &command.index_name,
                model: &command.model,
                model_version: &command.model_version,
            },
        )?
    } else {
        engine.write(event)?
    };

    write_json(&MemoryItemDto::from(item))
}

fn recall(command: RecallCommand) -> CliResult<()> {
    let query_vector = parse_vector(&command.query_vector)?;
    let engine = open_engine(&command.store, Some(&query_vector))?;
    let mut request = RecallRequest::new(
        &query_vector,
        command.top_k,
        time_from_optional_unix(command.now_unix)?,
    );

    if let Some(raw_query_context) = command.raw_query_context.as_deref() {
        request = request.with_raw_query_context(raw_query_context);
    }
    if command.include_cold {
        request = request.include_cold();
    }
    if command.include_instructions {
        request = request.include_instructions();
    }
    if let Some(max_context_tokens) = command.max_context_tokens {
        request = request.with_max_context_tokens(max_context_tokens);
    }

    let candidates = engine
        .recall(&request)?
        .into_iter()
        .map(RecallCandidateDto::from)
        .collect::<Vec<_>>();

    write_json(&candidates)
}

fn reinforce(command: ReinforceCommand) -> CliResult<()> {
    let engine = open_engine(&command.store, None)?;
    let id = parse_memory_id(&command.memory_id)?;
    let outcome = parse_access_outcome(&command.outcome)?;

    write_json(&json!({
        "applied": engine.reinforce(id, outcome)?,
    }))
}

fn why(command: WhyCommand) -> CliResult<()> {
    let engine = open_engine(&command.store, None)?;
    let id = parse_memory_id(&command.memory_id)?;
    let now = time_from_optional_unix(command.now_unix)?;
    let trace = engine.why_at(id, now)?;

    match command.format {
        WhyFormat::Text => write_why_text(id, trace.as_ref()),
        WhyFormat::Json => write_json(&trace.map(WhyTraceDto::from)),
    }
}

fn consolidate(command: ConsolidateCommand) -> CliResult<()> {
    let engine = open_engine(&command.store, None)?;
    let now = time_from_optional_unix(command.now_unix)?;
    let report = engine.consolidate(now)?;

    write_json(&ConsolidationPassDto::from(report))
}

fn challenge(command: HumanSignalCommand) -> CliResult<()> {
    human_signal(command, HumanSignalAction::Challenge)
}

fn affirm(command: HumanSignalCommand) -> CliResult<()> {
    human_signal(command, HumanSignalAction::Affirm)
}

fn pin(command: HumanSignalCommand) -> CliResult<()> {
    human_signal(command, HumanSignalAction::Pin)
}

fn unpin(command: HumanSignalCommand) -> CliResult<()> {
    human_signal(command, HumanSignalAction::Unpin)
}

fn human_signal(command: HumanSignalCommand, action: HumanSignalAction) -> CliResult<()> {
    let engine = open_engine(&command.store, None)?;
    let id = parse_memory_id(&command.memory_id)?;
    let request = human_signal_request(&command.actor, &command.reason, command.timestamp_unix)?;
    let outcome = match action {
        HumanSignalAction::Challenge => engine.challenge_with_request(id, request)?,
        HumanSignalAction::Affirm => engine.affirm_with_request(id, request)?,
        HumanSignalAction::Pin => engine.pin_with_request(id, request)?,
        HumanSignalAction::Unpin => engine.unpin_with_request(id, request)?,
        HumanSignalAction::Correct => {
            return Err(Box::new(CliError(
                "correct uses the `correct` command".to_owned(),
            )));
        }
    };

    write_json(
        &outcome.map_or(HumanMutationDto::NotFound { applied: false }, |outcome| {
            HumanMutationDto::Signal(Box::new(HumanSignalOutcomeDto::from(outcome)))
        }),
    )
}

fn correct(command: CorrectCommand) -> CliResult<()> {
    let engine = open_engine(&command.store, None)?;
    let id = parse_memory_id(&command.memory_id)?;
    let request = human_signal_request(&command.actor, &command.reason, command.timestamp_unix)?;
    let outcome = engine.correct_with_request(id, command.proposed_content, request)?;

    write_json(
        &outcome.map_or(HumanMutationDto::NotFound { applied: false }, |outcome| {
            HumanMutationDto::Correction(Box::new(HumanCorrectionOutcomeDto::from(outcome)))
        }),
    )
}

fn events(command: EventsCommand) -> CliResult<()> {
    let engine = open_engine(&command.store, None)?;
    let mut events = engine
        .event_records()?
        .into_iter()
        .map(EventRecordDto::from)
        .collect::<Vec<_>>();

    if let Some(limit) = command.limit
        && events.len() > limit
    {
        events = events.split_off(events.len() - limit);
    }

    write_json(&EventLogDto {
        event_count: events.len(),
        events,
    })
}

fn audit(command: AuditCommand) -> CliResult<()> {
    let engine = open_engine(&command.store, None)?;
    let id = parse_memory_id(&command.memory_id)?;
    let why = engine.why(id)?.map(WhyTraceDto::from);
    let events = engine
        .event_records()?
        .into_iter()
        .filter(|record| event_touches_memory(record, id))
        .map(EventRecordDto::from)
        .collect::<Vec<_>>();

    write_json(&AuditDetailDto {
        memory_id: id.to_string(),
        why,
        events,
    })
}

fn inspect(command: InspectCommand) -> CliResult<()> {
    let engine = open_engine(&command.store, None)?;
    let memories = engine
        .memory_items()?
        .into_iter()
        .map(MemoryItemDto::from)
        .collect::<Vec<_>>();

    write_json(&InspectOutput {
        version: shibahama_core::version(),
        path: command.store.path.display().to_string(),
        memory_count: memories.len(),
        memories,
    })
}

fn export(command: ExportCommand) -> CliResult<()> {
    let engine = open_engine(&command.store, None)?;
    let memories = engine
        .memory_items()?
        .into_iter()
        .map(MemoryItemDto::from)
        .collect::<Vec<_>>();

    match command.format {
        ExportFormat::Json => write_json(&memories),
        ExportFormat::Jsonl => write_jsonl(&memories),
    }
}

fn serve(command: ServeCommand) -> CliResult<()> {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;

    runtime.block_on(serve_async(command))
}

fn serve_mcp(command: McpCommand) -> CliResult<()> {
    let scope = mcp_memory_scope(&command)?;
    let principal = mcp_principal(&command.principal)?;
    let actor = mcp_actor(&command.actor)?;
    let mut engine = open_engine(&command.store, None)?;
    let mut backend = mcp_tools::McpEngineBackend::new(&mut engine);

    Ok(mcp::serve_stdio_with_backend(
        mcp::McpServerContext::new(scope, principal, actor),
        &mut backend,
    )?)
}

fn mcp_memory_scope(command: &McpCommand) -> CliResult<MemoryScope> {
    mcp_scope(
        &command.scope_repository,
        command.scope_team.as_deref(),
        &command.scope_visibility,
    )
}

fn server_mcp_scope(command: &ServeCommand) -> CliResult<MemoryScope> {
    mcp_scope(
        &command.namespace,
        command.mcp_scope_team.as_deref(),
        &command.mcp_scope_visibility,
    )
}

fn mcp_scope(repository: &str, team: Option<&str>, visibility: &str) -> CliResult<MemoryScope> {
    let repository = ScopeId::new(repository)?;
    match visibility {
        "repository" => {
            if team.is_some() {
                return Err(Box::new(CliError(
                    "repository MCP scope must not include --scope-team".to_owned(),
                )));
            }
            Ok(MemoryScope::repository(repository))
        }
        "team" => {
            let team = team.ok_or_else(|| {
                Box::new(CliError("team MCP scope requires --scope-team".to_owned()))
                    as Box<dyn Error>
            })?;
            Ok(MemoryScope::team(repository, ScopeId::new(team)?))
        }
        _ => Err(Box::new(CliError(
            "MCP scope visibility must be `repository` or `team`".to_owned(),
        ))),
    }
}

fn mcp_actor(value: &str) -> CliResult<PolicyActorClass> {
    match value {
        "human" => Ok(PolicyActorClass::Human),
        "agent" => Ok(PolicyActorClass::Agent),
        "automation" => Ok(PolicyActorClass::Automation),
        "service" => Ok(PolicyActorClass::Service),
        _ => Err(Box::new(CliError(
            "MCP actor must be `human`, `agent`, `automation`, or `service`".to_owned(),
        ))),
    }
}

fn mcp_principal(value: &str) -> CliResult<String> {
    let valid = !value.is_empty()
        && value.len() <= 128
        && value.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.' | ':')
        });
    if valid {
        Ok(value.to_owned())
    } else {
        Err(Box::new(CliError(
            "MCP principal must be 1-128 ASCII alphanumeric, `-`, `_`, `.`, or `:` characters"
                .to_owned(),
        )))
    }
}

#[allow(clippy::too_many_lines)]
async fn serve_async(command: ServeCommand) -> CliResult<()> {
    validate_namespace(&command.namespace)?;
    let mcp_scope = server_mcp_scope(&command)?;
    let api_key = command
        .api_key
        .clone()
        .or_else(|| env::var("SHIBAHAMA_API_KEY").ok())
        .filter(|value| !value.is_empty());
    let oidc = oidc_authenticator(&command)?;
    let administration = server_administration(&command)?;
    let rbac = server_rbac_policy(&command)?;
    let rate_limit = server_rate_limit_policy(&command)?;
    let cors = server_cors_policy(&command)?;
    if cors.uses_unsafe_local_defaults {
        eprintln!(
            "WARNING: unsafe local CORS defaults are active; configure --cors-origin for shared deployments"
        );
    }
    if (administration.bootstrap.is_some() || administration.recovery_secret_commitment.is_some())
        && api_key.is_none()
        && oidc.is_none()
    {
        return Err(Box::new(CliError(
            "administrator bootstrap and recovery require API-key or OIDC authentication"
                .to_owned(),
        )));
    }
    if command.full_semantic_erasure && api_key.is_none() && oidc.is_none() {
        return Err(Box::new(CliError(
            "--full-semantic-erasure requires API-key or OIDC authentication".to_owned(),
        )));
    }
    let engine = open_service_engine(&command)?;
    if let Some(bootstrap) = &administration.bootstrap {
        let opened_at = OffsetDateTime::now_utc();
        let ttl_seconds = i64::try_from(bootstrap.ttl_seconds).map_err(|_| {
            Box::new(CliError(
                "administrator bootstrap duration is invalid".to_owned(),
            )) as Box<dyn Error>
        })?;
        engine.ensure_administration_bootstrap_window(
            &bootstrap.secret_commitment,
            opened_at,
            opened_at + time::Duration::seconds(ttl_seconds),
        )?;
    }
    let state = ServerState {
        engine: Arc::new(Mutex::new(engine)),
        mcp_sessions: Arc::new(Mutex::new(BTreeMap::new())),
        path: command.store.path.display().to_string(),
        default_namespace: command.namespace,
        authentication: ServerAuthentication { api_key, oidc },
        administration,
        rbac,
        rate_limiter: Arc::new(Mutex::new(ServerRateLimiter::new(rate_limit))),
        mcp_scope,
        max_memories_per_namespace: command.max_memories_per_namespace,
        operational_log_key: operational_log_key(),
    };
    let app = Router::new()
        .route("/healthz", get(server_health))
        .route(
            "/mcp",
            post(server_mcp_post)
                .get(server_mcp_get)
                .delete(server_mcp_delete),
        )
        .route("/capabilities", get(server_capabilities))
        .route("/readyz", get(server_ready))
        .route("/inspect", get(server_inspect))
        .route("/write", post(server_write))
        .route(
            "/policy/simulate/capture",
            post(server_simulate_capture_policy),
        )
        .route(
            "/policy/simulate/recall",
            post(server_simulate_recall_policy),
        )
        .route("/invalidate", post(server_invalidate))
        .route("/erase", post(server_semantic_erase))
        .route("/admin/bootstrap", post(server_admin_bootstrap))
        .route("/admin/recover", post(server_admin_recover))
        .route("/admin/audit", get(server_admin_audit))
        .route(
            "/tokens",
            get(server_service_tokens).post(server_issue_service_token),
        )
        .route("/tokens/audit", get(server_service_token_audit))
        .route(
            "/tokens/{token_id}/rotate",
            post(server_rotate_service_token),
        )
        .route(
            "/tokens/{token_id}/revoke",
            post(server_revoke_service_token),
        )
        .route(
            "/rbac/grants",
            get(server_rbac_grants).post(server_rbac_grant),
        )
        .route("/rbac/revoke", post(server_rbac_revoke))
        .route("/rbac/audit", get(server_rbac_audit))
        .route("/recall", post(server_recall))
        .route("/recall/degraded", post(server_recall_degraded))
        .route("/timeline", post(server_timeline))
        .route("/reinforce", post(server_reinforce))
        .route("/consolidate", post(server_consolidate))
        .route("/challenge", post(server_challenge))
        .route("/affirm", post(server_affirm))
        .route("/correct", post(server_correct))
        .route("/pin", post(server_pin))
        .route("/unpin", post(server_unpin))
        .route("/events", get(server_events))
        .route("/audit/{memory_id}", get(server_audit))
        .route("/why/{memory_id}", get(server_why))
        .route("/graph", get(server_graph_snapshot))
        .route("/graph/entities", post(server_put_graph_entity))
        .route(
            "/graph/entities/{entity_id}",
            get(server_get_graph_entity).delete(server_delete_graph_entity),
        )
        .route("/graph/relations", post(server_put_graph_relation))
        .route(
            "/graph/relations/{relation_id}",
            get(server_get_graph_relation).delete(server_delete_graph_relation),
        )
        .route("/graph/traverse", post(server_graph_traverse))
        .route("/tideline/snapshot", get(server_tideline_snapshot))
        .route("/tideline/recording", get(server_tideline_recording))
        .route("/tideline/live", get(server_tideline_live))
        .layer(cors.layer())
        .layer(middleware::from_fn_with_state(
            state.clone(),
            server_operational_log_middleware,
        ))
        .with_state(state);
    let listener = tokio::net::TcpListener::bind(command.bind).await?;
    let local_addr = listener.local_addr()?;

    eprintln!("shibahama serve listening on http://{local_addr}");
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    Ok(())
}

fn oidc_authenticator(command: &ServeCommand) -> CliResult<Option<OidcAuthenticator>> {
    let issuer = command
        .oidc_issuer
        .clone()
        .or_else(|| env::var("SHIBAHAMA_OIDC_ISSUER").ok())
        .filter(|value| !value.is_empty());
    let audience = command
        .oidc_audience
        .clone()
        .or_else(|| env::var("SHIBAHAMA_OIDC_AUDIENCE").ok())
        .filter(|value| !value.is_empty());
    let ca_certificate = command
        .oidc_ca_certificate
        .clone()
        .or_else(|| env::var_os("SHIBAHAMA_OIDC_CA_CERT_PATH").map(PathBuf::from));

    let (Some(issuer), Some(audience)) = (issuer, audience) else {
        if command.oidc_issuer.is_some()
            || command.oidc_audience.is_some()
            || command.oidc_principal_claim.is_some()
            || command.oidc_ca_certificate.is_some()
            || env::var_os("SHIBAHAMA_OIDC_ISSUER").is_some()
            || env::var_os("SHIBAHAMA_OIDC_AUDIENCE").is_some()
            || env::var_os("SHIBAHAMA_OIDC_PRINCIPAL_CLAIM").is_some()
            || env::var_os("SHIBAHAMA_OIDC_CA_CERT_PATH").is_some()
        {
            return Err(Box::new(CliError(
                "OIDC requires issuer and audience".to_owned(),
            )));
        }
        return Ok(None);
    };
    let principal_claim = command
        .oidc_principal_claim
        .clone()
        .or_else(|| env::var("SHIBAHAMA_OIDC_PRINCIPAL_CLAIM").ok())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "sub".to_owned());
    let config = OidcConfig::new(issuer, audience, principal_claim)
        .map_err(|error| Box::new(CliError(error.to_string())) as Box<dyn Error>)?;

    OidcAuthenticator::discover_with_ca_certificate(config, ca_certificate.as_deref())
        .map(Some)
        .map_err(|error| Box::new(CliError(error.to_string())) as Box<dyn Error>)
}

fn server_administration(command: &ServeCommand) -> CliResult<ServerAdministration> {
    let bootstrap_secret = command
        .admin_bootstrap_secret
        .clone()
        .or_else(|| env::var("SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET").ok())
        .filter(|value| !value.is_empty());
    let recovery_secret = command
        .admin_recovery_secret
        .clone()
        .or_else(|| env::var("SHIBAHAMA_ADMIN_RECOVERY_SECRET").ok())
        .filter(|value| !value.is_empty());
    let recovery_secret_commitment = recovery_secret
        .as_deref()
        .map(|secret| operator_secret_commitment(secret, ADMIN_RECOVERY_SECRET_DOMAIN))
        .transpose()?;
    let bootstrap = bootstrap_secret
        .as_deref()
        .map(|secret| {
            if !(60..=86_400).contains(&command.admin_bootstrap_ttl_seconds) {
                return Err(Box::new(CliError(
                    "administrator bootstrap TTL must be between 60 and 86400 seconds".to_owned(),
                )) as Box<dyn Error>);
            }

            Ok(BootstrapAdministration {
                secret_commitment: operator_secret_commitment(
                    secret,
                    ADMIN_BOOTSTRAP_SECRET_DOMAIN,
                )?,
                ttl_seconds: command.admin_bootstrap_ttl_seconds,
            })
        })
        .transpose()?;

    if bootstrap.is_some() && recovery_secret_commitment.is_none() {
        return Err(Box::new(CliError(
            "administrator bootstrap requires --admin-recovery-secret or SHIBAHAMA_ADMIN_RECOVERY_SECRET"
                .to_owned(),
        )));
    }

    Ok(ServerAdministration {
        bootstrap,
        recovery_secret_commitment,
    })
}

fn server_rbac_policy(command: &ServeCommand) -> CliResult<ServerRbacPolicy> {
    Ok(ServerRbacPolicy {
        enforce: command.rbac_enforce,
        erasure_min_role: parse_rbac_minimum_role(&command.rbac_erasure_min_role)?,
        promotion_min_role: parse_rbac_minimum_role(&command.rbac_promotion_min_role)?,
    })
}

fn server_rate_limit_policy(command: &ServeCommand) -> CliResult<ServerRateLimitPolicy> {
    if command.rate_limit_requests_per_window == 0
        || command.rate_limit_burst == 0
        || command.rate_limit_window_seconds == 0
        || command.rate_limit_window_seconds > 86_400
    {
        return Err(Box::new(CliError(
            "rate-limit requests, burst, and window must be positive; window must not exceed 86400 seconds"
                .to_owned(),
        )));
    }

    Ok(ServerRateLimitPolicy {
        requests_per_window: command.rate_limit_requests_per_window,
        window: Duration::from_secs(command.rate_limit_window_seconds),
        burst: command.rate_limit_burst,
    })
}

fn server_cors_policy(command: &ServeCommand) -> CliResult<ServerCorsPolicy> {
    let configured_origins = cors_values(&command.cors_origin, "SHIBAHAMA_CORS_ORIGINS");
    let uses_unsafe_local_defaults = configured_origins.is_empty();
    let origins = if uses_unsafe_local_defaults {
        vec![
            "http://localhost:5173".to_owned(),
            "http://127.0.0.1:5173".to_owned(),
        ]
    } else {
        configured_origins
    };
    let methods = cors_values(&command.cors_method, "SHIBAHAMA_CORS_METHODS");
    let methods = if methods.is_empty() {
        vec!["GET".to_owned(), "POST".to_owned(), "DELETE".to_owned()]
    } else {
        methods
    };
    let headers = cors_values(&command.cors_header, "SHIBAHAMA_CORS_HEADERS");
    let headers = if headers.is_empty() {
        vec![
            "accept".to_owned(),
            "authorization".to_owned(),
            "content-type".to_owned(),
            "x-api-key".to_owned(),
            "x-shibahama-bootstrap-secret".to_owned(),
            "x-shibahama-namespace".to_owned(),
            "x-shibahama-recovery-secret".to_owned(),
            "x-shibahama-scope-team".to_owned(),
            "x-shibahama-scope-visibility".to_owned(),
        ]
    } else {
        headers
    };

    Ok(ServerCorsPolicy {
        origins: parse_cors_origins(origins)?,
        methods: parse_cors_methods(methods)?,
        headers: parse_cors_headers(headers)?,
        allow_credentials: command.cors_allow_credentials
            || cors_allow_credentials_from_environment()?,
        uses_unsafe_local_defaults,
    })
}

fn cors_values(cli_values: &[String], environment_key: &str) -> Vec<String> {
    let values = if cli_values.is_empty() {
        env::var(environment_key)
            .ok()
            .map(|value| value.split(',').map(str::to_owned).collect())
            .unwrap_or_default()
    } else {
        cli_values.to_vec()
    };
    values
        .into_iter()
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
        .collect()
}

fn cors_allow_credentials_from_environment() -> CliResult<bool> {
    match env::var("SHIBAHAMA_CORS_ALLOW_CREDENTIALS") {
        Ok(value) if matches!(value.as_str(), "1" | "true" | "TRUE") => Ok(true),
        Ok(value) if matches!(value.as_str(), "0" | "false" | "FALSE") => Ok(false),
        Ok(_) => Err(Box::new(CliError(
            "SHIBAHAMA_CORS_ALLOW_CREDENTIALS must be true or false".to_owned(),
        ))),
        Err(env::VarError::NotPresent) => Ok(false),
        Err(env::VarError::NotUnicode(_)) => Err(Box::new(CliError(
            "SHIBAHAMA_CORS_ALLOW_CREDENTIALS must be valid UTF-8".to_owned(),
        ))),
    }
}

fn parse_cors_origins(values: Vec<String>) -> CliResult<Vec<HeaderValue>> {
    let mut seen = BTreeSet::new();
    let mut origins = Vec::new();

    for value in values {
        let origin = Url::parse(&value).map_err(|_| {
            Box::new(CliError(
                "CORS origin must be an exact HTTP(S) origin".to_owned(),
            )) as Box<dyn Error>
        })?;
        if !matches!(origin.scheme(), "http" | "https")
            || origin.host_str().is_none()
            || !origin.username().is_empty()
            || origin.password().is_some()
            || origin.path() != "/"
            || origin.query().is_some()
            || origin.fragment().is_some()
        {
            return Err(Box::new(CliError(
                "CORS origin must be an exact HTTP(S) origin without path, query, or credentials"
                    .to_owned(),
            )));
        }
        let canonical = origin.origin().ascii_serialization();
        if canonical == "null" {
            return Err(Box::new(CliError("CORS origin is invalid".to_owned())));
        }
        if seen.insert(canonical.clone()) {
            origins.push(HeaderValue::from_str(&canonical).map_err(|_| {
                Box::new(CliError("CORS origin header is invalid".to_owned())) as Box<dyn Error>
            })?);
        }
    }
    if origins.is_empty() {
        return Err(Box::new(CliError(
            "CORS must allow at least one explicit origin".to_owned(),
        )));
    }

    Ok(origins)
}

fn parse_cors_methods(values: Vec<String>) -> CliResult<Vec<Method>> {
    let mut seen = BTreeSet::new();
    let mut methods = Vec::new();

    for value in values {
        let method = Method::from_bytes(value.as_bytes()).map_err(|_| {
            Box::new(CliError("CORS method is invalid".to_owned())) as Box<dyn Error>
        })?;
        if seen.insert(method.as_str().to_owned()) {
            methods.push(method);
        }
    }
    if methods.is_empty() {
        return Err(Box::new(CliError(
            "CORS must allow at least one explicit method".to_owned(),
        )));
    }

    Ok(methods)
}

fn parse_cors_headers(values: Vec<String>) -> CliResult<Vec<HeaderName>> {
    let mut seen = BTreeSet::new();
    let mut headers = Vec::new();

    for value in values {
        let header = HeaderName::from_bytes(value.as_bytes()).map_err(|_| {
            Box::new(CliError("CORS header is invalid".to_owned())) as Box<dyn Error>
        })?;
        if seen.insert(header.as_str().to_owned()) {
            headers.push(header);
        }
    }
    if headers.is_empty() {
        return Err(Box::new(CliError(
            "CORS must allow at least one explicit request header".to_owned(),
        )));
    }

    Ok(headers)
}

fn parse_rbac_minimum_role(value: &str) -> CliResult<RbacRole> {
    match value {
        "maintainer" => Ok(RbacRole::Maintainer),
        "administrator" => Ok(RbacRole::Administrator),
        _ => Err(Box::new(CliError(
            "RBAC minimum role must be `maintainer` or `administrator`".to_owned(),
        ))),
    }
}

fn parse_rbac_role(value: &str) -> Result<RbacRole, ServerError> {
    match value {
        "reader" => Ok(RbacRole::Reader),
        "writer" => Ok(RbacRole::Writer),
        "maintainer" => Ok(RbacRole::Maintainer),
        "administrator" => Ok(RbacRole::Administrator),
        _ => Err(ServerError::bad_request("RBAC role is invalid")),
    }
}

fn operator_secret_commitment(secret: &str, domain: &[u8]) -> CliResult<String> {
    if !(32..=1024).contains(&secret.len()) {
        return Err(Box::new(CliError(
            "administrator secret must contain 32-1024 bytes".to_owned(),
        )));
    }
    let mut hasher = blake3::Hasher::new();

    hasher.update(domain);
    hasher.update(&[0]);
    hasher.update(secret.len().to_string().as_bytes());
    hasher.update(&[0]);
    hasher.update(secret.as_bytes());

    Ok(hasher.finalize().to_hex().to_string())
}

fn commitments_match(expected: &str, submitted: &str) -> bool {
    let difference = expected.bytes().zip(submitted.bytes()).fold(
        u8::try_from(expected.len() ^ submitted.len()).unwrap_or(u8::MAX),
        |value, pair| value | (pair.0 ^ pair.1),
    );

    difference == 0
}

fn service_token_bearer_commitment(value: &str) -> Option<(String, String)> {
    let value = value.strip_prefix(SERVICE_TOKEN_PREFIX)?;
    let (token_id, token_secret) = value.split_once('_')?;
    if !valid_service_token_component(token_id)
        || !valid_service_token_component(token_secret)
        || token_secret.contains('_')
    {
        return None;
    }
    let mut hasher = blake3::Hasher::new();

    hasher.update(SERVICE_TOKEN_SECRET_DOMAIN);
    hasher.update(&[0]);
    hasher.update(value.as_bytes());

    Some((token_id.to_owned(), hasher.finalize().to_hex().to_string()))
}

fn valid_service_token_component(value: &str) -> bool {
    value.len() == 32
        && value.bytes().all(|byte| {
            byte.is_ascii_digit() || (byte.is_ascii_lowercase() && byte.is_ascii_hexdigit())
        })
}

fn issue_service_token_material(
    scope: MemoryScope,
    role: RbacRole,
    issued_by: String,
    issued_at: OffsetDateTime,
    expires_at: OffsetDateTime,
    rotated_from: Option<String>,
) -> Result<(ServiceTokenStoredMaterial, String), ServerError> {
    if expires_at <= issued_at {
        return Err(ServerError::bad_request(
            "service token expiry must be in the future",
        ));
    }
    let token_id = Uuid::new_v4().simple().to_string();
    let token_secret = Uuid::new_v4().simple().to_string();
    let access_token = format!("{SERVICE_TOKEN_PREFIX}{token_id}_{token_secret}");
    let (_, secret_commitment) = service_token_bearer_commitment(&access_token)
        .ok_or_else(|| ServerError::internal("generated service token is invalid"))?;
    let token = ServiceToken {
        schema_version: 1,
        principal: format!("service:{token_id}"),
        id: token_id,
        scope,
        role,
        issued_by,
        issued_at,
        expires_at,
        revoked_at: None,
        rotated_from,
        rotated_to: None,
    };

    Ok((
        ServiceTokenStoredMaterial {
            token,
            secret_commitment,
        },
        access_token,
    ))
}

async fn shutdown_signal() {
    if let Err(error) = tokio::signal::ctrl_c().await {
        eprintln!("failed to listen for shutdown signal: {error}");
    }
}

fn server_context(
    headers: &HeaderMap,
    state: &ServerState,
) -> Result<ServerRequestContext, ServerError> {
    let authenticated = authorize_server_request(headers, state)?;
    let namespace = request_namespace(headers, state)?;
    let scope = request_scope(headers, &namespace)?;
    if authenticated
        .token_scope
        .as_ref()
        .is_some_and(|token_scope| token_scope != &scope)
    {
        return Err(ServerError::forbidden(
            "service token scope does not match the request scope",
        ));
    }

    Ok(ServerRequestContext {
        namespace,
        scope,
        principal: authenticated.principal,
        principal_class: authenticated.principal_class,
        actor_class: authenticated.actor_class,
        credential_role: authenticated.credential_role,
    })
}

fn server_mcp_context(
    headers: &HeaderMap,
    state: &ServerState,
) -> Result<mcp::McpServerContext, ServerError> {
    let context = server_context(headers, state)?;
    if context.scope != state.mcp_scope {
        return Err(ServerError::forbidden(
            "requested MCP scope does not match the transport grant",
        ));
    }
    admit_server_request(state, &context)?;
    authorize_server_rbac(
        state,
        &context,
        RbacRequirement {
            action: AuthorizationAction::Read,
            role: RbacRole::Reader,
        },
        false,
    )?;
    Ok(mcp::McpServerContext::new_with_authorization(
        state.mcp_scope.clone(),
        context.principal,
        context.actor_class,
        context.credential_role,
        context.principal_class,
    ))
}

fn server_mcp_context_or_log(
    headers: &HeaderMap,
    state: &ServerState,
    method: &str,
) -> Result<mcp::McpServerContext, ServerError> {
    match server_mcp_context(headers, state) {
        Ok(context) => Ok(context),
        Err(error) => {
            let namespace = request_namespace(headers, state)
                .ok()
                .unwrap_or_else(|| "unknown".to_owned());
            log_server_request(
                method,
                "/mcp",
                Some(&namespace),
                "rejected",
                error.status,
                json!({ "request_units": 1 }),
            );
            Err(error)
        }
    }
}

fn server_context_or_log(
    headers: &HeaderMap,
    state: &ServerState,
    method: &str,
    route: &str,
) -> Result<ServerRequestContext, ServerError> {
    match server_context(headers, state) {
        Ok(context) => {
            if let Err(error) = admit_server_request(state, &context) {
                log_server_request(
                    method,
                    route,
                    Some(&context.namespace),
                    &context.principal,
                    error.status,
                    json!({ "request_units": 1 }),
                );
                return Err(error);
            }
            if let Some(requirement) = server_rbac_requirement(state, method, route)
                && let Err(error) = authorize_server_rbac(state, &context, requirement, false)
            {
                log_server_request(
                    method,
                    route,
                    Some(&context.namespace),
                    &context.principal,
                    error.status,
                    json!({ "request_units": 1 }),
                );
                return Err(error);
            }

            Ok(context)
        }
        Err(error) => {
            let namespace = request_namespace(headers, state)
                .ok()
                .unwrap_or_else(|| "unknown".to_owned());
            log_server_request(
                method,
                route,
                Some(&namespace),
                "rejected",
                error.status,
                json!({ "request_units": 1 }),
            );
            Err(error)
        }
    }
}

fn admit_server_request(
    state: &ServerState,
    context: &ServerRequestContext,
) -> Result<(), ServerError> {
    let mut limiter = state
        .rate_limiter
        .lock()
        .map_err(|error| ServerError::internal(format!("rate limiter lock poisoned: {error}")))?;
    limiter
        .admit(context, Instant::now())
        .map_err(ServerError::rate_limited)
}

fn server_rbac_requirement(
    state: &ServerState,
    method: &str,
    route: &str,
) -> Option<RbacRequirement> {
    if route.starts_with("/admin/")
        || route.starts_with("/rbac/")
        || route.starts_with("/tokens/")
        || route == "/tokens"
        || route == "/mcp"
    {
        return None;
    }
    let read = RbacRequirement {
        action: AuthorizationAction::Read,
        role: RbacRole::Reader,
    };
    let write = RbacRequirement {
        action: AuthorizationAction::Write,
        role: RbacRole::Writer,
    };
    let maintain = RbacRequirement {
        action: AuthorizationAction::Maintain,
        role: RbacRole::Maintainer,
    };

    match (method, route) {
        ("GET", _)
        | (
            "POST",
            "/policy/simulate/capture"
            | "/policy/simulate/recall"
            | "/recall"
            | "/recall/degraded"
            | "/timeline"
            | "/graph/traverse",
        ) => Some(read),
        ("POST", "/write" | "/reinforce" | "/graph/entities" | "/graph/relations") => Some(write),
        ("POST", "/erase") => Some(RbacRequirement {
            action: AuthorizationAction::SemanticErase,
            role: state.rbac.erasure_min_role,
        }),
        _ => Some(maintain),
    }
}

fn authorize_server_rbac(
    state: &ServerState,
    context: &ServerRequestContext,
    requirement: RbacRequirement,
    force_enforcement: bool,
) -> Result<(), ServerError> {
    let engine = state
        .engine
        .lock()
        .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
    let administration = engine
        .administration_state()
        .map_err(ServerError::internal)?;
    let global_administrator = administration
        .as_ref()
        .and_then(|administration| administration.administrator.as_ref())
        .is_some_and(|administrator| administrator.principal == context.principal);
    let active = context.credential_role.is_some()
        || state.rbac.enforce
        || administration
            .as_ref()
            .is_some_and(|administration| administration.administrator.is_some());
    if !active {
        return if force_enforcement {
            Err(ServerError::forbidden("RBAC administration is unavailable"))
        } else {
            Ok(())
        };
    }
    let allowed = engine
        .authorize_rbac_role_with_credential(
            context.scope.clone(),
            context.principal.clone(),
            requirement.action,
            requirement.role,
            global_administrator,
            context.credential_role,
            Some(context.principal_class),
            Some(context.actor_class),
            OffsetDateTime::now_utc(),
        )
        .map_err(ServerError::internal)?;

    if allowed {
        Ok(())
    } else {
        Err(ServerError::forbidden("RBAC role grant is required"))
    }
}

fn authorize_server_request(
    headers: &HeaderMap,
    state: &ServerState,
) -> Result<ServerAuthenticatedPrincipal, ServerError> {
    let authentication = &state.authentication;

    let bearer_token = headers
        .get(AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "));
    let header_key = headers
        .get("x-api-key")
        .and_then(|value| value.to_str().ok());

    if let Some(token) = bearer_token.filter(|token| token.starts_with(SERVICE_TOKEN_PREFIX)) {
        let Some((token_id, secret_commitment)) = service_token_bearer_commitment(token) else {
            return Err(ServerError::unauthorized("invalid service token"));
        };
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let Some(service_token) = engine
            .authenticate_service_token(&token_id, &secret_commitment, OffsetDateTime::now_utc())
            .map_err(ServerError::internal)?
        else {
            return Err(ServerError::unauthorized("invalid service token"));
        };
        return Ok(ServerAuthenticatedPrincipal {
            principal: service_token.principal,
            principal_class: AuthorizationPrincipalClass::ServiceToken,
            actor_class: PolicyActorClass::Automation,
            credential_role: Some(service_token.role),
            token_scope: Some(service_token.scope),
        });
    }

    if authentication.api_key.is_none() && authentication.oidc.is_none() {
        return Ok(ServerAuthenticatedPrincipal {
            principal: "anonymous".to_owned(),
            principal_class: AuthorizationPrincipalClass::Anonymous,
            actor_class: PolicyActorClass::Service,
            credential_role: None,
            token_scope: None,
        });
    }

    if let (Some(token), Some(oidc)) = (bearer_token, authentication.oidc.as_ref()) {
        let principal = oidc
            .authenticate(token)
            .map_err(|_| ServerError::unauthorized("missing or invalid bearer token"))?;
        return Ok(ServerAuthenticatedPrincipal {
            principal,
            principal_class: AuthorizationPrincipalClass::Oidc,
            actor_class: PolicyActorClass::Human,
            credential_role: None,
            token_scope: None,
        });
    }

    if let Some(api_key) = authentication.api_key.as_deref()
        && (bearer_token == Some(api_key) || header_key == Some(api_key))
    {
        return Ok(ServerAuthenticatedPrincipal {
            principal: "api_key".to_owned(),
            principal_class: AuthorizationPrincipalClass::ApiKey,
            actor_class: PolicyActorClass::Agent,
            credential_role: None,
            token_scope: None,
        });
    }

    Err(ServerError::unauthorized(
        "missing or invalid authentication",
    ))
}

fn request_namespace(headers: &HeaderMap, state: &ServerState) -> Result<String, ServerError> {
    let namespace = headers
        .get("x-shibahama-namespace")
        .and_then(|value| value.to_str().ok())
        .unwrap_or(&state.default_namespace);

    validate_namespace(namespace).map_err(ServerError::bad_request)?;

    Ok(namespace.to_owned())
}

fn request_scope(headers: &HeaderMap, namespace: &str) -> Result<MemoryScope, ServerError> {
    let request = ServerScopeRequest {
        repository: namespace.to_owned(),
        team: headers
            .get("x-shibahama-scope-team")
            .and_then(|value| value.to_str().ok())
            .map(ToOwned::to_owned),
        visibility: headers
            .get("x-shibahama-scope-visibility")
            .and_then(|value| value.to_str().ok())
            .unwrap_or("repository")
            .to_owned(),
    };

    server_memory_scope(Some(&request), namespace)
}

fn validate_namespace(namespace: &str) -> CliResult<()> {
    let valid = !namespace.is_empty()
        && namespace.len() <= 128
        && namespace.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.')
        });

    if valid {
        Ok(())
    } else {
        Err(Box::new(CliError(
            "namespace must be 1-128 characters using only ASCII letters, digits, '.', '_', or '-'"
                .to_owned(),
        )))
    }
}

fn namespace_source_prefix(namespace: &str) -> String {
    format!("shibahama-server:namespace={namespace};")
}

fn namespaced_source_ref(namespace: &str, source_ref: Option<String>) -> String {
    let prefix = namespace_source_prefix(namespace);

    match source_ref {
        Some(source_ref) if !source_ref.is_empty() => format!("{prefix}{source_ref}"),
        _ => prefix,
    }
}

fn server_memory_scope(
    request: Option<&ServerScopeRequest>,
    namespace: &str,
) -> Result<MemoryScope, ServerError> {
    let Some(request) = request else {
        return ScopeId::new(namespace)
            .map(MemoryScope::repository)
            .map_err(ServerError::bad_request);
    };
    let repository = ScopeId::new(&request.repository).map_err(ServerError::bad_request)?;
    if repository.as_str() != namespace {
        return Err(ServerError::bad_request(
            "scope.repository must equal the request namespace",
        ));
    }
    match request.visibility.as_str() {
        "repository" => {
            if request.team.is_some() {
                return Err(ServerError::bad_request(
                    "repository scope must not specify a team",
                ));
            }
            Ok(MemoryScope::repository(repository))
        }
        "team" => Ok(MemoryScope::team(
            repository,
            ScopeId::new(
                request
                    .team
                    .as_deref()
                    .ok_or_else(|| ServerError::bad_request("team scope requires a team"))?,
            )
            .map_err(ServerError::bad_request)?,
        )),
        _ => Err(ServerError::bad_request(
            "scope.visibility must be `repository` or `team`",
        )),
    }
}

fn memory_in_scope(item: &MemoryItem, scope: &MemoryScope) -> bool {
    item.scope == *scope
}

fn optional_time_from_unix(value: Option<i64>) -> Result<Option<OffsetDateTime>, ServerError> {
    value
        .map(OffsetDateTime::from_unix_timestamp)
        .transpose()
        .map_err(ServerError::bad_request)
}

fn required_time_from_unix(value: i64) -> Result<OffsetDateTime, ServerError> {
    OffsetDateTime::from_unix_timestamp(value).map_err(ServerError::bad_request)
}

fn now_or_unix(value: Option<i64>) -> Result<OffsetDateTime, ServerError> {
    value.map_or_else(
        || Ok(OffsetDateTime::now_utc()),
        |unix| OffsetDateTime::from_unix_timestamp(unix).map_err(ServerError::bad_request),
    )
}

fn parse_entity_id(value: &str) -> Result<EntityId, ServerError> {
    Uuid::parse_str(value)
        .map(EntityId::from)
        .map_err(ServerError::bad_request)
}

fn parse_relation_id(value: &str) -> Result<RelationId, ServerError> {
    Uuid::parse_str(value)
        .map(RelationId::from)
        .map_err(ServerError::bad_request)
}

fn graph_entity_in_scope(entity: &Entity, scope: &MemoryScope) -> bool {
    entity.scope == *scope
}

fn graph_relation_in_scope(relation: &Relation, scope: &MemoryScope) -> bool {
    relation.scope == *scope
}

fn namespace_graph_attributes(
    attributes: Option<BTreeMap<String, String>>,
    namespace: &str,
) -> BTreeMap<String, String> {
    let mut attributes = attributes.unwrap_or_default();
    attributes.insert("namespace".to_owned(), namespace.to_owned());
    attributes
}

fn graph_entity_from_request(
    body: ServerGraphEntityRequest,
    namespace: &str,
    scope: &MemoryScope,
) -> Result<Entity, ServerError> {
    let valid_from = now_or_unix(body.valid_from_unix)?;
    let ingested_at = body
        .ingested_at_unix
        .map_or(Ok(valid_from), required_time_from_unix)?;
    let mut entity = Entity::new(
        body.entity_type,
        body.label,
        body.stable_key,
        TemporalBounds {
            valid_from,
            valid_to: optional_time_from_unix(body.valid_to_unix)?,
            ingested_at,
        },
    );

    if let Some(id) = body.id {
        entity.id = parse_entity_id(&id)?;
    }
    entity.source_memory_id = body
        .memory_id
        .as_deref()
        .map(parse_memory_id)
        .transpose()
        .map_err(ServerError::bad_request)?;
    entity = entity.with_scope(scope.clone());
    entity.attributes = namespace_graph_attributes(body.attributes, namespace);

    Ok(entity)
}

fn graph_relation_from_request(
    body: ServerGraphRelationRequest,
    namespace: &str,
    scope: &MemoryScope,
) -> Result<Relation, ServerError> {
    let valid_from = now_or_unix(body.valid_from_unix)?;
    let ingested_at = body
        .ingested_at_unix
        .map_or(Ok(valid_from), required_time_from_unix)?;
    let mut relation = Relation::new(
        body.relation_type,
        parse_entity_id(&body.from_entity)?,
        parse_entity_id(&body.to_entity)?,
        body.memory_id
            .as_deref()
            .map(parse_memory_id)
            .transpose()
            .map_err(ServerError::bad_request)?,
        TemporalBounds {
            valid_from,
            valid_to: optional_time_from_unix(body.valid_to_unix)?,
            ingested_at,
        },
    );

    if let Some(id) = body.id {
        relation.id = parse_relation_id(&id)?;
    }
    relation = relation.with_scope(scope.clone());
    relation.supersedes = body
        .supersedes
        .as_deref()
        .map(parse_relation_id)
        .transpose()?;
    relation.attributes = namespace_graph_attributes(body.attributes, namespace);

    Ok(relation)
}

fn filter_graph_snapshot_for_scope(
    snapshot: shibahama_core::storage::GraphSnapshot,
    scope: &MemoryScope,
) -> GraphSnapshotDto {
    let entities = snapshot
        .entities
        .into_iter()
        .filter(|entity| graph_entity_in_scope(entity, scope))
        .collect::<Vec<_>>();
    let entity_ids = entities
        .iter()
        .map(|entity| entity.id)
        .collect::<BTreeSet<_>>();
    let relations = snapshot
        .relations
        .into_iter()
        .filter(|relation| {
            graph_relation_in_scope(relation, scope)
                && entity_ids.contains(&relation.from_entity)
                && entity_ids.contains(&relation.to_entity)
        })
        .collect::<Vec<_>>();

    GraphSnapshotDto {
        as_of_unix: snapshot.as_of.unix_timestamp(),
        entities: entities.into_iter().map(GraphEntityDto::from).collect(),
        relations: relations.into_iter().map(GraphRelationDto::from).collect(),
    }
}

fn filter_graph_traversal_for_scope(
    traversal: GraphTraversalResult,
    scope: &MemoryScope,
    as_of: OffsetDateTime,
) -> GraphSnapshotDto {
    let entities = traversal
        .entities
        .into_iter()
        .filter(|entity| graph_entity_in_scope(entity, scope))
        .collect::<Vec<_>>();
    let entity_ids = entities
        .iter()
        .map(|entity| entity.id)
        .collect::<BTreeSet<_>>();
    let relations = traversal
        .relations
        .into_iter()
        .filter(|relation| {
            graph_relation_in_scope(relation, scope)
                && entity_ids.contains(&relation.from_entity)
                && entity_ids.contains(&relation.to_entity)
        })
        .collect::<Vec<_>>();

    GraphSnapshotDto {
        as_of_unix: as_of.unix_timestamp(),
        entities: entities.into_iter().map(GraphEntityDto::from).collect(),
        relations: relations.into_iter().map(GraphRelationDto::from).collect(),
    }
}

fn server_json_result<T>(
    method: &'static str,
    route: &'static str,
    context: &ServerRequestContext,
    result: Result<(Json<T>, serde_json::Value), ServerError>,
) -> Result<Json<T>, ServerError> {
    match result {
        Ok((response, cost)) => {
            log_server_request(
                method,
                route,
                Some(&context.namespace),
                &context.principal,
                StatusCode::OK,
                cost,
            );
            Ok(response)
        }
        Err(error) => {
            log_server_request(
                method,
                route,
                Some(&context.namespace),
                &context.principal,
                error.status,
                json!({ "request_units": 1 }),
            );
            Err(error)
        }
    }
}

fn ensure_memory_in_scope(
    engine: &Shibahama<HnswVectorIndex>,
    id: MemoryId,
    scope: &MemoryScope,
) -> Result<MemoryItem, ServerError> {
    let Some(item) = engine
        .memory_items()
        .map_err(ServerError::internal)?
        .into_iter()
        .find(|item| item.id == id)
    else {
        return Err(ServerError::not_found(format!("memory {id} not found")));
    };

    if memory_in_scope(&item, scope) {
        Ok(item)
    } else {
        Err(ServerError::not_found(format!(
            "memory {id} not found in scope"
        )))
    }
}

fn event_records_for_scope(
    state: &ServerState,
    scope: &MemoryScope,
    as_of: Option<OffsetDateTime>,
) -> Result<Vec<EventRecord>, ServerError> {
    let engine = state
        .engine
        .lock()
        .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
    Ok(engine
        .store()
        .events_in_scope(scope)
        .map_err(ServerError::internal)?
        .into_iter()
        .filter(|record| as_of.is_none_or(|instant| record.recorded_at <= instant))
        .collect())
}

fn tideline_snapshot_for_scope(
    state: &ServerState,
    namespace: &str,
    scope: &MemoryScope,
    as_of: Option<OffsetDateTime>,
) -> Result<TidelineSnapshotDto, ServerError> {
    let engine = state
        .engine
        .lock()
        .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
    let scoped_memories = engine
        .store()
        .memory_items_in_scope(scope)
        .map_err(ServerError::internal)?
        .into_iter()
        .filter(|item| as_of.is_none_or(|instant| memory_believed_at(item, instant)))
        .collect::<Vec<_>>();
    let event_records = engine
        .store()
        .events_in_scope(scope)
        .map_err(ServerError::internal)?
        .into_iter()
        .filter(|record| as_of.is_none_or(|instant| record.recorded_at <= instant))
        .collect::<Vec<_>>();
    let last_sequence = event_records.last().map(|record| record.sequence);
    let graph = tideline_graph(&scoped_memories, &event_records);
    let event_count = event_records.len();
    let memories = scoped_memories
        .into_iter()
        .map(MemoryItemDto::from)
        .collect::<Vec<_>>();
    let events = event_records
        .into_iter()
        .map(tideline_event_from_record)
        .collect::<Vec<_>>();

    Ok(TidelineSnapshotDto {
        schema_version: 1,
        version: shibahama_core::version(),
        path: state.path.clone(),
        namespace: namespace.to_owned(),
        generated_at_unix: OffsetDateTime::now_utc().unix_timestamp(),
        as_of_unix: as_of.map(OffsetDateTime::unix_timestamp),
        memory_count: memories.len(),
        event_count,
        last_sequence,
        memories,
        events,
        graph,
    })
}

fn memory_believed_at(item: &MemoryItem, as_of: OffsetDateTime) -> bool {
    item.timestamps.ingested_at <= as_of && item.timestamps.is_valid_at(as_of)
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
        | MemoryEvent::PolicyDecisionRecorded { .. }
        | MemoryEvent::ReviewCandidateQueued { .. }
        | MemoryEvent::ObservabilityRecorded { .. } => false,
        MemoryEvent::ReviewDecisionRecorded { decision } => decision
            .approved_memory_id
            .is_some_and(|memory_id| memory_id == id),
        MemoryEvent::AutomaticCaptureRecorded { record } => {
            record.memory_id.is_some_and(|memory_id| memory_id == id)
        }
        MemoryEvent::MemoryInvalidated { id: event_id, .. }
        | MemoryEvent::MemoryRecordKeyDestroyed { id: event_id, .. }
        | MemoryEvent::ReverificationFlagged { id: event_id, .. }
        | MemoryEvent::AccessRecorded { id: event_id, .. }
        | MemoryEvent::TierChanged { id: event_id, .. }
        | MemoryEvent::ContentCompacted { id: event_id, .. } => *event_id == id,
        MemoryEvent::MemorySemanticallyErased { tombstone } => tombstone.memory_id == id,
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

#[allow(clippy::too_many_lines)]
fn tideline_event_from_record(record: EventRecord) -> TidelineEventDto {
    let sequence = record.sequence;
    let recorded_at = record.recorded_at;

    match record.event {
        MemoryEvent::MemoryWritten { item } => {
            tideline_memory_written_event(sequence, recorded_at, item)
        }
        MemoryEvent::MemoryScopePromoted {
            source_id,
            promoted_id,
            actor,
            rationale,
            ..
        } => tideline_scope_promotion_event(
            sequence,
            recorded_at,
            source_id,
            promoted_id,
            actor,
            rationale,
        ),
        MemoryEvent::ScopeAuthorizationDenied { principal, .. } => {
            tideline_scope_authorization_denied_event(sequence, recorded_at, principal)
        }
        MemoryEvent::PolicyDecisionRecorded { .. } => {
            base_tideline_event(sequence, recorded_at, "policy_decision", Vec::new())
        }
        MemoryEvent::ReviewCandidateQueued { .. } => {
            base_tideline_event(sequence, recorded_at, "review_candidate_queued", Vec::new())
        }
        MemoryEvent::ReviewDecisionRecorded { decision } => base_tideline_event(
            sequence,
            recorded_at,
            "review_decision",
            decision.approved_memory_id.into_iter().collect(),
        ),
        MemoryEvent::AutomaticCaptureRecorded { record } => base_tideline_event(
            sequence,
            recorded_at,
            "automatic_capture",
            record.memory_id.into_iter().collect(),
        ),
        MemoryEvent::ObservabilityRecorded { .. } => {
            base_tideline_event(sequence, recorded_at, "observability", Vec::new())
        }
        MemoryEvent::MemoryInvalidated { id, valid_to } => {
            let mut event =
                base_tideline_event(sequence, recorded_at, "memory_invalidated", vec![id]);
            event.valid_to_unix = Some(valid_to.unix_timestamp());
            event
        }
        MemoryEvent::MemoryRecordKeyDestroyed { id, .. } => base_tideline_event(
            sequence,
            recorded_at,
            "memory_record_key_destroyed",
            vec![id],
        ),
        MemoryEvent::MemorySemanticallyErased { tombstone } => base_tideline_event(
            sequence,
            recorded_at,
            "memory_semantically_erased",
            vec![tombstone.memory_id],
        ),
        MemoryEvent::ReverificationFlagged { id, flagged_at, .. } => {
            let mut event =
                base_tideline_event(sequence, recorded_at, "reverification_flagged", vec![id]);
            event.valid_to_unix = Some(flagged_at.unix_timestamp());
            event
        }
        MemoryEvent::AccessRecorded { id, event } => {
            let mut dto = base_tideline_event(sequence, recorded_at, "access_recorded", vec![id]);
            dto.access_outcome = Some(format!("{:?}", event.outcome));
            dto
        }
        MemoryEvent::TierChanged { id, from, to, .. } => {
            let mut event = base_tideline_event(sequence, recorded_at, "tier_changed", vec![id]);
            event.tier_from = Some(tier_str(from).to_owned());
            event.tier_to = Some(tier_str(to).to_owned());
            event
        }
        MemoryEvent::ContentCompacted { id, .. } => {
            let mut event =
                base_tideline_event(sequence, recorded_at, "content_compacted", vec![id]);
            event.tier_to = Some("cold".to_owned());
            event
        }
        MemoryEvent::ReconstructionApplied {
            superseded_id,
            replacement_id,
            valid_to,
        } => {
            let mut event = base_tideline_event(
                sequence,
                recorded_at,
                "reconstruction_applied",
                vec![superseded_id, replacement_id],
            );
            event.valid_to_unix = Some(valid_to.unix_timestamp());
            event
        }
        MemoryEvent::ConsolidationDecision {
            action,
            input_ids,
            output_id,
            tier_from,
            tier_to,
            why,
            ..
        } => consolidation_tideline_event(
            sequence,
            recorded_at,
            ConsolidationEventParts {
                action,
                input_ids,
                output_id,
                tier_from,
                tier_to,
                why,
            },
        ),
        MemoryEvent::HumanSignalRecorded { signal } => {
            let mut memory_ids = vec![signal.memory_id];

            if let Some(proposal_id) = signal.proposal_id {
                memory_ids.push(proposal_id);
            }

            let mut event = base_tideline_event(sequence, recorded_at, "human_signal", memory_ids);
            event.human_signal_action = Some(human_signal_action_str(signal.action).to_owned());
            event.human_signal_actor = Some(signal.actor);
            event.human_signal_reason = Some(signal.reason);
            event
        }
    }
}

fn tideline_memory_written_event(
    sequence: u64,
    recorded_at: OffsetDateTime,
    item: Box<MemoryItem>,
) -> TidelineEventDto {
    let mut event = base_tideline_event(sequence, recorded_at, "memory_written", vec![item.id]);
    event.tier_to = Some(tier_str(item.tier).to_owned());
    event.valid_to_unix = item.timestamps.valid_to.map(OffsetDateTime::unix_timestamp);
    event
}

fn tideline_scope_promotion_event(
    sequence: u64,
    recorded_at: OffsetDateTime,
    source_id: MemoryId,
    promoted_id: MemoryId,
    actor: String,
    rationale: String,
) -> TidelineEventDto {
    let mut event = base_tideline_event(
        sequence,
        recorded_at,
        "memory_scope_promoted",
        vec![source_id, promoted_id],
    );
    event.human_signal_actor = Some(actor);
    event.human_signal_reason = Some(rationale);
    event
}

fn tideline_scope_authorization_denied_event(
    sequence: u64,
    recorded_at: OffsetDateTime,
    principal: String,
) -> TidelineEventDto {
    let mut event = base_tideline_event(
        sequence,
        recorded_at,
        "scope_authorization_denied",
        Vec::new(),
    );
    event.human_signal_actor = Some(principal);
    event
}

fn base_tideline_event(
    sequence: u64,
    recorded_at: OffsetDateTime,
    kind: &str,
    memory_ids: Vec<MemoryId>,
) -> TidelineEventDto {
    TidelineEventDto {
        sequence,
        recorded_at_unix: recorded_at.unix_timestamp(),
        kind: kind.to_owned(),
        memory_ids: memory_ids.into_iter().map(|id| id.to_string()).collect(),
        tier_from: None,
        tier_to: None,
        access_outcome: None,
        valid_to_unix: None,
        consolidation_action: None,
        consolidation_why: None,
        consolidation_evidence: Vec::new(),
        human_signal_action: None,
        human_signal_actor: None,
        human_signal_reason: None,
    }
}

fn consolidation_tideline_event(
    sequence: u64,
    recorded_at: OffsetDateTime,
    parts: ConsolidationEventParts,
) -> TidelineEventDto {
    let mut memory_ids = parts.input_ids;

    if let Some(output_id) = parts.output_id {
        memory_ids.push(output_id);
    }

    let mut event =
        base_tideline_event(sequence, recorded_at, "consolidation_decision", memory_ids);

    event.tier_from = parts.tier_from.map(|tier| tier_str(tier).to_owned());
    event.tier_to = parts.tier_to.map(|tier| tier_str(tier).to_owned());
    event.consolidation_action = Some(consolidation_action_str(parts.action).to_owned());
    event.consolidation_why = Some(parts.why.summary);
    event.consolidation_evidence = parts
        .why
        .evidence
        .into_iter()
        .map(|evidence| TidelineConsolidationEvidenceDto {
            memory_id: evidence.memory_id.to_string(),
            significance: evidence.significance,
            access_count: evidence.access_count,
            actual_use_count: evidence.actual_use_count,
            contradiction_count: evidence.contradiction_count,
            tier: tier_str(evidence.tier).to_owned(),
            credence: credence_str(evidence.credence).to_owned(),
            credence_floor: tier_str(evidence.credence_floor).to_owned(),
        })
        .collect();

    event
}

fn consolidation_action_str(action: ConsolidationAction) -> &'static str {
    match action {
        ConsolidationAction::Merge => "merge",
        ConsolidationAction::Promote => "promote",
        ConsolidationAction::Demote => "demote",
        ConsolidationAction::FlagStale => "flag_stale",
    }
}

fn human_signal_action_str(action: HumanSignalAction) -> &'static str {
    match action {
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
        MemoryEvent::ReviewCandidateQueued { .. } => "review_candidate_queued",
        MemoryEvent::ReviewDecisionRecorded { .. } => "review_decision",
        MemoryEvent::AutomaticCaptureRecorded { .. } => "automatic_capture",
        MemoryEvent::ObservabilityRecorded { .. } => "observability",
        MemoryEvent::MemoryInvalidated { .. } => "memory_invalidated",
        MemoryEvent::MemoryRecordKeyDestroyed { .. } => "memory_record_key_destroyed",
        MemoryEvent::MemorySemanticallyErased { .. } => "memory_semantically_erased",
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
        | MemoryEvent::PolicyDecisionRecorded { .. }
        | MemoryEvent::ReviewCandidateQueued { .. }
        | MemoryEvent::ObservabilityRecorded { .. } => Vec::new(),
        MemoryEvent::ReviewDecisionRecorded { decision } => decision
            .approved_memory_id
            .iter()
            .map(ToString::to_string)
            .collect(),
        MemoryEvent::AutomaticCaptureRecorded { record } => {
            record.memory_id.iter().map(ToString::to_string).collect()
        }
        MemoryEvent::MemoryInvalidated { id, .. }
        | MemoryEvent::MemoryRecordKeyDestroyed { id, .. }
        | MemoryEvent::ReverificationFlagged { id, .. }
        | MemoryEvent::AccessRecorded { id, .. }
        | MemoryEvent::TierChanged { id, .. }
        | MemoryEvent::ContentCompacted { id, .. } => vec![id.to_string()],
        MemoryEvent::MemorySemanticallyErased { tombstone } => {
            vec![tombstone.memory_id.to_string()]
        }
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

fn tideline_graph(memories: &[MemoryItem], event_records: &[EventRecord]) -> TidelineGraphDto {
    let nodes = tideline_graph_nodes(memories);
    let namespace_ids = memories.iter().map(|item| item.id).collect::<BTreeSet<_>>();
    let mut edges = Vec::new();

    for record in event_records {
        append_tideline_graph_edges(record, &namespace_ids, &mut edges);
    }

    TidelineGraphDto { nodes, edges }
}

fn tideline_graph_nodes(memories: &[MemoryItem]) -> Vec<TidelineGraphNodeDto> {
    memories
        .iter()
        .map(|item| TidelineGraphNodeDto {
            id: item.id.to_string(),
            label: memory_label(&item.content),
            tier: tier_str(item.tier).to_owned(),
            credence: credence_str(item.credence).to_owned(),
            significance: item.significance,
            valid_from_unix: item.timestamps.valid_from.unix_timestamp(),
            valid_to_unix: item.timestamps.valid_to.map(OffsetDateTime::unix_timestamp),
        })
        .collect()
}

fn append_tideline_graph_edges(
    record: &EventRecord,
    namespace_ids: &BTreeSet<MemoryId>,
    edges: &mut Vec<TidelineGraphEdgeDto>,
) {
    match &record.event {
        MemoryEvent::MemoryInvalidated { id, valid_to } if namespace_ids.contains(id) => {
            edges.push(self_edge(record, *id, "invalidated", None, Some(*valid_to)));
        }
        MemoryEvent::ReverificationFlagged { id, flagged_at, .. } if namespace_ids.contains(id) => {
            edges.push(self_edge(
                record,
                *id,
                "reverification_flagged",
                Some(*flagged_at),
                None,
            ));
        }
        MemoryEvent::ReconstructionApplied {
            superseded_id,
            replacement_id,
            valid_to,
        } if namespace_ids.contains(superseded_id) || namespace_ids.contains(replacement_id) => {
            edges.push(TidelineGraphEdgeDto {
                id: format!("event-{}-reconstruction", record.sequence),
                from: superseded_id.to_string(),
                to: replacement_id.to_string(),
                kind: "reconstruction".to_owned(),
                valid_from_unix: None,
                valid_to_unix: Some(valid_to.unix_timestamp()),
            });
        }
        MemoryEvent::TierChanged { id, .. } if namespace_ids.contains(id) => {
            edges.push(self_edge(
                record,
                *id,
                "tier_transition",
                Some(record.recorded_at),
                None,
            ));
        }
        MemoryEvent::ConsolidationDecision {
            action,
            input_ids,
            output_id,
            ..
        } => append_consolidation_graph_edges(
            record,
            namespace_ids,
            edges,
            *action,
            input_ids,
            *output_id,
        ),
        MemoryEvent::HumanSignalRecorded { signal }
            if namespace_ids.contains(&signal.memory_id) =>
        {
            edges.push(self_edge(
                record,
                signal.memory_id,
                &format!("human_{}", human_signal_action_str(signal.action)),
                Some(signal.timestamp),
                None,
            ));
        }
        _ => {}
    }
}

fn self_edge(
    record: &EventRecord,
    id: MemoryId,
    kind: &str,
    valid_from: Option<OffsetDateTime>,
    valid_to: Option<OffsetDateTime>,
) -> TidelineGraphEdgeDto {
    TidelineGraphEdgeDto {
        id: format!("event-{}-{kind}", record.sequence),
        from: id.to_string(),
        to: id.to_string(),
        kind: kind.to_owned(),
        valid_from_unix: valid_from.map(OffsetDateTime::unix_timestamp),
        valid_to_unix: valid_to.map(OffsetDateTime::unix_timestamp),
    }
}

fn append_consolidation_graph_edges(
    record: &EventRecord,
    namespace_ids: &BTreeSet<MemoryId>,
    edges: &mut Vec<TidelineGraphEdgeDto>,
    action: ConsolidationAction,
    input_ids: &[MemoryId],
    output_id: Option<MemoryId>,
) {
    if action == ConsolidationAction::Merge
        && let Some(output_id) = output_id
        && (input_ids.iter().any(|id| namespace_ids.contains(id))
            || namespace_ids.contains(&output_id))
    {
        for input_id in input_ids {
            edges.push(consolidation_edge(
                record,
                *input_id,
                output_id,
                "consolidation_merge",
            ));
        }
        return;
    }

    for input_id in input_ids {
        if namespace_ids.contains(input_id) {
            edges.push(consolidation_edge(
                record,
                *input_id,
                *input_id,
                &format!("consolidation_{}", consolidation_action_str(action)),
            ));
        }
    }
}

fn consolidation_edge(
    record: &EventRecord,
    from: MemoryId,
    to: MemoryId,
    kind: &str,
) -> TidelineGraphEdgeDto {
    TidelineGraphEdgeDto {
        id: format!("event-{}-consolidation-{from}", record.sequence),
        from: from.to_string(),
        to: to.to_string(),
        kind: kind.to_owned(),
        valid_from_unix: Some(record.recorded_at.unix_timestamp()),
        valid_to_unix: None,
    }
}

fn memory_label(content: &str) -> String {
    let normalized = content.split_whitespace().collect::<Vec<_>>().join(" ");

    if normalized.chars().count() <= 64 {
        normalized
    } else {
        let mut label = normalized.chars().take(61).collect::<String>();
        label.push_str("...");
        label
    }
}

async fn server_operational_log_middleware(
    State(state): State<ServerState>,
    request: Request,
    next: Next,
) -> Response {
    let method = request.method().to_string();
    let route = request
        .extensions()
        .get::<MatchedPath>()
        .map_or_else(|| "unmatched".to_owned(), |path| path.as_str().to_owned());
    let namespace = request_namespace(request.headers(), &state).ok();
    let context = ServerRequestLogContext {
        started_at: Instant::now(),
        emitted: Arc::new(AtomicBool::new(false)),
        scope_hash_key: state.operational_log_key,
    };

    SERVER_REQUEST_LOG_CONTEXT
        .scope(context.clone(), async move {
            let response = next.run(request).await;
            shibahama_core::telemetry::record_boundary(
                shibahama_core::telemetry::TelemetryBoundary::Http,
                shibahama_core::telemetry::TelemetryOperation::Request,
                if response.status().is_success() {
                    shibahama_core::telemetry::TelemetryStatus::Ok
                } else {
                    shibahama_core::telemetry::TelemetryStatus::Error
                },
            );
            if !context.emitted.swap(true, Ordering::Relaxed) {
                emit_server_operational_log(
                    &method,
                    &route,
                    namespace.as_deref(),
                    "unknown",
                    response.status(),
                    &json!({}),
                    context
                        .started_at
                        .elapsed()
                        .as_millis()
                        .try_into()
                        .unwrap_or(u64::MAX),
                );
            }
            response
        })
        .await
}

fn log_server_request(
    method: &str,
    route: &str,
    namespace: Option<&str>,
    principal: impl AsRef<str>,
    status: StatusCode,
    cost: serde_json::Value,
) {
    let elapsed_ms = SERVER_REQUEST_LOG_CONTEXT
        .try_with(|context| {
            context.emitted.store(true, Ordering::Relaxed);
            context
                .started_at
                .elapsed()
                .as_millis()
                .try_into()
                .unwrap_or(u64::MAX)
        })
        .unwrap_or(0);
    emit_server_operational_log(
        method,
        route,
        namespace,
        principal.as_ref(),
        status,
        &cost,
        elapsed_ms,
    );
}

fn emit_server_operational_log(
    method: &str,
    route: &str,
    namespace: Option<&str>,
    principal: &str,
    status: StatusCode,
    cost: &serde_json::Value,
    duration_ms: u64,
) {
    let record = server_operational_log_record(
        method,
        route,
        namespace,
        principal,
        status,
        cost,
        duration_ms,
    );

    eprintln!("{record}");
}

fn server_operational_log_record(
    method: &str,
    route: &str,
    namespace: Option<&str>,
    principal: &str,
    status: StatusCode,
    cost: &serde_json::Value,
    duration_ms: u64,
) -> serde_json::Value {
    let scope_hash_key = SERVER_REQUEST_LOG_CONTEXT
        .try_with(|context| context.scope_hash_key)
        .unwrap_or([0; 32]);
    let error_code = cost
        .get("error_code")
        .and_then(serde_json::Value::as_str)
        .filter(|code| code.starts_with("SHIBA_"))
        .map(ToOwned::to_owned)
        .or_else(|| (!status.is_success()).then(|| format!("SHIBA_HTTP_{}", status.as_u16())));

    json!({
        "schema_version": OPERATIONAL_LOG_SCHEMA_VERSION,
        "event": "shibahama.operational",
        "timestamp_unix": OffsetDateTime::now_utc().unix_timestamp(),
        "component": "embedded_server",
        "operation": format!("{method} {route}"),
        "scope_id": operational_log_scope_id(namespace.unwrap_or("unknown"), &scope_hash_key),
        "principal_class": service_principal_class(principal),
        "duration_ms": duration_ms,
        "status": status.as_u16(),
        "error_code": error_code,
        "metrics": operational_log_metrics(cost),
    })
}

fn operational_log_key() -> [u8; 32] {
    *blake3::hash(Uuid::new_v4().as_bytes()).as_bytes()
}

fn operational_log_scope_id(scope: &str, key: &[u8; 32]) -> String {
    let mut hasher = blake3::Hasher::new_keyed(key);

    hasher.update(OPERATIONAL_LOG_SCOPE_DOMAIN);
    hasher.update(&[0]);
    hasher.update(scope.as_bytes());
    format!("scope_{}", &hasher.finalize().to_hex()[..16])
}

fn operational_log_metrics(cost: &serde_json::Value) -> serde_json::Map<String, serde_json::Value> {
    let Some(cost) = cost.as_object() else {
        return serde_json::Map::new();
    };

    cost.iter()
        .filter(|(key, value)| operational_log_metric_key_is_safe(key) && value.is_number())
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect()
}

fn operational_log_metric_key_is_safe(key: &str) -> bool {
    key.bytes()
        .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
        && ![
            "content",
            "vector",
            "ref",
            "credential",
            "claim",
            "secret",
            "token",
            "principal",
        ]
        .iter()
        .any(|forbidden| key.contains(forbidden))
}

fn service_principal_class(principal: &str) -> &'static str {
    if principal.starts_with("service:") {
        "service_token"
    } else if principal.starts_with("oidc:") {
        "oidc"
    } else if principal == "api_key" {
        "api_key"
    } else if principal == "anonymous" {
        "anonymous"
    } else {
        "unknown"
    }
}

async fn server_mcp_post(
    State(state): State<ServerState>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if !mcp_origin_is_allowed(&headers) {
        return mcp_transport_error(StatusCode::FORBIDDEN, -32000, "Origin rejected");
    }
    if !mcp_accepts(&headers, "application/json") || !mcp_accepts(&headers, "text/event-stream") {
        return mcp_transport_error(
            StatusCode::NOT_ACCEPTABLE,
            -32000,
            "Accept must include application/json and text/event-stream",
        );
    }
    let context = match server_mcp_context_or_log(&headers, &state, "POST") {
        Ok(context) => context,
        Err(error) => return error.into_response(),
    };
    let Ok(message) = serde_json::from_slice::<serde_json::Value>(&body) else {
        return mcp_transport_error(StatusCode::BAD_REQUEST, -32700, "Parse error");
    };

    if mcp::is_initialize_request(&message) {
        if headers.contains_key("mcp-session-id") {
            return mcp_transport_error(
                StatusCode::BAD_REQUEST,
                -32000,
                "Initialize must not include MCP-Session-Id",
            );
        }
        let mut session = mcp::McpSession::new(context);
        let Some(response) = session.handle(message) else {
            return mcp_transport_error(
                StatusCode::BAD_REQUEST,
                -32600,
                "Invalid initialize request",
            );
        };
        if response.get("result").is_none() {
            return mcp_json_response(StatusCode::OK, response, None);
        }
        let session_id = Uuid::now_v7().to_string();
        let Ok(mut sessions) = state.mcp_sessions.lock() else {
            return mcp_transport_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                -32603,
                "Internal error",
            );
        };
        sessions.insert(session_id.clone(), session);
        return mcp_json_response(StatusCode::OK, response, Some(&session_id));
    }

    if !mcp_protocol_version_is_current(&headers) {
        return mcp_transport_error(
            StatusCode::BAD_REQUEST,
            -32000,
            "Unsupported MCP protocol version",
        );
    }
    let Some(session_id) = headers
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok())
    else {
        return mcp_transport_error(
            StatusCode::BAD_REQUEST,
            -32000,
            "MCP-Session-Id is required",
        );
    };
    let Ok(mut sessions) = state.mcp_sessions.lock() else {
        return mcp_transport_error(StatusCode::INTERNAL_SERVER_ERROR, -32603, "Internal error");
    };
    let Some(session) = sessions.get_mut(session_id) else {
        return mcp_transport_error(StatusCode::NOT_FOUND, -32000, "MCP session not found");
    };
    if !session.matches_context(&context) {
        return mcp_transport_error(
            StatusCode::FORBIDDEN,
            -32000,
            "MCP session context mismatch",
        );
    }
    let Ok(mut engine) = state.engine.lock() else {
        return mcp_transport_error(StatusCode::INTERNAL_SERVER_ERROR, -32603, "Internal error");
    };
    let mut backend = mcp_tools::McpEngineBackend::with_rbac(
        &mut engine,
        mcp_tools::McpRbacPolicy {
            enforce: state.rbac.enforce,
            erasure_min_role: state.rbac.erasure_min_role,
            promotion_min_role: state.rbac.promotion_min_role,
        },
    );
    match session.handle_with(message, &mut backend) {
        Some(response) => mcp_json_response(StatusCode::OK, response, None),
        None => StatusCode::ACCEPTED.into_response(),
    }
}

async fn server_mcp_get(State(state): State<ServerState>, headers: HeaderMap) -> Response {
    if !mcp_origin_is_allowed(&headers) {
        return mcp_transport_error(StatusCode::FORBIDDEN, -32000, "Origin rejected");
    }
    if !mcp_accepts(&headers, "text/event-stream") {
        return mcp_transport_error(
            StatusCode::NOT_ACCEPTABLE,
            -32000,
            "Accept must include text/event-stream",
        );
    }
    if let Err(error) = server_mcp_context_or_log(&headers, &state, "GET") {
        return error.into_response();
    }
    StatusCode::METHOD_NOT_ALLOWED.into_response()
}

async fn server_mcp_delete(State(state): State<ServerState>, headers: HeaderMap) -> Response {
    if !mcp_origin_is_allowed(&headers) {
        return mcp_transport_error(StatusCode::FORBIDDEN, -32000, "Origin rejected");
    }
    if !mcp_protocol_version_is_current(&headers) {
        return mcp_transport_error(
            StatusCode::BAD_REQUEST,
            -32000,
            "Unsupported MCP protocol version",
        );
    }
    let context = match server_mcp_context_or_log(&headers, &state, "DELETE") {
        Ok(context) => context,
        Err(error) => return error.into_response(),
    };
    let Some(session_id) = headers
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok())
    else {
        return mcp_transport_error(
            StatusCode::BAD_REQUEST,
            -32000,
            "MCP-Session-Id is required",
        );
    };
    let Ok(mut sessions) = state.mcp_sessions.lock() else {
        return mcp_transport_error(StatusCode::INTERNAL_SERVER_ERROR, -32603, "Internal error");
    };
    let Some(session) = sessions.get(session_id) else {
        return mcp_transport_error(StatusCode::NOT_FOUND, -32000, "MCP session not found");
    };
    if !session.matches_context(&context) {
        return mcp_transport_error(
            StatusCode::FORBIDDEN,
            -32000,
            "MCP session context mismatch",
        );
    }
    sessions.remove(session_id);
    StatusCode::NO_CONTENT.into_response()
}

fn mcp_origin_is_allowed(headers: &HeaderMap) -> bool {
    headers.get(ORIGIN).is_none()
}

fn mcp_accepts(headers: &HeaderMap, expected: &str) -> bool {
    headers
        .get(ACCEPT)
        .and_then(|value| value.to_str().ok())
        .is_some_and(|accepted| {
            accepted.split(',').any(|entry| {
                entry
                    .split(';')
                    .next()
                    .is_some_and(|mime| mime.trim().eq_ignore_ascii_case(expected))
            })
        })
}

fn mcp_protocol_version_is_current(headers: &HeaderMap) -> bool {
    headers
        .get("mcp-protocol-version")
        .and_then(|value| value.to_str().ok())
        == Some(mcp::PROTOCOL_VERSION)
}

fn mcp_json_response(
    status: StatusCode,
    body: serde_json::Value,
    session_id: Option<&str>,
) -> Response {
    let mut response = (status, Json(body)).into_response();
    response.headers_mut().insert(
        CONTENT_TYPE,
        HeaderValue::from_static("application/json; charset=utf-8"),
    );
    if let Some(session_id) = session_id {
        let Ok(session_id) = HeaderValue::from_str(session_id) else {
            return mcp_transport_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                -32603,
                "Internal error",
            );
        };
        response.headers_mut().insert("mcp-session-id", session_id);
    }
    response
}

fn mcp_transport_error(status: StatusCode, code: i64, message: &str) -> Response {
    mcp_json_response(
        status,
        json!({
            "jsonrpc": "2.0",
            "id": null,
            "error": { "code": code, "message": message },
        }),
        None,
    )
}

async fn server_health() -> Json<serde_json::Value> {
    Json(json!({
        "status": "ok",
        "version": shibahama_core::version(),
    }))
}

async fn server_capabilities() -> Json<shibahama_core::CapabilityDocument> {
    Json(shibahama_core::capabilities())
}

async fn server_ready(
    State(state): State<ServerState>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/readyz")?;
    let result: Result<(Json<serde_json::Value>, serde_json::Value), ServerError> = (|| {
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let memories = engine.memory_items().map_err(ServerError::internal)?;
        let memory_count = memories
            .iter()
            .filter(|item| memory_in_scope(item, &context.scope))
            .count();

        Ok((
            Json(json!({
                "status": "ready",
                "path": state.path,
                "namespace": context.namespace,
                "memory_count": memory_count,
                "max_memories_per_namespace": state.max_memories_per_namespace,
            })),
            json!({
                "request_units": 1,
                "memories_scanned": memories.len(),
                "namespace_memory_count": memory_count,
            }),
        ))
    })();

    match result {
        Ok((response, cost)) => {
            log_server_request(
                "GET",
                "/readyz",
                Some(&context.namespace),
                context.principal,
                StatusCode::OK,
                cost,
            );
            Ok(response)
        }
        Err(error) => {
            log_server_request(
                "GET",
                "/readyz",
                Some(&context.namespace),
                context.principal,
                error.status,
                json!({ "request_units": 1 }),
            );
            Err(error)
        }
    }
}

async fn server_inspect(
    State(state): State<ServerState>,
    headers: HeaderMap,
) -> Result<Json<InspectOutput>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/inspect")?;
    let result: Result<(Json<InspectOutput>, serde_json::Value), ServerError> = (|| {
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let all_memories = engine.memory_items().map_err(ServerError::internal)?;
        let memories = all_memories
            .iter()
            .filter(|item| memory_in_scope(item, &context.scope))
            .cloned()
            .map(MemoryItemDto::from)
            .collect::<Vec<_>>();

        Ok((
            Json(InspectOutput {
                version: shibahama_core::version(),
                path: state.path,
                memory_count: memories.len(),
                memories,
            }),
            json!({
                "request_units": 1,
                "memories_scanned": all_memories.len(),
            }),
        ))
    })();

    match result {
        Ok((response, cost)) => {
            log_server_request(
                "GET",
                "/inspect",
                Some(&context.namespace),
                context.principal,
                StatusCode::OK,
                cost,
            );
            Ok(response)
        }
        Err(error) => {
            log_server_request(
                "GET",
                "/inspect",
                Some(&context.namespace),
                context.principal,
                error.status,
                json!({ "request_units": 1 }),
            );
            Err(error)
        }
    }
}

async fn server_simulate_capture_policy(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerCapturePolicySimulationRequest>,
) -> Result<Json<serde_json::Value>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/policy/simulate/capture")?;
    let result: Result<(Json<serde_json::Value>, serde_json::Value), ServerError> = (|| {
        let source_kind = parse_source_kind(body.source_kind.as_deref().unwrap_or("user"))
            .map_err(ServerError::bad_request)?;
        let request = CapturePolicyRequest {
            actor: parse_policy_actor(body.actor.as_deref().unwrap_or("human"))
                .map_err(ServerError::bad_request)?,
            intent: parse_capture_intent(body.intent.as_deref().unwrap_or("manual"))
                .map_err(ServerError::bad_request)?,
            confidence_percent: body.confidence_percent.unwrap_or(100),
        };
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let simulation = engine.simulate_capture_policy(source_kind, &context.scope, request);
        let response = serde_json::to_value(simulation).map_err(ServerError::internal)?;

        Ok((
            Json(response),
            json!({ "request_units": 1, "dry_run": true }),
        ))
    })();

    server_json_result("POST", "/policy/simulate/capture", &context, result)
}

async fn server_simulate_recall_policy(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerRecallPolicySimulationRequest>,
) -> Result<Json<serde_json::Value>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/policy/simulate/recall")?;
    let result: Result<(Json<serde_json::Value>, serde_json::Value), ServerError> = (|| {
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let simulation = engine.simulate_recall_policy(
            body.top_k.unwrap_or(8),
            body.max_context_tokens,
            body.include_cold.unwrap_or(false),
            body.include_instructions.unwrap_or(false),
            Some(&context.scope),
        );
        let response = serde_json::to_value(simulation).map_err(ServerError::internal)?;

        Ok((
            Json(response),
            json!({ "request_units": 1, "dry_run": true }),
        ))
    })();

    server_json_result("POST", "/policy/simulate/recall", &context, result)
}

async fn server_write(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerWriteRequest>,
) -> Result<Json<MemoryItemDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/write")?;
    let result: Result<(Json<MemoryItemDto>, serde_json::Value), ServerError> = (|| {
        let mut event = write_event(
            body.content,
            body.source_kind.as_deref().unwrap_or("user"),
            Some(namespaced_source_ref(&context.namespace, body.source_ref)),
            body.ingested_by.as_deref().unwrap_or("server"),
            body.valid_from_unix,
            body.ingested_at_unix,
        )
        .map_err(ServerError::bad_request)?;
        let scope = server_memory_scope(body.scope.as_ref(), &context.namespace)?;
        if scope != context.scope {
            return Err(ServerError::bad_request(
                "write scope must match the request scope headers",
            ));
        }
        event = event.with_scope(scope);

        if parse_memory_kind(body.kind.as_deref().unwrap_or("fact"))
            .map_err(ServerError::bad_request)?
            == MemoryKind::Instruction
        {
            event = event.as_instruction();
        }

        let mut engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let namespace_memory_count = engine
            .memory_items()
            .map_err(ServerError::internal)?
            .iter()
            .filter(|item| memory_in_scope(item, &context.scope))
            .count();

        if namespace_memory_count >= state.max_memories_per_namespace {
            return Err(ServerError::too_many_requests(format!(
                "namespace `{}` has reached the configured memory quota of {}",
                context.namespace, state.max_memories_per_namespace
            )));
        }

        let item = if let Some(vector) = body.vector.as_deref() {
            engine.write_with_embedding(
                event,
                WriteEmbedding {
                    vector,
                    index_name: body.index_name.as_deref().unwrap_or("default"),
                    model: body.model.as_deref().unwrap_or("unknown"),
                    model_version: body.model_version.as_deref().unwrap_or("unknown"),
                },
            )
        } else {
            engine.write(event)
        }
        .map_err(ServerError::internal)?;

        Ok((
            Json(MemoryItemDto::from(item)),
            json!({
                "request_units": 1,
                "memory_writes": 1,
                "namespace_memory_count_before": namespace_memory_count,
                "vector_dimensions": body.vector.as_ref().map_or(0, Vec::len),
            }),
        ))
    })();

    match result {
        Ok((response, cost)) => {
            log_server_request(
                "POST",
                "/write",
                Some(&context.namespace),
                context.principal,
                StatusCode::OK,
                cost,
            );
            Ok(response)
        }
        Err(error) => {
            log_server_request(
                "POST",
                "/write",
                Some(&context.namespace),
                context.principal,
                error.status,
                json!({ "request_units": 1, "memory_writes": 0 }),
            );
            Err(error)
        }
    }
}

async fn server_invalidate(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerInvalidateRequest>,
) -> Result<Json<serde_json::Value>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/invalidate")?;
    let result: Result<(Json<serde_json::Value>, serde_json::Value), ServerError> = (|| {
        let id = parse_memory_id(&body.memory_id).map_err(ServerError::bad_request)?;
        let valid_to = OffsetDateTime::from_unix_timestamp(body.valid_to_unix)
            .map_err(ServerError::bad_request)?;
        let mut engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;

        ensure_memory_in_scope(&engine, id, &context.scope)?;
        let applied = engine
            .invalidate(id, valid_to)
            .map_err(ServerError::internal)?;

        Ok((
            Json(json!({ "applied": applied })),
            json!({ "request_units": 1, "memory_writes": i32::from(applied) }),
        ))
    })();

    server_json_result("POST", "/invalidate", &context, result)
}

async fn server_semantic_erase(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerSemanticEraseRequest>,
) -> Result<Json<serde_json::Value>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/erase")?;
    let result: Result<(Json<serde_json::Value>, serde_json::Value), ServerError> = (|| {
        if !valid_semantic_erasure_metadata(&body.authorization_id) {
            return Err(ServerError::bad_request("authorization_id is invalid"));
        }
        let id = parse_memory_id(&body.memory_id).map_err(ServerError::bad_request)?;
        let mut engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;

        ensure_memory_in_scope(&engine, id, &context.scope)?;
        let outcome = engine
            .semantic_erase(
                id,
                SemanticErasureRequest::new(
                    context.principal.clone(),
                    body.authorization_id,
                    OffsetDateTime::now_utc(),
                ),
            )
            .map_err(ServerError::internal)?;
        let applied = outcome.is_some();
        let tombstone = outcome.map(|outcome| {
            json!({
                "memory_id": outcome.tombstone.memory_id.to_string(),
                "scope": MemoryScopeDto::from(outcome.tombstone.scope),
                "erased_at_unix": outcome.tombstone.erased_at.unix_timestamp(),
                "destroyed_record_key_count": outcome.tombstone.destroyed_record_key_count,
                "authorization_id_hash": outcome.tombstone.authorization_id_hash,
                "integrity_hash": outcome.tombstone.integrity_hash,
            })
        });

        Ok((
            Json(json!({
                "applied": applied,
                "irreversible": applied,
                "tombstone": tombstone,
            })),
            json!({ "request_units": 1, "memory_writes": i32::from(applied) }),
        ))
    })();

    server_json_result("POST", "/erase", &context, result)
}

async fn server_admin_bootstrap(
    State(state): State<ServerState>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/admin/bootstrap")?;
    let result: Result<(Json<serde_json::Value>, serde_json::Value), ServerError> = (|| {
        require_authenticated_administration_principal(&context.principal)?;
        let Some(bootstrap) = state.administration.bootstrap.as_ref() else {
            return Err(ServerError::forbidden(
                "administrator bootstrap is not configured",
            ));
        };
        let submitted = operator_secret_from_headers(&headers, "x-shibahama-bootstrap-secret")?;
        let submitted = operator_secret_commitment(&submitted, ADMIN_BOOTSTRAP_SECRET_DOMAIN)
            .map_err(ServerError::unauthorized)?;
        if !commitments_match(&bootstrap.secret_commitment, &submitted) {
            return Err(ServerError::unauthorized(
                "administrator bootstrap secret is invalid",
            ));
        }
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let outcome = engine
            .bootstrap_administrator(
                &submitted,
                context.principal.clone(),
                OffsetDateTime::now_utc(),
            )
            .map_err(ServerError::internal)?;

        match outcome {
            AdministrationBootstrapOutcome::Initialized(_) => Ok((
                Json(json!({ "initialized": true })),
                json!({ "request_units": 1, "administration_writes": 1 }),
            )),
            AdministrationBootstrapOutcome::AlreadyInitialized(_)
            | AdministrationBootstrapOutcome::Expired
            | AdministrationBootstrapOutcome::SecretMismatch
            | AdministrationBootstrapOutcome::NotConfigured => Err(ServerError::forbidden(
                "administrator bootstrap is unavailable",
            )),
        }
    })();

    server_json_result("POST", "/admin/bootstrap", &context, result)
}

async fn server_admin_recover(
    State(state): State<ServerState>,
    headers: HeaderMap,
) -> Result<Json<serde_json::Value>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/admin/recover")?;
    let result: Result<(Json<serde_json::Value>, serde_json::Value), ServerError> = (|| {
        require_authenticated_administration_principal(&context.principal)?;
        let Some(expected) = state.administration.recovery_secret_commitment.as_deref() else {
            return Err(ServerError::forbidden(
                "administrator recovery is not configured",
            ));
        };
        let submitted = operator_secret_from_headers(&headers, "x-shibahama-recovery-secret")?;
        let submitted = operator_secret_commitment(&submitted, ADMIN_RECOVERY_SECRET_DOMAIN)
            .map_err(ServerError::unauthorized)?;
        if !commitments_match(expected, &submitted) {
            return Err(ServerError::unauthorized(
                "administrator recovery secret is invalid",
            ));
        }
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let outcome = engine
            .recover_administrator(context.principal.clone(), OffsetDateTime::now_utc())
            .map_err(ServerError::internal)?;

        match outcome {
            AdministrationRecoveryOutcome::Recovered(_) => Ok((
                Json(json!({ "recovered": true })),
                json!({ "request_units": 1, "administration_writes": 1 }),
            )),
            AdministrationRecoveryOutcome::NotInitialized => Err(ServerError::forbidden(
                "administrator recovery is unavailable",
            )),
        }
    })();

    server_json_result("POST", "/admin/recover", &context, result)
}

async fn server_admin_audit(
    State(state): State<ServerState>,
    headers: HeaderMap,
) -> Result<Json<Vec<AdministrationAuditRecord>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/admin/audit")?;
    let result: Result<(Json<Vec<AdministrationAuditRecord>>, serde_json::Value), ServerError> =
        (|| {
            let engine = state
                .engine
                .lock()
                .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
            require_administrator(&engine, &context.principal)?;
            let audit = engine
                .administration_audit()
                .map_err(ServerError::internal)?;
            let audit_count = audit.len();

            Ok((
                Json(audit),
                json!({ "request_units": 1, "administration_records": audit_count }),
            ))
        })();

    server_json_result("GET", "/admin/audit", &context, result)
}

async fn server_issue_service_token(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerServiceTokenIssueRequest>,
) -> Result<Json<ServerIssuedServiceToken>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/tokens")?;
    authorize_server_rbac_or_log(
        &state,
        &context,
        "POST",
        "/tokens",
        RbacRequirement {
            action: AuthorizationAction::ManageRoles,
            role: RbacRole::Administrator,
        },
        true,
    )?;
    let result: Result<(Json<ServerIssuedServiceToken>, serde_json::Value), ServerError> = (|| {
        let scope = rbac_request_scope(body.scope.as_ref(), &context)?;
        let role = parse_rbac_role(&body.role)?;
        let now = OffsetDateTime::now_utc();
        let expires_at = required_time_from_unix(body.expires_at_unix)?;
        let (material, access_token) = issue_service_token_material(
            scope,
            role,
            context.principal.clone(),
            now,
            expires_at,
            None,
        )?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let token = engine
            .issue_service_token(&material)
            .map_err(ServerError::internal)?;

        Ok((
            Json(ServerIssuedServiceToken {
                token,
                access_token,
            }),
            json!({ "request_units": 1, "service_tokens_issued": 1 }),
        ))
    })();

    server_json_result("POST", "/tokens", &context, result)
}

async fn server_service_tokens(
    State(state): State<ServerState>,
    headers: HeaderMap,
) -> Result<Json<Vec<ServiceToken>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/tokens")?;
    authorize_server_rbac_or_log(
        &state,
        &context,
        "GET",
        "/tokens",
        RbacRequirement {
            action: AuthorizationAction::ManageRoles,
            role: RbacRole::Administrator,
        },
        true,
    )?;
    let result: Result<(Json<Vec<ServiceToken>>, serde_json::Value), ServerError> = (|| {
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let tokens = engine
            .service_tokens_in_scope(&context.scope)
            .map_err(ServerError::internal)?;
        let token_count = tokens.len();

        Ok((
            Json(tokens),
            json!({ "request_units": 1, "service_tokens_returned": token_count }),
        ))
    })();

    server_json_result("GET", "/tokens", &context, result)
}

async fn server_rotate_service_token(
    State(state): State<ServerState>,
    headers: HeaderMap,
    AxumPath(token_id): AxumPath<String>,
    Json(body): Json<ServerServiceTokenRotateRequest>,
) -> Result<Json<ServerIssuedServiceToken>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/tokens/{token_id}/rotate")?;
    authorize_server_rbac_or_log(
        &state,
        &context,
        "POST",
        "/tokens/{token_id}/rotate",
        RbacRequirement {
            action: AuthorizationAction::ManageRoles,
            role: RbacRole::Administrator,
        },
        true,
    )?;
    let result: Result<(Json<ServerIssuedServiceToken>, serde_json::Value), ServerError> = (|| {
        let now = OffsetDateTime::now_utc();
        let expires_at = required_time_from_unix(body.expires_at_unix)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let previous = engine
            .service_tokens_in_scope(&context.scope)
            .map_err(ServerError::internal)?
            .into_iter()
            .find(|token| token.id == token_id)
            .ok_or_else(|| ServerError::not_found("service token not found"))?;
        let (successor, access_token) = issue_service_token_material(
            previous.scope,
            previous.role,
            context.principal.clone(),
            now,
            expires_at,
            Some(token_id.clone()),
        )?;
        let Some(token) = engine
            .rotate_service_token(&token_id, &successor, context.principal.clone(), now)
            .map_err(ServerError::internal)?
        else {
            return Err(ServerError::not_found("service token is not active"));
        };

        Ok((
            Json(ServerIssuedServiceToken {
                token,
                access_token,
            }),
            json!({ "request_units": 1, "service_tokens_rotated": 1 }),
        ))
    })();

    server_json_result("POST", "/tokens/{token_id}/rotate", &context, result)
}

async fn server_revoke_service_token(
    State(state): State<ServerState>,
    headers: HeaderMap,
    AxumPath(token_id): AxumPath<String>,
) -> Result<Json<serde_json::Value>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/tokens/{token_id}/revoke")?;
    authorize_server_rbac_or_log(
        &state,
        &context,
        "POST",
        "/tokens/{token_id}/revoke",
        RbacRequirement {
            action: AuthorizationAction::ManageRoles,
            role: RbacRole::Administrator,
        },
        true,
    )?;
    let result: Result<(Json<serde_json::Value>, serde_json::Value), ServerError> = (|| {
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        if !engine
            .service_tokens_in_scope(&context.scope)
            .map_err(ServerError::internal)?
            .iter()
            .any(|token| token.id == token_id)
        {
            return Err(ServerError::not_found("service token not found"));
        }
        let Some(_) = engine
            .revoke_service_token(
                &token_id,
                context.principal.clone(),
                OffsetDateTime::now_utc(),
            )
            .map_err(ServerError::internal)?
        else {
            return Err(ServerError::not_found("service token is not active"));
        };

        Ok((
            Json(json!({ "revoked": true })),
            json!({ "request_units": 1, "service_tokens_revoked": 1 }),
        ))
    })();

    server_json_result("POST", "/tokens/{token_id}/revoke", &context, result)
}

async fn server_service_token_audit(
    State(state): State<ServerState>,
    headers: HeaderMap,
) -> Result<Json<Vec<ServiceTokenAuditRecord>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/tokens/audit")?;
    authorize_server_rbac_or_log(
        &state,
        &context,
        "GET",
        "/tokens/audit",
        RbacRequirement {
            action: AuthorizationAction::ManageRoles,
            role: RbacRole::Administrator,
        },
        true,
    )?;
    let result: Result<(Json<Vec<ServiceTokenAuditRecord>>, serde_json::Value), ServerError> =
        (|| {
            let engine = state
                .engine
                .lock()
                .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
            let audit = engine
                .service_token_audit_in_scope(&context.scope)
                .map_err(ServerError::internal)?;
            let audit_count = audit.len();

            Ok((
                Json(audit),
                json!({ "request_units": 1, "service_token_audit_records": audit_count }),
            ))
        })();

    server_json_result("GET", "/tokens/audit", &context, result)
}

async fn server_rbac_grant(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerRbacGrantRequest>,
) -> Result<Json<RbacGrant>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/rbac/grants")?;
    authorize_server_rbac_or_log(
        &state,
        &context,
        "POST",
        "/rbac/grants",
        RbacRequirement {
            action: AuthorizationAction::ManageRoles,
            role: RbacRole::Administrator,
        },
        true,
    )?;
    let result: Result<(Json<RbacGrant>, serde_json::Value), ServerError> = (|| {
        let scope = rbac_request_scope(body.scope.as_ref(), &context)?;
        let role = parse_rbac_role(&body.role)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let grant = engine
            .grant_rbac_role(
                scope,
                body.principal,
                role,
                context.principal.clone(),
                OffsetDateTime::now_utc(),
            )
            .map_err(ServerError::internal)?;

        Ok((
            Json(grant),
            json!({ "request_units": 1, "role_grants_written": 1 }),
        ))
    })();

    server_json_result("POST", "/rbac/grants", &context, result)
}

async fn server_rbac_revoke(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerRbacRevokeRequest>,
) -> Result<Json<serde_json::Value>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/rbac/revoke")?;
    authorize_server_rbac_or_log(
        &state,
        &context,
        "POST",
        "/rbac/revoke",
        RbacRequirement {
            action: AuthorizationAction::ManageRoles,
            role: RbacRole::Administrator,
        },
        true,
    )?;
    let result: Result<(Json<serde_json::Value>, serde_json::Value), ServerError> = (|| {
        let scope = rbac_request_scope(body.scope.as_ref(), &context)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let removed = engine
            .revoke_rbac_role(
                scope,
                body.principal,
                context.principal.clone(),
                OffsetDateTime::now_utc(),
            )
            .map_err(ServerError::internal)?;
        let applied = removed.is_some();

        Ok((
            Json(json!({ "applied": applied })),
            json!({ "request_units": 1, "role_grants_revoked": i32::from(applied) }),
        ))
    })();

    server_json_result("POST", "/rbac/revoke", &context, result)
}

async fn server_rbac_grants(
    State(state): State<ServerState>,
    headers: HeaderMap,
) -> Result<Json<Vec<RbacGrant>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/rbac/grants")?;
    authorize_server_rbac_or_log(
        &state,
        &context,
        "GET",
        "/rbac/grants",
        RbacRequirement {
            action: AuthorizationAction::ManageRoles,
            role: RbacRole::Administrator,
        },
        true,
    )?;
    let result: Result<(Json<Vec<RbacGrant>>, serde_json::Value), ServerError> = (|| {
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let grants = engine
            .rbac_grants_in_scope(&context.scope)
            .map_err(ServerError::internal)?;
        let grant_count = grants.len();

        Ok((
            Json(grants),
            json!({ "request_units": 1, "role_grants_returned": grant_count }),
        ))
    })();

    server_json_result("GET", "/rbac/grants", &context, result)
}

async fn server_rbac_audit(
    State(state): State<ServerState>,
    headers: HeaderMap,
) -> Result<Json<Vec<AuthorizationAuditRecord>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/rbac/audit")?;
    authorize_server_rbac_or_log(
        &state,
        &context,
        "GET",
        "/rbac/audit",
        RbacRequirement {
            action: AuthorizationAction::ManageRoles,
            role: RbacRole::Administrator,
        },
        true,
    )?;
    let result: Result<(Json<Vec<AuthorizationAuditRecord>>, serde_json::Value), ServerError> =
        (|| {
            let engine = state
                .engine
                .lock()
                .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
            let audit = engine
                .authorization_audit_in_scope(&context.scope)
                .map_err(ServerError::internal)?;
            let audit_count = audit.len();

            Ok((
                Json(audit),
                json!({ "request_units": 1, "authorization_records": audit_count }),
            ))
        })();

    server_json_result("GET", "/rbac/audit", &context, result)
}

fn authorize_server_rbac_or_log(
    state: &ServerState,
    context: &ServerRequestContext,
    method: &str,
    route: &str,
    requirement: RbacRequirement,
    force_enforcement: bool,
) -> Result<(), ServerError> {
    match authorize_server_rbac(state, context, requirement, force_enforcement) {
        Ok(()) => Ok(()),
        Err(error) => {
            log_server_request(
                method,
                route,
                Some(&context.namespace),
                &context.principal,
                error.status,
                json!({ "request_units": 1 }),
            );
            Err(error)
        }
    }
}

fn rbac_request_scope(
    request: Option<&ServerScopeRequest>,
    context: &ServerRequestContext,
) -> Result<MemoryScope, ServerError> {
    let scope = server_memory_scope(request, &context.namespace)?;
    if scope == context.scope {
        Ok(scope)
    } else {
        Err(ServerError::bad_request(
            "RBAC grant scope must match the request scope headers",
        ))
    }
}

fn operator_secret_from_headers(headers: &HeaderMap, name: &str) -> Result<String, ServerError> {
    headers
        .get(name)
        .and_then(|value| value.to_str().ok())
        .map(ToOwned::to_owned)
        .ok_or_else(|| ServerError::unauthorized("administrator secret is required"))
}

fn require_authenticated_administration_principal(principal: &str) -> Result<(), ServerError> {
    if principal == "anonymous" {
        Err(ServerError::unauthorized(
            "administrator operations require authentication",
        ))
    } else {
        Ok(())
    }
}

fn require_administrator(
    engine: &Shibahama<HnswVectorIndex>,
    principal: &str,
) -> Result<(), ServerError> {
    require_authenticated_administration_principal(principal)?;
    let state = engine
        .administration_state()
        .map_err(ServerError::internal)?;
    let authorized = state
        .and_then(|state| state.administrator)
        .is_some_and(|administrator| administrator.principal == principal);

    if authorized {
        Ok(())
    } else {
        Err(ServerError::forbidden("administrator access is required"))
    }
}

async fn server_recall(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerRecallRequest>,
) -> Result<Json<Vec<RecallCandidateDto>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/recall")?;
    let result = server_recall_execution(&state, &context, &body, false)
        .map(|(candidates, _, cost)| (Json(candidates), cost));

    match result {
        Ok((response, cost)) => {
            log_server_request(
                "POST",
                "/recall",
                Some(&context.namespace),
                context.principal,
                StatusCode::OK,
                cost,
            );
            Ok(response)
        }
        Err(error) => {
            log_server_request(
                "POST",
                "/recall",
                Some(&context.namespace),
                context.principal,
                error.status,
                json!({
                    "request_units": 1,
                    "query_dimensions": body.query_vector.len(),
                }),
            );
            Err(error)
        }
    }
}

async fn server_recall_degraded(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerRecallRequest>,
) -> Result<Json<DegradedRecallDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/recall/degraded")?;
    let result = server_recall_execution(&state, &context, &body, true).map(
        |(candidates, unavailable_stages, cost)| {
            (
                Json(DegradedRecallDto {
                    candidates,
                    unavailable_stages,
                }),
                cost,
            )
        },
    );

    match result {
        Ok((response, cost)) => {
            log_server_request(
                "POST",
                "/recall/degraded",
                Some(&context.namespace),
                context.principal,
                StatusCode::OK,
                cost,
            );
            Ok(response)
        }
        Err(error) => {
            log_server_request(
                "POST",
                "/recall/degraded",
                Some(&context.namespace),
                context.principal,
                error.status,
                json!({
                    "request_units": 1,
                    "query_dimensions": body.query_vector.len(),
                }),
            );
            Err(error)
        }
    }
}

fn server_recall_execution(
    state: &ServerState,
    context: &ServerRequestContext,
    body: &ServerRecallRequest,
    allow_degradation: bool,
) -> Result<(Vec<RecallCandidateDto>, Vec<String>, serde_json::Value), ServerError> {
    let requested_top_k = body.top_k.unwrap_or(5);
    let now = time_from_optional_unix(body.now_unix).map_err(ServerError::bad_request)?;
    let engine = state
        .engine
        .lock()
        .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
    let all_memories = engine.memory_items().map_err(ServerError::internal)?;
    let namespace_memory_count = all_memories
        .iter()
        .filter(|item| memory_in_scope(item, &context.scope))
        .count();
    let search_top_k = all_memories.len().max(requested_top_k);
    let mut request =
        RecallRequest::new(&body.query_vector, search_top_k, now).with_scope(&context.scope);

    if let Some(raw_query_context) = body.raw_query_context.as_deref() {
        request = request.with_raw_query_context(raw_query_context);
    }
    if body.include_cold.unwrap_or(false) {
        request = request.include_cold();
    }
    if body.include_instructions.unwrap_or(false) {
        request = request.include_instructions();
    }
    if let Some(max_context_tokens) = body.max_context_tokens {
        request = request.with_max_context_tokens(max_context_tokens);
    }

    let (mut candidates, unavailable_stages) = if allow_degradation {
        let result = engine
            .recall_with_degradation(&request)
            .map_err(ServerError::internal)?;
        (
            result.candidates,
            result
                .unavailable_stages
                .into_iter()
                .map(recall_unavailable_stage_str)
                .map(str::to_owned)
                .collect(),
        )
    } else {
        (
            engine.recall(&request).map_err(ServerError::internal)?,
            Vec::new(),
        )
    };
    candidates.truncate(requested_top_k);
    let returned = candidates.len();
    let candidates = candidates
        .into_iter()
        .map(RecallCandidateDto::from)
        .collect::<Vec<_>>();

    Ok((
        candidates,
        unavailable_stages,
        json!({
            "request_units": 1,
            "query_dimensions": body.query_vector.len(),
            "requested_top_k": requested_top_k,
            "searched_top_k": search_top_k,
            "max_context_tokens": body.max_context_tokens,
            "namespace_memory_count": namespace_memory_count,
            "returned": returned,
        }),
    ))
}

async fn server_timeline(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerTimelineRequest>,
) -> Result<Json<Vec<RecallCandidateDto>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/timeline")?;
    let result: Result<(Json<Vec<RecallCandidateDto>>, serde_json::Value), ServerError> = (|| {
        let requested_top_k = body.top_k.unwrap_or(5);
        let as_of = time_from_optional_unix(body.as_of_unix).map_err(ServerError::bad_request)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let all_memories = engine.memory_items().map_err(ServerError::internal)?;
        let namespace_memory_count = all_memories
            .iter()
            .filter(|item| memory_in_scope(item, &context.scope))
            .count();
        let search_top_k = all_memories.len().max(requested_top_k);
        let mut request =
            RecallRequest::new(&body.query_vector, search_top_k, as_of).with_scope(&context.scope);

        if let Some(raw_query_context) = body.raw_query_context.as_deref() {
            request = request.with_raw_query_context(raw_query_context);
        }
        if body.include_cold.unwrap_or(false) {
            request = request.include_cold();
        }
        if body.include_instructions.unwrap_or(false) {
            request = request.include_instructions();
        }
        if let Some(max_context_tokens) = body.max_context_tokens {
            request = request.with_max_context_tokens(max_context_tokens);
        }

        let mut candidates = engine.timeline(&request).map_err(ServerError::internal)?;
        candidates.truncate(requested_top_k);
        let returned = candidates.len();
        let candidates = candidates
            .into_iter()
            .map(RecallCandidateDto::from)
            .collect::<Vec<_>>();

        Ok((
            Json(candidates),
            json!({
                "request_units": 1,
                "query_dimensions": body.query_vector.len(),
                "requested_top_k": requested_top_k,
                "searched_top_k": search_top_k,
                "max_context_tokens": body.max_context_tokens,
                "namespace_memory_count": namespace_memory_count,
                "returned": returned,
            }),
        ))
    })();

    server_json_result("POST", "/timeline", &context, result)
}

async fn server_reinforce(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerReinforceRequest>,
) -> Result<Json<serde_json::Value>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/reinforce")?;
    let result: Result<(Json<serde_json::Value>, serde_json::Value), ServerError> = (|| {
        let id = parse_memory_id(&body.memory_id).map_err(ServerError::bad_request)?;
        let outcome = parse_access_outcome(body.outcome.as_deref().unwrap_or("cited"))
            .map_err(ServerError::bad_request)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;

        ensure_memory_in_scope(&engine, id, &context.scope)?;
        let applied = engine
            .reinforce(id, outcome)
            .map_err(ServerError::internal)?;

        Ok((
            Json(json!({ "applied": applied })),
            json!({ "request_units": 1, "memory_writes": i32::from(applied) }),
        ))
    })();

    server_json_result("POST", "/reinforce", &context, result)
}

async fn server_consolidate(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerConsolidateRequest>,
) -> Result<Json<ConsolidationPassDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/consolidate")?;
    let result: Result<(Json<ConsolidationPassDto>, serde_json::Value), ServerError> = (|| {
        let now = time_from_optional_unix(body.now_unix).map_err(ServerError::bad_request)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let all_memories = engine.memory_items().map_err(ServerError::internal)?;
        let store_wide = all_memories
            .iter()
            .any(|item| !memory_in_scope(item, &context.scope));

        if store_wide && body.allow_store_wide != Some(true) {
            return Err(ServerError::bad_request(
                "consolidation is store-wide; send allow_store_wide=true when other namespaces or non-server memories exist",
            ));
        }

        let report = engine.consolidate(now).map_err(ServerError::internal)?;
        let applied_count = report.applied.len();

        Ok((
            Json(ConsolidationPassDto::from(report)),
            json!({
                "request_units": 1,
                "memories_scanned": all_memories.len(),
                "consolidation_decisions": applied_count,
                "store_wide": store_wide,
            }),
        ))
    })();

    server_json_result("POST", "/consolidate", &context, result)
}

async fn server_challenge(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerHumanSignalRequest>,
) -> Result<Json<HumanMutationDto>, ServerError> {
    server_human_signal(
        state,
        headers,
        body,
        HumanSignalAction::Challenge,
        "/challenge",
    )
}

async fn server_affirm(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerHumanSignalRequest>,
) -> Result<Json<HumanMutationDto>, ServerError> {
    server_human_signal(state, headers, body, HumanSignalAction::Affirm, "/affirm")
}

async fn server_pin(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerHumanSignalRequest>,
) -> Result<Json<HumanMutationDto>, ServerError> {
    server_human_signal(state, headers, body, HumanSignalAction::Pin, "/pin")
}

async fn server_unpin(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerHumanSignalRequest>,
) -> Result<Json<HumanMutationDto>, ServerError> {
    server_human_signal(state, headers, body, HumanSignalAction::Unpin, "/unpin")
}

async fn server_correct(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerHumanSignalRequest>,
) -> Result<Json<HumanMutationDto>, ServerError> {
    server_human_signal(state, headers, body, HumanSignalAction::Correct, "/correct")
}

fn server_human_signal(
    state: ServerState,
    headers: HeaderMap,
    body: ServerHumanSignalRequest,
    action: HumanSignalAction,
    route: &'static str,
) -> Result<Json<HumanMutationDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", route)?;
    let result: Result<(Json<HumanMutationDto>, serde_json::Value), ServerError> = (|| {
        let id = parse_memory_id(&body.memory_id).map_err(ServerError::bad_request)?;
        let reason = body
            .reason
            .as_deref()
            .unwrap_or_else(|| human_signal_action_str(action));
        let actor = body.actor.as_deref().unwrap_or("server");
        let request = human_signal_request(actor, reason, body.timestamp_unix)
            .map_err(ServerError::bad_request)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;

        ensure_memory_in_scope(&engine, id, &context.scope)?;

        let response = match action {
            HumanSignalAction::Challenge => engine
                .challenge_with_request(id, request)
                .map_err(ServerError::internal)?
                .map_or(HumanMutationDto::NotFound { applied: false }, |outcome| {
                    HumanMutationDto::Signal(Box::new(HumanSignalOutcomeDto::from(outcome)))
                }),
            HumanSignalAction::Affirm => engine
                .affirm_with_request(id, request)
                .map_err(ServerError::internal)?
                .map_or(HumanMutationDto::NotFound { applied: false }, |outcome| {
                    HumanMutationDto::Signal(Box::new(HumanSignalOutcomeDto::from(outcome)))
                }),
            HumanSignalAction::Pin => engine
                .pin_with_request(id, request)
                .map_err(ServerError::internal)?
                .map_or(HumanMutationDto::NotFound { applied: false }, |outcome| {
                    HumanMutationDto::Signal(Box::new(HumanSignalOutcomeDto::from(outcome)))
                }),
            HumanSignalAction::Unpin => engine
                .unpin_with_request(id, request)
                .map_err(ServerError::internal)?
                .map_or(HumanMutationDto::NotFound { applied: false }, |outcome| {
                    HumanMutationDto::Signal(Box::new(HumanSignalOutcomeDto::from(outcome)))
                }),
            HumanSignalAction::Correct => {
                let proposed_content = body
                    .proposed_content
                    .ok_or_else(|| ServerError::bad_request("correct requires proposed_content"))?;
                engine
                    .correct_with_request(id, proposed_content, request)
                    .map_err(ServerError::internal)?
                    .map_or(HumanMutationDto::NotFound { applied: false }, |outcome| {
                        HumanMutationDto::Correction(Box::new(HumanCorrectionOutcomeDto::from(
                            outcome,
                        )))
                    })
            }
        };

        Ok((
            Json(response),
            json!({ "request_units": 1, "memory_writes": 1 }),
        ))
    })();

    server_json_result("POST", route, &context, result)
}

async fn server_events(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Query(query): Query<EventsQuery>,
) -> Result<Json<EventLogDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/events")?;
    let result: Result<(Json<EventLogDto>, serde_json::Value), ServerError> = (|| {
        let as_of = optional_time_from_unix(query.as_of_unix)?;
        let mut events = event_records_for_scope(&state, &context.scope, as_of)?
            .into_iter()
            .map(EventRecordDto::from)
            .collect::<Vec<_>>();

        if let Some(limit) = query.limit
            && events.len() > limit
        {
            events = events.split_off(events.len() - limit);
        }

        let event_count = events.len();

        Ok((
            Json(EventLogDto {
                event_count,
                events,
            }),
            json!({ "request_units": 1, "events_returned": event_count }),
        ))
    })();

    server_json_result("GET", "/events", &context, result)
}

async fn server_audit(
    State(state): State<ServerState>,
    headers: HeaderMap,
    AxumPath(memory_id): AxumPath<String>,
    Query(query): Query<WhyQuery>,
) -> Result<Json<AuditDetailDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/audit/{memory_id}")?;
    let result: Result<(Json<AuditDetailDto>, serde_json::Value), ServerError> = (|| {
        let id = parse_memory_id(&memory_id).map_err(ServerError::bad_request)?;
        let now = time_from_optional_unix(query.now_unix).map_err(ServerError::bad_request)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;

        ensure_memory_in_scope(&engine, id, &context.scope)?;
        let why = engine
            .why_at(id, now)
            .map_err(ServerError::internal)?
            .map(WhyTraceDto::from);
        let events = engine
            .store()
            .events_in_scope(&context.scope)
            .map_err(ServerError::internal)?
            .into_iter()
            .filter(|record| event_touches_memory(record, id))
            .map(EventRecordDto::from)
            .collect::<Vec<_>>();
        let event_count = events.len();

        Ok((
            Json(AuditDetailDto {
                memory_id: id.to_string(),
                why,
                events,
            }),
            json!({ "request_units": 1, "events_returned": event_count }),
        ))
    })();

    server_json_result("GET", "/audit/{memory_id}", &context, result)
}

async fn server_why(
    State(state): State<ServerState>,
    headers: HeaderMap,
    AxumPath(memory_id): AxumPath<String>,
    Query(query): Query<WhyQuery>,
) -> Result<Json<Option<WhyTraceDto>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/why/{memory_id}")?;
    let result: Result<(Json<Option<WhyTraceDto>>, serde_json::Value), ServerError> = (|| {
        let id = parse_memory_id(&memory_id).map_err(ServerError::bad_request)?;
        let now = time_from_optional_unix(query.now_unix).map_err(ServerError::bad_request)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let trace = engine
            .why_at(id, now)
            .map_err(ServerError::internal)?
            .filter(|trace| memory_in_scope(&trace.item, &context.scope))
            .map(WhyTraceDto::from);
        let found = trace.is_some();

        Ok((
            Json(trace),
            json!({
                "request_units": 1,
                "trace_lookup": 1,
                "found": found,
            }),
        ))
    })();

    match result {
        Ok((response, cost)) => {
            log_server_request(
                "GET",
                "/why/{memory_id}",
                Some(&context.namespace),
                context.principal,
                StatusCode::OK,
                cost,
            );
            Ok(response)
        }
        Err(error) => {
            log_server_request(
                "GET",
                "/why/{memory_id}",
                Some(&context.namespace),
                context.principal,
                error.status,
                json!({ "request_units": 1, "trace_lookup": 1 }),
            );
            Err(error)
        }
    }
}

async fn server_graph_snapshot(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Query(query): Query<GraphSnapshotQuery>,
) -> Result<Json<GraphSnapshotDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/graph")?;
    let result: Result<(Json<GraphSnapshotDto>, serde_json::Value), ServerError> = (|| {
        let as_of = now_or_unix(query.as_of_unix)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let snapshot = filter_graph_snapshot_for_scope(
            engine
                .graph_snapshot(as_of)
                .map_err(ServerError::internal)?,
            &context.scope,
        );
        let entity_count = snapshot.entities.len();
        let relation_count = snapshot.relations.len();

        Ok((
            Json(snapshot),
            json!({
                "request_units": 1,
                "entities_returned": entity_count,
                "relations_returned": relation_count,
            }),
        ))
    })();

    server_json_result("GET", "/graph", &context, result)
}

async fn server_put_graph_entity(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerGraphEntityRequest>,
) -> Result<Json<GraphEntityDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/graph/entities")?;
    let result: Result<(Json<GraphEntityDto>, serde_json::Value), ServerError> = (|| {
        let entity = graph_entity_from_request(body, &context.namespace, &context.scope)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        if let Some(memory_id) = entity.source_memory_id {
            ensure_memory_in_scope(&engine, memory_id, &context.scope)?;
        }
        if engine
            .graph_entity(entity.id)
            .map_err(ServerError::internal)?
            .as_ref()
            .is_some_and(|existing| !graph_entity_in_scope(existing, &context.scope))
        {
            return Err(ServerError::not_found(format!(
                "graph entity {} not found in namespace {}",
                entity.id, context.namespace
            )));
        }
        let entity = engine
            .put_graph_entity(&entity)
            .map_err(ServerError::internal)?;

        Ok((
            Json(GraphEntityDto::from(entity)),
            json!({ "request_units": 1, "graph_writes": 1 }),
        ))
    })();

    server_json_result("POST", "/graph/entities", &context, result)
}

async fn server_get_graph_entity(
    State(state): State<ServerState>,
    headers: HeaderMap,
    AxumPath(entity_id): AxumPath<String>,
) -> Result<Json<Option<GraphEntityDto>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/graph/entities/{entity_id}")?;
    let result: Result<(Json<Option<GraphEntityDto>>, serde_json::Value), ServerError> = (|| {
        let id = parse_entity_id(&entity_id)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let entity = engine
            .graph_entity(id)
            .map_err(ServerError::internal)?
            .filter(|entity| graph_entity_in_scope(entity, &context.scope))
            .map(GraphEntityDto::from);
        let found = entity.is_some();

        Ok((Json(entity), json!({ "request_units": 1, "found": found })))
    })();

    server_json_result("GET", "/graph/entities/{entity_id}", &context, result)
}

async fn server_delete_graph_entity(
    State(state): State<ServerState>,
    headers: HeaderMap,
    AxumPath(entity_id): AxumPath<String>,
    Query(query): Query<GraphDeleteQuery>,
) -> Result<Json<Option<GraphEntityDto>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "DELETE", "/graph/entities/{entity_id}")?;
    let result: Result<(Json<Option<GraphEntityDto>>, serde_json::Value), ServerError> = (|| {
        let id = parse_entity_id(&entity_id)?;
        let valid_to = now_or_unix(query.valid_to_unix)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let entity = engine
            .graph_entity(id)
            .map_err(ServerError::internal)?
            .filter(|entity| graph_entity_in_scope(entity, &context.scope))
            .map(|mut entity| {
                entity.timestamps = entity.timestamps.closed_at(valid_to);
                engine
                    .put_graph_entity(&entity)
                    .map(GraphEntityDto::from)
                    .map_err(ServerError::internal)
            })
            .transpose()?;
        let found = entity.is_some();

        Ok((
            Json(entity),
            json!({ "request_units": 1, "graph_writes": usize::from(found), "found": found }),
        ))
    })();

    server_json_result("DELETE", "/graph/entities/{entity_id}", &context, result)
}

async fn server_put_graph_relation(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerGraphRelationRequest>,
) -> Result<Json<GraphRelationDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/graph/relations")?;
    let result: Result<(Json<GraphRelationDto>, serde_json::Value), ServerError> = (|| {
        let relation = graph_relation_from_request(body, &context.namespace, &context.scope)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        if engine
            .graph_relation(relation.id)
            .map_err(ServerError::internal)?
            .as_ref()
            .is_some_and(|existing| !graph_relation_in_scope(existing, &context.scope))
        {
            return Err(ServerError::not_found(format!(
                "graph relation {} not found in namespace {}",
                relation.id, context.namespace
            )));
        }
        if let Some(memory_id) = relation.memory_id {
            let memory_in_scope = engine
                .memory_items()
                .map_err(ServerError::internal)?
                .iter()
                .any(|item| item.id == memory_id && memory_in_scope(item, &context.scope));
            if !memory_in_scope {
                return Err(ServerError::not_found(format!(
                    "memory {memory_id} not found in namespace {}",
                    context.namespace
                )));
            }
        }
        if let Some(supersedes) = relation.supersedes {
            let Some(existing) = engine
                .graph_relation(supersedes)
                .map_err(ServerError::internal)?
            else {
                return Err(ServerError::bad_request(format!(
                    "superseded graph relation {supersedes} not found"
                )));
            };
            if !graph_relation_in_scope(&existing, &context.scope) {
                return Err(ServerError::not_found(format!(
                    "graph relation {supersedes} not found in namespace {}",
                    context.namespace
                )));
            }
        }
        for entity_id in [relation.from_entity, relation.to_entity] {
            let Some(entity) = engine
                .graph_entity(entity_id)
                .map_err(ServerError::internal)?
            else {
                return Err(ServerError::bad_request(format!(
                    "graph entity {entity_id} not found"
                )));
            };
            if !graph_entity_in_scope(&entity, &context.scope) {
                return Err(ServerError::not_found(format!(
                    "graph entity {entity_id} not found in namespace {}",
                    context.namespace
                )));
            }
        }
        let relation = engine
            .put_graph_relation(&relation)
            .map_err(ServerError::internal)?;

        Ok((
            Json(GraphRelationDto::from(relation)),
            json!({ "request_units": 1, "graph_writes": 1 }),
        ))
    })();

    server_json_result("POST", "/graph/relations", &context, result)
}

async fn server_get_graph_relation(
    State(state): State<ServerState>,
    headers: HeaderMap,
    AxumPath(relation_id): AxumPath<String>,
) -> Result<Json<Option<GraphRelationDto>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/graph/relations/{relation_id}")?;
    let result: Result<(Json<Option<GraphRelationDto>>, serde_json::Value), ServerError> = (|| {
        let id = parse_relation_id(&relation_id)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let relation = engine
            .graph_relation(id)
            .map_err(ServerError::internal)?
            .filter(|relation| graph_relation_in_scope(relation, &context.scope))
            .map(GraphRelationDto::from);
        let found = relation.is_some();

        Ok((
            Json(relation),
            json!({ "request_units": 1, "found": found }),
        ))
    })();

    server_json_result("GET", "/graph/relations/{relation_id}", &context, result)
}

async fn server_delete_graph_relation(
    State(state): State<ServerState>,
    headers: HeaderMap,
    AxumPath(relation_id): AxumPath<String>,
    Query(query): Query<GraphDeleteQuery>,
) -> Result<Json<Option<GraphRelationDto>>, ServerError> {
    let context =
        server_context_or_log(&headers, &state, "DELETE", "/graph/relations/{relation_id}")?;
    let result: Result<(Json<Option<GraphRelationDto>>, serde_json::Value), ServerError> = (|| {
        let id = parse_relation_id(&relation_id)?;
        let valid_to = now_or_unix(query.valid_to_unix)?;
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let relation = engine
            .graph_relation(id)
            .map_err(ServerError::internal)?
            .filter(|relation| graph_relation_in_scope(relation, &context.scope))
            .map(|mut relation| {
                relation.timestamps = relation.timestamps.closed_at(valid_to);
                engine
                    .put_graph_relation(&relation)
                    .map(GraphRelationDto::from)
                    .map_err(ServerError::internal)
            })
            .transpose()?;
        let found = relation.is_some();

        Ok((
            Json(relation),
            json!({ "request_units": 1, "graph_writes": usize::from(found), "found": found }),
        ))
    })();

    server_json_result("DELETE", "/graph/relations/{relation_id}", &context, result)
}

async fn server_graph_traverse(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerGraphTraverseRequest>,
) -> Result<Json<GraphSnapshotDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/graph/traverse")?;
    let result: Result<(Json<GraphSnapshotDto>, serde_json::Value), ServerError> = (|| {
        let start_entity = parse_entity_id(&body.start_entity)?;
        let as_of = body.as_of_unix.map(required_time_from_unix).transpose()?;
        let traversal_as_of = as_of.unwrap_or_else(OffsetDateTime::now_utc);
        let mut request = GraphTraversalRequest::new(start_entity, body.max_hops.unwrap_or(1))
            .with_scope(context.scope.clone());

        if let Some(relation_types) = body.relation_types {
            request = request.with_relation_types(relation_types);
        }
        if let Some(as_of) = as_of {
            request = request.as_of(as_of);
        }

        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let Some(start) = engine
            .graph_entity(start_entity)
            .map_err(ServerError::internal)?
        else {
            return Err(ServerError::not_found(format!(
                "graph entity {start_entity} not found"
            )));
        };
        if !graph_entity_in_scope(&start, &context.scope) {
            return Err(ServerError::not_found(format!(
                "graph entity {start_entity} not found in namespace {}",
                context.namespace
            )));
        }
        let traversal = filter_graph_traversal_for_scope(
            engine
                .traverse_graph(&request)
                .map_err(ServerError::internal)?,
            &context.scope,
            traversal_as_of,
        );
        let entity_count = traversal.entities.len();
        let relation_count = traversal.relations.len();

        Ok((
            Json(traversal),
            json!({
                "request_units": 1,
                "entities_returned": entity_count,
                "relations_returned": relation_count,
            }),
        ))
    })();

    server_json_result("POST", "/graph/traverse", &context, result)
}

async fn server_tideline_snapshot(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Query(query): Query<TidelineQuery>,
) -> Result<Json<TidelineSnapshotDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/tideline/snapshot")?;
    let result: Result<(Json<TidelineSnapshotDto>, serde_json::Value), ServerError> = (|| {
        let as_of = optional_time_from_unix(query.as_of_unix)?;
        let snapshot =
            tideline_snapshot_for_scope(&state, &context.namespace, &context.scope, as_of)?;
        let cost = json!({
            "request_units": 1,
            "memories_returned": snapshot.memory_count,
            "events_returned": snapshot.event_count,
        });

        Ok((Json(snapshot), cost))
    })();

    match result {
        Ok((response, cost)) => {
            log_server_request(
                "GET",
                "/tideline/snapshot",
                Some(&context.namespace),
                context.principal,
                StatusCode::OK,
                cost,
            );
            Ok(response)
        }
        Err(error) => {
            log_server_request(
                "GET",
                "/tideline/snapshot",
                Some(&context.namespace),
                context.principal,
                error.status,
                json!({ "request_units": 1 }),
            );
            Err(error)
        }
    }
}

async fn server_tideline_recording(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Query(query): Query<TidelineQuery>,
) -> Result<Json<TidelineSnapshotDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/tideline/recording")?;
    let result: Result<(Json<TidelineSnapshotDto>, serde_json::Value), ServerError> = (|| {
        let as_of = optional_time_from_unix(query.as_of_unix)?;
        let snapshot =
            tideline_snapshot_for_scope(&state, &context.namespace, &context.scope, as_of)?;
        let cost = json!({
            "request_units": 1,
            "recording_schema_version": snapshot.schema_version,
            "memories_returned": snapshot.memory_count,
            "events_returned": snapshot.event_count,
        });

        Ok((Json(snapshot), cost))
    })();

    match result {
        Ok((response, cost)) => {
            log_server_request(
                "GET",
                "/tideline/recording",
                Some(&context.namespace),
                context.principal,
                StatusCode::OK,
                cost,
            );
            Ok(response)
        }
        Err(error) => {
            log_server_request(
                "GET",
                "/tideline/recording",
                Some(&context.namespace),
                context.principal,
                error.status,
                json!({ "request_units": 1 }),
            );
            Err(error)
        }
    }
}

async fn server_tideline_live(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Query(query): Query<TidelineQuery>,
) -> Result<Sse<impl Stream<Item = Result<SseEvent, Infallible>>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/tideline/live")?;
    let as_of = optional_time_from_unix(query.as_of_unix)?;

    log_server_request(
        "GET",
        "/tideline/live",
        Some(&context.namespace),
        context.principal,
        StatusCode::OK,
        json!({ "request_units": 1, "stream": "sse" }),
    );

    let state_for_stream = state.clone();
    let namespace = context.namespace;
    let scope = context.scope;
    let mut interval = tokio::time::interval(Duration::from_secs(1));
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let stream = IntervalStream::new(interval).map(move |_| {
        let event = match tideline_snapshot_for_scope(&state_for_stream, &namespace, &scope, as_of)
        {
            Ok(snapshot) => match serde_json::to_string(&snapshot) {
                Ok(data) => SseEvent::default().event("snapshot").data(data),
                Err(error) => SseEvent::default()
                    .event("error")
                    .data(json!({ "error": error.to_string() }).to_string()),
            },
            Err(error) => SseEvent::default().event("error").data(
                json!({
                    "error": error.detail,
                    "code": error.code,
                    "severity": error.severity,
                    "retryable": error.retryable,
                    "detail": error.detail,
                })
                .to_string(),
            ),
        };

        Ok(event)
    });

    Ok(Sse::new(stream).keep_alive(KeepAlive::default()))
}

fn open_engine(
    store: &StoreArgs,
    vector_hint: Option<&[f32]>,
) -> CliResult<Shibahama<HnswVectorIndex>> {
    let dimensions = store
        .dimensions
        .or_else(|| vector_hint.map(<[f32]>::len))
        .or(persisted_embedding_dimensions(&store.path)?)
        .unwrap_or(1);

    open_engine_with_dimensions(store, dimensions)
}

fn persisted_embedding_dimensions(path: &Path) -> CliResult<Option<usize>> {
    let store = RedbMemoryStore::open(path)?;

    Ok(store
        .stored_embeddings()?
        .first()
        .map(|embedding| embedding.vector.len()))
}

fn open_engine_with_dimensions(
    store: &StoreArgs,
    dimensions: usize,
) -> CliResult<Shibahama<HnswVectorIndex>> {
    let vector_index = HnswVectorIndex::with_capacity(dimensions, store.capacity);

    Ok(Shibahama::open(&store.path, vector_index)?)
}

enum ServiceStoreMode {
    Envelope(Box<EnvelopeEncryption<LocalKeyProvider>>),
    UnsafeDevelopmentPlaintext,
}

fn open_service_engine(command: &ServeCommand) -> CliResult<Shibahama<HnswVectorIndex>> {
    let config = service_engine_config(command);
    match service_store_mode(command)? {
        ServiceStoreMode::UnsafeDevelopmentPlaintext => {
            if command.full_semantic_erasure {
                return Err(Box::new(CliError(
                    "--full-semantic-erasure requires envelope encryption".to_owned(),
                )));
            }
            let dimensions = command
                .store
                .dimensions
                .or(persisted_embedding_dimensions(&command.store.path)?)
                .unwrap_or(1);
            let vector_index = HnswVectorIndex::with_capacity(dimensions, command.store.capacity);

            Ok(Shibahama::open_with_config(
                &command.store.path,
                vector_index,
                config,
            )?)
        }
        ServiceStoreMode::Envelope(encryption) => {
            let encryption = *encryption;
            let dimensions = command
                .store
                .dimensions
                .or(persisted_encrypted_embedding_dimensions(
                    &command.store.path,
                    encryption.clone(),
                )?)
                .unwrap_or(1);
            let vector_index = HnswVectorIndex::with_capacity(dimensions, command.store.capacity);

            Ok(Shibahama::open_with_config_and_encryption(
                &command.store.path,
                vector_index,
                config,
                encryption,
            )?)
        }
    }
}

fn service_engine_config(command: &ServeCommand) -> ShibahamaConfig {
    ShibahamaConfig {
        forgetting: ForgettingConfig {
            mode: service_forgetting_mode(command.full_semantic_erasure),
        },
        ..ShibahamaConfig::default()
    }
}

fn service_forgetting_mode(full_semantic_erasure: bool) -> ForgettingMode {
    if full_semantic_erasure {
        ForgettingMode::FullSemanticErase
    } else {
        ForgettingMode::SoftInvalidate
    }
}

fn persisted_encrypted_embedding_dimensions(
    path: &Path,
    encryption: EnvelopeEncryption<LocalKeyProvider>,
) -> CliResult<Option<usize>> {
    let store = RedbMemoryStore::open_with_encryption(path, encryption)?;

    Ok(store
        .stored_embeddings()?
        .first()
        .map(|embedding| embedding.vector.len()))
}

fn service_store_mode(command: &ServeCommand) -> CliResult<ServiceStoreMode> {
    service_store_mode_from_options(
        command
            .encryption_key
            .clone()
            .or_else(|| env::var("SHIBAHAMA_ENCRYPTION_KEY").ok())
            .filter(|value| !value.is_empty()),
        &command.encryption_key_id,
        command.unsafe_development_plaintext,
    )
}

fn service_store_mode_from_options(
    encryption_key: Option<String>,
    key_id: &str,
    unsafe_development_plaintext: bool,
) -> CliResult<ServiceStoreMode> {
    if unsafe_development_plaintext {
        if encryption_key.is_some() {
            return Err(Box::new(CliError(
                "--unsafe-development-plaintext cannot be combined with an encryption key"
                    .to_owned(),
            )));
        }

        return Ok(ServiceStoreMode::UnsafeDevelopmentPlaintext);
    }
    if key_id.is_empty() || key_id.len() > 128 {
        return Err(Box::new(CliError(
            "service encryption key id must contain 1-128 bytes".to_owned(),
        )));
    }
    let encryption_key = encryption_key.ok_or_else(|| {
        Box::new(CliError(
            "service encryption requires --encryption-key or SHIBAHAMA_ENCRYPTION_KEY; use --unsafe-development-plaintext only for local development"
                .to_owned(),
        )) as Box<dyn Error>
    })?;
    let key = parse_hex_encryption_key(&encryption_key)?;

    Ok(ServiceStoreMode::Envelope(Box::new(
        EnvelopeEncryption::new(LocalKeyProvider::new(key_id, key)),
    )))
}

fn parse_hex_encryption_key(value: &str) -> CliResult<[u8; 32]> {
    if value.len() != 64 {
        return Err(Box::new(CliError(
            "service encryption key must be exactly 64 hexadecimal characters".to_owned(),
        )));
    }
    let mut key = [0_u8; 32];

    for (index, byte) in key.iter_mut().enumerate() {
        let high = hex_nibble(value.as_bytes()[index * 2]).ok_or_else(|| {
            Box::new(CliError(
                "service encryption key must be exactly 64 hexadecimal characters".to_owned(),
            )) as Box<dyn Error>
        })?;
        let low = hex_nibble(value.as_bytes()[index * 2 + 1]).ok_or_else(|| {
            Box::new(CliError(
                "service encryption key must be exactly 64 hexadecimal characters".to_owned(),
            )) as Box<dyn Error>
        })?;

        *byte = high << 4 | low;
    }

    Ok(key)
}

fn valid_semantic_erasure_metadata(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':'))
}

const fn hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

fn write_event(
    content: String,
    source_kind: &str,
    source_ref: Option<String>,
    ingested_by: &str,
    valid_from_unix: Option<i64>,
    ingested_at_unix: Option<i64>,
) -> CliResult<MemoryWriteEvent> {
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

fn parse_vector(value: &str) -> CliResult<Vec<f32>> {
    let values = value
        .split(|character: char| character == ',' || character.is_whitespace())
        .filter(|part| !part.is_empty())
        .map(|part| {
            part.parse::<f32>()
                .map_err(|error| CliError(format!("invalid vector value `{part}`: {error}")))
        })
        .collect::<Result<Vec<_>, _>>()?;

    if values.is_empty() {
        return Err(Box::new(CliError(
            "vector must contain at least one numeric value".to_owned(),
        )));
    }

    Ok(values)
}

fn time_from_optional_unix(value: Option<i64>) -> CliResult<OffsetDateTime> {
    match value {
        Some(value) => Ok(OffsetDateTime::from_unix_timestamp(value)?),
        None => Ok(OffsetDateTime::now_utc()),
    }
}

fn parse_memory_id(value: &str) -> CliResult<MemoryId> {
    Ok(MemoryId::from(Uuid::parse_str(value)?))
}

fn parse_access_outcome(value: &str) -> CliResult<AccessOutcome> {
    match value {
        "surfaced" => Ok(AccessOutcome::Surfaced),
        "led_somewhere" | "led-somewhere" => Ok(AccessOutcome::LedSomewhere),
        "cited" => Ok(AccessOutcome::Cited),
        "ignored" => Ok(AccessOutcome::Ignored),
        "contradicted" => Ok(AccessOutcome::Contradicted),
        _ => Err(Box::new(CliError(
            "outcome must be one of: surfaced, led_somewhere, cited, ignored, contradicted"
                .to_owned(),
        ))),
    }
}

fn human_signal_request(
    actor: &str,
    reason: &str,
    timestamp_unix: Option<i64>,
) -> CliResult<HumanSignalRequest> {
    Ok(HumanSignalRequest::new(
        actor,
        reason,
        time_from_optional_unix(timestamp_unix)?,
    ))
}

fn parse_source_kind(value: &str) -> CliResult<SourceKind> {
    match value {
        "user" => Ok(SourceKind::User),
        "agent" => Ok(SourceKind::Agent),
        "file" => Ok(SourceKind::File),
        "web" => Ok(SourceKind::Web),
        "tool" => Ok(SourceKind::Tool),
        _ => Err(Box::new(CliError(
            "source-kind must be one of: user, agent, file, web, tool".to_owned(),
        ))),
    }
}

fn parse_policy_actor(value: &str) -> CliResult<PolicyActorClass> {
    match value {
        "human" => Ok(PolicyActorClass::Human),
        "agent" => Ok(PolicyActorClass::Agent),
        "automation" => Ok(PolicyActorClass::Automation),
        "service" => Ok(PolicyActorClass::Service),
        _ => Err(Box::new(CliError(
            "actor must be `human`, `agent`, `automation`, or `service`".to_owned(),
        ))),
    }
}

fn parse_capture_intent(value: &str) -> CliResult<CaptureIntent> {
    match value {
        "manual" => Ok(CaptureIntent::Manual),
        "suggested" => Ok(CaptureIntent::Suggested),
        "automatic" => Ok(CaptureIntent::Automatic),
        _ => Err(Box::new(CliError(
            "intent must be `manual`, `suggested`, or `automatic`".to_owned(),
        ))),
    }
}

fn parse_memory_kind(value: &str) -> CliResult<MemoryKind> {
    match value {
        "fact" => Ok(MemoryKind::Fact),
        "instruction" => Ok(MemoryKind::Instruction),
        _ => Err(Box::new(CliError(
            "kind must be one of: fact, instruction".to_owned(),
        ))),
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

fn write_json<T: Serialize>(value: &T) -> CliResult<()> {
    let stdout = io::stdout();
    let mut handle = stdout.lock();

    serde_json::to_writer_pretty(&mut handle, value)?;
    writeln!(handle)?;

    Ok(())
}

fn write_jsonl<T: Serialize>(values: &[T]) -> CliResult<()> {
    let stdout = io::stdout();
    let mut handle = stdout.lock();

    for value in values {
        serde_json::to_writer(&mut handle, value)?;
        writeln!(handle)?;
    }

    Ok(())
}

fn write_why_text(id: MemoryId, trace: Option<&WhyTrace>) -> CliResult<()> {
    let stdout = io::stdout();
    let mut handle = stdout.lock();

    let Some(trace) = trace else {
        writeln!(handle, "memory {id} was not found")?;
        return Ok(());
    };

    writeln!(handle, "Memory {id}")?;
    writeln!(handle, "Content: {}", trace.item.content)?;
    writeln!(handle)?;
    writeln!(handle, "State")?;
    writeln!(handle, "  currency: {}", currency_str(trace.currency.state))?;
    writeln!(handle, "  as of: {}", trace.currency.as_of)?;
    writeln!(handle, "  valid from: {}", trace.currency.valid_from)?;
    match trace.currency.valid_to {
        Some(valid_to) => writeln!(handle, "  valid to: {valid_to}")?,
        None => writeln!(handle, "  valid to: open")?,
    }
    writeln!(handle, "  ingested at: {}", trace.currency.ingested_at)?;
    writeln!(handle)?;
    writeln!(handle, "Tier")?;
    writeln!(handle, "  current: {}", tier_str(trace.tier.current))?;
    writeln!(handle, "  credence: {}", credence_str(trace.tier.credence))?;
    writeln!(
        handle,
        "  credence floor: {}",
        tier_str(trace.tier.credence_floor)
    )?;
    writeln!(handle)?;
    writeln!(handle, "Significance")?;
    writeln!(handle, "  base: {:.4}", trace.significance.base_score)?;
    writeln!(
        handle,
        "  decay multiplier: {:.4}",
        trace.significance.decay_multiplier
    )?;
    writeln!(
        handle,
        "  reinforcement: {:.4}",
        trace.significance.reinforcement
    )?;
    writeln!(
        handle,
        "  outcome bonus: {:.4}",
        trace.significance.outcome_bonus
    )?;
    writeln!(
        handle,
        "  contradiction penalty: {:.4}",
        trace.significance.contradiction_penalty
    )?;
    writeln!(handle, "  final: {:.4}", trace.significance.final_score)?;
    writeln!(handle)?;
    writeln!(handle, "Provenance")?;
    writeln!(
        handle,
        "  source kind: {}",
        source_kind_str(trace.provenance.source_kind)
    )?;
    writeln!(
        handle,
        "  source ref: {}",
        trace.provenance.source_ref.as_deref().unwrap_or("none")
    )?;
    writeln!(handle, "  ingested by: {}", trace.provenance.ingested_by)?;
    writeln!(handle)?;
    writeln!(handle, "Audit trail")?;
    if trace.audit_trail.is_empty() {
        writeln!(handle, "  none")?;
    } else {
        for entry in &trace.audit_trail {
            writeln!(
                handle,
                "  - sequence={} recorded_at={} cause={:?} change={:?}",
                entry.sequence, entry.recorded_at, entry.cause, entry.change
            )?;
        }
    }

    Ok(())
}

impl From<Provenance> for ProvenanceDto {
    fn from(value: Provenance) -> Self {
        Self {
            source_kind: source_kind_str(value.source_kind).to_owned(),
            source_ref: value.source_ref,
            ingested_by: value.ingested_by,
        }
    }
}

impl From<MemoryScope> for MemoryScopeDto {
    fn from(value: MemoryScope) -> Self {
        Self {
            repository: value.repository.to_string(),
            team: value.team.map(|team| team.to_string()),
            visibility: scope_visibility_str(value.visibility).to_owned(),
        }
    }
}

impl From<MemoryItem> for MemoryItemDto {
    fn from(value: MemoryItem) -> Self {
        Self {
            id: value.id.to_string(),
            content: value.content,
            kind: memory_kind_str(value.kind).to_owned(),
            provenance: ProvenanceDto::from(value.provenance),
            scope: MemoryScopeDto::from(value.scope),
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

impl From<RecallCandidate> for RecallCandidateDto {
    fn from(value: RecallCandidate) -> Self {
        Self {
            id: value.id.to_string(),
            item: MemoryItemDto::from(value.item),
            kind: memory_kind_str(value.kind).to_owned(),
            provenance: ProvenanceDto::from(value.provenance),
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

impl From<EventRecord> for EventRecordDto {
    fn from(value: EventRecord) -> Self {
        let kind = event_kind(&value.event).to_owned();
        let memory_ids = event_memory_ids(&value.event);
        let event = serde_json::to_value(value.event).unwrap_or_else(|error| {
            json!({
                "serialization_error": error.to_string(),
            })
        });

        Self {
            sequence: value.sequence,
            recorded_at_unix: value.recorded_at.unix_timestamp(),
            kind,
            memory_ids,
            event,
        }
    }
}

impl From<WhyTrace> for WhyTraceDto {
    fn from(value: WhyTrace) -> Self {
        Self {
            item: MemoryItemDto::from(value.item),
            significance: value.significance,
            provenance: ProvenanceDto::from(value.provenance),
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
                .map(|entry| {
                    format!(
                        "sequence={} recorded_at={} memory_id={} cause={:?} change={:?}",
                        entry.sequence,
                        entry.recorded_at,
                        entry.memory_id,
                        entry.cause,
                        entry.change
                    )
                })
                .collect(),
        }
    }
}

impl From<Entity> for GraphEntityDto {
    fn from(value: Entity) -> Self {
        Self {
            id: value.id.to_string(),
            scope: MemoryScopeDto::from(value.scope),
            source_memory_id: value.source_memory_id.map(|id| id.to_string()),
            entity_type: value.entity_type,
            label: value.label,
            stable_key: value.stable_key,
            attributes: value.attributes,
            valid_from_unix: value.timestamps.valid_from.unix_timestamp(),
            valid_to_unix: value
                .timestamps
                .valid_to
                .map(OffsetDateTime::unix_timestamp),
            ingested_at_unix: value.timestamps.ingested_at.unix_timestamp(),
        }
    }
}

impl From<Relation> for GraphRelationDto {
    fn from(value: Relation) -> Self {
        Self {
            id: value.id.to_string(),
            scope: MemoryScopeDto::from(value.scope),
            relation_type: value.relation_type,
            from_entity: value.from_entity.to_string(),
            to_entity: value.to_entity.to_string(),
            memory_id: value.memory_id.map(|id| id.to_string()),
            supersedes: value.supersedes.map(|id| id.to_string()),
            attributes: value.attributes,
            valid_from_unix: value.timestamps.valid_from.unix_timestamp(),
            valid_to_unix: value
                .timestamps
                .valid_to
                .map(OffsetDateTime::unix_timestamp),
            ingested_at_unix: value.timestamps.ingested_at.unix_timestamp(),
        }
    }
}

impl From<HumanSignal> for HumanSignalDto {
    fn from(value: HumanSignal) -> Self {
        Self {
            action: human_signal_action_str(value.action).to_owned(),
            memory_id: value.memory_id.to_string(),
            actor: value.actor,
            timestamp_unix: value.timestamp.unix_timestamp(),
            reason: value.reason,
            proposed_content: value.proposed_content,
            proposal_id: value.proposal_id.map(|id| id.to_string()),
            previous_credence: value
                .previous_credence
                .map(|credence| credence_str(credence).to_owned()),
            new_credence: value
                .new_credence
                .map(|credence| credence_str(credence).to_owned()),
            previous_credence_floor: value
                .previous_credence_floor
                .map(|tier| tier_str(tier).to_owned()),
            new_credence_floor: value
                .new_credence_floor
                .map(|tier| tier_str(tier).to_owned()),
        }
    }
}

impl From<HumanSignalOutcome> for HumanSignalOutcomeDto {
    fn from(value: HumanSignalOutcome) -> Self {
        let events = [
            value.records.access,
            value.records.revalidation_flag,
            Some(value.records.signal),
        ]
        .into_iter()
        .flatten()
        .map(EventRecordDto::from)
        .collect();

        Self {
            applied: true,
            signal: HumanSignalDto::from(value.signal),
            events,
        }
    }
}

impl From<HumanCorrectionOutcome> for HumanCorrectionOutcomeDto {
    fn from(value: HumanCorrectionOutcome) -> Self {
        let events = vec![
            value.records.invalidation,
            value.records.replacement_write,
            value.records.reconstruction,
            value.signal_record,
        ]
        .into_iter()
        .map(EventRecordDto::from)
        .collect();

        Self {
            applied: true,
            signal: HumanSignalDto::from(value.signal),
            proposal: MemoryItemDto::from(value.proposal.item),
            replacement: MemoryItemDto::from(value.replacement),
            events,
        }
    }
}

impl From<ConsolidationPassReport> for ConsolidationPassDto {
    fn from(value: ConsolidationPassReport) -> Self {
        let applied_count = value.applied.len();
        let outcomes = value
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
                .map(EventRecordDto::from)
                .collect();

                ConsolidationOutcomeDto {
                    action: consolidation_action_str(outcome.decision.action).to_owned(),
                    input_ids: outcome
                        .decision
                        .input_ids
                        .into_iter()
                        .map(|id| id.to_string())
                        .collect(),
                    output_id: outcome.decision.output.map(|item| item.id.to_string()),
                    tier_from: outcome
                        .decision
                        .tier_from
                        .map(|tier| tier_str(tier).to_owned()),
                    tier_to: outcome
                        .decision
                        .tier_to
                        .map(|tier| tier_str(tier).to_owned()),
                    why: outcome.decision.why.summary,
                    events,
                }
            })
            .collect();

        Self {
            pass_id: value.pass_id,
            applied_count,
            outcomes,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{
        RbacRequirement, ServerAdministration, ServerAuthentication, ServerError,
        ServerRateLimitPolicy, ServerRateLimiter, ServerRbacPolicy, ServerRequestContext,
        ServerState, ServiceStoreMode, authorize_server_rbac, parse_cors_headers,
        parse_cors_methods, parse_cors_origins, parse_hex_encryption_key, parse_vector,
        server_operational_log_record, service_forgetting_mode, service_store_mode_from_options,
    };
    use axum::http::StatusCode;
    use serde_json::json;
    use shibahama_core::api::Shibahama;
    use shibahama_core::model::MemoryScope;
    use shibahama_core::policy::PolicyActorClass;
    use shibahama_core::storage::{AuthorizationAction, AuthorizationPrincipalClass, RbacRole};
    use shibahama_core::vector::HnswVectorIndex;
    use std::collections::BTreeMap;
    use std::sync::{Arc, Mutex};
    use tempfile::NamedTempFile;
    use time::OffsetDateTime;

    #[test]
    fn parse_vector_accepts_commas_and_spaces() {
        assert_eq!(parse_vector("1, 2 3").ok(), Some(vec![1.0, 2.0, 3.0]));
    }

    #[test]
    fn parse_vector_rejects_empty_values() {
        assert!(parse_vector(" , ").is_err());
    }

    #[test]
    fn server_errors_preserve_core_error_metadata() {
        let error = ServerError::internal("[SHIBA_VECTOR] dimension mismatch: expected 2, got 1");

        assert_eq!(error.status, StatusCode::BAD_REQUEST);
        assert_eq!(error.code, "SHIBA_VECTOR");
        assert_eq!(error.severity, "fatal");
        assert!(!error.retryable);
        assert_eq!(error.detail, "vector index operation failed");
    }

    #[test]
    fn operational_logs_are_versioned_complete_and_redacted() {
        let namespace = "private-namespace";
        let claim = "oidc:alice@example.test";
        let record = server_operational_log_record(
            "POST",
            "/write",
            Some(namespace),
            claim,
            StatusCode::BAD_REQUEST,
            &json!({
                "request_units": 1,
                "content": "private-content",
                "vector": [0.1, 0.2],
                "source_ref": "private-ref",
                "credential": "private-credential",
                "claim": claim,
                "error_code": "SHIBA_INVALID_REQUEST",
            }),
            7,
        );
        let encoded = serde_json::to_string(&record).expect("log record should serialize");

        assert_eq!(record["schema_version"], 1);
        assert_eq!(record["component"], "embedded_server");
        assert_eq!(record["operation"], "POST /write");
        assert_eq!(record["duration_ms"], 7);
        assert_eq!(record["status"], 400);
        assert_eq!(record["error_code"], "SHIBA_INVALID_REQUEST");
        assert_eq!(record["metrics"]["request_units"], 1);
        for forbidden in [
            namespace,
            claim,
            "private-content",
            "private-ref",
            "private-credential",
            "content",
            "vector",
            "source_ref",
            "credential",
            "claim",
        ] {
            assert!(!encoded.contains(forbidden), "log contained {forbidden}");
        }
    }

    #[test]
    fn service_store_requires_an_encryption_key_unless_unsafe_development_is_explicit() {
        assert!(service_store_mode_from_options(None, "service-local", false).is_err());
        assert!(matches!(
            service_store_mode_from_options(None, "service-local", true),
            Ok(ServiceStoreMode::UnsafeDevelopmentPlaintext)
        ));
        assert!(
            service_store_mode_from_options(Some("00".repeat(32)), "service-local", true,).is_err()
        );
    }

    #[test]
    fn service_store_accepts_only_exact_hexadecimal_keys() {
        assert_eq!(
            parse_hex_encryption_key(&"ab".repeat(32)).expect("hex key should parse"),
            [0xab; 32]
        );
        assert!(parse_hex_encryption_key("abc").is_err());
        assert!(parse_hex_encryption_key(&"zz".repeat(32)).is_err());
        assert!(matches!(
            service_store_mode_from_options(Some("01".repeat(32)), "service-local", false),
            Ok(ServiceStoreMode::Envelope(_))
        ));
    }

    #[test]
    fn full_semantic_erasure_selects_only_the_explicit_forgetting_mode() {
        assert_eq!(
            service_forgetting_mode(false),
            shibahama_core::api::ForgettingMode::SoftInvalidate
        );
        assert_eq!(
            service_forgetting_mode(true),
            shibahama_core::api::ForgettingMode::FullSemanticErase
        );
    }

    #[test]
    fn cors_parsers_allow_only_explicit_exact_origins_methods_and_headers() {
        let origins = parse_cors_origins(vec![
            "http://localhost:5173/".to_owned(),
            "https://console.example.test".to_owned(),
        ])
        .expect("exact origins should parse");
        assert_eq!(origins[0].to_str().ok(), Some("http://localhost:5173"));
        assert_eq!(
            origins[1].to_str().ok(),
            Some("https://console.example.test")
        );
        assert!(parse_cors_origins(vec!["https://console.example.test/path".to_owned()]).is_err());
        assert!(parse_cors_origins(vec!["*".to_owned()]).is_err());
        assert_eq!(
            parse_cors_methods(vec!["GET".to_owned(), "POST".to_owned()])
                .expect("methods should parse")
                .len(),
            2
        );
        assert!(parse_cors_methods(vec!["bad method".to_owned()]).is_err());
        assert_eq!(
            parse_cors_headers(vec!["authorization".to_owned(), "x-api-key".to_owned()])
                .expect("headers should parse")
                .len(),
            2
        );
        assert!(parse_cors_headers(vec!["bad header".to_owned()]).is_err());
    }

    #[test]
    fn rate_limits_are_burst_bounded_scope_fair_and_retry_stable() {
        let scope = MemoryScope::default();
        let mut limiter = ServerRateLimiter::new(ServerRateLimitPolicy {
            requests_per_window: 2,
            window: std::time::Duration::from_secs(60),
            burst: 2,
        });
        let now = std::time::Instant::now();
        let context = ServerRequestContext {
            namespace: "default".to_owned(),
            scope: scope.clone(),
            principal: "oidc:alice".to_owned(),
            principal_class: AuthorizationPrincipalClass::Oidc,
            actor_class: PolicyActorClass::Human,
            credential_role: None,
        };
        assert!(limiter.admit(&context, now).is_ok());
        assert!(limiter.admit(&context, now).is_ok());
        assert_eq!(limiter.admit(&context, now), Err(30));

        let different_scope = ServerRequestContext {
            namespace: "default".to_owned(),
            scope: MemoryScope::team(
                scope.repository.clone(),
                shibahama_core::model::ScopeId::new("rate-team").expect("scope should validate"),
            ),
            principal: "oidc:alice".to_owned(),
            principal_class: AuthorizationPrincipalClass::Oidc,
            actor_class: PolicyActorClass::Human,
            credential_role: None,
        };
        let different_principal = ServerRequestContext {
            namespace: "default".to_owned(),
            scope,
            principal: "oidc:bob".to_owned(),
            principal_class: AuthorizationPrincipalClass::Oidc,
            actor_class: PolicyActorClass::Human,
            credential_role: None,
        };
        assert!(limiter.admit(&different_scope, now).is_ok());
        assert!(limiter.admit(&different_principal, now).is_ok());
        let error = ServerError::rate_limited(30);
        assert_eq!(error.status, StatusCode::TOO_MANY_REQUESTS);
        assert_eq!(error.code, "SHIBA_RATE_LIMITED");
        assert_eq!(error.retry_after_seconds, Some(30));
    }

    #[test]
    #[allow(clippy::too_many_lines)]
    fn active_server_rbac_requires_scoped_roles_and_audits_decisions() {
        let file = NamedTempFile::new().expect("tempfile should be created");
        let scope = MemoryScope::default();
        let now = OffsetDateTime::UNIX_EPOCH;
        let engine = Shibahama::open(file.path(), HnswVectorIndex::with_capacity(1, 8))
            .expect("engine should open");
        let commitment = "a".repeat(64);

        engine
            .ensure_administration_bootstrap_window(
                &commitment,
                now,
                now + time::Duration::hours(1),
            )
            .expect("bootstrap window should open");
        engine
            .bootstrap_administrator(&commitment, "oidc:global-admin", now)
            .expect("administrator should bootstrap");
        engine
            .grant_rbac_role(
                scope.clone(),
                "oidc:reader",
                RbacRole::Reader,
                "oidc:global-admin",
                now,
            )
            .expect("reader grant should persist");
        let state = ServerState {
            engine: Arc::new(Mutex::new(engine)),
            mcp_sessions: Arc::new(Mutex::new(BTreeMap::new())),
            path: file.path().display().to_string(),
            default_namespace: "default".to_owned(),
            authentication: ServerAuthentication {
                api_key: None,
                oidc: None,
            },
            administration: ServerAdministration {
                bootstrap: None,
                recovery_secret_commitment: None,
            },
            rbac: ServerRbacPolicy {
                enforce: false,
                erasure_min_role: RbacRole::Maintainer,
                promotion_min_role: RbacRole::Maintainer,
            },
            rate_limiter: Arc::new(Mutex::new(ServerRateLimiter::new(ServerRateLimitPolicy {
                requests_per_window: 120,
                window: std::time::Duration::from_secs(60),
                burst: 30,
            }))),
            mcp_scope: scope.clone(),
            max_memories_per_namespace: 1,
            operational_log_key: [0; 32],
        };
        let context = ServerRequestContext {
            namespace: "default".to_owned(),
            scope: scope.clone(),
            principal: "oidc:reader".to_owned(),
            principal_class: AuthorizationPrincipalClass::Oidc,
            actor_class: PolicyActorClass::Human,
            credential_role: None,
        };

        assert!(
            authorize_server_rbac(
                &state,
                &context,
                RbacRequirement {
                    action: AuthorizationAction::Read,
                    role: RbacRole::Reader,
                },
                false,
            )
            .is_ok()
        );
        assert!(
            authorize_server_rbac(
                &state,
                &context,
                RbacRequirement {
                    action: AuthorizationAction::Write,
                    role: RbacRole::Writer,
                },
                false,
            )
            .is_err()
        );
        let audit = state
            .engine
            .lock()
            .expect("engine lock should work")
            .authorization_audit_in_scope(&scope)
            .expect("audit should read");

        assert!(audit.iter().any(|record| {
            record.audit_action == shibahama_core::storage::AuthorizationAuditAction::Decision
                && record.allowed
                && record.required_role == RbacRole::Reader
                && record.principal_class == Some(AuthorizationPrincipalClass::Oidc)
                && record.actor_class == Some(PolicyActorClass::Human)
        }));
        assert!(audit.iter().any(|record| {
            record.audit_action == shibahama_core::storage::AuthorizationAuditAction::Decision
                && !record.allowed
                && record.required_role == RbacRole::Writer
        }));
    }
}
