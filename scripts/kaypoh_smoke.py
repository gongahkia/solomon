# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse

from solomon.boundary.kaypoh import load_kaypoh_client_class


def main() -> int:
    argparse.ArgumentParser(description="Smoke-test Solomon's vendored boundary client contract.").parse_args()

    client_class = load_kaypoh_client_class()
    with client_class() as client:
        ready = client.ready()
        if not getattr(ready, "ready", False):
            raise RuntimeError(f"Vendored boundary is not ready: {ready!r}")
        review = client.review(
            text="Public test memo for Solomon Kaypoh smoke.",
            source_jurisdiction="SG",
            destination_jurisdiction="SG",
            document_type="memo",
            review_profile="strict",
        )
        if not hasattr(review, "classification"):
            raise RuntimeError("Vendored boundary review response did not include classification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
