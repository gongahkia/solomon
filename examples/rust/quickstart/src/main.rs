// SPDX-License-Identifier: MIT

use shibahama_core::api::{Shibahama, WriteEmbedding};
use shibahama_core::model::{AccessOutcome, Provenance, SourceKind};
use shibahama_core::storage::MemoryWriteEvent;
use shibahama_core::vector::HnswVectorIndex;
use std::error::Error;
use std::fs;
use time::OffsetDateTime;

fn main() -> Result<(), Box<dyn Error>> {
    let path = std::env::temp_dir().join(format!(
        "shibahama-rust-quickstart-{}.redb",
        std::process::id()
    ));
    let _ = fs::remove_file(&path);

    let mut engine = Shibahama::open(&path, HnswVectorIndex::new(2))?;
    let now = OffsetDateTime::UNIX_EPOCH;
    let event = MemoryWriteEvent::new(
        "Project prefers boring, durable storage.",
        Provenance::new(
            SourceKind::User,
            Some("examples/rust/quickstart".to_owned()),
            "rust-example",
        ),
        now,
        now,
    );
    let item = engine.write_with_embedding(
        event,
        WriteEmbedding {
            vector: &[0.0, 1.0],
            index_name: "quickstart",
            model: "manual-example",
            model_version: "v1",
        },
    )?;

    let request = engine
        .recall_request(&[0.0, 1.0], 1, now)
        .with_raw_query_context("storage preference");
    let recalled = engine.recall(&request)?;

    assert_eq!(recalled[0].id, item.id);
    assert_eq!(recalled[0].item.content, item.content);

    engine.reinforce(item.id, AccessOutcome::Cited)?;
    let why = engine
        .why_at(item.id, now)?
        .expect("the written memory should still exist");

    println!("recalled: {}", recalled[0].item.content);
    println!("credence: {:?}", why.tier.credence);
    println!("significance: {:.3}", why.significance.final_score);

    drop(engine);
    let _ = fs::remove_file(path);

    Ok(())
}
