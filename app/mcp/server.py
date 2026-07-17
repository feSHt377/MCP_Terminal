"""mcpterminal MCP Server 启动入口（stdio）。"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.tools.definitions import mcp  # noqa: E402

if __name__ == "__main__":
    mcp.run(transport="stdio")
