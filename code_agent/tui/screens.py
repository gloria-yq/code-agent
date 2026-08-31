"""Modal screens for approvals and provider configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, Switch

from ..settings import UserSettings


@dataclass(frozen=True)
class ConnectionForm:
    provider: str
    api_key: str
    base_url: str
    model: str
    thinking: bool


class ApprovalScreen(ModalScreen[bool]):
    def __init__(self, tool: str, arguments: dict[str, Any]):
        super().__init__()
        self.tool = tool
        self.arguments = arguments

    def compose(self) -> ComposeResult:
        with Container(classes="modal approval-modal"):
            yield Label("Approval required", classes="modal-title")
            yield Label(self.tool, classes="approval-tool")
            yield Static(
                json.dumps(self.arguments, ensure_ascii=False, indent=2, default=str),
                classes="approval-arguments",
            )
            yield Label("Review the complete action before allowing it.", classes="helper")
            with Horizontal(classes="modal-actions"):
                yield Button("Reject", id="reject", variant="error")
                yield Button("Allow once", id="allow", variant="success")

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        if event.button.id == "allow":
            self.dismiss(True)
        elif event.button.id == "reject":
            self.dismiss(False)


class ConnectScreen(ModalScreen[ConnectionForm | None]):
    def __init__(self, settings: UserSettings, error: str | None = None):
        super().__init__()
        self.settings = settings
        self.error = error

    def compose(self) -> ComposeResult:
        current = self.settings.providers[self.settings.default_provider]
        with Container(classes="modal connect-modal"):
            yield Label("Connect a model provider", classes="modal-title")
            yield Label(
                "The API key is stored in your operating-system credential store.",
                classes="helper",
            )
            if self.error:
                yield Static(self.error, classes="form-error")
            with Vertical(classes="form-fields"):
                yield Label("Provider", classes="field-label")
                yield Select(
                    [("DeepSeek", "deepseek"), ("OpenAI", "openai")],
                    value=self.settings.default_provider,
                    allow_blank=False,
                    id="provider",
                )
                yield Label("API key", classes="field-label")
                yield Input(password=True, placeholder="Paste key", id="api-key")
                yield Label("Base URL", classes="field-label")
                yield Input(value=current.base_url, id="base-url")
                yield Label("Model", classes="field-label")
                yield Input(value=current.model, id="model")
                with Horizontal(classes="switch-row"):
                    yield Label("Thinking mode", classes="field-label")
                    yield Switch(value=current.thinking, id="thinking")
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Test and save", id="save", variant="success")

    @on(Select.Changed, "#provider")
    def provider_changed(self, event: Select.Changed) -> None:
        provider = str(event.value)
        if provider not in self.settings.providers:
            return
        selected = self.settings.providers[provider]
        self.query_one("#base-url", Input).value = selected.base_url
        self.query_one("#model", Input).value = selected.model
        self.query_one("#thinking", Switch).value = selected.thinking

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id != "save":
            return
        provider = str(self.query_one("#provider", Select).value)
        self.dismiss(
            ConnectionForm(
                provider=provider,
                api_key=self.query_one("#api-key", Input).value,
                base_url=self.query_one("#base-url", Input).value.strip(),
                model=self.query_one("#model", Input).value.strip(),
                thinking=self.query_one("#thinking", Switch).value,
            )
        )


class ModelScreen(ModalScreen[str | None]):
    def __init__(self, provider: str, current_model: str):
        super().__init__()
        self.provider = provider
        self.current_model = current_model

    def compose(self) -> ComposeResult:
        suggestions = (
            ["deepseek-v4-flash", "deepseek-v4-pro"]
            if self.provider == "deepseek"
            else [self.current_model]
        )
        with Container(classes="modal model-modal"):
            yield Label("Select model", classes="modal-title")
            yield Select(
                [(model, model) for model in dict.fromkeys(suggestions)],
                value=self.current_model,
                allow_blank=False,
                id="model-select",
            )
            yield Label("You can enter another provider-supported model name.", classes="helper")
            yield Input(value=self.current_model, id="custom-model")
            with Horizontal(classes="modal-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Use model", id="save", variant="success")

    @on(Select.Changed, "#model-select")
    def selected(self, event: Select.Changed) -> None:
        self.query_one("#custom-model", Input).value = str(event.value)

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            self.dismiss(self.query_one("#custom-model", Input).value.strip() or None)


class ConfigScreen(ModalScreen[None]):
    def __init__(self, settings: UserSettings, credential_source: str | None):
        super().__init__()
        self.settings = settings
        self.credential_source = credential_source

    def compose(self) -> ComposeResult:
        provider = self.settings.default_provider
        selected = self.settings.providers[provider]
        lines = [
            f"Provider: {provider}",
            f"Model: {selected.model}",
            f"Base URL: {selected.base_url}",
            f"Thinking: {'enabled' if selected.thinking else 'disabled'}",
            f"Approval: {self.settings.approval_mode}",
            f"Credential: {self.credential_source or 'not configured'}",
        ]
        with Container(classes="modal config-modal"):
            yield Label("Configuration", classes="modal-title")
            yield Static("\n".join(lines), classes="config-summary")
            yield Label("Secret values are never displayed.", classes="helper")
            yield Button("Close", id="close", variant="primary")

    @on(Button.Pressed, "#close")
    def close(self) -> None:
        self.dismiss(None)
