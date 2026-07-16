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
    print("  ✅ SSHSession 数据类")

    print("  ✅ Test 2 通过")


# =====================================================================
# Test 3: SSH 管理器 — 异步方法（无真实连接）
# =====================================================================

async def _test_ssh_manager_async_inner():
    """异步测试（不需要真实 SSH 服务器）。"""
    from app.ssh.manager import SSHManager

    m = SSHManager()

    # exec_command 不存在会话
    result = await m.exec_command("no@host:22", "ls")
    assert result["status"] == "error"
    print("  ✅ exec_command() 不存在会话 → 错误提示")

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

    from app.tools.definitions import mcp
    from mcp.server.fastmcp import FastMCP

    assert isinstance(mcp, FastMCP), "mcp 应为 FastMCP 实例"
    assert mcp.name == "mcpterminal", "Server 名称应为 mcpterminal"
    print(f"  ✅ FastMCP 实例: {mcp.name}")

    # 列出已注册工具
    tool_manager = mcp._tool_manager
    tools = tool_manager._tools
    expected = {
        "ssh_connect",
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
    }
    registered = set(tools.keys())
    missing = expected - registered
    extra = registered - expected
    assert not missing, f"缺少工具: {missing}"
    assert not extra, f"多余工具: {extra}"
    print(f"  ✅ 已注册 {len(registered)} 个工具:")
    for name in sorted(registered):
        print(f"     - {name}")

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
    )

    # list_servers
    r = list_servers()
    assert r["status"] == "success"
    assert "servers" in r
    print(f"  ✅ list_servers() → {r['count']} 台")

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
    from app.tools.definitions import (
        ssh_disconnect,
        ssh_exec,
        terminal_write,
        terminal_read,
        upload_file,
        download_file,
    )

    # ssh_exec 不存在会话
    r = await ssh_exec("no@x:22", "ls")
    assert r["status"] == "error"
    print("  ✅ ssh_exec() 不存在会话 → 错误提示")

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

    import logging

    from app.tools.definitions import _log_call, tool_logger

    log_dir = "logs"
    history_file = os.path.join(log_dir, "tool_call_history.json")
    log_file = os.path.join(log_dir, "tool_calls.log")

    # 释放日志文件句柄
    for handler in tool_logger.handlers[:]:
        handler.close()
        tool_logger.removeHandler(handler)

    # 清理旧日志
    for f in [history_file, log_file]:
        if os.path.exists(f):
            os.remove(f)

    # 重新初始化日志（写入测试记录）
    from app.tools.definitions import _setup_logger as _reinit_logger
    # 直接写入历史，绕过 logger（因为 logger 已被重置）
    _log_call("test_tool", {"arg1": "val1"}, {"status": "success"})
    _log_call("test_tool", {"arg1": "val2"}, {"status": "error"})

    # 验证历史文件
    assert os.path.exists(history_file), "应创建 tool_call_history.json"
    with open(history_file, "r", encoding="utf-8") as f:
        history = json.load(f)
    assert len(history) == 2
    assert history[0]["tool"] == "test_tool"
    print(f"  ✅ 调用历史: {len(history)} 条记录")

    # 重新初始化 logger 以便后续使用
    _reinit_logger()

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
