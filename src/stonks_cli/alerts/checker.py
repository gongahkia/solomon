from __future__ import annotations
import pandas as pd
from stonks_cli.alerts.models import Alert

def check_alert(alert: Alert, df: pd.DataFrame) -> bool:
    """Evaluate alert condition against dataframe."""
    if df.empty:
        return False
        
    # Latest close
    current_price = df["close"].iloc[-1]
    
    if alert.condition_type == "price_above":
        return current_price > alert.threshold
    elif alert.condition_type == "price_below":
        return current_price < alert.threshold
        
    # RSI calculation if needed
    if "rsi" in alert.condition_type:
        # Simple 14-period RSI calculation
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        
        if alert.condition_type == "rsi_above":
            return current_rsi > alert.threshold
        elif alert.condition_type == "rsi_below":
            return current_rsi < alert.threshold
    
    # SMA cross detection (golden_cross / death_cross)
    if alert.condition_type in ("golden_cross", "death_cross"):
        # Need at least 201 days of data for 200-day SMA
        if len(df) < 201:
            return False
            
        # Calculate SMAs
        sma_50 = df["close"].rolling(window=50).mean()
        sma_200 = df["close"].rolling(window=200).mean()
        
        # Get current and previous day values
        curr_fast = sma_50.iloc[-1]
        curr_slow = sma_200.iloc[-1]
        prev_fast = sma_50.iloc[-2]
        prev_slow = sma_200.iloc[-2]
        
        if alert.condition_type == "golden_cross":
            # Fast SMA crossed above slow SMA
            # Previous: fast <= slow, Current: fast > slow
            return prev_fast <= prev_slow and curr_fast > curr_slow
        elif alert.condition_type == "death_cross":
            # Fast SMA crossed below slow SMA
            # Previous: fast >= slow, Current: fast < slow
            return prev_fast >= prev_slow and curr_fast < curr_slow
    
    # Volume spike detection
    if alert.condition_type == "volume_spike":
        if "volume" not in df.columns:
            return False
        if len(df) < 21:
            return False
            
        # Compute 20-day average volume (excluding today)
        vol_20_avg = df["volume"].iloc[-21:-1].mean()
        if vol_20_avg <= 0:
            return False
            
        current_volume = df["volume"].iloc[-1]
        multiplier = alert.threshold if alert.threshold > 0 else 2.0
        
        return current_volume > vol_20_avg * multiplier
    
    # Earnings soon detection
    if alert.condition_type == "earnings_soon":
        from datetime import date, timedelta
        from stonks_cli.data.earnings import fetch_ticker_earnings_history
        
        try:
            history = fetch_ticker_earnings_history(alert.ticker, quarters=4)
            if not history:
                return False
            
            today = date.today()
            days_threshold = int(alert.threshold) if alert.threshold > 0 else 7
            
            # Find next upcoming earnings date
            upcoming = [e for e in history if e.report_date >= today]
            if not upcoming:
                return False
            
            next_earnings = min(upcoming, key=lambda e: e.report_date)
            days_until = (next_earnings.report_date - today).days
            
            return days_until <= days_threshold
        except Exception:
            return False
            
    return False


def check_all_alerts() -> list[tuple[Alert, bool]]:
    """Check all enabled alerts."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from stonks_cli.alerts.storage import load_alerts
    from stonks_cli.config import load_config
    from stonks_cli.pipeline import provider_for_config
    
    alerts = [a for a in load_alerts() if a.enabled]
    if not alerts:
        return []
        
    # Group by ticker to minimize fetches
    tickers = list(set(a.ticker for a in alerts))
    data: dict[str, pd.DataFrame] = {}
    cfg = load_config()
    
    def _fetch(t: str):
        try:
            p = provider_for_config(cfg, t)
            # Fetch enough history for RSI (at least 15 days, say 30)
            # Provider fetch_daily usually fetches max or substantial history
            # We assume it fetches efficiently
            s = p.fetch_daily(t)
            return t, s.df
        except Exception:
            return t, pd.DataFrame()
            
    max_workers = min(cfg.data.concurrency_limit, max(1, len(tickers)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fetch, t) for t in tickers]
        for fut in as_completed(futures):
            t, df = fut.result()
            if not df.empty:
                data[t] = df
                
    results = []
    for alert in alerts:
        df = data.get(alert.ticker)
        triggered = False
        if df is not None and not df.empty:
            try:
                triggered = check_alert(alert, df)
            except Exception:
                pass
        results.append((alert, triggered))
        
    return results
