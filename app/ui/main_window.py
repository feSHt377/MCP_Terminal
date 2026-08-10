"""主窗口 — 无边框玻璃窗口，三栏布局：服务器列表 | 终端 | 操作日志。"""  # noqa: D205

import sys
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QAction, QActionGroup, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QMainWindow,
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
from app.ui.theme import MODES, MODE_DARK, MODE_LIGHT, MODE_SYSTEM
from app.ui.title_bar import TitleBar
from app.ui.windows_effects import (
    HTCLIENT,
    HTLEFT,
    HTTOP,
    HTTOPRIGHT,
    HTTOPLEFT,
    HTBOTTOM,
    HTBOTTOMLEFT,
    HTBOTTOMRIGHT,
    HTRIGHT,
    RESIZE_MARGIN,
    WM_NCHITTEST,
    apply_window_effects,
)


class MainWindow(QMainWindow):
    """mcpterminal 主窗口 — 无边框 + Mica 圆角 + 自绘标题栏。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("mcpterminal — MCP 远程终端")
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        # 注意：不启用 WA_TranslucentBackground（每像素透明窗口在 Win11 上会导致
        # 子控件点击穿透）。玻璃质感由 Mica 背景 + QSS 渐变实现。
        self._effects_applied = False
        self._fit_current_screen()
        self._shown_once = False

        self._session_id: str | None = None

        self._setup_title_bar()
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
    # 标题栏（自绘，替代 Windows 原生边框）
    # ------------------------------------------------------------------

    def _setup_title_bar(self):
        self._title_bar = TitleBar(self)
        self._title_bar.set_app_name("MCP Terminal")
        self._title_bar.minimize_clicked.connect(self.showMinimized)
        self._title_bar.maximize_clicked.connect(self._toggle_maximize)
        self._title_bar.close_clicked.connect(self.close)
        self.setMenuWidget(self._title_bar)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _sync_maximize_state(self):
        self._title_bar.set_maximize_state(self.isMaximized())

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
        # 中央终端（始终占据主区域）
        self.terminal = TerminalWidget()
        self.terminal.command_executed.connect(self._on_command_executed)
        self.setCentralWidget(self.terminal)

        # 左侧服务器面板 —— 可拖出成独立窗口
        self.server_panel = ServerPanel()
        self.server_panel.connect_requested.connect(self._on_connect)
        self.server_panel.disconnect_requested.connect(self._on_disconnect)
        self._server_dock = self._make_dock("服务器", self.server_panel)

        # 右侧操作日志面板 —— 可拖出成独立窗口
        self.status_panel = StatusPanel()
        self._status_dock = self._make_dock("操作日志", self.status_panel)

        self.addDockWidget(Qt.LeftDockWidgetArea, self._server_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self._status_dock)
        self.resizeDocks([self._server_dock, self._status_dock], [220, 320], Qt.Horizontal)

        self.status_bar = QStatusBar()
        self.status_bar.showMessage("就绪 — 选择左侧服务器后点击「连接」")
        self.setStatusBar(self.status_bar)

    def _make_dock(self, title: str, widget) -> QDockWidget:
        """创建可移动 / 可拖出 / 可关闭的停靠面板。"""
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title}")
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        return dock

    def _reset_layout(self):
        """恢复默认停靠布局。"""
        self._server_dock.show()
        self._status_dock.show()
        self.addDockWidget(Qt.LeftDockWidgetArea, self._server_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self._status_dock)
        self.resizeDocks([self._server_dock, self._status_dock], [220, 320], Qt.Horizontal)
        self.status_bar.showMessage("已恢复默认布局", 3000)

    def _theme_manager_mode(self) -> str:
        """读取当前主题模式（来自 main.py 安装的 ThemeManager）。"""
        manager = getattr(QApplication.instance(), "_theme_manager", None)
        return manager.mode() if manager is not None else MODE_SYSTEM

    def _on_theme_selected(self, action: QAction):
        """菜单勾选 → 切换主题模式并持久化。"""
        manager = getattr(QApplication.instance(), "_theme_manager", None)
        if manager is None:
            return
        mode = action.data()
        manager.set_mode(mode)
        labels = {MODE_LIGHT: "亮色", MODE_DARK: "暗色", MODE_SYSTEM: "跟随系统"}
        self.status_bar.showMessage(f"主题: {labels.get(mode, mode)}", 3000)

    def _setup_menu(self):
        menu = self._title_bar.menu_bar

        file_menu = menu.addMenu("文件")
        refresh_action = QAction("刷新服务器列表", self)
        refresh_action.triggered.connect(self._load_servers)
        file_menu.addAction(refresh_action)
        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = menu.addMenu("视图")
        view_menu.addAction(self._server_dock.toggleViewAction())
        view_menu.addAction(self._status_dock.toggleViewAction())
        view_menu.addSeparator()
        reset_layout_action = QAction("恢复默认布局", self)
        reset_layout_action.triggered.connect(self._reset_layout)
        view_menu.addAction(reset_layout_action)

        tools_menu = menu.addMenu("工具")
        chat_action = QAction("🤖 Agent Chat（MCP 工具链测试）", self)
        chat_action.triggered.connect(self._open_chat)
        tools_menu.addAction(chat_action)

        clear_logs_action = QAction("清空操作日志", self)
        clear_logs_action.triggered.connect(self._clear_logs)
        tools_menu.addAction(clear_logs_action)

        theme_menu = menu.addMenu("主题")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        theme_mode = self._theme_manager_mode()
        for mode, label in (
            (MODE_LIGHT, "☀️ 亮色"),
            (MODE_DARK, "🌙 暗色"),
            (MODE_SYSTEM, "🖥️ 跟随系统"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(mode)
            action.setChecked(mode == theme_mode)
            self._theme_group.addAction(action)
            theme_menu.addAction(action)
        self._theme_group.triggered.connect(self._on_theme_selected)

    def _setup_toolbar(self):
        toolbar = QToolBar("快捷工具", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)

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

        toolbar.addSeparator()
        reset_layout = QAction("重置布局", self)
        reset_layout.setToolTip("将拖出的面板恢复到默认停靠位置")
        reset_layout.triggered.connect(self._reset_layout)
        toolbar.addAction(reset_layout)
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
    # 窗口系统事件：无边框 resize 命中测试 + 标题栏拖动
    # ------------------------------------------------------------------

    def nativeEvent(self, event_type, message):
        """拦截 WM_NCHITTEST，让无边框窗口支持边缘缩放。

        WM_NCHITTEST 的 lParam 是物理像素坐标，而 Qt 的 mapFromGlobal /
        默认命中测试按逻辑像素解释。高分屏（dpr>1）下直接用物理坐标会
        把窗口右侧/下侧大片区域误判为缩放边缘（HTRIGHT/HTBOTTOM 等），
        导致这些区域的控件收不到任何鼠标事件。因此先做 DPI 换算，并对
        内部区域显式返回 HTCLIENT，不再交给 Qt 默认处理。
        """
        if sys.platform == "win32" and event_type == b"windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_NCHITTEST:
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    result = self._hit_test(x, y)
                    if result is None:
                        # 内部区域：显式 HTCLIENT，避免 Qt 默认把高 DPI
                        # 物理坐标误判为边缘缩放区，吞掉按钮点击。
                        return True, HTCLIENT
                    return True, result
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def _hit_test(self, x: int, y: int):
        """WM_NCHITTEST 处理：仅在四边返回缩放区域，其余返回 HTCLIENT。

        x/y 为物理像素坐标，需先换算成逻辑坐标再与逻辑尺寸比较。
        """
        if self.isMaximized() or not self.isVisible():
            return None
        dpr = self.devicePixelRatio() or 1.0
        local = self.mapFromGlobal(QPoint(round(x / dpr), round(y / dpr)))
        width, height = self.width(), self.height()
        m = RESIZE_MARGIN
        # 四角优先
        if local.y() <= m and local.x() <= m:
            return HTTOPLEFT
        if local.y() <= m and local.x() >= width - m:
            return HTTOPRIGHT
        if local.y() >= height - m and local.x() <= m:
            return HTBOTTOMLEFT
        if local.y() >= height - m and local.x() >= width - m:
            return HTBOTTOMRIGHT
        if local.y() <= m:
            return HTTOP
        if local.y() >= height - m:
            return HTBOTTOM
        if local.x() <= m:
            return HTLEFT
        if local.x() >= width - m:
            return HTRIGHT
        return None


    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_maximize_state()

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if self._shown_once:
            return
        self._shown_once = True
        # 应用毛玻璃 + 圆角特效（需先有原生窗口句柄）
        if sys.platform == "win32" and not self._effects_applied:
            self._effects_applied = True
            try:
                from app.ui.theme import current as theme_current

                apply_window_effects(int(self.winId()), theme_current().scheme)
            except Exception:
                pass
        self._sync_maximize_state()

    def closeEvent(self, event):
        if SSHManager().list_sessions().get("count", 0):
            manager = SSHManager()

            # GUI 退出时统一关闭其拥有的全部 SSH 会话。
            self._bridge.submit(manager.disconnect_all())

        self._ipc.stop()
        self._bridge.stop()
        super().closeEvent(event)
