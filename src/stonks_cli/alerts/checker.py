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
