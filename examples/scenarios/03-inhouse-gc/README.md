<!-- SPDX-License-Identifier: Apache-2.0 -->

# Lantern Circuit in-house GC scenario

Lantern Circuit Pte. Ltd. is fictional. A web search on 2026-07-12 found no exact result; this is not trademark
clearance. The scenario uses a fictional amendment event and does not state current PDPA requirements.

Twelve fictional NDA clauses depend on a `PDPA 2012 section 26` anchor alongside handbook, policy, and template
content. After the fictional amendment, all twelve clauses become `StalePendingReverification`. A deterministic
Copilot-like assistant calls MCP `preflight_context` and receives no stale NDA context.

```bash
uv run python examples/scenarios/03-inhouse-gc/run.py
```

The [browser workflow replay](../../../docs/assets/scenarios/inhouse-gc/stale-nda-workflow.mp4) shows the twelve-item
review queue; [WebVTT captions](../../../docs/assets/scenarios/inhouse-gc/stale-nda-workflow.vtt) accompany it. This
scenario remains the headless evidence for the ripple and MCP path.
