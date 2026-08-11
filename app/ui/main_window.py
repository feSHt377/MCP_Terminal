"""主窗口 — 无边框玻璃窗口，三栏布局：服务器列表 | 终端 | 操作日志。"""  # noqa: D205

import os
import sys
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QEvent, QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
)

from app.config.manager import get_auto_switch_tab, get_check_updates, get_servers
from app.ipc import GuiIPCServer, IPCRequest
from app.ssh.bridge import SSHBridge
from app.ssh.manager import SSHManager
from app.ui.server_panel import ServerPanel
from app.ui.status_panel import StatusPanel
from app.ui.terminal_widget import TerminalWidget
from app.ui.theme import MODES, MODE_DARK, MODE_LIGHT, MODE_SYSTEM
from app.ui.title_bar import TitleBar
from app.ui.windows_effects import (
    HTCAPTION,
    HTCLIENT,
    HTLEFT,
    HTTOP,
    HTTOPRIGHT,
    HTTOPLEFT,
    HTBOTTOM,
    HTBOTTOMLEFT,
    HTBOTTOMRIGHT,
    HTRIGHT,
    MINMAXINFO,
    RESIZE_MARGIN,
    WM_GETMINMAXINFO,
    WM_NCCALCSIZE,
    WM_NCHITTEST,
    apply_window_effects,
    enable_native_snap,
)


class _CheckUpdateWorker(QThread):
    """后台检测更新（不阻塞 GUI）。"""

    done = Signal(object)

    def run(self):  # noqa: D102
        from app.updater import check_for_update

        self.done.emit(check_for_update(timeout=8.0))


