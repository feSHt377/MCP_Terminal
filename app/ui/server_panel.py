"""服务器列表面板 — 左侧栏，显示已配置的服务器及连接状态。"""  # noqa: D205

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ServerPanel(QWidget):
    """左侧服务器面板。"""

    connect_requested = Signal(dict)  # server info dict
    disconnect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_name: str | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        self.setStyleSheet("background:#0d1117;")

        # ---- 标题 ----
        title = QLabel("  🖥  服务器")
        title.setFont(QFont("", 11, QFont.Bold))
        title.setStyleSheet("color:#e6edf3;padding:6px 2px;font-weight:600;")
        layout.addWidget(title)

        # ---- 列表 ----
        self.list_widget = QListWidget()
        self.list_widget.setFrameStyle(QFrame.NoFrame)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background:#010409;
                color:#c9d1d9;
                border:1px solid #30363d;
                border-radius:8px;
                font-size: 12px;
            }
            QListWidget::item {
                padding:10px;
                margin:3px;
                border-radius:6px;
            }
            QListWidget::item:selected {
                background:#1f6feb;
                color:#ffffff;
            }
            QListWidget::item:hover {
                background:#21262d;
            }
        """)
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.list_widget, stretch=1)

        # ---- 按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self.connect_btn = QPushButton("🔌 连接")
        self.connect_btn.setStyleSheet(self._btn_style())
        self.connect_btn.clicked.connect(self._on_connect)
        btn_layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("⏹ 断开")
        self.disconnect_btn.setStyleSheet(self._btn_style())
        self.disconnect_btn.clicked.connect(self._on_disconnect)
        self.disconnect_btn.setEnabled(False)
        btn_layout.addWidget(self.disconnect_btn)

        layout.addLayout(btn_layout)

        # ---- 状态 ----
        self.status_label = QLabel("  未连接")
        self.status_label.setStyleSheet("color:#8b949e;font-size:11px;padding:4px 2px;")
        layout.addWidget(self.status_label)

    def load_servers(self, servers: dict):
        """从配置加载服务器列表。"""
        self.list_widget.clear()
        for name, info in servers.items():
            item = QListWidgetItem(f"  {name}\n  {info['user']}@{info['host']}:{info.get('port', 22)}")
            item.setData(Qt.UserRole, name)
            self.list_widget.addItem(item)

    def set_connected(self, name: str, session_id: str):
        """标记为已连接状态。"""
        self._current_name = name
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.status_label.setText(f"  ✅ 已连接: {session_id}")
        self.status_label.setStyleSheet("color:#7ee787;font-size:11px;padding:4px 2px;")

    def set_disconnected(self):
        """标记为已断开。"""
        self._current_name = None
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.status_label.setText("  未连接")
        self.status_label.setStyleSheet("color:#8b949e;font-size:11px;padding:4px 2px;")

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def _on_connect(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        name = item.data(Qt.UserRole)
        from app.config.manager import get_servers
        servers = get_servers()
        info = dict(servers.get(name, {}))
        info["_name"] = name
        self.connect_requested.emit(info)

    def _on_double_click(self, item):
        self._on_connect()

    def _on_disconnect(self):
        self.disconnect_requested.emit()

    # ------------------------------------------------------------------
    # 样式
    # ------------------------------------------------------------------

    def _btn_style(self) -> str:
        return """
            QPushButton {
                background:#238636;
                color:#ffffff;
                border:1px solid #2ea043;
                padding:7px 12px;
                font-size: 12px;
                border-radius:6px;
            }
            QPushButton:hover {
                background:#2ea043;
            }
            QPushButton:disabled {
                background:#21262d;
                color:#8b949e;
                border-color:#30363d;
            }
        """
