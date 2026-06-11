"""Deterministic benchmark embeddings.

The harness intentionally uses a local embedding function by default so CI and
portfolio demos do not depend on a hosted model. External adapters may ignore
these vectors if their backend owns embedding.
"""

from __future__ import annotations

from hashlib import blake2b
from math import sqrt


def embed_text(text: str, dimensions: int = 16) -> list[float]:
    """Return a deterministic unit-length vector for text."""

    values = [0.0] * dimensions

    for token in text.lower().split():
        digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = -1.0 if digest[4] & 1 else 1.0
        values[bucket] += sign

    magnitude = sqrt(sum(value * value for value in values))

    if magnitude == 0:
        return values

    return [value / magnitude for value in values]
