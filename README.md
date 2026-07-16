# mcpterminal — MCP 远程终端 / AI Agent 执行基础设施

> **定位：Agent 的手和脚，不是大脑。**
>
> mcpterminal 为 AI Agent（Codex、Claude Code 等）提供可靠的远程服务器执行环境。
> 它是一个 MCP Tool Server，把 SSH 终端能力暴露为标准化工具，
> 让 AI 可以操作远程服务器，同时保留人类的实时观察、干预和接管能力。

```
┌──────────────────────────────────────┐
│  AI Agent (Codex / Claude / ...)     │  ← 大脑：推理、规划、决策
├──────────────────────────────────────┤
│           MCP Protocol               │  ← 标准化工具调用协议
├──────────────────────────────────────┤
│          mcpterminal                 │  ← 本项目：执行基础设施
│  ┌────────────┐  ┌──────────────┐    │
│  │  MCP Server │  │  Terminal GUI │   │
│  ├────────────┤  ├──────────────┤    │
│  │  SSH 会话   │  │  人工接管      │    │
│  ├────────────┤  ├──────────────┤    │
│  │  权限控制   │  │  命令确认      │    │
│  ├────────────┤  ├──────────────┤    │
│  │  场景工具   │  │  操作记录      │    │
│  └────────────┘  └──────────────┘    │
├──────────────────────────────────────┤
│              SSH                      │
├──────────────────────────────────────┤
│         Remote Servers               │
└──────────────────────────────────────┘
```

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
- **打包**: PyInstaller

## 开发顺序

```
1. PySide6 GUI         ← 当前
2. SSH Terminal
3. MCP Server
4. 接入 Codex/Claude
5. LXD/GPU/Docker 场景工具
6. (未来) 内置 Agent 层
```
