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


def test_sandbox_analyze_alias_sets_sandbox_true(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_do_analyze(tickers, out_dir, *, sandbox=False):
        calls.append({"tickers": tickers, "out_dir": out_dir, "sandbox": sandbox})
        return Path("reports") / "dummy.txt"

    monkeypatch.setattr(dispatch, "do_analyze", fake_do_analyze)

    state = dispatch.ChatState(messages=[ChatMessage(role="system", content="sys")])
    handled, panels = _run("/sandbox analyze AAPL.US", state=state)
    assert handled is True
    assert calls and calls[0]["sandbox"] is True
    assert panels and panels[-1][0] == "analyze"


def test_history_shows_messages(monkeypatch):
    monkeypatch.setattr(
        dispatch,
        "load_chat_history",
        lambda limit=20: [ChatMessage(role="user", content="u"), ChatMessage(role="assistant", content="a")],
    )

    state = dispatch.ChatState(messages=[ChatMessage(role="system", content="sys")])
    handled, panels = _run("/history 2", state=state)
    assert handled is True
    assert panels and panels[-1][0] == "history"
    body = panels[-1][1]
    assert "[user]" in body
    assert "[assistant]" in body
