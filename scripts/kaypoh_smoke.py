# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from pathlib import Path

from solomon.boundary.kaypoh import load_kaypoh_client_class


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Solomon's Kaypoh client import and HTTP contract.")
    parser.add_argument("--kaypoh-repo", default="../kaypoh")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    client_class = load_kaypoh_client_class(Path(args.kaypoh_repo))
    with client_class(base_url=args.base_url) as client:
        ready = client.ready()
        if not getattr(ready, "ready", False):
            raise RuntimeError(f"Kaypoh is not ready: {ready!r}")
        review = client.review(
            text="Public test memo for Solomon Kaypoh smoke.",
            source_jurisdiction="SG",
            destination_jurisdiction="SG",
            document_type="memo",
            review_profile="strict",
        )
        if not hasattr(review, "classification"):
            raise RuntimeError("Kaypoh review response did not include classification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
