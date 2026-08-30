"""Deterministic context bounding owned by the local agent."""

from __future__ import annotations

import copy
import json
from typing import Any


def _size(message: dict[str, Any]) -> int:
    return len(json.dumps(message, ensure_ascii=False, separators=(",", ":")))


class ContextManager:
    def __init__(self, *, char_budget: int, max_tool_output_chars: int):
        self.char_budget = char_budget
        self.max_tool_output_chars = max_tool_output_chars

    def prepare(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        bounded = [self._bound_message(message) for message in copy.deepcopy(messages)]
        if sum(map(_size, bounded)) <= self.char_budget:
            return bounded
        if len(bounded) <= 2:
            return bounded

        prefix = bounded[:2]
        tail: list[dict[str, Any]] = []
        used = sum(map(_size, prefix)) + 300
        for message in reversed(bounded[2:]):
            message_size = _size(message)
            if used + message_size > self.char_budget and tail:
                break
            tail.append(message)
            used += message_size
        tail.reverse()

        # A tool result cannot be sent without the assistant message that owns its call id.
        while tail and tail[0].get("role") == "tool":
            tail.pop(0)
        omitted = len(bounded) - len(prefix) - len(tail)
        note = {
            "role": "system",
            "content": (
                f"Context notice: {omitted} older messages were omitted locally to stay within "
                "the configured context budget. Re-read files before relying on old details."
            ),
        }
        return prefix + [note] + tail

    def _bound_message(self, message: dict[str, Any]) -> dict[str, Any]:
        if message.get("role") != "tool":
            return message
        content = message.get("content")
        if isinstance(content, str) and len(content) > self.max_tool_output_chars:
            omitted = len(content) - self.max_tool_output_chars
            message["content"] = (
                content[: self.max_tool_output_chars]
                + f"\n...[locally truncated {omitted} characters]"
            )
        return message

