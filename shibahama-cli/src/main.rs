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
use shibahama_core::api::{Shibahama, WhyTrace, WriteEmbedding};
use shibahama_core::model::{
    ConsolidationAction, ConsolidationWhy, CredenceTier, HumanSignalAction, MemoryId, MemoryItem,
    MemoryKind, Provenance, SourceKind, Tier,
};
use shibahama_core::retrieval::{
    RecallCandidate, RecallCandidateCurrency, RecallCandidateSource, RecallRequest,
};
use shibahama_core::significance::SignificanceBreakdown;
use shibahama_core::storage::{EventRecord, MemoryEvent, MemoryWriteEvent, RedbMemoryStore};
use shibahama_core::vector::HnswVectorIndex;
use std::collections::BTreeSet;
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
    /// Explain why a memory has its current state.
    Why(WhyCommand),
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
struct MemoryItemDto {
    id: String,
    content: String,
    kind: String,
    provenance: ProvenanceDto,
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
    principal: &'static str,
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
struct WhyQuery {
    now_unix: Option<i64>,
}

#[derive(Deserialize)]
struct TidelineQuery {
    as_of_unix: Option<i64>,
}

#[derive(Debug)]
struct ServerError {
    status: StatusCode,
    message: String,
}

impl ServerError {
    fn internal(error: impl Display) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            message: error.to_string(),
        }
    }

    fn bad_request(error: impl Display) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: error.to_string(),
        }
    }

    fn unauthorized(error: impl Display) -> Self {
        Self {
            status: StatusCode::UNAUTHORIZED,
            message: error.to_string(),
        }
    }

    fn too_many_requests(error: impl Display) -> Self {
        Self {
            status: StatusCode::TOO_MANY_REQUESTS,
            message: error.to_string(),
        }
    }
}

