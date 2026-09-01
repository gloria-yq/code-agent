import json
import tempfile
import unittest
from pathlib import Path

from code_agent.errors import ConfigurationError
from code_agent.settings import SettingsService


class MemoryCredentialStore:
    def __init__(self):
        self.values: dict[str, str] = {}

    def get(self, provider: str) -> str | None:
        return self.values.get(provider)

    def set(self, provider: str, api_key: str) -> None:
        self.values[provider] = api_key

    def delete(self, provider: str) -> None:
        self.values.pop(provider, None)


class SettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = MemoryCredentialStore()
        self.service = SettingsService(
            self.root / "user" / "settings.json",
            credentials=self.store,
            environment={},
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_configure_keeps_secret_out_of_public_settings(self):
        secret = "deepseek-secret-value"
        self.service.configure_provider(
            "deepseek",
            api_key=secret,
            base_url="https://api.deepseek.com/",
            model="deepseek-v4-flash",
            thinking=True,
        )
        raw = self.service.path.read_text(encoding="utf-8")
        self.assertNotIn(secret, raw)
        self.assertNotIn("api_key", raw.lower())
        self.assertEqual(self.store.get("deepseek"), secret)

    def test_resolve_uses_keyring_credential(self):
        self.store.set("deepseek", "stored-secret")
        config = self.service.resolve(self.root)
        self.assertEqual(config.provider, "deepseek")
        self.assertEqual(config.api_key, "stored-secret")

    def test_environment_takes_precedence_over_keyring(self):
        self.store.set("deepseek", "stored-secret")
        service = SettingsService(
            self.service.path,
            credentials=self.store,
            environment={"DEEPSEEK_API_KEY": "environment-secret"},
        )
        self.assertEqual(service.resolve(self.root).api_key, "environment-secret")

    def test_fresh_install_infers_openai_from_only_available_environment_key(self):
        service = SettingsService(
            self.service.path,
            credentials=self.store,
            environment={"OPENAI_API_KEY": "openai-secret"},
        )
        config = service.resolve(self.root)
        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.api_key, "openai-secret")

    def test_auto_provider_honors_the_only_stored_credential(self):
        self.store.set("openai", "stored-openai-secret")
        config = self.service.resolve(self.root, provider="auto")
        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.api_key, "stored-openai-secret")

    def test_external_env_file_remains_supported(self):
        external = self.root / "credentials.env"
        external.write_text(
            "CODE_AGENT_PROVIDER=openai\nOPENAI_API_KEY=external-secret\n",
            encoding="utf-8",
        )
        service = SettingsService(
            self.service.path,
            credentials=self.store,
            environment={"CODE_AGENT_ENV_FILE": str(external)},
        )
        config = service.resolve(self.root)
        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.api_key, "external-secret")

    def test_failed_public_save_restores_previous_credential(self):
        self.store.set("deepseek", "old-secret")

        class FailingSettings(SettingsService):
            def save(self, settings):
                raise ConfigurationError("write failed")

        service = FailingSettings(
            self.service.path, credentials=self.store, environment={}
        )
        with self.assertRaises(ConfigurationError):
            service.configure_provider(
                "deepseek",
                api_key="new-secret",
                base_url="https://api.deepseek.com",
                model="deepseek-v4-flash",
                thinking=True,
            )
        self.assertEqual(self.store.get("deepseek"), "old-secret")

    def test_select_model_writes_only_public_model_setting(self):
        self.store.set("deepseek", "stored-secret")
        self.service.select_model("deepseek", "custom-model")
        payload = json.loads(self.service.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["providers"]["deepseek"]["model"], "custom-model")
        self.assertNotIn("stored-secret", json.dumps(payload))

    def test_select_approval_mode_persists_only_public_setting(self):
        self.store.set("deepseek", "stored-secret")

        settings = self.service.select_approval_mode("suggest")

        self.assertEqual(settings.approval_mode, "suggest")
        payload = json.loads(self.service.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["approval_mode"], "suggest")
        self.assertNotIn("stored-secret", json.dumps(payload))

        with self.assertRaises(ConfigurationError):
            self.service.select_approval_mode("unsafe")

    def test_rejects_string_boolean_in_public_settings(self):
        self.service.path.parent.mkdir(parents=True)
        self.service.path.write_text(
            json.dumps({"providers": {"deepseek": {"thinking": "false"}}}),
            encoding="utf-8",
        )
        with self.assertRaises(ConfigurationError):
            self.service.load()

    def test_remember_workspace_is_deduplicated_and_contains_no_secret(self):
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir()
        second.mkdir()
        self.store.set("deepseek", "stored-secret")

        self.service.remember_workspace(first)
        self.service.remember_workspace(second)
        settings = self.service.remember_workspace(first)

        self.assertEqual(
            settings.recent_workspaces,
            (str(first.resolve()), str(second.resolve())),
        )
        raw = self.service.path.read_text(encoding="utf-8")
        self.assertNotIn("stored-secret", raw)

    def test_rejects_invalid_recent_workspace_shape(self):
        self.service.path.parent.mkdir(parents=True)
        self.service.path.write_text(
            json.dumps({"recent_workspaces": "not-a-list"}), encoding="utf-8"
        )
        with self.assertRaises(ConfigurationError):
            self.service.load()


if __name__ == "__main__":
    unittest.main()
