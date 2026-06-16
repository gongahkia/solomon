# Prompt Comparison Harness

Run:

```sh
bench/compare-prompts.sh
```

The harness builds Shisa, starts a temporary `shisad`, then benchmarks prompt render commands with `hyperfine`.

Outputs:

- `bench-results/comparison.json`
- `bench-results/comparison.md`

Targets:

- `shisa`: always included.
- `starship`: included when `starship` is in `PATH`.
- `oh-my-posh`: included when `oh-my-posh` is in `PATH`; set `OMP_CONFIG=/path/to/theme.omp.json` to pick a config.
- `p10k`: set `P10K_BENCH_CMD` to a noninteractive render command.

Tuning:

- `SHISA_BENCH_RUNS=50`
- `SHISA_BENCH_WARMUP=10`
