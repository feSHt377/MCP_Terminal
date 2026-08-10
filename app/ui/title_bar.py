"""自绘标题栏 — 无边框窗口的标题区域，含菜单栏、应用名与窗口控制按钮。"""  # noqa: D205

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QSizePolicy,
    QToolButton,
    QWidget,
)


class TitleBar(QWidget):
    """无边框窗口的标题栏。

    - 左侧：应用名 + 菜单栏
    - 右侧：最小化 / 最大化 / 关闭 三个窗口控制按钮
    - 空白区域按住可拖动窗口，双击最大化/还原
    """

    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        # 让 QSS 的 background 真正生效（普通 QWidget 默认不绘制样式背景）
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(6)

        # ---- 应用名 ----
        self.app_label = QLabel("MCP Terminal")
        self.app_label.setObjectName("titleAppLabel")
        layout.addWidget(self.app_label)

        # ---- 菜单栏 ----
        self.menu_bar = QMenuBar(self)
        self.menu_bar.setObjectName("titleMenuBar")
        self.menu_bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        layout.addWidget(self.menu_bar)

        # 拖动手柄（空白区域）
        layout.addStretch(1)

        # ---- 窗口控制按钮 ----
        self.min_btn = self._make_btn("minBtn", "─", "最小化")
        self.max_btn = self._make_btn("maxBtn", "□", "最大化")
        self.close_btn = self._make_btn("closeBtn", "✕", "关闭")

        self.min_btn.clicked.connect(self.minimize_clicked)
        self.max_btn.clicked.connect(self.maximize_clicked)
        self.close_btn.clicked.connect(self.close_clicked)

        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

    def _make_btn(self, object_name: str, text: str, tooltip: str) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName(object_name)
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setFixedSize(46, 40)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def set_maximize_state(self, maximized: bool):
        """根据窗口状态更新最大化按钮图标。"""
        self.max_btn.setText("❐" if maximized else "□")
        self.max_btn.setToolTip("还原" if maximized else "最大化")

    def set_app_name(self, name: str):
        self.app_label.setText(name)

    # ------------------------------------------------------------------
    # 拖动 / 双击
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._dragging = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_dragging", False):
            window = self.window()
            if window is None:
                return
            delta = event.globalPosition().toPoint() - self._drag_start
            window.move(window.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.maximize_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
