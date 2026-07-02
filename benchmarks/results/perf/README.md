# Phase A Perf Results

Generated with:

```sh
cargo run -p shibahama-perf --release --bin record_perf -- --tiers 1k,10k,100k --queries 30 --quality-tiers 10k,100k --quality-queries 10 --tier-breakdown --tier-repetitions 30 --output-dir benchmarks/results/perf --omit-1m "1M local run omitted; immediate-durability ingest exceeded the available session budget"
```

| scale | items | queries | recall p50 ns | recall p95 ns | recall p99 ns | hnsw recall@10 | hot ns | warm ns | cold ns | rss bytes | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1k | 1000 | 30 | 61995791 | 77067167 | 79977125 | n/a | 64017667 | 65991166 | 61024250 | 82345984 | measured |
| 10k | 10000 | 30 | 68170000 | 81952916 | 82967875 | 0.4500 | 64853417 | 64006417 | 65491625 | 667992064 | measured |
| 100k | 100000 | 30 | 71840750 | 83998500 | 85011667 | 0.0700 | 66950833 | 67962250 | 64927584 | 3523788800 | measured |
| 1m | 1000000 | 30 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 1M local run omitted; immediate-durability ingest exceeded the available session budget |

Each `scale-*.json` carries the commit, rustc version, OS, CPU, RAM, seed,
embedding dimension, exact command, and UTC timestamp.

These local numbers are first proof artifacts, not a tuned result. They do not
show sub-millisecond recall on this machine.

HNSW recall@10 is below the Phase A target, especially at 100k. Treat this as a
tuning issue before using the latency numbers as a quality-adjusted proof.

The tier breakdown does not currently show hot recall consistently faster than
cold-content rehydration. Treat tier-latency benefit as unproven by these local
artifacts.
