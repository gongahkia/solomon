# Classifier Gateway Contract

The extension must not contain Anthropic, Exa, Tavily, Perplexity, or other paid API keys. Remote classification goes through a gateway controlled by Decorum.

## Chosen Architecture

Use a Cloudflare Worker as the public REST gateway and Cloudflare D1 as the session, audit, quota, and replay database. Keep the existing REST shape; do not put provider calls directly in the MV3 extension.

The Worker owns:

- request authentication and authorization
- contract validation
- rate limits and per-tester quotas
- Anthropic classifier calls
- future retrieval-provider calls
- replay/audit writes
- redaction before logs and client responses

D1 owns:

- tester/install records
- hashed refresh tokens
- revoked session IDs
- quota counters
- classifier request/response replay rows
- rating and false-positive state once shared ledger sync exists

[Inference] This shape keeps the client small while allowing provider keys, provider-specific retries, quota changes, and audit storage to change without shipping a new extension build.

## Endpoint

`POST /v1/classify-post`

Headers:

- `Authorization: Bearer <decorum access token>`
- `Content-Type: application/json`

Body:

- The exact `decorum.classifier.v1` request shape validated by `extension/src/shared/classifier-contract.js`.
- Example: `tests/contracts/classifier-request.json`.

Response:

- The exact `decorum.classifier.v1` response shape validated by `extension/src/shared/classifier-contract.js`.
- Example: `tests/contracts/classifier-response.json`.

## Session and Auth Handling

Private beta auth uses Decorum-issued tokens, not LinkedIn cookies, LinkedIn credentials, Chrome profile identity, or provider API keys.

1. A tester receives an invite code out of band.
2. The extension exchanges the invite code with `POST /v1/session` after explicit tester action.
3. The Worker stores the tester/install record in D1, stores only a hash of the refresh token, and returns:
   - short-lived access token
   - opaque refresh token
   - expiry timestamp
4. The extension stores Decorum tokens in `chrome.storage.local`.
5. `POST /v1/classify-post` accepts only the access token.
6. `POST /v1/session/refresh` rotates the refresh token and returns a new short-lived access token.
7. The Worker rejects expired, revoked, malformed, wrong-scope, or over-quota tokens with `401`, `403`, or `429`.

Access token requirements:

- signed by the gateway
- scoped to `classify:post`
- includes tester/install subject, token ID, issued-at, expiry, and schema version
- expires quickly enough that revocation exposure is bounded
- never contains LinkedIn post text or provider secrets

Refresh token requirements:

- opaque random value
- stored in D1 only as a hash
- rotated on each refresh
- revocable per tester/install
- never sent to provider APIs

The Worker should also restrict CORS/extension access to configured Decorum extension IDs for beta builds. This is not the primary security boundary; bearer-token validation is.

## Anthropic Adapter Boundary

The gateway may call Anthropic's Messages API with:

- `POST /v1/messages`
- `anthropic-version: 2023-06-01`
- `claude-haiku-4-5` for first-pass classification
- `claude-sonnet-5` only for borderline tonal decisions
- `max_tokens` sized for compact JSON output
- prompt caching on the stable rubric/schema prompt

The stable prompt prefix should include:

- classifier contract version
- tonal rubric version
- safety-copy version
- allowed note kinds
- exact JSON output schema
- false-positive avoidance examples

The per-request prompt should include only:

- post ID
- author text if available
- post text
- detected URL
- threshold/settings snapshot

The gateway implementation keeps this provider policy in `gateway/src/anthropic-tonal-classifier.js`. Confidence values within `0.06` of the configured threshold are treated as borderline and may be sent to Sonnet for a second pass. Non-borderline posts stay on Haiku.

## Key Isolation

Provider credentials are Worker secrets. Required secret names:

- `ANTHROPIC_API_KEY`
- `DECORUM_TOKEN_SIGNING_KEY`
- retrieval-provider keys only after retrieval is enabled

Do not store provider credentials in:

- `extension/manifest.json`
- bundled extension JavaScript
- `chrome.storage`
- request payloads from the extension
- classifier responses
- D1 replay rows
- logs or analytics events

Gateway responses may include provider and model names for replay, but never raw secret values, authorization headers, or provider request headers.

## Replay Requirements

Every shown note must preserve enough data to replay the decision:

- original classifier request, including full post text
- classifier response
- contract/rubric/safety-copy versions
- model/provider metadata
- threshold used for the decision
- trace ID and response ID
- rating, if supplied later

Server replay rows should also include:

- tester/install subject
- access-token ID
- gateway version
- provider latency
- provider request ID when available
- quota decision
- redaction/logging version

## Failure Policy

If the gateway is unavailable, invalid, or returns a malformed response, the extension should render no note. Empty is better than noisy.

## References

- Cloudflare Workers: https://developers.cloudflare.com/workers/
- Cloudflare D1: https://developers.cloudflare.com/d1/
- Cloudflare Workers secrets: https://developers.cloudflare.com/workers/configuration/secrets/
- Anthropic Messages API: https://platform.claude.com/docs/en/api/messages
- Anthropic prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
