// SPDX-License-Identifier: MIT

//! Golden-vector parity runner for Rust core behavior.

use serde::Deserialize;
use serde_json::{Value, json};
use shibahama_core::api::{Shibahama, WhyTrace, WriteEmbedding};
use shibahama_core::model::{MemoryId, MemoryItem, Provenance, SourceKind};
use shibahama_core::retrieval::{RecallCandidate, RecallRequest};
use shibahama_core::storage::MemoryWriteEvent;
use shibahama_core::vector::HnswVectorIndex;
use std::collections::BTreeMap;
use std::env;
use std::error::Error;
use std::fs;
use tempfile::NamedTempFile;
use time::OffsetDateTime;

#[derive(Deserialize)]
struct Fixture {
    dimensions: usize,
    capacity: usize,
    steps: Vec<Step>,
    queries: Vec<Query>,
    why_now_unix: i64,
}

#[derive(Deserialize)]
#[serde(tag = "op")]
enum Step {
    #[serde(rename = "write")]
    Write {
        content: String,
        vector: Vec<f32>,
        source_kind: String,
        source_ref: String,
        ingested_by: String,
        valid_from_unix: i64,
        ingested_at_unix: i64,
    },
    #[serde(rename = "invalidate")]
    Invalidate {
        source_ref: String,
        valid_to_unix: i64,
    },
}

#[derive(Deserialize)]
struct Query {
    name: String,
    vector: Vec<f32>,
    top_k: usize,
    now_unix: i64,
    raw_query_context: String,
    include_cold: bool,
}

fn main() -> Result<(), Box<dyn Error>> {
    let fixture_path = env::args()
        .nth(1)
        .ok_or("usage: cargo run --example golden_parity -- scripts/ci/golden-parity.json")?;
    let fixture: Fixture = serde_json::from_str(&fs::read_to_string(fixture_path)?)?;
    let store = NamedTempFile::new()?;
    let mut engine = Shibahama::open(
        store.path(),
        HnswVectorIndex::with_capacity(fixture.dimensions, fixture.capacity),
    )?;
    let mut ids = BTreeMap::<String, MemoryId>::new();
    for step in &fixture.steps {
        match step {
            Step::Write {
                content,
                vector,
                source_kind,
                source_ref,
                ingested_by,
                valid_from_unix,
                ingested_at_unix,
            } => {
                let event = MemoryWriteEvent::new(
                    content.clone(),
                    Provenance::new(
                        parse_source_kind(source_kind)?,
                        Some(source_ref.clone()),
                        ingested_by.clone(),
                    ),
                    unix(*valid_from_unix)?,
                    unix(*ingested_at_unix)?,
                );
                let item = engine.write_with_embedding(
                    event,
                    WriteEmbedding {
                        vector,
                        index_name: "default",
                        model: "unknown",
                        model_version: "unknown",
                    },
                )?;
                ids.insert(source_ref.clone(), item.id);
            }
            Step::Invalidate {
                source_ref,
                valid_to_unix,
            } => {
                let id = ids
                    .get(source_ref)
                    .copied()
                    .ok_or_else(|| format!("missing id for {source_ref}"))?;
                if !engine.invalidate(id, unix(*valid_to_unix)?)? {
                    return Err(format!("failed to invalidate {source_ref}").into());
                }
            }
        }
    }

    let mut query_outputs = Vec::new();
    for query in &fixture.queries {
        let mut request = RecallRequest::new(&query.vector, query.top_k, unix(query.now_unix)?)
            .with_raw_query_context(&query.raw_query_context);
        if query.include_cold {
            request = request.include_cold();
        }
        let recalled = engine.recall(&request)?;
        query_outputs.push(json!({
            "name": query.name,
            "recall": recalled.iter().map(normalize_candidate).collect::<Vec<_>>(),
        }));
    }
    let mut items = engine.memory_items()?;
    items.sort_by(|left, right| left.provenance.source_ref.cmp(&right.provenance.source_ref));
    let mut why_outputs = Vec::new();
    for item in &items {
        let trace = engine
            .why_at(item.id, unix(fixture.why_now_unix)?)?
            .ok_or_else(|| format!("missing why trace for {}", item.id))?;
        why_outputs.push(normalize_why(&trace));
    }
    let output = json!({
        "queries": query_outputs,
        "memories": items.iter().map(normalize_memory).collect::<Vec<_>>(),
        "why": why_outputs,
    });

    println!("{}", serde_json::to_string(&output)?);
    Ok(())
}

fn normalize_candidate(candidate: &RecallCandidate) -> Value {
    json!({
        "source_ref": candidate.item.provenance.source_ref,
        "tier": tier_str(candidate.tier),
        "credence": credence_str(candidate.item.credence),
        "currency": currency_str(candidate.currency),
        "significance_score": fixed(candidate.significance_score),
        "rank_score": fixed(candidate.rank_score),
    })
}

fn normalize_memory(memory: &MemoryItem) -> Value {
    json!({
        "source_ref": memory.provenance.source_ref,
        "tier": tier_str(memory.tier),
        "credence": credence_str(memory.credence),
        "significance": fixed(memory.significance),
        "valid_to_unix": memory.timestamps.valid_to.map(OffsetDateTime::unix_timestamp),
    })
}

fn normalize_why(trace: &WhyTrace) -> Value {
    json!({
        "source_ref": trace.item.provenance.source_ref,
        "currency_state": currency_str(trace.currency.state),
        "tier_current": tier_str(trace.tier.current),
        "tier_credence": credence_str(trace.tier.credence),
        "final_score": fixed(trace.significance.final_score),
        "valid_to_unix": trace.currency.valid_to.map(OffsetDateTime::unix_timestamp),
    })
}

fn parse_source_kind(value: &str) -> Result<SourceKind, Box<dyn Error>> {
    match value {
        "user" => Ok(SourceKind::User),
        "agent" => Ok(SourceKind::Agent),
        "file" => Ok(SourceKind::File),
        "web" => Ok(SourceKind::Web),
        "tool" => Ok(SourceKind::Tool),
        _ => Err(format!("unknown source kind: {value}").into()),
    }
}

fn unix(value: i64) -> Result<OffsetDateTime, Box<dyn Error>> {
    OffsetDateTime::from_unix_timestamp(value).map_err(Into::into)
}

fn tier_str(value: shibahama_core::model::Tier) -> &'static str {
    match value {
        shibahama_core::model::Tier::Hot => "hot",
        shibahama_core::model::Tier::Warm => "warm",
        shibahama_core::model::Tier::Cold => "cold",
    }
}

fn credence_str(value: shibahama_core::model::CredenceTier) -> &'static str {
    match value {
        shibahama_core::model::CredenceTier::Unverified => "unverified",
        shibahama_core::model::CredenceTier::ModelInferred => "model_inferred",
        shibahama_core::model::CredenceTier::VerifiedSource => "verified_source",
        shibahama_core::model::CredenceTier::FirmAuthoritative => "firm_authoritative",
    }
}

fn currency_str(value: shibahama_core::retrieval::RecallCandidateCurrency) -> &'static str {
    match value {
        shibahama_core::retrieval::RecallCandidateCurrency::Current => "current",
        shibahama_core::retrieval::RecallCandidateCurrency::NotYetValid => "not_yet_valid",
        shibahama_core::retrieval::RecallCandidateCurrency::Invalidated => "invalidated",
    }
}

fn fixed(value: f64) -> String {
    format!("{value:.6}")
}