impl IntoResponse for ServerError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(json!({
                "error": self.message,
            })),
        )
            .into_response()
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
        Command::Why(command) => why(command),
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
        .route("/readyz", get(server_ready))
        .route("/inspect", get(server_inspect))
        .route("/write", post(server_write))
        .route("/recall", post(server_recall))
        .route("/why/{memory_id}", get(server_why))
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

    Ok(ServerRequestContext {
        namespace,
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

fn memory_in_namespace(item: &MemoryItem, namespace: &str) -> bool {
    let prefix = namespace_source_prefix(namespace);

    item.provenance
        .source_ref
        .as_deref()
        .is_some_and(|source_ref| source_ref.starts_with(&prefix))
}

fn optional_time_from_unix(value: Option<i64>) -> Result<Option<OffsetDateTime>, ServerError> {
    value
        .map(OffsetDateTime::from_unix_timestamp)
        .transpose()
        .map_err(ServerError::bad_request)
}

fn tideline_snapshot_for_namespace(
    state: &ServerState,
    namespace: &str,
    as_of: Option<OffsetDateTime>,
) -> Result<TidelineSnapshotDto, ServerError> {
    let engine = state
        .engine
        .lock()
        .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
    let namespace_memories = engine
        .memory_items()
        .map_err(ServerError::internal)?
        .into_iter()
        .filter(|item| memory_in_namespace(item, namespace))
        .filter(|item| as_of.is_none_or(|instant| memory_believed_at(item, instant)))
        .collect::<Vec<_>>();
    let namespace_ids = namespace_memories
        .iter()
        .map(|item| item.id)
        .collect::<BTreeSet<_>>();
    let event_records = engine
        .event_records()
        .map_err(ServerError::internal)?
        .into_iter()
        .filter(|record| as_of.is_none_or(|instant| record.recorded_at <= instant))
        .filter(|record| event_touches_namespace(record, &namespace_ids, namespace))
        .collect::<Vec<_>>();
    let last_sequence = event_records.last().map(|record| record.sequence);
    let graph = tideline_graph(&namespace_memories, &event_records);
    let event_count = event_records.len();
    let memories = namespace_memories
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

fn event_touches_namespace(
    record: &EventRecord,
    namespace_ids: &BTreeSet<MemoryId>,
    namespace: &str,
) -> bool {
    match &record.event {
        MemoryEvent::MemoryWritten { item } => memory_in_namespace(item, namespace),
        MemoryEvent::MemoryInvalidated { id, .. }
        | MemoryEvent::ReverificationFlagged { id, .. }
        | MemoryEvent::AccessRecorded { id, .. }
        | MemoryEvent::TierChanged { id, .. }
        | MemoryEvent::ContentCompacted { id, .. } => namespace_ids.contains(id),
        MemoryEvent::ReconstructionApplied {
            superseded_id,
            replacement_id,
            ..
        } => namespace_ids.contains(superseded_id) || namespace_ids.contains(replacement_id),
        MemoryEvent::ConsolidationDecision {
            input_ids,
            output_id,
            ..
        } => {
            input_ids.iter().any(|id| namespace_ids.contains(id))
                || output_id.is_some_and(|id| namespace_ids.contains(&id))
        }
        MemoryEvent::HumanSignalRecorded { signal } => {
            namespace_ids.contains(&signal.memory_id)
                || signal
                    .proposal_id
                    .is_some_and(|id| namespace_ids.contains(&id))
        }
    }
}

fn tideline_event_from_record(record: EventRecord) -> TidelineEventDto {
    let sequence = record.sequence;
    let recorded_at = record.recorded_at;

    match record.event {
        MemoryEvent::MemoryWritten { item } => {
            let mut event =
                base_tideline_event(sequence, recorded_at, "memory_written", vec![item.id]);
            event.tier_to = Some(tier_str(item.tier).to_owned());
            event.valid_to_unix = item.timestamps.valid_to.map(OffsetDateTime::unix_timestamp);
            event
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
            .filter(|item| memory_in_namespace(item, &context.namespace))
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
            .filter(|item| memory_in_namespace(item, &context.namespace))
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
            .filter(|item| memory_in_namespace(item, &context.namespace))
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

async fn server_recall(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Json(body): Json<ServerRecallRequest>,
) -> Result<Json<Vec<RecallCandidateDto>>, ServerError> {
    let context = server_context_or_log(&headers, &state, "POST", "/recall")?;
    let result: Result<(Json<Vec<RecallCandidateDto>>, serde_json::Value), ServerError> = (|| {
        let requested_top_k = body.top_k.unwrap_or(5);
        let now = time_from_optional_unix(body.now_unix).map_err(ServerError::bad_request)?;
        let namespace_prefix = namespace_source_prefix(&context.namespace);
        let engine = state
            .engine
            .lock()
            .map_err(|error| ServerError::internal(format!("engine lock poisoned: {error}")))?;
        let all_memories = engine.memory_items().map_err(ServerError::internal)?;
        let namespace_memory_count = all_memories
            .iter()
            .filter(|item| memory_in_namespace(item, &context.namespace))
            .count();
        let search_top_k = all_memories.len().max(requested_top_k);
        let mut request = RecallRequest::new(&body.query_vector, search_top_k, now)
            .with_source_ref_prefix(&namespace_prefix);

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

        let mut candidates = engine.recall(&request).map_err(ServerError::internal)?;
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
            .filter(|trace| memory_in_namespace(&trace.item, &context.namespace))
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

async fn server_tideline_snapshot(
    State(state): State<ServerState>,
    headers: HeaderMap,
    Query(query): Query<TidelineQuery>,
) -> Result<Json<TidelineSnapshotDto>, ServerError> {
    let context = server_context_or_log(&headers, &state, "GET", "/tideline/snapshot")?;
    let result: Result<(Json<TidelineSnapshotDto>, serde_json::Value), ServerError> = (|| {
        let as_of = optional_time_from_unix(query.as_of_unix)?;
        let snapshot = tideline_snapshot_for_namespace(&state, &context.namespace, as_of)?;
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
        let snapshot = tideline_snapshot_for_namespace(&state, &context.namespace, as_of)?;
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
    let mut interval = tokio::time::interval(Duration::from_secs(1));
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let stream = IntervalStream::new(interval).map(move |_| {
        let event = match tideline_snapshot_for_namespace(&state_for_stream, &namespace, as_of) {
            Ok(snapshot) => match serde_json::to_string(&snapshot) {
                Ok(data) => SseEvent::default().event("snapshot").data(data),
                Err(error) => SseEvent::default()
                    .event("error")
                    .data(json!({ "error": error.to_string() }).to_string()),
            },
            Err(error) => SseEvent::default()
                .event("error")
                .data(json!({ "error": error.message }).to_string()),
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

impl From<MemoryItem> for MemoryItemDto {
    fn from(value: MemoryItem) -> Self {
        Self {
            id: value.id.to_string(),
            content: value.content,
            kind: memory_kind_str(value.kind).to_owned(),
            provenance: ProvenanceDto::from(value.provenance),
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

#[cfg(test)]
mod tests {
    use super::parse_vector;

    #[test]
    fn parse_vector_accepts_commas_and_spaces() {
        assert_eq!(parse_vector("1, 2 3").ok(), Some(vec![1.0, 2.0, 3.0]));
    }

    #[test]
    fn parse_vector_rejects_empty_values() {
        assert!(parse_vector(" , ").is_err());
    }
}
