"""Qt 冒烟测试：真正实例化 TerminalWidget，捕获"连接了不存在的方法"这类
单元测试覆盖不到的破坏（本次事故根因：__init__ 里 connect 了一个被误删的方法）。

用法: python tests_qt_smoke.py   （offscreen 平台，无需显示器）
"""

import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"E:\Docs\MCP_Terminal")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.terminal_widget import TerminalWidget  # noqa: E402

failures = []

app = QApplication.instance() or QApplication(sys.argv)

# 1) TerminalWidget 能否实例化（__init__ 会 connect 若干槽，缺一个就炸）
try:
    tw = TerminalWidget()
    print("✅ TerminalWidget() 实例化成功")
except Exception:
    failures.append("TerminalWidget() 实例化失败")
    traceback.print_exc()
    tw = None

# 2) __init__ 连接的所有槽必须真实存在
if tw is not None:
    required = [
        "_on_stream_received",
        "_on_interactive_finished",
        "_on_surface_command",
        "_send_raw_input",
        "_browse_history",
        "_on_send",
        "_execute",
        "_start_execute",
        "_on_result",
        "_run_next",
        "_cancel_pending",
        "_cancel_pending",
        "cancel_command",
        "_flush_stream_buffer",
        "_restore_normal_input",
    ]
    for name in dict.fromkeys(required):
        if not callable(getattr(tw, name, None)):
            failures.append(f"TerminalWidget 缺少方法: {name}")
            print(f"❌ 缺少方法: {name}")
        else:
            print(f"✅ TerminalWidget.{name} 存在")

# 3) 关键行为：未连接时会话下执行命令必须返回结构化错误而不是抛异常
if tw is not None:
    try:
        r = tw.execute_command("echo hi", timeout=5.0)
        assert isinstance(r, dict) and r.get("status") == "error", r
        print(f"✅ 未连接时 execute_command 返回结构化错误: {r.get('message')}")
    except Exception:
        failures.append("execute_command 在未连接会话时抛异常")
        traceback.print_exc()

# 4) cancel_command 在无任务时必须是安全 no-op，且接受 session_id 参数
if tw is not None:
    try:
        r = tw.cancel_command(session_id="nobody@nowhere:22")
        assert isinstance(r, dict) and r.get("status") == "success", r
        print(f"✅ cancel_command(session_id=...) 安全返回: {r.get('message')}")
    except Exception:
        failures.append("cancel_command 抛异常")
        traceback.print_exc()

# 5) MainWindow 的 IPC 相关方法必须存在且签名匹配（不实例化窗口，避免启动 bridge/IPC）
import inspect  # noqa: E402

from app.ui.main_window import MainWindow  # noqa: E402

for name, expected in [
    ("_on_ipc_request", ["self", "request"]),
    ("_finish_ipc_connect", ["self", "request", "result", "user", "host"]),
    ("_on_connected", ["self", "result", "user", "host", "switch"]),
    ("_on_connected_cli", ["self", "result", "user", "host"]),
    ("_finish_ipc_disconnect", ["self", "request", "result", "sid"]),
]:
    fn = getattr(MainWindow, name, None)
    if fn is None:
        failures.append(f"MainWindow 缺少方法: {name}")
        print(f"❌ MainWindow 缺少方法: {name}")
        continue
    params = list(inspect.signature(fn).parameters)
    if params != expected:
        failures.append(f"MainWindow.{name} 签名不符: {params} != {expected}")
        print(f"❌ {name} 签名 {params}，期望 {expected}")
    else:
        print(f"✅ MainWindow.{name}{tuple(params)}")

# 6) 模块级契约：bridge 必须提供三种提交方式
from app.ssh.bridge import SSHBridge  # noqa: E402

for name in ("submit", "submit_async", "submit_parallel", "submit_realtime", "is_ready"):
    if not callable(getattr(SSHBridge, name, None)):
        failures.append(f"SSHBridge 缺少方法: {name}")
        print(f"❌ SSHBridge 缺少方法: {name}")
    else:
        print(f"✅ SSHBridge.{name} 存在")

# 7) manager 必须提供 interrupt_process
from app.ssh.manager import SSHManager  # noqa: E402

if not callable(getattr(SSHManager, "interrupt_process", None)):
    failures.append("SSHManager 缺少 interrupt_process")
    print("❌ SSHManager 缺少 interrupt_process")
else:
    print("✅ SSHManager.interrupt_process 存在")

print()
if failures:
    print(f"结果: {len(failures)} 项失败")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("结果: 全部通过 ✅")
