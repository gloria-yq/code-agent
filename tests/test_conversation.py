import json
import tempfile
import unittest
from pathlib import Path

from code_agent.conversation import ConversationStore
from code_agent.errors import ConversationError


class ConversationStoreTests(unittest.TestCase):
    def test_save_list_and_load_redacted_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = "secret-value"
            store = ConversationStore(
                Path(directory),
                redact=lambda value: self._redact(value, secret),
                metadata={"model": "test-model"},
            )
            messages = [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "Implement session restore\nwith tests"},
                {"role": "assistant", "content": f"Result {secret}"},
            ]

            session_id = store.save(None, messages)
            summaries = store.list()
            loaded = store.load(session_id)

            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].session_id, session_id)
            self.assertEqual(summaries[0].title, "Implement session restore with tests")
            self.assertEqual(loaded.messages[-1]["content"], "Result [REDACTED]")
            self.assertFalse(list(Path(directory).glob("*.tmp")))

    def test_load_repairs_tool_call_interrupted_before_result(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(Path(directory))
            session_id = store.save(
                None,
                [
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "change it"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "edit_file", "arguments": "{}"},
                            }
                        ],
                    },
                ],
            )

            loaded = store.load(session_id)

            self.assertEqual(loaded.messages[-1]["role"], "tool")
            self.assertEqual(loaded.messages[-1]["tool_call_id"], "call-1")
            self.assertIn("interrupted", loaded.messages[-1]["content"])

    def test_empty_conversation_is_not_listed_and_invalid_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(Path(directory))
            self.assertEqual(store.save(None, [{"role": "system", "content": "s"}]), "")
            self.assertEqual(store.list(), ())
            with self.assertRaises(ConversationError):
                store.load("../outside")

    @classmethod
    def _redact(cls, value, secret):
        if isinstance(value, str):
            return value.replace(secret, "[REDACTED]")
        if isinstance(value, list):
            return [cls._redact(item, secret) for item in value]
        if isinstance(value, dict):
            return {key: cls._redact(item, secret) for key, item in value.items()}
        return value


if __name__ == "__main__":
    unittest.main()
