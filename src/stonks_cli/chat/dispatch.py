from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from stonks_cli.commands import (
    do_analyze,
    do_backtest,
    do_config_init,
    do_config_set,
    do_config_show,
    do_config_where,
    do_data_fetch,
    do_data_verify,
    do_doctor,
    do_llm_check,
    do_report_open,
    do_schedule_once,
    do_schedule_start_background,
    do_schedule_status,
    do_version,
)

from stonks_cli.chat.history import clear_chat_history, load_chat_history
from stonks_cli.chat.history import append_chat_message
from stonks_cli.llm.backends import ChatMessage


PanelCallback = Callable[[str, str], None]


def _append_command_context(state: ChatState, *, title: str, body: str, limit: int = 4000) -> None:
    txt = (body or "").strip()
    if not txt:
        return
    if len(txt) > limit:
        txt = txt[-limit:]
        txt = f"(truncated to last {limit} chars)\n\n" + txt
    content = f"Command output ({title}):\n{txt}"
    state.messages.append(ChatMessage(role="assistant", content=content))
    try:
        append_chat_message("assistant", content)
    except Exception:
        pass


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

    # Some models may output commands prefixed with /sandbox. Treat these as
    # aliases rather than "unknown command" to keep the UX resilient.
    sandbox = False
    if cmd == "/sandbox":
        sandbox = True
        if not args:
            show_panel("sandbox", "Usage: /sandbox analyze TICKER... | /sandbox backtest [TICKER...]")
            return True
        cmd = "/" + args[0].lower().lstrip("/")
        args = args[1:]
    elif cmd.startswith("/sandbox/"):
        sandbox = True
        cmd = "/" + cmd.split("/sandbox/", 1)[1]

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
            "Commands (you can also type: help, exit, clear, reset, history):\n"
            "  /help\n"
            "  /exit\n"
            "  /clear                      (clear in-memory chat)\n"
            "  /reset                      (clear in-memory + persisted history)\n"
            "  /history [N]                (show last N messages, default 20)\n"
            "  /status                     (show backend + output directory)\n"
            "  /version\n"
            "  /config where\n"
            "  /config show\n"
            "  /config init [path]\n"
            "  /config set FIELD_PATH JSON_VALUE\n"
            "  /data fetch [TICKER1 TICKER2 ...]\n"
            "  /analyze TICKER1 TICKER2 ...\n"
            "  /sandbox analyze TICKER1 TICKER2 ...   (run without saving last-run history)\n"
            "  /backtest [TICKER1 TICKER2 ...]\n"
            "  /sandbox backtest [TICKER1 TICKER2 ...]   (alias; currently same output behavior)\n"
            "  /report\n"
            "  /export [path]\n"
            "  /doctor\n"
            "  /llm check                 (checks configured backend; model.backend defaults to 'auto')\n"
            "  /schedule status\n"
            "  /schedule once [--out-dir DIR]\n"
            "  /schedule run [--out-dir DIR]    (runs in background)\n",
        )
        return True

    if cmd == "/status":
        llm = do_llm_check()
        show_panel("status", f"llm: {llm}\nout_dir: {out_dir}")
        return True

    if cmd == "/history":
        limit = 20
        if args:
            try:
                limit = int(args[0])
            except Exception:
                limit = 20
        limit = max(1, min(200, limit))
        msgs = load_chat_history(limit=limit)
        if not msgs:
            show_panel("history", "(empty)")
            return True
        body = "\n\n".join([f"[{m.role}]\n{m.content}" for m in msgs])
        show_panel("history", body)
        return True

    if cmd == "/clear":
        # Keep the system prompt (first message) if present.
        keep = []
        if state.messages:
            first = state.messages[0]
            if getattr(first, "role", None) == "system":
                keep = [first]
        state.messages = keep
        show_panel("clear", "Cleared in-memory chat context.")
        return True

    if cmd == "/reset":
        removed = clear_chat_history()
        keep = []
        if state.messages:
            first = state.messages[0]
            if getattr(first, "role", None) == "system":
                keep = [first]
        state.messages = keep
        show_panel("reset", "Cleared in-memory context and removed persisted history." if removed else "Cleared in-memory context.")
        return True

    if cmd == "/llm":
        if not args:
            show_panel("llm", "Usage: /llm check")
            return True
        sub = args[0].lower()
        if sub == "check":
            show_panel("llm check", do_llm_check())
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
        report = do_analyze(args, out_dir=out_dir, sandbox=sandbox)
        show_panel("analyze", f"Wrote report: {report}")
        try:
            txt = Path(report).read_text(encoding="utf-8")
            _append_command_context(state, title="analyze", body=txt)
        except Exception:
            _append_command_context(state, title="analyze", body=f"Wrote report: {report}")
        return True

    if cmd == "/backtest":
        path = do_backtest(args if args else None, start=None, end=None, out_dir=out_dir)
        show_panel("backtest", f"Wrote backtest: {path}")
        try:
            txt = Path(path).read_text(encoding="utf-8")
            _append_command_context(state, title="backtest", body=txt)
        except Exception:
            _append_command_context(state, title="backtest", body=f"Wrote backtest: {path}")
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
