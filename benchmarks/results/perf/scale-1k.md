# Perf Scale 1k

| scale | items | queries | write p50 ns | write p95 ns | write p99 ns | recall p50 ns | recall p95 ns | recall p99 ns | ingest items/sec | post-write available | post-write recall p50 ns | post-write recall p95 ns | post-write recall p99 ns | hnsw recall@10 | hot ns | warm ns | cold ns | rss bytes | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1k | 1000 | 10 | 35329000 | 95897917 | 95897917 | 383250458 | 485154667 | 485154667 | 8.85 | true | 319818792 | 459071625 | 459071625 | n/a | 392651333 | 373627291 | 270979750 | 8732672 | measured |
