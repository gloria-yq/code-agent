import unittest

from code_agent.errors import ToolError
from code_agent.tools.registry import ToolRegistry, ToolSpec


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(
            ToolSpec(
                name="echo",
                description="echo",
                parameters={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                handler=lambda args: {"value": args["value"]},
            )
        )

    def test_parses_and_executes(self):
        args = self.registry.parse_arguments("echo", '{"value":"hello"}')
        self.assertEqual(self.registry.execute("echo", args), {"value": "hello"})
        self.assertNotIn("strict", self.registry.schemas()[0]["function"])

    def test_rejects_invalid_json(self):
        with self.assertRaises(ToolError):
            self.registry.parse_arguments("echo", "{")

    def test_rejects_missing_and_extra_arguments(self):
        with self.assertRaises(ToolError):
            self.registry.parse_arguments("echo", "{}")
        with self.assertRaises(ToolError):
            self.registry.parse_arguments("echo", '{"value":"x","extra":1}')


if __name__ == "__main__":
    unittest.main()
