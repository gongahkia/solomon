<!-- SPDX-License-Identifier: Apache-2.0 -->

# Meridian Banyan LLP Big Law Singapore scenario

Meridian Banyan LLP is fictional. A web search on 2026-07-12 found no exact Singapore law-firm result; this is not
trademark clearance. The scenario uses real authority names only as anchors, not legal advice or statements about those
authorities' current requirements.

The YAML seed contains 30 fictional internal items across corporate, banking, and employment, plus eight external
authority anchors. Seven banking memos depend on the `MAS Notice 626` anchor. A fictional authority amendment stales
all seven dependencies and preserves audit evidence.

Run headlessly:

```bash
uv run python examples/scenarios/02-biglaw-sg/run.py
```

Expected invariants:

- 30 internal items and eight authority anchors load;
- the seven `MAS Notice 626` dependent memos transition to `StalePendingReverification`; and
- the audit journal verifies.

This harness supplies deterministic seed and cascade evidence for the partner-console walkthrough.

Run the partner walkthrough through the console's decision routes:

```bash
uv run python examples/scenarios/02-biglaw-sg/run.py --console-walkthrough
```

It has Partner Tan reaffirm three positions, supersede two with recorded successors, and retire two. The expected
post-review states are three `Live`, two `Superseded`, and two `Retired`; the audit journal must verify.

The [browser walkthrough replay](../../../docs/assets/scenarios/biglaw-sg/partner-walkthrough.mp4) captures the
actual local console states; [WebVTT captions](../../../docs/assets/scenarios/biglaw-sg/partner-walkthrough.vtt) and
[source frames](../../../docs/assets/scenarios/biglaw-sg/) accompany it.
