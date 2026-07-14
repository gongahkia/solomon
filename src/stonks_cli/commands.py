from __future__ import annotations

from pathlib import Path

from stonks_cli import __version__
from stonks_cli.config import (
    config_path,
    load_config,
    migrate_config_file,
    redacted_config_json,
    save_config,
    save_default_config,
    update_config_field,
)


def do_version() -> str:
    return __version__


def do_doctor() -> dict[str, str]:
    cfg = load_config()
    out: dict[str, str] = {}
    try:
        out["config_path"] = str(config_path())
        out["config_loaded"] = "ok"
    except Exception as e:
        out["config_loaded"] = f"error: {e}"
    try:
        from stonks_cli.paths import default_cache_dir, default_state_dir
        out["cache_dir"] = str(default_cache_dir())
        out["state_dir"] = str(default_state_dir())
    except Exception as e:
        out["paths"] = f"error: {e}"
    try: # whalemirror guard check
        from stonks_cli.whalemirror.guards import evaluate_execution_guards
        from stonks_cli.whalemirror.models import MirrorMode, Venue
        paper_guards = evaluate_execution_guards(venue=Venue.HYPERLIQUID, mode=MirrorMode.PAPER)
        live_guards = evaluate_execution_guards(venue=Venue.HYPERLIQUID, mode=MirrorMode.LIVE)
        out["whalemirror_paper_guards"] = "clear" if not paper_guards else "; ".join(paper_guards)
        out["whalemirror_live_guards"] = "clear" if not live_guards else "; ".join(live_guards)
    except Exception as e:
        out["whalemirror_guards"] = f"error: {e}"
    try: # plugin load status
        from stonks_cli.plugins import load_plugins_best_effort
        specs = tuple(cfg.plugins or [])
        if not specs:
            out["plugins"] = "skipped (none configured)"
        else:
            summary = load_plugins_best_effort(specs)
            out["plugins_ok"] = str(len(summary.ok))
            out["plugins_errors"] = str(len(summary.errors))
            if summary.errors:
                out["plugins_error_detail"] = "; ".join(f"{k}: {v}" for k, v in summary.errors.items())
    except Exception as e:
        out["plugins"] = f"error: {e}"
    issues: list[str] = []
    if out.get("config_loaded", "").startswith("error:"):
        issues.append("Configuration could not be loaded.")
    score = max(0, 100 - (15 * len(issues)))
    out["health_score"] = str(score)
    if issues:
        out["next_steps"] = " | ".join(issues)
    else:
        out["next_steps"] = "No blocking issues detected."
    return out


def do_config_where() -> Path:
    return config_path()


def do_config_init(path: Path | None) -> Path:
    return save_default_config(path)


def do_config_migrate(path: Path | None) -> Path:
    return migrate_config_file(path)


def do_config_show() -> str:
    cfg = load_config()
    return redacted_config_json(cfg, indent=2)


def do_config_set(field_path: str, value) -> str:
    cfg = load_config()
    updated = update_config_field(cfg, field_path, value)
    save_config(updated)
    return redacted_config_json(updated, indent=2)


def do_config_validate() -> dict[str, object]:
    cfg = load_config()
    return {
        "schema_version": cfg.schema_version,
        "tickers": list(cfg.tickers or []),
        "strategy": cfg.strategy,
        "vnext_enabled": cfg.vnext.enabled,
        "vnext_execution_mode": cfg.vnext.operator.execution_mode,
        "vnext_broker_read_only": cfg.vnext.moomoo.read_only,
    }
