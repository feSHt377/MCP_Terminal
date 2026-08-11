"""Interactive SSH terminal with streaming output and a shared Agent/Human session."""

from __future__ import annotations

import re
from collections import deque

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import current as theme_current


_ANSI_ESCAPE_RE = re.compile(
    r"(?:\x1B\][^\x07]*(?:\x07|\x1B\\))|(?:\x1B[@-_][0-?]*[ -/]*[@-~])"
)


def strip_terminal_control(text: str) -> str:
    """Remove ANSI/OSC control sequences while preserving CR progress updates."""
    return _ANSI_ESCAPE_RE.sub("", text).replace("\x00", "")


class TerminalSurface(QPlainTextEdit):
    """Read-only document which still accepts terminal-style keyboard input."""

    command_submitted = Signal(str)
    raw_input = Signal(str)
    history_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMaximumBlockCount(12000)
        self._connected = False
        self._busy = False
        self._prompt = "$ "
        self._input_buffer = ""
        self._input_anchor: int | None = None

    def set_terminal_state(self, connected: bool, busy: bool, prompt: str = "") -> None:
        self._connected = connected
        self._busy = busy
        if prompt:
            self._prompt = prompt
        if busy:
            self.cancel_input_line()

    def detach_input_line(self) -> str | None:
        """Temporarily remove the local input line while asynchronous output is appended."""
        if self._input_anchor is None:
            return None
        saved = self._input_buffer
        cursor = self.textCursor()
        cursor.setPosition(self._input_anchor)
        cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        self.setTextCursor(cursor)
        self._input_anchor = None
        return saved

    def restore_input_line(self, text: str | None) -> None:
        if text is None or self._busy or not self._connected:
            return
        self._input_buffer = text
        self._render_input_line()

    def cancel_input_line(self) -> None:
        saved = self.detach_input_line()
        if saved is not None:
            self._input_buffer = ""

    def replace_input(self, text: str) -> None:
        self.cancel_input_line()
        self._input_buffer = text.replace("\r", "").replace("\n", " ")
        self._render_input_line()
        self.setFocus()

    def finish_input_line(self) -> str:
        command = self._input_buffer
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText("\n")
        self.setTextCursor(cursor)
        self._input_buffer = ""
        self._input_anchor = None
        return command

    def _render_input_line(self) -> None:
        if not self._connected or self._busy:
            return
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._input_anchor = cursor.position()

        prompt_format = QTextCharFormat()
        prompt_format.setForeground(QColor(theme_current().success))
        prompt_format.setFontWeight(QFont.Bold)
        cursor.insertText(self._prompt, prompt_format)

        input_format = QTextCharFormat()
        input_format.setForeground(QColor(theme_current().text))
        cursor.insertText(self._input_buffer, input_format)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _append_typed_text(self, text: str) -> None:
        if self._input_anchor is None:
            self._render_input_line()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(theme_current().text))
        cursor.insertText(text, fmt)
        self.setTextCursor(cursor)
        self._input_buffer += text
        self.ensureCursorVisible()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._connected:
            super().keyPressEvent(event)
            return

        key = event.key()
        modifiers = event.modifiers()

        if self._busy:
            # 忙时（命令/Agent 运行中）：所有按键（含 Ctrl+C）都转发到远程 shell。
            # 该分支必须先于下方 Copy 快捷键处理，否则 Ctrl+C 会被复制动作吞掉，
            # 永远发不出中断信号 \x03，导致远程进程无法被取消。
            if event.matches(QKeySequence.Paste):
                pasted = QApplication.clipboard().text()
                if pasted:
                    self.raw_input.emit(pasted)
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                self.raw_input.emit("\n")
            elif key == Qt.Key_Backspace:
                self.raw_input.emit("\x7f")
            elif key == Qt.Key_Tab:
                self.raw_input.emit("\t")
            elif key == Qt.Key_C and modifiers & Qt.ControlModifier:
                self.raw_input.emit("\x03")
            elif key == Qt.Key_D and modifiers & Qt.ControlModifier:
                self.raw_input.emit("\x04")
            elif key == Qt.Key_Up:
                self.raw_input.emit("\x1b[A")
            elif key == Qt.Key_Down:
                self.raw_input.emit("\x1b[B")
            elif key == Qt.Key_Right:
                self.raw_input.emit("\x1b[C")
            elif key == Qt.Key_Left:
                self.raw_input.emit("\x1b[D")
            elif event.text():
                self.raw_input.emit(event.text())
            else:
                super().keyPressEvent(event)
            return

        if event.matches(QKeySequence.Copy):
            self.copy()
            return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            command = self.finish_input_line()
            self.command_submitted.emit(command)
            return
        if key == Qt.Key_Backspace:
            if self._input_buffer:
                self._input_buffer = self._input_buffer[:-1]
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.End)
                cursor.deletePreviousChar()
                self.setTextCursor(cursor)
            return
        if key == Qt.Key_Escape:
            self.replace_input("")
            return
        if key == Qt.Key_Up:
            self.history_requested.emit(-1)
            return
        if key == Qt.Key_Down:
            self.history_requested.emit(1)
            return
        if event.matches(QKeySequence.Paste):
            pasted = QApplication.clipboard().text().replace("\r", "").replace("\n", " ")
            if pasted:
                self._append_typed_text(pasted)
            return
        if event.text() and not modifiers & (Qt.ControlModifier | Qt.AltModifier):
            self._append_typed_text(event.text())
            return
        super().keyPressEvent(event)


