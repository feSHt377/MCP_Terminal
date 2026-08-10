"""服务器列表面板 — 左侧栏，显示已配置的服务器及连接状态。"""  # noqa: D205

from PySide6.QtCore import Qt, Signal
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
        self.setObjectName("serverPanel")
        self._current_name: str | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ---- 列表 ----
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("serverList")
        self.list_widget.setFrameStyle(QFrame.NoFrame)
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.list_widget, stretch=1)

        # ---- 按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self.connect_btn = QPushButton("🔌 连接")
        self.connect_btn.setObjectName("connectBtn")
        self.connect_btn.clicked.connect(self._on_connect)
        btn_layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("⏹ 断开")
        self.disconnect_btn.setObjectName("disconnectBtn")
        self.disconnect_btn.clicked.connect(self._on_disconnect)
        self.disconnect_btn.setEnabled(False)
        btn_layout.addWidget(self.disconnect_btn)

        layout.addLayout(btn_layout)

        # ---- 状态 ----
        self.status_label = QLabel("  未连接")
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)

    def load_servers(self, servers: dict):
        """从配置加载服务器列表，跳过 hide: true 的服务器。"""
        self.list_widget.clear()
        for name, info in servers.items():
            if info.get("hide") is True:
                continue
            item = QListWidgetItem(f"  {name}\n  {info['user']}@{info['host']}:{info.get('port', 22)}")
            item.setData(Qt.UserRole, name)
            self.list_widget.addItem(item)

    def set_connected(self, name: str, session_id: str):
        """标记为已连接状态。"""
        self._current_name = name
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.status_label.setText(f"  ✅ 已连接: {session_id}")
        self._set_status_state("connected")

    def set_disconnected(self):
        """标记为已断开。"""
        self._current_name = None
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.status_label.setText("  未连接")
        self._set_status_state("idle")

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

    def _set_status_state(self, state: str):
        """通过动态属性切换状态配色，主题切换时自动生效。"""
        self.status_label.setProperty("state", state)
        style = self.status_label.style()
        if style is not None:
            style.unpolish(self.status_label)
            style.polish(self.status_label)
