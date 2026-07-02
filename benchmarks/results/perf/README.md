# Phase A Perf Results

Generated with:

```sh
cargo run -p shibahama-perf --release --bin record_perf -- --tiers 1k,10k,100k --queries 30 --quality-tiers 10k,100k --quality-queries 10 --output-dir benchmarks/results/perf --omit-1m "1M local run omitted; immediate-durability ingest exceeded the available session budget"
```

| scale | items | queries | recall p50 ns | recall p95 ns | recall p99 ns | hnsw recall@10 | rss bytes | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1k | 1000 | 30 | 62974208 | 73965291 | 75001333 | n/a | 81920000 | measured |
| 10k | 10000 | 30 | 61740500 | 72042458 | 80616292 | 0.5000 | 663846912 | measured |
| 100k | 100000 | 30 | 83980041 | 95065791 | 134221209 | 0.0800 | 894959616 | measured |
| 1m | 1000000 | 30 | n/a | n/a | n/a | n/a | n/a | 1M local run omitted; immediate-durability ingest exceeded the available session budget |

Each `scale-*.json` carries the commit, rustc version, OS, CPU, RAM, seed,
embedding dimension, exact command, and UTC timestamp.

These local numbers are first proof artifacts, not a tuned result. They do not
show sub-millisecond recall on this machine.

HNSW recall@10 is below the Phase A target, especially at 100k. Treat this as a
tuning issue before using the latency numbers as a quality-adjusted proof.
