# Benchmark Results

| Suite | System | Queries | Accuracy | Stale Answer Rate | Mean Token Cost | Correction Lag s | p50 ms | p95 ms | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| longmemeval | full-context | 500 | 0.500 | 0.500 | 74014.154 | n/a | 0.353 | 1.058 | ok |
| longmemeval | mem0-oss-exact | 500 | 0.372 | 0.628 | 8758.462 | n/a | 9.143 | 35.347 | ok |
| longmemeval | shibahama | 500 | 0.218 | 0.782 | 7481.056 | n/a | 127.100 | 804.925 | ok |
| longmemeval | warehouse | 500 | 0.422 | 0.578 | 11128.144 | n/a | 14.266 | 36.186 | ok |

## Category Breakdown

| Suite | System | Category | Queries | Accuracy | Stale Answer Rate | Mean Token Cost | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| longmemeval | full-context | knowledge-update | 78 | 0.756 | 0.244 | 77829.154 | ok |
| longmemeval | full-context | multi-session | 133 | 0.541 | 0.459 | 78931.331 | ok |
| longmemeval | full-context | single-session-assistant | 56 | 0.554 | 0.446 | 78953.411 | ok |
| longmemeval | full-context | single-session-preference | 30 | 0.000 | 1.000 | 79051.733 | ok |
| longmemeval | full-context | single-session-user | 70 | 0.814 | 0.186 | 78930.443 | ok |
| longmemeval | full-context | temporal-reasoning | 133 | 0.233 | 0.767 | 61056.105 | ok |
| longmemeval | mem0-oss-exact | knowledge-update | 78 | 0.615 | 0.385 | 9210.154 | ok |
| longmemeval | mem0-oss-exact | multi-session | 133 | 0.383 | 0.617 | 8960.842 | ok |
| longmemeval | mem0-oss-exact | single-session-assistant | 56 | 0.518 | 0.482 | 8332.750 | ok |
| longmemeval | mem0-oss-exact | single-session-preference | 30 | 0.000 | 1.000 | 8697.333 | ok |
| longmemeval | mem0-oss-exact | single-session-user | 70 | 0.500 | 0.500 | 7999.086 | ok |
| longmemeval | mem0-oss-exact | temporal-reasoning | 133 | 0.173 | 0.827 | 8883.887 | ok |
| longmemeval | shibahama | knowledge-update | 78 | 0.359 | 0.641 | 8143.615 | ok |
| longmemeval | shibahama | multi-session | 133 | 0.308 | 0.692 | 7840.233 | ok |
| longmemeval | shibahama | single-session-assistant | 56 | 0.143 | 0.857 | 8248.179 | ok |
| longmemeval | shibahama | single-session-preference | 30 | 0.000 | 1.000 | 8026.900 | ok |
| longmemeval | shibahama | single-session-user | 70 | 0.229 | 0.771 | 7668.114 | ok |
| longmemeval | shibahama | temporal-reasoning | 133 | 0.120 | 0.880 | 6188.737 | ok |
| longmemeval | warehouse | knowledge-update | 78 | 0.692 | 0.308 | 11413.872 | ok |
| longmemeval | warehouse | multi-session | 133 | 0.391 | 0.609 | 11166.271 | ok |
| longmemeval | warehouse | single-session-assistant | 56 | 0.393 | 0.607 | 10422.357 | ok |
| longmemeval | warehouse | single-session-preference | 30 | 0.000 | 1.000 | 11870.667 | ok |
| longmemeval | warehouse | single-session-user | 70 | 0.714 | 0.286 | 10926.543 | ok |
| longmemeval | warehouse | temporal-reasoning | 133 | 0.248 | 0.752 | 11158.241 | ok |
