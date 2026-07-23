from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from stonks_cli.terminal_table import TerminalTable, render_table


def test_terminal_table_renders_ordered_string_rows() -> None:
    contract = TerminalTable(
        "Portfolio: personal",
        ("Metric", "Value"),
        (("Events", "1"), ("Cash balances", "2")),
    )
    output = StringIO()

    Console(file=output, width=80, color_system=None).print(render_table(contract))

    rendered = output.getvalue()
    assert "Portfolio: personal" in rendered
    assert "Metric" in rendered
    assert "Cash balances" in rendered


def test_terminal_table_contract_rejects_invalid_shape() -> None:
    with pytest.raises(ValueError, match="shape"):
        TerminalTable("Portfolio", ["Metric"], ())
    with pytest.raises(ValueError, match="columns"):
        TerminalTable("Portfolio", ("Metric", " Metric"), ())
    with pytest.raises(ValueError, match="rows"):
        TerminalTable("Portfolio", ("Metric", "Value"), (("Events",),))
