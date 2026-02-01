from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from stonks_cli.data.cache import default_cache_dir, load_cached_text, save_cached_text


@dataclass(frozen=True)
class EarningsEvent:
    """Represents an earnings event."""

    ticker: str
    company_name: str
    report_date: date
    report_time: str  # before_market, after_market, unknown
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None
    revenue_actual: float | None = None
    surprise_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "report_date": self.report_date.isoformat(),
            "report_time": self.report_time,
            "eps_estimate": self.eps_estimate,
            "eps_actual": self.eps_actual,
            "revenue_estimate": self.revenue_estimate,
            "revenue_actual": self.revenue_actual,
            "surprise_pct": self.surprise_pct,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EarningsEvent:
        """Create from dictionary."""
        return cls(
            ticker=data["ticker"],
            company_name=data["company_name"],
            report_date=date.fromisoformat(data["report_date"]),
            report_time=data["report_time"],
            eps_estimate=data.get("eps_estimate"),
            eps_actual=data.get("eps_actual"),
            revenue_estimate=data.get("revenue_estimate"),
            revenue_actual=data.get("revenue_actual"),
            surprise_pct=data.get("surprise_pct"),
        )


def fetch_ticker_earnings_history(ticker: str, quarters: int = 8) -> list[EarningsEvent]:
    """Fetch historical earnings data for a ticker using yfinance.

    Args:
        ticker: Stock ticker
        quarters: Number of quarters to fetch

    Returns:
        List of EarningsEvent objects
    """
    cache_dir = default_cache_dir()
    cache_key = f"earnings_history:{ticker.upper()}"
    ttl_seconds = 24 * 3600  # 24 hours

    cached = load_cached_text(cache_dir, cache_key, ttl_seconds=ttl_seconds)
    if cached:
        try:
            data = json.loads(cached)
            return [EarningsEvent.from_dict(e) for e in data]
        except Exception:
            pass

    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance required: install stonks-cli[yfinance]")

    base_ticker = ticker.split(".")[0]
    stock = yf.Ticker(base_ticker)

    events: list[EarningsEvent] = []

    try:
        # Get earnings dates
        earnings_dates = stock.earnings_dates
        if earnings_dates is None or earnings_dates.empty:
            return []

        # Get company name
        info = stock.info or {}
        company_name = info.get("shortName", base_ticker)

        for idx, row in earnings_dates.head(quarters).iterrows():
            try:
                # Parse the datetime index
                report_date = idx.date() if hasattr(idx, "date") else date.today()

                # Determine report time from hour
                report_time = "unknown"
                if hasattr(idx, "hour"):
                    if idx.hour < 10:
                        report_time = "before_market"
                    elif idx.hour > 16:
                        report_time = "after_market"

                eps_estimate = None
                eps_actual = None
                surprise_pct = None

                if "EPS Estimate" in row.index:
                    eps_estimate = float(row["EPS Estimate"]) if row["EPS Estimate"] == row["EPS Estimate"] else None
                if "Reported EPS" in row.index:
                    eps_actual = float(row["Reported EPS"]) if row["Reported EPS"] == row["Reported EPS"] else None
                if "Surprise(%)" in row.index:
                    surprise_pct = float(row["Surprise(%)"]) if row["Surprise(%)"] == row["Surprise(%)"] else None

                events.append(
                    EarningsEvent(
                        ticker=base_ticker,
                        company_name=company_name,
                        report_date=report_date,
                        report_time=report_time,
                        eps_estimate=eps_estimate,
                        eps_actual=eps_actual,
                        surprise_pct=surprise_pct,
                    )
                )
            except Exception:
                continue

    except Exception:
        pass

    # Sort by date descending
    events.sort(key=lambda e: e.report_date, reverse=True)

    # Cache results
    save_cached_text(cache_dir, cache_key, json.dumps([e.to_dict() for e in events]))

    return events


def calculate_earnings_reaction(
    ticker: str,
    earnings_date: date,
    df,  # pd.DataFrame
) -> dict[str, float | None]:
    """Calculate price reaction to earnings.

    Args:
        ticker: Stock ticker
        earnings_date: Date of earnings report
        df: DataFrame with price data

    Returns:
        Dictionary with same_day_change_pct and next_day_change_pct
    """
    if df.empty or "close" not in df.columns:
        return {"same_day_change_pct": None, "next_day_change_pct": None}

    try:
        # Find the earnings date in the data
        dates = df.index.tolist()
        date_strs = [str(d.date()) if hasattr(d, "date") else str(d) for d in dates]

        earnings_str = earnings_date.isoformat()
        if earnings_str not in date_strs:
            return {"same_day_change_pct": None, "next_day_change_pct": None}

        idx = date_strs.index(earnings_str)

        # Get closes
        closes = df["close"].tolist()

        # Same day change (vs previous day)
        same_day_pct = None
        if idx > 0:
            prev_close = closes[idx - 1]
            if prev_close != 0:
                same_day_pct = ((closes[idx] - prev_close) / prev_close) * 100

        # Next day change (vs earnings day)
        next_day_pct = None
        if idx < len(closes) - 1:
            earnings_close = closes[idx]
            if earnings_close != 0:
                next_day_pct = ((closes[idx + 1] - earnings_close) / earnings_close) * 100

        return {
            "same_day_change_pct": same_day_pct,
            "next_day_change_pct": next_day_pct,
        }
    except Exception:
        return {"same_day_change_pct": None, "next_day_change_pct": None}


def compute_earnings_implied_move(ticker: str) -> float | None:
    """Calculate average absolute post-earnings move from historical data.

    Args:
        ticker: Stock ticker

    Returns:
        Average absolute percentage move or None
    """
    history = fetch_ticker_earnings_history(ticker, quarters=8)
    if not history:
        return None

    moves: list[float] = []
    for event in history:
        if event.surprise_pct is not None:
            moves.append(abs(event.surprise_pct))

    if not moves:
        return None

    return sum(moves) / len(moves)
