<!-- SPDX-License-Identifier: Apache-2.0 -->

# Optional Office Front-Ends

Solomon does not fork or edit Kaypoh's Office add-ins. The optional front-end path is a thin Solomon
adapter around the sibling Kaypoh surfaces:

- `../kaypoh/packaging/word_addin/` is the Word taskpane review surface.
- `../kaypoh/packaging/office_addin/` is the Outlook taskpane plus pre-send Smart Alerts surface.

Those clients already know how to collect selected Word text or Outlook body text and send it to the local
Kaypoh daemon. Solomon reuses that boundary by keeping the flow two-step:

1. The add-in sends text to Kaypoh `/review` or `/redact` exactly as Kaypoh already defines it.
2. Only reviewed or redacted text is passed to Solomon through `/ingest`, `/recall`, `/why/{item_id}`, or `/graph`.
3. For server SKU deployments, the add-in must send `x-api-key` and `x-tenant-id` to Solomon; every tenant gets a
   separate Solomon data and journal namespace.

## Word Taskpane

Use Kaypoh's `word_addin/taskpane.js` selection/body collection unchanged. Add a second configured endpoint for
Solomon, for example `http://127.0.0.1:8140`, and call:

```http
POST /ingest
Content-Type: application/json

{
  "kind": "note",
  "content": "<kaypoh-reviewed text>",
  "source_kind": "matter-doc",
  "source_ref": "word-selection"
}
```

## Outlook Taskpane And Pre-Send

Use Kaypoh's `office_addin/` Outlook surface for pre-send boundary review. Solomon should only be called after
the Kaypoh taskpane has completed review or redaction. A common workflow is:

```http
POST /recall
Content-Type: application/json

{
  "query": "<kaypoh-reviewed email body or selected issue>",
  "review_mode": true,
  "max_context_tokens": 1200
}
```

## Deployment Notes

- Production deployment should still use Microsoft 365 admin-managed deployment for the add-in manifests.
- Solomon-specific tenant headers belong in the add-in configuration store, next to Kaypoh's endpoint/token fields.
- Do not persist Kaypoh pseudonymization mappings in the add-in or in Solomon.
- Keep the default local flow loopback-only: Kaypoh on `127.0.0.1:8765`, Solomon on `127.0.0.1:8140`.
