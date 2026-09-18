"""会话焦点绑定回归测试。

覆盖:
- 首个 SSH 会话打开标签页后，MainWindow._session_id 必须被正确设置
  （回归：曾因 addTab 同步触发 currentChanged 时映射尚未登记而为 None，
   导致 proxy_command 报「GUI 当前没有 SSH 会话」）
- 多会话切换后 _session_id 跟随当前标签页
- 复用已存在的标签页时 _session_id 仍被同步
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

# 测试在无显示环境下运行
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _StubPanel:
    """替代 server_panel，避免测试依赖真实 UI 控件。"""

    def __init__(self):
        self.calls = []

    def set_connected(self, sid, label):
        self.calls.append(("set_connected", sid, label))

    def set_disconnected(self):
        self.calls.append(("set_disconnected",))


def _make_window():
    """构造 MainWindow，但不启动 SSH 事件循环与 IPC 服务。

    GUI 进程是 .runtime/gui.json 的唯一持有者；测试若真的启动 IPC，
    会覆盖正在运行的 GUI 的状态文件，因此这里替换为无副作用的桩。
    """
    from PySide6.QtWidgets import QApplication, QTabWidget

    from app.ui.main_window import MainWindow

    # QWidget 必须在 QApplication 之后构造
    app = QApplication.instance() or QApplication([])

    with patch.object(MainWindow, "__init__", lambda self: None):
        window = MainWindow()
    # 手动搭建 _open_session_tab / _on_tab_changed 所需的最小状态
    window._tabs = QTabWidget()
    window._tab_widgets = {}
    window._session_id = None
    window.server_panel = _StubPanel()
    window._chat_window = None
    window._tabs.currentChanged.connect(window._on_tab_changed)
    window._app = app  # 防止被 GC
    return window


def test_first_session_sets_current():
    print("\n" + "=" * 60)
    print("Test 1: 首个会话应成为当前会话")
    print("=" * 60)
    window = _make_window()
    sid = "root@10.0.0.1:22"

    window._open_session_tab(sid, "root", "srv1")

    assert window._session_id == sid, (
        f"首个会话未绑定为当前会话: 期望 {sid!r}，实际 {window._session_id!r}"
    )
    print(f"  ✅ 首个会话绑定成功: {window._session_id}")


def test_second_session_switches_current():
    print("\n" + "=" * 60)
    print("Test 2: 第二个会话应接管当前会话")
    print("=" * 60)
    window = _make_window()
    sid1 = "root@10.0.0.1:22"
    sid2 = "root@10.0.0.2:22"

    window._open_session_tab(sid1, "root", "srv1")
    window._open_session_tab(sid2, "root", "srv2")

    assert window._session_id == sid2, (
        f"切换后当前会话错误: 期望 {sid2!r}，实际 {window._session_id!r}"
    )
    print(f"  ✅ 当前会话已切换: {window._session_id}")


def test_reopen_existing_tab_resyncs():
    print("\n" + "=" * 60)
    print("Test 3: 复用已有标签页应重新对准当前会话")
    print("=" * 60)
    window = _make_window()
    sid1 = "root@10.0.0.1:22"
    sid2 = "root@10.0.0.2:22"

    window._open_session_tab(sid1, "root", "srv1")
    window._open_session_tab(sid2, "root", "srv2")
    # 再次打开 sid1（已存在标签页，不触发 currentChanged 的 addTab 路径）
    window._open_session_tab(sid1, "root", "srv1")

    assert window._session_id == sid1, (
        f"复用标签页后未同步当前会话: 期望 {sid1!r}，实际 {window._session_id!r}"
    )
    print(f"  ✅ 复用标签页后当前会话: {window._session_id}")


def test_background_tab_does_not_steal_focus():
    print("\n" + "=" * 60)
    print("Test 4: 后台打开标签页不应抢占当前会话")
    print("=" * 60)
    window = _make_window()
    sid1 = "root@10.0.0.1:22"
    sid2 = "root@10.0.0.2:22"

    window._open_session_tab(sid1, "root", "srv1")
    window._open_session_tab(sid2, "root", "srv2", switch=False)

    assert window._session_id == sid1, (
        f"后台标签页不应改变当前会话: 期望 {sid1!r}，实际 {window._session_id!r}"
    )
    print(f"  ✅ 当前会话保持不变: {window._session_id}")


if __name__ == "__main__":
    test_first_session_sets_current()
    test_second_session_switches_current()
    test_reopen_existing_tab_resyncs()
    test_background_tab_does_not_steal_focus()
    print("\n" + "=" * 60)
    print("✅ 会话焦点绑定全部测试通过")
    print("=" * 60)
