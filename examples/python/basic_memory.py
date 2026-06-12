# SPDX-License-Identifier: MIT

import tempfile

import shibahama


def main() -> None:
    with tempfile.NamedTemporaryFile() as store:
        engine = shibahama.Shibahama(store.name, 2)
        item = engine.write(
            "Python examples should stay small and runnable.",
            vector=[1.0, 0.0],
            source_kind="user",
            source_ref="examples/python/basic_memory.py",
            ingested_by="python-example",
            valid_from_unix=0,
            ingested_at_unix=0,
        )
        recalled = engine.recall([1.0, 0.0], 1, now_unix=0)

        assert recalled[0].id == item.id
        assert engine.reinforce(item.id, "cited")

        why = engine.why(item.id, now_unix=0)
        assert why is not None

        print(f"recalled: {recalled[0].item.content}")
        print(f"credence: {why.tier_credence}")
        print(f"significance: {why.significance.final_score:.3f}")


if __name__ == "__main__":
    main()
