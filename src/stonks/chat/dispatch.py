from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from stonks.commands import (
    do_analyze,
    do_backtest,
    do_config_init,
    do_config_set,
    do_config_show,
    do_config_where,
    do_data_fetch,
    do_data_verify,
    do_doctor,
    do_ollama_check,
    do_report_open,
    do_schedule_once,
    do_schedule_start_background,
    do_schedule_status,
    do_version,
)


PanelCallback = Callable[[str, str], None]


@dataclass
class ChatState:
    messages: list
    scheduler: object | None = None


def handle_slash_command(
    cmdline: str,
    *,
    state: ChatState,
    show_panel: PanelCallback,
    out_dir: Path = Path("reports"),
) -> bool:
    """Handle /commands. Returns True if handled.

    This function is intentionally side-effectful (it calls into `stonks.commands`).
    It's extracted so it can be tested without running the interactive prompt loop.
    """

    parts = cmdline.strip().split()
    if not parts:
        return True
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in {"/exit", "/quit"}:
        if state.scheduler is not None:
            try:
                stop = getattr(state.scheduler, "stop", None)
                if callable(stop):
                    stop()
            except Exception:
                pass
        show_panel("exit", "Bye.")
        raise EOFError

    if cmd == "/help":
        show_panel(
            "help",
            "Commands:\n"
            "  /help\n"
            "  /exit\n"
            "  /version\n"
            "  /config where\n"
            "  /config show\n"
            "  /config init [path]\n"
            "  /config set FIELD_PATH JSON_VALUE\n"
            "  /data fetch [TICKER1 TICKER2 ...]\n"
            "  /analyze TICKER1 TICKER2 ...\n"
            "  /backtest [TICKER1 TICKER2 ...]\n"
            "  /report\n"
            "  /export [path]\n"
            "  /doctor\n"
            "  /schedule status\n"
            "  /schedule once [--out-dir DIR]\n"
            "  /schedule run [--out-dir DIR]    (runs in background)\n",
        )
        return True

    if cmd == "/llm":
        if not args:
            show_panel("llm", "Usage: /llm check")
            return True
        sub = args[0].lower()
        if sub == "check":
            show_panel("llm check", do_ollama_check())
            return True
        show_panel("llm", f"Unknown subcommand: {sub}")
        return True

    if cmd == "/doctor":
        results = do_doctor()
        body = "\n".join([f"{k}: {v}" for k, v in results.items()])
        show_panel("doctor", body)
        return True

    if cmd == "/version":
        show_panel("version", do_version())
        return True

    if cmd == "/config":
        if not args:
            show_panel("config", "Usage: /config where|show|init [path]")
            return True
        sub = args[0].lower()
        rest = args[1:]
        if sub == "where":
            show_panel("config where", str(do_config_where()))
            return True
        if sub == "show":
            show_panel("config show", do_config_show())
            return True
        if sub == "init":
            p = Path(rest[0]).expanduser() if rest else None
            out = do_config_init(p)
            show_panel("config init", f"Created config: {out}")
            return True
        if sub == "set":
            if len(rest) < 2:
                show_panel("config set", "Usage: /config set FIELD_PATH JSON_VALUE")
                return True
            field_path = rest[0]
            raw = " ".join(rest[1:])
            try:
                value = json.loads(raw)
            except Exception:
                value = raw
            try:
                new_cfg = do_config_set(field_path, value)
                show_panel("config set", new_cfg)
            except Exception as e:
                show_panel("config set", f"Error: {e}")
            return True
        show_panel("config", f"Unknown subcommand: {sub}")
        return True

    if cmd == "/analyze":
        if not args:
            show_panel("analyze", "Usage: /analyze TICKER1 TICKER2 ...")
            return True
        report = do_analyze(args, out_dir=out_dir)
        show_panel("analyze", f"Wrote report: {report}")
        return True

    if cmd == "/backtest":
        path = do_backtest(args if args else None, start=None, end=None, out_dir=out_dir)
        show_panel("backtest", f"Wrote backtest: {path}")
        return True

    if cmd == "/report":
        try:
            p = do_report_open()
            txt = Path(p).read_text(encoding="utf-8")
            limit = 8000
            if len(txt) > limit:
                body = f"path: {p}\n\n(truncated to last {limit} chars)\n\n" + txt[-limit:]
            else:
                body = f"path: {p}\n\n" + txt
            show_panel("report", body)
        except Exception as e:
            show_panel("report", f"Error: {e}")
        return True

    if cmd == "/data":
        if not args:
            show_panel("data", "Usage: /data fetch|verify [TICKER1 TICKER2 ...]")
            return True
        sub = args[0].lower()
        rest = args[1:]
        if sub == "fetch":
            fetched = do_data_fetch(rest if rest else None)
            show_panel("data fetch", f"Fetched {len(fetched)} tickers")
            return True
        if sub == "verify":
            results = do_data_verify(rest if rest else None)
            body = "\n".join([f"{t}: {s}" for t, s in results.items()])
            show_panel("data verify", body)
            return True
        show_panel("data", f"Unknown subcommand: {sub}")
        return True

    if cmd == "/schedule":
        if not args:
            show_panel("schedule", "Usage: /schedule status|once|run")
            return True
        sub = args[0].lower()
        if sub == "status":
            st = do_schedule_status()
            body = f"cron: {st.cron}\n"
            body += f"next: {st.next_run}\n" if st.next_run else f"next: unavailable ({st.error})\n"
            show_panel("schedule status", body)
            return True
        if sub == "once":
            report = do_schedule_once(out_dir=out_dir)
            show_panel("schedule once", f"Wrote report: {report}")
            return True
        if sub == "run":
            if state.scheduler is None:
                state.scheduler = do_schedule_start_background(out_dir=out_dir)
                show_panel("schedule run", "Scheduler started in background.")
            else:
                show_panel("schedule run", "Scheduler already running.")
            return True
        show_panel("schedule", f"Unknown subcommand: {sub}")
        return True

    show_panel("unknown", f"Unknown command: {cmd}")
    return True
