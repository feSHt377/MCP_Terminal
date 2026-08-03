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
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import asyncssh

logger = logging.getLogger("mcpterminal.ssh")

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
_SHELL_PROMPT_RE = re.compile(
    r"(?:^|[\r\n])(?:[^\r\n]{1,240}[#$]|[^\r\n]{0,220}(?:>>>|\.\.\.|[A-Za-z][\w.-]*>))\s*$"
)


def looks_like_shell_prompt(text: str) -> bool:
    """识别 PTY 输出末尾的普通 Bash/Zsh 风格提示符。"""
    visible = _ANSI_OSC_RE.sub("", _ANSI_CSI_RE.sub("", text))
    return bool(_SHELL_PROMPT_RE.search(visible))


def _strip_trailing_prompt(text: str) -> str:
    """去掉文本末尾的 Shell 提示符，保留其余内容。"""
    m = _SHELL_PROMPT_RE.search(text)
    if m:
        return text[: m.start()]
    return text


def _strip_command_echo(text: str, command: str) -> str:
    """去掉 PTY 回显的命令行（提示符 + 命令 + 换行），保留命令输出。

    某些客户端会多次回显同一条命令（如 docker 对 exit 的二次回显），
    这里循环剥离所有行首回显。
    """
    if not command:
        return text
    idx = text.find(command)
    while idx != -1:
        after = idx + len(command)
        nl = text.find("\n", after)
        new = text[nl + 1 :] if nl != -1 else text[after:]
        if new == text:
            break
        text = new
        m = re.match(r"[\r\n]*" + re.escape(command), text)
        if m is None:
            break
        idx = m.start()
    return text


