"""SSH 连接管理器 — 管理多服务器 SSH 会话。

使用 asyncssh 建立交互式 shell 会话，支持：
- 多会话管理（按 session_id 索引）
- 命令执行与输出读取
- 自动重连
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncssh

logger = logging.getLogger("mcpterminal.ssh")


@dataclass
class SSHSession:
    """单个 SSH 会话的状态。"""

    session_id: str
    host: str
    port: int = 22
    user: str = "root"
    conn: asyncssh.SSHClientConnection | None = None
    shell: asyncssh.SSHClientProcess | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    output_buffer: list[str] = field(default_factory=list)

    def touch(self) -> None:
        self.last_used = datetime.now().isoformat()


class SSHManager:
    """SSH 会话管理器（单例）。"""

    _instance: SSHManager | None = None

    def __new__(cls) -> SSHManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions: dict[str, SSHSession] = {}
        return cls._instance

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    async def connect(
        self,
        host: str,
        user: str = "root",
        port: int = 22,
        password: str | None = None,
        key_path: str | None = None,
    ) -> dict[str, Any]:
        """建立 SSH 连接并打开交互式 shell。

        Args:
            host: 服务器地址。
            user: 登录用户名。
            port: SSH 端口。
            password: 密码（与 key_path 二选一）。
            key_path: 私钥路径。
        """
        session_id = f"{user}@{host}:{port}"

        # 同一个 session_id 只保留一条连接；不同 session_id 可同时存在。
        existing = self._sessions.get(session_id)
        if existing is not None and existing.conn is not None and not existing.conn.is_closed():
            existing.touch()
            return {
                "status": "success",
                "session_id": session_id,
                "message": f"已复用当前会话 {session_id}",
                "reused": True,
            }

        if existing is not None:
            await self.disconnect(session_id)

        try:
            # 准备认证参数
            connect_kwargs: dict[str, Any] = {"port": port, "known_hosts": None}
            if key_path:
                key_path = os.path.expanduser(key_path)
                connect_kwargs["client_keys"] = [key_path]
            elif password:
                connect_kwargs["password"] = password
            else:
                # 尝试默认密钥
                connect_kwargs["client_keys"] = [
                    os.path.expanduser("~/.ssh/id_rsa"),
                    os.path.expanduser("~/.ssh/id_ed25519"),
                ]

            conn = await asyncssh.connect(host, username=user, **connect_kwargs)

            # 打开交互式 shell（PTY）
            shell = await conn.create_process(
                term_type="xterm-256color",
                term_size=(80, 24),
            )

            session = SSHSession(
                session_id=session_id,
                host=host,
                port=port,
                user=user,
                conn=conn,
                shell=shell,
            )
            self._sessions[session_id] = session

            logger.info("SSH 连接成功: %s", session_id)
            return {
                "status": "success",
                "session_id": session_id,
                "message": f"已连接到 {session_id}",
            }

        except asyncssh.Error as e:
            logger.error("SSH 连接失败 %s: %s", session_id, e)
            return {"status": "error", "session_id": session_id, "message": str(e)}
        except OSError as e:
            logger.error("SSH 连接失败 %s: %s", session_id, e)
            return {"status": "error", "session_id": session_id, "message": str(e)}

    async def disconnect(self, session_id: str) -> dict[str, Any]:
        """断开指定 SSH 会话。"""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return {"status": "error", "message": f"会话不存在: {session_id}"}

        try:
            if session.shell is not None:
                session.shell.close()
            if session.conn is not None:
                session.conn.close()
            logger.info("SSH 已断开: %s", session_id)
            return {"status": "success", "message": f"已断开 {session_id}"}
        except Exception as e:
            logger.error("断开 SSH 失败 %s: %s", session_id, e)
            return {"status": "error", "message": str(e)}

    async def disconnect_all(self) -> dict[str, Any]:
        """断开所有 SSH 会话。"""
        session_ids = list(self._sessions.keys())
        results = []
        for sid in session_ids:
            result = await self.disconnect(sid)
            results.append(result)
        return {
            "status": "success",
            "disconnected": len(results),
            "details": results,
        }

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------

    async def exec_command(
        self, session_id: str, command: str, timeout: float = 30.0
    ) -> dict[str, Any]:
        """在指定会话中执行命令（非交互式，适合单次命令）。

        Args:
            session_id: SSH 会话 ID。
            command: 要执行的命令。
            timeout: 超时秒数。
        """
        session = self._sessions.get(session_id)
        if session is None or session.conn is None:
            return {"status": "error", "message": f"会话不存在或未连接: {session_id}"}

        session.touch()
        try:
            result = await asyncio.wait_for(
                session.conn.run(command, encoding="utf-8", term_type="xterm-256color"),
                timeout=timeout,
            )
            return {
                "status": "success",
                "session_id": session_id,
                "command": command,
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
                "exit_code": result.exit_status,
            }
        except asyncio.TimeoutError:
            return {"status": "error", "message": f"命令超时 ({timeout}s): {command}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # 交互式终端
    # ------------------------------------------------------------------

    async def terminal_write(
        self, session_id: str, data: str
    ) -> dict[str, Any]:
        """向交互式 shell 写入数据。

        Args:
            session_id: SSH 会话 ID。
            data: 要写入的数据（命令 + 换行符）。
        """
        session = self._sessions.get(session_id)
        if session is None or session.shell is None:
            return {"status": "error", "message": f"会话不存在或 shell 未打开: {session_id}"}

        session.touch()
        try:
            session.shell.stdin.write(data)
            logger.info("[%s] 写入: %r", session_id, data.strip())
            return {"status": "success", "session_id": session_id, "written": data}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def terminal_read(
        self, session_id: str, size: int = 4096, timeout: float = 2.0
    ) -> dict[str, Any]:
        """从交互式 shell 读取输出。

        Args:
            session_id: SSH 会话 ID。
            size: 读取的最大字节数。
            timeout: 等待输出的超时秒数。
        """
        session = self._sessions.get(session_id)
        if session is None or session.shell is None:
            return {"status": "error", "message": f"会话不存在或 shell 未打开: {session_id}"}

        session.touch()
        try:
            data = await asyncio.wait_for(
                session.shell.stdout.read(size),
                timeout=timeout,
            )
            text = data.decode("utf-8", errors="replace") if data else ""
            session.output_buffer.append(text)
            # 只保留最近 100 条输出
            if len(session.output_buffer) > 100:
                session.output_buffer = session.output_buffer[-100:]
            return {"status": "success", "session_id": session_id, "output": text}
        except asyncio.TimeoutError:
            return {"status": "success", "session_id": session_id, "output": ""}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # 文件传输
    # ------------------------------------------------------------------

    async def upload_file(
        self, session_id: str, local_path: str, remote_path: str
    ) -> dict[str, Any]:
        """上传文件到远程服务器（使用 SFTP）。

        Args:
            session_id: SSH 会话 ID。
            local_path: 本地文件路径。
            remote_path: 远程目标路径。
        """
        session = self._sessions.get(session_id)
        if session is None or session.conn is None:
            return {"status": "error", "message": f"会话不存在或未连接: {session_id}"}

        session.touch()
        try:
            async with session.conn.start_sftp_client() as sftp:
                await sftp.put(local_path, remote_path)
            logger.info("[%s] 上传: %s → %s", session_id, local_path, remote_path)
            return {
                "status": "success",
                "session_id": session_id,
                "local": local_path,
                "remote": remote_path,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def download_file(
        self, session_id: str, remote_path: str, local_path: str
    ) -> dict[str, Any]:
        """从远程服务器下载文件（使用 SFTP）。

        Args:
            session_id: SSH 会话 ID。
            remote_path: 远程文件路径。
            local_path: 本地目标路径。
        """
        session = self._sessions.get(session_id)
        if session is None or session.conn is None:
            return {"status": "error", "message": f"会话不存在或未连接: {session_id}"}

        session.touch()
        try:
            async with session.conn.start_sftp_client() as sftp:
                await sftp.get(remote_path, local_path)
            logger.info("[%s] 下载: %s → %s", session_id, remote_path, local_path)
            return {
                "status": "success",
                "session_id": session_id,
                "remote": remote_path,
                "local": local_path,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_sessions(self) -> dict[str, Any]:
        """列出所有活跃 SSH 会话。"""
        sessions = {}
        for sid, s in self._sessions.items():
            sessions[sid] = {
                "host": s.host,
                "port": s.port,
                "user": s.user,
                "created_at": s.created_at,
                "last_used": s.last_used,
                "connected": s.conn is not None and not s.conn.is_closed(),
            }
        return {"status": "success", "sessions": sessions, "count": len(sessions)}
