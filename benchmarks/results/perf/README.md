# Phase A Perf Results

Generated with:

```sh
cargo run -p shibahama-perf --release --bin record_perf -- --tiers 1k,10k,100k --queries 30 --output-dir benchmarks/results/perf --omit-1m "1M local run omitted; immediate-durability ingest exceeded the available session budget"
```

| scale | items | queries | recall p50 ns | recall p95 ns | recall p99 ns | rss bytes | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1k | 1000 | 30 | 74885209 | 102433500 | 223013542 | 57540608 | measured |
| 10k | 10000 | 30 | 62939791 | 70041917 | 77550792 | 93585408 | measured |
| 100k | 100000 | 30 | 68567750 | 82027959 | 91084250 | 908836864 | measured |
| 1m | 1000000 | 30 | n/a | n/a | n/a | n/a | 1M local run omitted; immediate-durability ingest exceeded the available session budget |

Each `scale-*.json` carries the commit, rustc version, OS, CPU, RAM, seed,
embedding dimension, exact command, and UTC timestamp.

These local numbers are first proof artifacts, not a tuned result. They do not
show sub-millisecond recall on this machine.
