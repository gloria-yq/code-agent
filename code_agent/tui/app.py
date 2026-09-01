"""Keyboard-first Textual application over the independent agent runtime."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from ..agent import AgentResult
from ..config import AgentConfig
from ..errors import (
    CodeAgentError,
    ConfigurationError,
    MissingCredentialError,
    ProcessError,
)
from ..events import AgentEvent
from ..service import AgentRuntime, create_runtime, test_model_connection
from ..settings import SettingsService
from .screens import (
    ApprovalScreen,
    ConfigScreen,
    ConnectScreen,
    ConnectionForm,
    ModelScreen,
    PermissionScreen,
    ProcessAction,
    ProcessScreen,
    SessionScreen,
    WorkspaceScreen,
)
from .widgets import Composer, MessageBlock, ToolCard


HELP_TEXT = """### Local commands

- `/connect` configure or replace a provider credential
- `/models` select the active model
- `/config` inspect non-secret settings
- `/permissions` change approval behavior without leaving the TUI
- `/resume` browse and restore conversations saved in this workspace
- `/processes` inspect, reopen, or stop applications launched by the agent
- `/workspace` switch the single local workspace and start a new conversation
- `/disconnect` remove the active provider credential
- `/new` clear this conversation
- `/status` show session counters
- `/help` show this help
- `/exit` leave Code Agent

