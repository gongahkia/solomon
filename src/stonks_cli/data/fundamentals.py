from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from stonks_cli.data.cache import default_cache_dir, load_cached_text, save_cached_text


@dataclass(frozen=True)
class Fundamentals:
    """Fundamental metrics for a stock."""

    pe_ratio: float | None = None
    forward_pe: float | None = None
    peg_ratio: float | None = None
    price_to_book: float | None = None
    market_cap: float | None = None
    enterprise_value: float | None = None
    profit_margin: float | None = None
    revenue_growth_yoy: float | None = None
    earnings_growth_yoy: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pe_ratio": self.pe_ratio,
            "forward_pe": self.forward_pe,
            "peg_ratio": self.peg_ratio,
            "price_to_book": self.price_to_book,
            "market_cap": self.market_cap,
            "enterprise_value": self.enterprise_value,
            "profit_margin": self.profit_margin,
            "revenue_growth_yoy": self.revenue_growth_yoy,
            "earnings_growth_yoy": self.earnings_growth_yoy,
            "dividend_yield": self.dividend_yield,
            "beta": self.beta,
            "fifty_two_week_high": self.fifty_two_week_high,
            "fifty_two_week_low": self.fifty_two_week_low,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fundamentals:
        """Create from dictionary."""
        return cls(
            pe_ratio=data.get("pe_ratio"),
            forward_pe=data.get("forward_pe"),
            peg_ratio=data.get("peg_ratio"),
            price_to_book=data.get("price_to_book"),
            market_cap=data.get("market_cap"),
            enterprise_value=data.get("enterprise_value"),
            profit_margin=data.get("profit_margin"),
            revenue_growth_yoy=data.get("revenue_growth_yoy"),
            earnings_growth_yoy=data.get("earnings_growth_yoy"),
            dividend_yield=data.get("dividend_yield"),
            beta=data.get("beta"),
            fifty_two_week_high=data.get("fifty_two_week_high"),
            fifty_two_week_low=data.get("fifty_two_week_low"),
        )


def _safe_float(val: Any) -> float | None:
    """Safely convert value to float, return None if invalid."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None


def fetch_fundamentals_yahoo(ticker: str) -> Fundamentals | None:
    """Fetch fundamental data using yfinance.

    Args:
        ticker: Stock ticker (e.g., AAPL)

    Returns:
        Fundamentals dataclass or None if unavailable
    """
    # Check cache first (24-hour TTL)
    cache_dir = default_cache_dir()
    cache_key = f"fundamentals:{ticker.upper()}"
    ttl_seconds = 24 * 3600  # 24 hours

    cached = load_cached_text(cache_dir, cache_key, ttl_seconds=ttl_seconds)
    if cached:
        try:
            data = json.loads(cached)
            return Fundamentals.from_dict(data)
        except Exception:
            pass

    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance required: install stonks-cli[yfinance]")

    # Extract base ticker (remove .US suffix if present)
    base_ticker = ticker.split(".")[0]
    stock = yf.Ticker(base_ticker)

    try:
        info = stock.info
    except Exception:
        return None

    if not info:
        return None

    fundamentals = Fundamentals(
        pe_ratio=_safe_float(info.get("trailingPE")),
        forward_pe=_safe_float(info.get("forwardPE")),
        peg_ratio=_safe_float(info.get("pegRatio")),
        price_to_book=_safe_float(info.get("priceToBook")),
        market_cap=_safe_float(info.get("marketCap")),
        enterprise_value=_safe_float(info.get("enterpriseValue")),
        profit_margin=_safe_float(info.get("profitMargins")),
        revenue_growth_yoy=_safe_float(info.get("revenueGrowth")),
        earnings_growth_yoy=_safe_float(info.get("earningsGrowth")),
        dividend_yield=_safe_float(info.get("dividendYield")),
        beta=_safe_float(info.get("beta")),
        fifty_two_week_high=_safe_float(info.get("fiftyTwoWeekHigh")),
        fifty_two_week_low=_safe_float(info.get("fiftyTwoWeekLow")),
    )

    # Cache the result
    save_cached_text(cache_dir, cache_key, json.dumps(fundamentals.to_dict()))

    return fundamentals
