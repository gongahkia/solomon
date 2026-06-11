# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from solomon.performance import LatencyBudget, assert_recall_budget, measure_latency


def main() -> int:
    measurement = measure_latency(lambda: None)
    if not assert_recall_budget(measurement, LatencyBudget()):
        raise SystemExit(f"latency budget failed: {measurement.model_dump()}")
    print(measurement.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

