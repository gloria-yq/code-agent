"""Direct OpenAI-compatible Chat Completions client using the standard library."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .errors import ModelError
from .protocol import ModelReply, ToolCall
from .security import SecretRedactor


class OpenAICompatibleClient:
    """Calls /chat/completions without relying on an agent or vendor SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        provider: str = "openai",
        deepseek_thinking: bool = True,
        timeout: float = 120.0,
        max_retries: int = 2,
    ):
        self.api_key = api_key
        self._redact = SecretRedactor([api_key]).text
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.model = model
        self.provider = provider
        self.deepseek_thinking = deepseek_thinking
        self.timeout = timeout
        self.max_retries = max_retries

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelReply:
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        if self.provider == "deepseek":
            payload["thinking"] = {
                "type": "enabled" if self.deepseek_thinking else "disabled"
            }
            if tools and not self.deepseek_thinking:
                payload["tool_choice"] = "auto"
        elif tools:
            payload["tool_choice"] = "auto"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "code-agent/0.1",
            },
            method="POST",
        )

        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                return self._parse(data)
            except urllib.error.HTTPError as exc:
                detail = self._redact(exc.read().decode("utf-8", errors="replace")[:2000])
                retryable = exc.code in {408, 409, 429, 500, 502, 503, 504}
                if retryable and attempt < self.max_retries:
                    time.sleep(2**attempt)
                    continue
                raise ModelError(f"Model API returned HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                    continue
                raise ModelError(f"Cannot reach model API: {self._redact(str(exc))}") from exc
            except json.JSONDecodeError as exc:
                raise ModelError("Model API returned invalid JSON") from exc
        raise ModelError("Model request failed after retries")

    def complete_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_delta: Callable[[str, str], None],
    ) -> ModelReply:
        """Consume Chat Completions SSE and assemble one protocol-valid reply."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        if self.provider == "deepseek":
            payload["thinking"] = {
                "type": "enabled" if self.deepseek_thinking else "disabled"
            }
            if tools and not self.deepseek_thinking:
                payload["tool_choice"] = "auto"
        elif tools:
            payload["tool_choice"] = "auto"
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "code-agent/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return self._parse_stream(response, on_delta)
        except urllib.error.HTTPError as exc:
            detail = self._redact(exc.read().decode("utf-8", errors="replace")[:2000])
            raise ModelError(f"Model API returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ModelError(f"Cannot reach model API: {self._redact(str(exc))}") from exc

    @staticmethod
    def _parse_stream(response, on_delta: Callable[[str, str], None]) -> ModelReply:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        received_event = False
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
                choice = event["choices"][0]
                delta = choice.get("delta") or {}
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise ModelError("Model stream returned a malformed event") from exc
            received_event = True
            content = delta.get("content")
            if isinstance(content, str) and content:
                content_parts.append(content)
                on_delta("content", content)
            reasoning = delta.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                reasoning_parts.append(reasoning)
                on_delta("reasoning", reasoning)
            for item in delta.get("tool_calls") or []:
                try:
                    index = int(item.get("index", 0))
                    accumulated = calls.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    if item.get("id"):
                        accumulated["id"] += str(item["id"])
                    function = item.get("function") or {}
                    if function.get("name"):
                        accumulated["name"] += str(function["name"])
                    if function.get("arguments"):
                        arguments = str(function["arguments"])
                        accumulated["arguments"] += arguments
                        on_delta("tool_arguments", arguments)
                except (TypeError, ValueError) as exc:
                    raise ModelError("Model stream returned a malformed tool delta") from exc
            if choice.get("finish_reason") is not None:
                finish_reason = str(choice["finish_reason"])
        if not received_event:
            raise ModelError("Model stream ended without response events")
        tool_calls = tuple(
            ToolCall(
                id=value["id"] or f"call-{index}",
                name=value["name"],
                arguments=value["arguments"] or "{}",
            )
            for index, value in sorted(calls.items())
        )
        raw_message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts) or None,
        }
        if reasoning_parts:
            raw_message["reasoning_content"] = "".join(reasoning_parts)
        return ModelReply(
            content="".join(content_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            raw_message=raw_message,
        )

    @staticmethod
    def _parse(data: dict[str, Any]) -> ModelReply:
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("Response is missing choices[0].message") from exc

        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ModelError("Assistant message content must be a string or null")
        calls: list[ToolCall] = []
        for item in message.get("tool_calls") or []:
            try:
                function = item["function"]
                calls.append(
                    ToolCall(
                        id=str(item["id"]),
                        name=str(function["name"]),
                        arguments=str(function.get("arguments", "{}")),
                    )
                )
            except (KeyError, TypeError) as exc:
                raise ModelError("Malformed tool call in assistant response") from exc
        return ModelReply(
            content=content,
            tool_calls=tuple(calls),
            finish_reason=choice.get("finish_reason"),
            raw_message=message,
        )
