"""Windows 特效封装 — DWM 圆角 / Mica 背景 / 无边框窗口边缘缩放。

使用普通窗口 + DWM API（不启用每像素透明窗口，避免点击穿透问题）。
仅在 win32 平台生效；其他平台所有函数静默降级为 no-op。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

# ---- WM_NCHITTEST 常量 ----
WM_NCHITTEST = 0x0084
WM_NCCALCSIZE = 0x0083
WM_GETMINMAXINFO = 0x0024
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
RESIZE_MARGIN = 6

# ---- 窗口样式（SetWindowLongPtr GWL_STYLE） ----
GWL_STYLE = -16
WS_THICKFRAME = 0x00040000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_POPUP = 0x80000000

# ---- SetWindowPos 标志 ----
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

if sys.platform == "win32":
    _dwmapi = ctypes.windll.dwmapi
else:
    _dwmapi = None

# DWMWA 属性
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMSBT_MAINWINDOW = 2  # Mica
DWMSBT_TRANSIENTWINDOW = 3  # Acrylic（需要透明窗口，本实现不用）


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MINMAXINFO(ctypes.Structure):
    """WM_GETMINMAXINFO 结构：用于把最大化窗口限制在可用工作区内。"""

    _fields_ = [
        ("ptReserved", _POINT),
        ("ptMaxSize", _POINT),
        ("ptMaxPosition", _POINT),
        ("ptMinTrackSize", _POINT),
        ("ptMaxTrackSize", _POINT),
    ]


def _setup_dwm():
    if _dwmapi is None:
        return
    _dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    _dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long


_setup_dwm()


def _set_attr(hwnd: int, attr: int, value: int) -> bool:
    if _dwmapi is None or not hwnd:
        return False
    try:
        v = ctypes.c_int(value)
        return _dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0
    except Exception:
        return False


def round_corners(hwnd: int) -> bool:
    """开启 Win11 原生圆角（普通窗口即可，不影响点击）。"""
    return _set_attr(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)


def apply_mica(hwnd: int, dark: bool = True) -> bool:
    """启用 Mica 背景（Win11 22H2+）。普通窗口即可生效，失败静默返回 False。"""
    if _dwmapi is None or not hwnd:
        return False
    ok = _set_attr(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_MAINWINDOW)
    _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
    return ok


def apply_window_effects(hwnd: int, scheme: str = "dark") -> bool:
    """普通窗口方案：Mica 背景 + DWM 圆角 + 沉浸式深色模式。"""
    if not hwnd:
        return False
    applied = apply_mica(hwnd, scheme == "dark")
    round_corners(hwnd)
    return applied


def enable_native_snap(hwnd: int) -> bool:
    """恢复无边框窗口的 Windows 原生吸附/缩放手势。

    无边框窗口默认是 ``WS_POPUP`` 且没有 ``WS_THICKFRAME``，即使
    WM_NCHITTEST 返回 HTCAPTION，Windows 也只允许拖动、不会触发 Aero Snap
    （半屏/四分之一分屏、拖到顶部最大化、最大化后拖下还原）。这里重新加上
    ``WS_THICKFRAME | WS_CAPTION | WS_SYSMENU | WS_MIN/MAXIMIZEBOX`` 并去掉
    WS_POPUP，让窗口管理器把本窗口当作标准可缩放顶层窗口。配合主窗口对
    ``WM_NCCALCSIZE`` 返回 0（隐藏系统绘制边框）与 ``WM_GETMINMAXINFO``
    （最大化不遮任务栏），外观保持无边框同时恢复全部原生手势。
    """
    if _dwmapi is None or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t

        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        style &= ~WS_POPUP
        style |= (
            WS_THICKFRAME
            | WS_CAPTION
            | WS_SYSMENU
            | WS_MINIMIZEBOX
            | WS_MAXIMIZEBOX
        )
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
        flags = (
            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        )
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, flags)
        return True
    except Exception:
        return False
