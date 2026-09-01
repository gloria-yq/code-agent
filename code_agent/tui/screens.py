"""Modal screens for approvals and provider configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.content import Content
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label, Select, Static, Switch

from ..settings import UserSettings
from ..conversation import ConversationSummary


@dataclass(frozen=True)
class ConnectionForm:
    provider: str
    api_key: str
    base_url: str
    model: str
    thinking: bool


@dataclass(frozen=True)
class ProcessAction:
    action: str
    process_id: str


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
                yield Label(self.tool, classes="approval-tool", markup=False)
                yield Static(
                    json.dumps(self.arguments, ensure_ascii=False, indent=2, default=str),
                    classes="approval-arguments",
                    markup=False,
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
                    yield Static(self.error, classes="form-error", markup=False)
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
                    [
                        (Content.from_text(model, markup=False), model)
                        for model in dict.fromkeys(suggestions)
                    ],
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


class PermissionScreen(DismissibleModalScreen):
    DESCRIPTIONS = {
        "suggest": "Ask before every file change and command execution.",
        "auto-edit": "Apply file changes automatically; ask before commands. Recommended.",
        "full": (
            "Apply file changes and run commands without approval. Recognized destructive "
            "commands remain blocked."
        ),
    }

    def __init__(self, current_mode: str):
        super().__init__()
        self.current_mode = current_mode

    def compose(self) -> ComposeResult:
        with Container(classes="modal permission-modal"):
            with Horizontal(classes="modal-header"):
                yield Label("Permission mode", classes="modal-title")
                yield Button("X", id="dismiss", classes="modal-close", compact=True)
            with VerticalScroll(classes="modal-body"):
                yield Label(
                    "Choose how Code Agent approves local changes and commands.",
                    classes="helper",
                )
                yield Label("Mode", classes="field-label")
                yield Select(
                    [
                        ("Suggest — confirm changes and commands", "suggest"),
                        ("Auto-edit — confirm commands", "auto-edit"),
                        ("Full — no approval prompts", "full"),
                    ],
                    value=self.current_mode,
                    allow_blank=False,
                    id="permission-mode",
                )
                yield Static(
                    self.DESCRIPTIONS[self.current_mode],
                    id="permission-description",
                    classes="permission-description",
                )
                yield Label(
                    "The new mode applies immediately and is saved for future sessions.",
                    classes="helper",
                )
            with Horizontal(classes="modal-actions"):
                yield Button("Back", id="cancel", compact=True)
                yield Button("Apply mode", id="save", variant="success", compact=True)

    @on(Select.Changed, "#permission-mode")
    def selected(self, event: Select.Changed) -> None:
        mode = str(event.value)
        if mode in self.DESCRIPTIONS:
            self.query_one("#permission-description", Static).update(
                self.DESCRIPTIONS[mode]
            )

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        if event.button.id in {"cancel", "dismiss"}:
            self.dismiss(None)
        elif event.button.id == "save":
            mode = str(self.query_one("#permission-mode", Select).value)
            self.dismiss(mode if mode in self.DESCRIPTIONS else None)


class SessionScreen(DismissibleModalScreen):
    """Workspace-scoped conversation picker with a compact transcript preview."""

    def __init__(self, sessions: tuple[ConversationSummary, ...]):
        super().__init__()
        self.sessions = sessions
        self._by_id = {session.session_id: session for session in sessions}
        self.selected_id = sessions[0].session_id if sessions else None

    def compose(self) -> ComposeResult:
        with Container(classes="modal session-modal"):
            with Horizontal(classes="modal-header"):
                yield Label("Resume conversation", classes="modal-title")
                yield Button("X", id="dismiss", classes="modal-close", compact=True)
            with VerticalScroll(classes="modal-body"):
                yield Label(
                    "Saved conversations for the current workspace. Select one to preview it.",
                    classes="helper",
                )
                if self.sessions:
                    yield Label("Conversation", classes="field-label")
                    yield Select(
                        [
                            (
                                Content.from_text(
                                    self._option_label(session), markup=False
                                ),
                                session.session_id,
                            )
                            for session in self.sessions
                        ],
                        value=self.selected_id,
                        allow_blank=False,
                        id="session-select",
                    )
                    yield Static(
                        "", id="session-preview", classes="session-preview", markup=False
                    )
                else:
                    yield Static(
                        "No saved conversations exist in this workspace yet.\n"
                        "Send a message to create one automatically.",
                        classes="session-empty",
                    )
            with Horizontal(classes="modal-actions"):
                yield Button("Back", id="cancel", compact=True)
                yield Button(
                    "Resume",
                    id="resume",
                    variant="success",
                    compact=True,
                    disabled=not self.sessions,
                )

    def on_mount(self) -> None:
        self._update_preview()
        if self.sessions:
            self.query_one("#session-select", Select).focus()
        else:
            self.query_one("#cancel", Button).focus()

    @on(Select.Changed, "#session-select")
    def selected(self, event: Select.Changed) -> None:
        value = str(event.value)
        if value in self._by_id:
            self.selected_id = value
            self._update_preview()

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        if event.button.id in {"cancel", "dismiss"}:
            self.dismiss(None)
        elif event.button.id == "resume" and self.selected_id:
            self.dismiss(self.selected_id)

    def _update_preview(self) -> None:
        if not self.selected_id or self.selected_id not in self._by_id:
            return
        preview = self.query_one("#session-preview", Static)
        session = self._by_id[self.selected_id]
        lines = [
            f"Updated: {self._display_time(session.updated_at)}",
            f"Messages: {session.message_count} · Tool results: {session.tool_calls}",
            "",
        ]
        for role, content in session.preview:
            label = "YOU" if role == "user" else "ASSISTANT"
            lines.append(f"{label}  {content}")
        preview.update("\n".join(lines))

    @staticmethod
    def _display_time(value: str) -> str:
        if not value:
            return "unknown"
        try:
            return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value[:19].replace("T", " ")

    @classmethod
    def _option_label(cls, session: ConversationSummary) -> str:
        return f"{session.title}  ·  {cls._display_time(session.updated_at)}"


class ProcessScreen(DismissibleModalScreen):
    """Visible lifecycle controls for applications launched by the agent."""

    def __init__(self, processes: tuple[dict[str, Any], ...]):
        super().__init__()
        self.processes = processes
        self._by_id = {str(item["process_id"]): item for item in processes}
        self.selected_id = str(processes[0]["process_id"]) if processes else None

    def compose(self) -> ComposeResult:
        with Container(classes="modal process-modal"):
            with Horizontal(classes="modal-header"):
                yield Label("Running applications", classes="modal-title")
                yield Button("X", id="dismiss", classes="modal-close", compact=True)
            with VerticalScroll(classes="modal-body"):
                yield Label(
                    "Applications launched in this workspace remain separate from the chat.",
                    classes="helper",
                )
                if self.processes:
                    yield Label("Application", classes="field-label")
                    yield Select(
                        [
                            (
                                Content.from_text(self._option_label(item), markup=False),
                                str(item["process_id"]),
                            )
                            for item in self.processes
                        ],
                        value=self.selected_id,
                        allow_blank=False,
                        id="process-select",
                    )
                    yield Static(
                        "", id="process-preview", classes="process-preview", markup=False
                    )
                else:
                    yield Static(
                        "No applications have been launched in this workspace.\n"
                        "Ask Code Agent to run and show the completed program.",
                        classes="process-empty",
                    )
            with Horizontal(classes="modal-actions"):
                yield Button("Back", id="cancel", compact=True)
                yield Button(
                    "Open preview",
                    id="open",
                    compact=True,
                    disabled=not self._can_open(),
                )
                yield Button(
                    "Stop",
                    id="stop",
                    variant="error",
                    compact=True,
                    disabled=not self._can_stop(),
                )

    def on_mount(self) -> None:
        self._update_preview()
        if self.processes:
            self.query_one("#process-select", Select).focus()
        else:
            self.query_one("#cancel", Button).focus()

    @on(Select.Changed, "#process-select")
    def selected(self, event: Select.Changed) -> None:
        value = str(event.value)
        if value in self._by_id:
            self.selected_id = value
            self._update_preview()

    @on(Button.Pressed)
    def choose(self, event: Button.Pressed) -> None:
        if event.button.id in {"cancel", "dismiss"}:
            self.dismiss(None)
        elif event.button.id in {"open", "stop"} and self.selected_id:
            self.dismiss(ProcessAction(event.button.id, self.selected_id))

    def _selected(self) -> dict[str, Any] | None:
        return self._by_id.get(self.selected_id or "")

    def _can_open(self) -> bool:
        item = self._selected()
        return bool(item and item.get("status") == "running" and item.get("url"))

    def _can_stop(self) -> bool:
        item = self._selected()
        return bool(item and item.get("status") == "running")

    def _update_preview(self) -> None:
        item = self._selected()
        if not item:
            return
        lines = [
            f"Status: {str(item.get('status', 'unknown')).upper()}",
            f"Type: {item.get('mode', 'unknown')} · PID: {item.get('pid', 'unknown')}",
            f"Command: {item.get('command', '')}",
            f"Working directory: {item.get('cwd', '.')}",
        ]
        if item.get("url"):
            lines.append(f"URL: {item['url']}")
        logs = str(item.get("logs") or "").strip()
        if logs:
            lines.extend(("", "Recent logs:", logs[-2000:]))
        self.query_one("#process-preview", Static).update("\n".join(lines))
        self.query_one("#open", Button).disabled = not self._can_open()
        self.query_one("#stop", Button).disabled = not self._can_stop()

    @staticmethod
    def _option_label(item: dict[str, Any]) -> str:
        return (
            f"{item.get('name', 'Application')}  ·  "
            f"{str(item.get('status', 'unknown')).upper()}  ·  {item.get('mode', 'unknown')}"
        )


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
                        [
                            (Content.from_text(path, markup=False), path)
                            for path in self.recent
                        ],
                        prompt="Choose a recent workspace",
                        id="workspace-recent",
                    )
                yield Label("Workspace path", classes="field-label")
                yield Input(value=str(self.current), id="workspace-path")
                yield Static("", id="workspace-error", classes="form-error", markup=False)
                yield Label(
                    f"Browse directories under {tree_root}",
                    classes="field-label",
                    markup=False,
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
                yield Static("\n".join(lines), classes="config-summary", markup=False)
                yield Label("Secret values are never displayed.", classes="helper")
            with Horizontal(classes="modal-actions"):
                yield Button("Back", id="close", variant="primary", compact=True)

    @on(Button.Pressed)
    def close(self) -> None:
        self.dismiss(None)
