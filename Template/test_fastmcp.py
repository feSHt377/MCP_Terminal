"""FastMCP 注册、Schema 和本地工具执行的离线测试。"""

import unittest
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tools import execute_tool, get_tool_schema_list, mcp


class FastMCPToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_tools_are_exposed_by_mcp(self) -> None:
        tools = await mcp.list_tools()
        names = {tool.name for tool in tools}
        self.assertEqual(
            names,
            {
                "save_data_to_log",
                "query_logs",
                "get_test_statistics",
                "show_popup",
                "test_recall",
                "calculate",
                "get_local_time",
                "get_self_info",
            },
        )

    async def test_stdio_server_exposes_fastmcp_tools(self) -> None:
        project_dir = Path(__file__).parent.resolve()
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(project_dir / "mcp_server.py")],
            cwd=str(project_dir),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()

        names = {tool.name for tool in result.tools}
        self.assertIn("calculate", names)
        self.assertIn("save_data_to_log", names)

    def test_ollama_schema_is_generated_from_fastmcp_tools(self) -> None:
        schemas = get_tool_schema_list()
        calculate = next(schema for schema in schemas if schema["function"]["name"] == "calculate")
        self.assertEqual(calculate["function"]["parameters"]["required"], ["expression"])
        self.assertNotIn("point", calculate["function"])

    def test_calculate_executes_through_fastmcp_registration(self) -> None:
        result = execute_tool("calculate", {"expression": "2*(3+4)"})
        self.assertEqual(result, {"status": "success", "expression": "2*(3+4)", "result": 14})


if __name__ == "__main__":
    unittest.main(verbosity=2)
