"""配置管理模块 — 加载和访问 config.yaml。"""

import os
from pathlib import Path
from typing import Any

import yaml


# 项目根目录：config.yaml 所在目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _find_config() -> Path:
    """查找 config.yaml，优先项目根目录。"""
    config_path = _PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        return config_path
    raise FileNotFoundError(f"未找到 config.yaml（已搜索: {config_path}）")


def load_config() -> dict[str, Any]:
    """加载完整配置。"""
    config_path = _find_config()
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_servers() -> dict[str, dict[str, Any]]:
    """获取服务器列表配置。"""
    config = load_config()
    servers = config.get("servers") or {}
    # 过滤掉注释/示例（值为 None 或非字典的条目）
    return {k: v for k, v in servers.items() if isinstance(v, dict)}


def get_mcp_config() -> dict[str, Any]:
    """获取 MCP 相关配置。"""
    config = load_config()
    return config.get("mcp") or {"port": 5000}


def get_security_config() -> dict[str, Any]:
    """获取安全策略配置。"""
    config = load_config()
    return config.get("security") or {}


def get_logging_config() -> dict[str, Any]:
    """获取日志配置。"""
    config = load_config()
    return config.get("logging") or {"path": "./logs", "level": "INFO"}


def save_config(config: dict[str, Any]) -> None:
    """保存完整配置到 config.yaml。"""
    config_path = _find_config()
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def add_server(
    name: str,
    host: str,
    user: str = "root",
    port: int = 22,
    key_path: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """添加一台服务器到配置文件。

    Args:
        name: 服务器别名（如 "4090"）。
        host: IP 地址或主机名。
        user: SSH 用户名，默认 root。
        port: SSH 端口，默认 22。
        key_path: SSH 私钥路径（可选）。
        password: SSH 密码（可选，不推荐明文存储）。
    """
    config = load_config()
    if config is None:
        config = {}

    servers = config.get("servers") or {}
    if not isinstance(servers, dict):
        servers = {}

    if name in servers and isinstance(servers[name], dict):
        return {
            "status": "error",
            "message": f"服务器 {name} 已存在，请先 remove_server 再添加",
        }

    entry: dict[str, Any] = {"host": host, "port": port, "user": user}
    if key_path:
        entry["key_path"] = key_path
    if password:
        entry["password"] = password

    servers[name] = entry
    config["servers"] = servers
    save_config(config)

    return {
        "status": "success",
        "message": f"已添加服务器: {name}",
        "server": {name: {"host": host, "port": port, "user": user}},
    }


def remove_server(name: str) -> dict[str, Any]:
    """从配置文件中移除一台服务器。

    Args:
        name: 服务器别名。
    """
    config = load_config()
    servers = config.get("servers") or {}

    if name not in servers or not isinstance(servers[name], dict):
        return {"status": "error", "message": f"服务器 {name} 不存在"}

    removed = servers.pop(name)
    config["servers"] = servers
    save_config(config)

    return {
        "status": "success",
        "message": f"已移除服务器: {name}",
        "removed": {
            "host": removed.get("host"),
            "port": removed.get("port", 22),
            "user": removed.get("user"),
        },
    }
