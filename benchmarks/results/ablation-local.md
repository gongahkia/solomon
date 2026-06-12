# Benchmark Results

| Suite | System | Queries | Accuracy | Stale Answer Rate | Mean Token Cost | Correction Lag s | p50 ms | p95 ms | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ablation | shibahama | 3 | 1.000 | 0.000 | 8.000 | 60.000 | 1.278 | 1.636 | ok |
| ablation | shibahama-no-graph | 3 | 0.667 | 0.333 | 9.333 | 60.000 | 0.875 | 1.233 | ok |
| ablation | shibahama-no-reconstruction | 3 | 0.667 | 0.333 | 8.000 | n/a | 1.677 | 1.713 | ok |
| ablation | shibahama-no-significance | 3 | 0.667 | 0.333 | 6.333 | 60.000 | 1.243 | 1.644 | ok |
