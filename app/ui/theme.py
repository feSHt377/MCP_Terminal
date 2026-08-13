"""主题系统 — 亮/暗双配色，自动跟随系统外观，界面现代化样式。"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Palette:
    scheme: str
    bg: str
    surface: str
    surface_alt: str
    border: str
    border_hover: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    selection: str
    success: str
    danger: str
    warning: str
    info: str
    scroll_thumb: str
    glass: str
    glass_hi: str


LIGHT = Palette(
    scheme="light",
    bg="#f2f3f6",
    surface="#fafbfc",
    surface_alt="#eceef2",
    border="#d8dde5",
    border_hover="#b7c0cc",
    text="#1a1f26",
    text_muted="#5a6472",
    accent="#0b66d0",
    accent_hover="#2f80e6",
    selection="#a9cdf7",
    success="#187a3a",
    danger="#c92a34",
    warning="#9a6700",
    info="#0b66d0",
    scroll_thumb="#b7c0cc",
    glass="#fafbfc",
    glass_hi="#ffffff",
)

DARK = Palette(
    scheme="dark",
    bg="#050505",
    surface="#0d0d10",
    surface_alt="#17171b",
    border="#26262c",
    border_hover="#3a3a42",
    text="#e9ebef",
    text_muted="#9aa2ad",
    accent="#3b82f6",
    accent_hover="#5b96f7",
    selection="#1e40af",
    success="#22c55e",
    danger="#ef4444",
    warning="#eab308",
    info="#3b82f6",
    scroll_thumb="#33333a",
    glass="#0d0d10",
    glass_hi="#17171b",
)

PALETTES: dict[str, Palette] = {"light": LIGHT, "dark": DARK}

_active = "dark"

MODE_SYSTEM = "system"
MODE_LIGHT = "light"
MODE_DARK = "dark"
MODES = (MODE_SYSTEM, MODE_LIGHT, MODE_DARK)


def current() -> Palette:
    """返回当前激活的配色板。"""
    return PALETTES[_active]


def set_active(scheme: str) -> None:
    """设置当前激活的配色方案。"""
    global _active
    if scheme in PALETTES:
        _active = scheme


def _load_mode() -> str:
    """从 config.yaml 读取持久化的主题模式（app.theme）。"""
    try:
        from app.config.manager import load_config

        cfg = load_config() or {}
        mode = (cfg.get("app") or {}).get("theme", MODE_SYSTEM)
        return mode if mode in MODES else MODE_SYSTEM
    except Exception:
        return MODE_SYSTEM


def _save_mode(mode: str) -> None:
    """将主题模式写入 config.yaml 的 app.theme 字段。"""
    if mode not in MODES:
        return
    try:
        from app.config.manager import load_config, save_config

        cfg = load_config() or {}
        app_cfg = dict(cfg.get("app") or {})
        app_cfg["theme"] = mode
        cfg["app"] = app_cfg
        save_config(cfg)
    except Exception:
        pass


def detect_scheme() -> str:
    """检测操作系统当前外观模式。"""
    hints = QGuiApplication.styleHints()
    try:
        return "dark" if hints.colorScheme() == Qt.ColorScheme.Dark else "light"
    except Exception:
        return "dark"


def _palette_for(p: Palette) -> QPalette:
    qp = QPalette()
    qp.setColor(QPalette.Window, QColor(p.bg))
    qp.setColor(QPalette.WindowText, QColor(p.text))
    qp.setColor(QPalette.Base, QColor(p.bg))
    qp.setColor(QPalette.AlternateBase, QColor(p.surface_alt))
    qp.setColor(QPalette.Text, QColor(p.text))
    qp.setColor(QPalette.Button, QColor(p.surface_alt))
    qp.setColor(QPalette.ButtonText, QColor(p.text))
    qp.setColor(QPalette.Highlight, QColor(p.accent))
    qp.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    qp.setColor(QPalette.ToolTipBase, QColor(p.surface))
    qp.setColor(QPalette.ToolTipText, QColor(p.text))
    qp.setColor(QPalette.PlaceholderText, QColor(p.text_muted))
    qp.setColor(QPalette.Disabled, QPalette.Text, QColor(p.text_muted))
    qp.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p.text_muted))
    return qp


_QSS = Template(
    """
QMainWindow {
    background: $bg;
}

#titleBar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 $glass_hi, stop:0.45 $glass, stop:1 $glass);
    border-bottom: 1px solid $border;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
#titleAppLabel {
    color: $text;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
#titleMenuBar {
    background: transparent;
    color: $text;
    border: none;
    padding-left: 8px;
}
#titleMenuBar::item {
    background: transparent;
    padding: 6px 12px;
    border-radius: 6px;
}
#titleMenuBar::item:selected, #titleMenuBar::item:pressed {
    background: $surface_alt;
}
#minBtn, #maxBtn {
    color: $text_muted;
    background: transparent;
    border: none;
    border-radius: 6px;
    font-size: 14px;
}
#minBtn:hover, #maxBtn:hover {
    background: $surface_alt;
    color: $text;
}
#closeBtn {
    color: $text_muted;
    background: transparent;
    border: none;
    border-radius: 6px;
    font-size: 13px;
}
#closeBtn:hover {
    background: #e81123;
    color: #ffffff;
}

