# Governed dependency assertion CLI

These commands are non-interactive and emit stable JSON. They operate on explicit, reviewable assertions; they do
not infer dependencies. Pass a complete request in a JSON file when possible so quote offsets and provenance can be
reviewed as one artifact.

```bash
uv run solomon assert-dependency --json assertion.json
uv run solomon dependency-assertion assertion-1 --matter-id matter-alpha --client-id client-alpha
uv run solomon dependency-assertions --state pending --needs-reverification false --limit 20
uv run solomon decide-dependency-assertion assertion-1 --by reviewer-alpha --decision confirmed \
  --expected-state-version 1 --matter-id matter-alpha --client-id client-alpha
uv run solomon withdraw-dependency-assertion assertion-2 --by curator-alpha --reason "replaced" \
  --expected-state-version 2 --matter-id matter-alpha --client-id client-alpha
```

`assert-dependency` accepts either `--json` or flags, never both. Its required data is the source item/document ID
and document version, one registered target, assertion/evidence type, rationale, creator, and idempotency key. Quote
evidence uses `--quote`, `--quote-start`, and `--quote-end`; commentary instead uses `--commentary`. A trusted-upstream
assertion uses `--origin trusted_upstream --trusted-upstream-ref <reference>`. `--revision-of <assertion-id>` records
a traced successor.

`decide-dependency-assertion` accepts `confirmed`, `rejected`, or `deferred`; `--reason` is mandatory for deferred.
The creator cannot make any decision on their own assertion. Confirmation is the only command that can cause the
underlying lifecycle to create an edge. `withdraw-dependency-assertion` is limited to pending/deferred assertions;
confirmed records remain preserved and need a traced replacement. See `uv run solomon <command> --help` for the exact
flag schema.
