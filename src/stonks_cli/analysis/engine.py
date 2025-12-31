from __future__ import annotations

from typing import Protocol

import pandas as pd

from stonks_cli.analysis.strategy import Recommendation


class Strategy(Protocol):
    name: str

    def recommend(self, df: pd.DataFrame) -> Recommendation:
        ...
