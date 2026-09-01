import os
import socket
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from code_agent.errors import ProcessError, ToolError
from code_agent.processes import ProcessManager
from code_agent.tools.process import build_process_tools
from code_agent.workspace import Workspace


class FakeProcess:
    def __init__(self, pid=4321):
        self.pid = pid
        self.returncode = None
        self.stdout = StringIO("")
        self.stderr = StringIO("")

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = -1
        return self.returncode

    def kill(self):
        self.returncode = -9


class ProcessManagerTests(unittest.TestCase):
    def test_terminal_launch_uses_new_console_and_strips_credentials_on_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []

            def fake_popen(args, **kwargs):
                calls.append((args, kwargs))
                return FakeProcess()

            manager = ProcessManager(Workspace(Path(directory)), popen=fake_popen)
            # Headless Linux CI has no installed terminal emulator. Mock discovery here:
            # this test verifies spawn configuration, not the runner's desktop packages.
            with (
                patch.dict(os.environ, {"DEMO_API_KEY": "never-pass-this"}),
                patch(
                    "code_agent.processes.shutil.which",
                    return_value="/usr/bin/fake-terminal",
                ),
            ):
                result = manager.start(command="python game.py", mode="terminal")

            self.assertEqual(result["status"], "running")
            self.assertEqual(result["mode"], "terminal")
            if os.name == "nt":
                self.assertTrue(
                    calls[0][1]["creationflags"] & subprocess.CREATE_NEW_CONSOLE
                )
            self.assertNotIn("DEMO_API_KEY", calls[0][1]["env"])
            self.assertNotIn("stdout", calls[0][1])

    def test_web_launch_waits_then_opens_only_local_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            opened = []
            manager = ProcessManager(
                Workspace(Path(directory)),
                popen=lambda *_args, **_kwargs: FakeProcess(),
                opener=lambda url: opened.append(url) is None or True,
            )
            with patch.object(manager, "_wait_until_ready") as ready:
                result = manager.start(
                    command="python -m http.server 8123",
                    mode="web",
                    port=8123,
                )

            ready.assert_called_once()
            self.assertEqual(opened, ["http://127.0.0.1:8123"])
            self.assertEqual(result["url"], opened[0])
            with self.assertRaises(ProcessError):
                manager.start(
                    command="python server.py",
                    mode="web",
                    url="https://example.com",
                )
            with self.assertRaisesRegex(ProcessError, "requires a localhost URL or port"):
                manager.start(command="python server.py", mode="web")

    def test_real_web_process_reaches_port_and_can_be_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "server.py"
            script.write_text(
                "from http.server import HTTPServer, SimpleHTTPRequestHandler\n"
                "import sys\n"
                "HTTPServer(('127.0.0.1', int(sys.argv[1])), "
                "SimpleHTTPRequestHandler).serve_forever()\n",
                encoding="utf-8",
            )
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            opened = []
            manager = ProcessManager(
                Workspace(root), opener=lambda url: opened.append(url) is None or True
            )
            command = f'"{sys.executable}" server.py {port}'
            result = manager.start(
                command=command,
                mode="web",
                port=port,
                ready_timeout_seconds=10,
            )
            try:
                self.assertEqual(result["status"], "running")
                self.assertEqual(opened, [f"http://127.0.0.1:{port}"])
            finally:
                stopped = manager.stop(result["process_id"])
            self.assertEqual(stopped["status"], "stopped")

    def test_process_tools_reuse_command_safety_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ProcessManager(
                Workspace(Path(directory)), popen=lambda *_a, **_k: FakeProcess()
            )
            tools = {tool.name: tool for tool in build_process_tools(manager)}
            self.assertEqual(
                set(tools),
                {"launch_app", "list_processes", "stop_process", "open_preview"},
            )
            with self.assertRaises(ToolError):
                tools["launch_app"].handler({"command": "git reset --hard"})
            with self.assertRaises(ToolError):
                tools["launch_app"].handler({"command": "type .env"})


if __name__ == "__main__":
    unittest.main()
