<!-- SPDX-License-Identifier: Apache-2.0 -->

# VellumRelay vendor-integration scenario

VellumRelay is a fictional MCP host. A public web search on 2026-07-12 found no exact result for the name; this is
not trademark clearance.

The scenario compares two paths after Regulation R section 12 changes:

- **Without Solomon:** the host confidently reuses a stale firm view.
- **With Solomon:** the host calls `preflight_context` before drafting. The stale view is absent from injected
  context, then `check_currency` supplies a review message naming the moved dependency and date.

The “LLM” is deterministic mock output. The scenario proves context selection and currency handling; it does not
test a vendor product or a hosted model.

Run it headlessly:

```bash
uv run python examples/scenarios/01-vendor-integration/run.py
```

Render the animated comparison:

```bash
uv run python scripts/render_vendor_integration_gif.py
```

Watch the [MP4 replay](../../../docs/assets/scenarios/vendor-integration/comparison.mp4) with
[WebVTT captions](../../../docs/assets/scenarios/vendor-integration/comparison.vtt) and a
[static frame](../../../docs/assets/scenarios/vendor-integration/comparison.png).

Expected invariants:

- the preflight call returns one current item before the authority change and no item after it;
- the MCP currency state is `stale_pending` (the service's stale-pending-reverification state);
- the mock draft receives no stale firm text; and
- the audit chain verifies.
