from __future__ import annotations

from stonks_cli.llm.backends import ChatMessage, _format_messages_as_prompt, _strip_prompt_echo


def test_format_messages_as_prompt_contains_headers():
    prompt = _format_messages_as_prompt(
        [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="hello"),
        ]
    )
    assert "### System" in prompt
    assert "### User" in prompt
    assert "### Assistant" in prompt


def test_strip_prompt_echo_removes_prefix():
    prompt = "P"
    generated = "P\n\nanswer"
    assert _strip_prompt_echo(prompt, generated) == "answer"
