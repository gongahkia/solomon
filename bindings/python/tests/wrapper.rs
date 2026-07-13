// SPDX-License-Identifier: MIT

//! Integration coverage for the Python binding wrapper.

use _shibahama::PyShibahama;
use tempfile::tempdir;

#[test]
fn python_wrapper_round_trips_write_recall_timeline_and_invalidate() {
    let tempdir = tempdir().expect("temp dir should be created");
    let path = tempdir.path().join("python-binding.redb");
    let path = path.to_str().expect("temp path should be utf-8");
    let engine = PyShibahama::new(path, 2, 16).expect("engine should open");
    let item = engine
        .write(
            "Python binding memory".to_owned(),
            Some(vec![1.0, 0.0]),
            "user",
            Some("python-binding-test".to_owned()),
            "python-test",
            Some(0),
            Some(0),
            "fact",
            "default",
            "test",
            "v1",
            "default",
            None,
            "repository",
        )
        .expect("write should succeed");

    let candidates = engine
        .recall(
            vec![1.0, 0.0],
            1,
            Some(0),
            None,
            false,
            false,
            None,
            1.0,
            1.0,
            0.25,
            0.25,
            None,
        )
        .expect("recall should succeed");
    assert_eq!(
        candidates.first().map(|candidate| &candidate.id),
        Some(&item.id)
    );

    assert!(
        engine
            .invalidate(&item.id, 10)
            .expect("invalidate should succeed")
    );
    let why = engine
        .why(&item.id, Some(10))
        .expect("why should succeed")
        .expect("why should find memory");
    assert_eq!(why.currency_state, "invalidated");

    let historical = engine
        .timeline(vec![1.0, 0.0], 1, 0, false, false, None)
        .expect("timeline should succeed");
    assert_eq!(
        historical.first().map(|candidate| &candidate.id),
        Some(&item.id)
    );
}
