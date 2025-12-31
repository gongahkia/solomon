from __future__ import annotations

from pathlib import Path
import json

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.panel import Panel

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
    do_ollama_check,
    do_report_open,
    do_schedule_once,
    do_schedule_start_background,
    do_schedule_status,
    do_version,
)

from stonks_cli.llm.backends import ChatMessage, build_chat_backend, build_chat_backend_from_overrides
from stonks_cli.chat.history import append_chat_message, load_chat_history
from stonks_cli.chat.export import default_transcript_path, write_transcript
from stonks_cli.chat.prompts import format_analysis_question
from stonks_cli.chat.dispatch import ChatState, handle_slash_command
from stonks_cli.storage import get_last_report_path


SYSTEM_PROMPT = (
    "You are stonks-cli, a local CLI assistant for stock analysis. "
    "Be cautious: you are not a financial advisor. "
    "When you suggest actions, prefer concrete CLI commands like '/analyze AAPL.US'."
)


def run_chat(
    *,
    backend: str | None = None,
    model: str | None = None,
    host: str | None = None,
    path: str | None = None,
    offline: bool | None = None,
) -> None:
    console = Console()
    kb = KeyBindings()

    @kb.add("c-c")
    @kb.add("c-d")
    def _exit(event):
        event.app.exit()

    session = PromptSession()
    restored = load_chat_history(limit=50)
    state = ChatState(messages=[ChatMessage(role="system", content=SYSTEM_PROMPT), *restored], scheduler=None)
    if any(v is not None for v in (backend, model, host, path, offline)):
        backend_obj, selected_backend, warn = build_chat_backend_from_overrides(
            backend=backend,
            model=model,
            host=host,
            path=path,
            offline=offline,
        )
    else:
        backend_obj, selected_backend, warn = build_chat_backend()

    console.print(Panel.fit("stonks-cli chat (local model)", title="stonks-cli"))
    console.print("Note: outputs are informational only (not financial advice).")
    if warn:
        console.print(Panel(warn, title="llm backend"))
    else:
        console.print(Panel(f"backend: {selected_backend}", title="llm backend"))

    def show_panel(title: str, body: str) -> None:
        console.print(Panel(body, title=title))

    while True:
        try:
            user_text = session.prompt("> ", key_bindings=kb)
        except (EOFError, KeyboardInterrupt):
            if state.scheduler is not None:
                try:
                    state.scheduler.stop()
                except Exception:
                    pass
            console.print("\nBye.")
            return

        user_text = user_text.strip()
        if not user_text:
            continue

        # Tool-like intent parsing: allow common commands without leading '/'.
        lowered = user_text.lower().strip()
        if not lowered.startswith("/"):
            if lowered == "help":
                user_text = "/help"
            elif lowered in {"exit", "quit"}:
                user_text = "/exit"
            elif lowered.startswith("analyze "):
                user_text = "/analyze " + user_text.split(" ", 1)[1]
            elif lowered.startswith("backtest"):
                rest = user_text.split(" ", 1)[1] if " " in user_text else ""
                user_text = ("/backtest " + rest).strip()
            elif lowered == "report":
                user_text = "/report"
            elif lowered.startswith("schedule status"):
                user_text = "/schedule status"
            elif lowered.startswith("schedule once"):
                user_text = "/schedule once"
            elif lowered.startswith("llm check"):
                user_text = "/llm check"

        if user_text.startswith("/"):
            try:
                if user_text.startswith("/export"):
                    # Keep transcript export local to the REPL since it depends on the in-memory message list.
                    parts = user_text.strip().split()
                    args = parts[1:]
                    out = Path(args[0]).expanduser() if args else default_transcript_path()
                    try:
                        p = write_transcript(state.messages, out)
                        show_panel("export", f"Wrote transcript: {p}")
                    except Exception as e:
                        show_panel("export", f"Error: {e}")
                else:
                    handle_slash_command(user_text, state=state, show_panel=show_panel, out_dir=Path("reports"))
            except EOFError:
                return
            continue

        state.messages.append(ChatMessage(role="user", content=user_text))
        append_chat_message("user", user_text)
        console.print("\n[bold]assistant[/bold]: ", end="")
        try:
            prior = None
            try:
                p = get_last_report_path()
                if p is not None and p.exists():
                    prior = p.read_text(encoding="utf-8")
                    if len(prior) > 4000:
                        prior = prior[-4000:]
            except Exception:
                prior = None

            templated = format_analysis_question(user_text, prior_report=prior)
            # Replace the latest user message content with templated prompt for the model.
            state.messages[-1] = ChatMessage(role="user", content=templated)

            chunks = []
            for part in backend_obj.stream_chat(state.messages):
                chunks.append(part)
                console.print(part, end="")
            console.print()
            assistant_text = "".join(chunks)
            state.messages.append(ChatMessage(role="assistant", content=assistant_text))
            append_chat_message("assistant", assistant_text)
        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}")
