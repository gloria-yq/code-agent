"""Shared provider settings for CLI, TUI, and future presentation layers."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

from .config import AgentConfig, read_untracked_env
from .credentials import CredentialStore, KeyringCredentialStore
from .errors import ConfigurationError


@dataclass(frozen=True)
class ProviderSettings:
    base_url: str
    model: str
    thinking: bool = True


@dataclass(frozen=True)
class UserSettings:
    default_provider: str = "deepseek"
    providers: dict[str, ProviderSettings] = field(
        default_factory=lambda: {
            "deepseek": ProviderSettings(
                "https://api.deepseek.com", "deepseek-v4-flash", True
            ),
            "openai": ProviderSettings(
                "https://api.openai.com/v1", "gpt-5.4-mini", False
            ),
        }
    )
    approval_mode: str = "auto-edit"
    theme: str = "code-agent-dark"


class SettingsService:
    """Resolve public settings separately from provider credentials."""

    def __init__(
        self,
        path: Path | None = None,
        credentials: CredentialStore | None = None,
        environment: dict[str, str] | None = None,
    ):
        self.path = path or user_config_path("code-agent", "gloria-yq") / "settings.json"
        self.credentials = credentials or KeyringCredentialStore()
        self.environment = environment if environment is not None else os.environ

    def load(self) -> UserSettings:
        if not self.path.exists():
            return UserSettings()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Cannot read user settings {self.path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ConfigurationError("User settings must contain a JSON object.")
        defaults = UserSettings()
        provider_payload = payload.get("providers", {})
        if not isinstance(provider_payload, dict):
            raise ConfigurationError("settings.providers must be an object.")
        providers = dict(defaults.providers)
        for provider, raw in provider_payload.items():
            if provider not in {"deepseek", "openai"} or not isinstance(raw, dict):
                raise ConfigurationError(f"Unsupported provider settings: {provider}")
            fallback = providers[provider]
            thinking = raw.get("thinking", fallback.thinking)
            if not isinstance(thinking, bool):
                raise ConfigurationError(
                    f"settings.providers.{provider}.thinking must be a boolean."
                )
            providers[provider] = ProviderSettings(
                base_url=str(raw.get("base_url", fallback.base_url)).strip(),
                model=str(raw.get("model", fallback.model)).strip(),
                thinking=thinking,
            )
            if not providers[provider].base_url.startswith(("http://", "https://")):
                raise ConfigurationError(
                    f"settings.providers.{provider}.base_url must be an HTTP(S) URL."
                )
            if not providers[provider].model:
                raise ConfigurationError(
                    f"settings.providers.{provider}.model cannot be empty."
                )
        default_provider = str(
            payload.get("default_provider", defaults.default_provider)
        ).strip().lower()
        approval_mode = str(payload.get("approval_mode", defaults.approval_mode)).strip()
        theme = str(payload.get("theme", defaults.theme)).strip()
        if default_provider not in providers:
            raise ConfigurationError("default_provider must name a configured provider.")
        if approval_mode not in {"suggest", "auto-edit", "full"}:
            raise ConfigurationError("approval_mode must be suggest, auto-edit, or full.")
        return UserSettings(default_provider, providers, approval_mode, theme)

    def save(self, settings: UserSettings) -> None:
        payload: dict[str, Any] = {
            "default_provider": settings.default_provider,
            "providers": {
                name: asdict(provider) for name, provider in settings.providers.items()
            },
            "approval_mode": settings.approval_mode,
            "theme": settings.theme,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(temporary, self.path)
        except OSError as exc:
            raise ConfigurationError(f"Cannot save user settings {self.path}: {exc}") from exc

    def configure_provider(
        self,
        provider: str,
        *,
        api_key: str,
        base_url: str,
        model: str,
        thinking: bool,
    ) -> UserSettings:
        provider = provider.strip().lower()
        if provider not in {"deepseek", "openai"}:
            raise ConfigurationError("provider must be deepseek or openai.")
        if not base_url.startswith(("http://", "https://")):
            raise ConfigurationError("Base URL must start with http:// or https://.")
        if not model.strip():
            raise ConfigurationError("Model cannot be empty.")
        api_key = api_key.strip()
        if not api_key:
            raise ConfigurationError("API key cannot be empty.")
        current = self.load()
        providers = dict(current.providers)
        providers[provider] = ProviderSettings(base_url.rstrip("/"), model.strip(), thinking)
        updated = UserSettings(
            default_provider=provider,
            providers=providers,
            approval_mode=current.approval_mode,
            theme=current.theme,
        )
        # Keep the public file and keyring update transactional where possible.
        previous_key = self.credentials.get(provider)
        self.credentials.set(provider, api_key)
        try:
            self.save(updated)
        except Exception:
            if previous_key is None:
                self.credentials.delete(provider)
            else:
                self.credentials.set(provider, previous_key)
            raise
        return updated

    def disconnect(self, provider: str) -> None:
        self.credentials.delete(provider.strip().lower())

    def select_model(self, provider: str, model: str) -> UserSettings:
        provider = provider.strip().lower()
        model = model.strip()
        current = self.load()
        if provider not in current.providers:
            raise ConfigurationError(f"Provider is not configured: {provider}")
        if not model:
            raise ConfigurationError("Model cannot be empty.")
        providers = dict(current.providers)
        selected = providers[provider]
        providers[provider] = ProviderSettings(
            selected.base_url, model, selected.thinking
        )
        updated = UserSettings(provider, providers, current.approval_mode, current.theme)
        self.save(updated)
        return updated

    def credential_source(self, provider: str, workspace: Path) -> str | None:
        environment = self._environment_with_file(workspace)
        key_name = "DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"
        if environment.get(key_name, "").strip():
            return "environment"
        return "system-keyring" if self.credentials.get(provider) else None

    def resolve(
        self,
        workspace: str | Path,
        *,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        deepseek_thinking: str | None = None,
        max_turns: int = 24,
        approval_mode: str | None = None,
    ) -> AgentConfig:
        root = Path(workspace).expanduser().resolve()
        public = self.load()
        environment = self._environment_with_file(root)
        requested_provider = provider or environment.get("CODE_AGENT_PROVIDER")
        if requested_provider:
            chosen_provider = requested_provider.strip().lower()
        elif not self.path.exists():
            chosen_provider = self._infer_provider(
                environment, public.default_provider, base_url
            )
        else:
            chosen_provider = public.default_provider
        if chosen_provider == "auto":
            chosen_provider = self._infer_provider(
                environment, public.default_provider, base_url
            )
        if chosen_provider not in public.providers:
            raise ConfigurationError(f"Provider is not configured: {chosen_provider}")
        provider_settings = public.providers[chosen_provider]
        key_name = (
            "DEEPSEEK_API_KEY" if chosen_provider == "deepseek" else "OPENAI_API_KEY"
        )
        if not environment.get(key_name, "").strip():
            stored = self.credentials.get(chosen_provider)
            if stored:
                environment[key_name] = stored
        return AgentConfig.from_mapping(
            root,
            environment,
            provider=chosen_provider,
            model=model or provider_settings.model,
            base_url=base_url or provider_settings.base_url,
            deepseek_thinking=(
                deepseek_thinking
                or ("enabled" if provider_settings.thinking else "disabled")
            ),
            max_turns=max_turns,
            approval_mode=approval_mode or public.approval_mode,
        )

    def _environment_with_file(self, workspace: Path) -> dict[str, str]:
        environment = dict(self.environment)
        configured = environment.get("CODE_AGENT_ENV_FILE", "").strip()
        env_file = Path(configured).expanduser().resolve() if configured else workspace / ".env"
        file_values = read_untracked_env(env_file)
        file_values.update(environment)
        return file_values

    def _infer_provider(
        self,
        environment: dict[str, str],
        fallback: str,
        base_url: str | None,
    ) -> str:
        candidate_url = (
            base_url
            or environment.get("DEEPSEEK_BASE_URL")
            or environment.get("OPENAI_BASE_URL")
            or ""
        ).lower()
        if "api.deepseek.com" in candidate_url:
            return "deepseek"
        has_deepseek = bool(environment.get("DEEPSEEK_API_KEY", "").strip())
        has_openai = bool(environment.get("OPENAI_API_KEY", "").strip())
        if has_deepseek != has_openai:
            return "deepseek" if has_deepseek else "openai"
        if not has_deepseek:
            stored_deepseek = bool(self.credentials.get("deepseek"))
            stored_openai = bool(self.credentials.get("openai"))
            if stored_deepseek != stored_openai:
                return "deepseek" if stored_deepseek else "openai"
        return fallback