class TerminalWidget(QWidget):
    """SSH terminal shared by direct human input and MCP Agent commands."""

    command_executed = Signal(str, str, object)  # (session_id, command, result)
    stream_received = Signal(str, bool)
    interactive_finished = Signal(object)
    MAX_AGENT_QUEUE = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session_id: str | None = None
        self._user = ""
        self._host = ""
        self._cwd = "~"
        self._history: list[str] = []
        self._history_index = -1
        self._busy = False
        self._interactive_mode = False
        self._interactive_busy = False
        self._result_callback = None
        self._active_command = ""
        self._pending_commands = deque()
        self._setup_ui()
        self.stream_received.connect(self._on_stream_received)
        self.interactive_finished.connect(self._on_interactive_finished)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        self.output = TerminalSurface()
        self.output.setObjectName("terminalOutput")
        self.output.setFrameStyle(QFrame.NoFrame)
        mono = QFont("Cascadia Mono", 10)
        mono.setStyleHint(QFont.Monospace)
        self.output.setFont(mono)
        self.output.command_submitted.connect(self._on_surface_command)
        self.output.raw_input.connect(self._send_raw_input)
        self.output.history_requested.connect(self._browse_history)
        layout.addWidget(self.output, stretch=1)

        input_frame = QFrame()
        input_frame.setObjectName("terminalInputFrame")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(10, 7, 10, 7)
        input_layout.setSpacing(8)

        self.prompt_label = QLineEdit()
        self.prompt_label.setObjectName("promptLabel")
        self.prompt_label.setReadOnly(True)
        self.prompt_label.setFrame(False)
        self.prompt_label.setFixedWidth(190)

        self.input = QLineEdit()
        self.input.setObjectName("terminalInput")
        self.input.setFrame(False)
        self.input.setPlaceholderText("也可以在上方 Shell 区域直接输入…")
        self.input.returnPressed.connect(self._on_send)
        self.input.installEventFilter(self)

        self.activity = QProgressBar()
        self.activity.setObjectName("activity")
        self.activity.setRange(0, 0)
        self.activity.setTextVisible(False)
        self.activity.setFixedSize(54, 4)
        self.activity.setVisible(False)

        input_layout.addWidget(self.prompt_label)
        input_layout.addWidget(self.input, stretch=1)
        input_layout.addWidget(self.activity)
        layout.addWidget(input_frame)

    def set_session(
        self,
        session_id: str | None,
        user: str = "",
        host: str = "",
        cwd: str = "~",
    ) -> None:
        self._session_id = session_id
        self._user = user
        self._host = host
        self._cwd = cwd or "~"
        if session_id:
            prompt = self._prompt_text()
            self.prompt_label.setText(prompt.strip())
            self.input.setEnabled(True)
            self.output.set_terminal_state(True, self._busy, prompt)
            self.output.setFocus()
            self._append_output(f"\n— 已连接 {session_id} —\n", theme_current().success)
            self.output.replace_input("")
        else:
            self.prompt_label.setText("未连接")
            self.input.setEnabled(False)
            self.output.set_terminal_state(False, False)
            self._append_output("\n— 已断开 —\n", theme_current().text_muted)

    def append_line(self, text: str, color: str | None = None) -> None:
        if color is None:
            color = theme_current().text
        self._append_output(text, color)

    def clear_terminal(self) -> None:
        self.output.cancel_input_line()
        self.output.clear()
        if self._session_id and not self._busy:
            self.output.replace_input("")

    def execute_command(
        self,
        cmd: str,
        on_done=None,
        source: str = "Agent",
        timeout: float = 30.0,
        execution_mode: str = "auto",
    ) -> dict:
        return self._execute(
            cmd,
            on_done=on_done,
            source=source,
            timeout=timeout,
            execution_mode=execution_mode,
        )

    def set_input_text(self, text: str) -> None:
        self.input.setText(text)
        self.output.replace_input(text)

    def eventFilter(self, obj, event):
        # 命令运行/交互模式中，底部输入栏按 Ctrl+C 发送中断信号 \x03 而不是复制。
        if (
            obj is self.input
            and self._busy
            and event.type() == QEvent.KeyPress
            and event.matches(QKeySequence.Copy)
        ):
            self._send_raw_input("\x03")
            return True
        return super().eventFilter(obj, event)

    def _on_send(self) -> None:
        text = self.input.text()
        if self._busy:
            # 命令运行/交互模式中：底部输入栏作为活动进程的输入通道。
            # 可输入 exit 退出嵌套 shell，或在栏内按 Ctrl+C 中断当前命令。
            self.input.clear()
            if text or self._interactive_mode:
                self._send_raw_input(text + "\n")
            return
        if not text.strip():
            self.output.finish_input_line()
            self.output.replace_input("")
            return
        self.output.cancel_input_line()
        self._execute(text, source="Human", timeout=3600.0)

    def _on_surface_command(self, text: str) -> None:
        self.input.clear()
        if not text.strip():
            self.output.replace_input("")
            return
        self._execute(text, source="Human", timeout=3600.0, display_echo=False)

    def _prompt_text(self) -> str:
        return f"{self._user}@{self._host}:{self._cwd}$ "

    def _execute(
        self,
        text: str,
        on_done=None,
        source: str = "Human",
        timeout: float = 30.0,
        display_echo: bool = True,
        execution_mode: str = "auto",
    ) -> dict:
        sid = self._session_id
        if not sid:
            result = {"status": "error", "message": "GUI 当前没有 SSH 会话"}
            self._append_output("⚠ 未连接到任何服务器\n", theme_current().warning)
            if on_done:
                on_done(result)
            return result
        if execution_mode not in {"auto", "command", "interactive"}:
            result = {
                "status": "error",
                "message": f"未知 execution_mode: {execution_mode}",
            }
            if on_done:
                on_done(result)
            return result

        if self._busy:
            if source != "Agent":
                result = {"status": "error", "message": "命令运行中，请直接在 Shell 区域输入交互内容"}
                if on_done:
                    on_done(result)
                return result
            if self._interactive_mode:
                # 交互式 Shell 已就绪：新命令直接注入其中执行，不再排队阻塞。
                if self._interactive_busy:
                    if len(self._pending_commands) >= self.MAX_AGENT_QUEUE:
                        result = {
                            "status": "error",
                            "message": f"Agent 命令队列已满（最多 {self.MAX_AGENT_QUEUE} 条）",
                        }
                        if on_done:
                            on_done(result)
                        return result
                    self._pending_commands.append(
                        (text, on_done, source, timeout, sid, display_echo, execution_mode)
                    )
                    position = len(self._pending_commands)
                    self._append_output(f"⏳ [Agent 排队 #{position}] {text}\n", theme_current().warning)
                    return {"status": "queued", "position": position}
                self._start_execute(
                    text, on_done, source, timeout, sid, display_echo, execution_mode
                )
                return {"status": "running"}
            if len(self._pending_commands) >= self.MAX_AGENT_QUEUE:
                result = {
                    "status": "error",
                    "message": f"Agent 命令队列已满（最多 {self.MAX_AGENT_QUEUE} 条）",
                }
                if on_done:
                    on_done(result)
                return result
            self._pending_commands.append(
                (text, on_done, source, timeout, sid, display_echo, execution_mode)
            )
            position = len(self._pending_commands)
            self._append_output(f"⏳ [Agent 排队 #{position}] {text}\n", theme_current().warning)
            return {"status": "queued", "position": position}

        self._start_execute(
            text, on_done, source, timeout, sid, display_echo, execution_mode
        )
        return {"status": "running"}

    def _start_execute(
        self,
        text,
        on_done,
        source,
        timeout,
        sid,
        display_echo=True,
        execution_mode="auto",
    ) -> None:
        self._history.append(text)
        self._history_index = len(self._history)
        if display_echo:
            suffix = "  [Agent]" if source == "Agent" else ""
            self._append_output(f"$ {text}{suffix}\n", theme_current().info if suffix else theme_current().accent)

        # 命令运行期间底部输入栏保持可用，作为活动进程的输入通道
        # （回车转发输入、Ctrl+C 发送中断 \x03），不阻塞人工介入。
        self.input.clear()
        self.input.setPlaceholderText("命令运行中：回车发送到当前进程 / Ctrl+C 中断")
        self._busy = True
        self._interactive_busy = self._interactive_mode
        self.activity.setVisible(True)
        prompt = self._prompt_text()
        self.output.set_terminal_state(True, True, prompt)
        self.output.setFocus()
        self._result_callback = on_done
        self._active_command = text

        from app.ssh.bridge import SSHBridge
        from app.ssh.manager import SSHManager

        manager = SSHManager()

        def _stream(text_chunk: str, is_stderr: bool) -> None:
            self.stream_received.emit(text_chunk, is_stderr)

        interactive = {
            "auto": None,
            "command": False,
            "interactive": True,
        }[execution_mode]

        def _interactive_exit(result: dict) -> None:
            self.interactive_finished.emit(result)

        async def _exec():
            return await manager.exec_command_stream(
                sid,
                text,
                timeout=timeout,
                on_output=_stream,
                interactive=interactive,
                on_exit=_interactive_exit,
            )

        SSHBridge().submit_async(_exec(), self._on_result)

    def _on_stream_received(self, text: str, is_stderr: bool) -> None:
        self._append_output(text, theme_current().danger if is_stderr else theme_current().text, dynamic=True)

    def _on_result(self, result: dict) -> None:
        if result.get("interactive") and result.get("ready"):
            self._interactive_mode = True
            self._interactive_busy = False
            self.activity.setVisible(False)
            callback = self._result_callback
            command = self._active_command
            self._result_callback = None
            self._active_command = ""
            if callback:
                callback(result)
            self.command_executed.emit(self._session_id or "", command, result)
            # 交互模式：底部输入栏作为当前进程的输入通道，提示用户如何退出。
            self.input.setEnabled(bool(self._session_id))
            self.input.setPlaceholderText(
                "交互模式：输入并回车发送到当前进程（exit 退出 / Ctrl+C 中断）"
            )
            self.prompt_label.setText("交互模式")
            if self._pending_commands:
                QTimer.singleShot(0, self._run_next)
            else:
                self.output.setFocus()
            return

        self._busy = False
        self._interactive_mode = False
        self._interactive_busy = False
        self.activity.setVisible(False)

        if not result.get("streamed"):
            if result.get("stdout"):
                self._append_output(result["stdout"], theme_current().text)
            if result.get("stderr"):
                self._append_output(result["stderr"], theme_current().danger)
        if result.get("status") != "success":
            self._append_output(f"\n❌ {result.get('message', '命令执行失败')}\n", theme_current().danger)
        elif result.get("exit_code") not in (None, 0):
            self._append_output(f"\n[exit {result['exit_code']}]\n", theme_current().warning)

        callback = self._result_callback
        command = self._active_command
        self._result_callback = None
        self._active_command = ""
        if callback:
            callback(result)
        self.command_executed.emit(self._session_id or "", command, result)

        if self._pending_commands:
            QTimer.singleShot(0, self._run_next)
        else:
            self._restore_normal_input()

    def _restore_normal_input(self) -> None:
        """退出忙碌/交互状态后恢复普通输入栏。"""
        self.input.setEnabled(bool(self._session_id))
        self.input.setPlaceholderText("也可以在上方 Shell 区域直接输入…")
        self.prompt_label.setText(self._prompt_text().strip())
        prompt = self._prompt_text()
        self.output.set_terminal_state(bool(self._session_id), False, prompt)
        self.output.replace_input("")
        self.output.setFocus()

    def _on_interactive_finished(self, result: dict) -> None:
        """嵌套 Shell 输入 exit/EOF 后恢复普通命令模式。"""
        if not self._interactive_mode:
            return
        self._interactive_mode = False
        self._busy = False
        self._interactive_busy = False
        exit_code = result.get("exit_code")
        if result.get("status") == "error":
            self._append_output(f"\n❌ {result.get('message', '交互式 Shell 已断开')}\n", theme_current().danger)
        elif exit_code not in (None, 0):
            self._append_output(f"\n[interactive exit {exit_code}]\n", theme_current().warning)

        if self._pending_commands:
            QTimer.singleShot(0, self._run_next)
        else:
            self._restore_normal_input()

    def _run_next(self) -> None:
        if self._busy and not (self._interactive_mode and not self._interactive_busy):
            return
        while self._pending_commands:
            (
                text,
                on_done,
                source,
                timeout,
                sid,
                display_echo,
                execution_mode,
            ) = self._pending_commands.popleft()
            if sid != self._session_id:
                result = {"status": "error", "message": f"排队期间当前会话已切换: {sid}"}
                if on_done:
                    on_done(result)
                continue
            self._start_execute(
                text,
                on_done,
                source,
                timeout,
                sid,
                display_echo,
                execution_mode,
            )
            return

    def _cancel_pending(self, reason: str) -> int:
        """清空待执行队列，让排队中的命令全部以取消结果返回。返回被取消条数。

        Agent 连续下发的多条命令会排进 ``_pending_commands``。若只中断当前
        命令而不清空队列，排队的下一条会立即自动执行，看起来就像 Ctrl+C 失效。
        """
        count = 0
        while self._pending_commands:
            (
                _text,
                on_done,
                _source,
                _timeout,
                _sid,
                _display_echo,
                _execution_mode,
            ) = self._pending_commands.popleft()
            count += 1
            if on_done:
                on_done({
                    "status": "error",
                    "message": f"命令已取消（{reason}）",
                    "cancelled": True,
                })
        return count

    def cancel_command(self) -> dict:
        """强制停止当前正在执行的命令并清空 Agent 排队队列。

        MCP ``cancel_command`` 工具的 GUI 入口：向活动进程发送 Ctrl+C (\x03)
        中断，同时丢弃尚未执行的排队命令（其回调会收到 cancelled 结果）。
        """
        sid = self._session_id
        active = self._active_command or ""
        queued = len(self._pending_commands)

        if not self._busy and queued == 0:
            return {
                "status": "success",
                "message": "当前没有正在执行的命令或排队命令",
                "active": "",
                "cancelled_queued": 0,
            }

        if self._busy and sid:
            from app.ssh.bridge import SSHBridge
            from app.ssh.manager import SSHManager

            def _done(result: dict) -> None:
                if result.get("status") == "error":
                    self._append_output(
                        f"\n⚠ 中断信号发送失败: {result.get('message')}\n",
                        theme_current().warning,
                    )

            SSHBridge().submit_realtime(SSHManager().terminal_write(sid, "\x03"), _done)

        cancelled = self._cancel_pending("cancel_command")
        msg = "⛔ 已发送中断信号"
        if active:
            msg += f"，正在停止：{active}"
        if cancelled:
            msg += f"，并取消 {cancelled} 条排队命令"
        self._append_output(f"\n{msg}\n", theme_current().warning)

        return {
            "status": "success",
            "message": "已发送中断信号" + (f"，取消 {cancelled} 条排队命令" if cancelled else ""),
            "active": active,
            "cancelled_queued": cancelled,
        }

    def _send_raw_input(self, data: str) -> None:
        if not self._session_id or not self._busy:
            return
        if data == "\x03":
            # Ctrl+C：中断当前命令的同时清空排队中的 Agent 命令，避免队列
            # 又自动执行下一条，看起来像 Ctrl+C 被无视。
            cancelled = self._cancel_pending("Ctrl+C")
            if cancelled:
                self._append_output(
                    f"\n⛔ 已取消 {cancelled} 条排队命令\n",
                    theme_current().warning,
                )
        from app.ssh.bridge import SSHBridge
        from app.ssh.manager import SSHManager

        sid = self._session_id

        def _done(result: dict) -> None:
            if result.get("status") == "error":
                self._append_output(f"\n⚠ 输入失败: {result.get('message')}\n", theme_current().warning)

        SSHBridge().submit_realtime(SSHManager().terminal_write(sid, data), _done)

    def _browse_history(self, direction: int) -> None:
        if not self._history:
            return
        self._history_index = max(0, min(len(self._history), self._history_index + direction))
        text = "" if self._history_index == len(self._history) else self._history[self._history_index]
        self.input.setText(text)
        self.output.replace_input(text)

    def _append_output(self, text: str, color: str | None = None, dynamic: bool = False) -> None:
        if not text:
            return
        if color is None:
            color = theme_current().text
        saved_input = self.output.detach_input_line()
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))

        clean = strip_terminal_control(text).replace("\r\n", "\n")
        for char in clean:
            if dynamic and char == "\r":
                cursor.movePosition(QTextCursor.StartOfBlock)
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                cursor.movePosition(QTextCursor.End)
            elif dynamic and char == "\b":
                cursor.deletePreviousChar()
            else:
                cursor.insertText(char, fmt)

        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()
        self.output.restore_input_line(saved_input)
