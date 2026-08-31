import tempfile
import unittest
from pathlib import Path

from code_agent.agent import CodingAgent
from code_agent.approval import ApprovalPolicy
from code_agent.context import ContextManager
from code_agent.protocol import ModelReply, ToolCall
from code_agent.session import SessionLogger
from code_agent.security import SecretRedactor
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
        agent = build_agent(client)
        result = agent.run("do it", "system")
        self.assertEqual(result.status, "stalled")
        self.assertNotIn("tool_calls", agent.history()[-1])
        self.assertIn("Local agent stopped", agent.history()[-1]["content"])

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

    def test_jsonl_log_redacts_known_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "session.jsonl"
            secret = "super-secret-value"
            logger = SessionLogger(log_path, redact=SecretRedactor([secret]).value)
            logger.emit("tool.completed", result={"stdout": f"key={secret}"})
            contents = log_path.read_text(encoding="utf-8")
            self.assertNotIn(secret, contents)
            self.assertIn("[REDACTED]", contents)

    def test_follow_up_reuses_previous_conversation(self):
        client = FakeClient(
            [
                ModelReply(content="The project is code-agent"),
                ModelReply(content="It requires Python 3.10"),
            ]
        )
        agent = build_agent(client)
        first = agent.run("What is the project name?", "system")
        second = agent.run("What Python version does it require?")

        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "completed")
        roles = [message["role"] for message in client.requests[1][0]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(
            client.requests[1][0][-2]["content"], "The project is code-agent"
        )
        self.assertEqual(agent.stats()["user_turns"], 2)

    def test_reset_clears_conversation_but_keeps_system_prompt(self):
        client = FakeClient([ModelReply(content="first"), ModelReply(content="second")])
        agent = build_agent(client)
        agent.run("old task", "system")
        agent.reset()
        agent.run("new task")

        self.assertEqual(
            client.requests[1][0],
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "new task"},
            ],
        )
        self.assertEqual(agent.stats()["user_turns"], 1)

    def test_interrupt_rolls_back_partial_turn(self):
        class InterruptingClient:
            def complete(self, _messages, _tools):
                raise KeyboardInterrupt

        agent = build_agent(InterruptingClient())
        result = agent.run("interrupted task", "system")

        self.assertEqual(result.status, "interrupted")
        self.assertEqual(agent.history(), [{"role": "system", "content": "system"}])


if __name__ == "__main__":
    unittest.main()
