# Dependency Review wireframe

Status: console screen 2 of 3

## Purpose

Let a curator inspect proposed and confirmed dependency edges, accept or reject suggestions, and see which internal items rely on an external authority.

## Primary route

`GET /console/dependencies`

## Layout

```text
+----------------------------------------------------------------------------------+
| Solomon / Dependency Review               [authority filter] [depth 1 v] [refresh]|
+-----------------------------------+----------------------------------------------+
| Suggestions queue                 | Graph view                                    |
|                                   |                                              |
| [pending] [confirmed] [rejected] [deferred] | item-1 ---> regulation-r-section-12       |
| item id     authority       src   |      |                                       |
| item-1      Reg R s12       det   |      +---> dependent-1                        |
| item-4      MAS Notice 626  llm   |                                              |
|                                   | Selected edge                                 |
| [accept] [reject]                 | source item, target authority, confidence     |
| reviewer [________________]       | reason, parser, created_at, decided_by        |
|                                   |                                              |
| Confirmed dependencies            | Affected items                                |
| item id     target          by    | item-1, dependent-1                           |
+-----------------------------------+----------------------------------------------+
```

## Data sources

Suggestions:

- `dependency_suggestions(item_id=None, decision=pending|confirmed|rejected|deferred, limit=...)`
- `confirm_dependency_suggestion(suggestion_id, by=reviewer_id)`
- `reject_dependency_suggestion(suggestion_id, by=reviewer_id)`

Graph:

- `why(item_id)` for dependencies and dependents.
- `dependency_graph(output_format="json", matter_id=..., client_id=...)` when broader graph data is needed.
- `impact_query(authority_id)` to show affected items before an authority actually changes.

## Filters

- decision: pending, confirmed, rejected, deferred.
- source: deterministic, llm.
- target kind: external authority, knowledge item.
- external authority id.
- matter id.
- client id.
- depth: 1, 2, 3.

Depth controls graph traversal only. Accept/reject actions operate on the selected suggestion id, not all visible edges.

## Suggestion row fields

- suggestion id.
- item id.
- authority ref.
- target id.
- source.
- decision.
- confidence.
- created at.
- decided by.
- edge reason.
- source-document version, source span, authority span, normalized reference, and extraction explanation.

## Graph view

First version can render a simple SVG/HTML edge list, not a physics graph.

Requirements:

- confirmed edges and pending suggestions are visually distinct.
- selected item stays highlighted after accept/reject.
- stale or superseded source items show a muted state.
- graph depth cannot exceed the configured control.
- graph text uses ids/refs only; no raw confidential item content in node labels.

## Actions

### Accept suggestion

Service call:

`confirm_dependency_suggestion(suggestion_id, DependencySuggestionDecisionRequest(by=reviewer_id))`

Effect:

- creates a `DependencyEdge`.
- suggestion decision becomes `confirmed`.
- edge confidence becomes `human_confirmed`.
- audit journal records `dependency_suggestion_confirmed`.

### Reject suggestion

Service call:

`reject_dependency_suggestion(suggestion_id, DependencySuggestionDecisionRequest(by=reviewer_id))`

Effect:

- suggestion decision becomes `rejected`.
- no dependency edge is created.
- audit journal records `dependency_suggestion_rejected`.

### Defer suggestion

Service call:

`defer_dependency_suggestion(suggestion_id, DependencySuggestionDecisionRequest(by=reviewer_id, reason=...))`

Effect:

- suggestion decision becomes `deferred` with actor, time, and reason.
- no dependency edge is created; a later curator may confirm or reject it.
- audit journal records `dependency_suggestion_deferred`.

## HTMX behavior

- `GET /console/dependencies/suggestions?...` returns queue partial.
- `GET /console/dependencies/graph?item_id=...&depth=...` returns graph partial.
- `POST /console/dependencies/suggestions/{id}/confirm` returns updated queue row + graph refresh.
- `POST /console/dependencies/suggestions/{id}/reject` returns updated queue row + graph refresh.
- `GET /console/dependencies/impact?authority_id=...` returns affected-items partial.

## Empty states

- no pending suggestions: show confirmed/rejected tabs and a link to ingest a sample item.
- no graph edges: show selected item metadata and "No dependencies recorded".
- invalid reviewer: keep selected row and show field-level error.

## Acceptance checks

- Pending suggestions from ingest appear in queue.
- Accept creates a confirmed edge visible in graph.
- Reject removes suggestion from pending queue but keeps review history.
- Authority filter shows only matching target ids.
- Depth 1 excludes transitive dependents; depth 2 includes one transitive hop.
- Raw item content does not appear in graph node labels.
