# mcpterminal — MCP 远程终端 / AI Agent 执行基础设施

> **定位：Agent 的手和脚，不是大脑。**
>
> mcpterminal 为 AI Agent（Codex、Claude Code 等）提供可靠的远程服务器执行环境。
> 它是一个 MCP Tool Server，把 SSH 终端能力暴露为标准化工具，
> 让 AI 可以操作远程服务器，同时保留人类的实时观察、干预和接管能力。

```text
AI Agent (Codex / Claude / ...)
        │ MCP / stdio
        ▼
MCP Server (app.main --mcp)
        │ 本地回环 IPC（认证令牌）
        ▼
Terminal GUI ── 唯一的 SSHManager / SSH 会话 ──► Remote Server
    ▲   ▲
    │   └── Agent：proxy_command / ssh_exec 代理执行，或 autocomplete_command 补全
    └────── Human：在 GUI 输入、干预和接管
```

GUI 进程是 SSH 会话的唯一所有者，SSHManager 仍支持同时管理多个服务器会话；
GUI 当前终端只绑定其中一个“当前会话”，Agent 的代理与补全也只作用于该会话。
MCP Server 不建立第二条 SSH 连接，而是通过本地 IPC 请求 GUI 操作已有会话。
重复启动 GUI 会激活已有窗口，不会创建第二个终端程序实例。
`list_sessions` 仅查询 SSHManager 中的会话；切换 GUI 当前会话使用 `select_session`。

## MVP 目标

> "AI 版 SecureCRT" — 既是人工运维终端，也是 AI 的工具平台

- ✅ Windows GUI — 人类操作的终端界面
- ✅ SSH 连接 — 多服务器会话管理
- ✅ 实时 Terminal — 人工/AI 共享同一终端
- ✅ MCP Server — 将 SSH 能力标准化为 AI 可调用的工具
- ✅ 人工接管 — 随时介入 AI 的操作
- ✅ 命令确认 — 危险命令拦截与审批

## 为什么不是 Agent？

| 组件 | mcpterminal | AI Agent |
|------|:-----------:|:--------:|
| 推理 (Reasoning) | ❌ | ✅ |
| 规划 (Planning) | ❌ | ✅ |
| 记忆 (Memory) | ❌ | ✅ |
| 工具提供 (Tool Use) | ✅ | ✅ |
| 执行 (Execution) | ✅ | ✅ |
| 反馈循环 (Feedback Loop) | ❌ | ✅ |

mcpterminal 是 **Agent Runtime / Agent Tool Infrastructure**，提供 Agent 所需的执行层能力。
加上推理和规划层（Codex/Claude）后，才构成完整的 Agent 系统。

## 演进路线

```
Phase 1 (当前)           Phase 2               Phase 3
────────────────────────────────────────────────────────
MCP Remote Terminal  →  AI Ops Tool Platform  →  Agent Platform
(执行基础设施)          (场景工具生态)           (自带 Agent 层)
```

## 项目结构

```
mcpterminal/
├── app/
│   ├── main.py              # GUI 入口
│   ├── ipc.py               # MCP Server ↔ GUI 本地进程间桥接
│   ├── ui/                  # 界面（PySide6）
│   ├── terminal/            # SSH 终端组件
│   ├── tools/               # MCP 工具定义（场景专用工具）
│   ├── mcp/                 # MCP Server 核心
│   ├── ssh/                 # SSH 连接管理
│   └── config/              # 配置加载
├── tests/
├── requirements.txt
├── TODO.md
├── config.yaml
└── README.md
```

## 技术栈

- **GUI**: PySide6 + QML
- **SSH**: asyncssh / paramiko
- **终端**: QTermWidget / xterm.js
- **AI协议**: MCP (Model Context Protocol)
- **AI后端**: Codex CLI / Claude Code（作为 MCP Client）
- **数据库**: SQLite

## 安装与启动

### 源码用户（一次安装）

需要 Python 3.10–3.14。Windows 用户可以直接双击 `Install.cmd`，或在 PowerShell
中执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

安装并立即打开 GUI：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -RunGui
```

脚本会创建 `.venv`、安装运行时依赖并执行核心测试。MCP Server 本身只做依赖
检查和协议启动，不在 stdio 握手期间联网安装依赖。


## 开发顺序

```
1. PySide6 GUI         ← 当前
2. SSH Terminal
3. MCP Server
4. 接入 Codex/Claude
5. LXD/GPU/Docker 场景工具
6. (未来) 内置 Agent 层
```
