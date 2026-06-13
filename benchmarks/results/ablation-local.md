# Benchmark Results

| Suite | System | Queries | Accuracy | Stale Answer Rate | Mean Token Cost | Correction Lag s | p50 ms | p95 ms | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ablation | shibahama | 3 | 1.000 | 0.000 | 8.000 | 60.000 | 7.500 | 9.622 | ok |
| ablation | shibahama-no-graph | 3 | 0.667 | 0.333 | 9.333 | 60.000 | 3.973 | 7.064 | ok |
| ablation | shibahama-no-reconstruction | 3 | 0.667 | 0.333 | 8.000 | n/a | 7.205 | 7.367 | ok |
| ablation | shibahama-no-significance | 3 | 0.667 | 0.333 | 6.333 | 60.000 | 10.168 | 15.775 | ok |
