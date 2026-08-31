"""Modal screens for approvals and provider configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label, Select, Static, Switch

from ..settings import UserSettings


@dataclass(frozen=True)
class ConnectionForm:
    provider: str
    api_key: str
    base_url: str
    model: str
    thinking: bool


class DismissibleModalScreen(ModalScreen[Any]):
    """Modal with one predictable keyboard escape route."""

    BINDINGS = [Binding("escape", "cancel", "Back", show=False, priority=True)]

    def action_cancel(self) -> None:
        self.dismiss(None)


class ApprovalScreen(DismissibleModalScreen):
    def __init__(self, tool: str, arguments: dict[str, Any]):
        super().__init__()
        self.tool = tool
        self.arguments = arguments

    def compose(self) -> ComposeResult:
        with Container(classes="modal approval-modal"):
            with Horizontal(classes="modal-header"):
                yield Label("Approval required", classes="modal-title")
                yield Button("X", id="dismiss", classes="modal-close", compact=True)
            with VerticalScroll(classes="modal-body"):
                yield Label(self.tool, classes="approval-tool")
                yield Static(
                    json.dumps(self.arguments, ensure_ascii=False, indent=2, default=str),
                    classes="approval-arguments",
                )
                yield Label("Review the complete action before allowing it.", classes="helper")
            with Horizontal(classes="modal-actions"):
                yield Button("Reject", id="reject", variant="error", compact=True)
                yield Button("Allow once", id="allow", variant="success", compact=True)

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        if event.button.id == "allow":
            self.dismiss(True)
        elif event.button.id in {"reject", "dismiss"}:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConnectScreen(DismissibleModalScreen):
    def __init__(self, settings: UserSettings, error: str | None = None):
        super().__init__()
        self.settings = settings
        self.error = error

    def compose(self) -> ComposeResult:
        current = self.settings.providers[self.settings.default_provider]
        with Container(classes="modal connect-modal"):
            with Horizontal(classes="modal-header"):
                yield Label("Connect a model provider", classes="modal-title")
                yield Button("X", id="dismiss", classes="modal-close", compact=True)
            with VerticalScroll(classes="modal-body"):
                yield Label(
                    "The API key is stored in your operating-system credential store and "
                    "can be reused across workspaces.",
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
                yield Button("Back", id="cancel", compact=True)
                yield Button("Test and save", id="save", variant="success", compact=True)

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
        if event.button.id in {"cancel", "dismiss"}:
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


class ModelScreen(DismissibleModalScreen):
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
            with Horizontal(classes="modal-header"):
                yield Label("Select model", classes="modal-title")
                yield Button("X", id="dismiss", classes="modal-close", compact=True)
            with VerticalScroll(classes="modal-body"):
                yield Select(
                    [(model, model) for model in dict.fromkeys(suggestions)],
                    value=self.current_model,
                    allow_blank=False,
                    id="model-select",
                )
                yield Label("You can enter another provider-supported model name.", classes="helper")
                yield Input(value=self.current_model, id="custom-model")
            with Horizontal(classes="modal-actions"):
                yield Button("Back", id="cancel", compact=True)
                yield Button("Use model", id="save", variant="success", compact=True)

    @on(Select.Changed, "#model-select")
    def selected(self, event: Select.Changed) -> None:
        self.query_one("#custom-model", Input).value = str(event.value)

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        if event.button.id in {"cancel", "dismiss"}:
            self.dismiss(None)
        elif event.button.id == "save":
            self.dismiss(self.query_one("#custom-model", Input).value.strip() or None)


class WorkspaceScreen(DismissibleModalScreen):
    """Choose one validated root; selecting a tree node only fills the path field."""

    def __init__(self, current: Path, recent: tuple[str, ...] = ()):
        super().__init__()
        self.current = current.resolve()
        self.recent = tuple(
            path for path in recent if Path(path).expanduser().is_dir()
        )

    def compose(self) -> ComposeResult:
        tree_root = self.current.parent if self.current.parent.is_dir() else self.current
        with Container(classes="modal workspace-modal"):
            with Horizontal(classes="modal-header"):
                yield Label("Switch workspace", classes="modal-title")
                yield Button("X", id="dismiss", classes="modal-close", compact=True)
            with Vertical(classes="modal-body workspace-body"):
                yield Label(
                    "Switching rebuilds the local tool boundary and starts a new conversation.",
                    classes="helper",
                )
                if self.recent:
                    yield Label("Recent workspaces", classes="field-label")
                    yield Select(
                        [(path, path) for path in self.recent],
                        prompt="Choose a recent workspace",
                        id="workspace-recent",
                    )
                yield Label("Workspace path", classes="field-label")
                yield Input(value=str(self.current), id="workspace-path")
                yield Static("", id="workspace-error", classes="form-error")
                yield Label(
                    f"Browse directories under {tree_root}", classes="field-label"
                )
                yield DirectoryTree(tree_root, id="workspace-tree")
            with Horizontal(classes="modal-actions"):
                yield Button("Back", id="cancel", compact=True)
                yield Button("Switch workspace", id="switch", variant="success", compact=True)

    @on(Select.Changed, "#workspace-recent")
    def recent_changed(self, event: Select.Changed) -> None:
        if isinstance(event.value, str) and event.value in self.recent:
            self.query_one("#workspace-path", Input).value = event.value

    @on(DirectoryTree.DirectorySelected, "#workspace-tree")
    def directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.query_one("#workspace-path", Input).value = str(event.path)

    @on(Input.Submitted, "#workspace-path")
    def path_submitted(self) -> None:
        self._submit_path()

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        if event.button.id in {"cancel", "dismiss"}:
            self.dismiss(None)
        elif event.button.id == "switch":
            self._submit_path()

    def _submit_path(self) -> None:
        raw = self.query_one("#workspace-path", Input).value.strip()
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.current / candidate
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            self._show_error(f"Cannot resolve this path: {exc}")
            return
        if not resolved.is_dir():
            self._show_error("Choose an existing directory, not a file or missing path.")
            return
        self.dismiss(resolved)

    def _show_error(self, message: str) -> None:
        error = self.query_one("#workspace-error", Static)
        error.update(message)
        error.add_class("visible")


class ConfigScreen(DismissibleModalScreen):
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
            with Horizontal(classes="modal-header"):
                yield Label("Configuration", classes="modal-title")
                yield Button("X", id="dismiss", classes="modal-close", compact=True)
            with VerticalScroll(classes="modal-body"):
                yield Static("\n".join(lines), classes="config-summary")
                yield Label("Secret values are never displayed.", classes="helper")
            with Horizontal(classes="modal-actions"):
                yield Button("Back", id="close", variant="primary", compact=True)

    @on(Button.Pressed)
    def close(self) -> None:
        self.dismiss(None)
