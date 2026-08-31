"""Application service that wires the independent agent subsystems together."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .agent import CodingAgent
from .approval import ApprovalCallback, ApprovalPolicy
from .config import AgentConfig
from .context import ContextManager
from .events import AgentEvent
from .llm import OpenAICompatibleClient
from .prompt import build_system_prompt
from .protocol import ModelReply
from .security import SecretRedactor
from .session import SessionLogger
from .tools import ToolRegistry, build_file_tools, build_shell_tool
from .workspace import Workspace


@dataclass(frozen=True)
class AgentRuntime:
    agent: CodingAgent
    redactor: SecretRedactor


def create_runtime(
    config: AgentConfig,
    *,
    confirm: ApprovalCallback | None = None,
    on_status: Callable[[str, str], None] | None = None,
    on_event: Callable[[AgentEvent], None] | None = None,
    session_log: bool = True,
) -> AgentRuntime:
    redactor = SecretRedactor([config.api_key])
    workspace = Workspace(config.workspace)
    registry = ToolRegistry()
    for tool in build_file_tools(workspace):
        registry.register(tool)
    registry.register(
        build_shell_tool(
            workspace,
            timeout=config.command_timeout,
            output_limit=config.max_tool_output_chars,
            redact=redactor.text,
        )
    )
    log_path = None
    if session_log:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = config.workspace / ".code-agent" / "sessions" / f"{stamp}.jsonl"

    def safe_confirm(spec, arguments: dict[str, Any]) -> bool:
        return bool(confirm and confirm(spec, redactor.value(arguments)))

    def safe_status(kind: str, message: str) -> None:
        if on_status:
            on_status(kind, redactor.text(message))

    def safe_event(event: AgentEvent) -> None:
        if on_event:
            on_event(AgentEvent(event.kind, redactor.value(event.data)))

    agent = CodingAgent(
        client=OpenAICompatibleClient(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            provider=config.provider,
            deepseek_thinking=config.deepseek_thinking,
            timeout=config.request_timeout,
        ),
        tools=registry,
        context=ContextManager(
            char_budget=config.context_char_budget,
            max_tool_output_chars=config.max_tool_output_chars,
        ),
        approvals=ApprovalPolicy(config.approval_mode, safe_confirm),
        logger=SessionLogger(log_path, redact=redactor.value),
        max_turns=config.max_turns,
        max_consecutive_errors=config.max_consecutive_errors,
        on_status=safe_status,
        on_event=safe_event,
    )
    agent.start(build_system_prompt(config.workspace))
    return AgentRuntime(agent, redactor)


def test_model_connection(config: AgentConfig) -> ModelReply:
    """Perform one minimal real request before persisting a newly entered credential."""
    client = OpenAICompatibleClient(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        provider=config.provider,
        deepseek_thinking=False,
        timeout=min(config.request_timeout, 30.0),
        max_retries=0,
    )
    return client.complete(
        [{"role": "user", "content": "Reply with OK only."}],
        [],
    )
