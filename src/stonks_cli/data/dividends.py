from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from stonks_cli.data.cache import default_cache_dir, load_cached_text, save_cached_text


@dataclass(frozen=True)
class DividendEvent:
    """Represents a dividend payment event."""

    ex_date: date
    payment_date: date | None
    amount: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "ex_date": self.ex_date.isoformat(),
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "amount": self.amount,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DividendEvent:
        return cls(
            ex_date=date.fromisoformat(data["ex_date"]),
            payment_date=date.fromisoformat(data["payment_date"]) if data.get("payment_date") else None,
            amount=data["amount"],
        )


def fetch_dividend_info(ticker: str) -> dict:
    """Fetch dividend information for a ticker using yfinance.

    Args:
        ticker: Stock ticker

    Returns:
        Dictionary containing:
        - dividend_yield: Annual dividend yield percentage
        - annual_dividend: Annual dividend per share
        - payout_ratio: Payout ratio as percentage
        - ex_dividend_date: Next/last ex-dividend date
        - next_dividend_date: Estimated next dividend date
        - dividend_history: List of last 8 quarters of dividends
    """
    cache_dir = default_cache_dir()
    cache_key = f"dividend_info:{ticker.upper()}"
    ttl_seconds = 24 * 3600  # 24 hours

    cached = load_cached_text(cache_dir, cache_key, ttl_seconds=ttl_seconds)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance required: install stonks-cli[yfinance]")

    base_ticker = ticker.split(".")[0]
    stock = yf.Ticker(base_ticker)

    result: dict[str, Any] = {
        "ticker": base_ticker,
        "dividend_yield": None,
        "annual_dividend": None,
        "payout_ratio": None,
        "ex_dividend_date": None,
        "next_dividend_date": None,
        "dividend_history": [],
    }

    try:
        info = stock.info or {}

        # Dividend yield (as percentage)
        divi_yield = info.get("dividendYield")
        if divi_yield is not None:
            result["dividend_yield"] = float(divi_yield) * 100

        # Annual dividend (trailing)
        annual_div = info.get("dividendRate")
        if annual_div is not None:
            result["annual_dividend"] = float(annual_div)

        # Payout ratio
        payout = info.get("payoutRatio")
        if payout is not None:
            result["payout_ratio"] = float(payout) * 100

        # Ex-dividend date
        ex_date = info.get("exDividendDate")
        if ex_date is not None:
            if isinstance(ex_date, int):
                result["ex_dividend_date"] = datetime.fromtimestamp(ex_date).date().isoformat()
            elif hasattr(ex_date, "isoformat"):
                result["ex_dividend_date"] = ex_date.isoformat()

        # Get dividend history
        try:
            dividends = stock.dividends
            if dividends is not None and not dividends.empty:
                # Get last 8 dividends (approximately 2 years quarterly)
                recent = dividends.tail(8)
                history = []
                for idx, amt in recent.items():
                    try:
                        div_date = idx.date() if hasattr(idx, "date") else idx
                        history.append(
                            {
                                "ex_date": div_date.isoformat(),
                                "payment_date": None,  # Not available from this API
                                "amount": float(amt),
                            }
                        )
                    except Exception:
                        continue
                # Reverse to show most recent first
                history.reverse()
                result["dividend_history"] = history

                # Estimate next dividend date based on pattern
                if len(history) >= 2:
                    try:
                        last_date = date.fromisoformat(history[0]["ex_date"])
                        prev_date = date.fromisoformat(history[1]["ex_date"])
                        days_between = (last_date - prev_date).days
                        if days_between > 0:
                            from datetime import timedelta

                            next_est = last_date + timedelta(days=days_between)
                            if next_est > date.today():
                                result["next_dividend_date"] = next_est.isoformat()
                    except Exception:
                        pass
        except Exception:
            pass

    except Exception:
        pass

    # Cache result
    save_cached_text(cache_dir, cache_key, json.dumps(result))

    return result
