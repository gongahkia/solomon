# Audit Pack wireframe

Status: console screen 3 of 3

## Purpose

Let a lawyer select one knowledge item and export a compact evidence pack showing provenance, dependencies, verification history, boundary metadata, and audit hash-chain status.

## Primary route

`GET /console/audit-pack`

## Layout

```text
+----------------------------------------------------------------------------------+
| Solomon / Audit Pack                         [item id search____________] [load] |
+------------------------------------+---------------------------------------------+
| Item summary                       | Evidence tabs                                |
|                                    |                                             |
| item id                            | [provenance] [dependencies] [verification]   |
| kind                               | [boundary] [hash chain] [raw manifest]       |
| matter / client                    |                                             |
| currency state                     | Provenance                                   |
| credence tier                      | source kind, source ref, author, dates       |
| source ref                         |                                             |
|                                    | Dependency tree                              |
| [export JSON] [export PDF]         | upstream, downstream, stale reasons          |
| [verify pack]                      |                                             |
|                                    | Verification history                         |
| Pack status                        | verified_by, last_verified_at, contests      |
| manifest hash ok                   |                                             |
| journal hash ok                    | Boundary metadata                            |
| journal chain ok                   | classification, findings, quarantine state   |
+------------------------------------+---------------------------------------------+
```

## Data sources

Item summary:

- `why(item_id)` for item, currency, dependencies, dependents, provenance, credence, and verification state.

Pack export:

- `export_audit_pack(destination)` for a directory containing `manifest.json` and `journal.jsonl`.
- MCP `audit_pack` shape for in-process JSON return.

Journal validation:

- `AuditJournal.verify()`.
- `AuditJournal.verify_pack(pack_dir)`.

## Item picker

Inputs:

- item id.
- optional matter id filter.
- optional client id filter.

Search behavior:

- exact id load first.
- if no exact id, run `recall(query, review_mode=True, limit=10)` and show candidates.
- stale, superseded, retired, and contested items must be selectable.

## Evidence tabs

### Provenance

Show:

- source kind.
- source ref.
- author.
- matter id.
- item created / valid dates.
- source-derived credence.

### Dependencies

Show:

- upstream edges this item relies on.
- downstream dependents relying on this item.
- edge type.
- confidence.
- created by.
- valid_from / valid_to.
- staleness reasons.

### Verification

Show:

- current verified state.
- last verified at.
- verified by.
- successor id.
- contest history.
- pin metadata.
- verification attestation status if present.

### Boundary

Show:

- boundary review classification.
- boundary findings metadata.
- quarantine status.
- sanitized-context metadata when present.

Do not show volatile mapping tables or raw reidentification maps.

### Hash chain

Show:

- manifest schema.
- manifest hash check.
- journal file hash check.
- journal chain verification status.
- journal entry count.
- latest entry hash.

## Export actions

### JSON

First implementation:

- call `export_audit_pack(temp_dir)`.
- return downloadable `manifest.json` and `journal.jsonl` as a zip or render `manifest_json` inline.

### PDF

First implementation:

- allowed to return "not implemented" until PDF export exists.
- keep the button disabled if the server has no PDF renderer.

Future implementation:

- render the selected item summary and evidence tabs to print CSS.
- save as PDF from server-side renderer.

## HTMX behavior

- `GET /console/audit-pack/search?q=...` returns candidate rows.
- `GET /console/audit-pack/items/{item_id}` returns item summary + first tab.
- `GET /console/audit-pack/items/{item_id}/tab/{tab}` returns one evidence tab.
- `POST /console/audit-pack/items/{item_id}/export?format=json` returns export status/download partial.
- `POST /console/audit-pack/verify` verifies an uploaded or generated pack.

## Empty and error states

- missing item: show "No item found" and keep search box focused.
- pack verification failed: show manifest hash, journal hash, and chain status separately.
- scope denied: show non-sensitive denial.
- no dependencies: show "No dependencies recorded".
- no boundary metadata: show "No boundary review metadata recorded".

## Acceptance checks

- Can load a live item by id.
- Can load a stale/superseded/retired item by id.
- Provenance tab never renders raw boundary mapping tables.
- Dependency tab shows upstream and downstream edges.
- Hash-chain tab exposes journal verification status and latest entry hash.
- JSON export contains `manifest.json` and `journal.jsonl`.
- PDF control is disabled until real PDF generation lands.
