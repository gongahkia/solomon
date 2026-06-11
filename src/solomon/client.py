# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

import httpx


class SolomonAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _raise_for_error(response: httpx.Response) -> None:
    if response.is_error:
        raise SolomonAPIError(response.text, status_code=response.status_code)


class SolomonClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8140",
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SolomonClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def ingest(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post("/ingest", json=payload)
        _raise_for_error(response)
        return dict(response.json())

    def recall(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._client.post("/recall", json=payload)
        _raise_for_error(response)
        return list(response.json())

    def why(self, item_id: str) -> dict[str, Any]:
        response = self._client.get(f"/why/{item_id}")
        _raise_for_error(response)
        return dict(response.json())


class AsyncSolomonClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8140",
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncSolomonClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def ingest(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post("/ingest", json=payload)
        _raise_for_error(response)
        return dict(response.json())

    async def recall(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        response = await self._client.post("/recall", json=payload)
        _raise_for_error(response)
        return list(response.json())

    async def why(self, item_id: str) -> dict[str, Any]:
        response = await self._client.get(f"/why/{item_id}")
        _raise_for_error(response)
        return dict(response.json())

