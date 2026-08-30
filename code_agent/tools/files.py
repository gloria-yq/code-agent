"""Workspace-confined filesystem tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import ToolError
from ..workspace import Workspace
from .registry import ToolSpec

IGNORED_NAMES = {".git", ".venv", "__pycache__", "node_modules", ".code-agent"}


def _is_sensitive_config(path: Path) -> bool:
    name = path.name.casefold()
    return name == ".env" or (name.startswith(".env.") and name != ".env.example")


def _reject_sensitive_config(path: Path) -> None:
    if _is_sensitive_config(path):
        raise ToolError("Access to untracked credential configuration is blocked")


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(f"File is not UTF-8 text: {path.name}") from exc
    except OSError as exc:
        raise ToolError(f"Cannot read {path.name}: {exc}") from exc


def build_file_tools(workspace: Workspace) -> list[ToolSpec]:
    def list_files(args: dict[str, Any]) -> dict[str, Any]:
        root = workspace.resolve(args.get("path", "."), must_exist=True)
        if not root.is_dir():
            raise ToolError("list_files path must be a directory")
        max_depth = args.get("max_depth", 3)
        if not 0 <= max_depth <= 8:
            raise ToolError("max_depth must be between 0 and 8")
        items: list[str] = []

        def walk(directory: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except OSError as exc:
                raise ToolError(f"Cannot list directory: {exc}") from exc
            for child in children:
                if child.name in IGNORED_NAMES or _is_sensitive_config(child):
                    continue
                relative = workspace.display(child)
                items.append(relative + ("/" if child.is_dir() else ""))
                if child.is_dir():
                    walk(child, depth + 1)

        walk(root, 0)
        return {"ok": True, "path": workspace.display(root), "entries": items}

    def search_text(args: dict[str, Any]) -> dict[str, Any]:
        root = workspace.resolve(args.get("path", "."), must_exist=True)
        query = args["query"]
        if not query:
            raise ToolError("query cannot be empty")
        case_sensitive = args.get("case_sensitive", False)
        max_results = args.get("max_results", 100)
        if not 1 <= max_results <= 500:
            raise ToolError("max_results must be between 1 and 500")
        needle = query if case_sensitive else query.casefold()
        candidates = [root] if root.is_file() else root.rglob("*")
        matches: list[dict[str, Any]] = []
        skipped_binary = 0
        for candidate in candidates:
            if (
                not candidate.is_file()
                or any(part in IGNORED_NAMES for part in candidate.parts)
                or _is_sensitive_config(candidate)
            ):
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                skipped_binary += 1
                continue
            for line_number, line in enumerate(content.splitlines(), 1):
                haystack = line if case_sensitive else line.casefold()
                if needle in haystack:
                    matches.append(
                        {
                            "path": workspace.display(candidate),
                            "line": line_number,
                            "text": line[:500],
                        }
                    )
                    if len(matches) >= max_results:
                        return {
                            "ok": True,
                            "matches": matches,
                            "truncated": True,
                            "skipped_non_text_files": skipped_binary,
                        }
        return {
            "ok": True,
            "matches": matches,
            "truncated": False,
            "skipped_non_text_files": skipped_binary,
        }

    def read_file(args: dict[str, Any]) -> dict[str, Any]:
        path = workspace.resolve(args["path"], must_exist=True)
        _reject_sensitive_config(path)
        if not path.is_file():
            raise ToolError("read_file path must be a file")
        content = _text(path)
        lines = content.splitlines(keepends=True)
        start = args.get("start_line", 1)
        end = args.get("end_line", len(lines) or 1)
        if start < 1 or end < start:
            raise ToolError("Invalid line range")
        selected = "".join(lines[start - 1 : end])
        return {
            "ok": True,
            "path": workspace.display(path),
            "start_line": start,
            "end_line": min(end, len(lines)),
            "total_lines": len(lines),
            "content": selected,
        }

    def write_file(args: dict[str, Any]) -> dict[str, Any]:
        path = workspace.resolve(args["path"])
        _reject_sensitive_config(path)
        existed = path.exists()
        if existed and not args.get("overwrite", False):
            raise ToolError("File exists; set overwrite=true only after reading it")
        if path.exists() and not path.is_file():
            raise ToolError("write_file path is not a regular file")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8", newline="")
        except OSError as exc:
            raise ToolError(f"Cannot write file: {exc}") from exc
        return {
            "ok": True,
            "path": workspace.display(path),
            "created": not existed,
            "characters": len(args["content"]),
        }

    def edit_file(args: dict[str, Any]) -> dict[str, Any]:
        path = workspace.resolve(args["path"], must_exist=True)
        _reject_sensitive_config(path)
        if not path.is_file():
            raise ToolError("edit_file path must be a file")
        content = _text(path)
        old = args["old_text"]
        new = args["new_text"]
        if not old:
            raise ToolError("old_text cannot be empty")
        count = content.count(old)
        if count == 0:
            raise ToolError("old_text was not found; read the file and retry with exact text")
        if count != 1:
            raise ToolError(f"old_text matched {count} places; provide a unique larger block")
        updated = content.replace(old, new, 1)
        try:
            path.write_text(updated, encoding="utf-8", newline="")
        except OSError as exc:
            raise ToolError(f"Cannot edit file: {exc}") from exc
        return {
            "ok": True,
            "path": workspace.display(path),
            "replacements": 1,
            "character_delta": len(new) - len(old),
        }

    object_schema = lambda properties, required=(): {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }
    return [
        ToolSpec(
            name="list_files",
            description="List files under a workspace directory. Generated and dependency directories are omitted.",
            parameters=object_schema(
                {
                    "path": {"type": "string", "description": "Workspace-relative directory; defaults to ."},
                    "max_depth": {"type": "integer", "description": "Recursive depth from 0 to 8; defaults to 3"},
                }
            ),
            handler=list_files,
        ),
        ToolSpec(
            name="read_file",
            description="Read a UTF-8 text file, optionally selecting an inclusive line range.",
            parameters=object_schema(
                {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                ("path",),
            ),
            handler=read_file,
        ),
        ToolSpec(
            name="search_text",
            description="Search UTF-8 files for literal text and return matching paths, line numbers, and lines.",
            parameters=object_schema(
                {
                    "query": {"type": "string"},
                    "path": {"type": "string", "description": "Workspace-relative file or directory; defaults to ."},
                    "case_sensitive": {"type": "boolean"},
                    "max_results": {"type": "integer", "description": "1 to 500; defaults to 100"},
                },
                ("query",),
            ),
            handler=search_text,
        ),
        ToolSpec(
            name="write_file",
            description="Create a UTF-8 text file or overwrite one only when overwrite is explicitly true.",
            parameters=object_schema(
                {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                ("path", "content"),
            ),
            handler=write_file,
            mutation_kind="file",
        ),
        ToolSpec(
            name="edit_file",
            description="Replace exactly one unique text block in an existing UTF-8 file.",
            parameters=object_schema(
                {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                ("path", "old_text", "new_text"),
            ),
            handler=edit_file,
            mutation_kind="file",
        ),
    ]
