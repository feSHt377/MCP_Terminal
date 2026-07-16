"""mcpterminal 工具集 — MCP 工具定义。

使用 FastMCP 的 @mcp.tool() 装饰器注册工具，
函数签名 + docstring 即工具的 Schema，无需额外维护。
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.config.manager import add_server as _add_server, get_servers, get_security_config, remove_server as _remove_server
from app.ssh.manager import SSHManager

# ------------------------------------------------------------------
# MCP 实例
# ------------------------------------------------------------------

mcp = FastMCP("mcpterminal")

# ------------------------------------------------------------------
# 日志
# ------------------------------------------------------------------

LOG_DIR = "logs"
HISTORY_FILE = os.path.join(LOG_DIR, "tool_call_history.json")


def _setup_logger() -> logging.Logger:
    """配置文件日志，只写文件不输出到控制台。"""
    logger = logging.getLogger("mcpterminal.tools")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    os.makedirs(LOG_DIR, exist_ok=True)
    fh = logging.FileHandler(
        os.path.join(LOG_DIR, "tool_calls.log"),
        mode="a",
        encoding="utf-8",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)
    logger.propagate = False
    return logger


tool_logger = _setup_logger()


def _log_call(tool_name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    """记录工具调用到历史文件。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(),
        "tool": tool_name,
        "arguments": args,
        "result_status": result.get("status"),
    }
    history: list[dict[str, Any]] = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    history.append(record)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    tool_logger.info("%s(%s) → %s", tool_name, json.dumps(args, ensure_ascii=False), result.get("status"))


# ------------------------------------------------------------------
# 工具: SSH 连接
# ------------------------------------------------------------------

@mcp.tool()
async def ssh_connect(
    host: str,
    user: str = "root",
    port: int = 22,
    password: str | None = None,
    key_path: str | None = None,
) -> dict[str, Any]:
    """建立到远程服务器的 SSH 连接。

    连接建立后返回 session_id，后续所有操作都需要传入该 ID。

    Args:
        host: 服务器 IP 地址或主机名。
        user: SSH 登录用户名，默认 root。
        port: SSH 端口，默认 22。
        password: SSH 密码（与 key_path 二选一）。
        key_path: SSH 私钥路径（与 password 二选一）。
    """
    manager = SSHManager()
    result = await manager.connect(
        host=host, user=user, port=port,
        password=password, key_path=key_path,
    )
    _log_call("ssh_connect", {"host": host, "user": user, "port": port}, result)
    return result


@mcp.tool()
async def ssh_disconnect(session_id: str) -> dict[str, Any]:
    """断开指定的 SSH 会话。

    Args:
        session_id: 要断开的会话 ID（格式: user@host:port）。
    """
    manager = SSHManager()
    result = await manager.disconnect(session_id)
    _log_call("ssh_disconnect", {"session_id": session_id}, result)
    return result


# ------------------------------------------------------------------
# 工具: 命令执行
# ------------------------------------------------------------------

