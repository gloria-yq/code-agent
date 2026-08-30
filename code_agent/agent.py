"""The complete model-tool-model loop and its termination conditions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from .approval import ApprovalPolicy
from .context import ContextManager
from .errors import CodeAgentError, ModelError, ToolError
from .protocol import ModelReply
from .session import SessionLogger
from .tools.registry import ToolRegistry


class ModelClient(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply: ...


@dataclass(frozen=True)
class AgentResult:
    status: str
    final_text: str
    turns: int
    tool_calls: int
    error: str | None = None


class CodingAgent:
    def __init__(
        self,
        *,
        client: ModelClient,
        tools: ToolRegistry,
        context: ContextManager,
        approvals: ApprovalPolicy,
        logger: SessionLogger,
        max_turns: int = 24,
        max_consecutive_errors: int = 3,
        on_status=None,
    ):
        self.client = client
        self.tools = tools
        self.context = context
        self.approvals = approvals
        self.logger = logger
        self.max_turns = max_turns
        self.max_consecutive_errors = max_consecutive_errors
        self.on_status = on_status or (lambda _kind, _message: None)

    def run(self, task: str, system_prompt: str) -> AgentResult:
        if not task.strip():
            return AgentResult("invalid_task", "", 0, 0, "Task cannot be empty")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task.strip()},
        ]
        self.logger.emit("session.started", task=task.strip())
        tool_call_count = 0
        consecutive_errors = 0
        last_signature: str | None = None
        repeated_calls = 0

        for turn in range(1, self.max_turns + 1):
            self.on_status("model", f"Turn {turn}: asking the model")
            self.logger.emit("model.requested", turn=turn, message_count=len(messages))
            try:
                reply = self.client.complete(
                    self.context.prepare(messages), self.tools.schemas()
                )
            except ModelError as exc:
                self.logger.emit("session.failed", turn=turn, error=str(exc))
                return AgentResult("model_error", "", turn, tool_call_count, str(exc))

            messages.append(reply.as_assistant_message())
            self.logger.emit(
                "model.responded",
                turn=turn,
                finish_reason=reply.finish_reason,
                content=reply.content,
                tool_calls=[call.name for call in reply.tool_calls],
            )
            if not reply.tool_calls:
                final_text = reply.content.strip()
                if not final_text:
                    error = "Model returned neither text nor tool calls"
                    self.logger.emit("session.failed", turn=turn, error=error)
                    return AgentResult("protocol_error", "", turn, tool_call_count, error)
                self.logger.emit("session.completed", turn=turn, final_text=final_text)
                return AgentResult("completed", final_text, turn, tool_call_count)

            signature = json.dumps(
                [(call.name, call.arguments) for call in reply.tool_calls], sort_keys=True
            )
            repeated_calls = repeated_calls + 1 if signature == last_signature else 0
            last_signature = signature
            if repeated_calls >= 2:
                error = "The model repeated the same tool request three times"
                self.logger.emit("session.failed", turn=turn, error=error)
                return AgentResult("stalled", reply.content, turn, tool_call_count, error)

            for call in reply.tool_calls:
                tool_call_count += 1
                self.on_status("tool", f"{call.name} {call.arguments}")
                self.logger.emit(
                    "tool.requested", turn=turn, call_id=call.id, tool=call.name
                )
                try:
                    arguments = self.tools.parse_arguments(call.name, call.arguments)
                    spec = self.tools.get(call.name)
                    self.approvals.check(spec, arguments)
                    result = self.tools.execute(call.name, arguments)
                    consecutive_errors = 0
                    content = json.dumps(result, ensure_ascii=False)
                    self.logger.emit(
                        "tool.completed", turn=turn, call_id=call.id, tool=call.name, result=result
                    )
                except (ToolError, CodeAgentError) as exc:
                    consecutive_errors += 1
                    content = json.dumps(
                        {"ok": False, "error": type(exc).__name__, "message": str(exc)},
                        ensure_ascii=False,
                    )
                    self.logger.emit(
                        "tool.failed", turn=turn, call_id=call.id, tool=call.name, error=str(exc)
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": content,
                    }
                )
                if consecutive_errors >= self.max_consecutive_errors:
                    error = f"Stopped after {consecutive_errors} consecutive tool errors"
                    self.logger.emit("session.failed", turn=turn, error=error)
                    return AgentResult("tool_error_limit", reply.content, turn, tool_call_count, error)

        error = f"Stopped after reaching the maximum of {self.max_turns} turns"
        self.logger.emit("session.failed", turn=self.max_turns, error=error)
        return AgentResult("max_turns", "", self.max_turns, tool_call_count, error)

