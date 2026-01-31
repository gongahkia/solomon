from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed


def detect_unusual_volume(
    tickers: list[str],
    threshold: float = 2.0,
) -> list[dict]:
    """Identify tickers with volume > threshold * 20-day average.
    
    Args:
        tickers: List of ticker symbols to check
        threshold: Multiple of average volume to flag as unusual (default 2.0)
        
    Returns:
        List of dicts with: ticker, current_volume, avg_volume, multiple, price, change_pct
    """
    from stonks_cli.config import load_config
    from stonks_cli.pipeline import provider_for_config
    
    if not tickers:
        return []
    
    cfg = load_config()
    results = []
    
    def _check_ticker(ticker: str):
        try:
            p = provider_for_config(cfg, ticker)
            s = p.fetch_daily(ticker)
            df = s.df
            
            if df.empty or len(df) < 21:
                return None
            
            if "volume" not in df.columns:
                return None
            
            # Current volume and price
            current_vol = df["volume"].iloc[-1]
            current_price = df["close"].iloc[-1]
            
            # Previous close for % change
            prev_price = df["close"].iloc[-2]
            change_pct = ((current_price - prev_price) / prev_price * 100) if prev_price != 0 else 0
            
            # 20-day average volume (excluding today)
            avg_vol = df["volume"].iloc[-21:-1].mean()
            
            if avg_vol <= 0:
                return None
            
            multiple = current_vol / avg_vol
            
            if multiple > threshold:
                return {
                    "ticker": ticker,
                    "current_volume": current_vol,
                    "avg_volume": avg_vol,
                    "multiple": multiple,
                    "price": current_price,
                    "change_pct": change_pct,
                }
        except Exception:
            pass
        return None
    
    max_workers = min(cfg.data.concurrency_limit, max(1, len(tickers)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_check_ticker, t) for t in tickers]
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                results.append(result)
    
    # Sort by multiple descending
    results.sort(key=lambda x: x["multiple"], reverse=True)
    return results
