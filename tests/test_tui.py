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
from code_agent.errors import ConfigurationError, MissingCredentialError
from code_agent.settings import UserSettings
from code_agent.tui.app import CodeAgentApp
from code_agent.tui.screens import (
    ApprovalScreen,
    ConfigScreen,
    ConnectScreen,
    ModelScreen,
    WorkspaceScreen,
)
from code_agent.tui.widgets import Composer, MessageBlock


class FakeAgent:
    def run(self, task):
        return AgentResult("completed", "done", 1, 0)

    def cancel(self):
        return None

    def reset(self):
        return None

    def stats(self):
        return {"user_turns": 0, "model_turns": 0, "tool_calls": 0, "messages": 0}


class ConfiguredSettings:
    def __init__(self, config):
        self.config = config
        self.remembered: list[Path] = []

    def resolve(self, workspace, **overrides):
        return replace(self.config, workspace=Path(workspace).resolve())

    def load(self):
        return UserSettings()

    def credential_source(self, provider, workspace):
        return "system-keyring"

    def remember_workspace(self, workspace):
        self.remembered.append(Path(workspace).resolve())
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
