#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate the locked adversarial dependency corpus without running extraction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from solomon.adversarial_corpus import corpus_summary, load_adversarial_dependency_corpus, materialize_mutations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("examples/scenarios/adversarial-dependency-generalization-proof/corpus/manifest.json"),
    )
    arguments = parser.parse_args()
    corpus = load_adversarial_dependency_corpus(arguments.corpus)
    variants = materialize_mutations(corpus)
    print(
        json.dumps(
            {
                "schema": corpus["schema"],
                "version": corpus["version"],
                "manifest_sha256": corpus["manifest_sha256"],
                "summary": corpus_summary(corpus),
                "mutation_ids": [variant["id"] for variant in variants],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