@mcp.tool()
async def ssh_exec(
    session_id: str,
    command: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """在远程服务器上执行一条命令（非交互式），返回 stdout/stderr 和退出码。

    适合执行一次性命令，如 nvidia-smi、docker ps、ls 等。
    如需交互式终端，请使用 terminal_write / terminal_read。

    Args:
        session_id: SSH 会话 ID。
        command: 要执行的 shell 命令。
        timeout: 命令超时秒数，默认 30。
    """
    manager = SSHManager()
    result = await manager.exec_command(session_id, command, timeout=timeout)
    _log_call("ssh_exec", {"session_id": session_id, "command": command}, result)
    return result


# ------------------------------------------------------------------
# 工具: 交互式终端
# ------------------------------------------------------------------

@mcp.tool()
async def terminal_write(session_id: str, data: str) -> dict[str, Any]:
    """向交互式 SSH shell 写入数据。

    通常需要以 \\n 结尾来执行命令。配合 terminal_read 使用可实现交互式操作。

    Args:
        session_id: SSH 会话 ID。
        data: 要写入的文本（如果是命令，末尾需加 \\n）。
    """
    manager = SSHManager()
    result = await manager.terminal_write(session_id, data)
    _log_call("terminal_write", {"session_id": session_id}, result)
    return result


@mcp.tool()
async def terminal_read(
    session_id: str,
    size: int = 4096,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """从交互式 SSH shell 读取输出。

    Args:
        session_id: SSH 会话 ID。
        size: 最大读取字节数，默认 4096。
        timeout: 等待输出的超时秒数，默认 2。
    """
    manager = SSHManager()
    result = await manager.terminal_read(session_id, size=size, timeout=timeout)
    _log_call("terminal_read", {"session_id": session_id}, result)
    return result


# ------------------------------------------------------------------
# 工具: 文件传输
# ------------------------------------------------------------------

@mcp.tool()
async def upload_file(
    session_id: str,
    local_path: str,
    remote_path: str,
) -> dict[str, Any]:
    """上传本地文件到远程服务器（SFTP）。

    Args:
        session_id: SSH 会话 ID。
        local_path: 本地文件的完整路径。
        remote_path: 远程目标路径。
    """
    manager = SSHManager()
    result = await manager.upload_file(session_id, local_path, remote_path)
    _log_call("upload_file", {"session_id": session_id, "local": local_path, "remote": remote_path}, result)
    return result


@mcp.tool()
async def download_file(
    session_id: str,
    remote_path: str,
    local_path: str,
) -> dict[str, Any]:
    """从远程服务器下载文件到本地（SFTP）。

    Args:
        session_id: SSH 会话 ID。
        remote_path: 远程文件的完整路径。
        local_path: 本地目标路径。
    """
    manager = SSHManager()
    result = await manager.download_file(session_id, remote_path, local_path)
    _log_call("download_file", {"session_id": session_id, "remote": remote_path, "local": local_path}, result)
    return result


# ------------------------------------------------------------------
# 工具: 服务器管理
# ------------------------------------------------------------------

@mcp.tool()
def list_servers() -> dict[str, Any]:
    """列出配置文件中定义的所有服务器。"""
    servers = get_servers()
    # 隐藏敏感信息
    safe = {}
    for name, info in servers.items():
        safe[name] = {
            "host": info.get("host"),
            "port": info.get("port", 22),
            "user": info.get("user", "root"),
        }
    _log_call("list_servers", {}, {"status": "success"})
    return {"status": "success", "servers": safe, "count": len(safe)}


@mcp.tool()
def list_sessions() -> dict[str, Any]:
    """列出所有活跃的 SSH 会话及其状态。"""
    manager = SSHManager()
    result = manager.list_sessions()
    _log_call("list_sessions", {}, result)
    return result


@mcp.tool()
def get_dangerous_commands() -> dict[str, Any]:
    """获取已配置的危险命令列表和安全策略。"""
    security = get_security_config()
    _log_call("get_dangerous_commands", {}, {"status": "success"})
    return {
        "status": "success",
        "dangerous_commands": security.get("dangerous_commands", []),
        "risk_levels": security.get("risk_levels", {}),
    }


@mcp.tool()
def add_server(
    name: str,
    host: str,
    user: str = "root",
    port: int = 22,
    key_path: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """添加一台 SSH 服务器到配置文件，供后续 ssh_connect 使用。

    Args:
        name: 服务器别名，如 "4090" 或 "v100"。
        host: IP 地址或主机名。
        user: SSH 登录用户名，默认 root。
        port: SSH 端口，默认 22。
        key_path: SSH 私钥路径（可选，如 ~/.ssh/id_rsa）。
        password: SSH 密码（可选，不推荐明文存储）。
    """
    result = _add_server(
        name=name, host=host, user=user, port=port,
        key_path=key_path, password=password,
    )
    _log_call("add_server", {"name": name, "host": host, "port": port}, result)
    return result


@mcp.tool()
def remove_server(name: str) -> dict[str, Any]:
    """从配置文件中移除一台 SSH 服务器。

    Args:
        name: 要移除的服务器别名。
    """
    result = _remove_server(name)
    _log_call("remove_server", {"name": name}, result)
    return result
