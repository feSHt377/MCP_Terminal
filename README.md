# MCP Terminal — 通用 Agent 远程执行基础设施

> **定位：任意 Agent 的手和脚，不是大脑。**
>
> MCP Terminal 是一个基于 MCP 协议的通用执行层基础设施，为任何 AI Agent 提供可靠的远程服务器操作能力。
> 它将 SSH 终端能力暴露为标准化工具，通过 MCP 协议与 Agent 通信，
> 理论上兼容任何遵循 MCP 规范的 Agent——无论其底层模型是 GPT、Claude、Gemini、Qwen，还是本地部署的开源模型。
>
> **核心理念：人在回路（Human-in-the-Loop）**
>
> 人类不是旁观者，而是整个执行链路的监督者、决策者和最终接管者。
> MCP Terminal 确保人类始终拥有对远程操作的实时可见性、干预能力和完全控制权。

## 架构总览

```text
┌──────────────────────────────────────────────────────────────┐
│  AI Agent (Codex / Claude Code / ...)                        │
│  └── MCP Client (stdio)                                      │
└───────────────────────┬──────────────────────────────────────┘
                        │  MCP Protocol
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  MCP Server  (python -m app.main --mcp)                      │
│  ├── 16+ 标准化工具 (SSH / 文件传输 / 会话管理 / 安全策略)     │
│  └── 内置 Agent 层 (LLM + Function Calling)                  │
└───────────────────────┬──────────────────────────────────────┘
                        │  本地回环 IPC (JSON-RPC + 认证令牌)
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  Terminal GUI  (PySide6)                                     │
│  ├── 唯一 SSHManager ── 多服务器会话管理                      │
│  ├── 当前终端绑定 ── 人工/AI 共享同一终端                      │
│  ├── 聊天窗口 ── 自然语言指令输入                              │
│  └── 安全策略 ── 危险命令拦截 & 审批                           │
└───────────────────────┬──────────────────────────────────────┘
                        │  SSH
                        ▼
              ┌──────────────────┐
              │  Remote Servers  │
              │  (Linux / LXD)   │
              └──────────────────┘
```

**核心设计原则：**

- GUI 进程是 SSH 会话的**唯一所有者**，MCP Server 不建立第二条 SSH 连接
- MCP Server 通过本地 IPC（回环地址 + 随机令牌）请求 GUI 操作已有会话
- 重复启动 GUI 会激活已有窗口，不会创建第二个终端程序实例
- `list_sessions` 查询所有会话；`select_session` 切换 GUI 当前焦点

## 快速开始

### 安装

需要 **Python 3.10–3.14**。Windows 用户可直接双击 `Install.cmd`，或在 PowerShell 中执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

