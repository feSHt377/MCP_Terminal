"""诊断：Qt 逻辑坐标 与 Win32 物理像素坐标的差异（多屏高 DPI 命中测试问题）。

用途：排查「窗口移到另一块不同分辨率的屏幕后，控件点击区域错乱、窗口拖不动」。
打印每块屏幕的物理监视器矩形与 Qt 逻辑几何，并算出旧的换算方式
（``mapFromGlobal(QPoint(物理x / dpr, 物理y / dpr))``）在每块屏上的**固定偏移**。

偏移公式推导（dpr = 屏幕缩放）：
    真实逻辑全局坐标 = 逻辑原点 + (物理点 - 物理原点) / dpr
    旧算法得到的坐标 = 物理点 / dpr
    => 误差 = 逻辑原点 - 物理原点 / dpr
在物理原点非 (0,0) 的屏幕上该误差不为零，于是命中测试整体错位。
"""
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def physical_monitors():
    """枚举物理监视器矩形（物理像素，原点在虚拟桌面左上角）。"""
    monitors = []
    proc = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(RECT),
        ctypes.c_double,
    )

    def _cb(_hmon, _hdc, lprect, _data):
        r = lprect.contents
        monitors.append((r.left, r.top, r.right, r.bottom))
        return 1

    user32.EnumDisplayMonitors(None, None, proc(_cb), 0)
    return monitors


def main():
    app = QApplication(sys.argv)  # noqa: F841 - 需要 QGuiApplication 才能读屏幕信息

    physical = physical_monitors()
    print("=" * 74)
    print("物理监视器（Win32 EnumDisplayMonitors，物理像素）")
    for i, (l, t, r, b) in enumerate(physical):
        print(f"  #{i}: origin=({l},{t}) size={r - l}x{b - t}")

    print()
    print("Qt 屏幕（逻辑/设备无关像素）与旧算法的固定偏移")
    print("-" * 74)

    screens = QGuiApplication.screens()
    worst = 0.0
    for s in screens:
        g = s.geometry()
        dpr = float(s.devicePixelRatio())
        # 与该 Qt 屏幕尺寸匹配的物理监视器
        match = None
        for (l, t, r, b) in physical:
            if abs((r - l) / dpr - g.width()) < 2 and abs((b - t) / dpr - g.height()) < 2:
                match = (l, t)
                break
        if match is None:
            match = (round(g.x() * dpr), round(g.y() * dpr))
        px0, py0 = match

        err_x = g.x() - px0 / dpr
        err_y = g.y() - py0 / dpr
        worst = max(worst, abs(err_x), abs(err_y))

        print(f"  {s.name()}")
        print(f"    Qt 逻辑原点=({g.x()},{g.y()}) size={g.width()}x{g.height()} dpr={dpr}")
        print(f"    物理原点=({px0},{py0})")
        print(
            f"    旧算法『物理坐标 / dpr』的偏移 = ({err_x:+.1f}, {err_y:+.1f}) 逻辑像素"
            f"  {'← 命中测试整体错位' if abs(err_x) > 0.5 or abs(err_y) > 0.5 else '← 无偏移'}"
        )

    print("-" * 74)
    print(f"最大偏移: {worst:.1f} 逻辑像素")
    if worst > 0.5:
        print("结论：存在非零偏移，WM_NCHITTEST 必须用 ScreenToClient + 客户区比例换算")
        print("      （见 app/ui/windows_effects.py: screen_to_client_logical）")
    else:
        print("结论：当前显示器布局下旧算法恰好无偏移（单屏或副屏物理原点为 0,0）")


if __name__ == "__main__":
    main()
