# Classifier Gateway Contract

The extension must not contain Anthropic, Exa, Tavily, Perplexity, or other paid API keys. Remote classification goes through a gateway controlled by Decorum.

## Endpoint

`POST /v1/classify-post`

Headers:

- `Authorization: Bearer <decorum user/session token>`
- `Content-Type: application/json`

Body:

- The exact `decorum.classifier.v1` request shape validated by `extension/src/shared/classifier-contract.js`.
- Example: `tests/contracts/classifier-request.json`.

Response:

- The exact `decorum.classifier.v1` response shape validated by `extension/src/shared/classifier-contract.js`.
- Example: `tests/contracts/classifier-response.json`.

## Anthropic Adapter Boundary

The gateway may call Anthropic's Messages API with:

- `POST /v1/messages`
- `anthropic-version: 2023-06-01`
- a current Haiku model for first-pass classification
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

## Replay Requirements

Every shown note must preserve enough data to replay the decision:

- original classifier request, including full post text
- classifier response
- contract/rubric/safety-copy versions
- model/provider metadata
- threshold used for the decision
- trace ID and response ID
- rating, if supplied later

## Failure Policy

If the gateway is unavailable, invalid, or returns a malformed response, the extension should render no note. Empty is better than noisy.

## References

- Anthropic Messages API: https://platform.claude.com/docs/en/api/messages
- Anthropic prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
