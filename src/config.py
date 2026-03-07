import json
import os
import copy

CONFIG_PATH = os.path.expanduser("~/.config/senko/config.json")
DEFAULT_CONFIG = {
    "srs": {
        "initial_ease": 2.5,
        "minimum_ease": 1.3,
        "easy_bonus": 1.3,
        "hard_factor": 0.8
    },
    "tui": {
        "show_stats": True,
        "confirm_delete": True
    }
}

def _deep_merge(base:dict, override:dict) -> dict:
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result

def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r") as f:
            user_config = json.load(f)
        return _deep_merge(DEFAULT_CONFIG, user_config)
    except (IOError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)

def save_config(config:dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

def reset_config() -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    save_config(config)
    return config