QMainWindow::separator {
    background: $border;
    width: 2px;
}

QMenuBar {
    background: transparent;
    color: $text;
    font-size: 12px;
}
QMenuBar::item {
    background: transparent;
    padding: 6px 12px;
    border-radius: 6px;
}
QMenuBar::item:selected, QMenuBar::item:pressed {
    background: $surface_alt;
}
QMenu {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px;
    font-size: 12px;
}
QMenu::item {
    padding: 6px 28px 6px 18px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: $accent;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: $border;
    margin: 5px 10px;
}

QToolTip {
    color: $text;
    background: $surface;
    border: 1px solid $border;
    padding: 5px 8px;
    font-size: 11px;
}

QStatusBar {
    background: $glass;
    color: $text_muted;
    border-top: 1px solid $border;
    font-size: 11px;
}
QStatusBar::item { border: none; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:vertical { background: $scroll_thumb; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:horizontal { background: $scroll_thumb; border-radius: 5px; min-width: 28px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: $border_hover; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QDockWidget {
    color: $text;
    font-size: 12px;
    font-weight: 600;
    border: 1px solid $border;
    border-radius: 10px;
    margin: 5px;
    background: $glass;
}
QDockWidget::title {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 $glass_hi, stop:0.4 $glass, stop:1 $glass);
    border-bottom: 1px solid $border;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    padding: 7px 12px;
}
QDockWidget::close-button, QDockWidget::float-button {
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px;
}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {
    background: $surface_alt;
}

QToolBar#mainToolbar {
    background: $glass;
    border: none;
    border-bottom: 1px solid $border;
    spacing: 6px;
    padding: 6px 10px;
}
QToolButton {
    color: $text;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
}
QToolButton:hover { background: $surface_alt; border-color: $border; }
QToolButton:pressed { background: $border_hover; }
QToolButton:checked { background: $accent; color: #ffffff; }

#serverPanel {
    background: transparent;
}
#statusPanel {
    background: transparent;
}

QListWidget#serverList {
    background: $glass;
    color: $text;
    border: 1px solid $border;
    border-radius: 10px;
    font-size: 12px;
    outline: none;
    padding: 6px;
}
QListWidget#serverList::item {
    padding: 9px;
    margin: 2px 0;
    border-radius: 8px;
}
QListWidget#serverList::item:hover:!selected { background: $surface_alt; }
QListWidget#serverList::item:selected {
    background: $selection;
    color: $text;
}

QPushButton#connectBtn {
    background: $success;
    color: #ffffff;
    border: none;
    padding: 8px 12px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 12px;
}
QPushButton#connectBtn:hover { background: $accent_hover; }
QPushButton#disconnectBtn {
    background: transparent;
    color: $danger;
    border: 1px solid $border;
    padding: 8px 12px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 12px;
}
QPushButton#disconnectBtn:hover {
    background: $danger;
    color: #ffffff;
    border-color: $danger;
}
QPushButton#connectBtn:disabled, QPushButton#disconnectBtn:disabled {
    background: $surface_alt;
    color: $text_muted;
    border-color: $border;
}

QLabel#statusLabel {
    color: $text_muted;
    font-size: 11px;
    padding: 4px 2px;
}
QLabel#statusLabel[state="connected"] { color: $success; }
QLabel#statusLabel[state="error"] { color: $danger; }

QLabel#statsLabel {
    color: $text_muted;
    font-size: 11px;
    padding: 4px 2px;
}

QPlainTextEdit#terminalOutput {
    background: $glass;
    color: $text;
    selection-background-color: $selection;
    border: 1px solid $border;
    border-radius: 10px 10px 0 0;
    padding: 10px;
    font-family: 'Cascadia Mono';
}

QTabWidget#terminalTabs::pane {
    background: $glass;
    border: 1px solid $border;
    border-radius: 10px;
    top: -1px;
}
QTabWidget#terminalTabs QTabBar::tab {
    background: transparent;
    color: $text_muted;
    padding: 6px 16px;
    margin: 2px 2px 0 2px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-size: 12px;
}
QTabWidget#terminalTabs QTabBar::tab:selected {
    background: $glass;
    color: $text;
    border-color: $border;
    border-bottom-color: $glass;
}
QTabWidget#terminalTabs QTabBar::tab:hover:!selected {
    background: $surface_alt;
}
QTabWidget#terminalTabs QTabBar::close-button {
    image: url("$close_icon");
    margin: 4px;
    border-radius: 4px;
}
QTabWidget#terminalTabs QTabBar::close-button:hover {
    background: $surface_alt;
}
QFrame#terminalInputFrame {
    background: $glass;
    border: 1px solid $border;
    border-top: none;
    border-radius: 0 0 10px 10px;
}
QLineEdit#promptLabel {
    color: $success;
    background: transparent;
    border: none;
    font-family: 'Cascadia Mono';
    font-weight: 600;
}
QLineEdit#terminalInput {
    color: $text;
    background: transparent;
    border: none;
    padding: 3px;
    font-family: 'Cascadia Mono', 'Consolas', monospace;
    font-size: 12px;
}
QLineEdit#terminalInput:disabled { color: $text_muted; }
QProgressBar#activity {
    border: none;
    background: $surface_alt;
    border-radius: 2px;
    max-height: 4px;
}
QProgressBar#activity::chunk { background: $accent; border-radius: 2px; }

