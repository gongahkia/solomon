from __future__ import annotations

# Unicode block characters for sparkline visualization (8 levels)
SPARK_CHARS = "▁▂▃▄▅▆▇█"


def generate_sparkline(prices: list[float], width: int = 20) -> str:
    """Generate a sparkline string from a list of prices.

    Args:
        prices: List of price values
        width: Maximum width of the sparkline (will use last N values)

    Returns:
        Unicode sparkline string using block characters
    """
    if not prices:
        return ""

    # Take the last `width` prices
    values = prices[-width:]

    if len(values) == 0:
        return ""

    min_val = min(values)
    max_val = max(values)

    # Handle case where all values are the same
    if max_val == min_val:
        mid_char = SPARK_CHARS[len(SPARK_CHARS) // 2]
        return mid_char * len(values)

    # Map each value to a character level (0-7)
    range_val = max_val - min_val
    result = []
    for v in values:
        # Normalize to 0-1, then scale to 0-7
        normalized = (v - min_val) / range_val
        level = int(normalized * (len(SPARK_CHARS) - 1))
        level = max(0, min(level, len(SPARK_CHARS) - 1))
        result.append(SPARK_CHARS[level])

    return "".join(result)
