"""Human approval policy kept outside tool implementations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import ApprovalDeniedError
from .tools.registry import ToolSpec

ApprovalCallback = Callable[[ToolSpec, dict[str, Any]], bool]


class ApprovalPolicy:
    def __init__(self, mode: str, callback: ApprovalCallback | None = None):
        if mode not in {"suggest", "auto-edit", "full"}:
            raise ValueError(f"Unknown approval mode: {mode}")
        self.mode = mode
        self.callback = callback

    def check(self, spec: ToolSpec, arguments: dict[str, Any]) -> None:
        needs_approval = (
            self.mode == "suggest" and spec.mutation_kind != "none"
        ) or (self.mode == "auto-edit" and spec.mutation_kind == "command")
        if not needs_approval or self.mode == "full":
            return
        if self.callback is None or not self.callback(spec, arguments):
            raise ApprovalDeniedError(f"User denied {spec.name}")

