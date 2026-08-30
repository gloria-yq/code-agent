import tempfile
import unittest

from code_agent.errors import ToolError
from code_agent.tools.shell import build_shell_tool, command_is_dangerous
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


if __name__ == "__main__":
    unittest.main()

