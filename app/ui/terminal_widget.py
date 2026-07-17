"""终端组件 — 输出显示 + 命令输入。

人工通过此组件直接操作远程服务器，不经过 MCP 协议。
"""  # noqa: D205

from collections import deque

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class TerminalWidget(QWidget):
    """SSH 终端组件：输出区域 + 命令输入行。

    通过 SSHBridge 持久化事件循环执行所有 SSH 操作。
    """

    command_executed = Signal(str, object)  # (command, result_dict)
    MAX_AGENT_QUEUE = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session_id: str | None = None
        self._history: list[str] = []
        self._history_index: int = -1
        self._busy = False
        self._result_callback = None
        self._active_command = ""
        self._pending_commands = deque()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- 输出区域 ----
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFrameStyle(QFrame.NoFrame)

        mono = QFont("Consolas", 10)
        mono.setStyleHint(QFont.Monospace)
        self.output.setFont(mono)

        self.output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                selection-background-color: #264f78;
                border: none;
                padding: 4px;
            }
        """)
        layout.addWidget(self.output, stretch=1)

        # ---- 输入行 ----
        input_frame = QFrame()
        input_frame.setFrameStyle(QFrame.NoFrame)
        input_frame.setStyleSheet(
            "QFrame { background-color: #252526; border-top: 1px solid #3c3c3c; }"
        )
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(8, 4, 8, 4)

        self.prompt_label = QLineEdit()
        self.prompt_label.setReadOnly(True)
        self.prompt_label.setFrame(False)
        self.prompt_label.setFixedWidth(200)
        self.prompt_label.setStyleSheet(
            "color: #6a9955; background: transparent; font-weight: bold;"
        )

        self.input = QLineEdit()
        self.input.setFrame(False)
        self.input.setPlaceholderText("输入命令后按 Enter 执行…")
        self.input.setStyleSheet("""
            QLineEdit {
                color: #d4d4d4;
                background: transparent;
                font-family: 'Consolas', monospace;
                font-size: 12px;
                border: none;
            }
        """)
        self.input.returnPressed.connect(self._on_send)

        input_layout.addWidget(self.prompt_label)
        input_layout.addWidget(self.input)
        layout.addWidget(input_frame)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def set_session(self, session_id: str | None, user: str = "", host: str = ""):
        """绑定/解绑 SSH 会话。"""
        self._session_id = session_id
        if session_id:
            self.prompt_label.setText(f" {user}@{host} $")
            self.input.setEnabled(True)
            self.input.setFocus()
            self._append_output(f"--- 已连接 {session_id} ---\n", "#6a9955")
        else:
            self.prompt_label.setText(" 未连接")
            self.input.setEnabled(False)
            self._append_output("--- 已断开 ---\n", "#6a9955")

    def append_line(self, text: str, color: str = "#d4d4d4"):
        """向输出区追加一行（供外部调用）。"""
        self._append_output(text, color)

    def execute_command(
        self, cmd: str, on_done=None, source: str = "Agent", timeout: float = 30.0
    ):
        """代理：将命令注入输入框并立即执行。Agent 通过此方法操作用户的主终端。"""
        return self._execute(cmd, on_done=on_done, source=source, timeout=timeout)

    def set_input_text(self, text: str):
        """补全：将命令填入输入框但不执行。用户可修改后手动 Enter。"""
        self.input.setText(text)
        self.input.setFocus()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _on_send(self):
        text = self.input.text()
        if not text.strip():
            return

        self._execute(text, source="Human")

    def _execute(
        self, text: str, on_done=None, source: str = "Human", timeout: float = 30.0
    ):
        sid = self._session_id
        if not sid:
            self._append_output("⚠ 未连接到任何服务器\n", "#ce9178")
            if on_done:
                on_done({"status": "error", "message": "GUI 当前没有 SSH 会话"})
            return {"status": "error", "message": "GUI 当前没有 SSH 会话"}

        if self._busy:
            if source != "Agent":
                result = {"status": "error", "message": "当前终端正在执行 Agent 命令"}
                if on_done:
                    on_done(result)
                return result
            if len(self._pending_commands) >= self.MAX_AGENT_QUEUE:
                result = {
                    "status": "error",
                    "message": f"Agent 命令队列已满（最多 {self.MAX_AGENT_QUEUE} 条）",
                }
                if on_done:
                    on_done(result)
                return result
            self._pending_commands.append((text, on_done, source, timeout, sid))
            position = len(self._pending_commands)
            self._append_output(f"⏳ [Agent 排队 #{position}] {text}\n", "#dcdcaa")
            return {"status": "queued", "position": position}

        self._start_execute(text, on_done, source, timeout, sid)
        return {"status": "running"}

    def _start_execute(self, text, on_done, source, timeout, sid):
        """实际启动一条命令；调用方必须确保当前没有活动命令。"""

        # 历史记录
        self._history.append(text)
        self._history_index = len(self._history)

        # 回显命令
        suffix = "  [Agent]" if source == "Agent" else ""
        self._append_output(f"$ {text}{suffix}\n", "#4fc1ff" if suffix else "#569cd6")
        self.input.clear()
        self.input.setEnabled(False)
        self._busy = True
        self._result_callback = on_done
        self._active_command = text

        # 通过 SSHBridge 异步执行（同一 event loop）
        from app.ssh.manager import SSHManager
        from app.ssh.bridge import SSHBridge

        manager = SSHManager()

        async def _exec():
            return await manager.exec_command(sid, text, timeout=timeout)

        SSHBridge().submit_async(_exec(), self._on_result)

    def _on_result(self, result: dict):
        self._busy = False

        if result["status"] == "success":
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            if stdout:
                self._append_output(stdout, "#d4d4d4")
            if stderr:
                self._append_output(stderr, "#ce9178")
        else:
            self._append_output(f"❌ {result['message']}\n", "#f44747")

        callback = self._result_callback
        command = self._active_command
        self._result_callback = None
        self._active_command = ""
        if callback:
            callback(result)
        self.command_executed.emit(command, result)

        if self._pending_commands:
            QTimer.singleShot(0, self._run_next)
        else:
            self.input.setEnabled(True)
            self.input.setFocus()

    def _run_next(self):
        if self._busy:
            return
        while self._pending_commands:
            text, on_done, source, timeout, sid = self._pending_commands.popleft()
            if sid != self._session_id:
                result = {"status": "error", "message": f"排队期间当前会话已切换: {sid}"}
                if on_done:
                    on_done(result)
                continue
            self._start_execute(text, on_done, source, timeout, sid)
            return
        self.input.setEnabled(True)
        self.input.setFocus()

    def _append_output(self, text: str, color: str = "#d4d4d4"):
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def keyPressEvent(self, event):
        """键盘事件：上下箭头浏览历史。"""
        if event.key() == Qt.Key_Up:
            if self._history and self._history_index > 0:
                self._history_index -= 1
                self.input.setText(self._history[self._history_index])
            return
        if event.key() == Qt.Key_Down:
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                self.input.setText(self._history[self._history_index])
            else:
                self._history_index = len(self._history)
                self.input.clear()
            return
        super().keyPressEvent(event)
