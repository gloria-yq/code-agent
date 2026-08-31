"""Runtime configuration with environment-only credential loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigurationError

_ALLOWED_ENV_FILE_KEYS = {
    "CODE_AGENT_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_THINKING",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
}


def load_untracked_env(path: Path) -> None:
    """Load a tiny, allowlisted .env format without overwriting process variables."""
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigurationError(f"Cannot read untracked config {path}: {exc}") from exc
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or key not in _ALLOWED_ENV_FILE_KEYS:
            raise ConfigurationError(
                f"Unsupported entry in {path.name} line {line_number}; only model settings are allowed"
            )
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class AgentConfig:
    api_key: str
    base_url: str
    model: str
    workspace: Path
    provider: str = "openai"
    deepseek_thinking: bool = True
    max_turns: int = 24
    max_consecutive_errors: int = 3
    request_timeout: float = 120.0
    command_timeout: float = 60.0
    context_char_budget: int = 120_000
    max_tool_output_chars: int = 20_000
    approval_mode: str = "auto-edit"

    @classmethod
    def from_env(
        cls,
        workspace: str | Path,
        *,
        model: str | None = None,
        base_url: str | None = None,
        provider: str | None = None,
        deepseek_thinking: str | None = None,
        max_turns: int = 24,
        approval_mode: str = "auto-edit",
    ) -> "AgentConfig":
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir():
            raise ConfigurationError(f"Workspace is not a directory: {root}")
        configured_env_file = os.getenv("CODE_AGENT_ENV_FILE", "").strip()
        env_file = (
            Path(configured_env_file).expanduser().resolve()
            if configured_env_file
            else root / ".env"
        )
        load_untracked_env(env_file)

        provider_setting = (provider or os.getenv("CODE_AGENT_PROVIDER", "auto")).strip().lower()
        if provider_setting not in {"auto", "openai", "deepseek"}:
            raise ConfigurationError("provider must be auto, openai, or deepseek.")

        candidate_base_url = (
            base_url
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("DEEPSEEK_BASE_URL")
            or "https://api.openai.com/v1"
        ).strip()
        host = (urlparse(candidate_base_url).hostname or "").lower()
        inferred_deepseek = host == "api.deepseek.com" or (
            bool(os.getenv("DEEPSEEK_API_KEY")) and not os.getenv("OPENAI_API_KEY")
        )
        resolved_provider = (
            "deepseek" if provider_setting == "auto" and inferred_deepseek else provider_setting
        )
        if resolved_provider == "auto":
            resolved_provider = "openai"

        if resolved_provider == "deepseek":
            api_key = (os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY", "")).strip()
            chosen_model = (
                model
                or os.getenv("DEEPSEEK_MODEL")
                or os.getenv("OPENAI_MODEL")
                or "deepseek-v4-flash"
            ).strip()
            chosen_base_url = (
                base_url
                or os.getenv("DEEPSEEK_BASE_URL")
                or os.getenv("OPENAI_BASE_URL")
                or "https://api.deepseek.com"
            ).strip()
        else:
            api_key = os.getenv("OPENAI_API_KEY", "").strip()
            chosen_model = (model or os.getenv("OPENAI_MODEL", "gpt-5.4-mini")).strip()
            chosen_base_url = (
                base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            ).strip()
        if not api_key:
            raise ConfigurationError(
                "No model API key is set. Export OPENAI_API_KEY or DEEPSEEK_API_KEY; "
                "never put it in the repository."
            )
        if not chosen_model:
            raise ConfigurationError("The model name cannot be empty.")
        if not chosen_base_url.startswith(("http://", "https://")):
            raise ConfigurationError("OPENAI_BASE_URL must start with http:// or https://.")
        if max_turns < 1:
            raise ConfigurationError("max_turns must be at least 1.")
        if approval_mode not in {"suggest", "auto-edit", "full"}:
            raise ConfigurationError("approval_mode must be suggest, auto-edit, or full.")
        thinking_setting = (
            deepseek_thinking or os.getenv("DEEPSEEK_THINKING", "enabled")
        ).strip().lower()
        if thinking_setting not in {"enabled", "disabled"}:
            raise ConfigurationError("DEEPSEEK_THINKING must be enabled or disabled.")

        return cls(
            api_key=api_key,
            base_url=chosen_base_url.rstrip("/"),
            model=chosen_model,
            workspace=root,
            provider=resolved_provider,
            deepseek_thinking=thinking_setting == "enabled",
            max_turns=max_turns,
            approval_mode=approval_mode,
        )
