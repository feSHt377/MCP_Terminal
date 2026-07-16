# 🎯 FPS Tactical MCP — Asynchronous Strategic Brain for Tactical FPS Bots

> **让大模型成为战场指挥官，而非前线士兵。** 基于 Model Context Protocol (MCP) 的异步战略决策架构，将 LLM 的宏观战术智慧注入 FPS 游戏 Bot，同时彻底规避实时推理带来的帧率灾难。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/Protocol-MCP-orange)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://python.org)
[![Status](https://img.shields.io/badge/Status-Prototype-yellow)]()

---

## 📖 Table of Contents

- [Why This?](#-why-this)
- [Architecture](#-architecture)
- [MCP Primitives](#-mcp-primitives)
- [Quick Start](#-quick-start)
- [Roadmap](#-roadmap)
- [Disclaimer](#-disclaimer)

---

## 💡 Why This?

### 三种 AI 控制方案的终极对比

| 维度 | 🤖 传统硬编码 AI | ⚡ 实时 LLM 控制 | 🧠 **本项目 MCP 异步大脑** |
|------|:--:|:--:|:--:|
| **决策灵活性** | ❌ 行为树/状态机，死板 | ✅ 极强 | ✅ 极强 |
| **响应延迟** | ✅ < 1ms | ❌ 200-2000ms（致命） | ✅ 500-2000ms（仅战略层） |
| **显存占用** | ✅ 极低 | ❌ 挤爆 GPU，帧率暴跌 | ⚠️ 低频调用，GPU 竞争可控（优化中 → CPU 量化） |
| **战场感知深度** | ❌ 仅传感器触发 | ✅ 全量上下文 | ✅ 全量上下文 |
| **微操精度** | ✅ 硬编码精准 | ❌ LLM 无法控制毫秒级输入 | ✅ 引擎层独立处理 |
| **开发成本** | 高（每场景重写） | 中 | **低（MCP 协议标准化）** |

### 核心痛点与解决思路

```
┌─────────────────────────────────────────────────────────────────────────┐
│  痛点 1: 让 LLM 控制每帧的瞄准/射击 → 网络时延 + 推理延迟 = 灾难        │
│  解决:   LLM 只输出战略标签 (Flank/Suppress/Retreat)，不碰微操          │
│                                               │
│  痛点 2: GPU 跑推理 → 游戏掉帧、显存 OOM        │
│  解决:   本地 CPU 异步推理 (Qwen2.5-0.5B 量化)，与游戏进程完全隔离      │
│                                               │
│  痛点 3: 游戏引擎与 AI 服务耦合严重             │
│  解决:   MCP 协议标准化通信，引擎只关心 JSON，不关心后端是哪个模型       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Architecture

### 三角架构：Game Engine ↔ MCP Server ↔ LLM Client

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          FPS Tactical MCP Architecture                       │
│                                                                              │
│   ┌─────────────────────┐      MCP Protocol       ┌───────────────────────┐  │
│   │   Game Engine       │◄──── (JSON-RPC 2.0) ───►│   MCP Server          │  │
│   │   (Unity/Unreal)    │      Stdio / SSE        │   (Python / FastMCP)  │  │
│   │                     │                          │                       │  │
│   │  ┌───────────────┐  │                          │  ┌─────────────────┐  │  │
│   │  │ High-Freq     │  │  Read Resources          │  │ Tool Registry   │  │  │
│   │  │ Loop (0-20ms) │  │─────────────────────────►│  │                 │  │  │
│   │  │               │  │                          │  │ • save_battle   │  │  │
│   │  │ • Pathfinding │  │  Call Tools              │  │ • query_logs    │  │  │
│   │  │ • Recoil Ctrl │  │◄─────────────────────────│  │ • get_tactics   │  │  │
│   │  │ • Fire Control│  │  Strategic Tags          │  │ • calculate     │  │  │
│   │  └───────────────┘  │                          │  │ • show_popup    │  │  │
│   │                     │                          │  └─────────────────┘  │  │
│   │  ┌───────────────┐  │                          │                       │  │
│   │  │ Low-Freq      │  │  Write Resources         │  ┌─────────────────┐  │  │
│   │  │ Loop (500-2s) │  │◄─────────────────────────│  │ LLM Client      │  │  │
│   │  │               │  │                          │  │                 │  │  │
│   │  │ • Battle Snap │  │  Receive Strategy        │  │ • Ollama Local  │  │  │
│   │  │ • Decision    │  │─────────────────────────►│  │ • Qwen2.5-0.5B  │  │  │
│   │  │   Execution   │  │                          │  │ • CPU Inference │  │  │
│   │  └───────────────┘  │                          │  └─────────────────┘  │  │
│   └─────────────────────┘                          └───────────────────────┘  │
│                                                                              │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                     Data Flow Summary                                │   │
│   │                                                                      │   │
│   │   ① Engine 每 500-2000ms 推送战场快照 → MCP Server (Resource)       │   │
│   │   ② MCP Server 组装上下文 → 发送给 LLM Client                        │   │
│   │   ③ LLM 分析局势 → 调用 MCP Tools 返回战略标签                       │   │
│   │   ④ MCP Server 将战略标签写回 → Engine 执行层翻译为具体行为           │   │
│   │                                                                      │   │
│   │   ⚡ 全程异步，不阻塞游戏主线程，不占用 GPU 显存                       │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 频率分层设计

| 层级 | 频率 | 延迟预算 | 负责方 | 任务 |
|------|------|---------|--------|------|
| **微操层** | 50-1000 Hz | < 20ms | Game Engine | 寻路、控枪、开火、动画混合 |
| **战术层** | 0.5-2 Hz | 500-2000ms | LLM via MCP | 绕后/压制/撤退/集火决策 |
| **战略层** | 0.1-0.5 Hz | 2-5s | LLM via MCP | 资源分配、目标优先级、阵型变换 |

---

## 🔧 MCP Primitives

### Tools 设计

```typescript
// MCP Tool 定义 (简化版)

interface BattleSnapshot {
  timestamp: string;           // ISO 8601
  team: "alpha" | "bravo";
  players: PlayerState[];
  enemies: EnemyState[];
  audio_clues: AudioClue[];    // 脚步声、枪声方向
  map_state: MapState;
}

interface PlayerState {
  id: string;
  position: { x: number; y: number; z: number };
  health: number;             // 0-100
  ammo: number;
  weapon: string;
  last_fire_time: string;
  is_prone: boolean;
}

interface EnemyState {
  id: string;
  position: { x: number; y: number; z: number };
  estimated_health: number;
  last_seen: string;
  threat_level: "low" | "medium" | "high";
}

interface AudioClue {
  type: "footstep" | "gunshot" | "reload" | "voice";
  direction: { x: number; y: number; z: number };
  distance: number;           // meters
  timestamp: string;
  confidence: number;         // 0.0-1.0
}
```

### Resources 设计

```
mcp://fps-tactical/battle/snapshot      # 实时战场快照 (JSON)
mcp://fps-tactical/battle/history       # 最近 N 轮决策历史
mcp://fps-tactical/audio/clues         # 音频线索流
mcp://fps-tactical/map/heatmap         # 敌方热力图
mcp://fps-tactical/strategy/current    # 当前执行中的战略
```

### JSON-RPC 2.0 通信示例

```jsonc
// ① Engine → MCP Server: 推送战场快照 (Resource Write)
{
  "jsonrpc": "2.0",
  "method": "resources/update",
  "params": {
    "uri": "mcp://fps-tactical/battle/snapshot",
    "value": {
      "timestamp": "2026-06-07T14:32:15.123Z",
      "team": "alpha",
      "players": [
        {
          "id": "bot_01",
          "position": { "x": 124.5, "y": 3.2, "z": -89.1 },
          "health": 78,
          "ammo": 24,
          "weapon": "AK-47",
          "last_fire_time": "2026-06-07T14:32:14.890Z",
          "is_prone": false
        }
      ],
      "enemies": [
        {
          "id": "enemy_03",
          "position": { "x": 156.2, "y": 1.0, "z": -45.7 },
          "estimated_health": 45,
          "last_seen": "2026-06-07T14:32:12.000Z",
          "threat_level": "high"
        }
      ],
      "audio_clues": [
        {
          "type": "footstep",
          "direction": { "x": 0.82, "y": 0.0, "z": -0.57 },
          "distance": 23.5,
          "timestamp": "2026-06-07T14:32:14.950Z",
          "confidence": 0.87
        }
      ]
    }
  }
}

// ② LLM → MCP Server: 调用工具返回战略决策 (Tool Call)
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "get_tactical_decision",
    "arguments": {
      "snapshot_id": "snap_20260607_143215",
      "decision": {
        "primary": "FLANK",
        "secondary": "SUPPRESS",
        "target_enemy": "enemy_03",
        "flank_direction": "east",
        "confidence": 0.92,
        "reasoning": "敌方 bot_03 血量偏低且最后出现位置偏西，\n东侧有掩体可利用，建议绕后同时压制正面"
      }
    }
  }
}

// ③ MCP Server → Engine: 返回战略标签 (Tool Result)
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "status": "success",
    "strategy": {
      "tag": "FLANK+EAST",
      "priority": "high",
      "execution_hint": "利用东侧废墟掩体，接近至 15m 内开火"
    }
  }
}
```

---

## 🚀 Quick Start

### 环境要求

- **Python** 3.10+
- **Ollama** (本地模型推理)
- **Unity/Unreal** (游戏引擎，可选)

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/fps-tactical-mcp.git
cd fps-tactical-mcp

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动 MCP 服务器
python mcp_server.py

# 4. 配置 VS Code Copilot (可选)
# 在 .vscode/settings.json 中添加 MCP 服务器配置
```

### 测试

```bash
# 运行 Function Calling 测试套件
python test_function_calling.py

# 自定义测试
python test_function_calling.py -p "分析当前战场局势，给出战术建议"
```

---

## 🗺️ Roadmap

### Phase 1: 本地 Demo 验证 ✅

- [x] MCP 服务器基础框架
- [x] 工具注册中心 (Tool Registry)
- [x] Function Calling 测试脚本
- [x] 本地 Ollama 模型对接
- [ ] 模拟战场数据生成器
- [ ] 战略标签 → 行为映射表

### Phase 2: 端云协同混合架构 🔄

- [ ] Unity 引擎插件开发 (C# MCP Client)
- [ ] 战场快照采集模块 (位置/血量/音频)
- [ ] 异步决策管道 (Async Decision Pipeline)
- [ ] 云端大模型 fallback (API 降级策略)
- [ ] 决策缓存与热更新

### Phase 3: 多模态音频线索解析 🔮

- [ ] 音频特征提取 (Wav2Vec2 / Whisper)
- [ ] 枪声类型识别 (AK/M4/狙击)
- [ ] 脚步声方向三角定位
- [ ] 语音指令解析 (队友喊话)
- [ ] 多模态融合决策 (视觉 + 听觉 + 地图)

### Phase 4: 群体智能与自进化 🌟

- [ ] 多 Bot 协同战术 (Swarm Intelligence)
- [ ] 在线学习 (Online Learning from Gameplay)
- [ ] 对手行为模式建模
- [ ] 自适应难度调节
- [ ] 可视化战术分析面板

---

## ⚠️ Disclaimer

### 严正声明

> **本项目专注于独立游戏开发与 AI Agent 落地实验，谢绝用于任何网游的外挂/作弊器开发。**

1. **合法用途**：本项目仅用于单机游戏、独立游戏、AI 研究及学术实验。
2. **禁止用途**：严禁将本项目或其衍生代码用于任何在线多人游戏的作弊、外挂、自动化脚本等违反游戏服务条款的行为。
3. **责任自负**：使用者需自行承担因不当使用本项目而产生的任何法律后果。
4. **开源协议**：本项目采用 MIT License，但上述使用限制优先于 License 条款。

**We build AI for creativity, not for cheating.** 🎮

---

## 📄 License

[MIT License](LICENSE) — Copyright (c) 2026

---

## 🤝 Contributing

欢迎提交 Issue 和 Pull Request。在提交 PR 之前，请确保：

1. 代码通过所有测试 (`python test_function_calling.py`)
2. 遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范
3. 更新相关文档

---

<div align="center">

**Built with 🧠 by FPS Tactical MCP Team**

*让 AI 思考，让引擎执行。*

</div>

```
==================================================
开始 Function Calling 测试
==================================================

测试 1/5: 测试保存用户输入
✅ 模型决定调用 1 个工具
   调用工具: save_data_to_log
   参数: {"category": "user_action", "data": {...}, "priority": "high"}
   ✅ 工具执行成功

测试汇总:
  总测试数: 5
  工具调用总数: 5
  成功调用数: 5
  成功率: 100.0%
```
