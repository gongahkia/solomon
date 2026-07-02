// SPDX-License-Identifier: MIT

//! Integration coverage for the Node binding wrapper.

use shibahama::{RecallOptions, Shibahama, WriteOptions};
use tempfile::tempdir;

#[test]
fn node_wrapper_round_trips_write_recall_timeline_and_invalidate() {
    let tempdir = tempdir().expect("temp dir should be created");
    let path = tempdir.path().join("node-binding.redb");
    let engine = Shibahama::new(path.to_string_lossy().into_owned(), 2, Some(16))
        .expect("engine should open");

    assert!(engine.is_open());
    let item = engine
        .write(
            "Node binding memory".to_owned(),
            Some(WriteOptions {
                vector: Some(vec![1.0, 0.0]),
                source_kind: Some("user".to_owned()),
                source_ref: Some("node-binding-test".to_owned()),
                ingested_by: Some("node-test".to_owned()),
                valid_from_unix: Some(0.0),
                ingested_at_unix: Some(0.0),
                ..WriteOptions::default()
            }),
        )
        .expect("write should succeed");

    let candidates = engine
        .recall(
            vec![1.0, 0.0],
            1,
            Some(RecallOptions {
                now_unix: Some(0.0),
                ..RecallOptions::default()
            }),
        )
        .expect("recall should succeed");
    assert_eq!(
        candidates.first().map(|candidate| &candidate.id),
        Some(&item.id)
    );

    assert!(
        engine
            .invalidate(item.id.clone(), 10.0)
            .expect("invalidate should succeed")
    );
    let why = engine
        .why(item.id.clone(), Some(10.0))
        .expect("why should succeed")
        .expect("why should find memory");
    assert_eq!(why.currency_state, "invalidated");

    let historical = engine
        .timeline(vec![1.0, 0.0], 1, 0.0, Some(RecallOptions::default()))
        .expect("timeline should succeed");
    assert_eq!(
        historical.first().map(|candidate| &candidate.id),
        Some(&item.id)
    );
}
