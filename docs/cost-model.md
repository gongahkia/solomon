# Remote Cost Model

Reviewed: 2026-07-10.

These estimates are [Inference] from the assumptions and public pricing below. Reprice before any rollout after 2026-08-31 because the Sonnet 5 introductory price changes on 2026-09-01.

## Pricing Inputs

- Anthropic Claude Haiku 4.5: $1/MTok input, $1.25/MTok 5-minute cache write, $0.10/MTok cache read, $5/MTok output.
- Anthropic Claude Sonnet 5 through 2026-08-31: $2/MTok input, $2.50/MTok 5-minute cache write, $0.20/MTok cache read, $10/MTok output.
- Anthropic prompt caching: 5-minute cache writes cost 1.25x base input; cache reads cost 0.1x base input.
- Exa Search: 20,000 free requests/month, then $7/1k Search requests with up to 10 results.
- Exa contents/summaries: $1/1k pages per content type; AI page summaries are $1/1k pages.
- Cloudflare Workers Standard: 10M requests/month included, then $0.30/M requests; 30M CPU ms/month included, then $0.02/M CPU ms.
- Cloudflare D1 paid tier: 25B rows read/month included, then $0.001/M rows; 50M rows written/month included, then $1/M rows; 5 GB storage included, then $0.75/GB-month.

Sources:

- https://platform.claude.com/docs/en/about-claude/pricing
- https://exa.ai/pricing
- https://developers.cloudflare.com/workers/platform/pricing/
- https://developers.cloudflare.com/d1/platform/pricing/

## Base Assumptions

- 1 DAU scans 300 LinkedIn posts/day.
- 10% of scanned posts are remotely classified: 30 classifications/DAU/day.
- 10% of classified posts render a note: 3 notes/DAU/day.
- Every classified post gets a Haiku first pass.
- 5% of classified posts get a Sonnet borderline pass: 1.5 Sonnet calls/DAU/day.
- Stable cached prompt: 600 input tokens.
- Dynamic post input: 250 input tokens.
- JSON output: 250 output tokens.
- Stable prompt cache mix: 80% cache hits, 20% 5-minute cache writes.
- Funding retrieval is off by default.
- When enabled, retrieval runs on 1% of classified posts: 0.3 retrievals/DAU/day.
- One retrieval uses 1 Exa Search request, 5 result highlights, and 5 result summaries.

## Model Cost

Per-call formula:

- Haiku = `600 * (80% * $0.10 + 20% * $1.25) / 1M + 250 * $1 / 1M + 250 * $5 / 1M = $0.001698`.
- Sonnet = `600 * (80% * $0.20 + 20% * $2.50) / 1M + 250 * $2 / 1M + 250 * $10 / 1M = $0.003396`.

Per DAU:

| Mode | Daily cost/DAU | 30-day cost/DAU |
| --- | ---: | ---: |
| Tonal only | $0.0560 | $1.6810 |
| Tonal + funding retrieval | $0.0611 | $1.8340 |

Retrieval add-on:

- Exa per retrieval = `$0.007 Search + 5 * $0.001 highlights + 5 * $0.001 summaries = $0.017`.
- 0.3 retrievals/DAU/day = `$0.0051/DAU/day`.

## Worker and D1 Envelope

Not included in the main per-DAU table because the paid-plan included usage is account-wide.

- Worker requests: `30 classifications * 30 days = 900 requests/DAU-month`; overage-only request cost is `$0.00027/DAU-month`.
- D1 writes: assume 2 written rows/classification for quota and replay; `1,800 rows/DAU-month`; overage-only write cost is `$0.0018/DAU-month`.
- D1 reads should stay indexed on tester ID, day bucket, and trace ID before paid beta.
- CPU cost needs measurement from Worker analytics after an actual gateway deploy.

## Rollout Guardrails

- Private beta cap: 5 testers.
- Remote classification quota: 30 classifications/tester/day.
- Funding retrieval quota: 1 retrieval/tester/day.
- Sonnet escalation quota: 5% of classified posts/day, hard cap 2 Sonnet calls/tester/day.
- Prompt-cache health gate: pause remote expansion if stable-prompt cache hits stay below 60% for 2 consecutive days.
- Retrieval starts disabled for every tester; enable per tester only.
- Funding retrieval runs only for funding-announcement candidates.
- Gateway returns `429` for over-quota classification, retrieval, or Sonnet escalation.
- Gateway records estimated provider cost, model, token counts, cache write/read counts, Exa result count, and provider request IDs per response.
- Daily provider spend alert: $2/day during 5-tester beta.
- Daily provider hard stop: $5/day during 5-tester beta.
- Expand beyond 5 testers only after 7 consecutive days with observed cost <= $0.08/DAU/day and reviewed false-positive ratings.
