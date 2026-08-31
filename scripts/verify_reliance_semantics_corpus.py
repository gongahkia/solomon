#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate the locked reliance-semantics corpus without running extraction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from solomon.reliance_semantics_corpus import corpus_summary, load_reliance_semantics_corpus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("examples/scenarios/conservative-reliance-semantics-proof/corpus/manifest.json"),
    )
    arguments = parser.parse_args()
    corpus = load_reliance_semantics_corpus(arguments.corpus)
    print(
        json.dumps(
            {
                "schema": corpus["schema"],
                "version": corpus["version"],
                "manifest_sha256": corpus["manifest_sha256"],
                "summary": corpus_summary(corpus),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
