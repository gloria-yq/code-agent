"""Tiny JSON-backed todo CLI used as a Code Agent demonstration workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_tasks(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_tasks(path: Path, tasks: list[dict]) -> None:
    path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def add_task(path: Path, title: str) -> None:
    tasks = load_tasks(path)
    tasks.append({"title": title, "done": False})
    save_tasks(path, tasks)


def list_tasks(path: Path) -> list[str]:
    lines = []
    for index, task in enumerate(load_tasks(path), 1):
        marker = "x" if task["done"] else " "
        lines.append(f"{index}. [{marker}] {task['title']}")
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, default=Path("tasks.json"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    add = subparsers.add_parser("add")
    add.add_argument("title")
    subparsers.add_parser("list")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "add":
        add_task(args.file, args.title)
    elif args.command == "list":
        print("\n".join(list_tasks(args.file)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

