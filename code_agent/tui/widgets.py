"""Reusable keyboard-first widgets for the terminal conversation."""

from __future__ import annotations

import json
from typing import Any

from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Collapsible, Label, Markdown, Static, TextArea


class Composer(TextArea):
    """Chat composer with conventional send and newline shortcuts."""

    BINDINGS = [
        Binding("enter", "submit", "Send", show=True, priority=True),
        Binding(
            "shift+enter", "insert_newline", "New line", show=False, priority=True
        ),
        Binding(
            "ctrl+enter", "submit", "Send (alternate)", show=False, priority=True
        ),
    ]

    class Submitted(Message):
        def __init__(self, text: str):
            super().__init__()
            self.text = text

    def action_submit(self) -> None:
        text = self.text.strip()
        if text and not self.disabled:
            self.post_message(self.Submitted(text))

    def action_insert_newline(self) -> None:
        if not self.disabled:
            self.insert("\n")


class MessageBlock(Vertical):
    def __init__(self, role: str, content: str = ""):
        super().__init__(classes=f"message {role}")
        self.role = role
        self.content = content
        self.label = Label(role.upper(), classes="message-role")
        self.markdown = Markdown(content or " ", classes="message-content")

    def compose(self):
        yield self.label
        yield self.markdown

    def append(self, text: str) -> None:
        self.content += text
        self.markdown.update(self.content or " ")

    def replace(self, text: str) -> None:
        self.content = text
        self.markdown.update(text or " ")


class ToolCard(Collapsible):
    def __init__(self, call_id: str, tool: str, arguments: str):
        self.call_id = call_id
        self.tool = tool
        self.body = Static(arguments or "{}", classes="tool-body")
        super().__init__(
            self.body,
            title=f"RUNNING  {tool}",
            collapsed=True,
            classes="tool-card running",
        )

    def finish(self, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        self.remove_class("running")
        if error is not None:
            self.add_class("failed")
            self.title = f"FAILED   {self.tool}"
            self.body.update(error)
            return
        self.add_class("completed")
        self.title = f"DONE     {self.tool}"
        self.body.update(json.dumps(result or {}, ensure_ascii=False, indent=2, default=str))
