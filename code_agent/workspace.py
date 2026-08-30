"""Workspace boundary enforcement shared by every local tool."""

from __future__ import annotations

from pathlib import Path

from .errors import PathOutsideWorkspaceError, ToolError


class Workspace:
    def __init__(self, root: str | Path):
        resolved = Path(root).expanduser().resolve()
        if not resolved.is_dir():
            raise ToolError(f"Workspace is not a directory: {resolved}")
        self.root = resolved

    def resolve(self, user_path: str, *, must_exist: bool = False) -> Path:
        if not isinstance(user_path, str) or not user_path.strip():
            raise ToolError("path must be a non-empty string")
        candidate = Path(user_path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise PathOutsideWorkspaceError(
                f"Path escapes the workspace: {user_path}"
            ) from exc
        if must_exist and not resolved.exists():
            raise ToolError(f"Path does not exist: {user_path}")
        return resolved

    def display(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix() or "."
        except ValueError:
            return str(path)

