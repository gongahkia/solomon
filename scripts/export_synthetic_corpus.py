# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse

from solomon.evaluation import write_synthetic_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Solomon's deterministic synthetic evaluation corpus.")
    parser.add_argument("--size", type=int, default=10, help="Number of synthetic knowledge items.")
    parser.add_argument(
        "--output",
        default="docs/evaluation-corpus.synthetic.json",
        help="Destination JSON path.",
    )
    args = parser.parse_args()
    if args.size < 1:
        parser.error("--size must be >= 1")
    write_synthetic_corpus(args.output, size=args.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
