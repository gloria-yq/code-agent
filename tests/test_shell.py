import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from code_agent.errors import ToolError
from code_agent.tools.shell import (
    build_shell_tool,
    command_is_dangerous,
    command_references_sensitive_file,
)
from code_agent.workspace import Workspace


class ShellToolTests(unittest.TestCase):
    def test_dangerous_patterns(self):
        self.assertTrue(command_is_dangerous("git reset --hard HEAD"))
        self.assertTrue(command_is_dangerous("shutdown /s"))
        self.assertFalse(command_is_dangerous("git status --short"))

    def test_runs_command_and_captures_output(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = build_shell_tool(Workspace(directory))
            command = "echo hello"
            result = tool.handler({"command": command})
            self.assertTrue(result["ok"])
            self.assertIn("hello", result["stdout"])

    def test_rejects_destructive_command(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = build_shell_tool(Workspace(directory))
            with self.assertRaises(ToolError):
                tool.handler({"command": "git reset --hard HEAD"})

    def test_rejects_direct_dotenv_access_but_allows_example(self):
        self.assertTrue(command_references_sensitive_file("type .env"))
        self.assertTrue(command_references_sensitive_file("cat config/.env.local"))
        self.assertTrue(command_references_sensitive_file("cat .env.prod.local"))
        self.assertFalse(command_references_sensitive_file("type .env.example"))
        self.assertFalse(command_references_sensitive_file("echo .environment"))

    def test_command_child_does_not_receive_credentials(self):
        completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            tool = build_shell_tool(Workspace(directory))
            environment = {
                "PATH": "tool-path",
                "SystemRoot": "windows-root",
                "OPENAI_API_KEY": "must-not-leak",
                "GITHUB_TOKEN": "must-not-leak-either",
            }
            with patch.dict("os.environ", environment, clear=True):
                with patch("subprocess.run", return_value=completed) as mocked:
                    tool.handler({"command": "echo ok"})
        child_env = mocked.call_args.kwargs["env"]
        self.assertEqual(child_env["PATH"], "tool-path")
        normalized_child_env = {name.upper(): value for name, value in child_env.items()}
        self.assertEqual(normalized_child_env["SYSTEMROOT"], "windows-root")
        self.assertNotIn("OPENAI_API_KEY", child_env)
        self.assertNotIn("GITHUB_TOKEN", child_env)

    def test_command_output_is_redacted(self):
        completed = SimpleNamespace(
            returncode=0, stdout="value=super-secret-value", stderr=""
        )
        with tempfile.TemporaryDirectory() as directory:
            tool = build_shell_tool(
                Workspace(directory),
                redact=lambda text: text.replace("super-secret-value", "[REDACTED]"),
            )
            with patch("subprocess.run", return_value=completed):
                result = tool.handler({"command": "echo ok"})
        self.assertEqual(result["stdout"], "value=[REDACTED]")


if __name__ == "__main__":
    unittest.main()
