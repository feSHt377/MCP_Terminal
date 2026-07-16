"""mcpterminal MCP Server 启动入口。

以 stdio 传输模式启动 FastMCP Server，供 Codex CLI / Claude Code 等 AI Agent 连接。
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中，使 from app.tools.definitions import mcp 可用
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.tools.definitions import mcp  # noqa: E402


if __name__ == "__main__":
    mcp.run(transport="stdio")
