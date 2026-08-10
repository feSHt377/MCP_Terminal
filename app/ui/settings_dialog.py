"""设置面板 — 修改 GUI 行为选项并持久化到 config.yaml。"""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from app.config.manager import (
    get_auto_switch_tab,
    get_check_updates,
    set_auto_switch_tab,
    set_check_updates,
)


class SettingsDialog(QDialog):
    """GUI 设置对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(440, 200)
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("界面设置")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)

        self.auto_switch = QCheckBox("接受 Agent 自动切换标签页")
        self.auto_switch.setToolTip(
            "开启后，Agent 可通过 switch_tab 工具自动把 GUI 切换到正在执行命令的"
            "会话标签页；关闭后 Agent 无法擅自切换，只能由你手动点击标签页。"
        )
        layout.addWidget(self.auto_switch)

        self.check_updates = QCheckBox("启动时自动检查更新")
        self.check_updates.setToolTip(
            "启动 GUI 时在后台检查 GitHub 仓库是否有新版本，发现时弹出提示。"
        )
        layout.addWidget(self.check_updates)

        hint = QLabel(
            "该设置保存到 config.yaml 的 app.auto_switch_tab（默认开启）。\n"
            "修改后立即生效，Agent 下次调用 switch_tab 时按新设置执行。"
        )
        hint.setObjectName("settingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self):
        self.auto_switch.setChecked(get_auto_switch_tab())
        self.check_updates.setChecked(get_check_updates())

    def accept(self):
        set_auto_switch_tab(self.auto_switch.isChecked())
        set_check_updates(self.check_updates.isChecked())
        super().accept()
