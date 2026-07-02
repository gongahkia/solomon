// SPDX-License-Identifier: MIT

//! Criterion benchmark for ingest throughput.
#![allow(missing_docs)]

use criterion::{
    BatchSize, BenchmarkId, Criterion, Throughput, black_box, criterion_group, criterion_main,
};
use shibahama_perf::harness::{BenchStore, DEFAULT_BENCH_SCALE};

fn bench_ingest_throughput(criterion: &mut Criterion) {
    let mut group = criterion.benchmark_group("ingest_throughput");
    group.throughput(Throughput::Elements(DEFAULT_BENCH_SCALE as u64));
    group.bench_function(BenchmarkId::new("scale", DEFAULT_BENCH_SCALE), |bencher| {
        bencher.iter_batched(
            || BenchStore::empty(DEFAULT_BENCH_SCALE).expect("empty store should build"),
            |mut store| {
                store
                    .ingest_range(0, DEFAULT_BENCH_SCALE)
                    .expect("ingest should succeed");
                black_box(store.path);
            },
            BatchSize::LargeInput,
        );
    });
    group.finish();
}

criterion_group!(benches, bench_ingest_throughput);
criterion_main!(benches);
