"""mcpterminal 工具集 — MCP 工具定义。

使用 FastMCP 的 @mcp.tool() 装饰器注册工具，
函数签名 + docstring 即工具的 Schema，无需额外维护。
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from app.config.manager import add_server as _add_server, get_servers, get_security_config, remove_server as _remove_server
from app.ipc import call_gui, gui_is_running
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
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
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
# GUI 启动辅助
# ------------------------------------------------------------------

@mcp.tool()
def launch_gui() -> dict[str, Any]:
    """启动或激活共享 SSH 会话的人工终端 GUI。

    GUI 是 SSH 会话的唯一所有者。后续 MCP SSH 工具通过本地 IPC 操作该会话，
    因而人类输入和 Agent 操作会出现在同一个终端中。
    """
    if gui_is_running():
        call_gui("activate", timeout=1.0)
        return {"status": "success", "message": "GUI 已在运行", "already_running": True}

    project_root = Path(__file__).resolve().parents[2]
    executable = Path(sys.executable)
    popen_kwargs: dict[str, Any] = {
        "cwd": project_root,
        # GUI 不得继承 MCP stdio，否则关闭 GUI/控制台可能连带断开 Agent。
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        command = [str(executable), "-m", "app.main"]
    else:
        popen_kwargs["start_new_session"] = True
        command = [str(executable), "-m", "app.main"]

    process = subprocess.Popen(
        command,
        **popen_kwargs,
    )
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return {"status": "error", "message": "GUI 启动失败", "exit_code": process.returncode}
        if gui_is_running():
            return {"status": "success", "pid": process.pid, "message": "GUI 已启动"}
        time.sleep(0.1)
    process.terminate()
    return {"status": "error", "pid": process.pid, "message": "GUI 启动超时"}


async def _call_gui_async(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """在线程中执行阻塞 IPC，避免阻塞 MCP 的 asyncio 循环。"""
    import asyncio

    return await asyncio.to_thread(call_gui, method, params)


# ------------------------------------------------------------------
# 工具: SSH 连接
# ------------------------------------------------------------------

def _resolve_server_credentials(
    host: str,
    user: str,
    port: int,
    password: str | None,
    key_path: str | None,
) -> dict[str, Any] | None:
    """从 config.yaml 按主机名解析登录凭据。

    显式提供了 password/key_path 时直接使用；否则查找配置中与该主机匹配的
    服务器，取最近添加（匹配列表最后一个）的账号填充凭据。
    未匹配到配置且无凭据时返回 None，由调用方提示模型向用户索要。
    """
    if password or key_path:
        return {
            "user": user,
            "port": port,
            "password": password,
            "key_path": key_path,
            "account": None,
        }

    servers = get_servers()
    matches = [
        (name, info)
        for name, info in servers.items()
        if isinstance(info, dict) and info.get("host") == host
    ]
    if not matches:
        return None

    name, info = matches[-1]
    return {
        "user": info.get("user") or user,
        "port": info.get("port") or port,
        "password": info.get("password"),
        "key_path": info.get("key_path"),
        "account": name,
    }


@mcp.tool()
async def ssh_connect(
    host: str,
    user: str = "root",
    port: int = 22,
    password: str | None = None,
    key_path: str | None = None,
) -> dict[str, Any]:
    """建立到远程服务器的 SSH 连接。password 和 key_path 都可以不传。

    用法（照做即可）：
      1. 先只传 host 尝试连接：
           ssh_connect(host="1.2.3.4")
      2. 若 config.yaml 已配置过该主机，工具会自动使用其中最近添加的账号
         （用户名、端口、密码/私钥全部自动填充）登录，无需你提供任何凭据。
      3. 若 config.yaml 没有该主机且你没传凭据，工具会返回
         {"status":"error","reason":"credentials_required","message":...}。
         此时你必须停下，向用户询问该服务器的登录凭据，二选一：
           - SSH 密码：  ssh_connect(host="1.2.3.4", password="<用户给的密码>")
           - 私钥路径：  ssh_connect(host="1.2.3.4", key_path="/home/user/.ssh/id_rsa")
      4. 不要把失败当成功，也不要在没有凭据时反复重试或猜密码。

    连接建立后返回 session_id，后续所有操作都需要传入该 ID。

    Args:
        host: 服务器 IP 地址或主机名。
        user: SSH 登录用户名，默认 root。通常由配置自动填充，无需传入。
        port: SSH 端口，默认 22。通常由配置自动填充，无需传入。
        password: SSH 密码，可选。与 key_path 二选一。
        key_path: SSH 私钥路径，可选。与 password 二选一。
    """
    creds = _resolve_server_credentials(host, user, port, password, key_path)
    if creds is None:
        message = (
            f"config.yaml 中没有 {host} 的服务器配置，且你未提供登录凭据，无法连接。"
            "请向用户询问该服务器的登录凭据并重新调用 ssh_connect，二选一：\n"
            f'  ssh_connect(host="{host}", password="<用户给的密码>")\n'
            f'  ssh_connect(host="{host}", key_path="/用户给的/私钥路径")'
        )
        _log_call(
            "ssh_connect",
            {"host": host, "user": user, "port": port},
            {"status": "error", "message": message},
        )
        return {
            "status": "error",
            "message": message,
            "reason": "credentials_required",
        }

    result = await _call_gui_async("ssh_connect", {
        "host": host,
        "user": creds["user"],
        "port": creds["port"],
        "password": creds["password"],
        "key_path": creds["key_path"],
    })
    if creds.get("account"):
        result = {**result, "config_account": creds["account"]}
    _log_call(
        "ssh_connect",
        {"host": host, "user": creds["user"], "port": creds["port"]},
        result,
    )
    return result


@mcp.tool()
async def ssh_connect_from_config(name: str) -> dict[str, Any]:
    """使用 config.yaml 中已有服务器配置的「别名」直接连接，无需任何凭据。

    本工具与 ssh_connect 的区别：本工具按 config.yaml 中 servers 下的**别名
    （键名）精确匹配**，直接使用该条配置的 host/user/port/password/key_path，
    不做任何 IP 猜测。同一 IP 下配置多个账号（如 root/fuzihan）时，用别名
    连接可以精确指定用哪个账号，避免 IP 冲突。

    用法（照做即可）：
        1. 先调用 list_servers 查看配置里的服务器别名，然后：
             ssh_connect_from_config(name="4090")
        2. 连接成功后返回 session_id 和 config_account（实际使用的配置别名）。
        3. 若返回 {"status":"error","reason":"config_not_found",...}，说明
           config.yaml 中没有该别名，请改用 ssh_connect 并向用户询问
           password 或 key_path。

    Args:
        name: config.yaml 中 servers 下的服务器别名（键名）。
    """
    from app.config.manager import get_servers

    servers = get_servers()
    info = servers.get(name)
    if not isinstance(info, dict) or not info.get("host"):
        message = (
            f"config.yaml 中没有名为 {name!r} 的服务器配置（可用 list_servers "
            "查看全部别名）。请改用 ssh_connect，并向用户询问 password 或 key_path。"
        )
        _log_call(
            "ssh_connect_from_config",
            {"name": name},
            {"status": "error", "message": message},
        )
        return {
            "status": "error",
            "message": message,
            "reason": "config_not_found",
        }

    host = str(info["host"])
    user = str(info.get("user") or "root")
    port = int(info.get("port") or 22)
    result = await _call_gui_async("ssh_connect", {
        "host": host,
        "user": user,
        "port": port,
        "password": info.get("password"),
        "key_path": info.get("key_path"),
    })
    if result.get("status") == "success":
        result = {**result, "config_account": name}
    _log_call(
        "ssh_connect_from_config",
        {"name": name, "host": host},
        result,
    )
    return result


@mcp.tool()
async def ssh_disconnect(session_id: str) -> dict[str, Any]:
    """断开指定的 SSH 会话。

    Args:
        session_id: 要断开的会话 ID（格式: user@host:port）。
    """
    result = await _call_gui_async("ssh_disconnect", {"session_id": session_id})
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
    execution_mode: Literal["auto", "command", "interactive"] = "auto",
) -> dict[str, Any]:
    """在 GUI 当前 SSH 会话执行一条命令，返回 stdout/stderr 和退出码。

    一次只提交一条命令，等待并分析本次结果后再决定下一步；不要并行提交多个
    探测命令，也不要在未读取错误信息前用猜测的参数反复重试。
    适合执行一次性命令，如 nvidia-smi、docker ps、ls 等；交互程序可将
    execution_mode 设为 interactive，进入后使用 terminal_write 继续输入。

    Args:
        session_id: SSH 会话 ID。
        command: 要执行的 shell 命令。
        timeout: 命令超时秒数，默认 30。
        execution_mode: auto 根据 PTY 运行状态判断；command 必须等待退出码；
            interactive 在进程产生首段输出且仍存活时返回 ready=true。
    """
    result = await _call_gui_async("ssh_exec", {
        "session_id": session_id,
        "command": command,
        "timeout": timeout,
        "execution_mode": execution_mode,
    })
    _log_call("ssh_exec", {"session_id": session_id, "command": command}, result)
    return result


@mcp.tool()
async def cancel_command(session_id: str) -> dict[str, Any]:
    """强制停止当前正在执行的命令，并清空 Agent 排队中的命令。

    当 ssh_exec/proxy_command 返回 {"status":"queued",...}、命令长时间不返回、
    或想放弃本轮后续命令时，调用本工具：向远程活动进程发送 Ctrl+C (\x03)
    中断，同时丢弃队列中尚未执行的命令（其调用方会收到 cancelled 结果）。
    停止后即可重新 ssh_exec 下发新命令。此操作只影响本会话，不会断开连接。

    Args:
        session_id: 要停止命令的 SSH 会话 ID（格式: user@host:port）。
    """
    result = await _call_gui_async("cancel", {"session_id": session_id})
    _log_call("cancel_command", {"session_id": session_id}, result)
    return result


# ------------------------------------------------------------------
# 工具: 交互式终端
# ------------------------------------------------------------------

@mcp.tool()
async def terminal_write(session_id: str, data: str) -> dict[str, Any]:
    """向交互式 SSH shell 写入数据。

    通常需要以 \\n 结尾来执行命令。配合 terminal_read 使用可实现交互式操作。
    当 proxy_command/ssh_exec 返回 interactive=true、ready=true 时，使用本工具继续
    向该活动进程输入；Shell 通常可用 exit\\n 退出并恢复普通命令模式。

    Args:
        session_id: SSH 会话 ID。
        data: 要写入的文本（如果是命令，末尾需加 \\n）。
    """
    result = await _call_gui_async("terminal_write", {"session_id": session_id, "data": data})
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
    result = await _call_gui_async("terminal_read", {
        "session_id": session_id, "size": size, "timeout": timeout,
    })
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
    result = await _call_gui_async("upload_file", {
        "session_id": session_id, "local_path": local_path, "remote_path": remote_path,
    })
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
    result = await _call_gui_async("download_file", {
        "session_id": session_id, "remote_path": remote_path, "local_path": local_path,
    })
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
    result = call_gui("list_sessions")
    if result.get("status") == "error" and "GUI 未运行" in result.get("message", ""):
        result = SSHManager().list_sessions()
    _log_call("list_sessions", {}, result)
    return result


@mcp.tool()
async def proxy_command(
    command: str,
    timeout: float = 30.0,
    execution_mode: Literal["auto", "command", "interactive"] = "auto",
) -> dict[str, Any]:
    """在 GUI 当前会话代理执行一条命令，并把过程显示在人工终端。

    必须等待本次结果并根据 stdout/stderr 决定下一步。不要并行调用本工具，也不要
    在尚未分析错误原因时连续尝试多个相似命令。并发到达的少量命令会被串行排队。
    execution_mode 可为 auto、command 或 interactive。对任意已知会长期等待输入的
    程序使用 interactive；返回 interactive=true、ready=true 且没有 exit_code 属于
    正常状态，后续输入应改用 terminal_write。auto 会依据 PTY 提示符和进程生命周期判断。
    """
    result = await _call_gui_async("proxy_command", {
        "command": command,
        "timeout": timeout,
        "execution_mode": execution_mode,
    })
    _log_call("proxy_command", {"command": command}, result)
    return result


@mcp.tool()
async def autocomplete_command(command: str) -> dict[str, Any]:
    """将命令补全到 GUI 输入框但不执行，交由用户检查、修改或回车确认。"""
    result = await _call_gui_async("autocomplete_command", {"command": command})
    _log_call("autocomplete_command", {"command": command}, result)
    return result


@mcp.tool()
async def select_session(session_id: str) -> dict[str, Any]:
    """将 GUI 当前终端切换到一个已连接的 SSH 会话，不关闭其他会话。"""
    result = await _call_gui_async("select_session", {"session_id": session_id})
    _log_call("select_session", {"session_id": session_id}, result)
    return result


@mcp.tool()
async def switch_tab(session_id: str) -> dict[str, Any]:
    """将 GUI 切换到指定会话的终端标签页，便于用户盯着正在执行命令的连接。

    Agent 在 ssh_exec/proxy_command 前后调用本工具，可以让 GUI 自动对准命令所在
    的标签页，用户在人工终端里就能看到命令输出。若 GUI「设置」中关闭了
    「接受 Agent 自动切换标签页」，本工具不会擅自切换，而是返回
    {"status":"success","switched":false}，仍视为成功。

    Args:
        session_id: 要切换到的 SSH 会话 ID（格式: user@host:port）。
    """
    result = await _call_gui_async("switch_tab", {"session_id": session_id})
    _log_call("switch_tab", {"session_id": session_id}, result)
    return result


@mcp.tool()
def check_update() -> dict[str, Any]:
    """检查 GitHub 仓库是否有新版本（只检测，不下载、不更新）。"""
    from app.updater import check_for_update

    result = check_for_update(timeout=8.0)
    _log_call("check_update", {}, result)
    return result


@mcp.tool()
async def apply_update() -> dict[str, Any]:
    """下载并应用 GitHub 上的最新版本。

    返回后 GUI 会自动重启以加载新版本。注意：GUI 重启会断开其持有的全部
    SSH 会话，旧 session_id 全部失效，需重新 ssh_connect。
    """
    result = await _call_gui_async("apply_update", {})
    _log_call("apply_update", {}, result)
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
