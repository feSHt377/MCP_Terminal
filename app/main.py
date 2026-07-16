"""mcpterminal 主入口。

默认启动 GUI 模式。使用 --mcp 参数以 MCP Server (stdio) 模式运行。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def run_gui():
    """启动 PySide6 GUI。"""
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("mcpterminal")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def run_mcp():
    """以 MCP stdio 模式运行。"""
    from app.tools.definitions import mcp

    print("mcpterminal MCP Server 启动中...")
    print("传输模式: stdio")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    if "--mcp" in sys.argv:
        run_mcp()
    else:
        run_gui()
