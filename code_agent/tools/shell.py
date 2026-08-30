"""Local command execution with timeouts and explicit safety classification."""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

from ..errors import ToolError
from ..workspace import Workspace
from .registry import ToolSpec

DANGEROUS_PATTERNS = (
    r"(^|\s)(rm|rmdir)\s+(-[^\s]*r[^\s]*f|/s\s+/q)",
    r"git\s+(reset\s+--hard|clean\s+-[^\s]*f|push\s+.*--force)",
    r"(^|\s)(format|diskpart|shutdown|reboot|mkfs)(\s|$)",
    r"(^|\s)(del|erase)\s+.*[/\\*?]",
    r"(^|\s)(sudo|runas)(\s|$)",
)


def command_is_dangerous(command: str) -> bool:
    lowered = command.strip().lower()
    return any(re.search(pattern, lowered) for pattern in DANGEROUS_PATTERNS)


def build_shell_tool(
    workspace: Workspace, *, timeout: float = 60.0, output_limit: int = 20_000
) -> ToolSpec:
    def run_command(args: dict[str, Any]) -> dict[str, Any]:
        command = args["command"].strip()
        if not command:
            raise ToolError("command cannot be empty")
        if command_is_dangerous(command):
            raise ToolError("Command rejected by the destructive-command safety policy")
        cwd = workspace.resolve(args.get("cwd", "."), must_exist=True)
        if not cwd.is_dir():
            raise ToolError("cwd must be a directory")
        chosen_timeout = args.get("timeout_seconds", timeout)
        if not 1 <= chosen_timeout <= 300:
            raise ToolError("timeout_seconds must be between 1 and 300")
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=chosen_timeout,
                env=os.environ.copy(),
            )
            stdout = completed.stdout
            stderr = completed.stderr
            truncated = len(stdout) + len(stderr) > output_limit
            if truncated:
                remaining = output_limit
                stdout = stdout[:remaining]
                remaining -= len(stdout)
                stderr = stderr[: max(remaining, 0)]
            return {
                "ok": completed.returncode == 0,
                "command": command,
                "cwd": workspace.display(cwd),
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "truncated": truncated,
            }
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "")[:output_limit]
            stderr = (exc.stderr or "")[: max(output_limit - len(stdout), 0)]
            return {
                "ok": False,
                "command": command,
                "cwd": workspace.display(cwd),
                "error": "timeout",
                "timeout_seconds": chosen_timeout,
                "stdout": stdout,
                "stderr": stderr,
            }
        except OSError as exc:
            raise ToolError(f"Cannot start command: {exc}") from exc

    return ToolSpec(
        name="run_command",
        description=(
            "Run a foreground shell command inside the workspace. Use it to inspect the project "
            "and run tests. Destructive commands are rejected and execution is time-limited."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string", "description": "Workspace-relative directory; defaults to ."},
                "timeout_seconds": {"type": "integer", "description": "1 to 300 seconds"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        handler=run_command,
        mutation_kind="command",
    )

