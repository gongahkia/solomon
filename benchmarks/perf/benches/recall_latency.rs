// SPDX-License-Identifier: MIT

//! Criterion benchmark for recall latency.
#![allow(missing_docs)]

use criterion::{BenchmarkId, Criterion, Throughput, black_box, criterion_group, criterion_main};
use shibahama_perf::harness::{
    BenchStore, DEFAULT_BENCH_SCALE, DEFAULT_SEED, TOP_K, held_out_query,
};

fn bench_recall_latency(criterion: &mut Criterion) {
    let mut group = criterion.benchmark_group("recall_latency");
    group.throughput(Throughput::Elements(1));
    group.bench_function(BenchmarkId::new("scale", DEFAULT_BENCH_SCALE), |bencher| {
        let store =
            BenchStore::populated(DEFAULT_BENCH_SCALE).expect("benchmark store should build");
        let query = held_out_query(DEFAULT_SEED);

        bencher.iter(|| {
            let candidates = store
                .recall(black_box(&query), TOP_K)
                .expect("recall should succeed");

            black_box(candidates);
        });
    });
    group.finish();
}

criterion_group!(benches, bench_recall_latency);
criterion_main!(benches);
