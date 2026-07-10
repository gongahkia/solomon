# Shared Ledger Design

Reviewed: 2026-07-10.

## Decision

Keep the local `chrome.storage.local` ledger for the unpacked prototype. Add a gateway-backed shared ledger for remote beta builds using Cloudflare Worker + D1.

The shared ledger has two visibility layers:

- Private review ledger: full replay data for testers and maintainers.
- Public ledger snapshot: redacted trace metadata, note outcome, false-positive state, sources, and aggregate ratings.

Do not publish raw LinkedIn post text, LinkedIn author identity, tester identity, classifier prompts, or full provider responses in the public snapshot.

## Surface

### Tester Side Panel

Rename the current local ledger concept to "Activity Ledger" when remote sync exists.

Top-level counters:

- Notes shown
- False positives
- Pending review

List rows use the same row size and same order weight for successful notes and false positives. A false positive is not a nested state under a successful note; it is a first-class ledger row with the same trace detail affordance.

Filters:

- All
- Shown
- False positives
- Funding notes
- Tonal notes
- Needs review

Row fields:

- label
- note kind
- status: shown, false positive, under review, corrected, withdrawn
- confidence
- threshold
- model/provider
- timestamp
- rating label
- source count
- trace ID

Trace details:

- why flagged copy shown to the tester
- classifier request snapshot
- classifier response snapshot
- model/provider metadata
- threshold/settings snapshot
- evidence strings
- sources
- rating history for that trace
- false-positive review state

### Shared Review Ledger

Route: `GET /ledger`.

Access: authenticated maintainers and invited testers.

Default view has two equal columns:

- Shown notes
- False positives

Both columns have the same card component, filters, trace drawer, CSV export, and review controls. False positives are sorted by newest rating first; shown notes are sorted by newest note first.

Review actions:

- mark false positive reviewed
- assign reason: model error, retrieval error, source error, copy error, user disagreement
- link to eval fixture PR/commit
- withdraw public snapshot row
- request tester deletion

### Public Snapshot

Route: `GET /ledger/public`.

Public rows show:

- trace ID
- note kind
- status
- confidence bucket, not exact confidence
- model family, not raw provider response
- source domains and URLs for factual notes
- generated date
- review date
- false-positive category after review
- redacted note text

Public rows do not show raw post text. Use a short redacted excerpt only when the tester has opted in and the excerpt is needed to understand the correction.

## D1 Backend

Create the D1 database with the intended jurisdiction before beta data collection. Cloudflare D1 jurisdiction is selected at creation time and cannot be added later. Use an EU jurisdiction for EU testers; use a separate database for non-EU beta data if needed.

Tables:

```sql
ledger_entries(
  trace_id text primary key,
  response_id text not null,
  request_id text not null,
  tester_id text not null,
  install_id text not null,
  post_key_hash text not null,
  post_url_hash text,
  note_kind text not null,
  status text not null,
  confidence real,
  threshold real not null,
  classifier_provider text not null,
  classifier_model text not null,
  contract_version text not null,
  rubric_version text not null,
  safety_copy_version text not null,
  generated_at text not null,
  updated_at text not null,
  public_snapshot_enabled integer not null default 0
);

ledger_replay_blobs(
  trace_id text primary key references ledger_entries(trace_id),
  request_json_ciphertext text not null,
  response_json_ciphertext text not null,
  post_text_ciphertext text not null,
  settings_json_ciphertext text not null,
  encryption_key_version text not null,
  expires_at text not null
);

ledger_sources(
  id text primary key,
  trace_id text not null references ledger_entries(trace_id),
  url text not null,
  domain text not null,
  title text,
  published_at text,
  excerpt text,
  provider text,
  provider_request_id text
);

ledger_ratings(
  id text primary key,
  trace_id text not null references ledger_entries(trace_id),
  tester_id text not null,
  rating text not null,
  false_positive integer not null,
  created_at text not null,
  unique(trace_id, tester_id)
);

ledger_reviews(
  id text primary key,
  trace_id text not null references ledger_entries(trace_id),
  reviewer_id text not null,
  review_state text not null,
  false_positive_category text,
  eval_commit_sha text,
  notes text,
  created_at text not null
);

ledger_public_rows(
  trace_id text primary key references ledger_entries(trace_id),
  status text not null,
  note_kind text not null,
  confidence_bucket text,
  model_family text,
  redacted_note_text text,
  source_json text,
  false_positive_category text,
  generated_at text not null,
  reviewed_at text
);
```

Indexes:

- `ledger_entries(tester_id, generated_at)`
- `ledger_entries(status, generated_at)`
- `ledger_entries(post_key_hash)`
- `ledger_ratings(false_positive, created_at)`
- `ledger_reviews(review_state, created_at)`

## Data Preservation

Private review ledger stores:

- trace ID and response ID
- classifier request and response
- post text
- model/provider metadata
- contract/rubric/safety-copy versions
- threshold and settings snapshot
- evidence
- sources
- ratings
- false-positive state
- review state and eval commit

Public snapshot stores only redacted fields listed above.

## Privacy Policy

Private beta notice must say Decorum may store post text, post URL hash, note text, classifier request/response, trace ID, model/provider metadata, sources, threshold, rating label, false-positive state, and review metadata.

Rules:

- No LinkedIn cookies, credentials, session tokens, or private messages.
- Hash LinkedIn post URL and post ID with a server-side salt before writing lookup keys.
- Encrypt raw post text, request JSON, response JSON, and settings snapshot before D1 write.
- Keep raw replay blobs for 30 days by default.
- Keep redacted metadata, ratings, and review rows for 180 days by default.
- Delete raw replay blobs immediately when a tester requests deletion.
- Public rows require maintainer review and tester opt-in when any excerpt of the post text appears.
- Public rows must not identify the LinkedIn post author unless the author identity is already in a cited public source and review marks it necessary.
- Provider request IDs are private unless the provider permits public disclosure.
- Export/delete endpoints must cover local ledger rows and synced D1 rows.

## Sync Flow

1. Extension renders a note and writes the local ledger entry.
2. If remote sync is enabled, background sends the classifier response and local ledger metadata to `POST /v1/ledger`.
3. Worker validates tester token, trace ID, contract version, and quota.
4. Worker hashes post keys, encrypts replay blobs, and writes D1 rows in one batch.
5. Rating updates call `POST /v1/ledger/:traceId/rating`.
6. Negative ratings set `false_positive = 1` and move the trace to the false-positive lane.
7. Maintainer review writes `ledger_reviews`.
8. Public snapshot rows are generated only from reviewed traces.

## References

- Cloudflare D1 data location: https://developers.cloudflare.com/d1/configuration/data-location/
- Cloudflare D1 pricing: https://developers.cloudflare.com/d1/platform/pricing/
- LinkedIn User Agreement: https://www.linkedin.com/legal/user-agreement
- LinkedIn Professional Community Policies: https://www.linkedin.com/legal/professional-community-policies
