"""Agent 循环 — 自然语言 → 工具调用 → 执行 → 反馈。

支持两种模式:
- LLM 模式: 调用 OpenAI 兼容 API 进行推理
- 模拟模式: 无 API key 时用关键词匹配（演示用途）
"""  # noqa: D205

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("mcpterminal.agent")


# ------------------------------------------------------------------
# 模拟模式：关键词匹配
# ------------------------------------------------------------------

_SIMPLE_PATTERNS: list[tuple[list[str], str, dict[str, Any]]] = [
    (
        ["gpu", "显卡", "nvidia", "cuda"],
        "ssh_exec",
        {"command": "nvidia-smi"},
    ),
    (
        ["docker", "容器"],
        "ssh_exec",
        {"command": "docker ps"},
    ),
    (
        ["磁盘", "空间", "df", "硬盘"],
        "ssh_exec",
        {"command": "df -h"},
    ),
    (
        ["内存", "memory", "ram", "free"],
        "ssh_exec",
        {"command": "free -h"},
    ),
    (
        ["进程", "ps", "top", "cpu"],
        "ssh_exec",
        {"command": "ps aux --sort=-%cpu | head -10"},
    ),
    (
        ["系统", "版本", "uname", "系统信息"],
        "ssh_exec",
        {"command": "uname -a"},
    ),
    (
        ["时间", "运行时间", "uptime"],
        "ssh_exec",
        {"command": "uptime"},
    ),
    (
        ["谁", "用户", "whoami", "当前用户"],
        "ssh_exec",
        {"command": "whoami"},
    ),
    (
        ["lxc", "lxd", "lxd容器"],
        "ssh_exec",
        {"command": "lxc list"},
    ),
    (
        ["网络", "ip", "网卡", "ifconfig"],
        "ssh_exec",
        {"command": "ip addr"},
    ),
    (
        ["文件", "ls", "目录", "列出"],
        "ssh_exec",
        {"command": "ls -la"},
    ),
    (
        ["服务器列表", "有哪些服务器"],
        "list_servers",
        {},
    ),
    (
        ["连接状态", "会话"],
        "list_sessions",
        {},
    ),
    (
        ["危险命令", "安全"],
        "get_dangerous_commands",
        {},
    ),
]


def _match_simple(prompt: str) -> list[dict[str, Any]] | None:
    """关键词匹配，返回模拟的工具调用列表。"""
    prompt_lower = prompt.lower()
    for keywords, tool_name, args in _SIMPLE_PATTERNS:
        for kw in keywords:
            if kw in prompt_lower:
                return [{"id": "sim_0", "name": tool_name, "arguments": dict(args)}]
    return None


# ------------------------------------------------------------------
# 工具执行器
# ------------------------------------------------------------------

async def _execute_tool(name: str, arguments: dict[str, Any], session_id: str | None) -> dict[str, Any]:
    """执行单个 MCP 工具。"""
    from app.tools.definitions import mcp

    tools_map = {t.name: t for t in mcp._tool_manager._tools.values()}
    tool = tools_map.get(name)

    if tool is None:
        return {"status": "error", "message": f"未知工具: {name}"}

    # 异步工具直接 await，同步工具包装
    import asyncio
    import inspect

    try:
        if inspect.iscoroutinefunction(tool.fn):
            result = await tool.fn(**arguments)
        else:
            result = tool.fn(**arguments)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ------------------------------------------------------------------
# Agent 循环
# ------------------------------------------------------------------


async def run_agent(
    prompt: str,
    session_id: str | None = None,
    on_thinking: callable = None,
    on_result: callable = None,
    max_rounds: int = 5,
) -> list[dict[str, Any]]:
    """运行 Agent 循环：自然语言 → 工具调用 → 执行 → 反馈。

    Args:
        prompt: 用户输入的自然语言。
        session_id: 当前 SSH 会话 ID（自动注入 ssh_exec 等工具）。
        on_thinking: 思考过程回调 (text: str) -> None。
        on_result: 结果回调 (tool_name: str, result: dict) -> None。
        max_rounds: 最大工具调用轮数。

    Returns:
        所有工具调用的结果列表。
    """
    from app.agent.llm_client import create_client_from_config, get_tool_schemas

    all_results: list[dict[str, Any]] = []
    client = create_client_from_config()
    tools = get_tool_schemas()

    if on_thinking:
        on_thinking(f"用户: {prompt}")

    # ---- 模式 1: LLM 模式 ----
    if client is not None:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "你是 Linux 运维助手。用中文简短回复。"
                    "当需要执行操作时调用工具。"
                    "每轮最多执行一条远程命令，必须等待并分析 stdout/stderr 后再决定下一步。"
                    "不要并行发命令，不要在没理解错误时用猜测参数连续重试。"
                ),
            },
            {"role": "user", "content": prompt},
        ]

        for _round in range(max_rounds):
            # 调用 LLM
            payload: dict[str, Any] = {
                "model": client.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.2,
            }

            try:
                resp = client.session.post(
                    f"{client.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {client.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error("Agent LLM 请求失败: %s", e)
                if on_thinking:
                    on_thinking(f"❌ 模型请求失败: {e}")
                break

            choice = data["choices"][0]
            msg = choice.get("message", {})

            # LLM 返回文本（最终答案）
            if msg.get("content") and not msg.get("tool_calls"):
                if on_thinking:
                    on_thinking(f"Agent: {msg['content']}")
                break

            # LLM 返回工具调用
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    func = tc["function"]
                    try:
                        import json
                        args = json.loads(func["arguments"])
                    except Exception:
                        args = {}

                    # 自动注入 session_id
                    if func["name"] in ("ssh_exec", "ssh_connect", "ssh_disconnect",
                                        "terminal_write", "terminal_read",
                                        "upload_file", "download_file"):
                        if session_id and "session_id" not in args:
                            args["session_id"] = session_id

                    if on_thinking:
                        on_thinking(f"🔧 调用 {func['name']}({args})")

                    result = await _execute_tool(func["name"], args, session_id)
                    all_results.append({"tool": func["name"], "args": args, "result": result})

                    if on_result:
                        on_result(func["name"], result)

                    # 将结果反馈给 LLM
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tc],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })

        return all_results

    # ---- 模式 2: 模拟模式（关键词匹配） ----
    tool_calls = _match_simple(prompt)
    if tool_calls is None:
        if on_thinking:
            on_thinking(
                "Agent（模拟）: 未识别到具体操作。试试说 '检查GPU' / '查看磁盘' / '列出服务器' / 'docker状态' 等。"
            )
        return []

    for tc in tool_calls:
        name = tc["name"]
        args = dict(tc["arguments"])

        # 自动注入 session_id
        if name in ("ssh_exec", "ssh_connect", "ssh_disconnect",
                    "terminal_write", "terminal_read",
                    "upload_file", "download_file"):
            if session_id and "session_id" not in args:
                args["session_id"] = session_id

        if on_thinking:
            on_thinking(f"🔧 Agent（模拟）调用 {name}({args})")

        result = await _execute_tool(name, args, session_id)
        all_results.append({"tool": name, "args": args, "result": result})

        if on_result:
            on_result(name, result)

    return all_results
