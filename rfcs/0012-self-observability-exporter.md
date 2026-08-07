# RFC-0012: Local Self-Observability Exporter

- Status: Draft
- Created: 2026-07-08
- Owner: core maintainers
- Area: daemon observability, security

## Summary

Shisa may expose an optional localhost-only Prometheus `/metrics` endpoint for self-observability. It is off by default, refuses non-loopback bind addresses, emits no outbound traffic, and reuses the daemon's existing metrics counters and histograms.

This is not user telemetry. The user runs the daemon, enables the endpoint, and points their own local scraper at loopback.

## Motivation

`shisad --metrics` already reports daemon state as a one-shot admin request. That is enough for manual debugging but not for long-running local inspection. Users debugging prompt latency, cache churn, or plugin behavior need time-series visibility into:

- render latency buckets
- cache hit rate
- module class latency
- plugin timing and failure counts
- socket accept depth or backpressure

The north-star zero-telemetry rule bans outbound reporting. A loopback exporter is a different boundary: no metric leaves the machine unless the user configures a scraper to collect it.

## Threat Model

### Does Localhost Violate The Telemetry Ban?

No, if all of these remain true:

- disabled by default
- binds only to `127.0.0.1` or `::1`
- no outbound connections
- no automatic discovery or registration
- no raw prompt text, cwd, username, hostname, branch name, command, or environment values in labels

It becomes telemetry or data leakage if:

- Shisa sends metrics to any remote service
- the exporter binds to `0.0.0.0`, `::`, LAN IPs, or public IPs
- labels include local secrets or user-controlled high-cardinality text
- a container or SSH forwarding setup makes "localhost" reachable by an unexpected peer without user consent

### Local Attackers

A local same-user process can already connect to the Unix socket. The exporter must not expose more sensitive data than the existing metrics request. A different local user must not read metrics; loopback alone is not an authentication boundary on multi-user hosts, so the first implementation should either stay per-user and loopback-only or add a bearer token file under a `0700` directory.

### Label Injection

Prometheus labels must not contain unbounded user-controlled data. Module ids and execution classes are stable low-cardinality labels. Cwd, branch, context name, plugin output, and error text are not allowed as labels.

## Config

Proposed config:

```toml
[daemon.metrics.prometheus]
enabled = true
addr = "127.0.0.1:9878"
require_loopback = true
```

Defaults:

```toml
[daemon.metrics.prometheus]
enabled = false
addr = "127.0.0.1:9878"
require_loopback = true
```

Validation:

- `enabled=false`: do not bind.
- `require_loopback=true`: resolve and reject every non-loopback address.
- `require_loopback=false`: reserved for tests only in v0.x; release builds should still reject non-loopback unless a later RFC accepts remote scraping.
- invalid address: daemon startup fails with a clear config diagnostic.

## Endpoint

Expose:

```text
GET /metrics
```

Responses use Prometheus text format: UTF-8, line-oriented, `text/plain; version=0.0.4`, `HELP` and `TYPE` metadata, and histogram buckets following Prometheus conventions.

No other HTTP endpoints are required.

## Metrics

Initial metrics:

| Metric | Type | Labels | Notes |
| --- | --- | --- | --- |
| `shisa_render_seconds` | histogram | none | existing render histogram converted from microseconds |
| `shisa_render_total` | counter | none | render count |
| `shisa_prompt_cache_entries` | gauge | none | L1 entries |
| `shisa_prompt_cache_hit_total` | counter | none | hits |
| `shisa_prompt_cache_miss_total` | counter | none | misses |
| `shisa_module_render_seconds` | histogram | `module`, `class` | only stable module ids |
| `shisa_plugin_render_seconds` | histogram | `plugin`, `module` | plugin id and module id only |
| `shisa_plugin_error_total` | counter | `plugin`, `kind` | bounded error kind |
| `shisa_socket_connections` | counter | none | accepted connections |
| `shisa_subscription_backpressure_dropped_total` | counter | `topic` | bounded topic names |

Forbidden labels:

- cwd
- home
- username
- hostname
- Git branch
- cloud account or project names
- command text
- raw error strings
- plugin-rendered text

## Implementation Plan

1. Extend config parsing with the `[daemon.metrics.prometheus]` table.
2. Add loopback address validation before binding.
3. Start a small HTTP listener only when enabled.
4. Serialize the same counters used by `shisad --metrics` in Prometheus text format.
5. Add module/plugin timing once trace data exists; until then expose only daemon-level metrics.

The HTTP listener must share shutdown with the main daemon. It must not block render handling. If the exporter cannot bind, startup fails rather than silently running without metrics.

## OpenTelemetry

OTLP is rejected for the first implementation. It adds protocol complexity and often implies outbound collection. A future RFC can revisit OpenTelemetry after the localhost Prometheus exporter proves useful.

## Performance

Disabled path cost is zero after config parsing. Enabled path cost is bounded to counter increments already collected today plus occasional `/metrics` serialization on scrape. Serialization runs on the exporter request path, not prompt render.

No implementation should land unless:

```sh
scripts/perf-suite.sh --repo /path/to/pinned-large-repo
```

continues to pass with the exporter disabled.

## Security

The daemon must fail closed:

- non-loopback bind with `require_loopback=true`: refuse startup
- unsupported path other than `/metrics`: return `404`
- metric label outside allow-list: compile-time or test failure
- exporter thread panic: daemon logs and shuts down exporter; prompt rendering continues only if no state corruption occurred

No outbound network calls are allowed in the exporter implementation.

## Compatibility

The feature is off by default. Existing users see no open port and no config requirement. `shisad --metrics` remains supported for one-shot diagnostics.

Prometheus schema is explicitly unstable in the first release. Metric names may change before v1 unless documented as stable later.

## Rejected Alternatives

- Default-on exporter: violates least surprise.
- Bind on `0.0.0.0`: too easy to leak local context on laptops, devcontainers, and shared hosts.
- Pushgateway or remote write: outbound traffic violates the zero-telemetry contract.
- Full OpenTelemetry first: too much surface before local scrape proves demand.

## Unresolved Questions

- Whether multi-user hosts need a token even for loopback.
- Whether exporter bind failure should fail daemon startup or only disable exporter. This RFC recommends fail startup for explicit config errors.
- Whether plugin ids should be labels before plugin trust metadata is mature.
- Whether `shisad --metrics --prometheus` and the HTTP endpoint should share exactly one serializer.
