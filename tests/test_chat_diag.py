"""快速诊断 Chat 窗口按钮问题。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ssh.bridge import SSHBridge
from app.agent.agent_loop import run_agent

# 1. Bridge 启动
bridge = SSHBridge()
bridge.start()
print(f"Bridge ready: {bridge._ready}")

# 2. 提交 agent 任务
result = bridge.submit(run_agent("列出服务器", session_id=None))
print(f"Results: {len(result)} items")
for r in result:
    print(f"  {r['tool']} -> {r['result']['status']}")

# 3. 停止
bridge.stop()
print("OK - Bridge + Agent 链路正常")
