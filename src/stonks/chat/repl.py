from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.panel import Panel

from stonks.llm.backends import ChatMessage, OllamaBackend


@dataclass
class ChatState:
    messages: list[ChatMessage]


SYSTEM_PROMPT = (
    "You are Stonks, a local CLI assistant for stock analysis. "
    "Be cautious: you are not a financial advisor. "
    "When you suggest actions, prefer concrete CLI commands like '/analyze AAPL.US'."
)


def run_chat(host: str, model: str) -> None:
    console = Console()
    kb = KeyBindings()

    @kb.add("c-c")
    @kb.add("c-d")
    def _exit(event):
        event.app.exit()

    session = PromptSession()
    state = ChatState(messages=[ChatMessage(role="system", content=SYSTEM_PROMPT)])
    backend = OllamaBackend(host=host, model=model)

    console.print(Panel.fit("Stonks Chat (local model)", title="stonks chat"))

    while True:
        try:
            user_text = session.prompt("> ", key_bindings=kb)
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye.")
            return

        user_text = user_text.strip()
        if not user_text:
            continue

        if user_text in {"/exit", "/quit"}:
            console.print("Bye.")
            return
        if user_text == "/help":
            console.print(
                Panel(
                    "Commands:\n"
                    "  /help\n"
                    "  /exit\n"
                    "  /analyze TICKER1 TICKER2 ... (run from another terminal)\n"
                    "  /report (run from another terminal)",
                    title="help",
                )
            )
            continue

        state.messages.append(ChatMessage(role="user", content=user_text))
        console.print("\n[bold]assistant[/bold]: ", end="")
        try:
            chunks = []
            for part in backend.stream_chat(state.messages):
                chunks.append(part)
                console.print(part, end="")
            console.print()
            state.messages.append(ChatMessage(role="assistant", content="".join(chunks)))
        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}")
