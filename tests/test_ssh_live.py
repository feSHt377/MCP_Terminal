"""SSH 连接与命令执行集成测试。

用法：
    .venv\Scripts\activate
    python tests/test_ssh_live.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.manager import get_servers
from app.ssh.manager import SSHManager


async def main():
    servers = get_servers()
    if not servers:
        print("❌ config.yaml 中没有配置服务器，请先用 add_server 添加")
        return

    manager = SSHManager()
    name, cfg = list(servers.items())[0]
    host = cfg["host"]
    port = cfg.get("port", 22)
    user = cfg.get("user", "root")
    password = cfg.get("password")
    key_path = cfg.get("key_path")

    print("=" * 60)
    print(f"  连接: {user}@{host}:{port}")
    print(f"  认证: {'密码' if password else '密钥: ' + (key_path or '默认')}")
    print("=" * 60)

    # Step 1: 连接
    print("\n>>> ssh_connect ...")
    result = await manager.connect(
        host=host, user=user, port=port,
        password=password, key_path=key_path,
    )

    if result["status"] != "success":
        print(f"❌ 连接失败: {result['message']}")
        return

    session_id = result["session_id"]
    print(f"✅ 已连接: {session_id}")

    # Step 2: 执行测试命令
    test_commands = [
        ("whoami", "当前用户"),
        ("hostname", "主机名"),
        ("uname -a", "系统信息"),
        ("uptime", "运行时间"),
        ("df -h / | tail -1", "磁盘使用"),
        ("free -h | head -2", "内存信息"),
        ("ls -la /home", "家目录"),
    ]

    for cmd, desc in test_commands:
        print(f"\n>>> ssh_exec: {cmd}  ({desc})")
        result = await manager.exec_command(session_id, cmd, timeout=10)
        if result["status"] == "success":
            exit_code = result.get("exit_code", "?")
            stdout = result.get("stdout", "").strip()
            stderr = result.get("stderr", "").strip()
            print(f"    exit={exit_code}")
            if stdout:
                for line in stdout.splitlines():
                    print(f"    │ {line}")
            if stderr:
                print(f"    ⚠ {stderr}")
        else:
            print(f"    ❌ {result['message']}")

    # Step 3: 断开
    print(f"\n>>> ssh_disconnect ...")
    result = await manager.disconnect(session_id)
    print(f"    {result['message']}")

    print("\n" + "=" * 60)
    print("  ✅ SSH 集成测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
