import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from textual import on
from textual.app import App, ComposeResult

from code_agent.agent import AgentResult
from code_agent.config import AgentConfig
from code_agent.conversation import ConversationSummary
from code_agent.errors import ConfigurationError, MissingCredentialError
from code_agent.settings import UserSettings
from code_agent.tui.app import CodeAgentApp
from code_agent.tui.screens import (
    ApprovalScreen,
    ConfigScreen,
    ConnectScreen,
    ModelScreen,
    PermissionScreen,
    ProcessScreen,
    SessionScreen,
    WorkspaceScreen,
)
from code_agent.tui.widgets import Composer, MessageBlock


class FakeAgent:
    cancelled = False
    resumed = None
    saved_conversations = ()
    restored_history = [{"role": "system", "content": "system"}]

    def run(self, task):
        return AgentResult("completed", "done", 1, 0)

    def cancel(self):
        self.cancelled = True
        return None

    def reset(self):
        return None

    def stats(self):
        return {"user_turns": 0, "model_turns": 0, "tool_calls": 0, "messages": 0}

    def list_conversations(self):
        return self.saved_conversations

    def resume(self, session_id):
        self.resumed = session_id

    def history(self):
        return self.restored_history


class ConfiguredSettings:
    def __init__(self, config):
        self.config = config
        self.remembered: list[Path] = []
        self.approval_mode = config.approval_mode if config else "auto-edit"

    def resolve(self, workspace, **overrides):
        return replace(self.config, workspace=Path(workspace).resolve())

    def load(self):
        return replace(UserSettings(), approval_mode=self.approval_mode)

    def credential_source(self, provider, workspace):
        return "system-keyring"

    def remember_workspace(self, workspace):
        self.remembered.append(Path(workspace).resolve())
        return self.load()

    def select_approval_mode(self, mode):
        self.approval_mode = mode
        return self.load()


class MissingSettings(ConfiguredSettings):
    def resolve(self, workspace, **overrides):
        raise ConfigurationError("No model API key is set.")


class TargetCredentialSettings(ConfiguredSettings):
    def __init__(self, config, target):
        super().__init__(config)
        self.target = target.resolve()
        self.blocked = True

    def resolve(self, workspace, **overrides):
        if self.blocked and Path(workspace).resolve() == self.target:
            raise MissingCredentialError("No model API key is set.")
        return super().resolve(workspace, **overrides)


class FakeProcessManager:
    def __init__(self):
        self.opened = []
        self.stopped = []
        self.running = True

    def list(self):
        return (
            {
                "process_id": "app12345",
                "name": "Tic-Tac-Toe",
                "mode": "web",
                "status": "running" if self.running else "stopped",
                "pid": 1234,
                "command": "python server.py",
                "cwd": ".",
                "url": "http://127.0.0.1:8000",
                "logs": "ready",
            },
        )

    def open(self, process_id):
        self.opened.append(process_id)
        return self.list()[0]

    def stop(self, process_id):
        self.stopped.append(process_id)
        self.running = False
        return self.list()[0]

    def has_running(self):
        return self.running

    def stop_all(self):
        self.running = False


class ComposerHarness(App[None]):
    def __init__(self):
        super().__init__()
        self.submissions: list[str] = []

    def compose(self) -> ComposeResult:
        yield Composer(id="composer")

    @on(Composer.Submitted)
    def submitted(self, event: Composer.Submitted) -> None:
        self.submissions.append(event.text)


