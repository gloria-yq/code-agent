import tempfile
import unittest
from pathlib import Path

from todo import add_task, list_tasks


class TodoTests(unittest.TestCase):
    def test_add_and_list(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            add_task(path, "write tests")
            self.assertEqual(list_tasks(path), ["1. [ ] write tests"])


if __name__ == "__main__":
    unittest.main()

