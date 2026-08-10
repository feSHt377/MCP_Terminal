"""mcpterminal 核心模块测试脚本。

覆盖:
- 配置加载
- SSH 管理器（同步 + 异步）
- MCP 工具注册与调用
- FastMCP stdio 启动
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


# =====================================================================
# Test 1: 配置模块
# =====================================================================

def test_config():
    """测试配置加载。"""
    print("\n" + "=" * 60)
    print("Test 1: 配置模块")
    print("=" * 60)

    from app.config.manager import (
        load_config,
        get_servers,
        get_mcp_config,
        get_security_config,
        get_logging_config,
    )

    cfg = load_config()
    assert isinstance(cfg, dict), "load_config 应返回 dict"
    assert cfg["app"]["name"] == "mcpterminal", "app.name 应为 mcpterminal"
    print("  ✅ load_config()")

    servers = get_servers()
    assert isinstance(servers, dict), "get_servers 应返回 dict"
    print(f"  ✅ get_servers() → {len(servers)} 台服务器")

    mcp_cfg = get_mcp_config()
    assert "port" in mcp_cfg, "MCP 配置应包含 port"
    print(f"  ✅ get_mcp_config() → port={mcp_cfg['port']}")

    sec = get_security_config()
    assert "dangerous_commands" in sec, "安全配置应包含 dangerous_commands"
    print(f"  ✅ get_security_config() → {len(sec.get('risk_levels', {}))} 个风险等级")

    log_cfg = get_logging_config()
    assert "path" in log_cfg, "日志配置应包含 path"
    print(f"  ✅ get_logging_config() → level={log_cfg.get('level')}")

    print("  ✅ Test 1 通过")


# =====================================================================
# Test 2: SSH 管理器 — 同步方法
# =====================================================================

def test_ssh_manager_sync():
    """测试 SSH 管理器同步方法（不依赖真实 SSH）。"""
    print("\n" + "=" * 60)
    print("Test 2: SSH 管理器（同步）")
    print("=" * 60)

    from app.ssh.manager import SSHManager, SSHSession

    # 单例
    m1 = SSHManager()
    m2 = SSHManager()
    assert m1 is m2, "SSHManager 应为单例"
    print("  ✅ 单例模式")

    # list_sessions 空状态
    result = m1.list_sessions()
    assert result["status"] == "success"
    assert result["count"] == 0
    print("  ✅ list_sessions() 空状态")

    # 手动注入一个 session 测试 disconnect 不存在的情况
    result = asyncio.run(
        m1.disconnect("nonexistent@host:22")
    )
    assert result["status"] == "error"
    assert "不存在" in result["message"]
    print("  ✅ disconnect() 不存在会话 → 错误提示")

    # disconnect_all 空状态
    result = asyncio.run(m1.disconnect_all())
    assert result["status"] == "success"
    print("  ✅ disconnect_all() 空状态")

    # SSHSession 数据类
    sess = SSHSession(session_id="test@1.2.3.4:22", host="1.2.3.4")
    assert sess.session_id == "test@1.2.3.4:22"
    assert sess.port == 22
    assert sess.conn is None
    assert sess.current_dir == "~"
    assert sess.remote_hostname == ""
    print("  ✅ SSHSession 数据类")

    # 实时输入必须绕过正在等待的长命令，但不能改变普通命令的串行队列。
    from PySide6.QtCore import QCoreApplication
    from app.ssh.bridge import SSHBridge

    app = QCoreApplication.instance() or QCoreApplication([])
    bridge = SSHBridge()
    bridge.start()
    completed = []

    async def _slow():
        await asyncio.sleep(0.2)
        return {"status": "success", "name": "slow"}

    async def _realtime():
        await asyncio.sleep(0.01)
        return {"status": "success", "name": "realtime"}

    bridge.submit_async(_slow(), lambda result: completed.append(result["name"]))
    bridge.submit_realtime(_realtime(), lambda result: completed.append(result["name"]))
    deadline = time.monotonic() + 2.0
    while len(completed) < 2 and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    bridge.stop()
    assert completed == ["realtime", "slow"], completed
    print("  ✅ SSHBridge 实时输入绕过长命令等待")

    print("  ✅ Test 2 通过")


# =====================================================================
# Test 3: SSH 管理器 — 异步方法（无真实连接）
# =====================================================================

async def _test_ssh_manager_async_inner():
    """异步测试（不需要真实 SSH 服务器）。"""
    from app.ssh.manager import SSHManager, SSHSession

    m = SSHManager()

    # exec_command 不存在会话
    result = await m.exec_command("no@host:22", "ls")
    assert result["status"] == "error"
    print("  ✅ exec_command() 不存在会话 → 错误提示")

    # exec_command_stream 不存在会话
    result = await m.exec_command_stream("no@host:22", "ls")
    assert result["status"] == "error"
    print("  ✅ exec_command_stream() 不存在会话 → 错误提示")

    # terminal_write 不存在会话
    result = await m.terminal_write("no@host:22", "echo hi\n")
    assert result["status"] == "error"
    print("  ✅ terminal_write() 不存在会话 → 错误提示")

    # terminal_read 不存在会话
    result = await m.terminal_read("no@host:22")
    assert result["status"] == "error"
    print("  ✅ terminal_read() 不存在会话 → 错误提示")

    # upload_file 不存在会话
    result = await m.upload_file("no@host:22", "/tmp/a", "/tmp/b")
    assert result["status"] == "error"
    print("  ✅ upload_file() 不存在会话 → 错误提示")

    # download_file 不存在会话
    result = await m.download_file("no@host:22", "/tmp/a", "/tmp/b")
    assert result["status"] == "error"
    print("  ✅ download_file() 不存在会话 → 错误提示")

    from app.ui.terminal_widget import strip_terminal_control
    assert strip_terminal_control("\x1b[31mred\x1b[0m") == "red"
    print("  ✅ ANSI 终端控制码清理")

    from app.ssh.manager import looks_like_shell_prompt
    assert looks_like_shell_prompt("root@ft3:~# ")
    assert looks_like_shell_prompt("\x1b[32mfuzihan@workstation\x1b[0m:~$ ")
    assert looks_like_shell_prompt("Python 3.14\n>>> ")
    assert looks_like_shell_prompt("mysql> ")
    assert not looks_like_shell_prompt("Error: Instance not found\n")
    print("  ✅ auto 模式按 PTY 提示符识别，不依赖命令白名单")

    # 伪 PTY：提示符返回后工具应立即成功，后台进程继续接受输入直到退出。
    finished = asyncio.Event()
    exit_results = []

    class _Writer:
        def __init__(self):
            self.data = []
            self.awaiting_read = asyncio.Event()

        def write(self, data):
            self.data.append(data)
            self.awaiting_read.set()

        async def drain(self):
            return None

    class _PromptReader:
        def __init__(self, writer):
            self.first = True
            self.responded = False
            self.writer = writer

        async def read(self, _size):
            if self.first:
                self.first = False
                return "root@ft3:~# "
            if not self.responded:
                await self.writer.awaiting_read.wait()
                self.responded = True
                return "root@ft3:~# echo hi\r\nhi\r\nroot@ft3:~# "
            await finished.wait()
            return ""

    class _EmptyReader:
        async def read(self, _size):
            return ""

    class _Process:
        def __init__(self):
            self.stdin = _Writer()
            self.stdout = _PromptReader(self.stdin)
            self.stderr = _EmptyReader()
            self.exit_status = 0

        async def wait_closed(self):
            await finished.wait()

        def terminate(self):
            finished.set()

        def kill(self):
            finished.set()

    process = _Process()

    class _Connection:
        async def create_process(self, *_args, **_kwargs):
            return process

    fake_sid = "root@fake:22"
    m._sessions[fake_sid] = SSHSession(
        session_id=fake_sid,
        host="fake",
        conn=_Connection(),
        shell=process,
    )
    ready = await m.exec_command_stream(
        fake_sid,
        "lxc exec ft3 bash",
        timeout=1.0,
        interactive=True,
        on_exit=exit_results.append,
    )
    assert ready["status"] == "success" and ready["ready"] is True
    assert m._sessions[fake_sid].active_process is process

    # 交互式进程就绪后，后续 ssh_exec 命令自动注入其中执行，而不是被队列卡死。
    routed = await m.exec_command_stream(fake_sid, "echo hi", timeout=1.0)
    assert routed["status"] == "success"
    assert routed["interactive"] is True and routed["ready"] is True
    assert routed["stdout"] == "hi"
    assert process.stdin.data == ["echo hi\n"]
    print("  ✅ 交互式 Shell 就绪后，新命令自动注入执行（不再卡队列）")

    written = await m.terminal_write(fake_sid, "exit\n")
    assert written["target"] == "active_process"
    assert process.stdin.data == ["echo hi\n", "exit\n"]
    finished.set()
    for _ in range(20):
        if exit_results:
            break
        await asyncio.sleep(0.01)
    assert exit_results and exit_results[0]["exit_code"] == 0
    assert m._sessions[fake_sid].active_process is None
    m._sessions.pop(fake_sid)
    print("  ✅ 交互式 Shell 就绪后立即返回并保持可输入")

    # 提示符/回显清理辅助函数
    from app.ssh.manager import _strip_command_echo, _strip_trailing_prompt
    stripped = _strip_trailing_prompt("root@ft3:~# echo hi\r\nhi\r\nroot@ft3:~# ")
    assert not stripped.endswith("root@ft3:~# ")
    assert _strip_command_echo(stripped, "echo hi").strip("\r\n") == "hi"
    # docker 对 exit 等命令会二次回显
    assert _strip_command_echo("exit\r\n\rexit\r\n", "exit").strip() == ""
    print("  ✅ 提示符与回显清理")


def test_ssh_manager_async():
    """测试 SSH 管理器异步方法。"""
    print("\n" + "=" * 60)
    print("Test 3: SSH 管理器（异步 — 无真实连接）")
    print("=" * 60)

    asyncio.run(_test_ssh_manager_async_inner())

    print("  ✅ Test 3 通过")


# =====================================================================
# Test 4: MCP 工具注册
# =====================================================================

def test_mcp_tools_registration():
    """测试 FastMCP 工具注册。"""
    print("\n" + "=" * 60)
    print("Test 4: MCP 工具注册")
    print("=" * 60)

    import app.tools.definitions as definitions
    from app.tools.definitions import mcp
    from mcp.server.fastmcp import FastMCP

    assert isinstance(mcp, FastMCP), "mcp 应为 FastMCP 实例"
    assert mcp.name == "mcpterminal", "Server 名称应为 mcpterminal"
    print(f"  ✅ FastMCP 实例: {mcp.name}")

    # 列出已注册工具
    tool_manager = mcp._tool_manager
    tools = tool_manager._tools
    expected = {
        "launch_gui",
        "proxy_command",
        "autocomplete_command",
        "select_session",
        "switch_tab",
        "ssh_connect",
        "ssh_connect_from_config",
        "ssh_disconnect",
        "ssh_exec",
        "terminal_write",
        "terminal_read",
        "upload_file",
        "download_file",
        "list_servers",
        "list_sessions",
        "get_dangerous_commands",
        "add_server",
        "remove_server",
        "check_update",
        "apply_update",
    }
    registered = set(tools.keys())
    missing = expected - registered
    extra = registered - expected
    assert not missing, f"缺少工具: {missing}"
    assert not extra, f"多余工具: {extra}"
    print(f"  ✅ 已注册 {len(registered)} 个工具:")
    for name in sorted(registered):
        print(f"     - {name}")

    # 后续工具调用使用测试替身，不能污染或锁住正在运行程序的生产日志。
    definitions._test_original_log_call = definitions._log_call
    definitions._log_call = lambda *_args, **_kwargs: None

    print("  ✅ Test 4 通过")


# =====================================================================
# Test 5: MCP 工具调用（同步）
# =====================================================================

def test_mcp_tools_sync_call():
    """测试同步 MCP 工具的直接调用。"""
    print("\n" + "=" * 60)
    print("Test 5: MCP 工具调用（同步）")
    print("=" * 60)

    from app.tools.definitions import (
        list_servers,
        list_sessions,
        get_dangerous_commands,
        _resolve_server_credentials,
    )

    # list_servers
    r = list_servers()
    assert r["status"] == "success"
    assert "servers" in r
    print(f"  ✅ list_servers() → {r['count']} 台")

    # ssh_connect 凭据解析：config 中有该主机时自动取最近账号，否则提示索要
    c1 = _resolve_server_credentials("139.224.250.35", "root", 22, None, None)
    assert c1 is not None and c1["account"] == "Aliyun-Server" and c1["password"]
    c2 = _resolve_server_credentials("100.64.0.13", "root", 22, None, None)
    assert c2 is not None and c2["user"] == "fuzihan" and c2["password"]
    assert _resolve_server_credentials("1.2.3.4", "root", 22, None, None) is None
    c3 = _resolve_server_credentials("1.2.3.4", "root", 22, "pw", None)
    assert c3 is not None and c3["password"] == "pw" and c3["account"] is None
    print("  ✅ ssh_connect 凭据解析（自动取配置账号 / 缺失时提示索要）")

    # list_sessions
    r = list_sessions()
    assert r["status"] == "success"
    assert r["count"] == 0
    print(f"  ✅ list_sessions() → {r['count']} 个活跃会话")

    # get_dangerous_commands
    r = get_dangerous_commands()
    assert r["status"] == "success"
    assert len(r["dangerous_commands"]) > 0
    assert "rm" in r["dangerous_commands"]
    print(f"  ✅ get_dangerous_commands() → {len(r['dangerous_commands'])} 条危险命令")

    print("  ✅ Test 5 通过")


# =====================================================================
# Test 6: MCP 工具调用（异步 — 无真实连接）
# =====================================================================

async def _test_mcp_tools_async_inner():
    """异步工具调用测试。"""
    import app.tools.definitions as definitions
    from app.tools.definitions import (
        ssh_disconnect,
        ssh_exec,
        ssh_connect_from_config,
        terminal_write,
        terminal_read,
        upload_file,
        download_file,
    )

    # ssh_exec 不存在会话
    r = await ssh_exec("no@x:22", "ls")
    assert r["status"] == "error"
    print("  ✅ ssh_exec() 不存在会话 → 错误提示")

    # ssh_connect_from_config：配置中有该主机 → 用配置账号连接；没有 → 提示换 ssh_connect
    orig_call_gui = definitions._call_gui_async

    async def _fake_gui(method, params):
        assert method == "ssh_connect"
        return {"status": "success", "session_id": "root@fake:22", "message": "ok"}

    definitions._call_gui_async = _fake_gui
    try:
        r = await ssh_connect_from_config("139.224.250.35")
        assert r["status"] == "success" and r.get("config_account") == "Aliyun-Server"
        r = await ssh_connect_from_config("1.2.3.4")
        assert r["status"] == "error" and r.get("reason") == "config_not_found"
    finally:
        definitions._call_gui_async = orig_call_gui
    print("  ✅ ssh_connect_from_config（用配置账号连接 / 无配置时提示）")

    # terminal_write
    r = await terminal_write("no@x:22", "test\n")
    assert r["status"] == "error"
    print("  ✅ terminal_write() 不存在会话 → 错误提示")

    # terminal_read
    r = await terminal_read("no@x:22")
    assert r["status"] == "error"
    print("  ✅ terminal_read() 不存在会话 → 错误提示")

    # upload
    r = await upload_file("no@x:22", "/a", "/b")
    assert r["status"] == "error"
    print("  ✅ upload_file() 不存在会话 → 错误提示")

    # download
    r = await download_file("no@x:22", "/a", "/b")
    assert r["status"] == "error"
    print("  ✅ download_file() 不存在会话 → 错误提示")

    # ssh_disconnect
    r = await ssh_disconnect("no@x:22")
    assert r["status"] == "error"
    print("  ✅ ssh_disconnect() 不存在会话 → 错误提示")


def test_mcp_tools_async_call():
    """测试异步 MCP 工具调用。"""
    print("\n" + "=" * 60)
    print("Test 6: MCP 工具调用（异步）")
    print("=" * 60)

    asyncio.run(_test_mcp_tools_async_inner())

    print("  ✅ Test 6 通过")


# =====================================================================
# Test 7: FastMCP stdio 启动（语法验证）
# =====================================================================

def test_mcp_server_entry():
    """验证 MCP Server 入口文件语法正确。"""
    print("\n" + "=" * 60)
    print("Test 7: MCP Server 入口")
    print("=" * 60)

    import ast

    for entry in ["app/mcp/server.py", "app/main.py"]:
        with open(entry, encoding="utf-8") as f:
            ast.parse(f.read())
        print(f"  ✅ {entry} 语法正确")

    print("  ✅ Test 7 通过")


# =====================================================================
# Test 8: 日志与调用历史
# =====================================================================

def test_logging():
    """测试日志和历史记录写入。"""
    print("\n" + "=" * 60)
    print("Test 8: 日志与历史记录")
    print("=" * 60)

    import tempfile
    import app.tools.definitions as definitions

    original_log_dir = definitions.LOG_DIR
    original_history_file = definitions.HISTORY_FILE
    with tempfile.TemporaryDirectory(prefix="mcpterminal-test-") as temp_dir:
        definitions.LOG_DIR = temp_dir
        definitions.HISTORY_FILE = os.path.join(temp_dir, "tool_call_history.json")
        definitions.tool_logger = definitions._setup_logger()
        try:
            real_log_call = definitions._test_original_log_call
            real_log_call("test_tool", {"arg1": "val1"}, {"status": "success"})
            real_log_call("test_tool", {"arg1": "val2"}, {"status": "error"})

            with open(definitions.HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            assert len(history) == 2
            assert history[0]["tool"] == "test_tool"
            print(f"  ✅ 调用历史: {len(history)} 条记录（隔离目录）")
        finally:
            for handler in definitions.tool_logger.handlers[:]:
                handler.close()
                definitions.tool_logger.removeHandler(handler)
            definitions.LOG_DIR = original_log_dir
            definitions.HISTORY_FILE = original_history_file

    print("  ✅ Test 8 通过")


# =====================================================================
# Main
# =====================================================================

def main():
    print("\n" + "█" * 60)
    print("█  mcpterminal 核心模块测试")
    print("█" * 60)

    all_ok = True
    tests = [
        ("配置模块", test_config),
        ("SSH 管理器（同步）", test_ssh_manager_sync),
        ("SSH 管理器（异步）", test_ssh_manager_async),
        ("MCP 工具注册", test_mcp_tools_registration),
        ("MCP 工具调用（同步）", test_mcp_tools_sync_call),
        ("MCP 工具调用（异步）", test_mcp_tools_async_call),
        ("MCP Server 入口", test_mcp_server_entry),
        ("日志与历史记录", test_logging),
    ]

    passed = 0
    failed = 0
    for name, func in tests:
        try:
            func()
            passed += 1
        except Exception as e:
            failed += 1
            all_ok = False
            print(f"\n  ❌ [{name}] 失败: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "█" * 60)
    print(f"█  结果: {passed}/{len(tests)} 通过, {failed} 失败")
    print("█" * 60)

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