@dataclass
class SSHSession:
    """单个 SSH 会话的状态。"""

    session_id: str
    host: str
    port: int = 22
    user: str = "root"
    conn: asyncssh.SSHClientConnection | None = None
    shell: asyncssh.SSHClientProcess | None = None
    active_process: asyncssh.SSHClientProcess | None = None
    interactive_ready: bool = False
    interactive_out: list[str] = field(default_factory=list)
    interactive_prompt_count: int = 0
    interactive_read_offset: int = 0
    remote_hostname: str = ""
    current_dir: str = "~"
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
                "remote_hostname": existing.remote_hostname or existing.host,
                "current_dir": existing.current_dir,
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

            # 获取真实远程提示符信息，GUI 不再用连接 IP 冒充主机名。
            remote_hostname = host
            current_dir = "~"
            try:
                identity = await conn.run(
                    "printf '%s\\n%s\\n%s\\n' \"$(hostname)\" \"$HOME\" \"$PWD\"",
                    encoding="utf-8",
                    check=False,
                )
                identity_lines = (identity.stdout or "").splitlines()
                if identity_lines and identity_lines[0].strip():
                    remote_hostname = identity_lines[0].strip()
                if len(identity_lines) > 2 and identity_lines[2].strip():
                    home = identity_lines[1].strip()
                    pwd = identity_lines[2].strip()
                    current_dir = "~" if home and pwd == home else pwd
            except Exception:
                logger.debug("无法读取远程提示符信息，使用连接参数", exc_info=True)

            session = SSHSession(
                session_id=session_id,
                host=host,
                port=port,
                user=user,
                conn=conn,
                shell=shell,
                remote_hostname=remote_hostname,
                current_dir=current_dir,
            )
            self._sessions[session_id] = session

            logger.info("SSH 连接成功: %s", session_id)
            return {
                "status": "success",
                "session_id": session_id,
                "message": f"已连接到 {session_id}",
                "remote_hostname": remote_hostname,
                "current_dir": current_dir,
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
            if session.active_process is not None:
                session.active_process.terminate()
                session.active_process = None
            session.interactive_ready = False
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

    async def exec_command_stream(
        self,
        session_id: str,
        command: str,
        timeout: float = 30.0,
        on_output: Callable[[str, bool], None] | None = None,
        interactive: bool | None = None,
        on_exit: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """在 PTY 中执行命令并增量推送输出。

        ``on_output(text, is_stderr)`` 在 SSH 事件循环线程中调用。调用方应通过
        Qt Signal 等线程安全机制把内容转交给 GUI。活动进程保存在会话中，使
        ``terminal_write`` 和人工终端键盘可以继续回答提示、发送 Ctrl+C 等输入。
        """
        session = self._sessions.get(session_id)
        if session is None or session.conn is None:
            return {"status": "error", "message": f"会话不存在或未连接: {session_id}"}
        if session.active_process is not None:
            if session.interactive_ready:
                # 交互式 Shell 已就绪：把命令注入其中执行，避免被队列卡死。
                return await self._exec_inside_interactive(
                    session, command, timeout, on_output
                )
            return {"status": "error", "message": f"会话已有运行中的命令: {session_id}"}

        session.touch()
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        process: asyncssh.SSHClientProcess | None = None
        output_ready = asyncio.Event()
        detached = False
        session.interactive_out = stdout_parts
        session.interactive_prompt_count = 0
        session.interactive_read_offset = 0

        async def _pump(stream, target: list[str], is_stderr: bool) -> None:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                text = chunk if isinstance(chunk, str) else chunk.decode("utf-8", errors="replace")
                target.append(text)
                prompt_hit = not is_stderr and looks_like_shell_prompt(
                    "".join(target[-4:])
                )
                if prompt_hit and session.active_process is process:
                    session.interactive_prompt_count += 1
                if interactive is True:
                    output_ready.set()
                elif interactive is None and prompt_hit:
                    output_ready.set()
                if on_output is not None:
                    on_output(text, is_stderr)

        try:
            process = await session.conn.create_process(
                command,
                encoding="utf-8",
                term_type="xterm-256color",
                term_size=(120, 36),
            )
            session.active_process = process

            async def _run() -> None:
                await asyncio.gather(
                    _pump(process.stdout, stdout_parts, False),
                    _pump(process.stderr, stderr_parts, True),
                )
                await process.wait_closed()

            def _completed_result() -> dict[str, Any]:
                return {
                    "status": "success",
                    "session_id": session_id,
                    "command": command,
                    "stdout": "".join(stdout_parts),
                    "stderr": "".join(stderr_parts),
                    "exit_code": process.exit_status,
                    "streamed": True,
                    "interactive": False,
                    "ready": False,
                }

            if interactive is not False:
                async def _monitor_interactive() -> dict[str, Any]:
                    try:
                        await _run()
                        result = _completed_result()
                    except Exception as exc:
                        result = {
                            "status": "error",
                            "session_id": session_id,
                            "command": command,
                            "message": str(exc),
                            "streamed": True,
                            "interactive": True,
                            "ready": False,
                        }
                    finally:
                        if session.active_process is process:
                            session.active_process = None
                            session.interactive_ready = False
                    if detached and on_exit is not None:
                        on_exit(result)
                    return result

                monitor = asyncio.create_task(_monitor_interactive())
                ready_wait = asyncio.create_task(output_ready.wait())
                done, _ = await asyncio.wait(
                    {monitor, ready_wait},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if monitor in done:
                    ready_wait.cancel()
                    return monitor.result()
                if ready_wait in done:
                    # 给快速失败留出一个很短的退出窗口，避免把错误首行当成就绪。
                    await asyncio.sleep(0.15)
                    if monitor.done():
                        return monitor.result()
                    detached = True
                    session.interactive_ready = True
                    return {
                        "status": "success",
                        "session_id": session_id,
                        "command": command,
                        "message": "交互式进程已就绪",
                        "stdout": "".join(stdout_parts),
                        "stderr": "".join(stderr_parts),
                        "exit_code": None,
                        "streamed": True,
                        "interactive": True,
                        "ready": True,
                    }
                monitor.cancel()
                ready_wait.cancel()
                process.terminate()
                return {
                    "status": "error",
                    "session_id": session_id,
                    "command": command,
                    "message": (
                        f"交互式进程在 {timeout:g} 秒内没有就绪"
                        if interactive is True
                        else f"命令超时 ({timeout:g}s): {command}"
                    ),
                    "streamed": True,
                    "interactive": True,
                    "ready": False,
                }

            await asyncio.wait_for(_run(), timeout=timeout)
            return _completed_result()
        except asyncio.TimeoutError:
            if process is not None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait_closed(), timeout=3.0)
                except (OSError, asyncio.TimeoutError):
                    process.kill()
            return {
                "status": "error",
                "session_id": session_id,
                "command": command,
                "message": f"命令超时 ({timeout}s): {command}",
                "stdout": "".join(stdout_parts),
                "stderr": "".join(stderr_parts),
                "streamed": True,
            }
        except Exception as e:
            return {
                "status": "error",
                "session_id": session_id,
                "command": command,
                "message": str(e),
                "stdout": "".join(stdout_parts),
                "stderr": "".join(stderr_parts),
                "streamed": True,
            }
        finally:
            if interactive is False and session.active_process is process:
                session.active_process = None

    # ------------------------------------------------------------------
    # 交互式终端
    # ------------------------------------------------------------------

    async def _exec_inside_interactive(
        self,
        session: SSHSession,
        command: str,
        timeout: float = 30.0,
        on_output: Callable[[str, bool], None] | None = None,
    ) -> dict[str, Any]:
        """把命令注入已就绪的交互式 Shell 执行，并等待其再次出现提示符。

        用于 ``lxc exec xxx bash`` / ``docker exec -it xxx bash`` 等命令返回
        ``interactive=True, ready=True`` 之后，Agent 继续用 ``ssh_exec`` 下发命令
        时自动路由到当前活动进程，避免命令被串行队列永久卡死。
        """
        proc = session.active_process
        if proc is None or not session.interactive_ready:
            return {
                "status": "error",
                "message": "会话没有已就绪的交互式进程",
                "interactive": False,
                "ready": False,
            }

        loop = asyncio.get_running_loop()
        base_len = sum(len(c) for c in session.interactive_out)
        base_count = session.interactive_prompt_count
        cmd = command.rstrip("\n")

        try:
            proc.stdin.write(cmd + "\n")
            await proc.stdin.drain()
        except Exception as exc:
            return {
                "status": "error",
                "message": f"向交互式进程写入失败: {exc}",
                "interactive": True,
                "ready": False,
            }

        deadline = loop.time() + timeout
        while True:
            if session.active_process is not proc:
                break
            if session.interactive_prompt_count > base_count:
                break
            if loop.time() >= deadline:
                break
            await asyncio.sleep(0.05)

        raw = "".join(session.interactive_out)[base_len:]
        visible = _ANSI_OSC_RE.sub("", raw)
        visible = _ANSI_CSI_RE.sub("", visible)
        stdout = _strip_command_echo(_strip_trailing_prompt(visible), cmd).strip()

        if session.active_process is not proc:
            return {
                "status": "success",
                "message": "交互式 Shell 已退出",
                "stdout": stdout,
                "stderr": "",
                "exit_code": proc.exit_status if proc.exit_status is not None else 0,
                "streamed": True,
                "interactive": False,
                "ready": False,
            }
        if session.interactive_prompt_count <= base_count:
            return {
                "status": "error",
                "message": f"交互式命令超时 ({timeout:g}s): {command}",
                "stdout": stdout,
                "stderr": "",
                "exit_code": None,
                "streamed": True,
                "interactive": True,
                "ready": True,
            }
        return {
            "status": "success",
            "session_id": session.session_id,
            "command": command,
            "stdout": stdout,
            "stderr": "",
            "exit_code": None,
            "streamed": True,
            "interactive": True,
            "ready": True,
            "message": "已在交互式 Shell 中执行",
        }

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
            target = session.active_process or session.shell
            target.stdin.write(data)
            logger.info("[%s] 写入: %r", session_id, data.strip())
            return {
                "status": "success",
                "session_id": session_id,
                "written": data,
                "target": "active_process" if session.active_process else "shell",
            }
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
        if session.active_process is not None and session.interactive_ready:
            # 交互式进程中，输出由持续 pump 累积，从这里按偏移读取。
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while True:
                if len("".join(session.interactive_out)) > session.interactive_read_offset:
                    break
                if loop.time() >= deadline:
                    break
                await asyncio.sleep(0.05)
            full = "".join(session.interactive_out)
            text = full[session.interactive_read_offset :]
            session.interactive_read_offset = len(full)
            session.output_buffer.append(text)
            if len(session.output_buffer) > 100:
                session.output_buffer = session.output_buffer[-100:]
            return {"status": "success", "session_id": session_id, "output": text}

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
                "remote_hostname": s.remote_hostname or s.host,
                "current_dir": s.current_dir,
            }
        return {"status": "success", "sessions": sessions, "count": len(sessions)}
