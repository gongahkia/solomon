from __future__ import annotations
import json
from pathlib import Path
import platformdirs
from stonks_cli.alerts.models import Alert

def get_alerts_path() -> Path:
    """Get platform-appropriate path to alerts.json."""
    data_dir = Path(platformdirs.user_data_dir("stonks-cli"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "alerts.json"

def load_alerts() -> list[Alert]:
    """Load alerts from disk."""
    path = get_alerts_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Ensure it's a list
        if not isinstance(data, list):
            return []
        return [Alert.from_dict(d) for d in data]
    except Exception:
        return []

def _save_all_alerts(alerts: list[Alert]) -> None:
    """Internal helper to save list."""
    path = get_alerts_path()
    data = [a.to_dict() for a in alerts]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def save_alert(alert: Alert) -> None:
    """Append or update an alert."""
    alerts = load_alerts()
    # Check if ID exists
    idx = next((i for i, a in enumerate(alerts) if a.id == alert.id), -1)
    if idx >= 0:
        alerts[idx] = alert
    else:
        alerts.append(alert)
    _save_all_alerts(alerts)

def delete_alert(alert_id: str) -> bool:
    """Remove alert by ID. Returns True if found and removed."""
    alerts = load_alerts()
    initial_count = len(alerts)
    alerts = [a for a in alerts if a.id != alert_id]
    if len(alerts) < initial_count:
        _save_all_alerts(alerts)
        return True
    return False