QPlainTextEdit#logView {
    background: $glass;
    color: $text;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 8px;
    font-family: 'Consolas', monospace;
    font-size: 11px;
}

QDialog#chatDialog { background: $glass; }
QDialog#settingsDialog { background: $glass; }
QLabel#settingsTitle { color: $text; font-weight: 700; font-size: 12px; }
QLabel#settingsHint { color: $text_muted; font-size: 11px; }
QCheckBox { color: $text; font-size: 12px; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid $border; background: $surface; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QCheckBox::indicator:hover { border-color: $accent; }
QFrame#chatHeader { background: $glass; border-bottom: 1px solid $border; }
QLabel#chatTitle { color: $text; font-weight: 700; font-size: 12px; }
QLabel#chatMode { color: $text_muted; font-size: 11px; }
QTextEdit#chatView {
    background: $glass;
    color: $text;
    border: none;
    padding: 10px;
    font-family: 'Consolas', monospace;
    font-size: 12px;
}
QFrame#chatInputBar { background: $surface; border-top: 1px solid $border; }
QLineEdit#chatInput {
    background: $surface_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 12px;
}
QLineEdit#chatInput:focus { border-color: $accent; }
QPushButton#chatSend {
    background: $accent;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 7px 12px;
    font-weight: 600;
}
QPushButton#chatSend:hover { background: $accent_hover; }
QPushButton#chatProxy {
    background: $success;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 7px 12px;
    font-weight: 600;
}
QPushButton#chatProxy:hover { background: $accent_hover; }
QPushButton#chatAutocomplete {
    background: $warning;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 7px 12px;
    font-weight: 600;
}
QPushButton#chatAutocomplete:hover { background: $accent_hover; }
QPushButton#chatSend:disabled, QPushButton#chatProxy:disabled, QPushButton#chatAutocomplete:disabled {
    background: $surface_alt;
    color: $text_muted;
}
"""
)


def build_qss(palette: Palette) -> str:
    """基于配色板生成全局 QSS 样式表。"""
    return _QSS.safe_substitute(vars(palette), close_icon=_close_icon_url(palette))


_CLOSE_ICON_CACHE: dict[str, str] = {}


def _close_icon_url(palette: Palette) -> str:
    """生成（并缓存）一个 X 形关闭图标的 SVG 文件，返回可供 QSS ``url()`` 引用的路径。

    根因：QSS 一旦给 ``QTabBar::close-button`` 设置 background / border-radius 等
    绘制属性，Qt 就不再绘制默认的关闭 X 图标，必须显式提供 ``image``，否则标签页
    关闭按钮只剩一个可点击的空白区域。这里用主题色动态生成 SVG，兼顾图标可见与
    亮 / 暗主题自适应。
    """
    scheme = palette.scheme
    path = _CLOSE_ICON_CACHE.get(scheme)
    if path is not None and os.path.exists(path):
        return path
    color = palette.text_muted
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
        f'<path d="M4.5 4.5 L11.5 11.5 M11.5 4.5 L4.5 11.5" stroke="{color}" '
        'stroke-width="1.5" stroke-linecap="round" fill="none"/>'
        "</svg>"
    )
    directory = os.path.join(tempfile.gettempdir(), "mcpterminal")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"close-{scheme}.svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    _CLOSE_ICON_CACHE[scheme] = path
    return path.replace("\\", "/")


class ThemeManager(QObject):
    """应用级主题管理器：亮色 / 暗色 / 跟随系统三种模式，可持久化。"""

    theme_changed = Signal(str)

    def __init__(self, app: QApplication, parent=None):
        super().__init__(parent)
        self._app = app
        self._mode = _load_mode()
        app.styleHints().colorSchemeChanged.connect(self._on_scheme_changed)

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        """切换主题模式（light / dark / system）并持久化。"""
        if mode not in MODES or mode == self._mode:
            return
        self._mode = mode
        _save_mode(mode)
        self.apply()

    def _on_scheme_changed(self, *args) -> None:
        if self._mode == MODE_SYSTEM:
            self.apply()

    def apply(self) -> None:
        if self._mode == MODE_SYSTEM:
            scheme = detect_scheme()
        else:
            scheme = self._mode
        set_active(scheme)
        palette = PALETTES[scheme]
        self._app.setStyle("Fusion")
        self._app.setPalette(_palette_for(palette))
        self._app.setStyleSheet(build_qss(palette))
        # 强制全部窗口重新应用样式，避免主题切换后残留旧配色
        for widget in QApplication.topLevelWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        self.theme_changed.emit(scheme)
