"""Tool definitions, lightweight JSON argument validation, and dispatch."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from ..errors import ToolError

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    mutation_kind: str = "none"

    def api_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.api_schema() for tool in self._tools.values()]

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"Unknown tool: {name}") from exc

    def parse_arguments(self, name: str, raw_arguments: str) -> dict[str, Any]:
        spec = self.get(name)
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            raise ToolError(f"Arguments for {name} are not valid JSON: {exc.msg}") from exc
        if not isinstance(arguments, dict):
            raise ToolError(f"Arguments for {name} must be a JSON object")
        self._validate_object(arguments, spec.parameters, name)
        return arguments

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.get(name).handler(arguments)
        if not isinstance(result, dict):
            raise ToolError(f"Tool {name} returned a non-object result")
        return result

    @staticmethod
    def _validate_object(
        value: dict[str, Any], schema: dict[str, Any], tool_name: str
    ) -> None:
        properties = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in value]
        if missing:
            raise ToolError(f"Missing required arguments for {tool_name}: {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise ToolError(f"Unexpected arguments for {tool_name}: {', '.join(extras)}")

        python_types: dict[str, type | tuple[type, ...]] = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for key, item in value.items():
            expected_name = properties.get(key, {}).get("type")
            expected_type = python_types.get(expected_name)
            if expected_type is not None and not isinstance(item, expected_type):
                raise ToolError(f"Argument {key} for {tool_name} must be {expected_name}")
            if expected_name == "integer" and isinstance(item, bool):
                raise ToolError(f"Argument {key} for {tool_name} must be integer")
