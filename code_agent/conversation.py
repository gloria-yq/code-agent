"""Durable, workspace-local conversation snapshots.

The audit JSONL stream remains append-only and diagnostic. This module owns the
canonical, resumable model message history and writes it atomically after every
safe agent state transition.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ConversationError

_SESSION_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
_ALLOWED_ROLES = {"system", "user", "assistant", "tool"}


@dataclass(frozen=True)
class ConversationSummary:
    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    tool_calls: int
    preview: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ConversationRecord:
    session_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]]


class ConversationStore:
    """Persist one atomic JSON snapshot per conversation inside a workspace."""

    VERSION = 1

    def __init__(
        self,
        directory: Path,
        *,
        redact: Callable[[Any], Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.directory = directory
        self._redact = redact or (lambda value: value)
        self._metadata = dict(metadata or {})
        self._lock = threading.Lock()

    def save(
        self, session_id: str | None, messages: list[dict[str, Any]]
    ) -> str:
        snapshot = self._validate_messages(self._redact(copy.deepcopy(messages)))
        if not any(message["role"] == "user" for message in snapshot):
            if session_id:
                self.delete(session_id)
            return ""

        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            now = datetime.now(timezone.utc).isoformat()
            if not session_id:
                session_id = self._new_id()
                created_at = now
            else:
                path = self._path(session_id)
                created_at = now
                if path.is_file():
                    try:
                        existing = json.loads(path.read_text(encoding="utf-8"))
                        created_at = str(existing.get("created_at") or now)
                    except (OSError, json.JSONDecodeError):
                        pass

            payload = {
                "version": self.VERSION,
                "session_id": session_id,
                "title": self._title(snapshot),
                "created_at": created_at,
                "updated_at": now,
                "metadata": self._redact(copy.deepcopy(self._metadata)),
                "messages": snapshot,
            }
            target = self._path(session_id)
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            except OSError as exc:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise ConversationError(f"Cannot save conversation: {exc}") from exc
            return session_id

    def load(self, session_id: str) -> ConversationRecord:
        path = self._path(session_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConversationError("Saved conversation was not found.") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ConversationError(f"Cannot read saved conversation: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("version") != self.VERSION:
            raise ConversationError("Saved conversation has an unsupported format.")
        if payload.get("session_id") != session_id:
            raise ConversationError("Saved conversation identity does not match its file.")
        messages = self._repair_incomplete_tools(
            self._validate_messages(payload.get("messages"))
        )
        return ConversationRecord(
            session_id=session_id,
            title=str(payload.get("title") or "Untitled conversation"),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            messages=messages,
        )

    def list(self, *, limit: int = 50) -> tuple[ConversationSummary, ...]:
        if not self.directory.is_dir():
            return ()
        summaries: list[ConversationSummary] = []
        for path in self.directory.glob("*.json"):
            if not _SESSION_ID.fullmatch(path.stem):
                continue
            try:
                record = self.load(path.stem)
            except ConversationError:
                continue
            visible = [
                message
                for message in record.messages
                if message["role"] in {"user", "assistant"}
                and isinstance(message.get("content"), str)
                and message["content"].strip()
            ]
            if not any(message["role"] == "user" for message in visible):
                continue
            preview = tuple(
                (message["role"], self._compact(str(message["content"]), 180))
                for message in visible[-6:]
            )
            summaries.append(
                ConversationSummary(
                    session_id=record.session_id,
                    title=record.title,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    message_count=len(record.messages) - 1,
                    tool_calls=sum(
                        1 for message in record.messages if message["role"] == "tool"
                    ),
                    preview=preview,
                )
            )
        summaries.sort(key=lambda item: item.updated_at, reverse=True)
        return tuple(summaries[: max(1, limit)])

    def delete(self, session_id: str) -> None:
        try:
            self._path(session_id).unlink(missing_ok=True)
        except OSError as exc:
            raise ConversationError(f"Cannot remove empty conversation: {exc}") from exc

    def _path(self, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(session_id):
            raise ConversationError("Invalid conversation identifier.")
        return self.directory / f"{session_id}.json"

    @staticmethod
    def _new_id() -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{uuid.uuid4().hex[:8]}"

    @classmethod
    def _validate_messages(cls, messages: Any) -> list[dict[str, Any]]:
        if not isinstance(messages, list) or not messages:
            raise ConversationError("Saved conversation has no message history.")
        validated: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in _ALLOWED_ROLES:
                raise ConversationError("Saved conversation contains an invalid message.")
            validated.append(copy.deepcopy(message))
        if validated[0].get("role") != "system":
            raise ConversationError("Saved conversation does not begin with a system message.")
        if any(message.get("role") == "system" for message in validated[1:]):
            raise ConversationError("Saved conversation contains an unexpected system message.")
        return validated

    @staticmethod
    def _repair_incomplete_tools(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        repaired: list[dict[str, Any]] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            repaired.append(message)
            calls = message.get("tool_calls") if message.get("role") == "assistant" else None
            if not isinstance(calls, list) or not calls:
                index += 1
                continue
            expected = [str(call.get("id", "")) for call in calls if isinstance(call, dict)]
            present: set[str] = set()
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].get("role") == "tool":
                tool_message = messages[cursor]
                repaired.append(tool_message)
                present.add(str(tool_message.get("tool_call_id", "")))
                cursor += 1
            for call_id in expected:
                if call_id and call_id not in present:
                    repaired.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": "interrupted_tool",
                            "content": json.dumps(
                                {
                                    "ok": False,
                                    "error": "interrupted",
                                    "message": (
                                        "The previous process ended before this tool result was "
                                        "recorded. Inspect the workspace before retrying."
                                    ),
                                }
                            ),
                        }
                    )
            index = cursor
        return repaired

    @staticmethod
    def _title(messages: list[dict[str, Any]]) -> str:
        for message in messages:
            if message.get("role") == "user":
                return ConversationStore._compact(str(message.get("content") or ""), 72)
        return "Untitled conversation"

    @staticmethod
    def _compact(text: str, limit: int) -> str:
        compact = " ".join(text.split()) or "Untitled conversation"
        return compact if len(compact) <= limit else compact[: limit - 1] + "…"
