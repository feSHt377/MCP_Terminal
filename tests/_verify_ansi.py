"""临时验证：ANSI 颜色序列是否被解析为正确的 QTextCharFormat 前景色。"""
from PySide6.QtGui import QTextCharFormat, QColor

from app.ui.terminal_widget import _iter_ansi_segments

BASE = "#c5c8c6"
base = QTextCharFormat()
base.setForeground(QColor(BASE))


def color_of(text: str) -> str:
    for _chunk, f in _iter_ansi_segments(text, base):
        return f.foreground().color().name().lower()
    return ""


def formats(text: str):
    return [(c, f.foreground().color().name().lower()) for c, f in _iter_ansi_segments(text, base)]


# 1. 普通文本：默认前景色
assert color_of("hello world") == BASE, color_of("hello world")

# 2. systemctl 红色错误行 \x1b[1;31m（粗体红 31）
items = formats("\x1b[1;31mfailed\x1b[0m")
assert items[0][0] == "failed", items[0][0]
f = items[0][1]
assert f == "#c23621", f  # 标准 31 红

# 3. 绿色 active \x1b[0;1;32m（reset+bold+green 32）
items = formats("\x1b[0;1;32mactive\x1b[0m")
assert items[0][1] == "#25bc24", items[0][1]

# 4. reset 后恢复 base 色
items = formats("\x1b[31mred\x1b[0m then normal")
assert items[0][0] == "red" and items[0][1] == "#c23621"
assert items[1][0] == " then normal" and items[1][1] == BASE

# 5. 256 色 \x1b[38;5;208m（orange #ff8700）
items = formats("\x1b[38;5;208mhi\x1b[0m")
assert items[0][1] == "#ff8700", items[0][1]

# 6. 非 SGR 控制序列（清屏/光标）被忽略
assert "".join(c for c, _ in formats("ab\x1b[2J\x1b[1;1Hcd")) == "abcd"

# 7. OSC 标题被忽略
assert "".join(c for c, _ in formats("x\x1b]0;title\x07y")) == "xy"

# 8. NUL 被忽略
assert "".join(c for c, _ in formats("a\x00b")) == "ab"

# 9. 多段 SGR：黄字蓝底 \x1b[33;44m
items = formats("\x1b[33;44mz\x1b[0m")
assert items[0][1] == "#d3b113", items[0][1]

print("ALL_ANSI_PARSE_OK")
