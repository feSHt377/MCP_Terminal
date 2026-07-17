"""MCP Server 与 GUI 之间的本地 IPC。

GUI 是 SSH 会话的唯一所有者。MCP Server 通过仅监听回环地址、带随机令牌的
JSON-RPC 通道请求 GUI 执行操作，从而让人和 Agent 共同管理同一个会话。
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import socketserver
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
STATE_FILE = RUNTIME_DIR / "gui.json"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class GuiInstanceLock:
    """跨进程锁：保证同一工作区最多运行一个 GUI 实例。"""

    def __init__(self):
        self._file = None

    def acquire(self) -> bool:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        self._file = open(RUNTIME_DIR / "gui.lock", "a+b")
        self._file.seek(0)
        if self._file.read(1) != b"1":
            self._file.seek(0)
            self._file.write(b"1")
            self._file.flush()
        self._file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._file.close()
            self._file = None
            return False

    def wait_for_existing(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if gui_is_running():
                return True
            time.sleep(0.1)
        return False

    def release(self) -> None:
        if self._file is None:
            return
        try:
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None


def _read_state() -> dict[str, Any] | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def call_gui(method: str, params: dict[str, Any] | None = None, timeout: float = 180.0) -> dict[str, Any]:
    """调用当前 GUI；GUI 未运行或不可达时返回结构化错误。"""
    state = _read_state()
    if not state:
        return {"status": "error", "message": "GUI 未运行，请先调用 launch_gui"}

    request = {
        "token": state.get("token"),
        "method": method,
        "params": params or {},
    }
    payload = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")

    try:
        with socket.create_connection(("127.0.0.1", int(state["port"])), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(payload)
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    return {"status": "error", "message": "GUI IPC 响应过大"}
                if b"\n" in chunk:
                    break
        raw = b"".join(chunks).split(b"\n", 1)[0]
        return json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        return {"status": "error", "message": f"GUI IPC 不可用: {exc}"}


def gui_is_running() -> bool:
    return call_gui("ping", timeout=1.0).get("status") == "success"


@dataclass
class IPCRequest:
    method: str
    params: dict[str, Any]
    _event: threading.Event
    _result: dict[str, Any] | None = None

    def finish(self, result: dict[str, Any]) -> None:
        self._result = result
        self._event.set()

    def wait(self, timeout: float = 180.0) -> dict[str, Any]:
        if not self._event.wait(timeout):
            return {"status": "error", "message": f"GUI 操作超时: {self.method}"}
        return self._result or {"status": "error", "message": "GUI 未返回结果"}


class _ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class GuiIPCServer(QObject):
    """在后台线程接收 MCP 请求，并投递到 Qt 主线程。"""

    request_received = Signal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._token = secrets.token_urlsafe(32)
        self._server: _ThreadingServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                try:
                    data = json.loads(self.rfile.readline(MAX_RESPONSE_BYTES).decode("utf-8"))
                    if not secrets.compare_digest(str(data.get("token", "")), owner._token):
                        result = {"status": "error", "message": "GUI IPC 认证失败"}
                    else:
                        request = IPCRequest(
                            method=str(data.get("method", "")),
                            params=data.get("params") or {},
                            _event=threading.Event(),
                        )
                        owner.request_received.emit(request)
                        result = request.wait()
                except Exception as exc:
                    result = {"status": "error", "message": f"GUI IPC 请求失败: {exc}"}
                self.wfile.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))

        self._server = _ThreadingServer(("127.0.0.1", 0), Handler)
        port = int(self._server.server_address[1])
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        temp = STATE_FILE.with_suffix(".tmp")
        temp.write_text(
            json.dumps({"port": port, "token": self._token, "pid": os.getpid()}),
            encoding="utf-8",
        )
        temp.replace(STATE_FILE)

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        state = _read_state()
        if state and state.get("token") == self._token:
            try:
                STATE_FILE.unlink()
            except OSError:
                pass
