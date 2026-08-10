"""mcpterminal 主入口。

默认启动 GUI。--mcp 以 MCP stdio 模式运行。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def run_gui():
    """启动 PySide6 GUI。"""
    from app.ipc import GuiInstanceLock, call_gui, gui_is_running

    # 锁覆盖 GUI 尚未写出 IPC 状态文件的启动窗口，消除并发启动竞态。
    instance_lock = GuiInstanceLock()
    if not instance_lock.acquire():
        if instance_lock.wait_for_existing():
            call_gui("activate", timeout=1.0)
        return
    if gui_is_running():
        call_gui("activate", timeout=1.0)
        instance_lock.release()
        return

    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    from app.ui.theme import ThemeManager

    app = QApplication(sys.argv)
    app.setApplicationName("mcpterminal")
    # 全局现代化主题：跟随系统亮暗自动切换
    app._theme_manager = ThemeManager(app)
    app._theme_manager.apply()
    window = MainWindow()
    window.show()
    try:
        exit_code = app.exec()
    finally:
        instance_lock.release()
    sys.exit(exit_code)


def run_mcp():
    """以 MCP stdio 模式运行。"""
    try:
        from app.tools.definitions import mcp
    except ModuleNotFoundError as exc:
        sys.stderr.write(
            f"mcpterminal 缺少依赖 {exc.name!r}。请先运行 Install.cmd 或 setup.ps1。\n"
        )
        raise SystemExit(2) from exc
    mcp.run(transport="stdio")


if __name__ == "__main__":
    if "--mcp" in sys.argv:
        run_mcp()
    else:
        run_gui()