Use **Enter** to send, **Shift+Enter** for a new line, **Ctrl+O** to choose a workspace,
**Esc** to stop a running turn or close a dialog, **Ctrl+C** for terminal copy, and
**Ctrl+Q** to exit.
"""


class CodeAgentApp(App[None]):
    TITLE = "Code Agent"
    SUB_TITLE = "Local coding workspace"

    CSS = """
    Screen {
        background: #020617;
        color: #f8fafc;
        layout: vertical;
    }

    #topbar {
        height: 3;
        padding: 1 2;
        background: #0f172a;
        color: #f8fafc;
        border-bottom: solid #334155;
        text-style: bold;
    }

    #conversation {
        height: 1fr;
        padding: 1 2 2 2;
        scrollbar-color: #475569;
        scrollbar-color-hover: #22c55e;
    }

    .message {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1 1 1;
        border-left: thick #334155;
        background: #0f172a;
    }

    .message.user { border-left: thick #38bdf8; }
    .message.assistant { border-left: thick #22c55e; }
    .message.system { border-left: thick #f59e0b; }

    .message-role {
        height: 1;
        margin-bottom: 1;
        color: #94a3b8;
        text-style: bold;
    }

    .message-content { height: auto; background: transparent; }

    .tool-card {
        width: 100%;
        margin: 0 0 1 2;
        border: solid #475569;
        background: #0b1220;
    }
    .tool-card.running { border: solid #f59e0b; }
    .tool-card.completed { border: solid #22c55e; }
    .tool-card.failed { border: solid #ef4444; }
    .tool-body { padding: 1; color: #cbd5e1; }

    #composer-label {
        height: 1;
        margin: 0 2;
        color: #94a3b8;
    }

    #composer {
        height: 6;
        margin: 0 2;
        border: solid #475569;
        background: #0f172a;
        color: #f8fafc;
    }
    #composer:focus { border: solid #22c55e; }
    #composer:disabled { opacity: 50%; }

    #statusbar {
        height: 2;
        padding: 0 2;
        color: #cbd5e1;
        background: #1e293b;
        border-top: solid #334155;
    }

    ModalScreen { align: center middle; background: #020617 70%; }
    .modal {
        width: 72;
        max-width: 92%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        background: #0f172a;
        border: solid #475569;
    }
    .modal-header {
        height: 4;
        border-bottom: solid #334155;
        margin-bottom: 1;
        align-vertical: middle;
    }
    .modal-title {
        width: 1fr;
        height: 3;
        content-align: left middle;
        color: #f8fafc;
        text-style: bold;
    }
    .modal-header .modal-close {
        width: 5;
        min-width: 5;
        height: 1;
        margin: 0;
        color: #0f172a;
        background: #f8fafc;
        border: none;
        content-align: center middle;
        text-align: center;
        text-style: bold;
    }
    .modal-header .modal-close:hover {
        color: #0f172a;
        background: #e2e8f0;
        border: none;
    }
    .modal-header .modal-close:focus {
        color: #0f172a;
        background: #cbd5e1;
        border: none;
        outline: none;
    }
    .modal-body {
        height: 1fr;
        scrollbar-color: #475569;
        scrollbar-color-hover: #22c55e;
    }
    .helper { color: #94a3b8; margin-bottom: 1; height: auto; }
    .form-error { color: #fca5a5; border-left: thick #ef4444; padding-left: 1; }
    .field-label { color: #cbd5e1; height: 1; margin-top: 1; }
    .form-fields { height: auto; }
    .form-fields Input, .form-fields Select { width: 100%; }
    .switch-row { height: 3; align-vertical: middle; }
    .switch-row Label { width: 1fr; }
    .modal-actions {
        height: 4;
        margin-top: 1;
        align-horizontal: right;
        align-vertical: bottom;
        border-top: solid #334155;
    }
    .modal-actions Button {
        height: 3;
        margin-left: 1;
        min-width: 16;
        content-align: center middle;
        text-align: center;
    }
    .modal-actions Button:focus { outline: tall #22c55e; }
    .approval-tool { color: #fbbf24; text-style: bold; }
    .approval-arguments, .config-summary {
        height: auto;
        max-height: 18;
        padding: 1;
        margin: 1 0;
        background: #020617;
        color: #e2e8f0;
        border: solid #334155;
        overflow-y: auto;
    }
    .connect-modal { height: 90%; }
    .approval-modal { height: 80%; }
    .model-modal { width: 64; height: 22; }
    .config-modal { width: 64; height: 20; }
    .permission-modal { width: 72; height: 22; }
    .session-modal { width: 88%; height: 82%; }
    .process-modal { width: 90%; height: 84%; }
    .session-preview, .session-empty {
        height: auto;
        min-height: 10;
        margin: 1 0;
        padding: 1;
        color: #e2e8f0;
        background: #020617;
        border: solid #334155;
    }
    .process-preview, .process-empty {
        height: auto;
        min-height: 12;
        margin: 1 0;
        padding: 1;
        color: #e2e8f0;
        background: #020617;
        border: solid #334155;
    }
    .permission-description {
        height: auto;
        min-height: 4;
        margin: 1 0;
        padding: 1;
        color: #e2e8f0;
        background: #020617;
        border: solid #334155;
    }
    .workspace-modal { width: 90%; height: 90%; }
    .workspace-body { height: 1fr; }
    .workspace-modal DirectoryTree {
        height: 1fr;
        margin: 1 0;
        border: solid #334155;
        background: #020617;
    }
    #workspace-error { display: none; }
    #workspace-error.visible { display: block; }
    """

    BINDINGS = [
        Binding("escape", "cancel_turn", "Stop turn", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
        Binding("ctrl+p", "connect", "Connect", show=True),
        Binding("ctrl+o", "workspace", "Workspace", show=True),
    ]

    def __init__(
        self,
        workspace: str | Path,
        *,
        settings: SettingsService | None = None,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        deepseek_thinking: str | None = None,
        max_turns: int = 24,
        approval_mode: str | None = None,
        session_log: bool = True,
    ):
        super().__init__()
        self.workspace = Path(workspace).expanduser().resolve()
        self.settings = settings or SettingsService()
        self.overrides = {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "deepseek_thinking": deepseek_thinking,
            "max_turns": max_turns,
            "approval_mode": approval_mode,
        }
        self.session_log = session_log
        self.runtime: AgentRuntime | None = None
        self.config: AgentConfig | None = None
        self.busy = False
        self._ui_thread = 0
        self._assistant: MessageBlock | None = None
        self._assistant_pending = ""
        self._tool_cards: dict[str, ToolCard] = {}
        self._pending_workspace: Path | None = None

    def compose(self) -> ComposeResult:
        yield Static("Code Agent", id="topbar")
        yield VerticalScroll(id="conversation")
        yield Label("MESSAGE  Enter sends · Shift+Enter adds a line", id="composer-label")
        yield Composer(id="composer", placeholder="Describe a coding task or type /help")
        yield Static("Loading configuration…", id="statusbar")

    def on_mount(self) -> None:
        self._ui_thread = threading.get_ident()
        self.set_interval(0.05, self._flush_assistant)
        self.query_one(Composer).focus()
        self._append_message(
            "system",
            "Ready for a real coding task. Tool actions stay visible and commands require "
            "approval in the default mode. Type /resume to reopen a saved conversation.",
        )
        self._load_runtime()

    def _load_runtime(self) -> None:
        try:
            config = self.settings.resolve(self.workspace, **self.overrides)
        except MissingCredentialError:
            self._set_status("No provider connected")
            self.action_connect(
                "No global provider credential is configured. Connect once to test "
                "the provider and store its API key in the operating-system credential "
                "store for reuse across workspaces."
            )
            return
        except ConfigurationError as exc:
            self._set_status("No provider connected")
            self.action_connect(str(exc))
            return
        self._activate(config)

    def _activate(self, config: AgentConfig) -> None:
        existing_processes = None
        if self.runtime and self.config and self.config.workspace == config.workspace:
            existing_processes = getattr(self.runtime, "processes", None)
        runtime = create_runtime(
            config,
            confirm=self._confirm_from_worker,
            on_event=self._receive_agent_event,
            session_log=self.session_log,
            processes=existing_processes,
        )
        self.workspace = config.workspace
        self.config = config
        self.runtime = runtime
        self._set_status("Ready")
        self._refresh_topbar()
        self.query_one(Composer).disabled = False
        self.query_one(Composer).focus()

    def _refresh_topbar(self) -> None:
        if not self.config:
            title = f"Code Agent  ·  {self.workspace.name}  ·  not connected"
        else:
            title = (
                f"Code Agent  ·  {self.workspace.name}  ·  "
                f"{self.config.provider}/{self.config.model}"
            )
        self.query_one("#topbar", Static).update(title)

    @on(Composer.Submitted)
    def submit(self, event: Composer.Submitted) -> None:
        text = event.text.strip()
        if text.startswith("/"):
            self._route_command(text)
            return
        if self.busy:
            self.notify("A turn is already running. Press Esc to stop it.", severity="warning")
            return
        if not self.runtime:
            self.action_connect("Connect a provider before sending a task.")
            return
        composer = self.query_one(Composer)
        self._append_message("user", text)
        composer.clear()
        composer.disabled = True
        self.busy = True
        self._set_status("Working · Esc stops at the next safe boundary")
        self.run_agent(text)

    @work(thread=True, group="agent-turn", exclusive=True)
    def run_agent(self, task: str) -> None:
        assert self.runtime is not None
        try:
            result = self.runtime.agent.run(task)
        except Exception as exc:  # unexpected failures must restore the input surface
            self.call_from_thread(self._worker_failed, str(exc))
            return
        self.call_from_thread(self._turn_finished, result)

    def _turn_finished(self, result: AgentResult) -> None:
        self.busy = False
        composer = self.query_one(Composer)
        composer.disabled = False
        composer.focus()
        self._set_status(
            f"{result.status} · {result.turns} model turns · {result.tool_calls} tool calls"
        )

    def _worker_failed(self, error: str) -> None:
        self.busy = False
        self.query_one(Composer).disabled = False
        self._append_message("system", f"Unexpected local error: {error}")
        self._set_status("Failed · see error above")

    def _receive_agent_event(self, event: AgentEvent) -> None:
        if threading.get_ident() == self._ui_thread:
            self._handle_agent_event(event)
        else:
            self.call_from_thread(self._handle_agent_event, event)

    def _handle_agent_event(self, event: AgentEvent) -> None:
        data = event.data
        if event.kind == "model.started":
            self._assistant = self._append_message("assistant", "")
            self._assistant_pending = ""
            self._set_status(f"Thinking · model turn {data.get('turn', '?')}")
        elif event.kind == "model.delta":
            if data.get("delta_kind") == "content":
                self._assistant_pending += str(data.get("content", ""))
            elif data.get("delta_kind") == "reasoning":
                self._set_status("Thinking…")
        elif event.kind == "model.completed":
            self._flush_assistant()
            content = str(data.get("content", ""))
            if self._assistant and not self._assistant.content:
                self._assistant.replace(content or "Requesting a local tool…")
        elif event.kind == "tool.requested":
            card = ToolCard(
                str(data.get("call_id", "")),
                str(data.get("tool", "unknown")),
                str(data.get("arguments", "{}")),
            )
            self._tool_cards[card.call_id] = card
            self.query_one("#conversation", VerticalScroll).mount(card)
            self._scroll_end()
        elif event.kind == "tool.completed":
            card = self._tool_cards.get(str(data.get("call_id", "")))
            if card:
                card.finish(result=data.get("result") or {})
        elif event.kind == "tool.failed":
            card = self._tool_cards.get(str(data.get("call_id", "")))
            if card:
                card.finish(error=str(data.get("error", "Tool failed")))
        elif event.kind == "turn.failed":
            self._append_message("system", str(data.get("error", "Turn failed")))
        elif event.kind == "turn.interrupted":
            self._append_message("system", "Turn stopped; partial conversation state was rolled back.")

    def _flush_assistant(self) -> None:
        if self._assistant and self._assistant_pending:
            self._assistant.append(self._assistant_pending)
            self._assistant_pending = ""
            self._scroll_end()

    def _append_message(self, role: str, content: str) -> MessageBlock:
        block = MessageBlock(role, content)
        self.query_one("#conversation", VerticalScroll).mount(block)
        self._scroll_end()
        return block

    def _scroll_end(self) -> None:
        self.call_after_refresh(
            self.query_one("#conversation", VerticalScroll).scroll_end,
            animate=False,
        )

    def _set_status(self, text: str) -> None:
        mode = self.config.approval_mode if self.config else "unconfigured"
        self.query_one("#statusbar", Static).update(f"{mode}  ·  {text}")

    def _confirm_from_worker(self, spec, arguments) -> bool:
        answered = threading.Event()
        decision = {"allow": False}

        def receive(value: bool | None) -> None:
            decision["allow"] = bool(value)
            answered.set()

        self.call_from_thread(
            self.push_screen,
            ApprovalScreen(spec.name, arguments),
            receive,
        )
        answered.wait(timeout=600)
        return decision["allow"]

    def action_cancel_turn(self) -> None:
        if self.busy and self.runtime:
            self.runtime.agent.cancel()
            self._set_status("Stopping at the next safe boundary…")
        else:
            self.notify("No turn is currently running.")

    def action_connect(self, error: str | None = None) -> None:
        if self.busy:
            self.notify("Stop the current turn before changing providers.", severity="warning")
            return
        self.push_screen(ConnectScreen(self.settings.load(), error), self._connect_submitted)

    def _connect_submitted(self, form: ConnectionForm | None) -> None:
        if form is None:
            self._pending_workspace = None
            return
        self._set_status("Testing provider connection…")
        self.connect_provider(form)

    @work(thread=True, group="provider-connect", exclusive=True)
    def connect_provider(self, form: ConnectionForm) -> None:
        key_name = "DEEPSEEK_API_KEY" if form.provider == "deepseek" else "OPENAI_API_KEY"
        try:
            config = AgentConfig.from_mapping(
                self.workspace,
                {key_name: form.api_key},
                provider=form.provider,
                base_url=form.base_url,
                model=form.model,
                deepseek_thinking="enabled" if form.thinking else "disabled",
                approval_mode=self.settings.load().approval_mode,
            )
            reply = test_model_connection(config)
            if not reply.content.strip():
                raise ConfigurationError("The provider returned an empty test response.")
            self.settings.configure_provider(
                form.provider,
                api_key=form.api_key,
                base_url=form.base_url,
                model=form.model,
                thinking=form.thinking,
            )
        except CodeAgentError as exc:
            self.call_from_thread(self._connect_failed, str(exc))
            return
        self.call_from_thread(self._connect_succeeded)

    def _connect_failed(self, error: str) -> None:
        self._set_status("Connection failed")
        self.push_screen(ConnectScreen(self.settings.load(), error), self._connect_submitted)

    def _connect_succeeded(self) -> None:
        self.notify("Provider connected and stored securely.", severity="information")
        if self._pending_workspace is not None:
            workspace = self._pending_workspace
            self._pending_workspace = None
            self._workspace_selected(workspace)
            return
        self._load_runtime()

    def action_models(self) -> None:
        if not self.config or self.busy:
            self.notify("Connect a provider and stop the active turn first.", severity="warning")
            return
        self.push_screen(
            ModelScreen(self.config.provider, self.config.model), self._model_selected
        )

    def action_workspace(self) -> None:
        if self.busy:
            self.notify(
                "Stop the active turn before switching workspaces.", severity="warning"
            )
            return
        try:
            recent = self.settings.load().recent_workspaces
        except ConfigurationError as exc:
            self.notify(str(exc), severity="error")
            return
        self.push_screen(
            WorkspaceScreen(self.workspace, recent), self._workspace_selected
        )

    def action_permissions(self) -> None:
        if self.busy:
            self.notify(
                "Stop the active turn before changing permissions.", severity="warning"
            )
            return
        current = (
            self.config.approval_mode
            if self.config
            else self.settings.load().approval_mode
        )
        self.push_screen(PermissionScreen(current), self._permission_selected)

    def _permission_selected(self, mode: str | None) -> None:
        if not mode:
            return
        current = self.config.approval_mode if self.config else None
        if mode == current:
            self.notify(f"Permission mode is already {mode}.")
            return
        try:
            self.settings.select_approval_mode(mode)
        except ConfigurationError as exc:
            self.notify(str(exc), severity="error")
            return
        self.overrides["approval_mode"] = mode
        if self.config and self.runtime:
            self.config = replace(self.config, approval_mode=mode)
            self.runtime.agent.approvals.mode = mode
        self._set_status("Ready")
        self.notify(f"Permission mode changed to {mode}.")

    def action_sessions(self) -> None:
        if self.busy or not self.runtime:
            self.notify(
                "Connect a provider and stop the active turn before resuming a conversation.",
                severity="warning",
            )
            return
        try:
            sessions = self.runtime.agent.list_conversations()
        except CodeAgentError as exc:
            self.notify(str(exc), severity="error")
            return
        self.push_screen(SessionScreen(sessions), self._session_selected)

    def action_processes(self) -> None:
        manager = self._process_manager()
        if manager is None:
            self.notify("Connect a provider before managing applications.", severity="warning")
            return
        self.push_screen(ProcessScreen(manager.list()), self._process_action)

    def _process_action(self, action: ProcessAction | None) -> None:
        if action is None:
            return
        manager = self._process_manager()
        if manager is None:
            return
        try:
            if action.action == "open":
                manager.open(action.process_id)
                self.notify("Preview opened in the default browser.")
            elif action.action == "stop":
                manager.stop(action.process_id)
                self.notify("Application stopped.")
        except ProcessError as exc:
            self.notify(str(exc), severity="error")
            return
        self.push_screen(ProcessScreen(manager.list()), self._process_action)

    def _session_selected(self, session_id: str | None) -> None:
        if not session_id or not self.runtime:
            return
        try:
            self.runtime.agent.resume(session_id)
        except CodeAgentError as exc:
            self.notify(str(exc), severity="error")
            return
        self._render_restored_history(session_id)
        self._set_status("Conversation resumed")
        self.notify("Saved conversation restored.")

    def _render_restored_history(self, session_id: str) -> None:
        assert self.runtime is not None
        conversation = self.query_one("#conversation", VerticalScroll)
        conversation.remove_children()
        self._tool_cards.clear()
        self._assistant = None
        self._assistant_pending = ""
        self._append_message(
            "system", f"Resumed conversation `{session_id}` from this workspace."
        )
        hidden_tools = 0
        for message in self.runtime.agent.history()[1:]:
            role = str(message.get("role", ""))
            if role == "tool":
                hidden_tools += 1
                continue
            if role not in {"user", "assistant"}:
                continue
            content = str(message.get("content") or "").strip()
            if not content and role == "assistant" and message.get("tool_calls"):
                names = [
                    str(call.get("function", {}).get("name", "unknown"))
                    for call in message["tool_calls"]
                    if isinstance(call, dict)
                ]
                content = f"[Tool calls retained: {', '.join(names)}]"
            if content:
                self._append_message(role, content)
        if hidden_tools:
            self._append_message(
                "system",
                f"{hidden_tools} previous tool result(s) are retained in model context but "
                "collapsed from this restored transcript.",
            )

    def _workspace_selected(self, workspace: Path | None) -> None:
        if workspace is None:
            return
        workspace = workspace.expanduser().resolve()
        if workspace == self.workspace:
            self.notify("This workspace is already active.")
            return
        manager = self._process_manager()
        if manager is not None and manager.has_running():
            self.push_screen(
                ApprovalScreen(
                    "switch workspace",
                    {
                        "workspace": str(workspace),
                        "effect": "stop applications running in the current workspace",
                    },
                ),
                lambda allow: self._workspace_process_decided(workspace, allow),
            )
            return
        self._switch_workspace(workspace)

    def _workspace_process_decided(self, workspace: Path, allow: bool | None) -> None:
        if not allow:
            return
        manager = self._process_manager()
        if manager is not None:
            manager.stop_all()
        self._switch_workspace(workspace)

    def _switch_workspace(self, workspace: Path) -> None:
        previous_workspace = self.workspace
        try:
            config = self.settings.resolve(workspace, **self.overrides)
            self._activate(config)
        except MissingCredentialError:
            self._pending_workspace = workspace
            self.action_connect(
                "This workspace has no local API key. Connect once to store a provider "
                "credential in the operating-system credential store; after the test "
                "succeeds, the workspace switch will continue automatically."
            )
            return
        except (CodeAgentError, OSError) as exc:
            self.notify(f"Cannot switch workspace: {exc}", severity="error")
            return
        try:
            self.settings.remember_workspace(previous_workspace)
            self.settings.remember_workspace(workspace)
        except ConfigurationError as exc:
            self.notify(
                f"Workspace switched, but recent history was not saved: {exc}",
                severity="warning",
            )
        self._clear_conversation(
            f"Workspace switched to `{workspace}`. A new conversation was started."
        )
        self.notify(f"Workspace: {workspace}")

    def _model_selected(self, model: str | None) -> None:
        if not model or not self.config:
            return
        try:
            self.settings.select_model(self.config.provider, model)
            self._load_runtime()
        except ConfigurationError as exc:
            self.notify(str(exc), severity="error")
            return
        self._clear_conversation("Model changed; a new conversation was started.")

    def action_config(self) -> None:
        public = self.settings.load()
        source = self.settings.credential_source(public.default_provider, self.workspace)
        self.push_screen(ConfigScreen(public, source))

    def _route_command(self, command: str) -> None:
        name = command.split(maxsplit=1)[0].lower()
        if name == "/connect":
            self.action_connect()
        elif name == "/models":
            self.action_models()
        elif name == "/config":
            self.action_config()
        elif name in {"/permissions", "/permission"}:
            self.action_permissions()
        elif name in {"/resume", "/sessions", "/history"}:
            self.action_sessions()
        elif name in {"/processes", "/apps"}:
            self.action_processes()
        elif name == "/workspace":
            self.action_workspace()
        elif name == "/new":
            if self.runtime and not self.busy:
                self.runtime.agent.reset()
                self._clear_conversation("New conversation started.")
        elif name == "/status":
            stats = self.runtime.agent.stats() if self.runtime else {}
            self._append_message("system", " · ".join(f"{k}: {v}" for k, v in stats.items()))
        elif name == "/help":
            self._append_message("system", HELP_TEXT)
        elif name == "/disconnect":
            self._disconnect_active()
        elif name in {"/exit", "/quit", "/q"}:
            self.action_quit()
        else:
            self.notify(f"Unknown command: {name}. Use /help.", severity="warning")
        self.query_one(Composer).clear()

    def _disconnect_active(self) -> None:
        if not self.config or self.busy:
            self.notify("No idle provider connection is available.", severity="warning")
            return

        def decided(allow: bool | None) -> None:
            if not allow or not self.config:
                return
            try:
                manager = self._process_manager()
                if manager is not None:
                    manager.stop_all()
                self.settings.disconnect(self.config.provider)
            except ConfigurationError as exc:
                self.notify(str(exc), severity="error")
                return
            self.runtime = None
            self.config = None
            self._refresh_topbar()
            self._set_status("Credential removed")
            self.notify("Stored provider credential removed.")

        self.push_screen(
            ApprovalScreen(
                "disconnect provider",
                {
                    "provider": self.config.provider,
                    "effect": "stop applications launched in this workspace",
                },
            ),
            decided,
        )

    def action_quit(self) -> None:
        manager = self._process_manager()
        if manager is None or not manager.has_running():
            self.exit()
            return
        self.push_screen(
            ApprovalScreen(
                "exit Code Agent",
                {"effect": "stop all applications launched in this workspace"},
            ),
            self._quit_decided,
        )

    def _quit_decided(self, allow: bool | None) -> None:
        if not allow:
            return
        manager = self._process_manager()
        if manager is not None:
            manager.stop_all()
        self.exit()

    def _process_manager(self):
        return getattr(self.runtime, "processes", None) if self.runtime else None

    def _clear_conversation(self, notice: str) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        conversation.remove_children()
        self._tool_cards.clear()
        self._assistant = None
        self._assistant_pending = ""
        self.call_after_refresh(self._append_message, "system", notice)
