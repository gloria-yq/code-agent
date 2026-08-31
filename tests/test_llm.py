import json
import io
import unittest
import urllib.error
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
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)
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

    def test_deepseek_non_thinking_omits_tool_choice_without_tools(self):
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
        self.assertNotIn("tool_choice", payload)

    def test_rejects_missing_choices(self):
        with self.assertRaises(ModelError):
            OpenAICompatibleClient._parse({})

    def test_stream_assembles_text_reasoning_and_split_tool_arguments(self):
        events = [
            {"choices": [{"delta": {"reasoning_content": "inspect "}}]},
            {"choices": [{"delta": {"content": "Working. "}}]},
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":',
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '"a.py"}'}}
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        ]
        lines = [f"data: {json.dumps(event)}\n".encode() for event in events]
        lines.append(b"data: [DONE]\n")
        deltas: list[tuple[str, str]] = []

        reply = OpenAICompatibleClient._parse_stream(
            lines, lambda kind, value: deltas.append((kind, value))
        )

        self.assertEqual(reply.content, "Working. ")
        self.assertEqual(reply.raw_message["reasoning_content"], "inspect ")
        self.assertEqual(reply.tool_calls[0].id, "call-1")
        self.assertEqual(reply.tool_calls[0].name, "read_file")
        self.assertEqual(reply.tool_calls[0].arguments, '{"path":"a.py"}')
        self.assertIn(("content", "Working. "), deltas)
        self.assertIn(("reasoning", "inspect "), deltas)

    def test_stream_request_enables_streaming_and_tools(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                return iter(
                    [
                        b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n',
                        b"data: [DONE]\n",
                    ]
                )

        client = OpenAICompatibleClient(
            api_key="test-key", base_url="https://example.test/v1", model="test-model"
        )
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        with patch("urllib.request.urlopen", return_value=FakeResponse()) as mocked:
            reply = client.complete_stream([], tools, lambda *_args: None)
        payload = json.loads(mocked.call_args.args[0].data)
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(reply.content, "ok")

    def test_redacts_key_from_api_error_body(self):
        secret = "super-secret-api-key"
        client = OpenAICompatibleClient(
            api_key=secret, base_url="https://example.test/v1", model="test-model"
        )
        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            400,
            "bad request",
            {},
            io.BytesIO(f"request accidentally contained {secret}".encode()),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ModelError) as raised:
                client.complete([{"role": "user", "content": "hi"}], [])
        self.assertNotIn(secret, str(raised.exception))
        self.assertIn("[REDACTED]", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
