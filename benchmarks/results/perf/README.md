# Phase A Perf Results

Generated with:

```sh
target/release/record_perf --tiers 1k,10k,100k --queries 10 --quality-tiers 10k,100k --quality-queries 5 --tier-breakdown --tier-repetitions 3 --output-dir benchmarks/results/perf --omit-1m 1M local run omitted; immediate-durability ingest exceeded the available session budget --hnsw-m 8 --hnsw-ef-construction 32 --hnsw-ef-search 512
```

| scale | items | queries | write p50 ns | write p95 ns | write p99 ns | recall p50 ns | recall p95 ns | recall p99 ns | ingest items/sec | post-write available | post-write recall p50 ns | post-write recall p95 ns | post-write recall p99 ns | hnsw recall@10 | hot ns | warm ns | cold ns | rss bytes | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1k | 1000 | 10 | 35329000 | 95897917 | 95897917 | 383250458 | 485154667 | 485154667 | 8.85 | true | 319818792 | 459071625 | 459071625 | n/a | 392651333 | 373627291 | 270979750 | 8732672 | measured |
| 10k | 10000 | 10 | 9779500 | 12235833 | 12235833 | 179513791 | 333859417 | 333859417 | 62.91 | true | 173106125 | 652777750 | 652777750 | 0.5600 | 130999167 | 142667208 | 138800459 | 145195008 | measured |
| 100k | 100000 | 10 | 7224709 | 8030792 | 8030792 | 104757416 | 114615416 | 114615416 | 110.05 | true | 97306000 | 100754042 | 100754042 | 0.0600 | 86774375 | 83922042 | 83344958 | 1473150976 | measured |
| 1m | 1000000 | 10 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 1M local run omitted; immediate-durability ingest exceeded the available session budget |

These local numbers are first proof artifacts, not a tuned result. They do not show sub-millisecond recall on this machine.
HNSW recall@10 is below the 0.900 quality target for at least one measured tier. Treat those rows as tuning failures before using latency as quality-adjusted proof.
The tier breakdown does not currently show hot <= warm <= cold consistently. Treat tier-latency benefit as unproven by these artifacts.
Post-write availability is true for every measured tier.
1m local run omitted: 1M local run omitted; immediate-durability ingest exceeded the available session budget
CI smoke uses `scripts/ci/perf-smoke.sh`; default gross recall p99 threshold is 500000000 ns and this run used 500000000 ns when `--max-recall-p99-ns` was set.

Each `scale-*.json` carries the commit, rustc version, OS, CPU, RAM, seed, embedding dimension, HNSW params, exact command, and UTC timestamp.
