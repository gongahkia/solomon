from __future__ import annotations

ACTION_COLORS = {
    "BUY_DCA": "green",
    "HOLD_DCA": "green",
    "HOLD": "yellow",
    "HOLD_WAIT": "yellow",
    "WATCH_REVERSAL": "yellow",
    "AVOID_OR_HEDGE": "red",
    "REDUCE_EXPOSURE": "red",
    "NO_DATA": "red",
    "INSUFFICIENT_HISTORY": "yellow",
}


def format_quick_summary(
    ticker: str,
    price: float | None,
    change_pct: float | None,
    action: str,
    confidence: float,
    use_color: bool = True,
) -> str:
    """Format a one-liner summary for quick command output.

    Args:
        ticker: The ticker symbol (e.g., AAPL.US)
        price: Current price or None if unavailable
        change_pct: Daily change percentage or None
        action: Strategy action (e.g., BUY_DCA, HOLD)
        confidence: Confidence score (0.0 to 1.0)
        use_color: Whether to include Rich markup for colors

    Returns:
        Formatted one-liner string
    """
    # Format price
    price_str = f"${price:.2f}" if price is not None else "N/A"

    # Format change percentage
    if change_pct is not None:
        sign = "+" if change_pct >= 0 else ""
        if use_color:
            color = "green" if change_pct >= 0 else "red"
            change_str = f"[{color}]({sign}{change_pct:.2f}%)[/{color}]"
        else:
            change_str = f"({sign}{change_pct:.2f}%)"
    else:
        change_str = "(N/A)"

    # Format action
    if use_color:
        color = ACTION_COLORS.get(action, "white")
        action_str = f"[{color}]{action}[/{color}]"
    else:
        action_str = action

    return f"{ticker} {price_str} {change_str} {action_str} [confidence: {confidence:.2f}]"