安装并立即打开 GUI：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -RunGui
```

脚本会自动创建 `.venv`、安装运行时依赖并执行核心测试。

### 启动 GUI

```bash
python -m app.main
```

### 启动 MCP Server

```bash
python -m app.main --mcp
```

MCP Server 通过 stdio 与 AI Agent 通信，不在握手期间联网安装依赖。

## MCP 工具集

MCP Terminal 暴露以下标准化工具，AI Agent 可通过 MCP 协议调用：

### 终端控制

| 工具 | 说明 |
|------|------|
| `launch_gui` | 启动或激活 GUI 终端窗口 |

### SSH 连接

| 工具 | 说明 |
|------|------|
| `ssh_connect` | 建立到远程服务器的 SSH 连接 |
| `ssh_disconnect` | 断开指定的 SSH 会话 |

### 命令执行

| 工具 | 说明 |
|------|------|
| `proxy_command` | 在 GUI 当前会话代理执行命令（推荐） |
| `ssh_exec` | 通过 session_id 在指定会话执行命令 |
| `autocomplete_command` | 将命令补全到 GUI 输入框，交由用户确认 |

### 交互式终端

| 工具 | 说明 |
|------|------|
| `terminal_write` | 向交互式 SSH shell 写入数据 |
| `terminal_read` | 从交互式 SSH shell 读取输出 |

### 文件传输

| 工具 | 说明 |
|------|------|
| `upload_file` | 上传本地文件到远程服务器（SFTP） |
| `download_file` | 从远程服务器下载文件到本地（SFTP） |

### 服务器与会话管理

| 工具 | 说明 |
|------|------|
| `list_servers` | 列出配置文件中定义的所有服务器 |
| `list_sessions` | 列出所有活跃的 SSH 会话及状态 |
| `select_session` | 切换 GUI 当前终端到指定会话 |
| `add_server` | 添加 SSH 服务器到配置文件 |
| `remove_server` | 从配置文件中移除服务器 |

### 安全策略

| 工具 | 说明 |
|------|------|
| `get_dangerous_commands` | 获取危险命令列表和安全策略 |

## 使用方式

### 方式一：接入外部 AI Agent（MCP 协议）

MCP Terminal 本质上是一个 MCP Tool Server，任何支持 MCP 的 Agent 都可以接入。

#### VS Code / GitHub Copilot

在项目根目录创建 `.vscode/mcp.json`（`setup.ps1` 安装完成后会自动提示）：

```json
{
  "servers": {
    "mcpterminal": {
      "type": "stdio",
      "command": ".venv\\Scripts\\python.exe",
      "args": ["-m", "app.main", "--mcp"]
    }
  }
}
```

> macOS / Linux 将 `command` 改为 `.venv/bin/python`。

#### Claude Desktop

编辑 `claude_desktop_config.json`（Windows: `%APPDATA%\Claude\`，macOS: `~/Library/Application Support/Claude/`）：

```json
{
  "mcpServers": {
    "mcpterminal": {
      "command": ".venv\\Scripts\\python.exe",
      "args": ["-m", "app.main", "--mcp"]
    }
  }
}
```

#### 其他 MCP Client

任何遵循 MCP stdio 协议的客户端，只需配置：

- **command**: `.venv\Scripts\python.exe`（或 `.venv/bin/python`）
- **args**: `["-m", "app.main", "--mcp"]`

Agent 接入后即可通过自然语言调用所有工具，如：

> "帮我查看服务器的 GPU 状态"  →  Agent 调用 `ssh_exec(nvidia-smi)`
> "上传本地文件到远程 /tmp 目录"  →  Agent 调用 `upload_file(...)`

#### 模型无关性

MCP Terminal 通过标准 MCP 协议暴露工具，不依赖任何特定模型或 Agent 实现。
无论你使用 GPT-4、Claude Sonnet、Gemini、Qwen、DeepSeek，
还是本地 Ollama 部署的开源模型，只要 Agent 框架支持 MCP，即可无缝接入。

### 方式二：内置 Agent（自然语言 → 工具调用）

GUI 内置聊天窗口，支持直接输入自然语言指令：

- **LLM 模式**：连接 OpenAI 兼容 API，通过 Function Calling 自动选择工具
- **模拟模式**：无 API key 时，基于关键词匹配执行（演示用途）

### 方式三：人工操作 GUI

直接通过 GUI 界面连接服务器、执行命令、传输文件。
所有操作对 AI Agent 可见，人类可随时监控、干预和接管。

## 为什么不是 Agent？

| 组件 | MCP Terminal | AI Agent |
|------|:-----------:|:--------:|
| 推理 (Reasoning) | ❌ | ✅ |
| 规划 (Planning) | ❌ | ✅ |
| 记忆 (Memory) | ❌ | ✅ |
| 工具提供 (Tool Use) | ✅ | ✅ |
| 执行 (Execution) | ✅ | ✅ |
| 反馈循环 (Feedback Loop) | ❌ | ✅ |

MCP Terminal 是 **Agent Runtime / Agent Tool Infrastructure**，为任意 Agent 提供统一的执行层能力。

## 演进路线

```
Phase 1 (当前)           Phase 2               Phase 3
─────────────────────────────────────────────────────────
MCP Remote Terminal  →  AI Ops Tool Platform  →  Agent Platform
(执行基础设施)          (场景工具生态)           (自带 Agent 层)
```

## 项目结构

```
mcpterminal/
├── app/
│   ├── main.py              # GUI / MCP Server 入口
│   ├── ipc.py               # MCP Server ↔ GUI 本地进程间桥接
│   ├── agent/               # 内置 Agent 层
│   │   ├── agent_loop.py    # Agent 循环：自然语言 → 工具调用 → 执行
│   │   └── llm_client.py    # OpenAI 兼容 API 客户端
│   ├── ui/                  # 界面（PySide6）
│   │   ├── main_window.py   # 主窗口
│   │   ├── server_panel.py  # 服务器管理面板
│   │   ├── status_panel.py  # 状态面板
│   │   ├── terminal_widget.py # 终端组件
│   │   └── chat_window.py   # 聊天窗口
│   ├── terminal/            # SSH 终端组件
│   ├── tools/               # MCP 工具定义
│   │   └── definitions.py   # 16+ 标准化工具
│   ├── mcp/                 # MCP Server 核心
│   │   └── server.py        # FastMCP 服务
│   ├── ssh/                 # SSH 连接管理
│   │   ├── manager.py       # SSHManager：多会话管理
│   │   └── bridge.py        # SSH 桥接
│   └── config/              # 配置加载
│       └── manager.py       # 服务器/安全配置管理
├── Skills/                  # Agent 技能文档
│   └── mcpterminal-ops/     # 远程运维操作技能
├── tests/                   # 测试套件
├── config.yaml              # 服务器配置
├── setup.ps1                # Windows 安装脚本
├── Install.cmd              # Windows 一键安装
├── requirements.txt
└── README.md
```

## 技术栈

| 类别 | 技术 |
|------|------|
| **GUI** | PySide6 |
| **SSH** | asyncssh / paramiko |
| **AI 协议** | MCP (Model Context Protocol) / FastMCP |
| **AI 后端** | 任意支持 MCP 的 Agent（Copilot / Claude / Codex / 自定义 Agent） |
| **LLM** | OpenAI 兼容 API（Function Calling） |
| **IPC** | 本地回环 JSON-RPC |
| **数据库** | SQLite |

## 配置

服务器配置位于 `config.yaml`：

```yaml
servers:
  my-server:
    host: 192.168.1.100
    port: 22
    user: root
    key_path: ~/.ssh/id_rsa

security:
  dangerous_commands:
    - rm -rf
    - format
  require_confirmation: true
```

## 开发

```bash
# 安装依赖
powershell -ExecutionPolicy Bypass -File .\setup.ps1

# 运行测试
python -m pytest tests/

# 启动 GUI
python -m app.main

# 启动 MCP Server
python -m app.main --mcp
```

## 许可证

[MIT](LICENSE)
