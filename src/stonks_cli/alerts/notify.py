from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
import platformdirs
from rich.console import Console
from stonks_cli.alerts.models import Alert

def notify_terminal_bell(alert: Alert) -> None:
    """Print alert and ring bell."""
    console = Console()
    msg = f"ALERT TRIGGERED: {alert.ticker} {alert.condition_type.replace('_', ' ')} {alert.threshold}"
    console.print(f"\n[bold white on red]{msg}[/bold white on red]\n")
    print("\a") 

def get_alerts_log_path() -> Path:
    data_dir = Path(platformdirs.user_data_dir("stonks-cli"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "alerts_log.jsonl"

def log_alert_trigger(alert: Alert) -> None:
    """Log triggered alert."""
    path = get_alerts_log_path()
    entry = alert.to_dict()
    entry["log_timestamp"] = datetime.now().isoformat()
    
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def notify_webhook(alert: Alert, webhook_url: str) -> bool:
    """Send webhook notification."""
    try:
        import requests
        payload = alert.to_dict()
        payload["message"] = f"Alert: {alert.ticker} {alert.condition_type} {alert.threshold}"
        requests.post(webhook_url, json=payload, timeout=5)
        return True
    except Exception:
        return False
