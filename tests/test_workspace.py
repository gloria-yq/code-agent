import tempfile
import unittest
from pathlib import Path

from code_agent.errors import PathOutsideWorkspaceError, ToolError
from code_agent.workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def test_resolves_relative_path_inside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            self.assertEqual(workspace.resolve("src/a.py"), Path(directory).resolve() / "src/a.py")

    def test_rejects_parent_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with self.assertRaises(PathOutsideWorkspaceError):
                workspace.resolve("../secret.txt")

    def test_must_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(directory)
            with self.assertRaises(ToolError):
                workspace.resolve("missing", must_exist=True)


if __name__ == "__main__":
    unittest.main()

