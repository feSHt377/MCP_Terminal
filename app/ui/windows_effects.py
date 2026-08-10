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
HTCLIENT = 1
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
RESIZE_MARGIN = 6

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
