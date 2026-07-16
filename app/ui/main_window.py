"""主窗口 — 三栏布局：服务器列表 | 终端 | 操作日志。"""  # noqa: D205

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow,
    QSplitter,
    QStatusBar,
)

from app.config.manager import get_servers
from app.ssh.bridge import SSHBridge
from app.ssh.manager import SSHManager
from app.ui.server_panel import ServerPanel
from app.ui.status_panel import StatusPanel
from app.ui.terminal_widget import TerminalWidget


class MainWindow(QMainWindow):
    """mcpterminal 主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("mcpterminal — MCP 远程终端")
        self.resize(1400, 850)
        self.setMinimumSize(900, 500)

        self._session_id: str | None = None
        self._cmd_count: int = 0

        self._setup_ui()
        self._setup_menu()
        self._load_servers()

        # 启动持久化 SSH 事件循环
        self._bridge = SSHBridge()
        self._bridge.start()

    # ------------------------------------------------------------------
    # UI 搭建
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QStatusBar {
                background-color: #007acc;
                color: white;
                font-size: 11px;
            }
        """)

        splitter = QSplitter(Qt.Horizontal)

        self.server_panel = ServerPanel()
        self.server_panel.connect_requested.connect(self._on_connect)
        self.server_panel.disconnect_requested.connect(self._on_disconnect)

        self.terminal = TerminalWidget()

        self.status_panel = StatusPanel()

        splitter.addWidget(self.server_panel)
        splitter.addWidget(self.terminal)
        splitter.addWidget(self.status_panel)
        splitter.setSizes([220, 780, 400])
        splitter.setHandleWidth(2)

        self.setCentralWidget(splitter)

        self.status_bar = QStatusBar()
        self.status_bar.showMessage("就绪 — 选择左侧服务器后点击「连接」")
        self.setStatusBar(self.status_bar)

    def _setup_menu(self):
        menu = self.menuBar()
        menu.setStyleSheet("""
            QMenuBar { background-color: #3c3c3c; color: #cccccc; }
            QMenuBar::item:selected { background-color: #094771; }
            QMenu { background-color: #2d2d30; color: #cccccc; border: 1px solid #3c3c3c; }
            QMenu::item:selected { background-color: #094771; }
        """)

        file_menu = menu.addMenu("文件")
        refresh_action = QAction("刷新服务器列表", self)
        refresh_action.triggered.connect(self._load_servers)
        file_menu.addAction(refresh_action)
        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    # ------------------------------------------------------------------
    # 服务器列表
    # ------------------------------------------------------------------

    def _load_servers(self):
        servers = get_servers()
        self.server_panel.load_servers(servers)
        self.status_bar.showMessage(f"已加载 {len(servers)} 台服务器")

    # ------------------------------------------------------------------
    # 连接 / 断开
    # ------------------------------------------------------------------

    def _on_connect(self, info: dict):
        host = info.get("host", "")
        user = info.get("user", "root")
        port = info.get("port", 22)
        key_path = info.get("key_path")
        password = info.get("password")

        manager = SSHManager()

        async def _connect():
            return await manager.connect(
                host=host, user=user, port=port,
                key_path=key_path, password=password,
            )

        self.status_bar.showMessage(f"正在连接 {user}@{host}:{port}…")
        self.server_panel.connect_btn.setEnabled(False)

        self._bridge.submit_async(
            _connect(),
            lambda r: self._on_connected(r, user, host),
        )

    def _on_connected(self, result: dict, user: str, host: str):
        if result["status"] == "success":
            self._session_id = result["session_id"]
            self.terminal.set_session(self._session_id, user, host)
            self.server_panel.set_connected(
                self._session_id, self._session_id
            )
            self.status_panel.log_connect(self._session_id, host)
            self.status_bar.showMessage(f"已连接: {self._session_id}")

            # 展示系统欢迎信息
            self._show_welcome(user, host)
        else:
            self.server_panel.set_disconnected()
            self.status_panel.log_error(f"连接失败: {result['message']}")
            self.status_bar.showMessage(f"连接失败: {result['message']}")

    def _show_welcome(self, user: str, host: str):
        """连接成功后自动展示系统基本信息。"""
        sid = self._session_id
        if not sid:
            return

        manager = SSHManager()

        async def _welcome():
            results = {}
            for cmd, label in [
                ("uname -a", "系统"),
                ("uptime", "运行时间"),
                ("whoami", "用户"),
            ]:
                r = await manager.exec_command(sid, cmd, timeout=10)
                results[label] = r
            return results

        def _on_welcome(results: dict):
            self.terminal.append_line("", "#d4d4d4")
            for label, r in results.items():
                if r["status"] == "success":
                    out = r.get("stdout", "").strip()
                    self.terminal.append_line(f"  {label}: {out}\n", "#6a9955")
            self.terminal.append_line("", "#d4d4d4")

        self._bridge.submit_async(_welcome(), _on_welcome)

    def _on_disconnect(self):
        if not self._session_id:
            return

        manager = SSHManager()
        sid = self._session_id

        async def _disconnect():
            return await manager.disconnect(sid)

        self.status_bar.showMessage("正在断开…")
        self._bridge.submit_async(
            _disconnect(),
            lambda r: self._on_disconnected(r, sid),
        )

    def _on_disconnected(self, result: dict, session_id: str):
        self._session_id = None
        self.terminal.set_session(None)
        self.server_panel.set_disconnected()
        self.status_panel.log_disconnect(session_id)
        self.status_bar.showMessage(result.get("message", "已断开"))

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._session_id:
            manager = SSHManager()
            sid = self._session_id

            async def _disconnect():
                return await manager.disconnect(sid)

            # 同步等待断开（closeEvent 必须是同步的）
            self._bridge.submit(_disconnect)
            self.status_panel.log_disconnect(sid)

        self._bridge.stop()
        super().closeEvent(event)
