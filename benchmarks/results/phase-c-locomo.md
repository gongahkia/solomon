# Benchmark Results

| Suite | System | Queries | Accuracy | Stale Answer Rate | Mean Token Cost | Correction Lag s | p50 ms | p95 ms | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| locomo | full-context | 1531 | 0.314 | 0.686 | 4095.105 | n/a | 0.020 | 0.026 | ok |
| locomo | mem0-oss-exact | 1531 | 0.138 | 0.862 | 81.424 | n/a | 3.633 | 4.539 | ok |
| locomo | shibahama | 1531 | 0.047 | 0.953 | 79.133 | n/a | 38.390 | 43.679 | ok |
| locomo | warehouse | 1531 | 0.153 | 0.847 | 90.816 | n/a | 0.284 | 0.399 | ok |

## Category Breakdown

| Suite | System | Category | Queries | Accuracy | Stale Answer Rate | Mean Token Cost | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| locomo | full-context | locomo-category-1 | 282 | 0.209 | 0.791 | 4082.401 | ok |
| locomo | full-context | locomo-category-2 | 321 | 0.084 | 0.916 | 4014.059 | ok |
| locomo | full-context | locomo-category-3 | 96 | 0.115 | 0.885 | 4109.844 | ok |
| locomo | full-context | locomo-category-4 | 830 | 0.459 | 0.541 | 4131.806 | ok |
| locomo | full-context | locomo-category-5 | 2 | 1.000 | 0.000 | 2956.000 | ok |
| locomo | mem0-oss-exact | locomo-category-1 | 282 | 0.035 | 0.965 | 79.475 | ok |
| locomo | mem0-oss-exact | locomo-category-2 | 321 | 0.019 | 0.981 | 80.682 | ok |
| locomo | mem0-oss-exact | locomo-category-3 | 96 | 0.042 | 0.958 | 83.104 | ok |
| locomo | mem0-oss-exact | locomo-category-4 | 830 | 0.229 | 0.771 | 82.177 | ok |
| locomo | mem0-oss-exact | locomo-category-5 | 2 | 0.500 | 0.500 | 82.000 | ok |
| locomo | shibahama | locomo-category-1 | 282 | 0.011 | 0.989 | 77.784 | ok |
| locomo | shibahama | locomo-category-2 | 321 | 0.009 | 0.991 | 78.897 | ok |
| locomo | shibahama | locomo-category-3 | 96 | 0.031 | 0.969 | 78.656 | ok |
| locomo | shibahama | locomo-category-4 | 830 | 0.075 | 0.925 | 79.718 | ok |
| locomo | shibahama | locomo-category-5 | 2 | 0.500 | 0.500 | 87.500 | ok |
| locomo | warehouse | locomo-category-1 | 282 | 0.050 | 0.950 | 88.014 | ok |
| locomo | warehouse | locomo-category-2 | 321 | 0.037 | 0.963 | 92.059 | ok |
| locomo | warehouse | locomo-category-3 | 96 | 0.042 | 0.958 | 89.990 | ok |
| locomo | warehouse | locomo-category-4 | 830 | 0.247 | 0.753 | 91.370 | ok |
| locomo | warehouse | locomo-category-5 | 2 | 0.000 | 1.000 | 96.000 | ok |
