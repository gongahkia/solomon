# Binding Parity

Issue: https://github.com/gongahkia/shibahama/issues/14

The Rust core is the semantic source of truth. Python and Node bindings are
release surfaces for the practical memory API, not complete administrative or
research-control mirrors.

## CI Gate

Run:

```sh
scripts/ci/binding-parity.sh
```

That gate runs:

- `cargo test -p shibahama-python --test wrapper`
- `cargo test -p shibahama-node --test wrapper`
- `scripts/ci/python-binding-smoke.sh`
- `scripts/ci/node-binding-smoke.sh`

`scripts/ci/all.sh` includes the same gate.

## Parity Matrix

| Capability | Rust core | Python | Node | Evidence |
| --- | --- | --- | --- | --- |
| Open store | yes | yes | yes | `bindings/*/tests/wrapper.rs`, binding smoke scripts |
| Write memory with provenance | yes | yes | yes | wrapper tests, binding smoke scripts |
| Recall with ranking weights | yes | yes | yes | binding smoke scripts |
| Context token budget | yes | yes | yes | binding smoke scripts |
| Caller-supplied graph expansion | yes | yes | no | Python smoke covers `related_memory_ids_by_anchor`; Node release deferral below |
| Timeline recall | yes | yes | yes | wrapper tests, binding smoke scripts |
| Streaming recall | yes | yes | yes | binding smoke scripts |
| Streaming timeline | yes | yes | yes | binding smoke scripts |
| Invalidate memory | yes | yes | yes | wrapper tests, binding smoke scripts |
| Reinforce memory | yes | yes | yes | binding smoke scripts |
| `why` trace | yes | yes | yes | wrapper tests, binding smoke scripts |
| Event records | yes | yes | yes | binding smoke scripts |
| Audit trail | yes | yes | yes | binding smoke scripts |
| Memory row export | yes | yes | yes | binding smoke scripts |
| Human `challenge` | yes | yes | yes | binding smoke scripts |
| Human `affirm` | yes | yes | yes | binding smoke scripts |
| Human `correct` | yes | yes | yes | binding smoke scripts |
| Human `pin` / `unpin` | yes | yes | yes | binding smoke scripts |
| Consolidation | yes | yes | yes | binding smoke scripts |
| LangChain adapter helper | n/a | yes | yes | binding smoke scripts |
| Async wrapper helpers | async facade | yes | n/a | Python smoke script |
| Error categories | yes | no | no | release deferral below |
| Snapshot / restore | yes | no | no | release deferral below |
| Never-delete verifier | yes | no | no | release deferral below |
| Stored graph entity/relation admin API | yes | no | no | release deferral below |
| Learned-policy gates | yes | no | no | release deferral below |

## Release Deferrals

These gaps are intentional for v0.1:

- Node caller-supplied graph expansion is deferred until the options object can
  expose a stable memory-id map without making the TypeScript surface awkward.
- Error category exposure is deferred; bindings currently raise host-language
  errors around the practical API.
- Snapshot, restore, and `verify_never_delete_invariant` remain Rust/core and
  CLI maintenance surfaces for v0.1.
- Stored graph entity/relation administration remains Rust/core and server API
  surface for v0.1.
- Learned-policy gates remain Rust-only because they are research/safety gates,
  not runtime binding defaults.

Any release that claims full Rust/Python/Node parity must remove or replace this
deferral list with passing parity tests.
