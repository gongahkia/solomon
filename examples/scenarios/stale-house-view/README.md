<!-- SPDX-License-Identifier: Apache-2.0 -->

# Stale House-View Scenario

This runnable example demonstrates Solomon's wedge:

1. A 2023 house-view memo depends on Regulation R section 12 and is tied to a Client A matter.
2. A 2025 regulatory change is registered.
3. Solomon propagates `StalePendingReverification` to the memo.
4. A warehouse-style similarity baseline still returns the memo as if it were current.
5. The Solomon boundary proves the model-facing prompt did not contain the client identity.

Run:

```bash
uv run python examples/scenarios/stale-house-view/run.py
```
