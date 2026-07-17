"""MCP 工具链测试窗口 — 模拟外部 Agent 调用 MCP 工具的两种路径。

路径 1 — 代理 (proxy): Agent 将命令注入主终端 SSH 输入框并自动执行
路径 2 — 补全 (autocomplete): Agent 将命令填入主终端输入框，由用户决定是否执行
"""  # noqa: D205

import asyncio

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QColor, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QVBoxLayout,
)


class _AgentWorker(QThread):
    """在独立线程运行 Agent，避免占用唯一 SSHBridge 事件循环。"""

    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, prompt: str, session_id: str | None, parent=None):
        super().__init__(parent)
        self._prompt = prompt
        self._session_id = session_id

    def run(self):
        try:
            from app.agent.agent_loop import run_agent

            result = asyncio.run(run_agent(prompt=self._prompt, session_id=self._session_id))
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ChatWindow(QDialog):
    """MCP 工具链测试窗口。

    信号:
        proxy_command_requested(str)  → 代理：命令注入主终端立即执行
        autocomplete_requested(str)   → 补全：命令填入主终端，用户手动确认
    """

    proxy_command_requested = Signal(str)
    autocomplete_requested = Signal(str)

    def __init__(self, session_id=None, bridge=None, parent=None):
        super().__init__(parent)
        self._session_id = session_id
        self._bridge = bridge
        self._last_cmd = ""

        self.setWindowTitle("MCP 工具链测试 — Agent 模拟")
        self.resize(750, 650)
        self.setMinimumSize(550, 450)
        self._setup_ui()

        if session_id:
            self._add_message("system", f"已连接 {session_id}，输入指令测试 MCP 工具链")
        else:
            self._add_message("system", "未连接（请先在主窗口连接服务器）")

    def set_session(self, session_id):
        self._session_id = session_id
        if session_id:
            self._add_message("system", f"会话切换: {session_id}")

    # ==================================================================
    # UI
    # ==================================================================

    def _setup_ui(self):
        self.setStyleSheet("QDialog { background-color: #1e1e1e; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        hdr = QFrame()
        hdr.setFixedHeight(40)
        hdr.setStyleSheet("background:#2d2d30; border-bottom:1px solid #3c3c3c;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 6, 12, 6)
        t = QLabel("MCP 工具链测试 — Agent 模拟")
        t.setFont(QFont("", 10, QFont.Bold))
        t.setStyleSheet("color:#ccc; background:transparent;")
        hl.addWidget(t, 1)
        self.mode_lbl = QLabel("(模拟)")
        self.mode_lbl.setStyleSheet("color:#808080; font-size:10px; background:transparent;")
        hl.addWidget(self.mode_lbl)
        layout.addWidget(hdr)

        # 消息区
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setFrameStyle(QFrame.NoFrame)
        self.chat.setFont(QFont("Consolas", 10))
        self.chat.setStyleSheet(
            "QTextEdit{background:#1e1e1e;color:#d4d4d4;border:none;padding:8px;}"
            "QScrollBar:vertical{background:#2d2d30;width:10px;}"
            "QScrollBar::handle:vertical{background:#555;border-radius:5px;}"
        )
        layout.addWidget(self.chat, 1)

        # 输入栏
        inf = QFrame()
        inf.setFixedHeight(48)
        inf.setStyleSheet("background:#2d2d30; border-top:1px solid #3c3c3c;")
        il = QHBoxLayout(inf)
        il.setContentsMargins(10, 6, 10, 6)
        il.setSpacing(6)

        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("输入: 检查GPU / 磁盘 / docker / lxc / 进程…")
        self.msg_input.setStyleSheet(
            "QLineEdit{background:#3c3c3c;color:#d4d4d4;border:1px solid #555;"
            "border-radius:4px;padding:6px 10px;font-size:12px;}"
        )
        self.msg_input.returnPressed.connect(self._on_send)
        il.addWidget(self.msg_input, 1)

        btn_css = (
            "QPushButton{color:white;border:none;border-radius:4px;"
            "padding:6px;font-size:11px;}"
            "QPushButton:disabled{background:#555;color:#888;}"
        )

        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedWidth(50)
        self.send_btn.setStyleSheet(btn_css + "QPushButton{background:#0e639c;} QPushButton:hover{background:#1177bb;}")
        self.send_btn.clicked.connect(self._on_send)
        il.addWidget(self.send_btn)

        self.proxy_btn = QPushButton("代理")
        self.proxy_btn.setFixedWidth(50)
        self.proxy_btn.setToolTip("命令注入主终端并执行")
        self.proxy_btn.setEnabled(False)
        self.proxy_btn.setStyleSheet(btn_css + "QPushButton{background:#6a9955;} QPushButton:hover{background:#7eb356;}")
        self.proxy_btn.clicked.connect(self._on_proxy)
        il.addWidget(self.proxy_btn)

        self.ac_btn = QPushButton("补全")
        self.ac_btn.setFixedWidth(50)
        self.ac_btn.setToolTip("命令填入主终端，不自动执行")
        self.ac_btn.setEnabled(False)
        self.ac_btn.setStyleSheet(btn_css + "QPushButton{background:#ce9178;} QPushButton:hover{background:#d4a58a;}")
        self.ac_btn.clicked.connect(self._on_autocomplete)
        il.addWidget(self.ac_btn)

        layout.addWidget(inf)

        # LLM 检测
        from app.agent.llm_client import create_client_from_config
        if create_client_from_config() is not None:
            self.mode_lbl.setText("(LLM)")
            self.mode_lbl.setStyleSheet("color:#6a9955;font-size:10px;background:transparent;")

    # ==================================================================
    # 消息
    # ==================================================================

    def _add_message(self, role, text):
        c = self.chat.textCursor()
        c.movePosition(QTextCursor.End)
        colors = {"user": "#569cd6", "agent": "#4fc1ff", "tool": "#ce9178",
                   "result": "#6a9955", "system": "#808080", "error": "#f44747"}
        prefixes = {"user": "你", "agent": "Agent", "tool": "工具",
                     "result": "", "system": "info", "error": "ERR"}
        color = colors.get(role, "#d4d4d4")
        prefix = prefixes.get(role, "")
        fmt = c.charFormat()
        fmt.setForeground(QColor(color))
        c.setCharFormat(fmt)
        if prefix:
            c.insertText(f"[{prefix}] ")
        c.insertText(text + "\n")
        self.chat.setTextCursor(c)
        self.chat.ensureCursorVisible()

    def _sep(self):
        c = self.chat.textCursor()
        c.movePosition(QTextCursor.End)
        c.insertText("-" * 50 + "\n")

    # ==================================================================
    # 发送
    # ==================================================================

    def _on_send(self):
        text = self.msg_input.text().strip()
        if not text:
            return

        self._add_message("user", text)
        self.msg_input.clear()
        self.msg_input.setEnabled(False)
        self.send_btn.setEnabled(False)

        def _on_done(results):
            self.msg_input.setEnabled(True)
            self.send_btn.setEnabled(True)
            self.msg_input.setFocus()

            if not results:
                self._add_message("system",
                    "未识别。试试: GPU 磁盘 docker lxc 进程 系统 网络")
                return

            for item in results:
                tool = item["tool"]
                args = item["args"]
                result = item["result"]
                s = result.get("status", "?")

                if tool == "ssh_exec":
                    cmd = args.get("command", "")
                    if not cmd:
                        continue
                    self._last_cmd = cmd
                    self.proxy_btn.setEnabled(True)
                    self.ac_btn.setEnabled(True)

                    self._add_message("tool", f"ssh_exec: {cmd} -> {s}")
                    if s == "success":
                        out = result.get("stdout", "").strip()
                        if out:
                            for line in out.splitlines()[:20]:
                                self._add_message("result", line)
                    else:
                        self._add_message("error", result.get("message", ""))

                elif tool in ("list_servers", "list_sessions", "get_dangerous_commands",
                              "add_server", "remove_server"):
                    import json
                    self._add_message("tool", f"{tool} -> {s}")
                    self._add_message("result",
                        json.dumps(result, ensure_ascii=False, indent=2))
                else:
                    self._add_message("tool", f"{tool} -> {s}")

            self._sep()

        def _on_error(message):
            self._add_message("error", message)
            self.msg_input.setEnabled(True)
            self.send_btn.setEnabled(True)

        self._agent_worker = _AgentWorker(text, self._session_id, self)
        self._agent_worker.completed.connect(_on_done)
        self._agent_worker.failed.connect(_on_error)
        self._agent_worker.start()

    # ==================================================================
    # 代理 / 补全
    # ==================================================================

    def _on_proxy(self):
        if self._last_cmd:
            self.proxy_command_requested.emit(self._last_cmd)
            self._add_message("agent", f"代理执行: {self._last_cmd}")

    def _on_autocomplete(self):
        if self._last_cmd:
            self.autocomplete_requested.emit(self._last_cmd)
            self._add_message("agent", f"补全填入: {self._last_cmd}")