class TuiSmokeTests(unittest.IsolatedAsyncioTestCase):
    def assert_actions_visible(self, screen, action_ids):
        footer_regions = []
        for action_id in action_ids:
            button = screen.query_one(f"#{action_id}")
            if action_id == "dismiss":
                self.assertTrue(button.compact, action_id)
                self.assertEqual(str(button.label), "X")
            else:
                self.assertTrue(button.compact, action_id)
            self.assertGreater(button.region.width, 0, action_id)
            self.assertGreater(button.region.height, 0, action_id)
            self.assertGreaterEqual(button.region.y, 0, action_id)
            self.assertLessEqual(
                button.region.y + button.region.height,
                screen.size.height,
                action_id,
            )
            if action_id != "dismiss":
                footer_regions.append((button.region.y, button.region.height))
        self.assertEqual(len(set(footer_regions)), 1)

    async def test_enter_submits_and_shift_enter_inserts_newline(self):
        app = ComposerHarness()
        async with app.run_test(size=(80, 12)) as pilot:
            composer = app.query_one(Composer)
            composer.focus()
            composer.text = "send this"
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.submissions, ["send this"])

            composer.clear()
            await pilot.press("shift+enter")
            await pilot.pause()
            self.assertEqual(composer.text, "\n")
            self.assertEqual(app.submissions, ["send this"])

    async def test_ctrl_enter_remains_an_alternate_submit_shortcut(self):
        app = ComposerHarness()
        async with app.run_test(size=(80, 12)) as pilot:
            composer = app.query_one(Composer)
            composer.focus()
            composer.text = "alternate"
            await pilot.press("ctrl+enter")
            await pilot.pause()
            self.assertEqual(app.submissions, ["alternate"])

    async def test_ctrl_c_is_free_and_escape_stops_a_running_turn(self):
        declared_keys = {binding.key for binding in CodeAgentApp.BINDINGS}
        self.assertNotIn("ctrl+c", declared_keys)
        self.assertIn("escape", declared_keys)

        root = Path.cwd()
        config = AgentConfig(
            api_key="not-a-real-secret",
            base_url="https://example.test/v1",
            model="test-model",
            workspace=root,
        )
        app = CodeAgentApp(
            root, settings=ConfiguredSettings(config), session_log=False
        )
        agent = FakeAgent()
        runtime = SimpleNamespace(agent=agent)
        with patch("code_agent.tui.app.create_runtime", return_value=runtime):
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                app.busy = True
                await pilot.press("escape")
                await pilot.pause()
                self.assertTrue(agent.cancelled)

    async def test_app_mounts_and_local_help_adds_message(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = AgentConfig(
                api_key="not-a-real-secret",
                base_url="https://example.test/v1",
                model="test-model",
                workspace=root,
            )
            app = CodeAgentApp(root, settings=ConfiguredSettings(config), session_log=False)
            runtime = SimpleNamespace(agent=FakeAgent())
            with patch("code_agent.tui.app.create_runtime", return_value=runtime):
                async with app.run_test(size=(110, 36)) as pilot:
                    await pilot.pause()
                    self.assertIs(app.runtime, runtime)
                    self.assertIn("test-model", str(app.query_one("#topbar").render()))
                    before = len(app.query(MessageBlock))
                    app._route_command("/help")
                    await pilot.pause()
                    self.assertEqual(len(app.query(MessageBlock)), before + 1)

                    composer = app.query_one(Composer)
                    composer.text = "show my message"
                    composer.focus()
                    await pilot.press("enter")
                    await pilot.pause()
                    user_messages = [
                        block for block in app.query(MessageBlock) if block.role == "user"
                    ]
                    self.assertEqual(
                        [block.content for block in user_messages], ["show my message"]
                    )

    async def test_workspace_picker_rebuilds_runtime_and_starts_new_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "first"
            target = Path(directory) / "second"
            root.mkdir()
            target.mkdir()
            config = AgentConfig(
                api_key="not-a-real-secret",
                base_url="https://example.test/v1",
                model="test-model",
                workspace=root,
            )
            settings = ConfiguredSettings(config)
            app = CodeAgentApp(root, settings=settings, session_log=False)
            runtime = SimpleNamespace(agent=FakeAgent())
            with patch("code_agent.tui.app.create_runtime", return_value=runtime) as created:
                async with app.run_test(size=(110, 40)) as pilot:
                    await pilot.pause()
                    app.action_workspace()
                    await pilot.pause()
                    self.assertIsInstance(app.screen, WorkspaceScreen)
                    screen = app.screen
                    path_input = screen.query_one("#workspace-path")
                    path_input.value = str(Path(directory) / "missing")
                    screen._submit_path()
                    self.assertIs(app.screen, screen)
                    self.assertTrue(screen.query_one("#workspace-error").has_class("visible"))

                    path_input.value = str(target)
                    screen._submit_path()
                    await pilot.pause()
                    await pilot.pause()

                    self.assertEqual(app.workspace, target.resolve())
                    self.assertEqual(app.config.workspace, target.resolve())
                    self.assertEqual(
                        settings.remembered, [root.resolve(), target.resolve()]
                    )
                    self.assertEqual(created.call_count, 2)
                    self.assertIn("second", str(app.query_one("#topbar").render()))
                    messages = list(app.query(MessageBlock))
                    self.assertEqual(len(messages), 1)
                    self.assertIn("Workspace switched", messages[0].content)

    async def test_missing_credential_opens_connect_screen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = CodeAgentApp(
                root,
                settings=MissingSettings(None),
                session_log=False,
            )
            async with app.run_test(size=(110, 36)) as pilot:
                await pilot.pause()
                self.assertIsInstance(app.screen, ConnectScreen)

    async def test_all_dialogs_have_visible_exit_and_actions_in_small_terminal(self):
        root = Path.cwd()
        config = AgentConfig(
            api_key="not-a-real-secret",
            base_url="https://example.test/v1",
            model="test-model",
            workspace=root,
        )
        settings = ConfiguredSettings(config)
        app = CodeAgentApp(root, settings=settings, session_log=False)
        runtime = SimpleNamespace(agent=FakeAgent())
        dialogs = (
            (ConnectScreen(settings.load()), ("dismiss", "cancel", "save")),
            (ModelScreen("openai", "test-model"), ("dismiss", "cancel", "save")),
            (PermissionScreen("auto-edit"), ("dismiss", "cancel", "save")),
            (ProcessScreen(()), ("dismiss", "cancel", "open", "stop")),
            (SessionScreen(()), ("dismiss", "cancel", "resume")),
            (WorkspaceScreen(root), ("dismiss", "cancel", "switch")),
            (ConfigScreen(settings.load(), "system-keyring"), ("dismiss", "close")),
            (ApprovalScreen("write_file", {"path": "demo.txt"}), ("dismiss", "reject", "allow")),
        )
        with patch("code_agent.tui.app.create_runtime", return_value=runtime):
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                for dialog, actions in dialogs:
                    app.push_screen(dialog)
                    await pilot.pause()
                    self.assertIs(app.screen, dialog)
                    self.assert_actions_visible(dialog, actions)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertIsNot(app.screen, dialog)

    async def test_permission_mode_changes_in_place_without_losing_conversation(self):
        root = Path.cwd()
        config = AgentConfig(
            api_key="not-a-real-secret",
            base_url="https://example.test/v1",
            model="test-model",
            workspace=root,
            approval_mode="auto-edit",
        )
        settings = ConfiguredSettings(config)
        app = CodeAgentApp(root, settings=settings, session_log=False)
        agent = FakeAgent()
        agent.approvals = SimpleNamespace(mode="auto-edit")
        runtime = SimpleNamespace(agent=agent)
        with patch("code_agent.tui.app.create_runtime", return_value=runtime) as created:
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                app._append_message("user", "keep this conversation")
                before = list(app.query(MessageBlock))

                app.action_permissions()
                await pilot.pause()
                self.assertIsInstance(app.screen, PermissionScreen)
                app.screen.query_one("#permission-mode").value = "suggest"
                app.screen.query_one("#save").press()
                await pilot.pause()

                self.assertEqual(settings.approval_mode, "suggest")
                self.assertEqual(app.config.approval_mode, "suggest")
                self.assertEqual(runtime.agent.approvals.mode, "suggest")
                self.assertEqual(app.overrides["approval_mode"], "suggest")
                self.assertEqual(created.call_count, 1)
                self.assertEqual(list(app.query(MessageBlock)), before)

    async def test_resume_picker_restores_saved_conversation(self):
        root = Path.cwd()
        config = AgentConfig(
            api_key="not-a-real-secret",
            base_url="https://example.test/v1",
            model="test-model",
            workspace=root,
        )
        summary = ConversationSummary(
            session_id="20260901-120000-1234abcd",
            title="Fix the parser",
            created_at="2026-09-01T12:00:00+00:00",
            updated_at="2026-09-01T12:05:00+00:00",
            message_count=3,
            tool_calls=0,
            preview=(("user", "Fix the parser"), ("assistant", "Done")),
        )
        agent = FakeAgent()
        agent.saved_conversations = (summary,)
        agent.restored_history = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Fix the parser"},
            {"role": "assistant", "content": "Done"},
        ]
        app = CodeAgentApp(root, settings=ConfiguredSettings(config), session_log=False)
        runtime = SimpleNamespace(agent=agent)
        with patch("code_agent.tui.app.create_runtime", return_value=runtime):
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                app._route_command("/resume")
                await pilot.pause()
                self.assertIsInstance(app.screen, SessionScreen)
                self.assertIn("Fix the parser", str(app.screen.query_one("#session-preview").render()))
                app.screen.query_one("#resume").press()
                await pilot.pause()

                self.assertEqual(agent.resumed, summary.session_id)
                visible = [block.content for block in app.query(MessageBlock)]
                self.assertIn("Fix the parser", visible)
                self.assertIn("Done", visible)

    async def test_process_screen_can_reopen_and_stop_application(self):
        root = Path.cwd()
        config = AgentConfig(
            api_key="not-a-real-secret",
            base_url="https://example.test/v1",
            model="test-model",
            workspace=root,
        )
        manager = FakeProcessManager()
        runtime = SimpleNamespace(agent=FakeAgent(), processes=manager)
        app = CodeAgentApp(root, settings=ConfiguredSettings(config), session_log=False)
        with patch("code_agent.tui.app.create_runtime", return_value=runtime):
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                app._route_command("/processes")
                await pilot.pause()
                self.assertIsInstance(app.screen, ProcessScreen)
                self.assertIn(
                    "RUNNING", str(app.screen.query_one("#process-preview").render())
                )
                app.screen.query_one("#open").press()
                await pilot.pause()
                self.assertEqual(manager.opened, ["app12345"])
                self.assertIsInstance(app.screen, ProcessScreen)
                app.screen.query_one("#stop").press()
                await pilot.pause()
                self.assertEqual(manager.stopped, ["app12345"])
                self.assertIsInstance(app.screen, ProcessScreen)
                self.assertTrue(app.screen.query_one("#stop").disabled)

    async def test_workspace_without_local_env_opens_global_credential_form(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "first"
            target = Path(directory) / "second"
            root.mkdir()
            target.mkdir()
            config = AgentConfig(
                api_key="not-a-real-secret",
                base_url="https://example.test/v1",
                model="test-model",
                workspace=root,
            )
            settings = TargetCredentialSettings(config, target)
            app = CodeAgentApp(root, settings=settings, session_log=False)
            runtime = SimpleNamespace(agent=FakeAgent())
            with patch("code_agent.tui.app.create_runtime", return_value=runtime):
                async with app.run_test(size=(110, 40)) as pilot:
                    await pilot.pause()
                    app._workspace_selected(target)
                    await pilot.pause()

                    self.assertIsInstance(app.screen, ConnectScreen)
                    self.assertEqual(app._pending_workspace, target.resolve())
                    self.assertIn("operating-system credential store", app.screen.error)

    async def test_successful_connect_continues_pending_workspace_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "first"
            target = Path(directory) / "second"
            root.mkdir()
            target.mkdir()
            config = AgentConfig(
                api_key="not-a-real-secret",
                base_url="https://example.test/v1",
                model="test-model",
                workspace=root,
            )
            settings = TargetCredentialSettings(config, target)
            app = CodeAgentApp(root, settings=settings, session_log=False)
            runtime = SimpleNamespace(agent=FakeAgent())
            with patch("code_agent.tui.app.create_runtime", return_value=runtime):
                async with app.run_test(size=(110, 40)) as pilot:
                    await pilot.pause()
                    app._pending_workspace = target.resolve()
                    settings.blocked = False
                    app._connect_succeeded()
                    await pilot.pause()
                    await pilot.pause()

                    self.assertIsNone(app._pending_workspace)
                    self.assertEqual(app.workspace, target.resolve())


if __name__ == "__main__":
    unittest.main()