class _DownloadUpdateWorker(QThread):
    """后台下载并解压更新包。"""

    progress = Signal(str)
    done = Signal(object)

    def run(self):  # noqa: D102
        from app.updater import download_and_extract

        self.done.emit(download_and_extract(progress=lambda msg: self.progress.emit(msg)))



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
        # 中央终端区 —— 每个 SSH 会话一个标签页，各自独立管理 shell
        self._tabs = QTabWidget()
        self._tabs.setObjectName("terminalTabs")
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.setElideMode(Qt.ElideMiddle)
        self._tabs.tabCloseRequested.connect(self._on_tab_close)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tab_widgets: dict[str, TerminalWidget] = {}
        self.setCentralWidget(self._tabs)

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

        tools_menu.addSeparator()
        settings_action = QAction("⚙ 设置…", self)
        settings_action.triggered.connect(self._open_settings)
        tools_menu.addAction(settings_action)

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

        help_menu = menu.addMenu("帮助")
        check_update_action = QAction("检查更新…", self)
        check_update_action.triggered.connect(self._check_updates_manual)
        help_menu.addAction(check_update_action)
        help_menu.addSeparator()
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

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
        clear_terminal.setToolTip("清空当前终端标签页的可见内容")
        clear_terminal.triggered.connect(self._clear_current_terminal)
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

    def _on_command_executed(self, session_id: str, command: str, result: dict):
        self.status_panel.log_command(command, result.get("exit_code"), session=session_id)

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
            sid = result["session_id"]
            display_host = result.get("remote_hostname") or host
            current_dir = result.get("current_dir") or "~"
            self._open_session_tab(sid, user, display_host, current_dir)
            self.server_panel.set_connected(sid, sid)
            self.status_panel.log_connect(sid, host)
            self.status_bar.showMessage(f"已连接: {sid}")

            # 同步会话到已打开的 Chat 测试窗口
            if hasattr(self, "_chat_window") and self._chat_window is not None:
                self._chat_window.set_session(sid)

            # 展示系统欢迎信息
            self._show_welcome(sid, user, host)
        else:
            self.server_panel.set_disconnected()
            self.status_panel.log_error(f"连接失败: {result['message']}")
            self.status_bar.showMessage(f"连接失败: {result['message']}")

    def _open_session_tab(
        self, session_id: str, user: str, host: str, cwd: str = "~", switch: bool = True
    ) -> TerminalWidget:
        """为会话打开终端标签页（已存在则复用），可选是否立即切换过去。"""
        terminal = self._tab_widgets.get(session_id)
        if terminal is None:
            terminal = TerminalWidget()
            terminal.command_executed.connect(self._on_command_executed)
            terminal.set_session(session_id, user, host, cwd)
            index = self._tabs.addTab(terminal, f"{user}@{host}")
            self._tabs.setTabToolTip(index, session_id)
            self._tab_widgets[session_id] = terminal
        if switch:
            self._tabs.setCurrentWidget(terminal)
        else:
            # 后台打开的标签页不抢焦点，把焦点还给当前可见的终端。
            current = self._current_terminal()
            if current is not None and current is not terminal:
                current.output.setFocus()
        return terminal

    def _show_welcome(self, sid: str, user: str, host: str):
        """连接成功后自动展示系统基本信息。"""
        terminal = self._tab_widgets.get(sid)
        if terminal is None:
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
            terminal.append_line("", "#d4d4d4")
            for label, r in results.items():
                if r["status"] == "success":
                    out = r.get("stdout", "").strip()
                    terminal.append_line(f"  {label}: {out}\n", "#6a9955")
            terminal.append_line("", "#d4d4d4")

        self._bridge.submit_async(_welcome(), _on_welcome)

    def _on_disconnect(self):
        if not self._session_id:
            return
        sid = self._session_id
        self.status_bar.showMessage("正在断开…")
        self._disconnect_session(sid)

    def _disconnect_session(self, session_id: str):
        """异步断开会话，断开后移除对应标签页。"""
        manager = SSHManager()

        async def _disconnect():
            return await manager.disconnect(session_id)

        self._bridge.submit_async(
            _disconnect(),
            lambda r: self._on_disconnected(r, session_id),
        )

    def _on_disconnected(self, result: dict, session_id: str):
        self._remove_tab(session_id)
        if session_id == self._session_id:
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
        """Agent 代理执行：注入当前终端标签页的 SSH 输入框并自动执行。"""
        terminal = self._current_terminal()
        if terminal is None:
            self.status_panel.log_error("代理失败：未连接")
            return
        self.status_panel.log_tool_call("agent:proxy", "exec")
        terminal.append_line(f"\n-- Agent 代理执行 --\n", "#4fc1ff")
        terminal.execute_command(cmd)

    def _on_agent_autocomplete(self, cmd: str):
        terminal = self._current_terminal()
        if terminal is None:
            self.status_panel.log_error("补全失败：未连接")
            return
        self.status_panel.log_tool_call("agent:autocomplete", "ok")
        terminal.set_input_text(cmd)

    # ------------------------------------------------------------------
    # 终端标签页管理
    # ------------------------------------------------------------------

    def _current_terminal(self) -> TerminalWidget | None:
        """当前标签页的终端；没有打开任何标签页时返回 None。"""
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, TerminalWidget) else None

    def _session_for_widget(self, widget) -> str | None:
        for sid, term in self._tab_widgets.items():
            if term is widget:
                return sid
        return None

    def _terminal_for(self, session_id: str) -> TerminalWidget | None:
        """获取指定会话的终端；会话已连接但没打开标签页时后台打开一个。

        不主动切换当前标签页，避免 Agent 执行命令时抢占用户正在看的终端。
        """
        terminal = self._tab_widgets.get(session_id)
        if terminal is not None:
            return terminal
        sessions = SSHManager().list_sessions().get("sessions", {})
        info = sessions.get(session_id)
        if info is None or not info.get("connected"):
            return None
        return self._open_session_tab(
            session_id,
            info.get("user", ""),
            info.get("remote_hostname") or info.get("host", ""),
            info.get("current_dir") or "~",
            switch=False,
        )

    def _on_tab_close(self, index: int):
        widget = self._tabs.widget(index)
        sid = self._session_for_widget(widget)
        self._tabs.removeTab(index)
        if sid:
            self._disconnect_session(sid)

    def _remove_tab(self, session_id: str):
        terminal = self._tab_widgets.pop(session_id, None)
        if terminal is None:
            return
        index = self._tabs.indexOf(terminal)
        if index >= 0:
            self._tabs.removeTab(index)
        terminal.deleteLater()

    def _on_tab_changed(self, index: int):
        widget = self._tabs.widget(index) if index >= 0 else None
        sid = self._session_for_widget(widget) if widget is not None else None
        self._session_id = sid
        if sid:
            self.server_panel.set_connected(sid, sid)
            if hasattr(self, "_chat_window") and self._chat_window is not None:
                self._chat_window.set_session(sid)
        else:
            self.server_panel.set_disconnected()

    def _clear_current_terminal(self):
        terminal = self._current_terminal()
        if terminal is not None:
            terminal.clear_terminal()
        self.status_bar.showMessage("已清空当前终端标签页", 3000)

    def _open_settings(self):
        from app.ui.settings_dialog import SettingsDialog

        SettingsDialog(self).exec()

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
        if method == "switch_tab":
            self._switch_tab(request, str(params.get("session_id", "")))
            return
        if method == "autocomplete_command":
            command = str(params.get("command", ""))
            self._on_agent_autocomplete(command)
            request.finish({"status": "success", "command": command, "executed": False})
            return
        if method == "apply_update":
            self._start_ipc_update(request)
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

        requested_sid = str(params.get("session_id", "") or self._session_id or "")
        if method == "ssh_disconnect":
            if not requested_sid:
                request.finish({"status": "error", "message": "没有可断开的 SSH 会话"})
                return
            manager = SSHManager()
            self._bridge.submit_async(
                manager.disconnect(requested_sid),
                lambda result: self._finish_ipc_disconnect(request, result, requested_sid),
            )
            return

        if not requested_sid:
            request.finish({"status": "error", "message": "GUI 当前没有 SSH 会话"})
            return

        if method in ("ssh_exec", "proxy_command"):
            command = str(params.get("command", ""))
            tool_label = f"agent:{command[:30]}"

            def _finish_agent_command(result):
                self.status_panel.log_tool_call(tool_label, result.get("status", "error"))
                request.finish(result)

            terminal = self._terminal_for(requested_sid)
            if terminal is None:
                request.finish({
                    "status": "error",
                    "message": f"会话没有可用的终端标签页: {requested_sid}",
                })
                return
            dispatch = terminal.execute_command(
                command,
                on_done=_finish_agent_command,
                source="Agent",
                timeout=float(params.get("timeout", 30.0)),
                execution_mode=str(params.get("execution_mode", "auto")),
            )
            self.status_panel.log_tool_call(tool_label, dispatch.get("status", "error"))
            return

        if method == "cancel":
            terminal = self._terminal_for(requested_sid)
            if terminal is None:
                request.finish({
                    "status": "error",
                    "message": f"会话没有可用的终端标签页: {requested_sid}",
                })
                return
            result = terminal.cancel_command()
            self.status_panel.log_tool_call("agent:cancel", result.get("status", "error"))
            request.finish(result)
            return

        manager = SSHManager()
        sid = requested_sid
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

    def _finish_ipc_disconnect(self, request, result, sid):
        self._on_disconnected(result, sid)
        request.finish(result)

    def _select_session(self, request, session_id: str):
        sessions = SSHManager().list_sessions().get("sessions", {})
        info = sessions.get(session_id)
        if info is None or not info.get("connected"):
            request.finish({"status": "error", "message": f"SSH 会话不存在或未连接: {session_id}"})
            return
        self._open_session_tab(
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

    def _switch_tab(self, request: IPCRequest, session_id: str):
        """Agent 请求切换到指定会话标签页，受「自动切换标签页」开关约束。"""
        if not get_auto_switch_tab():
            request.finish({
                "status": "success",
                "session_id": session_id,
                "switched": False,
                "message": "「接受 Agent 自动切换标签页」已在 GUI 设置中关闭",
            })
            return
        self._select_session(request, session_id)

    # ------------------------------------------------------------------
    # 更新检测与自动更新
    # ------------------------------------------------------------------

    def _auto_check_updates(self):
        """启动后台静默检查更新；发现新版时非模态提示。"""
        if getattr(self, "_auto_check_started", False):
            return
        self._auto_check_started = True
        if not get_check_updates():
            return
        self._start_update_check(manual=False)

    def _start_update_check(self, manual: bool):
        """发起一次更新检查（单飞：已有检查/下载进行中则忽略）。

        全程用状态栏反馈，不弹无按钮的模态/非模态窗口，避免卡死。
        """
        if getattr(self, "_update_busy", False):
            self.status_bar.showMessage("已有更新检查/下载在进行中…", 3000)
            return
        self._update_busy = True
        self._update_check_manual = manual
        self.status_bar.showMessage("正在检查更新…", 30000)
        worker = _CheckUpdateWorker(self)
        worker.done.connect(self._on_update_check_done)
        self._update_check_worker = worker
        worker.start()

    def _on_update_check_done(self, result: dict):
        self._update_busy = False
        manual = bool(getattr(self, "_update_check_manual", False))
        self.status_bar.clearMessage()
        if result.get("status") == "success":
            if result.get("has_update"):
                self._prompt_update(str(result.get("local", "")), str(result.get("remote", "")))
            else:
                self.status_bar.showMessage(f"已是最新版本 v{result.get('local')}", 6000)
                if manual:
                    QMessageBox.information(
                        self, "检查更新", f"已是最新版本 v{result.get('local')}"
                    )
        else:
            self.status_bar.showMessage(f"检查更新失败：{result.get('message')}", 8000)
            if manual:
                QMessageBox.warning(self, "检查更新", f"检查失败：{result.get('message')}")

    def _check_updates_manual(self):
        """菜单「帮助 → 检查更新」：手动检查。"""
        self._start_update_check(manual=True)

    def _show_about(self):
        from app.updater import get_local_version

        QMessageBox.information(
            self,
            "关于",
            f"MCP Terminal — MCP 远程终端\n\n"
            f"当前版本 v{get_local_version()}\n"
            "基于 MCP 协议的通用 Agent 远程执行基础设施。",
        )

    def _close_update_prompt(self):
        box = getattr(self, "_update_prompt_box", None)
        if box is not None:
            box.close()
            self._update_prompt_box = None

    def _prompt_update(self, local: str, remote: str):
        """非模态提示发现新版本（只保留一个提示框）。"""
        self._close_update_prompt()
        box = QMessageBox(self)
        box.setWindowTitle("发现新版本")
        box.setIcon(QMessageBox.Information)
        box.setText(f"发现新版本 v{remote}（当前 v{local}）。\n是否立即下载并重启更新？")
        update_btn = box.addButton("立即更新", QMessageBox.AcceptRole)
        box.addButton("稍后", QMessageBox.RejectRole)
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.setModal(False)
        box.buttonClicked.connect(
            lambda btn: self._start_update_flow() if btn is update_btn else None
        )
        box.show()
        self._update_prompt_box = box

    def _start_update_flow(self, request: IPCRequest | None = None):
        """下载 → 校验 → 交给 helper 应用并重启。request 非空时先回包再重启。

        下载在后台线程执行，界面仅通过状态栏提示，不弹模态对话框。
        """
        if getattr(self, "_update_busy", False):
            if request is not None:
                request.finish({"status": "error", "message": "已有更新检查/下载在进行中"})
            return
        self._update_busy = True
        self._update_request = request
        self._close_update_prompt()
        self.status_bar.showMessage("正在下载更新…", 120000)

        worker = _DownloadUpdateWorker(self)
        worker.progress.connect(self._on_download_progress)
        worker.done.connect(self._on_download_done)
        self._download_worker = worker
        worker.start()

    def _on_download_progress(self, message: str):
        self.status_bar.showMessage(message, 120000)

    def _on_download_done(self, result: dict):
        self._update_busy = False
        self.status_bar.clearMessage()
        request = getattr(self, "_update_request", None)
        self._update_request = None

        if result.get("status") != "success":
            if request is not None:
                request.finish({"status": "error", "message": result.get("message")})
            else:
                self.status_bar.showMessage(f"更新失败：{result.get('message')}", 10000)
            return

        from app.updater import spawn_update_helper

        if request is not None:
            # 先回包，再交给 helper 重启，避免 IPC 连接被掐断导致 Agent 收到 error。
            request.finish({
                "status": "success",
                "remote": result.get("remote"),
                "message": "更新已就绪，GUI 即将重启",
            })
        else:
            self.status_bar.showMessage(
                f"已下载新版本 v{result.get('remote')}，GUI 将自动重启…", 5000
            )

        spawn_update_helper(os.getpid(), str(result["source"]))
        QTimer.singleShot(1500, self.close)

    def _start_ipc_update(self, request: IPCRequest):
        """Agent 请求更新：先检查再进入下载流程。"""
        if getattr(self, "_update_busy", False):
            request.finish({"status": "error", "message": "已有更新检查/下载在进行中"})
            return
        worker = _CheckUpdateWorker(self)
        worker.done.connect(lambda r: self._on_ipc_update_check(request, r))
        self._ipc_check_worker = worker
        worker.start()

    def _on_ipc_update_check(self, request: IPCRequest, result: dict):
        if result.get("status") != "success":
            request.finish({"status": "error", "message": result.get("message")})
            return
        if not result.get("has_update"):
            request.finish({
                "status": "success",
                "has_update": False,
                "local": result.get("local"),
                "remote": result.get("remote"),
                "message": "已是最新版本",
            })
            return
        self._start_update_flow(request=request)

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

        另处理 WM_NCCALCSIZE（返回 0 隐藏系统绘制的边框）与
        WM_GETMINMAXINFO（最大化限制在工作区内），配合 enable_native_snap
        恢复 Aero Snap 半屏/四分之一吸附手势。
        """
        if sys.platform == "win32" and event_type == b"windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_GETMINMAXINFO:
                    mmi = MINMAXINFO.from_address(msg.lParam)
                    screen = self.screen() or QGuiApplication.primaryScreen()
                    if screen is not None:
                        area = screen.availableGeometry()
                        mmi.ptMaxPosition.x = area.x()
                        mmi.ptMaxPosition.y = area.y()
                        mmi.ptMaxSize.x = area.width()
                        mmi.ptMaxSize.y = area.height()
                        mmi.ptMaxTrackSize.x = area.width()
                        mmi.ptMaxTrackSize.y = area.height()
                    return True, 0
                if msg.message == WM_NCCALCSIZE:
                    # 无边框：客户端区 = 整窗，不预留任何非客户端边框。
                    return True, 0
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
        """WM_NCHITTEST 处理：边缘缩放 + 标题栏空白区返回 HTCAPTION。

        x/y 为物理像素坐标，需先换算成逻辑坐标再与逻辑尺寸比较。
        标题栏空白区返回 HTCAPTION 以恢复 Windows 原生窗口手势：
        拖动移动/半屏吸附/四分之一分屏、双击最大化、最大化后拖下还原。
        按钮/菜单/应用名所在处返回 HTCLIENT，保证点击仍交给控件。
        """
        if not self.isVisible():
            return None
        dpr = self.devicePixelRatio() or 1.0
        local = self.mapFromGlobal(QPoint(round(x / dpr), round(y / dpr)))
        width, height = self.width(), self.height()
        m = RESIZE_MARGIN
        if not self.isMaximized():
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
        # 标题栏空白区域（无子控件处）→ HTCAPTION
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is not None and title_bar.isVisible() and 0 <= local.y() < title_bar.height():
            title_point = title_bar.mapFrom(self, local)
            if title_bar.childAt(title_point) is None:
                return HTCAPTION
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

                hwnd = int(self.winId())
                apply_window_effects(hwnd, theme_current().scheme)
                # 恢复 WS_THICKFRAME 等样式，启用 Windows 半屏/四分之一吸附。
                enable_native_snap(hwnd)
            except Exception:
                pass
        self._sync_maximize_state()
        # 启动后后台静默检查更新（可配置关闭），不阻塞窗口显示。
        QTimer.singleShot(1500, self._auto_check_updates)

    def closeEvent(self, event):
        if SSHManager().list_sessions().get("count", 0):
            manager = SSHManager()

            # GUI 退出时统一关闭其拥有的全部 SSH 会话。
            self._bridge.submit(manager.disconnect_all())

        self._ipc.stop()
        self._bridge.stop()
        super().closeEvent(event)
