<!-- SPDX-License-Identifier: Apache-2.0 -->

# Internal Supersession Scenario

This scenario demonstrates that Solomon does not rely on age or similarity alone. A 2022 internal position is
quietly superseded by a 2024 position on the same topic and jurisdiction.

Run:

```bash
uv run python examples/internal-supersession/run.py
```

Expected behavior:

- Solomon proposes a human-confirmed supersession.
- Default recall returns the 2024 position only.
- Review-mode recall can still show the 2022 position, marked `Superseded`, with its successor id.
