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

from app.ui.theme import current as theme_current


class StatusPanel(QWidget):
    """右侧状态面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusPanel")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ---- 日志区域 ----
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setFrameStyle(QFrame.NoFrame)
        self.log_view.setFont(QFont("Consolas, monospace", 9))
        layout.addWidget(self.log_view, stretch=1)

        # ---- 统计 ----
        self.stats_label = QLabel("  会话: 0  |  命令: 0")
        self.stats_label.setObjectName("statsLabel")
        layout.addWidget(self.stats_label)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def log_connect(self, session_id: str, host: str):
        """记录连接事件。"""
        self._append(f"[{self._now()}] 🔌 连接 {session_id}\n", theme_current().success)

    def log_disconnect(self, session_id: str):
        """记录断开事件。"""
        self._append(f"[{self._now()}] ⏹ 断开 {session_id}\n", theme_current().warning)

    def log_command(self, command: str, exit_code: int | None = None):
        """记录命令执行。"""
        status = f"exit={exit_code}" if exit_code is not None else "?"
        self._append(f"[{self._now()}] $ {command.strip()}  ({status})\n", theme_current().info)

    def log_tool_call(self, tool: str, status: str):
        """记录 MCP 工具调用。"""
        colors = {
            "success": theme_current().success,
            "running": theme_current().info,
            "exec": theme_current().info,
            "queued": theme_current().warning,
            "error": theme_current().danger,
        }
        color = colors.get(status, theme_current().warning)
        self._append(f"[{self._now()}] MCP:{tool} → {status}\n", color)

    def log_error(self, message: str):
        """记录错误。"""
        self._append(f"[{self._now()}] ❌ {message}\n", theme_current().danger)

    def update_stats(self, sessions: int, commands: int):
        """更新统计信息。"""
        self.stats_label.setText(f"  会话: {sessions}  |  命令: {commands}")

    def clear_logs(self):
        """清空当前窗口中的操作日志，不删除磁盘审计日志。"""
        self.log_view.clear()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _append(self, text: str, color: str):
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
