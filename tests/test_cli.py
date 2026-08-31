import unittest
from unittest.mock import patch

from code_agent.agent import AgentResult
from code_agent.cli import _interactive_loop


class FakeInteractiveAgent:
    def __init__(self):
        self.inputs = []
        self.reset_count = 0
        self._history = [{"role": "system", "content": "system"}]

    def run(self, text):
        self.inputs.append(text)
        self._history.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": f"answer:{text}"},
            ]
        )
        return AgentResult("completed", f"answer:{text}", 1, 0)

    def reset(self):
        self.reset_count += 1
        self._history = [{"role": "system", "content": "system"}]

    def history(self):
        return list(self._history)

    def stats(self):
        return {
            "user_turns": len(self.inputs),
            "model_turns": len(self.inputs),
            "tool_calls": 0,
            "messages": len(self._history) - 1,
        }


class InteractiveCliTests(unittest.TestCase):
    def test_natural_language_inputs_are_consecutive_followups(self):
        agent = FakeInteractiveAgent()
        with patch("builtins.input", side_effect=["first", "follow up", "/exit"]):
            with patch("builtins.print"):
                exit_code = _interactive_loop(agent)
        self.assertEqual(exit_code, 0)
        self.assertEqual(agent.inputs, ["first", "follow up"])

    def test_commands_are_handled_without_calling_model(self):
        agent = FakeInteractiveAgent()
        inputs = ["/help", "/status", "/history", "/new", "/unknown", "/q"]
        with patch("builtins.input", side_effect=inputs):
            with patch("builtins.print"):
                exit_code = _interactive_loop(agent)
        self.assertEqual(exit_code, 0)
        self.assertEqual(agent.inputs, [])
        self.assertEqual(agent.reset_count, 1)


if __name__ == "__main__":
    unittest.main()
