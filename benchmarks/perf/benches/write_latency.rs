// SPDX-License-Identifier: MIT

//! Criterion benchmark for single write latency.
#![allow(missing_docs)]

use criterion::{BenchmarkId, Criterion, Throughput, black_box, criterion_group, criterion_main};
use shibahama_perf::harness::{BenchStore, DEFAULT_BENCH_SCALE, DEFAULT_SEED, generated_item};

fn bench_write_latency(criterion: &mut Criterion) {
    let mut group = criterion.benchmark_group("write_latency");
    group.throughput(Throughput::Elements(1));
    group.bench_function(BenchmarkId::new("scale", DEFAULT_BENCH_SCALE), |bencher| {
        let mut store =
            BenchStore::populated(DEFAULT_BENCH_SCALE).expect("benchmark store should build");
        let mut next_index = DEFAULT_BENCH_SCALE;

        bencher.iter(|| {
            let item = generated_item(next_index, DEFAULT_SEED);
            let written = store
                .write_generated(next_index, black_box(&item))
                .expect("write should succeed");

            next_index = next_index.saturating_add(1);
            black_box(written.id);
        });
    });
    group.finish();
}

criterion_group!(benches, bench_write_latency);
criterion_main!(benches);
