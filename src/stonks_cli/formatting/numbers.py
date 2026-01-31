from __future__ import annotations


def format_market_cap(value: float | None) -> str:
    """Format large numbers with suffixes (T, B, M, K).

    Args:
        value: Number to format

    Returns:
        Formatted string like "1.2T", "845B", "12.3M"
    """
    if value is None:
        return "N/A"

    abs_value = abs(value)
    sign = "-" if value < 0 else ""

    if abs_value >= 1e12:
        return f"{sign}{abs_value / 1e12:.1f}T"
    elif abs_value >= 1e9:
        return f"{sign}{abs_value / 1e9:.1f}B"
    elif abs_value >= 1e6:
        return f"{sign}{abs_value / 1e6:.1f}M"
    elif abs_value >= 1e3:
        return f"{sign}{abs_value / 1e3:.1f}K"
    else:
        return f"{sign}{abs_value:.0f}"


def format_percent(value: float | None, decimal_places: int = 2) -> str:
    """Format a decimal as percentage.

    Args:
        value: Decimal value (0.15 = 15%)
        decimal_places: Number of decimal places

    Returns:
        Formatted string like "15.00%"
    """
    if value is None:
        return "N/A"
    return f"{value * 100:.{decimal_places}f}%"


def format_ratio(value: float | None, decimal_places: int = 2) -> str:
    """Format a ratio value.

    Args:
        value: Ratio value
        decimal_places: Number of decimal places

    Returns:
        Formatted string like "15.30"
    """
    if value is None:
        return "N/A"
    return f"{value:.{decimal_places}f}"
