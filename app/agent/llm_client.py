"""LLM 客户端 — OpenAI 兼容 API 封装。

支持任意 OpenAI 兼容接口（Claude API、Ollama、本地模型等）。
"""  # noqa: D205

from __future__ import annotations

import json
import logging
from typing import Any

import requests

logger = logging.getLogger("mcpterminal.agent")


# ------------------------------------------------------------------
# Schema 转换：FastMCP 工具 → OpenAI function calling 格式
# ------------------------------------------------------------------

def _fastmcp_to_openai_schema(tool) -> dict[str, Any]:
    """将 FastMCP 工具转为 OpenAI function calling schema。"""
    params = tool.parameters
    properties = {}
    required = []

    for name, info in params.get("properties", {}).items():
        prop: dict[str, Any] = {
            "type": info.get("type", "string"),
            "description": info.get("description", ""),
        }
        if "enum" in info:
            prop["enum"] = info["enum"]
        if "default" in info:
            prop["default"] = info["default"]
        properties[name] = prop

    if "required" in params:
        required = params["required"]

    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def get_tool_schemas() -> list[dict[str, Any]]:
    """获取所有 MCP 工具的 OpenAI function calling schema。"""
    from app.tools.definitions import mcp

    return [_fastmcp_to_openai_schema(t) for t in mcp._tool_manager._tools.values()]


# ------------------------------------------------------------------
# LLM Client
# ------------------------------------------------------------------


class LLMClient:
    """OpenAI 兼容 API 客户端。

    用法:
        client = LLMClient(base_url="https://api.openai.com/v1", api_key="...", model="gpt-4")
        response = client.chat("帮我检查 GPU 状态", tools=tool_schemas)
    """

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        model: str = "gpt-4",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.session = requests.Session()
        self.session.trust_env = False  # 不走系统代理

    def chat(
        self,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str = "",
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """发送单轮对话，返回模型响应或工具调用指令。

        Returns:
            {
                "status": "success" | "error",
                "content": "text response",         # 文本回复
                "tool_calls": [{...}],              # 工具调用指令
                "message": "error message",         # 错误信息
            }
        """
        if not system_prompt:
            system_prompt = (
                "你是一个 Linux 运维助手，可以通过 SSH 在远程服务器上执行命令。"
                "当用户要求执行操作时，请调用相应的工具。"
                "返回结果时用中文简短说明。"
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            resp = self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

            choice = data["choices"][0]
            msg = choice.get("message", {})

            result: dict[str, Any] = {"status": "success"}

            # 文本回复
            if msg.get("content"):
                result["content"] = msg["content"]

            # 工具调用
            if msg.get("tool_calls"):
                result["tool_calls"] = []
                for tc in msg["tool_calls"]:
                    func = tc["function"]
                    try:
                        args = json.loads(func["arguments"])
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    result["tool_calls"].append({
                        "id": tc.get("id", ""),
                        "name": func["name"],
                        "arguments": args,
                    })

            return result

        except requests.RequestException as e:
            logger.error("LLM 请求失败: %s", e)
            return {"status": "error", "message": str(e)}
        except (KeyError, IndexError) as e:
            logger.error("LLM 响应解析失败: %s", e)
            return {"status": "error", "message": f"响应解析失败: {e}"}


# ------------------------------------------------------------------
# 工厂函数
# ------------------------------------------------------------------


def create_client_from_config() -> LLMClient | None:
    """从 config.yaml 创建 LLM 客户端。"""
    import os

    from app.config.manager import load_config

    cfg = load_config()
    ai_cfg = cfg.get("ai", {})

    provider = ai_cfg.get("provider", "claude")
    model = ai_cfg.get("model", "claude-sonnet-4-20250514")
    api_key = ai_cfg.get("api_key") or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or ""

    if not api_key:
        return None  # 无 API key，走模拟模式

    base_urls = {
        "claude": "https://api.anthropic.com/v1",
        "openai": "https://api.openai.com/v1",
        "codex": "https://api.openai.com/v1",
        "ollama": "http://localhost:11434/v1",
    }
    base_url = ai_cfg.get("api_url") or base_urls.get(provider, base_urls["openai"])

    return LLMClient(base_url=base_url, api_key=api_key, model=model)
