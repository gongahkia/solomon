// SPDX-License-Identifier: MIT

//! Criterion benchmark for post-write recall availability.
#![allow(missing_docs)]

use criterion::{BenchmarkId, Criterion, Throughput, black_box, criterion_group, criterion_main};
use shibahama_perf::harness::{BenchStore, DEFAULT_BENCH_SCALE};
use std::time::Duration;

fn bench_post_write_availability(criterion: &mut Criterion) {
    let mut group = criterion.benchmark_group("post_write_availability");
    group.throughput(Throughput::Elements(1));
    group.bench_function(BenchmarkId::new("scale", DEFAULT_BENCH_SCALE), |bencher| {
        let mut store =
            BenchStore::populated(DEFAULT_BENCH_SCALE).expect("benchmark store should build");
        let mut next_index = DEFAULT_BENCH_SCALE;

        bencher.iter_custom(|iterations| {
            let mut total = Duration::ZERO;

            for _ in 0..iterations {
                let result = store
                    .post_write_availability(next_index)
                    .expect("post-write availability should run");

                assert!(
                    result.available,
                    "new memory must be immediately recallable"
                );
                next_index = next_index.saturating_add(1);
                total += result.recall_latency;
                black_box(result.memory_id);
            }

            total
        });
    });
    group.finish();
}

criterion_group!(benches, bench_post_write_availability);
criterion_main!(benches);
