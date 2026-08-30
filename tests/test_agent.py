import tempfile
import unittest
from pathlib import Path

from code_agent.agent import CodingAgent
from code_agent.approval import ApprovalPolicy
from code_agent.context import ContextManager
from code_agent.protocol import ModelReply, ToolCall
from code_agent.session import SessionLogger
from code_agent.tools.registry import ToolRegistry, ToolSpec

from .helpers import FakeClient


def registry_with_echo():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "echo",
            "echo",
            {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            lambda args: {"ok": True, "value": args["value"]},
        )
    )
    return registry


def build_agent(client, registry=None, max_turns=4):
    return CodingAgent(
        client=client,
        tools=registry or registry_with_echo(),
        context=ContextManager(char_budget=10_000, max_tool_output_chars=1000),
        approvals=ApprovalPolicy("full"),
        logger=SessionLogger(None),
        max_turns=max_turns,
    )


class AgentLoopTests(unittest.TestCase):
    def test_tool_round_trip_then_completion(self):
        client = FakeClient(
            [
                ModelReply(tool_calls=(ToolCall("c1", "echo", '{"value":"hi"}'),)),
                ModelReply(content="Done", finish_reason="stop"),
            ]
        )
        result = build_agent(client).run("do it", "system")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.tool_calls, 1)
        second_messages = client.requests[1][0]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertIn('"value": "hi"', second_messages[-1]["content"])

    def test_tool_errors_are_returned_to_model(self):
        client = FakeClient(
            [
                ModelReply(tool_calls=(ToolCall("c1", "missing", "{}"),)),
                ModelReply(content="Blocked"),
            ]
        )
        result = build_agent(client).run("do it", "system")
        self.assertEqual(result.status, "completed")
        self.assertIn("Unknown tool", client.requests[1][0][-1]["content"])

    def test_repeated_calls_stop_as_stalled(self):
        repeated = ModelReply(tool_calls=(ToolCall("c", "echo", '{"value":"x"}'),))
        client = FakeClient([repeated, repeated, repeated])
        result = build_agent(client).run("do it", "system")
        self.assertEqual(result.status, "stalled")

    def test_max_turns(self):
        replies = [
            ModelReply(tool_calls=(ToolCall(str(i), "echo", f'{{"value":"{i}"}}'),))
            for i in range(2)
        ]
        result = build_agent(FakeClient(replies), max_turns=2).run("do it", "system")
        self.assertEqual(result.status, "max_turns")

    def test_jsonl_log_is_append_only_events(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "session.jsonl"
            client = FakeClient([ModelReply(content="Done")])
            agent = CodingAgent(
                client=client,
                tools=registry_with_echo(),
                context=ContextManager(char_budget=1000, max_tool_output_chars=100),
                approvals=ApprovalPolicy("full"),
                logger=SessionLogger(log_path),
            )
            agent.run("task", "system")
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(lines), 4)
            self.assertIn('"event": "session.started"', lines[0])


if __name__ == "__main__":
    unittest.main()

