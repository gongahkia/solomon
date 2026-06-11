# CurrencyBench

CurrencyBench is a long-horizon memory benchmark focused on changed facts.

Each case injects an earlier fact and a later replacement fact, then asks for the current answer. Metrics:

- `stale_answer_rate`: answer cites the old fact or misses the replacement.
- `latency_p50_ms` and `latency_p95_ms`: wall-clock retrieval latency.
- `mean_token_cost`: approximate whitespace-token size of retrieved context.
- `accuracy`: answer contains the expected replacement and not the stale value.

The generated suite is deterministic:

```bash
python benchmarks/run.py --suite currencybench --systems shibahama,warehouse
```

External Mem0 and Zep runs use the same observations and queries through the optional adapters in `benchmarks/shibahama_bench/adapters.py`.
