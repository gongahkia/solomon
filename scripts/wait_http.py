# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from typing import Any
from urllib.parse import urlparse


def _coerce_expected(value: str) -> Any:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for a JSON HTTP endpoint to return an expected value.")
    parser.add_argument("url")
    parser.add_argument("--expect-key", required=True)
    parser.add_argument("--expect-value", required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    scheme = urlparse(args.url).scheme
    if scheme not in {"http", "https"}:
        raise SystemExit(f"unsupported URL scheme: {scheme!r}")

    expected = _coerce_expected(args.expect_value)
    deadline = time.time() + args.timeout
    last_error: str | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(args.url, timeout=2.0) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get(args.expect_key) == expected:
                return 0
            last_error = f"unexpected payload: {payload!r}"
        except Exception as exc:  # pragma: no cover - CI timing helper
            last_error = str(exc)
        time.sleep(1.0)
    raise SystemExit(f"{args.url} did not become ready: {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
