# mcpterminal — MCP 远程终端 / AI Agent 执行基础设施

> 项目定位：为 AI Agent 提供可靠的远程服务器执行环境。
> 本项目是 Agent 的"手和脚"（工具 + 执行），不是"大脑"（推理 + 规划）。
> AI 通过 MCP 协议调用本项目的工具来操作远程服务器，人可以实时观察、干预、接管。

---

## MVP 版本目标（第一版）

- [x] Windows GUI — 人工操作界面
- [x] SSH 连接 — 多服务器会话管理
- [x] 实时 Terminal — 人工/AI 共享当前 GUI 会话
- [x] MCP Server — 暴露 SSH 工具给 AI
- [x] 人工接管 — 代理执行与命令补全
- [ ] 命令确认 — 危险命令拦截

---

## Phase 0：项目初始化

- [ ] 创建项目目录结构 `mcpterminal/`
- [ ] 创建 `requirements.txt`
- [ ] 创建 `README.md`
- [ ] 创建 `config.yaml`

---

## Phase 1：GUI 基础框架

> 技术：PySide6 + QML

- [ ] 安装 PySide6：`pip install PySide6`
- [ ] 创建主窗口 `app/main.py`
- [x] 添加暗色主题
- [x] 实现三栏布局：
  - [x] 左侧：服务器列表
  - [x] 中间：Terminal
  - [x] 右侧：AI / MCP 状态面板

---

## Phase 2：SSH 终端模块

> 技术：asyncssh / paramiko + PTY

- [ ] SSH 连接管理：`ssh user@host`
- [ ] 创建交互 Shell（`invoke_shell()`，非 `exec_command()`）
- [x] 实时输出（包括 `\r` 动态进度刷新）
- [x] 输入命令（Shell 主区域和底部输入栏）
- [x] Ctrl+C 支持
- [ ] 远程 Shell 原生 Tab 补全（当前活动交互程序可接收 Tab）

---

## Phase 3：终端 GUI 组件

> 优先：QTermWidget；备选：xterm.js + WebView

- [ ] 集成终端组件
- [x] 彩色状态输出与 ANSI 控制码兼容
- [x] 滚动
- [x] 复制粘贴
- [ ] 多标签

---

## Phase 4：MCP Server（核心）

> 技术：MCP Python SDK
>
> 将 SSH 终端能力封装为标准化 MCP 工具，供外部 AI Agent 调用。

- [x] `launch_gui` — 启动共享会话 GUI
- [x] MCP Server 与 GUI 的本地认证 IPC
- [x] `ssh_connect` — 在 GUI 中创建 SSH 会话
- [x] `ssh_exec` / `proxy_command` — 在当前 GUI 会话代理执行并显示结果
- [x] `autocomplete_command` — 填入 GUI 输入框，由用户确认
- [x] `list_sessions` / `select_session` — 查询全部 SSH 会话并切换 GUI 当前会话
- [x] `terminal_write` — 发送命令
- [x] `terminal_read` — 读取输出
- [x] `upload_file` — 上传文件
- [x] `download_file` — 下载文件

---

## Phase 5：接入 AI Agent（MCP Client）

> mcpterminal 作为 MCP Server，被 Codex CLI / Claude Code 等 AI Agent 作为工具集调用。

- [ ] 启动 MCP Server，注册工具
- [ ] 配置 AI Agent 连接 mcpterminal
- [ ] 端到端测试：
  - 用户：`检查4090 GPU状态`
  - AI 通过 MCP 调用 `terminal_write`
  - 执行 `nvidia-smi`
  - 返回结果给 AI

---

## Phase 6：AI 操作可视化

- [ ] **Tool Call Log** — 显示 AI 调用了哪些工具、参数、结果
- [ ] **命令确认弹窗** — 危险命令拦截：
  - [ ] `rm`
  - [ ] `shutdown`
  - [ ] `iptables`
  - [ ] `mkfs`
  - [ ] `fdisk`

---

## Phase 7：服务器管理

- [ ] 配置文件：`servers` 列表（ip/user）
- [ ] 添加服务器
- [ ] 删除服务器
- [ ] 测试连接
- [ ] 保存 SSH Key

---

## Phase 8：场景专用工具（Tool 生态）

> 把运维场景封装为结构化 MCP 工具，让 AI 能更好地理解和调用。

### LXD 管理
- [ ] `lxd_status()`
- [ ] `lxd_list()`
- [ ] `lxd_create()`
- [ ] `lxd_delete()`
- [ ] `lxd_gpu_check()`

### GPU 管理
- [ ] `gpu_status()` — `nvidia-smi`
- [ ] `gpu_process()`
- [ ] `gpu_memory()`

### Docker 管理
- [ ] `docker_ps()`
- [ ] `docker_logs()`
- [ ] `docker_restart()`

---

## Phase 9：执行基础设施增强

- [ ] **命令自动验证** — 执行后自动检查状态
  - 例：`systemctl restart docker` 后自动运行 `systemctl status docker`
- [ ] **会话持久化** — 保持 SSH 长连接
- [ ] **输出结构化** — 将命令输出解析为结构化数据

---

## Phase 10：安全系统

- [ ] **命令风险检测** — 三级：
  - [ ] LOW：查看状态
  - [ ] MEDIUM：修改配置
  - [ ] HIGH：删除/重启
- [ ] sudo 确认
- [ ] **操作日志** — 记录：时间/用户/AI/命令/结果

---

## Phase 11：打包发布

- [ ] PyInstaller 打包：`pyinstaller main.py`
- [ ] 配置文件外置
- [ ] 自动更新

---

## Phase 12（未来）：内置 Agent 层

> 从"纯工具平台"升级为"自带 Agent 的运维平台"。

- [ ] **Memory（SQLite）** — 保存：
  - [ ] 服务器信息
  - [ ] 历史故障
  - [ ] 常用命令
  - [ ] 用户偏好
- [ ] **任务规划器** — 自动分解运维任务步骤
- [ ] **反馈循环** — 执行→检查→修正的自主循环
- [ ] **多步推理** — 根据执行结果自动决定下一步

---

## 开发顺序

```
1. PySide6 GUI          ← 当前
2. SSH Terminal
3. MCP Server           ← 核心：暴露工具给 AI
4. 接入 Codex/Claude     ← 验证 AI 能调用工具
5. 场景专用工具          ← 丰富工具生态
6. 安全与可视化          ← 人工监督
7. (未来) Agent 层       ← 从工具平台升级为 Agent 平台
```
