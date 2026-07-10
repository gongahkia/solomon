# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse

from solomon.evaluation import write_benchmark_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a synthetic currency benchmark corpus.")
    parser.add_argument("output")
    parser.add_argument("--size", type=int, default=12)
    parser.add_argument("--supersession-events", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    write_benchmark_corpus(
        args.output,
        size=args.size,
        supersession_events=args.supersession_events,
        seed=args.seed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
