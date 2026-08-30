import unittest

from code_agent.context import ContextManager


class ContextManagerTests(unittest.TestCase):
    def test_truncates_large_tool_output_without_mutating_source(self):
        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "tool", "tool_call_id": "1", "content": "x" * 100},
        ]
        prepared = ContextManager(char_budget=1000, max_tool_output_chars=10).prepare(messages)
        self.assertIn("locally truncated", prepared[2]["content"])
        self.assertEqual(len(messages[2]["content"]), 100)

    def test_omits_old_messages_when_over_budget(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
        ] + [{"role": "assistant", "content": "x" * 200} for _ in range(8)]
        prepared = ContextManager(char_budget=750, max_tool_output_chars=100).prepare(messages)
        self.assertEqual(prepared[0]["role"], "system")
        self.assertEqual(prepared[1]["role"], "user")
        self.assertIn("older messages were omitted", prepared[2]["content"])
        self.assertLess(len(prepared), len(messages) + 1)


if __name__ == "__main__":
    unittest.main()

