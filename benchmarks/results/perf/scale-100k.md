# Perf Scale 100k

| scale | items | queries | write p50 ns | write p95 ns | write p99 ns | recall p50 ns | recall p95 ns | recall p99 ns | ingest items/sec | post-write available | post-write recall p50 ns | post-write recall p95 ns | post-write recall p99 ns | hnsw recall@10 | hot ns | warm ns | cold ns | rss bytes | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 100k | 100000 | 10 | 7224709 | 8030792 | 8030792 | 104757416 | 114615416 | 114615416 | 110.05 | true | 97306000 | 100754042 | 100754042 | 0.0600 | 86774375 | 83922042 | 83344958 | 1473150976 | measured |
