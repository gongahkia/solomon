# Perf Scale 10k

| scale | items | queries | write p50 ns | write p95 ns | write p99 ns | recall p50 ns | recall p95 ns | recall p99 ns | ingest items/sec | post-write available | post-write recall p50 ns | post-write recall p95 ns | post-write recall p99 ns | hnsw recall@10 | hot ns | warm ns | cold ns | rss bytes | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 10k | 10000 | 10 | 9779500 | 12235833 | 12235833 | 179513791 | 333859417 | 333859417 | 62.91 | true | 173106125 | 652777750 | 652777750 | 0.5600 | 130999167 | 142667208 | 138800459 | 145195008 | measured |
