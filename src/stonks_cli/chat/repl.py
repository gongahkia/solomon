from __future__ import annotations

import os
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
from stonks_cli.chat.message_prep import is_slash_only, sanitize_assistant_output, should_template_question, suggest_cli_commands
from stonks_cli.storage import get_last_report_path


SYSTEM_PROMPT = (
    "You are stonks-assistant, the assistant inside stonks-cli (a local CLI for stock analysis).\n"
    "Important: you are not a financial advisor. Provide informational guidance only.\n\n"
    "You do not have access to live news, fundamentals, or company financial statements.\n"
    "Prefer stonks-cli's built-in price-based analysis and backtesting.\n\n"
    "You cannot execute commands yourself; you can only suggest what the user should run.\n"
    "Avoid repeating the same command or block of text.\n\n"
    "Do not output slash-commands unless the user explicitly asks for a command.\n"
    "If suggesting a command, describe it in words or as a plain example (e.g. 'analyze AAPL.US').\n"
    "Never invent commands (e.g. never output '/sandbox/...').\n\n"
    "Do not repeat system or user prompt text back to the user.\n"
    "Answer concisely and focus on actionable next steps.\n"
)


def run_chat(
    *,
    backend: str | None = None,
    model: str | None = None,
    host: str | None = None,
    path: str | None = None,
    offline: bool | None = None,
    out_dir: str = "reports",
) -> None:
    # Keep the interactive UI readable when models are downloaded on first use.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    console = Console()
    kb = KeyBindings()

    @kb.add("c-c")
    @kb.add("c-d")
    def _exit(event):
        event.app.exit()

    session = PromptSession()
    restored = load_chat_history(limit=50)
    # Avoid feeding pathological slash-command-only outputs back into the model.
    restored = [m for m in restored if not (getattr(m, "role", None) == "assistant" and is_slash_only(getattr(m, "content", "")))]
    state = ChatState(messages=[ChatMessage(role="system", content=SYSTEM_PROMPT), *restored], scheduler=None)
    if any(v is not None for v in (backend, model, host, path, offline)):
        backend_obj, selected_backend, selected_ref, warn = build_chat_backend_from_overrides(
            backend=backend,
            model=model,
            host=host,
            path=path,
            offline=offline,
        )
    else:
        backend_obj, selected_backend, selected_ref, warn = build_chat_backend()

    console.print(Panel.fit("stonks-assistant chat (local model)", title="stonks-assistant"))
    console.print("Note: outputs are informational only (not financial advice).")
    if warn:
        console.print(Panel(warn, title="llm backend"))
    else:
        body = f"backend: {selected_backend}"
        if (selected_ref or "").strip():
            body += f"\nmodel/path: {selected_ref}"
        body += f"\nout_dir: {out_dir}"
        console.print(Panel(body, title="llm backend"))

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
            elif lowered == "status":
                user_text = "/status"
            elif lowered == "clear":
                user_text = "/clear"
            elif lowered == "reset":
                user_text = "/reset"
            elif lowered == "history" or lowered.startswith("history "):
                rest = user_text.split(" ", 1)[1] if " " in user_text else ""
                user_text = ("/history " + rest).strip()
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
                    out = Path(args[0]).expanduser() if args else default_transcript_path(out_dir)
                    try:
                        p = write_transcript(state.messages, out)
                        show_panel("export", f"Wrote transcript: {p}")
                    except Exception as e:
                        show_panel("export", f"Error: {e}")
                else:
                    handle_slash_command(user_text, state=state, show_panel=show_panel, out_dir=Path(out_dir))
            except EOFError:
                return
            except Exception as e:
                show_panel("error", str(e))
            continue

        state.messages.append(ChatMessage(role="user", content=user_text))
        append_chat_message("user", user_text)
        console.print("\nassistant:")
        try:
            suggestions = suggest_cli_commands(user_text)
            if suggestions:
                console.print("suggested commands:")
                for s in suggestions:
                    console.print(f"- {s}")
                console.print()

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
            # Keep raw user text in history; only send a templated message to the model when it's
            # analysis-like or when the user is referencing prior output.
            model_user = templated if should_template_question(user_text, has_prior_report=bool(prior)) else user_text
            model_messages = [*state.messages[:-1], ChatMessage(role="user", content=model_user)]

            chunks = []
            with console.status("thinking...", spinner="dots"):
                for part in backend_obj.stream_chat(model_messages):
                    chunks.append(part)
            assistant_text = "".join(chunks)
            allow_slash = user_text.strip().startswith("/") or should_template_question(user_text, has_prior_report=bool(prior))
            assistant_text = sanitize_assistant_output(assistant_text, allow_slash_commands=allow_slash)

            if assistant_text:
                console.print(assistant_text, markup=False, highlight=False, soft_wrap=True)
            console.print()
            if assistant_text:
                state.messages.append(ChatMessage(role="assistant", content=assistant_text))
                append_chat_message("assistant", assistant_text)
        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}")
