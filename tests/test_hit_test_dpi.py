"""无边框窗口命中测试（WM_NCHITTEST）在多屏/不同分辨率下的正确性验证。

复现问题：窗口从主屏移到副屏后，窗口内部区域被 _hit_test 误判为缩放边缘
（HTLEFT/HTRIGHT/...），Windows 因此不把点击投递给控件、也不再返回
HTCAPTION 让标题栏可拖动 —— 表现为「点不动组件、拖不动窗口」。

本脚本直接调用真实的 ``MainWindow._hit_test``（用一个最小的无边框窗口承载），
在每块屏幕上用真实物理像素坐标探测，断言：
  * 窗口正中   → None（交给 Qt 当普通客户区，点击可达控件）
  * 左边框内 2px → HTLEFT（缩放仍然有效）
  * 标题栏空白  → HTCAPTION（窗口可拖动）
"""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMainWindow

from app.ui.main_window import MainWindow
from app.ui.title_bar import TitleBar
from app.ui.windows_effects import (
    HTCAPTION,
    HTLEFT,
    HTRIGHT,
    enable_native_snap,
)

user32 = ctypes.windll.user32

HT_NAMES = {
    1: "HTCLIENT", 2: "HTCAPTION", 10: "HTLEFT", 11: "HTRIGHT",
    12: "HTTOP", 13: "HTTOPLEFT", 14: "HTTOPRIGHT", 15: "HTBOTTOM",
    16: "HTBOTTOMLEFT", 17: "HTBOTTOMRIGHT",
}


class ProbeWindow(QMainWindow):
    """最小无边框窗口，复用真实的 MainWindow._hit_test。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self._title_bar = TitleBar(self)
        self.setMenuWidget(self._title_bar)

    _hit_test = MainWindow._hit_test


def client_physical_rect(hwnd):
    """返回 (物理客户区原点x, 原点y, 宽, 高)。"""
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(pt))
    rc = wintypes.RECT()
    user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rc))
    return pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top


def probe_on_screen(app, probe, screen, label):
    """把窗口放到指定屏幕，用物理坐标探测命中测试结果。"""
    area = screen.geometry()
    w = min(1000, area.width() - 80)
    h = min(600, area.height() - 80)
    probe.setGeometry(area.x() + 40, area.y() + 40, w, h)
    probe.show()
    probe.raise_()

    # 等 Qt 处理跨屏 DPI 变化并按新屏幕重算几何
    for _ in range(40):
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()

    hwnd = int(probe.winId())
    ox, oy, pw, ph = client_physical_rect(hwnd)
    lw, lh = probe.width(), probe.height()
    sx, sy = lw / pw, lh / ph          # 逻辑→物理 比例
    dpr = probe.devicePixelRatio()

    def phys(lx, ly):
        return ox + round(lx * pw / lw), oy + round(ly * ph / lh)

    cases = []

    # 1. 正中：必须是客户区（None 表示交给 Qt，点击可到达控件）
    cx, cy = phys(lw // 2, lh // 2)
    cases.append(("窗口正中 → 客户区", probe._hit_test(cx, cy), None))

    # 2. 左边框内 2 逻辑像素：必须识别为 HTLEFT
    ex, ey = phys(2, lh // 2)
    cases.append(("左边框 2px → 缩放", probe._hit_test(ex, ey), HTLEFT))

    # 3. 右边框内 2 逻辑像素：必须识别为 HTRIGHT
    rx, ry = phys(lw - 3, lh // 2)
    cases.append(("右边框 2px → 缩放", probe._hit_test(rx, ry), HTRIGHT))

    # 4. 标题栏空白处：必须 HTCAPTION（可拖动）
    tx, ty = phys(lw // 2, probe._title_bar.height() // 2)
    cases.append(("标题栏空白 → 可拖动", probe._hit_test(tx, ty), HTCAPTION))

    print(f"\n{'=' * 72}")
    print(f"{label}: {screen.name()}  dpr={dpr}")
    print(f"  Qt 逻辑: origin=({area.x()},{area.y()}) size={lw}x{lh}")
    print(f"  物理客户区: origin=({ox},{oy}) size={pw}x{ph}  (比例 {sx:.4f}, {sy:.4f})")
    print("-" * 72)

    ok = True
    for name, got, want in cases:
        good = got == want
        ok = ok and good
        mark = "OK  " if good else "FAIL"
        print(
            f"  {mark} {name}: 得到 {HT_NAMES.get(got, got)!r} "
            f"期望 {HT_NAMES.get(want, want)!r}"
        )
    return ok


def main():
    app = QApplication(sys.argv)
    probe = ProbeWindow()
    # 与真实窗口一致的窗口样式（无边框 + WS_THICKFRAME，恢复原生缩放手势）
    enable_native_snap(int(probe.winId()))

    all_ok = True
    for i, screen in enumerate(QGuiApplication.screens()):
        label = "主屏" if screen is QGuiApplication.primaryScreen() else f"副屏 #{i}"
        all_ok = probe_on_screen(app, probe, screen, label) and all_ok

    probe.close()
    app.processEvents()

    print()
    print("=" * 72)
    print("结果:", "全部通过 ✅" if all_ok else "存在失败 ❌（命中测试在不同屏幕上不正确）")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
