"""Direct OpenAI-compatible Chat Completions client using the standard library."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .errors import ModelError
from .protocol import ModelReply, ToolCall


class OpenAICompatibleClient:
    """Calls /chat/completions without relying on an agent or vendor SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        max_retries: int = 2,
    ):
        self.api_key = api_key
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.model = model
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
            "tools": tools,
            "tool_choice": "auto",
        }
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
                detail = exc.read().decode("utf-8", errors="replace")[:2000]
                retryable = exc.code in {408, 409, 429, 500, 502, 503, 504}
                if retryable and attempt < self.max_retries:
                    time.sleep(2**attempt)
                    continue
                raise ModelError(f"Model API returned HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                    continue
                raise ModelError(f"Cannot reach model API: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise ModelError("Model API returned invalid JSON") from exc
        raise ModelError("Model request failed after retries")

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

