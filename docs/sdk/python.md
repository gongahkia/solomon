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

## Governed dependency assertions

Both `SolomonClient` and `AsyncSolomonClient` provide matching HTTP methods:

- `create_dependency_assertion(payload)`
- `dependency_assertion(assertion_id, params=...)`
- `dependency_assertions(params=...)`
- `decide_dependency_assertion(assertion_id, payload)`
- `withdraw_dependency_assertion(assertion_id, payload)`
- `dependency_assertion_history(assertion_id, params=...)`

Create payloads must bind a registered source document version to the source knowledge item and use either exact quote
evidence (`quote`, `quote_start`, `quote_end`) or commentary evidence (`commentary`) exclusively. Decisions and
withdrawals can carry `expected_state_version` to reject stale state transitions. Scope parameters use `matter_id`
and `client_id`; callers outside the record scope receive the service's non-disclosing not-found/denial response.

The HTTP client exposes the curator lifecycle. The MCP server is deliberately read-only and only exposes governed
assertion provenance through `solomon.dependency_suggestions`.
