import unittest

from code_agent.security import (
    SecretRedactor,
    environment_name_is_sensitive,
    sanitized_subprocess_env,
)


class SecurityTests(unittest.TestCase):
    def test_detects_common_credential_environment_names(self):
        sensitive = [
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "GITHUB_TOKEN",
            "DATABASE_PASSWORD",
            "AWS_SECRET_ACCESS_KEY",
            "CLIENT_CREDENTIALS",
            "CODE_AGENT_ENV_FILE",
        ]
        for name in sensitive:
            with self.subTest(name=name):
                self.assertTrue(environment_name_is_sensitive(name))
        self.assertFalse(environment_name_is_sensitive("PATH"))
        self.assertFalse(environment_name_is_sensitive("PYTHONPATH"))
        self.assertFalse(environment_name_is_sensitive("OPENAI_MODEL"))

    def test_subprocess_environment_keeps_toolchain_but_removes_credentials(self):
        source = {
            "PATH": "tool-path",
            "SystemRoot": "windows-root",
            "VIRTUAL_ENV": "venv-path",
            "OPENAI_API_KEY": "openai-secret",
            "DEEPSEEK_API_KEY": "deepseek-secret",
            "GITHUB_TOKEN": "github-secret",
            "CODE_AGENT_ENV_FILE": "private-config-path",
        }
        cleaned = sanitized_subprocess_env(source)
        self.assertEqual(cleaned["PATH"], "tool-path")
        self.assertEqual(cleaned["SystemRoot"], "windows-root")
        self.assertEqual(cleaned["VIRTUAL_ENV"], "venv-path")
        self.assertNotIn("OPENAI_API_KEY", cleaned)
        self.assertNotIn("DEEPSEEK_API_KEY", cleaned)
        self.assertNotIn("GITHUB_TOKEN", cleaned)
        self.assertNotIn("CODE_AGENT_ENV_FILE", cleaned)

    def test_redacts_known_secret_recursively(self):
        redactor = SecretRedactor(["super-secret-value"])
        payload = {
            "message": "Bearer super-secret-value",
            "nested": ["prefix-super-secret-value-suffix"],
        }
        redacted = redactor.value(payload)
        self.assertEqual(redacted["message"], "Bearer [REDACTED]")
        self.assertEqual(redacted["nested"], ["prefix-[REDACTED]-suffix"])
        self.assertNotIn("super-secret-value", repr(redacted))


if __name__ == "__main__":
    unittest.main()
