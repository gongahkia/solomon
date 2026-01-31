from pathlib import Path
import platformdirs

def get_alerts_path() -> Path:
    """Get platform-appropriate path to alerts.json."""
    data_dir = Path(platformdirs.user_data_dir("stonks-cli"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "alerts.json"
