from __future__ import annotations


SECTOR_ETFS: dict[str, str] = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Energy": "XLE",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def identify_sector(ticker: str) -> str | None:
    """Identify the sector of a ticker using yfinance.

    Args:
        ticker: The stock ticker symbol.

    Returns:
        The sector name if found, None otherwise.
    """
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info
        return info.get("sector")
    except Exception:
        return None
