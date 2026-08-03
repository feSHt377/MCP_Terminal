"""主窗口 — 三栏布局：服务器列表 | 终端 | 操作日志。"""  # noqa: D205

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QAction, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSplitter,
    QStatusBar,
    QToolBar,
)

from app.config.manager import get_servers
from app.ipc import GuiIPCServer, IPCRequest
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
        self._fit_current_screen()
        self._shown_once = False

        self._session_id: str | None = None

        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._load_servers()

        # 启动持久化 SSH 事件循环
        self._bridge = SSHBridge()
        self._bridge.start()

        # GUI 持有唯一 SSH 会话；MCP Server 通过本地 IPC 共同操作它。
        self._ipc = GuiIPCServer(self)
        self._ipc.request_received.connect(self._on_ipc_request)
        self._ipc.start()

    # ------------------------------------------------------------------
    # UI 搭建
    # ------------------------------------------------------------------

    def _fit_current_screen(self):
        """按鼠标所在屏幕可用分辨率的 3/5 居中启动。"""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            self.resize(1152, 648)
            self.setMinimumSize(640, 400)
            return
        area = screen.availableGeometry()
        width = max(640, round(area.width() * 3 / 5))
        height = max(400, round(area.height() * 3 / 5))
        width = min(width, area.width())
        height = min(height, area.height())
        self.resize(width, height)
        self.setMinimumSize(min(640, width), min(400, height))
        self.move(
            area.x() + (area.width() - width) // 2,
            area.y() + (area.height() - height) // 2,
        )

    def _setup_ui(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #010409;
            }
            QStatusBar {
                background-color: #161b22;
                color: #8b949e;
                border-top: 1px solid #30363d;
                font-size: 11px;
            }
            QSplitter::handle { background: #21262d; }
            QSplitter::handle:hover { background: #2f81f7; }
            QToolTip {
                color: #e6edf3;
                background: #161b22;
                border: 1px solid #30363d;
                padding: 5px;
            }
        """)

        splitter = QSplitter(Qt.Horizontal)

        self.server_panel = ServerPanel()
        self.server_panel.connect_requested.connect(self._on_connect)
        self.server_panel.disconnect_requested.connect(self._on_disconnect)

        self.terminal = TerminalWidget()
        self.terminal.command_executed.connect(self._on_command_executed)

        self.status_panel = StatusPanel()

        splitter.addWidget(self.server_panel)
        splitter.addWidget(self.terminal)
        splitter.addWidget(self.status_panel)
        splitter.setSizes([210, 760, 310])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setHandleWidth(4)

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

        tools_menu = menu.addMenu("工具")
        chat_action = QAction("🤖 Agent Chat（MCP 工具链测试）", self)
        chat_action.triggered.connect(self._open_chat)
        tools_menu.addAction(chat_action)

        clear_logs_action = QAction("清空操作日志", self)
        clear_logs_action.triggered.connect(self._clear_logs)
        tools_menu.addAction(clear_logs_action)

    def _setup_toolbar(self):
        toolbar = QToolBar("快捷工具", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        toolbar.setStyleSheet("""
            QToolBar#mainToolbar {
                background: #0d1117;
                border: none;
                border-bottom: 1px solid #21262d;
                spacing: 5px;
                padding: 5px 8px;
            }
            QToolButton {
                color: #c9d1d9;
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QToolButton:hover { background: #21262d; border-color: #30363d; }
            QToolButton:pressed { background: #30363d; }
        """)

        refresh = QAction("刷新服务器", self)
        refresh.setToolTip("重新读取服务器配置")
        refresh.triggered.connect(self._load_servers)
        toolbar.addAction(refresh)

        clear_terminal = QAction("清空终端", self)
        clear_terminal.setToolTip("清空当前终端的可见内容")
        clear_terminal.triggered.connect(self.terminal.clear_terminal)
        toolbar.addAction(clear_terminal)

        clear_logs = QAction("清空日志", self)
        clear_logs.setToolTip("清空右侧可见操作日志，不删除审计文件")
        clear_logs.triggered.connect(self._clear_logs)
        toolbar.addAction(clear_logs)

        toolbar.addSeparator()
        agent = QAction("Agent", self)
        agent.setToolTip("打开内置 Agent 工具链测试窗口")
        agent.triggered.connect(self._open_chat)
        toolbar.addAction(agent)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

    def _clear_logs(self):
        self.status_panel.clear_logs()
        self.status_bar.showMessage("已清空窗口日志；磁盘审计记录未删除", 3000)

    def _on_command_executed(self, command: str, result: dict):
        self.status_panel.log_command(command, result.get("exit_code"))

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
            display_host = result.get("remote_hostname") or host
            current_dir = result.get("current_dir") or "~"
            self.terminal.set_session(
                self._session_id, user, display_host, current_dir
            )
            self.server_panel.set_connected(
                self._session_id, self._session_id
            )
            self.status_panel.log_connect(self._session_id, host)
            self.status_bar.showMessage(f"已连接: {self._session_id}")

            # 同步会话到已打开的 Chat 测试窗口
            if hasattr(self, "_chat_window") and self._chat_window is not None:
                self._chat_window.set_session(self._session_id)

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
    # Agent Chat 窗口（MCP 工具链开发测试用）
    # ------------------------------------------------------------------

    def _open_chat(self):
        """打开 MCP 工具链测试窗口。"""
        from app.ui.chat_window import ChatWindow

        chat = ChatWindow(
            session_id=self._session_id,
            bridge=self._bridge,
            parent=self,
        )
        # 代理：Agent 命令注入主终端并执行
        chat.proxy_command_requested.connect(self._on_agent_proxy)
        # 补全：Agent 命令填入主终端输入框
        chat.autocomplete_requested.connect(self._on_agent_autocomplete)

        self._chat_window = chat
        chat.show()

    def _on_agent_proxy(self, cmd: str):
        """Agent 代理执行：注入主终端 SSH 输入框并自动执行。"""
        if not self._session_id:
            self.status_panel.log_error("代理失败：未连接")
            return
        self.status_panel.log_tool_call("agent:proxy", "exec")
        self.terminal.append_line(f"\n-- Agent 代理执行 --\n", "#4fc1ff")
        self.terminal.execute_command(cmd)

    def _on_agent_autocomplete(self, cmd: str):
        self.status_panel.log_tool_call("agent:autocomplete", "ok")
        self.terminal.set_input_text(cmd)

    # ------------------------------------------------------------------
    # MCP / GUI 共享会话 IPC
    # ------------------------------------------------------------------

    def _on_ipc_request(self, request: IPCRequest):
        method = request.method
        params = request.params

        if method == "ping":
            request.finish({"status": "success", "session_id": self._session_id})
            return
        if method == "activate":
            self.showNormal()
            self.raise_()
            self.activateWindow()
            request.finish({"status": "success", "session_id": self._session_id})
            return
        if method == "list_sessions":
            request.finish(SSHManager().list_sessions())
            return
        if method == "select_session":
            self._select_session(request, str(params.get("session_id", "")))
            return
        if method == "autocomplete_command":
            command = str(params.get("command", ""))
            self._on_agent_autocomplete(command)
            request.finish({"status": "success", "command": command, "executed": False})
            return

        if method == "ssh_connect":
            host = str(params.get("host", ""))
            user = str(params.get("user", "root"))
            port = int(params.get("port", 22))
            manager = SSHManager()

            async def _connect():
                return await manager.connect(
                    host=host, user=user, port=port,
                    password=params.get("password"), key_path=params.get("key_path"),
                )

            self._bridge.submit_async(
                _connect(),
                lambda result: self._finish_ipc_connect(request, result, user, host),
            )
            return

        requested_sid = params.get("session_id")
        if method == "ssh_disconnect":
            sid_to_close = str(requested_sid or self._session_id or "")
            if not sid_to_close:
                request.finish({"status": "error", "message": "没有可断开的 SSH 会话"})
                return
            manager = SSHManager()
            self._bridge.submit_async(
                manager.disconnect(sid_to_close),
                lambda result: self._finish_ipc_disconnect(
                    request, result, sid_to_close, sid_to_close == self._session_id
                ),
            )
            return

        sid = self._session_id
        if not sid:
            request.finish({"status": "error", "message": "GUI 当前没有 SSH 会话"})
            return
        if requested_sid and requested_sid != sid:
            request.finish({
                "status": "error",
                "message": f"请求会话 {requested_sid} 不是 GUI 当前会话 {sid}",
            })
            return

        if method in ("ssh_exec", "proxy_command"):
            command = str(params.get("command", ""))
            tool_label = f"agent:{command[:30]}"

            def _finish_agent_command(result):
                self.status_panel.log_tool_call(tool_label, result.get("status", "error"))
                request.finish(result)

            dispatch = self.terminal.execute_command(
                command,
                on_done=_finish_agent_command,
                source="Agent",
                timeout=float(params.get("timeout", 30.0)),
                execution_mode=str(params.get("execution_mode", "auto")),
            )
            self.status_panel.log_tool_call(tool_label, dispatch.get("status", "error"))
            return

        manager = SSHManager()
        if method == "terminal_write":
            coro = manager.terminal_write(sid, str(params.get("data", "")))
            callback = request.finish
        elif method == "terminal_read":
            coro = manager.terminal_read(
                sid, size=int(params.get("size", 4096)), timeout=float(params.get("timeout", 2.0)),
            )
            callback = request.finish
        elif method == "upload_file":
            coro = manager.upload_file(sid, params["local_path"], params["remote_path"])
            callback = request.finish
        elif method == "download_file":
            coro = manager.download_file(sid, params["remote_path"], params["local_path"])
            callback = request.finish
        else:
            request.finish({"status": "error", "message": f"未知 GUI IPC 方法: {method}"})
            return
        if method == "terminal_write":
            self._bridge.submit_realtime(coro, callback)
        else:
            self._bridge.submit_async(coro, callback)

    def _finish_ipc_connect(self, request, result, user, host):
        self._on_connected(result, user, host)
        request.finish(result)

    def _finish_ipc_disconnect(self, request, result, sid, was_current=True):
        if was_current:
            self._on_disconnected(result, sid)
        elif result.get("status") == "success":
            self.status_panel.log_disconnect(sid)
        request.finish(result)

    def _select_session(self, request, session_id: str):
        sessions = SSHManager().list_sessions().get("sessions", {})
        info = sessions.get(session_id)
        if info is None or not info.get("connected"):
            request.finish({"status": "error", "message": f"SSH 会话不存在或未连接: {session_id}"})
            return
        self._session_id = session_id
        self.terminal.set_session(
            session_id,
            info.get("user", ""),
            info.get("remote_hostname") or info.get("host", ""),
            info.get("current_dir") or "~",
        )
        self.server_panel.set_connected(session_id, session_id)
        self.status_bar.showMessage(f"当前会话: {session_id}")
        if hasattr(self, "_chat_window") and self._chat_window is not None:
            self._chat_window.set_session(session_id)
        request.finish({"status": "success", "session_id": session_id, "message": "已切换当前会话"})

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if self._shown_once:
            return
        self._shown_once = True
        self.setWindowOpacity(0.0)
        self._fade_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_animation.setDuration(220)
        self._fade_animation.setStartValue(0.0)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_animation.start()

    def closeEvent(self, event):
        if SSHManager().list_sessions().get("count", 0):
            manager = SSHManager()

            # GUI 退出时统一关闭其拥有的全部 SSH 会话。
            self._bridge.submit(manager.disconnect_all())

        self._ipc.stop()
        self._bridge.stop()
        super().closeEvent(event)
