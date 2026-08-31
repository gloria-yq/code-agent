"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from .agent import CodingAgent
from .errors import CodeAgentError, ConfigurationError
from .service import create_runtime
from .settings import SettingsService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-agent", description="A small coding agent with local file and command tools."
    )
    parser.add_argument("task", nargs="?", help="One-shot task; omit to start interactive chat")
    parser.add_argument("--workspace", default=".", help="Directory the agent may access")
    parser.add_argument("--model", help="Model name; defaults to OPENAI_MODEL")
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL")
    parser.add_argument(
        "--provider",
        choices=("auto", "openai", "deepseek"),
        help="Compatibility mode; auto detects the official DeepSeek endpoint",
    )
    parser.add_argument(
        "--deepseek-thinking",
        choices=("enabled", "disabled"),
        help="DeepSeek thinking mode; defaults to enabled",
    )
    parser.add_argument("--max-turns", type=int, default=24)
    parser.add_argument(
        "--approval-mode",
        choices=("suggest", "auto-edit", "full"),
        help="Overrides saved mode; suggest confirms all mutations; auto-edit confirms commands",
    )
    parser.add_argument("--no-session-log", action="store_true")
    parser.add_argument(
        "--classic",
        action="store_true",
        help="Use the legacy line-oriented conversation instead of the Textual TUI",
    )
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


_INTERACTIVE_HELP = """Interactive commands:
  /help       Show this help
  /new        Clear conversation context and start a new session
  /history    Show the current conversation transcript
  /status     Show message, model-turn, and tool-call counts
  /exit       Exit Code Agent (aliases: /quit, /q)

Any other input is a follow-up in the same conversation."""


def _print_result(result) -> None:
    if result.final_text:
        print(f"\nAssistant> {result.final_text}")
    print(
        f"\n[RESULT] status={result.status} turns={result.turns} "
        f"tool_calls={result.tool_calls}"
    )
    if result.error:
        print(f"[ERROR] {result.error}", file=sys.stderr)


def _print_history(agent: CodingAgent) -> None:
    visible = [message for message in agent.history() if message.get("role") != "system"]
    if not visible:
        print("Conversation is empty.")
        return
    for index, message in enumerate(visible, 1):
        role = message.get("role", "unknown")
        if role == "tool":
            label = f"tool:{message.get('name', 'unknown')}"
            text = "[result recorded]"
        else:
            label = "you" if role == "user" else role
            text = str(message.get("content") or "")
            if not text and message.get("tool_calls"):
                names = [
                    call.get("function", {}).get("name", "unknown")
                    for call in message["tool_calls"]
                ]
                text = f"[tool calls: {', '.join(names)}]"
        if len(text) > 500:
            text = text[:500] + "...[truncated]"
        print(f"{index:>3} {label}> {text}")


def _interactive_loop(agent: CodingAgent) -> int:
    print("\nInteractive conversation started. Type /help for commands; /exit to quit.")
    while True:
        try:
            user_input = input("\nYou> ").strip()
        except EOFError:
            print("\nSession ended.")
            return 0
        except KeyboardInterrupt:
            print("\nInput cleared. Type /exit to quit.")
            continue
        if not user_input:
            continue
        if user_input in {"/exit", "/quit", "/q"}:
            print("Session ended.")
            return 0
        if user_input == "/help":
            print(_INTERACTIVE_HELP)
            continue
        if user_input == "/new":
            agent.reset()
            print("Started a new conversation.")
            continue
        if user_input == "/history":
            _print_history(agent)
            continue
        if user_input == "/status":
            stats = agent.stats()
            print(
                "Conversation status: "
                f"user_turns={stats['user_turns']} "
                f"model_turns={stats['model_turns']} "
                f"tool_calls={stats['tool_calls']} messages={stats['messages']}"
            )
            continue
        if user_input.startswith("/"):
            print(f"Unknown command: {user_input}. Type /help for available commands.")
            continue
        _print_result(agent.run(user_input))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = SettingsService()
        if args.task is None and not args.classic:
            from .tui import CodeAgentApp

            CodeAgentApp(
                args.workspace,
                settings=settings,
                model=args.model,
                base_url=args.base_url,
                provider=args.provider,
                deepseek_thinking=args.deepseek_thinking,
                max_turns=args.max_turns,
                approval_mode=args.approval_mode,
                session_log=not args.no_session_log,
            ).run()
            return 0

        config = settings.resolve(
            args.workspace,
            model=args.model,
            base_url=args.base_url,
            provider=args.provider,
            deepseek_thinking=args.deepseek_thinking,
            max_turns=args.max_turns,
            approval_mode=args.approval_mode,
        )
        runtime = create_runtime(
            config,
            confirm=_confirm,
            on_status=_status,
            session_log=not args.no_session_log,
        )
        agent = runtime.agent
        print(f"Workspace: {config.workspace}")
        print(f"Model: {config.model}")
        print(f"Provider compatibility: {config.provider}")
        print(f"Approval mode: {config.approval_mode}\n")
        if args.task is None:
            return _interactive_loop(agent)
        result = agent.run(args.task)
        _print_result(result)
        if result.status == "interrupted":
            return 130
        return 0 if result.status == "completed" else 1
    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        return 130
    except (ConfigurationError, CodeAgentError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
