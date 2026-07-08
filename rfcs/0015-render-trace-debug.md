# RFC-0015: Render Trace Debugging

- Status: Draft
- Created: 2026-07-08
- Owner: core maintainers
- Area: daemon protocol, debugging

## Summary

Adds a render-trace surface for diagnosing slow or wrong prompts. Requests may set `trace: true`; responses may include module timing entries. The CLI also provides `SHISA_DEBUG` and `shisa trace` local debug paths that write trace lines to stderr.

## Motivation

Users need a self-service way to see which module rendered, how long it took, and whether cache behavior explains the result. Reading foreground daemon logs is not a useful normal workflow.

## Design

Render requests accept:

```json
{ "trace": true }
```

Prompt responses may include:

```json
{
  "trace": [
    {
      "module": "git_branch",
      "class": "async",
      "duration_ns": 340000,
      "cache_state": "hit",
      "placeholder": false
    }
  ]
}
```

CLI output format is line-oriented stderr:

```text
[shisa] cwd=/path
[shisa] module=cwd sync 0.12ms cache=none
[shisa] module=git_branch async 0.34ms cache=hit
[shisa] total 3.24ms modules=3
```

`SHISA_DEBUG=2` appends cache-key inspection fields such as `key=module:git_branch age_ms=0 hit_rate=n/a`.

## Performance

Tracing is opt-in. Normal renders do not allocate trace entry arrays. `shisa trace` uses ephemeral local caches and does not mutate the daemon cache.

## Security

Trace output can include local paths and module names. It is local-only and written to stderr so shell prompt stdout remains clean.

## Compatibility

No protocol version bump. Existing daemons ignore unknown `trace` request fields; existing clients ignore unknown response fields.

## Rejected Alternatives

- **Persist traces to disk:** rejected for now. Users can redirect stderr.
- **OpenTelemetry export:** rejected for this issue; exporter design belongs to observability RFC work.

## Unresolved Questions

- Exact daemon-side cache hit-rate accounting.
- Whether trace entries should include structured cache keys or redacted summaries only.
