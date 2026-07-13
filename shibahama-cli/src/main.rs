// SPDX-License-Identifier: MIT

//! Command-line entry point for Shibahama.

#![allow(clippy::needless_pass_by_value)]

use axum::extract::{Path as AxumPath, Query, State};
use axum::http::header::AUTHORIZATION;
use axum::http::{HeaderMap, StatusCode};
use axum::response::sse::{Event as SseEvent, KeepAlive, Sse};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use clap::{Args, Parser, Subcommand, ValueEnum};
use serde::{Deserialize, Serialize};
use serde_json::json;
use shibahama_core::api::{
    ConsolidationPassReport, HumanCorrectionOutcome, HumanSignalOutcome, HumanSignalRequest,
    Shibahama, ShibahamaErrorMetadata, WhyTrace, WriteEmbedding,
};
use shibahama_core::model::{
    AccessOutcome, ConsolidationAction, ConsolidationWhy, CredenceTier, Entity, EntityId,
    HumanSignal, HumanSignalAction, MemoryId, MemoryItem, MemoryKind, MemoryScope, Provenance,
    Relation, RelationId, ScopeId, ScopeVisibility, SourceKind, TemporalBounds, Tier,
};
use shibahama_core::retrieval::{
    RecallCandidate, RecallCandidateCurrency, RecallCandidateSource, RecallRequest,
    RecallUnavailableStage,
};
use shibahama_core::significance::SignificanceBreakdown;
use shibahama_core::storage::{
    EventRecord, GraphTraversalRequest, GraphTraversalResult, MemoryEvent, MemoryWriteEvent,
    RedbMemoryStore,
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
use std::sync::{Arc, Mutex};
use std::time::Duration;
use time::OffsetDateTime;
use tokio_stream::Stream;
use tokio_stream::StreamExt;
use tokio_stream::wrappers::IntervalStream;
use tower_http::cors::{Any, CorsLayer};
use uuid::Uuid;

type CliResult<T> = Result<T, Box<dyn Error>>;

#[derive(Parser)]
#[command(author, version, about = "Shibahama memory engine CLI")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
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
    /// Maximum materialized memories allowed per namespace.
    #[arg(long, default_value_t = 10_000)]
    max_memories_per_namespace: usize,
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
    path: String,
    default_namespace: String,
    api_key: Option<String>,
    max_memories_per_namespace: usize,
}

struct ServerRequestContext {
    namespace: String,
    scope: MemoryScope,
    principal: &'static str,
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
struct ServerInvalidateRequest {
    memory_id: String,
    valid_to_unix: i64,
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
                detail: "internal server error",
            };
        };
        let Some(metadata) = ShibahamaErrorMetadata::for_code(code) else {
            return Self {
                status: StatusCode::INTERNAL_SERVER_ERROR,
                code: "SHIBA_INTERNAL".to_owned(),
                severity: "fatal",
                retryable: false,
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
            detail: metadata.detail,
        }
    }

    fn bad_request(_error: impl Display) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            code: "SHIBA_INVALID_REQUEST".to_owned(),
            severity: "fatal",
            retryable: false,
            detail: "invalid request",
        }
    }

    fn unauthorized(_error: impl Display) -> Self {
        Self {
            status: StatusCode::UNAUTHORIZED,
            code: "SHIBA_UNAUTHORIZED".to_owned(),
            severity: "fatal",
            retryable: false,
            detail: "authorization denied",
        }
    }

    fn not_found(_error: impl Display) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            code: "SHIBA_NOT_FOUND".to_owned(),
            severity: "fatal",
            retryable: false,
            detail: "resource not found",
        }
    }

    fn too_many_requests(_error: impl Display) -> Self {
        Self {
            status: StatusCode::TOO_MANY_REQUESTS,
            code: "SHIBA_RATE_LIMITED".to_owned(),
            severity: "recoverable",
            retryable: true,
            detail: "request rate limited",
        }
    }
}

impl IntoResponse for ServerError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(json!({
                "error": self.detail,
                "code": self.code,
                "severity": self.severity,
                "retryable": self.retryable,
                "detail": self.detail,
            })),
        )
            .into_response()
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

async fn serve_async(command: ServeCommand) -> CliResult<()> {
    validate_namespace(&command.namespace)?;
    let engine = open_engine(&command.store, None)?;
    let api_key = command
        .api_key
        .or_else(|| env::var("SHIBAHAMA_API_KEY").ok())
        .filter(|value| !value.is_empty());
    let state = ServerState {
        engine: Arc::new(Mutex::new(engine)),
        path: command.store.path.display().to_string(),
        default_namespace: command.namespace,
        api_key,
        max_memories_per_namespace: command.max_memories_per_namespace,
    };
    let app = Router::new()
        .route("/healthz", get(server_health))
        .route("/capabilities", get(server_capabilities))
        .route("/readyz", get(server_ready))
        .route("/inspect", get(server_inspect))
        .route("/write", post(server_write))
        .route("/invalidate", post(server_invalidate))
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
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers(Any),
        )
        .with_state(state);
    let listener = tokio::net::TcpListener::bind(command.bind).await?;
    let local_addr = listener.local_addr()?;

    eprintln!("shibahama serve listening on http://{local_addr}");
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    Ok(())
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
    let principal = authorize_server_request(headers, state)?;
    let namespace = request_namespace(headers, state)?;
    let scope = request_scope(headers, &namespace)?;

    Ok(ServerRequestContext {
        namespace,
        scope,
        principal,
    })
}

fn server_context_or_log(
    headers: &HeaderMap,
    state: &ServerState,
    method: &str,
    route: &str,
) -> Result<ServerRequestContext, ServerError> {
    match server_context(headers, state) {
        Ok(context) => Ok(context),
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

fn authorize_server_request(
    headers: &HeaderMap,
    state: &ServerState,
) -> Result<&'static str, ServerError> {
    let Some(api_key) = state.api_key.as_deref() else {
        return Ok("anonymous");
    };

    let bearer_key = headers
        .get(AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "));
    let header_key = headers
        .get("x-api-key")
        .and_then(|value| value.to_str().ok());

    if bearer_key == Some(api_key) || header_key == Some(api_key) {
        Ok("api_key")
    } else {
        Err(ServerError::unauthorized("missing or invalid API key"))
    }
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
                context.principal,
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
                context.principal,
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
        MemoryEvent::MemoryInvalidated { id, valid_to } => {
            let mut event =
                base_tideline_event(sequence, recorded_at, "memory_invalidated", vec![id]);
            event.valid_to_unix = Some(valid_to.unix_timestamp());
            event
        }
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

fn log_server_request(
    method: &str,
    route: &str,
    namespace: Option<&str>,
    principal: &str,
    status: StatusCode,
    cost: serde_json::Value,
) {
    let record = json!({
        "event": "shibahama_http_request",
        "at_unix": OffsetDateTime::now_utc().unix_timestamp(),
        "method": method,
        "route": route,
        "namespace": namespace.unwrap_or("unknown"),
        "principal": principal,
        "status": status.as_u16(),
        "cost": cost,
    });

    eprintln!("{record}");
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
    use super::{ServerError, parse_vector};
    use axum::http::StatusCode;

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
}
