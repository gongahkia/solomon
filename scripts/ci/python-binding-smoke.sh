#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

python -m venv "$tmpdir/venv"
export VIRTUAL_ENV="$tmpdir/venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

python -m pip install --disable-pip-version-check --quiet --upgrade pip
python -m pip install --disable-pip-version-check --quiet maturin==1.13.3

(
  cd bindings/python
  python -m maturin develop --quiet
)

python - <<'PY'
import asyncio
import sys
import tempfile
import types
from pathlib import Path

import shibahama

assert shibahama.version() == shibahama.__version__
assert shibahama.version()
assert (Path("bindings/python/python/shibahama/__init__.pyi")).is_file()
assert (Path("bindings/python/python/shibahama/py.typed")).is_file()

with tempfile.NamedTemporaryFile() as db:
    engine = shibahama.Shibahama(db.name, 2)
    item = engine.write(
        "Python binding memory",
        vector=[0.0, 0.0],
        source_kind="user",
        source_ref="smoke",
        valid_from_unix=0,
        ingested_at_unix=0,
    )
    engine.write(
        "Python binding overflow memory",
        vector=[10.0, 10.0],
        source_kind="user",
        source_ref="smoke-overflow",
        valid_from_unix=0,
        ingested_at_unix=0,
    )
    recalled = engine.recall([0.0, 0.0], 1, now_unix=0)
    budgeted = engine.recall([0.0, 0.0], 2, now_unix=0, max_context_tokens=3)
    streamed = engine.stream_recall([0.0, 0.0], 1, now_unix=0)
    timeline = engine.timeline([0.0, 0.0], 1, as_of_unix=0)
    why = engine.why(item.id, now_unix=0)

    assert item.content == "Python binding memory"
    assert recalled[0].id == item.id
    assert [candidate.id for candidate in budgeted] == [item.id]
    assert next(streamed).id == item.id
    assert timeline[0].id == item.id
    assert engine.reinforce(item.id, "cited")
    assert why is not None
    assert why.item.id == item.id

    records = engine.export_records()
    items = engine.memory_items()

    assert records and records[0]["id"]
    assert items and items[0].id
    assert any(record["content"] == "Python binding memory" for record in records)

    class FakeDataFrame:
        @staticmethod
        def from_records(records):
            return ("pandas", list(records))

    sys.modules["pandas"] = types.SimpleNamespace(DataFrame=FakeDataFrame)
    pandas_result = engine.to_pandas()
    assert pandas_result[0] == "pandas"
    assert pandas_result[1][0]["content"]

    class FakeTable:
        @staticmethod
        def from_pylist(records):
            return ("arrow", list(records))

    sys.modules["pyarrow"] = types.SimpleNamespace(Table=FakeTable)
    arrow_result = engine.to_arrow()
    assert arrow_result[0] == "arrow"
    assert arrow_result[1][0]["content"]
    sys.modules.pop("pandas", None)
    sys.modules.pop("pyarrow", None)

    async def check_async_api() -> None:
        async_item = await engine.async_write(
            "Python async memory",
            vector=[1.0, 1.0],
            source_kind="user",
            valid_from_unix=0,
            ingested_at_unix=0,
        )
        async_recalled = await engine.async_recall([1.0, 1.0], 3, now_unix=0)
        async_timeline = await engine.async_timeline([1.0, 1.0], 3, as_of_unix=0)
        async_streamed = [
            candidate async for candidate in engine.async_stream_recall([1.0, 1.0], 3, now_unix=0)
        ]
        async_why = await engine.async_why(async_item.id, now_unix=0)

        assert any(candidate.id == async_item.id for candidate in async_recalled)
        assert any(candidate.id == async_item.id for candidate in async_timeline)
        assert any(candidate.id == async_item.id for candidate in async_streamed)
        assert await engine.async_reinforce(async_item.id, "cited")
        assert async_why is not None
        assert async_why.item.id == async_item.id

    asyncio.run(check_async_api())

    def embed(text: str) -> list[float]:
        return [float("adapters" in text), float("async" in text)]

    memory = shibahama.LangChainMemory(engine, embed=embed, top_k=3)
    memory.save_context({"input": "remember adapters"}, {"output": "stored"})
    loaded = memory.load_memory_variables({"input": "adapters"})
    assert memory.memory_variables == ["history"]
    assert "Human: remember adapters" in loaded["history"]

    async def check_langchain_async() -> None:
        await memory.asave_context({"input": "async adapters"}, {"output": "stored"})
        async_loaded = await memory.aload_memory_variables({"input": "async"})
        await memory.aclear()

        assert "async adapters" in async_loaded["history"]

    asyncio.run(check_langchain_async())

print("python binding lane passed")
PY
