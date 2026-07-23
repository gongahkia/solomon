from __future__ import annotations

from dataclasses import dataclass

from rich.table import Table


@dataclass(frozen=True)
class TerminalTable:
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.columns, tuple)
            or not isinstance(self.rows, tuple)
            or any(not isinstance(row, tuple) for row in self.rows)
        ):
            raise ValueError("terminal table shape is invalid")
        title = self.title.strip() if isinstance(self.title, str) else ""
        columns = tuple(
            column.strip() if isinstance(column, str) else "" for column in self.columns
        )
        if not title:
            raise ValueError("terminal table title is required")
        if not columns or any(not column for column in columns):
            raise ValueError("terminal table columns are required")
        if len(set(columns)) != len(columns):
            raise ValueError("terminal table columns must be unique")
        if any(
            len(row) != len(self.columns) or any(not isinstance(value, str) for value in row)
            for row in self.rows
        ):
            raise ValueError("terminal table rows must match columns")
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "columns", columns)


def render_table(contract: TerminalTable) -> Table:
    table = Table(title=contract.title)
    for column in contract.columns:
        table.add_column(column)
    for row in contract.rows:
        table.add_row(*row)
    return table
