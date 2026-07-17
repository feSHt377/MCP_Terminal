"""Agent 模块集成测试 — 模拟模式。"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.agent_loop import _match_simple, run_agent
from app.config.manager import get_servers
from app.ssh.bridge import SSHBridge
from app.ssh.manager import SSHManager


async def main():
    servers = get_servers()
    if not servers:
        print("无服务器配置，跳过测试")
        return

    cfg = list(servers.values())[0]

    # 连接
    bridge = SSHBridge()
    bridge.start()

    async def _connect():
        return await SSHManager().connect(
            host=cfg["host"],
            user=cfg.get("user", "root"),
            port=cfg.get("port", 22),
            password=cfg.get("password"),
        )

    result = bridge.submit(_connect())
    assert result["status"] == "success", result
    sid = result["session_id"]
    print(f"已连接: {sid}")

    # ---- 测试 Agent 模拟模式 ----
    print("\n" + "=" * 50)
    print("测试 Agent 模拟模式")

    # 关键词匹配测试
    assert _match_simple("检查GPU状态"), "GPU 关键词应匹配"
    assert _match_simple("查看磁盘空间"), "磁盘 关键词应匹配"
    assert _match_simple("docker状态"), "docker 关键词应匹配"
    assert _match_simple("abcxyz123") is None, "无意义文本不应匹配"
    print("  ✅ 关键词匹配正确")

    # Agent 循环测试
    results = []

    async def on_thinking(text):
        results.append(("thinking", text))

    async def on_result(name, r):
        results.append(("result", name, r.get("status")))

    all_r = await run_agent(
        "检查GPU",
        session_id=sid,
        on_thinking=lambda t: print(f"  🤖 {t}"),
        on_result=lambda name, r: print(f"  ✅ {name} → {r.get('status')}"),
    )
    assert len(all_r) > 0, "GPU 查询应有结果"
    print(f"  ✅ Agent 循环: {len(all_r)} 个工具调用")

    # 断开
    async def _disconnect():
        return await SSHManager().disconnect(sid)

    bridge.submit(_disconnect())
    bridge.stop()
    print("\n✅ Agent 集成测试通过")


if __name__ == "__main__":
    asyncio.run(main())
