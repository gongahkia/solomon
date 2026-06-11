// SPDX-License-Identifier: MIT

//! Command-line entry point for Shibahama.

#![allow(clippy::needless_pass_by_value)]

use clap::{Args, Parser, Subcommand, ValueEnum};
use serde::Serialize;
use shibahama_core::api::{Shibahama, WhyTrace, WriteEmbedding};
use shibahama_core::model::{
    CredenceTier, MemoryId, MemoryItem, MemoryKind, Provenance, SourceKind, Tier,
};
use shibahama_core::retrieval::{
    RecallCandidate, RecallCandidateCurrency, RecallCandidateSource, RecallRequest,
};
use shibahama_core::significance::SignificanceBreakdown;
use shibahama_core::storage::{MemoryWriteEvent, RedbMemoryStore};
use shibahama_core::vector::HnswVectorIndex;
use std::error::Error;
use std::fmt::{self, Display, Formatter};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use time::OffsetDateTime;
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

#[derive(Clone, Copy, ValueEnum)]
enum ExportFormat {
    /// Pretty JSON array.
    Json,
    /// Newline-delimited JSON records.
    Jsonl,
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
    let trace = engine.why_at(id, now)?.map(WhyTraceDto::from);

    write_json(&trace)
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
