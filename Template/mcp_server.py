"""aitools 的 FastMCP 启动入口。"""

from tools import mcp


if __name__ == "__main__":
    mcp.run(transport="stdio")
