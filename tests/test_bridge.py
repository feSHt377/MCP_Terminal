"""验证 SSHBridge 线程模型：连接 → 执行 → 断开全流程。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.manager import get_servers
from app.ssh.bridge import SSHBridge
from app.ssh.manager import SSHManager


async def main():
    servers = get_servers()
    if not servers:
        print("无服务器配置，跳过测试")
        return

    cfg = list(servers.values())[0]

    bridge = SSHBridge()
    bridge.start()
    print("bridge 线程已启动")

    # 连接
    async def _connect():
        return await SSHManager().connect(
            host=cfg["host"],
            user=cfg.get("user", "root"),
            port=cfg.get("port", 22),
            password=cfg.get("password"),
            key_path=cfg.get("key_path"),
        )

    result = bridge.submit(_connect())
    assert result["status"] == "success", f"连接失败: {result}"
    sid = result["session_id"]
    print(f"  连接: OK ({sid})")

    # 执行 3 条命令（模拟多次 terminal 输入）
    for cmd in ["echo hello1", "echo hello2", "uname -r"]:
        async def _exec(c=cmd):
            return await SSHManager().exec_command(sid, c)

        result = bridge.submit(_exec())
        assert result["status"] == "success"
        out = result.get("stdout", "").strip()
        print(f"  {cmd} → {out}")

    # 断开
    async def _disconnect():
        return await SSHManager().disconnect(sid)

    result = bridge.submit(_disconnect())
    print(f"  断开: {result['message']}")

    bridge.stop()
    print("✅ SSHBridge 线程模型验证通过")


if __name__ == "__main__":
    asyncio.run(main())
