import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from textual import on
from textual.app import App, ComposeResult

from code_agent.agent import AgentResult
from code_agent.config import AgentConfig
from code_agent.errors import ConfigurationError
from code_agent.settings import UserSettings
from code_agent.tui.app import CodeAgentApp
from code_agent.tui.screens import ConnectScreen
from code_agent.tui.widgets import MessageBlock
from code_agent.tui.widgets import Composer


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

    def resolve(self, workspace, **overrides):
        return self.config

    def load(self):
        return UserSettings()

    def credential_source(self, provider, workspace):
        return "system-keyring"


class MissingSettings(ConfiguredSettings):
    def resolve(self, workspace, **overrides):
        raise ConfigurationError("No model API key is set.")


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


if __name__ == "__main__":
    unittest.main()
