from __future__ import annotations

from collections import deque

from code_agent.protocol import ModelReply


class FakeClient:
    def __init__(self, replies: list[ModelReply]):
        self.replies = deque(replies)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append((messages, tools))
        if not self.replies:
            raise AssertionError("Fake client ran out of replies")
        return self.replies.popleft()

