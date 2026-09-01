"""Conversation state plus the complete model-tool-model loop."""

from __future__ import annotations

import copy
import json
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from .approval import ApprovalPolicy
from .conversation import ConversationStore, ConversationSummary
from .context import ContextManager
from .errors import CodeAgentError, ModelError, ToolError, TurnCancelled
from .events import AgentEvent
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
    """A stateful conversation containing one ReAct loop per user turn."""

    def __init__(
        self,
        *,
        client: ModelClient,
        tools: ToolRegistry,
        context: ContextManager,
        approvals: ApprovalPolicy,
        logger: SessionLogger,
        conversations: ConversationStore | None = None,
        max_turns: int = 24,
        max_consecutive_errors: int = 3,
        on_status=None,
        on_event=None,
    ):
        self.client = client
        self.tools = tools
        self.context = context
        self.approvals = approvals
        self.logger = logger
        self.conversations = conversations
        self.max_turns = max_turns
        self.max_consecutive_errors = max_consecutive_errors
        self.on_status = on_status or (lambda _kind, _message: None)
        self.on_event = on_event or (lambda _event: None)
        self._system_prompt: str | None = None
        self._messages: list[dict[str, Any]] = []
        self._session_started = False
        self._user_turns = 0
        self._model_turns = 0
        self._tool_calls = 0
        self._cancel_requested = threading.Event()
        self._session_id: str | None = None

    def _emit(self, kind: str, **data: Any) -> None:
        self.on_event(AgentEvent(kind, data))

    def cancel(self) -> None:
        """Request a cooperative stop at the next model-stream or tool boundary."""
        self._cancel_requested.set()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested.is_set():
            raise TurnCancelled("Turn cancelled by user")

    def start(self, system_prompt: str) -> None:
        """Initialize the conversation once without adding a user message."""
        if self._session_started:
            return
        self._system_prompt = system_prompt
        self._messages = [{"role": "system", "content": system_prompt}]
        self._session_started = True
        self.logger.emit("session.started")
        self._emit("session.started")

    def reset(self) -> None:
        """Start a new conversation while retaining the configured system prompt."""
        prompt = self._system_prompt or ""
        self._messages = [{"role": "system", "content": prompt}]
        self._session_started = True
        self._user_turns = 0
        self._model_turns = 0
        self._tool_calls = 0
        self._session_id = None
        self.logger.emit("session.reset")
        self._emit("session.reset")

    def history(self) -> list[dict[str, Any]]:
        """Return a defensive copy of the complete in-memory conversation."""
        return copy.deepcopy(self._messages)

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def list_conversations(self) -> tuple[ConversationSummary, ...]:
        return self.conversations.list() if self.conversations else ()

    def resume(self, session_id: str) -> None:
        if self.conversations is None:
            raise CodeAgentError("Conversation persistence is not available.")
        record = self.conversations.load(session_id)
        self._messages = record.messages
        self._system_prompt = str(record.messages[0].get("content") or "")
        self._session_started = True
        self._session_id = record.session_id
        self._user_turns = sum(1 for item in self._messages if item.get("role") == "user")
        self._model_turns = sum(
            1 for item in self._messages if item.get("role") == "assistant"
        )
        self._tool_calls = sum(1 for item in self._messages if item.get("role") == "tool")
        self.logger.emit("session.resumed", session_id=session_id)
        self._emit("session.resumed", session_id=session_id, title=record.title)

    def _persist(self) -> None:
        if self.conversations is None:
            return
        self._session_id = self.conversations.save(self._session_id, self._messages) or None

    def stats(self) -> dict[str, int]:
        return {
            "user_turns": self._user_turns,
            "model_turns": self._model_turns,
            "tool_calls": self._tool_calls,
            "messages": max(0, len(self._messages) - 1),
        }

    def _record_local_stop(self, error: str, *, replace_last: bool = False) -> None:
        """Keep history API-valid after a locally enforced stop condition."""
        note = {"role": "assistant", "content": f"[Local agent stopped: {error}]"}
        if replace_last:
            self._messages[-1] = note
        else:
            self._messages.append(note)
        self._persist()

    def run(self, task: str, system_prompt: str | None = None) -> AgentResult:
        """Append one user turn and continue from the existing conversation."""
        if not task.strip():
            return AgentResult("invalid_task", "", 0, 0, "Task cannot be empty")
        if not self._session_started:
            self.start(system_prompt or "")

        turn_start = len(self._messages)
        self._cancel_requested.clear()
        user_input = task.strip()
        self._messages.append({"role": "user", "content": user_input})
        self._persist()
        self._user_turns += 1
        self.logger.emit("turn.started", user_input=user_input, user_turn=self._user_turns)
        self._emit("turn.started", content=user_input, user_turn=self._user_turns)
        try:
            return self._run_turn()
        except (KeyboardInterrupt, TurnCancelled):
            # Never leave a partial assistant/tool-call sequence in model history.
            del self._messages[turn_start:]
            self._user_turns -= 1
            self._persist()
            self.logger.emit("turn.interrupted")
            self._emit("turn.interrupted")
            return AgentResult("interrupted", "", 0, 0, "Turn interrupted by user")

    def _run_turn(self) -> AgentResult:
        tool_call_count = 0
        consecutive_errors = 0
        last_signature: str | None = None
        repeated_calls = 0

        for turn in range(1, self.max_turns + 1):
            self._raise_if_cancelled()
            self._model_turns += 1
            self.on_status("model", f"Turn {turn}: asking the model")
            self._emit("model.started", turn=turn)
            self.logger.emit(
                "model.requested", turn=turn, message_count=len(self._messages)
            )
            try:
                prepared = self.context.prepare(self._messages)
                stream = getattr(self.client, "complete_stream", None)
                if callable(stream):
                    reply = stream(
                        prepared,
                        self.tools.schemas(),
                        lambda delta_kind, content: self._stream_delta(
                            delta_kind, content
                        ),
                    )
                else:
                    reply = self.client.complete(prepared, self.tools.schemas())
                self._raise_if_cancelled()
            except ModelError as exc:
                self.logger.emit("turn.failed", turn=turn, error=str(exc))
                self._record_local_stop(str(exc))
                self._emit("turn.failed", status="model_error", error=str(exc))
                return AgentResult("model_error", "", turn, tool_call_count, str(exc))

            self._messages.append(reply.as_assistant_message())
            # Persist tool-call intent before any local side effect. If the process dies
            # during execution, ConversationStore repairs the missing result on resume.
            self._persist()
            self.logger.emit(
                "model.responded",
                turn=turn,
                finish_reason=reply.finish_reason,
                content=reply.content,
                tool_calls=[call.name for call in reply.tool_calls],
            )
            self._emit(
                "model.completed",
                turn=turn,
                content=reply.content,
                tool_calls=[call.name for call in reply.tool_calls],
            )
            if not reply.tool_calls:
                final_text = reply.content.strip()
                if not final_text:
                    error = "Model returned neither text nor tool calls"
                    self.logger.emit("turn.failed", turn=turn, error=error)
                    self._record_local_stop(error, replace_last=True)
                    self._emit("turn.failed", status="protocol_error", error=error)
                    return AgentResult("protocol_error", "", turn, tool_call_count, error)
                self.logger.emit("turn.completed", turn=turn, final_text=final_text)
                self._emit("turn.completed", content=final_text, turn=turn)
                return AgentResult("completed", final_text, turn, tool_call_count)

            signature = json.dumps(
                [(call.name, call.arguments) for call in reply.tool_calls], sort_keys=True
            )
            repeated_calls = repeated_calls + 1 if signature == last_signature else 0
            last_signature = signature
            if repeated_calls >= 2:
                error = "The model repeated the same tool request three times"
                self.logger.emit("turn.failed", turn=turn, error=error)
                self._record_local_stop(error, replace_last=True)
                self._emit("turn.failed", status="stalled", error=error)
                return AgentResult("stalled", reply.content, turn, tool_call_count, error)

            for call in reply.tool_calls:
                self._raise_if_cancelled()
                tool_call_count += 1
                self._tool_calls += 1
                self.on_status("tool", f"{call.name} {call.arguments}")
                self._emit(
                    "tool.requested",
                    turn=turn,
                    call_id=call.id,
                    tool=call.name,
                    arguments=call.arguments,
                )
                self.logger.emit(
                    "tool.requested", turn=turn, call_id=call.id, tool=call.name
                )
                try:
                    arguments = self.tools.parse_arguments(call.name, call.arguments)
                    spec = self.tools.get(call.name)
                    self.approvals.check(spec, arguments)
                    result = self.tools.execute(call.name, arguments)
                    self._raise_if_cancelled()
                    consecutive_errors = 0
                    content = json.dumps(result, ensure_ascii=False)
                    self.logger.emit(
                        "tool.completed",
                        turn=turn,
                        call_id=call.id,
                        tool=call.name,
                        result=result,
                    )
                    self._emit(
                        "tool.completed",
                        call_id=call.id,
                        tool=call.name,
                        result=result,
                    )
                except TurnCancelled:
                    raise
                except (ToolError, CodeAgentError) as exc:
                    consecutive_errors += 1
                    content = json.dumps(
                        {"ok": False, "error": type(exc).__name__, "message": str(exc)},
                        ensure_ascii=False,
                    )
                    self.logger.emit(
                        "tool.failed", turn=turn, call_id=call.id, tool=call.name, error=str(exc)
                    )
                    self._emit(
                        "tool.failed", call_id=call.id, tool=call.name, error=str(exc)
                    )
                self._messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": content,
                    }
                )
                self._persist()
                if consecutive_errors >= self.max_consecutive_errors:
                    error = f"Stopped after {consecutive_errors} consecutive tool errors"
                    self.logger.emit("turn.failed", turn=turn, error=error)
                    self._record_local_stop(error)
                    self._emit("turn.failed", status="tool_error_limit", error=error)
                    return AgentResult(
                        "tool_error_limit", reply.content, turn, tool_call_count, error
                    )

        error = f"Stopped after reaching the maximum of {self.max_turns} turns"
        self.logger.emit("turn.failed", turn=self.max_turns, error=error)
        self._record_local_stop(error)
        self._emit("turn.failed", status="max_turns", error=error)
        return AgentResult("max_turns", "", self.max_turns, tool_call_count, error)

    def _stream_delta(self, delta_kind: str, content: str) -> None:
        self._raise_if_cancelled()
        self._emit("model.delta", delta_kind=delta_kind, content=content)
