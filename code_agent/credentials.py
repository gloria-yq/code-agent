"""Credential storage abstraction backed by the operating-system keyring."""

from __future__ import annotations

from typing import Protocol

import keyring
from keyring.errors import KeyringError

from .errors import ConfigurationError


class CredentialStore(Protocol):
    def get(self, provider: str) -> str | None: ...

    def set(self, provider: str, api_key: str) -> None: ...

    def delete(self, provider: str) -> None: ...


class KeyringCredentialStore:
    """Store one provider credential per OS user without writing it to the project."""

    service_name = "code-agent"

    def get(self, provider: str) -> str | None:
        try:
            value = keyring.get_password(self.service_name, provider)
        except KeyringError as exc:
            raise ConfigurationError(f"Cannot read the system credential store: {exc}") from exc
        return value.strip() if value and value.strip() else None

    def set(self, provider: str, api_key: str) -> None:
        value = api_key.strip()
        if not value:
            raise ConfigurationError("API key cannot be empty.")
        try:
            keyring.set_password(self.service_name, provider, value)
        except KeyringError as exc:
            raise ConfigurationError(f"Cannot write the system credential store: {exc}") from exc

    def delete(self, provider: str) -> None:
        try:
            keyring.delete_password(self.service_name, provider)
        except keyring.errors.PasswordDeleteError:
            return
        except KeyringError as exc:
            raise ConfigurationError(f"Cannot update the system credential store: {exc}") from exc
