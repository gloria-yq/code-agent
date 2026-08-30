"""Local tools exposed to the model through a small registry."""

from .files import build_file_tools
from .registry import ToolRegistry, ToolSpec
from .shell import build_shell_tool

__all__ = ["ToolRegistry", "ToolSpec", "build_file_tools", "build_shell_tool"]

