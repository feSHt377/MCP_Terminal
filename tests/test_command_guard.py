"""命令聚合校验（command_guard）测试脚本。

覆盖:
- 应放行的命令：单命令、管道、单个连接符（cd && 形式）、后台运行、
  引号/转义/命令替换内的连接符
- 应拒绝的命令：多行命令、heredoc、2 个及以上连接符的命令链
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from app.tools.command_guard import check_agent_command, _scan


# 来自真实 Agent 日志的高聚合命令（应全部拒绝）
REAL_AGENT_CHAINS = [
    'ls -lh /home/fesht3/models/; echo "---"; ps aux 2>/dev/null | grep -E "wget.*Qwen3.8" | grep -v grep || echo "wget已退出"',
    'f="/home/fesht3/models/Qwen3.8.gguf"; head -c 4 "$f" | xxd; python3 - "$f" <<\'EOF\'\nprint("hi")\nEOF',
    'cd /root/llama.cpp/gguf-py && PYTHONPATH=/root/llama.cpp/gguf-py python3 - x.gguf <<\'EOF\' 2>&1 | tail -25\nimport sys\nEOF',
    '/root/venv-hf/bin/pip install -q numpy 2>&1 | tail -2; PYTHONPATH=/root /root/venv-hf/bin/python - x.gguf <<\'EOF\'\nimport sys\nEOF',
]

ALLOWED = [
    # 单命令 / 常用探测
    "nvidia-smi",
    "ls -lh /home/fesht3/models/",
    "ps aux --sort=-%cpu | head -10",
    "docker ps -a --format '{{.Names}}'",
    # 管道不受限，输出仍然逐步可见
    'ps aux 2>/dev/null | grep -E "wget.*Qwen3.8" | grep -v grep',
    "diff <(sort a.txt) <(sort b.txt)",
    # 单个连接符：cd 不会跨调用持久，cd && 形式必须保留
    "cd /root/llama.cpp/gguf-py && ls",
    'f="/home/fesht3/models/x.gguf"; head -c 4 "$f"',
    "ping -c1 host || echo down",
    "server1 & server2",
    # 单命令后台
    "nohup python server.py > server.log 2>&1 &",
    # 引号 / 转义 / 命令替换内的连接符不是命令链
    'echo "a && b; c || d"',
    "grep 'a;b' file.txt",
    r"find . -name '*.log' -exec rm {} \;",
    'echo "today is $(date; uptime)"',
    'echo `whoami`',
    # here-string 是单行输入
    'cat <<< "hello world"',
    # 末尾换行不算多行
    "echo hi\n",
]

REJECTED = [
    # 真实 Agent 链
    *REAL_AGENT_CHAINS,
    # 多行命令（即使没有连接符）
    "echo line1\necho line2",
    # heredoc 本身
    "cat <<EOF\nhello\nEOF",
    # 两个连接符
    "cd /opt && make && make install",
    "sync; echo done; sync",
    "for f in *.log; do gzip \"$f\"; done",
    # 连接式后台
    "server1 & server2 & server3",
    # 单行 for/case 等复合语句天然含多个分隔符
    "case $x in a) echo 1;; b) echo 2;; esac",
]


def test_allowed():
    print("\n" + "=" * 60)
    print("Test 1: 应放行的命令")
    print("=" * 60)
    for cmd in ALLOWED:
        result = check_agent_command(cmd)
        display = cmd.replace("\n", "\\n")[:70]
        assert result is None, f"应放行却被拒绝: {display!r} → {result}"
        print(f"  ✅ 放行: {display}")


def test_rejected():
    print("\n" + "=" * 60)
    print("Test 2: 应拒绝的高聚合命令")
    print("=" * 60)
    for cmd in REJECTED:
        result = check_agent_command(cmd)
        display = cmd.replace("\n", "\\n")[:70]
        assert result is not None, f"应拒绝却放行: {display!r}"
        assert result["reason"] == "aggregated_command"
        assert result["issues"], "拒绝结果应包含 issues 说明"
        assert "upload_file" in result["message"], "错误信息应给出替代方案"
        print(f"  ✅ 拒绝[{'; '.join(result['issues'])}]: {display}")


def test_scan_details():
    print("\n" + "=" * 60)
    print("Test 3: 扫描细节")
    print("=" * 60)
    scan = _scan("nohup python server.py > server.log 2>&1 &")
    assert scan["background"] is True, "末尾 & 应识别为单命令后台"
    assert scan["connectors"] == [], "2>&1 中的 & 不应计入连接符"

    scan = _scan("a & b")
    assert scan["connectors"] == ["&"], "连接式后台 & 应计入连接符"

    scan = _scan('ps aux | grep x |& grep y')
    assert scan["pipes"] == 2, "管道与 |& 应计入管道数"
    assert scan["connectors"] == [], "管道不是连接符"

    scan = _scan('echo "$(head -1 f; tail -1 f)"')
    assert scan["connectors"] == [], "命令替换内的连接符不应计入"

    scan = _scan("cat <<'EOF'\nbody\nEOF")
    assert scan["heredoc"] is True and scan["multiline"] is True, "heredoc 应同时标记多行"

    scan = _scan("")
    assert check_agent_command("  \n ") is None, "空白命令交给下游处理"

    print("  ✅ 扫描细节全部通过")


if __name__ == "__main__":
    test_allowed()
    test_rejected()
    test_scan_details()
    print("\n" + "=" * 60)
    print("✅ command_guard 全部测试通过")
    print("=" * 60)
