#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Under-minute stale API fact supersession demo."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY_BINDING = ROOT / "bindings" / "python" / "python"
sys.path.insert(0, str(ROOT))
if PY_BINDING.exists():
    sys.path.insert(0, str(PY_BINDING))

from benchmarks.shibahama_bench.embeddings import embed_text

DIMENSIONS = 16
SOURCE_REF = "bindings/python/python/shibahama/__init__.pyi:Shibahama.__init__"
QUERY = "Which Python constructor opens a Shibahama memory store?"
OLD_FACT = "API fact: open the Python memory store with shibahama.Memory(path, dims=16)."
CURRENT_FACT = (
    "API fact: open the Python memory store with "
    "shibahama.Shibahama(path, dimensions, capacity=1024)."
)


class CodingAgent:
    def __init__(self, engine) -> None:
        self.engine = engine

    def answer_constructor(self, now_unix: int) -> dict[str, object]:
        candidates = self.engine.recall(
            embed_text(QUERY, DIMENSIONS),
            3,
            now_unix=now_unix,
            raw_query_context=QUERY,
            include_cold=True,
        )
        context = "\n".join(candidate.item.content for candidate in candidates)
        if "shibahama.Shibahama(path, dimensions, capacity=1024)" in context:
            answer = "Use shibahama.Shibahama(path, dimensions, capacity=1024)."
        elif "shibahama.Memory(path, dims=16)" in context:
            answer = "Use shibahama.Memory(path, dims=16)."
        else:
            answer = "No verified constructor fact recalled."

        return {
            "answer": answer,
            "recalled": [
                {
                    "id": candidate.id,
                    "currency": candidate.currency,
                    "content": candidate.item.content,
                }
                for candidate in candidates
            ],
        }


def main() -> int:
    import shibahama

    with tempfile.NamedTemporaryFile() as store:
        engine = shibahama.Shibahama(store.name, DIMENSIONS)
        stale = engine.write(
            OLD_FACT,
            vector=embed_text(OLD_FACT, DIMENSIONS),
            source_kind="file",
            source_ref=SOURCE_REF,
            ingested_by="demo:old-docs",
            valid_from_unix=0,
            ingested_at_unix=0,
        )
        agent = CodingAgent(engine)
        before = agent.answer_constructor(now_unix=10)

        challenge = engine.challenge(
            stale.id,
            reason="local binding stub shows this constructor no longer exists",
            actor="demo:reviewer",
            timestamp_unix=55,
        )
        assert engine.invalidate(stale.id, valid_to_unix=60)
        current = engine.write(
            CURRENT_FACT,
            vector=embed_text(CURRENT_FACT, DIMENSIONS),
            source_kind="file",
            source_ref=SOURCE_REF,
            ingested_by="demo:verified-docs",
            valid_from_unix=60,
            ingested_at_unix=60,
        )
        after = agent.answer_constructor(now_unix=90)
        stale_why = engine.why(stale.id, now_unix=90)
        current_why = engine.why(current.id, now_unix=90)
        events = engine.event_records()["events"]

    assert stale_why is not None
    assert current_why is not None
    assert "shibahama.Memory" in str(before["answer"])
    assert "shibahama.Shibahama" in str(after["answer"])
    assert stale_why.currency_state == "invalidated"
    assert current_why.currency_state == "current"
    assert all(row["id"] != stale.id for row in after["recalled"])
    assert challenge["applied"]

    summary = {
        "before_governance": before,
        "governance": {
            "superseded_id": stale.id,
            "current_id": current.id,
            "challenge_reason": challenge["signal"]["reason"],
            "valid_to_unix": stale_why.valid_to_unix,
            "current_valid_from_unix": current_why.valid_from_unix,
            "current_credence": current_why.tier_credence,
        },
        "after_governance": after,
        "event_kinds": [event["kind"] for event in events],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
