# Python SDK quickstart

The Python client targets the FastAPI service.

## Start the API

```bash
uv run uvicorn solomon.api.app:create_app --factory --host 127.0.0.1 --port 8140
```

## Use the sync client

```python
from solomon.client import SolomonClient

with SolomonClient("http://127.0.0.1:8140") as solomon:
    item = solomon.ingest(
        {
            "content": "Structure X relies on Regulation R section 12.",
            "kind": "position",
            "source_kind": "partner",
            "source_ref": "memo-1",
            "matter_id": "matter-a",
            "client_id": "client-a",
        }
    )

    current = solomon.recall(
        {
            "query": "structure X regulation",
            "matter_id": "matter-a",
            "client_id": "client-a",
        }
    )
    why = solomon.why(item["id"])

print(current)
print(why["currency"])
```

## Use the async client

```python
import asyncio

from solomon.client import AsyncSolomonClient


async def main() -> None:
    async with AsyncSolomonClient("http://127.0.0.1:8140") as solomon:
        results = await solomon.recall({"query": "structure X regulation"})
        print(results)


asyncio.run(main())
```

## Error handling

```python
from solomon.client import SolomonAPIError, SolomonClient

try:
    with SolomonClient("http://127.0.0.1:8140") as solomon:
        solomon.why("missing-item")
except SolomonAPIError as exc:
    print(exc.status_code)
```

Use the CLI or MCP server for curator workflows that need verification decisions, audit-pack export, or preflight prompt context.
