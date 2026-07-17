"""状态面板 — 右侧栏，显示 MCP 工具调用日志和系统状态。"""  # noqa: D205

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class StatusPanel(QWidget):
    """右侧状态面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        self.setStyleSheet("background:#0d1117;")

        # ---- 标题 ----
        title = QLabel("  📋 操作日志")
        title.setFont(QFont("", 11, QFont.Bold))
        title.setStyleSheet("color:#e6edf3;padding:6px 2px;font-weight:600;")
        layout.addWidget(title)

        # ---- 日志区域 ----
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFrameStyle(QFrame.NoFrame)
        self.log_view.setFont(QFont("Consolas, monospace", 9))
        self.log_view.setStyleSheet("""
            QPlainTextEdit {
                background:#010409;
                color:#c9d1d9;
                border:1px solid #30363d;
                border-radius:8px;
                padding:8px;
            }
        """)
        layout.addWidget(self.log_view, stretch=1)

        # ---- 统计 ----
        self.stats_label = QLabel("  会话: 0  |  命令: 0")
        self.stats_label.setStyleSheet("color:#8b949e;font-size:11px;padding:4px 2px;")
        layout.addWidget(self.stats_label)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def log_connect(self, session_id: str, host: str):
        """记录连接事件。"""
        self._append(f"[{self._now()}] 🔌 连接 {session_id}\n", "#6a9955")

    def log_disconnect(self, session_id: str):
        """记录断开事件。"""
        self._append(f"[{self._now()}] ⏹ 断开 {session_id}\n", "#ce9178")

    def log_command(self, command: str, exit_code: int | None = None):
        """记录命令执行。"""
        status = f"exit={exit_code}" if exit_code is not None else "?"
        self._append(f"[{self._now()}] $ {command.strip()}  ({status})\n", "#569cd6")

    def log_tool_call(self, tool: str, status: str):
        """记录 MCP 工具调用。"""
        colors = {
            "success": "#6a9955",
            "running": "#4fc1ff",
            "exec": "#4fc1ff",
            "queued": "#dcdcaa",
            "error": "#f44747",
        }
        color = colors.get(status, "#ce9178")
        self._append(f"[{self._now()}] MCP:{tool} → {status}\n", color)

    def log_error(self, message: str):
        """记录错误。"""
        self._append(f"[{self._now()}] ❌ {message}\n", "#f44747")

    def update_stats(self, sessions: int, commands: int):
        """更新统计信息。"""
        self.stats_label.setText(f"  会话: {sessions}  |  命令: {commands}")

    def clear_logs(self):
        """清空当前窗口中的操作日志，不删除磁盘审计日志。"""
        self.log_view.clear()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _append(self, text: str, color: str = "#d4d4d4"):
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def _now(self) -> str:
        return datetime.now().strftime("%H:%M:%S")
