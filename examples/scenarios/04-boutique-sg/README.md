<!-- SPDX-License-Identifier: Apache-2.0 -->

# Kite & Quoin LLP boutique Singapore scenario

Kite & Quoin LLP is fictional. A web search on 2026-07-12 found no exact Singapore law-firm result; this is not
trademark clearance. The scenario uses real authority names only as anchors and uses a fictional amendment event.

The seed models an eight-lawyer Singapore boutique with one PSL, 50 working memos, five authority anchors, and eight
dependency edges. A fictional PDPA anchor change stales the four privacy-linked memos while the remaining library stays
current.

```bash
uv run python examples/scenarios/04-boutique-sg/run.py
```

Expected invariants:

- 50 memos and five authority anchors load;
- eight sparse dependency edges load;
- four privacy memos become `StalePendingReverification`; and
- the audit journal verifies.

The Compose console walkthrough and recording remain open work.
