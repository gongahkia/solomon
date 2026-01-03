from __future__ import annotations

from pathlib import Path

import stonks_cli.chat.dispatch as dispatch
from stonks_cli.llm.backends import ChatMessage


def _run(cmd: str, *, state: dispatch.ChatState):
    panels: list[tuple[str, str]] = []

    def show_panel(title: str, body: str) -> None:
        panels.append((title, body))

    handled = dispatch.handle_slash_command(cmd, state=state, show_panel=show_panel, out_dir=Path("reports"))
    return handled, panels


def test_clear_preserves_system_only():
    state = dispatch.ChatState(
        messages=[
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="hello"),
        ]
    )

    handled, panels = _run("/clear", state=state)
    assert handled is True
    assert [m.role for m in state.messages] == ["system"]
    assert panels and panels[-1][0] == "clear"


def test_reset_clears_and_calls_clear_history(monkeypatch):
    called = {"n": 0}

    def fake_clear_chat_history() -> bool:
        called["n"] += 1
        return True

    monkeypatch.setattr(dispatch, "clear_chat_history", fake_clear_chat_history)

    state = dispatch.ChatState(
        messages=[
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="hi"),
        ]
    )

    handled, panels = _run("/reset", state=state)
    assert handled is True
    assert called["n"] == 1
    assert [m.role for m in state.messages] == ["system"]
    assert panels and panels[-1][0] == "reset"
