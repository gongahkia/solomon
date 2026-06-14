# Curator console stack

Decision date: 2026-06-14

## Decision

Use FastAPI + Jinja2 templates + HTMX + plain CSS.

## Why

The console is exactly three operational screens:

- Verification Desk.
- Dependency Review.
- Audit Pack export.

It is not a product SPA. It needs forms, filtered tables, small partial updates, and server-owned mutations against the existing `SolomonService`.

FastAPI is already the API server. FastAPI documents native Jinja2 template rendering through `Jinja2Templates`, so the console can live in the same Python process as the API, store, audit journal, and boundary policy.

HTMX covers incremental HTML updates through normal server endpoints. Its docs define `hx-get`, `hx-post`, swaps, and boosted links/forms, which match the console workflow without introducing a separate front-end build.

Sources:

- https://fastapi.tiangolo.com/advanced/templates/
- https://htmx.org/docs/
- https://htmx.org/attributes/hx-post/

## Rejected options

### SvelteKit

Pros:

- Good UI ergonomics.
- Adapter ecosystem for deployment.

Cons:

- Requires Node toolchain and a front-end build.
- Adds a second server boundary or API client layer.
- More state machinery than the three-screen curator scope needs.

Source: https://svelte.dev/docs/kit/adapter-node

### Next.js

Pros:

- Strong full-stack React ecosystem.
- Server Actions can handle form mutations.

Cons:

- Requires Node/React stack and build/deploy path.
- Duplicates routing/auth/service boundaries already present in FastAPI.
- Larger dependency and security surface for a portfolio infrastructure demo.

Sources:

- https://nextjs.org/docs/app
- https://nextjs.org/docs/app/getting-started/mutating-data

## Implementation shape

Target module layout:

```text
src/solomon/console/
  app.py
  routes.py
  templates/
    base.html
    verification.html
    dependency.html
    audit_pack.html
    partials/
  static/
    console.css
```

CLI target:

```bash
solomon console serve --host 127.0.0.1 --port 8150
```

Server rules:

- Same `Settings` and `SolomonService` construction as API/MCP.
- Dev-mode bearer token only for portfolio scope.
- Mutations use existing service verbs; no duplicated business logic in templates.
- Responses are server-rendered HTML, with HTMX partials for row actions and filters.
- Static assets are local; no CDN dependency.

Test rules:

- Route tests use FastAPI `TestClient`.
- Snapshot only stable partials if needed.
- No browser test required until screenshots/GIF tasks.

## Risks

- HTMX partial contracts can get messy if screen count grows past the three committed views.
- Jinja templates need disciplined component partials to avoid large HTML files.
- Graph visualization may need a small client-side library later; keep it isolated to Dependency Review.

## Revisit trigger

Reconsider SvelteKit if the console grows beyond the three screens, needs offline editing, complex graph interaction, or a public multi-user product UI.
