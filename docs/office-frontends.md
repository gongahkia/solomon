<!-- SPDX-License-Identifier: Apache-2.0 -->

# Optional Office Front-Ends

Solomon does not require Office add-ins at runtime. An optional front-end can still mirror the boundary
review-before-send pattern:

- A Word taskpane collects selected text and sends it to Solomon `/ingest`; Solomon's vendored boundary reviews
  it before storage.
- An Outlook taskpane can call Solomon `/recall` with reviewed text and must not bypass Solomon's model-egress
  boundary.

Keep the flow two-step:

1. The add-in sends text to Solomon.
2. Solomon calls the vendored boundary before storage or model egress.
3. For server SKU deployments, the add-in must send `Authorization: Bearer <tenant-key>` or `x-api-key` plus
   `x-tenant-id` to Solomon. Tenants are registered in Solomon's tenant registry and can be
   suspended/reactivated by an admin before their isolated data and journal namespace is used.

## Word Taskpane

Use a Word taskpane selection/body collection against Solomon, for example `http://127.0.0.1:8140`, and call:

```http
POST /ingest
Content-Type: application/json

{
  "kind": "note",
  "content": "<selected text>",
  "source_kind": "matter-doc",
  "source_ref": "word-selection"
}
```

## Outlook Taskpane And Pre-Send

Use an Outlook surface for pre-send review and recall. Solomon reviews/sanitizes in-process. A common workflow is:

```http
POST /recall
Content-Type: application/json

{
  "query": "<reviewed email body or selected issue>",
  "review_mode": true,
  "max_context_tokens": 1200
}
```

## Deployment Notes

- Production deployment should still use Microsoft 365 admin-managed deployment for the add-in manifests.
- Solomon-specific tenant credentials and headers belong in the add-in configuration store. Prefer scoped
  tenant keys created through `/tenants`; the server admin key should remain in deployment automation.
- Do not persist pseudonymization mappings in the add-in or in Solomon.
- Keep the default local flow loopback-only: Solomon on `127.0.0.1:8140`.
