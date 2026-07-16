"""FastMCP 工具集。

每个函数使用 ``@mcp.tool()`` 注册；函数签名和 docstring 同时就是
工具的参数 Schema 与说明，避免维护独立的定义文件。
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("aitools")
LOG_DIR = "logs"
HISTORY_FILE = os.path.join(LOG_DIR, "tool_call_history.json")


def _setup_logger():
    """配置日志记录器，只写入文件，不输出到控制台"""
    logger = logging.getLogger("aitools")
    # 清除现有的 handlers
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    
    # 创建文件 handler
    os.makedirs(LOG_DIR, exist_ok=True)
    fh = logging.FileHandler(
        os.path.join(LOG_DIR, "tool_calls.log"),
        mode="a",
        encoding="utf-8"
    )
    fh.setLevel(logging.INFO)
    
    # 设置格式
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    fh.setFormatter(formatter)
    
    # 添加 handler，禁用传播到根 logger
    logger.addHandler(fh)
    logger.propagate = False
    
    return logger


logger = _setup_logger()


def _ensure_log_dir() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)


def _load_history() -> list[dict[str, Any]]:
    _ensure_log_dir()
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as history_file:
            return json.load(history_file)
    except (OSError, json.JSONDecodeError):
        return []


def _save_history(history: list[dict[str, Any]]) -> None:
    _ensure_log_dir()
    with open(HISTORY_FILE, "w", encoding="utf-8") as history_file:
        json.dump(history, history_file, ensure_ascii=False, indent=2)


@mcp.tool()
def save_data_to_log(category: str, data: dict[str, Any], priority: str = "medium") -> dict[str, Any]:
    """保存一条结构化记录到本地工具调用日志。

    Args:
        category: 记录分类，例如 user_input、model_response 或 system_event。
        data: 要保存的键值数据。
        priority: 优先级，只能是 low、medium 或 high。
    """
    if priority not in {"low", "medium", "high"}:
        return {"status": "error", "message": "priority 必须是 low、medium 或 high"}

    history = _load_history()
    record = {
        "timestamp": datetime.now().isoformat(),
        "category": category,
        "data": data,
        "priority": priority,
    }
    history.append(record)
    _save_history(history)
    logger.info("[%s] %s: %s", priority.upper(), category, json.dumps(data, ensure_ascii=False))
    return {"status": "success", "message": f"数据已保存到 {HISTORY_FILE}", "record_id": len(history)}


@mcp.tool()
def query_logs(category: str | None = None, limit: int = 10) -> dict[str, Any]:
    """查询已保存的工具调用日志，可按分类筛选。

    Args:
        category: 可选的记录分类；未提供时返回所有分类。
        limit: 返回的最大记录数，范围为 1 到 100。
    """
    if not 1 <= limit <= 100:
        return {"status": "error", "message": "limit 必须在 1 到 100 之间"}

    history = _load_history()
    records = [record for record in history if record["category"] == category] if category else history
    records = records[-limit:]
    return {
        "status": "success",
        "total_records": len(history),
        "filtered_records": len(records),
        "records": records,
    }


@mcp.tool()
def get_test_statistics() -> dict[str, Any]:
    """获取本地工具调用日志的总量、分类和优先级统计。"""
    history = _load_history()
    by_category: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for record in history:
        by_category[record["category"]] = by_category.get(record["category"], 0) + 1
        by_priority[record["priority"]] = by_priority.get(record["priority"], 0) + 1
    return {"status": "success", "statistics": {"total_calls": len(history), "by_category": by_category, "by_priority": by_priority}}


@mcp.tool()
def show_popup(title: str, content: str, icon: str = "info") -> dict[str, Any]:
    """显示一个 Windows 消息弹窗。

    Args:
        title: 弹窗标题。
        content: 弹窗文本内容。
        icon: 图标类型，只能是 info、warning、error 或 question。
    """
    icon_map = {"info": 0x40, "warning": 0x30, "error": 0x10, "question": 0x20}
    if icon not in icon_map:
        return {"status": "error", "message": "icon 必须是 info、warning、error 或 question"}

    popup_code = (
        "import ctypes;"
        f"ctypes.windll.user32.MessageBoxW(0,{content!r},{title!r},{icon_map[icon]}|0x1000)"
    )
    subprocess.Popen([sys.executable, "-c", popup_code])
    return {"status": "success", "message": f"弹窗已打开: {title}"}


@mcp.tool()
def test_recall() -> dict[str, Any]:
    """以弹窗显示最近一条日志记录，用于验证工具调用。"""
    history = _load_history()
    last_record = history[-1] if history else {"info": "暂无历史记录"}
    return show_popup("Function Calling 测试", json.dumps(last_record, ensure_ascii=False, indent=2), "info")


@mcp.tool()
def calculate(expression: str) -> dict[str, Any]:
    """计算仅包含加减乘除、括号和小数的数学表达式。

    Args:
        expression: 数学表达式，例如 5*9+10-3/2。
    """
    if not re.fullmatch(r"[\d\s+\-*/.()]+", expression):
        return {"status": "error", "message": "表达式包含非法字符"}
    try:
        return {"status": "success", "expression": expression, "result": eval(expression, {"__builtins__": {}}, {})}
    except ZeroDivisionError:
        return {"status": "error", "message": "除数不能为零"}
    except (ArithmeticError, SyntaxError, ValueError) as error:
        return {"status": "error", "message": f"计算失败: {error}"}


@mcp.tool()
def get_local_time() -> dict[str, Any]:
    """获取当前系统本地时间，返回 ISO 8601 格式字符串。"""
    return {"status": "success", "local_time": datetime.now().isoformat()}


@mcp.tool()
def get_self_info() -> dict[str, Any]:
    """读取配置文件并返回当前启用的本地模型信息。"""
    config_path = os.path.join("config", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except FileNotFoundError:
        return {"status": "error", "message": "配置文件不存在"}
    except (OSError, json.JSONDecodeError) as error:
        return {"status": "error", "message": f"读取配置失败: {error}"}

    for name, model in config.get("models", {}).items():
        if not model.get("disable", False):
            return {
                "status": "success",
                "model_info": {
                    "name": name,
                    "api_url": model.get("api_url", ""),
                    "default_model": model.get("default_model", ""),
                    "provider": "ollama",
                },
                "config_path": config_path,
            }
    return {"status": "error", "message": "未找到启用的模型配置"}


def get_tool_schema_list() -> list[dict[str, Any]]:
    """将 FastMCP 注册的工具转换为 Ollama Function Calling Schema。"""
    return [
        {
            "type": "function",
            "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
        }
        for tool in mcp._tool_manager.list_tools()
    ]


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """供本地测试脚本调用 FastMCP 已注册工具。"""
    try:
        result = asyncio.run(mcp._tool_manager.call_tool(name, arguments))
        return result if isinstance(result, dict) else {"status": "success", "result": result}
    except Exception as error:
        return {"status": "error", "message": f"{type(error).__name__}: {error}"}
