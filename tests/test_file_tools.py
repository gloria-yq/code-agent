import tempfile
import unittest
from pathlib import Path

from code_agent.errors import ToolError
from code_agent.tools.files import build_file_tools
from code_agent.tools.registry import ToolRegistry
from code_agent.workspace import Workspace


class FileToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = ToolRegistry()
        for tool in build_file_tools(Workspace(self.root)):
            self.registry.register(tool)

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, name, args):
        return self.registry.execute(name, args)

    def test_create_read_and_unique_edit(self):
        created = self.execute("write_file", {"path": "hello.txt", "content": "alpha\nbeta\n"})
        self.assertTrue(created["created"])
        read = self.execute("read_file", {"path": "hello.txt", "start_line": 2, "end_line": 2})
        self.assertEqual(read["content"], "beta\n")
        edited = self.execute(
            "edit_file", {"path": "hello.txt", "old_text": "beta", "new_text": "gamma"}
        )
        self.assertEqual(edited["replacements"], 1)
        self.assertEqual((self.root / "hello.txt").read_text(), "alpha\ngamma\n")

    def test_write_requires_explicit_overwrite(self):
        (self.root / "a.txt").write_text("old")
        with self.assertRaises(ToolError):
            self.execute("write_file", {"path": "a.txt", "content": "new"})

    def test_edit_rejects_ambiguous_match(self):
        (self.root / "a.txt").write_text("x x")
        with self.assertRaises(ToolError):
            self.execute("edit_file", {"path": "a.txt", "old_text": "x", "new_text": "y"})

    def test_search_text_reports_line_numbers(self):
        (self.root / "a.py").write_text("first\nHello World\n", encoding="utf-8")
        result = self.execute("search_text", {"query": "hello"})
        self.assertEqual(result["matches"][0]["path"], "a.py")
        self.assertEqual(result["matches"][0]["line"], 2)

    def test_credential_env_is_hidden_and_unreadable(self):
        (self.root / ".env").write_text("OPENAI_API_KEY=secret-value", encoding="utf-8")
        listed = self.execute("list_files", {"path": "."})
        self.assertNotIn(".env", listed["entries"])
        searched = self.execute("search_text", {"query": "secret-value"})
        self.assertEqual(searched["matches"], [])
        with self.assertRaises(ToolError):
            self.execute("read_file", {"path": ".env"})




if __name__ == "__main__":
    unittest.main()
