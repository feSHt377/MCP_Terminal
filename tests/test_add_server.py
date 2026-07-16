"""测试 add_server / remove_server 工具。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.definitions import (
    mcp,
    add_server,
    remove_server,
    list_servers,
)
from app.config.manager import load_config

print("=" * 60)
print("Test: add_server / remove_server")
print("=" * 60)

# 1. 验证工具注册
tools = mcp._tool_manager._tools
assert "add_server" in tools, "add_server 未注册"
assert "remove_server" in tools, "remove_server 未注册"
print(f"  工具总数: {len(tools)}")
print(f"  ✅ add_server 已注册")
print(f"  ✅ remove_server 已注册")

# 2. 测试添加服务器
r = add_server(
    "test-server",
    host="192.168.1.100",
    user="admin",
    port=2222,
    key_path="~/.ssh/test",
)
assert r["status"] == "success", f"添加失败: {r}"
print(f"  ✅ add_server: {r['message']}")

# 3. 重复添加应报错
r = add_server("test-server", host="192.168.1.100", user="admin")
assert r["status"] == "error"
print(f"  ✅ 重复添加 → {r['message']}")

# 4. 验证配置已写入
cfg = load_config()
assert "test-server" in cfg["servers"]
print(f"  ✅ config.yaml 已持久化: {cfg['servers']['test-server']}")

# 5. 测试 list_servers
r = list_servers()
assert "test-server" in r["servers"]
print(f"  ✅ list_servers 包含 test-server")

# 6. 测试删除
r = remove_server("test-server")
assert r["status"] == "success"
print(f"  ✅ remove_server: {r['message']}")

# 7. 删除不存在的
r = remove_server("test-server")
assert r["status"] == "error"
print(f"  ✅ 删除不存在 → {r['message']}")

# 8. 确认已清除
cfg = load_config()
assert "test-server" not in (cfg.get("servers") or {})
print(f"  ✅ config.yaml 已清理")

print()
print("  全部通过!")
