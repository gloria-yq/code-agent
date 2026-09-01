"""Cross-platform lifecycle management for user-visible local applications."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import socket
import subprocess
import threading
import time
import uuid
import webbrowser
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, IO
from urllib.parse import urlparse

from .errors import ProcessError
from .security import sanitized_subprocess_env
from .workspace import Workspace

_MODES = {"auto", "terminal", "web", "desktop"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass
class ManagedProcess:
    process_id: str
    name: str
    mode: str
    command: str
    cwd: str
    process: Any
    url: str | None = None
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    stdout: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    stderr: deque[str] = field(default_factory=lambda: deque(maxlen=200))


class ProcessManager:
    """Own long-lived app processes without giving them model credentials."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        redact: Callable[[str], str] | None = None,
        opener: Callable[[str], bool] | None = None,
        popen: Callable[..., Any] | None = None,
    ):
        self.workspace = workspace
        self._redact = redact or (lambda value: value)
        self._opener = opener or webbrowser.open_new_tab
        self._popen = popen or subprocess.Popen
        self._items: dict[str, ManagedProcess] = {}
        self._lock = threading.Lock()

    def start(
        self,
        *,
        command: str,
        cwd: str = ".",
        mode: str = "auto",
        name: str | None = None,
        url: str | None = None,
        port: int | None = None,
        ready_timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        command = command.strip()
        if not command:
            raise ProcessError("Launch command cannot be empty.")
        if mode not in _MODES:
            raise ProcessError("Launch mode must be auto, terminal, web, or desktop.")
        if not 1 <= ready_timeout_seconds <= 30:
            raise ProcessError("Readiness timeout must be between 1 and 30 seconds.")
        if port is not None and not 1 <= port <= 65535:
            raise ProcessError("Port must be between 1 and 65535.")
        resolved_cwd = self.workspace.resolve(cwd, must_exist=True)
        if not resolved_cwd.is_dir():
            raise ProcessError("Launch working directory must be a directory.")

        resolved_mode = "web" if mode == "auto" and (url or port) else mode
        if resolved_mode == "auto":
            resolved_mode = "terminal"
        normalized_url, ready_port = self._resolve_web_target(
            resolved_mode, url, port
        )
        process = self._spawn(command, resolved_cwd, resolved_mode)
        process_id = uuid.uuid4().hex[:8]
        item = ManagedProcess(
            process_id=process_id,
            name=(name or resolved_cwd.name or "Application").strip()[:80],
            mode=resolved_mode,
            command=self._redact(command),
            cwd=self.workspace.display(resolved_cwd),
            process=process,
            url=normalized_url,
        )
        with self._lock:
            self._items[process_id] = item
        self._start_log_reader(process.stdout, item.stdout)
        self._start_log_reader(process.stderr, item.stderr)

        if resolved_mode == "web":
            assert ready_port is not None
            try:
                self._wait_until_ready(item, ready_port, ready_timeout_seconds)
                self.open(process_id)
            except ProcessError:
                self.stop(process_id)
                raise
        elif process.poll() is not None:
            self._close_streams(item)
            raise ProcessError(
                f"Application exited immediately with code {process.returncode}.\n"
                f"{self._logs(item)}"
            )
        return self.describe(process_id)

    def list(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            ids = tuple(self._items)
        return tuple(self.describe(process_id) for process_id in reversed(ids))

    def describe(self, process_id: str) -> dict[str, Any]:
        item = self._get(process_id)
        exit_code = item.process.poll()
        return {
            "ok": exit_code is None or exit_code == 0,
            "process_id": item.process_id,
            "name": item.name,
            "mode": item.mode,
            "status": "running" if exit_code is None else "stopped",
            "pid": item.process.pid,
            "command": item.command,
            "cwd": item.cwd,
            "url": item.url,
            "exit_code": exit_code,
            "started_at": item.started_at,
            "logs": self._logs(item),
        }

    def open(self, process_id: str) -> dict[str, Any]:
        item = self._get(process_id)
        if not item.url:
            raise ProcessError("This process has no browser preview URL.")
        self._validate_local_url(item.url)
        if item.process.poll() is not None:
            raise ProcessError("Cannot open a preview for a stopped process.")
        if not self._opener(item.url):
            raise ProcessError("The operating system could not open the default browser.")
        result = self.describe(process_id)
        result["opened"] = True
        return result

    def stop(self, process_id: str) -> dict[str, Any]:
        item = self._get(process_id)
        process = item.process
        if process.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=3)
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    pass
        result = self.describe(process_id)
        self._close_streams(item)
        result["stopped"] = result["status"] == "stopped"
        return result

    def stop_all(self) -> None:
        for item in self.list():
            if item["status"] == "running":
                self.stop(str(item["process_id"]))

    def has_running(self) -> bool:
        return any(item["status"] == "running" for item in self.list())

    def set_redactor(self, redact: Callable[[str], str]) -> None:
        self._redact = redact

    def _spawn(self, command: str, cwd: Path, mode: str):
        environment = sanitized_subprocess_env(os.environ)
        kwargs: dict[str, Any] = {
            "cwd": cwd,
            "env": environment,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        args: Any = command
        if mode == "terminal":
            args, shell = self._terminal_command(command, cwd)
            kwargs["shell"] = shell
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            else:
                kwargs["start_new_session"] = True
        else:
            kwargs.update(
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if os.name == "nt":
                flags = subprocess.CREATE_NEW_PROCESS_GROUP
                if mode == "web":
                    flags |= subprocess.CREATE_NO_WINDOW
                kwargs["creationflags"] = flags
            else:
                kwargs["start_new_session"] = True
        try:
            return self._popen(args, **kwargs)
        except OSError as exc:
            raise ProcessError(f"Cannot start application: {exc}") from exc

    @staticmethod
    def _terminal_command(command: str, cwd: Path) -> tuple[Any, bool]:
        if os.name == "nt":
            return command, True
        shell_command = f"cd {shlex.quote(str(cwd))} && {command}"
        if sys_platform() == "darwin":
            escaped = shell_command.replace("\\", "\\\\").replace('"', '\\"')
            script = f'tell application "Terminal" to do script "{escaped}"'
            return ["osascript", "-e", script], False
        candidates = (
            ("x-terminal-emulator", ["-e", "sh", "-lc", shell_command]),
            ("gnome-terminal", ["--", "sh", "-lc", shell_command]),
            ("konsole", ["-e", "sh", "-lc", shell_command]),
            ("xterm", ["-e", "sh", "-lc", shell_command]),
        )
        for executable, arguments in candidates:
            located = shutil.which(executable)
            if located:
                return [located, *arguments], False
        raise ProcessError(
            "No supported terminal launcher was found. Install x-terminal-emulator, "
            "gnome-terminal, konsole, or xterm."
        )

    @classmethod
    def _resolve_web_target(
        cls, mode: str, url: str | None, port: int | None
    ) -> tuple[str | None, int | None]:
        if mode != "web":
            if url or port:
                raise ProcessError("URL and port are only valid for web launch mode.")
            return None, None
        if not url and port is None:
            raise ProcessError("Web launch mode requires a localhost URL or port.")
        normalized = (url or f"http://127.0.0.1:{port}").strip()
        cls._validate_local_url(normalized)
        parsed = urlparse(normalized)
        resolved_port = port or parsed.port or (443 if parsed.scheme == "https" else 80)
        return normalized, resolved_port

    @staticmethod
    def _validate_local_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in _LOCAL_HOSTS:
            raise ProcessError("Preview URL must use http(s) on localhost or 127.0.0.1.")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ProcessError("Preview URL contains an invalid port.") from exc

    @staticmethod
    def _wait_until_ready(
        item: ManagedProcess, port: int, timeout_seconds: int
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if item.process.poll() is not None:
                raise ProcessError(
                    f"Web application exited before it became ready.\n"
                    f"{ProcessManager._logs(item)}"
                )
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                    return
            except OSError:
                time.sleep(0.1)
        raise ProcessError(
            f"Web application did not listen on port {port} within {timeout_seconds} seconds.\n"
            f"{ProcessManager._logs(item)}"
        )

    def _start_log_reader(self, stream: IO[str] | None, target: deque[str]) -> None:
        if stream is None:
            return

        def read() -> None:
            try:
                for line in stream:
                    target.append(self._redact(line.rstrip()))
            except (OSError, ValueError):
                return

        threading.Thread(target=read, daemon=True).start()

    @staticmethod
    def _close_streams(item: ManagedProcess) -> None:
        for stream in (item.process.stdout, item.process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    @staticmethod
    def _logs(item: ManagedProcess) -> str:
        stdout = "\n".join(item.stdout)
        stderr = "\n".join(item.stderr)
        combined = "\n".join(part for part in (stdout, stderr) if part)
        return combined[-4000:]

    def _get(self, process_id: str) -> ManagedProcess:
        with self._lock:
            try:
                return self._items[process_id]
            except KeyError as exc:
                raise ProcessError(f"Unknown process: {process_id}") from exc


def sys_platform() -> str:
    """Small seam for platform-specific tests."""
    import sys

    return sys.platform
