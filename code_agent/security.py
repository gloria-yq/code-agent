"""Credential isolation and defense-in-depth redaction helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_SENSITIVE_NAME_PARTS = {
    "APIKEY",
    "API_KEY",
    "CREDENTIAL",
    "CREDENTIALS",
    "PASSWORD",
    "PASSWD",
    "PRIVATE_KEY",
    "SECRET",
    "TOKEN",
}
_ALWAYS_PRIVATE_ENV_NAMES = {"CODE_AGENT_ENV_FILE"}


def environment_name_is_sensitive(name: str) -> bool:
    """Return whether an environment-variable name is likely to hold a credential."""
    normalized = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    if normalized in _ALWAYS_PRIVATE_ENV_NAMES:
        return True
    if normalized in _SENSITIVE_NAME_PARTS:
        return True
    return any(
        normalized == part
        or normalized.startswith(f"{part}_")
        or normalized.endswith(f"_{part}")
        or f"_{part}_" in normalized
        for part in _SENSITIVE_NAME_PARTS
    )


def sanitized_subprocess_env(source: Mapping[str, str]) -> dict[str, str]:
    """Keep the normal toolchain environment while withholding credential-like values."""
    return {
        name: value
        for name, value in source.items()
        if not environment_name_is_sensitive(name)
    }


class SecretRedactor:
    """Remove known secret values from strings and nested log/tool payloads."""

    marker = "[REDACTED]"

    def __init__(self, secrets: list[str] | tuple[str, ...] = ()):
        # Longest first handles the uncommon case where one credential contains another.
        self._secrets = tuple(
            sorted({secret for secret in secrets if len(secret) >= 4}, key=len, reverse=True)
        )

    def text(self, value: str) -> str:
        redacted = value
        for secret in self._secrets:
            redacted = redacted.replace(secret, self.marker)
        return redacted

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {key: self.value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.value(item) for item in value)
        return value
