"""mcpterminal 主入口。

当前阶段：以 MCP Server (stdio) 模式运行。
后续 Phase 1 将添加 PySide6 GUI。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.tools.definitions import mcp


if __name__ == "__main__":
    print("mcpterminal MCP Server 启动中...")
    print("传输模式: stdio")
    print("可用工具: ssh_connect, ssh_exec, terminal_write, terminal_read, "
          "upload_file, download_file, ssh_disconnect, list_servers, "
          "list_sessions, get_dangerous_commands")
    mcp.run(transport="stdio")
