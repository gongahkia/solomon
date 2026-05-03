from __future__ import annotations

from typing import Any

import requests

JUPITER_PRICE_URL = "https://api.jup.ag/price/v3"


def fetch_jupiter_prices(ids: list[str], *, api_key: str | None = None, timeout_s: float = 10.0) -> dict[str, Any]:
    cleaned = [i.strip() for i in ids if i and i.strip()]
    if not cleaned:
        return {}
    headers = {"x-api-key": api_key} if api_key else None
    resp = requests.get(JUPITER_PRICE_URL, params={"ids": ",".join(cleaned)}, headers=headers, timeout=timeout_s)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}
