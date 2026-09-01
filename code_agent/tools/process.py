"""Model-facing tools for launching and controlling user-visible applications."""

from __future__ import annotations

from typing import Any

from ..errors import ProcessError, ToolError
from ..processes import ProcessManager
from .registry import ToolSpec
from .shell import command_is_dangerous, command_references_sensitive_file


def build_process_tools(manager: ProcessManager) -> list[ToolSpec]:
    def launch(args: dict[str, Any]) -> dict[str, Any]:
        command = args["command"].strip()
        if command_is_dangerous(command):
            raise ToolError("Command rejected by the destructive-command safety policy")
        if command_references_sensitive_file(command):
            raise ToolError("Command rejected because it directly references a credential file")
        try:
            return manager.start(
                command=command,
                cwd=args.get("cwd", "."),
                mode=args.get("mode", "auto"),
                name=args.get("name"),
                url=args.get("url"),
                port=args.get("port"),
                ready_timeout_seconds=args.get("ready_timeout_seconds", 15),
            )
        except ProcessError as exc:
            raise ToolError(str(exc)) from exc

    def list_processes(_args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "processes": list(manager.list())}

    def stop(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return manager.stop(args["process_id"])
        except ProcessError as exc:
            raise ToolError(str(exc)) from exc

    def open_preview(args: dict[str, Any]) -> dict[str, Any]:
        try:
            return manager.open(args["process_id"])
        except ProcessError as exc:
            raise ToolError(str(exc)) from exc

    return [
        ToolSpec(
            name="launch_app",
            description=(
                "Launch a completed application for the user to interact with. Use terminal mode "
                "for interactive CLI programs, web mode with a localhost URL/port for servers, "
                "and desktop mode for GUI programs. Do not simulate user interaction when the "
                "user asked to run and show the application."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "description": "Workspace-relative directory"},
                    "mode": {
                        "type": "string",
                        "description": "auto, terminal, web, or desktop",
                    },
                    "name": {"type": "string"},
                    "url": {
                        "type": "string",
                        "description": "Localhost URL for web mode",
                    },
                    "port": {"type": "integer"},
                    "ready_timeout_seconds": {"type": "integer"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            handler=launch,
            mutation_kind="command",
        ),
        ToolSpec(
            name="list_processes",
            description="List applications launched in the current workspace and their state.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=list_processes,
        ),
        ToolSpec(
            name="stop_process",
            description="Stop one application previously launched by Code Agent.",
            parameters={
                "type": "object",
                "properties": {"process_id": {"type": "string"}},
                "required": ["process_id"],
                "additionalProperties": False,
            },
            handler=stop,
            mutation_kind="command",
        ),
        ToolSpec(
            name="open_preview",
            description="Open the localhost browser preview for a running web application again.",
            parameters={
                "type": "object",
                "properties": {"process_id": {"type": "string"}},
                "required": ["process_id"],
                "additionalProperties": False,
            },
            handler=open_preview,
            mutation_kind="command",
        ),
    ]
