from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
RETIRED_SOURCE_DIRECTORIES = (
    "src/stonks_cli/carry",
    "src/stonks_cli/research",
    "src/stonks_cli/vnext",
)
RETIRED_IDENTIFIERS = ("carry", "polymarket", "hyperliquid", "vnext")


def test_retired_product_sources_and_identifiers_are_absent() -> None:
    for directory in RETIRED_SOURCE_DIRECTORIES:
        assert not (ROOT / directory).exists()
    for source in (ROOT / "src").rglob("*.py"):
        content = source.read_text().lower()
        for identifier in RETIRED_IDENTIFIERS:
            assert identifier not in content, source
