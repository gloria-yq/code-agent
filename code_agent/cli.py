"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .agent import CodingAgent
from .approval import ApprovalPolicy
from .config import AgentConfig
from .context import ContextManager
from .errors import CodeAgentError, ConfigurationError
from .llm import OpenAICompatibleClient
from .prompt import build_system_prompt
from .session import SessionLogger
from .tools import ToolRegistry, build_file_tools, build_shell_tool
from .workspace import Workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-agent", description="A small coding agent with local file and command tools."
    )
    parser.add_argument("task", nargs="?", help="Programming task; prompted interactively if omitted")
    parser.add_argument("--workspace", default=".", help="Directory the agent may access")
    parser.add_argument("--model", help="Model name; defaults to OPENAI_MODEL")
    parser.add_argument("--base-url", help="OpenAI-compatible /v1 base URL")
    parser.add_argument("--max-turns", type=int, default=24)
    parser.add_argument(
        "--approval-mode",
        choices=("suggest", "auto-edit", "full"),
        default="auto-edit",
        help="suggest confirms all mutations; auto-edit confirms commands; full confirms none",
    )
    parser.add_argument("--no-session-log", action="store_true")
    return parser


def _confirm(spec, arguments) -> bool:
    print(f"\nApproval required for {spec.name}:")
    for key, value in arguments.items():
        rendered = repr(value)
        print(f"  {key}: {rendered[:500]}")
    try:
        return input("Allow? [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def _status(kind: str, message: str) -> None:
    marker = {"model": "MODEL", "tool": "TOOL"}.get(kind, kind.upper())
    print(f"[{marker}] {message}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    task = args.task
    if not task:
        try:
            task = input("Describe the programming task: ").strip()
        except EOFError:
            task = ""
    try:
        config = AgentConfig.from_env(
            args.workspace,
            model=args.model,
            base_url=args.base_url,
            max_turns=args.max_turns,
            approval_mode=args.approval_mode,
        )
        workspace = Workspace(config.workspace)
        registry = ToolRegistry()
        for tool in build_file_tools(workspace):
            registry.register(tool)
        registry.register(
            build_shell_tool(
                workspace,
                timeout=config.command_timeout,
                output_limit=config.max_tool_output_chars,
            )
        )

        log_path = None
        if not args.no_session_log:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            log_path = config.workspace / ".code-agent" / "sessions" / f"{stamp}.jsonl"
        agent = CodingAgent(
            client=OpenAICompatibleClient(
                api_key=config.api_key,
                base_url=config.base_url,
                model=config.model,
                timeout=config.request_timeout,
            ),
            tools=registry,
            context=ContextManager(
                char_budget=config.context_char_budget,
                max_tool_output_chars=config.max_tool_output_chars,
            ),
            approvals=ApprovalPolicy(config.approval_mode, _confirm),
            logger=SessionLogger(log_path),
            max_turns=config.max_turns,
            max_consecutive_errors=config.max_consecutive_errors,
            on_status=_status,
        )
        print(f"Workspace: {config.workspace}")
        print(f"Model: {config.model}")
        print(f"Approval mode: {config.approval_mode}\n")
        result = agent.run(task or "", build_system_prompt(config.workspace))
        if result.final_text:
            print(f"\n{result.final_text}")
        print(
            f"\n[RESULT] status={result.status} turns={result.turns} "
            f"tool_calls={result.tool_calls}"
        )
        if result.error:
            print(f"[ERROR] {result.error}", file=sys.stderr)
        return 0 if result.status == "completed" else 1
    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        return 130
    except (ConfigurationError, CodeAgentError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

