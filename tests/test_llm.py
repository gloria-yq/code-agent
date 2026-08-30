import json
import unittest
from unittest.mock import patch

from code_agent.errors import ModelError
from code_agent.llm import OpenAICompatibleClient


class LlmParsingTests(unittest.TestCase):
    def test_complete_sends_chat_completions_payload(self):
        response_body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}]}
        ).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return response_body

        client = OpenAICompatibleClient(
            api_key="test-key", base_url="https://example.test/v1", model="test-model"
        )
        with patch("urllib.request.urlopen", return_value=FakeResponse()) as mocked:
            reply = client.complete([{"role": "user", "content": "hi"}], [])
        request = mocked.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(reply.content, "done")

    def test_parses_tool_call(self):
        reply = OpenAICompatibleClient._parse(
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": '{"path":"a"}'},
                                }
                            ],
                        },
                    }
                ]
            }
        )
        self.assertEqual(reply.tool_calls[0].name, "read_file")
        self.assertEqual(reply.finish_reason, "tool_calls")

    def test_deepseek_thinking_preserves_reasoning_and_omits_tool_choice(self):
        response_body = json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "I will inspect the file.",
                            "reasoning_content": "I need the file contents first.",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": '{"path":"a"}'},
                                }
                            ],
                        },
                    }
                ]
            }
        ).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return response_body

        client = OpenAICompatibleClient(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            provider="deepseek",
        )
        with patch("urllib.request.urlopen", return_value=FakeResponse()) as mocked:
            reply = client.complete([{"role": "user", "content": "hi"}], [])
        payload = json.loads(mocked.call_args.args[0].data)
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertNotIn("tool_choice", payload)
        self.assertEqual(
            reply.as_assistant_message()["reasoning_content"],
            "I need the file contents first.",
        )

    def test_deepseek_non_thinking_keeps_automatic_tool_choice(self):
        client = OpenAICompatibleClient(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            provider="deepseek",
            deepseek_thinking=False,
        )
        response_body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "done"}}]}
        ).encode()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return response_body

        with patch("urllib.request.urlopen", return_value=FakeResponse()) as mocked:
            client.complete([{"role": "user", "content": "hi"}], [])
        payload = json.loads(mocked.call_args.args[0].data)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["tool_choice"], "auto")

    def test_rejects_missing_choices(self):
        with self.assertRaises(ModelError):
            OpenAICompatibleClient._parse({})


if __name__ == "__main__":
    unittest.main()
