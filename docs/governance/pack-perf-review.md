# Pack Performance Review

Pack performance is reviewed quarterly against the core prompt baseline and the pack budgets in [Pack Status](../pack-status.md).

## Cadence

The calendar source lives at [Pack Performance Review Calendar](pack-perf-review-calendar.ics).

Each review covers the prior quarter's weekly `bench.yml` artifacts on `main`.

## Review Inputs

Collect:

- latest `pack-bench-head.json` artifact from `.github/workflows/bench.yml`
- prior quarter `pack-bench-head.json` artifacts
- prompt p99 dashboard output for the same commits
- merged pack changes since the prior review
- open `area/performance` issues for official packs

## Review Checks

For each official pack:

- compare current `packs.<id>` timing to its documented budget
- compare current timing to the prior quarter median
- explain any sustained overhead increase above 10%
- confirm new pack modules updated `src/bench.zig` and `docs/pack-status.md`
- open or update a `priority/p1` issue for any over-budget pack

Do not graduate a pack while its budget is over the documented limit or its benchmark coverage is missing.
