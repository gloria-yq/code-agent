import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent.config import AgentConfig
from code_agent.errors import ConfigurationError


class ConfigTests(unittest.TestCase):
    def test_loads_allowlisted_untracked_env_file(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "OPENAI_API_KEY=file-key\nOPENAI_MODEL=file-model\n", encoding="utf-8"
            )
            with patch.dict(os.environ, {}, clear=True):
                config = AgentConfig.from_env(directory)
            self.assertEqual(config.api_key, "file-key")
            self.assertEqual(config.model, "file-model")

    def test_process_environment_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text("OPENAI_API_KEY=file-key\n", encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "process-key"}, clear=True):
                config = AgentConfig.from_env(directory)
            self.assertEqual(config.api_key, "process-key")

    def test_rejects_unknown_env_file_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text("UNRELATED=value\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ConfigurationError):
                    AgentConfig.from_env(directory)


if __name__ == "__main__":
    unittest.main()

